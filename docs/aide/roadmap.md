# Roadmap de Desarrollo — ODIN

> **Paso 2 del flujo AI-Driven Engineering (AIDE).** Derivado de `docs/aide/vision.md`. Cada etapa produce una versión demostrable y testeable, dimensionada para ~1 semana de trabajo. Las etapas son acumulativas: cada una se construye sobre la anterior.

**Leyenda de referencias:** F# = funcionalidad de la visión, G# = objetivo, C# = criterio de éxito.

**Riesgo transversal (verificar en Etapa 1):** Python ≥ 3.14 es muy reciente; confirmar disponibilidad de wheels/soporte de `paramiko`, `py7zr`, `APScheduler` y `pywin32` para 3.14. Si alguna librería no soporta 3.14, decidir pin de versión o ajuste de `requires-python` antes de avanzar.

---

## Etapa 1 — Fundaciones: paquete, CLI, configuración JSON y validación

**Descripción:** crear el esqueleto del proyecto instalable con `uv`, el contrato de configuración JSON (esquema OS-agnóstico de la visión §5), su carga/validación y la CLI básica. Al finalizar, `odin validate` funciona sobre los dos ejemplos de configuración de la visión.

**Cubre:** F3, F6 (parcial), G5 (parcial), C5 (parcial), C6 (base).

### Entregables
- Estructura de paquete con layout `src/`: `src/odin/{__init__.py, cli.py, config.py, log.py, paths.py}`, `tests/`, `README.md` inicial.
- `pyproject.toml` actualizado: descripción del proyecto, dependencias (`paramiko`, `py7zr`, `apscheduler`, `pywin32; sys_platform == "win32"`), `[project.scripts] odin = "odin.cli:main"`, configuración de pytest.
- Módulo `config.py`: modelos de datos (dataclasses) para `databases`, `compression`, `servers`, `notification`, `local`, `scheduler`; parseo del JSON con errores claros (campo, motivo, ubicación).
- Módulo `paths.py`: normalización OS-agnóstica — `pathlib`, aceptación de `/` y `\`, expansión de `~`, resolución de rutas relativas respecto del archivo JSON.
- Módulo `log.py`: logging a consola + archivo con rotación, nivel configurable, utilidad de enmascarado de secretos.
- CLI con argparse: `odin validate --config <ruta>` (también variable de entorno `ODIN_CONFIG`), exit codes: 0 válido, 2 error de configuración, 1 error interno.
- Archivos de ejemplo: `examples/config.linux.json` y `examples/config.windows.json` (tomados de la visión).
- CI básico o script local: `uv run pytest` + `uv sync` funcionando en Linux y Windows.

**Dependencias:** ninguna.

### Criterios de validación
- `uv sync && uv run odin validate --config examples/config.linux.json` → exit code 0.
- Un JSON con campos inválidos (tipo, rango, ruta inexistente de clave privada) produce mensajes específicos por campo.
- Tests unitarios de parseo, normalización de rutas (inputs `/`, `\`, `~`, relativos) y enmascarado de secretos.
- Verificación temprana de compatibilidad de dependencias con Python 3.14 (documentar resultado).

---

## Etapa 2 — Respaldo Firebird con gbak

**Descripción:** implementar la generación del `.fbk` invocando `gbak` como subproceso, con auto-detección del binario por plataforma y versión. Al finalizar, `odin run` genera respaldos reales de una base Firebird local.

**Cubre:** F1, G1 (parcial).

### Entregables
- Módulo `src/odin/backup.py`:
  - Auto-detección de `gbak`: rutas típicas por SO (Windows: `C:\Program Files\Firebird\*\bin`; Linux: `/usr/bin`, `/opt/firebird/bin`), override por `gbak_path` en la config.
  - Ejecución de `gbak -b` vía `subprocess` con timeout configurable, captura de stdout/stderr, detección de fallo por exit code y por patrones de error en la salida.
  - Validación post-respaldo: archivo existe y no está vacío.
  - Soporte de múltiples bases en una ejecución; nombres de salida `<nombre_bd>_<timestamp>.fbk` en `local.work_dir` (creado si no existe).
  - Opciones esenciales exponibles: charset, rol, usuario/contraseña (pasados de forma segura por línea de comandos según soporte de gbak).
- Integración en la CLI: `odin run --config <ruta>` ejecuta solo la fase de respaldo (las fases posteriores aún no existen) y termina con exit code apropiado.
- Modelo de resultado de ejecución (`BackupResult`: estado, archivo generado, tamaño, duración, error) reutilizable por etapas posteriores.

**Dependencias:** Etapa 1.

### Criterios de validación
- Sobre un Firebird de prueba (instalación local o contenedor), `odin run` produce un `.fbk` íntegro: verificación con `gbak -v` de metadata o restauración a base scratch.
- `gbak_path` inválido, base inaccesible y timeout generan errores claros y exit code ≠ 0.
- Tests: mocking de `subprocess` para parseo de salida/errores de gbak; test de integración marcado (`@pytest.mark.integration`) que requiere Firebird real.

---

## Etapa 3 — Compresión 7z

**Descripción:** comprimir cada `.fbk` con 7z usando `py7zr`, con nivel configurable. Al finalizar, `odin run` produce `.fbk` + `.fbk.7z` verificados.

**Cubre:** F2, G2.

### Entregables
- Módulo `src/odin/compress.py`: compresión `.fbk → .fbk.7z` con `py7zr`, nivel de `compression.level` (1–9), manejo de archivo destino existente (sobreescritura controlada por timestamp), reporte de tamaño original/comprimido y duración.
- Opcional no bloqueante: cifrado AES-256 con `compression.password` (si `py7zr` lo soporta de forma estable en la versión elegida; documentar decisión).
- Extensión de `BackupResult` con datos de compresión.
- Pipeline incremental en `odin run`: respaldo → compresión, por cada base.

**Dependencias:** Etapa 2.

### Criterios de validación
- Test de ida y vuelta: comprimir archivo de prueba, descomprimir con `py7zr`, comparación byte a byte.
- Nivel de compresión configurable tiene efecto medible sobre el tamaño de salida.
- Fallo de compresión (disco lleno simulado, archivo corrupto) produce error claro y no deja `.7z` parciales huérfanos.
- Demostración: `odin run` sobre la base de prueba genera ambos archivos con tamaños informados.

---

## Etapa 4 — Transferencia SFTP con paramiko

**Descripción:** enviar el `.fbk.7z` a cada servidor destino con paramiko, con ambos métodos de autenticación, verificación y reintentos. Al finalizar, `odin run` deposita las copias en servidores SFTP reales o de prueba.

**Cubre:** F4, G3.

### Entregables
- Módulo `src/odin/transfer.py`:
  - Conexión paramiko por servidor: autenticación `password` y `key` (clave privada con passphrase opcional; soporte `~` en la ruta de la clave).
  - Política de host keys configurable por servidor (`strict` / `known_hosts` / `accept-new` / `insecure`, con `strict` por defecto).
  - Creación recursiva de directorios remotos si no existen.
  - Upload con verificación post-transferencia (`stat` remoto vs. tamaño local).
  - Reintentos configurables (intentos, backoff) ante errores transitorios de red; timeouts de conexión/operación.
  - Aislamiento de fallos: un servidor fallido no interrumpe al resto; resultado por servidor (`TransferResult`).
- Extensión del pipeline: respaldo → compresión → transferencia a todos los servidores, por cada base.
- Tests con dobles: mock de `paramiko.SFTPClient`/`SSHClient` para casos de éxito, fallo de auth, reintento y verificación de tamaño; test de integración opcional contra `sshd` local/contenedor.

**Dependencias:** Etapa 3.

### Criterios de validación
- Demostración: copia depositada y verificada (tamaño) en un servidor SFTP de prueba; ambos métodos de autenticación ejercitados.
- Servidor caído → reintento agotado, error registrado, el resto de servidores continúa.
- Host key desconocida con política `strict` falla con mensaje claro; `accept-new` la registra/acepta según configuración.
- Ningún log contiene contraseñas o contenido de claves.

---

## Etapa 5 — Notificación por correo y flujo end-to-end one-shot

**Descripción:** implementar el envío de correo a la casilla de control, el informe de ejecución, la retención local y cerrar el ciclo completo `odin run`. Al finalizar, una ejecución one-shot hace respaldo → compresión → transferencia → correo con informe y exit code final.

**Cubre:** F5, F8, F6 (exit codes finales), G4, C2–C6.

### Entregables
- Módulo `src/odin/notify.py`: envío SMTP con STARTTLS/SSL y autenticación desde `notification.smtp`; timeouts; destinatario `notification.to`.
- Informe de ejecución: estado global (ÉXITO / PARCIAL / FALLO), por base (tamaño original/comprimido, duración, errores) y por servidor destino (OK/FALLO + motivo). Formato texto plano; asunto con estado y hostname.
- Orquestador `src/odin/pipeline.py`: flujo completo por base, agregación de resultados, envío de correo **siempre** (éxito o fallo), manejo del caso SMTP caído (log + exit code, sin crash del proceso).
- Retención local (F8): limpieza de `.fbk`/`.fbk.7z` según `local.retention_days`, solo archivos gestionados por ODIN.
- Exit codes diferenciados: 0 éxito total, 3 fallo parcial, 4 fallo total, 2 error de configuración, 1 error interno.
- Tests: notificación con mock de `smtplib` (éxito, fallo SMTP, verificación de contenido sin secretos); política de retención; integración del pipeline con dobles de backup/compresión/transferencia.

**Dependencias:** Etapa 4.

### Criterios de validación
- Punta a end-to-end real: `odin run` sobre Firebird de prueba → correo recibido en la casilla de control con el resumen completo.
- Con un destino caído: correo con estado PARCIAL detallando el servidor fallido; exit code 3.
- Fallo de gbak: correo de FALLO con el error; exit code 4.
- Verificación explícita: logs y correo sin credenciales (test automatizado de enmascarado).

---

## Etapa 6 — Scheduler interno

**Descripción:** incorporar el scheduler propio que dispara el flujo completo según el bloque `scheduler` del JSON, sin planificadores del SO. Al finalizar, `odin service run` en primer plano ejecuta los jobs en los horarios configurados.

**Cubre:** F7 (scheduler), G6 (parcial).

### Entregables
- Módulo `src/odin/scheduler.py` sobre APScheduler (o implementación stdlib si la evaluación de la Etapa 1 lo recomienda):
  - Parseo de `schedule` tipo cron por job, con `timezone` global (validación de zonas horarias).
  - Políticas `skip_if_running` (sin respaldos simultáneos de la misma base) y `on_misfire` (`run_once` / `skip`) ante disparos perdidos.
  - Jobs por subconjunto de bases (`jobs[].databases`).
  - Recarga de configuración en caliente (señal SIGUSR1 en Linux / comando o reinicio controlado en Windows) con validación previa: si la nueva config es inválida, se mantiene la vigente y se loguea.
- CLI: `odin service run` (bloqueante, foreground) y `odin service status` básico (última ejecución, próximo disparo) vía archivo de estado JSON en `work_dir`.
- Cada ciclo del scheduler reutiliza el pipeline de la Etapa 5 con su propia notificación.
- Tests: programación de disparos con reloj falso, solapamiento (`skip_if_running`), misfire, recarga con config inválida.

**Dependencias:** Etapa 5.

### Criterios de validación
- Demostración: proceso foreground con job cada 1–2 minutos ejecuta el flujo completo y envía el correo por ciclo.
- Un job en ejecución al momento del próximo disparo no duplica el respaldo de la misma base (verificado por test).
- Cambio del JSON + recarga → próximos disparos actualizados sin reinicio; config inválida no rompe el servicio.

---

## Etapa 7 — Modo servicio: Windows Service y daemon Linux

**Descripción:** empaquetar el scheduler como servicio residente en ambas plataformas con gestión completa del ciclo de vida. Al finalizar, ODIN corre desatendido como servicio sin cron ni Task Scheduler.

**Cubre:** F7 (servicio), G6, C8.

### Entregables
- Subpaquete `src/odin/service/`:
  - **Windows** (`windows.py`, dependencia `pywin32` con marker): `odin service install|uninstall|start|stop|status` — registro del Windows Service, arranque automático, política de reinicio ante caída, manejo correcto de detención (shutdown limpio del scheduler).
  - **Linux**: `odin service run` ya existente; archivo de referencia `deploy/odin.service` (systemd: `Restart=always`, arranque en boot) + instrucciones; los comandos `install/uninstall` en Linux imprimen/guían la instalación de la unit (o la instalan si hay permisos, decisión a documentar).
- `odin service status` completo en ambas plataformas: estado del servicio, última ejecución, próximo disparo, errores recientes.
- Logging del servicio: archivo persistente con rotación (sin depender de la consola).
- Documentación operativa: `docs/service.md` con instalación, permisos requeridos (admin/root), arranque en boot y diagnóstico.
- Tests: lógica de ciclo de vida con mocks de `win32serviceutil` (Windows) y validación de la unit systemd (sintaxis, rutas); smoke test de arranque/detención limpia del scheduler.

**Dependencias:** Etapa 6.

### Criterios de validación
- Windows Server: `odin service install && odin service start` → el servicio sobrevive un reinicio del SO y arranca solo; una caída del proceso es recuperada por el gestor de servicios.
- Linux LTS: unit systemd activa el proceso en boot y lo reinicia ante caída.
- El scheduler dispara según horario configurado sin intervención externa en ambas plataformas.
- `odin service status` refleja estado real en ambas plataformas.

---

## Etapa 8 — Matriz de versiones Firebird, empaquetado uv y documentación final

**Descripción:** cerrar la calidad del producto: validar el soporte 2.5 → 6 de Firebird, verificar la instalación con `uv tool install` en ambas plataformas, pulir documentación y liberar la versión 1.0.

**Cubre:** G1 (completo), G5, C1, C7.

### Entregables
- Matriz de pruebas Firebird: al menos 2.5 y 5/6 con bases reales (contenedores/imágenes o instalaciones efímeras), verificando `gbak` de la familia correspondiente por versión; documentar incompatibilidades encontradas y la guía de `gbak_path` por versión.
- Verificación de instalación en limpio: `uv tool install` (desde el repositorio/paquete) en un Windows Server y un Linux LTS sin el entorno de desarrollo; prueba de `odin run` y del servicio instalado.
- `README.md` completo: instalación (uv), configuración (con los dos ejemplos por plataforma), operación (`run`, `validate`, `service`), resolución de problemas.
- Guía de seguridad: permisos del JSON (`600`/ACL), recomendación de autenticación por clave SSH, advertencia de credenciales en texto legible.
- Suite de tests completa corriendo en CI o script de verificación multiplataforma (`uv run pytest` verde en Linux y Windows).
- Tag/versión `1.0.0`.

**Dependencias:** Etapa 7.

### Criterios de validación
- Criterios de éxito 1–8 de la visión verificados uno a uno contra la release, con evidencia (logs/correos/salidas).
- Instalación desde cero en ambas plataformas sin pasos fuera de la documentación.
- Respaldo demostrado sobre Firebird 2.5 y sobre Firebird 5 o 6.
- Toda la documentación revisada por consistencia con el comportamiento real de la herramienta.

---

## Resumen de etapas

| Etapa | Entregable demostrable | Dependencia |
|---|---|---|
| 1 | `odin validate` sobre configs Linux/Windows | — |
| 2 | `odin run` genera `.fbk` con gbak | 1 |
| 3 | `odin run` genera `.fbk` + `.fbk.7z` | 2 |
| 4 | Copias depositadas vía SFTP (paramiko) | 3 |
| 5 | Ciclo one-shot completo con correo y retención | 4 |
| 6 | Scheduler interno en foreground | 5 |
| 7 | Servicio residente en Windows y Linux | 6 |
| 8 | Release 1.0 validada (matriz FB, uv, docs) | 7 |

---

## Próximo Paso

Revisar el roadmap y, en una **nueva sesión de chat**, ejecutar `/speckit.aide.create-progress` para crear el archivo de seguimiento de progreso.

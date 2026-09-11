# Progreso del Proyecto — ODIN

> **Paso 3 del flujo AI-Driven Engineering (AIDE).** Seguimiento de `docs/aide/vision.md` y `docs/aide/roadmap.md`. Actualizar durante la ejecución de work items (Paso 6).

**Leyenda:** 📋 Planificado · 🚧 En progreso · ✅ Completo · ⏸️ Diferido · ❌ Excluido

**Última actualización:** 2026-09-07 (Item 007 completo ✅)

---

## Resumen por Etapa

| Etapa | Nombre | Estado |
|---|---|---|
| 1 | Fundaciones: paquete, CLI, configuración JSON y validación | 🚧 |
| 2 | Respaldo Firebird con gbak | 🚧 |
| 3 | Compresión 7z | 📋 |
| 4 | Transferencia SFTP con paramiko | 📋 |
| 5 | Notificación por correo y flujo end-to-end one-shot | 📋 |
| 6 | Scheduler interno | 📋 |
| 7 | Modo servicio: Windows Service y daemon Linux | 📋 |
| 8 | Matriz Firebird, empaquetado uv y documentación final | 📋 |

---

## Etapa 1 — Fundaciones: paquete, CLI, configuración JSON y validación

Estado: 🚧

### Entregables
- ✅ Estructura de paquete `src/odin/` (`cli.py`, `config.py`, `log.py`, `paths.py`, `validate.py`), `tests/`, README inicial — todos los módulos de la Etapa 1 implementados (Item 006 ✅: `src/odin/validate.py` con validación completa del entorno local y de coherencia — 11 familias de verificación, `Severity`/`Finding`/`ValidationReport`, renderizado agrupado `ERRORES`/`ADVERTENCIAS`/`VERIFICACIONES`, solo lectura y sin red —, `--strict` en la CLI, sección "Validación de configuración" en el README; 63 tests nuevos)
- ✅ `pyproject.toml`: descripción, dependencias (`paramiko`, `py7zr`, `apscheduler`, `pywin32; sys_platform == "win32"`), `[project.scripts] odin`, config de pytest (Item 001)
- ✅ Modelo de configuración (dataclasses): `databases`, `compression`, `servers`, `notification`, `local`, `scheduler` con errores de parseo claros (Item 002 ✅: `src/odin/config.py` con validación agregada estructural + semántica, sugerencias de typo, defaults y campos de confiabilidad/observabilidad; fuentes del Item 001 restaurados tras pérdida sin commit)
- ✅ Normalización OS-agnóstica de rutas (`pathlib`, `/` y `\`, expansión de `~`, rutas relativas al JSON) (Item 003 ✅: `src/odin/paths.py` con absolutitud por sabor, `expand_user` propio y forma canónica `as_posix()`; integrado en `config.py` para `work_dir`, `log_dir`, `gbak_path`, `private_key`; 37 tests nuevos)
- ✅ Logging base: consola + archivo con rotación, nivel configurable, enmascarado de secretos (Item 004 ✅: `src/odin/log.py` con `setup_logging` idempotente — consola + `RotatingFileHandler` 5 MiB × 5 backups, nivel vía `LogLevel` — y `SecretMasker`/`MaskingFilter` puros reutilizables: secretos de `iter_secret_fields()` → `***` en ambos destinos, bloques PEM `PRIVATE KEY` vaciados por patrón; 30 tests en `tests/test_log.py`)
- ✅ CLI argparse: `odin validate --config <ruta>` + variable de entorno `ODIN_CONFIG`; exit codes (0/2/1) (Item 005 ✅: `src/odin/cli.py` con subcomando `validate` cableado a `load_config` + `setup_logging` — fallo operativo de logging no invalida la config (exit 0 + advertencia) —, resolución `--config` → `ODIN_CONFIG` → error 2, constantes `EXIT_OK`/`EXIT_INTERNAL`/`EXIT_CONFIG`, errores imprevistos → 1 con traceback controlado, SystemExit de argparse preservado y punto de extensión documentado para `run`/`service`; 15 tests en `tests/test_cli.py`)
- ✅ Ejemplos `examples/config.linux.json` y `examples/config.windows.json` (Item 007 ✅: fieles a la visión §5, charset `ISO8859_1`, secretos placeholder `***`, ambos con `odin validate` exit 0 en Linux — el de Windows omitiendo el `work_dir` por sabor distinto; `examples/README.md` con uso, seguridad (permisos 600/ACL, no versionar el JSON real) y campos opcionales con defaults; subsección "Ejemplos de configuración" en el README; 5 fixtures nuevos en `tests/fixtures/` —mínimo, rutas relativas+`~`, errores de tipo/rango/faltantes— y 16 tests en `tests/test_fixtures.py`)
- 📋 `uv sync` + `uv run pytest` funcionando en Linux y Windows

### Criterios de aceptación
- [x] `uv sync && uv run odin validate --config examples/config.linux.json` → exit code 0 — verificado en Linux (Item 007): ambos ejemplos dan exit 0 con advertencias no bloqueantes (JSON en 644, `work_dir` de desarrollo no creable sin root; el ejemplo Windows además omite el `work_dir` por sabor distinto). Con `--strict` dan 2 (esperado: son plantilla). Confirmación en Windows real → Item 009
- [x] JSON inválido produce mensajes específicos por campo (tipo, rango, ruta inexistente) — tipo/rango desde el Item 002 (`ConfigError.problems` con `field_path`); ruta inexistente/no creable desde el Item 006 (hallazgos ERROR/WARNING por campo, p. ej. `config.servers[1].auth.private_key`, `config.local.work_dir`)
- [x] Tests unitarios de parseo, normalización de rutas y enmascarado de secretos — parseo (Item 002, `test_config.py`), normalización (Item 003, `test_paths.py`) y enmascarado (Item 004, `test_log.py`) verdes; el Item 007 suma la capa sobre archivos reales (`test_fixtures.py`: mínimo→defaults, errores→`field_path` específicos, rutas relativas/`~`→normalización, ejemplos→pasan `validate`)
- [x] Compatibilidad de dependencias con Python 3.14 verificada y documentada (riesgo transversal) — verificada en Linux (Item 001); pendiente confirmación en Windows (Item 009)

---

## Etapa 2 — Respaldo Firebird con gbak

Estado: 📋

### Entregables
- ✅ `src/odin/backup.py`: auto-detección de `gbak` por SO/versión + override `gbak_path`
- ✅ Ejecución `gbak -b` con timeout, captura de progreso, detección de errores (exit code + patrones)
- ✅ Validación post-respaldo (archivo existe y no vacío); nombres `<nombre_bd>_<timestamp>.fbk` en `work_dir`
- ✅ Múltiples bases por ejecución; charset, rol, usuario/contraseña pasados de forma segura
- ✅ `odin run` ejecuta la fase de `ejecución` con exit codes apropiados
- ✅ Modelo `BackupResult` reutilizable (estado, archivo, tamaño, duración, error) y `BatchBackupResult` para múltiples bases (Item 015 ✅)
- 🚧 `src/odin/backup.py`: paso de `charset`, `role`, `user`, `password` a `gbak` sin exponer credenciales (Item 016 🚧)

### Criterios de aceptación
- [ ] `odin run` sobre Firebird de prueba produce `.fbk` íntegro (verificado con metadata gbak o restore scratch) (Item 018 🚧)
- [ ] `gbak_path` inválido, base inaccesible y timeout generan error claro y exit code ≠ 0
- [ ] Tests con mock de `subprocess` + test de integración marcado (`@pytest.mark.integration`) con Firebird real

---

## Etapa 3 — Compresión 7z

Estado: 📋

### Entregables
- 📋 `src/odin/compress.py`: `.fbk → .fbk.7z` con py7zr, nivel configurable, manejo de destino existente
- 📋 Reporte de tamaño original/comprimido y duración; extensión de `BackupResult`
- 📋 Opcional no bloqueante: cifrado AES-256 con `compression.password` (decisión documentada)
- 📋 Pipeline incremental en `odin run`: respaldo → compresión por base

### Criterios de aceptación
- [ ] Test ida y vuelta: comprimir/descomprimir con comparación byte a byte
- [ ] Nivel de compresión configurable tiene efecto medible en el tamaño
- [ ] Fallo de compresión no deja `.7z` parciales huérfanos y produce error claro
- [ ] Demo: `odin run` genera ambos archivos con tamaños informados

---

## Etapa 4 — Transferencia SFTP con paramiko

Estado: 📋

### Entregables
- 📋 `src/odin/transfer.py`: conexión paramiko con autenticación `password` y `key` (passphrase, `~` en ruta de clave)
- 📋 Política de host keys configurable (`strict` por defecto, `known_hosts`, `accept-new`, `insecure`)
- 📋 Creación recursiva de directorios remotos; upload + verificación de tamaño remoto vs. local
- 📋 Reintentos configurables con backoff; timeouts de conexión/operación
- 📋 Aislamiento de fallos por servidor; `TransferResult` por destino
- 📋 Pipeline extendido: respaldo → compresión → transferencia a todos los servidores

### Criterios de aceptación
- [ ] Demo: copia depositada y verificada en servidor SFTP de prueba con ambos métodos de autenticación
- [ ] Servidor caído: reintentos agotados, error registrado, resto de servidores continúa
- [ ] Host key desconocida falla con `strict` y se acepta con `accept-new` según config
- [ ] Ningún log contiene contraseñas o contenido de claves
- [ ] Tests con mock de paramiko (éxito, fallo de auth, reintentos, verificación) + integración opcional con sshd

---

## Etapa 5 — Notificación por correo y flujo end-to-end one-shot

Estado: 📋

### Entregables
- 📋 `src/odin/notify.py`: SMTP con STARTTLS/SSL, autenticación, timeouts, destinatario `notification.to`
- 📋 Informe de ejecución: estado global (ÉXITO/PARCIAL/FALLO), por base y por servidor (tamaños, duración, errores); asunto con estado y hostname
- 📋 `src/odin/pipeline.py`: flujo completo, correo **siempre**, SMTP caído no crashea (log + exit code)
- 📋 Retención local (F8): limpieza por `local.retention_days` solo de archivos gestionados por ODIN
- 📋 Exit codes: 0 éxito total, 3 parcial, 4 fallo total, 2 configuración, 1 interno

### Criterios de aceptación
- [ ] End-to-end real: `odin run` → correo recibido en la casilla de control con resumen completo
- [ ] Destino caído → correo PARCIAL con detalle; exit code 3
- [ ] Fallo de gbak → correo FALLO con error; exit code 4
- [ ] Test automatizado de enmascarado: logs y correo sin credenciales

---

## Etapa 6 — Scheduler interno

Estado: 📋

### Entregables
- 📋 `src/odin/scheduler.py` sobre APScheduler (o stdlib si la evaluación lo recomienda)
- 📋 `schedule` tipo cron por job + `timezone` con validación
- 📋 Políticas `skip_if_running` y `on_misfire` (`run_once`/`skip`); jobs por subconjunto de bases
- 📋 Recarga de configuración en caliente con validación previa (config inválida no rompe el servicio)
- 📋 CLI: `odin service run` (foreground) y `odin service status` básico vía archivo de estado en `work_dir`
- 📋 Cada ciclo reutiliza el pipeline con notificación propia

### Criterios de aceptación
- [ ] Demo: proceso foreground ejecuta el flujo completo en horarios cortos y envía correo por ciclo
- [ ] Job en ejecución no duplica respaldo de la misma base (test de solapamiento)
- [ ] Recarga con config válida actualiza disparos sin reinicio; config inválida mantiene la vigente
- [ ] Tests con reloj falso: disparos, misfire, solapamiento

---

## Etapa 7 — Modo servicio: Windows Service y daemon Linux

Estado: 📋

### Entregables
- 📋 `src/odin/service/windows.py` (pywin32): `odin service install|uninstall|start|stop|status`, arranque automático, reinicio ante caída, shutdown limpio
- 📋 Linux: `deploy/odin.service` de referencia (systemd `Restart=always`) + guía; comportamiento de `install/uninstall` en Linux documentado
- 📋 `odin service status` completo: estado del servicio, última ejecución, próximo disparo, errores recientes
- 📋 Logging persistente del servicio con rotación (sin depender de consola)
- 📋 `docs/service.md`: instalación, permisos (admin/root), arranque en boot, diagnóstico

### Criterios de aceptación
- [ ] Windows Server: servicio instalado y arrancado sobrevive reinicio del SO; caída recuperada automáticamente
- [ ] Linux LTS: unit systemd activa el proceso en boot y lo reinicia ante caída
- [ ] Scheduler dispara según horario sin intervención externa en ambas plataformas
- [ ] `odin service status` refleja estado real en ambas plataformas
- [ ] Tests de ciclo de vida (mock `win32serviceutil`) y validación de la unit systemd

---

## Etapa 8 — Matriz Firebird, empaquetado uv y documentación final

Estado: 📋

### Entregables
- 📋 Matriz de pruebas Firebird (mínimo 2.5 y 5/6) con `gbak` de la familia correspondiente; guía `gbak_path` por versión
- 📋 Verificación de `uv tool install` en Windows Server y Linux LTS limpios; prueba de `odin run` y del servicio
- 📋 `README.md` completo: instalación, configuración (ejemplos por plataforma), operación, troubleshooting
- 📋 Guía de seguridad: permisos del JSON (600/ACL), recomendación de clave SSH, advertencia de credenciales legibles
- 📋 Suite de tests completa verde en Linux y Windows (CI o script de verificación)
- 📋 Release/tag `1.0.0`

### Criterios de aceptación
- [ ] Criterios de éxito 1–8 de la visión verificados con evidencia (logs/correos/salidas)
- [ ] Instalación desde cero en ambas plataformas sin pasos fuera de la documentación
- [ ] Respaldo demostrado sobre Firebird 2.5 y sobre Firebird 5 o 6
- [ ] Documentación consistente con el comportamiento real

---

## Funcionalidades de la Visión (F1–F8)

| Funcionalidad | Estado | Etapa |
|---|---|---|
| F1. Respaldo Firebird 2.5 → 6 (gbak) | 📋 | 2 |
| F2. Compresión 7z (nivel configurable, AES opcional) | 📋 | 3 |
| F3. Configuración JSON legible OS-agnóstica + validación | 📋 | 1 |
| F4. Transferencia SFTP con paramiko (reintentos, verificación) | 📋 | 4 |
| F5. Notificación por correo (siempre, sin secretos) | 📋 | 5 |
| F6. CLI y operación (`run`, `validate`, `service`, exit codes, logging) | 📋 | 1, 5, 7 |
| F7. Scheduler propio + modo servicio residente | 📋 | 6, 7 |
| F8. Retención local | 📋 | 5 |

## Objetivos de la Visión (G1–G7)

| Objetivo | Estado | Etapa |
|---|---|---|
| G1. Respaldo confiable Firebird 2.5–6 | 📋 | 2, 8 |
| G2. Compresión 7z | 📋 | 3 |
| G3. Distribución SFTP con reintentos | 📋 | 4 |
| G4. Correo de trazabilidad en cada ejecución | 📋 | 5 |
| G5. Instalación uniforme vía uv (Windows/Linux) | 📋 | 1, 8 |
| G6. Servicio residente con scheduler propio | 📋 | 6, 7 |
| G7. Modo one-shot `odin run` compatible | 📋 | 2, 5 |

## Requisitos No Funcionales

- 📋 Confiabilidad: reintentos, aislamiento de fallos, recuperación del servicio, sin duplicación de respaldos (Etapas 4, 5, 6, 7)
- 📋 Seguridad: enmascarado de secretos, permisos del JSON, auth por clave SSH, política de host keys (Etapas 1, 4, 8)
- 📋 Portabilidad: misma base de código Windows Server 2016+ / Linux LTS (todas las etapas)
- 📋 Observabilidad: log con rotación, timestamps, duración y errores (Etapas 1, 5, 7)
- 📋 Rendimiento: timeouts en gbak/SFTP/SMTP, compresión acotada (Etapas 2, 4, 5)
- 📋 Mantenibilidad: pytest, dependencias mínimas, documentación (todas las etapas)

## Fuera de Alcance (exclusiones de la visión)

- ❌ Interfaz gráfica o web
- ❌ Restauración (restore) de backups
- ❌ Otros motores de base de datos
- ❌ Otros protocolos de envío (FTP, rsync, S3, nubes)
- ❌ Otros formatos de compresión (zip, gzip, zstd)
- ❌ Gestión de secretos tipo vault/KMS
- ❌ Agentes remotos o arquitectura distribuida
- ❌ Backups incrementales/diferenciales y replicación transaccional
- ❌ Plataformas fuera de Windows Server / Linux LTS

---

## Próximo Paso

Revisar el progreso y, en una **nueva sesión de chat**, ejecutar `/speckit.aide.create-queue` para generar el primer lote de work items priorizados.

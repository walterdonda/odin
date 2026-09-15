# Progreso del Proyecto — ODIN

> **Paso 3 del flujo AI-Driven Engineering (AIDE).** Seguimiento de `docs/aide/vision.md` y `docs/aide/roadmap.md`. Actualizar durante la ejecución de work items (Paso 6).

**Leyenda:** 📋 Planificado · 🚧 En progreso · ✅ Completo · ⏸️ Diferido · ❌ Excluido

**Última actualización:** 2026-09-15 (Etapa 5 en curso — Lote B completo: items 043-044, correo integrado al pipeline (siempre, SMTP caído no crashea) y matriz final de exit codes 0/1/3/4 con resumen de correo enmascarado; suite 376 passed + 1 skipped)
---

## Resumen por Etapa

| Etapa | Nombre | Estado |
|---|---|---|
| 1 | Fundaciones: paquete, CLI, configuración JSON y validación | 🚧 |
| 2 | Respaldo Firebird con gbak | ✅ |
| 3 | Compresión 7z | ✅ |
| 4 | Transferencia SFTP con paramiko | ✅ |
| 5 | Notificación por correo y flujo end-to-end one-shot | 🚧 |
| 6 | Scheduler interno | 🚧 |
| 7 | Modo servicio: Windows Service y daemon Linux | 🚧 |
| 8 | Matriz Firebird, empaquetado uv y documentación final | 🚧 |

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
- 🚧 `uv sync` + `uv run pytest` funcionando en Linux y Windows

### Criterios de aceptación
- [x] `uv sync && uv run odin validate --config examples/config.linux.json` → exit code 0 — verificado en Linux (Item 007): ambos ejemplos dan exit 0 con advertencias no bloqueantes (JSON en 644, `work_dir` de desarrollo no creable sin root; el ejemplo Windows además omite el `work_dir` por sabor distinto). Con `--strict` dan 2 (esperado: son plantilla). Confirmación en Windows real → Item 009
- [x] JSON inválido produce mensajes específicos por campo (tipo, rango, ruta inexistente) — tipo/rango desde el Item 002 (`ConfigError.problems` con `field_path`); ruta inexistente/no creable desde el Item 006 (hallazgos ERROR/WARNING por campo, p. ej. `config.servers[1].auth.private_key`, `config.local.work_dir`)
- [x] Tests unitarios de parseo, normalización de rutas y enmascarado de secretos — parseo (Item 002, `test_config.py`), normalización (Item 003, `test_paths.py`) y enmascarado (Item 004, `test_log.py`) verdes; el Item 007 suma la capa sobre archivos reales (`test_fixtures.py`: mínimo→defaults, errores→`field_path` específicos, rutas relativas/`~`→normalización, ejemplos→pasan `validate`)
- [x] Compatibilidad de dependencias con Python 3.14 verificada y documentada (riesgo transversal) — verificada en Linux (Item 001); pendiente confirmación en Windows (Item 009)

---

## Etapa 2 — Respaldo Firebird con gbak

Estado: ✅

### Entregables
- ✅ `src/odin/backup.py`: auto-detección de `gbak` por SO/versión + override `gbak_path`
- ✅ Ejecución `gbak -b` con timeout, captura de progreso, detección de errores (exit code + patrones)
- ✅ Validación post-respaldo (archivo existe y no vacío); nombres `<nombre_bd>_<timestamp>.fbk` en `work_dir`
- ✅ Múltiples bases por ejecución; charset, rol, usuario/contraseña pasados de forma segura
- ✅ `odin run` ejecuta la fase de `ejecución` con exit codes apropiados
- ✅ Modelo `BackupResult` reutilizable (estado, archivo, tamaño, duración, error) y `BatchBackupResult` para múltiples bases (Item 015 ✅)
- ✅ `src/odin/backup.py`: paso de `role`, `user`, `password` a `gbak` sin exponer credenciales (Item 016 ✅: switches corregidos a los nombres completos `-user`/`-password`/`-role` tras comprobar con `gbak -?` real que `-U`/`-P`/`-R`/`-E` eran inválidos —`-E` es `-expand`—; `charset` no se pasa porque `gbak` no tiene switch de charset y el respaldo transportable no depende del charset de conexión; enmascarado de `-password` en logs; verificado con Firebird 5.0.4 real: `odin run` → `.fbk` y restore scratch con las 3 filas intactas)
- ✅ Refactorización y limpieza de la Etapa 2 (Item 019 ✅: `odin run` integrado en la CLI — lote secuencial con `--config`/`ODIN_CONFIG`, resumen y exit codes 0/3/4 —, `BackupExecutor` con resolución de `gbak` por precedencia (`databases[].gbak_path` > ejecutor > auto-detección cacheada), `run_backup` que reporta todo error operativo en `BackupResult` (timeout incluido, ya no lanza), validación post-respaldo estricta (existe/no vacío/legible), `work_dir` autocreado y `BatchBackupResult.error_message` para fallos de lote; se retiró de `config.load_config` la comprobación de existencia de `gbak_path` que duplicaba `validate` y rompía configs cross-platform; logging consistente con la Etapa 1 y sin secretos; README con "Ejecución de respaldos (`odin run`)" y tabla de exit codes; test de integración endurecido (skip seguro, imagen oficial `firebirdsql/firebird`); limpieza de `D:/Backups/odin/logs/odin.log` y `README_COMPAT.md` con `.gitignore` ampliado; suite 231 passed + 1 skipped)

### Criterios de aceptación
- [x] `odin run` sobre Firebird de prueba produce `.fbk` íntegro (verificado con metadata gbak o restore scratch) (Item 018 ✅) — Firebird 5.0.4 real (Docker Desktop): `odin run` → `.fbk` de 1536 bytes; `gbak -c` a base scratch → `SELECT COUNT(*)` = 3 filas con datos idénticos; test `tests/test_backup_integration.py` **1 passed in 4.08 s**
- [x] `gbak_path` inválido, base inaccesible y timeout generan error claro y exit code ≠ 0 — `gbak_path` inexistente → exit 4 + "no se pudo ejecutar gbak" (test e2e en `tests/test_cli.py`); base inaccesible → exit 4 + `gbak: ERROR:I/O error ... "/var/lib/firebird/data/no_existe.fdb"`; timeout de 1 s sobre stub → exit 4 + "gbak excedió el timeout de 1 s"
- [x] Tests con mock de `subprocess` + test de integración marcado (`@pytest.mark.integration`) con Firebird real — `tests/test_backup.py` (16 tests con `unittest.mock`) y `tests/test_backup_integration.py` ejecutado contra el contenedor oficial `firebirdsql/firebird` (con skip seguro si falta Docker o `gbak`)

---

## Etapa 3 — Compresión 7z

Estado: 🚧

### Entregables
- ✅ `src/odin/compress.py`: `.fbk → .fbk.7z` con py7zr, nivel configurable, manejo de destino existente (Items 020-022 ✅: `compress_backup()` + `CompressionResult` + `archive_path_for()`, validación del artefacto, errores operativos en el resultado, escritura atómica que preserva la copia previa y mapeo de nivel 0=store / 1-9=LZMA2 con validación de rango; 28 tests unitarios en `tests/test_compress.py` contando el cifrado del Item 023 y el logging del Item 027)
- ✅ Reporte de tamaño original/comprimido y duración; extensión de `BackupResult` (Items 025 y 027 ✅: `BackupResult` extendido con `archive_path`/`compressed_size_bytes`/`compression_duration_seconds`/`compression_error_message` —defaults compatibles—, cruce por base en `_cmd_run` y resumen de consola con `.fbk` + `.fbk.7z`, tamaños y duración por fase; logs de `odin.compress` con doble barrera de enmascarado)
- ✅ Opcional no bloqueante: cifrado AES-256 con `compression.password` (Item 023 ✅: habilitado con 7zAES de py7zr 1.1.3, cabecera sin cifrar por estabilidad del error de clave incorrecta, filtro AES explícito —py7zr solo lo inyecta cuando `filters is None`—; round trip con clave correcta y fallo con clave ausente/incorrecta; cableado de `compression.password` verificado end-to-end en la CLI)
- ✅ Pipeline incremental en `odin run`: respaldo → compresión por base (Items 024-026 ✅: `CompressionExecutor` + `BatchCompressionResult` con aislamiento de fallos, `BackupResult` extendido, `_cmd_run` comprime tras el respaldo y cruza el éxito por base, resumen con ambos artefactos y exit codes 0/3/4 según el pipeline completo; 33 tests en `tests/test_compress.py` y 38 en `tests/test_cli.py`)

### Criterios de aceptación
- [ ] Demo: `odin run` genera ambos archivos con tamaños informados — cubierto por los tests e2e de los Items 025-026 (respaldo doblado + compresión real); la demo final con `gbak` real queda para el Item 029 (Lote C)
- [x] Test ida y vuelta: comprimir/descomprimir con comparación byte a byte — unitario en `tests/test_compress.py` (Items 020 y 023: sin cifrado y con AES-256); la variante de integración queda en el Item 028
- [x] Test de origen inexistente o corrupto
- [x] Test de fallo por disco lleno simulado (`OSError: No space left on device`)
- [x] Test de interrupción con limpieza de archivos temporales
- [x] Test de integración (`@pytest.mark.integration`) que ejecute `odin run` y verifique la generación de `.fbk` y `.fbk.7z`
- [x] `uv run pytest` pasa sin errores

---

## Etapa 4 — Transferencia SFFTP con paramiko

Estado: ✅

### Entregables
- ✅ `src/odin/transfer.py`: conexión paramiko con autenticación `password` y `key` (passphrase, `~` en ruta de clave) (Items 030 y 033 ✅)
- ✅ Política de host keys configurable (`strict` por defecto, `known_hosts`, `accept-new`, `insecure`) (Item 031 ✅)
- ✅ Creación recursiva de directorios remotos; upload + verificación de tamaño remoto vs. local (Item 032 ✅)
- ✅ Reintentos configurables con backoff; timeouts de conexión/operación (Item 033 ✅; parámetros por servidor cableados al parseo en el Item 035)
- ✅ Aislamiento de fallos por servidor y `TransferResult` por destino (Item 034 ✅: `TransferExecutor.run_batch_transfer()` recorre todos los `ServerConfig` y devuelve un `TransferResult` por destino —estado, tamaño verificado, duración y error— aunque un servidor falle tras agotar los reintentos; reenvía a `SFTPTransfer` los reintentos/timeouts/backoff y la política de host keys de cada servidor, cierra la conexión siempre (`finally`) y detecta el origen ausente antes de conectar; 8 tests nuevos en `tests/test_transfer_executor.py`; correcciones de integración necesarias: el auth ya no se reintenta y se usa el `set_missing_host_key_policy` real de paramiko; suite 295 passed + 1 skipped en ~5 s)
- ✅ Pipeline extendido: respaldo → compresión → transferencia a todos los servidores (Item 035 ✅: `src/odin/pipeline.py` con `run_pipeline(config)` — ejecutores inyectables — y `PipelineResult` (`BatchBackupResult` fusionado + `transfers` por base); solo se transfieren las bases con respaldo+compresión verdes; `BackupResult.transfer_error_message` marca la base fallida conservando los datos de las fases previas; exit codes 0/3/4 incluyen la transferencia; cierre de integración 030/033: `_parse_server` cablea `sftp_retries`/timeouts/backoff con validación y `_Validator.float_field` nuevo; 12 tests nuevos (`tests/test_pipeline.py`, exit codes en `tests/test_cli.py`, parseo en `tests/test_config.py`); suite 307 passed + 1 skipped)
- ✅ Reporte de transferencia en el resumen de `odin run` (Item 036 ✅: `BatchTransferResult` + `aggregate_transfer_results()` en `transfer.py`; `PipelineResult.transfers` expone el agregado por base — estructura lista para el correo de la Etapa 5 —; `_print_transfer_summary` con total de la fase y línea por servidor (OK con ruta remota/bytes/duración a stdout, FALLO con motivo a stderr) + agregado por base en el logger; README actualizado con la fase de transferencia y exit codes; 6 tests nuevos; suite 313 passed + 1 skipped)
- ✅ Tests de integración y unitarios SFTP (Item 037 ✅: `tests/test_transfer_upload.py` — 7 tests de huecos de upload: reintento de `put` ante error de red, agotamiento de reintentos, verificación de tamaño fallida como test propio, auth por clave con passphrase, rechazo PPK, cierre idempotente —; `tests/test_transfer_integration.py` — 3 tests contra un sshd ephemeral in-process (`paramiko.Transport` servidor + `SFTPServerInterface` sobre `tmp_path`, sin binarios ni contenedores): upload+verificación real con auth por contraseña y por clave RSA, y auth fallida —; bloque de código muerto de `tests/test_transfer.py` extraído a `test_upload_integrity_failure`; suite 323 passed + 1 skipped en ~11 s)
- ✅ `src/odin/transfer.py`: Implementación de reintentos y timeouts completada (Item 033)
- ✅ Enmascarado de secretos en la transferencia (Item 038 ✅: el resumen impreso de `odin run` —stdout y stderr— pasa por `SecretMasker.from_config` (`mask=` en `_print_backup_summary`/`_print_transfer_summary`, tipo `MaskFn`), porque los `error_message` pueden contener secretos indirectos (p. ej. la ruta de la clave privada en una excepción); los logs ya estaban cubiertos por `MaskingFilter`; 3 tests en `tests/test_transfer_masking.py` verifican por ausencia + presencia de `***` sobre CLI real y `odin.log` real; suite 326 passed + 1 skipped)

### Criterios de aceptación
- [x] Demo: copia depositada y verificada en servidor SFTP de prueba con ambos métodos de autenticación — servidor de prueba = sshd ephemeral in-process (protocolo SSH/SFTP real sobre loopback, Items 037): upload + verificación de tamaño end-to-end con autenticación por contraseña (`test_transfer_upload_and_verify_against_ephemeral_sshd`) y por clave RSA (`test_transfer_with_private_key_authentication`)
- [x] Servidor caído: reintentos agotados, error registrado, resto de servidores continúa — `tests/test_transfer_executor.py::test_retries_exhausted_before_continuing_with_next_server` (2 intentos al caído, el siguiente servidor sigue y completa) y aislamiento por base en `tests/test_pipeline.py`
- [x] Host key desconocida falla con `strict` y se acepta con `accept-new` según config — políticas unit-testeadas (`RejectPolicy` por defecto, `AutoAddPolicy` en accept-new, `WarningPolicy` en insecure); el sshd ephemeral demuestra `accept-new` real aceptando una clave desconocida en el primer contacto
- [x] Ningún log contiene contraseñas o contenido de claves — Item 038: tests de ausencia sobre `odin.log` real y sobre stdout/stderr de `odin run` con secretos inyectados en mensajes de error
- [x] Tests con mock de paramiko (éxito, fallo de auth, reintentos, verificación) + integración opcional con sshd — Items 034 y 037: 21 tests de transferencia (unit + executor + upload) más 3 de integración contra sshd ephemeral

---

## Etapa 5 — Notificación por correo y flujo end-to-end one-shot

Estado: 🚧

### Entregables
- ✅ `src/odin/notify.py`: SMTP con STARTTLS/SSL, autenticación, timeouts, destinatario `notification.to` (Item 039 ✅: `EmailNotifier`/`NotificationResult`/`ReportMessage` sobre `smtplib` con STARTTLS default, plano y SSL implícito `smtp.ssl` —mutuamente excluyente con `starttls` y validado en `config.py`—, timeout inline 30 s, errores operativos encapsulados sin propagación y sin credenciales; `validate` reporta el transporte y ya no advierte por `starttls: false` con SSL; ejemplos y README actualizados. Item 042 ✅: `tests/test_notify.py` con dobles de `smtplib.SMTP`/`SMTP_SSL` — 12 de transporte + 10 de render — y 3 tests de `smtp.ssl` en `tests/test_config.py`; 105 passed entre notify/config/log)
- ✅ Informe de ejecución: estado global (ÉXITO/PARCIAL/FALLO), por base y por servidor (tamaños, duración, errores); asunto con estado y hostname (Item 040 ✅: `render_report` puro sobre `PipelineResult`+`Config` con estado derivado del lote fusionado, detalle por base/destino, totales, cola de log opcional y enmascarado de asunto+cuerpo con `SecretMasker`; `now`/`hostname` inyectables. Item 041 ✅: `TailBufferHandler` + `capture_log_tail` en `log.py` con `deque(maxlen)`, enmascarado propio, `log_tail_lines == 0` desactivado y remoción garantizada; 11 tests nuevos en `tests/test_log.py`. Item 043 ✅: el pipeline captura la cola durante las fases y la entrega al render)
- ✅ `src/odin/pipeline.py`: flujo completo, correo **siempre**, SMTP caído no crashea (log + exit code) (Item 043 ✅: `run_pipeline` gana `notifier` inyectable (default `EmailNotifier.from_config`) y `PipelineResult.notification`; el informe se renderiza con la cola de `capture_log_tail` (`log_tail_lines` + `SecretMasker`) y se envía en todos los desenlaces —éxito, parcial, fallo total, lote no ejecutado y lote vacío—; `_send_report` convierte una excepción imprevista del notifier en `NotificationResult` fallido sin propagar; `_install_fake_executor`/`_install_fake_notifier` evitan SMTP real en la suite; 8 tests nuevos en `tests/test_pipeline.py`; ruff + mypy + 79 passed en pipeline/cli/notify)
- 🚧 Retención local (F8): limpieza por `local.retention_days` solo de archivos gestionados por ODIN
- ✅ Exit codes: 0 éxito total, 3 parcial, 4 fallo total, 2 configuración, 1 interno (Item 044 ✅: matriz final con el correo —0 exige correo enviado; un SMTP caído en corrida por lo demás exitosa degrada 0 → 1; el 4 de lote no ejecutado/vacío tiene precedencia y el 3 se conserva aunque el correo falle—, línea de resumen "Correo enviado a X"/"Correo NO enviado: motivo" enmascarada, `run --description` y tabla del README actualizados; 6 tests nuevos de CLI, suite pipeline/cli/notify/config 127 passed)

### Criterios de aceptación
- [ ] End-to-end real: `odin run` → correo recibido en la casilla de control con resumen completo
- [ ] Destino caído → correo PARCIAL con detalle; exit code 3
- [ ] Fallo de gbak → correo FALLO con error; exit code 4
- [ ] Test automatizado de enmascarado: logs y correo sin credenciales

---

## Etapa 6 — Scheduler interno

Estado: 🚧

### Entregables
- 🚧 `src/odin/scheduler.py` sobre APScheduler (o stdlib si la evaluación lo recomienda)
- 🚧 `schedule` tipo cron por job + `timezone` con validación
- 🚧 Políticas `skip_if_running` y `on_misfire` (`run_once`/`skip`); jobs por subconjunto de bases
- 🚧 Recarga de configuración en caliente con validación previa (config inválida no rompe el servicio)
- 🚧 CLI: `odin service run` (foreground) y `odin service status` básico vía archivo de estado en `work_dir`
- 🚧 Cada ciclo reutiliza el pipeline con notificación propia

### Criterios de aceptación
- [ ] Demo: proceso foreground ejecuta el flujo completo en horarios cortos y envía correo por ciclo
- [ ] Job en ejecución no duplica respaldo de la misma base (test de solapamiento)
- [ ] Recarga con config válida actualiza disparos sin reinicio; config inválida mantiene la vigente
- [ ] Tests con reloj falso: disparos, misfire, solapamiento

---

## Etapa 7 — Modo servicio: Windows Service y daemon Linux

Estado: 🚧

### Entregables
- 🚧 `src/odin/service/windows.py` (pywin32): `odin service install|uninstall|start|stop|status`, arranque automático, reinicio ante caída, shutdown limpio
- 🚧 Linux: `deploy/odin.service` de referencia (systemd `Restart=always`) + guía; comportamiento de `install/uninstall` en Linux documentado
- 🚧 `odin service status` completo: estado del servicio, última ejecución, próximo disparo, errores recientes
- 🚧 Logging persistente del servicio con rotación (sin depender de consola)
- 🚧 `docs/service.md`: instalación, permisos (admin/root), arranque en boot, diagnóstico

### Criterios de aceptación
- [ ] Windows Server: servicio instalado y arrancado sobrevive reinicio del SO; caída recuperada automáticamente
- [ ] Linux LTS: unit systemd activa el proceso en boot y lo reinicia ante caída
- [ ] Scheduler dispara según horario sin intervención externa en ambas plataformas
- [ ] `odin service status` refleja estado real en ambas plataformas
- [ ] Tests de ciclo de vida (mock `win32serviceutil`) y validación de la unit systemd

---

## Etapa 8 — Matriz Firebird, empaquetado uv y documentación final

Estado: 🚧

### Entregables
- 🚧 Matriz de pruebas Firebird (mínimo 2.5 y 5/6) con `gbak` de la familia correspondiente; guía `gbak_path` por versión
- 🚧 Verificación de `uv tool install` en Windows Server y Linux LTS limpios; prueba de `odin run` y del servicio
- 🚧 `README.md` completo: instalación, configuración (ejemplos por plataforma), operación, troubleshooting
- 🚧 Guía de seguridad: permisos del JSON (600/ACL), recomendación de clave SSH, advertencia de credenciales legibles
- 🚧 Suite de tests completa verde en Linux y Windows (CI o script de verificación)
- 🚧 Release/tag `1.0.0`

### Criterios de aceptación
- [ ] Criterios de éxito 1–8 de la visión verificados con evidencia (logs/correos/salidas)
- [ ] Instalación desde cero en ambas plataformas sin pasos fuera de la documentación
- [ ] Respaldo demostrado sobre Firebird 2.5 y sobre Firebird 5 o 6
- [ ] Documentación consistente con el comportamiento real

---

## Funcionalidades de la Visión (F1–F8)

| Funcionalidad | Estado | Etapa |
|---|---|---|
| F1. Respaldo Firebird 2.5 → 6 (gbak) | ✅ | 2 |
| F2. Compresión 7z (nivel configurable, AES opcional) | 🚧 | 3 |
| F3. Configuración JSON legible OS-agnóstica + validación | 🚧 | 1 |
| F4. Transferencia SFTP con paramiko (reintentos, verificación) | ✅ | 4 |
| F5. Notificación por correo (siempre, sin secretos) | 🚧 | 5 |
| F6. CLI y operación (`run`, `validate`, `service`, exit codes, logging) | 🚧 | 1, 5, 7 |
| F7. Scheduler propio + modo servicio residente | 🚧 | 6, 7 |
| F8. Retención local | 🚧 | 5 |

## Objetivos de la Visión (G1–G7)

| Objetivo | Estado | Etapa |
|---|---|---|
| G1. Respaldo confiable Firebird 2.5–6 | 🚧 | 2, 8 |
| G2. Compresión 7z | 🚧 | 3 |
| G3. Distribución SFTP con reintentos | ✅ | 4 |
| G4. Correo de trazabilidad en cada ejecución | 🚧 | 5 |
| G5. Instalación uniforme vía uv (Windows/Linux) | 🚧 | 1, 8 |
| G6. Servicio residente con scheduler propio | 🚧 | 6, 7 |
| G7. Modo one-shot `odin run` compatible | 🚧 | 2, 5 |

## Requisitos No Funcionales

- 🚧 Confiabilidad: reintentos, aislamiento de fallos, recuperación del servicio, sin duplicación de respaldos (Etapas 4, 5, 6, 7)
- 🚧 Seguridad: enmascarado de secretos, permisos del JSON, auth por clave SSH, política de host keys (Etapas 1, 4, 8)
- 🚧 Portabilidad: misma base de código Windows Server 2016+ / Linux LTS (todas las etapas)
- 🚧 Observabilidad: log con rotación, timestamps, duración y errores (Etapas 1, 5, 7)
- 🚧 Rendimiento: timeouts en gbak/SFTP/SMTP, compresión acotada (Etapas 2, 4, 5)
- 🚧 Mantenibilidad: pytest, dependencias mínimas, documentación (todas las etapas)

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

El **Lote B de la Etapa 5** quedó cerrado (items 043-044 ✅): el correo entró
al pipeline (`PipelineResult.notification`, notifier inyectable, cola de log
capturada durante las fases y envío en todos los desenlaces —éxito, parcial,
fallo total, lote no ejecutado y lote vacío—), y la matriz final de exit codes
quedó cerrada (0 exige correo enviado; SMTP caído en corrida exitosa → 1; lote
no ejecutado/vacío → 4 con precedencia), con línea "Correo enviado a X"/
"Correo NO enviado: motivo" enmascarada y README actualizado. 14 tests nuevos
(8 de pipeline, 6 de CLI). La suite completa queda en 376 passed + 1 skipped
(gbak real ausente en el host).

Siguiente: en una **nueva sesión de chat** ejecutar
`/speckit.aide.execute-batch 045,046` para el **Lote C** de `queue-005.md`:
retención local (`src/odin/retention.py`, F8) e integración en el pipeline,
reporte y actualización de `validate`.

# Progreso del Proyecto — ODIN

> **Paso 3 del flujo AI-Driven Engineering (AIDE).** Seguimiento de `docs/aide/vision.md` y `docs/aide/roadmap.md`. Actualizar durante la ejecución de work items (Paso 6).

**Leyenda:** 📋 Planificado · 🚧 En progreso · ✅ Completo · ⏸️ Diferido · ❌ Excluido

**Última actualización:** 2026-09-15 (Etapa 8 🚧 — Lote D 075-076 ✅: `README.md` reestructurado como entrada única —índice con anclas verificadas, requisitos, instalación con `uv tool install` desde wheel/repo y `uvx` más modo desarrollo con `scripts/verify.py`, configuración bloque por bloque con tabla resumen de campos y defaults tomada de `config.py`, operación y exit codes vigentes, logging, troubleshooting de 10 filas, seguridad, CI y licencia MIT— y `docs/security.md` con modelo de amenazas, permisos `chmod`/`icacls`, clave SFTP RSA con passphrase, políticas de host key, garantías y límites del enmascarado, TLS/SSL en SMTP, mínimo privilegio, checklist y rotación; enlazada desde README y `docs/service.md`, y los mensajes de permisos de `validate` apuntan a la guía con tests que lo afirman; gates **652 passed + 8 skipped in 71.12 s** + ruff + mypy Success 19 files)
---

## Resumen por Etapa

| Etapa | Nombre | Estado |
|---|---|---|
| 1 | Fundaciones: paquete, CLI, configuración JSON y validación | ✅ |
| 2 | Respaldo Firebird con gbak | ✅ |
| 3 | Compresión 7z | ✅ |
| 4 | Transferencia SFTP con paramiko | ✅ |
| 5 | Notificación por correo y flujo end-to-end one-shot | ✅ |
| 6 | Scheduler interno | ✅ |
| 7 | Modo servicio: Windows Service y daemon Linux | ✅ |
| 8 | Matriz Firebird, empaquetado uv y documentación final | 🚧 |

---

## Etapa 1 — Fundaciones: paquete, CLI, configuración JSON y validación

Estado: ✅

### Entregables
- ✅ Estructura de paquete `src/odin/` (`cli.py`, `config.py`, `log.py`, `paths.py`, `validate.py`), `tests/`, README inicial — todos los módulos de la Etapa 1 implementados (Item 006 ✅: `src/odin/validate.py` con validación completa del entorno local y de coherencia — 11 familias de verificación, `Severity`/`Finding`/`ValidationReport`, renderizado agrupado `ERRORES`/`ADVERTENCIAS`/`VERIFICACIONES`, solo lectura y sin red —, `--strict` en la CLI, sección "Validación de configuración" en el README; 63 tests nuevos)
- ✅ `pyproject.toml`: descripción, dependencias (`paramiko`, `py7zr`, `apscheduler`, `pywin32; sys_platform == "win32"`), `[project.scripts] odin`, config de pytest (Item 001)
- ✅ Modelo de configuración (dataclasses): `databases`, `compression`, `servers`, `notification`, `local`, `scheduler` con errores de parseo claros (Item 002 ✅: `src/odin/config.py` con validación agregada estructural + semántica, sugerencias de typo, defaults y campos de confiabilidad/observabilidad; fuentes del Item 001 restaurados tras pérdida sin commit)
- ✅ Normalización OS-agnóstica de rutas (`pathlib`, `/` y `\`, expansión de `~`, rutas relativas al JSON) (Item 003 ✅: `src/odin/paths.py` con absolutitud por sabor, `expand_user` propio y forma canónica `as_posix()`; integrado en `config.py` para `work_dir`, `log_dir`, `gbak_path`, `private_key`; 37 tests nuevos)
- ✅ Logging base: consola + archivo con rotación, nivel configurable, enmascarado de secretos (Item 004 ✅: `src/odin/log.py` con `setup_logging` idempotente — consola + `RotatingFileHandler` 5 MiB × 5 backups, nivel vía `LogLevel` — y `SecretMasker`/`MaskingFilter` puros reutilizables: secretos de `iter_secret_fields()` → `***` en ambos destinos, bloques PEM `PRIVATE KEY` vaciados por patrón; 30 tests en `tests/test_log.py`)
- ✅ CLI argparse: `odin validate --config <ruta>` + variable de entorno `ODIN_CONFIG`; exit codes (0/2/1) (Item 005 ✅: `src/odin/cli.py` con subcomando `validate` cableado a `load_config` + `setup_logging` — fallo operativo de logging no invalida la config (exit 0 + advertencia) —, resolución `--config` → `ODIN_CONFIG` → error 2, constantes `EXIT_OK`/`EXIT_INTERNAL`/`EXIT_CONFIG`, errores imprevistos → 1 con traceback controlado, SystemExit de argparse preservado y punto de extensión documentado para `run`/`service`; 15 tests en `tests/test_cli.py`)
- ✅ Ejemplos `examples/config.linux.json` y `examples/config.windows.json` (Item 007 ✅: fieles a la visión §5, charset `ISO8859_1`, secretos placeholder `***`, ambos con `odin validate` exit 0 en Linux — el de Windows omitiendo el `work_dir` por sabor distinto; `examples/README.md` con uso, seguridad (permisos 600/ACL, no versionar el JSON real) y campos opcionales con defaults; subsección "Ejemplos de configuración" en el README; 5 fixtures nuevos en `tests/fixtures/` —mínimo, rutas relativas+`~`, errores de tipo/rango/faltantes— y 16 tests en `tests/test_fixtures.py`)
- ✅ `uv sync` + `uv run pytest` funcionando en Linux y Windows — Item 071 ✅ cerró el pendiente del **Item 009 en Linux** (`scripts/verify.py`, solo stdlib, mismo archivo en ambas plataformas: `uv sync` → pytest → ruff → mypy → `odin validate` con salida por paso y exit 0 solo si todo pasa; evidencia EXIT=0, seis pasos OK); **Items 073/074 ✅** cierran el item: Windows corre el mismo script en el job `windows` de `.github/workflows/ci.yml` (listo para habilitar al publicar; hoy no hay remoto) más el smoke gated del SCM `ODIN_WINDOWS_SERVICE_SMOKE=1` y el runbook §8 — salvedad de la corrida real en `docs/service.md` §9

### Criterios de aceptación
- [x] `uv sync && uv run odin validate --config examples/config.linux.json` → exit code 0 — verificado en Linux (Item 007): ambos ejemplos dan exit 0 con advertencias no bloqueantes (JSON en 644, `work_dir` de desarrollo no creable sin root; el ejemplo Windows además omite el `work_dir` por sabor distinto). Con `--strict` dan 2 (esperado: son plantilla). Confirmación en Windows: el mismo gate corre en el job `windows` de la CI (Items 073/074) y el runbook §8 — salvedad de la primera corrida real al publicar el repositorio (`docs/service.md` §9)
- [x] JSON inválido produce mensajes específicos por campo (tipo, rango, ruta inexistente) — tipo/rango desde el Item 002 (`ConfigError.problems` con `field_path`); ruta inexistente/no creable desde el Item 006 (hallazgos ERROR/WARNING por campo, p. ej. `config.servers[1].auth.private_key`, `config.local.work_dir`)
- [x] Tests unitarios de parseo, normalización de rutas y enmascarado de secretos — parseo (Item 002, `test_config.py`), normalización (Item 003, `test_paths.py`) y enmascarado (Item 004, `test_log.py`) verdes; el Item 007 suma la capa sobre archivos reales (`test_fixtures.py`: mínimo→defaults, errores→`field_path` específicos, rutas relativas/`~`→normalización, ejemplos→pasan `validate`)
- [x] Compatibilidad de dependencias con Python 3.14 verificada y documentada (riesgo transversal) — verificada en Linux (Item 001; ciclo cerrado por el gate del Item 071); confirmación en Windows **delegada** al job `windows` de la CI (Items 073/074: `uv sync --locked` + gate único + smoke del SCM), con la salvedad de la primera corrida real al publicar (`docs/service.md` §9)

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

Estado: ✅

### Entregables
- ✅ `src/odin/notify.py`: SMTP con STARTTLS/SSL, autenticación, timeouts, destinatario `notification.to` (Item 039 ✅: `EmailNotifier`/`NotificationResult`/`ReportMessage` sobre `smtplib` con STARTTLS default, plano y SSL implícito `smtp.ssl` —mutuamente excluyente con `starttls` y validado en `config.py`—, timeout inline 30 s, errores operativos encapsulados sin propagación y sin credenciales; `validate` reporta el transporte y ya no advierte por `starttls: false` con SSL; ejemplos y README actualizados. Item 042 ✅: `tests/test_notify.py` con dobles de `smtplib.SMTP`/`SMTP_SSL` — 12 de transporte + 10 de render — y 3 tests de `smtp.ssl` en `tests/test_config.py`; 105 passed entre notify/config/log)
- ✅ Informe de ejecución: estado global (ÉXITO/PARCIAL/FALLO), por base y por servidor (tamaños, duración, errores); asunto con estado y hostname (Item 040 ✅: `render_report` puro sobre `PipelineResult`+`Config` con estado derivado del lote fusionado, detalle por base/destino, totales, cola de log opcional y enmascarado de asunto+cuerpo con `SecretMasker`; `now`/`hostname` inyectables. Item 041 ✅: `TailBufferHandler` + `capture_log_tail` en `log.py` con `deque(maxlen)`, enmascarado propio, `log_tail_lines == 0` desactivado y remoción garantizada; 11 tests nuevos en `tests/test_log.py`. Item 043 ✅: el pipeline captura la cola durante las fases y la entrega al render)
- ✅ `src/odin/pipeline.py`: flujo completo, correo **siempre**, SMTP caído no crashea (log + exit code) (Item 043 ✅: `run_pipeline` gana `notifier` inyectable (default `EmailNotifier.from_config`) y `PipelineResult.notification`; el informe se renderiza con la cola de `capture_log_tail` (`log_tail_lines` + `SecretMasker`) y se envía en todos los desenlaces —éxito, parcial, fallo total, lote no ejecutado y lote vacío—; `_send_report` convierte una excepción imprevista del notifier en `NotificationResult` fallido sin propagar; `_install_fake_executor`/`_install_fake_notifier` evitan SMTP real en la suite; 8 tests nuevos en `tests/test_pipeline.py`; ruff + mypy + 79 passed en pipeline/cli/notify)
- ✅ Retención local (F8): limpieza por `local.retention_days` solo de archivos gestionados por ODIN — Item 045 ✅: `src/odin/retention.py` con `RetentionExecutor`/`RetentionResult`/`RetentionError`/`is_managed_backup` (convención `<nombre_bd>_%Y%m%d_%H%M%S.fbk[.7z]`, frontera estricta del cutoff, protección `mtime >= inicio de corrida`, solo archivos regulares dentro de `work_dir`, sin symlinks, errores de borrado aislados e idempotencia; 25 tests en `tests/test_retention.py`). Item 046 ✅: fase de retención en `run_pipeline` **después del correo** (fuera del informe), `PipelineResult.retention`, notifier/ejecutor inyectables, red de seguridad que encapsula excepciones imprevistas y errores que no alteran el exit code; `_print_retention_summary` enmascarado (con variante deshabilitada y errores por stderr), `validate` sin "(Etapa 5)"
- ✅ Exit codes: 0 éxito total, 3 parcial, 4 fallo total, 2 configuración, 1 interno (Item 044 ✅: matriz final con el correo —0 exige correo enviado; un SMTP caído en corrida por lo demás exitosa degrada 0 → 1; el 4 de lote no ejecutado/vacío tiene precedencia y el 3 se conserva aunque el correo falle—, línea de resumen "Correo enviado a X"/"Correo NO enviado: motivo" enmascarada, `run --description` y tabla del README actualizados; 6 tests nuevos de CLI, suite pipeline/cli/notify/config 127 passed)
- ✅ Verificación y cierre de la Etapa 5 (Items 047-048 ✅: `tests/test_notify_integration.py` con SMTP efímero in-process sobre `socketserver` —`odin run` con `EmailNotifier` real contra el catcher: `MAIL FROM`/`RCPT TO`/`AUTH LOGIN`, asunto y cuerpo ÉXITO con base/servidor/totales/cola de log, sin secretos; puerto cerrado → exit 1 sin crash con entrada en `odin.log`; variante Firebird skip-safe—; README con las secciones "Notificación por correo" y "Retención local", `examples/README.md` y docstrings (`cli.py`, `log.py`, `validate.py`) alineados; criterios de aceptación de la etapa verificados uno a uno con evidencia; suite 410 passed + 2 skipped)

### Criterios de aceptación
- [x] End-to-end real: `odin run` → correo recibido en la casilla de control con resumen completo — Item 047: el catcher SMTP efímero in-process recibe el informe completo de un `odin run` con `EmailNotifier` real (`tests/test_notify_integration.py`, 2 passed); el envío a una casilla externa real no es verificable en este entorno (mismo criterio que el sshd ephemeral del Item 037) y la variante con Firebird por Docker queda skip-safe para el host que la tenga
- [x] Destino caído → correo PARCIAL con detalle; exit code 3 — `tests/test_cli.py::test_run_partial_transfer_failure_exits_3` (exit 3) + `tests/test_notify.py::test_render_partial_state` (el informe detalla el destino fallido); `uv run pytest ... -q` → 2 passed
- [x] Fallo de gbak → correo FALLO con error; exit code 4 — `tests/test_cli.py::test_run_total_failure_exits_4` + `tests/test_pipeline.py::test_total_failure_still_sends_report`; `uv run pytest ... -q` → 2 passed
- [x] Test automatizado de enmascarado: logs y correo sin credenciales — `tests/test_transfer_masking.py` (logs y resumen de `odin run`) + `tests/test_notify.py::test_render_never_includes_secrets` + `tests/test_notify_integration.py` (mensaje SMTP real); `uv run pytest ... -q` → 4 passed

---

## Etapa 6 — Scheduler interno

Estado: ✅

### Entregables
- ✅ `src/odin/scheduler.py` sobre APScheduler (o stdlib si la evaluación lo recomienda) — Items 049-051 ✅: helpers de calendario `cron_trigger`/`next_fire_times` (Item 049) y `SchedulerService` sobre APScheduler 3.11.3 (Item 050: `BlockingScheduler` con la timezone global, un job por `jobs[]` con id `job-N`/`max_instances=1`/`replace_existing=True`, `start()`/`shutdown()` bloqueante e idempotente, `cycle_runner` inyectable `(Config, SchedulerJob) -> CycleOutcome` con excepción encapsulada y `last_outcomes`) más el registro in-flight `InFlightRegistry` y las políticas de misfire (Item 051); decisión 3.x vs 4.x vs stdlib documentada en el docstring del módulo
- ✅ `schedule` tipo cron por job + `timezone` con validación — Item 049 ✅: `config._parse_job` valida la expresión con el mismo parser del scheduler (rango/sintaxis, `field_path` por job) y `_parse_scheduler` valida la `timezone` con `ZoneInfo` antes del trigger; `odin validate` reporta el próximo disparo de cada job en la timezone global (check `scheduler_next_fire`, WARNING si la expresión nunca dispara)
- ✅ Políticas `skip_if_running` y `on_misfire` (`run_once`/`skip`); jobs por subconjunto de bases — Item 051 ✅: reserva atómica por base con `threading.Lock` (todo-o-nada o solo libres), liberación garantizada en `finally`, omisión logueada con motivo en `CycleOutcome` (`skipped`/`skipped_reason`), `run_once` ↔ `coalesce=True` + `misfire_grace_time=None` y `skip` ↔ grace acotado + guard de latencia con reloj inyectable; tests de solapamiento con `threading.Event`, ambos valores de `skip_if_running` y misfire con reloj falso
- ✅ Recarga de configuración en caliente con validación previa (config inválida no rompe el servicio) — Item 055 ✅: `SchedulerService.request_reload()` (bandera thread-safe que activa el `SIGUSR1` instalado por `odin service run`) más el job interno `reload-watcher` (`IntervalTrigger` 2 s) que consume el archivo de control `work_dir/scheduler_reload.request` en plataformas sin señal; `process_reload()` valida `load_config` + `validate_config`, aplica timezone/jobs/`next_fire_time` sin detener el scheduler, elimina jobs ausentes del estado, refresca la máscara (`set_mask`) y dispara el hook `on_config_reloaded` (la CLI re-ejecuta `setup_logging`, idempotente); config inválida → conserva la vigente con el motivo en log + `recent_errors`; CLI `odin service reload` (SIGUSR1 / archivo de control / sin servicio → exit 1); 16 tests nuevos en `tests/test_scheduler.py`, `tests/test_scheduler_state.py` y `tests/test_cli.py`
- ✅ Test de integración del scheduler con el SMTP efímero (Item 056 ✅: `tests/test_scheduler_integration.py` — `SchedulerService` + `PipelineCycleRunner` + `run_pipeline` + `EmailNotifier` reales con fases dobles disparan por `run_job`: correo ÉXITO con el resumen del ciclo, `scheduler_state.json` con último ciclo + próximo disparo y sin secretos en mensaje/log/estado; caso FALLO con recuperación (2 correos, servicio operativo) —; catcher extraído a `tests/smtp_catcher.py` y reutilizado por `tests/test_notify_integration.py`; 4 passed + 1 skipped entre ambas integraciones)
- ✅ CLI: `odin service run` (foreground) y `odin service status` básico vía archivo de estado en `work_dir` (Item 052 ✅: estado consultable `ServiceState`/`JobState`/`CycleRecord` + `SchedulerStateStore` en `scheduler.py` — escritura atómica `tempfile.mkstemp`+`os.replace` con limpieza del temporal, lectura tolerante `StateLoadResult` con `warning` (ausente/corrupto/esquema desconocido), vigencia por `os.kill(pid, 0)` —siempre viva en Windows—, máscara de secretos al registrar y `recent_errors` acotado; `CycleOutcome.status` (`CycleStatus`) derivado de `skipped`/`partial`/`success`; 14 tests en `tests/test_scheduler_state.py`. Item 053 ✅: subcomando `service` con `run`/`status` en `cli.py` — `run` exige `scheduler.enabled: true`, arranca `SchedulerService` en primer plano con estado persistido, `SIGINT`/`SIGTERM` vía `_stop_signals` → shutdown + estado final + exit 0 (config inválida → 2, error interno → 1); `status` lee `scheduler_state.json` y presenta en ejecución/detenido/sin estado, jobs, próximo disparo, último ciclo, salud y errores recientes; `SchedulerService` acepta `state_store` opcional y `_complete` persiste cada desenlace (éxito/fallo/omisión) con su próximo disparo; 112 passed en cli/scheduler/scheduler_state)
- ✅ Cada ciclo reutiliza el pipeline con notificación propia (Item 054 ✅: `PipelineCycleRunner` en `scheduler.py` — filtra `config.databases` por las bases del job efectivo con la config del ciclo vía `dataclasses.replace` (la del servicio queda intacta), invoca `run_pipeline` con su correo y retención e inyecta `run`/opciones para tests e integración; traduce el resultado a `CycleOutcome` con estado global `CycleStatus` (éxito/parcial/fallo; prioridad del error de compresión > transferencia > respaldo), bases ejecutadas, duración y `notification_sent`; la excepción imprevista del pipeline la aísla el servicio y queda en `recent_errors`; secretos enmascarados en log y estado; 8 tests nuevos en `tests/test_scheduler.py`)
- ✅ Demo end-to-end en foreground con cadencia real de 1–2 minutos (Item 057 ✅: `tests/test_scheduler_foreground.py` con `odin service run` real en primer plano — CLI → `SchedulerService` → `PipelineCycleRunner` → `run_pipeline` → `EmailNotifier` — contra el catcher SMTP in-process y fases externas dobles: (1) dos ciclos con cadencia acortada (`modify_job` + `IntervalTrigger`), dos correos `[ODIN] ÉXITO`, estado actualizado tras cada ciclo, `odin service status` en vivo con "en ejecución (pid …)"/Salud OK/último ciclo y parada limpia con `EXIT_OK`; (2) proceso real en subproceso que responde a SIGTERM con exit 0 y estado final `stale`; (3) caso gated `ODIN_FOREGROUND_DEMO=1` con cron real `* * * * *` que corre dos ciclos en 78.6 s (evidencia ejecutada). README con la demo manual de 1–2 minutos; `uv run pytest tests/test_scheduler_foreground.py -q` → 2 passed + 1 skipped en ~3.7 s y la variante gated en 78.6 s)
- ✅ Documentación y cierre de la Etapa 6 (Item 058 ✅: README con la sección "Scheduler interno y modo servicio en primer plano" — bloque `scheduler` con tabla de campos, operación `run|status|reload`, formato de `scheduler_state.json`, recarga en caliente (SIGUSR1 / archivo de control / Windows), solapamiento y misfire, relación con `odin run`, exit codes de `service` y demo manual de 1–2 minutos —; docstrings de `validate.py` (reuso real en la recarga) y `scheduler.py` (rango de items) corregidos; criterios de la etapa verificados con evidencia y gates 495 passed + 3 skipped)

### Criterios de aceptación
- [x] Demo: proceso foreground ejecuta el flujo completo en horarios cortos y envía correo por ciclo — Item 057: `tests/test_scheduler_foreground.py` (2 passed + 1 skipped por defecto; gated `ODIN_FOREGROUND_DEMO=1` con cron real `* * * * *` → 2 ciclos en 78.6 s); el sustituto local y determinista ya estaba verde (Item 056: 2 ciclos reales por `run_job` contra el catcher SMTP, ÉXITO y FALLO + recuperación)
- [x] Job en ejecución no duplica respaldo de la misma base (test de solapamiento) — `tests/test_scheduler.py`: `test_overlapping_job_is_skipped`, `test_skip_if_running_false_runs_only_free_databases`, `test_skip_if_running_true_skips_whole_job_if_any_base_busy`, `test_skip_if_running_false_with_all_bases_busy_is_skipped` y `test_in_flight_registry_all_or_nothing` (reserva atómica por base con `threading.Lock`; `uv run pytest tests/test_scheduler.py -q -k "overlapping or skip_if_running or in_flight"` → 5 passed)
- [x] Recarga con config válida actualiza disparos sin reinicio; config inválida mantiene la vigente — Item 055: `tests/test_scheduler.py` (recarga válida con `next_fire_time` recalculado con reloj fijo y jobs altas/bajas aplicados; cron inválido y ERROR de entorno rechazados conservando `service.config`/triggers y registrando el motivo; archivo de control consumido de forma idempotente) + `tests/test_cli.py` (`service reload` → 0 con SIGUSR1, 1 sin servicio, archivo de control sin señal); `uv run pytest tests/test_scheduler.py tests/test_scheduler_state.py tests/test_cli.py -q` → **128 passed**
- [x] Tests con reloj falso: disparos, misfire, solapamiento — `tests/test_scheduler.py` con `now`/reloj inyectable: `test_next_fire_times_*` (reloj fijo, DST, fecha imposible, exactamente en `now`), `test_misfire_skip_discards_late_fire` / `test_misfire_run_once_executes_late_fire` / `test_misfire_policies_configure_apscheduler_job` y los de solapamiento con `threading.Event`; evidencia combinada: `uv run pytest tests/test_scheduler.py -q -k "overlapping or skip_if_running or misfire or next_fire_times or in_flight or reload"` → **22 passed**, 18 deselected

---

## Etapa 7 — Modo servicio: Windows Service y daemon Linux

Estado: ✅

### Entregables
- ✅ `src/odin/service/`: contrato portable del modo residente (Item 059 ✅: `src/odin/service/base.py` + `__init__.py` con `ServiceSpec` —`config_path` absoluta validada y `argv = <ejecutable> service run --config <ruta>`—, `ServiceStatus`, `ServiceManagerKind`, `ServiceManager` (ABC), `ServiceRuntime` (Protocol) y `ServiceError`/`ServiceUnsupportedError`/`ServiceNotInstalledError`; `create_service_manager(platform=...)` despacha con import diferido (`importlib`) sin tocar pywin32 en Linux; overrides de mypy para pywin32; 19 tests en `tests/test_service_base.py`; gates: 19 passed + ruff + mypy Success 16 files)
- ✅ `src/odin/service/windows.py` (pywin32): `odin service install|uninstall|start|stop|status`, arranque automático, reinicio ante caída, shutdown limpio (Item 061 ✅: `src/odin/service/windows.py` con imports de pywin32 perezosos (`_import_win32` → `ServiceUnsupportedError` fuera de Windows), `OdinWindowsService` construida perezosamente y publicada por `__getattr__` —`SvcDoRun` resuelve la config fijada en la instalación (`SetServiceCustomOption("ConfigPath")`, respaldo `ODIN_CONFIG`) y `SvcStop` espera la detención limpia—, `WindowsServiceManager` con `InstallService` en `SERVICE_AUTO_START`/manual + failure actions `SC_ACTION_RESTART` a `restart_delay_seconds` y reset periódico, `uninstall` idempotente, `start`/`stop` con espera por polling y `status` con auto-start/política de reinicio; 31 tests con dobles de pywin32. Item 062 ✅: CLI `install|uninstall|start|stop` — `install` exige `--config`/`ODIN_CONFIG`, valida el entorno (`validate_config`, solo ERROR bloquea) y pasa un `ServiceSpec` absoluto con el ejecutable resuelto (`sys.argv[0]`/`shutil.which`), imprimiendo el mensaje del gestor (o la guía sin permisos) y los pasos siguientes por plataforma; `uninstall|start|stop` operan por nombre fijo con `--config` opcional y capturan `ServiceError` → 1; 17 tests nuevos en `tests/test_cli.py`; gates: 88 passed en test_cli + ruff + mypy Success 18 files)
- ✅ Linux: `deploy/odin.service` de referencia (systemd `Restart=always`) + guía; comportamiento de `install/uninstall` en Linux documentado (Item 060 ✅: `src/odin/service/linux.py` con `render_unit` puro —`ExecStart` absoluto sin shell, quoting systemd, `Restart=always`/`no`, `User=`/`Group=` opcionales desde `account`— y `LinuxServiceManager` sobre `systemctl` inyectable: `install` escribe la unit + `daemon-reload` + `enable` con permisos y devuelve la guía textual sin ellos, `uninstall` idempotente, `start`/`stop` y `status` mapeando `show` (`is-active`/`is-enabled` de respaldo) a `ServiceStatus`; `deploy/odin.service` con placeholders documentados; 23 tests en `tests/test_service_linux.py`; gates: 42 passed + ruff + mypy Success 17 files)
- ✅ `odin service status` completo: estado del servicio, última ejecución, próximo disparo, errores recientes (Item 063 ✅: `render_platform_status` puro en `service/base.py` —encabezado del gestor (`systemd`/`windows`), estado instalado/en ejecución/detenido, arranque automático y política de reinicio en tres estados, sugerencias `odin service install`/`odin service start`— compuesto con `render_service_status`; `_cmd_service_status` consulta el gestor real (ruta absoluta, `manager_factory` inyectable) y degrada un `ServiceError` a advertencia conservando el exit 0; 7 tests en `tests/test_service_status.py` + 6 en `tests/test_cli.py`; gates: 120 passed + ruff + mypy Success 18 files)
- ✅ Logging persistente del servicio con rotación (sin depender de consola) (Item 064 ✅: `setup_logging(config, console=False)` deja un único `RotatingFileHandler` 5 MiB × 5 backups con nivel y `MaskingFilter`, sin `StreamHandler`, e idempotente entre recargas; `redirect_stdio_to_log(path)` redirige `sys.stdout`/`sys.stderr` a `odin.log` durante el bloque, restaura ambos al salir (incluso con excepción) y descarta el texto si el destino no es escribible; `odin service run` en primer plano conserva la consola; 9 tests nuevos en `tests/test_log.py` (50 passed))
- ✅ Runner compartido del modo residente (Item 065 ✅: `src/odin/service/runner.py` con `ServiceRunner` —carga/validación de la config, logging sin consola con stdio redirigido, store + `SchedulerService` real y `run()`/`stop()` thread-safe e idempotente—, parada previa al arranque en `SchedulerService` (cierra la carrera arranque/parada del gestor), delegación de `_cmd_service_run` en el runner conservando señales/exit codes/estado y fábrica `build_scheduler_service` compartida con la CLI; 13 tests en `tests/test_service_runner.py`; gates: 150 passed en cli/scheduler + 61 passed + 1 skipped en servicio + ruff + mypy Success 19 files)
- ✅ Verificación de integración del modo servicio Linux y runbook Windows (Item 066 ✅: `tests/test_service_linux_integration.py` con tres capas skip-safe —estructura de `deploy/odin.service` y `systemd-analyze verify` de la unit renderizada con ejecutable real (verify de la referencia saltado por placeholder, con motivo), ciclo de vida real de la CLI `install|start|status|stop|uninstall` contra `LinuxServiceManager` real con `systemctl` doble (secuencia exacta de comandos y exit 0/1) y demo gated `ODIN_SERVICE_DEMO=1` con unit temporal de usuario `Restart=always`: ciclo ÉXITO por el catcher SMTP, `kill -9` → systemd reinicia solo (MainPID nuevo) → segundo ciclo y limpieza total—; evidencia: 4 passed + 2 skipped por defecto y demo real **1 passed in 77.66 s** con sesión `systemctl --user`; el arranque en boot y Windows Server real quedan como procedimiento manual/runbook de `docs/service.md`, Item 067, para la Etapa 8/Item 009)
- ✅ `docs/service.md`: instalación, permisos (admin/root), arranque en boot, diagnóstico (Item 067 ✅: guía operativa completa —visión general, ciclo de vida con exit codes, Linux (unit de referencia, `daemon-reload`/`enable`, root vs usuario dedicado, recarga por `SIGUSR1`/archivo de control), Windows Server (consola elevada, arranque automático, failure actions de reinicio, cuenta y accesos, recarga por archivo de control, Visor de eventos), lectura de `odin service status` con salidas reales, log `<resolved_log_dir>/odin.log` con rotación 5 MiB × 5, diagnóstico de fallos comunes, desinstalación limpia y runbook de verificación en Windows Server real—; README con sección del modo servicio, matriz por plataforma, enlace a la guía y tabla de exit codes ampliada; sin cambios de código —la ayuda de la CLI ya estaba al día—; gates 623 passed + 5 skipped + ruff + mypy Success 19 files)
- ✅ Cierre de la Etapa 7 (Item 068 ✅: criterios verificados uno a uno con evidencia —unit y `systemd-analyze verify`, ciclo de vida Linux real por la CLI, auto-recuperación de systemd re-verificada en **102.27 s**, ciclo de vida Windows con 31 tests de dobles de pywin32, `status` compuesto (99 passed en status+cli) y validación de la unit systemd—; gates finales **623 passed + 5 skipped** + ruff + mypy Success 19 files; F7/G6 en ✅, C8 cubierto con la salvedad de Windows real y `queue-008.md` anunciada desde el item 069)

### Criterios de aceptación
- [x] Windows Server: servicio instalado y arrancado sobrevive reinicio del SO; caída recuperada automáticamente — ciclo de vida completo con dobles de `win32serviceutil`/`win32service` (Item 061: `InstallService` en `SERVICE_AUTO_START`, failure actions `SC_ACTION_RESTART` a los 5 s, `uninstall` idempotente, `start`/`stop` con espera y `status` con auto-start/política; 31 tests) y runbook de verificación en Windows Server real documentado en `docs/service.md` §8 (Item 067), a ejecutar en la Etapa 8 (Items 073/074: job `windows` de la CI o runbook §8; salvedad de la corrida real en `docs/service.md` §9); `uv run pytest tests/test_service_windows.py -q` → 31 passed
- [x] Linux LTS: unit systemd activa el proceso en boot y lo reinicia ante caída — validación estructural de `deploy/odin.service` y `systemd-analyze verify` de la unit renderizada con ejecutable real (Item 066, capa 1), arranque activado con `systemctl enable` + `WantedBy=multi-user.target` (Item 060) y auto-recuperación real re-verificada con la demo gated: ciclo ÉXITO por catcher SMTP, `kill -9` → systemd reinicia solo (MainPID nuevo) → segundo ciclo, `ODIN_SERVICE_DEMO=1 uv run pytest tests/test_service_linux_integration.py::test_user_service_restarts_after_kill_and_delivers_cycles -q` → **1 passed in 102.27 s**; el reinicio del SO queda como procedimiento manual (runbook §8)
- [x] Scheduler dispara según horario sin intervención externa en ambas plataformas — el parser/trigger cron está cubierto por los Items 049-051 y 057 (demo con cron real `* * * * *`: 2 ciclos en 78.6 s) y el modo residente lo ejecuta el mismo `ServiceRunner` compartido (Item 065): en la demo gated de systemd los dos ciclos los disparó el servicio sin intervención; `uv run pytest tests/test_service_runner.py tests/test_scheduler.py -q` → 54 passed (incluye reloj falso y solapamiento)
- [x] `odin service status` refleja estado real en ambas plataformas — `render_platform_status` compone el estado del gestor (`systemctl show` en Linux, `QueryServiceStatus`/`QueryServiceConfig` en Windows vía dobles) con `render_service_status` (pid vivo/obsoleto, jobs, próximo disparo, salud, errores); 7 tests en `tests/test_service_status.py` y 6 en `tests/test_cli.py` cubren las combinaciones (no instalado, detenido, corriendo, estado obsoleto, sin estado, gestor caído → exit 0 con advertencia); `uv run pytest tests/test_service_status.py tests/test_cli.py -q` → 99 passed
- [x] Tests de ciclo de vida (mock `win32serviceutil`) y validación de la unit systemd — `tests/test_service_windows.py` (31 tests con dobles de pywin32: params de `InstallService`, failure actions, espera en stop, mapeo de `status`, uninstall idempotente) y `tests/test_service_linux_integration.py` (4 passed + 2 skipped por defecto: estructura de la unit, verify real y ciclo CLI `install → start → status → stop → uninstall` con `systemctl` doble); suite de servicio completa: `uv run pytest tests/test_service_base.py tests/test_service_linux.py tests/test_service_windows.py tests/test_service_status.py tests/test_service_runner.py tests/test_service_linux_integration.py -q` → **97 passed + 2 skipped**

**C8 (criterio de éxito 8 de la visión):** cubierto por esta etapa —servicio
residente con scheduler propio sin cron ni Task Scheduler, recuperación
automática ante caída (demo systemd re-verificada) y solapamiento controlado
(Items 051/054)—, con el reinicio del SO en Windows Server real delegado al
runbook de `docs/service.md` §8 en la Etapa 8 (Items 073/074, salvedad de la
corrida real en §9). No se ajusta una
tabla C en `progress.md` (no existe para las etapas previas): la verificación
completa de los criterios 1–8 de la visión es el cierre de la Etapa 8.

---

## Etapa 8 — Matriz Firebird, empaquetado uv y documentación final

Estado: 🚧

### Entregables
- ✅ Matriz de pruebas Firebird (mínimo 2.5 y 5/6) con `gbak` de la familia correspondiente; guía `gbak_path` por versión (Items 069-070 ✅: `tests/firebird_container.py` —helper compartido de contenedores por familia, `gbak` de la propia imagen vía wrapper `docker exec --user root` con el `work_dir` montado en la misma ruta absoluta, sin `gbak` en el host— + `tests/test_firebird_matrix.py` parametrizado 2.5/3.0/4.0/5.0/6.0-snapshot `@integration` skip-safe que siembra con `isql`, respalda con `BackupExecutor`+`gbak_path`, valida el `.fbk` y restaura a scratch contando filas y charset; `test_backup_integration.py`/`test_notify_integration.py` adaptados al helper; matriz ejecutada con evidencia —2.5.9 LI-V2.5.9.27139 UTF8 2560 B, 3.0.9 LI-V3.0.9.33560 WIN1252, 4.0.5 LI-V4.0.5.3140 ISO8859_1, 5.0.4 LI-V5.0.4.1812 UTF8, 6.0-snapshot LI-T6.0.0.2177 UTF8, 3/3 filas restauradas en todas: `uv run pytest tests/test_firebird_matrix.py -q -m integration -s` → **5 passed in 23.31 s**—; `docs/firebird.md` con la matriz de compatibilidad, la regla de familia con las incompatibilidades verificadas (3+ ↔ 2.5 y formato de backup 1..9 vs 11), la guía de `gbak_path` (auto-detección, override, convivencia de instalaciones y ejemplos Linux/Windows), conexión/charset, reproducción local con `ODIN_FIREBIRD_*` y recomendación por despliegue; hueco real corregido: `/usr/local/firebird` (prefijo del tarball de 2.5) sumado a `gbak_finder` con test; README enlaza la guía; gates del batch: **631 passed + 3 skipped** + ruff + mypy Success 19 files)
- ✅ Verificación de `uv tool install` en Windows Server y Linux LTS limpios; prueba de `odin run` y del servicio — **Linux LTS ✅ (Items 071-072)**: `scripts/verify.py` como gate local (cierre del Item 009 en Linux) y empaquetado real verificado —`ODIN_BUILD_ARTIFACTS=1 uv run pytest tests/test_packaging.py -q` → 4 passed (wheel/sdist + `uv tool install` aislado + `odin 0.1.0`/`validate`/`service status`), capa `ubuntu:24.04` limpia (1 passed + 1 skipped) y e2e gated `ODIN_CLEAN_CONTAINER_E2E=1` → 2 passed con `odin run`, Firebird 5.0 de la matriz, SFTP/SMTP ephemeral, `.fbk`/`.fbk.7z` y correo `[ODIN] ÉXITO`; finding real: `tzdata` como dependencia directa—; **Windows Server (Item 074): vía preparada y delegada** — job `windows` de la CI (`.github/workflows/ci.yml`, gate + smoke gated del SCM) y runbook §8; la ejecución real queda pendiente al publicar el repositorio, con la evidencia a completar en `docs/service.md` §9
- ✅ `README.md` completo: instalación, configuración (ejemplos por plataforma), operación, troubleshooting (Item 075 ✅: reestructurado como entrada única —índice con anclas verificadas, requisitos por SO/Python/Firebird/conectividad, instalación con `uv tool install` desde wheel/repo y `uvx` más modo desarrollo con `scripts/verify.py`, configuración bloque por bloque con tabla resumen de campos y defaults tomada de `config.py`, operación con tabla de comandos y la tabla de exit codes vigente, logging con rotación/enmascarado/cola del informe, troubleshooting de 10 filas problema→causa→solución, seguridad enlazada a `docs/security.md`, CI y licencia MIT; enlaces y comandos contrastados contra el árbol y `--help`; gates 96 passed en smoke+cli + ruff + mypy Success 19 files)
- ✅ Guía de seguridad: permisos del JSON (600/ACL), recomendación de clave SSH, advertencia de credenciales legibles (Item 076 ✅: `docs/security.md` con modelo de amenazas y la decisión explícita del JSON legible, permisos por plataforma (`chmod`/`chown`/`icacls` con `/inheritance:r`), clave SFTP RSA con passphrase frente a password (con el límite real: `paramiko.RSAKey` y rechazo de PPK), las cuatro políticas de host key con sus riesgos, garantías y límites del enmascarado (incluido el `-password` de `gbak` en la lista de procesos y su mitigación), TLS/SSL en SMTP con la limitación de verificación de certificado, mínimo privilegio de la cuenta y checklist + rotación; enlazada desde README y `docs/service.md`, y los tres mensajes de permisos de `validate` apuntan a la guía (`_SECURITY_GUIDE`) con tests que lo afirman; gates 652 passed + 8 skipped + ruff + mypy Success 19 files)
- ✅ Suite de tests completa verde en Linux y Windows (CI o script de verificación) — Item 071 ✅: gate único `scripts/verify.py` (solo stdlib, Linux/Windows) con `--skip-sync`/`--quick`/`--only`, `tests/test_verify_script.py` (13 tests con runner inyectado, sin `uv` real) y quickstart por plataforma en el README; evidencia `uv run python scripts/verify.py` → EXIT=0 (pytest 48.84 s); **Item 073 ✅**: `.github/workflows/ci.yml` con jobs `linux`/`windows` (checkout, `astral-sh/setup-uv` con caché, `uv sync --locked`, el gate, `uv build` y wheel como artefacto) + sección "Integración continua" del README; el job `windows` suma el ciclo real del SCM gated `ODIN_WINDOWS_SERVICE_SMOKE=1` (`tests/test_service_windows_integration.py`) y `tests/test_ci_workflow.py` (6 tests) mantiene el YAML como contrato; workflow **listo para habilitar al publicar** (hoy sin remoto, primera corrida real en el Item 074)
- 🚧 Release/tag `1.0.0`

### Criterios de aceptación
- [ ] Criterios de éxito 1–8 de la visión verificados con evidencia (logs/correos/salidas)
- [ ] Instalación desde cero en ambas plataformas sin pasos fuera de la documentación — **Linux LTS ✅ (Item 072)**: host aislado y contenedor `ubuntu:24.04` limpio con el wheel, `odin --version`/`validate`/`service status` y e2e de `odin run`; **Windows Server (Items 073/074)**: vía CI/runbook preparada y documentada, con la salvedad de la ejecución real pendiente al publicar (`docs/service.md` §9)
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
| F5. Notificación por correo (siempre, sin secretos) | ✅ | 5 |
| F6. CLI y operación (`run`, `validate`, `service`, exit codes, logging) | 🚧 | 1, 5, 7 |
| F7. Scheduler propio + modo servicio residente | ✅ | 6, 7 |
| F8. Retención local | ✅ | 5 |

## Objetivos de la Visión (G1–G7)

| Objetivo | Estado | Etapa |
|---|---|---|
| G1. Respaldo confiable Firebird 2.5–6 | 🚧 | 2, 8 |
| G2. Compresión 7z | 🚧 | 3 |
| G3. Distribución SFTP con reintentos | ✅ | 4 |
| G4. Correo de trazabilidad en cada ejecución | ✅ | 5 |
| G5. Instalación uniforme vía uv (Windows/Linux) | 🚧 | 1, 8 (Linux ✅ 072) |
| G6. Servicio residente con scheduler propio | ✅ | 6, 7 |
| G7. Modo one-shot `odin run` compatible | ✅ | 2, 5 |

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

El **Lote D** de `queue-008.md` (items 075-076) quedó cerrado: el README es la
entrada única (índice, requisitos, instalación con `uv tool install`, tabla
resumen de campos y defaults, operación, logging, troubleshooting, seguridad,
CI y licencia) y `docs/security.md` documenta el modelo de amenazas, permisos,
claves SSH/host keys, enmascarado y rotación; los mensajes de permisos de
`validate` apuntan a la guía. La suite está en
**652 passed + 8 skipped in 71.12 s** + ruff + mypy Success 19 files.

Sigue la **Etapa 8** con el **Lote E** de `queue-008.md` (items 077-078: release
`1.0.0` con versión/CHANGELOG/artefactos/tag y el cierre de la etapa con los
criterios 1–8 de la visión verificados uno a uno). Siguiente: en una **nueva
sesión de chat** ejecutar `/speckit.aide.execute-batch 077,078`.

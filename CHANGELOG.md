# Changelog

Todos los cambios relevantes de ODIN se documentan en este archivo.

El formato se basa en [Keep a Changelog](https://keepachangelog.com/es/1.1.0/)
y el proyecto adhiere a [Versionado Semántico](https://semver.org/lang/es/).

## 1.1.0 - 2026-11-22

Segunda release menor: soporte **PostgreSQL 18.0+** como segundo motor de
respaldo junto a Firebird, con el contrato de configuración de dos motores
(`type` explícito y obligatorio por base) y el pipeline existente (compresión
7z, transferencia SFTP, correo y retención local) sin cambios de
comportamiento.

### Añadido

- **F9. Soporte PostgreSQL 18+ (`pg_dump`)**: segundo motor de respaldo con
  dump lógico por base (`pg_dump --format=custom`, artefacto `.dump` →
  `.dump.7z`) y contraseña vía `PGPASSWORD` en el entorno del subproceso
  (nunca en la línea de comandos ni en los logs). Contrato de configuración de
  dos motores: `databases[].type` explícito y obligatorio (`"firebird"` |
  `"postgresql"`), campos por motor (`host`, `port`, `dbname`,
  `pg_dump_path`, `pg_dump_timeout_sec` y `local.pg_dump_timeout_sec`) y
  checks condicionales en `odin validate` (que sigue siendo estático y sin
  red). Paquete `odin/engines/` (protocolo `Engine`, engines Firebird y
  PostgreSQL) con `BackupExecutor` genérico y dispatch por `type`; finder
  `pg_dump` con las rutas típicas de la serie 18 (majors ≥ 18, gana el mayor)
  y auto-detección por `PATH`. Retención de artefactos `.fbk|.dump` (`.7z`),
  CLI con descripción y helps de dos motores, y job de integración
  `postgresql` en la CI contra `postgres:18` real. La restauración (`.dump`)
  queda documentada como operación manual en
  [`docs/postgresql.md`](docs/postgresql.md). Firebird sin cambios de
  comportamiento.

### Corregido

- **CI (Linux)**: `test_encrypted_archive_wrong_password_fails` era inestable.
  py7zr cifra cada archivo con un IV aleatorio y, al descifrar con una clave
  incorrecta, el flujo LZMA2 resultante falla indistintamente con
  `lzma.LZMAError` (flujo corrupto) o `EOFError: Already at end of stream`
  (flujo terminado antes de tiempo); con IV aleatorio py7zr puede incluso no
  progresar y dejar el test colgado. Antes solo se aceptaba `LZMAError`; ahora
  el test fija el IV, cubre ambos fallos de forma determinista (más
  `py7zr.exceptions.ArchiveError` para un CRC que no cuadre) y comprueba que el
  contenido original no se recupera.
- **Windows**: `SyntaxError: multiple exception types must be parenthesized` al
  importar con builds de Python 3.14 previas a la final (la `3.14.0a6` que
  gestiona uv en Windows): el `except` de `_parse_scheduler` (`config.py`)
  usaba la sintaxis PEP 758 sin paréntesis; ahora va entre paréntesis, válida
  en toda la serie 3.x y semánticamente idéntica.
- **Windows**: `UnicodeEncodeError: 'charmap' codec can't encode character
  '\u2192'` al imprimir el resumen de `odin run` con la salida redirigida (ANSI
  `cp1252`), que terminaba con exit 1 una corrida por lo demás exitosa: la CLI
  reconfigura stdio a UTF-8 al arrancar (`_force_utf8_stdio`), en línea con
  `odin.log` y con el default de Python 3.15 (PEP 686).

### Documentación

- Nueva [`docs/postgresql.md`](docs/postgresql.md): **especificación, plan y
  notas de restauración del soporte PostgreSQL 18+** (segundo motor con
  `pg_dump`, formato custom `.dump`, contrato de configuración con `type`
  explícito y obligatorio, seam `odin/engines/`, finder `pg_dump`, tests y
  CI), aprobados en el mapa wayfinder `soporte-postgresql` e implementados en
  esta release.
- Nueva referencia [`docs/configuration.md`](docs/configuration.md): todos los
  campos del JSON de los dos motores (tipo, obligatoriedad, default, rangos,
  reglas cruzadas, ejemplos y límites conocidos), enlazada desde el README,
  `examples/README.md` y la guía de seguridad. En el resumen se corrigieron
  `local.log_level` (sin `CRITICAL`), la semántica de `sftp_retries`, los
  defaults de SMTP y el alcance real de los campos SFTP locales y de
  `sftp_operation_timeout_sec`.
- README, referencia de configuración, ejemplos y `CHANGELOG` actualizados al
  contrato de dos motores vigente: se retiró el estado «planificado» de
  PostgreSQL (descripción, requisitos, resumen de campos, flujo de `odin
  run`, retención y troubleshooting) y `examples/config.{linux,windows}.json`
  suman la entrada PostgreSQL.
- Nota de despliegue para Windows (README, troubleshooting y compatibilidad):
  instalar Python 3.14 **final** y no dejar que uv descargue la alpha
  `3.14.0a6` de su registro gestionado, previa a PEP 758 y con ABI incompatible
  con los wheels `cp314` de las dependencias.

## 1.0.0 - 2026-09-16

Primera release estable: respaldo externo de bases Firebird 2.5 → 6 con
`gbak`, compresión 7z, transferencia SFTP y notificación por correo, operable
como servicio residente en Windows Server y Linux LTS.

### Añadido

- **F1. Respaldo Firebird 2.5 → 6 (`gbak`)**: ejecución con timeout, charset,
  rol y credenciales por base, auto-detección de `gbak` con override
  `gbak_path` y validación del `.fbk` generado; matriz de compatibilidad
  verificada con Firebird 2.5.9, 3.0.9, 4.0.5, 5.0.4 y 6.0-snapshot
  (`docs/firebird.md`).
- **F2. Compresión 7z**: `.fbk` → `.fbk.7z` con `py7zr`, nivel configurable
  (0 = sin compresión, 1–9 LZMA2), escritura atómica y cifrado AES-256
  opcional con `compression.password`.
- **F3. Configuración JSON legible y OS-agnóstica**: único archivo con bases,
  servidores SFTP, SMTP, compresión, retención y scheduler; rutas con `/` o
  `\`, `~` y relativas al propio JSON; validación completa con `odin validate`
  (estructura, rutas, permisos, conectividad básica y `--strict`).
- **F4. Transferencia SFTP con paramiko**: autenticación por contraseña o
  clave privada (passphrase, `~`, rechazo de PPK), políticas de host key
  (`strict` por defecto, `known_hosts`, `accept-new`, `insecure`), creación de
  directorios remotos, verificación de tamaño, reintentos con backoff y
  aislamiento de fallos por servidor.
- **F5. Notificación por correo**: informe por ejecución (ÉXITO/PARCIAL/FALLO,
  detalle por base y servidor, totales y cola de log) enviado **siempre** por
  SMTP con STARTTLS (default) o SSL implícito, sin credenciales ni adjuntos.
- **F6. CLI y operación**: `odin validate`, `odin run` one-shot y
  `odin service run|status|reload|install|uninstall|start|stop`, con exit
  codes diferenciados (0 éxito, 3 parcial, 4 fallo, 2 configuración, 1
  interno), logging con rotación (5 MiB × 5) y opción `--config`/
  `ODIN_CONFIG`.
- **F7. Scheduler propio y modo servicio**: jobs cron por subconjunto de
  bases con timezone global, políticas `skip_if_running` y `on_misfire`,
  recarga en caliente (`SIGUSR1` / archivo de control / `odin service
  reload`), Windows Service con arranque automático y política de reinicio, y
  unit systemd de referencia con `Restart=always` (`deploy/odin.service`).
- **F8. Retención local**: limpieza de `.fbk`/`.fbk.7z` gestionados por ODIN
  según `local.retention_days`, con frontera estricta y protección de los
  archivos de la corrida en curso.
- **Distribución e instalación**: `uv tool install` (wheel, repositorio o
  `uvx`), gate único `scripts/verify.py` en Linux y Windows, CI
  multiplataforma lista para habilitar (`linux`/`windows`) y documentación
  final: `README.md`, `docs/firebird.md`, `docs/security.md` y
  `docs/service.md`.
- **Calidad**: suite de tests (unitarios, end-to-end con dobles, integración
  con contenedores Firebird, sshd ephemeral in-process y catcher SMTP) más
  `ruff` y `mypy` estrictos.

### Seguridad

- Enmascarado de secretos en logs, informes de correo, resumen de consola y
  `scheduler_state.json`; el JSON de configuración contiene credenciales en
  texto legible por decisión explícita, con guía de permisos (`chmod
  600`/`icacls`), claves SSH con passphrase y checklist de rotación en
  `docs/security.md`.

### Plataformas

- Windows Server 2016+ (incluye Windows Service nativo con `pywin32`) y Linux
  LTS (Ubuntu/Debian/RHEL/Rocky/AlmaLinux) con Python ≥ 3.14 gestionado por
  `uv`.

# ODIN

Respaldo externo de bases de datos Firebird (2.5 → 6): backup con `gbak`,
compresión 7z, transferencia SFTP (paramiko) y notificación por correo.

> Proyecto en desarrollo bajo el flujo AIDE (`docs/aide/`).

## Índice

- [Requisitos](#requisitos)
- [Instalación](#instalación)
  - [Instalación con `uv tool install`](#instalación-con-uv-tool-install)
  - [Modo desarrollo](#modo-desarrollo)
- [Configuración](#configuración)
  - [Bloques del JSON](#bloques-del-json)
  - [Tabla resumen de campos y defaults](#tabla-resumen-de-campos-y-defaults)
  - [Ejemplos](#ejemplos)
  - [Validación de configuración](#validación-de-configuración)
- [Operación](#operación)
  - [Ejecución de respaldos (`odin run`)](#ejecución-de-respaldos-odin-run)
  - [Notificación por correo](#notificación-por-correo)
  - [Retención local](#retención-local)
  - [Scheduler interno y modo servicio en primer plano](#scheduler-interno-y-modo-servicio-en-primer-plano)
  - [Modo servicio residente (Windows Service / daemon Linux)](#modo-servicio-residente-windows-service--daemon-linux)
  - [Logging](#logging)
  - [Exit codes](#exit-codes)
- [Troubleshooting](#troubleshooting)
- [Seguridad](#seguridad)
- [Integración continua](#integración-continua)
- [Compatibilidad de dependencias (Python 3.14)](#compatibilidad-de-dependencias-python-314)
- [Changelog](CHANGELOG.md)
- [Licencia](#licencia)

## Requisitos

| Requisito | Detalle |
|---|---|
| Sistema operativo | Windows Server 2016+ o Linux LTS. Misma base de código; la CI corre en `ubuntu-latest` y `windows-latest`. |
| Python | ≥ 3.14 (`requires-python = ">=3.14"`), gestionado con [uv](https://docs.astral.sh/uv/). `tzdata` viaja como dependencia para `scheduler.timezone` donde el SO no trae la base IANA (Windows y contenedores mínimos). |
| Firebird | Servidor accesible y `gbak` de la **misma versión mayor** que cada base (cliente o servidor instalado). La [guía de compatibilidad Firebird](docs/firebird.md) cubre la matriz 2.5 → 6 y la resolución de `gbak_path` por plataforma. |
| Conectividad | Firebird 3050/TCP (o el puerto configurado), SFTP 22/TCP (o el configurado) y el servidor SMTP. |
| Permisos | Escritura en `local.work_dir` y en el directorio de logs. `root` (Linux) o consola elevada (Windows) solo para instalar el servicio del SO. |

## Instalación

### Instalación con `uv tool install`

Con `uv` instalado, ODIN se instala como **herramienta aislada** (sin el
entorno de desarrollo ni el repositorio):

```bash
uv build                                # genera dist/odin-<versión>-py3-none-any.whl
uv tool install dist/odin-*.whl         # instala el wheel
odin --version                          # → odin 1.0.0
```

También se puede instalar directamente desde el repositorio (construye la
fuente actual), o ejecutarlo sin instalarlo:

```bash
uv tool install .                       # instala la fuente del repo
uvx --from . odin --version             # ejecución efímera, sin instalar
```

`uv tool install` deja el ejecutable en `~/.local/bin/odin` (Linux) o
`%USERPROFILE%\.local\bin\odin.exe` (Windows). Si ese directorio no está en el
`PATH`, agregalo con `uv tool update-shell` y volvé a abrir la terminal. Para
actualizar o desinstalar: `uv tool upgrade odin` (instalaciones desde índice o
repositorio) o reinstalar el wheel nuevo, y `uv tool uninstall odin`.

### Modo desarrollo

El **gate único** de desarrollo y CI es `scripts/verify.py`: corre `uv sync`,
la suite de tests, `ruff`, `mypy` y `odin validate` sobre los dos ejemplos,
con salida por paso (comando, duración, estado), resumen final y exit code 0
solo si todo pasa. Es solo stdlib y el mismo archivo en ambas plataformas
(`uv` se resuelve del `PATH`; en Windows es `uv.exe`).

**Linux LTS** (bash):

```bash
uv sync
uv run python scripts/verify.py                       # gate completo
uv run python scripts/verify.py --quick               # omite los tests @integration
uv run python scripts/verify.py --skip-sync --only pytest
```

**Windows Server** (PowerShell):

```powershell
uv sync
uv run python scripts\verify.py                       # gate completo
uv run python scripts\verify.py --quick               # omite los tests @integration
uv run python scripts\verify.py --skip-sync --only pytest
```

`--help` documenta los flags (`--skip-sync`, `--quick`, `--only <id>`; ids:
`sync`, `pytest`, `ruff`, `mypy`, `validate-linux`, `validate-windows`).

El ciclo de desarrollo completo se verifica con ese gate; `uv run odin
--version` está incluido en el quickstart.

## Configuración

ODIN se configura con un único **JSON legible y OS-agnóstico**: las rutas
aceptan `/` o `\`, `~` se expande al usuario que ejecuta y las rutas relativas
se resuelven contra el directorio del propio JSON. La configuración contiene
credenciales en texto legible: restringí sus permisos y no la versiones (ver
[Seguridad](#seguridad) y [`docs/security.md`](docs/security.md)).

### Bloques del JSON

Referencia rápida por bloque; los ejemplos completos están en
[`examples/`](examples/) y cada campo se valida al cargar la configuración.

- **`databases[]`** — una entrada por base Firebird. `name` es la clave
  estable que referencian los jobs del scheduler; `connection` se pasa a
  `gbak` tal cual (`host/puerto:ruta` o alias). `gbak_path: null` delega la
  resolución a la auto-detección por SO y versión
  (ver [`docs/firebird.md`](docs/firebird.md)).
- **`compression`** — nivel de 7z (`0` = *store*, `1–9` = LZMA2; default `7`)
  y `password` opcional para cifrado AES-256 del `.fbk.7z`.
- **`servers[]`** — destinos SFTP con reintentos, timeouts y política de host
  keys. `auth.method` es `password` o `key` (`private_key` con `passphrase`
  opcional, `~` permitido).
- **`notification`** — casilla destino/remitente y transporte SMTP
  (`starttls` por defecto; `smtp.ssl` para SSL implícito).
- **`local`** — directorios de trabajo y logs, nivel de logging, umbral de
  espacio libre y defaults operativos (timeouts y reintentos).
- **`scheduler`** — jobs cron por subconjunto de bases;

  ```json
  "scheduler": {
    "enabled": true,
    "timezone": "America/Argentina/Buenos_Aires",
    "jobs": [
      {
        "databases": ["erp_principal", "erp_sucursal"],
        "schedule": "0 2 * * *",
        "skip_if_running": true,
        "on_misfire": "run_once"
      }
    ]
  }
  ```

  La semántica de solapamiento y misfire está en
  [Scheduler interno](#scheduler-interno-y-modo-servicio-en-primer-plano).

### Tabla resumen de campos y defaults

| Bloque / campo | Default | Descripción |
|---|---|---|
| `databases[].name` | — (requerido) | Clave única de la base; la usan los jobs. |
| `databases[].connection` | — (requerido) | Cadena de conexión que se pasa a `gbak`. |
| `databases[].user` / `.password` | — (requeridos) | Credenciales Firebird; se enmascaran en logs e informes. |
| `databases[].role` | `null` | Rol SQL opcional (`-role`). |
| `databases[].charset` | `null` | Charset conservado en la configuración; `gbak` no admite switch de charset. |
| `databases[].gbak_path` | `null` | Ruta explícita al `gbak`; `null` = auto-detección. |
| `databases[].gbak_timeout_sec` | `null` → `local.gbak_timeout_sec` | Timeout del respaldo por base. |
| `compression.level` | `7` | `0` = sin compresión (*store*); `1–9` = LZMA2. |
| `compression.password` | `null` | Con valor, el `.fbk.7z` se cifra con AES-256. |
| `servers[].name` | — (requerido) | Identificador del destino en el informe. |
| `servers[].host` / `.port` | — (requeridos) | Servidor SFTP. |
| `servers[].username` | — (requerido) | Usuario SFTP. |
| `servers[].auth.method` | `password` | `password` o `key`. |
| `servers[].auth.password` | `null` | Contraseña SFTP cuando `method: password`. |
| `servers[].auth.private_key` / `.passphrase` | `null` | Clave privada (y passphrase) cuando `method: key`; `~` se expande. |
| `servers[].remote_path` | — (requerido) | Directorio remoto destino; se crea si no existe. |
| `servers[].host_key_policy` | `strict` | `strict`, `known_hosts`, `accept-new` o `insecure` (ver [Seguridad](#seguridad)). |
| `servers[].sftp_retries` | `3` | Reintentos de conexión/operación. |
| `servers[].sftp_connect_timeout_sec` | `30` | Timeout de conexión SSH. |
| `servers[].sftp_operation_timeout_sec` | `60` | Timeout por operación SFTP. |
| `servers[].sftp_retry_backoff_base` | `2.0` | Base del backoff exponencial entre reintentos (segundos). |
| `servers[].sftp_retry_max_delay_sec` | `30.0` | Tope del backoff (segundos). |
| `notification.to` / `.from` | — (requeridos) | Casilla de control y remitente del informe. |
| `notification.log_tail_lines` | `50` | Últimas líneas del log (ya enmascaradas) que se anexan al cuerpo; `0` desactiva la cola. |
| `notification.smtp.host` / `.port` | — (requeridos) | Servidor SMTP. |
| `notification.smtp.starttls` | `true` | Negocia STARTTLS antes de autenticar; `false` envía en plano (relays locales). |
| `notification.smtp.ssl` | `false` | SSL implícito (típicamente puerto 465); mutuamente excluyente con `starttls: true`. |
| `notification.smtp.username` / `.password` | `""` | Autenticación SMTP; vacíos omiten el `AUTH`. |
| `local.work_dir` | — (requerido) | Directorio de artefactos y estado; se autocrea. |
| `local.retention_days` | — (requerido) | `0` deshabilita la limpieza; `N > 0` elimina copias gestionadas de más de `N` días. |
| `local.log_level` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` o `CRITICAL`. |
| `local.log_dir` | `null` → `<work_dir>/logs` | Directorio del `odin.log`. |
| `local.min_free_mb` | `1024` | Espacio libre mínimo exigido en `work_dir` por `validate`. |
| `local.gbak_timeout_sec` | `7200` | Timeout por defecto del respaldo. |
| `local.sftp_retries` | `3` | Reintentos SFTP por defecto (si el servidor no los define). |
| `local.sftp_connect_timeout_sec` | `30` | Timeout de conexión SFTP por defecto (si el servidor no lo define). |
| `scheduler.enabled` | `false` | Habilita el scheduler interno; `odin service run` exige `true`. |
| `scheduler.timezone` | `"UTC"` | Zona IANA que interpreta los `schedule` y los `next_fire_time`. |
| `scheduler.jobs[].databases` | — (requerido) | Bases del job (validadas contra `databases`). |
| `scheduler.jobs[].schedule` | — (requerido) | Cron de 5 campos (minuto, hora, día del mes, mes, día de la semana). |
| `scheduler.jobs[].skip_if_running` | `true` | `true`: omite el ciclo si alguna base está ocupada; `false`: corre solo con las libres. |
| `scheduler.jobs[].on_misfire` | `run_once` | `run_once`: recupera el disparo vencido; `skip`: lo descarta. |

### Ejemplos

El directorio [`examples/`](examples/) trae configuraciones de ejemplo listas
para copiar, una por plataforma:

- [`examples/config.linux.json`](examples/config.linux.json) — Linux LTS.
- [`examples/config.windows.json`](examples/config.windows.json) — Windows
  Server.

Ambos reproducen el mismo esquema OS-agnóstico (solo cambian las rutas) con
secretos como placeholder `***`. [`examples/README.md`](examples/README.md)
explica cómo adaptarlos, las recomendaciones de seguridad (permisos `600`/ACL,
no versionar el JSON real) y los campos opcionales con sus valores por
defecto. Validá tu configuración con `odin validate` antes de ejecutar.

El bloque `notification.smtp` define el transporte del informe: `starttls: true`
(default) negocia STARTTLS; `starttls: false` envía en plano (relays locales); y
`smtp.ssl: true` usa SSL implícito (típicamente puerto 465) y es mutuamente
excluyente con `starttls: true`.

### Validación de configuración

```bash
uv run odin validate --config ruta/al/config.json    # o vía ODIN_CONFIG
uv run odin validate --config ruta/al/config.json --strict
```

`odin validate` comprueba, en este orden:

1. **Estructura y tipos** del JSON (campos requeridos, rangos, enums, campos
   desconocidos con sugerencia de typo) y **semántica** (nombres únicos,
   jobs del scheduler que referencian bases existentes, coherencia entre
   `auth.method` y sus credenciales).
2. **Entorno local**: `local.work_dir` y `local.log_dir` (existentes, creables
   o en conflicto), `servers[].auth.private_key` con método `key` (existe, es
   legible, permisos recomendados `600`), `databases[].gbak_path` explícito
   (existe y es ejecutable), permisos del propio JSON, espacio libre vs.
   `local.min_free_mb`.
3. **Coherencia operativa**: scheduler habilitado sin jobs, bases no cubiertas
   por ningún job, ausencia de destinos SFTP, `host_key_policy: insecure`,
   `starttls: false` sin `smtp.ssl` (canal SMTP sin cifrar), retención
   desactivada.

La salida agrupa los hallazgos en `ERRORES`, `ADVERTENCIAS` y `VERIFICACIONES`,
cada uno con la ruta del campo implicado (p. ej. `config.servers[1].auth.private_key`).
Los errores y el veredicto de invalidez van a stderr; el contexto y el veredicto
de validez, a stdout.

#### Garantías

- **Solo lectura:** `validate` no crea ni modifica archivos (el directorio de
  logs lo crea la configuración del logging, después de las verificaciones).
- **Sin red:** no comprueba conectividad SFTP, SMTP ni Firebird; un destino
  temporalmente caído no invalida la configuración.
- **Sin secretos:** la salida y el log nunca incluyen contraseñas,
  passphrases ni contenido de claves privadas.
- **OS-agnóstico:** una ruta cuyo sabor (Windows o POSIX) no coincide con el
  sistema donde se ejecuta no es comprobable: se omite con una nota, nunca
  cuenta como error.

## Operación

Los comandos aceptan `--config <ruta>`; si se omite, usan la variable de
entorno `ODIN_CONFIG`.

| Comando | Qué hace |
|---|---|
| `odin validate --config <ruta>` | Valida el JSON sin escribir nada; `--strict` trata las advertencias como errores (exit 2). |
| `odin run --config <ruta>` | Ciclo **one-shot** sobre todas las bases: respaldo, compresión, transferencia, correo y retención. |
| `odin service run --config <ruta>` | Scheduler en primer plano hasta `SIGINT`/`SIGTERM`. |
| `odin service status --config <ruta>` | Estado del gestor del SO y del scheduler. |
| `odin service reload --config <ruta>` | Recarga en caliente de la configuración. |
| `odin service install\|uninstall\|start\|stop [--config <ruta>]` | Ciclo de vida del servicio residente (systemd/SCM). |
| `odin --version` | Versión instalada (hoy `odin 1.0.0`). |
| `odin --help` / `odin <cmd> --help` | Ayuda y subcomandos. |

```bash
uv run odin validate --config examples/config.linux.json
uv run odin run --config /etc/odin/config.json
uv run odin service run --config /etc/odin/config.json
uv run odin --version
```

### Ejecución de respaldos (`odin run`)

```bash
uv run odin run --config ruta/al/config.json     # o vía ODIN_CONFIG
```

`odin run` ejecuta el **ciclo one-shot completo** de ODIN sobre todas las bases
de la configuración, en forma secuencial y con aislamiento de fallos: una base
que falla no interrumpe a las siguientes.

1. **Resuelve `gbak`** por base: `databases[].gbak_path` explícito; si es
   `null`, auto-detección por SO y versión de Firebird (rutas típicas de
   Windows/Linux y `PATH`). La
   [guía de compatibilidad Firebird](docs/firebird.md) explica la regla de
   familia (mismo mayor que la base), las rutas buscadas y qué hacer con
   varias instalaciones conviviendo.
2. **Ejecuta `gbak -b`** con timeout propio (`databases[].gbak_timeout_sec` o,
   si no, `local.gbak_timeout_sec`) y los parámetros de conexión `user`,
   `password` and `role` de cada base (nombres completos de switch: `-user`,
   `-password`, `-role`). La contraseña se enmascara en los logs. `gbak` no
   admite un switch de charset: el respaldo transportable no depende del
   charset de conexión, por eso `charset` se conserva en la configuración
   pero no se pasa al comando. Crea `local.work_dir` si no existe y guarda
   cada respaldo como `<nombre_bd>_<timestamp>.fbk` (timestamp
   `YYYYMMDD_HHMMSS`).
3. **Valida cada `.fbk`**: existe, no está vacío y es legible.
4. **Comprime cada `.fbk` (Etapa 3)**: utiliza `py7zr` para crear archivos
   `.fbk.7z`. El nivel de compresión y el cifrado AES-256 (si se provee
   `compression.password`) son configurables. Los archivos se nombran
   `<nombre_bd>_<timestamp>.fbk.7z`. El proceso mide la duración y el ratio de
   compresión, reportándolo en los logs.
5. **Transfiere cada `.fbk.7z` (Etapa 4)**: con paramiko, a todos los
   `servers` configurados (SFTP con reintentos, timeouts y verificación de
   tamaño por servidor). Solo se transfieren los artefactos con respaldo y
   compresión exitosos; una base cuenta como exitosa únicamente si las tres
   fases culminan bien. El resumen informa, por base y por servidor, la ruta
   remota, los bytes verificados, la duración y el estado (OK/FALLO).
6. **Envía el informe por correo (Etapa 5)**: se envía **siempre**, con el
   estado global, el detalle por base y por servidor y las últimas líneas del
   log (ver [Notificación por correo](#notificación-por-correo)). Un SMTP caído
   no rompe la corrida: el motivo queda en el log y en el resumen, y el exit
   code pasa de 0 a 1.
7. **Aplica la retención local (F8)**: elimina las copias gestionadas de
   `work_dir` más antiguas que `local.retention_days` (ver
   [Retención local](#retención-local)). Es una función secundaria: sus errores
   no alteran el exit code.

### Notificación por correo

Al terminar cada ejecución —éxito total, parcial o fallo, incluso si el lote no
llegó a ejecutarse— ODIN envía el informe a `notification.to` desde
`notification.from` usando `notification.smtp`:

```json
"notification": {
  "to": "control@example.com",
  "from": "odin-backups@example.com",
  "log_tail_lines": 50,
  "smtp": {
    "host": "smtp.example.com",
    "port": 587,
    "starttls": true,
    "username": "odin-backups@example.com",
    "password": "***"
  }
}
```

El timeout de conexión/operación SMTP es de 30 s (interno, no configurable).

**Contenido del informe** (texto plano): estado global `ÉXITO`/`PARCIAL`/`FALLO`
en el asunto y el cuerpo; detalle por base (ruta del `.fbk`, tamaño, duración,
tamaño comprimido y el error de la fase que falló); detalle por servidor destino
(`base → servidor: OK/FALLO` con motivo, bytes y duración); totales de la
corrida y las últimas líneas del log cuando `log_tail_lines > 0`.

**Seguridad:** el correo es solo texto y **nunca** adjunta el backup. El asunto
y el cuerpo pasan por el enmascarador de secretos además del enmascarado de los
logs, así que no incluyen contraseñas de bases, SFTP o SMTP, ni el contenido de
claves privadas.

**Si el SMTP cae**, `odin run` no crashea: registra el motivo en el log y en el
resumen ("Correo NO enviado: ...") y devuelve exit code 1 cuando el resto de la
corrida fue exitosa (ver [Exit codes](#exit-codes)).

### Retención local

`local.retention_days` habilita la limpieza de las copias locales, que corre
**después** del envío del correo:

```json
"local": {
  "work_dir": "/var/backups/odin",
  "retention_days": 7
}
```

| Valor | Comportamiento |
|---|---|
| `0` | Deshabilitada: no examina ni borra nada. |
| `N > 0` | Elimina `.fbk` y `.fbk.7z` de `work_dir` con `mtime` estrictamente anterior a `ahora − N días`. |

Solo se eliminan **archivos gestionados por ODIN**, es decir cuyo nombre cumple
la convención `<nombre_bd>_YYYYMMDD_HHMMSS.fbk` o `.fbk.7z`; nunca se tocan
`config.json`, `odin.log`, subdirectorios, enlaces simbólicos ni archivos
ajenos. Los artefactos recién creados por la corrida actual quedan protegidos
aunque el reloj del sistema esté desfasado (se exige `mtime >=` inicio de la
corrida). Un borrado fallido se registra por archivo y no interrumpe el resto.

La retención es una **función secundaria**: sus errores se reportan en el
resumen y en el log, pero no alteran el exit code de la corrida.

### Scheduler interno y modo servicio en primer plano

`odin service run` arranca el scheduler interno en primer plano: cada job del
bloque `scheduler` del JSON dispara el pipeline completo (respaldo, compresión,
transferencia, correo y retención) sobre su subconjunto de bases y envía su
propio informe por ciclo. `odin service status` consulta el estado persistido en
`local.work_dir/scheduler_state.json` y `odin service reload` pide la recarga de
la configuración sin reiniciar.

| Campo | Default | Descripción |
|---|---|---|
| `scheduler.enabled` | `false` | Habilita el scheduler interno; `odin service run` exige `true`. Con `false` solo queda disponible el modo one-shot `odin run`. |
| `scheduler.timezone` | `"UTC"` | Zona IANA del servicio; interpreta los `schedule` y los `next_fire_time` del estado. |
| `scheduler.jobs[].databases` | — (requerido) | Bases del job; cada ciclo ejecuta el pipeline solo con ese subconjunto (validado contra `databases`). |
| `scheduler.jobs[].schedule` | — (requerido) | Expresión cron de 5 campos (minuto, hora, día del mes, mes, día de la semana), validada al cargar la configuración. |
| `scheduler.jobs[].skip_if_running` | `true` | `true`: si alguna base del job está en ejecución por otro job, el ciclo se omite; `false`: corre solo con las bases libres. |
| `scheduler.jobs[].on_misfire` | `"run_once"` | `run_once`: los disparos vencidos se recuperan con una corrida; `skip`: se descartan. |

`odin validate` usa el mismo parser cron del scheduler y reporta en
`VERIFICACIONES` el próximo disparo de cada job en la `timezone` global (con
`WARNING` si la expresión nunca dispara), además de advertir si una base queda
fuera de todos los jobs.

#### Operación

```bash
uv run odin service run --config ruta/al/config.json     # scheduler en primer plano
uv run odin service status --config ruta/al/config.json  # estado actual
uv run odin service reload --config ruta/al/config.json  # recarga en caliente
```

- **`run`**: carga y valida la configuración, prepara el logging y el estado y
  arranca el scheduler bloqueante. Cada job dispara el pipeline completo sobre
  sus bases y cada ciclo envía su informe (y corre su retención). `SIGINT`
  (`Ctrl+C`) o `SIGTERM` paran limpio —shutdown del scheduler y estado final—
  con exit 0; configuración inválida o `scheduler.enabled: false` → 2; error
  interno → 1.
- **`status`**: lee `local.work_dir/scheduler_state.json` y presenta si el
  servicio está en ejecución (o si el estado quedó obsoleto de un proceso
  muerto), la configuración, cada job con su próximo disparo y último ciclo, la
  salud y los errores recientes.
- **`reload`**: pide la recarga sin reiniciar (ver
  [Recarga en caliente](#recarga-en-caliente)); devuelve 0 cuando la solicitud
  se entrega, 1 si no hay servicio en ejecución y 2 si la configuración no
  puede cargarse.

#### Archivo de estado (`scheduler_state.json`)

El servicio persiste su estado en `local.work_dir/scheduler_state.json` con
escritura atómica (temporal + reemplazo), de modo que `status` siempre lee un
archivo íntegro:

| Campo | Contenido |
|---|---|
| `version` | Esquema del archivo (hoy `1`). Una versión desconocida se informa como ilegible, nunca rompe. |
| `pid`, `config_path`, `started_at`, `updated_at` | Proceso que escribió el estado y marcas de la corrida; si el `pid` ya no vive, `status` lo reporta como **detenido** (estado obsoleto). |
| `jobs[]` | Por job: `job_id`, `schedule`, `databases`, `next_fire_time` y `last_cycle` (`status`, bases, `finished_at`, duración, si el correo salió y el error enmascarado). |
| `recent_errors` | Ventana acotada (10) de los últimos fallos, ya enmascarados. |

El estado se actualiza al arrancar, en cada ciclo (también en las omisiones por
solapamiento o misfire) y al detenerse. **Nunca contiene secretos**: los
mensajes pasan por el enmascarador antes de persistirse. El archivo es
consultable y de formato estable, pero no está pensado para editarse a mano.

#### Recarga en caliente

`odin service reload` no reinicia el scheduler:

- **POSIX**: envía `SIGUSR1` al `pid` del estado; el servicio lo captura como
  una bandera thread-safe (el manejador no toca el scheduler).
- **Windows o plataformas sin señal**: crea el archivo de control
  `local.work_dir/scheduler_reload.request`, que el servicio consume.

En ambos caminos el job interno `reload-watcher` (cada 2 s) procesa la
solicitud: carga y valida de nuevo la configuración editada; si es válida
reemplaza la vigente, actualiza la timezone, re-registra los jobs (altas, bajas
y cambios de horario) y recalcula los próximos disparos **sin detener** el
servicio, refrescando además el logging y la máscara de secretos. Si la
configuración es inválida, conserva la vigente y registra el motivo en el log y
en `recent_errors`. Consumir el archivo de control es idempotente.

#### Solapamiento y misfire

- **Solapamiento**: el servicio mantiene en proceso el registro de las bases en
  ejecución. Con `skip_if_running: true` un ciclo se omite si alguna de sus
  bases está siendo respaldada por otro job; con `false` el ciclo corre solo con
  las bases libres. La misma base nunca se respalda dos veces a la vez, y toda
  omisión queda en el log y en el estado con su motivo.
- **Misfire**: los disparos vencidos se colapsan en uno (`coalesce`). Con
  `on_misfire: run_once` la corrida recuperada se ejecuta aunque llegue tarde;
  con `skip` se descarta (tolerancia de 1 s) y queda registrada como omisión.

#### Relación con `odin run` (one-shot)

`odin run` ejecuta el pipeline **una vez** sobre todas las bases y termina (ver
[Ejecución de respaldos](#ejecución-de-respaldos-odin-run)); `odin service run`
es ese mismo pipeline, disparado por cada job según su cron, acotado a las bases
del job y con su propio correo y retención por ciclo, más el estado persistido
para operar sin intervención. Las dos vías comparten fases, enmascarado de
secretos y contrato de resultados por base.

#### Demo manual con cadencia real de 1–2 minutos

1. Configure un job que dispare cada minuto, manteniendo `scheduler.enabled:
   true` (el resto del JSON es el habitual):

   ```json
   "scheduler": {
     "enabled": true,
     "timezone": "UTC",
     "jobs": [
       {
         "databases": ["erp_principal"],
         "schedule": "* * * * *",
         "skip_if_running": true,
         "on_misfire": "run_once"
       }
     ]
   }
   ```

2. Arranque el servicio en primer plano:

   ```
   uv run odin service run --config /ruta/a/config.json
   ```

3. Verifique un ciclo por minuto en la consola y en
   `local.work_dir/logs/odin.log`, y **un correo por ciclo** en la casilla
   `notification.to` (asunto `[ODIN] ÉXITO/PARCIAL/FALLO`).
4. En otra terminal, con el servicio corriendo:

   ```
   uv run odin service status --config /ruta/a/config.json
   ```

   Debe informar el proceso en ejecución, el próximo disparo y el último ciclo.

5. Detenga el servicio con `Ctrl+C` (SIGINT) o `SIGTERM` (`kill <pid>`): la
   salida es 0, el scheduler se apaga y el estado final queda persistido.

La variante automatizada de esta demo —dos ciclos con cron real `* * * * *`,
catcher SMTP in-process y fases dobles— está en
`tests/test_scheduler_foreground.py` y se ejecuta solo con:

```
ODIN_FOREGROUND_DEMO=1 uv run pytest tests/test_scheduler_foreground.py -q
```

Por defecto se salta para no sumar ~2 minutos a la suite; los casos que sí
corren por defecto (ciclos acortados en primer plano y parada limpia con
SIGTERM) tardan segundos.

### Modo servicio residente (Windows Service / daemon Linux)

`odin service install` empaqueta el scheduler interno como **servicio del SO**:
Windows Service (SCM) en Windows Server y unit **systemd** en Linux LTS. Es la
vía para correr desatendido sin `cron` ni Task Scheduler; el pipeline, el
estado y la recarga en caliente son los mismos del
[scheduler interno](#scheduler-interno-y-modo-servicio-en-primer-plano).

```bash
# instala (exige --config/ODIN_CONFIG) y arranca
sudo odin service install --config /etc/odin/config.json   # Linux (root)
odin service install --config C:\odin\config.json          # Windows (consola elevada)
odin service start
odin service status        # gestor del SO + estado del scheduler
odin service reload        # recarga la config sin reiniciar
odin service stop
odin service uninstall     # idempotente
```

| Aspecto | Linux (systemd) | Windows Server (SCM) |
|---|---|---|
| Gestor | unit `odin.service` (`deploy/odin.service` de referencia) | servicio `odin` sobre el host de pywin32 |
| Permisos de instalación | root (o escritura en `/etc/systemd/system`); sin permisos imprime la guía | consola elevada (Administrador) |
| Arranque automático | `systemctl enable` (`WantedBy=multi-user.target`) | `SERVICE_AUTO_START` |
| Reinicio ante caída | `Restart=always` + `RestartSec=5` | failure actions del SCM (reinicio a los ~5 s, reset 24 h) |
| Recarga en caliente | `odin service reload` → `SIGUSR1` | `odin service reload` → archivo de control |
| Estado | `systemctl show` + `scheduler_state.json` | `QueryServiceStatus` + `scheduler_state.json` |
| Log | `<resolved_log_dir>/odin.log`, solo archivo y rotado 5 MiB × 5 | ídem |

La instalación **no arranca** el servicio (el arranque automático aplica en el
próximo boot): después de `install`, usá `odin service start`. La guía
operativa completa —cuenta del servicio y accesos, permisos del JSON, recarga,
diagnóstico de fallos comunes, desinstalación limpia y el runbook de
verificación en Windows Server real— está en
[`docs/service.md`](docs/service.md).

### Logging

ODIN escribe consola y archivo en las ejecuciones one-shot (`validate`, `run`);
el modo residente (`odin service run` y el servicio del SO) escribe **solo
archivo**, para no depender de una terminal.

| Aspecto | Detalle |
|---|---|
| Archivo | `<resolved_log_dir>/odin.log` = `local.log_dir` o, si es `null`, `<work_dir>/logs/odin.log`. |
| Rotación | 5 MiB por archivo con 5 backups (`odin.log.1` … `odin.log.5`). |
| Nivel | `local.log_level`: `DEBUG`, `INFO`, `WARNING`, `ERROR` o `CRITICAL` (default `INFO`). |
| Enmascarado | Contraseñas, passphrases y contenido de claves privadas se sustituyen por `***` antes de escribir a consola, archivo, correo y estado. |
| Cola del informe | `notification.log_tail_lines` (default `50`) anexa al correo las últimas líneas del log, ya enmascaradas; `0` la desactiva. |

### Exit codes

| Código | Significado |
|---|---|
| 0 | `validate`: configuración válida (puede tener advertencias) · `run`: todas las bases completaron respaldo, compresión y transferencia **y** el correo se envió · `service run`: parada limpia por SIGINT/SIGTERM · `service status`: estado leído · `service reload`: solicitud entregada · `service install\|uninstall\|start\|stop`: operación exitosa |
| 1 | Error interno inesperado · `run`: el correo no se pudo enviar en una corrida por lo demás exitosa (una ejecución sin informe incumple la trazabilidad) · `service run`: fallo inesperado · `service reload`: no hay servicio en ejecución · `service install\|uninstall\|start\|stop`: fallo del gestor (incluida plataforma no soportada o servicio no instalado) |
| 2 | Error de configuración, de uso de la CLI, o advertencias con `--strict`; `service run`: `scheduler.enabled: false` o configuración inválida; `service install`: falta la fuente de configuración o tiene errores; `service reload`: configuración ilegible |
| 3 | `run`: fallo parcial (algunas bases completaron todas las fases y otras fallaron en alguna); el desenlace del correo no cambia este código |
| 4 | `run`: fallo total (ninguna base completó todas las fases) o lote no ejecutado/vacío; tiene precedencia sobre el correo |

Con `--strict` las advertencias también devuelven 2: útil como gate previo al
despliegue o en CI.

## Troubleshooting

| Problema | Causa probable | Solución |
|---|---|---|
| `gbak` no encontrado o error de versión/formato al respaldar | La auto-detección no cubre la ruta instalada o el `gbak` es de una **familia distinta** a la base | Fijar `databases[].gbak_path` al binario de la misma versión mayor (`C:\Firebird_2_5\bin\gbak.exe`, `/opt/firebird/bin/gbak`, …); ver [`docs/firebird.md`](docs/firebird.md) |
| Login Firebird rechazado (`Your user name and password are not defined…`) | Usuario/clave incorrectos; en Firebird 2.5 la contraseña solo distingue los primeros **8 bytes** | Verificar las credenciales de `databases[]`; en 2.5 usar una clave de ≤ 8 bytes significativos y recrearla como SYSDBA |
| `odin validate` advierte permisos `644`/`666` del JSON | El archivo con credenciales es legible por grupo/otros | `chmod 600 config.json` y dueño correcto (Linux) o `icacls` restrictivo (Windows); ver [`docs/security.md`](docs/security.md) |
| El correo no llega o el resumen dice `Correo NO enviado` | SMTP bloqueado por firewall, host/puerto incorrectos o `starttls` no soportado por el relay | Probar conectividad al puerto SMTP, ajustar `notification.smtp.host/port/starttls/ssl` y revisar `odin.log`; un SMTP caído devuelve exit 1 |
| SFTP falla con `Host key … does not match` o `not found in known_hosts` | `host_key_policy: strict` y la clave del servidor es desconocida o cambió | Aprovisionar `known_hosts` para el destino o usar `accept-new` en el primer contacto; verificar el cambio de clave en el servidor |
| `odin validate` marca el schedule de un job o una timezone inválida | Expresión cron mal formada (5 campos) o zona IANA inexistente | Corregir `scheduler.jobs[].schedule` o `scheduler.timezone`; `validate` muestra el próximo disparo de cada job |
| `odin service install` no instala y devuelve la guía | Falta `root` (Linux) o la consola no está elevada (Windows) | Ejecutar como root/Administrador o completar la instalación con la guía impresa; ver [`docs/service.md`](docs/service.md) |
| El servicio arranca y se detiene, o los ciclos fallan con `Permission denied` | La cuenta del servicio no lee el JSON, no escribe `work_dir`/logs o no ejecuta `gbak` | Ajustar dueño/permisos/ACL al usuario que corre el servicio; probar antes con `odin run --config …` con esa cuenta; ver [`docs/service.md`](docs/service.md) |
| `odin service run` devuelve 2 al arrancar | `scheduler.enabled: false` o configuración inválida | Poner `scheduler.enabled: true`, definir al menos un job y correr `odin validate` |
| La compresión falla con `No space left on device` | Disco lleno en `local.work_dir` | Liberar espacio o bajar `local.retention_days`; `validate` compara con `local.min_free_mb` |
| `odin` en Windows falla al importar con `SyntaxError: multiple exception types must be parenthesized` o las dependencias mueren con `TypeError: bad argument type for built-in operation` | uv descargó la build **alpha** de Python 3.14 (`cpython-3.14.0a6`, la única 3.14 de su registro gestionado para Windows): es previa a la sintaxis PEP 758 y su ABI rompe los wheels `cp314` finales de `cffi`/`pycryptodomex` | Instalar Python 3.14 **final** (p. ej. `winget install Python.Python.3.14` o el instalador de python.org) y crear el entorno con `uv tool install --python <ruta>\python.exe …`; verificar con `python --version` que la versión no tenga sufijo `a` |

## Seguridad

ODIN guarda las credenciales (Firebird, SFTP y SMTP) en el **JSON legible**
deliberadamente, para que la configuración sea auditable y OS-agnóstica, y
concentra las mitigaciones en el entorno:

- **Permisos del JSON**: `600` (o ACL equivalente) solo para el dueño o la
  cuenta del servicio; `odin validate` advierte si hay acceso de grupo/otros.
- **SFTP con clave privada** en lugar de contraseña (passphrase obligatoria) y
  política de host key `strict` por defecto.
- **Enmascarado** de contraseñas, passphrases y contenido de claves en logs,
  correo y `scheduler_state.json`.
- **TLS/SSL en SMTP**: `starttls: true` por defecto o `smtp.ssl: true`; el
  canal en plano queda advertido por `validate`.
- **Mínimo privilegio** para la cuenta del servicio: lectura del JSON,
  escritura solo en `work_dir`/logs, ejecución de `gbak` y salida de red a
  Firebird/SFTP/SMTP.

La guía completa —modelo de amenazas, permisos por plataforma (`chmod`/
`icacls`), claves SSH, políticas de host key, límites del enmascarado, rotación
de credenciales y checklist de despliegue— está en
[`docs/security.md`](docs/security.md).

## Integración continua

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) corre el mismo gate en
las dos plataformas objetivo, con jobs `linux` (`ubuntu-latest`) y `windows`
(`windows-latest`):

1. checkout + `astral-sh/setup-uv` con caché;
2. `uv sync --locked` y `uv run python scripts/verify.py` como gate único
   (`pytest` + `ruff` + `mypy` + `odin validate` de los dos ejemplos);
3. `uv build` y el wheel publicado como artefacto de la corrida.

El job `windows` suma el **ciclo de vida real del servicio** contra el SCM
(los runners son administradores): `odin service install|start|status|stop|
uninstall` con una configuración de scheduler y fases externas dobles
(`gbak` *stub* y SMTP local, sin red externa), en el escenario gated
`ODIN_WINDOWS_SERVICE_SMOKE=1` de
`tests/test_service_windows_integration.py`. Fuera de Windows o sin la
variable, ese test se salta: la suite local no lo necesita.

El workflow **se activa al publicar el repositorio** (`push`/`pull_request`;
hoy el repositorio no tiene remoto y no se ha ejecutado todavía), usa
`permissions: contents: read` y no consume secretos. Hasta entonces, el gate
local equivalente es `scripts/verify.py`; la persona que publique el repo
debería confirmar la primera corrida del job `windows` (evidencia pendiente en
[`docs/service.md` §9](docs/service.md#9-evidencia-de-verificación-item-074)).

## Compatibilidad de dependencias (Python 3.14)

Se ha verificado la compatibilidad de las dependencias principales con Python 3.14. La resolución de paquetes mediante `uv` garantiza que los wheels adecuados para Windows y Linux se instalan correctamente.

### Matriz de compatibilidad

| Dependencia | Versión Resuelta | `Requires-Python` | Evidencia de soporte 3.14 |
|---|---|---|---|
| `paramiko` | 5.0.0 | `>=3.9` | Linux: `import paramiko` OK. |
| `py7zr` | 1.1.3 | `>=3.10` | Linux: `import py7zr` OK. |
| `apscheduler` | 3.11.3 | `>=3.8` | Linux: `import apscheduler` OK. |
| `pywin32` | 312 | `>=3.11` | Windows (estático): `uv.lock` contiene wheels `cp314` para `win32/amd64/arm64`. |
| `tzdata` | 2026.3 | — (wheel universal `py2.py3`) | Datos IANA para `zoneinfo`; Item 072: sin datos del SO (contenedor Linux mínimo) `odin validate` fallaba, y Windows tampoco trae tzdata del SO. |

**Decisión de versionado:**
- Se ha subido el floor de `pywin32` a `>=311` en `pyproject.toml` para reflejar el soporte real de wheels `cp314` en Python 3.14.
- Se agregó `tzdata` como dependencia directa (Item 072): `zoneinfo` la necesita para `scheduler.timezone`/cron cuando el SO no trae la base IANA (contenedores Linux mínimos y Windows); con datos del SO actúa solo como fallback.
- Se mantiene `requires-python >= 3.14`.
- **Windows: usar una 3.14 final, no la alpha gestionada de uv.** El registro
  gestionado de uv solo ofrece `cpython-3.14.0a6` (alpha) para Windows: es
  previa a la sintaxis PEP 758 y su ABI no es compatible con los wheels
  `cp314` finales de las dependencias (`cffi`/`pycryptodomex` mueren con
  `TypeError: bad argument type for built-in operation`), así que aunque el
  entorno se instale, `odin` no corre. Instalar Python 3.14 final (`winget
  install Python.Python.3.14` o el instalador de python.org) y crear el
  entorno con `uv tool install --python <ruta>\python.exe …` (o `uv sync
  --python <ruta>\python.exe`); verificar con `python --version` que no tenga
  sufijo `a`.
- La confirmación runtime en Windows Server queda delegada al job `windows`
  de la CI (Items 073/074; ver [`docs/service.md` §9](docs/service.md#9-evidencia-de-verificación-item-074)).

*Nota: El test `tests/test_deps_compat.py` actúa como un invariante para prevenir regresiones en la compatibilidad.*

El ciclo de desarrollo completo se verifica con el gate único
[`scripts/verify.py`](#modo-desarrollo); `uv run odin --version`
está incluido en el quickstart.

## Licencia

MIT. La declaración de licencia está en [`pyproject.toml`](pyproject.toml)
(`license = "MIT"`). El historial de cambios de cada versión está en
[`CHANGELOG.md`](CHANGELOG.md).

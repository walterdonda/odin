# ODIN

Respaldo externo de bases de datos: Firebird (2.5 → 6) con `gbak` y
PostgreSQL (18+) con `pg_dump`, compresión 7z, transferencia SFTP (paramiko) y
notificación por correo, operable como servicio residente en Windows Server y
Linux LTS.

| Motor | `type` | Binario | Artefacto | Guía |
|---|---|---|---|---|
| Firebird 2.5 → 6 | `"firebird"` | `gbak` (misma familia que la base) | `.fbk` → `.fbk.7z` | [`docs/firebird.md`](docs/firebird.md) |
| PostgreSQL 18.0+ | `"postgresql"` | `pg_dump` 18+ | `.dump` → `.dump.7z` | [`docs/postgresql.md`](docs/postgresql.md) |

El campo `databases[].type` elige el motor de cada base; el modelo multi-motor
está en [`docs/engines.md`](docs/engines.md) y la referencia completa de
campos, en [`docs/configuration.md`](docs/configuration.md).

## Requisitos

| Requisito | Detalle |
|---|---|
| Sistema operativo | Windows Server 2016+ o Linux LTS. Misma base de código; la CI corre en `ubuntu-latest` y `windows-latest`. |
| Python | ≥ 3.14 (`requires-python = ">=3.14"`), gestionado con [uv](https://docs.astral.sh/uv/). `tzdata` viaja como dependencia para `scheduler.timezone` donde el SO no trae la base IANA. |
| Firebird | Servidor accesible y `gbak` de la **misma versión mayor** que cada base (matriz 2.5 → 6 en [`docs/firebird.md`](docs/firebird.md)). |
| PostgreSQL | Solo la serie **18.0+**, con `pg_dump` 18 (respalda servidores 9.2 → 18.x); contrato y restauración en [`docs/postgresql.md`](docs/postgresql.md). |
| Conectividad | Firebird 3050/TCP y PostgreSQL 5432/TCP (o los puertos configurados), SFTP 22/TCP (o el configurado) y el servidor SMTP. |
| Permisos | Escritura en `local.work_dir` y en el directorio de logs. `root` (Linux) o consola elevada (Windows) solo para instalar el servicio del SO. |

> **Windows**: usar una Python 3.14 **final**, no la alpha que gestiona uv
> (`3.14.0a6`). Detalle y matriz de compatibilidad de dependencias en
> [`docs/dependencies.md`](docs/dependencies.md).

## Instalación

Con `uv` instalado, ODIN se instala como **herramienta aislada** (sin el
entorno de desarrollo ni el repositorio):

```bash
uv build                                # genera dist/odin-<versión>-py3-none-any.whl
uv tool install dist/odin-*.whl         # instala el wheel
odin --version                          # → odin 1.1.0
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

> **Docker**: el gate completo requiere el daemon de Docker corriendo — los
> tests de integración levantan contenedores reales (`firebird`, `postgres:18`)
> y el test de empaquetado instala el wheel en un contenedor limpio. Con el
> daemon caído ese último test falla (no se salta); sin Docker disponible,
> usá `--quick` para omitir los tests marcados `integration`.

## Configuración

ODIN se configura con un único **JSON legible y OS-agnóstico**: las rutas
aceptan `/` o `\`, `~` se expande al usuario que ejecuta y las rutas relativas
se resuelven contra el directorio del propio JSON. La configuración contiene
credenciales en texto legible: restringí sus permisos y no la versiones (ver
[Seguridad](#seguridad) y [`docs/security.md`](docs/security.md)).

Bloques del JSON:

- **`databases[]`** — una entrada por base; el campo **`type`**
  (`"firebird"` | `"postgresql"`, obligatorio) elige el motor y qué campos
  aplican. En Firebird, `connection` se pasa a `gbak` tal cual
  (`host/puerto:ruta` o alias) y `gbak_path: null` delega la auto-detección
  por SO y versión. En PostgreSQL, `host`, `port` (default `5432`) y `dbname`
  apuntan al servidor y `pg_dump_path: null` delega la auto-detección
  (majors ≥ 18, gana el mayor). Resumen del modelo multi-motor:
  [`docs/engines.md`](docs/engines.md).
- **`compression`** — nivel de 7z (`0` = *store*, `1–9` = LZMA2; default `7`)
  y `password` opcional para cifrado AES-256 del artefacto `.7z`.
- **`servers[]`** — destinos SFTP con reintentos, timeouts y política de host
  keys. `auth.method` es `password` o `key` (`private_key` **RSA** con
  `passphrase` opcional, `~` permitido).
- **`notification`** — casilla destino/remitente y transporte SMTP
  (`starttls` por defecto; `smtp.ssl` para SSL implícito).
- **`local`** — directorios de trabajo y logs, nivel de logging, retención,
  umbral de espacio libre y timeouts por defecto (`gbak_timeout_sec` y
  `pg_dump_timeout_sec`).
- **`scheduler`** — jobs cron por subconjunto de bases (semántica en
  [`docs/scheduler.md`](docs/scheduler.md)).

La referencia completa —tipo, obligatoriedad, default, rangos, reglas cruzadas
y límites de la versión— está en
[`docs/configuration.md`](docs/configuration.md). Los ejemplos listos para
copiar están en [`examples/`](examples/) (uno por plataforma, con secretos
placeholder `***`; ver [`examples/README.md`](examples/README.md)).

```bash
uv run odin validate --config ruta/al/config.json    # o vía ODIN_CONFIG
uv run odin validate --config ruta/al/config.json --strict
```

`odin validate` comprueba la **estructura** y **tipos** del JSON (campos
requeridos, rangos, enums, campos desconocidos con sugerencia de typo), la
**semántica** (nombres únicos, jobs que referencian bases existentes,
coherencia `auth.method`/credenciales, campos por motor según `type`), el
**entorno local** (rutas, binarios `gbak_path`/`pg_dump_path` explícitos,
permisos del JSON y de la clave privada, espacio libre) y la **coherencia
operativa** (scheduler sin jobs, bases sin job, SMTP sin cifrar,
`host_key_policy: insecure`, retención desactivada). Es de solo lectura y **sin
red**: un destino caído no invalida la configuración. La salida agrupa
`ERRORES`, `ADVERTENCIAS` y `VERIFICACIONES` con la ruta del campo implicado.

## Comandos

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
| `odin --version` | Versión instalada (hoy `odin 1.1.0`). |
| `odin --help` / `odin <cmd> --help` | Ayuda y subcomandos. |

```bash
uv run odin validate --config examples/config.linux.json
uv run odin run --config /etc/odin/config.json
uv run odin service run --config /etc/odin/config.json
uv run odin --version
```

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

## Operación

`odin run` ejecuta el ciclo one-shot completo sobre todas las bases, en forma
secuencial y con aislamiento de fallos:

1. **Resuelve el binario del motor** por base: `databases[].gbak_path` o
   `pg_dump_path` explícitos; si es `null`, auto-detección por SO y versión.
2. **Ejecuta el respaldo lógico del motor**: `gbak -b` con los switches de
   conexión (`-user`, `-password`, `-role`; el `charset` se conserva pero no
   se pasa) o `pg_dump --format=custom --no-password --no-privileges --file
   <destino>` con `--host`, `--port`, `--username`, `--dbname` y la contraseña
   vía `PGPASSWORD` (nunca en la línea de comandos ni en los logs). El timeout
   es el de la base o el default de `local`. Guarda cada respaldo como
   `<nombre_bd>_<timestamp>.fbk` (Firebird) o `.dump` (PostgreSQL).
3. **Valida cada artefacto**: existe, no está vacío y es legible.
4. **Comprime** con `py7zr` a `.fbk.7z`/`.dump.7z` (nivel configurable,
   cifrado AES-256 opcional); mide duración y ratio.
5. **Transfiere** cada `.7z` por SFTP a todos los `servers` configurados
   (reintentos, timeouts, verificación de tamaño por servidor). Una base
   cuenta como exitosa solo si las tres fases culminan bien.
6. **Envía el informe por correo** siempre —estado global, detalle por base y
   por servidor, cola del log enmascarada—; un SMTP caído no rompe la corrida
   (exit 1 si el resto fue exitoso).
7. **Aplica la retención local**: elimina los artefactos gestionados
   (`.fbk`/`.dump` y `.7z`) de `work_dir` más antiguos que
   `local.retention_days`; es función secundaria (no altera el exit code).

Otros temas de operación:

- **Scheduler interno**: `odin service run` dispara el pipeline por job (cron,
  subconjunto de bases, timezone IANA), persiste
  `local.work_dir/scheduler_state.json` y soporta recarga en caliente. Detalle
  en [`docs/scheduler.md`](docs/scheduler.md).
- **Servicio residente**: `odin service install` empaqueta el scheduler como
  Windows Service (SCM) o unit systemd, con arranque automático y reinicio
  ante caída. Guía completa en [`docs/service.md`](docs/service.md).
- **Logging**: consola y archivo en one-shot; solo archivo en modo residente.
  `<resolved_log_dir>/odin.log` (`local.log_dir` o `<work_dir>/logs`),
  rotación 5 MiB × 5, nivel `local.log_level`, secretos enmascarados con
  `***`.
- **Informe por correo**: texto plano, nunca adjunta el backup; asunto y
  cuerpo pasan por el enmascarador de secretos.

## Seguridad

ODIN guarda las credenciales (bases, SFTP y SMTP) en el **JSON legible**
deliberadamente, para que la configuración sea auditable y OS-agnóstica, y
concentra las mitigaciones en el entorno:

- **Permisos del JSON**: `600` (o ACL equivalente) solo para el dueño o la
  cuenta del servicio; `odin validate` advierte si hay acceso de grupo/otros.
- **SFTP con clave privada RSA** (passphrase recomendada, no obligatoria) en
  lugar de contraseña, y política de host key `strict` por defecto.
- **Enmascarado** de contraseñas, passphrases y contenido de claves en logs,
  correo y `scheduler_state.json`.
- **TLS/SSL en SMTP**: `starttls: true` por defecto o `smtp.ssl: true`; el
  canal en plano queda advertido por `validate`.
- **Mínimo privilegio** para la cuenta del servicio: lectura del JSON,
  escritura solo en `work_dir`/logs, ejecución de `gbak`/`pg_dump` y salida de
  red a las bases/SFTP/SMTP.

La guía completa —modelo de amenazas, permisos por plataforma (`chmod`/
`icacls`), claves SSH, políticas de host key, límites del enmascarado, rotación
de credenciales y checklist de despliegue— está en
[`docs/security.md`](docs/security.md).

## Documentación

| Doc | Contenido |
|---|---|
| [`docs/engines.md`](docs/engines.md) | El modelo multi-motor: `type`, dispatch, finders, artefactos, protocolo `Engine` y cómo agregar un motor. |
| [`docs/configuration.md`](docs/configuration.md) | Referencia completa de todos los campos del JSON (tipo, default, rangos, reglas cruzadas, límites). |
| [`docs/firebird.md`](docs/firebird.md) | Matriz de compatibilidad 2.5 → 6, regla de familia de `gbak` y resolución de `gbak_path`. |
| [`docs/postgresql.md`](docs/postgresql.md) | Motor PostgreSQL 18+: comando `pg_dump`, `PGPASSWORD`, finder y notas de restauración. |
| [`docs/security.md`](docs/security.md) | Modelo de amenazas, permisos, claves SSH, host keys, enmascarado y rotación. |
| [`docs/service.md`](docs/service.md) | Servicio residente (systemd/SCM), cuentas, diagnóstico y runbook de Windows Server. |
| [`docs/scheduler.md`](docs/scheduler.md) | Scheduler interno: estado, recarga en caliente, solapamiento, misfire y demo. |
| [`docs/dependencies.md`](docs/dependencies.md) | Compatibilidad de dependencias con Python 3.14 (incluida la nota de la alpha en Windows). |
| [`docs/release-1.0.md`](docs/release-1.0.md) | Documento histórico de la release 1.0.0. |
| [`examples/README.md`](examples/README.md) | Cómo adaptar las configuraciones de ejemplo. |

## Integración continua

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) corre el mismo gate en
las plataformas objetivo, con tres jobs:

1. **`linux`** (`ubuntu-latest`): checkout + `astral-sh/setup-uv` con caché,
   `uv sync --locked`, `scripts/verify.py` como gate único (`pytest` + `ruff`
   + `mypy` + `odin validate` de los dos ejemplos), `uv build` y el wheel como
   artefacto.
2. **`postgresql`** (`ubuntu-latest`): integración end-to-end contra un
   servicio `postgres:18` real (`tests/test_backup_integration_postgres.py`).
3. **`windows`** (`windows-latest`): el gate único más el **ciclo de vida real
   del servicio** contra el SCM (los runners son administradores):
   `odin service install|start|status|stop|uninstall` con fases externas
   dobles (`gbak` *stub* y SMTP local, sin red externa), en el escenario
   gated `ODIN_WINDOWS_SERVICE_SMOKE=1` de
   `tests/test_service_windows_integration.py`.

El workflow se activa con `push`/`pull_request`, usa
`permissions: contents: read` y no consume secretos. El gate local equivalente
es `scripts/verify.py`; la evidencia de la primera corrida real del job
`windows` queda registrada en
[`docs/service.md` §9](docs/service.md#9-evidencia-de-verificación-item-074).

## Troubleshooting

| Problema | Causa probable | Solución |
|---|---|---|
| `gbak` no encontrado o error de versión/formato al respaldar | La auto-detección no cubre la ruta instalada o el `gbak` es de una **familia distinta** a la base | Fijar `databases[].gbak_path` al binario de la misma versión mayor; ver [`docs/firebird.md`](docs/firebird.md) |
| `pg_dump` no encontrado al respaldar una base PostgreSQL | La auto-detección no cubre la ruta instalada (solo cuentan majors ≥ 18, y gana el mayor) | Instalar PostgreSQL 18+ o fijar `databases[].pg_dump_path` al binario; ver [`docs/postgresql.md`](docs/postgresql.md) |
| Login Firebird rechazado (`Your user name and password are not defined…`) | Usuario/clave incorrectos; en Firebird 2.5 la contraseña solo distingue los primeros **8 bytes** | Verificar las credenciales de `databases[]`; en 2.5 usar una clave de ≤ 8 bytes significativos y recrearla como SYSDBA |
| Login PostgreSQL rechazado (`password authentication failed…`) | Credenciales incorrectas o `pg_hba.conf` que no admite el usuario/origen | Verificar `databases[].user`/`password` y la entrada `pg_hba.conf`; ver [`docs/postgresql.md`](docs/postgresql.md) |
| `odin validate` advierte permisos `644`/`666` del JSON | El archivo con credenciales es legible por grupo/otros | `chmod 600 config.json` y dueño correcto (Linux) o `icacls` restrictivo (Windows); ver [`docs/security.md`](docs/security.md) |
| El correo no llega o el resumen dice `Correo NO enviado` | SMTP bloqueado por firewall, host/puerto incorrectos o `starttls` no soportado por el relay | Probar conectividad al puerto SMTP, ajustar `notification.smtp.host/port/starttls/ssl` y revisar `odin.log`; un SMTP caído devuelve exit 1 |
| SFTP falla con `Host key … does not match` o `not found in known_hosts` | `host_key_policy: strict` y la clave del servidor es desconocida o cambió | Aprovisionar `known_hosts` para el destino o usar `accept-new` en el primer contacto; verificar el cambio de clave en el servidor |
| `odin validate` marca el schedule de un job o una timezone inválida | Expresión cron mal formada (5 campos) o zona IANA inexistente | Corregir `scheduler.jobs[].schedule` o `scheduler.timezone`; `validate` muestra el próximo disparo de cada job |
| `odin service install` no instala y devuelve la guía | Falta `root` (Linux) o la consola no está elevada (Windows) | Ejecutar como root/Administrador o completar la instalación con la guía impresa; ver [`docs/service.md`](docs/service.md) |
| El servicio arranca y se detiene, o los ciclos fallan con `Permission denied` | La cuenta del servicio no lee el JSON, no escribe `work_dir`/logs o no ejecuta `gbak`/`pg_dump` | Ajustar dueño/permisos/ACL al usuario que corre el servicio; probar antes con `odin run --config …` con esa cuenta; ver [`docs/service.md`](docs/service.md) |
| `odin service run` devuelve 2 al arrancar | `scheduler.enabled: false` o configuración inválida | Poner `scheduler.enabled: true`, definir al menos un job y correr `odin validate` |
| La compresión falla con `No space left on device` | Disco lleno en `local.work_dir` | Liberar espacio o bajar `local.retention_days`; `validate` compara con `local.min_free_mb` |
| `odin` en Windows falla al importar o las dependencias mueren con `TypeError` | uv descargó la build **alpha** de Python 3.14 (`3.14.0a6`) | Instalar Python 3.14 **final** y crear el entorno con `uv tool install --python <ruta>\python.exe …`; ver [`docs/dependencies.md`](docs/dependencies.md) |

## Changelog y licencia

El historial de cambios de cada versión está en [`CHANGELOG.md`](CHANGELOG.md)
(formato Keep a Changelog; el documento histórico de la 1.0.0, en
[`docs/release-1.0.md`](docs/release-1.0.md)).

MIT. La declaración de licencia está en [`pyproject.toml`](pyproject.toml)
(`license = "MIT"`).

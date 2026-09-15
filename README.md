# ODIN

Respaldo externo de bases de datos Firebird (2.5 → 6): backup con `gbak`,
compresión 7z, transferencia SFTP (paramiko) y notificación por correo.

> Proyecto en desarrollo bajo el flujo AIDE (`docs/aide/`).

## Requisitos

- Python ≥ 3.14 (gestionado con [uv](https://docs.astral.sh/uv/))
- uv
- `gbak` de la **misma versión mayor** que cada base Firebird (cliente o
  servidor instalado); la [guía de compatibilidad Firebird](docs/firebird.md)
  cubre la matriz 2.5 → 6 y la resolución de `gbak_path` por plataforma

## Compatibilidad de dependencias (Python 3.14)

Se ha verificado la compatibilidad de las dependencias principales con Python 3.14. La resolución de paquetes mediante `uv` garantiza que los wheels adecuados para Windows y Linux se instalan correctamente.

### Matriz de compatibilidad

| Dependencia | Versión Resuelta | `Requires-Python` | Evidencia de soporte 3.14 |
|---|---|---|---|
| `paramiko` | 5.0.0 | `>=3.9` | Linux: `import paramiko` OK. |
| `py7zr` | 1.1.3 | `>=3.10` | Linux: `import py7zr` OK. |
| `apscheduler` | 3.11.3 | `>=3.8` | Linux: `import apscheduler` OK. |
| `pywin32` | 312 | `>=3.11` | Windows (estático): `uv.lock` contiene wheels `cp314` para `win32/amd64/arm64`. |

**Decisión de versionado:**
- Se ha subido el floor de `pywin32` a `>=311` en `pyproject.toml` para reflejar el soporte real de wheels `cp314` en Python 3.14.
- Se mantiene `requires-python >= 3.14`.
- La confirmación runtime en Windows Server se realizará en el **Item 009**.

*Nota: El test `tests/test_deps_compat.py` actúa como un invariante para prevenir regresiones en la compatibilidad.*

```bash
uv sync              # instala dependencias y crea uv.lock
uv run pytest        # ejecuta la suite de tests
uv run odin --version
```

El modo servicio residente tiene su guía operativa completa en
[`docs/service.md`](docs/service.md); la verificación de instalación desde
cero (`uv tool install`) en ambas plataformas llegará con la Etapa 8.

## Ejemplos de configuración

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

## Validación de configuración

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

### Garantías

- **Solo lectura:** `validate` no crea ni modifica archivos (el directorio de
  logs lo crea la configuración del logging, después de las verificaciones).
- **Sin red:** no comprueba conectividad SFTP, SMTP ni Firebird; un destino
  temporalmente caído no invalida la configuración.
- **Sin secretos:** la salida y el log nunca incluyen contraseñas,
  passphrases ni contenido de claves privadas.
- **OS-agnóstico:** una ruta cuyo sabor (Windows o POSIX) no coincide con el
  sistema donde se ejecuta no es comprobable: se omite con una nota, nunca
  cuenta como error.

## Ejecución de respaldos (`odin run`)

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

## Notificación por correo

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

| Campo | Default | Descripción |
|---|---|---|
| `notification.to` / `notification.from` | — (requeridos) | Casilla de control y remitente del informe. |
| `notification.log_tail_lines` | `50` | Últimas líneas del log (ya enmascaradas) que se anexan al cuerpo; `0` desactiva la cola. |
| `notification.smtp.host` / `port` | — (requeridos) | Servidor SMTP. |
| `notification.smtp.starttls` | `true` | Negocia STARTTLS antes de autenticar; `false` envía en plano (relays locales). |
| `notification.smtp.ssl` | `false` | SSL implícito (típicamente puerto 465); mutuamente excluyente con `starttls: true`. |
| `notification.smtp.username` / `password` | `""` | Autenticación SMTP; vacíos omiten el `AUTH`. |

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

## Retención local

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

## Scheduler interno y modo servicio en primer plano

`odin service run` arranca el scheduler interno en primer plano: cada job del
bloque `scheduler` del JSON dispara el pipeline completo (respaldo, compresión,
transferencia, correo y retención) sobre su subconjunto de bases y envía su
propio informe por ciclo. `odin service status` consulta el estado persistido en
`local.work_dir/scheduler_state.json` y `odin service reload` pide la recarga de
la configuración sin reiniciar.

### Bloque `scheduler` del JSON

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

### Operación

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

### Archivo de estado (`scheduler_state.json`)

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

### Recarga en caliente

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

### Solapamiento y misfire

- **Solapamiento**: el servicio mantiene en proceso el registro de las bases en
  ejecución. Con `skip_if_running: true` un ciclo se omite si alguna de sus
  bases está siendo respaldada por otro job; con `false` el ciclo corre solo con
  las bases libres. La misma base nunca se respalda dos veces a la vez, y toda
  omisión queda en el log y en el estado con su motivo.
- **Misfire**: los disparos vencidos se colapsan en uno (`coalesce`). Con
  `on_misfire: run_once` la corrida recuperada se ejecuta aunque llegue tarde;
  con `skip` se descarta (tolerancia de 1 s) y queda registrada como omisión.

### Relación con `odin run` (one-shot)

`odin run` ejecuta el pipeline **una vez** sobre todas las bases y termina (ver
[Ejecución de respaldos](#ejecución-de-respaldos-odin-run)); `odin service run`
es ese mismo pipeline, disparado por cada job según su cron, acotado a las bases
del job y con su propio correo y retención por ciclo, más el estado persistido
para operar sin intervención. Las dos vías comparten fases, enmascarado de
secretos y contrato de resultados por base.

### Demo manual con cadencia real de 1–2 minutos

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

## Modo servicio residente (Windows Service / daemon Linux)

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

## Exit codes

| Código | Significado |
|---|---|
| 0 | `validate`: configuración válida (puede tener advertencias) · `run`: todas las bases completaron respaldo, compresión y transferencia **y** el correo se envió · `service run`: parada limpia por SIGINT/SIGTERM · `service status`: estado leído · `service reload`: solicitud entregada · `service install\|uninstall\|start\|stop`: operación exitosa |
| 1 | Error interno inesperado · `run`: el correo no se pudo enviar en una corrida por lo demás exitosa (una ejecución sin informe incumple la trazabilidad) · `service run`: fallo inesperado · `service reload`: no hay servicio en ejecución · `service install\|uninstall\|start\|stop`: fallo del gestor (incluida plataforma no soportada o servicio no instalado) |
| 2 | Error de configuración, de uso de la CLI, o advertencias con `--strict`; `service run`: `scheduler.enabled: false` o configuración inválida; `service install`: falta la fuente de configuración o tiene errores; `service reload`: configuración ilegible |
| 3 | `run`: fallo parcial (algunas bases completaron todas las fases y otras fallaron en alguna); el desenlace del correo no cambia este código |
| 4 | `run`: fallo total (ninguna base completó todas las fases) o lote no ejecutado/vacío; tiene precedencia sobre el correo |

Con `--strict` las advertencias también devuelven 2: útil como gate previo al
despliegue o en CI.


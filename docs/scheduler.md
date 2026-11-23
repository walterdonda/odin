# ODIN — Scheduler interno

`odin service run` arranca el **scheduler interno** en primer plano: cada job
del bloque `scheduler` del JSON dispara el pipeline completo (respaldo,
compresión, transferencia, correo y retención) sobre su subconjunto de bases y
envía su propio informe por ciclo. `odin service status` consulta el estado
persistido en `local.work_dir/scheduler_state.json` y `odin service reload`
pide la recarga de la configuración sin reiniciar.

El mismo runtime se empaqueta como **servicio residente** del SO (Windows
Service / systemd): instalación, cuentas y diagnóstico en
[`docs/service.md`](service.md). La referencia de campos del bloque
`scheduler` está en [`docs/configuration.md`](configuration.md#8-scheduler).

## 1. Campos

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

## 2. Operación

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
  [Recarga en caliente](#4-recarga-en-caliente)); devuelve 0 cuando la
  solicitud se entrega, 1 si no hay servicio en ejecución y 2 si la
  configuración no puede cargarse.

## 3. Archivo de estado (`scheduler_state.json`)

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

## 4. Recarga en caliente

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

## 5. Solapamiento y misfire

- **Solapamiento**: el servicio mantiene en proceso el registro de las bases en
  ejecución. Con `skip_if_running: true` un ciclo se omite si alguna de sus
  bases está siendo respaldada por otro job; con `false` el ciclo corre solo
  con las bases libres. La misma base nunca se respalda dos veces a la vez, y
  toda omisión queda en el log y en el estado con su motivo.
- **Misfire**: los disparos vencidos se colapsan en uno (`coalesce`). Con
  `on_misfire: run_once` la corrida recuperada se ejecuta aunque llegue tarde;
  con `skip` se descarta (tolerancia de 1 s) y queda registrada como omisión.

## 6. Relación con `odin run` (one-shot)

`odin run` ejecuta el pipeline **una vez** sobre todas las bases y termina (ver
[Operación](../README.md#operación)); `odin service run` es ese mismo
pipeline, disparado por cada job según su cron, acotado a las bases del job y
con su propio correo y retención por ciclo, más el estado persistido para
operar sin intervención. Las dos vías comparten fases, enmascarado de secretos
y contrato de resultados por base.

## 7. Demo manual con cadencia real de 1–2 minutos

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

---

## Enlaces

- Servicio residente (systemd/SCM): [`docs/service.md`](service.md).
- Referencia del bloque `scheduler`:
  [`docs/configuration.md`](configuration.md#8-scheduler).
- Exit codes del scheduler: [`README.md`](../README.md#comandos).

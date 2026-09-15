# Item 055: Recarga de configuración en caliente con validación previa

## Description

Implementar la recarga de la configuración **sin reiniciar** `odin service run`:

- **Solicitud**: en POSIX, un manejador de `SIGUSR1` instalado por `odin service
  run` marca una bandera thread-safe (`threading.Event`) en el
  `SchedulerService`. En Windows (sin señales) la solicitud llega por un archivo
  de control `local.work_dir/scheduler_reload.request` cuya existencia/mtime
  vigila el servicio. El subcomando nuevo `odin service reload` dispara la señal
  (POSIX) o crea el archivo de control (Windows) usando el `pid` y el
  `work_dir` del estado persistido (Item 052).
- **Procesamiento**: un job interno del scheduler (id `reload-watcher`, disparo
  `IntervalTrigger` cada pocos segundos, `max_instances=1`) consume la solicitud
  —bandera o archivo, borrando el archivo— y ejecuta la recarga: `load_config`
  + `validate_config` sobre `config.config_path`. Si la nueva configuración es
  válida se reemplaza la vigente, se actualiza la timezone global, se
  re-registran los jobs (altas, bajas y cambios de horario con
  `replace_existing`) y se recalculan los próximos disparos **sin detener el
  scheduler**. Si es inválida, la configuración vigente se conserva y el motivo
  queda en `odin.log` y en `recent_errors` del estado.
- **Secretos**: en una recarga válida se refresca el enmascarador del
  `SchedulerStateStore` y, vía el hook `on_config_reloaded`, el logging
  (`setup_logging` es idempotente desde el Item 004), para que secretos nuevos
  no queden sin enmascarar en logs/estado.

El comando `service reload` falla con mensaje claro si no hay servicio en
ejecución (estado ausente u obsoleto): exit code 1; configuración ilegible: 2;
solicitud entregada: 0.

## Acceptance Criteria

- [ ] POSIX: `odin service run` instala un manejador de `SIGUSR1` que llama a
      `SchedulerService.request_reload()`; el manejador previo se restaura al
      salir y fuera del hilo principal no se tocan señales globales.
- [ ] `SchedulerService.process_reload()` aplica una configuración válida
      editada en el mismo `config_path`: `service.config` es la `Config` nueva,
      los jobs del scheduler reflejan altas/bajas/horarios nuevos, los
      `next_fire_time` se recalculan con el reloj inyectado y el estado
      persistido queda sincronizado (jobs vigentes, `next_fire_time` nuevos,
      último ciclo preservado).
- [ ] Configuración inválida (JSON/cron inválido o ERROR de `validate_config`)
      → `process_reload()` devuelve `False`, `service.config` y los triggers no
      cambian (identidad), el motivo queda en el log (ERROR) y en
      `recent_errors` del estado, y el servicio sigue operativo.
- [ ] El archivo de control se consume de forma idempotente: la primera
      detección procesa la recarga y lo elimina; una segunda llamada con el
      archivo ausente devuelve `False` sin efectos.
- [ ] Hook `on_config_reloaded`: se invoca con la `Config` nueva solo en
      recargas válidas; el `SchedulerStateStore` actualiza su máscara y la CLI
      real lo cablea a `setup_logging` (nivel y secretos nuevos vigentes).
- [ ] `odin service reload` sin servicio corriendo imprime el motivo y devuelve
      `EXIT_INTERNAL` (1); con la config ilegible, `EXIT_CONFIG` (2); con la
      solicitud entregada (SIGUSR1 en POSIX, archivo de control si no hay
      señal), `EXIT_OK` (0).
- [ ] Con `_RELOAD_VIA_SIGNAL = False` (Windows o sin `SIGUSR1`) el comando crea
      `<work_dir>/scheduler_reload.request` y no llama a `os.kill`.
- [ ] `tests/test_scheduler.py`, `tests/test_scheduler_state.py` y
      `tests/test_cli.py` cubren los casos anteriores sin dejar la suite
      bloqueada ni enviar señales reales al proceso de pytest.
- [ ] Gates en verde: `uv run pytest`, `uv run ruff check src/odin tests`,
      `uv run mypy src/odin`.

## Implementation Steps

1. `src/odin/scheduler.py`: constantes `RELOAD_REQUEST_FILENAME`,
   `RELOAD_POLL_SECONDS`, `RELOAD_WATCHER_JOB_ID`; helper
   `reload_request_path(work_dir)`; `SchedulerStateStore.set_mask()` y
   `remove_job()`.
2. `SchedulerService`: `request_reload()`, `process_reload()`, `_consume_reload`,
   `_apply_config` (timezone, reloj default, limpieza de jobs viejos, refresco de
   máscara), `_register_reload_watcher()` y el parámetro
   `on_config_reloaded`; guard en `run_job` para jobs eliminados por la recarga.
3. `src/odin/cli.py`: subcomando `service reload` en `build_parser`, constante
   `_RELOAD_VIA_SIGNAL`, `_reload_signal()` (handler `SIGUSR1`),
   `_cmd_service_reload()` con los exit codes acordados y cableado del hook en
   `_build_scheduler_service`/`_cmd_service_run`.
4. Tests: recarga válida/inválida, archivo de control idempotente, hook y
   watcher en `tests/test_scheduler.py`; `set_mask`/`remove_job` en
   `tests/test_scheduler_state.py`; parser/exit codes/señal/archivo y restauración
   del handler en `tests/test_cli.py`.
5. Actualizar docstrings de `scheduler.py`/`cli.py`; documentar decisiones y
   evidencia en "Decisions & Trade-offs" y actualizar `docs/aide/progress.md`.

## Testing Strategy

- Recarga válida: config con 1 job → reescribir el mismo `config_path` con 2
  jobs y horario distinto → `request_reload()` + `process_reload() is True`;
  `service.job_config("job-1")` existe, el trigger de `job-0` coincide con el
  nuevo `schedule`, `next_run_time == next_fire_times(cron_trigger(...), FIXED_NOW, 1)[0]`
  y el estado tiene ambos jobs con el `next_fire_time` nuevo.
- Recarga inválida: JSON con cron fuera de rango (`0 25 * * *`) → `False`,
  `service.config is original`, trigger intacto, `caplog` con el motivo y
  `recent_errors` con el motivo enmascarado; variante con ERROR de
  `validate_config` (`local.work_dir` apuntando a un archivo existente).
- Archivo de control: crear `reload_request_path(work_dir)` → primer
  `process_reload()` lo procesa y lo elimina; segundo → `False`.
- Hook: doble que registra configs → se llama una vez con la config nueva;
  recarga inválida → no se llama.
- Watcher: `service.scheduler.get_job("reload-watcher")` registrado con
  `max_instances=1`.
- CLI: sin estado → exit 1 y "No hay servicio en ejecución"; con estado vivo y
  `os.kill` monkeypatcheado (registra `(pid, SIGUSR1)`, responde a la señal 0 de
  `pid_is_alive`) → exit 0; `_RELOAD_VIA_SIGNAL = False` → archivo creado en el
  `work_dir` del estado; handler `SIGUSR1` → `request_reload` invocado y handler
  restaurado; config ilegible → exit 2.
- Gates completos del batch.

## Dependencies

- Items 049-054 (`SchedulerService`, estado, CLI `service run|status`, runner
  real), `load_config` (Item 002) y `validate_config` (Item 006).

## Decisions & Trade-offs

- **Vigilancia con un job interno (`reload-watcher`)**: un `IntervalTrigger` de
  `RELOAD_POLL_SECONDS = 2.0` reutiliza el scheduler ya existente, no agrega
  hilos ni ciclo de vida propio y queda cubierto por `max_instances=1`. La
  alternativa (comprobar la bandera al inicio de cada `run_job`) tenía latencia
  de un ciclo completo (hasta un día con cron diario) y la de un hilo dedicado
  sumaba una pieza que hay que parar y testear. El watcher no está en
  `self._jobs` ni en el estado: no es un job de la configuración.
- **`request_reload()` solo activa un `threading.Event`**: es lo único que
  ejecuta el handler de `SIGUSR1`; nada del scheduler se toca desde el contexto
  de la señal. El archivo de control se detecta por existencia y se consume con
  `unlink` (idempotente); su contenido ISO deja traza del pedido. Un archivo
  residual de una corrida anterior dispara una recarga inofensiva al arrancar
  (la config se re-valida antes de aplicarse).
- **Validación con `load_config` + `validate_config` e import diferido**: la
  estructural/semántica ya viene de `load_config` (incluye cron y timezone); la
  de entorno/coherencia agrega `validate_config` (`is_valid(strict=False)`:
  solo los ERROR bloquean, las advertencias no). El import es diferido porque
  `odin.validate` importa este módulo (ciclo real, no solo de tipado).
- **Re-registro explícito de jobs**: `_register_jobs` elimina el job existente
  antes de volver a agregarlo. El test de recarga con el scheduler detenido
  destapó que en APScheduler 3.x `replace_existing` no reemplaza jobs
  *pendientes* (`_pending_jobs`): quedaban dos entradas con el mismo id y
  `get_job` devolvía la vieja (próximo disparo sin actualizar). `remove_job`
  sí soporta jobs pendientes, así que el borrado previo cubre ambos estados.
- **`_apply_config` completo**: actualiza `config`, `self._timezone` (y
  `scheduler.timezone`), el reloj default (el reloj inyectado de los tests se
  conserva), la ruta del archivo de control, elimina del scheduler y del estado
  los jobs ausentes (`SchedulerStateStore.remove_job`), re-registra los
  vigentes con sus nuevos `next_fire_time`, refresca la máscara
  (`set_mask(SecretMasker.from_config(new_config).mask)`) y llama al hook
  `on_config_reloaded`. La CLI lo cablea a `setup_logging` (idempotente): nivel
  y secretos nuevos quedan vigentes tras la recarga, sin reiniciar.
- **Guard de disparos huérfanos**: `run_job` de un job eliminado por la recarga
  se descarta como omisión en vez de lanzar `KeyError` (un disparo ya encolado
  en el executor podía llegar después del re-registro).
- **Exit codes de `service reload`**: 0 = solicitud entregada (señal o archivo),
  2 = configuración que no carga, 1 = no hay servicio en ejecución (estado
  ausente u obsoleto) o fallo de entrega de la señal. Limitación heredada de
  `status`: si la config editada no parsea, el comando no puede ubicar el
  `work_dir` (exit 2); el caso "config inválida que el servicio rechaza" se
  cubre a nivel servicio (`request_reload` + `process_reload`).

**Evidencia:** `uv run pytest tests/test_scheduler.py tests/test_scheduler_state.py tests/test_cli.py -q` → **128 passed** (recarga válida con jobs/altas/bajas/disparos actualizados y estado sincronizado, recarga con cron inválido y con ERROR de entorno rechazada conservando config/triggers y registrando el motivo, archivo de control consumido idempotentemente, hook no invocado en rechazo, máscara refrescada con el secreto nuevo, watcher registrado, `service reload` sin servicio → 1 / con SIGUSR1 → 0 / sin señal → archivo / config ilegible → 2, handler restaurado); suite completa `uv run pytest -q` → **491 passed + 2 skipped**; `uv run ruff check src/odin tests` → All checks passed; `uv run mypy src/odin` → Success (14 source files).

## Prerequisites

- No requiere servicios externos: las pruebas usan reloj/estado y `os.kill`
  inyectados; nunca se envía `SIGUSR1` real al proceso de pytest.
- `docs/aide/progress.md` debe ser actualizado a 🚧 al iniciar.
- Al finalizar, actualizar `docs/aide/progress.md` a ✅.

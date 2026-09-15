# Item 050: Núcleo de `SchedulerService` sobre APScheduler 3.x

## Description

Implementar en `src/odin/scheduler.py` el servicio de scheduling: `BlockingScheduler` con la `timezone` global del JSON, registro de un job APScheduler por cada `scheduler.jobs[]` (id estable `job-N` por índice, `CronTrigger` del Item 049, `max_instances=1`, `replace_existing=True`) y ciclo de vida `start()`/`shutdown()` limpio con logging.

La ejecución de un job delega en un `cycle_runner` inyectable de interfaz `(Config, SchedulerJob) -> CycleOutcome` (el runner real sobre `run_pipeline` llega en el Item 054): el núcleo no conoce el pipeline y es testeable sin red ni reloj real. `CycleOutcome` se define acá como dataclass congelada (bases solicitadas, bases ejecutadas, omitido + motivo, éxito, duración, correo enviado, error) para que los Items 051/052/054 lo consuman.

Documentar en el docstring del módulo la decisión de implementación —APScheduler 3.11.3 (lockeado y verificado en Python 3.14 por el Item 008) por sobre 4.x y stdlib, con justificación—.

## Acceptance Criteria

- [ ] `SchedulerService(config, *, cycle_runner, ...)` construye un `BlockingScheduler` con la `timezone` del JSON y registra un job por `scheduler.jobs[]` con id `job-N`, `trigger` del Item 049, `max_instances=1` y `replace_existing=True`.
- [ ] `start()` bloquea hasta `shutdown()` (comportamiento `BlockingScheduler`) y ambos dejan entradas de log claras; `shutdown()` sobre un servicio no arrancado no lanza (`SchedulerNotRunningError` encapsulado).
- [ ] El `cycle_runner` inyectado se invoca con la `Config` y el `SchedulerJob` del job que dispara, y su `CycleOutcome` queda registrado en `last_outcomes[job_id]`.
- [ ] Una excepción imprevista del `cycle_runner` no escapa: se convierte en `CycleOutcome(success=False, error_message=...)` con log de excepción, y el servicio sigue operativo.
- [ ] Docstring del módulo con la decisión APScheduler 3.11.3 vs 4.x vs stdlib y su justificación.
- [ ] Tests en `tests/test_scheduler.py`: jobs registrados con trigger y próximo disparo esperados, timezone respetada, arranque/detención limpia y `cycle_runner` invocado con el job correcto (reloj inyectable).
- [ ] Gates en verde: `uv run pytest`, `uv run ruff check src/odin tests`, `uv run mypy src/odin`.

## Implementation Steps

1. Definir `CycleOutcome` y el tipo `CycleRunner = Callable[[Config, SchedulerJob], CycleOutcome]`.
2. Implementar `SchedulerService.__init__` (scheduler/timezone/reloj/registry inyectables), registro de jobs y `run_job(job_id)` público (usado por APScheduler y por los tests, sin esperar al reloj real).
3. Implementar `start()`/`shutdown()` con logging y encapsulamiento de `SchedulerNotRunningError`.
4. Escribir el docstring del módulo con la decisión tecnológica; declarar `__all__`.
5. Tests en `tests/test_scheduler.py` (reloj inyectable, arranque real en hilo + `shutdown`, excepción del runner).
6. Documentar decisiones y evidencia en "Decisions & Trade-offs" y actualizar `docs/aide/progress.md`.

## Testing Strategy

- Registro: `service.scheduler.get_jobs()` devuelve un job por entrada, con `CronTrigger` equivalente al del Item 049 y `max_instances == 1`.
- Timezone: `service.scheduler.timezone` es la `ZoneInfo` del JSON.
- `cycle_runner` doble que registra la llamada; `service.run_job("job-0")` devuelve su `CycleOutcome` y lo deja en `last_outcomes`.
- Excepción del runner (p. ej. `RuntimeError`) → `CycleOutcome` fallido, sin propagación, log con `caplog`.
- Ciclo de vida: `service.start()` en un hilo daemon con un job de cadencia lejana; esperar `scheduler.running`, `shutdown()` y verificar hilo terminado y `running` falso; `shutdown()` extra no lanza.
- Sin servicios externos (no hay red ni SMTP en este item).

## Dependencies

- Item 049 (`cron_trigger`/`next_fire_times`).

## Decisions & Trade-offs

- **APScheduler 3.11.3 (no 4.x ni stdlib)**: 3.x es la serie lockeada y verificada en Python 3.14 por el Item 008 y trae `BlockingScheduler`, `CronTrigger.from_crontab`, `timezone` IANA, `max_instances` y `replace_existing`; 4.x sigue en pre-release sin paridad documentada y la stdlib obligaría a reimplementar cron + coalescing + política de instancias. La justificación completa queda en el docstring del módulo.
- **`next_run_time` explícito con el reloj del servicio**: `add_job` recibe el próximo disparo calculado con `self._now()` en vez de dejar que APScheduler use `datetime.now()`; así el reloj inyectable es autoritativo (tests deterministas) y la base del guard de misfire del Item 051 es la misma fuente.
- **`run_job(job_id)` público**: APScheduler lo usa como función del job (vía `args`) y los tests lo invocan directamente, sin esperar un minuto real para verificar el registro y el desenlace. `max_instances=1` impide instancias simultáneas del mismo job; el solapamiento *entre* jobs distintos se resuelve en el Item 051.
- **`CycleOutcome` congelado y `last_outcomes`**: superficie mínima que el Item 052 persistirá y el Item 054 poblará desde `run_pipeline`; el núcleo no importa `pipeline` (sin ciclos de importación y testeable sin red/SMTP).
- **Excepción del runner encapsulada**: un fallo imprevisto del ciclo se convierte en `CycleOutcome(success=False)` con `duration_seconds` medido por el servicio; el scheduler nunca muere por un ciclo.

**Evidencia:** `uv run pytest tests/test_scheduler.py -q` → **13 passed** (registro por entrada, timezone/trigger/próximo disparo con reloj fijo, `cycle_runner` invocado con la config y el job correctos, excepción del runner aislada, arranque/detención real en hilo); suite completa `uv run pytest -q` → **429 passed + 2 skipped**; `uv run ruff check src/odin tests` → All checks passed; `uv run mypy src/odin` → Success (14 source files).

## Prerequisites

- No requiere servicios externos; APScheduler 3.11.3 ya está lockeado.
- `docs/aide/progress.md` debe ser actualizado a 🚧 al iniciar.
- Al finalizar, actualizar `docs/aide/progress.md` a ✅.

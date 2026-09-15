# Item 051: Anti-solapamiento (`skip_if_running`) y políticas `on_misfire`

## Description

Implementar el registro in-flight por base a nivel de proceso (conjunto thread-safe con `threading.Lock`) que impide respaldos simultáneos de la misma base entre jobs distintos: al disparar se calculan las bases en vuelo; con `skip_if_running: true` (default) el ciclo se omite si **alguna** base del job está en ejecución; con `false` el ciclo corre solo con las bases libres (nunca se duplica una base). Toda omisión queda en el log y en el `CycleOutcome` con su motivo (`skipped=True`, `skipped_reason`), y las bases reservadas se liberan siempre (`finally`), incluso si el runner lanza.

Configurar `on_misfire` en APScheduler 3.x: `run_once` → `coalesce=True` + `misfire_grace_time=None` (una sola corrida al recuperar el servicio); `skip` → descarte de disparos vencidos (`misfire_grace_time` acotado, `coalesce=True`) reforzado por la latencia del disparo en el wrapper (`now` inyectable contra el próximo disparo esperado del trigger); la semántica real de APScheduler 3.x queda fijada por tests.

## Acceptance Criteria

- [ ] `InFlightRegistry` (o equivalente) reserva/libera bases de forma atómica con `threading.Lock`; `reserve(databases, all_or_nothing=True)` devuelve `reserved=()` y las ocupadas si alguna está en vuelo; `all_or_nothing=False` reserva solo las libres.
- [ ] `skip_if_running: true`: si otra ejecución tiene una base del job, `run_job` devuelve `CycleOutcome(skipped=True, skipped_reason=...)` sin invocar al `cycle_runner` y con log de advertencia.
- [ ] `skip_if_running: false`: el ciclo corre con las bases libres (job efectivo con `dataclasses.replace`) y las ocupadas no se duplican; si no queda ninguna libre, se omite con motivo.
- [ ] Los jobs `run_once` registran `coalesce=True` y `misfire_grace_time=None`; los `skip` descartan disparos vencidos (test con reloj inyectable: disparo esperado muy anterior a `now` → omitido sin llamar al runner).
- [ ] Las bases se liberan siempre al terminar el ciclo (incluso con excepción del runner): un disparo posterior vuelve a ejecutarse.
- [ ] Tests en `tests/test_scheduler.py`: dos jobs que comparten base con `threading.Event` (el segundo se omite sin solaparse), `skip_if_running` en ambos valores, misfire `skip` con reloj falso y propiedades de job para `run_once`.
- [ ] Gates en verde: `uv run pytest`, `uv run ruff check src/odin tests`, `uv run mypy src/odin`.

## Implementation Steps

1. Agregar `InFlightRegistry`/`Reservation` con reserva atómica y `release`.
2. Integrar la reserva en `run_job` (Item 050): cálculo de bases en vuelo, omisión o job efectivo filtrado, `finally` de liberación, `CycleOutcome` de omisión con motivo.
3. Configurar `coalesce`/`misfire_grace_time` en el registro de jobs según `on_misfire` y agregar el guard de latencia del wrapper (`_MISFIRE_TOLERANCE_SEC`, `now` inyectable, próximo disparo esperado del trigger).
4. Tests de solapamiento con hilos/`threading.Event`, de ambos valores de `skip_if_running` y de misfire con reloj falso.
5. Documentar decisiones (tolerancia de misfire, semántica APScheduler 3.x) y evidencia; actualizar `docs/aide/progress.md`.

## Testing Strategy

- `tests/test_scheduler.py::test_overlapping_job_is_skipped`: runner del job 0 bloqueado en un `threading.Event`; el job 1 (misma base) devuelve omitido con "en ejecución" en el motivo; liberado el evento, un nuevo disparo del job 1 ejecuta.
- `skip_if_running=False`: job con dos bases y una ocupada por otro ciclo → runner invocado con el job efectivo de una sola base; sin bases libres → omitido.
- Misfire: reloj mutable (`now` inyectable); avanzar 5 minutos y disparar `on_misfire=skip` → omitido; mismo escenario con `run_once` → ejecuta (y las propiedades del job APScheduler son `coalesce=True`/`misfire_grace_time=None`).
- Excepción del runner: la base queda libre y el `CycleOutcome` es fallido.
- Gates completos del batch.

## Dependencies

- Items 049 y 050.

## Decisions & Trade-offs

- **Registro in-flight con reserva atómica**: `InFlightRegistry.reserve(databases, all_or_nothing=...)` resuelve bajo un solo `threading.Lock` las dos semánticas (`skip_if_running`): todo-o-nada devuelve `reserved=()` y las ocupadas; libre-por-base devuelve solo las tomadas. El `Reservation` transporta además las ocupadas para el motivo del `CycleOutcome` y el log.
- **Misfire en dos capas**: `run_once` se mapea entero a APScheduler (`coalesce=True`, `misfire_grace_time=None`: una sola corrida al recuperar); `skip` usa `misfire_grace_time=1` (APScheduler exige entero positivo) y además un guard de latencia en `run_job` con el reloj inyectable, porque el grace de APScheduler se evalúa en el executor contra `datetime.now(UTC)` real y no es fakeable. El guard compara `now` con el próximo disparo esperado del trigger (`_expected_fires`, actualizado en cada corrida).
- **`coalesce=True` siempre**: varios disparos vencidos se colapsan en uno; para `skip` el guard/grace los descarta directamente.
- **Reserva parcial (`skip_if_running: false`)**: el runner recibe un job efectivo con `dataclasses.replace` y solo las bases libres; el `CycleOutcome` conserva `job_databases` (lo solicitado) y `databases` (lo ejecutado) y se loguea un warning con las ocupadas.
- **Liberación garantizada**: el `finally` de `run_job` libera exactamente las bases reservadas, incluso si el runner lanza; un disparo posterior vuelve a ejecutarse (test dedicado).

**Evidencia:** `uv run pytest tests/test_scheduler.py -q` → **22 passed** (registro in-flight all-or-nothing; dos jobs con `threading.Event` donde el segundo se omite sin solaparse; `skip_if_running=true` omite el job completo si *alguna* base está ocupada; `false` corre solo con las libres y omite si no queda ninguna; liberación tras excepción del runner; misfire `skip` con reloj inyectable a 5 min de latencia → omitido sin llamar al runner; `run_once` ejecuta el disparo tardío; propiedades `coalesce`/`misfire_grace_time` del job APScheduler). Suite completa `uv run pytest -q` → **438 passed + 2 skipped**; `uv run ruff check src/odin tests` → All checks passed; `uv run mypy src/odin` → Success (14 source files).

## Prerequisites

- No requiere servicios externos.
- `docs/aide/progress.md` debe ser actualizado a 🚧 al iniciar.
- Al finalizar, actualizar `docs/aide/progress.md` a ✅.

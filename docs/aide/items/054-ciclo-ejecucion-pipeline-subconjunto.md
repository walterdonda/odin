# Item 054: Ciclo de ejecución: pipeline por subconjunto de bases y resultado por ciclo

## Description

Implementar en `src/odin/scheduler.py` el `cycle_runner` real: `PipelineCycleRunner` filtra `config.databases` por las bases del `SchedulerJob` efectivo (el que ya viene acotado por las políticas del Item 051), construye la config del ciclo con `dataclasses.replace` e invoca `run_pipeline` (`pipeline.py:182`) con su propio correo por ciclo y su retención. Devuelve un `CycleOutcome` con el estado global (`success`/`partial`/`failure`), las bases ejecutadas, la duración, si el correo salió y el resumen de errores.

Aislamiento: una excepción imprevista del pipeline no detiene el servicio y queda registrada (la encapsula `SchedulerService.run_job`, que ya libera reservas y persiste el estado); los logs del ciclo pasan por el enmascarado existente (handlers del logger `odin` y `SecretMasker` para el correo) y el error persistido en el estado queda enmascarado por el store (Item 052). Cada ciclo es independiente del anterior: la config del ciclo es inmutable y no toca la del servicio.

`PipelineCycleRunner` es inyectable (`run` y opciones del pipeline) para los tests del item y para la integración del Item 056.

## Acceptance Criteria

- [ ] `PipelineCycleRunner(config, job)` pasa a `run_pipeline` una `Config` con **exactamente** las bases de `job.databases` (orden de `config.databases`), sin mutar la original; solo las bases que aparecen en ambas.
- [ ] `CycleOutcome` devuelto: `databases` = bases ejecutadas del lote, `duration_seconds` medida, `notification_sent` del `PipelineResult.notification`, `error_message` con el resumen de fallos y `status`: `SUCCESS` (todo bien), `PARTIAL` (mezcla), `FAILURE` (todo mal o lote no ejecutado).
- [ ] Un job cuyas bases no existen en `config.databases` ejecuta un lote vacío sin romper (`status=FAILURE`, error "sin bases").
- [ ] Una excepción imprevista del pipeline se propaga a `SchedulerService.run_job`, que la convierte en `CycleOutcome` fallido, libera las reservas y deja el servicio operativo; con `state_store` el error queda en `recent_errors`.
- [ ] Los `error_message` persistidos en el estado y las líneas de log del ciclo no contienen secretos (máscara del store y `MaskingFilter` de los handlers).
- [ ] `tests/test_scheduler.py`: pipeline doble que registra la config del ciclo (éxito, parcial, fallo total, lote vacío, excepción) y servicio real con estado que sigue operativo tras un ciclo fallido.
- [ ] Gates en verde: `uv run pytest`, `uv run ruff check src/odin tests`, `uv run mypy src/odin`.

## Implementation Steps

1. Definir `PipelineCycleRunner` (callable `(Config, SchedulerJob) -> CycleOutcome`) con `run`/opciones inyectables.
2. Implementar el filtrado de bases, la config del ciclo con `replace`, la invocación del pipeline y la traducción `PipelineResult → CycleOutcome` (status, bases, duración, correo, resumen de fallos).
3. Agregar helper del resumen de fallos por base priorizando compresión > transferencia > respaldo.
4. Tests en `tests/test_scheduler.py` con pipeline doble (éxito/parcial/fallo/vacío/excepción) y un caso de enmascarado en el estado y en el log.
5. Documentar decisiones y evidencia en "Decisions & Trade-offs" y actualizar `docs/aide/progress.md`.

## Testing Strategy

- Pipeline doble que captura la config recibida: config con dos bases y job con una → `run` ve una sola base; la `Config` original conserva las dos.
- Éxito: dos `BackupResult` exitosos + `NotificationResult(success=True)` → `status=SUCCESS`, `notification_sent=True`, `databases` ambas.
- Parcial: un resultado fallido y uno exitoso → `status=PARTIAL`, `success=False`, el `error_message` nombra la base fallida (prioridad al error de compresión/transferencia).
- Fallo total y `BatchBackupResult.error_message` (lote no ejecutado) → `FAILURE` con el motivo.
- Job con base inexistente → lote vacío, `FAILURE`, sin excepción.
- Excepción del doble → propagada al servicio, `CycleOutcome` fallido y `service.run_job` posterior sigue funcionando; con store, `recent_errors` con el mensaje.
- Enmascarado: error del pipeline que contiene la contraseña de la config → el archivo de estado no la contiene; `setup_logging` + handler de archivo no la contiene en `odin.log`.
- Gates completos del batch.

## Dependencies

- Items 050/051 (`SchedulerService`), 052 (estado) y pipeline completo de las Etapas 2-5 (`run_pipeline`).

## Decisions & Trade-offs

- **Runner como clase callable con `run` y opciones inyectables**: `PipelineCycleRunner(run_pipeline, **options)` cumple la interfaz `(Config, SchedulerJob) -> CycleOutcome` del Item 050 y deja inyectar tanto un doble completo (tests de este item) como fases específicas (Item 056: `backup=`/`compression=`/`transfer=`/`notifier=`/`retention=`), sin tocar la firma del servicio. `run` tiene default `run_pipeline`, así que el cableado real de la CLI (que ya lo construye sin argumentos) no cambia.
- **Config del ciclo con `dataclasses.replace`**: el `Config` es inmutable y el del servicio no se toca; el ciclo ve exactamente `config.databases` filtrado por las bases del job efectivo, en el orden de la configuración. Repetir la config del ciclo en cada disparo es barato (dataclasses congeladas) y evita estado compartido entre ciclos: cada corrida es independiente, como pide el aislamiento.
- **Mapeo de estados con prioridad explícita**: lote con `error_message` (no ejecutado) → `FAILURE` con ese motivo; lote vacío → `FAILURE` con diagnóstico de las bases pedidas; fallos parciales → `PARTIAL` (o `FAILURE` si fallaron todas) con el resumen `base: motivo` de cada fallida —se prefiere el error de compresión, luego el de transferencia, luego el de respaldo, porque es el más específico de la fase donde se detuvo la base—. El `error_message` es lo que alimenta `recent_errors` del estado (Item 052).
- **Sin capturar excepciones en el runner**: el contrato de aislamiento vive en `SchedulerService.run_job` (Item 050), que además libera las reservas y persiste el desenlace; capturar también acá duplicaría la red de seguridad y escondería el `logger.exception` del servicio. La excepción del pipeline queda como `CycleOutcome` fallido con la duración medida por el servicio y entra a `recent_errors`.
- **Doble barrera de secretos**: el runner loguea el error crudo (la línea de warning con el motivo es la traza operativa del ciclo) y los handlers de `setup_logging` lo enmascaran; el `SchedulerStateStore` enmascara antes de persistir, de modo que ni el archivo de estado ni el log contienen secretos. El correo ya venía enmascarado por `render_report` (Item 040) y la cola de log por `TailBufferHandler` (Item 041).
- **Import de `run_pipeline` en `scheduler.py`**: no genera ciclo (`pipeline` no importa `scheduler`) y permite que la fábrica de la CLI (Item 053) deje de diferir el import y retire el `# type: ignore[attr-defined]` temporal al definir la clase; los tests del núcleo siguen sin red porque inyectan dobles.

**Evidencia:** `uv run pytest tests/test_scheduler.py tests/test_scheduler_state.py tests/test_cli.py -q` → **112 passed** (filtrado exacto de bases y no mutación del `Config` original, opciones reenviadas al pipeline, éxito con `notification_sent`, parcial con prioridad de compresión, fallo total con transferencia, lote no ejecutado, selección vacía, excepción aislada con `recent_errors` y servicio operativo, enmascarado en `odin.log` y `scheduler_state.json`); suite completa `uv run pytest -q` → **475 passed + 2 skipped**; `uv run ruff check src/odin tests` → All checks passed; `uv run mypy src/odin` → Success (14 source files).

## Prerequisites

- No requiere servicios externos: el pipeline se inyecta con dobles (respaldo/compresión/transferencia/correo), sin red ni SMTP real.
- `docs/aide/progress.md` debe ser actualizado a 🚧 al iniciar.
- Al finalizar, actualizar `docs/aide/progress.md` a ✅.

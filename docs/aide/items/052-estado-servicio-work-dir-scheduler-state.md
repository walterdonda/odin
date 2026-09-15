# Item 052: Estado del servicio en `work_dir` (`scheduler_state.json`)

## Description

Implementar en `src/odin/scheduler.py` el estado consultable por `odin service status`: dataclasses `ServiceState`/`JobState`/`CycleRecord` (versión de esquema, `pid`, `config_path`, `started_at`, `updated_at`, último ciclo por job con bases/estado/duración/correo, próximos disparos por job y errores recientes acotados) con escritura atómica (`tempfile` + `os.replace`) en `config.local.work_dir/scheduler_state.json`, sin secretos.

La lectura es tolerante: archivo ausente, JSON corrupto o esquema desconocido devuelven un `StateLoadResult` tipado con `warning` (nunca una excepción). El estado obsoleto se detecta comparando el `pid` guardado con el proceso vivo (POSIX `os.kill(pid, 0)`; en Windows se reporta el pid sin verificar, porque no hay comprobación barata y confiable). `SchedulerStateStore` es el acumulador mutable: registra jobs al arrancar, registra el desenlace de cada ciclo (con máscara de secretos), acumula los errores recientes con tope y persiste con `save()`.

El estado es la base de `odin service status` (Item 053) y el consumidor del `CycleOutcome` que el runner real poblará en el Item 054: para representar fielmente el estado global (éxito/parcial/fallo/omitido), `CycleOutcome` suma `partial` (campo) y `status` (`CycleStatus`, propiedad derivada de `skipped`/`partial`/`success`; el Item 054 marca `partial=True` en los ciclos con mezcla).

## Acceptance Criteria

- [ ] `ServiceState`/`JobState`/`CycleRecord` con `SCHEMA_VERSION`, `pid`, `config_path`, `started_at`, `updated_at`, jobs (schedule, bases, próximo disparo, último ciclo) y `recent_errors` acotado (`MAX_RECENT_ERRORS`).
- [ ] `write_state(path, state)` persiste con `tempfile.mkstemp` + `os.replace`; ante un fallo de escritura no deja archivos temporales ni corrompe el estado previo.
- [ ] `load_state(path)` devuelve `StateLoadResult(state, path, stale, warning)` sin lanzar: ausente, JSON corrupto, tipos inválidos o `version` desconocida → `state=None` + `warning`.
- [ ] `pid_is_alive()` reporta vivo/muerto en POSIX (`os.kill(pid, 0)`, `PermissionError` = vivo) y siempre vivo en Windows; `load_state` marca `stale=True` con un pid muerto.
- [ ] `SchedulerStateStore` registra jobs y ciclos, acumula errores hasta el tope, aplica la máscara de secretos (`mask` inyectable) y su `save()` es atómico y thread-safe.
- [ ] `CycleOutcome.status` (`CycleStatus`: `success`/`partial`/`failure`/`skipped`) se deriva de `skipped`/`partial`/`success` como propiedad (sin agregar un campo a la igualdad del dataclass): omitido → `SKIPPED`, mezcla → `PARTIAL`, `success` → `SUCCESS`, resto `FAILURE`.
- [ ] `tests/test_scheduler_state.py`: round trip completo, escritura atómica (fallo simulado de `os.replace`), ausencia/corrupción/esquema desconocido, ausencia de secretos y pid muerto.
- [ ] Gates en verde: `uv run pytest`, `uv run ruff check src/odin tests`, `uv run mypy src/odin`.

## Implementation Steps

1. Definir `CycleStatus`, extender `CycleOutcome` con `status` derivado y declarar `SCHEMA_VERSION`/`STATE_FILENAME`/`MAX_RECENT_ERRORS`/`state_path`.
2. Implementar `pid_is_alive`, la serialización de `ServiceState` (ISO 8601 para datetimes) y `write_state`/`load_state` con escritura atómica y lectura tolerante.
3. Implementar `SchedulerStateStore` (lock, registro de jobs, `record_cycle` con máscara, `record_error` con deque acotado, `snapshot`, `save`).
4. Tests en `tests/test_scheduler_state.py` (sin servicios externos).
5. Documentar decisiones y evidencia en "Decisions & Trade-offs" y actualizar `docs/aide/progress.md`.

## Testing Strategy

- Round trip: store con dos jobs, un ciclo éxito y uno parcial/fallo/omitido, `save()` → `load_state()` devuelve el mismo estado (jobs en orden de registro, datetimes ISO, errores recientes).
- Atómico: escribir un estado válido, monkeypatch de `os.replace` que lanza `OSError`, verificar que el archivo previo queda intacto y no quedan `*.tmp`.
- Tolerancia: archivo ausente, `no-json`, JSON con `version: 99` y JSON con campos faltantes → `state is None` y `warning` no vacío; ningún caso lanza.
- Secretos: un `CycleRecord` cuyo `error_message` contiene la contraseña de la config (via `SecretMasker.from_config`) se persiste con `***`; el archivo no contiene el secreto.
- Pid: `pid_is_alive(os.getpid())` es `True`; un pid imposible (`2**31 - 1`) es `False` en POSIX (en Windows se omite, `pid_is_alive` siempre reporta vivo); `load_state` con ese pid → `stale=True`.
- `CycleOutcome(success=True).status is CycleStatus.SUCCESS`, skip → `SKIPPED`, fallo → `FAILURE`, y `replace` conserva el status.
- Gates completos del batch.

## Dependencies

- Item 051 (no funcional; reutiliza `CycleOutcome` y el patrón de tests de `tests/test_scheduler.py`).

## Decisions & Trade-offs

- **`CycleOutcome.status` como propiedad, no campo**: un campo nuevo con default obligaría a un centinela para distinguir "no indicado" de un valor real y cambiaría la igualdad del dataclass que los tests del Item 050 ya fijan. La propiedad sobre `partial` (campo bool con default) da el estado global sin tocar la igualdad: `skipped` tiene precedencia (una omisión no ejecutó nada), luego `partial`, luego `success`.
- **Escritura atómica con `mkstemp` + `os.replace` en el mismo directorio**: el temporal nunca cruza filesystems, un lector concurrente jamás ve un archivo a medio escribir y el fallo deja el estado previo intacto; el `finally` elimina el temporal. El `fsync` previo al `replace` evita perder el estado ante un corte del SO (el archivo es chico: el costo es despreciable).
- **Lectura tolerante con `StateLoadResult`**: el estado es información auxiliar; ninguna combinación de archivo ausente/corrupto/esquema viejo debe impedir que `odin service status` o `odin service run` funcione. `warning` explica el motivo y `stale` distingue "no legible" de "proceso muerto". La validación de tipos por campo (`_parse_str`/`_parse_int`/`_parse_datetime`) hace que un JSON válido pero con campos absurdos no explote con `TypeError` en la construcción del dataclass.
- **Vigencia por `pid` sin verificar en Windows**: `os.kill(pid, 0)` es POSIX; en Windows comprobar el proceso exige abrir un handle (`OpenProcess`) y permisos, y el contrato pedido es "se reporta el pid sin verificar". `PermissionError` en POSIX se considera vivo: el proceso existe aunque sea de otro usuario.
- **Store con lock y máscara inyectable**: el mismo estado se escribe desde el hilo del executor de APScheduler (dos jobs pueden correr en paralelo); el lock serializa mutaciones, snapshots y escritura. La máscara se aplica al **registrar** (no al serializar): así `recent_errors` y `error_message` nunca contienen secretos ni siquiera en memoria, y el archivo cumple el contrato de la visión §6. `clock` y `max_recent_errors` son inyectables para tests deterministas.
- **`recent_errors` acotado con `deque(maxlen)`**: ventana de diagnóstico sin crecimiento indefinido; un estado que corre meses no puede inflar el archivo. Los ciclos omitidos no entran (no son errores) y los parciales/fallidos entran con una línea `job: estado: motivo`.

**Evidencia:** `uv run pytest tests/test_scheduler_state.py tests/test_scheduler.py -q` → **37 passed** (round trip con dos jobs y ciclos éxito/fallo, escritura atómica con `os.replace` simulado que falla sin corromper ni dejar temporales, ausencia/corrupción/esquema desconocido/campos faltantes → warning sin excepción, pid muerto → `stale`, máscara de secretos en archivo y errores recientes acotados, derivación de `CycleStatus`); `uv run ruff check src/odin tests` → All checks passed; `uv run mypy src/odin` → Success (14 source files).

## Prerequisites

- No requiere servicios externos (solo filesystem temporal y stdlib).
- `docs/aide/progress.md` debe ser actualizado a 🚧 al iniciar.
- Al finalizar, actualizar `docs/aide/progress.md` a ✅.

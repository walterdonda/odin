# Item 053: CLI `odin service run` (foreground) y `odin service status`

## Description

Registrar el subcomando `service` en `build_parser` (`src/odin/cli.py`) con las acciones `run` y `status`:

- `run`: resuelve `--config`/`ODIN_CONFIG`, carga la configuración (`load_config`), exige `scheduler.enabled` (si es `false` → exit 2 con motivo), configura el logging, construye el `SchedulerStateStore` del Item 052 y arranca `SchedulerService` (Item 050) en primer plano. `SIGINT`/`SIGTERM` detienen limpio (shutdown del scheduler + escritura final del estado) y devuelven exit code 0; config inválida → 2; error interno → 1.
- `status`: lee el estado del Item 052 y presenta última ejecución, próximo disparo, salud y errores recientes, con aviso si el proceso no corre (`stale`) o no hay estado. Es una consulta: devuelve 0 mientras la lectura sea posible (la salud va en la salida, no en el exit code).

Para que el CLI sea testeable con dobles desde este item, el armado del servicio pasa por una fábrica inyectable (`service_factory`); la fábrica por defecto construye el runner real `PipelineCycleRunner` importándolo perezosamente dentro de su cuerpo (llega en el Item 054). `SchedulerService` acepta desde acá un `state_store` opcional: registra cada job al arrancar y persiste el desenlace de cada disparo (incluidas las omisiones), sin cambiar el comportamiento cuando no se inyecta (los tests del Item 050/051 siguen verdes).

## Acceptance Criteria

- [ ] `build_parser` registra `service` con `run`/`status`; `service` sin acción devuelve 2 con la ayuda de la acción.
- [ ] `odin service run` con `scheduler.enabled: false` → exit 2 con mensaje claro; config ilegible/JSON inválido → 2; falta `--config`/`ODIN_CONFIG` → 2.
- [ ] `odin service run` arranca el servicio, y ante `KeyboardInterrupt`/`SIGINT`/`SIGTERM` ejecuta `shutdown()`, escribe el estado final y devuelve 0; un error inesperado de `start()` llega a `main` como exit 1 (con `shutdown` y estado final garantizados en `finally`).
- [ ] Los handlers de `SIGINT`/`SIGTERM` se instalan solo en el hilo principal y se restauran al salir; la instalación de señales no rompe si no es posible.
- [ ] `SchedulerService(state_store=...)` registra los jobs al construir y, al terminar cada `run_job` (éxito, fallo u omisión), actualiza y persiste el estado con el próximo disparo; sin `state_store` el comportamiento es idéntico al actual.
- [ ] `odin service status` imprime servicio en ejecución/detenido/sin estado, pid, config, jobs con schedule y próximo disparo, último ciclo por job (estado, bases, duración, correo) y errores recientes con tope; exit 0.
- [ ] `tests/test_cli.py`: parser/exit codes, `run` con doble de `SchedulerService` (arranque, señal simulada, shutdown, estado final), `status` vigente/obsoleto/ausente y handler de señales restaurado; la suite no queda bloqueada.
- [ ] Gates en verde: `uv run pytest`, `uv run ruff check src/odin tests`, `uv run mypy src/odin`.

## Implementation Steps

1. Agregar el subparser `service` con `run`/`status` y despacho en `main`.
2. Implementar `_cmd_service_run` (validación de config, logging, store, fábrica inyectable, señales, shutdown/estado final) y `_cmd_service_status` (carga de config, `load_state`, render).
3. Implementar `render_service_status` en `scheduler.py` (en ejecución/detenido/sin estado, salud y errores) y el context manager de señales en `cli.py`.
4. Cablear `state_store` en `SchedulerService` (registro de jobs, `_complete` de cada desenlace con próximo disparo, persistencia).
5. Tests en `tests/test_cli.py` (dobles, sin SMTP ni red) y de la integración servicio↔estado en `tests/test_scheduler.py`.
6. Documentar decisiones y evidencia en "Decisions & Trade-offs" y actualizar `docs/aide/progress.md`.

## Testing Strategy

- `main(["service"])` → 2 y ayuda con `run`/`status`; `main(["service", "run"])` sin config → 2; config con `enabled: false` → 2.
- `run` con `service_factory` doble que registra `start`/`shutdown`: `start` levanta `KeyboardInterrupt` → exit 0, `shutdown` llamado y `scheduler_state.json` final presente y parseable.
- `_stop_signals`: dentro del contexto, invocar el handler instalado de `SIGTERM` levanta `KeyboardInterrupt`; después del contexto los handlers vuelven a los anteriores.
- Servicio real + store (sin arrancar el scheduler): `run_job` con runner doble persiste el estado y actualiza `next_fire_time`; sin store no se crea archivo.
- `status`: estado escrito por el store con `pid=os.getpid()` → salida "en ejecución" con job y próximo disparo; pid imposible → "detenido"; sin archivo → "sin estado"; ambos exit 0.
- Gates completos del batch.

## Dependencies

- Items 050/051 (`SchedulerService`) y 052 (`SchedulerStateStore`, `load_state`, `state_path`).

## Decisions & Trade-offs

- **`run` exige `scheduler.enabled: true`**: arrancar en primer plano un scheduler que la configuración declara deshabilitado es contradictorio; se trata como error de configuración (exit 2) con mensaje explícito, en línea con el criterio del Item 006 (no crear `work_dir` ni efectos antes de fallar: el test verifica que no se escribió estado). Los jobs vacíos sí se permiten (el servicio queda a la espera, igual que el núcleo del Item 050).
- **Señales vía `KeyboardInterrupt` en el hilo principal**: `BlockingScheduler.start()` bloquea en el hilo principal; un handler que levanta `KeyboardInterrupt` convierte `SIGINT` y `SIGTERM` en el mismo camino de salida, que `_cmd_service_run` captura para hacer un shutdown limpio con exit 0. Los handlers previos se restauran en el `finally` del context manager y fuera del hilo principal (tests embebidos) no se toca el estado global de señales. Un `KeyboardInterrupt` directo (tests con doble) recorre exactamente el mismo camino.
- **Estado final garantizado**: el estado inicial se persiste tras construir el servicio (los jobs ya están registrados por el núcleo) y el final en un `finally` que corre también si `start()` lanza algo imprevisto —en ese caso la excepción llega a `main` y sale 1, pero el archivo queda consistente—. No se agrega un `stopped_at` al esquema: la vigencia la define la vida del `pid` (Item 052), que es lo que `status` consulta.
- **`status` es una consulta y devuelve 0**: la salud va en la salida (en ejecución / detenido / sin estado), no en el exit code; reservar un código para "no corre" chocaría con la convención 1=interno y complicaría el uso desde scripts. La salida siempre se imprime, incluso con el archivo corrupto (muestra el motivo).
- **`state_store` opcional en `SchedulerService`**: el parámetro con default `None` mantiene intactos los Items 050/051 (sin store no hay I/O ni cambios de comportamiento) y concentra la persistencia en `_complete`, por el que pasan **todas** las salidas de `run_job` (éxito, fallo, omisión por solapamiento y por misfire). El próximo disparo sale de `Job.next_run_time` (autoritativo con el scheduler vivo) con el cálculo del registro como respaldo en frío.
- **Fábrica inyectable y runner diferido**: `service_factory` permite testear el CLI con un doble sin arrancar APScheduler; la fábrica real importa `PipelineCycleRunner` dentro de su cuerpo (Item 054) con un `# type: ignore[attr-defined]` temporal que el propio Item 054 retira al definir la clase. Alternativa descartada: mover el runner a este item, que rompería la asignación de la queue.

**Evidencia:** `uv run pytest tests/test_cli.py tests/test_scheduler.py tests/test_scheduler_state.py -q` → **112 passed** (parser y exit codes de `service`, `run` con doble que simula la señal → exit 0 + shutdown + estado final con `pid` y jobs, `run` con retorno limpio, error interno de `start()` → exit 1 con shutdown y estado escritos, handlers de señal instalados/restaurados, `status` en ejecución/detenido/sin estado, servicio real con store persistiendo ciclo y próximo disparo —y sin store no escribe archivo—); `uv run ruff check src/odin tests` → All checks passed; `uv run mypy src/odin` → Success (14 source files).

## Prerequisites

- No requiere servicios externos (solo filesystem temporal; señales simuladas con dobles).
- `docs/aide/progress.md` debe ser actualizado a 🚧 al iniciar.
- Al finalizar, actualizar `docs/aide/progress.md` a ✅.

# Item 065: Runner compartido del servicio y arranque/detención limpia del scheduler

## Description

Crear `src/odin/service/runner.py` con `ServiceRunner`: la pieza que comparten
`odin service run` en primer plano, la unit systemd y el `SvcDoRun` de Windows.
Hoy esa lógica vive en `cli._cmd_service_run` (`cli.py:803-856`) y no es
reutilizable por el modo residente (Item 061 ya la espera: `windows.py:122-135`
importa `odin.service.runner` y busca `ServiceRunner`).

- **Construcción**: `ServiceRunner(config_path=None, *, console: bool = False,
  service_factory=None)`. Carga y valida la config de la ruta fijada en la
  instalación; en primer plano el CLI resuelve `--config`/`ODIN_CONFIG` y pasa
  la ruta (o `None`, que produce el mismo mensaje de fuente ausente de hoy).
  `config.scheduler.enabled: false` → mensaje claro y `EXIT_CONFIG` (2).
- **Logging** (Item 064): `setup_logging(config, console=console)` con la misma
  postura tolerante del CLI si el destino no es operable (advertencia y
  seguir); con `console=False` el bloque completo del servicio corre dentro de
  `redirect_stdio_to_log(<resolved_log_dir>/odin.log)`. El hook
  `on_config_reloaded` re-ejecuta `setup_logging` con el mismo `console`
  (idempotente) para que la recarga en caliente conserve la modalidad.
- **Servicio real** (fábrica por defecto): `SchedulerStateStore` (pid,
  `config_path`, `started_at`, máscara de secretos, `state_path(work_dir)`) +
  `SchedulerService` con `PipelineCycleRunner` (fábrica `build_scheduler_service`
  reutilizable por el CLI en foreground con `console=True`).
- **`run()` bloqueante** que devuelve exit code (`0` cierre limpio, `2` config)
  e **`stop()` thread-safe e idempotente** para el hilo del SCM o la señal del
  gestor: marca la parada, `SchedulerService.shutdown()` + `store.save()` +
  log de cierre, y una segunda invocación es no-op.
- **Ajuste en `SchedulerService`**: `shutdown()` antes de `start()` debe
  impedir que el scheduler arranque (bandera `threading.Event` propia), para
  cerrar la carrera real «el gestor pide parar justo cuando el proceso
  arranca» sin depender del timing.
- **Refactor del CLI**: `_cmd_service_run` delega en el runner conservando
  señales (`SIGINT`/`SIGTERM` → cierre limpio exit 0; `SIGUSR1` → recarga),
  exit codes y estado actuales; `_stop_signals`/`_reload_signal` se mueven al
  runner junto con sus tests.

Los exit codes del runner son el contrato del CLI (`0/1/2`); el módulo define
constantes locales y un test guarda su igualdad con `odin.cli.EXIT_*` para que
no deriven (el runner no importa el CLI: la dependencia sería invertida).

## Acceptance Criteria

- [x] `src/odin/service/runner.py` expone `ServiceRunner` con `run() -> int` y
      `stop() -> None`, y cumple el `ServiceRuntime` del Item 059.
- [x] `run()` carga la config: fuente ausente → mensaje de
      `--config`/`ODIN_CONFIG` y 2; JSON/estructura inválida (`ConfigError`) →
      mensaje y 2; `scheduler.enabled: false` → mensaje y 2, sin escribir
      estado.
- [x] `run()` con `console=False` configura el logging **sin** `StreamHandler`
      y redirige `sys.stdout`/`sys.stderr` al `odin.log` durante el servicio;
      con `console=True` conserva la consola (sin redirección).
- [x] `run()` persiste el estado inicial (`scheduler_state.json` con pid,
      config y jobs) antes de arrancar y el final al salir.
- [x] `stop()` desde otro hilo detiene un `SchedulerService` real bloqueado en
      `start()` dentro de un timeout, persiste el estado final y es
      idempotente (segunda llamada no-op). Un `stop()` previo al `run()`
      devuelve 0 sin arrancar el scheduler.
- [x] `SchedulerService.shutdown()` antes de `start()` impide el arranque
      (test unitario del scheduler) y `start()`/`shutdown()` siguen siendo
      idempotentes como hoy.
- [x] El hook de recarga vuelve a configurar el logging (nivel nuevo vigente
      tras `process_reload`) con la misma modalidad de consola.
- [x] `_cmd_service_run` delega en `ServiceRunner` sin cambiar su contrato
      externo: `tests/test_cli.py` (señales, exit codes, estado) sigue verde.
- [x] `tests/test_service_runner.py` cubre: arranque/parada desde hilos con
      `SchedulerService` real y `cycle_runner` doble dentro de timeout,
      `stop()` doble no-op, config inválida sin arrancar, hook de recarga y
      smoke del contrato limpio `run()`/`stop()` (el que pide la Etapa 7).
- [x] Gates del item en verde: `uv run pytest tests/test_service_runner.py
      tests/test_cli.py tests/test_scheduler.py`,
      `uv run ruff check src/odin tests`, `uv run mypy src/odin`.

## Implementation Steps

1. Escribir `src/odin/service/runner.py`: constantes de exit code, helpers de
   logging, `ServiceRunner` (`run`, `stop`, fábrica por defecto) y la
   traslación de `_stop_signals`/`_reload_signal`.
2. Ajustar `SchedulerService` (`scheduler.py`): bandera de parada previa en
   `__init__`, chequeo en `start()` y `set` en `shutdown()`.
3. Refactorizar `cli.py`: `_cmd_service_run` delega en el runner;
   `_build_scheduler_service` delega en la fábrica compartida; retirar los
   context managers movidos.
4. Crear `tests/test_service_runner.py`; actualizar `tests/test_cli.py`
   (imports/traslado de los dos tests de señales) y agregar el test de
   parada-previa en `tests/test_scheduler.py`.
5. Correr los gates del item y documentar decisiones/evidencia.

## Testing Strategy

- `uv run pytest tests/test_service_runner.py tests/test_cli.py
  tests/test_scheduler.py -q`.
- Runner: `SchedulerService` real con `cycle_runner` doble y trigger
  interval acelerado (`modify_job`), arrancado en un hilo y detenido con
  `runner.stop()` desde el hilo principal dentro de un timeout; estado final
  persistido y `stop()` dos veces sin error.
- Fábricas inyectadas (`service_factory`) para capturar el servicio y forzar
  desenlaces (`start()` que lanza `KeyboardInterrupt`, `start()` que retorna);
  config inválida con JSON roto y `scheduler.enabled: false`.
- Logging: `console=False` deja un solo handler de archivo (sin
  `StreamHandler`) y el hook de recarga aplica el nivel nuevo; con
  `console=True` no hay redirección de stdio.
- Sin systemd/SCM/pywin32: todo con procesos e hilos locales y `tmp_path`.

## Dependencies

- Items 052/053/054/055 (`SchedulerService`, `SchedulerStateStore`,
  `PipelineCycleRunner`, recarga) y Item 064 (`setup_logging(console=...)`,
  `redirect_stdio_to_log`).
- Contrato `ServiceRuntime`/`ServiceManager` del Item 059 y consumidores
  Item 061 (`SvcDoRun`/`SvcStop`) y Item 060 (`ExecStart` de la unit).
- Insumos: `queue-007.md` (Lote C) y `docs/aide/roadmap.md` (Etapa 7).

## Decisions & Trade-offs

- **El runner no importa `odin.cli`**: replicar el contrato de exit codes
  (0/1/2) como constantes locales evita la dependencia invertida
  servicio → CLI; `test_runner_exit_codes_match_cli_contract` guarda la
  igualdad con `odin.cli.EXIT_*` para que no deriven en silencio.
- **`console` es un parámetro del constructor, no un modo global**: default
  `False` (modo residente: solo archivo + stdio redirigido); la CLI en primer
  plano construye con `console=True` y conserva el contrato del Item 064. La
  fábrica `build_scheduler_service` recibe el mismo flag para que la recarga en
  caliente re-aplique el logging en la modalidad correcta.
- **`_stop_signals`/`_reload_signal` viven en el runner**: el runner es quien
  corre el ciclo de vida (foreground, systemd y SCM) y los necesita; la CLI
  delega. Los dos tests unitarios de los context managers se trasladaron de
  `tests/test_cli.py` a `tests/test_service_runner.py` (misma cobertura, ahora
  junto al consumidor) y `cli.py` ya no importa `threading`/`contextmanager`.
- **`SchedulerService` gana una parada previa al arranque**: `shutdown()` marca
  un `threading.Event` aunque el scheduler no esté corriendo y `start()` lo
  consulta antes de bloquear el `BlockingScheduler`. Sin esto, un `stop()` del
  gestor que llega en la ventana entre el chequeo del runner y `start()` se
  perdía y el proceso quedaba bloqueado para siempre (el `SvcStop` del SCM o
  el `SIGTERM` de systemd esperan la salida). El proceso no reinicia un
  `SchedulerService` ya detenido: el ciclo de vida es arrancar/parar una vez.
- **`stop()` persiste el estado además del `finally` de `run()`**: ambos
  caminos (`SchedulerService.shutdown()` y `store.save()`) son idempotentes y
  `save()` usa escritura atómica bajo lock, así que el doble guardado no
  corrompe nada y garantiza que el gestor vea el estado final incluso si el
  hilo del scheduler tarda en desbloquearse.
- **La parada se registra una sola vez**: `_stopped` (bajo lock) hace que las
  llamadas repetidas de `stop()` sean no-op y evita logs duplicados; el conteo
  `shutdown_calls == 2` del test de hilo (una del `stop()`, otra del `finally`)
  documenta el contrato.
- **La CLI conserva `_build_scheduler_service` como punto de inyección**: los
  tests de `test_cli.py`/`test_scheduler_foreground.py` lo monkeypatchean; su
  cuerpo ahora delega en `build_scheduler_service(..., console=True)` para que
  no existan dos construcciones del servicio.

**Evidencia:** `uv run pytest tests/test_service_runner.py -q` → **13 passed**
(arranque/parada entre hilos con `SchedulerService` real y trigger acelerado
sin cuelgue, `stop()` doble no-op, `stop()` previo al `run()`, fallo interno
con shutdown/estado, fuente ausente / `ODIN_CONFIG` / JSON roto / scheduler
deshabilitado, logging residente con stdio redirigido y primer plano con
consola, hook de recarga de la fábrica real, contrato de exit codes y los dos
context managers de señal); `uv run pytest tests/test_cli.py
tests/test_scheduler.py tests/test_scheduler_state.py -q` → **150 passed**;
`uv run pytest tests/test_scheduler_foreground.py
tests/test_scheduler_integration.py tests/test_service_base.py
tests/test_service_windows.py tests/test_service_status.py -q` → **61 passed
+ 1 skipped** (demo de cadencia real gated); `uv run ruff check src/odin tests`
→ All checks passed; `uv run mypy src/odin` → Success: no issues found in 19
source files.

## Prerequisites

- No requiere systemd, Windows ni pywin32 (los tests corren en Linux sin red).
- No requiere Firebird/SFTP/SMTP: las fases externas se doblan con
  `service_factory`/`cycle_runner` dobles.
- `docs/aide/progress.md` debe reflejar el avance (📋 → 🚧 → ✅) al completar.
- Al finalizar, actualizar `docs/aide/progress.md` con la evidencia del item.

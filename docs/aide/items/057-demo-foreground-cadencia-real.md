# Item 057: Demo end-to-end en foreground con cadencia real de 1–2 minutos

## Description

Cubrir el criterio de aceptación de la Etapa 6 ("proceso foreground con job cada
1–2 minutos ejecuta el flujo completo y envía el correo por ciclo") con un test
de integración `tests/test_scheduler_foreground.py` (marcado
`@pytest.mark.integration`) que ejercita `odin service run` **real** —mismo
`cli.main`, `SchedulerService`, `PipelineCycleRunner`, `run_pipeline` y
`EmailNotifier` que producción— contra el catcher SMTP in-process del Item 047
(`tests/smtp_catcher.py`), con fases externas dobladas (respaldo, compresión,
transferencia y retención) para no depender de gbak/Firebird/SFTP.

El archivo contiene tres casos:

1. **Ciclos en primer plano (suite por defecto, rápido)**: `cli.main(["service",
   "run", …])` corre en un hilo de fondo (fuera del hilo principal los
   contextos de señal no tocan `signal`, así que pytest no se ve afectado) con
   `schedule: "* * * * *"`; una vez arrancado el scheduler, el test acorta la
   cadencia del job registrado con `modify_job`/`IntervalTrigger` (reloj real,
   disparo real de APScheduler) y espera **dos ciclos**: dos correos
   `[ODIN] ÉXITO` (uno por ciclo), `scheduler_state.json` actualizado tras cada
   ciclo, `odin service status` coherente **mientras corre** y parada limpia
   (`service.shutdown()` + `main` → `EXIT_OK`).
2. **Parada limpia con SIGTERM (suite por defecto, rápido)**: lanza un proceso
   real (`python -m odin.cli service run`) con un horario que no dispara durante
   el test, verifica el estado y `odin service status` en ejecución con el pid
   del hijo, envía `SIGTERM` y exige salida 0 y estado final persistido.
3. **Cadencia real de 1 minuto (gated)**: el mismo montaje del caso 1 pero sin
   acortar la cadencia: cron `* * * * *` real y espera de hasta ~150 s a que
   lleguen los dos correos. Se ejecuta solo con `ODIN_FOREGROUND_DEMO=1` (se
   salta por defecto para no penalizar la suite con ~2 minutos) y es la
   automatización exacta de la demo manual.

Además, el README documenta el procedimiento de demo manual (config con
`schedule` de 1–2 minutos, `odin service run`, dos correos, `odin service
status`, parada con `Ctrl+C`/SIGTERM) y cómo correr la variante gated.

## Acceptance Criteria

- [x] `tests/test_scheduler_foreground.py` existe, está marcado
      `@pytest.mark.integration` y sus casos por defecto no requieren servicios
      externos (SMTP in-process sobre loopback; fases dobles); el caso de
      cadencia real se salta con motivo claro si `ODIN_FOREGROUND_DEMO != 1`.
- [x] Caso 1: dos ciclos reales del scheduler entregan 2 correos
      `[ODIN] ÉXITO` al catcher (asunto, base `OK`, servidor `OK`, totales);
      `scheduler_state.json` tiene el ciclo tras cada correo
      (`last_cycle.status == SUCCESS`, `notification_sent is True`,
      `updated_at` avanza entre ambos snapshots); `odin service status` impreso
      mientras el servicio corre muestra `en ejecución (pid …)`, `Salud: OK`,
      `job-0` y `Último ciclo: success`; la parada limpia deja el hilo terminado
      y `main` devuelve `EXIT_OK`; sin secretos (`masterkey`,
      `remote-secret-1`, `smtp-secret`) en mensajes, `odin.log` ni estado.
- [x] Caso 2: con el proceso real en primer plano, `odin service status`
      devuelve 0 y muestra `en ejecución` con el pid del hijo; `SIGTERM`
      termina el proceso con exit code 0; el estado final conserva el pid del
      hijo y un `updated_at` no anterior al inicial, y tras la salida
      `load_state(...).stale is True`; no queda `scheduler_reload.request`.
- [x] Caso 3 (gated): con `ODIN_FOREGROUND_DEMO=1` y cron real `* * * * *`,
      llegan 2 correos en ~2 minutos, el estado registra ambos ciclos y la
      parada es limpia con `EXIT_OK`.
- [x] `README.md` documenta la demo manual con cadencia de 1–2 minutos y el
      comando de la variante gated; sin promesas fuera de lo verificado.
- [x] Gates en verde: `uv run pytest`,
      `uv run pytest tests/test_scheduler_foreground.py -q`,
      `uv run ruff check src/odin tests`, `uv run mypy src/odin`.

## Implementation Steps

1. Crear `tests/test_scheduler_foreground.py` con el helper de config derivado
   del fixture Linux (mismo patrón que `tests/test_scheduler_integration.py`:
   `work_dir`/`log_dir` en `tmp_path`, `retention_days: 0`, un servidor,
   `notification.smtp` apuntando al catcher y el bloque `scheduler` con
   `timezone`, un job `erp_principal`, `schedule "* * * * *"`, `on_misfire:
   run_once` y `skip_if_running: true`), los dobles de fase y un fixture
   autouse que limpia los handlers del logger `odin`.
2. Caso 1: doblar `odin.pipeline.{BackupExecutor,CompressionExecutor,
   TransferExecutor,RetentionExecutor}` (clases, no instancias) para que el
   cableado real `main → _build_scheduler_service → PipelineCycleRunner() →
   run_pipeline` use dobles sin tocar la CLI; monkeypatch de
   `odin.cli._build_scheduler_service` con un wrapper que delega en la fábrica
   real y registra el `SchedulerService` creado; correr `main(["service","run",
   "--config", ruta])` en un `threading.Thread`; esperar a que el scheduler
   esté `running`; `modify_job("job-0", trigger=IntervalTrigger(seconds=2))`;
   esperar los correos con deadline y snapshots de estado entre ambos; llamar
   `main(["service","status", …])` y verificar la salida; `service.shutdown()`,
   `join` del hilo y `EXIT_OK`; asserts de estado final, secretos y artefactos.
3. Caso 2: `subprocess.Popen([sys.executable, "-m", "odin.cli", "service",
   "run", "--config", ruta], stdout=PIPE, stderr=STDOUT)` con un `schedule` que
   no dispara durante el test; esperar el estado con el pid del hijo y la línea
   "Scheduler iniciado" del log; `odin service status` como subproceso (0 y
   `en ejecución`); `SIGTERM` y `wait` con exit code 0; verificar estado final,
   `stale` y ausencia de archivos de control; cerrar el proceso en `finally`.
4. Caso 3: factorizar el montaje del caso 1 para reutilizarlo con la cadencia
   real (sin `modify_job`) y el `skipif` de `ODIN_FOREGROUND_DEMO`; deadline de
   ~150 s.
5. README: agregar la sección "Scheduler interno y modo servicio en primer
   plano" con la subsección de demo manual (config de 1–2 minutos, comandos,
   resultado esperado, parada) y el comando de la variante gated; el Item 058
   completa el resto de la sección.
6. Documentar decisiones y evidencia en "Decisions & Trade-offs" y actualizar
   `docs/aide/progress.md`.

## Testing Strategy

- Caso 1: `assert len(catcher.messages) == 2` con ambos asuntos `[ODIN] ÉXITO`
  y cuerpos con `Estado global: ÉXITO`, `- erp_principal: OK`, `sitio-alterno-1:
  OK` y `Totales: 1/1 base(s) OK`; `load_state` tras el primer y el segundo
  correo con `last_cycle` poblado, `updated_at` del segundo >= del primero y
  `recent_errors == ()`; salida de `service status` con `en ejecución`, `Salud:
  OK` y `Último ciclo: success`; `thread.join(15)` sin hilo vivo; `code ==
  EXIT_OK`; ausencia de los tres secretos en mensaje, log y estado.
- Caso 2: `load_state` con `pid == process.pid` antes del SIGTERM y
  `updated_at >= started_at`; `service status` con `en ejecución (pid …)`;
  `process.wait(15) == 0`; `load_state(...).stale is True` después; sin
  `work_dir/scheduler_reload.request`.
- Caso 3: igual que el caso 1 pero con deadline de 150 s y sin `modify_job`;
  ejecutarlo a mano una vez con `ODIN_FOREGROUND_DEMO=1` como evidencia y
  confirmar que en la suite por defecto aparece como `skipped`.
- Gates completos del batch (`uv run pytest`, `ruff`, `mypy`).

## Dependencies

- Items 049-056 (scheduler, estado, CLI `service run|status|reload`, runner
  real e integración con el catcher), `tests/smtp_catcher.py` (Item 047) y el
  pipeline de las Etapas 2-5 (`run_pipeline`).

## Decisions & Trade-offs

- **Doble variante para la cadencia**: la suite por defecto no puede permitirse
  ~2 minutos por corrida, así que el caso de ciclos en primer plano acorta la
  cadencia una vez arrancado el servicio (`SchedulerService.scheduler.modify_job`
  con un `IntervalTrigger` de 2 s) y la demo literal con cron `* * * * *` queda
  en un caso gated (`ODIN_FOREGROUND_DEMO=1`). El disparo sigue siendo real de
  APScheduler y el reloj real; la semántica de cron/trigger ya está fijada por
  los Items 049-051. El caso gated se ejecutó una vez durante el item como
  evidencia y en la suite por defecto aparece `skipped`.
- **`next_run_time` explícito al acortar la cadencia**: `modify_job` con un
  trigger nuevo **no** recalcula `next_run_time` (el `Job._modify` de
  APScheduler 3.11 conserva el próximo disparo viejo), de modo que sin pasarlo
  el test quedaba pegado al límite de minuto del cron y era flaky (un ciclo en
  ~25 s o hasta ~60 s de espera, por encima del deadline de 30 s). Se pasó
  `datetime.now(service.timezone)`: primer ciclo inmediato y luego cada 2 s.
  Esa fue la única corrección necesaria durante la implementación.
- **Montaje in-process con la CLI real**: `main(["service", "run", …])` corre
  en un hilo de fondo (fuera del hilo principal `_stop_signals`/`_reload_signal`
  no tocan señales globales, así que pytest no se ve afectado), con la fábrica
  real instrumentada por monkeypatch para capturar el `SchedulerService` y
  poder pararlo con `service.shutdown()` — el mismo camino que el `finally` de
  `_cmd_service_run` usa tras SIGINT/SIGTERM. La verificación real de SIGTERM
  la cubre el caso subprocess, que envía la señal al proceso hijo y exige 0.
- **Fases externas dobladas sin duplicar la CLI**: se parchean las **clases**
  `odin.pipeline.{BackupExecutor,CompressionExecutor,TransferExecutor,
  RetentionExecutor}`, de modo que `_build_scheduler_service →
  PipelineCycleRunner() → run_pipeline` queda tal cual producción y solo se
  sustituyen los procesos externos (gbak/7z/SFTP); el SMTP es real sobre
  loopback. Los dobles son locales al archivo (patrón del proyecto de no
  acoplar módulos de test), aunque repitan la forma de los del Item 056.
- **Caso SIGTERM con horario que no dispara**: el subprocess usa
  `schedule: "0 3 1 1 *"` para que el test sea determinista (sin ciclos ni
  intentos de gbak real durante la ventana); el foco del caso es el ciclo de
  vida del proceso (estado → `status` → SIGTERM → 0), no la cadencia, que ya
  cubren los otros dos casos. Se salta en Windows porque `SIGTERM` no modela
  la parada del servicio allí.
- **`stale` tras la salida**: después del SIGTERM el estado conserva el pid del
  hijo y `load_state` lo marca obsoleto (`pid_is_alive`), lo que prueba que la
  parada fue un shutdown limpio y no un estado perdido.

**Evidencia:** `ODIN_FOREGROUND_DEMO=1 uv run pytest tests/test_scheduler_foreground.py -q -rs --durations=5` → **3 passed in 82.39 s** (caso de cadencia real `* * * * *`: 78.63 s con dos ciclos y dos correos; caso de ciclos acortados: 2.56 s; caso SIGTERM: 1.00 s); `uv run pytest tests/test_scheduler_foreground.py -q` → **2 passed + 1 skipped in ~3.7 s** (repetido 3 veces, estable); `uv run pytest tests/test_scheduler_foreground.py tests/test_scheduler_integration.py tests/test_scheduler.py tests/test_scheduler_state.py tests/test_cli.py -q` → **132 passed + 1 skipped in 6.44 s**; `uv run ruff check src/odin tests` → All checks passed; `uv run mypy src/odin` → Success (14 source files). README: sección "Scheduler interno y modo servicio en primer plano" con la demo manual de 1–2 minutos y el comando `ODIN_FOREGROUND_DEMO=1`.

## Prerequisites

- No requiere servicios externos: SMTP in-process sobre loopback y fases
  dobles. El caso gated solo necesita el reloj real (sin Docker ni gbak).
- `docs/aide/progress.md` debe ser actualizado a 🚧 al iniciar.
- Al finalizar, actualizar `docs/aide/progress.md` a ✅.

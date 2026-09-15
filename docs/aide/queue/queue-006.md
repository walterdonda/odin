# Queue 006 — Scheduler interno (Etapa 6 del roadmap)

> **Paso 4 del flujo AIDE.** Lote de 10 work items priorizados desde `docs/aide/roadmap.md` y `docs/aide/progress.md`. Cubre la Etapa 6: scheduler propio sobre APScheduler que dispara el flujo completo según el bloque `scheduler` del JSON, políticas de solapamiento y misfire, recarga en caliente y los subcomandos `odin service run` / `odin service status`. Dimensión total: ~1 semana.
>
> **Agrupación de implementación:** los items se ejecutan en 4 lotes por afinidad de contexto (misma superficie de archivos). Cada lote se ejecuta en una sesión con `/speckit.aide.execute-batch <items>` (ver el comando exacto en cada lote), que crea los specs faltantes, implementa item por item y actualiza el progreso. La numeración de items no cambia.
>
> **Estado de partida:** la Etapa 5 quedó cerrada (`odin run` = respaldo → compresión → transferencia → correo → retención, suite 410 passed + 2 skipped). `src/odin/scheduler.py` no existe y `odin service` no está registrado en la CLI (`build_parser` deja el punto de extensión documentado en `cli.py:94-104`). Ya existen desde la Etapa 1: `SchedulerConfig`/`SchedulerJob`/`MisfirePolicy` (`config.py:204-220`, `78-86`) con `timezone` validada vía `ZoneInfo` y `jobs[].databases` contrastado contra las bases reales; `_parse_job` solo verifica que `schedule` tenga 5 campos (`config.py:799-805`), sin validar la expresión cron; `validate.py:516-548` reporta enabled/jobs/cobertura. `run_pipeline(config, *, backup, compression, transfer, notifier, retention)` (`pipeline.py:182`) es la pieza completa a reutilizar por ciclo (envía correo siempre y corre la retención al final). El Item 008 verificó `apscheduler 3.11.3` en Python 3.14 (lockeado) y difirió a esta etapa la decisión 3.x vs 4.x vs stdlib: **punto de partida = APScheduler 3.x**, a confirmar/documentar en el Item 050. El smoke multiplataforma (Item 009) sigue pendiente y queda delegado a la Etapa 8 por no ser verificable localmente.

---

## Lote A — Horarios y núcleo del scheduler (`src/odin/scheduler.py`, `src/odin/config.py`)

> Items 049, 050 y 051. Validación estricta de cron + helpers de calendario, el servicio de scheduling sobre APScheduler y las políticas de solapamiento/misfire. Todo gira alrededor del módulo nuevo `scheduler.py` y su superficie de tests.
>
> **Comando:** `/speckit.aide.execute-batch 049-051`

### Item 049: Validación estricta de cron/timezone y cálculo de próximos disparos
Crear `src/odin/scheduler.py` con los helpers de calendario: `cron_trigger(schedule, timezone)` construido sobre `apscheduler.triggers.cron.CronTrigger.from_crontab` (serie 3.x del lock, Item 008) y `next_fire_times(trigger, now, count)` determinista con `now` inyectable. Cablear la validación real en `config.py`: `_parse_job`/`_parse_scheduler` (`config.py:784-838`) deben rechazar con `field_path` y mensaje claro toda expresión inválida o fuera de rango (p. ej. `0 25 * * *`, `* * * *` de 4 campos, valores no cron), manteniendo la validación de `timezone` con `ZoneInfo` antes de construir el trigger. Extender `validate.py:_check_scheduler` para reportar el próximo disparo de cada job en la timezone global como verificación OK. Tests: `tests/test_config.py` (expresiones válidas/ inválidas por campo), `tests/test_scheduler.py` (próximo disparo con `now` fijo, caso DST si aplica) y `tests/test_validate.py` (mensaje con próximo disparo).

### Item 050: Núcleo de `SchedulerService` sobre APScheduler 3.x
Implementar en `src/odin/scheduler.py` el servicio de scheduling: `BlockingScheduler` con la `timezone` global del JSON, registro de un job APScheduler por cada `scheduler.jobs[]` (id estable, `CronTrigger` del Item 049, `max_instances=1`, `replace_existing=True`) y ciclo de vida `start()`/`shutdown()` limpio con logging. La ejecución de un job delega en un `cycle_runner` inyectable de interfaz `(Config, SchedulerJob) -> CycleOutcome` (el runner real llega en el Item 054): el núcleo no conoce el pipeline y es testeable sin red ni reloj real. Documentar en el docstring del módulo la decisión de implementación — APScheduler 3.11.3 (lockeado y verificado en Python 3.14 por el Item 008) por sobre 4.x y stdlib, con justificación. Tests en `tests/test_scheduler.py`: jobs registrados con trigger y próximo disparo esperados, timezone respetada, arranque/detención limpia y `cycle_runner` invocado con el job correcto.

### Item 051: Anti-solapamiento (`skip_if_running`) y políticas `on_misfire`
Implementar el registro in-flight por base a nivel de proceso (conjunto thread-safe con `threading.Lock`) que impide respaldos simultáneos de la misma base entre jobs distintos: al disparar se calculan las bases en vuelo; con `skip_if_running: true` (default) el ciclo se omite si alguna base del job está en ejecución; con `false` el ciclo corre solo con las bases libres (nunca se duplica una base). Toda omisión queda en el log y en el `CycleOutcome` con su motivo. Configurar `on_misfire` en APScheduler: `run_once` → `coalesce=True` + `misfire_grace_time=None` (una sola corrida al recuperar el servicio); `skip` → descarte de disparos vencidos, implementado con la latencia del disparo en el wrapper si `misfire_grace_time` no lo expresa; la semántica real de APScheduler 3.x queda fijada por tests. Tests: dos jobs que comparten base con `threading.Event` (el segundo se omite sin solaparse), `skip_if_running` en ambos valores, misfire con reloj falso/inicio simulado y política `skip`.

---

## Lote B — Estado, CLI y ciclo de ejecución (`src/odin/scheduler.py`, `src/odin/cli.py`)

> Items 052, 053 y 054. Archivo de estado consultable, los subcomandos `service run`/`service status` y el runner real del ciclo sobre `run_pipeline`. Un solo pase sobre `cli.py` y el cierre funcional del servicio.
>
> **Comando:** `/speckit.aide.execute-batch 052-054`

### Item 052: Estado del servicio en `work_dir` (`scheduler_state.json`)
Implementar el estado consultable por `odin service status`: dataclasses `ServiceState`/`CycleRecord` (versión de esquema, `pid`, `config_path`, `started_at`, `updated_at`, último ciclo por job con bases/estado/duración/correo, próximos disparos por job, errores recientes acotados) con escritura atómica (`tempfile` + `os.replace`) en `config.local.work_dir/scheduler_state.json`, sin secretos. Lectura tolerante: archivo ausente, JSON corrupto o esquema desconocido devuelven un resultado tipado con advertencia, nunca una excepción. Detección de estado obsoleto: si el `pid` ya no vive (POSIX `os.kill(pid, 0)`; en Windows se reporta el pid sin verificar) el estado se marca como no vigente. Tests en `tests/test_scheduler_state.py`: round trip, escritura atómica, corrupción/ausencia, ausencia de secretos y pid muerto.

### Item 053: CLI `odin service run` (foreground) y `odin service status`
Registrar el subcomando `service` en `build_parser` (`cli.py:94-158`) con acciones `run` y `status`: `run` carga y valida la config, configura el logging, arranca `SchedulerService` (Item 050) y queda bloqueante; SIGINT/SIGTERM detienen limpio (shutdown del scheduler + escritura final del estado) y devuelven exit code 0; config inválida → 2; error interno → 1 (mismos códigos de la CLI existente, documentados en el docstring del módulo). `status` lee el estado del Item 052 y presenta última ejecución, próximo disparo, salud y errores recientes, con aviso si el proceso no corre o no hay estado. Tests en `tests/test_cli.py` con `SchedulerService` doble (arranque/parada, señales, exit codes) y de render de `status` (vigente/obsoleto/ausente), sin dejar la suite bloqueada.

### Item 054: Ciclo de ejecución: pipeline por subconjunto de bases y resultado por ciclo
Implementar el `cycle_runner` real en `src/odin/scheduler.py`: filtrar `config.databases` por `job.databases`, construir la config del ciclo con `dataclasses.replace` e invocar `run_pipeline` (`pipeline.py:182`) con su propio correo por ciclo y su retención; devolver `CycleOutcome` (estado global, bases, duración, correo enviado, errores) para el estado del Item 052. Aislamiento: una excepción imprevista del pipeline no detiene el servicio y queda registrada; los logs del ciclo pasan por el enmascarado existente; cada ciclo es independiente del anterior. Tests con `run_pipeline` doble (éxito, parcial, fallo total, excepción) verificando el subconjunto exacto de bases, el resumen enmascarado, el `CycleOutcome` y que el servicio sigue operativo tras un ciclo fallido.

---

## Lote C — Recarga en caliente y verificación de integración

> Items 055 y 056. Recarga sin reinicio con validación previa, más el test de integración que ejercita el camino real del scheduler con el catcher SMTP efímero del Item 047.
>
> **Comando:** `/speckit.aide.execute-batch 055,056`

### Item 055: Recarga de configuración en caliente con validación previa
Implementar la recarga sin reinicio: en POSIX, manejador de `SIGUSR1` que marca una bandera thread-safe; en Windows (sin señales) vigilancia de un archivo de control `work_dir/scheduler_reload.request` con mtime; y el comando `odin service reload` que dispara la señal (POSIX) o crea el archivo de control (Windows) usando el `pid` del estado. Al procesar la recarga: `load_config` + `validate_config` sobre la ruta original; si la nueva config es válida se re-registran jobs/timezone y se recalculan los próximos disparos sin perder el servicio; si es inválida se mantiene la configuración vigente y se registra el motivo (log + estado + errores recientes). Tests: recarga válida actualiza jobs y disparos (helper del Item 049 con reloj fijo), recarga inválida conserva la config anterior y loguea, archivo de control consumido de forma idempotente y `reload` sin servicio corriendo falla con mensaje claro.

### Item 056: Test de integración del scheduler con SMTP efímero
Crear `tests/test_scheduler_integration.py` (marcado `@pytest.mark.integration`, skip seguro) reutilizando el catcher SMTP in-process del Item 047: un `SchedulerService` real con `run_pipeline` real y fases dobles (respaldo/compresión/transferencia) dispara por el camino real del scheduler y el correo con el resumen de cada ciclo llega al catcher; `scheduler_state.json` queda actualizado (última ejecución + próximo disparo) y no hay secretos en el mensaje ni en los logs. Caso adicional: un ciclo con fallo total envía informe FALLO y el servicio permanece operativo. Es el sustituto local y determinista de la demo de correo por ciclo.

---

## Lote D — Demo end-to-end y cierre de Etapa 6

> Items 057 y 058. La demo con cadencia real de 1–2 minutos que pide el criterio de aceptación, y la documentación/cierre con los gates de calidad.
>
> **Comando:** `/speckit.aide.execute-batch 057,058`

### Item 057: Demo end-to-end en foreground con cadencia real de 1–2 minutos
Cubrir el criterio de aceptación de la Etapa 6: `tests/test_scheduler_foreground.py` (marcado `@pytest.mark.integration`, skip seguro) que ejecuta `odin service run` en foreground con `schedule: "* * * * *"`, fases dobles (o el Firebird del contenedor del Item 018 si está disponible), catcher SMTP efímero y un ciclo de espera de ~2 minutos: verifica dos correos recibidos (uno por ciclo), estado actualizado con ambos ciclos, coherencia de `odin service status` mientras corre y parada limpia con SIGTERM (exit 0). Documentar en el README el procedimiento de demo manual con `schedule` de 1–2 minutos para el host sin Docker.

### Item 058: Documentación y cierre de la Etapa 6
Actualizar `README.md` con la sección "Scheduler interno y modo servicio en primer plano": bloque `scheduler` del JSON (`timezone`, `jobs`, `schedule`, `skip_if_running`, `on_misfire`), operación `odin service run|status|reload`, archivo de estado, recarga en caliente (SIGUSR1 / archivo de control / Windows), semántica de solapamiento y misfire, y relación con `odin run` one-shot. Revisar docstrings de `cli.py`/`scheduler.py` y la coherencia de `validate.py`. Verificar uno a uno los criterios de aceptación de la Etapa 6 del roadmap con evidencia (tests/salidas), correr los gates (`uv run pytest`, `uv run ruff check src/odin tests`, `uv run mypy src/odin`) y actualizar `docs/aide/progress.md` (Etapa 6 ✅ si los criterios quedan verificados), dejando anunciada la `queue-007` (Etapa 7 — Windows Service y daemon Linux) que arrancará en el item 059.

---

**Total: 10 items en 4 lotes.** Al completar este lote, el scheduler interno correrá en primer plano sobre APScheduler 3.x, disparará el pipeline completo por ciclo con su correo, respetará `skip_if_running`/`on_misfire`, se recargará en caliente y expondrá `odin service run|status|reload`. El siguiente lote (`queue-007.md`, Etapa 7) arrancará en el item 059.

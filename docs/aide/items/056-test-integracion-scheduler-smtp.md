# Item 056: Test de integración del scheduler con SMTP efímero

## Description

Crear `tests/test_scheduler_integration.py` (marcado `@pytest.mark.integration`)
que ejercita el camino real del ciclo del scheduler contra el **catcher SMTP
in-process** del Item 047: un `SchedulerService` real, con `PipelineCycleRunner`
real sobre `run_pipeline` real y fases dobles (respaldo, compresión,
transferencia y retención), dispara por la entrada real del scheduler
(`service.run_job(job_id)`, el mismo callable que APScheduler invoca) y el
correo con el resumen del ciclo —`EmailNotifier` real— llega al catcher; el
`scheduler_state.json` queda actualizado (último ciclo + próximo disparo) y no
hay secretos en el mensaje ni en los logs. Caso adicional: un ciclo con fallo
total envía el informe FALLO y el servicio permanece operativo (un segundo ciclo
vuelve a correr y a enviar).

Para reutilizar el catcher sin duplicarlo ni importar módulos de test entre sí,
se extrae el servidor SMTP de `tests/test_notify_integration.py` a un helper
compartido `tests/smtp_catcher.py` (`SmtpCatcher`, `parse_message`, `b64`,
`closed_port`); `test_notify_integration.py` pasa a importarlo y conserva sus
casos actuales. Es el sustituto local y determinista de la demo de correo por
ciclo (la cadencia real de 1-2 minutos queda para el Item 057).

## Acceptance Criteria

- [ ] `tests/smtp_catcher.py` contiene el servidor efímero y sus utilidades, y
      `tests/test_notify_integration.py` sigue verde usándolo (sin duplicar
      clases).
- [ ] `tests/test_scheduler_integration.py` está marcado
      `@pytest.mark.integration` y no requiere servicios externos (SMTP real
      sobre loopback in-process; fases dobles).
- [ ] Caso éxito: un `run_job("job-0")` del servicio real produce
      `outcome.status == SUCCESS` y `notification_sent is True`; el catcher
      recibe exactamente 1 mensaje con asunto `[ODIN] ÉXITO ...`, destinatario y
      remitente de la configuración, cuerpo con la base OK, el servidor OK y los
      totales.
- [ ] Estado: `scheduler_state.json` legible con el `last_cycle` del job
      (`SUCCESS`, bases, `notification_sent=True`) y `next_fire_time` no nulo;
      `recent_errors` vacío.
- [ ] Sin secretos (`masterkey`, `remote-secret-1`, `smtp-secret`) en el mensaje
      crudo, el cuerpo, `odin.log` ni `scheduler_state.json`.
- [ ] Caso fallo total: con el respaldo doble fallando, el ciclo devuelve
      `FAILURE`, el catcher recibe el informe `[ODIN] FALLO ...` con el motivo y
      el estado registra el error; al reponerse el doble, un segundo ciclo
      vuelve a ejecutarse y envía el informe de ÉXITO (servicio operativo).
- [ ] Gates en verde: `uv run pytest`,
      `uv run pytest tests/test_scheduler_integration.py tests/test_notify_integration.py`,
      `uv run ruff check src/odin tests`, `uv run mypy src/odin`.

## Implementation Steps

1. Extraer `SmtpCatcher`/`SmtpHandler`/`parse_message`/`b64`/`closed_port` a
   `tests/smtp_catcher.py` y actualizar `tests/test_notify_integration.py`.
2. Crear `tests/test_scheduler_integration.py` con: config derivada del fixture
   Linux (`work_dir` en `tmp_path`, SMTP → catcher, 1 servidor, job `job-0`),
   fases dobles (respaldo, compresión, transferencia, retención) y
   `SchedulerStateStore` real con la máscara de la config.
3. Test de éxito con `SchedulerService` real +
   `PipelineCycleRunner(backup=..., compression=..., transfer=..., retention=...)`
   y `EmailNotifier` real (default del pipeline); `setup_logging(config)` para
   verificar los logs y limpieza de handlers al salir.
4. Test de fallo total con respaldo doble conmutable y verificación de
   recuperación en el segundo ciclo.
5. Documentar decisiones y evidencia en "Decisions & Trade-offs" y actualizar
   `docs/aide/progress.md`.

## Testing Strategy

- Éxito: `outcome = service.run_job("job-0")`; asserts de outcome, catcher
  (1 mensaje, asunto/cuerpo con `Estado global: ÉXITO`, `- erp_principal: OK`,
  `sitio-alterno-1: OK`, `Totales: 1/1 base(s) OK`), `load_state(...)` con
  `last_cycle.status is CycleStatus.SUCCESS`, bases, correo y `next_fire_time`
  no nulo, `recent_errors == ()`, y ausencia de secretos en mensaje, log y
  estado.
- Fallo: primer `run_job` con el respaldo doble en fallo → `FAILURE`, mensaje
  `[ODIN] FALLO` con "gbak: error simulado" y `recent_errors` con el motivo;
  conmutar el doble a éxito → segundo `run_job` → `SUCCESS`, 2 mensajes en el
  catcher y estado final con `last_cycle` exitoso.
- Catcher cerrado y handlers de logging removidos en `finally`/fixtures
  autouse para no filtrar estado entre tests.
- Correr también `tests/test_notify_integration.py` para confirmar que la
  extracción no rompió el Item 047.

## Dependencies

- Item 047 (catcher SMTP efímero), Items 050-054 (servicio, estado, runner
  real) y pipeline de las Etapas 2-5 (`run_pipeline`).

## Decisions & Trade-offs

- **Catcher compartido en `tests/smtp_catcher.py`**: la extracción evita que un
  módulo de test importe a otro (`tests.test_notify_integration`) y deja el
  servidor disponible para futuros tests; al no llamarse `test_*.py`, pytest no
  lo recolecta. La API pública (`SmtpCatcher`, `parse_message`, `closed_port`)
  reemplazó a los nombres privados en `test_notify_integration.py`, que quedó
  verde sin duplicación.
- **Disparo por `service.run_job("job-0")`**: es exactamente el callable que
  APScheduler invoca en el hilo del executor, así que se ejercita el camino real
  del servicio (reserva in-flight, misfire, runner, estado) sin `sleep`s ni
  dependencia del reloj. La cadencia real de 1-2 minutos en foreground es el
  objeto del Item 057.
- **Pipeline real con fases dobles**: se usa el `run_pipeline` real (y el
  `EmailNotifier` real del default, sin inyectarlo) con `PipelineCycleRunner`
  y dobles de respaldo/compresión/transferencia/retención. La compresión doble
  escribe el `.fbk.7z` como copia del `.fbk`: el contrato que consume el
  pipeline es el artefacto con su ruta/tamaño, no el formato 7z (ya cubierto por
  los tests de la Etapa 3); el SMTP sí es real (protocolo sobre loopback).
- **Reloj fijo (`FIXED_NOW`) y `on_misfire: run_once`** del fixture: hacen
  determinista el `next_fire_time` persistido y evitan que el guard de misfire
  descarte el disparo del test.
- **Recuperación demostrada con un doble conmutable**: la misma instancia del
  respaldo doble falla en el primer ciclo y funciona en el segundo, probando que
  el servicio queda operativo tras un ciclo fallido (dos correos FALLO→ÉXITO,
  `last_cycle` final exitoso y el error del primer ciclo en `recent_errors`).
- **Sin `skipif`**: no hay Docker, gbak ni red externa que puedan faltar; el
  marcador `integration` queda por el protocolo SMTP real y el pipeline real,
  consistente con el criterio del Item 047.

**Evidencia:** `uv run pytest tests/test_scheduler_integration.py tests/test_notify_integration.py -q` → **4 passed + 1 skipped** (la variante Firebird por Docker del Item 047 se salta sin gbak; los 2 casos nuevos del scheduler pasan contra el catcher in-process: ÉXITO con estado actualizado y sin secretos en mensaje/log/estado, FALLO + recuperación con 2 correos); `uv run pytest tests/test_scheduler_integration.py tests/test_notify_integration.py tests/test_scheduler.py -q` → **44 passed + 1 skipped**; suite completa `uv run pytest -q` → **493 passed + 2 skipped**; `uv run ruff check src/odin tests` → All checks passed; `uv run mypy src/odin` → Success (14 source files).

## Prerequisites

- No requiere servicios externos ni Docker: el SMTP es in-process sobre loopback
  y todas las fases se doblan. No necesita `skipif` (no hay dependencia
  opcional), pero se marca `integration` por ejercitar protocolo SMTP real.
- `docs/aide/progress.md` debe ser actualizado a 🚧 al iniciar.
- Al finalizar, actualizar `docs/aide/progress.md` a ✅.

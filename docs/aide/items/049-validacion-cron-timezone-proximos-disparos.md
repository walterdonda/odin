# Item 049: Validación estricta de cron/timezone y cálculo de próximos disparos

## Description

Crear `src/odin/scheduler.py` con los helpers de calendario del scheduler interno: `cron_trigger(schedule, timezone)` construido sobre `apscheduler.triggers.cron.CronTrigger.from_crontab` (APScheduler 3.11.3, lockeado y verificado en Python 3.14 por el Item 008) y `next_fire_times(trigger, now, count)` determinista con `now` inyectable.

Cablear la validación real de cron en `config.py`: hoy `_parse_job` (`config.py:784`) solo verifica que `schedule` tenga 5 campos y nunca valida rangos ni sintaxis; debe rechazar toda expresión inválida o fuera de rango con `field_path` y mensaje claro (p. ej. `0 25 * * *`, `* * * *` de 4 campos, `not a cron`), manteniendo la validación de `timezone` con `ZoneInfo` (`_parse_scheduler`, `config.py:821`) **antes** de construir el trigger. `_parse_job` recibe la `ZoneInfo` ya validada (o `None` si la timezone global es inválida, en cuyo caso valida la expresión con UTC para reportar ambos problemas).

Extender `validate.py:_check_scheduler` (`validate.py:516`) para reportar el próximo disparo de cada job en la timezone global como verificación `OK` (check `scheduler_next_fire`), sin efectos secundarios y tolerante a expresiones sin próximo disparo.

## Acceptance Criteria

- [ ] `src/odin/scheduler.py` expone `cron_trigger(schedule: str, timezone: str) -> CronTrigger` y `next_fire_times(trigger, now: datetime, count: int) -> list[datetime]`; el cálculo es determinista con `now` inyectable (tz-aware) y devuelve menos de `count` elementos solo si el trigger no tiene más disparos.
- [ ] `load_config` rechaza expresiones cron inválidas con un `ConfigProblem` en `config.scheduler.jobs[N].schedule` y mensaje que incluye la causa (mínimo: hora fuera de rango `0 25 * * *`, número incorrecto de campos `* * * *`, texto no cron `not a cron`).
- [ ] La `timezone` sigue validándose con `ZoneInfo` en `config.scheduler.timezone`; una timezone desconocida no impide reportar además el problema de cron (validación con UTC de respaldo).
- [ ] `odin validate` agrega una verificación `OK` por job con el próximo disparo calculado en la timezone global (check `scheduler_next_fire`, campo `config.scheduler.jobs[N].schedule`); sin jobs, el comportamiento actual no cambia.
- [ ] Tests: `tests/test_config.py` (válidas/inválidas por campo), `tests/test_scheduler.py` (nuevo; próximo disparo con `now` fijo y caso DST), `tests/test_validate.py` (mensaje con próximo disparo).
- [ ] Gates en verde: `uv run pytest`, `uv run ruff check src/odin tests`, `uv run mypy src/odin`.

## Implementation Steps

1. Crear `src/odin/scheduler.py` con el docstring del módulo (decisión APScheduler 3.x se documenta en el Item 050), `cron_trigger` y `next_fire_times`; `previous=None` en el primer cálculo para no perder un disparo exactamente en `now`.
2. En `config.py`, importar `CronTrigger` y cambiar `_parse_job` para recibir la `ZoneInfo` (o `None`) y validar la expresión dentro de `try/except ValueError`; `_parse_scheduler` construye la `ZoneInfo` una sola vez y la pasa a cada job.
3. Extender `_check_scheduler` en `validate.py` con el próximo disparo por job (`cron_trigger` + `next_fire_times` con `datetime.now(ZoneInfo(timezone))`), encapsulando cualquier `ValueError` imprevisto en `WARNING` para no romper `validate`.
4. Crear `tests/test_scheduler.py` y ampliar `tests/test_config.py` / `tests/test_validate.py`.
5. Documentar decisiones y evidencia en "Decisions & Trade-offs" y actualizar `docs/aide/progress.md`.

## Testing Strategy

- `tests/test_scheduler.py`: `cron_trigger` con timezone IANA; próximo disparo con `now` fijo (p. ej. `0 2 * * *` en `America/Argentina/Buenos_Aires`); múltiples disparos con `count`; caso DST (`America/New_York` salto de primavera) verificando el desplazamiento del disparo inexistente según APScheduler 3.x.
- `tests/test_config.py`: expresión válida aceptada; `0 25 * * *`, `* * * *`, `not a cron` y minuto fuera de rango rechazadas con el `field_path` correcto; timezone inválida + cron inválido reportan ambos problemas.
- `tests/test_validate.py`: con scheduler habilitado y un job, existe un `Finding` `OK` con check `scheduler_next_fire` y "próximo disparo" en el mensaje; el test existente de jobs sigue verde.
- Gates completos por el comando del batch.

## Dependencies

- Item 008 (APScheduler 3.11.3 lockeado en Python 3.14), Etapa 5 cerrada (config y validate estables).

## Decisions & Trade-offs

- **Mismo parser en config y scheduler**: `config.py` valida con `CronTrigger.from_crontab` (importa APScheduler) en lugar de un mini-parser propio; así lo aceptado en la configuración es exactamente lo que el scheduler podrá programar y los mensajes de rango/sintaxis vienen del motor real. Coste: `config.py` deja de ser "solo stdlib"; el docstring del módulo lo refleja.
- **Timezone validada una sola vez**: `_parse_scheduler` construye la `ZoneInfo` y la pasa a `_parse_job`; si la timezone global es inválida, la expresión cron se valida con UTC de respaldo para que el usuario vea ambos problemas de una vez (no se silencia el error de cron por el de timezone).
- **Enumeración de disparos**: `next_fire_times` pasa `previous` como segundo argumento (`now` de la búsqueda) en las llamadas siguientes; con un `now` fijo, `min(now, previous+1µs)` repetía el mismo disparo si `previous` caía en el futuro. La primera llamada usa `previous=None` para no perder un disparo que coincida exactamente con `now`.
- **Semántica DST fijada por test**: APScheduler 3.x resuelve una hora local inexistente conservando el offset previo (`2026-03-08 02:30-05:00` = 07:30 UTC); el test lo documenta en vez de "corregirlo", porque el scheduler real se comportará así.
- **Job sin próximos disparos → WARNING en `validate`**: una expresión como `0 0 31 2 *` es válida para el parser pero nunca dispara; se reporta como advertencia (no error) porque el JSON es estructuralmente correcto y no rompe `odin validate`.

**Evidencia:** `uv run pytest tests/test_scheduler.py tests/test_config.py tests/test_validate.py -q` → **109 passed**; suite completa `uv run pytest -q` → **425 passed + 2 skipped** (los 2 skip son gbak real ausente en el host); `uv run ruff check src/odin tests` → All checks passed; `uv run mypy src/odin` → Success (14 source files, `scheduler.py` nuevo).

## Prerequisites

- No requiere servicios externos: helpers de calendario puros + validación estática del JSON.
- `docs/aide/progress.md` debe ser actualizado a 🚧 al iniciar.
- Al finalizar, actualizar `docs/aide/progress.md` a ✅.

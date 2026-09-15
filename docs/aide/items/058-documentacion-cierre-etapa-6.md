# Item 058: Documentación y cierre de la Etapa 6

## Description

Cerrar la Etapa 6 del roadmap: completar `README.md` con la sección "Scheduler
interno y modo servicio en primer plano" (bloque `scheduler` del JSON con
`timezone`, `jobs`, `schedule`, `skip_if_running` y `on_misfire`; operación
`odin service run|status|reload`; archivo de estado
`local.work_dir/scheduler_state.json`; recarga en caliente por `SIGUSR1`,
archivo de control y Windows; semántica de solapamiento y misfire; relación con
`odin run` one-shot y con la demo de cadencia del Item 057), revisar la
coherencia de los docstrings de `cli.py`/`scheduler.py` y los mensajes de
`validate.py` con el comportamiento real, verificar **uno a uno** los criterios
de aceptación de la Etapa 6 del roadmap con evidencia (tests/salidas), correr
los gates (`uv run pytest`, `uv run ruff check src/odin tests`, `uv run mypy
src/odin`) y actualizar `docs/aide/progress.md` (Etapa 6 ✅ si los criterios
quedan verificados, entregables de la etapa con su evidencia y
"Última actualización"), dejando anunciada la `queue-007` (Etapa 7 — Windows
Service y daemon Linux) que arrancará en el item 059.

## Acceptance Criteria

- [x] `README.md` tiene la sección "Scheduler interno y modo servicio en primer
      plano" con: ejemplo del bloque `scheduler` del JSON y tabla/descripción de
      `timezone`, `jobs[].schedule`, `jobs[].databases`, `jobs[].skip_if_running`
      y `jobs[].on_misfire` (`run_once`/`skip`); uso de `odin service run`,
      `odin service status` y `odin service reload` (incluido el
      comportamiento sin servicio y en Windows vía archivo de control); formato
      y contenido de `scheduler_state.json`; semántica de solapamiento (nunca
      dos respaldos de la misma base) y misfire; y la relación con `odin run`
      (`run` = one-shot manual, `service run` = scheduler que dispara el mismo
      pipeline por ciclo con su correo y retención).
- [x] La sección de demo manual del Item 057 queda integrada y el README no
      duplica información contradictoria (exit codes, formato de estado,
      mecanismos de recarga).
- [x] Docstrings de `src/odin/cli.py` y `src/odin/scheduler.py` revisados y
      coherentes con el comportamiento implementado (subcomandos, exit codes,
      recarga, estado); si algo quedó desactualizado, se corrige.
- [x] Los criterios de aceptación de la Etapa 6 del roadmap quedan verificados
      con evidencia concreta: (a) demo foreground con cadencia real → Item 057
      (test gated `ODIN_FOREGROUND_DEMO=1` + casos por defecto); (b) no
      duplicación de respaldo de la misma base → tests de solapamiento de los
      Items 051/054; (c) recarga con config válida/inválida → tests del Item
      055; (d) tests con reloj falso de disparos/misfire/solapamiento → tests
      de los Items 049-051.
- [x] `docs/aide/progress.md`: Etapa 6 en ✅, entregables y criterios de la
      etapa marcados con la evidencia, F7 con el estado que corresponda
      (parcial: el modo residente del SO queda para la Etapa 7),
      "Última actualización" con la fecha del cierre y "Próximo Paso"
      anunciando `queue-007` desde el item 059.
- [x] No se crea `docs/aide/queue/queue-007.md` todavía (solo se anuncia).
- [x] Gates en verde: `uv run pytest`,
      `uv run ruff check src/odin tests`, `uv run mypy src/odin`.

## Implementation Steps

1. Leer `README.md`, `src/odin/cli.py` (docstring del módulo y de
   `build_parser`/`_cmd_service_*`), `src/odin/scheduler.py` (docstring del
   módulo y de las clases públicas) y `src/odin/validate.py`
   (`_check_scheduler`/`_check_scheduler_next_fires`) para redactar la sección
   con el comportamiento real, no el deseado.
2. Escribir la sección "Scheduler interno y modo servicio en primer plano" en
   `README.md` (antes de "Exit codes") con ejemplos JSON, tablas de políticas y
   comandos, referenciando la demo del Item 057; ajustar "Exit codes" si
   `service run|status|reload` no están reflejados.
3. Corregir cualquier docstring desactualizado detectado en la revisión.
4. Verificar los criterios de la etapa ejecutando los tests citados y
   recolectando evidencia (comandos + resultado).
5. Correr los gates completos desde la raíz.
6. Actualizar `docs/aide/progress.md` (Etapa 6 ✅, entregables/criterios,
   F7, última actualización, próximo paso con `queue-007`).
7. Documentar decisiones y evidencia en "Decisions & Trade-offs".

## Testing Strategy

- Documentación: `grep -n "Scheduler interno\|odin service run\|skip_if_running\|on_misfire\|scheduler_state.json" README.md` para confirmar que todos los
  temas exigidos están presentes; `uv run odin validate --config
  examples/config.linux.json` para comprobar que la salida de `validate`
  coincide con lo documentado (próximo disparo por job).
- Evidencia de criterios: correr los tests de Items 051 (solapamiento), 055
  (recarga), 049-051 (reloj falso/misfire) y 056/057 (integración y
  foreground) y citar los comandos con su resultado en `progress.md`.
- Gates completos del batch.
- Sin cambios de código funcional: si aparece un desajuste real se documenta y
  se corrige en el punto que corresponda (spec del item o código), nunca se
  oculta.

## Dependencies

- Items 049-057 (todo el alcance de la Etapa 6) y `docs/aide/roadmap.md`
  (criterios de la etapa).

## Decisions & Trade-offs

- **La sección del README es operativa, no un resumen del código**: cada
  afirmación se contrastó contra la implementación (`config.py` para defaults
  `enabled: false`/`timezone: "UTC"`/`skip_if_running: true`/`on_misfire:
  run_once`; `cli.py` para exit codes de `service`; `scheduler.py` para el
  formato de `scheduler_state.json`, la atomicidad y la tolerancia de misfire
  de 1 s; `RELOAD_POLL_SECONDS = 2.0` para el watcher). Se documentaron también
  los límites (el archivo de estado no se edita a mano; la demo tarda 1–2
  minutos) en vez de prometer más de lo verificado.
- **`service status` en la tabla de exit codes**: el contrato era "0 mientras
  la lectura sea posible" y `reload` "0 entrega / 1 sin servicio / 2 config
  ilegible"; se agregaron a la tabla para que la documentación no dejara esos
  códigos implícitos solo en el `--help`.
- **Dos docstrings desactualizados corregidos**: `validate.py` hablaba del
  reuso del modo servicio en futuro ("lo reutilizará") cuando el Item 055 ya lo
  usa de hecho, y el encabezado de `scheduler.py` decía "Items 049-054" con la
  recarga (Item 055) documentada en el mismo módulo. Son los únicos desajustes
  encontrados en la revisión; `cli.py` ya describía `run|status|reload` y el
  trabajo de la Etapa 7 como pendiente.
- **F7 queda 🚧 a propósito**: el scheduler propio ya está cerrado, pero la
  funcionalidad "scheduler propio + modo servicio residente" no se completa
  hasta la Etapa 7 (`install|start|stop`, systemd), así que la tabla de la
  visión no se adelanta.
- **La `queue-007` no se crea acá**: el item pide anunciarla, no generarla; su
  creación es el Paso 4 del flujo (`/speckit.aide.create-queue`) en una sesión
  nueva, y `progress.md` lo deja como siguiente paso.

**Evidencia:** `grep -n "Scheduler interno|odin service run|odin service
status|odin service reload|skip_if_running|on_misfire|scheduler_state.json|SIGUSR1"
README.md` → 20 coincidencias que cubren bloque/operación/estado/recarga/
semántica/relación; `uv run odin validate --config examples/config.linux.json`
→ `VERIFICACIONES (10)` con `config.scheduler: habilitado con 1 job(s) en
America/Argentina/Buenos_Aires` y `próximo disparo: 2026-09-16T02:00:00-03:00`
(coherente con lo documentado). Criterios de la etapa: demo foreground →
`tests/test_scheduler_foreground.py` (2 passed + 1 skipped por defecto; gated
`ODIN_FOREGROUND_DEMO=1` → 3 passed, cron real en 78.6 s); solapamiento →
`uv run pytest tests/test_scheduler.py -q -k "overlapping or skip_if_running or
in_flight"` → **5 passed**; reloj falso/misfire/recarga → `uv run pytest
tests/test_scheduler.py -q -k "overlapping or skip_if_running or misfire or
next_fire_times or in_flight or reload"` → **22 passed**, 18 deselected;
recarga completa → `tests/test_scheduler.py tests/test_scheduler_state.py
tests/test_cli.py` → **128 passed**. Gates finales: `uv run pytest -q` →
**495 passed + 3 skipped in 18.08 s** (los 3 skips son gbak/Firebird ausentes y
la demo lenta gated); `uv run ruff check src/odin tests` → All checks passed;
`uv run mypy src/odin` → Success (14 source files). `docs/aide/progress.md`
actualizado: Etapa 6 ✅ (tabla y sección), entregables y criterios con evidencia,
última actualización y próximo paso con `queue-007` desde el item 059.

## Prerequisites

- No requiere servicios externos: es documentación, verificación y gates;
  los tests citados ya son verdes.
- `docs/aide/progress.md` debe ser actualizado a 🚧 al iniciar.
- Al finalizar, actualizar `docs/aide/progress.md` a ✅.

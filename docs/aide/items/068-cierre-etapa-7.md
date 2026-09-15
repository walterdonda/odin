# Item 068: Cierre de la Etapa 7

## Description

Cerrar la Etapa 7 del roadmap ("Modo servicio: Windows Service y daemon
Linux") verificando **uno a uno** sus criterios de aceptación con evidencia
concreta (salidas de tests y demos), corriendo los gates de calidad y
actualizando `docs/aide/progress.md`.

Verificaciones exigidas:

- **Linux**: validación estructural de `deploy/odin.service` más la demo gated
  de auto-recuperación (Item 066: `systemd-analyze verify` de la unit
  renderizada y demo `ODIN_SERVICE_DEMO=1` con sesión systemd de usuario:
  ciclo por catcher SMTP, `kill -9` → systemd reinicia solo → segundo ciclo).
- **Windows**: ciclo de vida con mocks de `win32serviceutil` (Item 061) más el
  runbook documentado (Item 067); dejar explícito que la ejecución en Windows
  Server real sigue delegada a la Etapa 8 (Item 009), igual que la salvedad de
  la Etapa 1.
- **`odin service status`** compuesto (gestor + scheduler) en ambas
  plataformas (Item 063).
- **Tests de ciclo de vida/unit** de los Items 060, 061 y 066.

Gates de calidad: `uv run pytest`, `uv run ruff check src/odin tests` y
`uv run mypy src/odin` (con los overrides de pywin32 del Item 059) en verde,
dejando constancia del conteo de la suite.

Actualizar `docs/aide/progress.md`: Etapa 7 ✅ si los criterios quedan
verificados (con la salvedad de Windows real pendiente), entregables y
criterios de la etapa con su evidencia, tablas de funcionalidades/objetivos
(F7, G6) y C8 según corresponda, "Última actualización" y "Próximo Paso"
anunciando la `queue-008.md` (Etapa 8 — matriz Firebird, empaquetado uv,
documentación final y release 1.0), que arrancará en el item 069.

## Acceptance Criteria

- [x] Criterios de la Etapa 7 del roadmap verificados uno a uno con evidencia
      citada: (a) unit systemd activa y reinicia ante caída; (b) servicio
      Windows instalado/arrancado con ciclo de vida mockeado y runbook
      documentado; (c) scheduler dispara sin intervención; (d) `odin service
      status` refleja el estado real en ambas plataformas; (e) tests de ciclo
      de vida (mock `win32serviceutil`) y validación de la unit systemd.
- [x] Los gates corren en verde y el conteo de la suite queda registrado en
      `progress.md` y en este spec.
- [x] `docs/aide/progress.md`: Etapa 7 en ✅ (con la salvedad de Windows Server
      real → Etapa 8/Item 009), entregables de la etapa con evidencia,
      criterios marcados, F7 y G6 con el estado que corresponda, C8 tratado
      según corresponda, "Última actualización" y "Próximo Paso" con
      `queue-008.md` desde el item 069.
- [x] No se crea `docs/aide/queue/queue-008.md`: solo se anuncia.
- [x] El runbook de Windows Server real de `docs/service.md` (Item 067) queda
      referenciado como la verificación manual de la Etapa 8.

## Implementation Steps

1. Ejecutar los tests que prueban cada criterio y registrar comandos +
   resultados: unit/estructura (Item 060), ciclo de vida Windows (Item 061),
   `status` compuesto (Item 063), integración Linux (Item 066).
2. Correr los gates completos desde la raíz y anotar el conteo.
3. Actualizar `docs/aide/progress.md`: Etapa 7 ✅, entregables/criterios con
   evidencia, F7/G6/C8, última actualización y próximo paso con `queue-008`.
4. Documentar decisiones y evidencia en "Decisions & Trade-offs".

## Testing Strategy

- `uv run pytest tests/test_service_linux.py tests/test_service_windows.py
  tests/test_service_status.py tests/test_service_linux_integration.py -q` →
  evidencia de ciclo de vida/unit/status.
- `uv run pytest` completo → conteo de la suite.
- `uv run ruff check src/odin tests` y `uv run mypy src/odin`.
- Sin cambios de código funcional: si aparece un desajuste real entre
  documentación y comportamiento se corrige y se registra.

## Dependencies

- Items 059-067 (todo el alcance de la Etapa 7, incluida la documentación del
  Item 067) y `docs/aide/roadmap.md` (criterios de la etapa).
- Item 066 (demo gated de auto-recuperación) y Item 061 (mocks de Windows).

## Decisions & Trade-offs

- **Verificación por criterio con evidencia re-ejecutada**: no se citó el
  resultado previo del Item 066 sin más: la demo gated de systemd se volvió a
  correr en esta sesión (sesión `systemctl --user` en estado `running`) y pasó
  en **102.27 s**, confirmando que la auto-recuperación es reproducible. Los
  conteos citados se obtuvieron con los comandos exactos anotados en cada
  criterio de `progress.md`.
- **Windows: criterio marcado ✅ con la salvedad explícita**. No hay Windows
  real en este entorno; el ciclo de vida se verifica con los 31 tests de
  dobles de pywin32 (Item 061) y el runbook de `docs/service.md` §8, y la
  ejecución en Windows Server real (reinicio del SO y recuperación) queda
  delegada a la Etapa 8/Item 009, igual que la confirmación de la Etapa 1. El
  cierre no oculta la brecha: la salvedad está en el criterio, en la
  "Última actualización" y en el "Próximo Paso".
- **C8 sin tabla nueva**: `progress.md` nunca tuvo una tabla de criterios de
  éxito (C1-C8); crear una ahora solo para C8 sería inconsistente y la
  verificación completa de los criterios 1-8 es, por roadmap, el cierre de la
  Etapa 8. C8 queda cubierto en la sección de la Etapa 7 (servicio residente
  con scheduler propio sin cron/Task Scheduler, recuperación automática y
  solapamiento controlado) con la salvedad de Windows real.
- **`queue-008.md` solo se anuncia**: el Paso 4 del flujo
  (`/speckit.aide.create-queue`) la genera en una sesión nueva; el
  "Próximo Paso" queda apuntando a ese comando.
- **Deliverables de etapa ajustados**: el entregable Linux de la Etapa 7 y
  `docs/service.md` pasan a ✅, F7 y G6 a ✅; el resto de las secciones (Etapa
  8, F2/F3/F6, G1/G2/G5 y los requisitos no funcionales) no se toca porque
  depende de etapas abiertas.

**Evidencia:** `uv run pytest tests/test_service_windows.py -q` → 31 passed;
`uv run pytest tests/test_service_base.py tests/test_service_linux.py
tests/test_service_windows.py tests/test_service_status.py
tests/test_service_runner.py tests/test_service_linux_integration.py -q` →
**97 passed + 2 skipped**; `uv run pytest tests/test_service_status.py
tests/test_cli.py -q` → 99 passed; `uv run pytest tests/test_service_runner.py
tests/test_scheduler.py -q` → 54 passed;
`ODIN_SERVICE_DEMO=1 uv run pytest
tests/test_service_linux_integration.py::test_user_service_restarts_after_kill_and_delivers_cycles
-q` → **1 passed in 102.27 s** (systemd de usuario real: ciclo ÉXITO por
catcher SMTP, `kill -9` → MainPID nuevo y segundo ciclo). Gates finales:
`uv run pytest -q` → **623 passed + 5 skipped in 18.2 s**; `uv run ruff check
src/odin tests` → All checks passed; `uv run mypy src/odin` → Success: no
issues found in 19 source files. `docs/aide/progress.md` actualizado: Etapa 7
✅ (tabla y sección), entregables (Linux y `docs/service.md` ✅ más el cierre
del Item 068), los cinco criterios de la etapa con evidencia, C8 cubierto,
F7/G6 ✅, última actualización y próximo paso con `queue-008.md` desde el item
069.

## Prerequisites

- No requiere servicios externos salvo la demo gated del Item 066, que ya es
  skip-safe (solo corre con `ODIN_SERVICE_DEMO=1` y sesión systemd de usuario).
- `docs/aide/progress.md` debe reflejar el avance (📋 → 🚧 → ✅) al completar.
- Al finalizar, actualizar `docs/aide/progress.md` con la evidencia del item.

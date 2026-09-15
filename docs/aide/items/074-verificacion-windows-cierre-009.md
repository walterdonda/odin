# Item 074: Verificación en limpio en Windows Server y cierre del Item 009

## Description

Ejecutar la verificación en limpio de ODIN en Windows Server —runbook §8 de
`docs/service.md` o el job `windows` de la CI del Item 073— y **cerrar el Item
009** (`docs/aide/items/009-smoke-test-multiplataforma.md`), registrando la
evidencia y la salvedad del entorno:

1. **Evidencia**: sección nueva **"Evidencia de verificación"** en
   `docs/service.md` (§9) con:
   - lo ejecutado localmente (Linux) como preparación: tests del gestor
     Windows con dobles de pywin32, escenario gated
     `ODIN_WINDOWS_SERVICE_SMOKE=1` del Item 073 skip-safe, YAML de CI
     validado y gates del proyecto;
   - el procedimiento y los **campos a completar con la corrida real** (fecha,
     build del SO, versiones de uv/Python/Firebird, salidas de
     `install|start|status|stop|uninstall` y estado del SCM, reinicio tras
     reboot y recuperación ante caída);
   - la **salvedad explícita**: en este entorno no hay Windows Server ni
     remoto publicado, así que la ejecución real queda delegada al job
     `windows` de la CI (Item 073) o al runbook, con el mismo criterio de las
     Etapas 5 y 7 (casilla externa real, systemd de usuario).
2. **Cierre del Item 009**: actualizar su spec (Decisions & Trade-offs) con el
   cierre y la salvedad, y `docs/aide/progress.md`:
   - Etapa 1 → ✅ y la fila "`uv sync` + `uv run pytest` funcionando en Linux y
     Windows" con la evidencia (Linux ✅ Items 071-072; Windows por el job de
     CI con el mismo `scripts/verify.py`);
   - criterio de compatibilidad Python 3.14 con la confirmación Windows
     delegada a la CI;
   - filas de la Etapa 8 afectadas por la verificación Windows (instalación en
     limpio y servicio) con la salvedad enlazada a `docs/service.md` §9;
   - "Última actualización" y "Próximo Paso" (Lote D, items 075-076).

Sin cambios de código: el item es de verificación/documentación; los artefactos
de preparación los aporta el Item 073.

## Acceptance Criteria

- [x] `docs/service.md` con la sección **"Evidencia de verificación"** (§9,
      renumerando Referencias) que distingue lo **ejecutado** (Linux:
      `tests/test_service_windows.py`, escenario gated del Item 073, YAML de
      CI, gates) de lo **delegado** (corrida real en Windows Server/CI) y
      contiene la checklist de evidencia a completar (fecha, SO, versiones,
      salidas, estado SCM, reboot y recuperación).
- [x] Salvedad explícita de que no hubo Windows Server real en este entorno y
      la vía de ejecución es el job `windows` de la CI al publicar o el
      runbook §8.
- [x] `docs/aide/items/009-smoke-test-multiplataforma.md` actualizado con el
      cierre (fecha, references a Items 071/073/074 y salvedad).
- [x] `docs/aide/progress.md`: Etapa 1 → ✅; filas del smoke multiplataforma y
      de Python 3.14 con la evidencia y la salvedad; filas de Etapa 8 de
      verificación Windows enlazadas a `docs/service.md` §9; "Última
      actualización" y "Próximo Paso" al Lote D (075-076).
- [x] Gates en verde: `uv run pytest`, `uv run ruff check src/odin tests`,
      `uv run mypy src/odin` (sin regresiones por los cambios documentales).

## Implementation Steps

1. Agregar la sección §9 "Evidencia de verificación" a `docs/service.md`
   (con la renumeración de "Referencias" a §10) y enlazarla desde §8.
2. Actualizar `docs/aide/items/009-smoke-test-multiplataforma.md` con el cierre
   y la salvedad.
3. Actualizar `docs/aide/progress.md` (Etapa 1 → ✅, filas del smoke y de
   Python 3.14, filas de Etapa 8 afectadas, "Última actualización", "Próximo
   Paso").
4. Correr los gates y registrar la evidencia en este spec; verificar que no
   queden enlaces rotos (specs referenciados existentes).

## Testing Strategy

- `uv run pytest` + `uv run ruff check src/odin tests` +
  `uv run mypy src/odin` → sin cambios de código, los gates deben seguir
  verdes (evidencia del item).
- `uv run pytest tests/test_service_windows.py -q` → 31 passed (la evidencia
  local que cita la sección §9).
- `uv run pytest tests/test_service_windows_integration.py -q` → skip con
  motivo en Linux (delegación documentada).
- Revisión de enlaces/rutas citados en la sección nueva (`docs/service.md`,
  specs de Items 009/071/073, `tests/smtp_catcher.py`) contra el repositorio.

## Dependencies

- Item 009: spec a cerrar (`docs/aide/items/009-smoke-test-multiplataforma.md`).
- Item 073: `.github/workflows/ci.yml` y el escenario gated del servicio
  Windows (vía de ejecución real).
- Item 067: runbook §8 de `docs/service.md`.
- Item 071/072: gate único y evidencia Linux (cierre del Item 009 en Linux).

## Decisions & Trade-offs

- **Sección en `docs/service.md` y no un archivo aparte**: la evidencia vive en
  §9, junto al runbook §8 que la produce, y queda enlazada desde el README
  (`docs/service.md#9-evidencia-de-verificación-item-074`); se descartó
  `docs/verification-windows.md` para no fragmentar la guía operativa.
- **Cierre honesto del Item 009**: el item se cierra con la evidencia de Linux
  (Items 071-072) y la corrida real de Windows **delegada** al job `windows`
  de la CI (Item 073) o al runbook §8. No se declara ejecutada una verificación
  en Windows Server que no ocurrió en este entorno (no hay host Windows ni
  remoto publicado); §9.2 deja la tabla de evidencia con los campos
  *pendiente* para completarlos en la primera corrida real.
- **Salvedad explícita y trazable**: es la misma política que las Etapas 5
  (casilla externa real) y 7 (Windows Server real); el Item 009, su
  `progress.md` y el README apuntan todos a `docs/service.md` §9, de modo que
  la salvedad no queda implícita en ningún lado.
- **README: se corrigió la referencia al Item 009** en "Compatibilidad de
  dependencias (Python 3.14)" —la confirmación runtime de Windows ya no "se
  realizará en el Item 009" porque el item se cierra con la delegación— y
  ahora enlaza a la CI y a §9.
- **Alcance del cierre en `progress.md`**: se marca **Etapa 1 ✅** y el smoke
  multiplataforma con la salvedad, pero las filas de la **Etapa 8** que
  dependen de la *ejecución* real (instalación limpia en Windows Server,
  `uv tool install` en Windows) siguen 🚧/sin marcar: la corrida real las
  cierra y no corresponde adelantarlas.
- **Sin cambios de código**: item documental; la preparación técnica
  (`tests/test_service_windows_integration.py`, YAML de CI, contrato del
  workflow) es del Item 073 y su evidencia se cita desde §9.

**Evidencia:** `uv run pytest tests/test_service_windows.py -q` → **31 passed**
(dobles de pywin32, base de la evidencia local); `uv run pytest
tests/test_service_windows_integration.py -q` → **1 skipped** (delegación
documentada); `uv run pytest tests/test_ci_workflow.py -q` → **6 passed**
(YAML de CI); `uv run pytest -q` → **652 passed + 8 skipped in 95.10 s**;
`uv run python scripts/verify.py` → **EXIT=0** (6 pasos); `uv run ruff check
src/odin tests` → All checks passed; `uv run mypy src/odin` → Success 19
files. `docs/service.md` §9 con 9.1 ejecutado/9.2 delegado y la tabla de
evidencia pendiente; Item 009 actualizado y `progress.md` con Etapa 1 ✅.

## Prerequisites

- **Servicios requeridos**: ninguno; item documental. La ejecución real (job
  Windows/runbook) requiere Windows Server o el remoto publicado, ausentes en
  este entorno.
- **Configuración de entorno**: ninguna variable nueva; sin secretos.
- **Checklist de validación manual**:
  - [x] `docs/service.md` §9 presente, con evidencia ejecutada y campos
        pendientes claramente separados, y Referencias renumeradas.
  - [x] Item 009 con el cierre documentado y la salvedad.
  - [x] `progress.md`: Etapa 1 ✅ y filas del smoke con la salvedad; sin marcar
        como completas las filas de Etapa 8 que dependen de la corrida real.
  - [x] Gates completos verdes.
- **Resultados esperados**: verificación Windows preparada y documentada,
  Item 009 cerrado con salvedad y progreso consistente para el Lote D.
- `docs/aide/progress.md` debe reflejar el avance (📋 → 🚧 → ✅) al completar.
- Al finalizar, actualizar `docs/aide/progress.md` con la evidencia del item.

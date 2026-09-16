# Item 078: Cierre de la Etapa 8: criterios 1–8 de la visión y consistencia documental

## Description

Cerrar formalmente la **Etapa 8** y la release `1.0.0`: verificar uno a uno los
ocho criterios de éxito de `docs/aide/vision.md` §9 con evidencia ejecutada
(salidas de `scripts/verify.py`, tests, correo/estado del catcher SMTP, logs,
matriz Firebird, evidencia de instalación/CI), revisar la consistencia
documental del release y dejar `docs/aide/progress.md` con el estado final del
proyecto (Etapa 8 ✅, Etapa 1 ✅ con el cierre del Item 009, tablas F1–F8/G1–G7,
requisitos no funcionales y "Última actualización"). Las salvedades de
plataforma (casilla de correo externa real y Windows Server real vía CI/runbook)
se explicitan, con el mismo criterio que las Etapas 5 y 7.

Contenido requerido:

1. **Checklist de criterios 1–8** en `docs/release-1.0.md` (documento nuevo),
   cada uno con su evidencia y su salvedad si aplica:
   1. Instalación limpia: Linux LTS real (Items 072/074) y Windows delegado a
      CI/runbook.
   2. Punta a punta con Firebird 2.5 y 5/6 (Items 069/070 + e2e del 072).
   3. Tolerancia a fallos (servidor caído, parcial).
   4. Notificación de error y exit codes.
   5. Validación (`odin validate`).
   6. Enmascarado de secretos.
   7. Calidad (suite + documentación).
   8. Modo servicio residente (Items 066/068 + CI/runbook para Windows).
2. **Revisión de consistencia documental**: cada comando de `README.md` y
   `docs/*` contrastado con `--help`, enlaces relativos válidos, `odin validate`
   sobre los dos ejemplos, versiones coherentes (`pyproject.toml` ↔
   `src/odin/__init__.py` ↔ CHANGELOG ↔ README) y guía de seguridad enlazada.
3. **Gates finales**: `uv run python scripts/verify.py` completo (pytest con
   integración skip-safe + ruff + mypy + `validate` de los ejemplos) → exit 0.
4. **`docs/aide/progress.md` final**: Etapa 8 ✅, Etapa 1 ✅ con el cierre del
   Item 009 explícito, criterios de aceptación de la etapa 8 marcados,
   `F2`/`F3`/`F6`/`G1`/`G2`/`G5` y requisitos no funcionales al estado final
   real, y "Última actualización" con el cierre.
5. **Sin cambios de comportamiento**: si la revisión de consistencia encuentra
   una divergencia entre documentación y código, se corrige el documento o el
   texto (no se altera el comportamiento en un item de cierre); cualquier
   hallazgo real se registra en Decisions & Trade-offs.

## Acceptance Criteria

- [x] `docs/release-1.0.md` existe con los criterios 1–8 verificados uno a uno,
      cada uno con su evidencia (comando + resultado) y salvedades explícitas.
- [x] Consistencia de comandos: cada subcomando/flag citado en el README y en
      `docs/*` existe en `--help` y `odin validate` pasa sobre los dos ejemplos.
- [x] Consistencia de enlaces: los enlaces relativos de `README.md` y `docs/*`
      resuelven en el árbol (incluida la guía de seguridad).
- [x] Consistencia de versiones: `1.0.0` en `pyproject.toml`,
      `src/odin/__init__.py`, `CHANGELOG.md` y README sin divergencias.
- [x] Gates finales en verde: `uv run python scripts/verify.py` (exit 0) y
      `uv run pytest` con la suite completa (integración skip-safe).
- [x] `docs/aide/progress.md`: Etapa 8 ✅, Etapa 1 ✅ con el cierre del Item 009,
      criterios de la Etapa 8 marcados, tablas F1–F8/G1–G7 y requisitos no
      funcionales en su estado final, "Última actualización" y "Próximo Paso"
      al día.
- [x] Salvedades de plataforma explícitas (correo externo real, Windows Server
      real vía CI/runbook) sin declarar verificado lo que no se ejecutó.
- [x] Evidencia registrada en "Decisions & Trade-offs".

## Implementation Steps

1. Recolectar la evidencia ya ejecutada en los items de la Etapa 8 (matriz
   Firebird 069/070, empaquetado 071/072, CI 073/074, README/seguridad 075/076,
   release 077) y re-ejecutar los gates finales.
2. Escribir `docs/release-1.0.md` con la checklist de los criterios 1–8, la
   tabla de evidencia por criterio y la sección de salvedades.
3. Revisar la consistencia documental: comandos vs `--help`, enlaces relativos,
   ejemplos válidos, versiones coherentes y enlace a `docs/security.md`.
4. Actualizar `docs/aide/progress.md`: Etapa 8 ✅ (y sus criterios), Etapa 1 ✅
   con el cierre del Item 009, tablas F1–F8/G1–G7, requisitos no funcionales,
   "Última actualización" y "Próximo Paso" (release cerrada).
5. Correr los gates finales completos y registrar la salida.
6. Escribir las decisiones/evidencia en este spec y dejar constancia de
   cualquier hallazgo real de la revisión.

## Testing Strategy

- `uv run python scripts/verify.py` (sin `--quick`, con integración) → EXIT 0
  con los seis pasos OK.
- `uv run pytest -q` → suite completa; confirmar que los skips son los
  esperados (`ODIN_*` gated / Windows / Docker).
- `uv run odin validate --config examples/config.linux.json` y
  `.../config.windows.json` → exit 0.
- `uv run odin --version` → `odin 1.0.0`; contraste con
  `pyproject.toml`/`__init__.py`/CHANGELOG/README.
- Chequeo de enlaces y anclas de `README.md` y `docs/*.md` (rutas relativas y
  encabezados) y de comandos citados contra `--help` (grep + ejecución).
- Re-ejecución de la evidencia gated disponible (p. ej.
  `ODIN_BUILD_ARTIFACTS=1 uv run pytest tests/test_packaging.py -q`) para que
  la checklist cite salidas reales, no recuerdos.

## Dependencies

- Items 069–077 ✅: toda la evidencia de la Etapa 8 (matriz, empaquetado, CI,
  documentación, seguridad, release).
- `scripts/verify.py` (Item 071) como gate único y `.github/workflows/ci.yml`
  (Item 073) como vía delegada de Windows.
- `docs/service.md` §9 (Item 074) para la salvedad de Windows Server.
- `docs/aide/items/009-smoke-test-multiplataforma.md` (cierre del Item 009) y
  `docs/aide/vision.md` §9 como fuente de los criterios.

## Decisions & Trade-offs

- **Checklist con evidencia re-ejecutada, no recuerdos**: los gates finales se
  volvieron a correr en el cierre (`scripts/verify.py` → EXIT 0, 6/6 pasos;
  suite completa en el mismo gate) y se citan con su fecha las corridas
  gated de los items 069-077 (matriz Firebird, contenedor limpio, demos
  systemd/SCM). Cuando una corrida requiere un host/red que este entorno no
  tiene (Windows Server real, casilla de correo externa), se declara como
  **salvedad** con su procedimiento de cierre, sin declararla verificada.
- **Etapa 3 y F2/G2 al estado final**: la etapa 3 estaba en 🚧 por su único
  criterio pendiente ("demo con `gbak` real de ambos archivos"), que ya había
  sido cubierto por los e2e de los Items 025-026 y quedó demostrado con
  `gbak` real en el e2e gated del contenedor limpio (Item 072:
  `ODIN_CLEAN_CONTAINER_E2E=1` → `.fbk` y `.fbk.7z` > 0 con Firebird 5.0). Se
  marcó el criterio y la etapa ✅ con esa evidencia; el Item 029 de la cola
  original nunca se ejecutó como tal y su alcance (documentar la compresión y
  limpiar la etapa) quedó absorbido por los items de pipeline/documentación.
- **Consistencia documental programática**: se chequeó con un script temporal
  (fuera del repo) que (a) resuelve cada enlace relativo y cada ancla GitHub de
  `README.md`, `CHANGELOG.md` y `docs/*.md` contra el árbol y sus encabezados,
  y (b) extrae cada invocación `odin` citada y la contrasta contra `--help`.
  Resultado: **0 enlaces/anclas rotos y 12 comandos OK**. Los registros
  históricos de AIDE conservan la versión `0.1.0` de entonces; la búsqueda de
  versiones se acotó a fuentes, tests y documentación de producto.
- **G5 (instalación uniforme) ✅ con salvedad**: Linux verificado de punta a
  punta (Items 072/077) y Windows con la vía CI/runbook preparada (Items
  073/074); se marca ✅ con la misma convención que las Etapas 5/7 para
  criterios cuyo runtime real depende de un host externo, explicitando la
  salvedad en `docs/release-1.0.md`.
- **Sin cambios de comportamiento**: la revisión no encontró divergencias
  entre documentación y código que requirieran tocar lógica; los únicos
  cambios del cierre son documentales (checklist, `progress.md`). El tag
  `v1.0.0` sigue pendiente del commit de la release (regla de no-commit del
  batch), documentado en el spec 077.

**Evidencia:** `docs/release-1.0.md` con los criterios 1–8 (tabla resumen +
detalle por criterio + salvedades); `uv run python scripts/verify.py` →
**EXIT 0, 6/6 pasos** (pytest 73.77 s); `uv run pytest -q` → **652 passed + 8
skipped in 79.53 s**; `uv run ruff check src/odin tests` → All checks passed;
`uv run mypy src/odin` → Success 19 files; `ODIN_BUILD_ARTIFACTS=1 uv run
pytest tests/test_packaging.py -q` → **4 passed in 9.33 s**; `uv run odin
--version` → `odin 1.0.0`; chequeo de consistencia → 0 enlaces/anclas rotos y
12 comandos citados existentes; `uv run odin validate` sobre ambos ejemplos →
exit 0. `docs/aide/progress.md` actualizado: Etapa 3 ✅, Etapa 8 ✅ (criterios
marcados), Etapa 1 ✅ con el cierre del Item 009, F1–F8 y G1–G7 ✅, requisitos
no funcionales ✅ y "Próximo Paso" con las acciones post-commit (tag `v1.0.0` y
corrida real de Windows en CI/runbook).

## Prerequisites

- **Servicios requeridos**: ninguno obligatorio; Docker disponible habilita la
  matriz Firebird y los tests de integración (skip-safe si falta).
- **Configuración de entorno**: ninguna variable obligatoria; las gated
  (`ODIN_BUILD_ARTIFACTS`, `ODIN_CLEAN_CONTAINER_E2E`, `ODIN_FIREBIRD_*`,
  `ODIN_SERVICE_DEMO`) son opcionales y se citan como están.
- **Checklist de validación manual**:
  - [ ] `uv run python scripts/verify.py` → EXIT 0.
  - [ ] `docs/release-1.0.md` con los 8 criterios y salvedades.
  - [ ] `docs/aide/progress.md` sin 🚧 en Etapa 8 ni en las tablas F/G.
  - [ ] Enlaces relativos del README/docs resueltos; versiones coherentes.
- **Resultados esperados**: Etapa 8 cerrada, release `1.0.0` documentada con
  evidencia y salvedades, progreso final consistente.
- `docs/aide/progress.md` debe reflejar el avance (🚧 → ✅) al completar.
- Al finalizar, actualizar `docs/aide/progress.md` con la evidencia del item
  (este item cierra la Etapa 8 y el proyecto queda como release `1.0.0`).

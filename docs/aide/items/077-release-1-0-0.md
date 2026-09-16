# Item 077: Release 1.0.0: versión, CHANGELOG, artefactos y tag

## Description

Preparar la release `1.0.0` de ODIN: la versión deja de ser `0.1.0` (aún el
valor del esqueleto del Item 001) y pasa a `1.0.0` en las dos fuentes de
verdad (`pyproject.toml` y `src/odin/__init__.py`), con la metadata de
clasificación de madurez actualizada a *Production/Stable*, un `CHANGELOG.md`
estilo Keep a Changelog que resuma la release, los artefactos `uv build`
(wheel/sdist) verificados con una instalación limpia de prueba y el tag
anotado `v1.0.0`. Los tests que hoy fijan `0.1.0` (`tests/test_smoke.py`,
`tests/test_packaging.py` y `tests/test_packaging_integration.py`) deben dejar
de fijar una constante y derivar la versión de `odin.__version__`/metadata,
para que el próximo bump no requiera tocarlos.

Contenido requerido:

1. **Versión `1.0.0`**: `version = "1.0.0"` en `pyproject.toml:7`,
   `__version__ = "1.0.0"` en `src/odin/__init__.py:3` y refresco del `uv.lock`
   (contiene la entrada del proyecto con su versión; `uv sync --locked` de la
   CI fallaría con el lock desactualizado).
2. **Tests sin versión hardcodeada**: `tests/test_smoke.py:10,17`,
   `tests/test_packaging.py:37,102` y `tests/test_packaging_integration.py:171,234`
   derivan de `odin.__version__` (y la metadata de `pyproject.toml` se contrasta
   contra esa única fuente).
3. **Metadata de release** en `pyproject.toml`: clasificador
   `Development Status :: 5 - Production/Stable` (hoy `3 - Alpha`) y revisión
   de `license`, `keywords`, `classifiers` y `requires-python` (sin inventar
   campos que el backend no consuma).
4. **`CHANGELOG.md`** estilo [Keep a Changelog](https://keepachangelog.com/es/1.1.0/)
   con la sección `1.0.0` que resuma F1–F8, plataformas soportadas, exit codes
   y notas de seguridad, más una sección `Unreleased` vacía para el próximo
   ciclo; enlazado desde `README.md` (índice y/o sección de licencia/versión).
5. **Artefactos**: `uv build` produce `dist/odin-1.0.0-py3-none-any.whl` y
   `dist/odin-1.0.0.tar.gz`; la instalación de prueba del wheel en entorno
   aislado (`uv tool install`, ya cubierta por `tests/test_packaging.py` con
   `ODIN_BUILD_ARTIFACTS=1`) reporta `odin --version` → `odin 1.0.0`; el
   `test_clean_uv_tool_install_runs_the_cli` de integración también queda
   alineado a la versión derivada.
6. **Tag anotado `v1.0.0`** con el resumen de la release. El comando de batch
   prohíbe crear commits, así que el tag (que debe apuntar al commit de la
   release, aún sin crear) se documenta con su comando exacto para ejecutarlo
   después del commit del usuario; el push queda para cuando exista remoto.

## Acceptance Criteria

- [x] `pyproject.toml` declara `version = "1.0.0"` y el clasificador
      `Development Status :: 5 - Production/Stable`; `license`, `keywords`,
      `classifiers` y `requires-python` revisados.
- [x] `src/odin/__init__.py` declara `__version__ = "1.0.0"` y `uv lock` deja
      `uv.lock` consistente (entrada del proyecto en `1.0.0`).
- [x] `tests/test_smoke.py`, `tests/test_packaging.py` y
      `tests/test_packaging_integration.py` no contienen `0.1.0` y derivan la
      versión de `odin.__version__`/metadata.
- [x] `CHANGELOG.md` existe, sigue Keep a Changelog y su sección `1.0.0`
      resume F1–F8, plataformas, exit codes y notas de seguridad.
- [x] `CHANGELOG.md` está enlazado desde `README.md` y las menciones de versión
      del README (`odin --version` → `odin 1.0.0`) quedan al día.
- [x] `uv build` genera wheel y sdist `1.0.0` y la instalación de prueba en
      entorno aislado responde `odin 1.0.0` (gate
      `ODIN_BUILD_ARTIFACTS=1 uv run pytest tests/test_packaging.py -q`).
- [x] Tag anotado `v1.0.0` documentado con su comando exacto (creación local
      diferida al commit de la release por la regla de no-commit del batch).
- [x] Gates en verde: `uv run pytest tests/test_smoke.py tests/test_packaging.py
      tests/test_ci_workflow.py -q`, `uv run ruff check src/odin tests`,
      `uv run mypy src/odin`.
- [x] `docs/aide/progress.md` marca el entregable "Release/tag `1.0.0`" con la
      evidencia (y la salvedad del tag).
- [x] Evidencia registrada en "Decisions & Trade-offs".

## Implementation Steps

1. Actualizar `pyproject.toml` (versión `1.0.0`, clasificador
   Production/Stable, revisión de metadata) y `src/odin/__init__.py`
   (`__version__`); correr `uv lock` para refrescar la entrada del proyecto en
   `uv.lock`.
2. Reescribir las aserciones de versión de los tests de humo y empaquetado
   para derivarlas de `odin.__version__` (metadata `pyproject` contrastada en
   `test_packaging.py`), sin tocar el resto de la cobertura.
3. Escribir `CHANGELOG.md` (Keep a Changelog, `Unreleased` + `1.0.0` con
   F1–F8, plataformas, exit codes y seguridad) y enlazarlo desde `README.md`;
   actualizar las dos menciones de versión del README.
4. Construir y verificar artefactos: `uv build`, inspección del nombre y la
   metadata (`METADATA` con `Version: 1.0.0`) y corrida del gate de
   empaquetado con `ODIN_BUILD_ARTIFACTS=1`.
5. Documentar el tag anotado `v1.0.0` con su comando exacto (`git tag -a
   v1.0.0 -m "<resumen de la release>"`) para ejecutarlo tras el commit, y
   registrar la razón de la deferencia.
6. Correr los gates, actualizar `docs/aide/progress.md` (entregable 🚧 → ✅)
   y este spec con decisiones/evidencia.

## Testing Strategy

- `uv run odin --version` → `odin 1.0.0`, exit 0.
- `uv run pytest tests/test_smoke.py tests/test_packaging.py
  tests/test_ci_workflow.py -q` → verde sin versión hardcodeada; la metadata
  del `pyproject.toml` coincide con `odin.__version__`.
- `ODIN_BUILD_ARTIFACTS=1 uv run pytest tests/test_packaging.py -q` → build
  real + `uv tool install` aislado + `validate`/`service status` con el wheel
  `1.0.0` (4 passed esperados).
- Inspección del wheel/sdist: nombre `odin-1.0.0-*`, `METADATA` con
  `Version: 1.0.0` y `Development Status :: 5 - Production/Stable`.
- Verificación de consistencia: `git diff uv.lock` muestra solo la versión del
  proyecto; `grep -rn "0\.1\.0"` sobre fuentes/tests/README sin coincidencias.
- Gates del repositorio: `uv run pytest` (suite completa),
  `uv run ruff check src/odin tests`, `uv run mypy src/odin`.
- No se agregan tests de contenido del CHANGELOG (documentación); su
  consistencia de versión se verifica contra `pyproject.toml`/`__version__`.

## Dependencies

- Items 069–076 ✅ (Etapa 8 completa salvo el cierre): matriz Firebird,
  empaquetado/instalación limpia (`tests/test_packaging.py`,
  `tests/test_packaging_integration.py`), CI, README y guía de seguridad.
- `tests/packaging_tools.py` (Item 072) para el build/instalación aislada.
- `uv.lock` como lock vigente (`uv sync --locked` de la CI).
- Item 078 (mismo lote): el cierre de la etapa consume el tag/versión de este
  item en la revisión de consistencia.

## Decisions & Trade-offs

- **Una sola fuente de versión en los tests**: `tests/test_smoke.py` usa
  `importlib.metadata.version("odin")` como invariante instalación ↔ paquete y
  `odin.__version__` para el CLI; `tests/test_packaging.py` y
  `tests/test_packaging_integration.py` derivan de `odin.__version__` (la
  metadata del `pyproject.toml` se contrasta contra esa fuente, no al revés).
  Hallazgo real durante el gate: en `test_clean_uv_tool_install_runs_the_cli`
  la variable local `odin` (ruta del ejecutable instalado) **ensombrecía** el
  import del módulo (`AttributeError: 'PosixPath' object has no attribute
  '__version__'`); se resolvió importando `from odin import __version__ as
  ODIN_VERSION`. Sin el gate `ODIN_BUILD_ARTIFACTS=1` el fallo no aparecía.
- **`uv.lock` también lleva la versión**: la entrada editable del proyecto en
  `uv.lock` se refrescó con `uv lock` (`Updated odin v0.1.0 -> v1.0.0`), porque
  el `uv sync --locked` de la CI falla con el lock desactualizado.
- **Metadata**: `Development Status :: 5 - Production/Stable` (antes
  `3 - Alpha`); `license = "MIT"` se mantiene y el wheel lo emite como
  `License-Expression: MIT` (PEP 639, verificado en `METADATA`); `keywords`,
  `requires-python >= 3.14` y el resto de clasificadores se revisaron sin
  cambios. No se agregó un archivo `LICENSE` (fuera del alcance del item; el
  README declara la licencia en `pyproject.toml`).
- **CHANGELOG sin enlaces de comparación**: Keep a Changelog 1.1 con
  `Unreleased` vacía y `1.0.0 - 2026-09-16` que resume F1–F8, plataformas,
  exit codes y seguridad. No se agregaron links `compare`/`releases` porque el
  repositorio todavía no tiene remoto: inventar URLs habría sido peor que
  omitirlas.
- **README**: se actualizaron las dos menciones de versión (`odin 1.0.0` en el
  quickstart de instalación y en la tabla de operación) y `CHANGELOG.md` quedó
  enlazado desde el índice y desde la sección de licencia (enlaces reales).
- **Tag `v1.0.0` diferido (decisión de proceso)**: el comando de batch prohíbe
  crear commits y el tag anotado debe apuntar al **commit de la release**, que
  aún no existe; crearlo sobre `HEAD` dejaría `v1.0.0` apuntando a un commit
  anterior a la release (peor que no tenerlo). Queda documentado el comando
  exacto para ejecutarlo tras el commit del usuario:

  ```bash
  git tag -a v1.0.0 -m "ODIN 1.0.0: release estable (Firebird 2.5-6, gbak, 7z, SFTP, correo, servicio residente)"
  ```

  El push del tag queda para cuando exista remoto.

**Evidencia:** `uv lock` → `Updated odin v0.1.0 -> v1.0.0`; `uv run odin
--version` → `odin 1.0.0`; `grep -rn "0\.1\.0" README.md pyproject.toml src/
tests/ CHANGELOG.md` → sin coincidencias; `uv run pytest tests/test_smoke.py
tests/test_packaging.py tests/test_ci_workflow.py -q` → **11 passed + 3
skipped**; `ODIN_BUILD_ARTIFACTS=1 uv run pytest tests/test_packaging.py -q`
→ **4 passed in 9.33 s** (build real + `uv tool install` aislado + `odin
1.0.0` + `validate`/`service status`); `uv build` → `odin-1.0.0-py3-none-any.whl`
y `odin-1.0.0.tar.gz` con `Version: 1.0.0`, `License-Expression: MIT` y
`Classifier: Development Status :: 5 - Production/Stable` en `METADATA`; suite
completa `uv run pytest -q` → **652 passed + 8 skipped in 79.53 s**; `uv run
ruff check src/odin tests` → All checks passed; `uv run mypy src/odin` →
Success 19 files. Tag `v1.0.0` pendiente al commit (comando en la decisión);
`git tag -l` sigue vacío.

## Prerequisites

- **Servicios requeridos**: ninguno para los tests por defecto (el build real
  usa la caché de `uv`); Docker no hace falta.
- **Configuración de entorno**: `ODIN_BUILD_ARTIFACTS=1` para el gate de
  empaquetado real; `uv` en el `PATH`.
- **Checklist de validación manual**:
  - [ ] `grep -rn "0\.1\.0"` sobre `README.md`, `pyproject.toml`, `src/`,
        `tests/`, `docs/firebird.md`, `docs/security.md`, `docs/service.md` →
        sin coincidencias.
  - [ ] `uv run odin --version` → `odin 1.0.0`.
  - [ ] `uv build` → wheel/sdist `1.0.0`; `unzip -p <wheel> METADATA` muestra
        `Version: 1.0.0`.
  - [ ] `ODIN_BUILD_ARTIFACTS=1 uv run pytest tests/test_packaging.py -q` →
        verde con la instalación aislada.
  - [ ] `CHANGELOG.md` enlazado desde el README (ruta relativa real).
- **Resultados esperados**: versión `1.0.0` en fuentes, lock y artefactos;
  tests sin constantes de versión; CHANGELOG de release; tag documentado.
- `docs/aide/progress.md` debe reflejar el avance (entregable 🚧 → ✅) al
  completar.
- Al finalizar, actualizar `docs/aide/progress.md` con la evidencia del item
  (este item cierra el entregable "Release/tag `1.0.0`" de la Etapa 8; el
  cierre formal de la etapa es el Item 078).

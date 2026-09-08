# Item 008: Verificación de compatibilidad de dependencias con Python 3.14

> **Work item — Paso 5 del flujo AIDE.** Origen: `docs/aide/queue/queue-001.md`, Item 008. Etapa 1 del roadmap.
>
> **Trazabilidad:** riesgo transversal del roadmap ("Python ≥ 3.14 es muy reciente; confirmar disponibilidad de wheels/soporte de `paramiko`, `py7zr`, `APScheduler` y `pywin32` para 3.14. Si alguna librería no soporta 3.14, decidir pin de versión o ajuste de `requires-python`"), criterio de validación de la Etapa 1 ("Verificación temprana de compatibilidad de dependencias con Python 3.14 (documentar resultado)"), visión §4 (stack: paramiko excluyente, py7zr, APScheduler, pywin32), §7 Restricciones ("Python ≥ 3.14", "Instalación únicamente vía uv"), NFR Portabilidad (misma base de código Windows Server / Linux LTS), NFR Mantenibilidad ("dependencias mínimas"). Cierra el criterio de aceptación de la Etapa 1 "Compatibilidad de dependencias con Python 3.14 verificada y documentada (riesgo transversal)" y habilita el smoke multiplataforma del Item 009.

---

## Descripción

**Verificar, decidir y documentar** que las cuatro dependencias de runtime de ODIN (`paramiko`, `py7zr`, `apscheduler`, `pywin32`) —y sus transitivas críticas— **resuelven, instalan e importan bajo `requires-python >= 3.14` con uv**, tanto en Linux como en Windows. Ante cualquier conflicto, **decidir y registrar** el pin de versiones soportadas o el ajuste de `requires-python`/`.python-version`, y **documentar la decisión** en el README (o en una nota de decisiones del proyecto).

Este es un **item de verificación y documentación**, no de funcionalidad: el núcleo del entregable es (a) evidencia reproducible de compatibilidad, (b) una decisión de versionado registrada, (c) un **test durable** que fija la compatibilidad como invariante del proyecto, y (d) una sección de README. **No se modifica `src/odin/`.**

### Estado actual (verificado el 2026-09-07, Linux, Python 3.14.5, uv 0.11.17)

Buena parte del riesgo ya está **resuelto de facto** por los Items 001–007 (el proyecto instala y corre en Python 3.14). Lo que falta es **formalizarlo, decidir el versionado y dejarlo verificado de forma reproducible y durable**:

- `requires-python = ">=3.14"` y `.python-version = 3.14` ya fijados (Item 001).
- `uv.lock` es **universal** (multiplataforma) y está **al día**: `uv lock --check` → "Resolved 37 packages". Contiene las 4 dependencias y sus transitivas resueltas para **todas** las plataformas, incluidos los wheels de `pywin32` para Windows.
- Las 4 dependencias y sus transitivas críticas **resuelven y son compatibles con 3.14** (ver matriz abajo). En Linux, `paramiko`, `py7zr` y `apscheduler` **importan correctamente**; `pywin32` **no se instala** en Linux (marker `sys_platform == 'win32'`) — comportamiento esperado y correcto.
- `uv sync` es idempotente y `uv run pytest -q` → **196 passed** (baseline verde).
- `progress.md` ya marca el criterio de compatibilidad como `[x]` ("verificada en Linux (Item 001); pendiente confirmación en Windows (Item 009)") — pero **no existe un artefacto durable** (test) ni una **decisión de versionado documentada**, y el hallazgo del floor de `pywin32` (abajo) **no está registrado**.

### Hallazgo clave: el floor declarado de `pywin32` es insatisfacible en Python 3.14

El `pyproject.toml` declara `pywin32>=310`. Verificado contra PyPI:

| pywin32 | ¿Wheels `cp314` (win32/amd64/arm64)? |
|---|---|
| 310 | **NO** — no instalable en Python 3.14 |
| 311 | Sí (primer release con cp314) |
| 312 | Sí (**resuelto en `uv.lock`**) |

uv **no** se rompe porque su resolución es *wheel-aware*: descarta 310 (sin wheel cp314) y elige 312. Pero el floor declarado `>=310` es **engañoso** — el mínimo real para Python 3.14 es **311**. Este item debe **decidir y documentar** si se sube el floor (recomendado: `>=311`, el mínimo verdadero; o `>=312`, lo probado/lockeado) para que la restricción declarada coincida con la realidad.

### Lo que falta y es el núcleo de este item

1. **Matriz de compatibilidad documentada** (versión resuelta, `Requires-Python`, evidencia de soporte 3.14) para las 4 deps + transitivas críticas, con la evidencia Linux (import real) y la evidencia Windows (wheels cp314 en el lock universal).
2. **Decisión de versionado registrada:** política de floors (`>=`) en `pyproject.toml` + lock exacto reproducible (`uv.lock`); corrección del floor de `pywin32` (subir a `>=311`/`>=312`); confirmación de que APScheduler queda en la **serie 3.x** (3.11.3), no la 4.x.
3. **Test durable de compatibilidad** (`tests/test_deps_compat.py`): afirma que las deps multiplataforma importan bajo 3.14 y que `pywin32` solo se importa/verifica en `win32` (skip elsewhere). Convierte la compatibilidad en un invariante que falla si una actualización futura la rompe.
4. **Sección de README** "Compatibilidad de dependencias (Python 3.14)" con la matriz resumida y la decisión (o, alternativamente, una nota `docs/aide/notes/python-3.14-compat.md` enlazada desde el README).
5. **Confirmación en Windows real diferida al Item 009** (el entorno de desarrollo es Linux): acá se deja la evidencia estática más fuerte disponible (lock universal con wheels cp314 + markers correctos) y el test listo para correr en Windows.

### Principios que rigen este item

- **Sin cambios en `src/odin/`.** Este item agrega un módulo de test, documentación y (decisión) un posible ajuste de floors en `pyproject.toml`; **no toca** el código de producción. Regresión: los 196 tests existentes siguen pasando.
- **Verificación reproducible y no destructiva.** No se borra `uv.lock` ni se fuerza un re-resolve que pueda cambiar versiones; se verifica con `uv lock --check`, `uv sync --frozen` y smoke de import. La evidencia se documenta con los comandos exactos.
- **La evidencia Windows es estática (lock universal), la runtime es del Item 009.** Sin máquina Windows disponible, lo verificable acá es que el lock universal resuelve `pywin32` con wheels cp314 y markers correctos; el `import win32serviceutil` real en Windows se confirma en el Item 009.
- **Decisión registrada, no implícita.** El riesgo transversal exige una decisión explícita de versionado. Se documenta en el README (fuente de verdad operativa) y en el log de decisiones de este item.
- **Durable por diseño.** El test de compatibilidad es el artefacto que evita la regresión futura: si un bump de dependencia rompe 3.14, `pytest` lo detecta.

## Alcance

| Incluido | Excluido (diferido) |
|---|---|
| Matriz de compatibilidad (4 deps + transitivas críticas) con evidencia Linux (import) y Windows (wheels cp314 en lock) | Smoke multiplataforma real en Windows Server (`uv sync`/`pytest`/`odin validate` nativos) → **Item 009** |
| Decisión de versionado: floors `>=` + `uv.lock` exacto; corrección del floor de `pywin32`; APScheduler 3.x | `odin run`/backup/compresión/SFTP (Etapas 2–5) que ejercitan runtime las deps |
| `tests/test_deps_compat.py`: import multiplataforma + `pywin32` solo en `win32` | Decisión APScheduler 3.x vs 4.x vs stdlib de fondo → **Etapa 6** (acá solo se documenta que el lock está en 3.11.3) |
| Sección "Compatibilidad de dependencias (Python 3.14)" en `README.md` (o nota enlazada) | Matriz de versiones de Firebird y `uv tool install` en limpio → **Etapa 8** |
| Verificación no destructiva: `uv lock --check`, `uv sync --frozen`, smoke de import, `pytest` | Cambios en `src/odin/`, en fixtures/tests existentes o en el esquema de configuración |
| Registro de la decisión en `docs/aide/progress.md` (nota del criterio de compatibilidad) | Ajuste de `requires-python`/`.python-version` (no hace falta: 3.14 es viable; solo se documenta la decisión de **mantenerlo**) |

## Criterios de Aceptación

1. **Matriz de compatibilidad verificada y documentada.** Para cada dependencia de runtime, la versión resuelta en `uv.lock`, su `Requires-Python` y la evidencia de soporte 3.14 quedan registradas (README o nota) y coinciden con el estado real del lock:

   | Dependencia | Floor (`pyproject.toml`) | Resuelta (`uv.lock`) | `Requires-Python` | Soporte 3.14 — evidencia |
   |---|---|---|---|---|
   | `paramiko` | `>=3.5` | `5.0.0` | `>=3.9` | Linux: `import paramiko` OK. Pure-Python sobre `cryptography`/`pynacl`/`bcrypt` (todas con wheels cp314). |
   | `py7zr` | `>=1.0` | `1.1.3` | `>=3.10` | Linux: `import py7zr` OK. Transitivas (`pybcj`, `pyppmd`, `multivolumefile`, `inflate64`, `texttable`, `pycryptodomex`, `brotli`) resueltas en el lock. |
   | `apscheduler` | `>=3.11` | `3.11.3` | `>=3.8` | Linux: `import apscheduler` OK. **Serie 3.x** (no 4.x). Transitivas `tzlocal`/`tzdata` resueltas. |
   | `pywin32` | `>=310` → **`>=311`** (decisión) | `312` | `>=3.9` | Windows (estático): `uv.lock` contiene wheels **`cp314-cp314-win32`/`-win_amd64`/`-win_arm64`** (pywin32 312, subidos 2026-06-04) con marker `sys_platform == 'win32'`. En Linux no se instala (marker) — esperado. |

   Transitivas críticas (todas con `Requires-Python` compatible con 3.14 y wheels cp314 en el lock): `cryptography 50.0.1` (`>=3.9,!=3.9.0,!=3.9.1`), `pynacl 1.6.2` (`>=3.8`), `bcrypt 5.0.0` (`>=3.8`), `cffi 2.1.1` (`>=3.10`), `tzlocal 5.4.4`.

2. **Resolución universal al día y reproducible.** `uv lock --check` pasa sin cambios (el lock universal es consistente con `pyproject.toml` y `requires-python >= 3.14` para **todas** las plataformas, Windows incluida). `uv sync --frozen` instala exactamente las versiones lockeadas sin re-resolver.

3. **Smoke de import en Linux (Python 3.14).** `paramiko`, `py7zr` y `apscheduler` importan y exponen `__version__`; `pywin32` **no** está instalado en Linux (marker) y su ausencia es el comportamiento correcto, no un fallo.

4. **Floor de `pywin32` corregido y documentado.** `pyproject.toml` declara un floor de `pywin32` que **sí** es satisfacible en Python 3.14 (`>=311`, primer release con wheels cp314; o `>=312`, lo lockeado). La decisión (valor elegido y motivo) queda registrada en el README/nota y en el log de decisiones. Tras el cambio, `uv lock` sigue resolviendo 312 y `uv lock --check` pasa. *(Si se decide mantener `>=310`, debe documentarse explícitamente que uv lo descarta por ausencia de wheel cp314 y que el mínimo efectivo es 311 — pero la opción recomendada es subir el floor.)*

5. **Decisión de versionado registrada.** Queda documentado que: (a) `pyproject.toml` usa **floors `>=`** (compatibilidad declarada) y `uv.lock` fija las **versiones exactas** (reproducibilidad); (b) se **mantiene `requires-python >= 3.14`** y `.python-version = 3.14` (no hace falta relajar porque todas las deps son viables en 3.14); (c) APScheduler queda en la **serie 3.x** (3.11.3), y la evaluación 3.x vs 4.x vs stdlib es propia de la Etapa 6.

6. **Test durable de compatibilidad** `tests/test_deps_compat.py` (nuevo), como mínimo: (a) `paramiko`, `py7zr`, `apscheduler` importan y tienen `__version__` no vacío; (b) las versiones instaladas satisfacen los floors declarados en `pyproject.toml` (leídos de `importlib.metadata`, sin hardcodear); (c) `pywin32` (`import win32serviceutil`) se verifica **solo** cuando `sys.platform == 'win32'` y se **skipea** en el resto (no falla en Linux); (d) el lock universal incluye wheels cp314 de `pywin32` para win — verificación estática leyendo `uv.lock` (texto), estable en cualquier plataforma. **≥ 5 tests nuevos.**

7. **Sección de README** "Compatibilidad de dependencias (Python 3.14)" con la matriz resumida (criterio 1), la decisión de versionado (criterios 4–5) y la nota de que la confirmación **runtime en Windows** corresponde al Item 009. (Alternativa aceptable: `docs/aide/notes/python-3.14-compat.md` con la matriz completa, enlazado desde una línea del README.)

8. **Gates verdes sin cambios en `src/`.** `uv run pytest -q` (196 previos + nuevos), `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy` (sin cambios en `src/odin`, sigue limpio). Si se ajusta el floor de `pywin32`, `uv lock --check` sigue pasando y el lock no cambia de versiones (312 ya satisface `>=311`).

### Contenido de referencia — evidencia recolectada (Linux, Python 3.14.5, uv 0.11.17)

Comandos y salidas reales que respaldan la matriz (reproducibles):

```bash
# Lock universal al día (no destructivo)
uv lock --check                       # → "Resolved 37 packages"

# Instalación idempotente contra el lock
uv sync --frozen                      # → sin re-resolver; instala versiones lockeadas

# Smoke de import multiplataforma (pywin32 excluido por marker en Linux)
uv run python -c "import paramiko, py7zr, apscheduler as a; \
print(paramiko.__version__, py7zr.__version__, a.__version__)"
# → 5.0.0 1.1.3 3.11.3

# Requires-Python efectivo de cada dep instalada
uv run python -c "from importlib.metadata import metadata as m, version as v; \
[print(p, v(p), m(p).get('Requires-Python')) for p in \
('paramiko','py7zr','apscheduler','cryptography','pynacl','bcrypt','cffi')]"

# Evidencia Windows estática: wheels cp314 de pywin32 en el lock universal
grep -E 'pywin32-312-cp314.*win' uv.lock
# → pywin32-312-cp314-cp314-win32.whl / -win_amd64.whl / -win_arm64.whl
```

Wheels cp314 de `pywin32` presentes en `uv.lock` (marker `sys_platform == 'win32'`):
`pywin32-312-cp314-cp314-win32.whl`, `pywin32-312-cp314-cp314-win_amd64.whl`, `pywin32-312-cp314-cp314-win_arm64.whl` (upload-time 2026-06-04).

## Pasos de Implementación

1. **Re-verificar el estado** con los comandos de referencia (no destructivos): `uv lock --check`, `uv sync --frozen`, smoke de import, `Requires-Python` por dep, y `grep` de wheels cp314 de `pywin32` en `uv.lock`. Confirmar que coinciden con la matriz del criterio 1.
2. **Decidir el floor de `pywin32`** (criterio 4). Recomendado: subir `pywin32>=310` → `pywin32>=311` (mínimo verdadero con cp314). Editar `pyproject.toml` y correr `uv lock` — debe seguir resolviendo 312 (sin cambio de versiones) y `uv lock --check` debe pasar.
3. **Crear `tests/test_deps_compat.py`** (criterio 6) siguiendo el patrón de los módulos existentes (`from __future__ import annotations`). Leer floors de `pyproject.toml` con `tomllib` (stdlib 3.11+) y comparar contra `importlib.metadata.version`; `pywin32` con `@pytest.mark.skipif(sys.platform != "win32", …)`; verificación estática del lock leyendo `uv.lock` como texto.
4. **Documentar la decisión y la matriz** en `README.md` (sección "Compatibilidad de dependencias (Python 3.14)") o en `docs/aide/notes/python-3.14-compat.md` enlazado (criterios 1, 4, 5, 7). Incluir la nota "confirmación runtime en Windows → Item 009".
5. **Gates:** `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv lock --check`. Commitear fuentes, `pyproject.toml`/`uv.lock` (si cambió el floor), test y docs apenas pasan los gates (lección del incidente del Item 002: no dejar trabajo sin commit).
6. **Actualizar `docs/aide/progress.md`** según el "Recordatorio de Completado".

## Estrategia de Testing

- **Compatibilidad como invariante (test durable):** `tests/test_deps_compat.py` no solo documenta, **protege**: si una actualización futura de una dep deja de soportar 3.14 (o el import falla), `pytest` lo detecta. Es el artefacto que da valor duradero a un item de verificación.
- **Floors leídos, no hardcodeados:** el test compara `importlib.metadata.version(dep)` contra el floor declarado en `pyproject.toml` (vía `tomllib`). Así, si el floor se ajusta (p. ej. `pywin32>=311`), el test sigue siendo correcto sin edits.
- **`pywin32` condicionado por plataforma:** `import win32serviceutil` solo tiene sentido en Windows. En Linux el test se **skipea** (`skipif sys.platform != "win32"`), no falla. La ausencia de `pywin32` en Linux es correcta (marker `sys_platform == 'win32'`).
- **Evidencia Windows estática, verificable en cualquier plataforma:** un test lee `uv.lock` (texto) y afirma que existen entradas `pywin32-…-cp314-…win_amd64.whl` con marker `sys_platform == 'win32'`. Esto prueba que la **resolución universal** cubre Windows+3.14 sin necesitar una máquina Windows (que se confirma runtime en el Item 009).
- **No destructivo:** no se borra el lock ni se fuerza re-resolve; se usa `uv lock --check` y `uv sync --frozen`. La reproducibilidad se afirma verificando que el lock está al día.
- **Regresión:** los 196 tests previos pasan sin edits (no se tocan fixtures ni tests existentes; `src/odin/` intacto).
- **Gates:** `uv run pytest -q`, `uv run ruff check .` (aplica a `tests/`), `uv run ruff format --check .`, `uv run mypy` (solo `src/odin`, sin cambios), `uv lock --check`.

## Dependencias

- **De items anteriores:** Item 001 (`pyproject.toml` con las 4 deps, `requires-python >= 3.14`, `.python-version`, `uv.lock`, configuración de pytest) — ✅. Items 002–007 demuestran que el proyecto **corre** en 3.14 (196 tests verdes) — ✅.
- **Bloquea a:** Item 009 (smoke multiplataforma que corre `uv sync`/`pytest`/`odin validate` en Windows real, confirmando runtime lo que acá se verifica estáticamente); Etapa 6 (decisión APScheduler 3.x vs 4.x vs stdlib parte de la serie 3.x documentada acá); Etapa 7 (`pywin32` para el Windows Service — el floor cp314 correcto es prerrequisito); Etapa 8 (`uv tool install` en limpio y matriz de plataformas).

## Prerrequisitos de Testing

> **Adaptación de plantilla:** sección adaptada al proyecto — no hay servicios externos ni red (verificación de dependencias y resolución de paquetes). El foco del checklist es la resolución/instalación con uv, el smoke de import y la evidencia estática de Windows en el lock universal.

### Servicios Requeridos
- Ninguno. **No** se requieren Firebird, SFTP ni SMTP: este item verifica resolución/instalación/import de paquetes Python, no runtime de las features. Sin red propia (solo `uv`/PyPI para resolver, que ya está cacheado en `uv.lock`).

### Configuración de Entorno
- Entorno del Item 001 operativo: `uv sync` (Python 3.14 vía `.python-version`), uv disponible.
- Sin variables de entorno obligatorias (`ODIN_CONFIG` no aplica; los tests la aíslan si hiciera falta).
- Sin secretos ni puertos.
- Hechos del entorno de desarrollo (Linux, sin máquina Windows) que explican los resultados esperados:
  - `pywin32` **no se instala** en Linux (marker `sys_platform == 'win32'`): `import win32serviceutil` falla en Linux → el test lo **skipea**, no es un error.
  - La evidencia de Windows es **estática** (wheels cp314 en el `uv.lock` universal); la confirmación **runtime** en Windows Server es del **Item 009**.
  - `uv.lock` es universal: un único lock cubre Linux y Windows; `uv lock --check` valida la resolución para **todas** las plataformas.

### Checklist de Validación Manual

- [ ] **Lock al día (no destructivo):** `uv lock --check` → "Resolved N packages", sin diff.
- [ ] **Instalación congelada:** `uv sync --frozen` instala las versiones lockeadas sin re-resolver.
- [ ] **Tests pasan:** `uv run pytest -q` → **196 previos + ≥ 5 nuevos** (suite ~201+), incluido `tests/test_deps_compat.py`.
- [ ] **Lint/tipos:** `uv run ruff check .` → "All checks passed!"; `uv run ruff format --check .` → sin diffs; `uv run mypy` → "Success: no issues found in 6 source files" (sin cambios en `src/`).
- [ ] **Smoke de import (Linux):** `uv run python -c "import paramiko, py7zr, apscheduler; print(paramiko.__version__, py7zr.__version__, apscheduler.__version__)"` → `5.0.0 1.1.3 3.11.3`.
- [ ] **`pywin32` ausente en Linux es esperado:** `uv run python -c "import win32serviceutil"` falla con `ModuleNotFoundError` (marker); el test correspondiente se **skipea**.
- [ ] **Evidencia Windows estática:** `grep -E 'pywin32-312-cp314.*win' uv.lock` lista los 3 wheels (`win32`, `win_amd64`, `win_arm64`) con marker `sys_platform == 'win32'`.
- [ ] **Floor de `pywin32` corregido (si se decide):** `pyproject.toml` declara `pywin32>=311` (o `>=312`); tras `uv lock`, sigue resolviendo 312 y `uv lock --check` pasa.
- [ ] **`Requires-Python` compatibles:** cada dep instalada reporta `Requires-Python` que admite 3.14 (paramiko `>=3.9`, py7zr `>=3.10`, apscheduler `>=3.8`, pywin32 `>=3.9`, cryptography `>=3.9,!=3.9.0,!=3.9.1`, pynacl/bcrypt `>=3.8`, cffi `>=3.10`).
- [ ] **README/nota actualizados:** sección "Compatibilidad de dependencias (Python 3.14)" con matriz resumida + decisión de versionado + nota "runtime Windows → Item 009".

### Resultados Esperados

- **Archivos nuevos:** `tests/test_deps_compat.py`; (opcional, si se elige la nota) `docs/aide/notes/python-3.14-compat.md`.
- **Archivos modificados:** `README.md` (sección de compatibilidad) o la nota enlazada; `pyproject.toml` (+ `uv.lock` sin cambio de versiones) **si** se sube el floor de `pywin32`; `docs/aide/progress.md` (nota del criterio de compatibilidad + "Última actualización").
- **Intactos:** `src/odin/**`, `tests/fixtures/**`, `tests/test_{config,paths,log,cli,validate,smoke,fixtures}.py`, `.python-version`, `requires-python`.
- **Comportamiento observable:** las 4 deps (y transitivas) resuelven e importan bajo 3.14 en Linux; el lock universal prueba la resolución Windows+cp314; `pytest` verde con el nuevo test de compatibilidad; decisión de versionado documentada.
- **≥ 5 tests nuevos** pasando; suite total ~201+.

### Plantilla de Documentación de Validación

```markdown
## Validation Results
- [x] Servicio iniciado: N/A (sin servicios externos; verificación de dependencias/resolución)
- [x] Aplicación ejecutada: smoke de import bajo Python 3.14 (paramiko 5.0.0, py7zr 1.1.3,
      apscheduler 3.11.3); pywin32 ausente en Linux por marker (esperado, test skipeado)
- [x] Tablas/BD verificadas: N/A
- [x] Datos semilla verificados: N/A — evidencia = matriz de compatibilidad (versión resuelta,
      Requires-Python, wheels cp314 de pywin32 en uv.lock universal)
- [x] Endpoints verificados: N/A (sin red propia; solo uv/PyPI para resolver, cacheado en uv.lock)
- [x] Lock: `uv lock --check` al día · `uv sync --frozen` instala versiones lockeadas
- [x] pytest: ~201 passed (196 previos + ≥5 nuevos en test_deps_compat.py) · ruff · mypy · uv lock --check: OK
- [ ] Runtime Windows real (import win32serviceutil + pytest nativo): DIFERIDO al Item 009
```

## Adaptaciones de Plantilla (documentadas)

- Se omiten "Servicios Requeridos"/"Health checks"/"Seed data": el item es verificación de resolución/instalación de paquetes, sin red ni servicios. Se sustituyen por un checklist de **`uv lock --check` + `uv sync --frozen` + smoke de import + evidencia estática de wheels cp314 en el lock universal + gates**.
- Se agrega la sección **Contenido de referencia — evidencia recolectada** con los comandos exactos y salidas reales (matriz de versiones, `Requires-Python`, wheels cp314 de `pywin32`): es la evidencia reproducible contra la que se escribe el test y la documentación.
- Se documenta el **hallazgo del floor de `pywin32`** (310 sin wheels cp314; mínimo real 311) como decisión explícita — es el resultado concreto del "decidir pin de versiones" que pide el riesgo transversal del roadmap.
- Se distingue explícitamente **evidencia Linux (runtime, import real)** de **evidencia Windows (estática, lock universal)**, y se difiere la confirmación runtime en Windows al Item 009 — coherente con el patrón de los Items 006/007.
- El **test durable** (`test_deps_compat.py`) es la adaptación principal: convierte un item de verificación puntual en un invariante protegido por la suite.

## Fuera de Alcance (explícito)

- **Confirmación runtime en Windows Server** (`uv sync`/`pytest`/`odin validate`/`import win32serviceutil` nativos): corresponde al **Item 009**. Acá solo se aporta la evidencia estática (lock universal con wheels cp314) y el test listo para correr en Windows.
- **Ejercitar runtime las dependencias** (respaldo con gbak, compresión con py7zr, SFTP con paramiko, scheduler con APScheduler, servicio con pywin32): son las Etapas 2–7; este item verifica que **resuelven e importan**, no su comportamiento funcional.
- **Decisión de fondo APScheduler 3.x vs 4.x vs stdlib:** es de la **Etapa 6** (`src/odin/scheduler.py`). Acá solo se documenta que el lock está en la **serie 3.x** (3.11.3) y se fija ese estado como punto de partida.
- **Ajuste de `requires-python`/`.python-version`:** **no** se relaja ni se cambia — 3.14 es viable para todas las deps. Se **documenta la decisión de mantenerlo** (parte del criterio 5), no se edita.
- **Matriz de versiones de Firebird, `uv tool install` en limpio, CI multiplataforma:** Etapa 8.
- **Actualización/bump de dependencias** más allá del floor de `pywin32`: no se buscan versiones más nuevas; se verifica y documenta lo que el lock ya resuelve.

## Decisions & Trade-offs

> **To be updated during implementation.** Las decisiones siguientes están **pre-marcadas** (propuestas de diseño de este work item) para confirmarse o ajustarse durante la ejecución; las que surjan en la implementación se numeran a continuación.

1. **Mantener `requires-python >= 3.14` y `.python-version = 3.14`** (no relajar a 3.13). Verificado: las 4 deps y sus transitivas críticas son viables en 3.14 (matriz del criterio 1). Trade-off: 3.14 es reciente y el ecosistema aún madura; se mitiga con el lock exacto y el test durable que detecta regresiones. Relajar el floor no aporta valor y contradice la restricción de la visión §7.
2. **Política de versionado: floors `>=` en `pyproject.toml` + `uv.lock` exacto.** El `pyproject` declara la compatibilidad mínima (floors); el lock fija las versiones concretas para reproducibilidad (`uv sync --frozen`). Trade-off: los floors amplios permiten futuras versiones no probadas, pero el lock las congela; el test de floors + la suite dan la red de seguridad.
3. **Subir el floor de `pywin32` a `>=311`** (mínimo verdadero con wheels cp314; 310 no los tiene). Recomendado sobre mantener `>=310` (engañoso: uv lo descarta por ausencia de wheel, pero la restricción declarada no refleja la realidad) y sobre `>=312` (más estricto de lo necesario; 311 ya soporta 3.14). Trade-off: `>=311` excluye instalaciones en Python < 3.14 con pywin32 310, irrelevante porque el proyecto exige 3.14. Tras el cambio, `uv lock` sigue resolviendo 312 (sin cambio de versiones).
4. **Documentar APScheduler en la serie 3.x (3.11.3), decisión de fondo diferida a Etapa 6.** El lock resuelve 3.11.3 (serie 3.x, estable y con semántica cron/misfire que el roadmap necesita); la evaluación 3.x vs 4.x vs stdlib es propia del Item de scheduler. Trade-off: no se explora 4.x ahora (evita scope creep); se fija el estado actual como punto de partida documentado.
5. **Evidencia Windows estática vía lock universal; runtime diferido al Item 009.** Sin máquina Windows, lo verificable es que `uv.lock` (universal) resuelve `pywin32` cp314 para win con markers correctos; el `import win32serviceutil` nativo se confirma en el Item 009. Trade-off: no hay prueba runtime de Windows en este item; se mitiga con el test estático del lock + el test de import condicionado a `win32` (listo para correr allá).
6. **Test durable que lee floors de `pyproject.toml` (no hardcodeados).** `test_deps_compat.py` compara versiones instaladas contra los floors declarados vía `tomllib` + `importlib.metadata`, y lee `uv.lock` como texto para la evidencia cp314. Trade-off: acopla el test al formato del lock/pyproject; se justifica porque son estables y el test debe fallar si cambia la compatibilidad.
7. **Verificación no destructiva (`uv lock --check` / `uv sync --frozen`).** No se borra el lock ni se fuerza re-resolve (podría cambiar versiones y romper reproducibilidad). Trade-off: no se prueba una resolución "from scratch" contra PyPI en vivo; se mitiga porque `uv lock --check` valida la consistencia del lock universal con `pyproject.toml` para todas las plataformas.

## Recordatorio de Completado

> **IMPORTANTE:** al completar este item, actualizar `docs/aide/progress.md` (**solo** las filas correspondientes al Item 008, según la regla de scoping de `/speckit.aide.execute-item`):
>
> - Criterio de aceptación de la Etapa 1 "[x] Compatibilidad de dependencias con Python 3.14 verificada y documentada (riesgo transversal)": ya está `[x]`; **enriquecer la nota** para reflejar el Item 008 — matriz de compatibilidad documentada (paramiko 5.0.0 / py7zr 1.1.3 / apscheduler 3.11.3 / pywin32 312), floor de `pywin32` corregido a `>=311`, test durable `tests/test_deps_compat.py`, decisión registrada en el README; **confirmación runtime en Windows → Item 009**.
> - Entregable de la Etapa 1 "📋 `uv sync` + `uv run pytest` funcionando en Linux y Windows": **NO** marcarlo completo (falta Windows runtime → Item 009). Opcionalmente agregar nota: "Linux verificado (Item 008: lock universal al día, import OK, ~201 tests); Windows runtime pendiente (Item 009)".
> - Línea "**Última actualización:**" → fecha del día + "(Item 008 completo ✅)".
> - **No** marcar: el estado de la Etapa 1 (🚧, se cierra al completar el Item 009), las filas F3/F6 de la tabla de funcionalidades, los objetivos G1–G7 ni los NFR (se cierran en etapas posteriores). El riesgo transversal del roadmap queda **verificado y documentado** en Linux + evidencia estática de Windows.

## Próximo Paso

Iniciar una **nueva sesión de chat** y ejecutar `/speckit.aide.execute-item` con el número **008** para implementar (verificación, decisión de versionado, `tests/test_deps_compat.py`, sección de README, actualización de `progress.md`).

Al completar el Item 008, la Etapa 1 queda con **un solo pendiente**: el smoke multiplataforma del **Item 009** (`uv sync` + `uv run pytest` + `odin validate --config examples/config.<plataforma>.json` en Linux **y Windows** reales), que cerrará la Etapa 1 y habilitará la Etapa 2 (gbak).

**Nota para el Item 009:** la evidencia estática de Windows de este item (wheels cp314 de `pywin32` en el lock universal) debe confirmarse runtime en Windows Server: `uv sync --frozen`, `uv run pytest -q` (incluido `test_deps_compat.py` con el `import win32serviceutil` **no** skipeado), y `odin validate --config examples/config.windows.json` → exit 0.

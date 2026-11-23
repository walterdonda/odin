# ODIN — Compatibilidad de dependencias (Python 3.14)

ODIN exige Python **≥ 3.14** (`requires-python = ">=3.14"` en
`pyproject.toml`), gestionado con [uv](https://docs.astral.sh/uv/). Esta guía
reúne la evidencia de compatibilidad de las dependencias con 3.14 y las
decisiones de versionado que la sostienen.

## Matriz de compatibilidad

| Dependencia | Versión resuelta | `Requires-Python` | Evidencia de soporte 3.14 |
|---|---|---|---|
| `paramiko` | 5.0.0 | `>=3.9` | Linux: `import paramiko` OK. |
| `py7zr` | 1.1.3 | `>=3.10` | Linux: `import py7zr` OK. |
| `apscheduler` | 3.11.3 | `>=3.8` | Linux: `import apscheduler` OK. |
| `pywin32` | 312 | `>=3.11` | Windows (estático): `uv.lock` contiene wheels `cp314` para `win32/amd64/arm64`. |
| `tzdata` | 2026.3 | — (wheel universal `py2.py3`) | Datos IANA para `zoneinfo`; Item 072: sin datos del SO (contenedor Linux mínimo) `odin validate` fallaba, y Windows tampoco trae tzdata del SO. |

## Decisiones de versionado

- El floor de `pywin32` subió a `>=311` para reflejar el soporte real de
  wheels `cp314` en Python 3.14.
- `tzdata` es dependencia directa (Item 072): `zoneinfo` la necesita para
  `scheduler.timezone`/cron cuando el SO no trae la base IANA (contenedores
  Linux mínimos y Windows); con datos del SO actúa solo como fallback.
- Se mantiene `requires-python >= 3.14`.

## Windows: usar una 3.14 final, no la alpha gestionada de uv

El registro gestionado de uv solo ofrece `cpython-3.14.0a6` (alpha) para
Windows: es previa a la sintaxis PEP 758 y su ABI no es compatible con los
wheels `cp314` finales de las dependencias (`cffi`/`pycryptodomex` mueren con
`TypeError: bad argument type for built-in operation`), así que aunque el
entorno se instale, `odin` no corre.

- Instalar Python 3.14 **final** (p. ej. `winget install
  Python.Python.3.14` o el instalador de python.org).
- Crear el entorno con `uv tool install --python <ruta>\python.exe …` (o
  `uv sync --python <ruta>\python.exe`).
- Verificar con `python --version` que la versión **no tenga sufijo `a`**.

La confirmación runtime en Windows Server queda delegada al job `windows` de la
CI (Items 073/074; ver [`docs/service.md` §9](service.md#9-evidencia-de-verificación-item-074)).

## Invariante

El test `tests/test_deps_compat.py` actúa como invariante para prevenir
regresiones en la compatibilidad: fija las versiones resueltas de la matriz y
falla si la resolución cambia sin revisar la evidencia.

# README.md (fragment)

## Compatibilidad de dependencias (Python 3.14)

Se ha verificado la compatibilidad de las dependencias principales con Python 3.14. La resolución de paquetes mediante `uv` garantiza que los wheels adecuados para Windows y Linux se instalan correctamente.

### Matriz de compatibilidad

| Dependencia | Versión Resuelta | `Requires-Python` | Evidencia de soporte 3.14 |
|---|---|---|---|
| `paramiko` | 5.0.0 | `>=3.9` | Linux: `import paramiko` OK. |
| `py7zr` | 1.1.3 | `>=3.10` | Linux: `import py7zr` OK. |
| `apscheduler` | 3.11.3 | `>=3.8` | Linux: `import apscheduler` OK. |
| `pywin32` | 312 | `>=3.11` | Windows (estático): `uv.lock` contiene wheels `cp314` para `win32/amd64/arm64`. |

**Decisión de versionado:**
- Se ha subido el floor de `pywin32` a `>=311` en `pyproject.toml` para reflejar el soporte real de wheels `cp3lan` en Python 3.14.
- Se mantiene `requires-python >= 3.14`.
- La confirmación runtime en Windows Server se realizará en el **Item 009**.

*Nota: El test `tests/test_deps_compat.py` actúa como un invariante para prevenir regresiones en la compatibilidad.*

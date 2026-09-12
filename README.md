# ODIN

Respaldo externo de bases de datos Firebird (2.5 → 6): backup con `gbak`,
compresión 7z, transferencia SFTP (paramiko) y notificación por correo.

> Proyecto en desarrollo bajo el flujo AIDE (`docs/aide/`).

## Requisitos

- Python ≥ 3.14 (gestionado con [uv](https://docs.astral.sh/uv/))
- uv
- Firebird cliente o servidor instalado (aporta `gbak`)

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
- Se ha subido el floor de `pywin32` a `>=311` en `pyproject.toml` para reflejar el soporte real de wheels `cp314` en Python 3.14.
- Se mantiene `requires-python >= 3.14`.
- La confirmación runtime en Windows Server se realizará en el **Item 009**.

*Nota: El test `tests/test_deps_compat.py` actúa como un invariante para prevenir regresiones en la compatibilidad.*

```bash
uv sync              # instala dependencias y crea uv.lock
uv run pytest        # ejecuta la suite de tests
uv run odin --version
```

La documentación completa de instalación y operación llegará con el
Item 009 del roadmap.

## Ejemplos de configuración

El directorio [`examples/`](examples/) trae configuraciones de ejemplo listas
para copiar, una por plataforma:

- [`examples/config.linux.json`](examples/config.linux.json) — Linux LTS.
- [`examples/config.windows.json`](examples/config.windows.json) — Windows
  Server.

Ambos reproducen el mismo esquema OS-agnóstico (solo cambian las rutas) con
secretos como placeholder `***`. [`examples/README.md`](examples/README.md)
explica cómo adaptarlos, las recomendaciones de seguridad (permisos `600`/ACL,
no versionar el JSON real) y los campos opcionales con sus valores por
defecto. Validá tu configuración con `odin validate` antes de ejecutar.

## Validación de configuración

```bash
uv run odin validate --config ruta/al/config.json    # o vía ODIN_CONFIG
uv run odin validate --config ruta/al/config.json --strict
```

`odin validate` comprueba, en este orden:

1. **Estructura y tipos** del JSON (campos requeridos, rangos, enums, campos
   desconocidos con sugerencia de typo) y **semántica** (nombres únicos,
   jobs del scheduler que referencian bases existentes, coherencia entre
   `auth.method` y sus credenciales).
2. **Entorno local**: `local.work_dir` y `local.log_dir` (existentes, creables
   o en conflicto), `servers[].auth.private_key` con método `key` (existe, es
   legible, permisos recomendados `600`), `databases[].gbak_path` explícito
   (existe y es ejecutable), permisos del propio JSON, espacio libre vs.
   `local.min_free_mb`.
3. **Coherencia operativa**: scheduler habilitado sin jobs, bases no cubiertas
   por ningún job, ausencia de destinos SFTP, `host_key_policy: insecure`,
   `starttls: false`, retención desactivada.

La salida agrupa los hallazgos en `ERRORES`, `ADVERTENCIAS` y `VERIFICACIONES`,
cada uno con la ruta del campo implicado (p. ej. `config.servers[1].auth.private_key`).
Los errores y el veredicto de invalidez van a stderr; el contexto y el veredicto
de validez, a stdout.

### Garantías

- **Solo lectura:** `validate` no crea ni modifica archivos (el directorio de
  logs lo crea la configuración del logging, después de las verificaciones).
- **Sin red:** no comprueba conectividad SFTP, SMTP ni Firebird; un destino
  temporalmente caído no invalida la configuración.
- **Sin secretos:** la salida y el log nunca incluyen contraseñas,
  passphrases ni contenido de claves privadas.
- **OS-agnóstico:** una ruta cuyo sabor (Windows o POSIX) no coincide con el
  sistema donde se ejecuta no es comprobable: se omite con una nota, nunca
  cuenta como error.

## Ejecución de respaldos (`odin run`)

```bash
uv run odin run --config ruta/al/config.json     # o vía ODIN_CONFIG
```

`odin run` ejecuta la **fase de respaldo** de ODIN sobre todas las bases de la
configuración, en forma secuencial y con aislamiento de fallos: una base que
falla no interrumpe a las siguientes:

1. **Resuelve `gbak`** por base: `databases[].gbak_path` explícito; si es
   `null`, auto-detección por SO y versión de Firebird (rutas típicas de
   Windows/Linux y `PATH`).
2. **Ejecuta `gbak -b`** con timeout propio (`databases[].gbak_timeout_sec` o,
   si no, `local.gbak_timeout_sec`) y los parámetros de conexión `user`,
   `password` and `role` de cada base (nombres completos de switch: `-user`,
   `-password`, `-role`). La contraseña se enmascara en los logs. `gbak` no
   admite un switch de charset: el respaldo transportable no depende del
   charset de conexión, por eso `charset` se conserva en la configuración
   pero no se pasa al comando.
3. **Valida cada `.fbk`**: existe, no está vacío y es legible.
4. **Comprime cada `.fbk` (Etapa 3)**: utiliza `py7zr` para crear archivos
   `.fbk.7z`. El nivel de compresión y el cifrado AES-256 (si se provee
   `compression.password`) son configurables. Los archivos se nombran
   `<nombre_bd>_<timestamp>.fbk.7z` para el backup. El proceso
   mide la duración y el ratio de compresión, reportándolo en los logs.
5. Crea `local.work_dir` si no existe y guarda cada respaldo como
   `<nombre_bd>_<timestamp>.fbk` (timestamp `YYYYMMDD_HHMMSS`).

La transferencia SFTP y el correo se sumarán al pipeline en las
Etapas 3, 4 y 5; hoy `run` cubre solo el respaldo y la compresión.

## Exit codes

| Código | Significado |
|---|---|
| 0 | `validate`: configuración válida (puede tener advertencias) · `run`: todas las bases respaldadas |
| 1 | Error interno inesperado |
| 2 | Error de configuración, de uso de la CLI, o advertencias con `--strict` |
| 3 | `run`: fallo parcial (algunas bases respaldadas y otras con error) |
| 4 | `run`: fallo total (ninguna base respaldada) |

Con `--strict` las advertencias también devuelven 2: útil como gate previo al
despliegue o en CI.


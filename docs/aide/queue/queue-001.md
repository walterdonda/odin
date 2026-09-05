# Queue 001 — Fundaciones (Etapa 1 del roadmap)

> **Paso 4 del flujo AIDE.** Lote de ~10 work items priorizados desde `docs/aide/roadmap.md` y `docs/aide/progress.md`. Cubre la Etapa 1: paquete instalable con uv, configuración JSON OS-agnóstica y `odin validate`. Dimensión total: ~1 semana.
>
> Para ejecutar un item: iniciar una nueva sesión de chat y correr `/speckit.aide.create-item` con la descripción del item.

### Item 001: Esqueleto del paquete y pyproject con dependencias
Crear la estructura base del proyecto con layout `src/`: paquete `src/odin/` con `__init__.py`, directorio `tests/` con smoke test, y `pyproject.toml` actualizado: descripción del proyecto, dependencias (`paramiko`, `py7zr`, `apscheduler`, `pywin32` con marker `sys_platform == "win32"`), `[project.scripts] odin = "odin.cli:main"` y configuración de pytest. Verificar que `uv sync` instala todo y que el paquete es importable (`uv run python -c "import odin"`).

### Item 002: Modelos de configuración y parseo del JSON
Implementar `src/odin/config.py` con dataclasses para las secciones del contrato de configuración (`databases`, `compression`, `servers`, `notification`, `local`, `scheduler`), carga del archivo JSON y validación estructural con mensajes de error claros que indiquen campo, motivo y ubicación. Incluir valores por defecto según la visión (p. ej. `compression.level` por defecto, `gbak_path: null` = auto-detección). Tests unitarios de parseo con JSON válidos y malformados.

### Item 003: Normalización OS-agnóstica de rutas
Implementar `src/odin/paths.py`: normalización con `pathlib` aceptando separadores `/` y `\` indistintamente, expansión de `~`, y resolución de rutas relativas respecto de la ubicación del archivo JSON de configuración. Integrar la normalización en el modelo de configuración para `work_dir`, `private_key` y `gbak_path`. Tests unitarios con rutas POSIX, Windows, `~` y relativas en ambas direcciones de normalización.

### Item 004: Logging con rotación y enmascarado de secretos
Implementar `src/odin/log.py`: logging a consola y a archivo con rotación (directorio de logs dentro de `work_dir` o ruta configurable), nivel configurable, formato con timestamps. Incluir utilidad de enmascarado de secretos (contraseñas, passphrases, contenido de claves) utilizable por logs y, más adelante, por correos. Tests unitarios del enmascarado y de configuración del logger.

### Item 005: CLI con argparse, subcomandos y exit codes
Implementar `src/odin/cli.py` con argparse: subcomando `validate` (y punto de extensión para `run`/`service` de etapas posteriores), opción `--config` con fallback a la variable de entorno `ODIN_CONFIG`, y convención de exit codes: 0 válido, 2 error de configuración, 1 error interno. Verificar que el script de consola `odin` queda disponible tras `uv sync` (`uv run odin --help`).

### Item 006: Lógica completa de `odin validate`
Conectar la CLI con el modelo de configuración para la validación completa: parseo del JSON, validación estructural y de tipos, verificación de rutas locales existentes cuando aplique (p. ej. `private_key` con método `key`, `work_dir` creable), validación de coherencia (jobs del scheduler que referencien bases existentes, métodos de auth válidos). Salida humana legible en consola diferenciando errores y advertencias. Tests de extremo a extremo de `validate` invocando la CLI.

### Item 007: Configuraciones de ejemplo y fixtures de test
Crear `examples/config.linux.json` y `examples/config.windows.json` a partir de los ejemplos de la visión (charset ISO8859_1 incluidos), y fixtures de test: JSON válidos mínimos, JSON con errores de tipo/rango/campos faltantes, y casos de rutas por plataforma. Verificar que ambos ejemplos pasan `odin validate` en la plataforma correspondiente.

### Item 008: Verificación de compatibilidad de dependencias con Python 3.14
Confirmar que `paramiko`, `py7zr`, `apscheduler` y `pywin32` resuelven e instalan correctamente bajo `requires-python >= 3.14` con uv en Linux y Windows (o documentar la incompatibilidad). Ante conflicto, decidir y documentar: pin de versiones soportadas o ajuste de `requires-python`/`.python-version`. Registrar la decisión en el README o en una nota de decisiones del proyecto.

### Item 009: Smoke test multiplataforma del ciclo de desarrollo
Validar el ciclo completo de desarrollo en las dos plataformas objetivo: `uv sync`, `uv run pytest` verde y `uv run odin validate --config examples/config.<plataforma>.json` con exit code 0, tanto en Linux LTS como en Windows Server (o entorno equivalente disponible). Documentar el flujo en un Quickstart del README con los comandos exactos por plataforma.

---

**Total: 9 items.** Al completar este lote, la Etapa 1 del roadmap queda cerrada y la Etapa 2 (gbak) puede comenzar. El siguiente lote (`queue-002.md`) arrancará en el item 010.

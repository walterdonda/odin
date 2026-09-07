# Item 005: CLI con argparse, subcomandos y exit codes

> **Work item — Paso 5 del flujo AIDE.** Origen: `docs/aide/queue/queue-001.md`, Item 005. Etapa 1 del roadmap.

---

## Descripción

Reimplementar `src/odin/cli.py` (hoy stub del Item 001 que solo expone `--version`/`--help`) con argparse: subcomando `validate` funcional cableado a `load_config` (Item 002) y a `setup_logging` (Item 004), opción `--config` con fallback a la variable de entorno `ODIN_CONFIG`, y la convención base de exit codes: **0** válido, **2** error de configuración (y de uso de la CLI), **1** error interno. Los códigos 3 (fallo parcial) y 4 (fallo total) llegan con la Etapa 5 y quedan fuera de alcance.

El subcomando `validate` carga y valida el JSON (validación estructural + semántica ya provista por `config.py`), imprime una confirmación humana legible en stdout y registra el resultado en el log vía `setup_logging(config)` — este es el cableado que el Item 004 dejó explícitamente diferido para los items 005–007. La estructura de subcomandos deja el punto de extensión documentado para `run`/`service` (Etapas 2+); este item **no** registra esos subcomandos.

Este item no agrega lógica de validación nueva (existencia de rutas, advertencias, reporte enriquecido): eso es del Item 006.

## Criterios de Aceptación

1. `build_parser()` registra el subcomando `validate` con opción `--config`; `--version` sigue funcionando; el punto de extensión para `run`/`service` queda documentado en el código (p. ej. docstring de `build_parser`/`main`) sin registrarlos aún.
2. `odin validate --config <ruta válida>` → exit code **0** y confirmación humana legible en stdout (incluye la ruta validada y un resumen mínimo, p. ej. cantidad de bases y servidores).
3. Resolución de la ruta de configuración: `--config` tiene precedencia sobre `ODIN_CONFIG`; sin ninguno de los dos → mensaje claro en stderr (menciona `--config` y `ODIN_CONFIG`) y exit code **2**.
4. Errores de configuración (JSON malformado, problema estructural, problema semántico, archivo ilegible/inexistente) → exit code **2** con el detalle de todos los problemas en stderr (reutilizando `str(ConfigError)`, que ya lista `field_path: mensaje`).
5. Excepción inesperada fuera de `ConfigError` → exit code **1** con mensaje en stderr; el proceso no muere con traceback sin manejar.
6. Tras cargar una config válida, `validate` invoca `setup_logging(config)` (Item 004) y registra la validación en consola y archivo con secretos enmascarados. Si `setup_logging` falla (p. ej. `OSError` porque el directorio de logs no es creable), la validación **igualmente devuelve 0** e imprime una advertencia en stderr: la config es válida, el problema es operativo. Esta postura se confirma o ajusta en Decisions & Trade-offs durante la implementación.
7. Comportamiento sin subcomando se preserva: `main([])` imprime la ayuda y devuelve 0 (el smoke test del Item 001 sigue pasando sin cambios). Subcomando inexistente → error de uso de argparse → exit code 2 (consistente con la convención).
8. Exit codes como constantes de módulo exportadas (`EXIT_OK = 0`, `EXIT_INTERNAL = 1`, `EXIT_CONFIG = 2`) con docstring de la convención completa (incluyendo que 3/4 llegan en la Etapa 5).
9. Console script operativo tras `uv sync`: `uv run odin --help` y `uv run odin validate --config <ruta>` funcionan; `odin` sin args imprime la ayuda con `validate` listado.
10. Tests unitarios/e2e (`tests/test_cli.py`, invocando `main([...])` in-process con `capsys`): config válida por `--config` (exit 0 + stdout + `odin.log` creado en `resolved_log_dir`), válida vía `ODIN_CONFIG`, precedencia `--config` sobre la variable, ausencia de ambos (exit 2 + stderr), archivo inexistente (exit 2), JSON estructuralmente inválido (exit 2 + `field_path` en stderr), error semántico p. ej. nombre de base duplicado (exit 2), excepción inesperada simulada con monkeypatch (exit 1), sin args (ayuda + 0), subcomando inexistente (SystemExit 2).
11. Sin dependencias nuevas; `uv run pytest -q` verde; `uv run ruff check .`, `uv run ruff format --check .` y `uv run mypy` limpios.
12. Los tests existentes (Items 001–004) siguen pasando sin cambios de comportamiento; sin modificaciones a `config.py`/`paths.py`/`log.py` (se consume su API pública).

## Pasos de Implementación

1. **Reescribir `src/odin/cli.py`** (solo stdlib: `argparse`, `os`, `pathlib`, `logging`, `traceback`):
   - Constantes: `EXIT_OK`, `EXIT_INTERNAL`, `EXIT_CONFIG`, `ENV_CONFIG_VAR = "ODIN_CONFIG"`, docstring de módulo con la convención de exit codes (0/2/1 hoy; 3/4 en Etapa 5).
   - `build_parser()`: parser raíz (`prog="odin"`, descripción, `--version`) + `add_subparsers(dest="command")` con `validate` y su `--config`; docstring indicando dónde se registrarán `run`/`service`.
   - Resolución de config: `--config` → `os.environ.get(ENV_CONFIG_VAR)` → error exit 2 con mensaje que menciona ambas vías.
   - `validate`: `load_config(path)`; `ConfigError` → stderr + `EXIT_CONFIG`; éxito → `setup_logging(config)` (con fallback de advertencia si falla), registro en el logger `odin`, confirmación con resumen en stdout → `EXIT_OK`.
   - `main(argv: Sequence[str] | None) -> int`: parseo, dispatch por subcomando, sin subcomando → ayuda + 0; catch de excepciones inesperadas → stderr (mensaje + traceback) + `EXIT_INTERNAL`. Preservar `if __name__ == "__main__": raise SystemExit(main())`.
2. **Tests (`tests/test_cli.py`):** según criterio 10. Usar `tmp_path` para configs y directorios de log: copiar el JSON del fixture `tests/fixtures/config_valid_linux.json` sobreescribiendo `local.work_dir` hacia `tmp_path` (mismo patrón que `_load_fixture_config` de `tests/test_log.py`; reimplementar el helper localmente para no acoplar módulos de test). Para `ODIN_CONFIG` usar `monkeypatch.setenv`/`delenv`; para el exit 1, monkeypatch de `odin.cli.load_config` lanzando `RuntimeError`. Limpiar el logger `odin` entre tests (mismo patrón de fixture que `tests/test_log.py`) para no dejar handlers abiertos.
3. **Verificación de gates:** `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, más la verificación manual del console script.

## Estrategia de Testing

- Tests in-process invocando `main([...])` con `capsys` y `monkeypatch` (sin subprocess): rápidos y con aserciones sobre stdout/stderr/exit code. El console script real (`uv run odin ...`) se verifica manualmente.
- Configs de test generadas en `tmp_path` a partir del fixture válido, mutando solo lo necesario (work_dir, y errores puntuales para los casos inválidos).
- El humo del Item 001 (`tests/test_smoke.py`) actúa como test de regresión del comportamiento sin args y de `--version`.
- Gates: `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`.

## Dependencias

- **De items anteriores:** Item 001 (console script `odin`, smoke tests), Item 002 (`load_config`, `ConfigError`), Item 004 (`setup_logging`, logger `odin`) — todos completados ✅.
- **Bloquea a:** Item 006 (lógica completa de `validate`), Item 007 (configs de ejemplo validadas con esta CLI), Item 009 (smoke multiplataforma), Etapas 2+ (subcomandos `run`/`service`).

## Prerrequisitos de Testing

> **Adaptación de plantilla:** sección adaptada a este proyecto — no hay servicios externos (CLI pura sobre stdlib + módulos ya implementados); el foco del checklist manual son los exit codes.

### Servicios Requeridos
- Ninguno.

### Configuración de Entorno
- Entorno del Item 001 operativo (`uv sync`). Sin variables de entorno obligatorias; `ODIN_CONFIG` se prueba explícitamente con `monkeypatch` en tests y manualmente con prefijo de shell.

### Checklist de Validación Manual
- [x] **Tests pasan:** `uv run pytest -q` verde (suite Items 001–004 intacta + tests nuevos de `test_cli.py`) — 117 passed (102 previos + 15 nuevos).
- [x] **Lint/tipos:** `uv run ruff check . && uv run ruff format --check . && uv run mypy` sin errores.
- [x] **Console script:** `uv run odin --help` lista `validate`; `uv run odin --version` imprime la versión (`odin 0.1.0`); `uv run odin` sin args imprime la ayuda con `validate` y devuelve 0.
- [x] **Exit code 0:** `uv run odin validate --config tests/fixtures/config_valid_linux.json; echo $?` → 0 (advertencia en stderr por `/var/backups/odin` no creable — Permission denied — comportamiento esperado, criterio 6).
- [x] **Fallback env:** `ODIN_CONFIG=tests/fixtures/config_valid_linux.json uv run odin validate; echo $?` → 0.
- [x] **Exit code 2:** `uv run odin validate; echo $?` → 2 (mensaje menciona `--config` y `ODIN_CONFIG`); con `{}` temporal → 2 con 4 `field_path` en stderr; subcomando inexistente (`odin volar`) → 2.
- [x] **Enmascarado/log:** con config de work_dir en `/tmp`, `<resolved_log_dir>/odin.log` existe y contiene la línea `timestamp | INFO | odin | Configuración válida: ... (bases: 1 | servidores SFTP: 2)`.

### Resultados Esperados
- Archivo reescrito: `src/odin/cli.py`. Archivo nuevo: `tests/test_cli.py`.
- Sin modificaciones a `config.py`/`paths.py`/`log.py`; `tests/test_smoke.py` intacto y verde.
- ≥ 10 tests nuevos pasando; ninguna dependencia nueva en `pyproject.toml`.

## Decisions & Trade-offs

1. **Postura ante fallo de `setup_logging` (criterio 6): confirmada.** Se captura únicamente `OSError` (helper `_setup_logging_or_warn`): la config es válida y el problema es operativo → `validate` devuelve 0 con advertencia en stderr. Cualquier otra excepción no se considera "fallo operativo de logging" sino bug → cae al handler global y devuelve 1. Verificado manualmente: con el fixture Linux real (`work_dir=/var/backups/odin`, no creable sin root) el comando da exit 0 + advertencia.
2. **Doble captura de `ConfigError`:** local en `_cmd_validate` (para contextualizar con la ruta: `Configuración inválida en '<ruta>':` + `str(exc)` con todos los `field_path`), más una red de seguridad en `main` que traduce cualquier `ConfigError` que escape de un handler a exit 2. La red deja el punto de extensión listo para los subcomandos futuros (`run`/`service`) y para la lógica ampliada del Item 006 sin depender de que cada handler capture su propio error.
3. **`SystemExit` de argparse no se convierte a `int`:** `main` solo captura `Exception` (`SystemExit` deriva de `BaseException`), así los errores de uso propagan el código 2 de argparse — consistente con la convención — y el smoke test del Item 001 (`--version` → `SystemExit(0)`) sigue pasando sin cambios.
4. **Valores en blanco tratados como ausentes:** `--config ""` u `ODIN_CONFIG` vacía/en blanco caen al mismo mensaje claro (menciona ambas vías) con exit 2, en vez de intentar abrir una ruta sin sentido (que produciría un `OSError` menos legible). Precedencia implementada con `args.config or os.environ.get(...)` (falsy → fallback).
5. **Error interno inesperado: mensaje humano + traceback completo en stderr, exit 1.** El traceback se imprime de forma controlada (`traceback.print_exc()` dentro del handler) en vez de omitirlo: el proceso no muere con una excepción sin manejar (criterio 5) pero el diagnóstico completo queda disponible para reportar bugs.
6. **Resumen mínimo en stdout:** `bases: N | servidores SFTP: M` + la ruta validada, misma cadena que se registra en el logger `odin` (mensaje único compartido consola/archivo). El reporte enriquecido (advertencias, existencia de rutas) queda para el Item 006 por alcance.
7. **Parser: `add_subparsers(dest="command", title="subcomandos")` sin `metavar`** — la línea de uso muestra `{validate}` y se actualizará automáticamente al registrar `run`/`service`; el dispatch en `main` es un `if` con `raise RuntimeError` defensivo para ramas no registradas (inalcanzable hoy: argparse valida las opciones).
8. **Tests in-process con doble fixture `autouse`** en `tests/test_cli.py`: limpieza del logger `odin` (mismo patrón que `test_log.py`, reimplementado localmente para no acoplar módulos de test) y `delenv` de `ODIN_CONFIG` (hermeticidad: un valor del entorno real no puede alterar resultados). Helper `_write_config(tmp_path, mutate=...)` copia el fixture Linux válido y muta solo lo necesario (work_dir, duplicados, etc.). El console script real se verificó manualmente (checklist abajo). 15 tests nuevos, suite total 117.

## Recordatorio de Completado

> **IMPORTANTE:** al completar este item, actualizar `docs/aide/progress.md`: el entregable "CLI argparse: `odin validate --config <ruta>` + variable de entorno `ODIN_CONFIG`; exit codes (0/2/1)" de la Etapa 1 debe pasar de 📋 → 🚧 → ✅, y actualizar la línea de "Última actualización". Este paso es parte de `/speckit.aide.execute-item`.

## Próximo Paso

Al completar, iniciar una **nueva sesión de chat** y ejecutar `/speckit.aide.create-item` con el número **006** (lógica completa de `odin validate`), luego `/speckit.aide.execute-item`.

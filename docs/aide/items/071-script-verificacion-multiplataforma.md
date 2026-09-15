# Item 071: Script de verificación multiplataforma (`scripts/verify.py`) y quickstart

## Description

Crear `scripts/verify.py`, el **gate único** de desarrollo/CI del proyecto: un
script solo stdlib, idéntico en Linux y Windows, ejecutable con
`uv run python scripts/verify.py`, que corre en orden los gates de ODIN y
resume el resultado:

1. `uv sync`
2. `uv run pytest` — con `--quick`: `uv run pytest -m "not integration"`
3. `uv run ruff check src/odin tests`
4. `uv run mypy src/odin`
5. `uv run odin validate --config examples/config.linux.json`
6. `uv run odin validate --config examples/config.windows.json`

Comportamiento requerido:

- Cada paso imprime su comando, su duración y su estado (`OK`/`FALLO` con el
  código de salida) y, si falla, las últimas líneas de su salida (sin volcar
  la salida completa de los pasos verdes).
- Resumen final con el estado por paso y exit code 0 **solo** si todos los
  pasos seleccionados pasan; 1 si alguno falla; 2 si los argumentos son
  inválidos (mismo criterio que la CLI de ODIN).
- Los pasos siguen ejecutándose aunque uno falle (panorama completo en una
  sola corrida), pero el exit code final es distinto de 0.
- Flags documentados en `--help`:
  - `--skip-sync`: omite `uv sync` (entorno ya sincronizado).
  - `--quick`: excluye los tests `@pytest.mark.integration`.
  - `--only <id>`: corre solo los pasos indicados (repetible o separados por
    comas); ids: `sync`, `pytest`, `ruff`, `mypy`, `validate-linux`,
    `validate-windows`.
- La lógica vive en funciones puras testeables: `Gate`, `GateResult`,
  `build_gates(...)`, `run_gate(gate, ..., runner=...)`, `render_step`,
  `render_summary` y `main(argv, runner=...)`, con el subprocess **inyectable**
  para que los tests no ejecuten `uv` real.
- Solo stdlib (`argparse`, `dataclasses`, `subprocess`, `time`, `pathlib`),
  sin `shell=True` y con los comandos como listas de argumentos
  (Windows-safe).

Además:

- `tests/test_verify_script.py` cubre las funciones puras importando
  `scripts/verify.py` por ruta (`importlib.util.spec_from_file_location`),
  sin ejecutar `uv`.
- `README.md` gana un **quickstart** por plataforma (Linux LTS y Windows
  Server) que usa `scripts/verify.py` como gate único, más la nota de que es
  el mismo gate que usará la CI (Item 073). El bloque actual de la sección
  "Compatibilidad de dependencias (Python 3.14)" se integra con el quickstart
  sin duplicar comandos.
- Con esto queda **cerrado el pendiente del Item 009 en Linux** (ciclo
  `uv sync` + `uv run pytest` + `odin validate` como script reproducible);
  Windows queda con el mismo script como gate (CI/Item 074).

## Acceptance Criteria

- [x] `scripts/verify.py` existe, solo stdlib, corre con
      `uv run python scripts/verify.py` y no requiere cambios por plataforma.
- [x] Ejecuta los seis gates en el orden indicado; `--quick` usa
      `-m "not integration"`, `--skip-sync` omite `uv sync` y `--only`
      restringe la corrida.
- [x] Salida por paso (comando, duración, estado) con resumen final; exit 0
      solo si todos los pasos seleccionados pasan; 1 si alguno falla; 2 con
      argumentos inválidos.
- [x] `--help` documenta `--skip-sync`, `--quick` y `--only`.
- [x] `tests/test_verify_script.py` cubre con runner inyectado (sin `uv`
      real): orden/ids/comandos de los gates, `--quick`, `--skip-sync`,
      `--only` (incluido un id inválido), fallo de un paso → exit 1 y resumen
      correcto, y `--help` → exit 0.
- [x] Evidencia ejecutada en Linux: `uv run python scripts/verify.py` (o la
      variante justificada) verde, registrada en "Decisions & Trade-offs".
- [x] `README.md` con el quickstart por plataforma y `scripts/verify.py`
      como gate único de desarrollo/CI.
- [x] Gates en verde: `uv run pytest tests/test_verify_script.py -q`,
      `uv run pytest`, `uv run ruff check src/odin tests`,
      `uv run mypy src/odin`.

## Implementation Steps

1. Crear `scripts/verify.py` con `Gate`/`GateResult`, `build_gates`,
   `run_gate`, `render_step`, `render_summary` y `main` (argparse con
   `--skip-sync`, `--quick`, `--only`), subprocess inyectable y exit codes
   0/1/2.
2. Crear `tests/test_verify_script.py`: carga del módulo por ruta con
   `importlib.util`, casos puros y runner falso (sin ejecutar `uv`).
3. Documentar en `README.md` el quickstart por plataforma y
   `scripts/verify.py` como gate único.
4. Correr `uv run python scripts/verify.py` y registrar la evidencia;
   correr los gates completos.
5. Actualizar `docs/aide/progress.md` (📋 → 🚧 → ✅) con la evidencia.

## Testing Strategy

- `uv run pytest tests/test_verify_script.py -q` → funciones puras y flags.
- `uv run python scripts/verify.py --help` → ayuda con los tres flags.
- `uv run python scripts/verify.py` → corrida real de los seis gates en
  Linux (evidencia del item); `--quick` queda documentado para corridas
  acotadas.
- `uv run pytest` + `uv run ruff check src/odin tests` +
  `uv run mypy src/odin` → gates del repositorio.
- Windows: el script usa listas de argumentos y `uv`/`uv.exe` del `PATH`, sin
  rutas POSIX ni `shell=True`; el contraste real se delega a CI/Item 074
  (mismo patrón que el resto de la suite).

## Dependencies

- `pyproject.toml` (pytest/ruff/mypy ya presentes) y `examples/` (Items 007).
- `tests/` existentes y `uv` operativo; sin dependencias nuevas.
- Item 073 consume `scripts/verify.py` como gate de la CI (no al revés).

## Decisions & Trade-offs

- **Captura por paso, no streaming**: cada gate corre con
  `subprocess.run(capture_output=True)` y solo al fallar se imprimen las
  últimas 20 líneas. La salida queda legible y determinista (`render_step`/
  `render_summary` son funciones puras verificables), a cambio de que un
  paso largo (pytest) no muestre progreso en vivo; la línea "Ejecutando:
  …" antes de cada gate mantiene la visibilidad de qué está corriendo.
- **`main` devuelve el exit code en vez de lanzarlo**: `parse_args` con
  `SystemExit` capturado permite testear `--help` (0) y un flag inválido (2)
  como valores de retorno, y el `raise SystemExit(main())` del final
  conserva el comportamiento de CLI.
- **`--only` con ids canónicos**: ids estables (`sync`, `pytest`, `ruff`,
  `mypy`, `validate-linux`, `validate-windows`), repetible o separado por
  comas, preservando el orden canónico; un id desconocido o una selección
  vacía (`--skip-sync --only sync`) devuelven 2 con mensaje a stderr. Se
  descartó seleccionar por posición (frágil ante cambios) o por etiqueta
  (texto de presentación).
- **`uv sync` explícito aunque `uv run` sincroniza**: se mantiene como
  primer gate porque el item lo pide y porque un fallo de resolución se
  aísla en su propio paso; `--skip-sync` permite omitirlo en corridas
  repetidas.
- **El gate de ruff conserva el alcance del queue (`src/odin tests`)**:
  `scripts/verify.py` queda fuera de ese comando, así que durante el item se
  verificó además a mano (`uv run ruff check tests/test_verify_script.py
  scripts/verify.py` → All checks passed). El script solo usa stdlib y
  argparse, y su contrato está cubierto por los tests que sí corren en el
  gate.
- **README sin comandos duplicados**: el bloque `uv sync`/`uv run pytest`/
  `uv run odin --version` de "Compatibilidad de dependencias" se reemplazó
  por un enlace al quickstart, que es la única lista de comandos por
  plataforma.

**Evidencia:** `uv run python scripts/verify.py --help` → ayuda con
`--skip-sync`/`--quick`/`--only` e ids. `uv run python scripts/verify.py` →
**EXIT=0** con los seis pasos OK (sync 0.02 s, pytest **48.84 s**, ruff
0.05 s, mypy 0.22 s, validate-linux 0.32 s, validate-windows 0.30 s).
`uv run pytest tests/test_verify_script.py -q` → **13 passed in 0.04 s**.
`uv run ruff check tests/test_verify_script.py scripts/verify.py` → All
checks passed. `README.md` con "Quickstart por plataforma" (bash y
PowerShell) y `scripts/verify.py` como gate único; la sección de
compatibilidad de dependencias enlaza al quickstart. Con esto queda cerrado
el ciclo `uv sync` + `uv run pytest` + `uv validate` del **Item 009 en
Linux** (Windows conserva el mismo script como gate, CI/Item 074).

## Prerequisites

- **Servicios requeridos**: ninguno externo; `uv` en el `PATH` y el entorno
  del repo sincronizable (los pasos de validación usan los ejemplos, que no
  comprueban red).
- **Configuración de entorno**: sin variables nuevas ni secretos; los dos
  JSON de `examples/` ya existen y dan exit 0.
- **Checklist de validación manual**:
  - [ ] `uv run python scripts/verify.py --help` muestra `--skip-sync`,
        `--quick`, `--only`.
  - [ ] `uv run python scripts/verify.py` termina con exit 0 y resumen de los
        seis pasos.
  - [ ] `uv run python scripts/verify.py --only ruff` corre solo ese paso.
  - [ ] `uv run python scripts/verify.py --only no-existe` sale con 2.
- **Resultados esperados**: script único multiplataforma con salida por paso
  (comando, duración, estado), `tests/test_verify_script.py` verde y README
  con el quickstart por plataforma.
- `docs/aide/progress.md` debe reflejar el avance (📋 → 🚧 → ✅) al completar,
  incluida la nota del cierre del Item 009 en Linux.
- Al finalizar, actualizar `docs/aide/progress.md` con la evidencia del item.

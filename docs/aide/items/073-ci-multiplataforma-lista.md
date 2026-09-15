# Item 073: CI multiplataforma lista para habilitar (`.github/workflows/ci.yml`)

## Description

Dejar la **integración continua lista para habilitar** en el repositorio, con
los dos jobs del proyecto y el gate único del Item 071 como única fuente de
verdad:

1. `.github/workflows/ci.yml` con `on: push`/`pull_request`,
   `permissions: contents: read` y **sin secretos**:
   - job `linux` (`ubuntu-latest`) y job `windows` (`windows-latest`);
   - `actions/checkout`, `astral-sh/setup-uv` con caché, `uv sync --locked` y
     `uv run python scripts/verify.py` (Item 071) como gate único;
   - `uv build` y subida del wheel como artefacto (`actions/upload-artifact`).
2. El job `windows` suma el **ciclo de vida real del servicio** con pywin32
   (los runners son administradores): escenario *gated* por
   `ODIN_WINDOWS_SERVICE_SMOKE=1` en
   `tests/test_service_windows_integration.py` que usa `odin service
   install|start|status|stop|uninstall` contra el SCM real con:
   - una config con `scheduler` (`* * * * *`, timezone UTC) y **fases externas
     dobles** (misma mecánica de las demos de los Items 057/066: `gbak` *stub*
     propio que escribe el `.fbk`, `servers: []` sin SFTP y el
     `tests/smtp_catcher.py` in-process como SMTP, sin red externa);
   - un correo `[ODIN] ÉXITO` capturado, `scheduler_state.json` con el ciclo y
     `odin service status` afirmando **estado del SCM** (en ejecución, arranque
     automático, reinicio ante caída);
   - `uninstall` idempotente y limpieza garantizada en `finally`.
3. `tests/test_ci_workflow.py` valida el YAML (jobs, runners, pasos, caché,
   artefacto, `permissions`, ausencia de `secrets.` y el gate de Windows) para
   que la CI no derive en silencio; `pyyaml` se suma al grupo `dev` (solo
   test).
4. `README.md` gana la sección **"Integración continua"** documentando que el
   workflow se activa al publicar el repositorio (hoy **no hay remoto**) y que
   `scripts/verify.py` es el gate local equivalente.

Alcance: la ejecución real del job `windows` ocurre al publicar el repositorio
(Item 074); acá se prepara y se valida todo lo verificable en Linux (YAML,
suite, contraste con los dobles de pywin32 existentes).

## Acceptance Criteria

- [x] `.github/workflows/ci.yml` parsea como YAML con `on: push`/
      `pull_request`, `permissions: contents: read`, sin `secrets.` y con los
      jobs `linux` (`ubuntu-latest`) y `windows` (`windows-latest`); ambos con
      checkout, `astral-sh/setup-uv` + caché, `uv sync`, el gate
      `uv run python scripts/verify.py`, `uv build` y el wheel como artefacto.
- [x] El job `windows` ejecuta el escenario gated
      `ODIN_WINDOWS_SERVICE_SMOKE=1` sobre
      `tests/test_service_windows_integration.py`.
- [x] `tests/test_service_windows_integration.py` (`@integration`) es
      skip-safe fuera de Windows y sin la variable; en Windows con la variable
      recorre el ciclo real por la CLI y afirma correo, estado del scheduler y
      estado del SCM, con `uninstall` idempotente y limpieza en `finally`.
- [x] `tests/test_ci_workflow.py` cubre el YAML (estructura, runners, pasos,
      gate, artefacto, `permissions`, sin secretos y el smoke de Windows) y
      corre en Linux.
- [x] `README.md` con la sección "Integración continua" (activación al
      publicar, gate local equivalente y artefactos).
- [x] Evidencia ejecutada en Linux registrada en "Decisions & Trade-offs":
      tests del YAML verdes, escenario de Windows recolectado y saltado con
      motivo, y suite/gates en verde.
- [x] Gates en verde: `uv run pytest tests/test_ci_workflow.py
      tests/test_service_windows_integration.py -q`, `uv run pytest`,
      `uv run ruff check src/odin tests`, `uv run mypy src/odin`.

## Implementation Steps

1. Sumar `pyyaml` al grupo `dev` (`uv add --dev pyyaml`) para poder parsear el
   workflow en los tests.
2. Crear `.github/workflows/ci.yml` con los jobs `linux` y `windows` (pasos
   compartidos + smoke del servicio en Windows).
3. Crear `tests/test_service_windows_integration.py`: config con `gbak` stub,
   `servers: []`, SMTP al catcher y scheduler `* * * * *`; ciclo por la CLI
   (`main([...])`) con `install → start → status → wait correo → stop →
   uninstall` y aserciones de SCM/estado; `finally` con stop + uninstall.
4. Crear `tests/test_ci_workflow.py` con el parseo del YAML (normalizando la
   clave `on`, que YAML 1.1 lee como `True`) y las aserciones estructurales.
5. Documentar en `README.md` la sección "Integración continua".
6. Correr la evidencia y los gates; actualizar `docs/aide/progress.md`
   (📋 → 🚧 → ✅) y registrar decisiones/evidencia en este spec.

## Testing Strategy

- `uv run pytest tests/test_ci_workflow.py -q` → estructura del workflow.
- `uv run pytest tests/test_service_windows_integration.py -q` → skip seguro
  en Linux (recolección válida); en el runner Windows del job `windows` con
  `ODIN_WINDOWS_SERVICE_SMOKE=1` corre el ciclo real (Item 074 registra la
  primera corrida).
- `uv run pytest` + `uv run ruff check src/odin tests` +
  `uv run mypy src/odin` → gates del repositorio.
- Contraste de los pasos Windows con los tests mock existentes
  (`tests/test_service_windows.py`, 31 pasados) y con
  `tests/test_service_linux_integration.py` (misma mecánica de fases dobles).
- YAML parseable (el propio test lo cubre) y sin secretos (aserción textual).

## Dependencies

- Item 071: `scripts/verify.py` como gate único del workflow.
- Item 061 (`src/odin/service/windows.py`) y Item 065
  (`src/odin/service/runner.py`) para el ciclo real.
- Item 057/066: patrón de demos gated y de config con fases dobles.
- `tests/smtp_catcher.py` (Item 047/056) y `pyproject.toml` (`pywin32` con
  marker `sys_platform == "win32"`).
- El repositorio **no tiene remoto**: la activación del workflow es al
  publicarlo; la corrida real del job Windows queda para el Item 074.

## Decisions & Trade-offs

- **Versiones de las acciones**: `actions/checkout@v5`,
  `astral-sh/setup-uv@v6` (con `enable-cache: true`) y
  `actions/upload-artifact@v4` — majors existentes y soportados; no se fijan
  SHAs porque el repositorio todavía no tiene remoto. Al publicar se pueden
  subir a los majors vigentes sin tocar la estructura (los tests no los fijan).
- **`uv sync --locked` en la CI**: el paso pedido `uv sync` se corre con
  `--locked` para que la CI falle si `uv.lock` quedó desactualizado (drift de
  dependencias); el gate `scripts/verify.py` conserva su propio `uv sync`, así
  que un lock viejo no pasa desapercibido. Localmente nada cambia.
- **PyYAML en el grupo `dev`**: para parsear el YAML en la suite hizo falta un
  parser real; `pyyaml` (6.0.3) queda como dependencia **solo de test** y no
  toca el wheel. YAML 1.1 lee la clave `on` como el booleano `True`; el helper
  `_triggers` del test normaliza ambas formas en lugar de depender del
  comportamiento del parser.
- **Smoke de Windows gated y skip-safe**: el ciclo real del SCM no es
  ejecutable en Linux, así que el test lleva `@integration` + `skipif` de
  plataforma + `skipif` de `ODIN_WINDOWS_SERVICE_SMOKE`; el job `windows` (que
  sí es administrador) exporta la variable y lo corre. Se descartó verificar
  el reinicio por failure actions en la CI (matar el proceso del host y
  esperar al SCM) por fragilidad del runner: la configuración de reinicio se
  afirma leyendo el SCM (`Reinicio ante caída: sí`) y el escenario de caída +
  recovery queda en el runbook §8/Item 074.
- **Fases externas dobles sin red**: el smoke usa un `gbak` *stub* en batch
  (`.cmd` que escribe el `.fbk` en `%3`; Python 3.12.2+ invoca `.cmd`/`.bat`
  con quoting seguro desde `subprocess`), `servers: []` y el
  `tests/smtp_catcher.py` in-process, replicando la mecánica de las demos de
  los Items 057/066 sin depender de Firebird ni de SFTP.
- **Host del servicio desde el venv de `uv sync`**: se revisó el wheel de
  pywin32 312: `LocatePythonServiceExe` copia `pythonservice.exe` a
  `sys.exec_prefix` y `pywintypesNNN.dll` junto a la DLL de Python al instalar,
  de modo que `odin service install` desde el entorno del repo registra el
  host correcto sin pasos extra de `pywin32_postinstall`. La primera corrida
  real del job `windows` (al publicar) confirmará el ciclo (Item 074).
- **`uv build` en ambos jobs**: el wheel es universal (`py3-none-any`), pero
  construir en las dos plataformas valida metadata/entry points en el SO
  objetivo; los artefactos se suben con nombres distintos
  (`odin-wheel-linux`/`odin-wheel-windows`) para no colisionar.

**Evidencia:** `uv run pytest tests/test_ci_workflow.py
tests/test_service_windows_integration.py tests/test_service_windows.py -q` →
**37 passed + 1 skipped** (el smoke salta con el motivo de plataforma). YAML
parseado por los 6 tests nuevos del contrato de CI. `uv run pytest -q` →
**652 passed + 8 skipped in 95.10 s**. `uv run python scripts/verify.py` →
**EXIT=0** (6 pasos OK; pytest 65.06 s). `uv run ruff check src/odin tests` →
All checks passed; `uv run mypy src/odin` → Success 19 files.
`uv add --dev pyyaml` → `pyyaml==6.0.3` (solo test).

## Prerequisites

- **Servicios requeridos**: ninguno externo en Linux; `uv` en el `PATH` y el
  entorno sincronizable. En el runner Windows: SCM y permisos de
  administrador (los runners de GitHub lo son), `pywin32` instalado por
  `uv sync`.
- **Configuración de entorno**: `ODIN_WINDOWS_SERVICE_SMOKE=1` para el smoke
  (sin ella el test se salta); sin secretos (credenciales de prueba del
  catcher y del `gbak` stub).
- **Checklist de validación manual**:
  - [x] `uv run python -c "import yaml, pathlib;
        yaml.safe_load(pathlib.Path('.github/workflows/ci.yml').read_text())"`
        no lanza.
  - [x] `uv run pytest tests/test_ci_workflow.py -q` verde.
  - [x] `uv run pytest tests/test_service_windows_integration.py -q` salta
        con motivo en Linux.
  - [x] `uv run python scripts/verify.py` en verde tras los cambios.
- **Resultados esperados**: workflow listo para habilitar al publicar, tests
  del YAML verdes, escenario Windows skip-safe y documentado en el README.
- `docs/aide/progress.md` debe reflejar el avance (📋 → 🚧 → ✅) al completar,
  con la nota de que el job Windows real se estrena con el Item 074.
- Al finalizar, actualizar `docs/aide/progress.md` con la evidencia del item.

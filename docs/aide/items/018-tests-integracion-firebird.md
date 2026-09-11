# Work Item 018: Implementación de Tests de Integración (Firebird Real/Container)

## Description
Create an integration test marked with `@pytest.mark.integration` that uses a real Firebird environment (or a Docker container if available) to validate that the entire flow (`odin run` -> `gbak` -> `.fbk` file) is functional and produces valid files.

## Acceptance Criteria
- [x] A new test file or test class is created in `tests/`.
- [x] The test is decorated with `@pytest.mark.integration`.
- [x] The test uses a real Firebird instance (locally or via Docker).
- [x] The test executes a command that triggers the backup process.
- [x] The test verifies that the `.fbk` file is created and is not empty.
- [x] The test verifies that the process completes without errors.

## Implementation Steps
1. [x] Set up a requirement for a running Firebird instance (Docker is preferred).
2. [x] Implement the integration test in `tests/test_backup_integration.py`.
3. [x] Use `subprocess` or the internal `BackupExecutor` to trigger a backup.
4. [x] Add assertions for file existence and non-zero size.
5. [x] Ensure the test can be skipped if a Firebird environment is not available.

## Testing Strategy
- **Integration Tests**:
    - Environment: Docker (running Firebird).
    - Action: Run the backup command.
    - Assertion: File exists, file size > 0, exit code 0.

## Dependencies
- `pytest`
- `docker` (or local Firebird installation)
- `src/odin/backup.py`

## Decisions & Trade-offs
- **Imagen oficial**: `firebirdsql/firebird:latest` (la imagen crea la base vía
  `FIREBIRD_DATABASE` y fija la password con `FIREBIRD_ROOT_PASSWORD`); se
  publica el puerto con `-P` (aleatorio) y se descubre con `docker port`, para
  evitar colisiones con un Firebird local del host.
- **Skips seguros en recolección**: `shutil.which("docker")` y `find_gbak()` en
  lugar de invocar `subprocess` al importar (el código anterior lanzaba
  `FileNotFoundError` en entornos sin Docker). El `docker run` fallido produce
  `pytest.skip`, no error.
- **`gbak` del host**: el test resuelve el binario con `find_gbak()` (PATH o
  rutas típicas). En este entorno WSL no había Firebird instalado: se usó el
  `gbak` 5.0.4 extraído de la propia imagen oficial (con sus ICU) agregado al
  `PATH` al correr la suite.
- **Ejecución verificada**: `PATH=<gbak-fb5>:$PATH uv run pytest
  tests/test_backup_integration.py -m integration -v` → **1 passed in 4.08s**
  (2026-09-11) contra Firebird 5.0.4 en Docker Desktop, con `localhost:<puerto>`
  alcanzable desde WSL.
- **Evidencia adicional de integridad** (verificada también fuera del test):
  `odin run` contra el mismo Firebird → `.fbk`; `gbak -c` a base scratch →
  `SELECT COUNT(*)` = 3 y datos idénticos.

## Testing Prerequisites

**Required Services**
- Firebird Instance (Docker: `docker run --name firebird-test -p 3050:3050 -d firebird`)

**Environment Configuration**
- A configuration file pointing to the test Firebird instance.

**Manual Validation Checklist**
- [x] Build succeeds
- [x] Tests pass
- [x] **Services started**: Docker container is running.
- [x] **Application runs**: The test executes the `odin run` flow.
- [x] **Feature verified**: The `.fbk` file is present in `work_dir`.

**Expected Outcomes**
- Integration test passes when Firebird is running.
- Integration test is skipped gracefully when Firebird is not found.

## Validation Results
- [x] Service started: Firebird 5.0.4 (Docker Desktop, imagen `firebirdsql/firebird:latest`)
- [x] Application started successfully — test de integración **1 passed in 4.08s**
- [ ] Database tables verified: N/A
- [x] Seed data verified — restore scratch del `.fbk` conserva las 3 filas de `clientes`
- [ ] API endpoints verified: N/A
- [ ] Screenshots captured: N/A

## Completion Reminder
`docs/aide/progress.md` MUST be updated (📋 → 018 🚧 → ✅) when the item is completed.

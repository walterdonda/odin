# Item 035: Extensión del pipeline `odin run`: respaldo → compresión → transferencia

## Description

Crear el orquestador `src/odin/pipeline.py` y conectar la fase de transferencia (Etapa 4) en `odin run`. El flujo es: respaldo (Etapa 2) → compresión (Etapa 3) → y, si ambas fases culminan bien para una base, transferencia del `.fbk.7z` a todos los servidores configurados (Etapa 4). El éxito global depende de la culminación exitosa de todas las fases para cada base de datos; los exit codes de `odin run` (0/3/4) pasan a reflejar también la transferencia.

## Acceptance Criteria

- [ ] `src/odin/pipeline.py` existe y orquesta las tres fases; `odin.cli._cmd_run` delega en él.
- [ ] Solo las bases con respaldo + compresión exitosos se transfieren a los servidores configurados.
- [ ] Una base cuenta como exitosa solo si respaldo, compresión **y** transferencia a todos sus servidores culminan bien; un fallo de transferencia marca la base como fallida sin perder los datos de respaldo/compresión.
- [ ] Exit codes de `odin run`: 0 éxito total, 3 parcial, 4 fallo total (incluidos fallos de transferencia); 2 configuración; 1 interno.
- [ ] Tests unitarios del pipeline con dobles de los tres ejecutores y tests de CLI de los nuevos exit codes.

## Implementation Steps

1. Crear `src/odin/pipeline.py` con:
   - `PipelineResult` (frozen dataclass): `backup: BatchBackupResult` (respaldo + compresión + éxito por base que ya incluye la transferencia) y `transfers: Mapping[str, tuple[TransferResult, ...]]` (por base exitosa, en el orden de la configuración de servidores).
   - `run_pipeline(config, *, backup=None, compression=None, transfer=None) -> PipelineResult`: construye los ejecutores por defecto desde `config` (inyectables para tests), ejecuta respaldo → compresión → transferencia y devuelve el resultado; no propaga excepciones operativas (cada fase ya las encapsula en sus resultados).
2. Mover `_merge_compression_results` de `odin/cli.py` a `pipeline.py` (quedará interna del pipeline) y extender el cruce: tras transferir, una base cuyo lote de transferencia tenga fallos queda con `success=False` y `transfer_error_message` informado.
3. Agregar el campo `transfer_error_message: str | None = None` a `BackupResult` (patrón idéntico al de `compression_error_message`, Item 025; default compatible).
4. Transferir cada `archive_path` exitoso con `TransferExecutor.run_batch_transfer(config.servers, archive_path)`; si no hay servidores configurados, la fase se considera trivially satisfecha (no se transfiere nada).
5. Cablear `odin.cli._cmd_run` a `run_pipeline` (los exit codes se derivan del `BatchBackupResult` final, con la misma lógica que hoy).
6. Cablear en `_parse_server` (config.py) los campos de reintentos/timeouts del JSON (`sftp_retries`, `sftp_connect_timeout_sec`, `sftp_operation_timeout_sec`, `sftp_retry_backoff_base`, `sftp_retry_max_delay_sec`): son parte del cierre de integración de los Items 030/033 y sin ellos el pipeline ignora silenciosamente la configuración por servidor.
7. Tests: `tests/test_pipeline.py` (orquestación con dobles) y casos nuevos en `tests/test_cli.py` (exit codes con transferencia).

## Testing Strategy

- **Unit (`tests/test_pipeline.py`)** con dobles de los tres ejecutores:
  - Éxito total: respaldo + compresión + transferencia verdes → `backup.success` True, `transfers` por base con todos los resultados, ejecutor de transferencia invocado con `config.servers` y el `.7z`.
  - Fallo de transferencia en una base: la base queda `success=False` con `transfer_error_message`, las demás intactas, y el lote global es fallido/parcial según corresponda.
  - Fallo de respaldo o compresión: esa base **no** se transfiere (el ejecutor de transferencia no recibe su artefacto).
  - Sin servidores configurados: éxito sin invocar transferencia.
- **CLI (`tests/test_cli.py`)**: con `BackupExecutor`/`TransferExecutor` doblados, verificar exit codes 0/3/4 cuando la transferencia total, parcialmente o del todo falla; respaldo de `.fbk.7z` real para los casos de éxito.
- Suite completa: `uv run pytest`, `uv run ruff check`, `uv run mypy`.

## Dependencies

- `src/odin/transfer.py` (Items 030-034), `src/odin/backup.py` (Etapa 2), `src/odin/compress.py` (Etapa 3), `src/odin/cli.py` (Item 019), `src/odin/config.py` (Item 002).

## Decisions & Trade-offs

- **`PipelineResult` con dos campos** (`backup: BatchBackupResult` fusionado + `transfers: Mapping[str, tuple[TransferResult, ...]]`): el `BatchBackupResult` final es el único dueño del éxito por base y global (incluida la transferencia), y `transfers` conserva el detalle por servidor para el resumen (Item 036) y el correo (Etapa 5). Sin un `success` propio en `PipelineResult` para no duplicar estado.
- **`BackupResult.transfer_error_message`** (default `None`): sigue el patrón exacto de `compression_error_message` (Item 025) — una base con transferencia fallida queda `success=False` conservando ruta/tamaños de respaldo y compresión, y el detalle del fallo queda separado por fase. La fusión (``_merge_compression_results``) se movió de `odin.cli` a `odin.pipeline` (quedó interna del pipeline) y el cruce de transferencia se hace en `run_pipeline`.
- **Sin servidores configurados**: la fase de transferencia se considera satisfecha (no hay destinos); la base no se transfiere y no aparece en `transfers`. Evita el caso borde "vacío = fallo".
- **Solo se transfieren artefactos exitosos**: la transferencia se invoca únicamente sobre bases con respaldo + compresión verdes (`archive_path` presente); los fallos previos no consumen conexiones.
- **Cierre de integración de los Items 030/033**: `_parse_server` no cableaba al `ServerConfig` los campos `sftp_retries`/`sftp_connect_timeout_sec`/`sftp_operation_timeout_sec` (y no aceptaba los dos de backoff) — pendiente registrado en el Item 034. Se cablearon los 5 campos con validación (`sftp_retries >= 0`, timeouts >= 1, backoff >= 0) y se agregó `_Validator.float_field` (acepta int y float, rechaza bool) para los dos parámetros de backoff. Sin esto el pipeline ignoraba silenciosamente la configuración por servidor.
- **Exit codes sin cambios de convención**: 0/3/4 derivados del `BatchBackupResult` final (que ya incluye la transferencia); la lógica de `_cmd_run` queda idéntica salvo la delegación al pipeline.
- **Tests de CLI existentes**: `_install_fake_executor` ahora parchea `odin.pipeline.BackupExecutor` (antes `odin.cli`) e instala un `TransferExecutor` doble exitoso, para que los casos de respaldo/compresión no intenten conexiones SFTP reales contra los servidores del fixture.
- **Fix de entorno (fuera del alcance funcional)**: `tests/test_deps_compat.py` tenía 13 violaciones de ruff preexistentes y un bloque de verificación de floors de versión muerto (indentado tras un `break`, con un bug de `floor_str[1:]`); se limpió el lint y se activó la verificación real de floors (pasa con las versiones instaladas). Necesario para el gate `uv run ruff check` del cierre de lote.

**Evidencia:** `uv run pytest -q` → 307 passed, 1 skipped (antes 295); `uv run ruff check src/odin tests` → All checks passed; `uv run mypy src/odin` → Success.

## Prerequisites

- `docs/aide/progress.md` debe ser actualizado a 📋 al iniciar.
- Al finalizar, actualizar `docs/aide/progress.md` a ✅.

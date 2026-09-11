# Work Item 025: Extensión de `BackupResult` y pipeline `odin run`: respaldo → compresión

## Description
Extend `BackupResult` with the compression data (`archive_path`, `compressed_size_bytes`,
`compression_duration_seconds`, compression error) and modify `_cmd_run` so that, after the backup
batch, every successful `.fbk` is compressed. A database counts as successful only if both backup
and compression finish well; the batch keeps failure isolation. CLI integration tests with `gbak`
mocked (backup double) and real compression in a temporary `work_dir`.

## Acceptance Criteria
- [x] `BackupResult` gains `archive_path`, `compressed_size_bytes`, `compression_duration_seconds` and `compression_error_message`, all with defaults so existing consumers keep working (frozen dataclass, positional fields untouched).
- [x] `_cmd_run` builds a `CompressionExecutor` from `config.compression` (`level`, `password`) and runs it over the backup batch results after `run_batch_backup`.
- [x] Each base is merged by name: backup OK + compression OK → `success=True` with archive data; backup OK + compression failure → `success=False` with `compression_error_message`; backup failure → unchanged.
- [x] `BatchBackupResult` handed to the summary carries the merged results, recomputed `success` and the summed backup + compression duration.
- [x] Exit codes follow the merged per-base success (0 all, 3 mixed, 4 all failed/batch error).
- [x] Tests: CLI with a backup double that writes real `.fbk` files in a temporary `work_dir` and real compression (no `gbak` needed), plus mixed backup/compression failures.
- [x] Existing `run` tests updated to stop pointing at nonexistent `/tmp/*.fbk` paths (the pipeline now compresses them).

## Implementation Steps
1. [x] Add the four compression fields (with defaults) to `BackupResult` in `src/odin/backup.py`.
2. [x] In `src/odin/cli.py`, instantiate `CompressionExecutor` with the configured level/password after the backup batch.
3. [x] Add `_merge_compression_results(batch, compressed)` using `dataclasses.replace`; recompute `success` and total duration.
4. [x] Update `_cmd_run` to print the merged batch and keep the exit-code logic based on merged results.
5. [x] Extend `tests/test_cli.py` with pipeline tests; update `_result`/builders to create real files.

## Testing Strategy
- **Integration Tests (in-process CLI)**: `main(["run", ...])` with `odin.cli.BackupExecutor` replaced by a double that writes real `.fbk` files under the temporary `work_dir`, while compression runs for real (fast, small payloads).
- **Unit Tests**: merge behavior via CLI outcomes (path, size, duration, failure propagation).
- **Manual Check**: inspect a run where one `.fbk` is missing to see the compression failure marked.

## Dependencies
- Item 024 (`CompressionExecutor`, `BatchCompressionResult`).
- Items 020-023 (`compress_backup()`).
- Item 019 (`_cmd_run` and `BatchBackupResult`).

## Decisions & Trade-offs
- **Merge en `cli.py`, no en `backup.py`**: la dirección de import queda
  `compress → backup` y `cli → {backup, compress}`, sin ciclos. Mientras no
  exista `odin.pipeline` (Etapa 5), el cruce de fases vive junto a la
  orquestación de `_cmd_run`; allí migrará con el pipeline completo.
- **Cruce por `database_name`**: `Config.validate_semantics` prohíbe nombres
  duplicados, así que el nombre es una clave segura; el `CompressionExecutor`
  solo devuelve resultados de respaldos exitosos.
- **`success` de la base = respaldo ∧ compresión**: el merge reescribe el
  `BackupResult` con `dataclasses.replace`; un fallo de compresión deja
  `success=False` + `compression_error_message` y conserva la ruta/tamaño del
  `.fbk` para que el resumen (Item 026) pueda mostrarla.
- **Rama defensiva `compression is None`**: si un ejecutor externo no
  intentara comprimir un respaldo exitoso, la base se marca fallida con
  "no se intentó la compresión del respaldo" en lugar de contarse como éxito
  sin archivo.
- **Duración total = respaldo + compresión**: `total_duration_seconds` del
  lote merged suma ambas fases; el desglose por fase queda en los campos de
  cada `BackupResult`.
- **Tests existentes con rutas reales**: los dobles de respaldo escribían
  `/tmp/<base>.fbk` inexistentes; ahora escriben un `.fbk` real en el
  `work_dir` temporal y la compresión corre de verdad (sin `gbak`), tal como
  pide el item. Se verificó además el cableado de `compression.password`
  (archivo cifrado con `py7zr`).
- **Fallback de resumen**: `_print_backup_summary` usa
  `error_message or compression_error_message or "fallo sin detalle"` para no
  imprimir `None` en fallos de compresión; el rediseño completo del resumen
  es el Item 026.

## Testing Prerequisites

**Required Services**
- N/A (backup is doubled; compression is local and real).

**Environment Configuration**
- N/A

**Manual Validation Checklist**
- [x] Build succeeds — `uv sync`.
- [x] Tests pass — `uv run pytest tests/test_cli.py`: **37 passed in 0.65 s**; suite conjunta con compresión y respaldo: **86 passed in 4.45 s**.
- [x] **Application runs**: `main(["run", "--config", ...])` con doble de respaldo que escribe `.fbk` reales.
- [x] **Feature verified**: `.fbk.7z` por base exitosa; la compresión fallida marca la base (`test_run_compression_failure_with_successful_backup_exits_4`).
- [x] **Data verified**: exit codes 0/3/4 según el cruce respaldo + compresión; archivo cifrado cuando `compression.password` está configurado.

**Expected Outcomes**
- `odin run` now performs backup → compression per base, with isolation.
- Extended `BackupResult` carries both phases for the summary (Item 026).

## Validation Results
- [ ] Service started: N/A
- [x] Application started successfully — `uv run pytest tests/test_cli.py` (37 passed, 0.65 s)
- [ ] Database tables verified: N/A
- [ ] Seed data verified: N/A
- [ ] API endpoints verified: N/A
- [ ] Screenshots captured: N/A

## Completion Reminder
`docs/aide/progress.md` MUST be updated (📋 → 025 🚧 → ✅) when the item is completed.

# Work Item 024: `CompressionExecutor` con lotes y aislamiento de fallos

## Description
Implement an executor that walks the successful backups of a batch and compresses each one
sequentially, isolating failures per database (a failed compression does not interrupt the rest)
and reporting an aggregate result (`BatchCompressionResult`, analogous to `BatchBackupResult`).
Only validated `.fbk` files are compressed; failed backups are skipped. Tests with doubles/mocks of
the compression function and of `py7zr` for success, failure and empty-batch cases.

## Acceptance Criteria
- [x] `src/odin/compress.py` defines `BatchCompressionResult` with `results` (sequence of `CompressionResult`), `success` and `total_duration_seconds`.
- [x] `CompressionExecutor(level=..., password=None)` exposes `run_batch_compression(backups: Sequence[BackupResult]) -> BatchCompressionResult`.
- [x] Only backups with `success=True` and a `backup_path` are compressed, preserving the input order; failed backups are omitted from `results`.
- [x] One compression failure does not interrupt the rest of the batch; every eligible backup is attempted and has its own `CompressionResult`.
- [x] `BatchCompressionResult.success` is `True` only when there was at least one eligible backup and all compressions succeeded; an empty batch reports `success=False` with no results.
- [x] The executor forwards `level` and `password` to `compress_backup()` (naming default `<fbk>.7z`).
- [x] Tests: batch with mixed backup success/failure, isolated compression failure, empty batch (compression function not called), and password/level pass-through with real files.

## Implementation Steps
1. [x] Add `BatchCompressionResult` and `CompressionExecutor` to `src/odin/compress.py`.
2. [x] Select eligible backups (`success and backup_path is not None`) and compress them sequentially.
3. [x] Log the batch summary (`%d/%d exitosos`) and the empty case.
4. [x] Add the batch tests to `tests/test_compress.py` (real temporary files + doubles for failures).

## Testing Strategy
- **Unit Tests**: construct `BackupResult` stubs; real `.fbk` files for success paths; a backup whose
  path does not exist to force a controlled compression failure; monkeypatch `compress_backup` to
  assert it is not called for failed/empty backups.
- **Manual Check**: run the executor over a mixed list and inspect `BatchCompressionResult`.

## Dependencies
- Items 020-023 (`compress_backup()`, levels and encryption).
- `odin.backup.BackupResult` (Item 012/019).

## Decisions & Trade-offs
- **El ejecutor vive en `compress.py` y consume `Sequence[BackupResult]`**: la
  dirección de import `compress → backup` es acíclica (`backup.py` no conoce
  la compresión; en el Item 025 solo se le agregan campos de datos), y evita
  un módulo nuevo antes de que la Etapa 5 introduzca `pipeline.py`.
- **Elegibles resueltos antes de comprimir**: se arma una lista de tuplas
  `(nombre, ruta)` filtrando `success and backup_path is not None`; además de
  preservar el orden, deja el tipado estricto de mypy sin `assert` ni casts
  dentro de `_compress_one`.
- **`success` del lote comprimido = hubo elegibles y todos exitosos**: un lote
  vacío da `success=False` (nada se comprimió), análogo a
  `BatchBackupResult`; el éxito global del pipeline lo recalcula el merge del
  Item 025, que sí conoce los fallos de respaldo.
- **Nivel/contraseña en el constructor**: el pipeline (Item 025) construye el
  ejecutor desde `config.compression`; los tests usan primitivas. Se mantiene
  el default de nivel 7 y `password=None`.
- **Sin `error_message` a nivel de lote**: los fallos son por base y ya viajan
  en cada `CompressionResult`; no hay una causa de lote previa a la primera
  base (a diferencia de `work_dir` en el respaldo).

## Testing Prerequisites

**Required Services**
- N/A

**Environment Configuration**
- N/A

**Manual Validation Checklist**
- [x] Build succeeds — `uv sync`.
- [x] Tests pass — `uv run pytest tests/test_compress.py`: **33 passed in 4.14 s**.
- [x] **Application runs**: lote con un respaldo bueno, uno fallido y uno con `.fbk` inexistente.
- [x] **Feature verified**: los respaldos fallidos se omiten y la compresión fallida no interrumpe al resto (`test_batch_isolates_a_compression_failure`).
- [x] **Data verified**: el `.fbk.7z` existe para cada elegible exitoso; lote vacío no llama a `compress_backup`.

**Expected Outcomes**
- Aggregate result ready to be merged into the `odin run` flow (Item 025).
- Failure isolation identical in spirit to `BatchBackupResult`.

## Validation Results
- [ ] Service started: N/A
- [x] Application started successfully — `uv run pytest tests/test_compress.py` (33 passed, 4.14 s)
- [ ] Database tables verified: N/A
- [ ] Seed data verified: N/A
- [ ] API endpoints verified: N/A
- [ ] Screenshots captured: N/A

## Completion Reminder
`docs/aide/progress.md` MUST be updated (📋 → 024 🚧 → ✅) when the item is completed.

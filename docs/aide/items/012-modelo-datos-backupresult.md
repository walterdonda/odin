# Work Item 012: Modelo de datos `BackupResult` y registro de errores

## Description
Create a `BackupResult` dataclass to encapsulate the outcome of a backup operation. This includes the status (success/failure), the path to the generated `.fbk` file, its size, the duration of the operation, and any captured error messages. The implementation must ensure that error patterns from `gbak` (previously identified) are properly mapped into this model to provide structured error reporting.

## Acceptance Criteria
- [ ] `BackupResult` dataclass exists in `src/odin/backup.py`.
- [ ] `BackupResult` contains the following fields:
    - `success`: `bool`
     
    - `database_name`: `str`
    - `backup_path`: `Path | None`
    - `file_size_bytes`: `int | None`
    - `duration_seconds`: `float`
    - `error_message`: `str | None`
- [ ] `BackupExecutor.run_backup` is updated to return a `BackupResult` instead of a `bool`.
- [ ] The implementation correctly captures and populates `error_message` when a `GbakExecutionError` or `subprocess.TimeoutExpired` occurs.
- [ ] The implementation captures `file_size_bytes` (if success) and `duration_seconds`.
- [ ] Unit tests verify the creation of `BackupResult` for both success and failure scenarios.

## Implementation Steps
1. [ ] Define the `BackupResult` dataclass in `src/odin/backup.py`.
2. [ ] Refactor `BackupExecutor.run_backup` to:
    - Start a timer.
    - Wrap the execution in a try/except block that captures errors.
    - Construct and return a `BackupResult` instance.
3. [ ] Integrate file size calculation (using `os.path.getsize`) into the result construction.
4. [ ] Ensure that `GbakExecutionError` details (stderr) are extracted and placed in `error_message`.
5. [ ] Update `tests/test_backup.py` to assert against the new `BackupResult` object.

## Testing Strategy
- **Unit Tests**:
    - Test `BackupResult` creation on success: verify `success=True`, non-null `backup_path`, and valid `duration`.
    - Test `BackupResult` creation on `GbakExecutionError`: verify `success=False`, `error_message` contains the error from stderr.
    - Test `BackupResult` creation on `TimeoutExpired`: verify `success=False` and `error_message` indicates timeout.
    - Verify `file_size_bytes` is correctly calculated for a mock file.

## Dependencies
- `dataclasses` (standard library)
- `time` (standard library)
- `pathlib` (standard and `os.path`)
- `src/odin/backup.py` (refactoring existing logic)

## Decisions & Trade-offs
- To be updated during implementation.

## Testing Prerequisites

**Required Services**
- N/A (Using mocks)

**Environment Configuration**
- N/A

**Manual Validation Checklist**
- [ ] Build succeeds
- [ ] Tests pass
- [ ] **Application runs**: `odin validate` passes.

**Expected Outcomes**
- `run_backup` returns a structured object.
- Error messages from `gbak` are preserved in the `error_message` field.
- Duration and file size are accurately reported.

## Validation Results
- [ ] Service started: N/A
- [ ] Application started successfully
- [ ] Database tables verified: N/A
- [ ] Seed data verified: N/A
- [ ] API endpoints verified: N/A
- [ ] Screenshots captured: N/A

## Completion Reminder
`docs/aide/progress.md` MUST be updated (📋 → 🚧 → ✅) when the item is completed.

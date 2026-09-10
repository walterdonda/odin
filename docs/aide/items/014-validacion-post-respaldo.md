# Work Item 014: Validación post-respaldo y manejo de archivos

## Description
Implement automatic checks after `gbak` execution: verify that the `.fbk` file exists, that its size is greater than 0, and that it is accessible. Handle the creation of the `work_dir` if it does not already exist.

## Acceptance Criteria
- [ ] Post-backup validation logic is implemented.
- [ ] The system verifies the existence of the generated `.fbk` file.
- [ ] The system verifies the file size is greater than 0.
- [ ] The system verifies the file is readable/accessible.
- [ ] The `work_dir` is automatically created if it does not exist.
- [ ] Errors in validation are captured and reported via `BackupResult`.

## Implementation Steps
1. [ ] Implement the file validation logic (existence, size > 0).
2. [ ] Implement the directory creation logic for `work_dir`.
3. [ ] Integrate these checks into the `BackupExecutor.run_backup` workflow.
4. [ ] Ensure that any validation failure results in a `BackupResult` with `success=False` and a descriptive error message.

## Testing Strategy
- **Unit Tests**:
    - Test validation logic with a real (temporary) file.
    - Test validation logic with a non-existent file.
    - Test validation logic with a zero-byte file.
    - Test `work_dir` creation logic.

## Dependencies
- `pathlib`
- `os`
- `src/odin/backup.py`

## Decisions & Trade-offs
- To be updated during implementation.

## Testing Prerequisites

**Required Services**
- N/A

**Environment Configuration**
- N/A

**Manual Validation Checklist**
- [ ] Build succeeds
- [ ] Tests pass
- [ ] **Application runs**: `odin run` executes and performs the checks.

**Expected Outcomes**
- Files are verified after creation.
- `work_dir` exists after execution.
- Invalid files (zero size) trigger a failure in the `BackupResult`.

## Validation Results
- [ ] Service started: N/A
- [ ] Application started successfully
- [ ] Database tables verified: N/A
- [ ] Seed data verified: N/A
- [ ] API endpoints verified: N/A
- [ ] Screenshots captured: N/N/A

## Completion Reminder
`docs/aide/progress.md` MUST be updated (📋 → 014 🚧 → ✅) when the item is completed.

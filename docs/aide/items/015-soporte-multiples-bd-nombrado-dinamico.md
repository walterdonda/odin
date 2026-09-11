# Work Item 015: Soporte para múltiples bases de datos y nombrado dinámico

## Description
Extend the backup logic to iterate over all databases defined in the `databases` section of the configuration. Implement a dynamic output naming scheme using the pattern `<database_name>_<timestamp>.fbk` to prevent collisions and enable traceability.

## Acceptance Criteria
- [ ] The backup process iterates through all entries in the `databases` list from the configuration.
- [ ] Each backup operation uses a unique filename based on `<name>_<timestamp>.fbk`.
- [ ] Backups are executed sequentially.
- [ ] The `work_dir` is used as the destination for all generated `.fbk` files.
- [ ] The process continues to the next database even if one fails (unless configured otherwise).
- [ ] Logs clearly indicate which database is currently being processed.

## Implementation Steps
1. [x] Update `BackupExecutor.run_backup` (or the orchestration logic) to accept a list of database configurations.
2. [x] Implement a loop to iterate over the list of `DatabaseConfig` objects.
3. [x] Implement the timestamp generation (using `datetime.now().strftime("%Y%m%d_%H%M%S")`).
4. [x] Implement the filename construction: `f"{db_name}_{timestamp}.fbk"`.
5. [x] Ensure the `backup_path` is correctly constructed within the `work_dir`.
6. [x] Integrate with the existing `BackupResult` or a new `BatchBackupResult` to report progress for the entire batch.

## Decisions & Trade-offs
- Created `BatchBackupResult` to encapsulate results of multiple backups.
- Implemented `run_batch_backup` in `BackupExecutor`.
- Used `datetime.datetime.now().strftime("%Y%m%d_%H%M%S")` for unique filenames.
- The batch process continues even if one database fails, reporting all results at the end.


## Testing Prerequisites

**Required Services**
- N/A

**Environment Configuration**
- N/A

**Manual Validation Checklist**
- [ ] Build succeeds
- [ ] Tests pass
- [ ] **Application runs**: `odin run` with multiple databases in config.

**Expected Outcomes**
- Multiple `.fbk` files are created in `work_dir`.
- Filenames are unique and include the database name and timestamp.
- Logs show the start and completion of each database backup.

## Validation Results
- [ ] Service started: N/A
- [ 
    ] Application started successfully
- [ ] Database tables verified: N/A
- [ ] Seed data verified: N/A
- [ ] API endpoints verified: N/A
- [ ] Screenshots captured: N/A

## Completion Reminder
`docs/aide/progress.md` MUST be updated (📋 → 🚧 → ✅) when the item is completed.

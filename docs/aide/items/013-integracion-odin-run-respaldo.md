# Work Item 013: Integración de `odin run` para la fase de respaldo

## Description
Implement the `run` subcommand in `src/odin/cli.py` (or the necessary orchestration logic) so that, upon detecting Stage 2 configuration, it executes the backup process for all databases listed in the JSON. The execution must be sequential and report progress.

## Acceptance Criteria
- [ ] `odin run` subcommand is implemented.
- [ ] The command reads the database list from the configuration.
- [ ] For each database, the backup process is triggered.
- [ ] The process is sequential (one database at a time).
- [ ] Progress is reported in the logs (starting, completing, or erroring for each database).
- [ ] If a database fails, the error is logged, but the process continues for subsequent databases (or as decided in implementation).
- [ ] The command exits with an appropriate exit code (e. 0 for all success, 3 for partial success, 4 for total failure).

## Implementation Steps
1. [ ] Implement orchestration logic in a new or existing service/module (e.g., `src/odin/pipeline.py` or within `src/odin/cli.py`).
2. [ ] Update `src/odin/cli.py` to include the `run` command.
3. [ ] Implement the loop that iterates over `config.databases`.
4. [ ] For each database, call `BackupExecutor.run_backup`.
5. [ ] Collect results and implement the exit code logic.
6. [ ] Add logging for each step of the orchestration.

## Testing Strategy
- **Integration Tests**:
    - Mock `BackupExecutor.run_backup` to simulate success and failure for a list of databases.
    - Verify that the loop runs the correct number of times.
    - Verify that the exit code is correct based on the outcomes (all success vs partial failure).

## Dependencies
- `src/odin/cli.py`
- `src/odin/backup.py`
- `src/odin/config.py`

## Decisions & Trade-offs
- To be updated during implementation.

## Testing Prerequisites

**Required Services**
- N/A (Using mocks for initial implementation)

**Environment Configuration**
- N/A

**Manual Validation Checklist**
- [ ] Build succeeds
- [ ] Tests pass
- [ ] **Application runs**: `odin run --config examples/config.linux.json` executes without errors.

**Expected Outcomes**
- The `run` command iterates through all configured databases.
- Logs show the start and end of each backup process.
- Exit code is 0 if all backups succeed.

## Validation Results
- [ ] Service started: N/A
- [ ] Application started successfully
- [ ] Database tables verified: N/A
- [ ] Seed data verified: N/A
- [ ] API endpoints verified: N/A
- [ ] Screenshots captured: N/A

## Completion Reminder
`docs/aide/progress.md` MUST be updated (📋 → 013 🚧 → ✅) when the item is completed.

# Work Item 018: Implementación de Tests de Integración (Firebird Real/Container)

## Description
Create an integration test marked with `@pytest.mark.integration` that uses a real Firebird environment (or a Docker container if available) to validate that the entire flow (`odin run` -> `gbak` -> `.fbk` file) is functional and produces valid files.

## Acceptance Criteria
- [ ] A new test file or test class is created in `tests/`.
- [ ] The test is decorated with `@pytest.mark.integration`.
- [ ] The test uses a real Firebird instance (locally or via Docker).
- [ ] The test executes a command that triggers the backup process.
- [ ] The test verifies that the `.fbk` file is created and is not empty.
- [ ] The test verifies that the process completes without errors.

## Implementation Steps
1. [ ] Set up a requirement for a running Firebird instance (Docker is preferred).
2. [ ] Implement the integration test in `tests/test_backup_integration.py`.
3. [ ] Use `subprocess` or the internal `BackupExecutor` to trigger a backup.
4. [ ] Add assertions for file existence and non-zero size.
5. [ ] Ensure the test can be skipped if a Firebird environment is not available.

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
- To be updated during implementation.

## Testing Prerequisites

**Required Services**
- Firebird Instance (Docker: `docker run --name firebird-test -p 3050:3050 -d firebird`)

**Environment Configuration**
- A configuration file pointing to the test Firebird instance.

**Manual Validation Checklist**
- [ ] Build succeeds
- [ ] Tests pass
- [ ] **Services started**: Docker container is running.
- [ ] **Application runs**: The test executes the `odin run` flow.
- [ ] **Feature verified**: The `.fbk` file is present in `work_dir`.

**Expected Outcomes**
- Integration test passes when Firebird is running.
- Integration test is skipped gracefully when Firebird is not found.

## Validation Results
- [ ] Service started: Firebird (Docker)
- [ ] Application started successfully
- [ ] Database tables verified: N/A
- [ ] Seed data verified: N/A
- [ ] API endpoints verified: N/A
- [ ] Screenshots captured: N/A

## Completion Reminder
`docs/aide/progress.md` MUST be updated (📋 → 018 🚧 → ✅) when the item is completed.

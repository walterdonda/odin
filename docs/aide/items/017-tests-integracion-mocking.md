# Work Item 017: Implementación de Tests de Integración (Mocking de Subprocess)

## Description
Create tests in `tests/test_backup.py` using `unittest.mock` to simulate the execution of `subprocess.run`. These tests should cover various scenarios: successful execution (exit code 0), failure (non-zero exit code), timeouts, and capturing error messages from `stderr`.

## Acceptance Criteria
- [ ] `tests/test_backup.py` exists and is comprehensive.
- [ ] Tests successfully mock `subprocess.run` to avoid requiring a real `gbak` installation.
- [ ] Coverage of:
    - Successful backup (exit code 0).
    - Failed backup due to exit code != 0.
    - Failed backup due to specific error patterns in `stderr`.
    - Backup timeout triggering `subprocess.TimeoutExpired`.
- [ ] All tests pass within the CI/CD-like environment.

## Implementation Steps
1. [ ] Inspect existing `tests/test_backup.py`.
2. [ ] Implement `unittest.mock` patches for `subprocess.run`.
3. [ ] Add test cases for each requirement in the acceptance criteria.
4. [ ] Verify that the `BackupResult` object is correctly asserted in each test case.

## Testing Strategy
- **Unit Tests**: Use `unittest.mock.patch` on `subprocess.run`.
    - Test success: return `returncode=0`, `stdout="ok"`.
    - Test failure: return `returncode=1`, `stderr="error"`.
    - Test pattern: return `stderr="not a valid database"`.
    - Test timeout: raise `subprocess.TimeoutExpired`.

## Dependencies
- `unittest.mock` (standard library)
- `subprocess` (standard library)
- `src/odin/backup.py`

## Decisions & Trade- tradeoffs
- To be updated during implementation.

## Testing Prerequisites

**Required Services**
- N/A

**Environment Configuration**
- N/A

**Manual Validation Checklist**
- [ ] Build succeeds
- [ ] Tests pass

**Expected Outcomes**
- `pytest` or `unittest` execution returns "OK".

## Validation Results
- [ ] Service started: N/ 
- [ ] Application started successfully
- [ ] Database tables verified: N/A
- [ ] Seed data verified: N/A
- [ ] API endpoints verified: N/A
- [ ] Screenshots captured: N/A

## Completion Reminder
`docs/aide/progress.md` MUST be updated (📋 → 🚧 → ✅) when the item is completed.

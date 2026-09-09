# Work Item 010: Implementación core de `src/odin/backup.py` (Ejecución de `gbak`)

## Description
Implement the base logic in `src/odin/backup.py` to execute the `gbak -b` command using `subprocess`. The implementation must capture `stdout` and `stderr`, handle configurable timeouts, and detect failures both by exit code and by identifying known error patterns in the `gbak` output.

## Acceptance Criteria
- [ ] `src/odin/backup.py` exists and contains a class or function to run `gbak`.
- [ ] The implementation uses `subprocess.run` (or similar) to execute the command.
- [ ] `stdout` and `stderr` are captured and stored.
- [ ] A configurable timeout mechanism is implemented.
- [ ] Failures are detected via non-zero exit codes.
- [ ] Known error patterns in `stderr` are identified and handled (to be defined).
- [ ] The core execution logic is decoupled from path detection (which will be Item 011).

## Implementation Steps
1. [x] Create the initial structure for `src/odin/backup.py`.
2. [x] Implement the subprocess execution logic.
3. [x] Add error parsing logic for known `gbak` error patterns.
4. [x] Implement timeout handling.
5. [x] Ensure the implementation can be easily tested with mocks.

## Testing Strategy
- **Unit Tests**: Use `unittest.mock` to mock `subprocess.run`.
    - Test successful execution (exit code 0).
    - Test execution with non-zero exit code.
    - Test execution with timeout triggering `subprocess.TimeoutExpired`.
    - Test error pattern detection in `stderr`.

## Dependencies
- `subprocess` (standard library)
- `src/odin/backup.py` depends on the existence of `gbak` (to be handled by Item 011).

## Decisions & Trade-offs
- Used `subprocess.run` with `capture_output=True` for simplicity and to easily access `stdout` and `stderr`.
- Implemented manual error pattern matching in `stderr` to catch specific `gbak` errors that might not result in a non-zero exit code immediately or that need specific handling.
- Chose to raise `GbakExecutionError` for both non-zero exit codes and pattern matches to provide a consistent error interface.
- Decided to return `False` on unexpected/uncaught exceptions to prevent the entire application from crashing during a scheduled backup task, while still logging the error.


## Testing Prerequisites

**Required Services**
- N/A (Using mocks for core implementation)

**Environment Configuration**
- N/A

**Manual Validation Checklist**
- [ ] Build succeeds
- [ ] Tests pass
- [ ] **Services started**: N/A
- [ ] **Application runs**: N/A
- [ ] **Feature verified**: Manual check of logs if running (though mocks are preferred).
- [ ] **Data verified**: N/A
- [ ] **Health checks pass**: N/A

**Expected Outcomes**
- `subprocess.run` is called with correct arguments (`-b`).
- Captured output contains the expected strings from the mock command.
- Exceptions are raised correctly on timeout or error pattern match.

## Validation Results
- [ ] Service started: N/A
- [ ] Application started successfully
- [ ] Database tables verified: N/A
- [ ] Seed data verified: N/A
- [ ] API endpoints verified: N/A
- [ ] Screenshots captured: N/A

## Completion Reminder
`docs/aide/progress.md` MUST be updated (📋 → 🚧 → ✅) when the item is completed.

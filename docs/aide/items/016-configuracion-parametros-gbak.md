# Work Item 016: Configuración de parámetros de `gbak` (charset, user, password)

## Description
Enhance the backup process by passing additional `gbak` parameters (such as `charset`, `role`, `user`, and `password`) from the JSON configuration to the `gbak` command execution. Ensure that sensitive credentials are handled securely and are not exposed in the logs.

## Acceptance Criteria
- [ ] `DatabaseConfig` in `src/odin/config.py` includes `charset`, `role`, `user`, and `password` (already present in model, but needs wiring to execution).
- [ ] The `BackupExecutor.run_backup` method is updated to accept and use these parameters.
- [ ] The `gbak` command is constructed with the provided parameters (e.g., `-U user -P password -E charset`).
- [ ] Sensitive parameters (like `password`) are **never** logged in plain text.
- [ ] The implementation handles cases where some parameters are missing (uses defaults or omits the flag).

## Implementation Steps
1. [ ] Verify `DatabaseConfig` model in `src/odin/config. py` correctly parses `charset`, `role`, `user`, and `password`.
2. [ ] Update `BackupExecutor.run_backup` to use the parameters from the `DatabaseConfig` object.
3. [ ] Update the `gbak` command list construction logic to include `-U`, `-P`, `-E`, etc., based on available values.
4. [ ] Implement logic to mask or omit the password from the command logging.
5. [ ] Add unit tests to verify the command construction for various parameter combinations.

## Testing Strategy
- **Unit Tests**:
    - Test `run_backup` with only minimal parameters (verify command is correct).
    - Test `run_suppress_backup` with all parameters present (verify `-U`, `-P`, etc., are added).
    - Test `run_backup` with `charset` provided (verify `-E` flag).
    - **Security Test**: Verify that the `password` is NOT present in the `logger.info` output.

## Dependencies
- `src/odin/backup.py`
- `src/odin/config.py`

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
- [ ] **Application runs**: `odin run` with a configuration containing user/password/charset.

**Expected Outcomes**
- The `gbak` command contains the correct flags for any provided parameters.
- Passwords do not appear in the application logs.

## Validation Results
- [ ] Service started: N/A
- [ ] Application started successfully
- [ ] Database tables verified: N/A
- [ ] Seed data verified: N/A
- [ ] API endpoints verified: N/A
- [ ] Screenshots captured: N/A

## Completion Reminder
`docs/aide/progress.md` MUST be updated (📋 → 🚧 → ✅) when the item is completed.

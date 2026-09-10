# Work Item 011: Auto-detección de `gbak` por plataforma y override

## Description
Implement logic to automatically locate the `gbak` binary on different platforms (Linux and Windows) and allow overriding this path via the `gbak_path` property in the JSON configuration.

## Acceptance Criteria
- [ ] Logic is implemented to check common paths on Linux (e.g., `/usr/bin/gbak`, `/opt/firebird/bin/gbak`).
- [ ] Logic is implemented to check common paths on Windows (e.g., `C:\Program Files\Firebird\...\bin\gbak.exe`).
- [ ] The system successfully detects `gbak` on the current platform.
- [ ] If `gbak_path` is provided in the configuration, it takes precedence over auto-detection.
- [ ] The implementation is integrated into the configuration loading process or available via `src/odin/paths.py`.
- [ ] If `gbak` cannot be found anywhere, a clear error is raised.

## Implementation Steps
1. [ ] Define default search paths for Linux and Windows in `src/odin/paths.py` or `src/odin/config.py`.
2. [ ] Implement a function `find_gbak()` that iterates through these paths and checks for file existence.
3. [ ] Update the configuration loading logic to use `gbak_path` from JSON if present, otherwise call `find_gbak()`.
4. [ ] Implement unit tests to verify detection logic by mocking `os.path.exists` and `sys.platform`.

## Testing Strategy
- **Unit Tests**: Use `unittest.mock` to simulate different platforms (`sys.platform`) and file existence (`os.path.exists`).
    - Test successful detection on Linux.
    - Test successful detection on Windows.
    - Test successful override using `gbak_path` from configuration.
    - Test failure when `gbak` is not found.

## Dependencies
- `sys` (standard library)
- `os` or `pathlib` (standard library)
- `src/odin/config.py` (to use the `gbak_path` property)

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
- [ ] **Application runs**: `odin validate` shows correctly detected `gbak_path` or provided path.

**Expected Outcomes**
- `find_gbak()` returns the correct path based on the environment.
- Manual configuration override works as expected.

## Validation Results
- [ ] Service started: N/A
- [ ] Application started successfully
- [ ] Database tables verified: N/A
- [ ] Seed data verified: N/A
- [ ] API endpoints verified: N/A
- [ ] Screenshots captured: N/A

## Completion Reminder
`docs/aide/progress.md` MUST be updated (📋 → 🚧 → ✅) when the item is completed.

# Work Item 026: Resumen de `odin run` y exit codes con archivos comprimidos

## Description
Update the console summary to report per database the `.fbk` path, the `.fbk.7z` path, original and
compressed size and the duration of each phase, and adjust the exit-code semantics: 0 only if every
database was backed up and compressed, 3 if there was a mix of successes and failures, 4 if
everything failed. CLI tests for each scenario, including compression failure with a successful
backup.

## Acceptance Criteria
- [x] The summary prints, per successful base, the `.fbk` path with its size and backup duration and the `.fbk.7z` path with the compressed size and compression duration.
- [x] A base that backed up but failed to compress is reported as failure with the compression error (and still shows the `.fbk` data when available).
- [x] Backup failures keep their current message.
- [x] Exit codes: 0 when all bases complete backup + compression, 3 when some complete and some fail, 4 when none completes (backup or compression) or the batch could not start.
- [x] `run` help/docstrings describe the compressed output (`.fbk` + `.fbk.7z`) and the combined exit-code semantics.
- [x] Tests for each scenario: all success, compression failure with successful backup (total failure), mixed backup/compression failure (partial), and the existing backup-only cases.

## Implementation Steps
1. [x] Update `_print_backup_summary` in `src/odin/cli.py` to render the archive path, compressed size and compression duration, and to distinguish compression failures.
2. [x] Keep the exit-code computation based on the merged per-base flags (already `succeeded == 0 / < total / == total`).
3. [x] Update the `run` subparser description and the CLI module docstring (exit codes and stages).
4. [x] Add the CLI tests, reusing the real-`.fbk` builders from Item 025.

## Testing Strategy
- **Integration Tests (in-process CLI)**: assert stdout/stderr content and exit codes for the full matrix (all OK, partial, all failed) including compression-specific failures.
- **Manual Check**: run the CLI with a backup double to inspect the summary format.

## Dependencies
- Item 025 (merged `BackupResult` with compression data and pipeline).

## Decisions & Trade-offs
- **Encabezado del resumen**: pasa de "Respaldo finalizado" a "Respaldo y
  compresión finalizados" para reflejar ambas fases; la línea de éxito por
  base usa `origen (N bytes, T1 s) → .fbk.7z (M bytes, T2 s)`, reutilizando el
  formato existente de tamaño/duración.
- **Fallo de compresión con respaldo exitoso**: el detalle es
  `compresión fallida: <mensaje>; respaldo: <ruta> (N bytes, T s)`, así el
  operador ve que el `.fbk` existe y puede rescatarlo aunque el `.7z` haya
  fallado. Los fallos de respaldo conservan su mensaje original.
- **Exit codes sin lógica nueva**: el cruce del Item 025 ya deja `success` por
  base en el resultado merged; `_cmd_run` conserva su cómputo
  (`succeeded == 0 → 4`, `< total → 3`, `== total → 0`) y solo cambiaron los
  docstrings/ayuda para describir la semántica combinada.
- **Criterio de demo**: la demo real de `odin run` con `gbak` y `.fbk` +
  `.fbk.7z` se reserva para el Item 029 (Lote C), como indica la queue; los
  tests e2e de este item ya generan ambos artefactos con una compresión real y
  el respaldo doblado.

## Testing Prerequisites

**Required Services**
- N/A

**Environment Configuration**
- N/A

**Manual Validation Checklist**
- [x] Build succeeds — `uv sync`.
- [x] Tests pass — `uv run pytest tests/test_cli.py`: **38 passed in 0.64 s**.
- [x] **Application runs**: `odin run` summary shows both artifacts with sizes and durations (`test_run_all_success_exits_0`).
- [x] **Feature verified**: compresión fallida con respaldo exitoso → exit 4 y mensaje con la ruta del `.fbk` (`test_run_compression_failure_with_successful_backup_exits_4`).
- [x] **Data verified**: mezcla de fallos → exit 3; dos compresiones fallidas → exit 4; todo OK → exit 0.

**Expected Outcomes**
- Complete per-base traceability of both phases in the console output.
- Exit codes answer "did the whole pipeline succeed?" rather than "did gbak run?".

## Validation Results
- [ ] Service started: N/A
- [x] Application started successfully — `uv run pytest tests/test_cli.py` (38 passed, 0.64 s)
- [ ] Database tables verified: N/A
- [ ] Seed data verified: N/A
- [ ] API endpoints verified: N/A
- [ ] Screenshots captured: N/A

## Completion Reminder
`docs/aide/progress.md` MUST be updated (📋 → 026 🚧 → ✅) when the item is completed.

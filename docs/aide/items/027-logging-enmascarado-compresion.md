# Work Item 027: Logging y enmascarado de secretos en la fase de compresión

## Description
Integrate the compression logs with the Stage 1 logging system: start/end per database, original
and compressed size, ratio, level, duration and whether the artifact is encrypted (without
exposing the password). Ensure `compression.password` is covered by `iter_secret_fields()` /
`SecretMasker` and the existing masking patterns. Tests for the absence of the secret in logs and
error outputs.

## Acceptance Criteria
- [x] The compression module logs through `logger = logging.getLogger(__name__)` (`odin.compress`), consistent with `odin.backup`.
- [x] Start line per database with source/destination, level and encrypted flag (never the password).
- [x] Success line per database with original/compressed size, ratio and duration.
- [x] Failure line per database with the clear error message; no password in the message.
- [x] `compression.password` continues to be yielded by `Config.iter_secret_fields()` and is collected by `SecretMasker.from_config()`.
- [x] Tests: `caplog` over a compression with password contains no secret; error messages contain no secret; `SecretMasker` masks a `config.compression.password` value.
- [x] Lazy logging (`%s`-style) and levels follow the Stage 1/2 convention (INFO for happy path, ERROR for failures).

## Implementation Steps
1. [x] Add the start/success/failure log lines to `src/odin/compress.py` (level, sizes, ratio, duration, encrypted flag).
2. [x] Verify `Config.iter_secret_fields()` already includes `config.compression.password` (Item 002) and add the masking test if missing.
3. [x] Extend `tests/test_log.py` with a `SecretMasker.from_config()` case over a config that defines `compression.password`.
4. [x] Add `caplog`-based tests in `tests/test_compress.py` for the absence of the secret in logs and in `CompressionResult.error_message`.

## Testing Strategy
- **Unit Tests**: `caplog.at_level(logging.INFO, logger="odin.compress")`; `SecretMasker` direct masking; `MaskingFilter` integration over an encrypted compression run.
- **Manual Check**: inspect the rotated `odin.log` of a real run and `grep` for the configured password.

## Dependencies
- Item 020 and Item 023 (`src/odin/compress.py` core and encryption).
- Item 004 (`src/odin/log.py`: `SecretMasker`, `MaskingFilter`).
- Item 002 (`Config.iter_secret_fields()`).

## Decisions & Trade-offs
- **Trazas en `odin.compress` con formato lazy**: inicio
  (`Comprimiendo '<base>': origen → destino (nivel N, cifrado: sí/no)`),
  éxito (`Compresión exitosa ... (N → M bytes, X % del original, T s)`) y
  fallo (`Compresión fallida de '<base>': <mensaje>`), con `%s`/`%d` y niveles
  INFO/ERROR, igual que `odin.backup` (Item 019). El flag de cifrado va en la
  línea de inicio porque es una propiedad de la operación solicitada.
- **Doble barrera para la contraseña**: el módulo nunca interpola el valor
  (solo el booleano "cifrado: sí/no") y, además, `setup_logging` aplica
  `MaskingFilter` con los secretos de `Config.iter_secret_fields()`, que ya
  incluía `config.compression.password` desde el Item 002. Los tests cubren
  ambas capas: `caplog` directo sobre `odin.compress` y el archivo/consola
  reales de `setup_logging`.
- **Sin cambios en `iter_secret_fields()`**: la cobertura del secreto ya
  existía; se agregó el test específico de máscara para el valor de
  `compression.password` en `tests/test_log.py`.
- **`CompressionResult.error_message` sin secretos**: los mensajes se
  construyen con rutas y excepciones operativas, nunca con la contraseña; el
  test de fallo con contraseña forzada verifica la ausencia tanto en el
  resultado como en `caplog`.

## Testing Prerequisites

**Required Services**
- N/A

**Environment Configuration**
- A test password of at least `MIN_SECRET_LENGTH` (4) characters so the masker applies.

**Manual Validation Checklist**
- [x] Build succeeds — `uv sync`.
- [x] Tests pass — `uv run pytest tests/test_compress.py tests/test_log.py`: **59 passed in 3.83 s**.
- [x] **Application runs**: compresión con `password` y logging configurado por `setup_logging`.
- [x] **Feature verified**: las líneas de log muestran nivel, tamaños, ratio, duración y "cifrado: sí".
- [x] **Data verified**: `caplog`, la consola y el archivo `odin.log` no contienen el secreto; el `error_message` tampoco.

**Expected Outcomes**
- Complete, consistent compression traceability without secrets.
- `compression.password` covered by the existing masking utilities.

## Validation Results
- [ ] Service started: N/A
- [x] Application started successfully — `uv run pytest tests/test_compress.py tests/test_log.py` (59 passed, 3.83 s)
- [ ] Database tables verified: N/A
- [ ] Seed data verified: N/A
- [ ] API endpoints verified: N/A
- [ ] Screenshots captured: N/A

## Completion Reminder
`docs/aide/progress.md` MUST be updated (📋 → 027 🚧 → ✅) when the item is completed.

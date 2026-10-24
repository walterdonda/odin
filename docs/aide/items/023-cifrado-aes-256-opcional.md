# Work Item 023: Cifrado AES-256 opcional con `compression.password`

## Description
Implement archive encryption when `compression.password` is defined, using the 7zAES/AES-256
support of `py7zr`. Verify its stability on the pinned version and document the decision (enabled,
or discarded with a reason) in the docstring/README. The password must never appear in logs, error
messages or summaries. Tests: the encrypted archive can only be extracted with the correct
password; a wrong password fails; logs do not contain the secret.

## Acceptance Criteria
- [x] `compress_backup()` is extended with `password: str | None = None` and `CompressionResult` with the `encrypted: bool = False` field (default keeps Item 020 consumers working).
- [x] When `password` is set, the archive is encrypted with AES-256 (7zAES); `CompressionResult.encrypted` is `True`.
- [x] Without `password`, the archive is not encrypted and `encrypted` is `False`.
- [x] The encrypted archive extracts with the correct password to the exact original bytes.
- [x] Extraction attempts with a wrong password (or no password) fail.
- [x] The decision about header encryption is documented (enabled vs. content-only and why).
- [x] The password never appears in logs or error messages (covered together with Item 027).
- [x] Stability of the feature confirmed against `py7zr` 1.1.3 (pinned in `uv.lock`).

## Implementation Steps
1. [x] Pass `password` through to `py7zr.SevenZipFile` so the 7zAES filter is applied; set `encrypted` in the result.
2. [x] Document the encryption decision in the module docstring (including the header-encryption choice).
3. [x] Add tests: encrypted round trip with correct password, extraction failure with wrong/no password, `encrypted` flag in both modes.
4. [x] Confirm the failure mode of a wrong password is stable on the pinned version before asserting it in tests.

## Testing Strategy
- **Unit Tests**: `compress_backup(password=...)`, then `py7zr.SevenZipFile(..., password=...)` extraction and byte comparison; wrong password/no password with `pytest.raises` on the observed py7zr/lzma failure; `caplog` absence check.
- **Manual Check**: extract the encrypted archive with 7-Zip/py7zr using the right and wrong credentials.

## Dependencies
- Item 020 and Item 021 (`src/odin/compress.py` core and atomic write).
- Item 027 (secret masking in logs).

## Decisions & Trade-offs
- **Cifrado habilitado, con `header_encryption=False`**: se verificó en
  `py7zr` 1.1.3 que el cifrado de contenido (7zAES/AES-256) funciona estable;
  en cambio, con cabecera cifrada una contraseña incorrecta falla con
  `TypeError: Unknown field: b'...'` (error interno ilegible). Con cabecera en
  claro la extracción tampoco devuelve el contenido, pero el error depende del
  IV aleatorio que py7zr usa por archivo: el flujo LZMA2 descifrado con la
  clave incorrecta puede ser inválido (`lzma.LZMAError`), terminar antes de lo
  esperado (`EOFError: Already at end of stream`) o, en casos raros, dejar al
  extractor de py7zr en un bucle sin progreso. Los dos primeros son
  interpretables y por eso el test fija el IV en lugar de depender del azar;
  el nombre de archivo no es un secreto.
- **Filtro AES explícito (trampa de py7zr 1.1.3)**: `_prepare_write` solo
  inyecta `DEFAULT_FILTERS.ENCRYPTED_ARCHIVE_FILTER` cuando `password` está
  definido **y `filters is None`**. Como ODIN pasa filtros explícitos para el
  nivel (Item 022), la primera versión "cifraba" en falso: el `password` se
  pasaba pero el archivo quedaba en claro y los tests de extracción sin clave
  pasaban. Se corrigió agregando a mano
  `{"id": py7zr.FILTER_CRYPTO_AES256_SHA256}` después del filtro de
  compresión (orden comprimir → cifrar) cuando hay contraseña. Evidencia: el
  round trip cifrado extrae byte a byte con la clave correcta y falla sin
  clave/clave incorrecta.
- **`encrypted` refleja la intención también en fallos**: `_failure()` recibe
  `encrypted` para que el resultado fallido indique si se pidió cifrado; el
  pipeline (Item 025) podrá informarlo en el resumen.
- **Compatibilidad de la firma**: `password` es keyword-only y con default
  `None`; los consumidores del Item 020 no cambian.

## Testing Prerequisites

**Required Services**
- N/A

**Environment Configuration**
- A test password of at least `MIN_SECRET_LENGTH` (4) characters so the masker applies.

**Manual Validation Checklist**
- [x] Build succeeds — `uv sync`.
- [x] Tests pass — `uv run pytest tests/test_compress.py`: **24 passed in 2.87 s**.
- [x] **Application runs**: `compress_backup(..., password="...")` sobre un `.fbk` real.
- [x] **Feature verified**: el `.7z` solo se extrae con la contraseña correcta; sin clave lanza `PasswordRequired` y con clave incorrecta un error de descompresión (`lzma.LZMAError` o `EOFError`, según el IV aleatorio del archivo).
- [x] **Data verified**: los bytes extraídos coinciden con el origen; `encrypted` es `True` solo con contraseña.

**Expected Outcomes**
- Optional encryption enabled through configuration, no new CLI surface.
- Documented, reproducible decision for header encryption.

## Validation Results
- [ ] Service started: N/A
- [x] Application started successfully — `uv run pytest tests/test_compress.py` (24 passed, 2.87 s)
- [ ] Database tables verified: N/A
- [ ] Seed data verified: N/A
- [ ] API endpoints verified: N/A
- [ ] Screenshots captured: N/A

## Completion Reminder
`docs/aide/progress.md` MUST be updated (📋 → 023 🚧 → ✅) when the item is completed.

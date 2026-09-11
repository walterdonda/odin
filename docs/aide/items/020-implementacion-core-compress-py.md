# Work Item 020: Implementación core de `src/odin/compress.py` (`.fbk → .fbk.7z` con py7zr)

## Description
Implement the base compression logic with `py7zr`: receive the source `.fbk` and the destination
`.fbk.7z`, compress with the configured level, and validate the resulting artifact (exists,
non-empty and readable), measuring duration and original/compressed sizes. Define the reusable
`CompressionResult` dataclass (success/failure, paths, sizes, ratio, duration and error message)
for the pipeline. Expected operational errors (missing/empty source, `py7zr` failure, permissions)
must not propagate as exceptions: they are reported in `CompressionResult`. Unit tests with real
temporary files.

## Acceptance Criteria
- [x] `src/odin/compress.py` exposes `compress_backup(database_name, source_path, archive_path=None, *, level=7) -> CompressionResult` (the `password` parameter and the `encrypted` field are introduced by Item 023).
- [x] `CompressionResult` is a frozen dataclass with: `success`, `database_name`, `source_path`, `archive_path`, `original_size_bytes`, `compressed_size_bytes`, `compression_ratio`, `duration_seconds`, `error_message`.
- [x] Default destination follows the `<origen>.7z` convention (e.g. `erp_20260911_020000.fbk` → `erp_20260911_020000.fbk.7z`), including a public helper for the naming.
- [x] The generated archive is validated (exists, size > 0, readable) before reporting success.
- [x] Missing, empty or unreadable source, and `py7zr`/I/O failures return `success=False` with a clear message; no exception escapes.
- [x] Round trip test with a real temporary file: the archive extracted with `py7zr` matches the source byte by byte.
- [x] `compression_ratio` is documented as `compressed_size / original_size` (1.0 = no reduction).

## Implementation Steps
1. [x] Create `src/odin/compress.py` with module docstring and `logger = logging.getLogger(__name__)`.
2. [x] Define `CompressionError`, the `CompressionResult` dataclass and the `archive_path_for()` helper.
3. [x] Implement `compress_backup()`: validate source, build the `py7zr.SevenZipFile` filters, write the archive and validate the artifact.
4. [x] Report failures through a `_failure()` helper that logs `ERROR` and fills `CompressionResult`.
5. [x] Add `tests/test_compress.py` with real temporary files (round trip, result fields, missing/empty source).

## Testing Strategy
- **Unit Tests**: real temporary files; `py7zr` extraction and byte-by-byte comparison; missing/empty source; failed write via mocked `py7zr`.
- **Manual Check**: compress a synthetic file and inspect sizes and result fields.

## Dependencies
- `py7zr >= 1.0` (already in `pyproject.toml`, pinned 1.1.3 in `uv.lock`)
- `odin.config.CompressionConfig` (level/password model, Item 002)
- Placeholder for the atomic publication introduced in Item 021.

## Decisions & Trade-offs
- **Función de módulo, no clase**: `compress_backup()` recibe primitivas
  (``level``) en lugar de un `CompressionConfig`, para que la compresión no
  dependa del modelo de configuración; el futuro `CompressionExecutor`
  (Item 024) resuelve el config y llama a la función. `archive_path_for()` se
  expone como helper público reutilizable por el pipeline.
- **`database_name` en `CompressionResult`**: el pipeline necesita asociar el
  resultado a una base sin depender de la ruta; reutiliza el patrón de
  `BackupResult`.
- **`compression_ratio = compressed / original`**: se documenta como fracción
  del original (1.0 = sin reducción; menor es mejor) para evitar la ambigüedad
  de la convención inversa; los consumidores pueden mostrarla como porcentaje.
- **Errores operativos siempre en el resultado**: las precondiciones se
  validan con `CompressionError` y la operación captura `OSError`,
  `py7zr.exceptions.ArchiveError` y `lzma.LZMAError`; `_failure()` registra el
  error y devuelve `success=False`. No se capturan excepciones arbitrarias:
  un bug interno debe seguir aflorando (postura del Item 019).
- **Escritura directa al destino en este item**: la escritura atómica y la
  limpieza de temporales son el alcance del Item 021; acá el artefacto se
  escribe en la ruta final para mantener el incremento mínimo verificable.
- **Filtros `py7zr` 1.1.3**: `[{"id": FILTER_LZMA2, "preset": level}]` es la
  API estable de la versión fijada; el mapeo completo del nivel 0 y la
  validación de rango llegan en el Item 022.
- **Origen legible**: además de existir y no estar vacío se comprueba
  `os.access(R_OK)`, alineado con la validación post-respaldo del Item 014.

## Testing Prerequisites

**Required Services**
- N/A (pure local file compression; no 7-Zip/p7zip binary required).

**Environment Configuration**
- N/A

**Manual Validation Checklist**
- [x] Build succeeds — `uv sync` (entorno ya sincronizado).
- [x] Tests pass — `uv run pytest tests/test_compress.py`: **8 passed in 0.29 s**.
- [x] **Application runs**: `compress_backup()` sobre `PAYLOAD` real genera el `.7z` con nombre por defecto.
- [x] **Feature verified**: el `.7z` se extrae con `py7zr` y coincide byte a byte (`test_round_trip_is_byte_identical`).
- [x] **Data verified**: `original_size_bytes`, `compressed_size_bytes` y `compression_ratio` coherentes con los archivos en disco.

**Expected Outcomes**
- `.fbk.7z` archive created next to the source with the `<origen>.7z` name.
- `CompressionResult` always returned (never an exception) for expected operational errors.
- Round trip byte-identical.

## Validation Results
- [ ] Service started: N/A
- [x] Application started successfully — `uv run pytest tests/test_compress.py` (8 passed, 0.29 s)
- [ ] Database tables verified: N/A
- [ ] Seed data verified: N/A
- [ ] API endpoints verified: N/A
- [ ] Screenshots captured: N/A

## Completion Reminder
`docs/aide/progress.md` MUST be updated (📋 → 020 🚧 → ✅) when the item is completed.

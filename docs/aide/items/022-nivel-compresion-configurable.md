# Work Item 022: Nivel de compresión configurable (`compression.level`) con efecto medible

## Description
Map `compression.level` (0–9, default 7) to the `py7zr` presets/filters, validating the range in
the compression phase in addition to `config.py`. Tests that compress synthetic compressible data
and verify that level 1 and level 9 produce different output sizes (measurable effect), and that
the level actually used is recorded in the log.

## Acceptance Criteria
- [x] Level `0` maps to store mode (`py7zr.FILTER_COPY`); levels `1–9` map to `FILTER_LZMA2` with `preset` = level.
- [x] The range `0–9` is validated inside the compression phase (defense in depth over `config.py`); out-of-range values return `success=False` with a clear message and create no file.
- [x] Level 1 and level 9 produce measurably different archive sizes when compressing synthetic data with long-range redundancy (dictionary size effect).
- [x] The effective level is logged (start and/or success lines) and can be asserted from `caplog`.
- [x] Level 0 archive extracts to the exact original bytes (store mode is not lossy).
- [x] `DEFAULT_COMPRESSION_LEVEL`, `MIN_COMPRESSION_LEVEL` and `MAX_COMPRESSION_LEVEL` constants are exported/documented.

## Implementation Steps
1. [x] Add the level constants and `_filters_for_level(level)` mapping in `src/odin/compress.py`.
2. [x] Validate the level before touching the filesystem; report invalid values as a failure result.
3. [x] Pass the filters to `py7zr.SevenZipFile` and include the level in the log lines.
4. [x] Add tests: level effect (1 vs 9), level 0 round trip, invalid levels (`-1`, `10`), level present in logs.

## Testing Strategy
- **Unit Tests**: synthesize data with a repeated block larger than the preset-1 dictionary (1 MiB) so preset 9 wins measurably; extract both archives and compare sizes and bytes; `caplog` assertion for the level.
- **Manual Check**: compress the same fixture with levels 0, 1 and 9 and compare sizes.

## Dependencies
- Item 020 (`src/odin/compress.py` core).
- Item 002 (`compression.level` parsing and range validation in `config.py`).

## Decisions & Trade-offs
- **Nivel 0 = `FILTER_COPY` (store)**: el rango `0-9` de `config.py` (Item
  002) y de la queue incluye el 0; se interpreta como el nivel 0 de 7-Zip
  (sin compresión) y no como `preset=0` de LZMA2, que igualmente comprime y
  volvería engañoso el valor. El roadmap mencionaba `1-9`: se prioriza el
  contrato del modelo de configuración y se documenta acá la divergencia.
- **Validación duplicada a propósito**: `config.py` valida el rango al parsear
  y `_filters_for_level` lo revalida en la fase de compresión. La función es
  API pública y puede ser llamada con valores construidos a mano (tests,
  pipeline futuro); el fallo se reporta como `CompressionResult` y no crea
  archivos porque la validación precede a la creación del temporal.
- **Efecto medible con redundancia de largo rango**: el test de nivel 1 vs 9
  usa un bloque aleatorio de 1.5 MB repetido 3 veces; el diccionario del
  preset 1 (1 MiB) no alcanza la distancia de repetición y el 9 (64 MiB) sí.
  Así la diferencia de tamaño es contundente y reproducible, en lugar de
  depender de datos demasiado compresibles donde ambos presets empatan.
- **Nivel en el log de inicio**: la línea "Comprimiendo ... (nivel N)" deja
  constancia del nivel efectivo sin necesidad de mirar la configuración.

## Testing Prerequisites

**Required Services**
- N/A

**Environment Configuration**
- N/A

**Manual Validation Checklist**
- [x] Build succeeds — `uv sync`.
- [x] Tests pass — `uv run pytest tests/test_compress.py`: **20 passed in 2.34 s**.
- [x] **Application runs**: misma fuente comprimida con `level=1` y `level=9`.
- [x] **Feature verified**: tamaño nivel 1 (4.5 MB aprox.) vs nivel 9 (1.5 MB aprox.); el log reporta el nivel efectivo.
- [x] **Data verified**: nivel 0 extrae byte a byte el original; niveles inválidos no crean archivo.

**Expected Outcomes**
- Level mapping documented and logged.
- Invalid levels reported through `CompressionResult`, never as an exception.

## Validation Results
- [ ] Service started: N/A
- [x] Application started successfully — `uv run pytest tests/test_compress.py` (20 passed, 2.34 s)
- [ ] Database tables verified: N/A
- [ ] Seed data verified: N/A
- [ ] API endpoints verified: N/A
- [ ] Screenshots captured: N/A

## Completion Reminder
`docs/aide/progress.md` MUST be updated (📋 → 022 🚧 → ✅) when the item is completed.

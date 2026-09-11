# Work Item 021: Escritura atómica del `.7z` y manejo del destino existente

## Description
Compress to a temporary file in the same directory as the destination and publish it with
`os.replace` only when the operation was successful, removing the temporary file on any failure
so no orphan partial `.7z` files are left behind. Define and document the behavior when the
destination already exists (controlled overwrite, consistent with the timestamp naming
convention). Tests: a simulated mid-compression failure (mock of `py7zr`) leaves no residue; an
existing destination is handled without corrupting the previous file.

## Acceptance Criteria
- [x] Compression writes to a unique temporary file in the destination directory, never directly to the final path.
- [x] The final archive is published with `os.replace` (atomic on Windows and Linux) only after the artifact passed validation.
- [x] Any failure (I/O error, `py7zr` error, validation) removes the temporary file; no `*.tmp` or partial `.7z` remains.
- [x] Destination policy documented: an existing archive is replaced only after the new one is complete, so a failed compression never corrupts the previous archive.
- [x] Tests: mocked `py7zr` failure leaves the destination directory clean; pre-existing archive survives a failure; pre-existing archive is atomically replaced on success.

## Implementation Steps
1. [x] Add a `_temporary_path()` helper using `tempfile.mkstemp` in the destination directory (handle closed immediately, Windows-safe).
2. [x] Write the archive to the temporary path inside a `try`, validate it, and publish with `os.replace`.
3. [x] In the `except` path, `unlink(missing_ok=True)` the temporary file before returning the failure result.
4. [x] Document the destination policy in the module docstring and in `compress_backup()`.
5. [x] Extend `tests/test_compress.py` with the failure/residue and existing-destination cases.

## Testing Strategy
- **Unit Tests**: failure injected with `unittest.mock.patch` on `odin.compress.py7zr.SevenZipFile`; glob the destination directory to assert no leftovers; sentinel content in a pre-existing archive.
- **Manual Check**: run the same compression twice and confirm a single coherent archive remains.

## Dependencies
- Item 020 (`src/odin/compress.py` core).

## Decisions & Trade-offs
- **Temporal con `tempfile.mkstemp` en el directorio destino**: el descriptor
  se cierra de inmediato (en Windows un handle abierto bloquearía a `py7zr`) y
  el temporal comparte sistema de archivos con el destino, requisito para que
  `os.replace` sea atómico. El nombre es oculto y único
  (`.{destino}.XXXX.tmp`), así que dos compresiones concurrentes no colisionan.
- **Destino existente: sobreescritura atómica**: con el nombrado por timestamp
  las colisiones son raras, pero si el destino existe se reemplaza recién
  cuando la nueva copia pasó la validación. El archivo anterior queda intacto
  ante cualquier fallo; no se implementa renombrado incremental (p. ej.
  `.1`, `.2`) porque el timestamp ya garantiza unicidad y la retención
  (Etapa 5) se encargará de la limpieza.
- **Validar antes de publicar**: `_validate_archive` corre sobre el temporal y
  acepta `display_path` para que los mensajes de error apunten a la ruta final
  y no al temporal interno.
- **Limpieza única en el `except`**: todas las ramas de fallo posteriores a la
  creación del temporal llaman `unlink(missing_ok=True)`; la creación del
  temporal tiene su propio `try` con mensaje específico
  ("no se pudo preparar el temporal...").
- **Cobertura con dobles**: `_PartialThenFailArchive` escribe contenido parcial
  y falla al salir (simula disco lleno a mitad de compresión);
  `_EmptyArchive` no escribe nada (simula artefacto vacío). Ambos verifican
  limpieza con `glob("*.tmp")` y ausencia/estabilidad del destino.

## Testing Prerequisites

**Required Services**
- N/A

**Environment Configuration**
- N/A

**Manual Validation Checklist**
- [x] Build succeeds — `uv sync`.
- [x] Tests pass — `uv run pytest tests/test_compress.py`: **14 passed in 0.45 s**.
- [x] **Application runs**: compresión sobre un destino con una copia previa.
- [x] **Feature verified**: tras el fallo simulado no hay `.tmp`/`.7z` parcial y la copia previa queda intacta.
- [x] **Data verified**: la copia previa solo se reemplaza cuando la nueva compresión culmina (`test_existing_archive_is_replaced_on_success`).

**Expected Outcomes**
- No orphan temporary files under any failure path.
- Existing archive replaced atomically on success, preserved on failure.

## Validation Results
- [ ] Service started: N/A
- [x] Application started successfully — `uv run pytest tests/test_compress.py` (14 passed, 0.45 s)
- [ ] Database tables verified: N/A
- [ ] Seed data verified: N/A
- [ ] API endpoints verified: N/A
- [ ] Screenshots captured: N/A

## Completion Reminder
`docs/aide/progress.md` MUST be updated (📋 → 021 🚧 → ✅) when the item is completed.

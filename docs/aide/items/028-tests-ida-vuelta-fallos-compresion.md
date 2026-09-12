# Work Item 028: Tests de ida y vuelta y de fallos de compresión

## Description
Consolidar la batería de la Etapa 3: ida y vuelta (comprimir con ODIN, extraer con `py7zr`, comparación byte a byte), origen inexistente/corrupto, fallo por disco lleno simulado (`OSError: No space left on device`), interrupción con limpieza de temporales, y test de integración marcado con `@pytest.mark.integration` que ejecute `odin run` (con `gbak` mockeado o Firebird real) y verifique la generación de ambos artefactos. Dejar `uv run pytest` verde.

## Acceptance Criteria
- [ ] Test de ida y vuelta: comprimir con ODIN, extraer con `py7zr` y comparar byte a byte.
- [ ] Test de origen inexistente o corrupto.
- [ ] Test de fallo por disco lleno simulado (`OSError: No space left on device`).
- [ ] Test de interrupción con limpieza de archivos temporales.
- [ ] Test de integración (`@pytest.mark.integration`) que ejecute `odin run` y verifique la generación de `.fbk` y `.fbv.7z`.
- [ ] `uv run pytest` pasa sin errores.

## Implementation Steps
1. Implementar tests unitarios para los escenarios de error identificados en `src/odin/compress.py`.
2. Implementar test de integración que utilice un `work_dir` temporal y mocks/instancias de `gbak` si es necesario.
3. Asegurar que la limpieza de temporales se verifique durante los tests de interrupción.
4. Ejecutar la suite completa de tests para confirmar que no hay regresiones.

## Testing Strategy
- **Unit Tests**: Utilizar `pytest` para probar la lógica de `compress.py` con archivos temporales y mocks de errores de sistema (e.g., `OSError`).
- **Integration Tests**: Utilizar `@pytest.mark.integration` para probar el flujo completo de `odin run` y la presencia de los archivos resultantes.
- **Byte-by-byte Validation**: Implementar una utilidad de comparación para asegurar la integridad de los datos tras la extracción.

## Dependencies
- `py7zr` (para la extracción y validación).
- `pytest` (framework de testing).
- `src/odin/compress.py` (módulo a testear).

## Decisions & Trade-offs
To be updated during implementation.

## Completion Reminder
`docs/aide/progress.md` MUST be updated (📋 → 🚧 → ✅) when the item is completed.

## Testing Prerequisites

**Required Services**
- N/A

**Environment Configuration**
- Python environment with `uv` and necessary dependencies (`py7zr`, etc.).

**Manual Validation Checklist**
- [ ] Build succeeds
- [ ] Tests pass
- [ ] **Services started**: N/A
- [ ] **Application runs**: `uv run pytest`
- [ ] **Feature verified**: Verificación de archivos `.fbk` y `.fbk.7z` existentes tras ejecución.
- [ ] **Data verified**: Comparación de hashes o bytes entre origen y destino extraído.
- [ ] **Health checks pass**: N/A

**Expected Outcomes**
- Los tests unitarios cubren todos los casos de error (disco lleno, archivo no encontrado).
- El test de integración confirma la creación de artefactos comprimidos.
- No hay archivos temporales huérfanos tras un fallo simulado.

## Validation Results
- [ ] Service started: N/A
- [ ] Application started successfully
- [ ] Database tables verified: N/A
- [ ] Seed data verified: N/A
- [ ] API endpoints verified: N/A
- [ ] Screenshots captured: N/A

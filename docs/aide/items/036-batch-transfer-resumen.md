# Item 036: Integración de notificaciones y reporte de transferencia en el resumen

## Description

Actualizar el resumen de `odin run` y el logging para incluir información detallada de la fase de transferencia: rutas de archivos transferidos, tamaño, duración y estado por servidor destino. Definir `BatchTransferResult` (agregado con totales) en `src/odin/transfer.py` y hacer que `PipelineResult` lo exponga por base, de modo que el informe final que llegará por correo en la Etapa 5 ya tenga la estructura agregada.

## Acceptance Criteria

- [ ] `BatchTransferResult` (frozen dataclass) en `src/odin/transfer.py`: resultados por servidor, éxito agregado y duración total del lote.
- [ ] `PipelineResult.transfers` pasa a ser `Mapping[str, BatchTransferResult]` (por base).
- [ ] El resumen de consola de `odin run` informa por base y por servidor: ruta remota, bytes transferidos, duración y estado (OK/FALLO con motivo); el logger registra el resumen agregado de la fase.
- [ ] El comportamiento de exit codes del Item 035 se conserva.
- [ ] Tests del agregado y del nuevo formato del resumen.

## Implementation Steps

1. Definir `BatchTransferResult` en `src/odin/transfer.py` y un constructor de agregación (p. ej. `BatchTransferResult.from_results(...)` o helper) que derive `success` de los resultados y totalice la duración.
2. Actualizar `src/odin/pipeline.py`: `run_pipeline` agrega los resultados por base en `BatchTransferResult` y los expone en `PipelineResult.transfers`.
3. Extender el resumen de `odin run` en `odin/cli.py`: tras el resumen de respaldo/compresión, líneas por base y por servidor (`- {base} → {servidor}: OK {remote_path} ({bytes} bytes, {s}s)` / `FALLO {servidor}: {motivo}`) y un total de la fase de transferencia; los fallos van a stderr como en el resumen actual.
4. Registrar en el logger el resumen agregado por base (estado, servidores exitosos/totales, duración) para que quede en el archivo rotado y sirva de base al informe de correo de la Etapa 5.
5. Actualizar la sección "Ejecución de respaldos (`odin run`)" del README para mencionar la fase de transferencia en el resumen.
6. Tests: agregación en `tests/test_transfer_executor.py` (o archivo dedicado), pipeline con `BatchTransferResult` en `tests/test_pipeline.py` y formato del resumen en `tests/test_cli.py`.

## Testing Strategy

- Unit: `BatchTransferResult` agrega correctamente (todo éxito, mezcla, todo fallo, vacío) y totaliza duraciones.
- Unit (`tests/test_pipeline.py`): `transfers` contiene `BatchTransferResult` por base con los resultados individuales intactos.
- CLI: captura de stdout/stderr para verificar líneas por servidor (OK con ruta remota/bytes/duración y FALLO con motivo), y que los exit codes 0/3/4 no cambian.
- Suite completa: `uv run pytest`, `uv run ruff check`, `uv run mypy`.

## Dependencies

- Item 035 (pipeline), `src/odin/transfer.py` (Item 034), `src/odin/cli.py` (Items 025-026).

## Decisions & Trade-offs

- **`BatchTransferResult` inmutable + `aggregate_transfer_results()`**: sigue el patrón de `BatchBackupResult`/`BatchCompressionResult` (`results` + `success` + `total_duration_seconds`). La duración del lote se calcula como **suma de duraciones individuales** en lugar de medir el tiempo de pared: las transferencias son secuenciales y la suma aproxima el total sin añadir un reloj en el agregador (el ejecutor ya mide el lote en su log).
- **Éxito vacuo del lote vacío** (`all([]) is True`): documentado en el docstring; el pipeline nunca agrega un lote vacío porque sin servidores la fase se salta (Item 035).
- **`PipelineResult.transfers: Mapping[str, BatchTransferResult]`**: el mapping por base que introdujo el Item 035 ahora expone el agregado por base — es la estructura que el informe de correo de la Etapa 5 consumirá directamente (totales por base + detalle por servidor en `.results`).
- **Resumen en dos niveles**: `_print_transfer_summary` en `odin/cli.py` imprime un total global de la fase y una línea por servidor por base (OK con ruta remota/bytes/duración a stdout; FALLO con motivo a stderr, consistente con el resumen de respaldo/compresión). El logger registra además el agregado por base (`Transferencia de '%s': x/y servidor(es)`) para el archivo rotado, que es la fuente del modo servicio (Etapa 7).
- **Cruce de información**: la línea `FALLO {base}` del resumen de respaldo ya apuntaba `transferencia fallida: <detalle por servidor>` desde el Item 035; el detalle fino por servidor vive en la sección de transferencia, sin duplicar la causa en dos lugares.
- **`tests/test_cli.py`**: los dobles de transferencia ahora usan `posixpath.join` para la ruta remota (el `remote_path` del fixture termina en `/` y la concatenación ingenua dejaba doble barra, que el `TransferExecutor` real no produce).

**Evidencia:** `uv run pytest -q` → 313 passed, 1 skipped; `uv run ruff check src/odin tests` → All checks passed; `uv run mypy src/odin` → Success. 6 tests nuevos (4 de agregación en `tests/test_transfer_executor.py`, 2 de resumen en `tests/test_cli.py`).

## Prerequisites

- `docs/aide/progress.md` debe ser actualizado a 📋 al iniciar.
- Al finalizar, actualizar `docs/aide/progress.md` a ✅.

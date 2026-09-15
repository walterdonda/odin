# Item 046: Integración de la retención en el pipeline, reporte y actualización de `validate`

## Description

Insertar la fase de retención en `run_pipeline` **después del envío del correo** (orden del flujo de la visión: recopilación → correo → limpieza → exit code), con el ejecutor inyectable; `PipelineResult` gana `retention: RetentionResult | None`. La retención no aparece en el correo (se envía antes) pero sí en el log y en el resumen de consola: línea "Retención local: N archivo(s) eliminado(s), X MB liberados" enmascarada. Política de fallo: la retención es función secundaria; sus errores se reportan y loguean pero **no** alteran el exit code (decisión documentada). Actualizar `validate.py` para describir el comportamiento real (sin "(Etapa 5)") y revisar que la advertencia de `retention_days=0` siga siendo coherente. Tests: pipeline con retención doble verifica el orden respecto de la notificación y el aislamiento; CLI imprime el resumen de retención; tests de `validate` actualizados.

## Acceptance Criteria

- [ ] `PipelineResult.retention: RetentionResult | None` y `run_pipeline(retention=...)` inyectable; el default es `RetentionExecutor()`.
- [ ] La retención corre **después** de `_send_report` (el informe nunca la menciona) y **antes** de retornar el resultado.
- [ ] La retención nunca lanza ni propaga excepciones: un fallo del ejecutor queda como `RetentionResult` con errores y no rompe el pipeline.
- [ ] `_cmd_run` imprime "Retención local: N archivo(s) eliminado(s), X MB liberados." (stdout) o "Retención local: deshabilitada (retention_days=0)." y los errores por archivo a stderr; todo enmascarado con `SecretMasker`.
- [ ] El exit code no cambia por la retención (0/1/3/4 según la matriz vigente).
- [ ] `validate.py` describe el comportamiento real: "las copias locales de más de N día(s) se eliminarán tras el envío del correo" (sin "(Etapa 5)") y `retention_days=0` sigue siendo INFO.
- [ ] Tests: pipeline con doble de retención verifica orden (correo antes) y aislamiento; CLI imprime el resumen; `tests/test_validate.py` actualizado.
- [ ] Suite verde: `uv run pytest`, `uv run ruff check`, `uv run mypy`.

## Implementation Steps

1. Extender `PipelineResult` con `retention: RetentionResult | None = None` y agregar `retention: RetentionExecutor | None = None` a `run_pipeline` (default `RetentionExecutor()`).
2. Ejecutar `retention.run_retention(config.local.work_dir, config.local.retention_days)` después de `_send_report` y devolverlo en el resultado con `replace`.
3. Documentar en los docstrings de módulo y de `run_pipeline` el orden de fases y la política de fallo (no altera exit code).
4. Agregar `_print_retention_summary(retention, *, mask)` en `cli.py` siguiendo el patrón de `_print_notification_summary`; invocarlo desde `_cmd_run` junto a los demás resúmenes y registrar el desenlace en el logger.
5. Actualizar `_check_compression_and_retention` en `validate.py` (mensaje sin "(Etapa 5)").
6. Actualizar `tests/test_pipeline.py`, `tests/test_cli.py` y `tests/test_validate.py`.

## Testing Strategy

- `tests/test_pipeline.py`: doble `FakeRetentionExecutor` que registra el estado de los dobles en el momento de su llamada (assert `notifier.calls` ya tiene el informe → orden correo → retención), no altera exit codes del pipeline, y un ejecutor que lanza queda contenido (red de seguridad en `run_pipeline`) sin excepción.
- `tests/test_cli.py`: `_cmd_run` imprime la línea de retención con archivos eliminados (crear artefactos viejos en el `work_dir` real + fake de retención) y la variante deshabilitada; errores a stderr; enmascarado del error con un secreto inyectado; exit code sin cambios.
- `tests/test_validate.py`: el mensaje positivo ya no contiene "(Etapa 5)"; `retention_days=0` sigue INFO.
- Gates: `uv run pytest`, `uv run ruff check`, `uv run mypy`.

## Dependencies

- Item 045 (`RetentionResult`, `RetentionExecutor`).

## Decisions & Trade-offs

- **Retención al final, fuera de la captura de cola del correo**: `run_pipeline` envía el informe y solo después ejecuta la limpieza; el `TailBufferHandler` ya está removido en ese punto, así que ninguna línea de retención entra al correo (el informe describe la corrida antes de la limpieza, como pide el flujo de la visión).
- **Red de seguridad `_run_retention` en el pipeline**: `RetentionExecutor` ya aísla los `OSError` de borrado, pero el pipeline envuelve la llamada y convierte una excepción imprevista en `RetentionResult(errors=(...))` logueado — la limpieza es secundaria y jamás puede romper la corrida ni cambiar el exit code.
- **El ejecutor default siempre corre, incluso con `retention_days=0`**: devuelve un resultado `enabled=False` (no-op barato) y así `PipelineResult.retention` queda siempre poblado; `None` queda reservado a construcciones manuales, igual que `notification`.
- **La retención no participa del éxito global**: `BatchBackupResult.success` y la matriz 0/1/3/4 se calculan solo con las tres fases + correo; los errores de la limpieza se imprimen por stderr y quedan en el log, pero el código de salida se conserva (decisión documentada en docstrings de `pipeline.py`/`cli.py`).
- **Doble salida del resumen**: totales por stdout ("Retención local: N archivo(s) eliminado(s), X MB liberados." o "deshabilitada (retention_days=0).") y errores por archivo por stderr, siguiendo el patrón del resto de los resúmenes; ambos enmascarados con `SecretMasker`, y el desenlace también se registra en `odin.log` (lo consume el `MaskingFilter`).
- **`validate` describe el comportamiento real**: se retiró el "(Etapa 5)" del mensaje positivo y se explicita "después del envío del correo"; la advertencia informativa de `retention_days=0` ("sin limpieza automática") sigue siendo coherente con el no-op.

**Evidencia:** `uv run pytest tests/test_retention.py tests/test_pipeline.py tests/test_cli.py tests/test_validate.py -q` → 147 passed (3 tests nuevos de pipeline: orden correo → retención y ausencia de la retención en el informe, resultado default poblado, excepción del ejecutor contenida; 4 de CLI: línea con eliminados + log, variante deshabilitada, error por stderr sin cambiar el exit code, enmascarado en stderr y `odin.log`; `test_validate.py` verifica el mensaje sin "(Etapa 5)"); suite completa `uv run pytest` → 408 passed + 1 skipped (gbak real ausente); `uv run ruff check src/odin tests` → All checks passed; `uv run mypy src/odin` → Success.

## Prerequisites

- `docs/aide/progress.md` debe ser actualizado a 🚧 al iniciar.
- Al finalizar, actualizar `docs/aide/progress.md` a ✅.

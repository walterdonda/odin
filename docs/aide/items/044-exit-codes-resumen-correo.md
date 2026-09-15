# Item 044: Exit codes finales y resumen de consola consistentes con el correo

## Description

Cerrar la matriz completa de exit codes de `odin run` con la notificación incluida y documentarla: `0` todas las bases completaron las tres fases **y** correo enviado; `3` mezcla de éxitos y fallos (cualquier fase); `4` fallo total / respaldo no ejecutado / lote vacío; `2` error de configuración; `1` error interno o fallo de notificación en una corrida por lo demás exitosa. Extender el resumen de consola de `_cmd_run` con una línea del resultado de la notificación ("Correo enviado a X" o "Correo NO enviado: motivo") enmascarada con `SecretMasker`. Actualizar el help/description de `run` en `build_parser` y la tabla de exit codes del README.

## Acceptance Criteria

- [ ] `_cmd_run` aplica la precedencia completa: 4 (lote no ejecutado/vacío/fallo total) > 1 (correo fallido en corrida exitosa) > 0; 3 se conserva con mezcla aunque el correo falle.
- [ ] Una corrida con todas las fases OK y SMTP caído devuelve `EXIT_INTERNAL` (1), no 0.
- [ ] El resumen imprime "Correo enviado a <destinatario>" (stdout) o "Correo NO enviado: <motivo>" (stderr), enmascarado.
- [ ] `run --help`/description menciona la fase de correo.
- [ ] README: tabla de exit codes actualizada (0 exige correo enviado; 1 incluye fallo de notificación) y descripción de `odin run` con la fase de correo.
- [ ] Tests de CLI: los cinco códigos, incluido pipeline OK + SMTP caído → 1, línea de correo presente y sin secretos.
- [ ] Suite verde: `uv run pytest`, `uv run ruff check`, `uv run mypy`.

## Implementation Steps

1. Agregar `_print_notification_summary(notification, *, mask)` en `src/odin/cli.py` siguiendo el patrón de los resúmenes existentes (éxito a stdout, fallo a stderr).
2. Integrar la línea en `_cmd_run` tras los resúmenes de respaldo/compresión y transferencia, y registrar el resultado en el logger.
3. Reescribir la decisión de exit code con la notificación incluida (documentar la precedencia en el docstring del módulo y de `_cmd_run`).
4. Actualizar el `description`/`help` de `run` en `build_parser` y la tabla de exit codes + sección de `odin run` del README.
5. Agregar `_install_fake_notifier` en `tests/test_cli.py` y los tests de los cinco exit codes.

## Testing Strategy

- `tests/test_cli.py`: doble de notifier controlable (éxito/fallo/lanza) y los cinco códigos: 0 con correo OK, 1 con corrida OK + SMTP caído, 3 con mezcla, 4 con fallo total, 2 con config inválida (ya existente). Verificación de la línea impresa y de enmascarado con un secreto inyectado en `error_message`.
- `tests/test_pipeline.py`: el exit code no se prueba acá (es de la CLI), pero el `notification` que lo alimenta sí (Item 043).
- Gates: `uv run pytest`, `uv run ruff check`, `uv run mypy`.

## Dependencies

- Item 043 (`PipelineResult.notification`).

## Decisions & Trade-offs

- **Precedencia explícita en `_cmd_run`**: `4` (lote no ejecutado/vacío/fallo total) > `1` (correo fallido con lote exitoso) > `0`; `3` se mantiene con mezcla aunque el correo falle, porque el informe sí salió y la degradación a `1` solo está prevista para corridas "por lo demás exitosas". La decisión queda en el docstring del módulo, el de `_cmd_run` y el README.
- **`notification is None` cuenta como correo no enviado**: una corrida con todas las fases OK pero sin resultado de notificación devuelve `1`, no `0`; el pipeline real siempre lo llena, así que el caso solo es alcanzable por construcciones manuales y prevalece la postura conservadora ("0 exige correo enviado").
- **Línea de correo por stdout/stderr**: éxito por stdout ("Correo enviado a X (0.0 s).") y fallo por stderr ("Correo NO enviado: motivo"), coherente con el resto de los resúmenes; ambas pasan por `MaskFn` (el motivo puede contener credenciales SMTP).
- **Registro en el log con el desenlace**: `logger.info`/`logger.error` de la notificación se suman a los de respaldo y transferencia; el `MaskingFilter` garantiza que el archivo rotado no conserve el secreto (verificado con `masterkey` inyectada en el `error_message` del doble).
- **`--help` y README como contrato del usuario**: la matriz completa (0/1/3/4) queda en el `description` de `run` y en la tabla de exit codes, incluida la precedencia del 4 y la neutralidad del 3 ante fallo de correo.

**Evidencia:** `uv run pytest tests/test_cli.py -q` → 49 passed (6 tests nuevos: línea de éxito, SMTP caído en corrida exitosa → 1, parcial con correo caído → 3, total con correo caído → 4, enmascarado del motivo con `masterkey` → `***` en stderr y en `odin.log`, y `--help` mencionando el correo); `uv run ruff check src/odin tests` → All checks passed; `uv run mypy src/odin` → Success; `uv run pytest tests/test_cli.py tests/test_pipeline.py tests/test_notify.py tests/test_config.py -q` → 127 passed.

## Prerequisites

- `docs/aide/progress.md` debe ser actualizado a 🚧 al iniciar.
- Al finalizar, actualizar `docs/aide/progress.md` a ✅.

# Item 038: Verificación de seguridad y enmascarado en la transferencia

## Description

Garantizar que ningún secreto de los servidores (contraseñas, rutas de claves privadas, passphrases) aparezca en los logs de transferencia ni en el reporte de salida de `odin run`, validando que el enmascarado de la Etapa 1 (`SecretMasker`/`MaskingFilter`) cubre los nuevos campos de la Etapa 4 en todos los destinos: log de archivo, consola y el resumen impreso del pipeline (que no pasa por el logger).

## Acceptance Criteria

- [ ] El resumen de `odin run` (stdout/stderr) pasa por el `SecretMasker` de la configuración: ningún secreto de servidores ni de compresión aparece aunque un mensaje de error lo contenga (p. ej. excepción con la ruta de la clave privada o la passphrase).
- [ ] Tests automatizados que demuestran el enmascarado: log de archivo (con `setup_logging` real) y salida de la CLI (con dobles de ejecutores que inyectan secretos en mensajes de error).
- [ ] Los campos de servidores (`auth.password`, `auth.private_key`, `auth.passphrase`) siguen cubiertos por `Config.iter_secret_fields` (ya lo están; verificar con test si falta).
- [ ] Suite completa verde: `uv run pytest`, `uv run ruff check`, `uv run mypy`.

## Implementation Steps

1. Verificar dónde se imprime el reporte de `odin run` sin enmascarar: los `print` de `_cmd_run`/helpers del resumen (backup/compresión y el nuevo de transferencia del Item 036) van directos a stdout/stderr y los `error_message` pueden contener secretos indirectos (p. ej. la ruta de la clave privada dentro de un `OSError` de `RSAKey.from_private_key_file`).
2. Aplicar el masker a todas las líneas impresas del resumen de `odin run`: construir `SecretMasker.from_config(config)` en `_cmd_run` y enmascarar cada línea (stdout y stderr) antes de imprimirla.
3. Confirmar que los logs ya están cubiertos: `transfer.py` usa el logger `odin`, cuyos handlers aplican `MaskingFilter`; los mensajes con `exc` interpolado quedan enmascarados en consola y archivo.
4. Tests en `tests/test_transfer_masking.py` (o ampliando `tests/test_log.py`/`tests/test_cli.py`):
   - `setup_logging` real con una config con secretos de servidor → ejecutar un lote de transferencia con dobles que fallen con mensajes que contienen cada secreto → leer `odin.log` y verificar que los secretos no aparecen (y que `***` sí).
   - CLI con ejecutores doblados que devuelven `error_message` conteniendo la passphrase y la ruta de clave → capturar stdout/stderr y verificar ausencia de secretos.
   - Test de que `iter_secret_fields` sigue incluyendo `servers[].auth.{password,private_key,passphrase}`.
5. Documentar en Decisions & Trade-offs el alcance: el reporte de `odin validate` (diagnóstico de configuración) no se enmascara porque su propósito es mostrar los problemas del propio JSON del usuario (incluida la ruta de clave), y es salida local del operador, no log ni correo.

## Testing Strategy

- Los tests de enmascarado usan configs reales en `tmp_path` (patrón de `tests/test_log.py`/`tests/test_cli.py`), con secretos distintivos de longitud ≥ 4 (p. ej. `sup3r-secret-passphrase`) para evitar falsos negativos del `MIN_SECRET_LENGTH`.
- Verificación por ausencia: `assert secret not in salida` sobre el contenido completo del log y de la salida capturada.
- Suite completa: `uv run pytest`, `uv run ruff check`, `uv run mypy`.

## Dependencies

- Item 036 (resumen de transferencia), `src/odin/log.py` (Item 004), `src/odin/config.py` (Item 002).

## Decisions & Trade-offs

- **Dos barreras, dos alcances**: los **logs** ya estaban cubiertos por `MaskingFilter` en los handlers del logger `odin` (todo mensaje —incluidos `exc` interpolados— se enmascara en consola y archivo). El hueco real era el **reporte impreso** de `odin run`: `_print_backup_summary`/`_print_transfer_summary` imprimen `error_message` crudos por stdout/stderr sin pasar por el logger, y una excepción puede contener la ruta de la clave privada (p. ej. `RSAKey.from_private_key_file` falla con el `OSError` que incluye la ruta, que es secreto registrado). Solución: `_cmd_run` construye `SecretMasker.from_config(config)` y pasa `mask=masker.mask` a ambos printers; cada línea impresa se enmascara.
- **`MaskFn`** (`Callable[[str], str]`) con default identidad: los printers siguen siendo testeables sin máscara; el enmascarado es explícito y centralizado en `_cmd_run`.
- **Alcance del reporte de `odin validate`**: no se enmascara a propósito. Su función es diagnosticar el JSON del operador (incluida la ruta de la clave privada con permiso incorrecto); es salida local e interactiva del dueño de la configuración, no un log persistente ni un correo. El **log** de `validate` sí queda enmascarado (pasa por el logger con filtro).
- **Verificación por ausencia + presencia de `***`**: los tests inyectan secretos distintivos (longitud ≥ 4) dentro de mensajes de error de transferencia y verifican que no aparezcan en stdout+stderr (CLI) ni en el `odin.log` real (con `setup_logging` verdadero), y que `***` sí esté — el patrón de la Etapa 1, ahora sobre los campos de servidores de la Etapa 4.
- **`iter_secret_fields` ya cubría** `servers[].auth.{password,private_key,passphrase}` desde el Item 004; se agregó el test `test_masker_covers_server_auth_fields` para fijarlo explícitamente (defensa contra regresiones de parseo).

**Evidencia:** `uv run pytest -q` → 326 passed, 1 skipped (3 tests nuevos en `tests/test_transfer_masking.py`); `uv run ruff check src/odin tests` → All checks passed; `uv run mypy src/odin` → Success.

## Prerequisites

- `docs/aide/progress.md` debe ser actualizado a 📋 al iniciar.
- Al finalizar, actualizar `docs/aide/progress.md` a ✅.

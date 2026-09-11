# Work Item 016: Configuración de parámetros de `gbak` (charset, user, password)

## Description
Enhance the backup process by passing additional `gbak` parameters (such as `charset`, `role`, `user`, and `password`) from the JSON configuration to the `gbak` command execution. Ensure that sensitive credentials are handled securely and are not exposed in the logs.

## Acceptance Criteria
- [x] `DatabaseConfig` in `src/odin/config.py` includes `charset`, `role`, `user`, and `password` (ya presentes en el modelo; cableados a la ejecución salvo `charset`, ver decisiones).
- [x] The `BackupExecutor.run_backup` method is updated to accept and use these parameters.
- [x] The `gbak` command is constructed with the provided parameters (nombres completos de switch: `-user user -password password -role role`; `charset` no aplica, ver decisiones).
- [x] Sensitive parameters (like `password`) are **never** logged in plain text.
- [x] The implementation handles cases where some parameters are missing (uses defaults or omits the flag).

## Implementation Steps
1. [x] Verify `DatabaseConfig` model in `src/odin/config.py` correctly parses `charset`, `role`, `user`, and `password`.
2. [x] Update `BackupExecutor.run_backup` to use the parameters from the `DatabaseConfig` object.
3. [x] Update the `gbak` command list construction logic to include the correct switches based on available values.
4. [x] Implement logic to mask or omit the password from the command logging.
5. [x] Add unit tests to verify the command construction for various parameter combinations.

## Testing Strategy
- **Unit Tests**:
    - Test `run_backup` with only minimal parameters (verify command is correct).
    - Test `run_backup` with all parameters present (verify `-user`, `-password`, `-role` are added).
    - Test `run_backup` con `charset` configurado (verifica que **no** se agregue un switch de charset).
    - **Security Test**: Verify that the `password` is NOT present in the `logger.info` output.

## Dependencies
- `src/odin/backup.py`
- `src/odin/config.py`

## Decisions & Trade-offs
- **Corrección de switches de `gbak`**: la primera implementación usó `-U`, `-P`, `-R`, `-E`
  (el ejemplo del enunciado estaba equivocado). Con `gbak -?` real (Firebird 5.0.4)
  se comprobó que `-U` no es válido (`-USER` exige nombre completo porque `-u`
  choca con `-use_all_space`), `-P` es `-page_size`, `-R` es `-recreate_database`
  y `-E` es `-expand` (flag sin valor). Contra el binario real el comando fallaba
  con `gbak: ERROR:found unknown switch` y exit 4 (evidencia "en rojo" antes del
  fix). Se usan los nombres completos `-user`, `-password`, `-role`, válidos en
  Firebird 2.5–6 (las abreviaturas `-u`/`-p`/`-r` son ambiguas).
- **`charset` no se pasa a `gbak`**: `gbak` no tiene switch de charset
  (confirmado en `gbak -?` y en la documentación oficial de FB 2.5–5). El
  respaldo es transportable y no depende del charset de conexión, por lo que
  `DatabaseConfig.charset` se conserva en el contrato y la validación, pero se
  omite del comando. Se documentó en README y `examples/README.md`.
- **Enmascarado**: la contraseña se reemplaza por `********` en la línea del
  comando (`-password`; también `-pas`/`-P` por compatibilidad) y además queda
  cubierta por `SecretMasker` (Item 004) en los handlers de logging.
- **Verificación real**: `odin run` contra Firebird 5.0.4 con `SYSDBA`/
  `masterkey` genera el `.fbk`; restaurado a una base scratch, conserva las 3
  filas de la tabla de prueba (integridad del respaldo).

## Testing Prerequisites

**Required Services**
- N/A (Using mocks)

**Environment Configuration**
- N/A

**Manual Validation Checklist**
- [x] Build succeeds — `uv run mypy` sin hallazgos; ruff limpio.
- [x] Tests pass — `tests/test_backup.py` (16) y `tests/test_cli.py` (34) verdes.
- [x] **Application runs**: `odin run` con user/password/role reales contra Firebird 5.0.4 → exit 0 y `.fbk` de 1536 bytes; restore scratch con `gbak -c` + `SELECT COUNT(*)` = 3 filas.
- [x] **Logs verified**: línea del comando con `-password ********` y sin secretos en el archivo de log.

**Expected Outcomes**
- The `gbak` command contains the correct flags for any provided parameters.
- Passwords do not appear in the application logs.

## Validation Results
- [ ] Service started: N/A
- [x] Application started successfully — `odin run` contra Firebird 5.0.4 (Docker) con `SYSDBA`/`masterkey`.
- [ ] Database tables verified: N/A
- [x] Seed data verified — 3 filas de `clientes` íntegras tras el restore scratch del `.fbk`.
- [ ] API endpoints verified: N/A
- [ ] Screenshots captured: N/A

## Completion Reminder
`docs/aide/progress.md` MUST be updated (📋 → 🚧 → ✅) when the item is completed.

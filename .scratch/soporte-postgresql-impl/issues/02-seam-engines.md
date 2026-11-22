# 02: Seam de engines (extracción sin cambio de comportamiento)

**What to build:** la ejecución de respaldos se reorganiza detrás de un protocolo de motor con **cero cambio de comportamiento**: `odin run` para Firebird se comporta exactamente como hoy (mismo comando, mismos artefactos, mismos mensajes y exit codes). Es el prefactor que deja el engine PostgreSQL como una adición pequeña, no como una cirugía del código existente.

Especificación: `docs/postgresql.md` §5.1 (protocolo) y §5.2 (excepciones neutras). Detalle y reversiones en `.scratch/soporte-postgresql/issues/03-costura-engines-y-tests.md`.

**Blocked by:** 01 — configuración de dos motores + validate (los fixtures y el config ya portan `type`).

**Status:** resolved

- [x] Paquete de engines con la clase base `Engine` (`binary_name`, `extension`, `secret_flags`, `error_patterns`, `env(database)`, `build_command(binary, database, target)`, `not_found_message()`, `resolve_binary(db_config)`) y el motor Firebird cubriendo exactamente el comportamiento actual.
- [x] Excepciones neutras `EngineNotFoundError` / `EngineExecutionError`; el detalle (nombre del binario + hint) lo aporta el motor. Solo `odin.backup` y sus tests las referencian.
- [x] El ejecutor de respaldos consume el protocolo sin dispatcher por tipo todavía: una sola vía, la de Firebird, sin duplicación de lógica.
- [x] `odin run` Firebird idéntico al actual: comando gbak, artefacto `<nombre>_<timestamp>.fbk`, validación post-respaldo, timeout, enmascarado de secretos, hints de binario no encontrado, exit codes.
- [x] Suite completa en verde; sin comportamiento nuevo visible para el usuario.

## Answer

Implementado con TDD (red→green→refactor). Commits en `impl/02-seam-engines`.

**Commits:** `<hash-tests>` (tests del protocolo, rojos) → `<hash-engines>` (paquete `odin/engines/` + refactor de `backup.py` + ajuste mínimo de patches en `test_backup.py`).

**Qué se construyó:**

- `src/odin/engines/__init__.py`: clase base `Engine` con el protocolo de §5.1 (`binary_name`, `extension`, `secret_flags`, `error_patterns`, `env(database)`, `build_command(binary, database, target, db_config)`, `not_found_message()`) y `resolve_binary(db_config)` genérico con la precedencia de §3.7 (binario de la base > del ejecutor > auto-detección, con cache de la detección en la instancia) delegando en dos hooks por motor (`_configured_binary`, `_find_binary`). Excepciones neutras: `EngineError` (base), `EngineNotFoundError`, `EngineExecutionError(binary_name, returncode, stdout, stderr)` — el mensaje se arma con el nombre del binario que aporta el motor.
- `src/odin/engines/firebird.py`: `FirebirdEngine` que replica exactamente el comportamiento histórico: `gbak`, `.fbk`, `secret_flags ("-password", "-pas", "-P")`, los 4 patrones de error actuales, `env` vacío (`{}`), comando `gbak -b` + `-user/-password/-role` (charset no se pasa), hint `"no se encontró el binario gbak; instale Firebird o indique databases[].gbak_path en la configuración"`, `_configured_binary` → `db_config.gbak_path`, `_find_binary` → `gbak_finder.find_gbak`. Sin `postgresql.py` (lo agrega el 03 sobre este protocolo).
- `src/odin/backup.py`: reescrito para consumir el protocolo, **sin dispatcher por tipo** (una sola vía, la Firebird). Constructor intacto (`gbak_path`, `timeout`), `BackupResult`/`BatchBackupResult` intactos, `_masked_command(command, secret_flags)` usa los `secret_flags` del engine, `subprocess.run` pasa `env={**os.environ, **env}` solo cuando el motor declara variables (Firebird: `{}` → sin env, idéntico a hoy), `_check_completed` usa `error_patterns` del engine y lanza `EngineExecutionError`, validación del artefacto con `EngineError` y mensajes vía `binary_name` del engine (cadenas idénticas), lote secuencial con aislamiento y timeout por base iguales. `BackupError`/`GbakNotFoundError`/`GbakExecutionError` eliminados (renombrados a las neutras; verificado con grep: solo `odin/backup.py` los referenciaba, los tests asercionan por subcadenas de mensajes).
- `odin.pipeline` **sin cambios** (consume `BackupExecutor(timeout=...)` igual que antes).
- `tests/test_engines.py` (nuevo, 13 tests): protocolo Firebird, precedencia y cache de `resolve_binary`, not-found con hint, jerarquía y mensajes de las excepciones neutras.
- `tests/test_backup.py`: cambio mínimo (2 líneas): el patch del finder pasa de `odin.backup.find_gbak` a `odin.engines.firebird.find_gbak` (el import ahora vive en el engine). No cambia qué verifica.

**Desvíos explícitos (documentados):**

- `build_command` recibe `db_config` además de `(binary, database, target)`: la tabla de §5.1 omite el parámetro por brevedad, pero el comando Firebird necesita los parámetros de conexión.
- `env` del protocolo acepta `DatabaseConfig | None` porque `run_backup` puede correr sin `db_config` (test del comando mínimo); los motores ignoran el argumento hoy.

**Riesgos GitNexus (impact upstream, desde el checkout principal):** `BackupExecutor` MEDIUM (importado por `pipeline`/`cli`/`compress`/`notify`; interfaz pública `run_batch_backup` + `BackupResult` sin cambios), `BackupError` MEDIUM, `_masked_command` y `find_gbak` LOW. Esperable en un prefactor; mitigado con la suite espejo `test_backup.py` intacta (solo cambió el target del patch del finder) y `tests/test_engines.py` nuevo. Ningún HIGH/CRITICAL; sin `UNKNOWN`.

**Gate:** `uv run python scripts/verify.py` completo en verde (6/6: sync, pytest completo **incluyendo integración** — 120 s —, ruff, mypy, validate-linux, validate-windows). Sin cambios en `test_cli.py` (sus dobles siguen usando `__init__(gbak_path=None, timeout=None)` en `odin.pipeline.BackupExecutor`, firma intacta).

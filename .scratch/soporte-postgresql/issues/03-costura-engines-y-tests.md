# Costura de código por motor y cobertura de tests

Type: grilling
Status: resolved
Blocked by: 01

## Question

Grilling para especificar la costura de código y los tests. Punto de partida cerrado (mapa, Notes 1, 5, 6, 7, 10): módulos por motor con interfaz común, pipeline y etapas 3–5 intactas, `.sql` como extensión, `PGPASSWORD`, contenedor `postgres:18`.

Resolver con el humano:

- Forma de los módulos por motor (`odin/engines/firebird.py` y `odin/engines/postgresql.py`) y el protocolo común: resolver binario, construir comando, extensión del artefacto, patrones de error, error "binario no encontrado".
- Qué queda en `BackupExecutor` (genérico, despacha por motor) y qué se mueve a cada engine.
- Cambios mínimos en `retention.py` (regex `.fbk|.sql`), `cli.py` (ayuda y reporte), y confirmar que `pipeline.py` no cambia.
- Matriz de tests unitarios y de integración por motor.
- `validate.py`: checks estáticos por motor y coherencia de campos (los mensajes exactos salen del ticket 02).
- Matriz de tests: unitarios espejo (finder, config, backup por motor) y `PostgresContainer` espejo de `tests/firebird_container.py` + CI.
- Detalles del engine PostgreSQL que dependen de los datos del ticket 01 (comando exacto, patrones de error, finder).
- Decisión `--encoding` del dump: default (encoding de la base) vs forzar UTF8 — el trap `SQL_ASCII` (dump rotulado UTF8 con bytes crudos, sin conversión) está documentado en 01.

## Answer

Resuelto por grilling (HITL). Costura de código por motor y cobertura de tests, decisión por decisión:

**Formato del dump (revierte Notes 3 y 5 del mapa)**

- Formato **custom `-F c`** (binario, comprimido por defecto), artefacto **`.dump`**; pg_dump escribe el archivo él mismo vía `-f` (espejo del seam de gbak: sin redirect de stdout ni buffering). Verificado contra docs oficiales de pg_dump 18.7.
- Comando fijo: `pg_dump --host H --port P --username U --dbname D --format=custom --no-password --no-privileges --file <artefacto>.dump`.
- Sin `--encoding` (con formatos de archivo la conversión ocurre al restaurar): el trap `SQL_ASCII` se documenta en el restore (`docs/postgresql.md`). Sin `--no-owner` (ignorado con formatos de archivo; se documenta que se pasa a `pg_restore` al restaurar). Sin `-b` (redundante: los large objects se incluyen por defecto), sin `-v`, sin `-W` (nunca prompt interactivo: password por config → `PGPASSWORD`).

**Seam por motor**

- Paquete `odin/engines/` con `firebird.py` y `postgresql.py`; protocolo común (clase base `Engine`) con: `binary_name`, `extension` (`.fbk`/`.dump`), `secret_flags` (gbak `("-password", "-pas", "-P")`; pg_dump `()`), `error_patterns`, `env(database)` (gbak `{}`; pg_dump `{"PGPASSWORD": password}`), `build_command(binary, database, target)`, `not_found_message()`, `resolve_binary(db_config)` (precedencia base > ejecutor > finder, espejo de hoy).
- Excepciones neutras `EngineNotFoundError` / `EngineExecutionError` en `odin/engines/`; el detalle (nombre del binario + hint de instalación) lo aporta el engine. Renombrado interno: nadie captura esas excepciones fuera de `backup.py`.
- `BackupExecutor` queda genérico: dispatch por `database.type`, timeout, `subprocess.run` con env del engine, `_check_completed` (exit code ≠ 0 o patrón en stderr), validación del artefacto, lote con aislamiento, resultados. Constructor gana `pg_dump_path` junto al `gbak_path` actual; timeout por base `pg_dump_timeout_sec`.
- Finders sueltos: `odin/gbak_finder.py` intacto; `odin/pg_dump_finder.py` espejo con las rutas verificadas en 01. Busca **cualquier major ≥ 18 y gana el mayor** (soporte futuro de 19/20 sin tocar código); si solo hay ≤ 17 → `None`. Sin verificación de versión en runtime (regla documentada).

**Engine pg_dump**

- Patrones de error: lista completa verificada en 01 (8 patrones), semántica actual (`returncode != 0 or pattern in stderr.lower()`).
- Password: `PGPASSWORD` por subproceso, nunca en argv ni en logs.

**Retención**

- Regex `^.+_\d{8}_\d{6}\.(?:fbk|dump)(?:\.7z)?$`.

**CLI**

- Descripción raíz y helps generales para los motores; resúmenes por base, exit codes 0/1/2/3/4 y `pipeline.py` intactos (pipeline solo docstring).

**validate**

- `_check_pg_dump_paths` espejo de `_check_gbak_paths` (null → INFO `pg_dump_autodetect`; directorio → ERROR; inexistente → WARN; no ejecutable → WARN; OK → "existe y es ejecutable"), ambos filtrados por `type`. `_db_problems` en `config.py` espejo de `_auth_problems`, con los mensajes exactos del 02.

**Tests**

- Unitarios espejo por motor: `test_pg_dump_finder.py` (rutas, filtro ≥ 18, mayor gana, `None`); `test_config.py` (campos por motor, `type` obligatorio y enum, `_db_problems`, `local.pg_dump_timeout_sec`); `test_backup.py` (dispatch, comando exacto, `PGPASSWORD` en env nunca logueada, patrones, timeout, not-found con hint por motor); `test_retention.py` (`.dump`); `test_validate.py` (`pg_dump_path`, filtro por `type`); `test_cli.py` (helps).
- Integración: `PostgresContainer` espejo de `FirebirdContainer` (Docker directo por subprocess, `postgres:18`, `POSTGRES_PASSWORD`, readiness con `pg_isready`, `pg_dump_wrapper` vía `docker exec`); imagen única con override `ODIN_POSTGRES_IMAGE`.
- CI: job de integración PostgreSQL en ubuntu-latest contra `postgres:18`; actualizar `test_ci_workflow.py`; gate `scripts/verify.py` intacto.

**Out of scope anotado en el mapa**: extensiones de retención configurables (p. ej. `local.managed_extensions`) — trabajo posterior.

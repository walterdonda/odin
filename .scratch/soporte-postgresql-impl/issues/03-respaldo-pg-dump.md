# 03: Respaldo PostgreSQL con pg_dump 18+

**What to build:** `odin run` respalda una entrada `type: "postgresql"` con el comando exacto de pg_dump de la spec, escribe `<nombre>_<timestamp>.dump` en `work_dir` y reporta errores con la misma semántica que gbak. La contraseña viaja solo por `PGPASSWORD` en el env del subproceso —nunca en la línea de comandos ni en logs—, y sin `pg_dump_path` el binario se auto-detecta (major ≥ 18, gana el mayor). Firebird no cambia.

Especificación: `docs/postgresql.md` §2 (engine), §5.2 (ejecutor genérico) y §5.3 (finder). Datos duros de pg_dump 18 verificados en `.scratch/soporte-postgresql/issues/01-pg-dump-datos-duros.md` (rama `research/pg-dump-18`).

**Blocked by:** 02 — seam de engines (el dispatch se monta sobre el protocolo).

**Status:** resolved

- [x] Comando exacto de §2.1: `--host --port --username --dbname --format=custom --no-password --no-privileges --file <work_dir>/<name>_<YYYYMMDD_HHMMSS>.dump`; pg_dump escribe el archivo él mismo (`-f`).
- [x] `PGPASSWORD` seteada solo en el env del subproceso; el engine no declara flags de secreto (`secret_flags = ()`).
- [x] Detección de fallo: `returncode != 0` o alguno de los 8 patrones de §2.4 en stderr (lowercase); timeout con la precedencia `databases[].pg_dump_timeout_sec` > `local.pg_dump_timeout_sec`.
- [x] Validación del artefacto (existe, no vacío, legible) y lote secuencial con aislamiento de fallos por base, como hoy.
- [x] Finder espejo: rutas de §2.6 + cada entrada del `PATH`; solo majors ≥ 18, gana el mayor; solo ≤ 17 → `None` → mensaje de binario no encontrado con hint de instalación.
- [x] Precedencia de binario: `databases[].pg_dump_path` > ejecutor > finder. Dispatch por `type`; motor Firebird intacto.
- [x] Tests unitarios de §7.1: dispatch, comando exacto, `PGPASSWORD` en env y nunca en logs, patrones, timeout, not-found con hint por motor; finder cubierto en archivo propio. Suite en verde.

## Answer

Engine PostgreSQL (pg_dump 18+) montado sobre el seam del ticket 02, con dispatch por `type` en `BackupExecutor`; Firebird intacto.

**Commits**
- `engines: PostgreSQLEngine + pg_dump_finder con regla major ≥ 18 (ticket 03)` — `src/odin/engines/postgresql.py` (comando exacto de §2.1, `env` = `{"PGPASSWORD": password}`, `secret_flags = ()`, 8 patrones de §2.4, `not_found_message` con rutas típicas + `--host/--username/--dbname`, precedencia de binario por herencia del protocolo) y `src/odin/pg_dump_finder.py` (rutas §2.6 + PATH; solo majors ≥ 18, gana el mayor; solo ≤ 17 → `None`; sin verificación de versión en runtime).
- `backup+pipeline: dispatch por type, timeout pg_dump y env del engine (ticket 03)` — `src/odin/backup.py` (dispatch `_engine_for`/`_timeout_for`, constructor gana `pg_dump_path`/`pg_dump_timeout`, `_check_completed`/`_validate_backup_file` reciben el engine, `_database_target` para logs), `src/odin/pipeline.py` (una línea: pasa `local.pg_dump_timeout_sec` al ejecutor, necesario para la precedencia §3.7 "vía ejecutor" — desvío menor del "pipeline no cambia" de §5.2, documentado), docstring de `odin/engines/__init__.py`.
- `tests: espejo PostgreSQL de §7.1 + dobles que acompañan la firma (ticket 03)` — `tests/test_pg_dump_finder.py` (nuevo), `tests/test_backup.py` y `tests/test_engines.py` (ampliados), y los 3 dobles de `BackupExecutor` que `run_pipeline` construye (`test_cli.py`, `test_notify_integration.py`, `test_scheduler_foreground.py`) ganan `pg_dump_path`/`pg_dump_timeout`.

**Gate**: `uv run python scripts/verify.py` completo en verde (6/6, incluye pytest con integración: 66 tests nuevos/ampliados entre los 3 archivos tocados).

**Riesgos GitNexus** (antes de editar): `BackupExecutor` MEDIUM (importadores directos cli/compress/notify/pipeline/scheduler + tests) y `run_pipeline` CRITICAL (38 afectados, 20 procesos) — mitigación: cambios aditivos en la firma del constructor (kwargs con defaults) y una línea extra de wiring; cubierto por la suite completa. `run_backup` LOW, `FirebirdEngine` LOW (intacto).

**Desvíos explícitos**
1. `odin.pipeline` cambia una línea (pasar `local.pg_dump_timeout_sec`), contra el "solo docstring" de §5.2/§8: sin esto el campo de config quedaría muerto (§3.6-3.7 exigen la precedencia vía ejecutor). Comportamiento del pipeline intacto.
2. Los 3 dobles de `BackupExecutor` que el pipeline real construye tuvieron que acompañar la firma del constructor (práctica ya documentada en el repo para el ticket 02).
3. En `test_engines.py` agregué la sección de protocolo `PostgreSQLEngine` (no estaba en la lista explícita de §7.1, pero el espejo por motor la pide y cubre `secret_flags`/`env`/`build_command` a nivel engine).

No se agregó entrada PostgreSQL a `examples/` (llega en el 07).

# 03: Respaldo PostgreSQL con pg_dump 18+

**What to build:** `odin run` respalda una entrada `type: "postgresql"` con el comando exacto de pg_dump de la spec, escribe `<nombre>_<timestamp>.dump` en `work_dir` y reporta errores con la misma semántica que gbak. La contraseña viaja solo por `PGPASSWORD` en el env del subproceso —nunca en la línea de comandos ni en logs—, y sin `pg_dump_path` el binario se auto-detecta (major ≥ 18, gana el mayor). Firebird no cambia.

Especificación: `docs/postgresql.md` §2 (engine), §5.2 (ejecutor genérico) y §5.3 (finder). Datos duros de pg_dump 18 verificados en `.scratch/soporte-postgresql/issues/01-pg-dump-datos-duros.md` (rama `research/pg-dump-18`).

**Blocked by:** 02 — seam de engines (el dispatch se monta sobre el protocolo).

**Status:** ready-for-agent

- [ ] Comando exacto de §2.1: `--host --port --username --dbname --format=custom --no-password --no-privileges --file <work_dir>/<name>_<YYYYMMDD_HHMMSS>.dump`; pg_dump escribe el archivo él mismo (`-f`).
- [ ] `PGPASSWORD` seteada solo en el env del subproceso; el engine no declara flags de secreto (`secret_flags = ()`).
- [ ] Detección de fallo: `returncode != 0` o alguno de los 8 patrones de §2.4 en stderr (lowercase); timeout con la precedencia `databases[].pg_dump_timeout_sec` > `local.pg_dump_timeout_sec`.
- [ ] Validación del artefacto (existe, no vacío, legible) y lote secuencial con aislamiento de fallos por base, como hoy.
- [ ] Finder espejo: rutas de §2.6 + cada entrada del `PATH`; solo majors ≥ 18, gana el mayor; solo ≤ 17 → `None` → mensaje de binario no encontrado con hint de instalación.
- [ ] Precedencia de binario: `databases[].pg_dump_path` > ejecutor > finder. Dispatch por `type`; motor Firebird intacto.
- [ ] Tests unitarios de §7.1: dispatch, comando exacto, `PGPASSWORD` en env y nunca en logs, patrones, timeout, not-found con hint por motor; finder cubierto en archivo propio. Suite en verde.

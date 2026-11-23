# Soporte PostgreSQL (18+) en ODIN — implementación

## Destination

Implementar la especificación aprobada `docs/postgresql.md` (mapa wayfinder
`soporte-postgresql`, resuelto) como soporte PostgreSQL 18.0+ en ODIN, con un
ticket por paso y el gate `scripts/verify.py` en verde por paso. La spec y el
plan en 12 pasos viven en `docs/postgresql.md`; las reversiones de decisiones y
los datos duros están en `.scratch/soporte-postgresql/issues/` (tickets 01–04
del mapa, `resolved`).

## Notes

- **Idioma**: español (repo, tickets y respuestas).
- **Tickets**: `.scratch/soporte-postgresql-impl/issues/` (numerados desde 01;
  el frontier es el ticket con `Status: ready-for-agent`, sin resolver y con
  todos sus `Blocked by:` resueltos, de menor número).
- **Cómo se cierra trabajo** (convención del tracker local, ver
  `docs/agents/issue-tracker.md`): cada implementador marca los checkboxes de
  su ticket, agrega una sección `## Answer` con el gist (commits + tests), deja
  `Status: resolved`, y agrega acá una línea en Decisions so far.
- **Ramas**: integración `integration/soporte-postgresql`; cada ticket en
  worktree propio con rama `impl/<NN>-<slug>` basada en la de integración.
- **GitNexus** (reglas de `AGENTS.md`): `impact` antes de editar símbolos;
  `detect_changes` antes de commitear; `UNKNOWN` no es all-clear.
- **Gate por ticket**: `uv run python scripts/verify.py` (con `--quick` se
  omiten los tests marcados `@integration`).

## Decisions so far

<!-- una línea por ticket resuelto: título con link y gist; el detalle vive en el ticket -->
- [01: Configuración de dos motores + validate](issues/01-configuracion-dos-motores.md) — `type` obligatorio por entrada de `databases[]` (enum `DbEngine`), campos PostgreSQL con `_db_problems` (mensajes exactos §3.5), `_check_pg_dump_paths` en validate con filtro por `type`, `local.pg_dump_timeout_sec`; fixtures/ejemplos ganan `"type": "firebird"`. Gate completo en verde (pytest 676 passed; quick 5/5).
- [02: Seam de engines](issues/02-seam-engines.md) — paquete `odin/engines/` con protocolo `Engine` (§5.1) y `FirebirdEngine` replicando exactamente el comportamiento actual (gbak, `.fbk`, 4 patrones, secret_flags, env `{}`, hint); excepciones neutras `EngineNotFoundError`/`EngineExecutionError` (renombrado verificado con grep: solo `odin.backup` las referenciaba); `BackupExecutor` consume el protocolo sin dispatcher por tipo (una vía, la Firebird), constructor y resultados intactos; `odin.pipeline` sin cambios. Gate completo en verde (6/6 con integración).
- [03: Respaldo PostgreSQL con pg_dump 18+](issues/03-respaldo-pg-dump.md) — `PostgreSQLEngine` (§2: comando exacto §2.1 con `--format=custom --no-password --no-privileges --file`, `PGPASSWORD` solo en env del subproceso, 8 patrones §2.4, hint con rutas típicas) + `pg_dump_finder` espejo (rutas §2.6 + PATH, majors ≥ 18 gana el mayor, ≤ 17 → `None`, sin verificación de versión en runtime); dispatch por `type` en `BackupExecutor` con `pg_dump_path`/`pg_dump_timeout` por base; desvío documentado: una línea en `odin.pipeline` para que `local.pg_dump_timeout_sec` llegue al ejecutor (§3.7) y los 3 dobles de `BackupExecutor` que el pipeline construye acompañan la firma. Gate completo en verde (6/6 con integración; finder con archivo propio de tests).
- [04: Retención `.dump` y CLI genérica](issues/04-retencion-cli-generica.md) — regex única de retención `^.+_\d{8}_\d{6}\.(?:fbk|dump)(?:\.7z)?$` (semántica intacta: cutoff estricto, `run_started_at`, no-symlink, aislamiento, idempotencia); CLI describe ambos motores (descripción raíz, help/description de `run`, docstrings) y los resúmenes por base ya eran genéricos (rutas por resultado según `type`; solo docstring de `_print_backup_summary`); `odin.pipeline` sin cambios y exit codes 0/1/2/3/4 intactos. Gate completo en verde (6/6).
- [05: Integración real contra postgres:18](issues/05-integracion-postgres-18.md) — `tests/postgres_container.py` (`PostgresContainer` espejo del helper Firebird: Docker por subprocess, `postgres:18` con override `ODIN_POSTGRES_IMAGE`, `POSTGRES_PASSWORD`, readiness TCP con `pg_isready`, `pg_dump_wrapper` vía `docker exec` con `PGPASSWORD` reenviada) + `tests/test_backup_integration_postgres.py` (flujo real de `odin run` contra el contenedor; verifica `.dump` y `.dump.7z` existentes y no vacíos y major de pg_dump ≥ 18; skip en dos niveles como Firebird, marker `integration`); sin cambios en los tests Firebird existentes. Gate completo en verde (6/6), el test corre verde contra `postgres:18` real.
- [06: CI con job de integración PostgreSQL](issues/06-ci-postgresql.md) — `.github/workflows/ci.yml` gana el job `postgresql` (`ubuntu-latest`) junto al job `linux`, con `postgres:18` como servicio (env `POSTGRES_PASSWORD` con valor de prueba fijo y health check `pg_isready` en `options`); el job corre la suite de integración del ticket 05 (`uv run pytest tests/test_backup_integration_postgres.py -q`) con el andamiaje uv de los otros jobs y sin build ni artefacto; jobs `linux`/`windows` sin tocar. `tests/test_ci_workflow.py` suma 2 tests que fijan ese contrato (servicio `postgres:18` + pg_isready, uv con caché, comando de la suite, sin `upload-artifact`; módulo de la suite marcado `integration` con skip). `scripts/verify.py` intacto; gate completo en verde (6/6, pytest 136 s) y la integración corre verde contra `postgres:18` real.
- [07: Docs, ejemplos y publicación 1.1.0](issues/07-docs-ejemplos-publicacion.md) — docs presentan el contrato de dos motores como vigente: `docs/configuration.md` sin las notas de "especificación aprobada, implementación pendiente" (encabezado, §3, §7, §9, §10–§11), `docs/postgresql.md` declara la spec implementada, README sin el estado "planificado" (descripción, requisitos, resumen de campos, flujo de `odin run` y retención de ambos motores) y CHANGELOG con la release 1.1.0 (F9 + correcciones y docs movidas de Unreleased). `examples/config.{linux,windows}.json` suman la entrada PostgreSQL de §4 (`ventas_pg`, auto-detección vía `null`) con el job cubriendo ambas bases; test nuevo `test_examples_postgresql_entry_matches_contract` (rojo→verde). Paquete 1.1.0 (`pyproject.toml`, `__version__`, `uv.lock`; descripción y keywords de dos motores). Gate completo en verde (6/6, pytest 148 s) con validate-linux/validate-windows sobre los ejemplos con la entrada PostgreSQL.

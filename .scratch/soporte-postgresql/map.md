# Soporte PostgreSQL (18+) en ODIN

## Destination

Especificación aprobada y plan de implementación para incorporar **PostgreSQL 18.0+** como segundo motor de ODIN, reutilizando el pipeline existente (compresión 7z, transferencia SFTP, correo, retención y scheduler) y preservando intacta la compatibilidad de las configuraciones Firebird actuales. El mapa termina cuando la especificación y el plan están redactados y aprobados; el código en sí es el handoff posterior al mapa.

## Notes

- **Idioma**: español (repo, tickets y respuestas).
- **Skills por sesión**: `grilling` + `domain-modeling` en tickets HITL; `research` en el ticket 01; `prototype` si un sketch ayuda a reaccionar.
- **GitNexus**: el repo está indexado; antes de editar código correr impacto/detect-changes. En este mapa solo se edita `.scratch/` y una rama throwaway de research.
- **Entregable en el mapa**: la spec + plan se redactan y aprueban dentro del mapa (ticket 04); es la única ejecución que el mapa transporta.
- **Tickets**: `.scratch/soporte-postgresql/issues/` (numerados desde 01; el frontier es el ticket abierto, desbloqueado y sin reclamar de menor número).
- **Decisiones cerradas en el charting** (contexto que todos los tickets asumen):
  1. Motor por base en la misma configuración y pipeline (`type` por entrada, default `firebird`); compatibilidad retroactiva total de las configs actuales.
  2. Respaldo lógico por base con `pg_dump`; sin `pg_dumpall` ni PITR; restore fuera de alcance.
  3. Formato plain SQL con `--no-owner --no-privileges`.
  4. Campos con nombre de motor; PostgreSQL usa `host`/`port` (default 5432)/`dbname` reutilizando `name`/`user`/`password`.
  5. Artefacto `.sql` (→ `.sql.7z`); la retención acepta `.fbk` y `.sql`.
  6. `pg_dump_finder.py` espejo del finder actual; sin verificación de versión en runtime (regla documentada).
  7. Contraseña vía `PGPASSWORD` por subproceso (nunca en la CLI ni en logs).
  8. `odin validate`: checks estáticos espejo de los actuales, sin conexión a la base.
  9. Solo PostgreSQL **18.0+**; nada anterior.
  10. Tests: helper `PostgresContainer` espejo de `tests/firebird_container.py`, contenedor `postgres:18` en CI, gate `scripts/verify.py` intacto.

## Decisions so far

<!-- una línea por ticket cerrado: título con link y gist; el detalle vive en el ticket -->

- [Datos duros de pg_dump para PostgreSQL 18](issues/01-pg-dump-datos-duros.md): flags, exit codes, patrones de error, semántica de `PGPASSWORD` y rutas de pg_dump 18 verificados contra docs oficiales; notas en rama `research/pg-dump-18`; decisión nueva `--encoding` (UTF8 vs default, trap `SQL_ASCII`) derivada al 03.

## Not yet specified

<!-- niebla en alcance que aún no es ticket: se gradúa cuando el frontier avanza -->

- Campos/defaults/mensajes de validación exactos de `databases[]` y `local` → ticket 02.
- Semántica y default de `local.pg_dump_timeout_sec` → 02.
- Matriz de tests unitarios y de integración por motor → 03.
- Redacción de `docs/postgresql.md` y actualización de `docs/configuration.md`, `README.md`, `CHANGELOG.md` → 04.
- Ejemplo JSON con ambos motores → sketch en 02, versión definitiva en 04.

## Out of scope

<!-- trabajo descartado por quedar más allá del destino; nunca se gradúa -->

- Restauración (`psql` / `pg_restore`) — decidido en el charting.
- `pg_dumpall` y objetos globales (roles, tablespaces).
- Backups físicos, PITR y WAL.
- Migración de datos Firebird → PostgreSQL.
- PostgreSQL anterior a 18.
- Motores adicionales más allá de Firebird y PostgreSQL.

# Soporte PostgreSQL (18+) en ODIN

## Destination

Especificación aprobada y plan de implementación para incorporar **PostgreSQL 18.0+** como segundo motor de ODIN, reutilizando el pipeline existente (compresión 7z, transferencia SFTP, correo, retención y scheduler), con `type` explícito y obligatorio por entrada (a las configs Firebird actuales solo les falta agregar ese campo). El mapa termina cuando la especificación y el plan están redactados y aprobados; el código en sí es el handoff posterior al mapa.

## Notes

- **Idioma**: español (repo, tickets y respuestas).
- **Skills por sesión**: `grilling` + `domain-modeling` en tickets HITL; `research` en el ticket 01; `prototype` si un sketch ayuda a reaccionar.
- **GitNexus**: el repo está indexado; antes de editar código correr impacto/detect-changes. En este mapa solo se edita `.scratch/` y una rama throwaway de research.
- **Entregable en el mapa**: la spec + plan se redactan y aprueban dentro del mapa (ticket 04); es la única ejecución que el mapa transporta.
- **Tickets**: `.scratch/soporte-postgresql/issues/` (numerados desde 01; el frontier es el ticket abierto, desbloqueado y sin reclamar — sin campo `Claim:` — de menor número).
- **Decisiones cerradas en el charting** (contexto que todos los tickets asumen):
  1. Motor por base en la misma configuración y pipeline; `type` por entrada **obligatorio y explícito** (`firebird` | `postgresql`, sin default) — decisión del ticket 02, revierte el default `firebird` del charting.
  2. Respaldo lógico por base con `pg_dump`; sin `pg_dumpall` ni PITR; restore fuera de alcance.
  3. Formato **custom** (`-F c`, comprimido por defecto) con `--no-password --no-privileges`; artefacto escrito por pg_dump vía `-f`; sin `--encoding` ni `--no-owner` (ignorados con formatos de archivo; trap `SQL_ASCII` y `pg_restore --no-owner` documentados) — decisión del ticket 03, revierte el plain SQL del charting.
  4. Campos con nombre de motor; PostgreSQL usa `host`/`port` (default 5432)/`dbname` con `name`/`user`/`password` comunes (`dbname` no defaulta a `name`, ver 02).
  5. Artefacto `.dump` (→ `.dump.7z`); la retención acepta `.fbk` y `.dump` — decisión del ticket 03, revierte el `.sql` del charting.
  6. `pg_dump_finder.py` espejo del finder actual; sin verificación de versión en runtime (regla documentada).
  7. Contraseña vía `PGPASSWORD` por subproceso (nunca en la CLI ni en logs).
  8. `odin validate`: checks estáticos espejo de los actuales, sin conexión a la base.
  9. Solo PostgreSQL **18.0+**; nada anterior.
  10. Tests: helper `PostgresContainer` espejo de `tests/firebird_container.py`, contenedor `postgres:18` en CI, gate `scripts/verify.py` intacto.

## Decisions so far

<!-- una línea por ticket cerrado: título con link y gist; el detalle vive en el ticket -->

- [Datos duros de pg_dump para PostgreSQL 18](issues/01-pg-dump-datos-duros.md): flags, exit codes, patrones de error, semántica de `PGPASSWORD` y rutas de pg_dump 18 verificados contra docs oficiales; notas en rama `research/pg-dump-18`; decisión nueva `--encoding` (UTF8 vs default, trap `SQL_ASCII`) derivada al 03.
- [Contrato de configuración con dos motores](issues/02-contrato-configuracion.md): contrato campo por campo — `type` explícito y obligatorio en ambos motores (revierte el default `firebird` del charting), `host`/`dbname` requeridos en PG, `port` default 5432, credenciales comunes obligatorias, checks condicionales espejo de `auth`, `local.pg_dump_timeout_sec` default 7200, sin campo `encoding` (→ 03), sketch JSON con ambos motores.
- [Costura de código por motor y cobertura de tests](issues/03-costura-engines-y-tests.md): seam `odin/engines/` con protocolo `Engine` y excepciones neutras, `BackupExecutor` genérico; dump custom `-Fc` a `.dump` (revierte Notes 3 y 5; encoding/SQL_ASCII documentados en el restore); finder ≥ 18 mayor gana; retención `fbk|dump`; helps generales; `_check_pg_dump_paths` + `_db_problems`; tests espejo; `PostgresContainer` `postgres:18` + job de integración en CI.

## Not yet specified

<!-- niebla en alcance que aún no es ticket: se gradúa cuando el frontier avanza -->

## Out of scope

<!-- trabajo descartado por quedar más allá del destino; nunca se gradúa -->

- Restauración (`psql` / `pg_restore`) — decidido en el charting.
- `pg_dumpall` y objetos globales (roles, tablespaces).
- Backups físicos, PITR y WAL.
- Migración de datos Firebird → PostgreSQL.
- PostgreSQL anterior a 18.
- Motores adicionales más allá de Firebird y PostgreSQL.
- Extensiones de retención configurables (p. ej. `local.managed_extensions`): sugerido por Walter en el ticket 03; trabajo posterior, más allá del destino de este mapa.

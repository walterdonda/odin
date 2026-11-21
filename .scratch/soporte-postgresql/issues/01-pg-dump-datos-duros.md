# Datos duros de pg_dump para PostgreSQL 18

Type: research
Status: resolved

## Question

Investigar, con fuentes primarias (documentación oficial de PostgreSQL en postgresql.org), los hechos exactos de `pg_dump` de la serie 18 que la especificación necesita para el módulo del motor y el finder. Decisiones cerradas que enmarcan la búsqueda (mapa, Notes): dump plain SQL portable con `--no-owner --no-privileges`, contraseña por `PGPASSWORD`, solo PostgreSQL 18.0+.

1. Invocación exacta para un dump plain-SQL portable: flags de conexión (`--host`, `--port`, `--username`, `--dbname`), formato por defecto, y qué hace `--encoding` (¿conviene fijarlo a UTF8 o respetar el encoding de la base?).
2. Exit codes de `pg_dump` (éxito/error) y a qué stream escribe los errores.
3. Texto exacto de los errores típicos de conexión/autenticación (insumo del equivalente de `_ERROR_PATTERNS` de `odin/backup.py`).
4. Semántica de `PGPASSWORD`: vacía vs no seteada, interacción con `.pgpass`, flag `--no-password`, comportamiento en Windows.
5. Rutas de instalación típicas de `pg_dump` 18 en Windows y Linux (insumo del finder espejo).
6. Regla oficial de compatibilidad pg_dump↔servidor (¿a qué mayores de servidor puede apuntar un pg_dump 18?).
7. Cambios de `pg_dump` en la serie 18 relevantes para un dump plain portable.
8. Estado de la serie 18 hoy (última menor publicada, estado de soporte).

Capturar los hallazgos en la rama throwaway `research/pg-dump-18` (push, sin PR; nunca se mergea) y reportar la ruta del archivo de notas para dejar acá el puntero de contexto.

## Answer

Resuelto por sub-agente de research. Notas completas con citas (docs oficiales 18.7, release notes, código REL_18_STABLE) en la rama throwaway `research/pg-dump-18`, commit `1deec39`, archivo `docs/pg-dump-18-datos-duros.md` (`git show research/pg-dump-18:docs/pg-dump-18-datos-duros.md`). Push pendiente de credenciales SSH (ver nota operativa abajo).

Hechos que fijan las decisiones:

1. **Invocación**: `pg_dump [connection-option...] [option...] [dbname]`; `-h/--host`, `-p/--port` (default 5432/`PGPORT`), `-U/--username`, `-d/--dbname`; formato por defecto **plain** (`-F p`). `--no-owner` y `--no-privileges` confirmados. `--encoding`: por defecto el dump sale en el encoding de la base; forzando UTF8 se convierte en cliente, salvo `SQL_ASCII` donde **no hay conversión** (dump rotulado UTF8 con bytes crudos — trap documentado). La decisión UTF8-vs-default se agrega al ticket 03.
2. **Exit codes/streams**: 0 = éxito, 1 = error (sin otros). Dump → stdout; errores/warnings → stderr con prefijo `pg_dump: error:`.
3. **Patrones de error** (insumo de `_ERROR_PATTERNS`): `password authentication failed for user "%s"`, `fe_sendauth: no password supplied`, `no pg_hba.conf entry for host ...`, `connection to server at "%s" (%s), port %s failed: `, `connection to server on socket "%s" failed: `, `could not translate host name`, `timeout expired`, `aborting because of server version mismatch`. (`could not connect to server` no existe en libpq 18.)
4. **PGPASSWORD**: vacía ≡ no seteada (ambas caen a `.pgpass` y luego a `fe_sendauth`); precedencia connstring `password=` > `PGPASSWORD` > `~/.pgpass` > prompt; `-w/--no-password` desactiva **solo** el prompt (flag correcto para batch); Windows sin semántica especial.
5. **Rutas**: Windows `C:\Program Files\PostgreSQL\18\bin\pg_dump.exe`; Debian/Ubuntu `/usr/lib/postgresql/18/bin/pg_dump` + wrapper `/usr/bin/pg_dump`; PGDG yum `/usr/pgsql-18/bin/pg_dump`; Fedora `/usr/bin/pg_dump`; source `/usr/local/pgsql/bin`.
6. **Compatibilidad**: pg_dump 18 vuelca servidores 9.2→18.x; rechaza 19+ con exit 1; el output carga en servers ≥ 18.
7. **Serie 18**: 18.0 agrega `--statistics`, `--sequence-data`, `--statistics-only/--no-data/--no-schema`, `--no-policies`; fixes de validez de dump en 18.1/18.2/18.4/18.6/18.7; nada cambia el formato plain.
8. **Estado**: última menor **18.7** (2026-11-12); 18.5 nunca se publicó; soportada hasta finales de 2030; 19.0 publicada el 2026-11-19 (fuera del alcance: el mapa cubre solo 18.0+).

Nota operativa: el push de la rama quedó pendiente (SSH sin agente, clave con passphrase, sin token/`gh`). El commit local conserva las notas; para publicarla: `git push -u origin research/pg-dump-18`.

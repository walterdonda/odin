# 05: Integración real contra `postgres:18`

**What to build:** una prueba de integración end-to-end que levanta un contenedor `postgres:18` real con Docker, corre el flujo de respaldo de ODIN contra él y demuestra el artefacto: el `.dump` de pg_dump 18 y su `.dump.7z` existen y no están vacíos. Sin Docker la prueba se salta de forma segura, igual que la de Firebird.

Especificación: `docs/postgresql.md` §7.2 (matriz de tests de integración).

**Blocked by:** 03 — respaldo pg_dump (el flujo real que se ejercita).

**Status:** resolved

- [x] Helper `PostgresContainer` espejo del de Firebird: Docker directo por subprocess, imagen `postgres:18`, `POSTGRES_PASSWORD`, readiness con `pg_isready`, ejecución de pg_dump vía `docker exec`, override de imagen única con `ODIN_POSTGRES_IMAGE`.
- [x] Test de integración que corre el flujo real de `odin run` contra el contenedor y verifica que el `.dump` y el `.dump.7z` resultantes existen y no están vacíos.
- [x] Skip seguro cuando no hay Docker (mismo patrón de skip que el de Firebird), marcado con el marker de integración para que el gate `--quick` lo omita.
- [x] Suite completa en verde; sin cambios en los tests de integración Firebird existentes.

## Answer

Integración end-to-end contra `postgres:18` real: helper `PostgresContainer` espejo de `tests/firebird_container.py` (mismo estilo, manejo de errores y detección de Docker) y test que corre el flujo real de `odin run` (CLI in-process, respaldo + compresión + correo real vía `SmtpCatcher` local) contra el contenedor.

**Commits**
- `tests: integración end-to-end PostgreSQL 18 contra postgres:18 real (ticket 05, rojo)` — `tests/test_backup_integration_postgres.py`: configuración generada desde el fixture Linux con una entrada `type: postgresql` apuntando al contenedor (`host 127.0.0.1`, `port 5432`, `pg_dump_path` = wrapper), `servers: []`, retención deshabilitada y SMTP del catcher local; assert de `exit_code == EXIT_OK`, resumen `1/1 base(s) con éxito`, exactamente un `.dump` y un `.dump.7z` no vacíos en `work_dir`, y evidencia de versión (major del `pg_dump` de la imagen ≥ 18). Marker `integration` + `skipif(DOCKER is None)` a nivel módulo y skip dinámico si el contenedor no arranca (patrón Firebird, los dos caminos verificados).
- `tests: helper PostgresContainer espejo del de Firebird, readiness TCP con pg_isready (ticket 05)` — `tests/postgres_container.py`: `PostgresContainer` con `start`/`remove`/`exec`/`wait_ready`/`port` espejo del helper Firebird, imagen `default_image()` = `postgres:18` con override `ODIN_POSTGRES_IMAGE`, `-e POSTGRES_PASSWORD`/`-e POSTGRES_DB`, `pg_dump_wrapper` (`docker exec --user root … pg_dump`, con `PGPASSWORD` reenviada al exec para conservar el seam §2.2; `.cmd` equivalente en Windows) y `pg_dump_version` como evidencia del major.
- `merge: 04 retención .dump y CLI genérica (base para 05)` — merge de la punta de integración (ticket 04), sin conflictos.
- `scratch: resuelve ticket 05 (integración postgres:18) y actualiza mapa` — checkboxes, `Status: resolved`, `## Answer` y línea en `map.md`.

**Gate**: `uv run python scripts/verify.py` completo en verde (6/6) antes y después del merge; el test nuevo corre **en verde contra `postgres:18` real** en esta máquina (imagen 18.7, artefactos `.dump` 957 bytes → `.dump.7z` 575 bytes). Sin Docker verificado en los dos niveles: CLI ausente → skip de módulo (`Docker no instalado en el host`); daemon caído → skip dinámico en `start()` (simulado con `DOCKER_HOST` a un socket inexistente).

**Riesgos GitNexus**: solo archivos de tests nuevos; ningún símbolo de `src/odin` editado. `impact` sobre `FirebirdContainer` (símbolo espejado): `UNKNOWN` sin callers resueltos — confirmado con búsqueda de texto (usado por `test_backup_integration.py`, `test_notify_integration.py`, `test_firebird_matrix.py`, `test_packaging_integration.py`), no lo modifiqué: espejo simple en archivo nuevo.

**Desvíos explícitos**
1. Espejo simple, sin extracción de utilidades compartidas del helper Firebird: extraer una base común tocaría `tests/firebird_container.py` y arriesgaría el comportamiento de los tests Firebird existentes, que el ticket prohíbe cambiar. La única duplicación real es el esqueleto `exec`/`start`/`remove` (~40 líneas), que se mantiene deliberadamente idéntico en forma.
2. Readiness con `pg_isready` por **TCP `127.0.0.1:5432`**, no por socket: durante la inicialización el entrypoint de la imagen levanta un servidor temporal que escucha solo el socket (`listen_addresses=''`), y `pg_isready` por socket lo da por listo aunque el respaldo por TCP todavía reciba *Connection refused* (el test lo capturó en rojo). Documentado en el helper.
3. El test corre el flujo completo de `odin run` con el correo real hacia el `SmtpCatcher` local (patrón de `test_notify_integration.py`): sin servidores SFTP y con retención deshabilitada para que los artefactos queden en `work_dir`.
4. Evidencia extra no pedida: assert de que el major de `pg_dump --version` de la imagen es ≥ 18 (alinea con "solo PostgreSQL 18.0+", estilo `gbak_version` de la matriz Firebird).

Sin cambios en los tests de integración Firebird existentes; el job de CI para PostgreSQL queda para el ticket 06.

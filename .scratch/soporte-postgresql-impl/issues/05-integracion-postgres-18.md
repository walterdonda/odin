# 05: Integración real contra `postgres:18`

**What to build:** una prueba de integración end-to-end que levanta un contenedor `postgres:18` real con Docker, corre el flujo de respaldo de ODIN contra él y demuestra el artefacto: el `.dump` de pg_dump 18 y su `.dump.7z` existen y no están vacíos. Sin Docker la prueba se salta de forma segura, igual que la de Firebird.

Especificación: `docs/postgresql.md` §7.2 (matriz de tests de integración).

**Blocked by:** 03 — respaldo pg_dump (el flujo real que se ejercita).

**Status:** ready-for-agent

- [ ] Helper `PostgresContainer` espejo del de Firebird: Docker directo por subprocess, imagen `postgres:18`, `POSTGRES_PASSWORD`, readiness con `pg_isready`, ejecución de pg_dump vía `docker exec`, override de imagen única con `ODIN_POSTGRES_IMAGE`.
- [ ] Test de integración que corre el flujo real de `odin run` contra el contenedor y verifica que el `.dump` y el `.dump.7z` resultantes existen y no están vacíos.
- [ ] Skip seguro cuando no hay Docker (mismo patrón de skip que el de Firebird), marcado con el marker de integración para que el gate `--quick` lo omita.
- [ ] Suite completa en verde; sin cambios en los tests de integración Firebird existentes.

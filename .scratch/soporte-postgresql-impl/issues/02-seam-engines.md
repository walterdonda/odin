# 02: Seam de engines (extracción sin cambio de comportamiento)

**What to build:** la ejecución de respaldos se reorganiza detrás de un protocolo de motor con **cero cambio de comportamiento**: `odin run` para Firebird se comporta exactamente como hoy (mismo comando, mismos artefactos, mismos mensajes y exit codes). Es el prefactor que deja el engine PostgreSQL como una adición pequeña, no como una cirugía del código existente.

Especificación: `docs/postgresql.md` §5.1 (protocolo) y §5.2 (excepciones neutras). Detalle y reversiones en `.scratch/soporte-postgresql/issues/03-costura-engines-y-tests.md`.

**Blocked by:** 01 — configuración de dos motores + validate (los fixtures y el config ya portan `type`).

**Status:** ready-for-agent

- [ ] Paquete de engines con la clase base `Engine` (`binary_name`, `extension`, `secret_flags`, `error_patterns`, `env(database)`, `build_command(binary, database, target)`, `not_found_message()`, `resolve_binary(db_config)`) y el motor Firebird cubriendo exactamente el comportamiento actual.
- [ ] Excepciones neutras `EngineNotFoundError` / `EngineExecutionError`; el detalle (nombre del binario + hint) lo aporta el motor. Solo `odin.backup` y sus tests las referencian.
- [ ] El ejecutor de respaldos consume el protocolo sin dispatcher por tipo todavía: una sola vía, la de Firebird, sin duplicación de lógica.
- [ ] `odin run` Firebird idéntico al actual: comando gbak, artefacto `<nombre>_<timestamp>.fbk`, validación post-respaldo, timeout, enmascarado de secretos, hints de binario no encontrado, exit codes.
- [ ] Suite completa en verde; sin comportamiento nuevo visible para el usuario.

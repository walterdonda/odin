# 04: Retención `.dump` y CLI genérica

**What to build:** los artefactos PostgreSQL (`.dump` y `.dump.7z`) entran al ciclo de retención local exactamente como los `.fbk`, y la CLI habla de dos motores: descripción raíz, helps y resúmenes por base ya no dicen "solo Firebird". Los exit codes 0/1/2/3/4 quedan intactos y el pipeline no cambia.

Especificación: `docs/postgresql.md` §5.4 (retención) y §5.5 (CLI).

**Blocked by:** 03 — respaldo pg_dump (la retención gestiona artefactos que `odin run` ya produce).

**Status:** ready-for-agent

- [ ] Regex única de artefactos gestionados: `^.+_\d{8}_\d{6}\.(?:fbk|dump)(?:\.7z)?$`; el resto de la semántica de retención (seguridad, cutoff, mtime, aislamiento de archivos no gestionados) sin cambios.
- [ ] Tests de retención ampliados: `.dump` y `.dump.7z` gestionados (rotados y protegidos igual que `.fbk`), archivos no gestionados siguen intocables.
- [ ] Descripción raíz y helps de la CLI describen ambos motores; los resúmenes por base son genéricos y muestran los artefactos `.dump`/`.dump.7z` para entradas PostgreSQL.
- [ ] Exit codes 0/1/2/3/4 intactos; `odin.pipeline` sin cambios (solo docstring si aplica).
- [ ] Suite completa y gate `scripts/verify.py` en verde.

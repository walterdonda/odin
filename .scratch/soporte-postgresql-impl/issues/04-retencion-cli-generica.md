# 04: Retención `.dump` y CLI genérica

**What to build:** los artefactos PostgreSQL (`.dump` y `.dump.7z`) entran al ciclo de retención local exactamente como los `.fbk`, y la CLI habla de dos motores: descripción raíz, helps y resúmenes por base ya no dicen "solo Firebird". Los exit codes 0/1/2/3/4 quedan intactos y el pipeline no cambia.

Especificación: `docs/postgresql.md` §5.4 (retención) y §5.5 (CLI).

**Blocked by:** 03 — respaldo pg_dump (la retención gestiona artefactos que `odin run` ya produce).

**Status:** resolved

- [x] Regex única de artefactos gestionados: `^.+_\d{8}_\d{6}\.(?:fbk|dump)(?:\.7z)?$`; el resto de la semántica de retención (seguridad, cutoff, mtime, aislamiento de archivos no gestionados) sin cambios.
- [x] Tests de retención ampliados: `.dump` y `.dump.7z` gestionados (rotados y protegidos igual que `.fbk`), archivos no gestionados siguen intocables.
- [x] Descripción raíz y helps de la CLI describen ambos motores; los resúmenes por base son genéricos y muestran los artefactos `.dump`/`.dump.7z` para entradas PostgreSQL.
- [x] Exit codes 0/1/2/3/4 intactos; `odin.pipeline` sin cambios (solo docstring si aplica).
- [x] Suite completa y gate `scripts/verify.py` en verde.

## Answer

Gist: la retención pasa a una **regex única** de artefactos gestionados
(`^.+_\d{8}_\d{6}\.(?:fbk|dump)(?:\.7z)?$` en `src/odin/retention.py`); todo el
resto de la semántica (cutoff estricto, protección por `run_started_at`,
archivos regulares no-symlink dentro de `work_dir`, aislamiento de fallos,
idempotencia) queda intacto. La CLI (`src/odin/cli.py`) describe ambos motores:
descripción raíz, help y description de `run`, y docstrings (`.fbk`/`.dump` +
`.7z`); los resúmenes por base ya eran genéricos (imprimen las rutas de los
resultados, que el motor produce según `type`), así que solo se actualizó el
docstring de `_print_backup_summary`. `odin.pipeline` **sin cambios**.

Commits:
- `tests: retención .dump/.dump.7z y helps de CLI bilingües (rojo)`
- `feat: regex única de retención (fbk|dump) y CLI de dos motores (verde)`

Tests (ampliados, sin tocar lo que los existentes verifican):
- `tests/test_retention.py`: parametrize de aceptación/rechazo gana casos
  `.dump`/`.dump.7z` y lookalikes (`.dump.bak`, `.dump.7z.tmp`, `.dmp`); tests
  dedicados de rotación y protección por `run_start` para `.dump`.
- `tests/test_cli.py`: `test_root_help_describes_both_engines`,
  `test_run_help_describes_both_engines` y
  `test_run_summary_lists_dump_artifacts_for_postgresql_database` (entrada
  `type: postgresql` real por el pipeline con compresión 7z verdadera → el
  resumen muestra `.dump`/`.dump.7z`; exit 0).

Gate: `uv run python scripts/verify.py` completo en verde (6/6: uv sync, suite
completa 725 passed + integración, ruff, mypy, ambos examples). Exit codes
0/1/2/3/4 intactos (`test_exit_code_constants_follow_convention` verde).

Riesgos GitNexus: `impact` sobre `is_managed_backup`, `build_parser` y
`_print_backup_summary` → CRITICAL (esperable: corazón del flujo `run`, 21
procesos afectados). Mitigación: firmas/interfaces intactas; la regex solo
amplía el conjunto aceptado y la CLI solo cambia textos; comportamiento
cubierto por los tests ampliados y la suite completa. No hubo `UNKNOWN`.

Desvíos: ninguno. `examples/` sigue solo con `type: firebird` (correcto en este
ticket; el gate valida ambos examples en verde).

# 07: Docs, ejemplos y publicación 1.1.0

**What to build:** la documentación deja de presentar PostgreSQL como "aprobado, sin implementar" y describe el contrato de dos motores como vigente; los ejemplos suman la entrada PostgreSQL y validan en verde; el paquete se publica como 1.1.0 con la descripción y keywords de dos motores.

Especificación: `docs/postgresql.md` §3–§4 (contrato y ejemplo JSON definitivo); pasos 11 y 12 del plan §8.

**Blocked by:** 03, 04, 05, 06 — la doc describe comportamiento ya implementado y probado.

**Status:** resolved

- [x] `docs/configuration.md`: contrato de dos motores vigente — se retiran las notas de "especificación aprobada, implementación pendiente" de los campos PostgreSQL.
- [x] `README.md`: descripción, requisitos y resumen de campos actualizados para ambos motores.
- [x] `CHANGELOG.md`: entrada de release 1.1.0 con el soporte PostgreSQL 18+.
- [x] `examples/config.linux.json` y `examples/config.windows.json`: las bases Firebird llevan `"type": "firebird"` y se suma la entrada PostgreSQL (ejemplo definitivo de §4, adaptado a cada sabor de ruta); el gate `validate-*` sigue en verde sobre ambos.
- [x] `pyproject.toml`: versión 1.1.0, descripción y keywords que mencionan ambos motores.
- [x] Gate completo `scripts/verify.py` en verde (Linux; Windows por el job de CI habitual).

## Answer

Docs, ejemplos y publicación 1.1.0: la documentación presenta el contrato de dos motores como **vigente** — `docs/configuration.md` retira la nota de "especificación aprobada, implementación pendiente" del encabezado y los parentéticos "especificación aprobada" de §3/§7/§9/§10 y la fila "no implementada" de §11, con las referencias de versión pasadas a la actual; `docs/postgresql.md` declara la spec **implementada** en 1.1.0 (tickets 01–06). El README retira el banner y el estado "planificado" (requisitos, tabla resumen, flujo de `odin run`, retención y troubleshooting ahora describen ambos motores, y `odin --version` → 1.1.0). Los ejemplos suman la entrada PostgreSQL del ejemplo definitivo de §4 (`ventas_pg`, auto-detección de `pg_dump` vía `null`, espejo de `gbak_path`) y el job del scheduler cubre ambas bases. El paquete pasa a **1.1.0** (`pyproject.toml` + `src/odin/__init__.py` + `uv.lock`, descripción y keywords de dos motores) y el CHANGELOG gana la entrada de release 1.1.0 (F9 + correcciones y documentación movidas de Unreleased).

**Commits**
- `tests: fija el contrato de la entrada PostgreSQL en los ejemplos (ticket 07, rojo)` — `tests/test_fixtures.py`: `test_examples_postgresql_entry_matches_contract` (segunda base de ambos ejemplos: `type` postgresql, `host`/`dbname`/`port`, `pg_dump_path`/`pg_dump_timeout_sec` `null`, password placeholder, cobertura del job). Test **nuevo** (no se edita el existente): rojo verificado con 2 failed.
- `examples: entrada PostgreSQL en config.linux y config.windows (ticket 07)` — ambos ejemplos: base `ventas_pg` de §4 tras la entrada Firebird (que ya tenía `"type": "firebird"`) y `scheduler.jobs[0].databases` cubre ambas bases (elimina el WARN de base no cubierta). Verde: `test_fixtures` 18 passed y `odin validate` de ambos ejemplos con exit 0.
- `packaging: version 1.1.0 con descripcion y keywords de dos motores (ticket 07)` — `pyproject.toml` (version 1.1.0, descripción Firebird+PostgreSQL, keywords con `postgresql`/`pg_dump`), `src/odin/__init__.py` (`__version__ = "1.1.0"`, docstring del paquete), `uv.lock` refrescado. Rojo verificado antes del bump de `__version__`: `test_project_metadata_declares_python_and_entry_point` y `test_package_import_and_version` fallaban (2 failed); verde después (5 passed).
- `docs: contrato de dos motores vigente y CHANGELOG 1.1.0 (ticket 07)` — los cuatro archivos de doc.
- `scratch: resuelve ticket 07 (docs, ejemplos y publicacion) y actualiza mapa` — checkboxes, `Status: resolved`, `## Answer` y línea en `map.md`.

**Gate**: `uv run python scripts/verify.py` completo en verde (6/6: sync, pytest 148 s, ruff, mypy, validate-linux y validate-windows **con la entrada PostgreSQL nueva**); el merge de `integration/soporte-postgresql` estaba ya aplicado ("Already up to date", punta 46ac301). Los pasos `validate-*` validan ambos ejemplos con `bases: 2` y `pg_dump_path: null → auto-detección`.

**Riesgos GitNexus**: `impact` sobre `__version__` (`src/odin/__init__.py`): `UNKNOWN` con 0 callers resueltos — confirmado por búsqueda de texto que solo se lee dinámicamente (`odin.cli`, `test_smoke`, `test_packaging`); el cambio es el bump de valor que exige el contrato metadata≡`__version__`. `impact` sobre `test_examples_load_and_match_vision_structure` devolvió `CRITICAL` con procesos de `src/odin` como "incoming" — artefacto del índice (otros tests conectados por imports/fixtures compartidos, no llamadas reales; una función de test solo la colecciona pytest). Por eso **no se editó ese símbolo**: se agregó un test nuevo (`test_examples_postgresql_entry_matches_contract`, sin incoming) que fija el contrato nuevo.

**Desvíos explícitos**
1. `src/odin/__init__.py` se tocó pese a que el ticket decía "nada de src/odin debería cambiar": el bump de versión 1.1.0 es inherente al paso 12 del plan (Publicación) y es **obligatorio** para que `tests/test_packaging.py` (`PROJECT["version"] == ODIN_VERSION`) y `tests/test_smoke.py` (`odin.__version__ == version("odin")`) queden verdes; `uv.lock` se refrescó en consecuencia (`uv sync --locked` de la CI lo exige).
2. La entrada PostgreSQL es **idéntica en ambos sabores** de ejemplo: no tiene rutas locales (`host`/`dbname` son endpoints de red) y `pg_dump_path: null` delega la auto-detección, espejo de `gbak_path: null`; la adaptación de "rutas nativas" sigue viviendo en `connection`/`work_dir` de cada archivo.
3. El job del scheduler del ejemplo pasó a cubrir `ventas_pg` además de `nombre_clave_sistema`: evita el WARN de base no cubierta y deja el ejemplo coherente (ambas bases respaldadas por el cron); no lo exigía el ticket pero lo fija el test nuevo.
4. El gate local es Linux; Windows queda para el job de CI habitual (como en los tickets anteriores). `detect_changes` no se corrió acá: lo hace el merger (regla del mapa).

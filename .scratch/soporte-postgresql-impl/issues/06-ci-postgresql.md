# 06: CI con job de integración PostgreSQL

**What to build:** la CI ejecuta la integración PostgreSQL contra `postgres:18` en `ubuntu-latest` junto a los jobs existentes, y el test que verifica la forma del workflow queda actualizado y verde. El gate local `scripts/verify.py` no cambia.

Especificación: `docs/postgresql.md` §7.3 (CI).

**Blocked by:** 04 — retención y CLI genérica; 05 — integración postgres:18 (el job ejecuta esa prueba).

**Status:** resolved

- [x] El workflow de CI gana un job de integración PostgreSQL en `ubuntu-latest` con `postgres:18` (imagen/servicio), junto al job Linux existente.
- [x] `tests/test_ci_workflow.py` actualizado para reflejar el nuevo job y en verde.
- [x] `scripts/verify.py` intacto (mismos pasos); gate local completo en verde.
- [x] La suite completa pasa en Linux; el job Windows no se ve afectado.

## Answer

CI con job de integración PostgreSQL: el workflow gana el job `postgresql` (`ubuntu-latest`) junto al job `linux`, con `postgres:18` como **servicio** (imagen oficial, `POSTGRES_PASSWORD` como valor de prueba fijo y health check con `pg_isready` en `options`). El job ejecuta la suite de integración end-to-end del ticket 05 (`uv run pytest tests/test_backup_integration_postgres.py -q`) con el mismo andamiaje de uv que los otros jobs (checkout, `astral-sh/setup-uv` con caché, `uv sync --locked`); es un job liviano: no construye ni publica artefactos. `tests/test_ci_workflow.py` fija ese contrato con dos tests nuevos; `scripts/verify.py` queda intacto.

**Commits**
- `tests: contrato del job postgresql en CI contra servicio postgres:18 (ticket 06, rojo)` — `tests/test_ci_workflow.py`: `test_postgresql_job_runs_the_integration_suite_against_postgres18` (job `postgresql` en `ubuntu-latest`; servicio `postgres` con `image: postgres:18`, `POSTGRES_PASSWORD` en env y `pg_isready` en las options del health check; checkout/uv con caché/`uv sync`; comando de la suite de integración con `uv run pytest`; sin `upload-artifact`) y `test_postgres_integration_test_module_is_marked_integration` (el módulo de la suite está marcado `integration` y tiene skip condicional, espejo del smoke de Windows); constante `POSTGRES_INTEGRATION_TEST_PATH` y docstring del módulo actualizados. Rojo verificado: 1 failed (el job no existía), 7 passed.
- `ci: job postgresql contra servicio postgres:18 (ticket 06)` — `.github/workflows/ci.yml`: job `postgresql` entre `linux` y `windows` con `services.postgres` (image `postgres:18`, `env.POSTGRES_PASSWORD: odin-postgres`, `options` con `--health-cmd "pg_isready -U postgres"` + interval/timeout/retries) y pasos Checkout, Instalar uv (con caché), Sincronizar el entorno e Integración PostgreSQL; comentario de cabecera actualizado (la contraseña del servicio es un valor de prueba fijo, no un secreto). Jobs `linux`/`windows` sin tocar. Verde verificado: 8 passed.
- `scratch: resuelve ticket 06 (CI postgresql) y actualiza mapa` — checkboxes, `Status: resolved`, `## Answer` y línea en `map.md`.

**Gate**: `uv run python scripts/verify.py` completo en verde (6/6, pytest 136 s) con el merge de integración ya aplicado; la suite de integración corre **en verde contra `postgres:18` real** en esta máquina (`uv run pytest tests/test_backup_integration_postgres.py -q` → 1 passed). `scripts/verify.py` intacto (sin cambios en el diff).

**Riesgos GitNexus**: `impact` (upstream) sobre `tests/test_ci_workflow.py`, `_assert_job_is_verified` y `test_both_platform_jobs_run_the_single_gate`: `UNKNOWN` con 0 callers en los tres casos — confirmado con búsqueda de texto que nada fuera del módulo los referencia (solo menciones en docs históricas); módulo de tests consumido únicamente por pytest, ningún símbolo de `src/odin` editado. Los tests existentes del módulo quedaron byte-idénticos (solo docstring, una constante y dos tests nuevos).

**Desvíos explícitos**
1. El servicio se declara junto al job aunque la suite hoy levanta su propio contenedor (`tests/postgres_container.py`, que usa Docker del runner): la instrucción del ticket es declararlo con `POSTGRES_PASSWORD` y health check `pg_isready`, y tiene dos efectos reales — pre-pullea `postgres:18` (el `docker run` del test no descarga nada) y valida el arranque de la imagen con el health check antes de los pasos. El test no se modifica (fuera del alcance del ticket).
2. La contraseña del servicio (`odin-postgres`, igual a `DEFAULT_PASSWORD` del helper) va literal en el YAML: es un valor de prueba fijo, no un secreto; el workflow sigue sin referencias `secrets.` y con `permissions: contents: read` (lo fija `test_workflow_is_read_only_and_has_no_secrets`).
3. Sin puertos mapeados en el servicio (`ports`): nadie lo consume por red hoy; el mapeo se agrega si un ticket futuro apunta la suite al servicio.
4. El job no corre el gate completo (`scripts/verify.py`): lo hace el job `linux`; `postgresql` es un job liviano y enfocado solo en la integración (sin build ni artefacto, lo fija el test con la ausencia de `upload-artifact`).

# 01: Configuración de dos motores + validate

**What to build:** una config JSON puede declarar `"type": "firebird"` | `"postgresql"` por entrada de `databases[]` (obligatorio, sin default), y `odin validate` da feedback completo por motor: campos faltantes o de otro motor, `pg_dump_path` verificado como el `gbak_path` actual y `local.pg_dump_timeout_sec`. Las configs y fixtures Firebird existentes solo ganan `"type": "firebird"`; todo lo demás sigue igual.

Especificación: `docs/postgresql.md` §3 (contrato) y §5.6 (validate). Detalle y reversiones de decisiones en `.scratch/soporte-postgresql/issues/02-contrato-configuracion.md`.

**Blocked by:** None (can start immediately).

**Status:** resolved

- [x] `type` requerido y validado contra el enum: ausente → "campo requerido ausente"; valor inválido → mensaje con los valores permitidos.
- [x] Campos PostgreSQL parseados: `host`/`dbname` (exigencia semántica por motor), `port` (default 5432, bounds 1–65535, parseo nullable), `pg_dump_path`, `pg_dump_timeout_sec`; `local.pg_dump_timeout_sec` (default 7200, `exclusive_minimum=0`).
- [x] Checks condicionales `_db_problems` (espejo del patrón `auth`): campo del otro motor → "solo aplica cuando type es '<motor>'"; `connection` ausente en firebird / `host` o `dbname` ausentes en postgresql → "es requerido cuando type es '...'" (mensajes exactos de §3.5).
- [x] Validate: `_check_pg_dump_paths` espejo del check de gbak — `null` → INFO `pg_dump_autodetect`; directorio → ERROR; inexistente → WARN; no ejecutable → WARN; OK → "existe y es ejecutable". Ambos checks filtrados por `type`.
- [x] `iter_secret_fields` intacto: la contraseña sigue enmascarada y nunca aparece en logs.
- [x] Todos los fixtures de tests y los ejemplos existentes ganan `"type": "firebird"`; la suite completa y el gate `scripts/verify.py` quedan en verde.

## Answer

Implementado el contrato de dos motores en config + validate, con tests en rojo primero
(TDD). Detalle:

- **`src/odin/config.py`**: enum `DbEngine` (`firebird` | `postgresql`); `DatabaseConfig`
  gana `type` (obligatorio, sin default), `connection` pasa a `str | None` (exigencia
  semántica), y campos nuevos `host`/`port`/`dbname`/`pg_dump_path`/`pg_dump_timeout_sec`
  (parseo nullable; `port` sin default en el modelo —el 5432 efectivo lo aplicará el
  engine—, bounds 1–65535; paths normalizados). `_db_problems` espeja `_auth_problems` y
  se invoca en `validate_semantics` con los mensajes exactos de §3.5 ("solo aplica cuando
  type es '<motor>'", "es requerido cuando type es '...'"; `null` cuenta como ausente).
  `LocalConfig.pg_dump_timeout_sec` default 7200, `exclusive_minimum=0`.
  `iter_secret_fields` sin cambios.
- **`src/odin/validate.py`**: `_check_gbak_paths` filtrado por `type: firebird`;
  `_check_pg_dump_paths` espejo (checks `pg_dump_autodetect`/`pg_dump_path_exists`/
  `pg_dump_path_executable`), filtrado por `type: postgresql`, en `validate_config`.
- **`src/odin/backup.py`**: ajuste mínimo de tipos (`connection or ""`) porque
  `DatabaseConfig.connection` pasó a `str | None` (mypy estricto). Sin cambio de
  comportamiento: la validación exige `connection` para firebird.
- **Fixtures/ejemplos**: los 7 fixtures de `tests/fixtures/` y los 2 ejemplos de
  `examples/` ganan `"type": "firebird"`; nada más cambia.
- **Tests**: `tests/test_config.py` (+14 tests: type obligatorio/enum con mensajes
  exactos, campos por motor, port bounds/nullable, `_db_problems` por motor, timeout
  local y por base), `tests/test_validate.py` (+7 tests: pg_dump_path y filtro por
  type), `tests/test_fixtures.py` (aserciones de `type`), y adaptación de las
  construcciones directas de `DatabaseConfig` en `test_backup.py`,
  `test_backup_integration.py` y `test_firebird_matrix.py` (`type=DbEngine.FIREBIRD`).

**Gate**: `uv run python scripts/verify.py --quick --skip-sync` → 5/5 pasos en verde
(pytest 659 passed, ruff, mypy, validate-linux, validate-windows). Pytest completo
(sin `-m "not integration"`): **676 passed, 8 skipped** (skips documentados: Docker,
empaquetado, demos gated).

**Riesgos GitNexus (impact upstream)**: `DatabaseConfig` MEDIUM y `LocalConfig` MEDIUM
(cambios aditivos, solo lectores de campos). `load_config`, `validate_config` y
`_check_gbak_paths` CRITICAL por estar en el camino de `odin validate`/CLI (blast radius
de procesos, no riesgo específico del cambio): mitigado con comportamiento firebird
idéntico para configs válidas existentes y gate completo en verde. Sin `UNKNOWN` sin
confirmar.

**Desvíos explícitos**: (1) `port` se guarda como `int | None` (None = ausente, para
detectar presencia y disparar "solo aplica…"); el default efectivo 5432 se aplicará en
el engine (ticket 03), como anticipa §3.4. (2) `src/odin/backup.py` recibió un ajuste
de tipos de 2 líneas (necesario por el cambio de `connection` a nullable, mypy estricto).
(3) Los tests de backup/firebird_matrix ganaron `type=DbEngine.FIREBIRD` en sus
construcciones directas (adaptación obligada por `type` sin default).

**Commits**: ver `git log` en la rama `impl/01-configuracion-dos-motores`.

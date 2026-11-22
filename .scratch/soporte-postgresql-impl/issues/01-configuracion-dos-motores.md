# 01: Configuración de dos motores + validate

**What to build:** una config JSON puede declarar `"type": "firebird"` | `"postgresql"` por entrada de `databases[]` (obligatorio, sin default), y `odin validate` da feedback completo por motor: campos faltantes o de otro motor, `pg_dump_path` verificado como el `gbak_path` actual y `local.pg_dump_timeout_sec`. Las configs y fixtures Firebird existentes solo ganan `"type": "firebird"`; todo lo demás sigue igual.

Especificación: `docs/postgresql.md` §3 (contrato) y §5.6 (validate). Detalle y reversiones de decisiones en `.scratch/soporte-postgresql/issues/02-contrato-configuracion.md`.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] `type` requerido y validado contra el enum: ausente → "campo requerido ausente"; valor inválido → mensaje con los valores permitidos.
- [ ] Campos PostgreSQL parseados: `host`/`dbname` (exigencia semántica por motor), `port` (default 5432, bounds 1–65535, parseo nullable), `pg_dump_path`, `pg_dump_timeout_sec`; `local.pg_dump_timeout_sec` (default 7200, `exclusive_minimum=0`).
- [ ] Checks condicionales `_db_problems` (espejo del patrón `auth`): campo del otro motor → "solo aplica cuando type es '<motor>'"; `connection` ausente en firebird / `host` o `dbname` ausentes en postgresql → "es requerido cuando type es '...'" (mensajes exactos de §3.5).
- [ ] Validate: `_check_pg_dump_paths` espejo del check de gbak — `null` → INFO `pg_dump_autodetect`; directorio → ERROR; inexistente → WARN; no ejecutable → WARN; OK → "existe y es ejecutable". Ambos checks filtrados por `type`.
- [ ] `iter_secret_fields` intacto: la contraseña sigue enmascarada y nunca aparece en logs.
- [ ] Todos los fixtures de tests y los ejemplos existentes ganan `"type": "firebird"`; la suite completa y el gate `scripts/verify.py` quedan en verde.

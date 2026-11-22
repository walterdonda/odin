# 06: CI con job de integración PostgreSQL

**What to build:** la CI ejecuta la integración PostgreSQL contra `postgres:18` en `ubuntu-latest` junto a los jobs existentes, y el test que verifica la forma del workflow queda actualizado y verde. El gate local `scripts/verify.py` no cambia.

Especificación: `docs/postgresql.md` §7.3 (CI).

**Blocked by:** 04 — retención y CLI genérica; 05 — integración postgres:18 (el job ejecuta esa prueba).

**Status:** ready-for-agent

- [ ] El workflow de CI gana un job de integración PostgreSQL en `ubuntu-latest` con `postgres:18` (imagen/servicio), junto al job Linux existente.
- [ ] `tests/test_ci_workflow.py` actualizado para reflejar el nuevo job y en verde.
- [ ] `scripts/verify.py` intacto (mismos pasos); gate local completo en verde.
- [ ] La suite completa pasa en Linux; el job Windows no se ve afectado.

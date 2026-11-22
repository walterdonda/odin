# 07: Docs, ejemplos y publicación 1.1.0

**What to build:** la documentación deja de presentar PostgreSQL como "aprobado, sin implementar" y describe el contrato de dos motores como vigente; los ejemplos suman la entrada PostgreSQL y validan en verde; el paquete se publica como 1.1.0 con la descripción y keywords de dos motores.

Especificación: `docs/postgresql.md` §3–§4 (contrato y ejemplo JSON definitivo); pasos 11 y 12 del plan §8.

**Blocked by:** 03, 04, 05, 06 — la doc describe comportamiento ya implementado y probado.

**Status:** ready-for-agent

- [ ] `docs/configuration.md`: contrato de dos motores vigente — se retiran las notas de "especificación aprobada, implementación pendiente" de los campos PostgreSQL.
- [ ] `README.md`: descripción, requisitos y resumen de campos actualizados para ambos motores.
- [ ] `CHANGELOG.md`: entrada de release 1.1.0 con el soporte PostgreSQL 18+.
- [ ] `examples/config.linux.json` y `examples/config.windows.json`: las bases Firebird llevan `"type": "firebird"` y se suma la entrada PostgreSQL (ejemplo definitivo de §4, adaptado a cada sabor de ruta); el gate `validate-*` sigue en verde sobre ambos.
- [ ] `pyproject.toml`: versión 1.1.0, descripción y keywords que mencionan ambos motores.
- [ ] Gate completo `scripts/verify.py` en verde (Linux; Windows por el job de CI habitual).

# Especificación y plan de implementación

Type: task
Status: resolved
Blocked by: 01, 02, 03

## Question

Redactar el entregable del mapa: la **especificación** del soporte PostgreSQL (contrato de config según 02, costura de código según 03, comportamiento del engine según 01) y el **plan de implementación** (módulos, tests, docs, CI, orden de trabajo). El borrador lo redacta el agente (AFK) a partir de las resoluciones de 01–03; la aprobación final es del humano (HITL). El documento vive en el repo (ubicación a fijar en 03) y la resolución es la aprobación: sin aprobación el ticket no se cierra.
- Redactar `docs/postgresql.md` y actualizar `docs/configuration.md`, `README.md` y `CHANGELOG.md`.
- Incluir el ejemplo JSON definitivo con ambos motores (sketch resuelto en 02).

## Answer

**Aprobado por Walter (2026-11-22).** El entregable del mapa quedó redactado en
el repo:

- **`docs/postgresql.md`** (nuevo): especificación consolidada del soporte
  PostgreSQL 18+ —engine `pg_dump` (comando exacto `--format=custom
  --no-password --no-privileges -f <.dump>`, `PGPASSWORD`, exit codes 0/1, 8
  patrones de error, compatibilidad 9.2→18.x, rutas y regla del finder "major
  ≥ 18 gana")—, contrato de configuración por motor (según 02, con el ejemplo
  JSON definitivo de ambos motores), seam `odin/engines/` (según 03), retención
  `fbk|dump`, CLI, validate, notas de restauración (trap `SQL_ASCII`,
  `--no-owner` en `pg_restore`), matriz de tests (`PostgresContainer`
  `postgres:18` + job de CI) y **plan de implementación ordenado en 12 pasos**
  con el gate `scripts/verify.py` en verde por paso.
- **`docs/configuration.md`**: contrato de dos motores (§3, §7, §9, §10–§12)
  con nota de alcance: los campos PostgreSQL quedan marcados como
  "especificación aprobada, implementación pendiente" (el parser de 1.0.0
  todavía los rechaza) para no documentar como vigente lo que aún no existe.
- **`README.md`**: descripción, requisitos y resumen de campos con estado
  "planificado" para lo PostgreSQL.
- **`CHANGELOG.md`**: entrada de documentación en Unreleased con el mismo
  encuadre de estado.

Con esta aprobación el mapa queda completo: no queda nada por decidir antes de
implementar. El código es el handoff posterior al mapa (plan §8).

## Comments

### 2026-11-22 — Borrador AFK listo para aprobación (HITL)

Reclamado y redactado el borrador del entregable a partir de las resoluciones
de 01–03, sin tocar código (`src/` intacto). Archivos:

- **Nuevo** `docs/postgresql.md`: especificación consolidada (engine pg_dump
  con comando exacto, `PGPASSWORD`, exit codes/patrones, compatibilidad
  pg_dump↔servidor, rutas del finder, serie 18), contrato de configuración por
  motor, ejemplo JSON definitivo con ambos motores, seam `odin/engines/`,
  retención, CLI, validate, notas de restauración (trap `SQL_ASCII`,
  `--no-owner` en `pg_restore`), matriz de tests, CI y plan de implementación
  ordenado en 12 pasos con gate `scripts/verify.py` en verde por paso.
- **Actualizados** `docs/configuration.md` (contrato de dos motores en §3, §7,
  §9, §10–§12, con nota de alcance que marca los campos PostgreSQL como
  especificación aprobada aún no implementada), `README.md` (descripción,
  requisitos, resumen de campos con estado "planificado") y `CHANGELOG.md`
  (entrada de documentación en Unreleased).

Quedan sin commitear en el working tree a la espera de la **aprobación del
humano**; la resolución del ticket es esa aprobación (sin ella no se cierra).
Aprobado el contenido, se registra la respuesta, se cierra el ticket y se
apunta en el mapa (Decisions so far); el commit de los docs se coordina con el
humano (docs solos, o docs junto al primer paso de implementación).

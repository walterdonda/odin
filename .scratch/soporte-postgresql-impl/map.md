# Soporte PostgreSQL (18+) en ODIN — implementación

## Destination

Implementar la especificación aprobada `docs/postgresql.md` (mapa wayfinder
`soporte-postgresql`, resuelto) como soporte PostgreSQL 18.0+ en ODIN, con un
ticket por paso y el gate `scripts/verify.py` en verde por paso. La spec y el
plan en 12 pasos viven en `docs/postgresql.md`; las reversiones de decisiones y
los datos duros están en `.scratch/soporte-postgresql/issues/` (tickets 01–04
del mapa, `resolved`).

## Notes

- **Idioma**: español (repo, tickets y respuestas).
- **Tickets**: `.scratch/soporte-postgresql-impl/issues/` (numerados desde 01;
  el frontier es el ticket con `Status: ready-for-agent`, sin resolver y con
  todos sus `Blocked by:` resueltos, de menor número).
- **Cómo se cierra trabajo** (convención del tracker local, ver
  `docs/agents/issue-tracker.md`): cada implementador marca los checkboxes de
  su ticket, agrega una sección `## Answer` con el gist (commits + tests), deja
  `Status: resolved`, y agrega acá una línea en Decisions so far.
- **Ramas**: integración `integration/soporte-postgresql`; cada ticket en
  worktree propio con rama `impl/<NN>-<slug>` basada en la de integración.
- **GitNexus** (reglas de `AGENTS.md`): `impact` antes de editar símbolos;
  `detect_changes` antes de commitear; `UNKNOWN` no es all-clear.
- **Gate por ticket**: `uv run python scripts/verify.py` (con `--quick` se
  omiten los tests marcados `@integration`).

## Decisions so far

<!-- una línea por ticket resuelto: título con link y gist; el detalle vive en el ticket -->

# Costura de código por motor y cobertura de tests

Type: grilling
Status: open
Blocked by: 01

## Question

Grilling para especificar la costura de código y los tests. Punto de partida cerrado (mapa, Notes 1, 5, 6, 7, 10): módulos por motor con interfaz común, pipeline y etapas 3–5 intactas, `.sql` como extensión, `PGPASSWORD`, contenedor `postgres:18`.

Resolver con el humano:

- Forma de los módulos por motor (`odin/engines/firebird.py` y `odin/engines/postgresql.py`) y el protocolo común: resolver binario, construir comando, extensión del artefacto, patrones de error, error "binario no encontrado".
- Qué queda en `BackupExecutor` (genérico, despacha por motor) y qué se mueve a cada engine.
- Cambios mínimos en `retention.py` (regex `.fbk|.sql`), `cli.py` (ayuda y reporte), y confirmar que `pipeline.py` no cambia.
- `validate.py`: checks estáticos por motor y coherencia de campos (los mensajes exactos salen del ticket 02).
- Matriz de tests: unitarios espejo (finder, config, backup por motor) y `PostgresContainer` espejo de `tests/firebird_container.py` + CI.
- Detalles del engine PostgreSQL que dependen de los datos del ticket 01 (comando exacto, patrones de error, finder).

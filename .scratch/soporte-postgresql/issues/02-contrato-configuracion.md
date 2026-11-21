# Contrato de configuración con dos motores

Type: grilling
Status: open

## Question

Grilling con el humano para especificar el contrato de configuración exacto (campo por campo) con dos motores. Punto de partida cerrado en el charting (mapa, Notes 1, 4, 6, 8, 9): campo `type` por entrada (default `firebird`), campos con nombre de motor, `host`/`port`/`dbname` para PostgreSQL reutilizando `name`/`user`/`password`.

Resolver con el humano, campo por campo:

- Tabla completa de campos por motor: Firebird (`connection`, `role`, `charset`, `gbak_path`, `gbak_timeout_sec`) y PostgreSQL (`host`, `port` default 5432, `dbname`, `pg_dump_path`, `pg_dump_timeout_sec`); comunes `name`, `user`, `password`, `type`.
- Obligatoriedad condicionada por `type` y mensajes de validación ("solo aplica cuando type es…"), reutilizando el patrón de `auth` en `config.py`.
- `local`: `pg_dump_timeout_sec` (¿default 7200, espejo del gbak?) junto al `gbak_timeout_sec` actual.
- Precedencia del binario por motor: `*_path` de la base > del ejecutor > finder (espejo exacto de hoy).
- Sketch de JSON de ejemplo con bases de ambos motores para reaccionar (insumo del ticket 04).

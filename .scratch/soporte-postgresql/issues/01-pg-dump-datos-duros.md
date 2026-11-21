# Datos duros de pg_dump para PostgreSQL 18

Type: research
Status: open

## Question

Investigar, con fuentes primarias (documentación oficial de PostgreSQL en postgresql.org), los hechos exactos de `pg_dump` de la serie 18 que la especificación necesita para el módulo del motor y el finder. Decisiones cerradas que enmarcan la búsqueda (mapa, Notes): dump plain SQL portable con `--no-owner --no-privileges`, contraseña por `PGPASSWORD`, solo PostgreSQL 18.0+.

1. Invocación exacta para un dump plain-SQL portable: flags de conexión (`--host`, `--port`, `--username`, `--dbname`), formato por defecto, y qué hace `--encoding` (¿conviene fijarlo a UTF8 o respetar el encoding de la base?).
2. Exit codes de `pg_dump` (éxito/error) y a qué stream escribe los errores.
3. Texto exacto de los errores típicos de conexión/autenticación (insumo del equivalente de `_ERROR_PATTERNS` de `odin/backup.py`).
4. Semántica de `PGPASSWORD`: vacía vs no seteada, interacción con `.pgpass`, flag `--no-password`, comportamiento en Windows.
5. Rutas de instalación típicas de `pg_dump` 18 en Windows y Linux (insumo del finder espejo).
6. Regla oficial de compatibilidad pg_dump↔servidor (¿a qué mayores de servidor puede apuntar un pg_dump 18?).
7. Cambios de `pg_dump` en la serie 18 relevantes para un dump plain portable.
8. Estado de la serie 18 hoy (última menor publicada, estado de soporte).

Capturar los hallazgos en la rama throwaway `research/pg-dump-18` (push, sin PR; nunca se mergea) y reportar la ruta del archivo de notas para dejar acá el puntero de contexto.

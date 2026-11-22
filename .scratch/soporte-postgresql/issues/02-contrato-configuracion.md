# Contrato de configuración con dos motores

Type: grilling
Status: resolved

## Question

Grilling con el humano para especificar el contrato de configuración exacto (campo por campo) con dos motores. Punto de partida cerrado en el charting (mapa, Notes 1, 4, 6, 8, 9): campo `type` por entrada (default `firebird`), campos con nombre de motor, `host`/`port`/`dbname` para PostgreSQL reutilizando `name`/`user`/`password`.

Resolver con el humano, campo por campo:

- Tabla completa de campos por motor: Firebird (`connection`, `role`, `charset`, `gbak_path`, `gbak_timeout_sec`) y PostgreSQL (`host`, `port` default 5432, `dbname`, `pg_dump_path`, `pg_dump_timeout_sec`); comunes `name`, `user`, `password`, `type`.
- Obligatoriedad condicionada por `type` y mensajes de validación ("solo aplica cuando type es…"), reutilizando el patrón de `auth` en `config.py`.
- `local`: `pg_dump_timeout_sec` (¿default 7200, espejo del gbak?) junto al `gbak_timeout_sec` actual.
- Precedencia del binario por motor: `*_path` de la base > del ejecutor > finder (espejo exacto de hoy).
- Sketch de JSON de ejemplo con bases de ambos motores para reaccionar (insumo del ticket 04).

## Answer

Resuelto por grilling (HITL). Contrato de configuración con dos motores, campo por campo:

**`type` (todas las entradas)**

- Enum `"firebird"` | `"postgresql"`, **obligatorio y explícito en ambos motores, sin default**. Ausente → `campo requerido ausente`; valor inválido → mensaje con los valores permitidos (comportamiento estándar de `enum_field` con `required=True`, sin default).
- **Revierte la decisión 1 del charting** (default `firebird`): las configs Firebird actuales deberán agregar `"type": "firebird"`. Mapa actualizado (Notes 1 y Destination).

**Comunes (ambos motores)**

- `name`, `user`, `password`: obligatorios en ambos motores. Sin excepción para PostgreSQL (nada de depender de `.pgpass` o prompt): `PGPASSWORD` siempre seteado por subproceso (decisión 7 del charting).

**Firebird (aplica con `type: "firebird"`)**

- `connection`: requerido — nullable en el parse estructural, "es requerido cuando type es 'firebird'" en semántica.
- `role`, `charset`: opcionales, nullable.
- `gbak_path`: opcional, nullable, normalización de rutas (espejo del comportamiento actual).
- `gbak_timeout_sec`: opcional, nullable, `exclusive_minimum=0`.

**PostgreSQL (aplica con `type: "postgresql"`)**

- `host`: requerido — nullable en el parse, "es requerido cuando type es 'postgresql'" en semántica. Sin default `localhost`.
- `dbname`: requerido — no defaulta a `name`; `name` queda como identificador lógico (scheduler, retención) y `dbname` es el nombre real de la base en el servidor.
- `port`: opcional, default 5432, bounds 1–65535. Se parsea nullable para detectar presencia explícita (un `port` explícito en una entrada firebird dispara "solo aplica cuando type es 'postgresql'").
- `pg_dump_path`: opcional, nullable, normalización de rutas.
- `pg_dump_timeout_sec`: opcional, nullable, `exclusive_minimum=0`.

**Checks condicionales** — espejo del patrón `auth` (`_auth_problems`): el parse estructural valida solo tipos de dato; una `_db_problems` en `validate_semantics` aplica las reglas por `type`:

- Campo de un motor presente en una entrada del otro → `"solo aplica cuando type es '<motor>'"`.
- `connection` ausente con `type: "firebird"`; `host`/`dbname` ausentes con `type: "postgresql"` → `"es requerido cuando type es '...'"`.

**`local`**

- Nuevo `pg_dump_timeout_sec`: opcional, default 7200, `exclusive_minimum=0` — espejo exacto de `gbak_timeout_sec`.

**Precedencia** (confirmada contra el código actual, espejo exacto de hoy):

- Binario: `databases[].*_path` > ejecutor (constructor) > finder (`gbak_finder` / futuro `pg_dump_finder`).
- Timeout: `databases[].*_timeout_sec` > `local.*_timeout_sec` (vía ejecutor).

**Sin campo `encoding`** en la config: la decisión `--encoding` (UTF8 vs default, trap `SQL_ASCII`) queda a nivel de engine en el ticket 03.

**Sketch JSON** (base del ejemplo definitivo del 04):

```jsonc
{
  "databases": [
    {
      "name": "contabilidad",
      "type": "firebird",
      "connection": "C:/datos/CONTAB.FDB",
      "user": "SYSDBA",
      "password": "masterkey",
      "role": null,
      "charset": "UTF8"
    },
    {
      "name": "ventas_pg",
      "type": "postgresql",
      "host": "db.example.com",
      "port": 5432,
      "dbname": "ventas",
      "user": "odin_backup",
      "password": "s3cret",
      "pg_dump_path": null,
      "pg_dump_timeout_sec": null
    }
  ],
  "local": {
    "work_dir": "C:/odin/work",
    "retention_days": 30,
    "gbak_timeout_sec": 7200,
    "pg_dump_timeout_sec": 7200
  }
}
```

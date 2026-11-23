# Guía del motor PostgreSQL 18+ (`pg_dump`)

> **Estado:** implementado en la versión **1.1.0**. Esta guía es la versión
> consolidada del soporte PostgreSQL: el contrato de configuración (§3), el
> engine `pg_dump` (§2, §5), la retención `.dump`, la CLI y la CI de
> integración ya están activos en el código. Los tickets del mapa wayfinder
> `soporte-postgresql` (`.scratch/soporte-postgresql/` y
> `.scratch/soporte-postgresql-impl/`) contienen el detalle y las reversiones
> de decisiones originales.

- Guía de compatibilidad Firebird (el motor existente): [`docs/firebird.md`](firebird.md).
- El modelo multi-motor (dispatch, finders, protocolo `Engine`): [`docs/engines.md`](engines.md).
- Referencia de configuración (ambos motores): [`docs/configuration.md`](configuration.md).

---

## 1. Alcance

ODIN incorpora **PostgreSQL 18.0+** como segundo motor de respaldo,
reutilizando el pipeline existente —compresión 7z, transferencia SFTP, correo y
retención local, scheduler y modo servicio— sin cambios de comportamiento en
esas etapas.

Decisiones de diseño (cerradas en el mapa):

1. **`type` por entrada, explícito y obligatorio** (`"firebird"` | `"postgresql"`),
   sin default. Las configs Firebird actuales solo necesitan agregar
   `"type": "firebird"`. **Revirtió** el default `firebird` del charting.
2. **Respaldo lógico por base con `pg_dump`**; sin `pg_dumpall` ni objetos
   globales (roles, tablespaces), sin backups físicos/PITR/WAL.
3. **Formato custom** (`--format=custom`, binario y comprimido por defecto);
   artefacto **`.dump`** (→ `.dump.7z`), escrito por pg_dump vía `-f`.
   **Revirtió** el plain SQL y el `.sql` del charting.
4. **Solo PostgreSQL 18.0+**; nada anterior. El finder ya acepta majors ≥ 18
   (a prueba de futuro para 19/20), sin verificación de versión en runtime
   (regla documentada).
5. **Sin `--encoding`** en el dump (con formatos de archivo la conversión
   ocurre al restaurar); el trap `SQL_ASCII` se documenta en §9.
6. **Contraseña vía `PGPASSWORD`** por subproceso, nunca en la línea de
   comandos ni en logs.
7. **`odin validate`** sigue siendo estático y sin red: checks espejo de los
   actuales, sin conexión a la base.

**Fuera de alcance** (de este mapa y de la implementación): restauración
(`psql`/`pg_restore`, documentada como operación manual en §9), `pg_dumpall`,
backups físicos/PITR, migración Firebird → PostgreSQL, PostgreSQL anterior a
18, motores adicionales y extensiones de retención configurables
(`local.managed_extensions`).

---

## 2. Comportamiento del engine `postgresql`

### 2.1 Comando exacto

```text
pg_dump --host H --port P --username U --dbname D \
        --format=custom --no-password --no-privileges \
        --file <work_dir>/<name>_<YYYYMMDD_HHMMSS>.dump
```

- pg_dump **escribe el archivo él mismo** (`-f/--file`): espejo del seam de
  gbak —sin redirect de stdout ni buffering— y el artefacto no pasa por
  memoria.
- `--no-password` desactiva **solo** el prompt interactivo (el flag correcto
  para batch); la contraseña llega por `PGPASSWORD` (§2.2).
- Sin `--encoding` (formato custom: la conversión ocurre al restaurar), sin
  `--no-owner` (ignorado con formatos de archivo; se pasa a `pg_restore` al
  restaurar, §9), sin `-b` (los large objects ya se incluyen por defecto), sin
  `-v`, sin `-W`.
- Flags de conexión: `--host`, `--port` (default 5432/`PGPORT`), `--username`,
  `--dbname`. `dbname` es el nombre real de la base en el servidor y **no**
  defaulta a `name` (§3).

### 2.2 Credenciales y `PGPASSWORD`

- `PGPASSWORD` se setea en el `env` del subproceso, **nunca** en argv ni en
  logs. El engine no declara flags de secreto (`secret_flags = ()`), a
  diferencia de gbak.
- Precedencia de libpq: connstring `password=` > `PGPASSWORD` > `~/.pgpass` >
  prompt. ODIN siempre setea `PGPASSWORD` (la config exige `password` no
  vacío) y `--no-password` elimina el prompt, así que `.pgpass` nunca
  interviene.
- Dato duro: `PGPASSWORD` vacía ≡ no seteada (ambas caen a `.pgpass`). Como el
  parser exige `password` no vacío, ODIN nunca emite el env vacío.
- Sin semántica especial en Windows.

### 2.3 Exit codes y streams

- `0` = éxito, `1` = error (no hay otros códigos).
- Con `-f`, el dump va al archivo; errores y warnings van a **stderr** con
  prefijo `pg_dump: error:`.
- Detección de fallo (semántica actual de `_check_completed`):
  `returncode != 0 or pattern in stderr.lower()`.

### 2.4 Patrones de error

Lista verificada contra docs oficiales (insumo del `error_patterns` del
engine):

| Patrón (en stderr, lowercase) |
|---|
| `password authentication failed for user "%s"` |
| `fe_sendauth: no password supplied` |
| `no pg_hba.conf entry for host ...` |
| `connection to server at "%s" (%s), port %s failed: ` |
| `connection to server on socket "%s" failed: ` |
| `could not translate host name` |
| `timeout expired` |
| `aborting because of server version mismatch` |

Nota verificada: `could not connect to server` **no existe** en libpq 18 (no
incluir).

### 2.5 Compatibilidad pg_dump ↔ servidor

- `pg_dump` 18 vuelca servidores **9.2 → 18.x**; rechaza 19+ con exit 1
  (`aborting because of server version mismatch`).
- El artefacto `.dump` restaura en servidores **≥ 18**.
- Consecuencia para el finder: se busca cualquier major **≥ 18 y gana el
  mayor**; si ninguna instalación versionada llega a 18, el finder cae a las
  rutas sin versión —las típicas y cada entrada del `PATH` (§2.6 "Siempre")—
  y alcanza la primera que exista; recién si no hay ninguna devuelve `None`
  (equivale a "binario no encontrado", con el hint de instalación del
  engine).

### 2.6 Rutas de `pg_dump` 18 (insumo del finder)

| Plataforma | Ruta |
|---|---|
| Windows | `C:\Program Files\PostgreSQL\18\bin\pg_dump.exe` |
| Debian/Ubuntu | `/usr/lib/postgresql/18/bin/pg_dump` (+ wrapper `/usr/bin/pg_dump`) |
| PGDG yum (RHEL/Fedora-like) | `/usr/pgsql-18/bin/pg_dump` |
| Fedora | `/usr/bin/pg_dump` |
| Source | `/usr/local/pgsql/bin` |
| Siempre | cada entrada de `PATH` + `pg_dump(.exe)` |

La comprobación es de **existencia**, no de ejecutabilidad (la validación fina
la hace `odin validate`, igual que con gbak). Prioridad del finder: entre las
instalaciones versionadas se aceptan majors ≥ 18 y gana el mayor; si ninguna
llega a 18, alcanza la primera ruta sin versión existente (las típicas y cada
entrada del `PATH`, que se consultan **siempre**).

### 2.7 Serie 18 (estado verificado)

- Última menor publicada: **18.7** (2026-11-12); 18.5 nunca se publicó.
  Soportada hasta finales de 2030.
- 18.0 agregó `--statistics`, `--sequence-data`, `--statistics-only`,
  `--no-policies`; fixes de validez de dump en 18.1/18.2/18.4/18.6/18.7; nada
  cambia el formato custom.
- 19.0 se publicó el 2026-11-19: **fuera del alcance** de este mapa (solo
  18.0+), aunque el finder ya la resolvería sin tocar código.

---

## 3. Contrato de configuración (dos motores)

Resuelto campo por campo en el ticket 02; implementación en `src/odin/config.py`.

### 3.1 `databases[].type` (todas las entradas)

- Enum `"firebird"` | `"postgresql"`, **obligatorio y explícito, sin default**.
- Ausente → `campo requerido ausente`; valor inválido → mensaje con los valores
  permitidos (comportamiento estándar de `enum_field` con `required=True`).
- **Revirtió** el default `firebird` del charting: las configs Firebird
  existentes deben agregar `"type": "firebird"`.

### 3.2 Comunes (ambos motores)

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `name` | `string` | Sí | Identificador lógico (jobs, artefactos, retención); único en `databases[]`. |
| `user` | `string` | Sí | Usuario de conexión. |
| `password` | `string` | Sí | Contraseña; enmascarada. En PostgreSQL viaja por `PGPASSWORD`; nunca depende de `.pgpass` ni del prompt. |

### 3.3 Firebird (`type: "firebird"`)

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `connection` | `string` | Sí | Se pasa a `gbak` tal cual. Parseo estructural nullable; la exigencia por motor es semántica. |
| `role` | `string \| null` | No | `null` → no se pasa. |
| `charset` | `string \| null` | No | Conservado; `gbak` no lo usa. |
| `gbak_path` | `string \| null` | No | Normalización de rutas. |
| `gbak_timeout_sec` | `integer \| null` | No | `exclusive_minimum=0`. |

### 3.4 PostgreSQL (`type: "postgresql"`)

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `host` | `string` | Sí | Sin default `localhost`. Exigencia por motor semántica (parseo nullable). |
| `dbname` | `string` | Sí | Nombre real de la base en el servidor; **no** defaulta a `name`. |
| `port` | `integer` | No | Default **5432**, bounds 1–65535. Se parsea nullable para detectar presencia explícita (un `port` en una entrada firebird dispara "solo aplica…"). |
| `pg_dump_path` | `string \| null` | No | Normalización de rutas. |
| `pg_dump_timeout_sec` | `integer \| null` | No | `exclusive_minimum=0`. |

### 3.5 Checks condicionales (`_db_problems`)

Espejo del patrón `auth` (`_auth_problems`): el parse estructural valida solo
tipos; una `_db_problems` en `validate_semantics` aplica las reglas por `type`:

- Campo de un motor presente en una entrada del otro →
  `"solo aplica cuando type es '<motor>'"`.
- `connection` ausente con `type: "firebird"`; `host`/`dbname` ausentes con
  `type: "postgresql"` → `"es requerido cuando type es '...'"`.

### 3.6 `local`

| Campo | Tipo | Obligatorio | Default | Notas |
|---|---|---|---|---|
| `pg_dump_timeout_sec` | `integer` | No | `7200` | `exclusive_minimum=0`; espejo exacto de `gbak_timeout_sec`. |

### 3.7 Precedencia (espejo exacto de hoy)

- **Binario**: `databases[].*_path` > ejecutor (constructor) > finder
  (`gbak_finder` / `pg_dump_finder`).
- **Timeout**: `databases[].*_timeout_sec` > `local.*_timeout_sec` (vía ejecutor).

### 3.8 Sin campo `encoding`

La decisión `--encoding` (UTF8 vs default, trap `SQL_ASCII`) queda a nivel de
engine: **no se pasa** (§2.1) y se documenta en el restore (§9).

---

## 4. Ejemplo JSON definitivo (ambos motores)

```json
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

(Bloques `compression`, `servers`, `notification` y `scheduler`: sin cambios.)

---

## 5. Costura de código (seam por motor)

Resuelto en el ticket 03.

### 5.1 Paquete `odin/engines/`

- `odin/engines/__init__.py`, `odin/engines/firebird.py`,
  `odin/engines/postgresql.py`.
- Protocolo común (clase base `Engine`) por motor:

| Miembro | Firebird | PostgreSQL |
|---|---|---|
| `binary_name` | `gbak` (`.exe` en Windows) | `pg_dump` (`.exe` en Windows) |
| `extension` | `.fbk` | `.dump` |
| `secret_flags` | `("-password", "-pas", "-P")` | `()` |
| `error_patterns` | los 4 actuales | los 8 de §2.4 |
| `env(database)` | `{}` | `{"PGPASSWORD": database.password}` |
| `build_command(binary, database, target)` | `gbak -b` + conexión | comando de §2.1 |
| `not_found_message()` | hint de instalación | hint de instalación (`--host/--username/--dbname` + rutas) |
| `resolve_binary(db_config)` | precedencia §3.7 | precedencia §3.7 |

- Excepciones **neutras** en `odin/engines/`: `EngineNotFoundError` /
  `EngineExecutionError`; el detalle (nombre del binario + hint) lo aporta el
  engine. Renombrado interno: nadie captura esas excepciones fuera de
  `backup.py` (verificado: solo `odin.backup` y sus tests las referencian).

### 5.2 `BackupExecutor` genérico

- Dispatch por `database.type` al engine correspondiente.
- Conserva: timeout, `subprocess.run` con el `env` del engine, `_check_completed`
  (exit ≠ 0 o patrón en stderr), validación del artefacto (existe, no vacío,
  legible), lote secuencial con aislamiento de fallos, resultados.
- Constructor gana `pg_dump_path` junto al `gbak_path` actual; timeout por base
  `pg_dump_timeout_sec`; `_masked_command` pasa a usar `secret_flags` del
  engine.
- `odin.pipeline` gana **una línea funcional**: el wiring de
  `local.pg_dump_timeout_sec` al `BackupExecutor` (junto al
  `local.gbak_timeout_sec` existente), porque §3.7 exige que la precedencia de
  timeout llegue vía el ejecutor. El resto del pipeline consume
  `BackupExecutor` y los resultados genéricos; compresión/transferencia/correo/
  retención siguen igual (la compresión recibe `archive_path` cualquiera sea la
  extensión).

### 5.3 Finders

- `odin/gbak_finder.py` queda **intacto**.
- `odin/pg_dump_finder.py` espejo, con las rutas verificadas de §2.6 y la
  regla "**major ≥ 18, gana el mayor**; si ninguna instalación versionada
  llega a 18, alcanza la primera ruta sin versión existente (típicas y cada
  entrada del `PATH`); recién entonces `None`". Sin verificación de versión
  en runtime (regla documentada: existir en una ruta típica o del `PATH`
  basta).

### 5.4 Retención

- Regex única: `^.+_\d{8}_\d{6}\.(?:fbk|dump)(?:\.7z)?$` (reemplaza la actual
  `.fbk`); todo lo demás (seguridad, cutoff, mtime, aislamiento) sin cambios.

### 5.5 CLI

- Descripción raíz y helps generales para los motores (ya no "solo Firebird");
  resúmenes por base genéricos; exit codes 0/1/2/3/4 intactos; `pipeline.py`
  con la línea de wiring del timeout pg_dump (§5.2).

### 5.6 `odin validate`

- `_check_pg_dump_paths` espejo de `_check_gbak_paths`: `null` → INFO
  `pg_dump_autodetect`; directorio → ERROR; inexistente → WARN; no ejecutable →
  WARN; OK → "existe y es ejecutable". Ambos filtrados por `type`.
- `_db_problems` en `config.py` (espejo de `_auth_problems`) con los mensajes
  exactos de §3.5.
- Sin conexión a la base (principio "sin red" vigente).

---

## 6. Notas de restauración (operación manual, fuera del alcance del código)

- El `.dump` es custom y comprimido: `7z x <archivo>.dump.7z` y luego
  `pg_restore --dbname <destino> --no-owner <archivo>.dump` (crear la base
  destino vacía primero con `createdb`).
- `--no-privileges` se aplicó al crear el dump; al restaurar, `--no-owner`
  evita exigir el dueño original.
- **Trap `SQL_ASCII`**: sin `--encoding`, el dump se rotula con el encoding de
  la base y **no se convierte**; una base `SQL_ASCII` produce un dump rotulado
  `UTF8` con bytes crudos. Al restaurar, creá la base destino con el encoding
  real de los datos y verificá; la conversión de encoding con formatos de
  archivo ocurre en este paso, no al respaldar.

---

## 7. Matriz de tests

### 7.1 Unitarios (espejo por motor)

| Archivo | Cobertura |
|---|---|
| `tests/test_pg_dump_finder.py` | rutas por plataforma, filtro ≥ 18, mayor gana, fallback a rutas sin versión (típicas y `PATH`), `None` sin candidatos |
| `tests/test_config.py` (ampliado) | campos por motor, `type` obligatorio/enum, `_db_problems` (mensajes exactos), `local.pg_dump_timeout_sec` |
| `tests/test_backup.py` (ampliado) | dispatch por `type`, comando exacto, `PGPASSWORD` en env (nunca logueada), patrones, timeout, not-found con hint por motor |
| `tests/test_retention.py` (ampliado) | `.dump` y `.dump.7z` gestionados |
| `tests/test_validate.py` (ampliado) | `pg_dump_path`, filtro por `type` |
| `tests/test_cli.py` (ampliado) | helps generales |

### 7.2 Integración

- `tests/postgres_container.py`: `PostgresContainer` espejo de
  `tests/firebird_container.py` —Docker directo por subprocess, imagen
  `postgres:18`, `POSTGRES_PASSWORD`, readiness con `pg_isready`,
  `pg_dump_wrapper` vía `docker exec`—; imagen única con override
  `ODIN_POSTGRES_IMAGE`.
- `tests/test_backup_integration.py` (o `test_backup_integration_postgres.py`):
  flujo real respaldo contra el contenedor, skip sin Docker (mismo patrón de
  skip que Firebird).
- Los tests existentes de Firebird **no cambian** salvo los fixtures de config
  que pasan a incluir `"type": "firebird"`; además, las construcciones
  directas de `DatabaseConfig` en los tests ganan `type=DbEngine.FIREBIRD` y
  los dobles de `BackupExecutor` acompañan la firma nueva (paths y timeouts
  por motor).

### 7.3 CI

- Job de integración PostgreSQL en `ubuntu-latest` contra `postgres:18`
  (`.github/workflows/ci.yml`), cubierto por `tests/test_ci_workflow.py`.
- Gate `scripts/verify.py` **intacto**: sus pasos son los mismos; los examples
  incluyen la entrada PostgreSQL y el gate `validate-*` los valida.

---

## 8. Criterios de aceptación (cumplidos en 1.1.0)

El gate completo pasa en Linux y Windows; la matriz Firebird existente sigue
verde; el flujo de integración PostgreSQL respalda un contenedor `postgres:18`
real y el `.dump.7z` resultante existe y no está vacío.

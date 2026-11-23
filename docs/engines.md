# ODIN — Motores de respaldo

ODIN respalda bases de datos de **varios motores** con el mismo pipeline:
respaldo lógico, compresión 7z, transferencia SFTP, informe por correo y
retención local. Esta guía explica el **modelo multi-motor**: cómo se elige el
motor de cada base, qué aporta cada uno, qué comparten y cómo se agrega un
motor nuevo.

- Referencia completa de campos por motor: [`docs/configuration.md`](configuration.md).
- Guía de compatibilidad Firebird: [`docs/firebird.md`](firebird.md).
- Guía del motor PostgreSQL y restauración: [`docs/postgresql.md`](postgresql.md).
- Operación del pipeline: [`README.md`](../README.md#operación).

---

## 1. El modelo: `databases[].type` y dispatch

Cada entrada de `databases[]` declara su motor con el campo **`type`**,
obligatorio y explícito, sin default: `"firebird"` o `"postgresql"`. Ese campo
determina:

- **qué campos aplican** a la entrada (los del otro motor son error de
  configuración);
- **qué binario** se resuelve (`gbak` o `pg_dump`);
- **qué comando** se ejecuta y **qué artefacto** se produce (`.fbk` o
  `.dump`).

El resto del pipeline es **agnóstico al motor**: la compresión recibe el
archivo resultante cualquiera sea su extensión, y la transferencia, el correo,
la retención y el scheduler trabajan sobre artefactos genéricos.

| Motor | `type` | Binario | Comando | Artefacto | Serie soportada |
|---|---|---|---|---|---|
| Firebird | `"firebird"` | `gbak` | `gbak -b` con `-user`/`-password`/`-role` | `.fbk` → `.fbk.7z` | 2.5 → 6 (misma familia de `gbak` que la base) |
| PostgreSQL | `"postgresql"` | `pg_dump` | `pg_dump --format=custom --no-password --no-privileges --file …` | `.dump` → `.dump.7z` | solo 18.0+ (`pg_dump` 18 respalda servidores 9.2 → 18.x) |

El dispatch vive en `src/odin/backup.py` (`BackupExecutor._engine_for`): un
diccionario `DbEngine → Engine`. El enum `DbEngine` de `src/odin/config.py`
solo acepta esos dos valores; cualquier otro se rechaza al cargar la
configuración con el mensaje de valores permitidos.

## 2. Campos por motor

Resumen por motor; la referencia completa (tipo, obligatoriedad, default,
rangos y reglas cruzadas) está en [`docs/configuration.md`](configuration.md#3-databases).

| Campo | Firebird | PostgreSQL | Notas |
|---|---|---|---|
| `type` | requerido | requerido | `"firebird"` o `"postgresql"`, sin default. |
| `name` | requerido | requerido | Clave única que referencian los jobs; prefijo del archivo de respaldo. |
| `user` | requerido | requerido | `-user` (gbak) o `--username` (pg_dump). |
| `password` | requerido | requerido | `-password` (gbak) o `PGPASSWORD` (pg_dump); siempre enmascarada. |
| `connection` | requerido | — | Se pasa a `gbak` tal cual (`host/puerto:ruta` o alias). |
| `role` | opcional | — | `-role`; `null` no lo envía. |
| `charset` | opcional | — | Se conserva en la configuración; `gbak` no tiene switch de charset y no se pasa. |
| `gbak_path` | opcional | — | Binario explícito; `null` = auto-detección. |
| `gbak_timeout_sec` | opcional | — | `null` → `local.gbak_timeout_sec`. |
| `host` | — | requerido | Servidor (`--host`); sin default `localhost`. |
| `port` | — | opcional (default `5432`) | Puerto del servidor (`--port`). |
| `dbname` | — | requerido | Nombre real de la base (`--dbname`); **no** defaulta a `name`. |
| `pg_dump_path` | — | opcional | Binario explícito; `null` = auto-detección. |
| `pg_dump_timeout_sec` | — | opcional | `null` → `local.pg_dump_timeout_sec`. |

Checks condicionales (espejo del patrón de `auth`): un campo de un motor
presente en una entrada del otro es error (`solo aplica cuando type es '…'`);
`connection` ausente con `type: "firebird"`, o `host`/`dbname` ausentes con
`type: "postgresql"`, son error (`es requerido cuando type es '…'`). `odin
validate` filtra las verificaciones de binarios por `type` y sigue siendo
estático y sin red.

## 3. Resolución del binario

Precedencia común, implementada en el protocolo `Engine`
(`src/odin/engines/__init__.py`):

1. `databases[].<motor>_path` explícito en el JSON (`gbak_path` o
   `pg_dump_path`).
2. Binario del ejecutor (`BackupExecutor`, uso programático).
3. Auto-detección del finder del motor, cacheada tras el primer uso.

La auto-detección de `gbak` busca las rutas típicas por SO (regla de familia:
el mayor de `gbak` debe coincidir con el de la base; detalle en
[`docs/firebird.md`](firebird.md)). La de `pg_dump` busca instalaciones con
**major ≥ 18 y gana el mayor**; si ninguna instalación versionada llega a 18,
cae a las rutas sin versión (típicas y cada entrada del `PATH`) y recién
entonces falla. Sin verificación de versión en runtime: existir en una ruta
típica o del `PATH` basta (detalle en
[`docs/postgresql.md`](postgresql.md#25-compatibilidad-pgdump--servidor)).

## 4. Artefactos, compresión y retención

- El respaldo se guarda en `local.work_dir` como
  `<name>_<YYYYMMDD_HHMMSS>.<ext>`: `.fbk` (Firebird) o `.dump` (PostgreSQL).
  En PostgreSQL el archivo lo escribe el propio `pg_dump` vía `--file`.
- La compresión produce `<name>_<timestamp>.<ext>.7z` con `py7zr`, nivel
  configurable y cifrado AES-256 opcional (`compression.password`). Es
  agnóstica a la extensión.
- La retención local reconoce y elimina los cuatro patrones gestionados:
  `.fbk`, `.fbk.7z`, `.dump` y `.dump.7z`
  (`^.+_\d{8}_\d{6}\.(?:fbk|dump)(?:\.7z)?$` en `src/odin/retention.py`).

## 5. Timeouts

Un timeout por motor: `gbak_timeout_sec` y `pg_dump_timeout_sec`. Precedencia:
`databases[].<motor>_timeout_sec` (si no es `null`) > `local.<motor>_timeout_sec`
(default `7200` en ambos).

## 6. Secretos y enmascarado por motor

- **Firebird**: la contraseña viaja como argumento (`-password`), visible en
  la lista de procesos mientras corre el respaldo. Los logs la enmascaran con
  los flags declarados en `secret_flags` (`-password`, `-pas`, `-P`).
- **PostgreSQL**: la contraseña viaja **solo** en el entorno del subproceso
  (`PGPASSWORD`), nunca en argv ni en logs (`secret_flags = ()`). La
  exposición es menor pero no nula (`/proc/<pid>/environ`).
- Ambos motores pasan por el mismo enmascarador para logs, informes, resumen de
  consola y `scheduler_state.json`. Detalle y mitigaciones:
  [`docs/security.md`](security.md#5-enmascarado-de-secretos-garantías-y-límites).

## 7. Identificación de la base en logs e informes

El objetivo legible de cada respaldo depende del motor
(`_database_target` en `src/odin/backup.py`): Firebird usa `connection`;
PostgreSQL usa `host/dbname` (o lo que haya si falta alguno). El informe por
correo y el estado no fijan extensión: muestran la ruta del artefacto tal como
se produjo.

## 8. Protocolo `Engine` y cómo agregar un motor

Los motores viven en el paquete `src/odin/engines/` sobre una clase base común
(`Engine`) que declara datos y comportamiento:

| Miembro | Firebird | PostgreSQL |
|---|---|---|
| `binary_name` | `gbak` (`.exe` en Windows) | `pg_dump` (`.exe` en Windows) |
| `extension` | `.fbk` | `.dump` |
| `secret_flags` | `("-password", "-pas", "-P")` | `()` |
| `error_patterns` | 4 patrones de `gbak` | 8 patrones de `pg_dump` |
| `env(database)` | `{}` | `{"PGPASSWORD": database.password}` |
| `build_command(binary, database, target, db_config)` | `gbak -b` + conexión | comando custom con `--file` |
| `not_found_message()` | hint de instalación | hint de instalación + conexión |
| `resolve_binary(db_config)` | precedencia de §3 | precedencia de §3 |

`BackupExecutor` consume solo el protocolo: timeout, `subprocess.run` con el
`env` del motor, detección de fallo (exit ≠ 0 o patrón en stderr), validación
del artefacto (existe, no vacío, legible), lote secuencial con aislamiento de
fallos y enmascarado vía `secret_flags`. Los errores operativos esperados no
se propagan: se reportan en el `BackupResult` de cada base. Las excepciones
del paquete (`EngineNotFoundError`, `EngineExecutionError`, base
`EngineError`) son neutras: el detalle lo aporta el motor.

Para agregar un tercer motor, el contrato exige tocar estos puntos:

1. **`src/odin/config.py`**: valor nuevo en el enum `DbEngine`, campos del
   motor en el esquema de `databases[]` (parseo estructural nullable), default
   de timeout en `local` si el motor lo necesita, y las reglas por motor en
   `_db_problems` (espejo de `_auth_problems`).
2. **`src/odin/engines/`**: clase nueva que implemente el protocolo `Engine`
   (`binary_name`, `extension`, `secret_flags`, `error_patterns`, `env`,
   `build_command`, `not_found_message`, `_configured_binary`, `_find_binary`).
3. **`src/odin/backup.py`**: registrar el engine en el diccionario de
   `BackupExecutor` y el timeout por motor.
4. **Finder** del binario nuevo (espejo de `gbak_finder.py`/
   `pg_dump_finder.py`) si la auto-detección no cubre el `PATH` a secas.
5. **`src/odin/retention.py`**: sumar la extensión nueva a la regex de
   artefactos gestionados.
6. **`src/odin/validate.py`**: verificación de rutas del binario nuevo
   (espejo de `_check_gbak_paths`), filtrada por `type`.
7. **`src/odin/cli.py`**: descripción y helps generales.
8. **Tests**: unitarios espejo (`tests/test_engines.py`,
   `tests/test_config.py`, `tests/test_backup.py`, `tests/test_retention.py`,
   `tests/test_validate.py`, `tests/test_cli.py`) e integración con el
   contenedor del motor; fixtures de config con `type`.
9. **Docs**: esta guía, `docs/configuration.md`, README, ejemplos y CHANGELOG.

Los tests actuales cubren los dos motores (matriz en
`tests/test_engines.py` y los ampliados por motor); `scripts/verify.py`
sigue siendo el gate único.

---

## Enlaces

- `src/odin/engines/` — protocolo y motores (`__init__.py`, `firebird.py`,
  `postgresql.py`).
- `src/odin/gbak_finder.py`, `src/odin/pg_dump_finder.py` — auto-detección.
- `src/odin/backup.py` — `BackupExecutor`, dispatch y objetivos legibles.
- Tests: `tests/test_engines.py`, `tests/test_backup.py`,
  `tests/test_config.py`, `tests/test_retention.py`, `tests/test_validate.py`,
  `tests/test_cli.py`.

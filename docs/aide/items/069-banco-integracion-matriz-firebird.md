# Item 069: Banco de integración de la matriz Firebird 2.5 → 5/6

## Description

Crear `tests/test_firebird_matrix.py`, el banco de integración parametrizado
por versión de Firebird, y el helper de contenedor compartido
`tests/firebird_container.py` que reutilizan los tests existentes
(`tests/test_backup_integration.py`, `tests/test_notify_integration.py`) sin
duplicar el código Docker.

Filas de la matriz:

- **2.5** — `jacobalberty/firebird:2.5-sc` (familia legacy: `ISC_PASSWORD`,
  base en `/firebird/data`, binarios en `/usr/local/firebird/bin`).
- **3.0** — `firebirdsql/firebird:3.0.9` (familia moderna, fila extra de bajo
  costo para el Item 070).
- **5.0** — `firebirdsql/firebird:latest` (familia moderna:
  `FIREBIRD_ROOT_PASSWORD`/`FIREBIRD_DATABASE`, base en
  `/var/lib/firebird/data`, binarios en `/opt/firebird/bin`).
- **6.x (best-effort)** — `firebirdsql/firebird:6-snapshot`; la fila se omite
  (skip) si la imagen no existe para la arquitectura del host o el contenedor
  no arranca.

Cada fila debe: arrancar el contenedor con puerto publicado dinámico (la
imagen crea la base vía variables de entorno), sembrar una tabla con filas vía
`isql` **dentro** del contenedor, ejecutar el respaldo con `BackupExecutor` y
`databases[].gbak_path` apuntando al **`gbak` de la misma familia que la
imagen**, validar el `.fbk` (existe y no vacío) y **restaurar a una base
scratch** con el mismo `gbak`, contando las filas sembradas vía `isql` (deben
coincidir). Cubrir al menos una variante de usuario dedicado y de charset por
versión.

El `gbak` del host **no está instalado y no debe requerirse**: el wrapper
elegido invoca `docker exec` sobre el binario de la imagen (`--user root`) con
el `work_dir` montado en la misma ruta absoluta, de modo que los caminos que
`BackupExecutor` pasa al wrapper son válidos dentro del contenedor.

## Acceptance Criteria

- [x] `tests/firebird_container.py` existe con el helper único de contenedor
      (imagen por familia, arranque/parada, `isql`, `gbak`, wrapper
      `docker exec`, puerto dinámico, espera de arranque) y docstring con
      imágenes/digests y convenciones de entorno por familia.
- [x] `tests/test_firebird_matrix.py` parametrizado por versión (2.5, 3.0,
      5.0 y 6 best-effort), marcado `@pytest.mark.integration` y skip-safe sin
      Docker; la fila 6 se omite si la imagen no existe/arranca.
- [x] Cada fila siembra filas con `isql` dentro del contenedor, respalda con
      `BackupExecutor` + `gbak_path` al wrapper de la imagen, valida el `.fbk`
      y restaura a scratch con el mismo `gbak` contando las filas (coinciden).
- [x] El charset de cada base creada por la imagen se verifica
      (`rdb$character_set_name`) y cada fila usa un usuario dedicado
      (`odin_matrix`) con su password.
- [x] `tests/test_backup_integration.py` y `tests/test_notify_integration.py`
      usan el helper y ya no requieren `gbak` en el host ni duplican el código
      Docker.
- [x] El docstring del test documenta imágenes/digests, convenciones por
      familia (2.5 `ISC_PASSWORD`; 5.x `FIREBIRD_ROOT_PASSWORD`/
      `FIREBIRD_DATABASE`) y que no se requiere `gbak` en el host.
- [x] Evidencia: filas 2.5, 3.0 y 5.0 en verde; fila 6 en verde si la imagen
      funciona (skip justificado en caso contrario).
- [x] Gates en verde: `uv run pytest` (con integración), `uv run ruff check
      src/odin tests`, `uv run mypy src/odin`.

## Implementation Steps

1. Crear `tests/firebird_container.py`: dataclass de imagen por familia
   (`legacy` vs moderna), `FirebirdContainer` con `start/remove`,
   `wait_ready`, `isql`, `count_rows`, `connection`, `port`, `gbak_wrapper` y
   manejo de errores; sin dependencia de `gbak` del host.
2. Crear `tests/test_firebird_matrix.py` con las filas 2.5/3.0/5.0/6,
   `@pytest.mark.integration`, skip seguro y aserciones de respaldo, restore,
   filas y charset.
3. Adaptar `tests/test_backup_integration.py` y
   `tests/test_notify_integration.py` para usar el helper (y el wrapper de
   `gbak` de la imagen), eliminando el código Docker duplicado y el skip por
   `gbak` ausente.
4. Correr la matriz completa, registrar evidencia (versión de gbak de cada
   imagen, tamaño del `.fbk`, filas restauradas) y dejarla en el docstring del
   test.
5. Correr los gates y documentar decisiones en "Decisions & Trade-offs".

## Testing Strategy

- `uv run pytest tests/test_firebird_matrix.py -q -m integration` →
  evidencia de las 4 filas (o skip justificado de la 6).
- `uv run pytest tests/test_backup_integration.py
  tests/test_notify_integration.py -q` → adaptaciones verdes sin `gbak` host.
- `uv run pytest` completo + `uv run ruff check src/odin tests` +
  `uv run mypy src/odin`.
- Sin Docker o sin red para imágenes: la suite salta sin fallar (skip-safe).

## Dependencies

- `tests/test_backup_integration.py` (Item 018) y
  `tests/test_notify_integration.py` (Item 047) como patrón a unificar.
- `src/odin/backup.py` (`BackupExecutor`, precedencia de `gbak_path`),
  `src/odin/config.py` (`DatabaseConfig`) e `src/odin/gbak_finder.py`.
- Docker operativo y las imágenes `jacobalberty/firebird:2.5-sc`,
  `firebirdsql/firebird:3.0.9`, `firebirdsql/firebird:latest` y
  `firebirdsql/firebird:6-snapshot` (esta última best-effort).

## Decisions & Trade-offs

- **Wrapper `docker exec` en vez de extracción de `bin/`+`lib/`+ICU**: el
  wrapper (`docker exec --user root <contenedor> <gbak de la imagen> "$@"`)
  usa exactamente el binario de la familia de la imagen, sin copiar binarios
  ni resolver `LD_LIBRARY_PATH`/ICU/plugins; el `work_dir` se monta en la misma
  ruta absoluta host↔contenedor para que los argumentos que pasa
  `BackupExecutor` sean válidos en ambos lados, y la cadena de conexión es
  `localhost/3050:<ruta>` desde dentro del propio contenedor. La extracción
  selectiva se descartó por fragilidad y por no aportar nada al objetivo
  (probar el `gbak` de la familia). En Windows el wrapper se escribe como
  `.cmd` con la misma mecánica.
- **`--user root` en `docker exec`**: los binarios corren como root dentro del
  contenedor para poder escribir el `.fbk` en el bind mount (propiedad del
  usuario del host); el archivo queda 0644 y `BackupExecutor` lo valida como
  legible. Sin root, el usuario de la imagen podría no poder escribir el mount.
- **Sin `gbak` en el host**: se retiró el `skipif(GBACK is None)` de los tests
  adaptados; el único requisito es Docker. En este host los casos Firebird de
  `test_notify_integration.py` pasan de skip a ejecutarse (y se sumó el de
  `test_backup_integration.py`), por eso la suite pasa de 623+5 a 629+3.
- **`isql` no basta con el código de salida**: Firebird 3.0 devuelve 0 ante un
  fallo de conexión (y 5.0 devuelve 1), así que `wait_ready` exige que
  `SELECT 1 FROM rdb$database` devuelva el valor `1` y `isql` falla si el
  stderr trae `Statement failed`/`-SQL error code`. Sin esto, la espera de
  arranque pasaba de inmediato y el seed/count corrían contra un servidor aún
  no disponible (race detectado al ejecutar la matriz).
- **`gbak -Z` (mayúscula) para la versión**: `-z` no existe como switch de
  versión en `gbak`; en Firebird 5 `-Z` imprime la versión pero sale con
  código 1, por eso `gbak_version()` tolera el código y busca la línea
  `version`.
- **Fila 3.0 incluida**: la imagen ya estaba descargada y comparte toda la
  familia moderna con la 5.0, así que suma evidencia para el Item 070 a costo
  casi nulo; la fila 4.0 no se incluye (imagen no descargada) y el Item 070 la
  registrará como best-effort si el costo es bajo.
- **Usuario dedicado por fila**: se crea `odin_matrix` con
  `FIREBIRD_USER`/`FIREBIRD_PASSWORD` (la imagen crea la base con ese dueño);
  el respaldo se autentica con él y el restore usa `SYSDBA` (dueño de la base
  scratch). La variante de charset usa `FIREBIRD_DATABASE_DEFAULT_CHARSET` en
  la familia moderna (`WIN1252`, `ISO8859_1`, `UTF8`); la familia 2.5 crea la
  base con `DEFAULT CHARACTER SET UTF8` fijo y el helper lo rechaza si se pide
  un charset, con el test verificando el UTF8 observado.
- **Override por variable de entorno**: cada fila acepta
  `ODIN_FIREBIRD_<CLAVE>_IMAGE` y el test de respaldo conserva
  `ODIN_FIREBIRD_IMAGE`, para reproducir la matriz con otras etiquetas/digests
  sin tocar el código.

**Evidencia:** `uv run pytest tests/test_firebird_matrix.py -q -m integration
-s` → **4 passed in 18.35 s**:
`[matriz Firebird 25] jacobalberty/firebird:2.5-sc gbak version
LI-V2.5.9.27139 Firebird 2.5 charmap=UTF8 .fbk=2560 B restore=3/3`
`[matriz Firebird 30] firebirdsql/firebird:3.0.9 gbak version
LI-V3.0.9.33560 Firebird 3.0 charmap=WIN1252 .fbk=1536 B restore=3/3`
`[matriz Firebird 50] firebirdsql/firebird:latest gbak version
LI-V5.0.4.1812 Firebird 5.0 charmap=ISO8859_1 .fbk=1536 B restore=3/3`
`[matriz Firebird 60] firebirdsql/firebird:6-snapshot gbak version
LI-T6.0.0.2177 Firebird 6.0 charmap=UTF8 .fbk=3584 B restore=3/3`.
Adaptaciones: `uv run pytest tests/test_backup_integration.py
tests/test_notify_integration.py -q` → **4 passed in 8.00 s** (antes: 2 passed
+ 2 skipped por `gbak` ausente). Gates: `uv run pytest -q` → **629 passed + 3
skipped in 43.62 s**; `uv run ruff check src/odin tests` → All checks passed;
`uv run mypy src/odin` → Success: no issues found in 19 source files.

## Prerequisites

- Docker operativo en el host; sin Docker los tests se saltan sin fallar.
- `gbak` del host **no** requerido (se usa el de la imagen vía `docker exec`).
- `docs/aide/progress.md` debe reflejar el avance (📋 → 🚧 → ✅) al completar.
- Al finalizar, actualizar `docs/aide/progress.md` con la evidencia del item.

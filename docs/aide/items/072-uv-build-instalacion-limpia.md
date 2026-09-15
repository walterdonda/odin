# Item 072: `uv build` e instalación limpia con `uv tool install` en Linux LTS

## Description

Verificar el **empaquetado real** de ODIN y la instalación desde cero en Linux
LTS, y dejar la verificación automatizada en la suite:

1. `uv build` produce wheel y sdist. El wheel contiene el paquete `odin/`
   (`src/odin`), el entry point `odin = odin.cli:main` y la metadata
   (`Requires-Python: >=3.14` y las dependencias de runtime, sin las de
   desarrollo); el sdist contiene las fuentes (`src/odin/...`).
2. El wheel se instala con `uv tool install` en un entorno **limpio y
   aislado**: `HOME`, `UV_TOOL_DIR`, `UV_TOOL_BIN_DIR` y `UV_CACHE_DIR`
   temporales, fuera del venv del repo. Desde ahí:
   - `odin --version` → `odin 0.1.0`;
   - `odin validate --config examples/config.linux.json` y
     `examples/config.windows.json` → exit 0;
   - `odin service status` sin servicio → exit 0 con `no instalado` (o la
     advertencia del gestor cuando no hay bus systemd).
3. Capa de **Linux LTS limpio en contenedor** (`ubuntu:24.04` + `uv` + el
   wheel copiado, sin el repo) que repite la instalación y el CLI, y un
   escenario end-to-end `odin run` con Firebird de la matriz y fases externas
   contra el `tests/smtp_catcher.py` y el sshd ephemeral de la suite.

Archivos:

- `tests/test_packaging.py`: metadata (sin build) + contenido de wheel/sdist
  y `uv tool install` limpio en host, **gated** por `ODIN_BUILD_ARTIFACTS=1`
  (skip por defecto por ser lento).
- `tests/test_packaging_integration.py` (`@pytest.mark.integration`,
  skip-safe): capa de contenedor limpio. La instalación + CLI corre siempre
  que haya Docker/`uv`; el end-to-end `odin run` queda gated por
  `ODIN_CLEAN_CONTAINER_E2E=1` (patrón de las demos de los Items 057/066)
  por requerir socket Docker y binarios del host montados en el contenedor.
- `tests/packaging_tools.py`: helper compartido `build_artifacts()` que corre
  `uv build --out-dir` una vez y devuelve las rutas de wheel y sdist.
- `tests/sshd_ephemeral.py`: extracción del sshd in-process de
  `tests/test_transfer_integration.py` (mismo comportamiento, host de bind
  configurable) para reutilizarlo sin duplicar código; el test original pasa
  a importarlo.
- `tests/smtp_catcher.py`: parámetro `host` opcional (default
  `127.0.0.1`, sin cambio de comportamiento) para que los contenedores
  alcancen el catcher vía `--network host`.

Config del escenario end-to-end (JSON puro derivado de
`examples/config.linux.json`): base de la matriz 5.0 (`FirebirdContainer` con
`gbak_path` al wrapper `docker exec` del helper), un servidor SFTP ephemeral
(password, `accept-new`), SMTP al catcher (`starttls: false`), compresión 7z
y `local.work_dir` montado en la misma ruta absoluta en el contenedor limpio
y en el de Firebird. El test afirma: exit 0 de `odin run`, `.fbk` y `.fbk.7z`
generados y válidos, filas restauradas contadas por `isql`, archivo en el
destino SFTP y correo capturado sin secretos.

`dist/`, `build/` y `wheels/` ya están en `.gitignore`: no hay cambios de
empaquetado pendientes (versión `0.1.0`; el salto a `1.0.0` es el Item 077).

## Acceptance Criteria

- [x] `tests/test_packaging.py`: metadata del `pyproject.toml`
      (`requires-python == ">=3.14"`, entry point `odin = odin.cli:main`,
      nombre/versión) sin build; con `ODIN_BUILD_ARTIFACTS=1`, `uv build`
      produce wheel y sdist verificados (contenido del wheel, `METADATA`,
      `entry_points.txt`, sdist con `src/odin`) e instalación limpia con
      `uv tool install` (HOME/tool dirs temporales) que ejecuta
      `odin --version` = `odin 0.1.0`, `odin validate` sobre los dos ejemplos
      y `odin service status` sin servicio (exit 0).
- [x] `tests/test_packaging_integration.py` (`@integration`, skip-safe sin
      Docker/`uv`): instalación + CLI dentro de `ubuntu:24.04` limpio desde
      el wheel; y escenario gated `ODIN_CLEAN_CONTAINER_E2E=1` con Firebird
      de la matriz + SFTP ephemeral + SMTP catcher y `odin run` completo.
- [x] `tests/sshd_ephemeral.py` extraído y `tests/test_transfer_integration.py`
      adaptado sin cambios de comportamiento (mismos 3 tests verdes).
- [x] `tests/smtp_catcher.py` acepta `host` opcional con default
      `127.0.0.1` (los consumidores actuales no cambian).
- [x] Evidencia ejecutada en Linux: build + instalación limpia en host, capa
      de contenedor y e2e gated, registradas en "Decisions & Trade-offs".
- [x] `README.md`/`docs/service.md` sin pasos fuera de la documentación para
      la instalación desde cero (si el flujo revela un hueco documental, se
      corrige en este item).
- [x] Gates en verde: `uv run pytest`, `uv run ruff check src/odin tests`,
      `uv run mypy src/odin`,
      `ODIN_BUILD_ARTIFACTS=1 uv run pytest tests/test_packaging.py -q`.

## Implementation Steps

1. Crear `tests/packaging_tools.py` con `build_artifacts(out_dir)` (uv build,
   localización del wheel/sdist, error claro si `uv` falta) y los helper de
   entorno limpio compartidos.
2. Crear `tests/test_packaging.py` con la metadata sin build y los tests
   gated por `ODIN_BUILD_ARTIFACTS=1` (wheel, sdist, `uv tool install`
   limpio + CLI).
3. Extraer `tests/sshd_ephemeral.py` desde `tests/test_transfer_integration.py`
   (host de bind configurable) y adaptar el test original; sumar `host` a
   `tests/smtp_catcher.py`.
4. Crear `tests/test_packaging_integration.py`: capa de contenedor limpio
   (ubuntu:24.04 + uv + wheel) y escenario gated de `odin run` con la matriz
   Firebird + SSH/SMTP de la suite.
5. Correr la evidencia completa (host, contenedor y e2e gated), corregir los
   huecos documentales que aparezcan y anotar decisiones/evidencia.
6. Actualizar `docs/aide/progress.md` (📋 → 🚧 → ✅) con la evidencia.

## Testing Strategy

- `ODIN_BUILD_ARTIFACTS=1 uv run pytest tests/test_packaging.py -q` → build,
  contenido y `uv tool install` limpio en host.
- `uv run pytest tests/test_packaging_integration.py -q -m integration` →
  contenedor limpio; con `ODIN_CLEAN_CONTAINER_E2E=1` también el end-to-end.
- `uv run pytest tests/test_transfer_integration.py -q` → sin regresión tras
  la extracción del sshd.
- `uv run pytest` + `uv run ruff check src/odin tests` +
  `uv run mypy src/odin` → gates del repositorio.
- Sin Docker o sin `uv`: los tests de contenedor se saltan con motivo (no
  fallan); `ODIN_BUILD_ARTIFACTS` sin definir salta el build por defecto.

## Dependencies

- Item 069/070: `tests/firebird_container.py` (wrapper `docker exec`, puerto
  dinámico, `isql`) y las imágenes de la matriz.
- Item 037: `tests/test_transfer_integration.py` (`_EphemeralSshd` a
  extraer) e Item 047/056: `tests/smtp_catcher.py`.
- Item 071: `scripts/verify.py` (los tests nuevos quedan cubiertos por los
  gates; no se modifica el script).
- `pyproject.toml`/`uv` (build con hatchling), Docker operativo.

## Decisions & Trade-offs

- **Hueco real encontrado y corregido — `tzdata`**: el contenedor limpio
  `ubuntu:24.04` no trae `/usr/share/zoneinfo`, y `odin validate` sobre el
  ejemplo (scheduler habilitado con un job) moría con
  `ZoneInfoNotFoundError: 'No time zone found with key UTC'`. En `uv.lock`
  `tzdata` solo aparecía como transitiva con marker `sys_platform == 'win32'`,
  insuficiente para Linux mínimo (y en Windows tampoco hay datos IANA del SO).
  Se agregó `tzdata>=2026.3` como dependencia directa (`uv add tzdata`, lock
  actualizado), `tests/test_packaging.py` afirma `Requires-Dist: tzdata` y la
  tabla de dependencias del README documenta la razón. Con datos del SO,
  `zoneinfo` sigue usando el sistema (el paquete es solo fallback).
- **Servidores de prueba alcanzables desde el contenedor**: en este host
  (Docker Desktop + WSL) `--network host` no comparte el loopback real: un
  listener en `127.0.0.1` no es alcanzable, uno en `0.0.0.0` sí. Se agregó
  `host` opcional a `SmtpCatcher` (default `127.0.0.1`) y se extrajo
  `tests/sshd_ephemeral.py` (`EphemeralSshd` con el mismo parámetro);
  `test_transfer_integration.py` importa el helper sin cambios de
  comportamiento y solo el escenario de contenedor bindea `0.0.0.0` con
  credenciales de prueba.
- **Binarios del host montados como staging, sin apt**: el contenedor limpio
  recibe `uv` y `docker` copiados por el test (`shutil.which(...).resolve()`,
  binarios estáticos) y el socket Docker solo en el e2e gated. Es
  infraestructura de test, no parte de la instalación: el `uv tool install`
  del wheel es el que se verifica. Se descartó `apt-get install` por peso,
  red y dependencia del espejo.
- **Intérprete y caché sin escribir en el host**: se monta el directorio de
  Pythons gestionados del host read-only (`UV_PYTHON_INSTALL_DIR`,
  `UV_PYTHON_DOWNLOADS=manual`) y el contenedor usa su propia caché efímera
  (`/tmp/uv-cache`): el `uv tool install` no descarga CPython (~50 s menos) y
  no deja archivos root-owned en la caché del host. Si no hay un 3.14
  gestionado, el test cae al camino con descarga.
- **e2e gated por `ODIN_CLEAN_CONTAINER_E2E=1`**: la instalación + CLI corre
  como `@integration` normal (skip-safe); el `odin run` completo necesita el
  socket Docker y los binarios del host dentro del contenedor, así que sigue
  el patrón de demos gated de los Items 057/066 y mantiene acotada la suite
  por defecto. La evidencia local se ejecutó con la variable activa.
- **Limpieza del `work_dir`**: los artefactos los crea root dentro del
  contenedor; el test hace `chown -R <uid>:<gid>` del `work_dir` al terminar
  para que el `tmp_path` de pytest se pueda limpiar (un `chmod` no bastaba:
  los directorios root-owned rompían `rm -rf` y generaban un `PytestWarning`).
- **Metadatos del wheel vs. versión**: la versión sigue en `0.1.0` (el salto
  a `1.0.0`, `CHANGELOG` y tag son el Item 077); el test deriva el
  `dist-info` del propio wheel en lugar de fijar el nombre.
- **Divergencia con la marcha de la spec**: el `odin service status` dentro
  del contenedor no imprime `no instalado` (no hay bus systemd), imprime la
  advertencia del gestor; por eso las dos variantes afirman exit 0 + el
  encabezado `Servicio del SO` en lugar del texto exacto, que sí aparece en
  la corrida de host con systemd real.

**Evidencia:** `ODIN_BUILD_ARTIFACTS=1 uv run pytest tests/test_packaging.py
-q` → **4 passed in 10.09 s** (build, wheel/sdist, `uv tool install` limpio,
`odin 0.1.0`, ambos `validate` exit 0 y `service status` exit 0); sin la
variable → 1 passed + 3 skipped. `uv run pytest
tests/test_packaging_integration.py -q -m integration` → **1 passed + 1
skipped in 20.93 s**; con `ODIN_CLEAN_CONTAINER_E2E=1` → **2 passed in 62.56
s** (e2e solo: 1 passed in 32.92 s) con `.fbk`/`.fbk.7z` reales, restore de
3/3 filas con el `gbak` de la imagen, archivo en el SFTP ephemeral idéntico
al local, correo `[ODIN] ÉXITO` con `matrix50` y AUTH LOGIN del catcher.
`uv run pytest tests/test_transfer_integration.py
tests/test_notify_integration.py tests/test_backup_integration.py -q` → **7
passed in 13.74 s** (sin regresión por la extracción del sshd). Wheel
`odin-0.1.0-py3-none-any.whl` con `odin/cli.py`, `entry_points.txt` (`odin =
odin.cli:main`), `Requires-Python: >=3.14` y `Requires-Dist` de runtime
(paramiko, py7zr, apscheduler, tzdata); sdist con `src/odin/cli.py`.
`pyproject.toml` + `uv.lock` con `tzdata>=2026.3` (finding del contenedor
limpio).

## Prerequisites

- **Servicios requeridos**: Docker operativo (imagen `ubuntu:24.04` y la
  imagen 5.0 de la matriz, ya descargadas en este host); `uv` en el `PATH`;
  sin servicios externos de red salvo la descarga de dependencias/Python del
  `uv tool install` (caché de uv compartida como optimización).
- **Configuración de entorno**: `ODIN_BUILD_ARTIFACTS=1` para el build y
  `ODIN_CLEAN_CONTAINER_E2E=1` para el end-to-end; `ODIN_FIREBIRD_50_IMAGE`
  permite fijar la imagen de la matriz. Sin secretos reales (credenciales de
  prueba del catcher/sshd).
- **Checklist de validación manual**:
  - [ ] `uv build` produce `odin-0.1.0-py3-none-any.whl` y
        `odin-0.1.0.tar.gz` con el contenido esperado.
  - [ ] `uv tool install` limpio + `odin --version`/`validate`/`service status`
        sin pasos fuera de la documentación.
  - [ ] Contenedor `ubuntu:24.04` limpio repite la instalación y el CLI.
  - [ ] `odin run` gated genera `.fbk`, `.fbk.7z`, deja el archivo en el
        SFTP ephemeral y entrega el correo al catcher.
- **Resultados esperados**: wheel/sdist correctos, `odin 0.1.0` instalado en
  entorno aislado, evidencia de corrida end-to-end en Linux LTS limpio y
  tests nuevos verdes.
- `docs/aide/progress.md` debe reflejar el avance (📋 → 🚧 → ✅) al completar.
- Al finalizar, actualizar `docs/aide/progress.md` con la evidencia del item.

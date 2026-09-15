# Item 063: `odin service status` completo (gestor de servicios + estado del scheduler)

## Description

Completar `odin service status` para que refleje el estado real del servicio
residente en ambas plataformas, componiendo la consulta al gestor del SO con
el estado del scheduler que ya renderiza `render_service_status`
(`scheduler.py:696`).

- Nuevo render puro `render_platform_status(status, scheduler_report,
  warning=None)` en `src/odin/service/base.py` (re-exportado por
  `odin.service`): encabezado del servicio del SO a partir de un
  `ServiceStatus` (Item 059) y, debajo, la sección del scheduler ya
  renderizada (última ejecución por job, próximo disparo, salud y errores
  recientes). La función es solo presentación: no consulta nada por su cuenta.
  - Gestor `systemd`/`windows` visible en el encabezado.
  - `installed=False` → "no instalado" + sugerencia
    `odin service install --config <ruta>`.
  - `installed=True, running=False` → "instalado y detenido" + sugerencia
    `odin service start`; muestra arranque automático y política de reinicio
    cuando el gestor los informa.
  - `installed=True, running=True` → "en ejecución" con el detalle y las
    banderas del gestor.
  - `warning` (consulta al gestor fallida) → advertencia en el encabezado y la
    sección del scheduler igual se imprime.
- `_cmd_service_status` (`cli.py:778-792`) cablea manager + store: carga la
  configuración (como hoy), construye el gestor con
  `create_service_manager(config.config_path.absolute())`
  (`manager_factory` inyectable para tests), consulta `status()` y compone
  `render_platform_status(service_status, render_service_status(state_result),
  warning=...)`.
- La consulta al gestor es tolerante: un `ServiceError` (systemctl/SCM caído,
  plataforma no soportada) **no** rompe el comando — se reporta como
  advertencia y el exit code sigue siendo 0 mientras la configuración cargue y
  el estado se pueda interpretar (o su ausencia se informe). Sigue siendo una
  consulta de solo lectura.
- `--config` continúa opcional en el parser, resuelto con
  `_resolve_config_source`; sin fuente o con config inválida → 2 (igual que
  hoy).

## Acceptance Criteria

- [x] `render_platform_status` es una función pura en `odin/service/base.py`
      re-exportada por `odin.service`; cubre las combinaciones: no instalado,
      instalado y detenido, instalado y corriendo, instalado y corriendo con
      estado obsoleto (pid muerto) y sin archivo de estado, siempre con la
      sección del scheduler visible.
- [x] No instalado sugiere `odin service install`; detenido sugiere
      `odin service start`; el encabezado nombra el gestor
      (`systemd`/`windows`) y, cuando aplica, `auto_start` y
      `restart_on_failure`.
- [x] Con `warning` (fallo del gestor) el encabezado reporta la advertencia y
      el estado del scheduler se imprime igual.
- [x] `odin service status --config <válida>` con gestor doble: exit 0,
      encabezado del gestor + estado del scheduler en stdout; sin secretos.
- [x] Un gestor que lanza `ServiceError` → exit 0 con la advertencia en el
      encabezado (nunca exit 1).
- [x] Sin `--config`/`ODIN_CONFIG` o con configuración inválida → 2 (sin
      cambios respecto del Item 053).
- [x] `manager_factory` es inyectable; el default es
      `create_service_manager` y no toca pywin32/systemctl en los tests.
- [x] Tests en `tests/test_service_status.py` (gestor falso + estados fixture
      por combinación) y en `tests/test_cli.py` (cableado, advertencia sin
      fallo, exit 0, sin secretos).
- [x] Gates del item en verde: `uv run pytest tests/test_service_status.py
      tests/test_cli.py`, `uv run ruff check src/odin tests`,
      `uv run mypy src/odin`.

## Implementation Steps

1. Escribir `render_platform_status` en `src/odin/service/base.py` (y
   re-exportarlo en `__init__.py`/`__all__`).
2. Cablear `_cmd_service_status` en `cli.py` (import de `create_service_manager`
   y del render, alias `ManagerFactory`, captura de `ServiceError`).
3. Escribir `tests/test_service_status.py` con un gestor falso y estados
   fixture (`StateLoadResult` con `state`/`stale`/`warning`) para cada
   combinación.
4. Ampliar `tests/test_cli.py` con el cableado CLI (gestor doble 0 y con
   error).
5. Correr los gates del item y documentar decisiones/evidencia.

## Testing Strategy

- `uv run pytest tests/test_service_status.py tests/test_cli.py -q`.
- Gestor falso que devuelve `ServiceStatus` prefabricados (no instalado,
  detenido, corriendo con/sin banderas) o lanza `ServiceError`; el estado del
  scheduler se construye con `SchedulerStateStore`/`StateLoadResult` (fixtures
  del estilo de `tests/test_cli.py::_write_service_state`), incluidos los casos
  obsoleto (`pid` muerto) y sin archivo.
- Se verifica por ausencia la no impresión de secretos en la salida compuesta.
- No se ejecuta `systemctl` ni SCM real: la verificación de integración queda
  en el Item 066.
- Gates: ruff y mypy completos.

## Dependencies

- Item 059 (`ServiceStatus`/`create_service_manager`) y Items 060-061
  (gestores concretos).
- Item 053 (`render_service_status`, `load_state`, `state_path`).
- Item 062 (helpers de CLI para el gestor) — no bloqueante: si se implementa
  primero, reutiliza los mismos helpers.
- Insumos: `queue-007.md` (Lote B) y `docs/aide/roadmap.md` (Etapa 7).

## Decisions & Trade-offs

- **El render compone texto, no consulta el scheduler**: `render_platform_status`
  recibe el bloque del scheduler ya renderizado por
  `odin.scheduler.render_service_status` en lugar de un `StateLoadResult`. Así
  `odin.service.base` (contrato portable) no importa `odin.scheduler` (que
  arrastra APScheduler y la configuración) y la sección existente se reutiliza
  literal, sin duplicar formato ni divergir del `service status` del Item 053.
- **Fallo del gestor = advertencia, no error**: la consulta al SO puede fallar
  legítimamente (systemctl ausente, SCM sin permisos), pero el estado del
  scheduler en `work_dir` sigue siendo útil. El error se captura en el CLI
  (`ServiceError` → `warning`) y la firma del render lo expone como parámetro:
  el comando conserva el exit 0 de "consulta de solo lectura" y nunca deja de
  imprimir la sección del scheduler.
- **La detección de estado obsoleto sigue siendo del scheduler**:
  `load_state`/`pid_is_alive` (Item 052) son la única fuente de verdad del
  estado del scheduler; el render del SO no la recalcula. Cuando el gestor dice
  "en ejecución" y el estado tiene el pid muerto, la salida muestra ambas
  capas y la inconsistencia queda visible sin que el comando falle.
- **Banderas del gestor en tres estados**: `auto_start`/`restart_on_failure`
  en `None` se presentan como "desconocido" (no como "no"): el gestor puede no
  informarlas (Item 060) y no se inventa un `False`.
- **`config.config_path.absolute()` también en `status`**: igual que en
  `install` (Item 062), el gestor exige una ruta absoluta y `load_config` no
  la resuelve si el `--config` vino relativo; `.absolute()` no toca symlinks y
  coincide con el `base_dir` que usa el parseo.

**Evidencia:** `uv run pytest tests/test_service_status.py -q` → **7 passed**
(las cinco combinaciones del render: no instalado → `install`, detenido →
`start`, corriendo con banderas y detalle, corriendo con estado obsoleto,
advertencia con sección del scheduler, estado sin estado y banderas
`None` → "desconocido"); `uv run pytest tests/test_cli.py -q` → **94 passed**
(6 casos nuevos: composición completa sin secretos, no instalado, detenido,
estado obsoleto con gestor corriendo, error del gestor → 0 con advertencia y
ruta absoluta al gestor); `uv run pytest tests/test_service_status.py
tests/test_cli.py tests/test_service_base.py -q` → **120 passed**;
`uv run ruff check src/odin tests` → All checks passed; `uv run mypy src/odin`
→ Success: no issues found in 18 source files.

## Prerequisites

- No requiere systemd ni Windows: el gestor es un doble inyectado.
- `docs/aide/progress.md` debe reflejar el avance del entregable `status`
  completo al completar.
- Al finalizar, actualizar `docs/aide/progress.md` con la evidencia del item.

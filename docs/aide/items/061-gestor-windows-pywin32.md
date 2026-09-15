# Item 061: Gestor Windows sobre pywin32 con arranque automático y reinicio ante caída

## Description

Implementar `src/odin/service/windows.py` con imports de pywin32 **perezosos y
guardados**: un helper `_import_win32()` que importa `servicemanager`,
`win32service`, `win32serviceutil` y `winerror` dentro de la operación y lanza
`ServiceUnsupportedError` con mensaje accionable fuera de Windows (o sin
pywin32), de modo que `import odin.service.windows` funcione limpio en Linux y
solo falle al usarse.

- `OdinWindowsService`: subclase real de
  `win32serviceutil.ServiceFramework` con `_svc_name_ = "odin"`,
  `_svc_display_name_` y `_svc_description_`. Como la base solo existe en
  Windows, la clase se construye **perezosamente** con `_service_class()` (una
  sola vez, cacheada) y se publica como atributo de módulo vía
  `__getattr__` (PEP 562): el string registrado por el SCM
  (`odin.service.windows.OdinWindowsService`) resuelve en Windows y en Linux
  da `ServiceUnsupportedError`. Métodos:
  - `__init__(args)`: inicializa la base real (registra el control handler),
    crea el `threading.Event` de finalización y el runtime perezoso.
  - `SvcStop`: reporta `SERVICE_STOP_PENDING`, llama al `stop()` del runner
    compartido (Protocol `ServiceRuntime` del Item 059; el `ServiceRunner`
    real llega en el Item 065 vía factory diferida `_build_runtime`) y espera
    la detención limpia (`Event`, timeout) antes de reportar
    `SERVICE_STOPPED`.
  - `SvcDoRun`: resuelve la config fijada en la instalación
    (`win32serviceutil.GetServiceCustomOption(name, "ConfigPath")`, con
    `ODIN_CONFIG` como respaldo de diagnóstico), construye el runtime con la
    factory y llama a `run()`; los errores se registran con
    `servicemanager.LogErrorMsg` sin escapar.
- `WindowsServiceManager`:
  - `install(spec)`: `win32serviceutil.InstallService(<class string>,
    spec.name, spec.display_name, startType=SERVICE_AUTO_START si auto_start
    else SERVICE_DEMAND_START, userName=spec.account, description=...)`; fija
    la config con `SetServiceCustomOption(name, "ConfigPath", <absoluta>)`; y
    si `restart_on_failure`, `win32service.ChangeServiceConfig2` con
    `SERVICE_CONFIG_FAILURE_ACTIONS` y una acción `SC_ACTION_RESTART` a
    `restart_delay_seconds * 1000` ms con reset periódico.
  - `uninstall()` (stop tolerante + `RemoveService`, idempotente),
    `start()`/`stop()` con espera de la transición por polling de
    `QueryServiceStatus` (timeout y `sleep` inyectables, tolerantes a
    "ya corriendo"/"no activo"), y `status()` mapeando
    `QueryServiceStatus`/`QueryServiceConfig` (corriendo/detenido, auto-start,
    política de reinicio) a `ServiceStatus`; servicio ausente →
    `ServiceStatus(installed=False)`.
  - La ejecución en Windows real queda para el runbook de la Etapa 8 (Item
    009): acá se cubre con `unittest.mock`/dobles de los módulos de pywin32.

## Acceptance Criteria

- [x] `import odin.service.windows` funciona en Linux sin pywin32; usar
      `WindowsServiceManager(...).status()` (o cualquier operación) lanza
      `ServiceUnsupportedError` con mensaje que indique Windows + pywin32.
- [x] `OdinWindowsService` expone `_svc_name_ == "odin"`,
      `_svc_display_name_` y `_svc_description_`; se construye con los módulos
      inyectados (dobles) y su `__init__` inicializa la base real/doble.
- [x] `install` llama a `InstallService` con el class string
      `odin.service.windows.OdinWindowsService`, el nombre/display name del
      spec, `startType=SERVICE_AUTO_START` (o `SERVICE_DEMAND_START` con
      `auto_start=False`), `description` y `userName=account` cuando aplica;
      persiste `ConfigPath` absoluto con `SetServiceCustomOption`.
- [x] `install` con `restart_on_failure=True` aplica failure actions:
      `ChangeServiceConfig2(..., SERVICE_CONFIG_FAILURE_ACTIONS, ...)` con
      `Actions=[(SC_ACTION_RESTART, 5000)]`, `ResetPeriod` periódico y sin
      comando/reboot; con `restart_on_failure=False` no llama a
      `ChangeServiceConfig2` de failure actions.
- [x] `uninstall` es idempotente (stop + remove; servicio ausente no falla) y
      libera los handles del SCM.
- [x] `start`/`stop` esperan la transición (`QueryServiceStatus` polling con
      `sleep` inyectable) y devuelven mensaje; el timeout lanza
      `ServiceError`; "ya en ejecución"/"no activo" no son error.
- [x] `status()` mapea `SERVICE_RUNNING`/`SERVICE_STOPPED`,
      `SERVICE_AUTO_START` y la política de failure actions a `ServiceStatus`;
      servicio ausente (`ERROR_SERVICE_DOES_NOT_EXIST`) →
      `ServiceStatus(installed=False)`.
- [x] `SvcStop` reporta `SERVICE_STOP_PENDING`, llama a `runtime.stop()` una
      vez, espera la finalización y reporta `SERVICE_STOPPED`; `SvcDoRun`
      construye el runtime con la config persistida en la instalación y no
      propaga excepciones.
- [x] Tests en `tests/test_service_windows.py`: import perezoso en Linux sin
      pywin32, ciclo de vida completo con dobles de
      `win32serviceutil`/`win32service`/`servicemanager` (parámetros de
      `InstallService`, estructura de failure actions, espera en stop, mapeo
      de `status`, uninstall idempotente) y `SvcStop`/`SvcDoRun` con runtime
      doble.
- [x] Gates del item en verde: `uv run pytest tests/test_service_windows.py`,
      `uv run ruff check src/odin tests`, `uv run mypy src/odin`.

## Implementation Steps

1. Escribir `src/odin/service/windows.py`: constantes (`SERVICE_CLASS_STRING`,
   `CONFIG_OPTION = "ConfigPath"`, periodos y timeout de espera),
   `_import_win32`, `_service_class` + `__getattr__`, `_build_runtime`
   (import diferido de `odin.service.runner`, Item 065),
   `OdinWindowsService` y `WindowsServiceManager`.
2. Ampliar el override de mypy en `pyproject.toml` (el Item 059 lo crea) para
   `odin.service.windows` con `disallow_subclassing_any = false`.
3. Escribir `tests/test_service_windows.py` con dobles de los módulos de
   pywin32 y un runtime doble.
4. Correr los gates del item y documentar decisiones/evidencia.

## Testing Strategy

- `uv run pytest tests/test_service_windows.py -q`.
- Dobles: `types.SimpleNamespace`/clases mínimas para
  `win32serviceutil` (`ServiceFramework`, `InstallService`,
  `SetServiceCustomOption`, `GetServiceCustomOption`, `RemoveService`,
  `StartService`, `StopService`, `QueryServiceStatus`,
  `QueryServiceConfig`), `win32service` (constantes y
  `OpenSCManager`/`OpenService`/`ChangeServiceConfig2`/
  `CloseServiceHandle`) y `servicemanager`; se inyectan monkeypatching
  `odin.service.windows._import_win32` y reseteando la clase cacheada.
- El error real sin pywin32 se cubre sin dobles en Linux
  (`ServiceUnsupportedError`).
- `start`/`stop` usan listas de estatus prefabricadas y un `sleep` doble que
  cuenta llamadas (sin esperas reales); el timeout se verifica con una lista
  que nunca llega al estado objetivo.
- La ejecución en Windows real no se ejecuta: se documenta como runbook de la
  Etapa 8 (Item 009).
- Gates: ruff y mypy completos.

## Dependencies

- Item 059 (contrato base y overrides de mypy).
- El `ServiceRunner` del Item 065 no existe todavía: se consume vía el
  Protocol `ServiceRuntime` y la factory diferida `_build_runtime`, que el
  Item 065 cablea definitivamente.
- Insumos: `queue-007.md` (Lote A) y `docs/aide/roadmap.md` (Etapa 7).

## Decisions & Trade-offs

- **Clase de servicio perezosa vía `get_service_class()` + `__getattr__`**
  (PEP 562): `win32serviceutil.ServiceFramework` solo existe en Windows, así
  que no se puede declarar la subclase al importar el módulo. El string que el
  SCM registra (`odin.service.windows.OdinWindowsService`) resuelve por
  `__getattr__` en Windows y lanza `ServiceUnsupportedError` en Linux. La
  subclase dinámica necesita `# type: ignore[valid-type, misc]` más el override
  `disallow_subclassing_any = false` (creado en el Item 059).
- **La config se fija con `SetServiceCustomOption`/`GetServiceCustomOption`**,
  no con argumentos en el `ImagePath`: PythonService.exe no propaga de forma
  confiable los argumentos del binario del servicio a `sys.argv` (limitación
  documentada de pywin32); la opción `ConfigPath` en
  `HKLM\SYSTEM\CurrentControlSet\Services\odin\Parameters` es el mecanismo que
  el propio pywin32 recomienda para persistir propiedades del servicio. Se
  persiste también `WorkingDirectory` y `ODIN_CONFIG` queda como respaldo de
  diagnóstico.
- **Failure actions con las claves reales de pywin32**:
  `{"ResetPeriod": 86400, "RebootMsg": "", "Command": "", "Actions":
  [(SC_ACTION_RESTART, restart_delay_seconds * 1000)]}` (el parser C espera
  `Command`, no `lpCommand`) más `SERVICE_CONFIG_FAILURE_ACTIONS_FLAG = True`
  para que el SCM encolare el reinicio también ante fallos que no son caída
  dura. La verificación en Windows real sigue en el runbook de la Etapa 8.
- **`SvcStop` espera con un `threading.Event`** que `SvcDoRun` setea en su
  `finally`, con tope `STOP_WAIT_TIMEOUT_SECONDS`, en lugar de asumir que
  `runtime.stop()` bloquea hasta el cierre: la interfaz `ServiceRuntime` no
  promete bloqueo y el SCM exige reportar `SERVICE_STOPPED` solo cuando el
  proceso terminó de verdad.
- **`_build_runtime` con `importlib` + `cast`**: el `ServiceRunner` real llega
  en el Item 065; el import diferido mantiene mypy verde y el error explícito
  si el runner no está disponible en la instalación. La factory es inyectable
  por instancia para los tests.
- **El manager adopta `spec.name` tras instalar**: `start`/`stop`/`status`
  operan sobre `self._name` (por defecto `odin`); tras un `install` con otro
  nombre, las operaciones siguientes apuntan al servicio realmente creado.

**Evidencia:** `uv run pytest tests/test_service_windows.py -q` → **31
passed** (import perezoso sin pywin32, parámetros de `InstallService`,
estructura de failure actions con el retardo configurado, uninstall
idempotente, espera y timeout de start/stop, mapeo de `status` con y sin
política de reinicio, `SvcDoRun`/`SvcStop` con runtime doble y despacho real
desde `create_service_manager`); `uv run pytest
tests/test_service_base.py tests/test_service_linux.py
tests/test_service_windows.py -q` → **73 passed**; suite completa `uv run
pytest -q` → **568 passed + 3 skipped**; `uv run ruff check src/odin tests` →
All checks passed; `uv run mypy src/odin` → Success: no issues found in 18
source files.

## Prerequisites

- No requiere pywin32 ni Windows: todos los caminos se cubren con dobles; el
  paquete debe importar limpio en Linux.
- `docs/aide/progress.md` debe reflejar el avance del entregable Windows al
  completar.
- Al finalizar, actualizar `docs/aide/progress.md` con la evidencia del item.

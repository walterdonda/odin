# Item 059: Contrato portable del modo servicio y despacho por plataforma

## Description

Crear el subpaquete `src/odin/service/` con `__init__.py` y `base.py`: el
contrato del modo residente independiente del SO que consumirán los gestores
Linux (Item 060), Windows (Item 061), la CLI (Item 062) y el runner compartido
(Item 065).

`base.py` define:

- `ServiceSpec` (frozen dataclass): nombre del servicio (`odin` por defecto),
  display name, descripción, `config_path` **absoluta y validada** (el servicio
  corre desatendido: no puede depender del cwd ni de `ODIN_CONFIG`),
  `executable` y argv derivado (`service run --config <ruta>`), `working_dir`
  (default: el directorio de la config), `auto_start=True`,
  `restart_on_failure=True`, `restart_delay_seconds=5`, `account=None` (cuenta
  por defecto de la plataforma).
- `ServiceStatus` (frozen dataclass): `installed`, `running`, `auto_start` /
  `restart_on_failure` opcionales, `manager` (`systemd`/`windows`) y `detail`.
- `ServiceManagerKind` (StrEnum: `systemd`, `windows`).
- Excepciones `ServiceError`, `ServiceUnsupportedError`,
  `ServiceNotInstalledError`.
- `ServiceManager` (ABC): `install(spec)`, `uninstall()`, `start()`, `stop()`,
  `status()`; cada operación de ciclo de vida devuelve el mensaje a imprimir.
- `ServiceRuntime` (Protocol): `run() -> int` / `stop() -> None`, el contrato
  que el `SvcDoRun`/`SvcStop` de Windows (Item 061) espera del runner
  compartido (Item 065).
- `create_service_manager(config_path, *, platform=sys.platform, **kwargs)`:
  despacha a `linux.py`/`windows.py` con **import diferido** (importar
  `odin.service` en Linux no debe tocar pywin32; `odin.service.windows` se
  construye sin importar pywin32 hasta que se usa) y lanza
  `ServiceUnsupportedError` con mensaje claro en plataformas fuera de alcance.
- `ensure_absolute_config_path(...)`: validación compartida de la ruta de
  configuración (relativa → `ServiceError` con mensaje claro).

`status()` de un servicio no instalado devuelve `ServiceStatus(installed=False)`
(no es error). Sumar a `pyproject.toml` los módulos de pywin32 (`win32api`,
`win32con`, `win32service`, `win32serviceutil`, `servicemanager`, `winerror`)
en `[[tool.mypy.overrides]]` con `ignore_missing_imports = true` para que
`uv run mypy src/odin` siga verde en Linux.

## Acceptance Criteria

- [x] Existen `src/odin/service/__init__.py` y `src/odin/service/base.py`; el
      paquete expone `ServiceSpec`, `ServiceStatus`, `ServiceManagerKind`,
      `ServiceManager`, `ServiceRuntime`, `ServiceError`,
      `ServiceUnsupportedError`, `ServiceNotInstalledError`,
      `create_service_manager` y `ensure_absolute_config_path`.
- [x] `ServiceSpec` valida `config_path` absoluta (relativa → `ServiceError`
      con la ruta en el mensaje), exige `executable` no vacío y
      `restart_delay_seconds >= 0`; normaliza `working_dir` (default: el
      directorio de `config_path`).
- [x] `ServiceSpec.argv` devuelve `(executable, "service", "run", "--config",
      <ruta absoluta>)`; el modo servicio queda autocontenido (sin depender del
      cwd ni de variables de entorno).
- [x] `create_service_manager` despacha por `platform` inyectable: `linux*` →
      `LinuxServiceManager`, `win32` → `WindowsServiceManager` (sin importar
      pywin32), cualquier otra → `ServiceUnsupportedError` con mensaje
      accionable.
- [x] `ServiceStatus(installed=False)` es el estado por defecto de un servicio
      no instalado (campos opcionales en `None`, sin excepción).
- [x] `ServiceManager` es un ABC no instanciable directamente; `ServiceRuntime`
      es un Protocol con `run()`/`stop()`.
- [x] `pyproject.toml` declara los módulos de pywin32 en
      `[[tool.mypy.overrides]]` con `ignore_missing_imports = true` (y
      `disallow_subclassing_any = false` para `odin.service.windows`, que el
      Item 061 creará).
- [x] Tests en `tests/test_service_base.py`: despacho por plataforma (módulos
      `odin.service.linux`/`odin.service.windows` inyectados en `sys.modules`
      mientras el Item 060/061 no existen; cada gestor agrega después su test
      de despacho real), rechazo de `config_path` relativa, `status()` no
      instalado, round-trip de las dataclasses, ABC no instanciable y ausencia
      de pywin32 en `sys.modules` tras importar el paquete.
- [x] Gates del item en verde: `uv run pytest tests/test_service_base.py`,
      `uv run ruff check src/odin tests`, `uv run mypy src/odin`.

## Implementation Steps

1. Crear `src/odin/service/base.py` con las constantes (`SERVICE_NAME =
   "odin"`, display name, descripción, `DEFAULT_RESTART_DELAY_SECONDS = 5`),
   las dataclasses, los errores, el ABC, el Protocol, la validación de ruta y
   `create_service_manager` con imports diferidos.
2. Crear `src/odin/service/__init__.py` que re-exporte la API pública de
   `base.py` (docstring del subpaquete incluido) sin importar los gestores.
3. Agregar a `pyproject.toml` el override de mypy para los módulos de pywin32.
4. Escribir `tests/test_service_base.py` cubriendo los criterios.
5. Correr los gates del item y documentar decisiones/evidencia en
   "Decisions & Trade-offs".

## Testing Strategy

- `uv run pytest tests/test_service_base.py -q`.
- Casos: `create_service_manager(..., platform="linux")` devuelve el manager
  del módulo inyectado con la ruta/kwargs correctos; `platform="win32"` hace lo
  propio sin importar pywin32; `platform="darwin"` lanza
  `ServiceUnsupportedError`; `ServiceSpec(config_path=Path("rel.json"))` lanza
  `ServiceError`; round-trip de igualdad de `ServiceSpec`/`ServiceStatus`;
  un manager doble mínimo implementa el ABC y su `status()` no instalado
  devuelve `installed=False`; `ServiceManager()` directo lanza `TypeError`;
  `import odin.service` no agrega `win32serviceutil` a `sys.modules`.
- El módulo doble de `sys.modules` registra los argumentos del constructor: el
  despacho (ruta + kwargs) se verifica sin necesitar los gestores reales; la
  integración del despacho con `LinuxServiceManager`/`WindowsServiceManager`
  reales se agrega en los Items 060 y 061.
- Gates: ruff y mypy completos.

## Dependencies

- Ninguna de código: es el primer item de la Etapa 7. Insumos: `queue-007.md`
  (Lote A), `docs/aide/roadmap.md` (Etapa 7) y los patrones de dataclasses/
  StrEnum/ABC de `scheduler.py`/`config.py`.

## Decisions & Trade-offs

- **Despacho con `importlib.import_module` + `cast` en vez de `from
  odin.service.linux import ...`**: el import diferido sigue siendo el mismo,
  pero la resolución dinámica evita que mypy analice módulos específicos de
  plataforma (y que falle mientras el Item 060/061 todavía no crearon los
  gestores). El costo es que el nombre de la clase no se verifica
  estáticamente: lo cubren los tests de despacho real de los Items 060/061
  más el error explícito (`ServiceUnsupportedError`) si el módulo no expone la
  clase.
- **`working_dir` opcional con `resolved_working_dir`**: en vez de mutar el
  dataclass para rellenar el default con el directorio del JSON, se expone una
  propiedad. Mantiene la anotación `Path | None` honesta y evita que los
  consumidores vean un `Path` que puede ser `None` (o un `None` que en
  realidad siempre está resuelto).
- **Tests de despacho con módulos dobles**: en el Item 059 los gestores
  concretos todavía no existen; inyectar módulos dobles en `sys.modules`
  verifica el contrato de despacho (ruta + kwargs + clase por plataforma) sin
  crear esqueletos desechables, y los Items 060/061 agregan el test contra los
  gestores reales.
- **Overrides de mypy de pywin32 ya en este item**: aunque `windows.py` llega
  en el Item 061, declarar los módulos como `Any` acá deja el gate de mypy
  verde en Linux desde el primer item del lote (sin pywin32 instalado).

**Evidencia:** `uv run pytest tests/test_service_base.py -q` → **19 passed**;
`uv run ruff check src/odin tests` → All checks passed; `uv run mypy src/odin`
→ Success: no issues found in 16 source files. El paquete importa sin pywin32
(`test_package_import_is_lazy_about_pywin32`) y el despacho `platform="win32"`
no agrega `win32serviceutil`/`win32service` a `sys.modules`.

## Prerequisites

- No requiere servicios externos ni pywin32 instalado: todo se cubre con
  imports diferidos y un manager doble en los tests.
- `docs/aide/progress.md` debe reflejar el inicio del item (Etapa 7 ya está
  🚧; se agrega la evidencia del entregable al completar).
- Al finalizar, actualizar `docs/aide/progress.md` con la evidencia del item.

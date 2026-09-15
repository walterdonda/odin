# Item 060: Gestor Linux con `deploy/odin.service` y ciclo de vida `systemctl`

## Description

Implementar `src/odin/service/linux.py` (`LinuxServiceManager`) y la unit de
referencia `deploy/odin.service`.

- Función pura `render_unit(spec)` que genera la unit:
  `[Unit] Description`, `After=network-online.target` (y
  `Wants=network-online.target`); `[Service] Type=simple`,
  `ExecStart=<executable> service run --config <ruta absoluta>` (sin shell,
  con quoting seguro de systemd), `WorkingDirectory`,
  `Restart=always`/`no` según `restart_on_failure`,
  `RestartSec=<restart_delay_seconds>`, `User=`/`Group=` opcionales
  (`account="usuario"` o `"usuario:grupo"`); `[Install]
  WantedBy=multi-user.target`.
- `install(spec)`: si hay permisos (root o unit dir escribible) escribe la
  unit, corre `systemctl daemon-reload` y `systemctl enable <unit>` (si
  `auto_start`); si no, **no escribe nada** y devuelve la guía exacta con la
  unit renderizada y los comandos a ejecutar (decisión a documentar:
  instalación real con permisos, guía textual sin ellos). Es idempotente:
  reemplaza la unit existente.
- `uninstall()` idempotente: `systemctl stop` (tolera no activo), `disable`
  (tolera no encontrado), borra la unit si existe y `daemon-reload`.
- `start()`/`stop()` vía `systemctl`, con errores encapsulados en
  `ServiceError` con el stderr.
- `status()` parsea `systemctl show <unit> --property=...` hacia
  `ServiceStatus`: `LoadState=not-found` → `installed=False`; `ActiveState ==
  "active"` → `running`; `UnitFileState == "enabled"` → `auto_start`;
  `Restart` (`always`/`on-failure`) → `restart_on_failure`; `detail` con los
  valores crudos. `is-active`/`is-enabled` quedan como respaldo documentado.
- El ejecutor de `systemctl` es inyectable (`runner: Callable[[Sequence[str]],
  CommandResult]`) para tests sin systemd real; el runner por defecto usa
  `subprocess.run` con timeout y `FileNotFoundError` → `ServiceError`
  accionable. `unit_dir` y `can_write_unit` también son inyectables.
- `deploy/odin.service` se versiona como referencia con placeholders
  documentados (ruta del ejecutable y de la config, usuario/permisos).

## Acceptance Criteria

- [x] `render_unit(spec)` incluye `[Unit]`, `[Service]`, `[Install]`,
      `Type=simple`, `After=network-online.target`, `WantedBy=multi-user.target`
      y `Restart=always`/`RestartSec=5` por defecto; `ExecStart` empieza con una
      ruta absoluta y contiene `service run --config <config absoluta>`, sin
      `sh -c`; los paths con espacios quedan quotados y siguen siendo absolutos.
- [x] Con `account="odin"` la unit agrega `User=odin`; con
      `account="odin:backup"` agrega `User=odin` y `Group=backup`.
- [x] `install` con permisos: escribe la unit en `unit_dir`, ejecuta
      `daemon-reload` y `enable` en ese orden y devuelve un mensaje con la ruta;
      con `auto_start=False` no ejecuta `enable`.
- [x] `install` sin permisos: no escribe ningún archivo, ejecuta cero comandos
      `systemctl` y devuelve la guía con la unit renderizada y los comandos
      exactos (`daemon-reload`/`enable`/`start`).
- [x] `uninstall` es idempotente (stop + disable + borrar + `daemon-reload`;
      segunda invocación con unit ausente no falla y no lanza), `start`/`stop`
      ejecutan el comando correcto y un fallo de `systemctl` se propaga como
      `ServiceError` con el stderr del runner.
- [x] `status()` mapea las combinaciones active/inactive × enabled/disabled y
      `installed=False` cuando el show reporta `LoadState=not-found`; la
      política de reinicio se refleja en `restart_on_failure`.
- [x] `deploy/odin.service` existe, es una unit de referencia válida con
      placeholders documentados y sin credenciales.
- [x] Tests en `tests/test_service_linux.py`: render (claves obligatorias,
      `ExecStart` absoluto y sin shell, quoting), secuencia de comandos de
      install/uninstall con runner doble, instalación sin permisos → guía sin
      escrituras, idempotencia de uninstall, mapeo de `status` y error de
      `systemctl` propagado.
- [x] Gates del item en verde: `uv run pytest tests/test_service_linux.py`,
      `uv run ruff check src/odin tests`, `uv run mypy src/odin`.

## Implementation Steps

1. Escribir `src/odin/service/linux.py`: constantes (`UNIT_NAME =
   "odin.service"`, `SYSTEMD_UNIT_DIR = Path("/etc/systemd/system")`),
   `CommandResult`, `render_unit`, quoting de argumentos, runner por defecto y
   `LinuxServiceManager`.
2. Escribir `deploy/odin.service` (referencia con placeholders comentados).
3. Escribir `tests/test_service_linux.py` con un runner doble que registra
   comandos y respuestas configurables, y `unit_dir=tmp_path` para los caminos
   de escritura.
4. Correr los gates del item y documentar decisiones/evidencia.

## Testing Strategy

- `uv run pytest tests/test_service_linux.py -q`.
- El runner doble devuelve `CommandResult` por comando y registra la secuencia;
  `can_write_unit=lambda: False` cubre la guía sin tocar el sistema; el
  `unit_dir` apunta a `tmp_path` para verificar bytes escritos.
- `status()` se cubre con salidas de `systemctl show` fixture
  (`LoadState`, `ActiveState`, `UnitFileState`, `Restart`), incluida la
  variante `not-found`.
- No se ejecuta `systemctl` real: la verificación de integración de la unit
  llega en el Item 066.
- Gates: ruff y mypy completos.

## Dependencies

- Item 059 (contrato `ServiceSpec`/`ServiceStatus`/`ServiceManager`).
- Insumos: `queue-007.md` (Lote A) y `docs/aide/roadmap.md` (Etapa 7).

## Decisions & Trade-offs

- **Sin permisos: guía, no error**: `install` devuelve la unit renderizada y
  los comandos (`daemon-reload`/`enable`/`start`) en vez de lanzar
  `ServiceError`. Un operador que olvidó `sudo` recibe la ruta y el contenido
  exactos para completar la instalación, y el comando sigue devolviendo 0
  (la CLI del Item 062 imprime la guía). La escritura real se reserva a root o
  a un `unit_dir` escribible.
- **`render_unit` exige ejecutable absoluto**: systemd rechaza un
  `ExecStart` relativo, así que la validación vive en el render (no en
  `ServiceSpec`, que es compartido con Windows y no usa el ejecutable). El
  error es un `ServiceError` claro con el valor recibido.
- **`status()` sobre `systemctl show` con respaldo**: `show
  --property=LoadState,ActiveState,UnitFileState,Restart` da las cuatro
  señales en una sola llamada; si una versión vieja de systemd no soporta
  `--property` (respuesta vacía) se consulta `is-active` e `is-enabled`
  (cuyo estado es el stdout, no el returncode). `Restart=always`/`on-failure`
  → `restart_on_failure=True`, `no` → `False`, ausente → `None`; `auto_start`
  queda `None` si `UnitFileState` no se pudo leer (no se inventa `False`).
- **`uninstall` con `daemon-reload` condicional**: solo recarga systemd si
  detuvo, deshabilitó o borró algo; la segunda invocación no toca el sistema y
  devuelve "no estaba instalado". Así la idempotencia no depende de un
  `systemctl` disponible para una operación vacía.
- **La unit de referencia deja `User=`/`Group=` comentados**: activarlos exige
  que la cuenta exista en el host; un `systemd-analyze verify` (Item 066) no
  debe fallar por un usuario de ejemplo. El render sí los emite cuando el
  `ServiceSpec` trae `account`.

**Evidencia:** `uv run pytest tests/test_service_linux.py tests/test_service_base.py -q`
→ **42 passed** (23 del gestor Linux: render con quoting y cuenta, install con
y sin permisos, uninstall idempotente, start/stop, mapeo de `status` con y sin
respaldo, runner por defecto sin systemctl y despacho real desde
`create_service_manager`); `uv run ruff check src/odin tests` → All checks
passed; `uv run mypy src/odin` → Success: no issues found in 17 source files.
`deploy/odin.service` versionado con placeholders documentados y sin
credenciales.

## Prerequisites

- No requiere systemd en el host: todo el ciclo de vida se cubre con el runner
  doble; `deploy/odin.service` solo se valida estructuralmente acá (el
  `systemd-analyze verify` queda en el Item 066).
- `docs/aide/progress.md` debe reflejar el avance del entregable Linux al
  completar.
- Al finalizar, actualizar `docs/aide/progress.md` con la evidencia del item.

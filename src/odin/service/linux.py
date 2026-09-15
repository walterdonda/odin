"""Gestor del modo servicio de ODIN en Linux sobre systemd (Item 060).

Contenido:

- ``render_unit(spec)``: función pura que genera la unit de systemd para un
  ``ServiceSpec`` (``[Unit]``/``[Service]``/``[Install]``, ``Type=simple``,
  ``After=network-online.target``, ``ExecStart=<ejecutable> service run
  --config <ruta>`` sin shell, ``WorkingDirectory``, ``Restart=always`` o
  ``Restart=no`` según ``restart_on_failure``, ``RestartSec`` y
  ``User=``/``Group=`` opcionales desde ``account`` —``usuario`` o
  ``usuario:grupo``—). Los argumentos se quotan con la sintaxis de systemd
  (comillas dobles solo cuando hacen falta).
- ``LinuxServiceManager``: ciclo de vida sobre ``systemctl``.
  - ``install(spec)``: con permisos (root o unit dir escribible) escribe la
    unit, ejecuta ``daemon-reload`` y ``enable`` (si ``auto_start``); sin
    permisos **no escribe nada** y devuelve la guía exacta con la unit
    renderizada y los comandos a ejecutar. Decisión del item: la instalación
    real se hace con permisos y, sin ellos, el comando es una guía textual
    (un servicio de sistema no debe fallar con una excepción cuando el
    operador simplemente no usó ``sudo``).
  - ``uninstall()`` idempotente (stop + disable tolerantes + borrar la unit +
    ``daemon-reload`` solo si hubo algo que desinstalar), ``start()``/``stop()``
    y ``status()`` parseando ``systemctl show
    --property=LoadState,ActiveState,UnitFileState,Restart`` (con
    ``is-active``/``is-enabled`` como respaldo si ``show`` no aporta estado,
    p. ej. systemd viejo) hacia ``ServiceStatus``.
- El ejecutor de ``systemctl`` es inyectable (``runner``), igual que
  ``unit_dir`` y ``can_write_unit``: los tests corren sin systemd real. El
  runner por defecto usa ``subprocess.run`` con timeout y convierte
  ``FileNotFoundError`` (systemd ausente) en ``ServiceError`` accionable.

``deploy/odin.service`` versiona la unit de referencia con placeholders
documentados; ``odin service install`` genera la misma estructura con las rutas
reales.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from odin.service.base import (
    ServiceError,
    ServiceManager,
    ServiceManagerKind,
    ServiceNotInstalledError,
    ServiceSpec,
    ServiceStatus,
    ensure_absolute_config_path,
)

__all__ = [
    "SYSTEMD_UNIT_DIR",
    "UNIT_NAME",
    "CommandResult",
    "LinuxServiceManager",
    "render_unit",
]

SYSTEMD_UNIT_DIR = Path("/etc/systemd/system")
UNIT_NAME = "odin.service"
DEFAULT_TIMEOUT_SECONDS = 30.0

# systemctl show devuelve LoadState=not-found (returncode 0) para una unidad
# inexistente; igual se reconocen estos fragmentos por si una versión antigua
# falla con error.
_MISSING_UNIT_FRAGMENTS = (
    "not found",
    "not be found",
    "does not exist",
    "not loaded",
    "not-found",
)

# Valores de ``Restart=`` que implican reinicio ante caída (política de
# ``restart_on_failure``); ``no`` la desactiva y el resto se reporta como None.
_RESTART_POLICIES = frozenset({"always", "on-failure", "on-abnormal", "on-abort", "on-watchdog"})


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Resultado de una invocación de ``systemctl`` (doble inyectable)."""

    returncode: int
    stdout: str = ""
    stderr: str = ""


SystemctlRunner = Callable[[Sequence[str]], CommandResult]


def _quote_argument(argument: str) -> str:
    """Quoting de systemd: sin comillas si el valor es seguro, doble comilla si no."""
    safe = bool(argument) and all(char.isalnum() or char in "/._-:@+=" for char in argument)
    if safe:
        return argument
    escaped = argument.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _parse_properties(text: str) -> dict[str, str]:
    """Parsea la salida ``Clave=Valor`` de ``systemctl show``."""
    properties: dict[str, str] = {}
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip():
            properties[key.strip()] = value.strip()
    return properties


def _restart_policy(value: str) -> bool | None:
    """Traduce ``Restart=`` de systemd a ``restart_on_failure``."""
    if not value:
        return None
    return value in _RESTART_POLICIES


def render_unit(spec: ServiceSpec) -> str:
    """Renderiza la unit de systemd para ``spec`` (función pura, sin I/O).

    ``ExecStart`` apunta al ejecutable con los argumentos del modo servicio
    (``service run --config <ruta absoluta>``): no se usa shell, así el
    ``ExecStart`` no depende de comillas de shell ni de variables de entorno.
    systemd exige una ruta absoluta en ``ExecStart``: un ejecutable relativo
    lanza ``ServiceError``.
    """
    if not Path(spec.executable).is_absolute():
        raise ServiceError(
            "ExecStart requiere una ruta absoluta al ejecutable de ODIN "
            f"(recibido: {spec.executable!r})"
        )
    lines = [
        "[Unit]",
        f"Description={spec.display_name}",
        "After=network-online.target",
        "Wants=network-online.target",
        "",
        "[Service]",
        "Type=simple",
        "ExecStart=" + " ".join(_quote_argument(part) for part in spec.argv),
        f"WorkingDirectory={_quote_argument(str(spec.resolved_working_dir))}",
        "Restart=always" if spec.restart_on_failure else "Restart=no",
        f"RestartSec={spec.restart_delay_seconds}",
    ]
    if spec.account:
        user, _, group = spec.account.partition(":")
        lines.append(f"User={user}")
        if group:
            lines.append(f"Group={group}")
    lines += ["", "[Install]", "WantedBy=multi-user.target", ""]
    return "\n".join(lines)


def _default_runner(args: Sequence[str]) -> CommandResult:
    """Ejecuta ``systemctl`` con timeout y encapsula los fallos de entorno."""
    try:
        completed = subprocess.run(
            ["systemctl", *args],
            capture_output=True,
            text=True,
            timeout=DEFAULT_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ServiceError(
            "no se encontró 'systemctl' en PATH: el modo servicio de Linux requiere systemd"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ServiceError(
            f"'systemctl {' '.join(args)}' excedió el timeout de {DEFAULT_TIMEOUT_SECONDS:.0f} s"
        ) from exc
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _install_guide(unit_text: str, target: Path, *, auto_start: bool) -> str:
    """Guía textual para instalar sin permisos (sin tocar el sistema)."""
    lines = [
        f"Sin permisos para escribir en {target.parent}: la unidad no se instaló.",
        f"Guarde el siguiente contenido en {target}:",
        "",
        unit_text.rstrip("\n"),
        "",
        "Luego ejecute con permisos de administrador:",
        "  sudo systemctl daemon-reload",
    ]
    if auto_start:
        lines.append(f"  sudo systemctl enable {UNIT_NAME}")
    lines.append(f"  sudo systemctl start {UNIT_NAME}")
    return "\n".join(lines)


class LinuxServiceManager(ServiceManager):
    """Ciclo de vida del servicio ODIN en Linux sobre systemd (Item 060)."""

    manager = ServiceManagerKind.SYSTEMD

    def __init__(
        self,
        config_path: Path | str,
        *,
        unit_dir: Path | str = SYSTEMD_UNIT_DIR,
        runner: SystemctlRunner | None = None,
        can_write_unit: Callable[[], bool] | None = None,
    ) -> None:
        self._config_path = ensure_absolute_config_path(config_path)
        self._unit_dir = Path(unit_dir)
        self._runner = runner or _default_runner
        self._can_write_unit = can_write_unit

    @property
    def config_path(self) -> Path:
        """Ruta absoluta del JSON que el servicio usará al arrancar."""
        return self._config_path

    @property
    def unit_path(self) -> Path:
        """Ruta del archivo de la unit que administra el gestor."""
        return self._unit_dir / UNIT_NAME

    # --- helpers internos ---

    def _unit_is_writable(self) -> bool:
        """¿Se puede escribir la unit? (root o directorio de unidades escribible)."""
        if self._can_write_unit is not None:
            return self._can_write_unit()
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            return True
        try:
            return self._unit_dir.exists() and os.access(self._unit_dir, os.W_OK)
        except OSError:
            return False

    def _run(self, args: Sequence[str], *, context: str) -> CommandResult:
        """Ejecuta ``systemctl`` y convierte un fallo en ``ServiceError``."""
        result = self._runner(args)
        if result.returncode == 0:
            return result
        detail = result.stderr.strip() or result.stdout.strip() or "systemctl falló"
        if any(fragment in detail.lower() for fragment in _MISSING_UNIT_FRAGMENTS):
            raise ServiceNotInstalledError(f"{context}: {detail}")
        raise ServiceError(f"{context}: {detail}")

    def _run_tolerating(
        self, args: Sequence[str], *, context: str, tolerated: tuple[str, ...]
    ) -> bool:
        """Ejecuta ``systemctl`` para operaciones idempotentes.

        Devuelve ``True`` si el comando culminó bien, ``False`` si falló con uno
        de los fragmentos tolerados (p. ej. unidad ya detenida o inexistente) y
        lanza ``ServiceError`` en cualquier otro fallo.
        """
        result = self._runner(args)
        if result.returncode == 0:
            return True
        detail = result.stderr.strip() or result.stdout.strip() or "systemctl falló"
        if any(fragment in detail.lower() for fragment in tolerated):
            return False
        if any(fragment in detail.lower() for fragment in _MISSING_UNIT_FRAGMENTS):
            raise ServiceNotInstalledError(f"{context}: {detail}")
        raise ServiceError(f"{context}: {detail}")

    # --- ciclo de vida ---

    def install(self, spec: ServiceSpec) -> str:
        """Instala (o reemplaza) la unit; sin permisos devuelve la guía."""
        unit_text = render_unit(spec)
        target = self.unit_path
        if not self._unit_is_writable():
            return _install_guide(unit_text, target, auto_start=spec.auto_start)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(unit_text, encoding="utf-8")
        except OSError as exc:
            raise ServiceError(f"no se pudo escribir la unit {target}: {exc}") from exc
        self._run(["daemon-reload"], context="systemctl daemon-reload")
        if spec.auto_start:
            self._run(["enable", UNIT_NAME], context=f"systemctl enable {UNIT_NAME}")
        suffix = " y habilitado para el arranque" if spec.auto_start else ""
        return f"Servicio instalado{suffix}: {target}"

    def uninstall(self) -> str:
        """Desinstala la unit; idempotente (segunda corrida no falla)."""
        stopped = self._run_tolerating(
            ["stop", UNIT_NAME],
            context=f"systemctl stop {UNIT_NAME}",
            tolerated=_MISSING_UNIT_FRAGMENTS,
        )
        disabled = self._run_tolerating(
            ["disable", UNIT_NAME],
            context=f"systemctl disable {UNIT_NAME}",
            tolerated=_MISSING_UNIT_FRAGMENTS,
        )
        removed = False
        target = self.unit_path
        if target.exists():
            try:
                target.unlink()
            except OSError as exc:
                raise ServiceError(f"no se pudo eliminar la unit {target}: {exc}") from exc
            removed = True
        if removed or stopped or disabled:
            self._run(["daemon-reload"], context="systemctl daemon-reload")
        if not removed:
            return f"El servicio no estaba instalado en {self._unit_dir}."
        return f"Servicio desinstalado: {target}"

    def start(self) -> str:
        """Arranca el servicio; lanza ``ServiceNotInstalledError`` si no existe."""
        self._run(["start", UNIT_NAME], context=f"systemctl start {UNIT_NAME}")
        return f"Servicio arrancado ({UNIT_NAME})."

    def stop(self) -> str:
        """Detiene el servicio; lanza ``ServiceNotInstalledError`` si no existe."""
        self._run(["stop", UNIT_NAME], context=f"systemctl stop {UNIT_NAME}")
        return f"Servicio detenido ({UNIT_NAME})."

    def status(self) -> ServiceStatus:
        """Consulta el estado real vía ``systemctl show`` (respaldo is-active/enabled)."""
        result = self._runner(
            [
                "show",
                UNIT_NAME,
                "--property=" + ",".join(("LoadState", "ActiveState", "UnitFileState", "Restart")),
                "--no-pager",
            ]
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "systemctl show falló"
            if any(fragment in detail.lower() for fragment in _MISSING_UNIT_FRAGMENTS):
                return ServiceStatus.not_installed(ServiceManagerKind.SYSTEMD, detail=detail)
            raise ServiceError(f"systemctl show {UNIT_NAME}: {detail}")
        properties = _parse_properties(result.stdout)
        load_state = properties.get("LoadState", "")
        if load_state == "not-found":
            return ServiceStatus.not_installed(
                ServiceManagerKind.SYSTEMD, detail="LoadState=not-found"
            )
        active_state = properties.get("ActiveState")
        unit_file_state = properties.get("UnitFileState")
        if active_state is None and unit_file_state is None:
            # systemd sin soporte de --property: respaldo con is-active/is-enabled.
            active_state = self._query_state("is-active")
            unit_file_state = self._query_state("is-enabled")
            if unit_file_state == "not-found":
                return ServiceStatus.not_installed(
                    ServiceManagerKind.SYSTEMD, detail="is-enabled=not-found"
                )
        restart = properties.get("Restart", "")
        detail = (
            f"LoadState={load_state or 'desconocido'}, "
            f"ActiveState={active_state or 'desconocido'}, "
            f"UnitFileState={unit_file_state or 'desconocido'}, "
            f"Restart={restart or 'desconocido'}"
        )
        return ServiceStatus(
            installed=True,
            running=active_state == "active",
            auto_start=(
                None if not unit_file_state else unit_file_state in ("enabled", "enabled-runtime")
            ),
            restart_on_failure=_restart_policy(restart),
            manager=ServiceManagerKind.SYSTEMD,
            detail=detail,
        )

    def _query_state(self, command: str) -> str:
        """Consulta ``systemctl is-active``/``is-enabled`` sin exigir returncode 0.

        ``is-active`` devuelve 3 para "inactive" y ``is-enabled`` 1 para
        "disabled": el estado es el stdout, no el código de salida.
        """
        result = self._runner([command, UNIT_NAME])
        return result.stdout.strip()

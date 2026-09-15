"""Gestor del modo servicio de ODIN en Windows Server sobre pywin32 (Item 061).

Los imports de pywin32 son **perezosos y guardados**: ``_import_win32()``
importa ``servicemanager``, ``win32service``, ``win32serviceutil`` y
``winerror`` dentro de la operación y lanza ``ServiceUnsupportedError`` con un
mensaje accionable fuera de Windows (o sin pywin32). Importar este módulo en
Linux es seguro y no toca pywin32.

Contenido:

- ``OdinWindowsService``: subclase real de
  ``win32serviceutil.ServiceFramework`` (``_svc_name_ = "odin"``,
  ``_svc_display_name_``, ``_svc_description_``). Como la base solo existe en
  Windows, la clase se construye **perezosamente** con ``get_service_class()``
  (cacheada) y se publica como atributo de módulo vía ``__getattr__`` (PEP
  562): el string que el SCM guarda en el registro
  (``odin.service.windows.OdinWindowsService``) resuelve en Windows y en Linux
  lanza ``ServiceUnsupportedError`` al usarse.
  - ``SvcStop``: reporta ``SERVICE_STOP_PENDING``, delega en ``stop()`` del
    runner (``ServiceRuntime``, Item 065) y espera la detención limpia antes de
    reportar ``SERVICE_STOPPED``.
  - ``SvcDoRun``: resuelve la config fijada en la instalación
    (``GetServiceCustomOption(..., "ConfigPath")``, con ``ODIN_CONFIG`` como
    respaldo de diagnóstico), construye el runner con la factory diferida y
    ejecuta ``run()``. Un fallo se registra con ``servicemanager.LogErrorMsg``
    y nunca escapa.
- ``WindowsServiceManager``: ``install`` con ``InstallService`` en arranque
  automático (``SERVICE_AUTO_START``) o manual, ``userName``/``description``,
  la config persistida con ``SetServiceCustomOption`` y —si
  ``restart_on_failure``— failure actions (``SERVICE_CONFIG_FAILURE_ACTIONS``:
  ``SC_ACTION_RESTART`` a ``restart_delay_seconds``, reset periódico) más
  ``SERVICE_CONFIG_FAILURE_ACTIONS_FLAG``; ``uninstall`` idempotente;
  ``start``/``stop`` con espera de la transición por polling de
  ``QueryServiceStatus`` (timeout y ``sleep`` inyectables); ``status`` mapeando
  ``QueryServiceStatus``/``QueryServiceConfig`` a ``ServiceStatus``.

La ejecución en Windows Server real se verifica con el runbook de la Etapa 8
(Item 009); este item cubre todo con dobles de los módulos de pywin32.
"""

from __future__ import annotations

import contextlib
import importlib
import os
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from odin.service.base import (
    DEFAULT_DESCRIPTION,
    DEFAULT_DISPLAY_NAME,
    SERVICE_NAME,
    ServiceError,
    ServiceManager,
    ServiceManagerKind,
    ServiceNotInstalledError,
    ServiceRuntime,
    ServiceSpec,
    ServiceStatus,
    ServiceUnsupportedError,
    ensure_absolute_config_path,
)

__all__ = [
    "CONFIG_OPTION",
    "ENV_CONFIG_VAR",
    "FAILURE_RESET_PERIOD_SECONDS",
    "POLL_INTERVAL_SECONDS",
    "SERVICE_CLASS_STRING",
    "STOP_WAIT_TIMEOUT_SECONDS",
    "WORKING_DIR_OPTION",
    "Win32Modules",
    "WindowsServiceManager",
    "get_service_class",
]

# El SCM guarda este string en el registro (PythonClass) y PythonService.exe lo
# resuelve al arrancar; debe apuntar a la clase publicada por __getattr__.
SERVICE_CLASS_STRING = "odin.service.windows.OdinWindowsService"
CONFIG_OPTION = "ConfigPath"
WORKING_DIR_OPTION = "WorkingDirectory"
ENV_CONFIG_VAR = "ODIN_CONFIG"
FAILURE_RESET_PERIOD_SECONDS = 24 * 60 * 60
STOP_WAIT_TIMEOUT_SECONDS = 30.0
POLL_INTERVAL_SECONDS = 0.5

# Errores del SCM que significan "el servicio no existe" (idempotencia de
# uninstall y mapeo de status a "no instalado").
_MISSING_SERVICE_ERRORS = ("ERROR_SERVICE_DOES_NOT_EXIST", "ERROR_INVALID_NAME")
_MISSING_UNIT_FRAGMENTS = ("does not exist", "not installed", "no existe")


@dataclass(frozen=True, slots=True)
class Win32Modules:
    """Módulos de pywin32 importados en forma perezosa por ``_import_win32``."""

    servicemanager: Any
    win32service: Any
    win32serviceutil: Any
    winerror: Any


def _import_win32() -> Win32Modules:
    """Importa pywin32 o lanza ``ServiceUnsupportedError`` con mensaje accionable."""
    try:
        import servicemanager
        import win32service
        import win32serviceutil
        import winerror
    except ImportError as exc:
        raise ServiceUnsupportedError(
            "el modo servicio de Windows requiere Windows Server con pywin32 "
            f"instalado (el paquete declara 'pywin32; sys_platform == \"win32\"'): {exc}"
        ) from exc
    return Win32Modules(servicemanager, win32service, win32serviceutil, winerror)


def _build_runtime(config_path: Path) -> ServiceRuntime:
    """Factory real del runner compartido del servicio (Item 065, import diferido).

    Importa ``odin.service.runner`` en forma diferida para no cargar el runner
    (ni apscheduler) al importar este módulo; la factory es inyectable a nivel
    de instancia del ``OdinWindowsService`` para los tests.
    """
    module = importlib.import_module("odin.service.runner")
    factory = getattr(module, "ServiceRunner", None)
    if factory is None:
        raise ServiceUnsupportedError(
            "el módulo 'odin.service.runner' no expone ServiceRunner: "
            "instalación de ODIN incompleta"
        )
    return cast(ServiceRuntime, factory(config_path))


def _is_winerror(modules: Win32Modules, exc: BaseException, name: str) -> bool:
    """¿``exc`` es el error del SCM ``name``? (constante del módulo ``winerror``)."""
    code = getattr(modules.winerror, name, None)
    return code is not None and getattr(exc, "winerror", None) == code


def _is_missing_service(modules: Win32Modules, exc: BaseException) -> bool:
    """¿``exc`` significa "servicio inexistente" (o su mensaje lo dice)?"""
    if any(_is_winerror(modules, exc, name) for name in _MISSING_SERVICE_ERRORS):
        return True
    message = str(exc).lower()
    return any(fragment in message for fragment in _MISSING_UNIT_FRAGMENTS)


def _restart_from_failure_actions(failure_actions: Any, win32service: Any) -> bool | None:
    """Traduce las failure actions de pywin32 a ``restart_on_failure``.

    pywin32 devuelve un diccionario con ``Actions`` como secuencia de pares
    ``(tipo, retardo_ms)``; ``None`` si el servicio no tiene configuración de
    reinicio.
    """
    if failure_actions is None:
        return None
    actions = failure_actions.get("Actions", ()) if isinstance(failure_actions, dict) else ()
    for action in actions:
        action_type = (
            action[0] if isinstance(action, (tuple, list)) else getattr(action, "Type", None)
        )
        if action_type == win32service.SC_ACTION_RESTART:
            return True
    return False


def _build_service_class() -> type[Any]:
    """Construye la clase de servicio con la base real de pywin32."""
    modules = _import_win32()
    base = modules.win32serviceutil.ServiceFramework

    # La base es un objeto variable (solo existe con pywin32): mypy no puede
    # validarla como tipo; la subclase es dinámica por diseño y el override de
    # pyproject permite subclassing-any.
    class OdinWindowsService(base):  # type: ignore[valid-type, misc]
        """Servicio ODIN hospedado por PythonService.exe."""

        _svc_name_ = SERVICE_NAME
        _svc_display_name_ = DEFAULT_DISPLAY_NAME
        _svc_description_ = DEFAULT_DESCRIPTION

        def __init__(self, args: Sequence[str]) -> None:
            base.__init__(self, args)
            self._runtime: ServiceRuntime | None = None
            self._runtime_factory: Callable[[Path], ServiceRuntime] = _build_runtime
            self._finished = threading.Event()
            self._stop_wait_seconds = STOP_WAIT_TIMEOUT_SECONDS

        def SvcStop(self) -> None:
            """Pide la detención del runner y espera su cierre limpio."""
            self.ReportServiceStatus(modules.win32service.SERVICE_STOP_PENDING)
            runtime = self._runtime
            if runtime is not None:
                runtime.stop()
            self._finished.wait(timeout=self._stop_wait_seconds)
            self.ReportServiceStatus(modules.win32service.SERVICE_STOPPED)

        def SvcDoRun(self) -> None:
            """Ejecuta el runner con la config fijada en la instalación."""
            try:
                config_path = self._resolve_config_path()
                if config_path is None:
                    self._log_error(
                        "no se encontró la ruta de configuración del servicio "
                        f"(opción '{CONFIG_OPTION}' o {ENV_CONFIG_VAR}): reinstale con "
                        "'odin service install --config <ruta absoluta>'"
                    )
                    return
                self._chdir_if_configured()
                self._runtime = self._runtime_factory(config_path)
                exit_code = self._runtime.run()
                if exit_code != 0:
                    self._log_error(f"el servicio terminó con exit code {exit_code}")
            except Exception as exc:  # noqa: BLE001 - un servicio no debe morir con traceback
                self._log_error(f"fallo del servicio: {type(exc).__name__}: {exc}")
            finally:
                self._finished.set()

        def _resolve_config_path(self) -> Path | None:
            modules = _import_win32()
            raw = modules.win32serviceutil.GetServiceCustomOption(
                self._svc_name_, CONFIG_OPTION, None
            ) or os.environ.get(ENV_CONFIG_VAR)
            if not raw:
                return None
            return ensure_absolute_config_path(str(raw))

        def _chdir_if_configured(self) -> None:
            modules = _import_win32()
            raw = modules.win32serviceutil.GetServiceCustomOption(
                self._svc_name_, WORKING_DIR_OPTION, None
            )
            if raw:
                try:
                    os.chdir(raw)
                except OSError as exc:
                    self._log_error(f"no se pudo cambiar al directorio de trabajo {raw!r}: {exc}")

        def _log_error(self, message: str) -> None:
            with contextlib.suppress(Exception):
                _import_win32().servicemanager.LogErrorMsg(message)

    OdinWindowsService.__name__ = "OdinWindowsService"
    OdinWindowsService.__qualname__ = "OdinWindowsService"
    OdinWindowsService.__module__ = __name__
    return OdinWindowsService


_odin_service_class: type[Any] | None = None


def get_service_class() -> type[Any]:
    """Devuelve ``OdinWindowsService``, construyéndola la primera vez.

    Construir la clase importa pywin32, por lo que en Linux lanza
    ``ServiceUnsupportedError``.
    """
    global _odin_service_class
    if _odin_service_class is None:
        _odin_service_class = _build_service_class()
    return _odin_service_class


def __getattr__(name: str) -> Any:
    """Publica ``OdinWindowsService`` sin importar pywin32 al cargar el módulo."""
    if name == "OdinWindowsService":
        return get_service_class()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class WindowsServiceManager(ServiceManager):
    """Ciclo de vida del servicio ODIN en Windows Server sobre pywin32 (Item 061)."""

    manager = ServiceManagerKind.WINDOWS

    def __init__(
        self,
        config_path: Path | str,
        *,
        name: str = SERVICE_NAME,
        timeout_seconds: float = STOP_WAIT_TIMEOUT_SECONDS,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._config_path = ensure_absolute_config_path(config_path)
        self._name = name
        self._timeout_seconds = timeout_seconds
        self._sleep = sleep or time.sleep

    @property
    def config_path(self) -> Path:
        """Ruta absoluta del JSON que el servicio usará al arrancar."""
        return self._config_path

    @property
    def name(self) -> str:
        """Nombre del servicio administrado (``odin`` por defecto)."""
        return self._name

    # --- helpers internos ---

    def _apply_failure_actions(self, spec: ServiceSpec, modules: Win32Modules) -> None:
        """Configura el reinicio automático ante caída (failure actions del SCM)."""
        win32service = modules.win32service
        actions = {
            "ResetPeriod": FAILURE_RESET_PERIOD_SECONDS,
            "RebootMsg": "",
            "Command": "",
            "Actions": [(win32service.SC_ACTION_RESTART, spec.restart_delay_seconds * 1000)],
        }
        hscm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ALL_ACCESS)
        try:
            hs = win32service.OpenService(
                hscm,
                spec.name,
                win32service.SERVICE_CHANGE_CONFIG | win32service.SERVICE_START,
            )
            try:
                win32service.ChangeServiceConfig2(
                    hs, win32service.SERVICE_CONFIG_FAILURE_ACTIONS, actions
                )
                win32service.ChangeServiceConfig2(
                    hs, win32service.SERVICE_CONFIG_FAILURE_ACTIONS_FLAG, True
                )
            finally:
                win32service.CloseServiceHandle(hs)
        finally:
            win32service.CloseServiceHandle(hscm)

    def _wait_for_state(self, modules: Win32Modules, target: int, action: str) -> None:
        """Espera (polling) a que el servicio alcance ``target`` o falla por timeout."""
        win32service = modules.win32service
        deadline = time.monotonic() + self._timeout_seconds
        while True:
            state = modules.win32serviceutil.QueryServiceStatus(self._name)[1]
            if state == target:
                return
            if target == win32service.SERVICE_RUNNING and state == win32service.SERVICE_STOPPED:
                raise ServiceError(
                    f"el servicio '{self._name}' no pudo arrancar: quedó detenido"
                )
            if time.monotonic() >= deadline:
                raise ServiceError(
                    f"timeout de {self._timeout_seconds:.0f} s esperando que el servicio "
                    f"'{self._name}' termine de {action} (estado {state})"
                )
            self._sleep(POLL_INTERVAL_SECONDS)

    def _query_config(self, modules: Win32Modules) -> tuple[bool | None, bool | None]:
        """Consulta arranque automático y política de reinicio del servicio."""
        win32service = modules.win32service
        hscm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
        try:
            hs = win32service.OpenService(hscm, self._name, win32service.SERVICE_QUERY_CONFIG)
            try:
                config = win32service.QueryServiceConfig(hs)
                auto_start = config[1] == win32service.SERVICE_AUTO_START
                failure_actions = win32service.QueryServiceConfig2(
                    hs, win32service.SERVICE_CONFIG_FAILURE_ACTIONS
                )
                restart_on_failure = _restart_from_failure_actions(failure_actions, win32service)
                return auto_start, restart_on_failure
            finally:
                win32service.CloseServiceHandle(hs)
        finally:
            win32service.CloseServiceHandle(hscm)

    # --- ciclo de vida ---

    def install(self, spec: ServiceSpec) -> str:
        """Instala el servicio con arranque automático, config fija y reinicio."""
        modules = _import_win32()
        start_type = (
            modules.win32service.SERVICE_AUTO_START
            if spec.auto_start
            else modules.win32service.SERVICE_DEMAND_START
        )
        try:
            modules.win32serviceutil.InstallService(
                SERVICE_CLASS_STRING,
                spec.name,
                spec.display_name,
                startType=start_type,
                userName=spec.account,
                description=spec.description,
            )
            modules.win32serviceutil.SetServiceCustomOption(
                spec.name, CONFIG_OPTION, str(spec.config_path)
            )
            modules.win32serviceutil.SetServiceCustomOption(
                spec.name, WORKING_DIR_OPTION, str(spec.resolved_working_dir)
            )
            if spec.restart_on_failure:
                self._apply_failure_actions(spec, modules)
        except Exception as exc:  # noqa: BLE001 - pywin32 reporta errores variados
            raise ServiceError(
                f"no se pudo instalar el servicio '{spec.name}': {exc}"
            ) from exc
        self._name = spec.name
        auto = "arranque automático" if spec.auto_start else "arranque manual"
        restart = "reinicio ante caída activado" if spec.restart_on_failure else "sin reinicio"
        return (
            f"Servicio '{spec.name}' instalado ({auto}, {restart}). "
            f"Config: {spec.config_path}"
        )

    def uninstall(self) -> str:
        """Detiene y elimina el servicio; idempotente si no está instalado."""
        modules = _import_win32()
        try:
            modules.win32serviceutil.StopService(self._name)
        except Exception as exc:  # noqa: BLE001 - stop tolerante (no activo o ausente)
            if not (
                _is_winerror(modules, exc, "ERROR_SERVICE_NOT_ACTIVE")
                or _is_missing_service(modules, exc)
            ):
                raise ServiceError(
                    f"no se pudo detener el servicio '{self._name}': {exc}"
                ) from exc
        try:
            modules.win32serviceutil.RemoveService(self._name)
        except Exception as exc:  # noqa: BLE001 - remove idempotente
            if _is_missing_service(modules, exc):
                return f"El servicio '{self._name}' no estaba instalado."
            raise ServiceError(
                f"no se pudo desinstalar el servicio '{self._name}': {exc}"
            ) from exc
        return f"Servicio desinstalado: {self._name}"

    def start(self) -> str:
        """Arranca el servicio y espera a que esté en ejecución."""
        modules = _import_win32()
        try:
            modules.win32serviceutil.StartService(self._name)
        except Exception as exc:  # noqa: BLE001 - se traduce a error tipado
            if _is_winerror(modules, exc, "ERROR_SERVICE_ALREADY_RUNNING"):
                return f"El servicio '{self._name}' ya estaba en ejecución."
            if _is_missing_service(modules, exc):
                raise ServiceNotInstalledError(
                    f"el servicio '{self._name}' no está instalado: "
                    "use 'odin service install --config <ruta>'"
                ) from exc
            raise ServiceError(f"no se pudo arrancar el servicio '{self._name}': {exc}") from exc
        self._wait_for_state(modules, modules.win32service.SERVICE_RUNNING, "arrancar")
        return f"Servicio arrancado: {self._name}."

    def stop(self) -> str:
        """Detiene el servicio y espera a que esté detenido."""
        modules = _import_win32()
        try:
            modules.win32serviceutil.StopService(self._name)
        except Exception as exc:  # noqa: BLE001 - se traduce a error tipado
            if _is_winerror(modules, exc, "ERROR_SERVICE_NOT_ACTIVE"):
                return f"El servicio '{self._name}' ya estaba detenido."
            if _is_missing_service(modules, exc):
                raise ServiceNotInstalledError(
                    f"el servicio '{self._name}' no está instalado: "
                    "use 'odin service install --config <ruta>'"
                ) from exc
            raise ServiceError(f"no se pudo detener el servicio '{self._name}': {exc}") from exc
        self._wait_for_state(modules, modules.win32service.SERVICE_STOPPED, "detener")
        return f"Servicio detenido: {self._name}."

    def status(self) -> ServiceStatus:
        """Consulta el estado real del servicio en el SCM."""
        modules = _import_win32()
        try:
            status = modules.win32serviceutil.QueryServiceStatus(self._name)
        except Exception as exc:  # noqa: BLE001 - ausente no es error
            if _is_missing_service(modules, exc):
                return ServiceStatus.not_installed(
                    ServiceManagerKind.WINDOWS, detail=f"servicio '{self._name}' no instalado"
                )
            raise ServiceError(
                f"no se pudo consultar el servicio '{self._name}': {exc}"
            ) from exc
        state = status[1]
        running = state == modules.win32service.SERVICE_RUNNING
        detail = f"estado={state}"
        auto_start: bool | None = None
        restart_on_failure: bool | None = None
        try:
            auto_start, restart_on_failure = self._query_config(modules)
        except Exception as exc:  # noqa: BLE001 - el estado básico ya es útil
            detail += f"; configuración no consultable: {exc}"
        return ServiceStatus(
            installed=True,
            running=running,
            auto_start=auto_start,
            restart_on_failure=restart_on_failure,
            manager=ServiceManagerKind.WINDOWS,
            detail=detail,
        )

"""Tests del gestor Windows del modo servicio sobre pywin32 (Item 061).

Sin Windows ni pywin32: el paquete debe importar limpio en Linux y el ciclo de
vida completo se ejerce con dobles de ``win32serviceutil``/``win32service``/
``servicemanager``/``winerror`` inyectados en ``_import_win32``. La ejecución
en Windows Server real queda para el runbook de la Etapa 8 (Item 009).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from odin.service import (
    DEFAULT_DESCRIPTION,
    DEFAULT_DISPLAY_NAME,
    ServiceError,
    ServiceManagerKind,
    ServiceNotInstalledError,
    ServiceSpec,
    ServiceUnsupportedError,
    create_service_manager,
)
from odin.service import windows as windows_module
from odin.service.windows import (
    CONFIG_OPTION,
    ENV_CONFIG_VAR,
    FAILURE_RESET_PERIOD_SECONDS,
    SERVICE_CLASS_STRING,
    WORKING_DIR_OPTION,
    Win32Modules,
    WindowsServiceManager,
)

CONFIG_PATH = (
    Path("C:/odin/config.json")
    if sys.platform == "win32"
    else Path("/etc/odin/config.json")
)
PYWIN32_AVAILABLE = importlib.util.find_spec("win32serviceutil") is not None


class FakeWindowsError(Exception):
    """Error con ``winerror``, como los que reporta pywin32."""

    def __init__(self, winerror: int) -> None:
        super().__init__(f"winerror {winerror}")
        self.winerror = winerror


class FakeServiceFramework:
    """Base de relleno del ``ServiceFramework`` de pywin32."""

    def __init__(self, args: Any) -> None:
        self.args = tuple(args)
        self.reported: list[int] = []

    def ReportServiceStatus(
        self, status: int, waitHint: int = 5000, win32ExitCode: int = 0, svcExitCode: int = 0
    ) -> None:
        self.reported.append(status)

    def ServiceCtrlHandlerEx(self, control: int, event_type: int, data: Any) -> None:
        return None


class FakeRuntime:
    """Runtime doble del ``ServiceRunner`` del Item 065."""

    def __init__(self, exit_code: int = 0) -> None:
        self.exit_code = exit_code
        self.run_calls = 0
        self.stop_calls = 0

    def run(self) -> int:
        self.run_calls += 1
        return self.exit_code

    def stop(self) -> None:
        self.stop_calls += 1


class FakeWin32:
    """Dobles de los módulos de pywin32 con registro de llamadas y fallos inyectables."""

    SERVICE_STOPPED = 1
    SERVICE_START_PENDING = 2
    SERVICE_STOP_PENDING = 3
    SERVICE_RUNNING = 4
    SERVICE_AUTO_START = 2
    SERVICE_DEMAND_START = 3
    SC_MANAGER_ALL_ACCESS = 0xF003F
    SC_MANAGER_CONNECT = 1
    SERVICE_QUERY_CONFIG = 1
    SERVICE_CHANGE_CONFIG = 2
    SERVICE_START = 16
    SERVICE_CONFIG_FAILURE_ACTIONS = 2
    SERVICE_CONFIG_FAILURE_ACTIONS_FLAG = 4
    SC_ACTION_RESTART = 1
    SC_ACTION_NONE = 0
    ERROR_SERVICE_DOES_NOT_EXIST = 1060
    ERROR_INVALID_NAME = 123
    ERROR_SERVICE_NOT_ACTIVE = 1062
    ERROR_SERVICE_ALREADY_RUNNING = 1056

    def __init__(self) -> None:
        self.install_calls: list[tuple[str, str, str, dict[str, Any]]] = []
        self.custom_options: dict[tuple[str, str], str] = {}
        self.remove_calls: list[str] = []
        self.start_calls: list[str] = []
        self.stop_calls: list[str] = []
        self.statuses: list[tuple[int, int]] = [(0, self.SERVICE_STOPPED)]
        self.start_type = self.SERVICE_AUTO_START
        self.failure_actions: dict[str, Any] = {
            "ResetPeriod": FAILURE_RESET_PERIOD_SECONDS,
            "RebootMsg": "",
            "Command": "",
            "Actions": [(self.SC_ACTION_RESTART, 5000)],
        }
        self.change_config2_calls: list[tuple[int, Any]] = []
        self.closed_handles: list[Any] = []
        self.error_log: list[str] = []
        self.sleeps: list[float] = []
        self.install_error: FakeWindowsError | None = None
        self.remove_error: FakeWindowsError | None = None
        self.start_error: FakeWindowsError | None = None
        self.stop_error: FakeWindowsError | None = None
        self.status_error: FakeWindowsError | None = None
        self.config_error: FakeWindowsError | None = None
        self.host_exe: Path | None = None

    # --- win32serviceutil ---

    def install_service(
        self, class_string: str, name: str, display_name: str, **kwargs: Any
    ) -> None:
        if self.install_error is not None:
            raise self.install_error
        self.install_calls.append((class_string, name, display_name, kwargs))

    def set_custom_option(self, name: str, option: str, value: str) -> None:
        self.custom_options[(name, option)] = value

    def get_custom_option(self, name: str, option: str, default: Any = None) -> Any:
        return self.custom_options.get((name, option), default)

    def remove_service(self, name: str) -> None:
        if self.remove_error is not None:
            raise self.remove_error
        self.remove_calls.append(name)

    def start_service(self, name: str) -> None:
        if self.start_error is not None:
            raise self.start_error
        self.start_calls.append(name)

    def stop_service(self, name: str) -> None:
        if self.stop_error is not None:
            raise self.stop_error
        self.stop_calls.append(name)

    def query_status(self, name: str, machine: Any = None) -> tuple[int, int]:
        if self.status_error is not None:
            raise self.status_error
        if len(self.statuses) > 1:
            return self.statuses.pop(0)
        return self.statuses[0]

    def locate_python_service_exe(self) -> str:
        """Ruta del host del servicio (en producción lo copia pywin32)."""
        if self.host_exe is not None:
            return str(self.host_exe)
        return str(Path(sys.exec_prefix) / "pythonservice.exe")

    # --- win32service ---

    def open_sc_manager(self, machine: Any, database: Any, access: int) -> str:
        return "hscm"

    def open_service(self, hscm: str, name: str, access: int) -> str:
        return "hs"

    def change_service_config2(self, hs: str, level: int, info: Any) -> None:
        self.change_config2_calls.append((level, info))

    def query_service_config(self, hs: str) -> tuple[Any, ...]:
        if self.config_error is not None:
            raise self.config_error
        return (0x10, self.start_type, 0, "cmd", None, 0, (), None, "ODIN")

    def query_service_config2(self, hs: str, level: int) -> Any:
        return self.failure_actions

    def close_service_handle(self, handle: str) -> None:
        self.closed_handles.append(handle)

    def log_error(self, message: str) -> None:
        self.error_log.append(message)

    def modules(self) -> Win32Modules:
        """Construye los cuatro módulos falsos como ``Win32Modules``."""
        fake = self
        win32serviceutil = SimpleNamespace(
            ServiceFramework=FakeServiceFramework,
            InstallService=fake.install_service,
            SetServiceCustomOption=fake.set_custom_option,
            GetServiceCustomOption=fake.get_custom_option,
            RemoveService=fake.remove_service,
            StartService=fake.start_service,
            StopService=fake.stop_service,
            QueryServiceStatus=fake.query_status,
            LocatePythonServiceExe=fake.locate_python_service_exe,
        )
        win32service = SimpleNamespace(
            SERVICE_STOPPED=fake.SERVICE_STOPPED,
            SERVICE_START_PENDING=fake.SERVICE_START_PENDING,
            SERVICE_STOP_PENDING=fake.SERVICE_STOP_PENDING,
            SERVICE_RUNNING=fake.SERVICE_RUNNING,
            SERVICE_AUTO_START=fake.SERVICE_AUTO_START,
            SERVICE_DEMAND_START=fake.SERVICE_DEMAND_START,
            SC_MANAGER_ALL_ACCESS=fake.SC_MANAGER_ALL_ACCESS,
            SC_MANAGER_CONNECT=fake.SC_MANAGER_CONNECT,
            SERVICE_QUERY_CONFIG=fake.SERVICE_QUERY_CONFIG,
            SERVICE_CHANGE_CONFIG=fake.SERVICE_CHANGE_CONFIG,
            SERVICE_START=fake.SERVICE_START,
            SERVICE_CONFIG_FAILURE_ACTIONS=fake.SERVICE_CONFIG_FAILURE_ACTIONS,
            SERVICE_CONFIG_FAILURE_ACTIONS_FLAG=fake.SERVICE_CONFIG_FAILURE_ACTIONS_FLAG,
            SC_ACTION_RESTART=fake.SC_ACTION_RESTART,
            OpenSCManager=fake.open_sc_manager,
            OpenService=fake.open_service,
            ChangeServiceConfig2=fake.change_service_config2,
            QueryServiceConfig=fake.query_service_config,
            QueryServiceConfig2=fake.query_service_config2,
            CloseServiceHandle=fake.close_service_handle,
        )
        winerror = SimpleNamespace(
            ERROR_SERVICE_DOES_NOT_EXIST=fake.ERROR_SERVICE_DOES_NOT_EXIST,
            ERROR_INVALID_NAME=fake.ERROR_INVALID_NAME,
            ERROR_SERVICE_NOT_ACTIVE=fake.ERROR_SERVICE_NOT_ACTIVE,
            ERROR_SERVICE_ALREADY_RUNNING=fake.ERROR_SERVICE_ALREADY_RUNNING,
        )
        servicemanager = SimpleNamespace(LogErrorMsg=fake.log_error)
        return Win32Modules(servicemanager, win32service, win32serviceutil, winerror)


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeWin32:
    """Instala los dobles de pywin32 y limpia la clase de servicio cacheada."""
    fake_win32 = FakeWin32()
    monkeypatch.setattr(windows_module, "_import_win32", fake_win32.modules)
    monkeypatch.setattr(windows_module, "_odin_service_class", None)
    return fake_win32


def _manager(fake: FakeWin32, **kwargs: Any) -> WindowsServiceManager:
    return WindowsServiceManager(
        CONFIG_PATH, sleep=fake.sleeps.append, timeout_seconds=1.0, **kwargs
    )


def _spec(**overrides: Any) -> ServiceSpec:
    values: dict[str, Any] = {"executable": "odin", "config_path": CONFIG_PATH}
    values.update(overrides)
    return ServiceSpec(**values)


def _service_instance(fake: FakeWin32) -> Any:
    service_class = windows_module.get_service_class()
    return service_class(["odin"])


# --- import perezoso ---


def test_windows_module_import_does_not_build_the_service_class() -> None:
    assert "odin.service.windows" in sys.modules
    assert windows_module._odin_service_class is None


def test_install_copies_dlls_next_to_host_for_venv(
    fake: FakeWin32, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un venv no tiene las DLL en su raíz: install las deja junto al host."""
    base = tmp_path / "base"
    host_dir = tmp_path / "venv"
    base.mkdir()
    host_dir.mkdir()
    major, minor = sys.version_info[:2]
    names = (
        f"python{major}{minor}.dll",
        f"pywintypes{major}{minor}.dll",
        "vcruntime140.dll",
        "vcruntime140_1.dll",
    )
    for name in names:
        (base / name).write_bytes(b"dll")
    fake.host_exe = host_dir / "pythonservice.exe"
    monkeypatch.setattr(sys, "base_prefix", str(base))

    _manager(fake).install(_spec())

    assert sorted(path.name for path in host_dir.iterdir()) == sorted(names)


@pytest.mark.skipif(PYWIN32_AVAILABLE, reason="pywin32 instalado: el error de plataforma no aplica")
def test_get_service_class_without_pywin32_raises() -> None:
    with pytest.raises(ServiceUnsupportedError, match="pywin32"):
        windows_module.get_service_class()


@pytest.mark.skipif(PYWIN32_AVAILABLE, reason="pywin32 instalado: el error de plataforma no aplica")
def test_manager_operations_without_pywin32_raise() -> None:
    manager = WindowsServiceManager(CONFIG_PATH)
    with pytest.raises(ServiceUnsupportedError, match="pywin32"):
        manager.status()


# --- install ---


def test_install_registers_service_with_autostart_and_config(fake: FakeWin32) -> None:
    message = _manager(fake).install(_spec())
    assert fake.install_calls == [
        (
            SERVICE_CLASS_STRING,
            "odin",
            DEFAULT_DISPLAY_NAME,
            {
                "startType": FakeWin32.SERVICE_AUTO_START,
                "userName": None,
                "description": DEFAULT_DESCRIPTION,
            },
        )
    ]
    assert fake.custom_options[("odin", CONFIG_OPTION)] == str(CONFIG_PATH)
    assert fake.custom_options[("odin", WORKING_DIR_OPTION)] == str(CONFIG_PATH.parent)
    assert "instalado" in message
    assert "arranque automático" in message
    assert "reinicio ante caída activado" in message


def test_install_manual_start_without_restart_and_with_account(fake: FakeWin32) -> None:
    manager = _manager(fake)
    manager.install(
        _spec(auto_start=False, restart_on_failure=False, account="NT AUTHORITY\\LocalService")
    )
    kwargs = fake.install_calls[0][3]
    assert kwargs["startType"] == FakeWin32.SERVICE_DEMAND_START
    assert kwargs["userName"] == "NT AUTHORITY\\LocalService"
    assert fake.change_config2_calls == []


def test_install_sets_failure_actions_with_configured_delay(fake: FakeWin32) -> None:
    _manager(fake).install(_spec(restart_delay_seconds=12))
    level, actions = fake.change_config2_calls[0]
    assert level == FakeWin32.SERVICE_CONFIG_FAILURE_ACTIONS
    assert actions["Actions"] == [(FakeWin32.SC_ACTION_RESTART, 12000)]
    assert actions["ResetPeriod"] == FAILURE_RESET_PERIOD_SECONDS
    assert actions["Command"] == ""
    assert (FakeWin32.SERVICE_CONFIG_FAILURE_ACTIONS_FLAG, True) in fake.change_config2_calls
    assert fake.closed_handles == ["hs", "hscm"]


def test_install_error_is_wrapped_in_service_error(fake: FakeWin32) -> None:
    fake.install_error = FakeWindowsError(5)
    with pytest.raises(ServiceError, match="no se pudo instalar"):
        _manager(fake).install(_spec())


# --- uninstall ---


def test_uninstall_stops_and_removes(fake: FakeWin32) -> None:
    message = _manager(fake).uninstall()
    assert fake.stop_calls == ["odin"]
    assert fake.remove_calls == ["odin"]
    assert "desinstalado" in message


def test_uninstall_tolerates_inactive_stop(fake: FakeWin32) -> None:
    fake.stop_error = FakeWindowsError(FakeWin32.ERROR_SERVICE_NOT_ACTIVE)
    message = _manager(fake).uninstall()
    assert fake.remove_calls == ["odin"]
    assert "desinstalado" in message


def test_uninstall_is_idempotent_when_service_is_missing(fake: FakeWin32) -> None:
    fake.stop_error = FakeWindowsError(FakeWin32.ERROR_SERVICE_DOES_NOT_EXIST)
    fake.remove_error = FakeWindowsError(FakeWin32.ERROR_SERVICE_DOES_NOT_EXIST)
    message = _manager(fake).uninstall()
    assert "no estaba instalado" in message


def test_uninstall_propagates_unexpected_remove_error(fake: FakeWin32) -> None:
    fake.remove_error = FakeWindowsError(5)
    with pytest.raises(ServiceError, match="no se pudo desinstalar"):
        _manager(fake).uninstall()


# --- start / stop ---


def test_start_waits_until_running(fake: FakeWin32) -> None:
    fake.statuses = [
        (0, FakeWin32.SERVICE_START_PENDING),
        (0, FakeWin32.SERVICE_RUNNING),
    ]
    message = _manager(fake).start()
    assert fake.start_calls == ["odin"]
    assert fake.sleeps == [windows_module.POLL_INTERVAL_SECONDS]
    assert "arrancado" in message


def test_start_already_running_is_not_an_error(fake: FakeWin32) -> None:
    fake.start_error = FakeWindowsError(FakeWin32.ERROR_SERVICE_ALREADY_RUNNING)
    message = _manager(fake).start()
    assert "ya estaba en ejecución" in message


def test_start_missing_service_raises_not_installed(fake: FakeWin32) -> None:
    fake.start_error = FakeWindowsError(FakeWin32.ERROR_SERVICE_DOES_NOT_EXIST)
    with pytest.raises(ServiceNotInstalledError, match="no está instalado"):
        _manager(fake).start()


def test_start_when_service_ends_stopped_raises(fake: FakeWin32) -> None:
    fake.statuses = [(0, FakeWin32.SERVICE_STOPPED)]
    with pytest.raises(ServiceError, match="no pudo arrancar"):
        _manager(fake).start()


def test_start_timeout_raises_without_sleeping_past_deadline(fake: FakeWin32) -> None:
    fake.statuses = [(0, FakeWin32.SERVICE_START_PENDING)]
    manager = WindowsServiceManager(CONFIG_PATH, sleep=fake.sleeps.append, timeout_seconds=0.0)
    with pytest.raises(ServiceError, match="timeout"):
        manager.start()
    assert fake.sleeps == []


def test_stop_waits_until_stopped(fake: FakeWin32) -> None:
    fake.statuses = [
        (0, FakeWin32.SERVICE_STOP_PENDING),
        (0, FakeWin32.SERVICE_STOPPED),
    ]
    message = _manager(fake).stop()
    assert fake.stop_calls == ["odin"]
    assert "detenido" in message


def test_stop_not_active_is_not_an_error(fake: FakeWin32) -> None:
    fake.stop_error = FakeWindowsError(FakeWin32.ERROR_SERVICE_NOT_ACTIVE)
    message = _manager(fake).stop()
    assert "ya estaba detenido" in message


# --- status ---


def test_status_maps_running_autostart_and_restart_policy(fake: FakeWin32) -> None:
    fake.statuses = [(0, FakeWin32.SERVICE_RUNNING)]
    fake.start_type = FakeWin32.SERVICE_AUTO_START
    status = _manager(fake).status()
    assert status.installed is True
    assert status.running is True
    assert status.auto_start is True
    assert status.restart_on_failure is True
    assert status.manager is ServiceManagerKind.WINDOWS
    assert f"estado={FakeWin32.SERVICE_RUNNING}" in (status.detail or "")


def test_status_without_restart_policy(fake: FakeWin32) -> None:
    fake.statuses = [(0, FakeWin32.SERVICE_STOPPED)]
    fake.failure_actions = {
        "ResetPeriod": 0,
        "RebootMsg": "",
        "Command": "",
        "Actions": [(FakeWin32.SC_ACTION_NONE, 0)],
    }
    status = _manager(fake).status()
    assert status.running is False
    assert status.auto_start is True
    assert status.restart_on_failure is False


def test_status_missing_service_reports_not_installed(fake: FakeWin32) -> None:
    fake.status_error = FakeWindowsError(FakeWin32.ERROR_SERVICE_DOES_NOT_EXIST)
    status = _manager(fake).status()
    assert status.installed is False
    assert status.running is False
    assert status.manager is ServiceManagerKind.WINDOWS


def test_status_survives_config_query_failure(fake: FakeWin32) -> None:
    fake.statuses = [(0, FakeWin32.SERVICE_RUNNING)]
    fake.config_error = FakeWindowsError(5)
    status = _manager(fake).status()
    assert status.installed is True
    assert status.running is True
    assert status.auto_start is None
    assert status.restart_on_failure is None
    assert "no consultable" in (status.detail or "")


# --- clase de servicio (SvcDoRun / SvcStop) ---


def test_service_class_attributes_and_dynamic_base(fake: FakeWin32) -> None:
    service_class = windows_module.get_service_class()
    assert windows_module.OdinWindowsService is service_class
    assert issubclass(service_class, FakeServiceFramework)
    assert service_class._svc_name_ == "odin"
    assert service_class._svc_display_name_ == DEFAULT_DISPLAY_NAME
    assert service_class._svc_description_ == DEFAULT_DESCRIPTION


def test_svc_do_run_uses_config_fixed_at_install(fake: FakeWin32) -> None:
    fake.custom_options[("odin", CONFIG_OPTION)] = str(CONFIG_PATH)
    service = _service_instance(fake)
    created: list[Path] = []
    runtime = FakeRuntime()

    def factory(config_path: Path) -> FakeRuntime:
        created.append(config_path)
        return runtime

    service._runtime_factory = factory
    service.SvcDoRun()
    assert created == [CONFIG_PATH]
    assert runtime.run_calls == 1
    assert service._finished.is_set()
    assert fake.error_log == []


def test_svc_do_run_falls_back_to_env_config(
    fake: FakeWin32, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ENV_CONFIG_VAR, str(CONFIG_PATH))
    service = _service_instance(fake)
    created: list[Path] = []
    service._runtime_factory = lambda path: created.append(path) or FakeRuntime()
    service.SvcDoRun()
    assert created == [CONFIG_PATH]


def test_svc_do_run_without_config_logs_error(
    fake: FakeWin32, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(ENV_CONFIG_VAR, raising=False)
    service = _service_instance(fake)
    created: list[Path] = []
    service._runtime_factory = lambda path: created.append(path) or FakeRuntime()
    service.SvcDoRun()
    assert created == []
    assert any("configuración" in message for message in fake.error_log)
    assert service._finished.is_set()


def test_svc_do_run_logs_runtime_failure_without_raising(fake: FakeWin32) -> None:
    fake.custom_options[("odin", CONFIG_OPTION)] = str(CONFIG_PATH)
    service = _service_instance(fake)

    class _FailingRuntime:
        def run(self) -> int:
            raise RuntimeError("boom")

        def stop(self) -> None:
            return None

    service._runtime_factory = lambda path: _FailingRuntime()
    service.SvcDoRun()
    assert any("boom" in message for message in fake.error_log)
    assert service._finished.is_set()


def test_svc_do_run_chdirs_to_installed_working_dir(
    fake: FakeWin32, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    origin = tmp_path / "origin"
    origin.mkdir()
    monkeypatch.chdir(origin)
    fake.custom_options[("odin", CONFIG_OPTION)] = str(CONFIG_PATH)
    fake.custom_options[("odin", WORKING_DIR_OPTION)] = str(tmp_path)
    service = _service_instance(fake)
    service._runtime_factory = lambda path: FakeRuntime()
    service.SvcDoRun()
    assert Path.cwd() == tmp_path


def test_svc_stop_reports_pending_then_stopped_and_stops_runtime(fake: FakeWin32) -> None:
    service = _service_instance(fake)
    runtime = FakeRuntime()
    service._runtime = runtime
    service._stop_wait_seconds = 0.01
    service.SvcStop()
    assert service.reported == [
        FakeWin32.SERVICE_STOP_PENDING,
        FakeWin32.SERVICE_STOPPED,
    ]
    assert runtime.stop_calls == 1


def test_svc_stop_without_runtime_is_safe(fake: FakeWin32) -> None:
    service = _service_instance(fake)
    service._finished.set()
    service.SvcStop()
    assert service.reported == [
        FakeWin32.SERVICE_STOP_PENDING,
        FakeWin32.SERVICE_STOPPED,
    ]


def test_create_service_manager_dispatches_to_windows_manager() -> None:
    manager = create_service_manager(CONFIG_PATH, platform="win32")
    assert isinstance(manager, WindowsServiceManager)
    assert manager.manager is ServiceManagerKind.WINDOWS
    assert manager.config_path == CONFIG_PATH
    assert manager.name == "odin"

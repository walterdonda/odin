"""Tests del contrato portable del modo servicio (Item 059).

Sin servicios externos ni pywin32: el despacho a los gestores concretos se
verifica con módulos dobles inyectados en ``sys.modules`` (el gestor Linux real
llega en el Item 060 y el de Windows en el Item 061, que agregan su propio test
de despacho real); el resto es contrato puro (dataclasses, validaciones, ABC).
"""

from __future__ import annotations

import dataclasses
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from odin.service import (
    DEFAULT_DISPLAY_NAME,
    DEFAULT_RESTART_DELAY_SECONDS,
    SERVICE_NAME,
    ServiceError,
    ServiceManager,
    ServiceManagerKind,
    ServiceSpec,
    ServiceStatus,
    ServiceUnsupportedError,
    create_service_manager,
    ensure_absolute_config_path,
)

CONFIG_PATH = Path("/etc/odin/config.json")


class _FakeManager(ServiceManager):
    """Gestor doble: implementa el ABC y registra su construcción."""

    manager = ServiceManagerKind.SYSTEMD

    def __init__(self, config_path: Path | str, **kwargs: object) -> None:
        self.config_path = Path(config_path)
        self.kwargs = kwargs

    def install(self, spec: ServiceSpec) -> str:
        return f"instalado {spec.name}"

    def uninstall(self) -> str:
        return "desinstalado"

    def start(self) -> str:
        return "arrancado"

    def stop(self) -> str:
        return "detenido"

    def status(self) -> ServiceStatus:
        return ServiceStatus.not_installed(self.manager)


def _install_fake_manager_module(
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
    class_name: str,
    kind: ServiceManagerKind,
    created: list[Any],
) -> None:
    """Publica un ``module_name`` doble en ``sys.modules`` con su manager."""
    module = types.ModuleType(module_name)

    class _Manager(_FakeManager):
        manager = kind

        def __init__(self, config_path: Path | str, **kwargs: object) -> None:
            super().__init__(config_path, **kwargs)
            created.append(self)

    _Manager.__name__ = class_name
    _Manager.__qualname__ = class_name
    setattr(module, class_name, _Manager)
    monkeypatch.setitem(sys.modules, module_name, module)


# --- despacho por plataforma ---


def test_dispatch_linux_builds_manager_with_config_path_and_kwargs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[Any] = []
    _install_fake_manager_module(
        monkeypatch,
        "odin.service.linux",
        "LinuxServiceManager",
        ServiceManagerKind.SYSTEMD,
        created,
    )
    manager = create_service_manager(CONFIG_PATH, platform="linux", unit_dir=Path("/tmp/u"))
    assert isinstance(manager, _FakeManager)
    assert created[0].config_path == CONFIG_PATH
    assert created[0].kwargs == {"unit_dir": Path("/tmp/u")}


def test_dispatch_win32_does_not_require_pywin32(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[Any] = []
    _install_fake_manager_module(
        monkeypatch,
        "odin.service.windows",
        "WindowsServiceManager",
        ServiceManagerKind.WINDOWS,
        created,
    )
    manager = create_service_manager(CONFIG_PATH, platform="win32")
    assert manager.manager is ServiceManagerKind.WINDOWS
    assert created[0].config_path == CONFIG_PATH
    assert "win32serviceutil" not in sys.modules
    assert "win32service" not in sys.modules


def test_dispatch_unsupported_platform_raises() -> None:
    with pytest.raises(ServiceUnsupportedError, match="no soportada"):
        create_service_manager(CONFIG_PATH, platform="darwin")


def test_package_import_is_lazy_about_pywin32() -> None:
    assert "odin.service" in sys.modules
    assert "win32serviceutil" not in sys.modules
    assert "win32service" not in sys.modules


# --- ServiceSpec: validación y derivados ---


def test_service_spec_rejects_relative_config_path() -> None:
    with pytest.raises(ServiceError, match="absoluta"):
        ServiceSpec(config_path=Path("config.json"))


def test_service_spec_rejects_relative_working_dir() -> None:
    with pytest.raises(ServiceError, match="absoluta"):
        ServiceSpec(config_path=CONFIG_PATH, working_dir=Path("work"))


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"executable": "   "}, "vacío"),
        ({"name": ""}, "inválido"),
        ({"name": "mi servicio"}, "inválido"),
        ({"restart_delay_seconds": -1}, "negativo"),
    ],
)
def test_service_spec_rejects_invalid_fields(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ServiceError, match=message):
        ServiceSpec(config_path=CONFIG_PATH, **kwargs)


def test_service_spec_defaults_and_derived_argv() -> None:
    spec = ServiceSpec(config_path=CONFIG_PATH)
    assert spec.name == SERVICE_NAME == "odin"
    assert spec.display_name == DEFAULT_DISPLAY_NAME
    assert spec.auto_start is True
    assert spec.restart_on_failure is True
    assert spec.restart_delay_seconds == DEFAULT_RESTART_DELAY_SECONDS == 5
    assert spec.account is None
    assert spec.arguments == ("service", "run", "--config", str(CONFIG_PATH))
    assert spec.argv == ("odin", "service", "run", "--config", str(CONFIG_PATH))
    assert spec.resolved_working_dir == CONFIG_PATH.parent


def test_service_spec_accepts_explicit_executable_and_working_dir() -> None:
    spec = ServiceSpec(
        config_path=CONFIG_PATH,
        executable="/opt/odin/bin/odin",
        working_dir=Path("/var/lib/odin"),
    )
    assert spec.argv[0] == "/opt/odin/bin/odin"
    assert spec.resolved_working_dir == Path("/var/lib/odin")


def test_service_spec_round_trip_equality_and_frozen() -> None:
    spec = ServiceSpec(config_path=CONFIG_PATH)
    assert spec == ServiceSpec(config_path=CONFIG_PATH)
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.auto_start = False
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.config_path = Path("/otra/ruta.json")


# --- ServiceStatus y ServiceManager ---


def test_status_not_installed_is_a_valid_state() -> None:
    status = ServiceStatus.not_installed(ServiceManagerKind.SYSTEMD, detail="unit ausente")
    assert status == ServiceStatus(
        installed=False, manager=ServiceManagerKind.SYSTEMD, detail="unit ausente"
    )
    assert status.installed is False
    assert status.running is False
    assert status.auto_start is None
    assert status.restart_on_failure is None


def test_status_round_trip_equality() -> None:
    status = ServiceStatus(
        installed=True,
        running=True,
        auto_start=True,
        restart_on_failure=True,
        manager=ServiceManagerKind.WINDOWS,
        detail="SERVICE_RUNNING",
    )
    assert status == ServiceStatus(
        installed=True,
        running=True,
        auto_start=True,
        restart_on_failure=True,
        manager=ServiceManagerKind.WINDOWS,
        detail="SERVICE_RUNNING",
    )
    assert status != ServiceStatus(installed=False)


def test_service_manager_abc_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError):
        ServiceManager()


def test_manager_status_of_not_installed_service_is_not_an_error() -> None:
    status = _FakeManager(CONFIG_PATH).status()
    assert status == ServiceStatus(installed=False, manager=ServiceManagerKind.SYSTEMD)


# --- validación compartida de rutas ---


def test_ensure_absolute_config_path_normalizes_absolute_str() -> None:
    assert ensure_absolute_config_path(str(CONFIG_PATH)) == CONFIG_PATH


def test_ensure_absolute_config_path_rejects_relative_path() -> None:
    with pytest.raises(ServiceError, match="absoluta"):
        ensure_absolute_config_path(Path("./config.json"))

"""Tests del gestor Linux del modo servicio sobre systemd (Item 060).

Sin systemd real: el ejecutor de ``systemctl`` es un doble que registra los
comandos y devuelve respuestas configurables; ``unit_dir`` apunta a un
directorio temporal para verificar lo escrito y la rama sin permisos se ejerce
con ``can_write_unit`` inyectable.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

from odin.service import (
    ServiceError,
    ServiceManagerKind,
    ServiceNotInstalledError,
    ServiceSpec,
    create_service_manager,
)
from odin.service.linux import (
    UNIT_NAME,
    CommandResult,
    LinuxServiceManager,
    _quote_argument,
    render_unit,
)

IS_WINDOWS = sys.platform == "win32"
CONFIG_PATH = Path("C:/odin/config.json") if IS_WINDOWS else Path("/etc/odin/config.json")
EXECUTABLE = "C:/odin/bin/odin" if IS_WINDOWS else "/opt/odin/bin/odin"
SHOW_COMMAND = (
    "show",
    UNIT_NAME,
    "--property=LoadState,ActiveState,UnitFileState,Restart",
    "--no-pager",
)


class FakeSystemctl:
    """Doble del ejecutor de systemctl: registra comandos y responde por comando."""

    def __init__(self, responses: dict[str, CommandResult | list[CommandResult]] | None = None):
        self.commands: list[tuple[str, ...]] = []
        self._responses: dict[str, list[CommandResult]] = {
            command: [result] if isinstance(result, CommandResult) else list(result)
            for command, result in (responses or {}).items()
        }

    def __call__(self, args: Sequence[str]) -> CommandResult:
        command = tuple(args)
        self.commands.append(command)
        queue = self._responses.get(command[0])
        if not queue:
            return CommandResult(returncode=0)
        return queue[0] if len(queue) == 1 else queue.pop(0)


def _manager(
    tmp_path: Path, runner: FakeSystemctl | None = None, *, writable: bool = True
) -> LinuxServiceManager:
    return LinuxServiceManager(
        CONFIG_PATH,
        unit_dir=tmp_path / "systemd",
        runner=runner if runner is not None else FakeSystemctl(),
        can_write_unit=lambda: writable,
    )


def _spec(**overrides: object) -> ServiceSpec:
    values: dict[str, object] = {"executable": EXECUTABLE, "config_path": CONFIG_PATH}
    values.update(overrides)
    return ServiceSpec(**values)


def _show(
    *,
    load_state: str = "loaded",
    active_state: str = "active",
    unit_file_state: str = "enabled",
    restart: str = "always",
) -> CommandResult:
    stdout = "\n".join(
        [
            f"LoadState={load_state}",
            f"ActiveState={active_state}",
            f"UnitFileState={unit_file_state}",
            f"Restart={restart}",
            "",
        ]
    )
    return CommandResult(returncode=0, stdout=stdout)


# --- render_unit ---


def test_render_unit_has_required_sections_and_absolute_exec_start() -> None:
    unit = render_unit(_spec())
    assert unit.startswith("[Unit]\n")
    assert "Description=ODIN Backup Service" in unit
    assert "After=network-online.target" in unit
    assert "Wants=network-online.target" in unit
    assert "[Service]" in unit
    assert "Type=simple" in unit
    assert (
        f"ExecStart={_quote_argument(EXECUTABLE)} service run --config "
        f"{_quote_argument(str(CONFIG_PATH))}"
    ) in unit
    assert f"WorkingDirectory={_quote_argument(str(CONFIG_PATH.parent))}" in unit
    assert "Restart=always" in unit
    assert "RestartSec=5" in unit
    assert "[Install]" in unit
    assert "WantedBy=multi-user.target" in unit
    assert "sh -c" not in unit


def test_render_unit_rejects_relative_executable() -> None:
    with pytest.raises(ServiceError, match="absoluta"):
        render_unit(_spec(executable="odin"))


def test_render_unit_quotes_paths_with_spaces() -> None:
    executable = "C:/opt/odin dir/odin" if IS_WINDOWS else "/opt/odin dir/odin"
    config_path = (
        Path("C:/srv/odin dir/config.json")
        if IS_WINDOWS
        else Path("/srv/odin dir/config.json")
    )
    unit = render_unit(_spec(executable=executable, config_path=config_path))
    expected_config = _quote_argument(str(config_path))
    expected_work_dir = _quote_argument(str(config_path.parent))
    assert f"ExecStart={_quote_argument(executable)} service run --config {expected_config}" in unit
    assert f"WorkingDirectory={expected_work_dir}" in unit


def test_render_unit_with_account_user_and_group() -> None:
    assert "User=odin\n" in render_unit(_spec(account="odin"))
    unit = render_unit(_spec(account="odin:backup"))
    assert "User=odin" in unit
    assert "Group=backup" in unit
    assert "User=odin:backup" not in unit


def test_render_unit_restart_no_when_restart_on_failure_disabled() -> None:
    unit = render_unit(_spec(restart_on_failure=False, restart_delay_seconds=10))
    assert "Restart=no" in unit
    assert "Restart=always" not in unit
    assert "RestartSec=10" in unit


# --- install ---


def test_install_writes_unit_and_enables(tmp_path: Path) -> None:
    runner = FakeSystemctl()
    manager = _manager(tmp_path, runner)
    message = manager.install(_spec())
    target = tmp_path / "systemd" / UNIT_NAME
    assert target.read_text(encoding="utf-8") == render_unit(_spec())
    assert runner.commands == [("daemon-reload",), ("enable", UNIT_NAME)]
    assert str(target) in message
    assert "habilitado" in message


def test_install_without_auto_start_skips_enable(tmp_path: Path) -> None:
    runner = FakeSystemctl()
    manager = _manager(tmp_path, runner)
    manager.install(_spec(auto_start=False))
    assert runner.commands == [("daemon-reload",)]
    assert (tmp_path / "systemd" / UNIT_NAME).exists()


def test_install_without_permissions_returns_guide_and_writes_nothing(tmp_path: Path) -> None:
    runner = FakeSystemctl()
    manager = _manager(tmp_path, runner, writable=False)
    guide = manager.install(_spec())
    assert runner.commands == []
    assert not (tmp_path / "systemd").exists()
    assert str(tmp_path / "systemd" / UNIT_NAME) in guide
    assert render_unit(_spec()).rstrip("\n") in guide
    assert "sudo systemctl daemon-reload" in guide
    assert f"sudo systemctl enable {UNIT_NAME}" in guide
    assert f"sudo systemctl start {UNIT_NAME}" in guide


def test_install_with_filesystem_permission_check_writes(tmp_path: Path) -> None:
    unit_dir = tmp_path / "systemd"
    unit_dir.mkdir()
    runner = FakeSystemctl()
    manager = LinuxServiceManager(CONFIG_PATH, unit_dir=unit_dir, runner=runner)
    manager.install(_spec())
    assert (unit_dir / UNIT_NAME).exists()


def test_install_propagates_enable_failure(tmp_path: Path) -> None:
    runner = FakeSystemctl(
        {"enable": CommandResult(returncode=1, stderr="Interactive authentication required.")}
    )
    manager = _manager(tmp_path, runner)
    with pytest.raises(ServiceError, match="Interactive authentication required"):
        manager.install(_spec())


# --- uninstall / start / stop ---


def test_uninstall_stops_disables_removes_and_reloads(tmp_path: Path) -> None:
    runner = FakeSystemctl()
    manager = _manager(tmp_path, runner)
    target = tmp_path / "systemd" / UNIT_NAME
    target.parent.mkdir(parents=True)
    target.write_text("[Unit]\n", encoding="utf-8")
    message = manager.uninstall()
    assert not target.exists()
    assert runner.commands == [
        ("stop", UNIT_NAME),
        ("disable", UNIT_NAME),
        ("daemon-reload",),
    ]
    assert "desinstalado" in message


def test_uninstall_is_idempotent_when_unit_is_absent(tmp_path: Path) -> None:
    runner = FakeSystemctl(
        {
            "stop": CommandResult(returncode=5, stderr="Unit odin.service not loaded."),
            "disable": CommandResult(returncode=1, stderr="Unit odin.service does not exist."),
        }
    )
    manager = _manager(tmp_path, runner)
    message = manager.uninstall()
    assert "no estaba instalado" in message
    assert ("daemon-reload",) not in runner.commands


def test_start_and_stop_run_systemctl(tmp_path: Path) -> None:
    runner = FakeSystemctl()
    manager = _manager(tmp_path, runner)
    assert "arrancado" in manager.start()
    assert "detenido" in manager.stop()
    assert runner.commands == [("start", UNIT_NAME), ("stop", UNIT_NAME)]


def test_start_missing_unit_raises_not_installed(tmp_path: Path) -> None:
    runner = FakeSystemctl(
        {"start": CommandResult(returncode=5, stderr="Unit odin.service not found.")}
    )
    manager = _manager(tmp_path, runner)
    with pytest.raises(ServiceNotInstalledError, match="not found"):
        manager.start()


# --- status ---


def test_status_reports_running_enabled(tmp_path: Path) -> None:
    runner = FakeSystemctl({"show": _show()})
    status = _manager(tmp_path, runner).status()
    assert status.installed is True
    assert status.running is True
    assert status.auto_start is True
    assert status.restart_on_failure is True
    assert status.manager is ServiceManagerKind.SYSTEMD
    assert "ActiveState=active" in (status.detail or "")
    assert runner.commands == [SHOW_COMMAND]


def test_status_reports_stopped_disabled_without_restart(tmp_path: Path) -> None:
    runner = FakeSystemctl(
        {"show": _show(active_state="inactive", unit_file_state="disabled", restart="no")}
    )
    status = _manager(tmp_path, runner).status()
    assert status.installed is True
    assert status.running is False
    assert status.auto_start is False
    assert status.restart_on_failure is False


def test_status_not_found_reports_not_installed(tmp_path: Path) -> None:
    runner = FakeSystemctl({"show": _show(load_state="not-found", unit_file_state="")})
    status = _manager(tmp_path, runner).status()
    assert status.installed is False
    assert status.running is False
    assert "not-found" in (status.detail or "")


def test_status_show_failure_with_missing_unit_reports_not_installed(tmp_path: Path) -> None:
    runner = FakeSystemctl(
        {"show": CommandResult(returncode=4, stderr="Unit odin.service could not be found.")}
    )
    status = _manager(tmp_path, runner).status()
    assert status.installed is False


def test_status_show_failure_propagates_service_error(tmp_path: Path) -> None:
    runner = FakeSystemctl(
        {"show": CommandResult(returncode=1, stderr="Failed to connect to bus: No such file")}
    )
    with pytest.raises(ServiceError, match="Failed to connect to bus"):
        _manager(tmp_path, runner).status()


def test_status_falls_back_to_is_active_and_is_enabled(tmp_path: Path) -> None:
    runner = FakeSystemctl(
        {
            "show": CommandResult(returncode=0, stdout=""),
            "is-active": CommandResult(returncode=3, stdout="active\n"),
            "is-enabled": CommandResult(returncode=1, stdout="enabled\n"),
        }
    )
    status = _manager(tmp_path, runner).status()
    assert status.installed is True
    assert status.running is True
    assert status.auto_start is True
    assert status.restart_on_failure is None
    assert runner.commands[1:] == [("is-active", UNIT_NAME), ("is-enabled", UNIT_NAME)]


def test_status_fallback_not_found_reports_not_installed(tmp_path: Path) -> None:
    runner = FakeSystemctl(
        {
            "show": CommandResult(returncode=0, stdout=""),
            "is-active": CommandResult(returncode=4, stdout="unknown\n"),
            "is-enabled": CommandResult(returncode=1, stdout="not-found\n"),
        }
    )
    status = _manager(tmp_path, runner).status()
    assert status.installed is False


# --- runner por defecto y despacho ---


def test_default_runner_missing_systemctl_raises_service_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _missing(*args: object, **kwargs: object) -> object:
        raise FileNotFoundError("systemctl")

    monkeypatch.setattr(subprocess, "run", _missing)
    manager = LinuxServiceManager(CONFIG_PATH, unit_dir=tmp_path)
    with pytest.raises(ServiceError, match="systemctl"):
        manager.status()


def test_create_service_manager_dispatches_to_linux_manager(tmp_path: Path) -> None:
    runner = FakeSystemctl()
    manager = create_service_manager(
        CONFIG_PATH,
        platform="linux",
        unit_dir=tmp_path / "systemd",
        runner=runner,
        can_write_unit=lambda: True,
    )
    assert isinstance(manager, LinuxServiceManager)
    assert manager.manager is ServiceManagerKind.SYSTEMD
    assert manager.unit_path == tmp_path / "systemd" / UNIT_NAME
    assert manager.config_path == CONFIG_PATH

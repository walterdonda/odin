"""Integración del modo servicio Linux: unit systemd, CLI y auto-recuperación (Item 066).

Tres capas, todas skip-safe:

1. **Estructura de la unit**: `deploy/odin.service` se valida por texto
   (secciones, `Type=simple`, `ExecStart` absoluto con `service run --config`,
   `Restart=always`, `WantedBy=multi-user.target`) y con `systemd-analyze
   verify` cuando el binario existe en el host: una unit renderizada por
   `render_unit` con ejecutable real siempre, y el archivo de referencia solo
   si el binario de su `ExecStart` está instalado (hoy es un placeholder
   documentado → skip con motivo).
2. **Ciclo de vida por la CLI real** (`odin service
   install|start|status|stop|uninstall`) con `LinuxServiceManager` real y el
   ejecutor de `systemctl` doble, afirmando la secuencia exacta de comandos,
   los exit codes y la unit escrita con rutas absolutas.
3. **Demo gated** (`ODIN_SERVICE_DEMO=1`): con sesión systemd de usuario se
   instala una unit temporal con `Restart=always` que corre `odin service run`
   sobre una configuración acelerada (cron `* * * * *`, `gbak` *stub* local,
   sin servidores SFTP) y el catcher SMTP in-process; se verifica un ciclo, se
   mata el proceso con `kill -9` y se comprueba que systemd lo reinicia solo
   (MainPID nuevo) y llega un segundo ciclo.

Alcance y delegaciones (documentados también en el runbook):

- El **arranque en boot** tras reiniciar el SO no se puede automatizar en este
  entorno (implicaría tocar el systemd del host y reiniciarlo): queda como
  procedimiento manual —`systemctl enable` + reinicio + `odin service status`—
  registrado en `docs/aide/progress.md` y en el runbook de `docs/service.md`
  (Item 067).
- La **verificación en Windows Server real** se ejecuta con el runbook de
  `docs/service.md` en la Etapa 8 (Item 009); acá Windows queda cubierto por
  los dobles de `win32serviceutil` del Item 061 y el ciclo de vida del runner
  del Item 065.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from odin.cli import EXIT_INTERNAL, EXIT_OK, main
from odin.config import load_config
from odin.scheduler import load_state, state_path
from odin.service import ServiceSpec
from odin.service.linux import (
    UNIT_NAME,
    CommandResult,
    LinuxServiceManager,
    _quote_argument,
    render_unit,
)
from tests.smtp_catcher import SmtpCatcher, parse_message

REPO_ROOT = Path(__file__).resolve().parent.parent
REFERENCE_UNIT = REPO_ROOT / "deploy" / "odin.service"
FIXTURES = Path(__file__).parent / "fixtures"
LINUX_FIXTURE = FIXTURES / "config_valid_linux.json"

SHOW_COMMAND = (
    "show",
    UNIT_NAME,
    "--property=LoadState,ActiveState,UnitFileState,Restart",
    "--no-pager",
)
DEMO_DEADLINE_SECONDS = 150
POLL_SECONDS = 0.5
FAR_FUTURE_SCHEDULE = "0 3 1 1 *"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Aísla los tests de un ``ODIN_CONFIG`` o modo demo del entorno real."""
    monkeypatch.delenv("ODIN_CONFIG", raising=False)


# --- capa 1: estructura de la unit ---


def _parse_sections(text: str) -> dict[str, list[str]]:
    """Secciones de una unit systemd con sus directivas efectivas (sin comentarios)."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(line)
    return sections


def _directive(lines: Sequence[str], key: str) -> str | None:
    """Valor de la directiva ``key=`` (la primera aparición) o ``None``."""
    prefix = f"{key}="
    for line in lines:
        if line.startswith(prefix):
            return line[len(prefix) :]
    return None


def test_reference_unit_is_structurally_sound() -> None:
    """La unit de referencia tiene las claves que exige el modo residente."""
    unit = REFERENCE_UNIT.read_text(encoding="utf-8")
    sections = _parse_sections(unit)
    for section in ("[Unit]", "[Service]", "[Install]"):
        assert section in sections, f"falta la sección {section}"

    service = sections["[Service]"]
    assert _directive(service, "Type") == "simple"
    exec_start = _directive(service, "ExecStart")
    assert exec_start is not None
    parts = exec_start.split()
    # La unit es un artefacto Linux: la absolutitud se juzga con sintaxis POSIX
    # aunque el test corra en un host Windows (Path('/opt/...') no es absoluta ahí).
    assert PurePosixPath(parts[0]).is_absolute(), "ExecStart debe ser absoluto"
    assert parts[1:3] == ["service", "run"]
    assert parts[3] == "--config"
    assert PurePosixPath(parts[4]).is_absolute(), "la config de ExecStart debe ser absoluta"
    assert _directive(service, "Restart") == "always"
    assert _directive(service, "WorkingDirectory") is not None

    assert "ODIN" in (_directive(sections["[Unit]"], "Description") or "")
    assert _directive(sections["[Install]"], "WantedBy") == "multi-user.target"


def test_rendered_unit_passes_systemd_analyze(tmp_path: Path) -> None:
    """`systemd-analyze verify` acepta una unit renderizada con rutas reales."""
    analyze = shutil.which("systemd-analyze")
    if analyze is None:
        pytest.skip("systemd-analyze no está instalado en este host")
    executable = tmp_path / "odin"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    unit_path = tmp_path / UNIT_NAME
    unit_path.write_text(
        render_unit(ServiceSpec(executable=str(executable), config_path=config_path)),
        encoding="utf-8",
    )

    result = subprocess.run(
        [analyze, "verify", str(unit_path)], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_reference_unit_passes_systemd_analyze_when_executable_exists() -> None:
    """Verify de `deploy/odin.service` solo con su binario instalado (placeholder)."""
    analyze = shutil.which("systemd-analyze")
    if analyze is None:
        pytest.skip("systemd-analyze no está instalado en este host")
    sections = _parse_sections(REFERENCE_UNIT.read_text(encoding="utf-8"))
    exec_start = _directive(sections["[Service]"], "ExecStart")
    assert exec_start is not None
    binary = Path(exec_start.split()[0])
    if not binary.exists():
        pytest.skip(
            "el ejecutable de la unit de referencia no existe en el host "
            f"({binary}): placeholder documentado, se valida la unit renderizada"
        )

    result = subprocess.run(
        [analyze, "verify", str(REFERENCE_UNIT)], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr or result.stdout


# --- capa 2: ciclo de vida por la CLI con systemctl doble ---


class FakeSystemctl:
    """Doble del ejecutor de `systemctl`: registra comandos y responde por verbo."""

    def __init__(
        self, responses: dict[str, CommandResult | list[CommandResult]] | None = None
    ) -> None:
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


def _show_output(
    *,
    load_state: str = "loaded",
    active_state: str = "active",
    unit_file_state: str = "enabled",
    restart: str = "always",
) -> str:
    return "\n".join(
        [
            f"LoadState={load_state}",
            f"ActiveState={active_state}",
            f"UnitFileState={unit_file_state}",
            f"Restart={restart}",
            "",
        ]
    )


def _write_config(
    tmp_path: Path, *, smtp_port: int = 0, schedule: str = FAR_FUTURE_SCHEDULE
) -> Path:
    """Copia el fixture Linux con `work_dir`, SMTP y horario controlados."""
    data: dict[str, Any] = json.loads(LINUX_FIXTURE.read_text(encoding="utf-8"))
    data["local"]["work_dir"] = str(tmp_path / "work")
    data["local"]["retention_days"] = 0
    data["servers"] = []
    if smtp_port:
        data["notification"]["smtp"] = {
            "host": "127.0.0.1",
            "port": smtp_port,
            "starttls": False,
            "ssl": False,
            "username": "odin-backups@example.com",
            "password": "smtp-secret",
        }
    data["scheduler"]["timezone"] = "UTC"
    data["scheduler"]["jobs"][0]["schedule"] = schedule
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_cli_lifecycle_with_fake_systemctl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """La CLI real recorre install/start/status/stop/uninstall con systemctl doble."""
    fake = FakeSystemctl({"show": CommandResult(returncode=0, stdout=_show_output())})
    unit_dir = tmp_path / "systemd"
    managers: list[LinuxServiceManager] = []

    def factory(config_path: Path | str, **kwargs: Any) -> LinuxServiceManager:
        manager = LinuxServiceManager(
            config_path,
            unit_dir=unit_dir,
            runner=fake,
            can_write_unit=lambda: True,
        )
        managers.append(manager)
        return manager

    monkeypatch.setattr("odin.cli.create_service_manager", factory)
    config_path = _write_config(tmp_path)

    assert main(["service", "install", "--config", str(config_path)]) == EXIT_OK
    assert fake.commands == [("daemon-reload",), ("enable", UNIT_NAME)]
    unit = (unit_dir / UNIT_NAME).read_text(encoding="utf-8")
    assert unit.startswith("[Unit]\n")
    assert "Type=simple" in unit
    assert "Restart=always" in unit
    assert f"service run --config {_quote_argument(str(config_path))}" in unit
    assert "Siguiente paso" in capsys.readouterr().out

    assert main(["service", "start"]) == EXIT_OK
    assert fake.commands[-1] == ("start", UNIT_NAME)

    assert main(["service", "status", "--config", str(config_path)]) == EXIT_OK
    status_out = capsys.readouterr().out
    assert "Servicio del SO (systemd): en ejecución" in status_out
    assert "Arranque automático: sí" in status_out
    assert "Reinicio ante caída: sí" in status_out
    assert "Servicio ODIN: sin estado" in status_out
    assert fake.commands[-1] == SHOW_COMMAND

    assert main(["service", "stop"]) == EXIT_OK
    assert fake.commands[-1] == ("stop", UNIT_NAME)

    assert main(["service", "uninstall"]) == EXIT_OK
    assert fake.commands[-3:] == [
        ("stop", UNIT_NAME),
        ("disable", UNIT_NAME),
        ("daemon-reload",),
    ]
    assert not (unit_dir / UNIT_NAME).exists()


def test_cli_start_failure_exits_1_with_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Un fallo del gestor (unidad ausente) se reporta con exit code 1."""
    fake = FakeSystemctl(
        {
            "start": CommandResult(
                returncode=1,
                stderr="Failed to start odin.service: Unit odin.service not found.",
            )
        }
    )

    def factory(config_path: Path | str, **kwargs: Any) -> LinuxServiceManager:
        return LinuxServiceManager(
            config_path,
            unit_dir=tmp_path / "systemd",
            runner=fake,
            can_write_unit=lambda: True,
        )

    monkeypatch.setattr("odin.cli.create_service_manager", factory)

    assert main(["service", "start"]) == EXIT_INTERNAL
    err = capsys.readouterr().err
    assert "No se pudo arrancar el servicio" in err
    assert "not found" in err


# --- capa 3: demo gated con systemd de usuario real ---


def _run_systemctl_user(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["systemctl", "--user", *args], capture_output=True, text=True, timeout=60
    )


def _user_systemd_available() -> bool:
    """Hay una sesión systemd de usuario operativa para la demo."""
    if shutil.which("systemctl") is None:
        return False
    try:
        result = _run_systemctl_user("is-system-running")
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.stdout.strip() in ("running", "degraded")


def _user_unit_dir() -> Path:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return config_home / "systemd" / "user"


def _main_pid(unit_name: str) -> int | None:
    result = _run_systemctl_user("show", unit_name, "--property=MainPID", "--no-pager")
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == "MainPID":
            try:
                return int(value.strip())
            except ValueError:
                return None
    return None


def _wait_until(condition: Callable[[], bool], *, timeout: float, what: str) -> None:
    """Espera activa con deadline: falla con contexto si ``condition`` no llega."""
    deadline = time.monotonic() + timeout
    while True:
        if condition():
            return
        if time.monotonic() >= deadline:
            raise AssertionError(f"timeout de {timeout:.0f}s esperando {what}")
        time.sleep(POLL_SECONDS)


def _write_gbak_stub(tmp_path: Path) -> Path:
    """`gbak` falso: escribe el `.fbk` de salida (3.er argumento) y sale 0."""
    stub = tmp_path / "gbak-stub.sh"
    stub.write_text('#!/bin/sh\nprintf "stub backup payload" > "$3"\n', encoding="utf-8")
    stub.chmod(0o755)
    return stub


def _write_demo_config(tmp_path: Path, *, smtp_port: int) -> Path:
    """Config acelerada para la demo: sin SFTP, stub gbak y SMTP al catcher."""
    data: dict[str, Any] = json.loads(LINUX_FIXTURE.read_text(encoding="utf-8"))
    data["databases"][0]["gbak_path"] = str(_write_gbak_stub(tmp_path))
    data["databases"][0]["connection"] = "localhost/3050:/tmp/base-inexistente.fdb"
    data["servers"] = []
    data["notification"]["log_tail_lines"] = 5
    data["notification"]["smtp"] = {
        "host": "127.0.0.1",
        "port": smtp_port,
        "starttls": False,
        "ssl": False,
        "username": "odin-backups@example.com",
        "password": "smtp-secret",
    }
    data["local"]["work_dir"] = str(tmp_path / "work")
    data["local"]["retention_days"] = 0
    data["scheduler"]["timezone"] = "UTC"
    data["scheduler"]["jobs"][0]["schedule"] = "* * * * *"
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _assert_demo_reports(catcher: SmtpCatcher) -> None:
    """Cada correo capturado es un informe ÉXITO y sin secretos."""
    assert catcher.errors == []
    assert len(catcher.messages) >= 2
    for raw in catcher.messages:
        assert "masterkey" not in raw
        assert "smtp-secret" not in raw
        message = parse_message(raw)
        assert str(message["Subject"]).startswith("[ODIN] ÉXITO")
        assert "erp_principal: OK" in message.get_content()


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("ODIN_SERVICE_DEMO") != "1",
    reason="demo con systemd de usuario real: exporte ODIN_SERVICE_DEMO=1 para ejecutarla",
)
def test_user_service_restarts_after_kill_and_delivers_cycles(tmp_path: Path) -> None:
    """systemd reinicia solo el proceso (`Restart=always`) y llega otro ciclo."""
    if not _user_systemd_available():
        pytest.skip("no hay sesión systemd de usuario operativa (systemctl --user)")

    unit_name = f"odin-intdemo-{os.getpid()}.service"
    unit_path = _user_unit_dir() / unit_name
    catcher = SmtpCatcher()
    try:
        config_path = _write_demo_config(tmp_path, smtp_port=catcher.port)
        config = load_config(config_path)
        unit_path.parent.mkdir(parents=True, exist_ok=True)
        unit_path.write_text(
            "\n".join(
                [
                    "[Unit]",
                    "Description=ODIN integration demo",
                    "",
                    "[Service]",
                    "Type=simple",
                    f"ExecStart={sys.executable} -m odin.cli service run "
                    f"--config {config_path}",
                    f"WorkingDirectory={tmp_path}",
                    "Restart=always",
                    "RestartSec=1",
                    "",
                    "[Install]",
                    "WantedBy=default.target",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        _run_systemctl_user("daemon-reload")
        _run_systemctl_user("reset-failed", unit_name)
        _run_systemctl_user("start", unit_name)
        _wait_until(
            lambda: len(catcher.messages) >= 1,
            timeout=DEMO_DEADLINE_SECONDS,
            what="primer ciclo del servicio",
        )
        first_pid = _main_pid(unit_name)
        assert first_pid is not None and first_pid > 0

        os.kill(first_pid, signal.SIGKILL)
        messages_after_kill = len(catcher.messages)
        _wait_until(
            lambda: (pid := _main_pid(unit_name)) is not None and pid != first_pid,
            timeout=DEMO_DEADLINE_SECONDS,
            what="reinicio automático de systemd con MainPID nuevo",
        )
        _wait_until(
            lambda: len(catcher.messages) > messages_after_kill,
            timeout=DEMO_DEADLINE_SECONDS,
            what="segundo ciclo tras el reinicio",
        )

        _assert_demo_reports(catcher)
        restarted_pid = _main_pid(unit_name)
        state = load_state(state_path(config.local.work_dir)).state
        assert state is not None
        assert state.pid == restarted_pid
        assert state.jobs[0].last_cycle is not None
    finally:
        with contextlib.suppress(OSError, subprocess.TimeoutExpired):
            _run_systemctl_user("stop", unit_name)
            _run_systemctl_user("reset-failed", unit_name)
        with contextlib.suppress(OSError):
            unit_path.unlink()
        with contextlib.suppress(OSError, subprocess.TimeoutExpired):
            _run_systemctl_user("daemon-reload")
        catcher.close()

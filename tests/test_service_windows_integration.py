"""Smoke del ciclo de vida real del servicio Windows sobre el SCM (Items 073/074).

Escenario **gated**: solo corre en Windows con ``ODIN_WINDOWS_SERVICE_SMOKE=1``
(lo activa el job ``windows`` de ``.github/workflows/ci.yml``; los runners son
administradores). Fuera de Windows o sin la variable se salta con motivo, igual
que las demos gated de los Items 057/066, así que la suite por defecto en Linux
no se altera.

Mecánica (sin red externa, misma que las demos del servicio Linux):

- Config con **fases externas dobles**: un ``gbak`` *stub* (``.cmd`` propio que
  escribe el ``.fbk``), ``servers: []`` sin SFTP y el catcher SMTP in-process
  (``tests/smtp_catcher.py``); scheduler habilitado con cron ``* * * * *``.
- La CLI real recorre ``install → start → status → stop → uninstall`` contra
  pywin32 y el SCM; se verifica un ciclo completo (correo ``[ODIN] ÉXITO`` y
  ``scheduler_state.json`` con el último ciclo) y el estado del servicio en el
  SCM (en ejecución, arranque automático, reinicio ante caída).
- ``uninstall`` es idempotente y la limpieza (parar + desinstalar) corre en
  ``finally`` para no dejar el servicio instalado en el runner.

La ejecución real de este escenario se registra en ``docs/service.md`` §9
(Item 074); en Linux solo se valida su recolección y su salto seguro.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from odin.cli import EXIT_OK, main
from odin.config import load_config
from odin.scheduler import load_state, state_path
from tests.smtp_catcher import SmtpCatcher, parse_message

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        sys.platform != "win32",
        reason="el ciclo de vida usa el SCM real de Windows (pywin32): solo aplica en Windows",
    ),
    pytest.mark.skipif(
        os.environ.get("ODIN_WINDOWS_SERVICE_SMOKE") != "1",
        reason="smoke del servicio Windows deshabilitado: exporte ODIN_WINDOWS_SERVICE_SMOKE=1",
    ),
]

DEMO_DEADLINE_SECONDS = 150
POLL_SECONDS = 0.5


def _write_gbak_stub(tmp_path: Path) -> Path:
    """`gbak` falso en batch: escribe el `.fbk` de salida (3.er argumento) y sale 0."""
    stub = tmp_path / "gbak-stub.cmd"
    stub.write_text(
        "@echo off\r\necho stub backup payload>\"%~3\"\r\n",
        encoding="ascii",
    )
    return stub


def _write_smoke_config(tmp_path: Path, *, smtp_port: int) -> Path:
    """Config acelerada para el smoke: stub gbak, sin SFTP y SMTP al catcher."""
    data: dict[str, Any] = {
        "databases": [
            {
                "name": "erp_principal",
                "connection": "localhost/3050:C:\\Datos\\ERP\\erp.fdb",
                "user": "SYSDBA",
                "password": "masterkey",
                "role": None,
                "charset": "ISO8859_1",
                "gbak_path": str(_write_gbak_stub(tmp_path)),
            }
        ],
        "compression": {"level": 7, "password": None},
        "servers": [],
        "notification": {
            "to": "control@example.com",
            "from": "odin-backups@example.com",
            "log_tail_lines": 5,
            "smtp": {
                "host": "127.0.0.1",
                "port": smtp_port,
                "starttls": False,
                "ssl": False,
                "username": "odin-backups@example.com",
                "password": "smtp-secret",
            },
        },
        "local": {"work_dir": str(tmp_path / "work"), "retention_days": 0},
        "scheduler": {
            "enabled": True,
            "timezone": "UTC",
            "jobs": [
                {
                    "databases": ["erp_principal"],
                    "schedule": "* * * * *",
                    "skip_if_running": True,
                    "on_misfire": "run_once",
                }
            ],
        },
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(data), encoding="utf-8")
    return config_path


def _wait_until(condition: Callable[[], bool], *, timeout: float, what: str) -> None:
    """Espera activa con deadline: falla con contexto si ``condition`` no llega."""
    deadline = time.monotonic() + timeout
    while True:
        if condition():
            return
        if time.monotonic() >= deadline:
            raise AssertionError(f"timeout de {timeout:.0f}s esperando {what}")
        time.sleep(POLL_SECONDS)


def _run_service(*args: str) -> int:
    """Ejecuta un subcomando de `odin service` por la CLI real (in-process)."""
    return main(["service", *args])


def _dump_start_failure(
    config_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Vuelca diagnóstico útil cuando el SCM no logra arrancar el servicio."""
    captured = capsys.readouterr()
    print("--- salida de 'odin service start' ---")
    print(captured.out)
    print(captured.err, file=sys.stderr)
    config = load_config(config_path)
    log_path = config.local.resolved_log_dir / "odin.log"
    if log_path.is_file():
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        print(f"--- {log_path} (últimas {min(len(lines), 40)} líneas) ---")
        print("\n".join(lines[-40:]))
    else:
        print(f"--- sin log del servicio en {log_path} ---")
    for label, directory in (
        ("exec_prefix", sys.exec_prefix),
        ("base_prefix", sys.base_prefix),
    ):
        path = Path(directory)
        dlls = sorted(item.name for item in path.glob("*.dll"))
        print(f"{label}={directory} dlls={dlls}")
    pyvenv = Path(sys.exec_prefix) / "pyvenv.cfg"
    if pyvenv.is_file():
        print(f"--- {pyvenv} ---")
        print(pyvenv.read_text(encoding="utf-8", errors="replace"))
    query = subprocess.run(
        ["sc.exe", "query", "odin"], capture_output=True, text=True, timeout=30
    )
    print("--- sc query odin ---")
    print(query.stdout or query.stderr)
    _dump_service_registry()
    _dump_event_log()
    _dump_host_debug()


def _dump_service_registry() -> None:
    """Muestra el ImagePath y las opciones persistidas del servicio."""
    import winreg

    key_path = r"SYSTEM\CurrentControlSet\Services\odin"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
            for name in ("ImagePath", "ObjectName", "PythonClass"):
                try:
                    print(f"{name}={winreg.QueryValueEx(key, name)[0]}")
                except FileNotFoundError:
                    print(f"{name}=<ausente>")
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path + r"\Parameters") as key:
            index = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, index)
                except OSError:
                    break
                print(f"Parameters.{name}={value!r}")
                index += 1
    except OSError as exc:
        print(f"no se pudo leer el registro del servicio: {exc}")


def _dump_event_log() -> None:
    """Muestra los últimos eventos de Application ligados a Python/ODIN."""
    try:
        query = subprocess.run(
            ["wevtutil", "qe", "Application", "/c:60", "/rd:true", "/f:text"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"no se pudo leer el Event Log: {exc}")
        return
    blocks = [
        block
        for block in (query.stdout or "").split("\n\n")
        if block.strip()
        and any(
            needle in block.lower()
            for needle in ("python", "odin", "pythonservice")
        )
    ]
    print("--- Event Log (Application, python/odin) ---")
    print("\n\n".join(blocks[-6:]) or "sin eventos de Python/ODIN")


def _as_text(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


def _dump_host_debug() -> None:
    """Corre el host en modo ``-debug`` (sin SCM) para ver el error real."""
    host = Path(sys.exec_prefix) / "pythonservice.exe"
    if not host.is_file():
        print(f"--- host del servicio ausente: {host} ---")
        return
    try:
        completed = subprocess.run(
            [str(host), "-debug", "odin"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired as exc:
        print("--- host en modo -debug: siguió vivo (arranque OK) ---")
        print(_as_text(exc.stdout))
        print(_as_text(exc.stderr), file=sys.stderr)
        return
    except OSError as exc:
        print(f"no se pudo ejecutar el host en modo -debug: {exc}")
        return
    print("--- host en modo -debug ---")
    print(completed.stdout or "")
    print(completed.stderr or "", file=sys.stderr)


def test_windows_service_smoke_lifecycle(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ciclo real install/start/status/stop/uninstall con un ciclo del scheduler."""
    catcher = SmtpCatcher()
    config_path = _write_smoke_config(tmp_path, smtp_port=catcher.port)
    try:
        # Estado limpio: una corrida previa fallida no debe romper el smoke.
        assert _run_service("uninstall") == EXIT_OK
        capsys.readouterr()

        assert _run_service("install", "--config", str(config_path)) == EXIT_OK
        install_out = capsys.readouterr().out
        assert "instalado" in install_out
        assert "arranque automático" in install_out
        assert "reinicio ante caída activado" in install_out
        assert str(config_path) in install_out

        start_code = _run_service("start")
        if start_code != EXIT_OK:
            _dump_start_failure(config_path, capsys)
        assert start_code == EXIT_OK
        assert "arrancado" in capsys.readouterr().out

        _wait_until(
            lambda: len(catcher.messages) >= 1,
            timeout=DEMO_DEADLINE_SECONDS,
            what="primer ciclo del servicio (correo capturado)",
        )

        assert _run_service("status", "--config", str(config_path)) == EXIT_OK
        status_out = capsys.readouterr().out
        assert "Servicio del SO (windows): en ejecución." in status_out
        assert "Arranque automático: sí" in status_out
        assert "Reinicio ante caída: sí" in status_out
        assert "Scheduler:" in status_out

        config = load_config(config_path)
        state = load_state(state_path(config.local.work_dir)).state
        assert state is not None
        assert state.jobs[0].last_cycle is not None
        assert state.jobs[0].last_cycle.notification_sent is True

        _assert_smoke_reports(catcher)

        assert _run_service("stop") == EXIT_OK
        assert "detenido" in capsys.readouterr().out

        assert _run_service("uninstall") == EXIT_OK
        capsys.readouterr()
        assert _run_service("uninstall") == EXIT_OK
        assert "no estaba instalado" in capsys.readouterr().out

        assert _run_service("status", "--config", str(config_path)) == EXIT_OK
        assert "no instalado" in capsys.readouterr().out
    finally:
        with contextlib.suppress(Exception):
            _run_service("stop")
        with contextlib.suppress(Exception):
            _run_service("uninstall")
        catcher.close()


def _assert_smoke_reports(catcher: SmtpCatcher) -> None:
    """Cada correo capturado es un informe ÉXITO y sin secretos."""
    assert catcher.errors == []
    assert len(catcher.messages) >= 1
    for raw in catcher.messages:
        assert "masterkey" not in raw
        assert "smtp-secret" not in raw
        message = parse_message(raw)
        assert str(message["Subject"]).startswith("[ODIN] ÉXITO")
        assert "erp_principal: OK" in message.get_content()

"""Demo end-to-end en foreground del scheduler (Item 057).

Cubre el criterio de aceptación de la Etapa 6: un proceso en primer plano con
jobs cada 1–2 minutos ejecuta el flujo completo y envía el correo por ciclo.
Los casos por defecto corren `odin service run` **real** (`cli.main` →
`SchedulerService` → `PipelineCycleRunner` → `run_pipeline` → `EmailNotifier`)
contra el catcher SMTP in-process compartido del Item 047
(`tests/smtp_catcher.py`), doblando solo las fases externas
(respaldo/compresión/transferencia/retención) para no depender de
gbak/Firebird/SFTP:

- ``test_foreground_service_cycles_mail_state_and_live_status``: dos ciclos
  reales disparados por APScheduler (cadencia acortada con ``modify_job`` para
  no esperar al reloj), dos correos, estado actualizado tras cada ciclo,
  ``odin service status`` coherente en caliente y parada limpia (``EXIT_OK``).
- ``test_foreground_process_stops_cleanly_on_sigterm``: el proceso real en
  primer plano responde a ``SIGTERM`` con salida 0 y estado final persistido.
- ``test_foreground_service_real_cron_cadence``: la demo exacta con cron
  ``* * * * *`` y espera de ~2 minutos; solo corre con
  ``ODIN_FOREGROUND_DEMO=1`` para no penalizar la suite por defecto.

El README documenta el procedimiento manual con la misma cadencia de 1–2
minutos.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from apscheduler.triggers.interval import IntervalTrigger

from odin import cli as cli_module
from odin.backup import BackupResult, BatchBackupResult
from odin.cli import EXIT_OK, main
from odin.compress import BatchCompressionResult, CompressionResult
from odin.config import Config, DatabaseConfig, load_config
from odin.log import LOG_FILENAME, LOGGER_NAME
from odin.retention import RetentionResult
from odin.scheduler import (
    CycleStatus,
    SchedulerService,
    ServiceState,
    load_state,
    reload_request_path,
    state_path,
)
from odin.transfer import TransferResult
from tests.smtp_catcher import SmtpCatcher, parse_message

FIXTURES = Path(__file__).parent / "fixtures"
LINUX_FIXTURE = FIXTURES / "config_valid_linux.json"
PAYLOAD = b"ODIN foreground demo payload " * 32
TIMESTAMP = "20260915_120000"
FAST_CADENCE_SECONDS = 2
FAR_FUTURE_SCHEDULE = "0 3 1 1 *"
DEMO_DEADLINE_SECONDS = 150
POLL_SECONDS = 0.05


@pytest.fixture(autouse=True)
def clean_odin_logger() -> Iterator[None]:
    """Limpia el logger ``odin`` tras cada test (sin handlers abiertos)."""
    yield
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.setLevel(logging.NOTSET)
    logger.propagate = True


def _write_config(tmp_path: Path, *, smtp_port: int, schedule: str = "* * * * *") -> Path:
    """Copia el fixture Linux y apunta SMTP, ``work_dir`` y horario al test."""
    data: dict[str, Any] = json.loads(LINUX_FIXTURE.read_text(encoding="utf-8"))
    data["local"]["work_dir"] = str(tmp_path / "work")
    data["local"]["retention_days"] = 0
    data["servers"] = data["servers"][:1]
    notification = data["notification"]
    notification["log_tail_lines"] = 5
    notification["smtp"] = {
        "host": "127.0.0.1",
        "port": smtp_port,
        "starttls": False,
        "ssl": False,
        "username": "smtp-user",
        "password": "smtp-secret",
    }
    scheduler = data["scheduler"]
    scheduler["timezone"] = "UTC"
    scheduler["jobs"][0]["schedule"] = schedule
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class _FakeBackupExecutor:
    """Doble de gbak: escribe un ``.fbk`` real por base."""

    def __init__(self, gbak_path: Any = None, timeout: Any = None) -> None:
        self.gbak_path = gbak_path
        self.timeout = timeout

    def run_batch_backup(
        self, databases: Sequence[DatabaseConfig], work_dir: Path
    ) -> BatchBackupResult:
        results: list[BackupResult] = []
        for database in databases:
            backup_path = work_dir / f"{database.name}_{TIMESTAMP}.fbk"
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            backup_path.write_bytes(PAYLOAD)
            results.append(
                BackupResult(
                    success=True,
                    database_name=database.name,
                    backup_path=backup_path,
                    file_size_bytes=len(PAYLOAD),
                    duration_seconds=0.05,
                )
            )
        return BatchBackupResult(
            results=results, success=bool(results), total_duration_seconds=0.05
        )


class _FakeCompressionExecutor:
    """Doble de 7z: crea el ``.fbk.7z`` como copia del ``.fbk``."""

    def __init__(self, level: Any = None, password: Any = None) -> None:
        self.level = level
        self.password = password

    def run_batch_compression(
        self, backups: Sequence[BackupResult]
    ) -> BatchCompressionResult:
        results: list[CompressionResult] = []
        for backup in backups:
            if not backup.success or backup.backup_path is None:
                continue
            source = backup.backup_path
            archive = source.with_name(f"{source.name}.7z")
            archive.write_bytes(source.read_bytes())
            results.append(
                CompressionResult(
                    success=True,
                    database_name=backup.database_name,
                    source_path=source,
                    archive_path=archive,
                    original_size_bytes=backup.file_size_bytes,
                    compressed_size_bytes=archive.stat().st_size,
                    compression_ratio=1.0,
                    duration_seconds=0.05,
                )
            )
        return BatchCompressionResult(
            results=results, success=bool(results), total_duration_seconds=0.05
        )


class _FakeTransferExecutor:
    """Doble SFTP: éxito por servidor verificando el tamaño del ``.fbk.7z``."""

    def run_batch_transfer(
        self, servers: Sequence[Any], local_path: Path
    ) -> list[TransferResult]:
        size = local_path.stat().st_size
        return [
            TransferResult(
                success=True,
                server_name=server.name,
                local_path=local_path,
                remote_path=f"{server.remote_path}/{local_path.name}",
                transferred_bytes=size,
                duration_seconds=0.02,
            )
            for server in servers
        ]


class _FakeRetentionExecutor:
    """Doble de retención: no-op deshabilitado (no toca el ``work_dir``)."""

    def run_retention(self, work_dir: Path, retention_days: int) -> RetentionResult:
        return RetentionResult(enabled=False)


def _install_fake_phases(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dobla solo las fases externas: CLI → servicio → pipeline quedan reales."""
    monkeypatch.setattr("odin.pipeline.BackupExecutor", _FakeBackupExecutor)
    monkeypatch.setattr("odin.pipeline.CompressionExecutor", _FakeCompressionExecutor)
    monkeypatch.setattr("odin.pipeline.TransferExecutor", _FakeTransferExecutor)
    monkeypatch.setattr("odin.pipeline.RetentionExecutor", _FakeRetentionExecutor)


def _start_foreground(
    config_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[threading.Thread, dict[str, int], list[SchedulerService]]:
    """Corre ``odin service run`` en un hilo con la fábrica real instrumentada.

    Fuera del hilo principal los contextos de señal de la CLI no tocan
    ``signal``, así que pytest no se ve afectado; la parada se pide con
    ``service.shutdown()``, el mismo camino que ejecuta el ``finally`` de
    ``_cmd_service_run`` tras atender ``SIGINT``/``SIGTERM``.
    """
    real_factory = cli_module._build_scheduler_service
    captured: list[SchedulerService] = []

    def factory(config: Config, *, state_store: Any) -> SchedulerService:
        service = real_factory(config, state_store=state_store)
        captured.append(service)
        return service

    monkeypatch.setattr(cli_module, "_build_scheduler_service", factory)
    result: dict[str, int] = {}

    def target() -> None:
        result["code"] = main(["service", "run", "--config", str(config_path)])

    thread = threading.Thread(target=target, name="odin-service-run", daemon=True)
    thread.start()
    return thread, result, captured


def _wait_until(condition: Callable[[], bool], *, timeout: float, what: str) -> None:
    """Espera activa con deadline: falla con contexto si ``condition`` no llega."""
    deadline = time.monotonic() + timeout
    while True:
        if condition():
            return
        if time.monotonic() >= deadline:
            raise AssertionError(f"timeout de {timeout:.0f}s esperando {what}")
        time.sleep(POLL_SECONDS)


def _load_running_state(work_dir: Path) -> ServiceState | None:
    return load_state(state_path(work_dir)).state


def _state_pid(work_dir: Path) -> int | None:
    state = _load_running_state(work_dir)
    return state.pid if state is not None else None


def _has_cycle(work_dir: Path) -> bool:
    state = _load_running_state(work_dir)
    return bool(state and state.jobs and state.jobs[0].last_cycle is not None)


def _state_updated_after(work_dir: Path, reference: ServiceState) -> bool:
    state = _load_running_state(work_dir)
    return state is not None and state.updated_at > reference.updated_at


def _log_contains(path: Path, text: str) -> bool:
    try:
        return text in path.read_text(encoding="utf-8")
    except OSError:
        return False


def _assert_success_reports(catcher: SmtpCatcher) -> None:
    """Los correos capturados son informes de ÉXITO por ciclo y sin secretos."""
    assert catcher.errors == []
    assert len(catcher.messages) == 2
    assert catcher.recipients == ["control@example.com"] * 2
    for raw in catcher.messages:
        assert "masterkey" not in raw
        assert "remote-secret-1" not in raw
        assert "smtp-secret" not in raw
        message = parse_message(raw)
        assert str(message["Subject"]).startswith("[ODIN] ÉXITO")
        body = message.get_content()
        assert "Estado global: ÉXITO" in body
        assert "- erp_principal: OK" in body
        assert "sitio-alterno-1: OK" in body
        assert "Totales: 1/1 base(s) OK" in body


@pytest.mark.integration
def test_foreground_service_cycles_mail_state_and_live_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Dos ciclos en primer plano: correo por ciclo, estado y ``status`` en vivo."""
    catcher = SmtpCatcher()
    try:
        config_path = _write_config(tmp_path, smtp_port=catcher.port)
        _install_fake_phases(monkeypatch)
        thread, result, captured = _start_foreground(config_path, monkeypatch)
        _wait_until(
            lambda: bool(captured) and captured[0].scheduler.running,
            timeout=20,
            what="scheduler en ejecución",
        )
        service = captured[0]
        config = load_config(config_path)
        work_dir = config.local.work_dir
        try:
            service.scheduler.modify_job(
                "job-0",
                trigger=IntervalTrigger(seconds=FAST_CADENCE_SECONDS, timezone=service.timezone),
                next_run_time=datetime.now(service.timezone),
            )
            _wait_until(
                lambda: len(catcher.messages) >= 1,
                timeout=30,
                what="primer correo del ciclo",
            )
            _wait_until(
                lambda: _has_cycle(work_dir), timeout=10, what="primer ciclo en el estado"
            )
            first_state = _load_running_state(work_dir)
            _wait_until(
                lambda: len(catcher.messages) >= 2,
                timeout=30,
                what="segundo correo del ciclo",
            )
            assert first_state is not None
            _wait_until(
                lambda: _state_updated_after(work_dir, first_state),
                timeout=10,
                what="segundo ciclo en el estado",
            )
            second_state = _load_running_state(work_dir)

            assert main(["service", "status", "--config", str(config_path)]) == EXIT_OK
            status_output = capsys.readouterr().out
            assert f"Servicio ODIN: en ejecución (pid {os.getpid()})" in status_output
            assert "Salud: OK" in status_output
            assert "job-0" in status_output
            assert "Último ciclo: success" in status_output
            assert "correo enviado" in status_output
        finally:
            if captured[0].scheduler.running:
                captured[0].shutdown()
        thread.join(timeout=15)
        assert not thread.is_alive()
        assert result.get("code") == EXIT_OK

        _assert_success_reports(catcher)
        assert second_state is not None
        for state in (first_state, second_state):
            assert state.jobs[0].job_id == "job-0"
            assert state.jobs[0].last_cycle is not None
            assert state.jobs[0].last_cycle.status is CycleStatus.SUCCESS
            assert state.jobs[0].last_cycle.notification_sent is True
            assert state.jobs[0].last_cycle.databases == ("erp_principal",)
            assert state.recent_errors == ()

        final_state = _load_running_state(work_dir)
        assert final_state is not None
        assert final_state.pid == os.getpid()
        assert final_state.jobs[0].next_fire_time is not None
        assert final_state.jobs[0].last_cycle is not None
        assert final_state.jobs[0].last_cycle.status is CycleStatus.SUCCESS

        log_text = (config.local.resolved_log_dir / LOG_FILENAME).read_text(encoding="utf-8")
        state_text = state_path(work_dir).read_text(encoding="utf-8")
        for secret in ("masterkey", "remote-secret-1", "smtp-secret"):
            assert secret not in log_text
            assert secret not in state_text
    finally:
        catcher.close()


@pytest.mark.integration
@pytest.mark.skipif(sys.platform == "win32", reason="SIGTERM de proceso en POSIX")
def test_foreground_process_stops_cleanly_on_sigterm(tmp_path: Path) -> None:
    """El proceso real en primer plano atiende ``SIGTERM`` con exit code 0."""
    catcher = SmtpCatcher()
    try:
        config_path = _write_config(
            tmp_path, smtp_port=catcher.port, schedule=FAR_FUTURE_SCHEDULE
        )
        config = load_config(config_path)
        work_dir = config.local.work_dir
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "odin.cli",
                "service",
                "run",
                "--config",
                str(config_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            _wait_until(
                lambda: _state_pid(work_dir) == process.pid,
                timeout=30,
                what="estado del proceso en primer plano",
            )
            initial_state = _load_running_state(work_dir)
            assert initial_state is not None
            log_path = config.local.resolved_log_dir / LOG_FILENAME
            _wait_until(
                lambda: _log_contains(log_path, "Scheduler iniciado"),
                timeout=15,
                what="scheduler iniciado en el log",
            )
            status = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "odin.cli",
                    "service",
                    "status",
                    "--config",
                    str(config_path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert status.returncode == EXIT_OK
            assert f"Servicio ODIN: en ejecución (pid {process.pid})" in status.stdout

            process.send_signal(signal.SIGTERM)
            try:
                exit_code = process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                raise
            output = process.stdout.read() if process.stdout is not None else ""
            assert exit_code == EXIT_OK, output
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)

        final = load_state(state_path(work_dir))
        assert final.state is not None
        assert final.state.pid == process.pid
        assert final.state.updated_at >= initial_state.updated_at
        assert final.stale is True
        assert not reload_request_path(work_dir).exists()
    finally:
        catcher.close()


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("ODIN_FOREGROUND_DEMO") != "1",
    reason="demo de cadencia real (~2 min): exporte ODIN_FOREGROUND_DEMO=1 para ejecutarla",
)
def test_foreground_service_real_cron_cadence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Demo exacta del criterio: dos ciclos con cron real ``* * * * *``."""
    catcher = SmtpCatcher()
    try:
        config_path = _write_config(tmp_path, smtp_port=catcher.port)
        config = load_config(config_path)
        work_dir = config.local.work_dir
        _install_fake_phases(monkeypatch)
        thread, result, captured = _start_foreground(config_path, monkeypatch)
        _wait_until(
            lambda: bool(captured) and captured[0].scheduler.running,
            timeout=20,
            what="scheduler en ejecución",
        )
        try:
            _wait_until(
                lambda: len(catcher.messages) >= 1,
                timeout=DEMO_DEADLINE_SECONDS,
                what="primer correo del cron real",
            )
            _wait_until(
                lambda: _has_cycle(work_dir), timeout=15, what="primer ciclo en el estado"
            )
            first_state = _load_running_state(work_dir)
            assert first_state is not None
            _wait_until(
                lambda: len(catcher.messages) >= 2,
                timeout=DEMO_DEADLINE_SECONDS,
                what="segundo correo del cron real",
            )
            _wait_until(
                lambda: _state_updated_after(work_dir, first_state),
                timeout=15,
                what="segundo ciclo en el estado",
            )
        finally:
            if captured[0].scheduler.running:
                captured[0].shutdown()
        thread.join(timeout=20)
        assert not thread.is_alive()
        assert result.get("code") == EXIT_OK
        _assert_success_reports(catcher)
        final_state = _load_running_state(work_dir)
        assert final_state is not None
        assert final_state.jobs[0].last_cycle is not None
        assert final_state.jobs[0].last_cycle.status is CycleStatus.SUCCESS
        assert final_state.recent_errors == ()
    finally:
        catcher.close()

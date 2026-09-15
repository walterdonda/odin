"""Test de integración del scheduler con el SMTP efímero (Item 056).

Ejercita el camino real del ciclo: un ``SchedulerService`` real, con
``PipelineCycleRunner`` real sobre ``run_pipeline`` real y fases dobles
(respaldo, compresión, transferencia y retención), dispara por la entrada que
usa APScheduler (``service.run_job``) y el ``EmailNotifier`` real entrega el
informe de cada ciclo al catcher SMTP in-process compartido con el Item 047
(``tests/smtp_catcher.py``). Es el sustituto local y determinista de la demo de
correo por ciclo: no requiere servicios externos (SMTP real sobre loopback,
fases dobles) ni espera el reloj.

Se verifican: el informe ÉXITO y el FALLO, la actualización de
``scheduler_state.json`` (último ciclo + próximo disparo), la recuperación del
servicio tras un ciclo fallido y la ausencia de secretos en mensaje, log y
estado.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from odin.backup import BackupResult, BatchBackupResult
from odin.compress import BatchCompressionResult, CompressionResult
from odin.config import Config, DatabaseConfig, load_config
from odin.log import LOG_FILENAME, LOGGER_NAME, SecretMasker, setup_logging
from odin.retention import RetentionResult
from odin.scheduler import (
    CycleStatus,
    PipelineCycleRunner,
    SchedulerService,
    SchedulerStateStore,
    load_state,
    state_path,
)
from odin.transfer import TransferResult
from tests.smtp_catcher import SmtpCatcher, parse_message

FIXTURES = Path(__file__).parent / "fixtures"
LINUX_FIXTURE = FIXTURES / "config_valid_linux.json"
FIXED_NOW = datetime(2026, 9, 15, 12, 30, tzinfo=UTC)
PAYLOAD = b"ODIN scheduler integration payload " * 32
TIMESTAMP = "20260915_120000"


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


def _write_config(tmp_path: Path, *, smtp_port: int) -> Path:
    """Copia el fixture Linux y apunta SMTP/SMTP y ``work_dir`` al test."""
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
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class _FakeBackupExecutor:
    """Doble de gbak: escribe un ``.fbk`` real por base y falla si se pide."""

    def __init__(self, gbak_path: Any = None, timeout: Any = None) -> None:
        self.gbak_path = gbak_path
        self.timeout = timeout
        self.fail = False
        self.calls = 0

    def run_batch_backup(
        self, databases: Sequence[DatabaseConfig], work_dir: Path
    ) -> BatchBackupResult:
        self.calls += 1
        if self.fail:
            return BatchBackupResult(
                results=[
                    BackupResult(
                        success=False,
                        database_name=database.name,
                        error_message="gbak: error simulado",
                    )
                    for database in databases
                ],
                success=False,
                total_duration_seconds=0.05,
            )
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
        return BatchBackupResult(results=results, success=True, total_duration_seconds=0.05)


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


def _build_service(
    config: Config, backup: _FakeBackupExecutor
) -> tuple[SchedulerService, SchedulerStateStore]:
    """Servicio real con runner real sobre el pipeline y fases dobles."""
    store = SchedulerStateStore(
        state_path(config.local.work_dir),
        pid=os.getpid(),
        config_path=str(config.config_path),
        started_at=FIXED_NOW,
        mask=SecretMasker.from_config(config).mask,
    )
    runner = PipelineCycleRunner(
        backup=backup,
        compression=_FakeCompressionExecutor(),
        transfer=_FakeTransferExecutor(),
        retention=_FakeRetentionExecutor(),
    )
    service = SchedulerService(
        config, cycle_runner=runner, now=lambda: FIXED_NOW, state_store=store
    )
    return service, store


def _close_logging() -> None:
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


@pytest.mark.integration
def test_scheduler_cycle_delivers_report_and_updates_state(tmp_path: Path) -> None:
    catcher = SmtpCatcher()
    try:
        config_path = _write_config(tmp_path, smtp_port=catcher.port)
        config = load_config(config_path)
        backup = _FakeBackupExecutor()
        service, store = _build_service(config, backup)
        setup_logging(config)
        try:
            outcome = service.run_job("job-0")
        finally:
            _close_logging()
    finally:
        catcher.close()

    assert outcome.status is CycleStatus.SUCCESS
    assert outcome.notification_sent is True
    assert outcome.databases == ("erp_principal",)

    assert catcher.errors == []
    assert catcher.recipients == ["control@example.com"]
    assert len(catcher.messages) == 1
    raw = catcher.messages[0]
    message = parse_message(raw)
    assert str(message["Subject"]).startswith("[ODIN] ÉXITO")
    body = message.get_content()
    assert "Estado global: ÉXITO" in body
    assert "- erp_principal: OK" in body
    assert "sitio-alterno-1: OK" in body
    assert "Totales: 1/1 base(s) OK" in body

    state = load_state(store.path).state
    assert state is not None
    job = state.jobs[0]
    assert job.job_id == "job-0"
    assert job.next_fire_time is not None
    assert job.last_cycle is not None
    assert job.last_cycle.status is CycleStatus.SUCCESS
    assert job.last_cycle.databases == ("erp_principal",)
    assert job.last_cycle.notification_sent is True
    assert state.recent_errors == ()

    log_text = (config.local.resolved_log_dir / LOG_FILENAME).read_text(encoding="utf-8")
    state_text = store.path.read_text(encoding="utf-8")
    for secret in ("masterkey", "remote-secret-1", "smtp-secret"):
        assert secret not in raw
        assert secret not in body
        assert secret not in log_text
        assert secret not in state_text


@pytest.mark.integration
def test_scheduler_cycle_failure_sends_report_and_service_stays_operative(
    tmp_path: Path,
) -> None:
    catcher = SmtpCatcher()
    try:
        config_path = _write_config(tmp_path, smtp_port=catcher.port)
        config = load_config(config_path)
        backup = _FakeBackupExecutor()
        service, store = _build_service(config, backup)

        backup.fail = True
        first = service.run_job("job-0")
        backup.fail = False
        second = service.run_job("job-0")
    finally:
        catcher.close()

    assert first.status is CycleStatus.FAILURE
    assert first.notification_sent is True
    assert first.error_message is not None
    assert "gbak: error simulado" in first.error_message
    assert second.status is CycleStatus.SUCCESS
    assert service.last_outcomes["job-0"] is second

    assert len(catcher.messages) == 2
    failure_message = parse_message(catcher.messages[0])
    assert str(failure_message["Subject"]).startswith("[ODIN] FALLO")
    failure_body = failure_message.get_content()
    assert "Estado global: FALLO" in failure_body
    assert "gbak: error simulado" in failure_body
    success_message = parse_message(catcher.messages[1])
    assert str(success_message["Subject"]).startswith("[ODIN] ÉXITO")
    assert "Estado global: ÉXITO" in success_message.get_content()

    state = load_state(store.path).state
    assert state is not None
    assert state.jobs[0].last_cycle is not None
    assert state.jobs[0].last_cycle.status is CycleStatus.SUCCESS
    assert any("gbak: error simulado" in error for error in state.recent_errors)

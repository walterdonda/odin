"""Tests del pipeline de ``odin run``: respaldo → compresión → transferencia → correo."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from odin.backup import BackupResult, BatchBackupResult
from odin.compress import BatchCompressionResult, CompressionResult
from odin.config import Config, ServerConfig, load_config
from odin.notify import NotificationResult, ReportMessage
from odin.pipeline import PipelineResult, run_pipeline
from odin.transfer import BatchTransferResult, TransferResult

FIXTURES = Path(__file__).parent / "fixtures"

ARCHIVE_SUFFIX = ".fbk.7z"


def _config(
    tmp_path: Path, *, servers: bool = True, log_tail_lines: int | None = None
) -> Config:
    """Config Linux válida con ``work_dir`` en ``tmp_path`` (servidores opcionales)."""
    data: dict[str, Any] = json.loads(
        (FIXTURES / "config_valid_linux.json").read_text(encoding="utf-8")
    )
    data["local"]["work_dir"] = str(tmp_path / "work")
    if not servers:
        data["servers"] = []
    if log_tail_lines is not None:
        data["notification"]["log_tail_lines"] = log_tail_lines
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return load_config(str(path))


def _backup_result(name: str, success: bool = True) -> BackupResult:
    if success:
        return BackupResult(
            success=True,
            database_name=name,
            backup_path=Path(f"/work/{name}.fbk"),
            file_size_bytes=100,
            duration_seconds=0.1,
        )
    return BackupResult(
        success=False,
        database_name=name,
        duration_seconds=0.1,
        error_message="gbak falló (código 1): database is in use",
    )


def _compression_result(name: str, success: bool = True) -> CompressionResult:
    if success:
        return CompressionResult(
            success=True,
            database_name=name,
            source_path=Path(f"/work/{name}.fbk"),
            archive_path=Path(f"/work/{name}{ARCHIVE_SUFFIX}"),
            original_size_bytes=100,
            compressed_size_bytes=40,
            compression_ratio=0.4,
            duration_seconds=0.1,
        )
    return CompressionResult(
        success=False,
        database_name=name,
        source_path=Path(f"/work/{name}.fbk"),
        duration_seconds=0.1,
        error_message="no se pudo comprimir: disco lleno",
    )


class FakeBackupExecutor:
    def __init__(self, results: list[BackupResult]) -> None:
        self._results = results
        self.calls = 0

    def run_batch_backup(self, databases: list[Any], work_dir: Path) -> BatchBackupResult:
        self.calls += 1
        return BatchBackupResult(
            results=self._results,
            success=bool(self._results) and all(result.success for result in self._results),
            total_duration_seconds=0.1,
        )


class FakeCompressionExecutor:
    def __init__(self, outcomes: dict[str, CompressionResult]) -> None:
        self._outcomes = outcomes

    def run_batch_compression(self, backups: list[BackupResult]) -> BatchCompressionResult:
        results = [
            self._outcomes[backup.database_name]
            for backup in backups
            if backup.success and backup.database_name in self._outcomes
        ]
        return BatchCompressionResult(
            results=results,
            success=bool(results) and all(result.success for result in results),
            total_duration_seconds=0.1,
        )


class FakeTransferExecutor:
    def __init__(
        self,
        outcome: Callable[[list[ServerConfig], Path], list[TransferResult]],
    ) -> None:
        self._outcome = outcome
        self.calls: list[tuple[list[ServerConfig], Path]] = []

    def run_batch_transfer(
        self, servers: list[ServerConfig], local_path: Path
    ) -> list[TransferResult]:
        self.calls.append((servers, Path(local_path)))
        return self._outcome(servers, local_path)


def _all_ok(servers: list[ServerConfig], local_path: Path) -> list[TransferResult]:
    size = local_path.stat().st_size if local_path.exists() else 40
    return [
        TransferResult(
            success=True,
            server_name=server.name,
            local_path=local_path,
            remote_path=f"{server.remote_path}/{local_path.name}",
            transferred_bytes=size,
            duration_seconds=0.05,
        )
        for server in servers
    ]


def _fail_first(servers: list[ServerConfig], local_path: Path) -> list[TransferResult]:
    results = _all_ok(servers, local_path)
    if results:
        results[0] = TransferResult(
            success=False,
            server_name=results[0].server_name,
            local_path=local_path,
            remote_path=results[0].remote_path,
            duration_seconds=0.05,
            error_message="Connection error: refused",
        )
    return results


def _all_fail(servers: list[ServerConfig], local_path: Path) -> list[TransferResult]:
    return [
        TransferResult(
            success=False,
            server_name=server.name,
            local_path=local_path,
            remote_path=f"{server.remote_path}/{local_path.name}",
            duration_seconds=0.05,
            error_message="Authentication failed",
        )
        for server in servers
    ]


class FakeNotifier:
    """Doble de ``EmailNotifier``: registra los informes y permite forzar el desenlace."""

    def __init__(
        self,
        result: NotificationResult | None = None,
        exception: Exception | None = None,
    ) -> None:
        self._result = result
        self._exception = exception
        self.calls: list[ReportMessage] = []
        self.to = "control@example.com"

    def send(self, report: ReportMessage) -> NotificationResult:
        self.calls.append(report)
        if self._exception is not None:
            raise self._exception
        if self._result is not None:
            return self._result
        return NotificationResult(success=True, recipient=self.to, duration_seconds=0.01)


class _OfflineNotifier:
    """Notifier default sin red para los tests que no inyectan uno propio."""

    def __init__(self) -> None:
        self.to = "control@example.com"

    @classmethod
    def from_config(cls, config: Config) -> _OfflineNotifier:
        return cls()

    def send(self, report: ReportMessage) -> NotificationResult:
        return NotificationResult(success=True, recipient=self.to)


@pytest.fixture(autouse=True)
def offline_notifier(monkeypatch: pytest.MonkeyPatch) -> None:
    """Evita que el notifier default abra SMTP real (Item 043)."""
    monkeypatch.setattr("odin.pipeline.EmailNotifier", _OfflineNotifier)


def test_full_success_runs_all_three_phases(tmp_path: Path) -> None:
    config = _config(tmp_path)
    transfer = FakeTransferExecutor(_all_ok)

    result = run_pipeline(
        config,
        backup=FakeBackupExecutor([_backup_result("erp_principal")]),
        compression=FakeCompressionExecutor(
            {"erp_principal": _compression_result("erp_principal")}
        ),
        transfer=transfer,
    )

    assert isinstance(result, PipelineResult)
    assert result.backup.success is True
    assert result.backup.results[0].success is True
    assert result.backup.results[0].transfer_error_message is None
    assert set(result.transfers) == {"erp_principal"}
    batch_transfer = result.transfers["erp_principal"]
    assert isinstance(batch_transfer, BatchTransferResult)
    assert batch_transfer.success is True
    assert len(batch_transfer.results) == 2
    assert all(transfer_result.success for transfer_result in batch_transfer.results)
    assert batch_transfer.total_duration_seconds > 0
    assert len(transfer.calls) == 1
    servers, archive = transfer.calls[0]
    assert servers == list(config.servers)
    assert archive == Path("/work/erp_principal.fbk.7z")


def test_transfer_failure_marks_database_failed(tmp_path: Path) -> None:
    config = _config(tmp_path)
    transfer = FakeTransferExecutor(_fail_first)

    result = run_pipeline(
        config,
        backup=FakeBackupExecutor([_backup_result("erp_principal")]),
        compression=FakeCompressionExecutor(
            {"erp_principal": _compression_result("erp_principal")}
        ),
        transfer=transfer,
    )

    assert result.backup.success is False
    failed = result.backup.results[0]
    assert failed.success is False
    assert failed.transfer_error_message is not None
    assert "sitio-alterno-1" in failed.transfer_error_message
    assert "Connection error: refused" in failed.transfer_error_message
    assert failed.backup_path is not None
    assert failed.archive_path is not None
    batch_transfer = result.transfers["erp_principal"]
    assert batch_transfer.success is False
    assert batch_transfer.results[0].success is False
    assert batch_transfer.results[1].success is True


def test_backup_failure_is_not_transferred(tmp_path: Path) -> None:
    config = _config(tmp_path)
    transfer = FakeTransferExecutor(_all_ok)

    result = run_pipeline(
        config,
        backup=FakeBackupExecutor([_backup_result("erp_principal", success=False)]),
        compression=FakeCompressionExecutor({}),
        transfer=transfer,
    )

    assert transfer.calls == []
    assert result.transfers == {}
    assert result.backup.success is False
    assert "database is in use" in (result.backup.results[0].error_message or "")


def test_compression_failure_is_not_transferred(tmp_path: Path) -> None:
    config = _config(tmp_path)
    transfer = FakeTransferExecutor(_all_ok)

    result = run_pipeline(
        config,
        backup=FakeBackupExecutor([_backup_result("erp_principal")]),
        compression=FakeCompressionExecutor(
            {"erp_principal": _compression_result("erp_principal", success=False)}
        ),
        transfer=transfer,
    )

    assert transfer.calls == []
    assert result.transfers == {}
    failed = result.backup.results[0]
    assert failed.success is False
    assert failed.compression_error_message == "no se pudo comprimir: disco lleno"
    assert failed.transfer_error_message is None


def test_no_servers_skips_transfer_phase(tmp_path: Path) -> None:
    config = _config(tmp_path, servers=False)
    transfer = FakeTransferExecutor(_all_ok)

    result = run_pipeline(
        config,
        backup=FakeBackupExecutor([_backup_result("erp_principal")]),
        compression=FakeCompressionExecutor(
            {"erp_principal": _compression_result("erp_principal")}
        ),
        transfer=transfer,
    )

    assert transfer.calls == []
    assert result.transfers == {}
    assert result.backup.success is True


def test_mixed_databases_isolate_transfer_failures(tmp_path: Path) -> None:
    config = _config(tmp_path)

    def outcomes(servers: list[ServerConfig], local_path: Path) -> list[TransferResult]:
        if local_path.name.startswith("uno"):
            return _all_fail(servers, local_path)
        return _all_ok(servers, local_path)

    transfer = FakeTransferExecutor(outcomes)

    result = run_pipeline(
        config,
        backup=FakeBackupExecutor([_backup_result("uno"), _backup_result("dos")]),
        compression=FakeCompressionExecutor(
            {
                "uno": _compression_result("uno"),
                "dos": _compression_result("dos"),
            }
        ),
        transfer=transfer,
    )

    uno, dos = result.backup.results
    assert uno.success is False
    assert uno.transfer_error_message is not None
    assert "Authentication failed" in (uno.transfer_error_message or "")
    assert uno.archive_path is not None
    assert dos.success is True
    assert dos.transfer_error_message is None
    assert result.backup.success is False
    assert set(result.transfers) == {"uno", "dos"}


# --- Notificación del pipeline (Item 043) ---


def _run_successful(config: Config, notifier: FakeNotifier) -> PipelineResult:
    """Corrida totalmente exitosa con el notifier indicado."""
    return run_pipeline(
        config,
        backup=FakeBackupExecutor([_backup_result("erp_principal")]),
        compression=FakeCompressionExecutor(
            {"erp_principal": _compression_result("erp_principal")}
        ),
        transfer=FakeTransferExecutor(_all_ok),
        notifier=notifier,
    )


class LoggingBackupExecutor(FakeBackupExecutor):
    """Respaldo doble que emite una línea de log durante la fase."""

    def run_batch_backup(self, databases: list[Any], work_dir: Path) -> BatchBackupResult:
        logging.getLogger("odin").info("marca-de-cola-123456")
        return super().run_batch_backup(databases, work_dir)


def test_success_sends_report_once_with_rendered_content(tmp_path: Path) -> None:
    config = _config(tmp_path)
    notifier = FakeNotifier()

    result = _run_successful(config, notifier)

    assert len(notifier.calls) == 1
    report = notifier.calls[0]
    assert report.subject.startswith("[ODIN] ÉXITO — respaldo de ")
    assert "erp_principal" in report.body
    assert "Servidores destino:" in report.body
    assert "sitio-alterno-1" in report.body
    assert "Totales:" in report.body
    assert result.notification is not None
    assert result.notification.success is True
    assert result.notification.recipient == "control@example.com"


def test_total_failure_still_sends_report(tmp_path: Path) -> None:
    config = _config(tmp_path)
    notifier = FakeNotifier()

    result = run_pipeline(
        config,
        backup=FakeBackupExecutor([_backup_result("erp_principal", success=False)]),
        compression=FakeCompressionExecutor({}),
        transfer=FakeTransferExecutor(_all_ok),
        notifier=notifier,
    )

    assert len(notifier.calls) == 1
    report = notifier.calls[0]
    assert report.subject.startswith("[ODIN] FALLO — respaldo de ")
    assert "database is in use" in report.body
    assert result.notification is not None
    assert result.notification.success is True


def test_batch_not_executed_still_sends_report(tmp_path: Path) -> None:
    config = _config(tmp_path)
    notifier = FakeNotifier()

    class ErrorBatchExecutor:
        def run_batch_backup(self, databases: list[Any], work_dir: Path) -> BatchBackupResult:
            return BatchBackupResult(
                results=[],
                success=False,
                total_duration_seconds=0.0,
                error_message="no se pudo preparar el directorio de trabajo",
            )

    result = run_pipeline(
        config,
        backup=ErrorBatchExecutor(),
        compression=FakeCompressionExecutor({}),
        transfer=FakeTransferExecutor(_all_ok),
        notifier=notifier,
    )

    assert len(notifier.calls) == 1
    report = notifier.calls[0]
    assert report.subject.startswith("[ODIN] FALLO — respaldo de ")
    assert "Respaldo no ejecutado: no se pudo preparar el directorio de trabajo" in report.body
    assert result.notification is not None


def test_empty_batch_still_sends_report(tmp_path: Path) -> None:
    config = _config(tmp_path)
    notifier = FakeNotifier()

    class EmptyBatchExecutor:
        def run_batch_backup(self, databases: list[Any], work_dir: Path) -> BatchBackupResult:
            return BatchBackupResult(results=[], success=False, total_duration_seconds=0.0)

    result = run_pipeline(
        config,
        backup=EmptyBatchExecutor(),
        compression=FakeCompressionExecutor({}),
        transfer=FakeTransferExecutor(_all_ok),
        notifier=notifier,
    )

    assert len(notifier.calls) == 1
    assert "No hay bases configuradas: nada que respaldar." in notifier.calls[0].body
    assert result.notification is not None


def test_notification_failure_is_returned_without_raising(tmp_path: Path) -> None:
    config = _config(tmp_path)
    failed = NotificationResult(
        success=False,
        recipient="control@example.com",
        error_message="SMTPConnectError: conexión rechazada",
    )
    notifier = FakeNotifier(result=failed)

    result = _run_successful(config, notifier)

    assert len(notifier.calls) == 1
    assert result.backup.success is True
    assert result.notification is failed


def test_notifier_exception_is_contained(tmp_path: Path) -> None:
    config = _config(tmp_path)
    notifier = FakeNotifier(exception=RuntimeError("boom"))

    result = _run_successful(config, notifier)

    assert len(notifier.calls) == 1
    assert result.backup.success is True
    assert result.notification is not None
    assert result.notification.success is False
    assert result.notification.recipient == "control@example.com"
    assert "fallo inesperado del notificador" in (result.notification.error_message or "")
    assert "RuntimeError: boom" in (result.notification.error_message or "")


def test_log_tail_lines_reach_the_report(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="odin")
    config = _config(tmp_path)
    notifier = FakeNotifier()

    run_pipeline(
        config,
        backup=LoggingBackupExecutor([_backup_result("erp_principal")]),
        compression=FakeCompressionExecutor(
            {"erp_principal": _compression_result("erp_principal")}
        ),
        transfer=FakeTransferExecutor(_all_ok),
        notifier=notifier,
    )

    report = notifier.calls[0]
    assert "Últimas líneas del log" in report.body
    assert "marca-de-cola-123456" in report.body


def test_log_tail_disabled_with_zero_lines(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="odin")
    config = _config(tmp_path, log_tail_lines=0)
    notifier = FakeNotifier()

    run_pipeline(
        config,
        backup=LoggingBackupExecutor([_backup_result("erp_principal")]),
        compression=FakeCompressionExecutor(
            {"erp_principal": _compression_result("erp_principal")}
        ),
        transfer=FakeTransferExecutor(_all_ok),
        notifier=notifier,
    )

    assert "marca-de-cola-123456" not in notifier.calls[0].body

"""Tests del pipeline de ``odin run`` (Item 035): respaldo → compresión → transferencia."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from odin.backup import BackupResult, BatchBackupResult
from odin.compress import BatchCompressionResult, CompressionResult
from odin.config import Config, ServerConfig, load_config
from odin.pipeline import PipelineResult, run_pipeline
from odin.transfer import BatchTransferResult, TransferResult

FIXTURES = Path(__file__).parent / "fixtures"

ARCHIVE_SUFFIX = ".fbk.7z"


def _config(tmp_path: Path, *, servers: bool = True) -> Config:
    """Config Linux válida con ``work_dir`` en ``tmp_path`` (servidores opcionales)."""
    data: dict[str, Any] = json.loads(
        (FIXTURES / "config_valid_linux.json").read_text(encoding="utf-8")
    )
    data["local"]["work_dir"] = str(tmp_path / "work")
    if not servers:
        data["servers"] = []
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

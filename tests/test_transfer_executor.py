from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar
from unittest.mock import MagicMock

import pytest

from odin.config import AuthMethod, HostKeyPolicy, ServerAuth, ServerConfig
from odin.transfer import (
    AuthenticationError,
    ConnectionError,
    TransferExecutor,
    TransferResult,
)


def make_server(name: str, host: str, **overrides: Any) -> ServerConfig:
    values: dict[str, Any] = {
        "name": name,
        "host": host,
        "port": 22,
        "username": "backup",
        "auth": ServerAuth(method=AuthMethod.PASSWORD, password="s3cret"),
        "remote_path": "/backups/odin",
    }
    values.update(overrides)
    return ServerConfig(**values)


class FakeSFTPTransfer:
    """Doble de ``SFTPTransfer`` que registra kwargs, uploads y cierres."""

    instances: ClassVar[list[FakeSFTPTransfer]] = []
    fail_connect: ClassVar[dict[str, Exception]] = {}
    fail_upload: ClassVar[dict[str, Exception]] = {}

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.hostname: str = kwargs["hostname"]
        self.uploaded: list[tuple[Path, str]] = []
        self.closed = False
        FakeSFTPTransfer.instances.append(self)

    def connect(self) -> None:
        error = self.fail_connect.get(self.hostname)
        if error is not None:
            raise error

    def upload(self, local_path: Path, remote_path: str) -> None:
        error = self.fail_upload.get(self.hostname)
        if error is not None:
            raise error
        self.uploaded.append((local_path, remote_path))

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_transfer(monkeypatch: pytest.MonkeyPatch) -> type[FakeSFTPTransfer]:
    FakeSFTPTransfer.instances = []
    FakeSFTPTransfer.fail_connect = {}
    FakeSFTPTransfer.fail_upload = {}
    monkeypatch.setattr("odin.transfer.SFTPTransfer", FakeSFTPTransfer)
    return FakeSFTPTransfer


@pytest.fixture
def artifact(tmp_path: Path) -> Path:
    path = tmp_path / "clientes_20260914.fbk.7z"
    path.write_bytes(b"x" * 128)
    return path


def test_transfer_result_dataclass_fields() -> None:
    success = TransferResult(success=True, server_name="uno", local_path=Path("/tmp/a.7z"))

    assert success.success is True
    assert success.server_name == "uno"
    assert success.local_path == Path("/tmp/a.7z")
    assert success.remote_path is None
    assert success.transferred_bytes is None
    assert success.duration_seconds == 0.0
    assert success.error_message is None

    failure = TransferResult(
        success=False,
        server_name="dos",
        local_path=Path("/tmp/a.7z"),
        remote_path="/backups/odin/a.7z",
        duration_seconds=1.5,
        error_message="timeout",
    )

    assert failure.success is False
    assert failure.error_message == "timeout"
    assert failure.transferred_bytes is None


def test_batch_isolates_failing_server_and_continues(
    fake_transfer: type[FakeSFTPTransfer], artifact: Path
) -> None:
    servers = [
        make_server("uno", "uno.example"),
        make_server("dos", "dos.example"),
        make_server("tres", "tres.example"),
    ]
    fake_transfer.fail_upload["dos.example"] = ConnectionError(
        "upload failed after max retries on dos.example: timeout"
    )

    results = TransferExecutor().run_batch_transfer(servers, artifact)

    assert [result.success for result in results] == [True, False, True]
    assert [result.server_name for result in results] == ["uno", "dos", "tres"]
    assert [instance.hostname for instance in fake_transfer.instances] == [
        "uno.example",
        "dos.example",
        "tres.example",
    ]

    failed = results[1]
    assert failed.error_message is not None
    assert "failed after max retries" in failed.error_message
    assert failed.transferred_bytes is None

    assert results[0].transferred_bytes == 128
    assert results[0].remote_path == "/backups/odin/clientes_20260914.fbk.7z"
    assert results[0].error_message is None
    assert results[2].transferred_bytes == 128
    assert results[2].error_message is None
    assert all(result.duration_seconds >= 0 for result in results)

    uploaded = [instance.uploaded for instance in fake_transfer.instances]
    assert uploaded[0] == [(artifact, "/backups/odin/clientes_20260914.fbk.7z")]
    assert uploaded[1] == []
    assert uploaded[2] == [(artifact, "/backups/odin/clientes_20260914.fbk.7z")]


def test_authentication_failure_does_not_stop_batch(
    fake_transfer: type[FakeSFTPTransfer], artifact: Path
) -> None:
    servers = [
        make_server("uno", "uno.example"),
        make_server("dos", "dos.example"),
        make_server("tres", "tres.example"),
    ]
    fake_transfer.fail_connect["dos.example"] = AuthenticationError("Authentication failed")

    results = TransferExecutor().run_batch_transfer(servers, artifact)

    assert [result.success for result in results] == [True, False, True]
    assert results[1].error_message == "Authentication failed"


def test_transfer_parameters_are_forwarded_per_server(
    fake_transfer: type[FakeSFTPTransfer], artifact: Path
) -> None:
    uno = make_server(
        "uno",
        "uno.example",
        port=2222,
        sftp_retries=5,
        sftp_connect_timeout_sec=11,
        sftp_operation_timeout_sec=22,
        sftp_retry_backoff_base=0.5,
        sftp_retry_max_delay_sec=9.0,
    )
    dos = make_server(
        "dos",
        "dos.example",
        host_key_policy=HostKeyPolicy.ACCEPT_NEW,
        auth=ServerAuth(
            method=AuthMethod.KEY,
            private_key="/keys/id_rsa",
            passphrase="frase secreta",
        ),
    )

    TransferExecutor().run_batch_transfer([uno, dos], artifact)

    primero, segundo = fake_transfer.instances
    assert primero.kwargs == {
        "hostname": "uno.example",
        "port": 2222,
        "username": "backup",
        "password": "s3cret",
        "key_path": None,
        "passphrase": None,
        "sftp_retries": 5,
        "sftp_connect_timeout_sec": 11,
        "sftp_operation_timeout_sec": 22,
        "sftp_retry_backoff_base": 0.5,
        "sftp_retry_max_delay_sec": 9.0,
        "host_keys_policy": "strict",
    }
    assert segundo.kwargs["host_keys_policy"] == "accept-new"
    assert segundo.kwargs["key_path"] == "/keys/id_rsa"
    assert segundo.kwargs["passphrase"] == "frase secreta"
    assert segundo.kwargs["password"] is None


def test_close_called_for_every_server_even_on_failure(
    fake_transfer: type[FakeSFTPTransfer], artifact: Path
) -> None:
    servers = [make_server("uno", "uno.example"), make_server("dos", "dos.example")]
    fake_transfer.fail_upload["dos.example"] = ConnectionError("boom")

    TransferExecutor().run_batch_transfer(servers, artifact)

    assert len(fake_transfer.instances) == 2
    assert all(instance.closed for instance in fake_transfer.instances)


def test_missing_local_file_reports_failure_without_connecting(
    fake_transfer: type[FakeSFTPTransfer], artifact: Path
) -> None:
    servers = [make_server("uno", "uno.example"), make_server("dos", "dos.example")]

    results = TransferExecutor().run_batch_transfer(servers, artifact.parent / "no-existe.7z")

    assert [result.success for result in results] == [False, False]
    assert fake_transfer.instances == []
    assert results[0].error_message is not None
    assert "no se pudo leer el archivo local" in results[0].error_message


def test_empty_server_list_returns_empty_result(
    fake_transfer: type[FakeSFTPTransfer], artifact: Path
) -> None:
    assert TransferExecutor().run_batch_transfer([], artifact) == []


def test_retries_exhausted_before_continuing_with_next_server(
    monkeypatch: pytest.MonkeyPatch, artifact: Path
) -> None:
    attempts: dict[str, int] = {"malo.example": 0, "bueno.example": 0}

    class FakeSSHClient:
        def set_missing_host_key_policy(self, policy: Any) -> None: ...

        def load_system_host_keys(self) -> None: ...

        def connect(self, **kwargs: Any) -> None:
            hostname = kwargs["hostname"]
            attempts[hostname] += 1
            if hostname == "malo.example":
                raise OSError("Connection refused")

        def open_sftp(self) -> MagicMock:
            sftp = MagicMock()
            remote_stat = MagicMock()
            remote_stat.st_size = artifact.stat().st_size
            sftp.stat.return_value = remote_stat
            return sftp

        def close(self) -> None: ...

    monkeypatch.setattr("odin.transfer.paramiko.SSHClient", FakeSSHClient)

    malo = make_server(
        "malo",
        "malo.example",
        sftp_retries=2,
        sftp_retry_backoff_base=0.001,
        sftp_retry_max_delay_sec=0.001,
    )
    bueno = make_server("bueno", "bueno.example")

    results = TransferExecutor().run_batch_transfer([malo, bueno], artifact)

    assert attempts["malo.example"] == 2
    assert attempts["bueno.example"] == 1
    assert [result.success for result in results] == [False, True]
    assert results[0].error_message is not None
    assert "failed after max retries" in results[0].error_message
    assert results[1].transferred_bytes == artifact.stat().st_size

"""Tests unitarios de upload con reintentos, verificación de tamaño y auth por clave (Item 037).

Complementan ``tests/test_transfer.py`` (conexión y políticas de host keys) y
``tests/test_transfer/test_retry_logic.py`` (backoff genérico). Acá se cubren
los huecos de la capa de upload: reintentos de ``put`` ante errores de red,
agotamiento de reintentos, verificación de tamaño fallida como test propio,
carga de clave privada y rechazo de claves PPK, y cierre idempotente.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from odin.transfer import AuthenticationError, SFTPTransfer, TransferError

LOCAL_SIZE = 100


@pytest.fixture
def connected(monkeypatch: pytest.MonkeyPatch) -> SFTPTransfer:
    """``SFTPTransfer`` conectado contra dobles de paramiko (upload listo)."""
    transfer = SFTPTransfer(
        hostname="example.com",
        username="odin",
        password="no-se-usa",
        sftp_retries=3,
        sftp_retry_backoff_base=0.001,
        sftp_retry_max_delay_sec=0.001,
    )
    mock_client = MagicMock()
    mock_sftp = MagicMock()
    mock_client.open_sftp.return_value = mock_sftp
    monkeypatch.setattr("odin.transfer.paramiko.SSHClient", lambda: mock_client)
    transfer.connect()
    return transfer


@pytest.fixture
def local_file(tmp_path: Path) -> Path:
    path = tmp_path / "artifact.fbk.7z"
    path.write_bytes(b"a" * LOCAL_SIZE)
    return path


def _remote_stat(size: int) -> MagicMock:
    stat = MagicMock()
    stat.st_size = size
    return stat


def test_upload_retries_transient_network_error_then_succeeds(
    connected: SFTPTransfer, local_file: Path
) -> None:
    sftp = connected._sftp
    assert sftp is not None
    sftp.put.side_effect = [OSError("Connection reset"), OSError("Connection reset"), None]
    sftp.stat.return_value = _remote_stat(LOCAL_SIZE)

    with patch("odin.transfer.logger"):
        connected.upload(local_file, "/backups/artifact.fbk.7z")

    assert sftp.put.call_count == 3
    sftp.stat.assert_any_call("/backups/artifact.fbk.7z")


def test_upload_exhausts_retries_and_raises_transfer_error(
    connected: SFTPTransfer, local_file: Path
) -> None:
    sftp = connected._sftp
    assert sftp is not None
    sftp.put.side_effect = OSError("Connection refused")

    with patch("odin.transfer.logger"), pytest.raises(
        TransferError, match="failed after max retries"
    ):
        connected.upload(local_file, "/backups/artifact.fbk.7z")

    assert sftp.put.call_count == 3
    sftp.stat.assert_called_once_with("/backups")


def test_upload_integrity_failure_on_size_mismatch(
    connected: SFTPTransfer, local_file: Path
) -> None:
    sftp = connected._sftp
    assert sftp is not None
    sftp.stat.return_value = _remote_stat(LOCAL_SIZE - 1)

    with patch("odin.transfer.logger"), pytest.raises(TransferError) as excinfo:
        connected.upload(local_file, "/backups/artifact.fbk.7z")

    assert "Integrity check failed" in str(excinfo.value)
    assert "Local size 100 != Remote size 99" in str(excinfo.value)


def test_upload_verification_stat_error_reported(
    connected: SFTPTransfer, local_file: Path
) -> None:
    sftp = connected._sftp
    assert sftp is not None
    sftp.stat.side_effect = OSError("stat failed")

    with patch("odin.transfer.logger"), pytest.raises(
        TransferError, match="Integrity verification failed"
    ):
        connected.upload(local_file, "/backups/artifact.fbk.7z")


def test_connect_with_private_key_loads_rsa_key_with_passphrase(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    key_file = tmp_path / "id_rsa"
    key_file.write_text("-----BEGIN RSA PRIVATE KEY-----fake-----END RSA PRIVATE KEY-----\n")

    fake_key = MagicMock()
    monkeypatch.setattr(
        "odin.transfer.paramiko.RSAKey.from_private_key_file",
        lambda path, password=None: fake_key,
    )
    mock_client = MagicMock()
    mock_client.open_sftp.return_value = MagicMock()
    monkeypatch.setattr("odin.transfer.paramiko.SSHClient", lambda: mock_client)

    transfer = SFTPTransfer(
        hostname="example.com",
        username="odin",
        key_path=str(key_file),
        passphrase="frase-clave",
    )
    transfer.connect()

    kwargs = mock_client.connect.call_args.kwargs
    assert kwargs["pkey"] is fake_key
    assert kwargs.get("password") is None


def test_ppk_key_is_rejected_with_clear_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    key_file = tmp_path / "id_rsa.ppk"
    key_file.write_text("PuTTY-User-Key-File-2")
    mock_client = MagicMock()
    monkeypatch.setattr("odin.transfer.paramiko.SSHClient", lambda: mock_client)

    transfer = SFTPTransfer(hostname="example.com", key_path=str(key_file))
    with pytest.raises(AuthenticationError, match="PPK not supported"):
        transfer.connect()
    mock_client.connect.assert_not_called()


def test_close_without_connect_is_idempotent() -> None:
    transfer = SFTPTransfer(hostname="example.com")
    transfer.close()
    transfer.close()

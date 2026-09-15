"""Tests de integración SFTP contra un sshd ephemeral in-process (Item 037).

El servidor es real (handshake SSH + protocolo SFTP vía ``paramiko.Transport``
en modo servidor sobre loopback) pero no depende de binarios externos ni de
contenedores: host key generada en memoria, autenticación por contraseña fija
y un ``SFTPServerInterface`` respaldado por un directorio temporal. El helper
se extrajo a ``tests/sshd_ephemeral.py`` en el Item 072 para reutilizarlo sin
duplicar código. Está marcado ``integration`` por semántica (flujo real de
red en proceso) y corre en la suite completa porque no requiere servicios
externos.
"""

from __future__ import annotations

from pathlib import Path

import paramiko
import pytest

from odin.config import AuthMethod, HostKeyPolicy, ServerAuth, ServerConfig
from odin.transfer import TransferExecutor
from tests.sshd_ephemeral import EphemeralSshd


def _server_config(port: int, password: str) -> ServerConfig:
    return ServerConfig(
        name="sshd-local",
        host="127.0.0.1",
        port=port,
        username="odin",
        auth=ServerAuth(method=AuthMethod.PASSWORD, password=password),
        remote_path="/backups/odin",
        host_key_policy=HostKeyPolicy.ACCEPT_NEW,
        sftp_retries=2,
        sftp_connect_timeout_sec=15,
        sftp_retry_backoff_base=0.001,
        sftp_retry_max_delay_sec=0.001,
    )


@pytest.mark.integration
def test_transfer_upload_and_verify_against_ephemeral_sshd(tmp_path: Path) -> None:
    remote_root = tmp_path / "remote_root"
    remote_root.mkdir()
    server = EphemeralSshd(password="int-secreto", root=remote_root)
    try:
        artifact = tmp_path / "clientes.fbk.7z"
        artifact.write_bytes(b"x" * 4096)

        results = TransferExecutor().run_batch_transfer(
            [_server_config(server.port, "int-secreto")], artifact
        )

        assert len(results) == 1
        assert results[0].success is True
        assert results[0].transferred_bytes == 4096
        assert results[0].remote_path == "/backups/odin/clientes.fbk.7z"
        uploaded = remote_root / "backups" / "odin" / "clientes.fbk.7z"
        assert uploaded.read_bytes() == b"x" * 4096
        assert server.errors == []
    finally:
        server.close()


@pytest.mark.integration
def test_transfer_with_private_key_authentication(tmp_path: Path) -> None:
    remote_root = tmp_path / "remote_root"
    remote_root.mkdir()
    client_key = paramiko.RSAKey.generate(1024)
    key_file = tmp_path / "id_rsa"
    client_key.write_private_key_file(str(key_file))
    server = EphemeralSshd(public_key=client_key, root=remote_root)
    try:
        artifact = tmp_path / "clientes.fbk.7z"
        artifact.write_bytes(b"y" * 2048)

        target = ServerConfig(
            name="sshd-key",
            host="127.0.0.1",
            port=server.port,
            username="odin",
            auth=ServerAuth(method=AuthMethod.KEY, private_key=str(key_file)),
            remote_path="/backups/odin",
            host_key_policy=HostKeyPolicy.ACCEPT_NEW,
            sftp_retries=2,
            sftp_connect_timeout_sec=15,
            sftp_retry_backoff_base=0.001,
            sftp_retry_max_delay_sec=0.001,
        )

        results = TransferExecutor().run_batch_transfer([target], artifact)

        assert results[0].success is True
        assert results[0].transferred_bytes == 2048
        uploaded = remote_root / "backups" / "odin" / "clientes.fbk.7z"
        assert uploaded.read_bytes() == b"y" * 2048
        assert server.errors == []
    finally:
        server.close()


@pytest.mark.integration
def test_wrong_password_reports_authentication_failure(tmp_path: Path) -> None:
    remote_root = tmp_path / "remote_root"
    remote_root.mkdir()
    server = EphemeralSshd(password="int-secreto", root=remote_root)
    try:
        artifact = tmp_path / "clientes.fbk.7z"
        artifact.write_bytes(b"x" * 256)

        results = TransferExecutor().run_batch_transfer(
            [_server_config(server.port, "contraseña-errónea")], artifact
        )

        assert len(results) == 1
        assert results[0].success is False
        assert results[0].transferred_bytes is None
        assert "Authentication" in (results[0].error_message or "")
        assert not (remote_root / "backups").exists()
        assert server.errors == []
    finally:
        server.close()

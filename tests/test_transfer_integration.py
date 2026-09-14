"""Tests de integración SFTP contra un sshd ephemeral in-process (Item 037).

El servidor es real (handshake SSH + protocolo SFTP vía ``paramiko.Transport``
en modo servidor sobre loopback) pero no depende de binarios externos ni de
contenedores: host key generada en memoria, autenticación por contraseña fija
y un ``SFTPServerInterface`` respaldado por un directorio temporal. Está
marcado ``integration`` por semántica (flujo real de red en proceso) y corre
en la suite completa porque no requiere servicios externos.
"""

from __future__ import annotations

import os
import socket
import threading
import time
from pathlib import Path

import paramiko
import pytest
from paramiko import SFTPAttributes, SFTPServerInterface

from odin.config import AuthMethod, HostKeyPolicy, ServerAuth, ServerConfig
from odin.transfer import TransferExecutor


class _PasswordServer(paramiko.ServerInterface):
    """Acepta solo una contraseña fija (ejercita el camino de auth real)."""

    def __init__(self, password: str) -> None:
        super().__init__()
        self._password = password

    def check_auth_password(self, username: str, password: str) -> int:
        if password == self._password:
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def check_channel_request(self, kind: str, chanid: int) -> int:
        if kind == "session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED


class _KeyServer(paramiko.ServerInterface):
    """Acepta una clave pública RSA fija (ejercita el camino de auth por clave)."""

    def __init__(self, public_key: paramiko.RSAKey) -> None:
        super().__init__()
        self._public_key = public_key

    def check_auth_publickey(self, username: str, key: paramiko.RSAKey) -> int:
        if key.get_fingerprint() == self._public_key.get_fingerprint():
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def check_channel_request(self, kind: str, chanid: int) -> int:
        if kind == "session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED


class _FileHandle(paramiko.SFTPHandle):
    """Handle de escritura respaldado por un archivo local abierto."""

    def __init__(self, file: object, flags: int) -> None:
        super().__init__(flags)
        self.writefile = file


class _FileSFTPServer(SFTPServerInterface):
    """SFTPServerInterface sobre un directorio real con lo que ODIN usa.

    Implementa ``stat``, ``mkdir`` y ``open`` (solo escritura); la escritura
    la hace el ``SFTPHandle`` por defecto sobre ``writefile`` y el cierre lo
    hace su ``close``. El resto de operaciones no se ejercitan en la
    transferencia de ODIN.
    """

    def __init__(self, server: object, root: Path) -> None:
        super().__init__(server)
        self._root = root

    def _real(self, path: str) -> Path:
        return self._root / path.lstrip("/")

    def stat(self, path: str) -> SFTPAttributes:
        try:
            return SFTPAttributes.from_stat(os.stat(self._real(path)))
        except OSError as exc:
            raise OSError(paramiko.sftp.SFTP_NO_SUCH_FILE, str(exc)) from exc

    def mkdir(self, path: str, attr: SFTPAttributes) -> int:
        os.makedirs(self._real(path), exist_ok=True)
        return paramiko.sftp.SFTP_OK

    def open(self, path: str, flags: int, attr: SFTPAttributes) -> _FileHandle:
        real = self._real(path)
        real.parent.mkdir(parents=True, exist_ok=True)
        mode = "wb" if flags & os.O_TRUNC else "r+b"
        return _FileHandle(open(real, mode), flags)


class _EphemeralSshd:
    """sshd ephemeral en un hilo: puerto aleatorio, clave generada en memoria."""

    def __init__(
        self,
        *,
        password: str | None = None,
        public_key: paramiko.RSAKey | None = None,
        root: Path,
    ) -> None:
        self.errors: list[BaseException] = []
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(1)
        self.port: int = self._sock.getsockname()[1]
        self._host_key = paramiko.RSAKey.generate(1024)
        self._server: paramiko.ServerInterface
        if password is not None:
            self._server = _PasswordServer(password)
        elif public_key is not None:
            self._server = _KeyServer(public_key)
        else:
            raise ValueError("se requiere password o public_key")
        self._root = root
        self._transport: paramiko.Transport | None = None
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        try:
            client, _ = self._sock.accept()
            self._transport = paramiko.Transport(client)
            self._transport.add_server_key(self._host_key)
            self._transport.set_subsystem_handler(
                "sftp", paramiko.SFTPServer, _FileSFTPServer, self._root
            )
            self._transport.start_server(server=self._server)
            channel = self._transport.accept(timeout=20)
            if channel is None:
                return
            while self._transport.is_active():
                time.sleep(0.05)
        except BaseException as exc:
            self.errors.append(exc)

    def close(self) -> None:
        if self._transport is not None:
            self._transport.close()
        self._sock.close()
        self._thread.join(timeout=5)


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
    server = _EphemeralSshd(password="int-secreto", root=remote_root)
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
    server = _EphemeralSshd(public_key=client_key, root=remote_root)
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
    server = _EphemeralSshd(password="int-secreto", root=remote_root)
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

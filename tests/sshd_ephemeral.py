"""sshd ephemeral in-process reutilizable por los tests de integración.

Servidor SSH real sobre loopback (handshake + subsistema SFTP vía
``paramiko.Transport`` en modo servidor) con host key generada en memoria, sin
binarios externos ni contenedores: el patrón que introdujo el Item 037 y que
reutilizan los tests de transferencia y la capa de instalación limpia del
Item 072.

El bind por defecto es ``127.0.0.1``; los escenarios que corren un contenedor
externo pueden pedir ``0.0.0.0`` para que el contenedor alcance el servidor
(las credenciales son siempre de prueba).
"""

from __future__ import annotations

import os
import socket
import threading
import time
from pathlib import Path

import paramiko
from paramiko import SFTPAttributes, SFTPServerInterface


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


class EphemeralSshd:
    """sshd ephemeral en un hilo: puerto aleatorio, clave generada en memoria."""

    def __init__(
        self,
        *,
        password: str | None = None,
        public_key: paramiko.RSAKey | None = None,
        root: Path,
        host: str = "127.0.0.1",
    ) -> None:
        self.errors: list[BaseException] = []
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind((host, 0))
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

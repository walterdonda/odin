"""Transferencia SFTP de los artefactos de respaldo (Etapa 4).

``SFTPTransfer`` encapsula una conexión paramiko: autenticación por contraseña
o clave privada, política de host keys por servidor, creación recursiva de
directorios remotos, upload con verificación de tamaño y reintentos con
backoff exponencial. ``TransferExecutor`` recorre la lista de servidores
destino aislando los fallos: cada destino se reporta con su propio
``TransferResult`` y un fallo (tras agotar los reintentos) no interrumpe al
resto.
"""

from __future__ import annotations

import posixpath
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

import paramiko

from odin.config import ServerConfig
from odin.log import logger
from odin.paths import resolve_path

_T = TypeVar("_T")


class TransferError(Exception):
    """Base error for transfer operations."""


class AuthenticationError(TransferError):
    """Error during authentication."""


class ConnectionError(TransferError):
    """Error during connection."""


@dataclass(frozen=True, slots=True)
class TransferResult:
    """Resultado de transferir un archivo a un servidor (éxito o fallo).

    ``transferred_bytes`` es el tamaño local verificado contra el ``stat``
    remoto y queda en ``None`` cuando la transferencia falla.
    """

    success: bool
    server_name: str
    local_path: Path
    remote_path: str | None = None
    transferred_bytes: int | None = None
    duration_seconds: float = 0.0
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class BatchTransferResult:
    """Resultado agregado de transferir un artefacto a un lote de servidores.

    ``success`` es ``True`` solo si todos los destinos culminaron bien (vacuo
    para un lote vacío, que el pipeline no produce porque sin servidores no
    se transfiere). ``total_duration_seconds`` suma las duraciones
    individuales: las transferencias son secuenciales, así que la suma
    aproxima el tiempo de pared del lote sin medirlo aparte.
    """

    results: Sequence[TransferResult]
    success: bool
    total_duration_seconds: float


def aggregate_transfer_results(results: Sequence[TransferResult]) -> BatchTransferResult:
    """Agrega resultados individuales de transferencia en un ``BatchTransferResult``."""
    return BatchTransferResult(
        results=tuple(results),
        success=all(result.success for result in results),
        total_duration_seconds=sum(result.duration_seconds for result in results),
    )


class SFTPTransfer:
    """Conexión SFTP a un servidor con reintentos y backoff configurables."""

    def __init__(
        self,
        hostname: str,
        port: int = 22,
        username: str | None = None,
        password: str | None = None,
        key_path: str | Path | None = None,
        passphrase: str | None = None,
        sftp_retries: int = 3,
        sftp_connect_timeout_sec: int = 30,
        sftp_operation_timeout_sec: int = 60,
        sftp_retry_backoff_base: float = 2.0,
        sftp_retry_max_delay_sec: float = 30.0,
        host_keys_policy: str = "strict",
    ) -> None:
        self.hostname = hostname
        self.port = port
        self.username = username
        self.password = password
        self.key_path: Path | None = None if key_path is None else resolve_path(str(key_path))
        self.passphrase = passphrase
        self.host_keys_policy = host_keys_policy
        self.sftp_retries = sftp_retries
        self.sftp_connect_timeout_sec = sftp_connect_timeout_sec
        self.sftp_operation_timeout_sec = sftp_operation_timeout_sec
        self.sftp_retry_backoff_base = sftp_retry_backoff_base
        self.sftp_retry_max_delay_sec = sftp_retry_max_delay_sec
        self._client: paramiko.SSHClient | None = None
        self._sftp: paramiko.SFTPClient | None = None

    def _execute_with_retry(self, operation: Callable[[], _T], name: str) -> _T:
        """Ejecuta ``operation`` con reintentos y backoff exponencial.

        Los errores de autenticación no se reintentan (fallan de inmediato);
        los errores de red/SSH agotan ``sftp_retries`` intentos totales y
        terminan en un ``ConnectionError`` con el último error recibido.
        """
        if self.sftp_retries < 1:
            raise ConnectionError(
                f"sftp_retries debe ser al menos 1 para ejecutar {name} en {self.hostname}"
            )
        last_exception: Exception | None = None
        for attempt in range(self.sftp_retries):
            try:
                return operation()
            except (ConnectionError, paramiko.SSHException, EOFError, OSError) as exc:
                if (
                    isinstance(exc, paramiko.AuthenticationException)
                    or "authentication" in str(exc).lower()
                ):
                    raise
                last_exception = exc
                if attempt == self.sftp_retries - 1:
                    break
                wait_time = min(
                    self.sftp_retry_backoff_base * (2**attempt),
                    self.sftp_retry_max_delay_sec,
                )
                logger.warning(
                    "Error en %s para %s (intento %d/%d): %s. Reintentando en %.1f s...",
                    name,
                    self.hostname,
                    attempt + 1,
                    self.sftp_retries,
                    exc,
                    wait_time,
                )
                time.sleep(wait_time)

        detail = str(last_exception) if last_exception is not None else "error desconocido"
        logger.error("Falló %s tras %d intentos en %s", name, self.sftp_retries, self.hostname)
        raise ConnectionError(
            f"{name} failed after max retries on {self.hostname}: {detail}"
        ) from last_exception

    def _set_policy(self, client: paramiko.SSHClient) -> None:
        """Aplica la política de host keys configurada al cliente SSH."""
        if self.host_keys_policy == "strict":
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
        elif self.host_keys_policy == "accept-new":
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        elif self.host_keys_policy == "insecure":
            client.set_missing_host_key_policy(paramiko.WarningPolicy())
        elif self.host_keys_policy == "known_hosts":
            client.load_system_host_keys()
        else:
            client.set_missing_host_key_policy(paramiko.RejectPolicy())

    def connect(self) -> None:
        """Conecta al servidor y abre el canal SFTP (con reintentos)."""

        def _connect_logic() -> paramiko.SSHClient:
            client = paramiko.SSHClient()
            self._set_policy(client)
            client.load_system_host_keys()

            connect_kwargs: dict[str, Any] = {
                "hostname": self.hostname,
                "port": self.port,
                "username": self.username,
                "timeout": self.sftp_connect_timeout_sec,
            }

            if self.password:
                connect_kwargs["password"] = self.password

            if self.key_path is not None:
                if self.key_path.suffix == ".ppk":
                    raise AuthenticationError(
                        "PPK not supported directly, use OpenSSH format."
                    )
                connect_kwargs["pkey"] = paramiko.RSAKey.from_private_key_file(
                    str(self.key_path), password=self.passphrase
                )

            client.connect(**connect_kwargs)
            self._sftp = client.open_sftp()
            logger.info("Successfully connected to %s", self.hostname)
            return client

        try:
            self._client = self._execute_with_retry(_connect_logic, "connect")
        except (paramiko.AuthenticationException, AuthenticationError) as exc:
            logger.error("Authentication failed for %s", self.hostname)
            raise AuthenticationError(f"Authentication failed: {exc}") from exc
        except (paramiko.SSHException, ConnectionError):
            raise
        except Exception as exc:
            logger.error("Failed to connect to %s", self.hostname)
            raise ConnectionError(f"Connection error: {exc}") from exc

    def upload(self, local_path: Path, remote_path: str) -> None:
        """Sube ``local_path`` a ``remote_path`` y verifica el tamaño remoto."""
        sftp = self._sftp
        if sftp is None:
            raise ConnectionError("Not connected to SFTP server.")

        try:
            remote_dir = posixpath.dirname(remote_path)
            if remote_dir:
                self._ensure_remote_dir_exists(remote_dir)

            logger.info("Uploading %s to %s on %s", local_path, remote_path, self.hostname)
            local_size = local_path.stat().st_size
            self._execute_with_retry(lambda: sftp.put(str(local_path), remote_path), "upload")
            self._verify_transfer_integrity(remote_path, local_size)
            logger.info("Upload successful: %s", remote_path)
        except Exception as exc:
            logger.error("Upload failed for %s", remote_path)
            raise TransferError(f"Upload failed: {exc}") from exc

    def _ensure_remote_dir_exists(self, remote_path: str) -> None:
        """Crea recursivamente en el servidor los directorios que falten."""
        sftp = self._sftp
        if sftp is None:
            raise ConnectionError("Not connected to SFTP server.")
        current_path = ""
        for part in remote_path.split("/"):
            if not part:
                continue
            current_path += f"/{part}"
            try:
                sftp.stat(current_path)
            except OSError:
                logger.info("Creating remote directory: %s", current_path)
                sftp.mkdir(current_path)

    def _verify_transfer_integrity(self, remote_path: str, local_size: int) -> None:
        """Verifica que el tamaño remoto coincida con el tamaño local."""
        sftp = self._sftp
        if sftp is None:
            raise ConnectionError("Not connected to SFTP server.")
        try:
            remote_stat = sftp.stat(remote_path)
            if remote_stat.st_size != local_size:
                raise TransferError(
                    f"Integrity check failed for {remote_path}: "
                    f"Local size {local_size} != Remote size {remote_stat.st_size}"
                )
            logger.info("Integrity check passed for %s", remote_path)
        except Exception as exc:
            raise TransferError(f"Integrity verification failed: {exc}") from exc

    def close(self) -> None:
        """Cierra los canales SFTP/SSH abiertos (tolerante a fallos previos)."""
        if self._sftp is not None:
            self._sftp.close()
        if self._client is not None:
            self._client.close()
        logger.info("Connection to %s closed.", self.hostname)


class TransferExecutor:
    """Transfiere un artefacto a todos los servidores destino, aislando fallos.

    Recorre la lista completa de ``ServerConfig``: cada servidor se conecta con
    sus propios reintentos, timeouts y política de host keys (integrados en
    ``SFTPTransfer``); un fallo tras agotar los reintentos se registra en su
    ``TransferResult`` y no interrumpe los destinos siguientes.
    """

    def run_batch_transfer(
        self,
        servers: Sequence[ServerConfig],
        local_path: str | Path,
    ) -> list[TransferResult]:
        """Transfiere ``local_path`` a cada servidor y devuelve un resultado por destino."""
        local = Path(local_path)
        start_time = time.perf_counter()
        results = [self._transfer_one(server, local) for server in servers]
        succeeded = sum(result.success for result in results)
        logger.info(
            "Lote de transferencia finalizado: %d/%d exitosos en %.1f s",
            succeeded,
            len(results),
            time.perf_counter() - start_time,
        )
        return results

    def _transfer_one(self, server: ServerConfig, local_path: Path) -> TransferResult:
        """Transfiere el archivo a un servidor y encapsula cualquier error."""
        start_time = time.perf_counter()
        remote_path = posixpath.join(server.remote_path, local_path.name)
        try:
            local_size = local_path.stat().st_size
        except OSError as exc:
            logger.error("No se pudo leer el archivo local %s: %s", local_path, exc)
            return TransferResult(
                success=False,
                server_name=server.name,
                local_path=local_path,
                remote_path=remote_path,
                duration_seconds=time.perf_counter() - start_time,
                error_message=f"no se pudo leer el archivo local {local_path}: {exc}",
            )

        logger.info(
            "Transfiriendo %s a '%s' (%s:%d)",
            local_path.name,
            server.name,
            server.host,
            server.port,
        )
        transfer: SFTPTransfer | None = None
        try:
            transfer = self._build_transfer(server)
            transfer.connect()
            transfer.upload(local_path, remote_path)
        except Exception as exc:
            duration = time.perf_counter() - start_time
            logger.error("Transferencia a '%s' falló tras %.1f s: %s", server.name, duration, exc)
            return TransferResult(
                success=False,
                server_name=server.name,
                local_path=local_path,
                remote_path=remote_path,
                duration_seconds=duration,
                error_message=str(exc),
            )
        finally:
            if transfer is not None:
                try:
                    transfer.close()
                except Exception as exc:
                    logger.warning(
                        "No se pudo cerrar la conexión con '%s': %s", server.name, exc
                    )

        duration = time.perf_counter() - start_time
        logger.info(
            "Transferencia exitosa a '%s': %s (%d bytes, %.1f s)",
            server.name,
            remote_path,
            local_size,
            duration,
        )
        return TransferResult(
            success=True,
            server_name=server.name,
            local_path=local_path,
            remote_path=remote_path,
            transferred_bytes=local_size,
            duration_seconds=duration,
        )

    def _build_transfer(self, server: ServerConfig) -> SFTPTransfer:
        """Construye el ``SFTPTransfer`` con los parámetros del servidor."""
        auth = server.auth
        return SFTPTransfer(
            hostname=server.host,
            port=server.port,
            username=server.username,
            password=auth.password,
            key_path=auth.private_key,
            passphrase=auth.passphrase,
            sftp_retries=server.sftp_retries,
            sftp_connect_timeout_sec=server.sftp_connect_timeout_sec,
            sftp_operation_timeout_sec=server.sftp_operation_timeout_sec,
            sftp_retry_backoff_base=server.sftp_retry_backoff_base,
            sftp_retry_max_delay_sec=server.sftp_retry_max_delay_sec,
            host_keys_policy=server.host_key_policy.value,
        )

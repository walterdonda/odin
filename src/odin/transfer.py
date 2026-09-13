import paramiko
import time
import socket
from pathlib import Path
from typing import Optional, Any

from odin.paths import resolve_path
from odin.log import logger

class TransferError(Exception):
    """Base error for transfer operations."""
    pass

class AuthenticationError(TransferError):
    """Error during authentication."""
    pass

class ConnectionError(TransferError):
    """Error during connection."""
    pass

class SFTPTransfer:
    def __init__(
        self,
        hostname: str,
        port: int = 22,
        username: Optional[str] = None,
        password: Optional[str] = None,
        key_path: Optional[str] = None,
        passphrase: Optional[str] = None,
        sftp_retries: int = 3,
        sftp_connect_timeout_sec: int = 30,
        sftp_operation_timeout_sec: int = 60,
        sftp_retry_backoff_base: float = 2.0,
        sftp_retry_max_delay_sec: float = 30.0,
        host_keys_policy: str = "strict"
    ):
        self.hostname = hostname
        self.port = port
        self.username = username
        self.password = password
        self.key_path = resolve_path(key_path) if key_path else None
        self.passphrase = passphrase
        self.host_keys_policy = host_keys_policy
        self.sftp_retries = sftp_retries
        self.sftp_connect_timeout_sec = sftp_connect_timeout_sec
        self.sftp_operation_timeout_sec = sftp_operation_timeout_sec
        self.sftp_retry_backoff_base = sftp_retry_backoff_base
        self.sftp_retry_max_delay_sec = sftp_retry_max_delay_sec
        self._client: Optional[paramiko.SSHClient] = None
        self._sftp: Optional[paramiko.SFTPClient] = None

    def _execute_with_retry(self, operation, name: str) -> Any:
        """Ejecuta una operación con reintentamente y backoff exponencial."""
        last_exception = None
        for attempt in range(self.sftp_retries):
            try:
                return operation()
            except (ConnectionError, paramiko.SSHException, EOFError, socket.error) as e:
                # No reintentar si es un error de autenticación explícito
                if isinstance(e, AuthenticationError) or "authentication" in str(e).lower():
                    raise e

                
                last_exception = e
                if attempt == self.sftp_retries - 1:
                    break
                
                # Cálculo del tiempo de espera (backoff)
                wait_time = min(
                    self.sftp_retry_backoff_base * (2 ** attempt),
                    self.sftp_retry_max_delay_sec
                )
                logger.warning(
                    f"Error en {name} para {self.hostname} (intento {attempt + 1}/{self.sftp_retries}): {e}. "
                    f"Reintentando en {wait_time:.1f}s..."
                )
                time.sleep(wait_time)
        
        logger.error(f"Falló {name} tras {self.sftp_retries} intentos en {self.hostname}")
        raise_error = str(last_exception) if last_exception else "Error desconocido"
        raise ConnectionError(f"{name} failed after max retries on {self.hostname}: {raise_error}")


    def _set_policy(self, client: paramiko.SSHClient):
        """Sets the SSH host key policy."""
        if self.host_keys_policy == "strict":
            client.set_missing_hostkey_policy(paramiko.RejectPolicy())
        elif self.host_keys_policy == "accept-new":
            client.set_missing_hostkey_policy(paramiko.AutoAddPolicy())
        elif self.host_keys_policy == "insecure":
            client.set_missing_hostkey_policy(paramiko.WarningPolicy())
        elif self.host_keys_policy == "known_hosts":
            client.load_system_host_keys()
        else:
            client.set_missing_host_key_policy(paramiko.RejectPolicy())

    def connect(self):
        def _connect_logic():
            client = paramiko.SSHClient()
            self._set_policy(client)
            client.load_system_host_keys()
            
            connect_kwargs = {
                "hostname": self.hostname,
                "port": self.port,
                "username": self.username,
                "timeout": self.sftp_connect_timeout_sec
            }
            
            if self.password:
                connect_kwargs["password"] = self.password
            
            if self.key_path:
                if self.key_path.endswith(".ppk"):
                    raise AuthenticationError("PPK not supported directly, use OpenSSH format.")
                
                key = paramiko.RSAKey.from_private_key_file(
                    str(self.key_path), 
                    password=self.passphrase
                ) if self.passphrase else paramiko.RSAKey.from_private_key_file(str(self.key_path))
                connect_kwargs["pkey"] = key
            
            client.connect(**connect_kwargs)
            self._sftp = client.open_sftp()
            logger.info(f"Successfully connected to {self.hostname}")
            return client

        try:
            self._client = self._execute_with_retry(_connect_logic, "connect")
        except (paramiko.AuthenticationException, AuthenticationError) as e:
            logger.error(f"Authentication failed for {self.hostname}")
            raise AuthenticationError(f"Authentication failed: {str(e)}")
        except (paramiko.SSHException, ConnectionError) as e:
            raise
        except Exception as e:
            logger.error(f"Failed to connect to {self.hostname}")
            raise ConnectionError(f"Connection error: {str(e)}")





    def upload(self, local_path: Path, remote_path: str):
        if not self._sftp:
            raise ConnectionError("Not connected to SFTP server.")
        
        try:
            # 1. Ensure remote directory exists
            remote_dir = str(Path(remote_path).parent)
            self._ensure_remote_dir_exists(remote_dir)

            logger.info(f"Uploading {local_path} to {remote_path} on {self.hostname}")
            self._execute_with_retry(lambda: self._sftp.put(str(local_path), remote_path), "upload")
            
            # 2. Verify integrity
            self._verify_transfer_integrity(remote_path, local_path.stat().st_size)
            
            logger.info(f"Upload successful: {remote_path}")
        except Exception as e:
            logger.error(f"Upload failed for {remote_path}")
            raise TransferError(f"Upload failed: {str(e)}")


    def _ensure_remote_dir_exists(self, remote_path: str):
        """Recursively creates remote directories if they don't exist."""
        parts = remote_path.split('/')
        current_path = ""
        for part in parts:
            if not part:
                continue
            current_path += f"/{part}"
            try:
                self._sftp.stat(current_path)
            except IOError:
                logger.info(f"Creating remote directory: {current_path}")
                self._sftp.mkdir(current_path)

    def _verify_transfer_integrity(self, remote_path: str, local_size: int):
        """Verifies that the transferred file size matches the local file size."""
        try:
            remote_stat = self._sftp.stat(remote_path)
            if remote_stat.st_size != local_size:
                raise TransferError(
                    f"Integrity check failed for {remote_path}: "
                    f"Local size {local_size} != Remote size {remote_stat.st_size}"
                )
            logger.info(f"Integrity check passed for {remote_path}")
        except Exception as e:
            raise TransferError(f"Integrity verification failed: {str(e)}")

    def close(self):
        if self._sftp:
            self._sftp.close()
        if self._client:
            self._client.close()
        logger.info(f"Connection to {self.hostname} closed.")

"""Verificación de enmascarado de secretos en la transferencia (Item 038).

Garantiza que contraseñas, rutas de claves privadas y passphrases de los
servidores nunca aparecen en los logs de transferencia ni en el reporte
impreso de ``odin run``, aunque los mensajes de error las contengan
indirectamente (p. ej. la ruta de la clave dentro de una excepción).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from odin.backup import BackupResult, BatchBackupResult
from odin.cli import EXIT_FAILURE, main
from odin.config import Config, load_config
from odin.log import LOGGER_NAME, SecretMasker, setup_logging
from odin.transfer import TransferExecutor, TransferResult

FIXTURES = Path(__file__).parent / "fixtures"
PAYLOAD = b"ODIN backup payload " * 16

PASSWORD = "remote-secret-1"
PASSPHRASE = "passphrase-super-secreta"
KEY_PATH = "/home/odin/keys/id_secreta"


@pytest.fixture(autouse=True)
def clean_odin_logger() -> Iterator[None]:
    yield
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.setLevel(logging.NOTSET)
    logger.propagate = True


def _config_with_server_secrets(tmp_path: Path) -> Config:
    data: dict[str, Any] = json.loads(
        (FIXTURES / "config_valid_linux.json").read_text(encoding="utf-8")
    )
    data["local"]["work_dir"] = str(tmp_path / "work")
    data["servers"][1]["auth"] = {
        "method": "key",
        "private_key": KEY_PATH,
        "passphrase": PASSPHRASE,
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return load_config(str(path))


def _secret_values(config: Config) -> list[str]:
    """Secretos de servidores que no deben aparecer en ninguna salida."""
    server = config.servers[1]
    assert server.auth.private_key is not None
    assert server.auth.passphrase is not None
    return [PASSWORD, PASSPHRASE, server.auth.private_key]


def _install_failing_pipeline(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Respaldo exitoso real + transferencia que falla con secretos en el mensaje."""

    class FakeBackupExecutor:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def run_batch_backup(
            self, databases: list[Any], work_dir: Path
        ) -> BatchBackupResult:
            results = []
            for db in databases:
                backup_path = work_dir / f"{db.name}.fbk"
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                backup_path.write_bytes(PAYLOAD)
                results.append(
                    BackupResult(
                        success=True,
                        database_name=db.name,
                        backup_path=backup_path,
                        file_size_bytes=len(PAYLOAD),
                        duration_seconds=0.1,
                    )
                )
            return BatchBackupResult(
                results=results, success=True, total_duration_seconds=0.1
            )

    def errors(servers: list[Any], local_path: Path) -> list[TransferResult]:
        return [
            TransferResult(
                success=False,
                server_name=server.name,
                local_path=Path(local_path),
                remote_path=f"{server.remote_path}/{Path(local_path).name}",
                duration_seconds=0.05,
                error_message=(
                    f"auth rechazada: contraseña '{PASSWORD}' y clave "
                    f"'{KEY_PATH}' con frase '{PASSPHRASE}'"
                ),
            )
            for server in servers
        ]

    class FakeTransferExecutor:
        def run_batch_transfer(
            self, servers: list[Any], local_path: Path
        ) -> list[TransferResult]:
            return errors(servers, local_path)

    monkeypatch.setattr("odin.pipeline.BackupExecutor", FakeBackupExecutor)
    monkeypatch.setattr("odin.pipeline.TransferExecutor", FakeTransferExecutor)
    return errors


def test_run_report_masks_server_secrets_in_stdout_and_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _config_with_server_secrets(tmp_path)
    _install_failing_pipeline(monkeypatch)

    assert main(["run", "--config", str(config.config_path)]) == EXIT_FAILURE
    captured = capsys.readouterr()
    output = captured.out + captured.err

    for secret in _secret_values(config):
        assert secret not in output
    assert "***" in output
    assert "sitio-alterno-1" in captured.err
    assert "FALLO" in captured.err


def test_transfer_logs_mask_server_secrets_in_log_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config_with_server_secrets(tmp_path)
    logger = setup_logging(config)

    class LeakySFTPTransfer:
        def __init__(self, **kwargs: Any) -> None:
            self.hostname: str = kwargs["hostname"]

        def connect(self) -> None:
            raise RuntimeError(
                f"no se pudo leer la clave '{KEY_PATH}' "
                f"(frase: '{PASSPHRASE}', contraseña de respaldo: '{PASSWORD}')"
            )

        def upload(self, local_path: Path, remote_path: str) -> None:
            raise AssertionError("no debería llegar acá")

        def close(self) -> None:
            pass

    monkeypatch.setattr("odin.transfer.SFTPTransfer", LeakySFTPTransfer)
    artifact = tmp_path / "clientes.fbk.7z"
    artifact.write_bytes(PAYLOAD)

    results = TransferExecutor().run_batch_transfer(list(config.servers), artifact)
    assert all(result.success is False for result in results)

    logger.handlers[0].flush()
    log_content = (config.local.resolved_log_dir / "odin.log").read_text(encoding="utf-8")
    for secret in _secret_values(config):
        assert secret not in log_content
    assert "***" in log_content
    assert "sitio-alterno-1" in log_content


def test_masker_covers_server_auth_fields(tmp_path: Path) -> None:
    config = _config_with_server_secrets(tmp_path)
    masker = SecretMasker.from_config(config)

    assert masker.mask(PASSWORD) == "***"
    assert masker.mask(PASSPHRASE) == "***"
    assert masker.mask(KEY_PATH) == "***"
    masked = masker.mask(f"key={KEY_PATH} pass={PASSPHRASE}")
    assert KEY_PATH not in masked and PASSPHRASE not in masked
    assert masked == "key=*** pass=***"

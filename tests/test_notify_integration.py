"""Tests de integración de la notificación con un SMTP efímero in-process (Item 047).

El servidor SMTP es real (protocolo SMTP sobre loopback en un puerto efímero)
pero implementado con la stdlib (``socketserver``) en el mismo proceso: sin
dependencias externas ni contenedores, como el sshd ephemeral del Item 037.
Los casos de ``odin run`` doblan respaldo y transferencia (proceso externo y
red) y ejercitan la compresión real y el ``EmailNotifier`` real contra el
catcher: es el sustituto local de "correo recibido en la casilla de control".

La variante con Firebird real por Docker (patrón del Item 018) corre el flujo
``gbak + 7z + correo`` completo contra el catcher y se salta sin fallo cuando
Docker o su daemon no están disponibles. El ``gbak`` que se usa es el de la
propia imagen (helper ``tests.firebird_container``), así que no se requiere
``gbak`` en el host.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from odin.backup import BackupResult, BatchBackupResult
from odin.cli import ENV_CONFIG_VAR, EXIT_INTERNAL, EXIT_OK, main
from odin.config import DatabaseConfig, load_config
from odin.log import LOG_FILENAME, LOGGER_NAME
from odin.retention import RetentionResult
from odin.transfer import TransferResult
from tests.firebird_container import (
    DOCKER,
    FirebirdContainer,
    FirebirdContainerError,
    modern_image,
)
from tests.smtp_catcher import SmtpCatcher, closed_port, parse_message

FIXTURES = Path(__file__).parent / "fixtures"
LINUX_FIXTURE = FIXTURES / "config_valid_linux.json"

PAYLOAD = b"ODIN notify integration payload " * 32
TIMESTAMP = "20260915_120000"

CONTAINER = "odin-notify-integration"
FIREBIRD_PASSWORD = "masterkey"
FIREBIRD_DATABASE = "odin_notify_integration.fdb"


@pytest.fixture(autouse=True)
def clean_odin_logger() -> Iterator[None]:
    """Limpia el logger ``odin`` tras cada test (sin handlers abiertos)."""
    yield
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.setLevel(logging.NOTSET)
    logger.propagate = True


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Aísla los tests de un ``ODIN_CONFIG`` presente en el entorno real."""
    monkeypatch.delenv(ENV_CONFIG_VAR, raising=False)


def _write_config(
    tmp_path: Path,
    *,
    smtp_port: int,
    servers: bool = True,
    retention_days: int = 0,
    log_tail_lines: int = 5,
) -> Path:
    """Copia el fixture Linux y apunta ``notification.smtp`` al catcher."""
    data: dict[str, Any] = json.loads(LINUX_FIXTURE.read_text(encoding="utf-8"))
    data["local"]["work_dir"] = str(tmp_path / "work")
    data["local"]["retention_days"] = retention_days
    data["servers"] = data["servers"][:1] if servers else []
    notification = data["notification"]
    notification["log_tail_lines"] = log_tail_lines
    notification["smtp"] = {
        "host": "127.0.0.1",
        "port": smtp_port,
        "starttls": False,
        "ssl": False,
        "username": "smtp-user",
        "password": "smtp-secret",
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class _FakeBackupExecutor:
    """Doble de gbak: escribe un ``.fbk`` real por base (la compresión es real)."""

    def __init__(self, gbak_path: Any = None, timeout: Any = None) -> None:
        self.gbak_path = gbak_path
        self.timeout = timeout

    def run_batch_backup(
        self, databases: Sequence[DatabaseConfig], work_dir: Path
    ) -> BatchBackupResult:
        results: list[BackupResult] = []
        for database in databases:
            backup_path = work_dir / f"{database.name}_{TIMESTAMP}.fbk"
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            backup_path.write_bytes(PAYLOAD)
            results.append(
                BackupResult(
                    success=True,
                    database_name=database.name,
                    backup_path=backup_path,
                    file_size_bytes=len(PAYLOAD),
                    duration_seconds=0.1,
                )
            )
        return BatchBackupResult(results=results, success=True, total_duration_seconds=0.1)


class _FakeTransferExecutor:
    """Doble SFTP: éxito por servidor verificando el tamaño del ``.fbk.7z`` real."""

    def run_batch_transfer(
        self, servers: Sequence[Any], local_path: Path
    ) -> list[TransferResult]:
        size = local_path.stat().st_size
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


class _FakeRetentionExecutor:
    """Doble de retención: no-op deshabilitado (no toca el ``work_dir``)."""

    def run_retention(self, work_dir: Path, retention_days: int) -> RetentionResult:
        return RetentionResult(enabled=False)


def _install_fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dobla respaldo, transferencia y retención; el correo queda real."""
    monkeypatch.setattr("odin.pipeline.BackupExecutor", _FakeBackupExecutor)
    monkeypatch.setattr("odin.pipeline.TransferExecutor", _FakeTransferExecutor)
    monkeypatch.setattr("odin.pipeline.RetentionExecutor", _FakeRetentionExecutor)


@pytest.mark.integration
def test_run_delivers_report_through_real_smtp_without_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    catcher = SmtpCatcher()
    try:
        config_path = _write_config(tmp_path, smtp_port=catcher.port)
        _install_fakes(monkeypatch)

        exit_code = main(["run", "--config", str(config_path)])
    finally:
        catcher.close()

    captured = capsys.readouterr()
    assert exit_code == EXIT_OK
    assert "Correo enviado a control@example.com" in captured.out

    assert catcher.errors == []
    assert catcher.auth == [("smtp-user", "smtp-secret")]
    assert catcher.senders == ["odin-backups@example.com"]
    assert catcher.recipients == ["control@example.com"]
    assert len(catcher.messages) == 1

    raw = catcher.messages[0]
    message = parse_message(raw)
    assert message["To"] == "control@example.com"
    assert message["From"] == "odin-backups@example.com"
    assert str(message["Subject"]).startswith("[ODIN] ÉXITO")
    body = message.get_content()
    assert "Estado global: ÉXITO" in body
    assert "- erp_principal: OK" in body
    assert "sitio-alterno-1: OK" in body
    assert "Totales: 1/1 base(s) OK" in body
    assert "Últimas líneas del log" in body
    for secret in ("masterkey", "remote-secret-1", "smtp-secret"):
        assert secret not in raw
        assert secret not in body


@pytest.mark.integration
def test_run_with_unreachable_smtp_exits_1_without_crashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path, smtp_port=closed_port())
    _install_fakes(monkeypatch)

    exit_code = main(["run", "--config", str(config_path)])

    captured = capsys.readouterr()
    assert exit_code == EXIT_INTERNAL
    assert "1/1 base(s) con éxito" in captured.out
    assert "Correo NO enviado:" in captured.err
    assert "ConnectionRefusedError" in captured.err
    log_path = load_config(config_path).local.resolved_log_dir / LOG_FILENAME
    log_content = log_path.read_text(encoding="utf-8")
    assert "Correo NO enviado" in log_content


def _point_to_firebird(config_path: Path, container: FirebirdContainer) -> None:
    """Redirige la base del fixture al contenedor Firebird del test."""
    data = json.loads(config_path.read_text(encoding="utf-8"))
    data["databases"][0]["connection"] = container.database_spec()
    data["databases"][0]["user"] = "SYSDBA"
    data["databases"][0]["password"] = FIREBIRD_PASSWORD
    data["databases"][0]["gbak_path"] = str(
        container.gbak_wrapper(config_path.parent / "gbak-notify")
    )
    config_path.write_text(json.dumps(data), encoding="utf-8")


@pytest.mark.integration
@pytest.mark.skipif(DOCKER is None, reason="Docker no instalado en el host")
def test_run_end_to_end_with_firebird_and_local_catcher(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    catcher = SmtpCatcher()
    container = FirebirdContainer(
        modern_image(),
        name=CONTAINER,
        mount=tmp_path,
        root_password=FIREBIRD_PASSWORD,
        database_name=FIREBIRD_DATABASE,
    )
    try:
        container.start()
    except FirebirdContainerError as exc:
        catcher.close()
        pytest.skip(f"No se pudo iniciar el contenedor Firebird: {exc}")
    try:
        container.wait_ready()
        config_path = _write_config(tmp_path, smtp_port=catcher.port, servers=False)
        _point_to_firebird(config_path, container)

        exit_code = main(["run", "--config", str(config_path)])
    finally:
        catcher.close()
        container.remove()

    captured = capsys.readouterr()
    assert exit_code == EXIT_OK
    assert "Correo enviado a control@example.com" in captured.out
    assert catcher.errors == []
    assert catcher.recipients == ["control@example.com"]
    assert len(catcher.messages) == 1
    body = parse_message(catcher.messages[0]).get_content()
    assert "Estado global: ÉXITO" in body
    assert "- erp_principal: OK" in body
    assert "Servidores destino: ninguno configurado." in body
    assert list((tmp_path / "work").glob("*.fbk.7z"))

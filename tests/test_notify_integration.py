"""Tests de integración de la notificación con un SMTP efímero in-process (Item 047).

El servidor SMTP es real (protocolo SMTP sobre loopback en un puerto efímero)
pero implementado con la stdlib (``socketserver``) en el mismo proceso: sin
dependencias externas ni contenedores, como el sshd ephemeral del Item 037.
Los casos de ``odin run`` doblan respaldo y transferencia (proceso externo y
red) y ejercitan la compresión real y el ``EmailNotifier`` real contra el
catcher: es el sustituto local de "correo recibido en la casilla de control".

La variante con Firebird real por Docker (patrón del Item 018) corre el flujo
``gbak + 7z + correo`` completo contra el catcher y se salta sin fallo cuando
Docker, su daemon o ``gbak`` no están disponibles.
"""

from __future__ import annotations

import base64
import email
import json
import logging
import shutil
import socket
import socketserver
import subprocess
import threading
import time
from collections.abc import Iterator, Sequence
from email import policy
from pathlib import Path
from typing import Any

import pytest

from odin.backup import BackupExecutor, BackupResult, BatchBackupResult
from odin.cli import ENV_CONFIG_VAR, EXIT_INTERNAL, EXIT_OK, main
from odin.config import DatabaseConfig, load_config
from odin.gbak_finder import find_gbak
from odin.log import LOG_FILENAME, LOGGER_NAME
from odin.retention import RetentionResult
from odin.transfer import TransferResult

FIXTURES = Path(__file__).parent / "fixtures"
LINUX_FIXTURE = FIXTURES / "config_valid_linux.json"

PAYLOAD = b"ODIN notify integration payload " * 32
TIMESTAMP = "20260915_120000"

DOCKER = shutil.which("docker")
GBACK = find_gbak()
CONTAINER = "odin-notify-integration"
IMAGE = "firebirdsql/firebird:latest"
FIREBIRD_PASSWORD = "masterkey"
FIREBIRD_DATABASE = "odin_notify_integration.fdb"
FIREBIRD_PATH = f"/var/lib/firebird/data/{FIREBIRD_DATABASE}"


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


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("ascii")).decode("ascii")


class _SmtpHandler(socketserver.StreamRequestHandler):
    """Sesión SMTP mínima: EHLO, AUTH LOGIN, MAIL/RCPT, DATA y QUIT."""

    server: _SmtpCatcher

    def handle(self) -> None:
        try:
            self._serve()
        except (OSError, ValueError) as exc:
            self.server.errors.append(exc)

    def _serve(self) -> None:
        self._reply("220 odin-test ESMTP")
        while True:
            raw = self.rfile.readline()
            if not raw:
                return
            parts = raw.decode("ascii", "replace").strip().split(" ", 1)
            verb = parts[0].upper()
            argument = parts[1] if len(parts) > 1 else ""
            if verb in ("EHLO", "HELO"):
                self._reply("250-odin-test")
                self._reply("250-AUTH LOGIN")
                self._reply("250 OK")
            elif verb == "AUTH":
                self._auth(argument)
            elif verb in ("MAIL", "RCPT"):
                target = self._address(argument)
                if verb == "MAIL":
                    self.server.senders.append(target)
                else:
                    self.server.recipients.append(target)
                self._reply("250 OK")
            elif verb == "DATA":
                self._reply("354 End data with <CR><LF>.<CR><LF>")
                self.server.messages.append(self._read_data())
                self._reply("250 OK")
            elif verb == "QUIT":
                self._reply("221 Bye")
                return
            else:
                self._reply("250 OK")

    def _auth(self, argument: str) -> None:
        """Acepta ``AUTH LOGIN`` con respuesta inicial o por desafío."""
        pieces = argument.split()
        if not pieces or pieces[0].upper() != "LOGIN":
            self._reply("504 Unrecognized authentication type")
            return
        if len(pieces) > 1:
            username = self._decode(pieces[1])
        else:
            self._reply(f"334 {_b64('Username:')}")
            username = self._decode(self._read_auth_value())
        self._reply(f"334 {_b64('Password:')}")
        password = self._decode(self._read_auth_value())
        self.server.auth.append((username, password))
        self._reply("235 Authentication successful")

    def _read_auth_value(self) -> str:
        return self.rfile.readline().decode("ascii", "replace").strip()

    def _read_data(self) -> str:
        lines: list[bytes] = []
        while True:
            line = self.rfile.readline()
            if not line or line in (b".\r\n", b".\n"):
                break
            lines.append(line)
        return b"".join(lines).decode("utf-8", "replace")

    @staticmethod
    def _address(argument: str) -> str:
        """Extrae la dirección de ``MAIL FROM:<...>``/``RCPT TO:<...>``."""
        _, _, address = argument.partition(":")
        return address.strip().strip("<>")

    @staticmethod
    def _decode(value: str) -> str:
        return base64.b64decode(value).decode("utf-8", "replace")

    def _reply(self, text: str) -> None:
        self.wfile.write(f"{text}\r\n".encode("ascii"))


class _SmtpCatcher(socketserver.ThreadingTCPServer):
    """Servidor SMTP efímero en un hilo: captura lo que ODIN entrega."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _SmtpHandler)
        self.messages: list[str] = []
        self.senders: list[str] = []
        self.recipients: list[str] = []
        self.auth: list[tuple[str, str]] = []
        self.errors: list[BaseException] = []
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)
        self._thread.start()

    @property
    def port(self) -> int:
        return int(self.server_address[1])

    def close(self) -> None:
        self.shutdown()
        self.server_close()
        self._thread.join(timeout=5)


def _parse_message(raw: str) -> email.message.Message:
    """Parsea el mensaje capturado decodificando cabeceras/cuerpo MIME."""
    return email.message_from_string(raw, policy=policy.default)


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


def _closed_port() -> int:
    """Reserva y libera un puerto loopback: la conexión será rechazada."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.mark.integration
def test_run_delivers_report_through_real_smtp_without_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    catcher = _SmtpCatcher()
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
    message = _parse_message(raw)
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
    config_path = _write_config(tmp_path, smtp_port=_closed_port())
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


def _docker(*args: str) -> subprocess.CompletedProcess[str]:
    assert DOCKER is not None
    return subprocess.run([DOCKER, *args], capture_output=True, text=True)


def _wait_for_firebird(port: int, tmp_path: Path) -> None:
    """Espera a que Firebird acepte un ``gbak`` real (retry hasta 60 s)."""
    assert GBACK is not None
    database = DatabaseConfig(
        name="odin_notify_probe",
        connection=f"localhost/{port}:{FIREBIRD_PATH}",
        user="sysdba",
        password=FIREBIRD_PASSWORD,
    )
    executor = BackupExecutor(GBACK, timeout=60)
    probe = tmp_path / "probe.fbk"
    deadline = time.monotonic() + 60
    result = executor.run_backup(database.name, database.connection, str(probe), database)
    while not result.success and time.monotonic() < deadline:
        time.sleep(3)
        result = executor.run_backup(database.name, database.connection, str(probe), database)
    if not result.success:
        pytest.skip(f"Firebird no respondió a tiempo: {result.error_message}")


def _point_to_firebird(config_path: Path, port: str) -> None:
    """Redirige la base del fixture al contenedor Firebird del test."""
    data = json.loads(config_path.read_text(encoding="utf-8"))
    data["databases"][0]["connection"] = f"localhost/{port}:{FIREBIRD_PATH}"
    data["databases"][0]["user"] = "SYSDBA"
    data["databases"][0]["password"] = FIREBIRD_PASSWORD
    config_path.write_text(json.dumps(data), encoding="utf-8")


@pytest.mark.integration
@pytest.mark.skipif(DOCKER is None, reason="Docker no instalado en el host")
@pytest.mark.skipif(GBACK is None, reason="gbak no instalado en el host")
def test_run_end_to_end_with_firebird_and_local_catcher(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    catcher = _SmtpCatcher()
    _docker("rm", "-f", CONTAINER)
    started = _docker(
        "run",
        "--name",
        CONTAINER,
        "-d",
        "-P",
        "-e",
        f"FIREBIRD_ROOT_PASSWORD={FIREBIRD_PASSWORD}",
        "-e",
        f"FIREBIRD_DATABASE={FIREBIRD_DATABASE}",
        IMAGE,
    )
    try:
        if started.returncode != 0:
            pytest.skip(f"No se pudo iniciar el contenedor Firebird: {started.stderr.strip()}")
        mapped = _docker("port", CONTAINER, "3050/tcp").stdout.strip()
        if not mapped:
            pytest.skip("Docker no publicó el puerto 3050 del contenedor")
        port = mapped.rsplit(":", 1)[1]
        _wait_for_firebird(int(port), tmp_path)
        config_path = _write_config(tmp_path, smtp_port=catcher.port, servers=False)
        _point_to_firebird(config_path, port)

        exit_code = main(["run", "--config", str(config_path)])
    finally:
        catcher.close()
        _docker("rm", "-f", CONTAINER)

    captured = capsys.readouterr()
    assert exit_code == EXIT_OK
    assert "Correo enviado a control@example.com" in captured.out
    assert catcher.errors == []
    assert catcher.recipients == ["control@example.com"]
    assert len(catcher.messages) == 1
    body = _parse_message(catcher.messages[0]).get_content()
    assert "Estado global: ÉXITO" in body
    assert "- erp_principal: OK" in body
    assert "Servidores destino: ninguno configurado." in body
    assert list((tmp_path / "work").glob("*.fbk.7z"))

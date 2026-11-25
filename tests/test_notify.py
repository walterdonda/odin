"""Tests de notificación (Items 039-042): transporte SMTP mockeado y render del informe."""

from __future__ import annotations

import json
import smtplib
from collections.abc import Mapping, Sequence
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any, ClassVar

import pytest

from odin.backup import BackupResult, BatchBackupResult
from odin.config import Config, SchedulerJob, SmtpConfig, load_config
from odin.notify import (
    DEFAULT_SMTP_TIMEOUT_SEC,
    EmailNotifier,
    ReportMessage,
    render_report,
    render_template,
)
from odin.pipeline import PipelineResult
from odin.transfer import BatchTransferResult, TransferResult

FIXTURES = Path(__file__).parent / "fixtures"


class FakeSMTP:
    """Doble de ``smtplib.SMTP`` que registra llamadas y permite inyectar fallos."""

    instances: ClassVar[list[FakeSMTP]] = []
    connect_exception: ClassVar[Exception | None] = None
    login_exception: ClassVar[Exception | None] = None
    send_exception: ClassVar[Exception | None] = None

    def __init__(self, host: str, port: int, timeout: float | None = None) -> None:
        if type(self).connect_exception is not None:
            raise type(self).connect_exception
        self.host = host
        self.port = port
        self.timeout = timeout
        self.calls: list[Any] = []
        self.message: EmailMessage | None = None
        type(self).instances.append(self)

    def ehlo(self) -> None:
        self.calls.append("ehlo")

    def starttls(self) -> None:
        self.calls.append("starttls")

    def login(self, user: str, password: str) -> None:
        self.calls.append(("login", user, password))
        if type(self).login_exception is not None:
            raise type(self).login_exception

    def send_message(self, message: EmailMessage) -> None:
        self.calls.append("send_message")
        self.message = message
        if type(self).send_exception is not None:
            raise type(self).send_exception

    def quit(self) -> None:
        self.calls.append("quit")


class FakeSMTPSSL(FakeSMTP):
    """Doble de ``smtplib.SMTP_SSL`` (SSL implícito)."""

    instances: ClassVar[list[FakeSMTPSSL]] = []


@pytest.fixture()
def smtp_mock(monkeypatch: pytest.MonkeyPatch) -> type[FakeSMTP]:
    """Instala los dobles de ``smtplib`` y resetea el estado de clase."""
    for cls in (FakeSMTP, FakeSMTPSSL):
        cls.instances = []
        cls.connect_exception = None
        cls.login_exception = None
        cls.send_exception = None
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTPSSL)
    return FakeSMTP


def _config(
    tmp_path: Path,
    *,
    servers: bool = True,
    environment: tuple[str, str] | None = None,
    notification: Mapping[str, Any] | None = None,
    **smtp_overrides: Any,
) -> Config:
    """Config Linux válida; permite apagar servidores, mutar ``notification`` y el entorno."""
    data: dict[str, Any] = json.loads(
        (FIXTURES / "config_valid_linux.json").read_text(encoding="utf-8")
    )
    data["local"]["work_dir"] = str(tmp_path / "work")
    if not servers:
        data["servers"] = []
    data["notification"]["smtp"].update(smtp_overrides)
    if environment is not None:
        data["environment"] = {"client": environment[0], "name": environment[1]}
    if notification:
        data["notification"].update(notification)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return load_config(str(path))


def _report(subject: str = "asunto", body: str = "cuerpo") -> ReportMessage:
    return ReportMessage(subject=subject, body_text=body)


# --- Transporte SMTP (Item 039) ---


def test_plain_mode_when_starttls_disabled(tmp_path: Path, smtp_mock: type[FakeSMTP]) -> None:
    config = _config(tmp_path, starttls=False)

    result = EmailNotifier.from_config(config).send(_report())

    (server,) = FakeSMTP.instances
    assert server.calls == [
        ("login", "odin-backups@example.com", "smtp-secret"),
        "send_message",
        "quit",
    ]
    assert result.success is True
    assert result.recipient == "control@example.com"
    assert result.error_message is None
    assert result.duration_seconds >= 0


def test_starttls_negotiated_when_enabled(tmp_path: Path, smtp_mock: type[FakeSMTP]) -> None:
    config = _config(tmp_path)

    EmailNotifier.from_config(config).send(_report())

    (server,) = FakeSMTP.instances
    assert server.calls[:3] == ["ehlo", "starttls", "ehlo"]


def test_ssl_mode_uses_smtp_ssl(tmp_path: Path, smtp_mock: type[FakeSMTP]) -> None:
    config = _config(tmp_path, starttls=False, ssl=True)

    EmailNotifier.from_config(config).send(_report())

    assert FakeSMTP.instances == []
    (server,) = FakeSMTPSSL.instances
    assert server.host == "smtp.example.com"
    assert server.port == 587
    assert "starttls" not in server.calls
    assert "send_message" in server.calls


def test_login_skipped_without_username(tmp_path: Path, smtp_mock: type[FakeSMTP]) -> None:
    notifier = EmailNotifier(
        SmtpConfig(host="smtp.example.com", port=587, starttls=False),
        to="control@example.com",
        from_="odin-backups@example.com",
    )

    notifier.send(_report())

    (server,) = FakeSMTP.instances
    assert all(not isinstance(call, tuple) for call in server.calls)


def test_envelope_from_to_and_body(tmp_path: Path, smtp_mock: type[FakeSMTP]) -> None:
    config = _config(tmp_path)

    EmailNotifier.from_config(config).send(_report("Asunto X", "Cuerpo Y"))

    (server,) = FakeSMTP.instances
    message = server.message
    assert message is not None
    assert message["From"] == "odin-backups@example.com"
    assert message["To"] == "control@example.com"
    assert message["Subject"] == "Asunto X"
    assert message["Content-Language"] == "es-419"
    assert message.get_content_type() == "text/plain"
    assert not message.is_multipart()
    assert message.get_content().strip() == "Cuerpo Y"
    assert message.get_content_charset() == "utf-8"


def test_report_html_part_becomes_alternative(tmp_path: Path, smtp_mock: type[FakeSMTP]) -> None:
    config = _config(tmp_path)

    EmailNotifier.from_config(config).send(
        ReportMessage(subject="Asunto X", body_text="plano", body_html="<p>html</p>")
    )

    (server,) = FakeSMTP.instances
    message = server.message
    assert message is not None
    assert message.get_content_type() == "multipart/alternative"
    parts = message.get_payload()
    assert [part.get_content_type() for part in parts] == ["text/plain", "text/html"]
    plain, html_part = parts
    assert plain.get_content().strip() == "plano"
    assert plain.get_content_charset() == "utf-8"
    assert html_part.get_content().strip() == "<p>html</p>"
    assert html_part.get_content_charset() == "utf-8"


def test_timeout_passed_to_transport(tmp_path: Path, smtp_mock: type[FakeSMTP]) -> None:
    config = _config(tmp_path)

    EmailNotifier.from_config(config).send(_report())

    (server,) = FakeSMTP.instances
    assert server.timeout == DEFAULT_SMTP_TIMEOUT_SEC


def test_socket_timeout_becomes_failed_result(
    tmp_path: Path, smtp_mock: type[FakeSMTP]
) -> None:
    FakeSMTP.connect_exception = TimeoutError("timed out")

    result = EmailNotifier.from_config(_config(tmp_path)).send(_report())

    assert result.success is False
    assert "TimeoutError" in (result.error_message or "")
    assert "smtp.example.com:587" in (result.error_message or "")


def test_authentication_error_becomes_failed_result(
    tmp_path: Path, smtp_mock: type[FakeSMTP]
) -> None:
    FakeSMTP.login_exception = smtplib.SMTPAuthenticationError(535, b"bad credentials")

    result = EmailNotifier.from_config(_config(tmp_path)).send(_report())

    assert result.success is False
    assert "SMTPAuthenticationError" in (result.error_message or "")
    (server,) = FakeSMTP.instances
    assert "quit" in server.calls


def test_connect_error_becomes_failed_result(
    tmp_path: Path, smtp_mock: type[FakeSMTP]
) -> None:
    FakeSMTP.connect_exception = smtplib.SMTPConnectError(421, b"service down")

    result = EmailNotifier.from_config(_config(tmp_path)).send(_report())

    assert result.success is False
    assert "SMTPConnectError" in (result.error_message or "")


def test_connection_refused_becomes_failed_result(
    tmp_path: Path, smtp_mock: type[FakeSMTP]
) -> None:
    FakeSMTP.connect_exception = ConnectionRefusedError(111, "Connection refused")

    result = EmailNotifier.from_config(_config(tmp_path)).send(_report())

    assert result.success is False
    assert "ConnectionRefusedError" in (result.error_message or "")
    assert result.recipient == "control@example.com"


def test_send_failure_becomes_failed_result_and_closes(
    tmp_path: Path, smtp_mock: type[FakeSMTP]
) -> None:
    FakeSMTP.send_exception = smtplib.SMTPDataError(554, b"message rejected")

    result = EmailNotifier.from_config(_config(tmp_path)).send(_report())

    assert result.success is False
    assert "SMTPDataError" in (result.error_message or "")
    (server,) = FakeSMTP.instances
    assert server.calls[-1] == "quit"


# --- Render del informe (Item 040) ---

NOW = datetime(2026, 9, 15, 10, 30, 0)


def _ok_backup(name: str) -> BackupResult:
    return BackupResult(
        success=True,
        database_name=name,
        backup_path=Path(f"/work/{name}.fbk"),
        file_size_bytes=100,
        duration_seconds=0.1,
        archive_path=Path(f"/work/{name}.fbk.7z"),
        compressed_size_bytes=40,
        compression_duration_seconds=0.2,
    )


def _failed_backup(
    name: str, error: str = "gbak falló (código 1): database is in use"
) -> BackupResult:
    return BackupResult(
        success=False,
        database_name=name,
        duration_seconds=0.1,
        error_message=error,
    )


def _compression_failure(name: str) -> BackupResult:
    return BackupResult(
        success=False,
        database_name=name,
        backup_path=Path(f"/work/{name}.fbk"),
        file_size_bytes=100,
        duration_seconds=0.1,
        compression_error_message="no se pudo comprimir: disco lleno",
    )


def _transfer_failure(
    name: str, error: str = "sitio-alterno-1: Connection error: refused"
) -> BackupResult:
    return BackupResult(
        success=False,
        database_name=name,
        backup_path=Path(f"/work/{name}.fbk"),
        file_size_bytes=100,
        duration_seconds=0.1,
        archive_path=Path(f"/work/{name}.fbk.7z"),
        compressed_size_bytes=40,
        compression_duration_seconds=0.2,
        transfer_error_message=error,
    )


def _transfer(
    name: str, server: str, *, success: bool = True, error: str | None = None
) -> TransferResult:
    return TransferResult(
        success=success,
        server_name=server,
        local_path=Path(f"/work/{name}.fbk.7z"),
        remote_path=f"/backups/firebird/{name}.fbk.7z",
        transferred_bytes=40 if success else None,
        duration_seconds=0.3,
        error_message=error,
    )


def _render(
    config: Config,
    results: Sequence[BackupResult],
    transfers: Mapping[str, Sequence[TransferResult]] | None = None,
    *,
    error_message: str | None = None,
    log_tail: Sequence[str] = (),
    job: SchedulerJob | None = None,
) -> ReportMessage:
    batch = BatchBackupResult(
        results=tuple(results),
        success=bool(results) and all(result.success for result in results),
        total_duration_seconds=0.5,
        error_message=error_message,
    )
    batches = {
        name: BatchTransferResult(
            results=tuple(items),
            success=all(item.success for item in items),
            total_duration_seconds=sum(item.duration_seconds for item in items),
        )
        for name, items in (transfers or {}).items()
    }
    pipeline = PipelineResult(backup=batch, transfers=batches)
    return render_report(
        config, pipeline, log_tail=log_tail, now=NOW, hostname="srv-prueba", job=job
    )


def test_render_success_state(tmp_path: Path) -> None:
    config = _config(tmp_path)

    report = _render(
        config,
        [_ok_backup("erp_principal")],
        {
            "erp_principal": [
                _transfer("erp_principal", "sitio-alterno-1"),
                _transfer("erp_principal", "sitio-alterno-2"),
            ]
        },
    )

    assert report.subject == "[ODIN] ÉXITO — respaldo de erp_principal (2026-09-15 10:30:00)"
    assert "Estado global: ÉXITO" in report.body_text
    assert "- erp_principal: OK" in report.body_text
    assert f"{Path('/work/erp_principal.fbk')} (100 bytes, 0.1 s)" in report.body_text
    assert f"{Path('/work/erp_principal.fbk.7z')} (40 bytes, 0.2 s)" in report.body_text
    assert "transferencia: 2/2 destino(s) OK" in report.body_text
    assert (
        "- erp_principal → sitio-alterno-1: OK /backups/firebird/erp_principal.fbk.7z "
        "(40 bytes, 0.3 s)" in report.body_text
    )
    assert "Totales: 1/1 base(s) OK" in report.body_text
    assert "destinos 2/2 OK" in report.body_text
    assert report.body_html is not None
    assert "<h3>Estado global: ÉXITO</h3>" in report.body_html
    assert "erp_principal: OK" in report.body_html
    assert "--" in report.body_text
    assert "ODIN" in report.body_text


def test_render_partial_state(tmp_path: Path) -> None:
    config = _config(tmp_path)

    report = _render(config, [_ok_backup("uno"), _failed_backup("dos")])

    assert report.subject.startswith("[ODIN] PARCIAL")
    assert "Estado global: PARCIAL" in report.body_text
    assert "- uno: OK" in report.body_text
    assert "- dos: FALLO" in report.body_text
    assert "error de respaldo: gbak falló (código 1): database is in use" in report.body_text
    assert "Totales: 1/2 base(s) OK" in report.body_text


def test_render_failure_state(tmp_path: Path) -> None:
    config = _config(tmp_path)

    report = _render(config, [_failed_backup("uno"), _compression_failure("dos")])

    assert report.subject.startswith("[ODIN] FALLO")
    assert "Estado global: FALLO" in report.body_text
    assert "error de compresión: no se pudo comprimir: disco lleno" in report.body_text
    assert "Totales: 0/2 base(s) OK" in report.body_text


def test_render_batch_error_message(tmp_path: Path) -> None:
    config = _config(tmp_path)

    report = _render(config, [], error_message="no se pudo preparar el directorio de trabajo")

    assert report.subject.startswith("[ODIN] FALLO")
    assert "Respaldo no ejecutado: no se pudo preparar el directorio de trabajo" in report.body_text
    assert "Bases:" not in report.body_text


def test_render_empty_batch(tmp_path: Path) -> None:
    config = _config(tmp_path)

    report = _render(config, [])

    assert report.subject.startswith("[ODIN] FALLO")
    assert "No hay bases configuradas" in report.body_text


def test_render_without_servers(tmp_path: Path) -> None:
    config = _config(tmp_path, servers=False)

    report = _render(config, [_ok_backup("erp_principal")])

    assert "transferencia: no aplica (sin servidores)" in report.body_text
    assert "Servidores destino: ninguno configurado." in report.body_text
    assert "destinos 0/0 OK" in report.body_text


def test_render_base_without_transfer(tmp_path: Path) -> None:
    config = _config(tmp_path)

    report = _render(config, [_failed_backup("erp_principal")])

    assert "Servidores destino: sin transferencias en esta ejecución." in report.body_text


def test_render_transfer_failure_detail(tmp_path: Path) -> None:
    config = _config(tmp_path)

    report = _render(
        config,
        [_transfer_failure("erp_principal")],
        {
            "erp_principal": [
                _transfer(
                    "erp_principal",
                    "sitio-alterno-1",
                    success=False,
                    error="Connection error: refused",
                )
            ]
        },
    )

    assert "error de transferencia: sitio-alterno-1: Connection error: refused" in report.body_text
    assert (
        "- erp_principal → sitio-alterno-1: FALLO (Connection error: refused)"
        in report.body_text
    )
    assert "destinos 0/1 OK" in report.body_text


def test_render_includes_log_tail(tmp_path: Path) -> None:
    config = _config(tmp_path)

    report = _render(
        config, [_ok_backup("erp_principal")], log_tail=["primera línea", "segunda línea"]
    )

    assert "Últimas líneas del log (2):" in report.body_text
    assert report.body_text.index("primera línea") < report.body_text.index("segunda línea")


def test_render_omits_log_tail_header_when_empty(tmp_path: Path) -> None:
    config = _config(tmp_path)

    report = _render(config, [_ok_backup("erp_principal")])

    assert "Últimas líneas del log" not in report.body_text


def test_render_never_includes_secrets(tmp_path: Path) -> None:
    config = _config(tmp_path)
    secrets = [
        config.databases[0].password,
        config.servers[0].auth.password,
        config.notification.smtp.password,
    ]
    private_key = config.servers[1].auth.private_key
    assert private_key is not None
    secrets.append(private_key)
    error = "falló con " + " ".join(secrets)

    report = _render(
        config,
        [_failed_backup("erp_principal", error=error), _transfer_failure("otra", error=error)],
        log_tail=[f"linea de log con {secrets[0]}"],
    )

    text = f"{report.subject}\n{report.body_text}\n{report.body_html}"
    for secret in secrets:
        assert secret not in text
    assert "***" in text


# --- Plantillas y contexto del informe (Item 079) ---


def test_render_default_subject_with_environment(tmp_path: Path) -> None:
    config = _config(tmp_path, environment=("caktus", "prod"))

    report = _render(config, [_ok_backup("erp_principal")])

    assert report.subject == (
        "[ODIN] [caktus-prod] ÉXITO — respaldo de erp_principal (2026-09-15 10:30:00)"
    )
    assert "Cliente: caktus · Entorno: prod" in report.body_text
    assert "Cliente: caktus · Entorno: prod" in (report.body_html or "")


def test_render_custom_subject_template(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        environment=("caktus", "prod"),
        notification={"subject": "ODIN {cliente}/{entorno}: {estado} de {motor}"},
    )

    report = _render(config, [_ok_backup("erp_principal")])

    assert report.subject == "ODIN caktus/prod: ÉXITO de firebird"


def test_render_custom_body_text_template(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        notification={
            "body_text": "Corrida {fecha} sobre {instancia} ({motor}).\n\n{totales}"
        },
    )

    report = _render(config, [_ok_backup("erp_principal")])

    assert "Corrida 2026-09-15 10:30:00 sobre erp_principal (firebird)." in report.body_text
    assert "Totales: 1/1 base(s) OK" in report.body_text
    assert "--" in report.body_text
    assert "ODIN" in report.body_text  # firma aplicada después de la plantilla


def test_render_custom_body_html_template_escapes_values(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        notification={"body_html": "<p>{instancia} &amp; co</p>"},
    )
    report = _render(config, [_ok_backup("erp_principal")])
    assert "<p>erp_principal &amp; co</p>" in (report.body_html or "")
    assert "--" in (report.body_html or "")


def test_render_signature_with_contact(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        environment=("caktus", "prod"),
        notification={"contact": "ops@caktus.example"},
    )

    report = _render(config, [_ok_backup("erp_principal")])

    assert "ODIN · caktus-prod" in report.body_text
    assert "Contacto: ops@caktus.example" in report.body_text
    assert "ODIN · caktus-prod" in (report.body_html or "")


def test_render_custom_signature_template(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        environment=("caktus", "prod"),
        notification={
            "signature": "Backups de {cliente} — {contacto}",
            "contact": "ops@caktus.example",
        },
    )

    report = _render(config, [_ok_backup("erp_principal")])

    assert "Backups de caktus — ops@caktus.example" in report.body_text


def test_render_scheduled_job_shows_human_schedule(tmp_path: Path) -> None:
    config = _config(tmp_path)
    job = SchedulerJob(databases=["erp_principal"], schedule="0 3 * * *")

    report = _render(config, [_ok_backup("erp_principal")], job=job)

    assert (
        "Horario: todos los días a las 03:00 (America/Argentina/Buenos_Aires)"
        in report.body_text
    )


def test_render_manual_run_omits_schedule_line(tmp_path: Path) -> None:
    config = _config(tmp_path)

    report = _render(config, [_ok_backup("erp_principal")])

    assert "Horario:" not in report.body_text


def test_render_truncates_many_instances_in_subject(tmp_path: Path) -> None:
    config = _config(tmp_path)

    report = _render(
        config, [_ok_backup(name) for name in ("uno", "dos", "tres", "cuatro", "cinco")]
    )

    assert "respaldo de uno, dos, tres +2" in report.subject


def test_render_lists_engines_without_duplicates(tmp_path: Path) -> None:
    config = _config(tmp_path, notification={"subject": "motores: {motor}"})

    report = _render(config, [_ok_backup("erp_principal")])

    assert report.subject == "motores: firebird"


def test_render_template_replaces_whitelisted_placeholders() -> None:
    assert render_template("Hola {cliente}", {"cliente": "caktus"}) == "Hola caktus"


def test_render_template_values_with_braces_are_literal() -> None:
    assert render_template("{log}", {"log": "línea {literal} rara"}) == "línea {literal} rara"


def test_render_template_unknown_placeholder_raises() -> None:
    with pytest.raises(ValueError):
        render_template("hola {desconocido}", {"cliente": "caktus"})

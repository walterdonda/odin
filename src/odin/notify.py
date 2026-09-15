"""Notificación por correo del informe de ejecución (Items 039 y 040).

Cliente SMTP sobre ``smtplib`` (solo stdlib) que envía el informe a
``notification.to`` desde ``notification.from_`` usando ``notification.smtp``:
STARTTLS por defecto, modo plano para relays locales (``starttls: false``) y
SSL implícito para el puerto 465 (``smtp.ssl: true``, mutuamente excluyente con
STARTTLS y validado en ``config.py``). Los timeouts de conexión/operación son
parametrizables con ``DEFAULT_SMTP_TIMEOUT_SEC`` (30 s); no se exponen en el
JSON para no sumar superficie de configuración.

``NotificationResult`` documenta el desenlace: los errores operativos
esperados (``SMTPException``, ``OSError``, ``socket.timeout`` y sus
subclases como ``ConnectionRefusedError``) **no** se propagan — se reportan en
el resultado y se loguean sin exponer credenciales, de modo que un SMTP caído
no tumba el pipeline (Item 043).

``render_report`` construye el asunto y el cuerpo en texto plano desde el
``PipelineResult`` + ``Config`` sin tocar la red. El texto pasa por
``SecretMasker`` como segunda barrera de enmascarado: el correo nunca incluye
credenciales ni adjunta el backup.
"""

from __future__ import annotations

import smtplib
import socket
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from typing import TYPE_CHECKING

from odin.config import Config, SmtpConfig
from odin.log import SecretMasker, logger

if TYPE_CHECKING:
    from odin.backup import BatchBackupResult
    from odin.pipeline import PipelineResult

__all__ = [
    "DEFAULT_SMTP_TIMEOUT_SEC",
    "EmailNotifier",
    "NotificationResult",
    "ReportMessage",
    "render_report",
]

DEFAULT_SMTP_TIMEOUT_SEC = 30

STATUS_SUCCESS = "ÉXITO"
STATUS_PARTIAL = "PARCIAL"
STATUS_FAILURE = "FALLO"

_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


@dataclass(frozen=True, slots=True)
class NotificationResult:
    """Resultado del envío del informe (éxito o fallo con causa).

    ``error_message`` queda en ``None`` cuando el correo se envió; en caso
    contrario contiene la causa legible (tipo de excepción + detalle) sin
    credenciales. ``recipient`` es el destinatario configurado
    (``notification.to``).
    """

    success: bool
    recipient: str
    duration_seconds: float = 0.0
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class ReportMessage:
    """Informe renderizado listo para enviar: asunto y cuerpo en texto plano."""

    subject: str
    body: str


class EmailNotifier:
    """Envía el informe de ejecución por SMTP con la configuración de ODIN."""

    def __init__(
        self,
        smtp: SmtpConfig,
        to: str,
        from_: str,
        timeout: int = DEFAULT_SMTP_TIMEOUT_SEC,
    ) -> None:
        self.smtp = smtp
        self.to = to
        self.from_ = from_
        self.timeout = timeout

    @classmethod
    def from_config(cls, config: Config) -> EmailNotifier:
        """Construye el notifier desde ``config.notification``."""
        notification = config.notification
        return cls(
            smtp=notification.smtp,
            to=notification.to,
            from_=notification.from_,
        )

    def send(self, report: ReportMessage) -> NotificationResult:
        """Envía ``report`` y devuelve el resultado; nunca propaga errores SMTP.

        El cuerpo va como texto plano y no se adjunta el backup. El cierre de
        la conexión es best-effort: un fallo al cerrar no convierte un envío
        exitoso en fallo.
        """
        start_time = time.perf_counter()
        try:
            message = self._build_message(report)
            server = self._connect()
            try:
                if self.smtp.username:
                    server.login(self.smtp.username, self.smtp.password)
                server.send_message(message)
            finally:
                self._close(server)
        except (smtplib.SMTPException, OSError) as exc:
            return self._failure(start_time, exc)

        duration = time.perf_counter() - start_time
        logger.info(
            "Correo enviado a %s vía %s:%d (%.1f s)",
            self.to,
            self.smtp.host,
            self.smtp.port,
            duration,
        )
        return NotificationResult(
            success=True,
            recipient=self.to,
            duration_seconds=duration,
        )

    def _build_message(self, report: ReportMessage) -> EmailMessage:
        """Construye el ``EmailMessage`` con el envelope de la configuración."""
        message = EmailMessage()
        message["From"] = self.from_
        message["To"] = self.to
        message["Subject"] = report.subject
        message.set_content(report.body)
        return message

    def _connect(self) -> smtplib.SMTP:
        """Abre la conexión SMTP según el transporte configurado.

        El valor de retorno se tipa como ``SMTP``: ``SMTP_SSL`` deriva de él,
        así que ambos transportes comparten la superficie usada acá
        (``starttls``/``login``/``send_message``/``quit``).
        """
        smtp = self.smtp
        logger.info(
            "Conectando a %s:%d (%s)",
            smtp.host,
            smtp.port,
            "SSL implícito" if smtp.ssl else ("STARTTLS" if smtp.starttls else "sin cifrar"),
        )
        if smtp.ssl:
            return smtplib.SMTP_SSL(smtp.host, smtp.port, timeout=self.timeout)
        server = smtplib.SMTP(smtp.host, smtp.port, timeout=self.timeout)
        if smtp.starttls:
            server.ehlo()
            server.starttls()
            server.ehlo()
        return server

    @staticmethod
    def _close(server: smtplib.SMTP) -> None:
        """Cierra la conexión sin dejar que un fallo de cierre oculte el envío."""
        try:
            server.quit()
        except (smtplib.SMTPException, OSError) as exc:
            logger.warning("No se pudo cerrar la conexión SMTP: %s", exc)

    def _failure(self, start_time: float, exc: Exception) -> NotificationResult:
        """Construye y registra un ``NotificationResult`` fallido."""
        duration = time.perf_counter() - start_time
        message = (
            f"fallo al enviar el correo a {self.to} vía {self.smtp.host}:"
            f"{self.smtp.port}: {type(exc).__name__}: {exc}"
        )
        logger.error("%s", message)
        return NotificationResult(
            success=False,
            recipient=self.to,
            duration_seconds=duration,
            error_message=message,
        )


def _global_status(batch: BatchBackupResult) -> str:
    """Deriva el estado global del lote final del pipeline.

    ÉXITO si todas las bases completaron las tres fases; PARCIAL si hubo
    mezcla; FALLO si fallaron todas, el lote no se ejecutó
    (``error_message``) o no hay resultados.
    """
    if batch.error_message is not None or not batch.results:
        return STATUS_FAILURE
    succeeded = sum(result.success for result in batch.results)
    if succeeded == len(batch.results):
        return STATUS_SUCCESS
    if succeeded:
        return STATUS_PARTIAL
    return STATUS_FAILURE


def _base_section(pipeline: PipelineResult) -> list[str]:
    """Detalle por base: respaldo, compresión, transferencia y fase fallida."""
    lines = ["Bases:"]
    for result in pipeline.backup.results:
        state = "OK" if result.success else "FALLO"
        lines.append(f"- {result.database_name}: {state}")
        if result.backup_path is not None:
            lines.append(
                f"    respaldo: {result.backup_path} "
                f"({result.file_size_bytes} bytes, {result.duration_seconds:.1f} s)"
            )
        if result.error_message is not None:
            lines.append(f"    error de respaldo: {result.error_message}")
        if result.archive_path is not None:
            lines.append(
                f"    compresión: {result.archive_path} "
                f"({result.compressed_size_bytes} bytes, "
                f"{result.compression_duration_seconds:.1f} s)"
            )
        if result.compression_error_message is not None:
            lines.append(f"    error de compresión: {result.compression_error_message}")
        if result.transfer_error_message is not None:
            lines.append(f"    error de transferencia: {result.transfer_error_message}")
        elif result.success and result.archive_path is not None:
            batch_transfer = pipeline.transfers.get(result.database_name)
            if batch_transfer is None:
                lines.append("    transferencia: no aplica (sin servidores)")
            else:
                ok = sum(item.success for item in batch_transfer.results)
                lines.append(
                    f"    transferencia: {ok}/{len(batch_transfer.results)} destino(s) OK"
                )
    return lines


def _server_section(config: Config, pipeline: PipelineResult) -> list[str]:
    """Detalle por servidor destino de cada base transferida."""
    if not config.servers:
        return ["Servidores destino: ninguno configurado."]
    if not pipeline.transfers:
        return ["Servidores destino: sin transferencias en esta ejecución."]
    lines = ["Servidores destino:"]
    for database_name, batch_transfer in pipeline.transfers.items():
        for result in batch_transfer.results:
            if result.success:
                lines.append(
                    f"- {database_name} → {result.server_name}: OK {result.remote_path} "
                    f"({result.transferred_bytes} bytes, {result.duration_seconds:.1f} s)"
                )
            else:
                lines.append(
                    f"- {database_name} → {result.server_name}: FALLO "
                    f"({result.error_message or 'fallo sin detalle'})"
                )
    return lines


def _totals_line(pipeline: PipelineResult) -> str:
    """Línea de totales: bases, duración acumulada y destinos."""
    batch = pipeline.backup
    succeeded = sum(result.success for result in batch.results)
    server_results = [item for transfer in pipeline.transfers.values() for item in transfer.results]
    servers_ok = sum(item.success for item in server_results)
    transfer_duration = sum(
        transfer.total_duration_seconds for transfer in pipeline.transfers.values()
    )
    return (
        f"Totales: {succeeded}/{len(batch.results)} base(s) OK; "
        f"respaldo + compresión {batch.total_duration_seconds:.1f} s; "
        f"transferencia {transfer_duration:.1f} s; "
        f"destinos {servers_ok}/{len(server_results)} OK."
    )


def render_report(
    config: Config,
    pipeline: PipelineResult,
    *,
    log_tail: Sequence[str] = (),
    now: datetime | None = None,
    hostname: str | None = None,
) -> ReportMessage:
    """Construye el informe de ejecución sin tocar la red (Item 040).

    Deriva el estado global del ``BatchBackupResult`` final (ÉXITO/PARCIAL/
    FALLO), detalla cada base (respaldo, compresión y el error de la fase que
    falló), cada servidor destino y los totales. Si ``log_tail`` trae líneas
    capturadas (Item 041), las agrega al final bajo "Últimas líneas del log".
    ``now`` y ``hostname`` son inyectables para tests deterministas.

    El asunto y el cuerpo finales pasan por ``SecretMasker.from_config`` como
    segunda barrera de enmascarado. El correo es solo texto: nunca adjunta el
    backup ni incluye credenciales.
    """
    batch = pipeline.backup
    status = _global_status(batch)
    moment = now if now is not None else datetime.now()
    host = hostname if hostname is not None else socket.gethostname()
    subject = f"[ODIN] {status} — respaldo de {host} ({moment.strftime(_TIMESTAMP_FORMAT)})"

    lines = [
        f"Estado global: {status}",
        f"Host: {host}",
        f"Fecha: {moment.strftime(_TIMESTAMP_FORMAT)}",
        "",
    ]
    if batch.error_message is not None:
        lines.append(f"Respaldo no ejecutado: {batch.error_message}")
    elif not batch.results:
        lines.append("No hay bases configuradas: nada que respaldar.")
    else:
        lines.extend(_base_section(pipeline))
        lines.append("")
        lines.extend(_server_section(config, pipeline))
        lines.append("")
        lines.append(_totals_line(pipeline))
    if log_tail:
        lines.append("")
        lines.append(f"Últimas líneas del log ({len(log_tail)}):")
        lines.extend(log_tail)

    masker = SecretMasker.from_config(config)
    return ReportMessage(subject=masker.mask(subject), body=masker.mask("\n".join(lines)))

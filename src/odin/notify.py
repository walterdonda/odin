"""Notificación por correo del informe de ejecución (Items 039, 040 y 079).

Cliente SMTP sobre ``smtplib`` (solo stdlib) que envía el informe a
``notification.to`` desde ``notification.from_`` usando ``notification.smtp``:
STARTTLS por defecto, modo plano para relays locales (``starttls: false``) y
SSL implícito para el puerto 465 (``smtp.ssl: true``, mutuamente excluyente con
STARTTLS y validado en ``config.py``). Los timeouts de conexión/operación son
parametrizables con ``DEFAULT_SMTP_TIMEOUT_SEC`` (30 s); no se exponen en el
JSON para no sumar superficie de configuración.

El mensaje es **multipart** (Item 079): ``text/plain`` y ``text/html`` en
UTF-8 explícito con cabecera ``Content-Language: es-419``. Asunto, cuerpos y
firma se construyen desde las plantillas opcionales del JSON
(``notification.subject``/``body_text``/``body_html``/``signature``) con
placeholders ``{clave}`` de whitelist (``odin.config.TEMPLATE_KEYS``); si el
campo falta se usa el contenido integrado.

``NotificationResult`` documenta el desenlace: los errores operativos
esperados (``SMTPException``, ``OSError``, ``socket.timeout`` y sus
subclases como ``ConnectionRefusedError``) **no** se propagan — se reportan en
el resultado y se loguean sin exponer credenciales, de modo que un SMTP caído
no tumba el pipeline (Item 043).

``render_report`` construye el asunto y los cuerpos desde el
``PipelineResult`` + ``Config`` (+ contexto del job del scheduler, opcional)
sin tocar la red. El texto pasa por ``SecretMasker`` como segunda barrera de
enmascarado: el correo nunca incluye credenciales ni adjunta el backup.
"""

from __future__ import annotations

import html
import re
import smtplib
import socket
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from typing import TYPE_CHECKING

from odin.config import Config, SchedulerJob, SmtpConfig
from odin.cron_phrase import humanize_cron
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
    "render_template",
]

DEFAULT_SMTP_TIMEOUT_SEC = 30

STATUS_SUCCESS = "ÉXITO"
STATUS_PARTIAL = "PARCIAL"
STATUS_FAILURE = "FALLO"

_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

# Un placeholder que quedó sin reemplazar después del render (defensa: la
# validación de configuración ya rechaza las claves desconocidas).
_LEFTOVER_PLACEHOLDER_RE = re.compile(r"\{[^{}]*\}")


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
    """Informe renderizado listo para enviar: asunto y cuerpos (texto + HTML).

    ``body_html`` es opcional; cuando está presente el correo sale multipart
    (``text/plain`` + ``text/html``), y ``None`` mantiene solo texto plano.
    """

    subject: str
    body_text: str
    body_html: str | None = None


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

        El cuerpo va como ``text/plain`` + ``text/html`` (multipart, UTF-8) y
        no se adjunta el backup. El cierre de la conexión es best-effort: un
        fallo al cerrar no convierte un envío exitoso en fallo.
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
        """Construye el ``EmailMessage`` multipart con el envelope de la configuración.

        Ambas partes van en UTF-8 explícito y el mensaje declara el idioma con
        ``Content-Language: es-419`` (español latinoamericano, Item 079). La
        cabecera se asigna **después** de ``set_content``/``add_alternative``:
        en Python 3.14 esas llamadas limpian la cabecera si se fijó antes.
        """
        message = EmailMessage()
        message["From"] = self.from_
        message["To"] = self.to
        message["Subject"] = report.subject
        message.set_content(report.body_text, subtype="plain", charset="utf-8")
        if report.body_html is not None:
            message.add_alternative(report.body_html, subtype="html", charset="utf-8")
        message["Content-Language"] = "es-419"
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


def render_template(template: str, values: Mapping[str, str]) -> str:
    """Rellena los placeholders ``{clave}`` de ``template`` con ``values``.

    Reemplazo literal por whitelist (nada de ``str.format``): los valores pueden
    contener llaves sin riesgo de interpolación y las claves desconocidas no
    pueden escapar a atributos. Un placeholder del ``template`` que no esté en
    ``values`` lanza ``ValueError``: la validación de configuración
    (``odin.config``) ya rechaza las claves desconocidas, así que acá es una
    defensa de programación.
    """
    for match in _LEFTOVER_PLACEHOLDER_RE.finditer(template):
        key = match.group(0)[1:-1]
        if key not in values:
            raise ValueError(f"placeholder sin valor: '{match.group(0)}'")
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", value)
    return rendered


def _instances_phrase(names: Sequence[str]) -> str:
    """Nombres de las instancias de la corrida, truncando a 3 con `` +N``."""
    if not names:
        return ""
    if len(names) <= 3:
        return ", ".join(names)
    return ", ".join(names[:3]) + f" +{len(names) - 3}"


def _default_signature(client: str, entorno: str, contact: str | None) -> str:
    """Firma integrada: ``ODIN · {cliente}-{entorno}`` + línea de contacto."""
    if client and entorno:
        label = f"ODIN · {client}-{entorno}"
    elif client:
        label = f"ODIN · {client}"
    else:
        label = "ODIN"
    lines = [label]
    if contact:
        lines.append(f"Contacto: {contact}")
    return "\n".join(lines)


def _log_section(log_tail: Sequence[str]) -> str:
    """Sección de cola de log para las plantillas (vacía sin líneas)."""
    if not log_tail:
        return ""
    return f"Últimas líneas del log ({len(log_tail)}):\n" + "\n".join(log_tail)


def render_report(
    config: Config,
    pipeline: PipelineResult,
    *,
    log_tail: Sequence[str] = (),
    now: datetime | None = None,
    hostname: str | None = None,
    job: SchedulerJob | None = None,
) -> ReportMessage:
    """Construye el informe de ejecución sin tocar la red (Items 040 y 079).

    Deriva el estado global del ``BatchBackupResult`` final (ÉXITO/PARCIAL/
    FALLO), detalla cada base (respaldo, compresión y el error de la fase que
    falló), cada servidor destino y los totales. Si ``log_tail`` trae líneas
    capturadas (Item 041), las agrega bajo "Últimas líneas del log".
    ``now``, ``hostname`` y ``job`` son inyectables para tests deterministas:
    ``job`` es el ``SchedulerJob`` del scheduler que disparó el ciclo (Item
    079) —con él el ``{horario}`` sale legible y con su timezone—; en corridas
    manuales (``None``) el horario es "manual".

    Asunto, cuerpos y firma salen de las plantillas opcionales del JSON
    (``notification.subject``/``body_text``/``body_html``/``signature``) o del
    contenido integrado; la firma se aplica siempre, en ambas partes. El
    asunto y los cuerpos finales pasan por ``SecretMasker.from_config`` como
    segunda barrera de enmascarado. El correo nunca adjunta el backup ni
    incluye credenciales.
    """
    batch = pipeline.backup
    status = _global_status(batch)
    moment = now if now is not None else datetime.now()
    host = hostname if hostname is not None else socket.gethostname()
    environment = config.environment
    client = environment.client if environment is not None else ""
    entorno = environment.name if environment is not None else ""

    instance_names = [result.database_name for result in batch.results]
    if not instance_names:
        instance_names = [database.name for database in config.databases]
    instancia = _instances_phrase(instance_names)

    engines = list(dict.fromkeys(database.type.value for database in config.databases))
    motor = ", ".join(engines)

    if job is not None:
        horario = humanize_cron(job.schedule, config.scheduler.timezone)
        zona_horaria = config.scheduler.timezone
    else:
        horario = "manual"
        zona_horaria = ""

    bases_text = "\n".join(_base_section(pipeline))
    servers_text = "\n".join(_server_section(config, pipeline))
    totals_text = _totals_line(pipeline)
    log_text = _log_section(log_tail)
    contact = config.notification.contact or ""

    values = {
        "cliente": client,
        "entorno": entorno,
        "instancia": instancia,
        "motor": motor,
        "estado": status,
        "horario": horario,
        "zona_horaria": zona_horaria,
        "host": host,
        "fecha": moment.strftime(_TIMESTAMP_FORMAT),
        "contacto": contact,
        "log": log_text,
        "bases": bases_text,
        "servidores": servers_text,
        "totales": totals_text,
    }

    notification = config.notification
    signature = (
        render_template(notification.signature, values)
        if notification.signature is not None
        else _default_signature(client, entorno, contact)
    )

    if notification.subject is not None:
        subject = render_template(notification.subject, values)
    elif environment is not None:
        subject = (
            f"[ODIN] [{client}-{entorno}] {status} — respaldo de {instancia} "
            f"({moment.strftime(_TIMESTAMP_FORMAT)})"
        )
    else:
        subject = (
            f"[ODIN] {status} — respaldo de {instancia} "
            f"({moment.strftime(_TIMESTAMP_FORMAT)})"
        )

    if notification.body_text is None:
        body_text = _default_body_text(values, signature, batch, pipeline, config, log_tail)
    else:
        body_text = render_template(notification.body_text, values) + _signature_block(signature)
    if notification.body_html is None:
        body_html = _default_body_html(values, signature, batch, pipeline, config, log_tail)
    else:
        escaped_values = {key: html.escape(value) for key, value in values.items()}
        body_html = (
            render_template(notification.body_html, escaped_values)
            + f"<p>--</p><pre>{html.escape(signature)}</pre>"
        )

    masker = SecretMasker.from_config(config)
    return ReportMessage(
        subject=masker.mask(subject),
        body_text=masker.mask(body_text),
        body_html=masker.mask(body_html),
    )


def _signature_block(signature: str) -> str:
    """Firma para texto plano: separador ``--`` + líneas de la firma."""
    return f"\n\n--\n{signature}"


def _default_body_text(
    values: Mapping[str, str],
    signature: str,
    batch: BatchBackupResult,
    pipeline: PipelineResult,
    config: Config,
    log_tail: Sequence[str],
) -> str:
    """Cuerpo texto integrado: cabecera, secciones y firma (Items 040 y 079)."""
    header = [
        f"Estado global: {values['estado']}",
        f"Host: {values['host']}",
        f"Fecha: {values['fecha']}",
    ]
    if values["horario"] != "manual":
        header.append(f"Horario: {values['horario']}")
    if values["cliente"]:
        header.append(f"Cliente: {values['cliente']} · Entorno: {values['entorno']}")
    lines = [*header, ""]
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
        lines.append(values["log"])
    lines.append("")
    lines.append("--")
    lines.extend(signature.splitlines())
    return "\n".join(lines)


def _default_body_html(
    values: Mapping[str, str],
    signature: str,
    batch: BatchBackupResult,
    pipeline: PipelineResult,
    config: Config,
    log_tail: Sequence[str],
) -> str:
    """Cuerpo HTML integrado: resumen, secciones en ``<pre>`` y firma (Item 079)."""
    esc = html.escape
    items = [
        f"<li>Host: {esc(values['host'])}</li>",
        f"<li>Fecha: {esc(values['fecha'])}</li>",
    ]
    if values["horario"] != "manual":
        items.append(f"<li>Horario: {esc(values['horario'])}</li>")
    if values["cliente"]:
        items.append(
            f"<li>Cliente: {esc(values['cliente'])} · Entorno: {esc(values['entorno'])}</li>"
        )
    lines = [
        "<html><head><meta charset=\"utf-8\"></head><body>",
        f"<h3>Estado global: {esc(values['estado'])}</h3>",
        "<ul>",
        *items,
        "</ul>",
    ]
    if batch.error_message is not None:
        lines.append(f"<pre>{esc(batch.error_message)}</pre>")
    elif not batch.results:
        lines.append("<pre>No hay bases configuradas: nada que respaldar.</pre>")
    else:
        sections = [values["bases"], values["servidores"], values["totales"]]
        detail = "\n\n".join(section for section in sections if section)
        lines.append(f"<pre>{esc(detail)}</pre>")
    if log_tail:
        lines.append(f"<pre>{esc(values['log'])}</pre>")
    lines.append(f"<p>--</p><pre>{esc(signature)}</pre>")
    lines.append("</body></html>")
    return "\n".join(lines)

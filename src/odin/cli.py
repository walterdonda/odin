"""Interfaz de línea de comandos de ODIN (Items 005, 006, 013, 019 y 053).

Subcomando ``validate``: carga y valida el JSON de configuración
(``odin.config.load_config``, Item 002), ejecuta la validación completa del
entorno local y de coherencia (``odin.validate.validate_config``, Item 006),
imprime el reporte con severidades (errores y advertencias diferenciados) y
registra el resultado en consola y archivo con secretos enmascarados
(``odin.log.setup_logging``, Item 004). Con ``--strict`` las advertencias
también fallan (exit code 2), útil como gate de despliegue o de CI.

Subcomando ``run``: ejecuta el pipeline completo (``odin.pipeline``, Items 035
y 043): respaldo (``odin.backup.BackupExecutor``), compresión 7z
(``odin.compress.CompressionExecutor``), transferencia SFTP
(``odin.transfer.TransferExecutor``) y notificación por correo
(``odin.notify.EmailNotifier``) sobre todas las bases de la configuración, de
forma secuencial y con aislamiento de fallos por base y por servidor. Una
base cuenta como exitosa solo si el respaldo, la compresión y la transferencia
a todos los servidores culminan bien (Items 025 y 035). El informe se envía
**siempre** (éxito, parcial o fallo); un SMTP caído no crashea: queda en el
log y en el resumen, y degrada el exit code 0 a 1. Después del correo corre la
retención local (``odin.retention.RetentionExecutor``, Item 046): es una
función secundaria cuyos errores se reportan pero no alteran el exit code.

Subcomando ``service`` (Items 053, 055, 062 y 065): ``run`` arranca el scheduler
interno en primer plano delegando en el runner compartido del modo servicio
(``odin.service.runner.ServiceRunner``, el mismo que usan la unit systemd y el
``SvcDoRun`` de Windows) con el estado consultable en
``local.work_dir/scheduler_state.json``; ``SIGINT``/``SIGTERM`` detienen limpio
(shutdown + estado final) con exit 0. ``status`` lee ese estado
y presenta última ejecución, próximo disparo, salud y errores recientes; es una
consulta: devuelve 0 mientras la lectura sea posible, con aviso si el proceso
ya no corre o no hay estado. ``reload`` pide la recarga en caliente de la
configuración: en POSIX envía ``SIGUSR1`` al pid del estado (el servicio lo
procesa con el job ``reload-watcher``, valida la config nueva y conserva la
vigente si es inválida) y sin señales (Windows) crea el archivo de control
``local.work_dir/scheduler_reload.request`` que el servicio consume; devuelve 1
si no hay servicio en ejecución.

El modo residente del SO (Items 060-062) se controla con ``install`` —
exige ``--config``/``ODIN_CONFIG``, carga y valida la configuración (errores →
2, sin instalar) e instala el servicio en systemd/SCM; en Linux sin permisos
devuelve la guía para completar la instalación a mano —, ``uninstall``,
``start`` y ``stop`` — operan por nombre fijo ``odin`` con ``--config``
opcional y devuelven 0, o 1 si el gestor falla (``ServiceError``, plataforma
no soportada) —.

Convención de exit codes (constantes exportadas de este módulo):

- ``EXIT_OK`` (0): operación exitosa (configuración válida, aunque tenga
  advertencias salvo con ``--strict``; respaldo, compresión y transferencia
  de todas las bases exitosos **y correo enviado**).
- ``EXIT_INTERNAL`` (1): error interno inesperado (bug, fallo de I/O no
  controlado); se imprime mensaje + traceback en stderr sin morir con una
  excepción sin manejar. Incluye el fallo de notificación en una corrida por
  lo demás exitosa: una ejecución sin correo incumple el contrato de
  trazabilidad (visión C2/C4), así que no puede devolver 0.
- ``EXIT_CONFIG`` (2): error de configuración (archivo ilegible/inexistente,
  JSON malformado, problema estructural o semántico, verificación de entorno
  fallida, falta la ruta de config) o de uso de la CLI (errores de argparse,
  p. ej. subcomando inexistente).
- ``EXIT_PARTIAL`` (3): algunas bases completaron todas las fases y otras
  fallaron (en cualquiera de las fases: respaldo, compresión o transferencia).
  Un fallo de notificación no cambia este código: el correo sí salió.
- ``EXIT_FAILURE`` (4): el pipeline falló por completo (ninguna base completó
  todas las fases; p. ej. gbak no encontrado o ``work_dir`` no creable) o el
  lote no se ejecutó / quedó vacío. Tiene precedencia sobre el correo.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import sys
import traceback
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from logging import Logger
from pathlib import Path

from odin import __version__
from odin.backup import BatchBackupResult
from odin.config import Config, ConfigError, load_config
from odin.log import SecretMasker, setup_logging
from odin.notify import NotificationResult
from odin.pipeline import PipelineResult, run_pipeline
from odin.retention import RetentionResult
from odin.scheduler import (
    SchedulerService,
    SchedulerStateStore,
    load_state,
    reload_request_path,
    render_service_status,
    state_path,
)
from odin.service import (
    ServiceError,
    ServiceManager,
    ServiceManagerKind,
    ServiceSpec,
    ServiceStatus,
    create_service_manager,
    render_platform_status,
)
from odin.service.runner import ServiceRunner, build_scheduler_service
from odin.validate import (
    Severity,
    ValidationReport,
    render_stderr,
    render_stdout,
    report_from_config_error,
    validate_config,
)

__all__ = [
    "ENV_CONFIG_VAR",
    "EXIT_CONFIG",
    "EXIT_FAILURE",
    "EXIT_INTERNAL",
    "EXIT_OK",
    "EXIT_PARTIAL",
    "build_parser",
    "main",
]

EXIT_OK = 0
EXIT_INTERNAL = 1
EXIT_CONFIG = 2
EXIT_PARTIAL = 3
EXIT_FAILURE = 4
ENV_CONFIG_VAR = "ODIN_CONFIG"

# Recarga en caliente (Item 055): POSIX pide la recarga con SIGUSR1; las
# plataformas sin señal (Windows) dejan un archivo de control. La constante es
# inyectable en tests para cubrir ambas ramas en cualquier SO.
_RELOAD_VIA_SIGNAL = sys.platform != "win32" and hasattr(signal, "SIGUSR1")
# ``signal.SIGUSR1`` no existe en Windows y mypy corriendo sobre un host win32
# marca el acceso directo como attr-defined: se resuelve una sola vez con
# ``getattr`` y la rama de señal queda guardada además por ``_RELOAD_VIA_SIGNAL``
# (los tests de esa rama se saltan donde no hay SIGUSR1).
_RELOAD_SIGNAL: signal.Signals | None = getattr(signal, "SIGUSR1", None)

MaskFn = Callable[[str], str]
ServiceFactory = Callable[..., SchedulerService]
ManagerFactory = Callable[..., ServiceManager]


def _force_utf8_stdio() -> None:
    """Reconfigura ``sys.stdout``/``sys.stderr`` a UTF-8 (tolerante si no se puede).

    En Windows, cuando la salida está redirigida (pipe o archivo: ``odin run >
    resumen.txt``, un scheduler externo que capture la salida), Python usa el
    ANSI codepage (``cp1252``) para los streams y un carácter del resumen como
    ``→`` (U+2192) lanza ``UnicodeEncodeError`` y termina la corrida con exit 1
    aunque el respaldo haya sido exitoso. La consola interactiva (PEP 528) y
    POSIX ya usan UTF-8, así que esto solo uniformiza el caso redirigido: la
    salida pasa a coincidir con Linux, con ``odin.log`` (UTF-8) y con el
    default de Python 3.15 (PEP 686). Streams sin ``reconfigure`` (p. ej. el
    writer del servicio en ``redirect_stdio_to_log``, ya UTF-8) o cerrados se
    dejan como están.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            continue


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser raíz de la CLI de ODIN.

    Subcomandos registrados hoy: ``validate``, ``run`` — este último orquesta el
    pipeline completo de las Etapas 2-5 (respaldo, compresión, transferencia,
    correo y retención local) en ``odin.pipeline`` — y ``service`` (Items 053,
    055 y 062) con las acciones ``run`` (scheduler en primer plano), ``status``
    (consulta del estado en ``work_dir``), ``reload`` (recarga en caliente) e
    ``install``/``uninstall``/``start``/``stop`` (ciclo de vida del modo
    residente del SO sobre los gestores de ``odin.service``).
    """
    parser = argparse.ArgumentParser(
        prog="odin",
        description="Respaldo externo de bases de datos Firebird: gbak + 7z + SFTP + correo.",
    )
    parser.add_argument("--version", action="version", version=f"odin {__version__}")
    subparsers = parser.add_subparsers(dest="command", title="subcomandos")
    validate_parser = subparsers.add_parser(
        "validate",
        help="Valida el JSON de configuración.",
        description=(
            "Carga y valida el JSON de configuración de ODIN (estructura, semántica, rutas "
            "locales y coherencia), configura el logging y registra el resultado."
        ),
    )
    validate_parser.add_argument(
        "--config",
        metavar="RUTA",
        default=None,
        help=f"ruta al JSON de configuración; si se omite, usa la variable {ENV_CONFIG_VAR}.",
    )
    validate_parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "trata las advertencias como errores (exit code 2); "
            "útil como gate previo al despliegue."
        ),
    )
    run_parser = subparsers.add_parser(
        "run",
        help=(
            "Ejecuta respaldo (gbak), compresión 7z, transferencia SFTP, "
            "el correo y la retención."
        ),
        description=(
            "Ejecuta el pipeline completo de cada base de la configuración: respaldo "
            "(gbak -b), compresión 7z, transferencia SFTP del .fbk.7z a todos los "
            "servidores configurados y envío del informe por correo, de forma "
            "secuencial y con aislamiento de fallos por base y por servidor. Los "
            "artefactos se guardan en local.work_dir como <nombre>_<timestamp>.fbk y "
            "su .fbk.7z. Una base cuenta como exitosa solo si el respaldo, la "
            "compresión y la transferencia culminan bien; el correo se envía siempre "
            "y un fallo de notificación en una corrida por lo demás exitosa devuelve "
            "exit code 1 (matriz completa: 0/1/3/4). Al final se aplica la retención "
            "local (local.retention_days); sus errores no alteran el exit code."
        ),
    )
    run_parser.add_argument(
        "--config",
        metavar="RUTA",
        default=None,
        help=f"ruta al JSON de configuración; si se omite, usa la variable {ENV_CONFIG_VAR}.",
    )
    service_parser = subparsers.add_parser(
        "service",
        help="Ejecuta el scheduler en primer plano o administra el servicio del SO.",
        description=(
            "Modo servicio del scheduler interno: 'run' ejecuta el scheduler en primer "
            "plano (hasta SIGINT/SIGTERM) con las políticas de solapamiento y misfire "
            "del bloque scheduler del JSON, y 'status' consulta el estado persistido en "
            "local.work_dir/scheduler_state.json (última ejecución, próximo disparo, "
            "salud y errores recientes). 'install'/'uninstall'/'start'/'stop' "
            "administran el servicio residente del SO (systemd en Linux, SCM en "
            "Windows) para que el scheduler corra desatendido."
        ),
    )
    service_actions = service_parser.add_subparsers(dest="service_action", title="acciones")
    service_run_parser = service_actions.add_parser(
        "run",
        help="Ejecuta el scheduler en primer plano hasta SIGINT/SIGTERM.",
        description=(
            "Carga y valida la configuración, configura el logging y arranca el "
            "scheduler bloqueante: cada job dispara el pipeline completo por el "
            "subconjunto de bases configurado y cada ciclo envía su propio informe. "
            "SIGINT/SIGTERM detienen el servicio limpiamente (shutdown del scheduler y "
            "escritura final del estado) con exit code 0; una configuración inválida "
            "devuelve 2 y un error interno 1. Requiere scheduler.enabled: true."
        ),
    )
    service_run_parser.add_argument(
        "--config",
        metavar="RUTA",
        default=None,
        help=f"ruta al JSON de configuración; si se omite, usa la variable {ENV_CONFIG_VAR}.",
    )
    service_status_parser = service_actions.add_parser(
        "status",
        help="Consulta el estado del servicio (scheduler_state.json).",
        description=(
            "Lee local.work_dir/scheduler_state.json y presenta si el servicio corre "
            "(o quedó un estado obsoleto de un proceso muerto), la configuración, cada "
            "job con su próximo disparo y último ciclo, la salud y los errores "
            "recientes. Sin estado o con el archivo ilegible informa el motivo sin "
            "fallar."
        ),
    )
    service_status_parser.add_argument(
        "--config",
        metavar="RUTA",
        default=None,
        help=f"ruta al JSON de configuración; si se omite, usa la variable {ENV_CONFIG_VAR}.",
    )
    service_reload_parser = service_actions.add_parser(
        "reload",
        help="Solicita la recarga en caliente de la configuración al servicio.",
        description=(
            "Solicita al servicio en primer plano que recargue la configuración sin "
            "reiniciar: en POSIX envía SIGUSR1 al pid del estado y sin señales (Windows) "
            "crea local.work_dir/scheduler_reload.request, que el servicio consume. La "
            "configuración nueva se valida antes de aplicarse; si es inválida el servicio "
            "mantiene la vigente y registra el motivo. Devuelve 0 cuando la solicitud se "
            "entrega, 1 cuando no hay servicio en ejecución y 2 si la configuración no "
            "puede cargarse."
        ),
    )
    service_reload_parser.add_argument(
        "--config",
        metavar="RUTA",
        default=None,
        help=f"ruta al JSON de configuración; si se omite, usa la variable {ENV_CONFIG_VAR}.",
    )
    service_install_parser = service_actions.add_parser(
        "install",
        help="Instala el servicio residente del SO (systemd/SCM).",
        description=(
            "Instala (o reemplaza) el servicio residente del SO para que el scheduler "
            "corra desatendido: systemd en Linux, SCM en Windows. Exige --config o "
            "ODIN_CONFIG con una configuración cargable y sin errores de validación "
            "(errores → exit code 2, sin instalar). En Linux sin permisos no escribe "
            "nada y devuelve la guía con la unit y los comandos a ejecutar con sudo."
        ),
    )
    service_install_parser.add_argument(
        "--config",
        metavar="RUTA",
        default=None,
        help=f"ruta al JSON de configuración; si se omite, usa la variable {ENV_CONFIG_VAR}.",
    )
    service_uninstall_parser = service_actions.add_parser(
        "uninstall",
        help="Desinstala el servicio residente del SO (idempotente).",
        description=(
            "Detiene, deshabilita y elimina el servicio residente del SO. Es idempotente: "
            "una segunda invocación informa que no estaba instalado. Opera por nombre "
            "fijo 'odin'; --config solo se usa para construir el gestor."
        ),
    )
    service_uninstall_parser.add_argument(
        "--config",
        metavar="RUTA",
        default=None,
        help=f"ruta al JSON de configuración; si se omite, usa la variable {ENV_CONFIG_VAR}.",
    )
    service_start_parser = service_actions.add_parser(
        "start",
        help="Arranca el servicio residente del SO.",
        description=(
            "Arranca el servicio residente del SO y espera su transición a 'en "
            "ejecución'. Opera por nombre fijo 'odin'; --config solo se usa para "
            "construir el gestor. Un fallo del gestor devuelve exit code 1."
        ),
    )
    service_start_parser.add_argument(
        "--config",
        metavar="RUTA",
        default=None,
        help=f"ruta al JSON de configuración; si se omite, usa la variable {ENV_CONFIG_VAR}.",
    )
    service_stop_parser = service_actions.add_parser(
        "stop",
        help="Detiene el servicio residente del SO.",
        description=(
            "Detiene el servicio residente del SO y espera su transición a 'detenido'. "
            "Opera por nombre fijo 'odin'; --config solo se usa para construir el "
            "gestor. Un fallo del gestor devuelve exit code 1."
        ),
    )
    service_stop_parser.add_argument(
        "--config",
        metavar="RUTA",
        default=None,
        help=f"ruta al JSON de configuración; si se omite, usa la variable {ENV_CONFIG_VAR}.",
    )
    return parser


def _resolve_config_source(args: argparse.Namespace) -> str | None:
    """Ruta de configuración: ``--config`` (precedencia) o ``ODIN_CONFIG``.

    Devuelve ``None`` si ninguna vía aporta un valor; los valores vacíos o en
    blanco se tratan como ausentes (el mensaje de error resultante es más
    claro que intentar abrir una ruta sin sentido).
    """
    raw: str | None = args.config or os.environ.get(ENV_CONFIG_VAR)
    if raw is None or not raw.strip():
        return None
    return raw


def _load_config_or_report(source: str | None) -> Config | None:
    """Carga la configuración de ``source`` o imprime el motivo y devuelve ``None``.

    Unifica la resolución ``--config``/``ODIN_CONFIG`` de ``validate``/``run``
    con la de ``service``: ``None`` (falta la fuente) y ``ConfigError`` se
    reportan en stderr y el llamador traduce a ``EXIT_CONFIG``.
    """
    if source is None:
        print(
            "No se indicó el archivo de configuración: use --config <ruta> "
            f"o defina la variable de entorno {ENV_CONFIG_VAR}.",
            file=sys.stderr,
        )
        return None
    try:
        return load_config(source)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return None


def _setup_logging_or_warn(config: Config) -> Logger | None:
    """Configura el logging; si el destino no es operable, advierte y sigue.

    Postura (criterio 6 del Item 005): un fallo operativo de logging (p. ej.
    ``OSError`` porque el directorio de logs no es creable) no invalida la
    configuración — ``validate`` igualmente devuelve ``EXIT_OK`` con una
    advertencia en stderr. Solo se captura ``OSError``: cualquier otra
    excepción es un error interno (``EXIT_INTERNAL`` vía ``main``).
    """
    try:
        return setup_logging(config)
    except OSError as exc:
        print(
            f"Advertencia: no se pudo configurar el logging ({exc}); "
            "la configuración es válida pero esta ejecución no quedará registrada.",
            file=sys.stderr,
        )
        return None


def _print_report(report: ValidationReport, *, strict: bool) -> None:
    """Imprime el reporte: contexto a stdout, errores y veredicto inválido a stderr."""
    stdout = render_stdout(report, strict=strict)
    if stdout:
        print(stdout)
    stderr = render_stderr(report, strict=strict)
    if stderr:
        print(stderr, file=sys.stderr)


def _log_report(report: ValidationReport, logger: Logger) -> None:
    """Registra el resultado en el log: resumen + cada hallazgo ERROR/WARNING.

    El reporte detallado no se duplica acá (ya salió por stdout/stderr); los
    hallazgos bloqueantes y las advertencias sí, para que queden en el archivo
    rotado cuando no hay consola (modo servicio, Etapa 7). La ruta de
    ``private_key`` puede aparecer como ``***`` en el log porque
    ``Config.iter_secret_fields`` la lista entre los secretos (postura
    conservadora del Item 004, ver Decisions & Trade-offs del Item 006).
    """
    errors = report.count(Severity.ERROR)
    warnings = report.count(Severity.WARNING)
    resumen = f"{report.summary} | errores: {errors} | advertencias: {warnings}"
    if errors:
        logger.error("Configuración inválida: %s (%s)", report.config_path, resumen)
    elif warnings:
        logger.warning(
            "Configuración válida con advertencias: %s (%s)", report.config_path, resumen
        )
    else:
        logger.info("Configuración válida: %s (%s)", report.config_path, resumen)
    for finding in report.errors:
        logger.error("%s: %s", finding.field_path, finding.message)
    for finding in report.warnings:
        logger.warning("%s: %s", finding.field_path, finding.message)


def _cmd_validate(args: argparse.Namespace) -> int:
    """Ejecuta ``odin validate`` y devuelve el exit code.

    Orden obligatorio: ``validate_config`` (solo lectura) corre **antes** que
    ``setup_logging``, cuyo ``mkdir`` del directorio de logs crearía
    ``work_dir`` y enmascararía el hallazgo de "directorio inexistente".
    """
    source = _resolve_config_source(args)
    if source is None:
        print(
            "No se indicó el archivo de configuración: use --config <ruta> "
            f"o defina la variable de entorno {ENV_CONFIG_VAR}.",
            file=sys.stderr,
        )
        return EXIT_CONFIG
    strict = bool(args.strict)
    try:
        config = load_config(source)
    except ConfigError as exc:
        _print_report(report_from_config_error(exc, source), strict=strict)
        return EXIT_CONFIG

    report = validate_config(config)
    logger = _setup_logging_or_warn(config)
    _print_report(report, strict=strict)
    if logger is not None:
        _log_report(report, logger)
    return EXIT_OK if report.is_valid(strict=strict) else EXIT_CONFIG


def _print_backup_summary(batch: BatchBackupResult, *, mask: MaskFn | None = None) -> None:
    """Imprime el resumen del lote: totales a stdout, fallos a stderr.

    Por base exitosa informa ambas fases (Item 026): el ``.fbk`` con tamaño y
    duración del respaldo y el ``.fbk.7z`` con tamaño comprimido y duración de
    la compresión. Los fallos distinguen respaldo y compresión. Con ``mask``
    (Item 038) cada línea impresa pasa por el enmascarador de secretos de la
    configuración, porque los mensajes de error pueden contener indirectamente
    secretos (p. ej. la ruta de la clave privada dentro de una excepción).
    """
    mask = mask or (lambda line: line)
    if batch.error_message is not None:
        print(mask(f"Respaldo no ejecutado: {batch.error_message}"), file=sys.stderr)
        return
    succeeded = sum(result.success for result in batch.results)
    print(
        mask(
            f"Respaldo y compresión finalizados: {succeeded}/{len(batch.results)} base(s) "
            f"con éxito en {batch.total_duration_seconds:.1f} s."
        )
    )
    for result in batch.results:
        if result.success:
            print(
                mask(
                    f"- OK    {result.database_name}: {result.backup_path} "
                    f"({result.file_size_bytes} bytes, {result.duration_seconds:.1f} s) → "
                    f"{result.archive_path} ({result.compressed_size_bytes} bytes, "
                    f"{result.compression_duration_seconds:.1f} s)"
                )
            )
        else:
            if result.compression_error_message is not None:
                detail = f"compresión fallida: {result.compression_error_message}"
                if result.backup_path is not None:
                    detail += (
                        f"; respaldo: {result.backup_path} "
                        f"({result.file_size_bytes} bytes, {result.duration_seconds:.1f} s)"
                    )
            elif result.transfer_error_message is not None:
                detail = f"transferencia fallida: {result.transfer_error_message}"
                if result.archive_path is not None:
                    detail += (
                        f"; artefacto: {result.archive_path} "
                        f"({result.compressed_size_bytes} bytes)"
                    )
            else:
                detail = result.error_message or "fallo sin detalle"
            print(mask(f"- FALLO {result.database_name}: {detail}"), file=sys.stderr)


def _print_transfer_summary(
    pipeline: PipelineResult, *, mask: MaskFn | None = None
) -> None:
    """Imprime el detalle de la fase de transferencia (Item 036).

    Por base transferida, una línea por servidor destino con ruta remota,
    bytes verificados, duración y estado; los fallos van a stderr como en el
    resumen de respaldo/compresión. Sin transferencias no imprime nada. Con
    ``mask`` (Item 038) cada línea pasa por el enmascarador de secretos (los
    ``error_message`` pueden contenerlos indirectamente).
    """
    mask = mask or (lambda line: line)
    transfers = pipeline.transfers
    if not transfers:
        return
    servers_total = sum(len(batch.results) for batch in transfers.values())
    servers_ok = sum(
        result.success for batch in transfers.values() for result in batch.results
    )
    total_duration = sum(batch.total_duration_seconds for batch in transfers.values())
    print(
        mask(
            f"Transferencia SFTP: {servers_ok}/{servers_total} servidor(es) exitosos "
            f"en {total_duration:.1f} s."
        )
    )
    for database_name, batch in transfers.items():
        for result in batch.results:
            if result.success:
                print(
                    mask(
                        f"- {database_name} → {result.server_name}: OK "
                        f"{result.remote_path} ({result.transferred_bytes} bytes, "
                        f"{result.duration_seconds:.1f} s)"
                    )
                )
            else:
                print(
                    mask(
                        f"- {database_name} → {result.server_name}: FALLO "
                        f"({result.error_message or 'fallo sin detalle'})"
                    ),
                    file=sys.stderr,
                )


def _print_notification_summary(
    notification: NotificationResult | None, *, mask: MaskFn | None = None
) -> None:
    """Imprime el resultado de la fase de correo (Item 044).

    Éxito ("Correo enviado a ...") por stdout y fallo ("Correo NO enviado:
    motivo") por stderr, como el resto de los fallos del resumen. Con ``mask``
    cada línea pasa por el enmascarador de secretos: el ``error_message``
    puede contener credenciales SMTP dentro de una excepción.
    """
    mask = mask or (lambda line: line)
    if notification is not None and notification.success:
        print(
            mask(
                f"Correo enviado a {notification.recipient} "
                f"({notification.duration_seconds:.1f} s)."
            )
        )
        return
    detail = (
        notification.error_message
        if notification is not None and notification.error_message
        else "sin resultado de notificación"
    )
    print(mask(f"Correo NO enviado: {detail}"), file=sys.stderr)


def _print_retention_summary(
    retention: RetentionResult | None, *, mask: MaskFn | None = None
) -> None:
    """Imprime el resultado de la limpieza local (Item 046).

    Línea de totales por stdout —"Retención local: N archivo(s) eliminado(s), X
    MB liberados." o la variante deshabilitada— y los errores por archivo por
    stderr, como el resto de los fallos del resumen. Con ``mask`` cada línea
    pasa por el enmascarador de secretos (un error de borrado podría exponer
    una ruta sensible).
    """
    mask = mask or (lambda line: line)
    if retention is None:
        return
    if not retention.enabled:
        print(mask("Retención local: deshabilitada (retention_days=0)."))
    else:
        print(
            mask(
                f"Retención local: {retention.deleted} archivo(s) eliminado(s), "
                f"{retention.freed_bytes / (1024 * 1024):.1f} MB liberados."
            )
        )
    for error in retention.errors:
        print(mask(f"- FALLO retención de {error.path}: {error.message}"), file=sys.stderr)


def _cmd_run(args: argparse.Namespace) -> int:
    """Ejecuta ``odin run``: respaldo + compresión + transferencia + correo + retención.

    El pipeline completo vive en ``odin.pipeline.run_pipeline`` (Items 035,
    043 y 046). Matriz de exit codes (Item 044): ``0`` si todas las bases
    completaron las tres fases **y** el correo se envió; ``1`` si el correo
    falló en una corrida por lo demás exitosa (una ejecución sin informe
    incumple la trazabilidad); ``3`` si hubo mezcla de éxitos y fallos en
    cualquier fase (aunque el correo falle); ``4`` si falló todo, el lote no
    se ejecutó o quedó vacío (tiene precedencia sobre el correo); ``2`` para
    errores de configuración (carga/parseo), igual que en ``validate``. La
    retención local posterior al correo es secundaria: sus errores se
    reportan pero **no** cambian el exit code de la corrida (Item 046).
    """
    source = _resolve_config_source(args)
    if source is None:
        print(
            "No se indicó el archivo de configuración: use --config <ruta> "
            f"o defina la variable de entorno {ENV_CONFIG_VAR}.",
            file=sys.stderr,
        )
        return EXIT_CONFIG
    try:
        config = load_config(source)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return EXIT_CONFIG

    logger = _setup_logging_or_warn(config)

    if logger is not None:
        logger.info(
            "Iniciando respaldo de %d base(s) en %s",
            len(config.databases),
            config.local.work_dir,
        )
    pipeline = run_pipeline(config)
    batch = pipeline.backup
    notification = pipeline.notification
    masker = SecretMasker.from_config(config)
    _print_backup_summary(batch, mask=masker.mask)
    _print_transfer_summary(pipeline, mask=masker.mask)
    _print_notification_summary(notification, mask=masker.mask)
    _print_retention_summary(pipeline.retention, mask=masker.mask)

    succeeded = sum(result.success for result in batch.results)
    if logger is not None:
        if batch.error_message is not None:
            logger.error("Respaldo no ejecutado: %s", batch.error_message)
        else:
            logger.info(
                "Respaldo finalizado: %d/%d base(s) con éxito en %.1f s",
                succeeded,
                len(batch.results),
                batch.total_duration_seconds,
            )
        for database_name, transfer_batch in pipeline.transfers.items():
            ok = sum(result.success for result in transfer_batch.results)
            logger.info(
                "Transferencia de '%s': %d/%d servidor(es) exitosos en %.1f s",
                database_name,
                ok,
                len(transfer_batch.results),
                transfer_batch.total_duration_seconds,
            )
        if notification is not None and notification.success:
            logger.info(
                "Notificación finalizada: correo enviado a %s", notification.recipient
            )
        else:
            detail = (
                notification.error_message
                if notification is not None and notification.error_message
                else "sin resultado de notificación"
            )
            logger.error("Correo NO enviado: %s", detail)
        retention = pipeline.retention
        if retention is not None:
            logger.info(
                "Retención local: %d/%d archivo(s) eliminados, %d bytes liberados",
                retention.deleted,
                retention.examined,
                retention.freed_bytes,
            )
            for error in retention.errors:
                logger.error(
                    "Retención local: no se pudo eliminar '%s': %s",
                    error.path,
                    error.message,
                )

    if batch.error_message is not None or not batch.results:
        return EXIT_FAILURE
    if batch.success:
        if notification is not None and notification.success:
            return EXIT_OK
        return EXIT_INTERNAL
    if succeeded:
        return EXIT_PARTIAL
    return EXIT_FAILURE


def _build_scheduler_service(
    config: Config, *, state_store: SchedulerStateStore
) -> SchedulerService:
    """Fábrica real del servicio para ``odin service run`` (Items 053 y 065).

    Delega en ``odin.service.runner.build_scheduler_service`` con
    ``console=True``: el modo residente usa la misma construcción con logging
    sin consola. El runner comparte ``PipelineCycleRunner`` y el hook de recarga
    que re-configura el logging (idempotente).
    """
    return build_scheduler_service(config, state_store=state_store, console=True)


def _cmd_service_run(
    args: argparse.Namespace, *, service_factory: ServiceFactory | None = None
) -> int:
    """Ejecuta ``odin service run``: scheduler en primer plano (Items 053 y 065).

    Delega en ``odin.service.runner.ServiceRunner`` con ``console=True``: el
    runner carga y valida la configuración (``scheduler.enabled: false`` es un
    error de configuración), configura el logging, persiste el estado del
    Item 052 y arranca el scheduler bloqueante. ``SIGINT``/``SIGTERM`` (o un
    ``KeyboardInterrupt`` directo) paran el servicio con exit 0; ``SIGUSR1``
    (POSIX) pide la recarga en caliente. ``service_factory`` es inyectable para
    tests; el default arma el servicio real.
    """
    return ServiceRunner(
        _resolve_config_source(args),
        console=True,
        service_factory=service_factory or _build_scheduler_service,
    ).run()


def _cmd_service_status(
    args: argparse.Namespace, *, manager_factory: ManagerFactory | None = None
) -> int:
    """Ejecuta ``odin service status``: gestor del SO + estado del scheduler.

    Items 053 y 063. Es una consulta de solo lectura: exit 0 mientras la
    configuración cargue y el estado se pueda interpretar (o su ausencia se
    informe). ``render_platform_status`` compone el encabezado real del
    servicio en systemd/SCM (instalado, en ejecución, arranque automático,
    política de reinicio) con ``render_service_status``, que distingue
    servicio en ejecución, estado obsoleto (pid muerto) y sin estado. Un
    ``ServiceError`` del gestor (systemctl/SCM caído o plataforma no
    soportada) se reporta como advertencia **sin** fallar el comando.
    ``manager_factory`` es inyectable para tests.
    """
    source = _resolve_config_source(args)
    config = _load_config_or_report(source)
    if config is None:
        return EXIT_CONFIG
    result = load_state(state_path(config.local.work_dir))
    factory = manager_factory or create_service_manager
    service_status: ServiceStatus | None = None
    warning: str | None = None
    try:
        service_status = factory(config.config_path.absolute()).status()
    except ServiceError as exc:
        warning = str(exc)
    print(
        render_platform_status(
            service_status, render_service_status(result), warning=warning
        )
    )
    return EXIT_OK


def _cmd_service_reload(args: argparse.Namespace) -> int:
    """Ejecuta ``odin service reload``: pide la recarga en caliente (Item 055).

    Carga la configuración (para ubicar el ``work_dir``) y lee el estado del
    servicio: sin estado o con un estado obsoleto no hay a quién pedirle nada
    (exit 1 con el motivo). Con el servicio vivo, ``_RELOAD_VIA_SIGNAL`` decide
    el mecanismo: ``SIGUSR1`` al pid del estado en POSIX (un fallo de entrega es
    exit 1) o la creación de ``work_dir/scheduler_reload.request`` en las
    plataformas sin señal. La recarga en sí la valida y aplica el servicio
    (``SchedulerService.process_reload``); una configuración inválida mantiene
    la vigente sin afectar este exit code.
    """
    source = _resolve_config_source(args)
    config = _load_config_or_report(source)
    if config is None:
        return EXIT_CONFIG
    result = load_state(state_path(config.local.work_dir))
    if result.state is None:
        print(
            f"No hay servicio en ejecución: {result.warning}",
            file=sys.stderr,
        )
        return EXIT_INTERNAL
    if result.stale:
        print(
            "No hay servicio en ejecución: el estado pertenece al pid "
            f"{result.state.pid}, que ya no vive. Arranque 'odin service run' "
            "antes de pedir una recarga.",
            file=sys.stderr,
        )
        return EXIT_INTERNAL
    if _RELOAD_VIA_SIGNAL and _RELOAD_SIGNAL is not None:
        try:
            os.kill(result.state.pid, _RELOAD_SIGNAL)
        except OSError as exc:
            print(
                f"No se pudo enviar SIGUSR1 al pid {result.state.pid}: {exc}",
                file=sys.stderr,
            )
            return EXIT_INTERNAL
        print(f"Recarga solicitada al pid {result.state.pid} mediante SIGUSR1.")
        return EXIT_OK
    request_path = reload_request_path(config.local.work_dir)
    request_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_text(datetime.now(UTC).isoformat(), encoding="utf-8")
    print(f"Recarga solicitada: archivo de control creado en {request_path}.")
    return EXIT_OK


def _service_executable() -> str:
    """Ruta del ejecutable de ODIN para la unit del servicio (Item 062).

    systemd exige un ``ExecStart`` absoluto: se prefiere el propio
    ``sys.argv[0]`` (lo invocado, p. ej. ``.../.venv/bin/odin``), con
    ``shutil.which("odin")`` como respaldo de PATH. Como último recurso se
    devuelve ``odin``: Windows no consume el ejecutable (el SCM registra la
    clase del servicio) y en Linux el gestor reporta el error accionable si la
    ruta no es absoluta.
    """
    candidates = [sys.argv[0] if sys.argv else "", shutil.which("odin") or ""]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.exists():
            return str(path.resolve())
    return "odin"


def _service_manager_config_path(source: str | None) -> Path:
    """Ruta absoluta con la que se construye el gestor en el ciclo de vida.

    ``uninstall``/``start``/``stop`` identifican el servicio por nombre fijo y
    no consumen el JSON; el contrato del gestor, en cambio, exige una ruta
    absoluta. Con ``--config``/``ODIN_CONFIG`` se pasa esa ruta; sin fuente se
    usa un centinela absoluto (``<cwd>/config.json``) que ninguna de esas
    operaciones lee.
    """
    if source is not None:
        return Path(source).absolute()
    return Path.cwd() / "config.json"


def _install_next_steps(manager: ServiceManager) -> str:
    """Pasos siguientes por plataforma tras una instalación (Item 062)."""
    if manager.manager is ServiceManagerKind.WINDOWS:
        return (
            "Siguiente paso: arranque el servicio con 'odin service start' y "
            "consulte su estado con 'odin service status'."
        )
    return (
        "Siguiente paso: arranque el servicio con 'odin service start' "
        "(o 'sudo systemctl start odin.service') y consulte su estado con "
        "'odin service status'."
    )


def _cmd_service_install(
    args: argparse.Namespace, *, manager_factory: ManagerFactory | None = None
) -> int:
    """Ejecuta ``odin service install``: instala el servicio residente (Item 062).

    Exige una fuente de configuración, la carga (``ConfigError`` → 2) y la
    valida con ``validate_config``: un hallazgo ERROR de entorno/estructura
    aborta la instalación con 2 (no se crea un servicio con una configuración
    que fallaría al arrancar); las advertencias no bloquean. El ``ServiceSpec``
    se construye con la ruta **absoluta** del JSON (el servicio corre sin cwd)
    y el ejecutable resuelto. Un ``ServiceError`` del gestor (incluida la
    plataforma no soportada) devuelve 1 con el motivo en stderr. El mensaje del
    gestor se imprime tal cual: en Linux sin permisos es la guía con la unit y
    los comandos ``sudo`` (Item 060).
    """
    source = _resolve_config_source(args)
    config = _load_config_or_report(source)
    if config is None:
        return EXIT_CONFIG
    report = validate_config(config)
    if not report.is_valid(strict=False):
        _print_report(report, strict=False)
        return EXIT_CONFIG
    spec = ServiceSpec(
        config_path=config.config_path.absolute(),
        executable=_service_executable(),
    )
    factory = manager_factory or create_service_manager
    try:
        manager = factory(spec.config_path)
        message = manager.install(spec)
    except ServiceError as exc:
        print(f"No se pudo instalar el servicio: {exc}", file=sys.stderr)
        return EXIT_INTERNAL
    print(message)
    print(_install_next_steps(manager))
    return EXIT_OK


_LIFECYCLE_VERBS = {
    "uninstall": "desinstalar",
    "start": "arrancar",
    "stop": "detener",
}


def _cmd_service_lifecycle(
    action: str,
    args: argparse.Namespace,
    *,
    manager_factory: ManagerFactory | None = None,
) -> int:
    """Ejecuta ``odin service uninstall|start|stop`` (Item 062).

    Las tres acciones operan por nombre fijo ``odin``: ``--config`` es opcional
    y no se carga (solo resuelve la ruta con la que se construye el gestor).
    Cada acción devuelve 0 con el mensaje del gestor o 1 con el motivo en
    stderr si el gestor falla (``ServiceError``, plataforma no soportada).
    """
    source = _resolve_config_source(args)
    factory = manager_factory or create_service_manager
    try:
        manager = factory(_service_manager_config_path(source))
        if action == "uninstall":
            message = manager.uninstall()
        elif action == "start":
            message = manager.start()
        else:
            message = manager.stop()
    except ServiceError as exc:
        print(
            f"No se pudo {_LIFECYCLE_VERBS[action]} el servicio: {exc}",
            file=sys.stderr,
        )
        return EXIT_INTERNAL
    print(message)
    return EXIT_OK


def _cmd_service(args: argparse.Namespace) -> int:
    """Despacha las acciones de ``odin service`` (Items 053, 055 y 062)."""
    action = args.service_action
    if action == "run":
        return _cmd_service_run(args)
    if action == "status":
        return _cmd_service_status(args)
    if action == "reload":
        return _cmd_service_reload(args)
    if action == "install":
        return _cmd_service_install(args)
    if action in ("uninstall", "start", "stop"):
        return _cmd_service_lifecycle(action, args)
    print(
        "Acción de 'service' requerida: run (scheduler en primer plano), "
        "status (consulta el estado), reload (recarga la configuración), "
        "install/uninstall (modo residente del SO), start o stop (control del servicio).",
        file=sys.stderr,
    )
    return EXIT_CONFIG


def main(argv: Sequence[str] | None = None) -> int:
    """Ejecuta la CLI y devuelve el exit code (convención en el docstring del módulo).

    Sin subcomando imprime la ayuda y devuelve ``EXIT_OK`` (comportamiento del
    Item 001, cubierto por ``tests/test_smoke.py``). Los errores de uso de
    argparse (subcomando inexistente, opción inválida) y las acciones
    ``--help``/``--version`` lanzan ``SystemExit`` con código propio — el 2 de
    los errores de uso ya coincide con ``EXIT_CONFIG`` — y no se capturan acá
    (``SystemExit`` no deriva de ``Exception``). Las excepciones imprevistas
    no matan el proceso con un traceback sin manejar: mensaje + traceback en
    stderr y ``EXIT_INTERNAL``. ``ConfigError`` que escape de un handler se
    traduce a ``EXIT_CONFIG`` (red de seguridad para los subcomandos futuros).
    Antes de parsear reconfigura stdio a UTF-8 (``_force_utf8_stdio``): el
    resumen usa ``→`` y en Windows con salida redirigida (``cp1252``) eso
    lanzaba ``UnicodeEncodeError`` tras un respaldo exitoso.
    """
    _force_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return EXIT_OK
    try:
        if args.command == "validate":
            return _cmd_validate(args)
        if args.command == "run":
            return _cmd_run(args)
        if args.command == "service":
            return _cmd_service(args)
        raise RuntimeError(f"subcomando no implementado: {args.command!r}")
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return EXIT_CONFIG
    except Exception as exc:
        print(f"Error interno inesperado: {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc()
        return EXIT_INTERNAL


if __name__ == "__main__":
    raise SystemExit(main())

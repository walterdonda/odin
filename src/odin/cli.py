"""Interfaz de línea de comandos de ODIN (Items 005, 006, 013 y 019).

Subcomando ``validate``: carga y valida el JSON de configuración
(``odin.config.load_config``, Item 002), ejecuta la validación completa del
entorno local y de coherencia (``odin.validate.validate_config``, Item 006),
imprime el reporte con severidades (errores y advertencias diferenciados) y
registra el resultado en consola y archivo con secretos enmascarados
(``odin.log.setup_logging``, Item 004). Con ``--strict`` las advertencias
también fallan (exit code 2), útil como gate de despliegue o de CI.

Subcomando ``run``: ejecuta el pipeline completo (``odin.pipeline``, Item 035):
respaldo (``odin.backup.BackupExecutor``), compresión 7z
(``odin.compress.CompressionExecutor``) y transferencia SFTP
(``odin.transfer.TransferExecutor``) sobre todas las bases de la
configuración, de forma secuencial y con aislamiento de fallos por base y por
servidor. Una base cuenta como exitosa solo si el respaldo, la compresión y
la transferencia a todos los servidores culminan bien (Items 025 y 035). El
subcomando ``service`` (Etapas 6-7) aún no se registra; el punto de extensión
queda documentado en ``build_parser``.

Convención de exit codes (constantes exportadas de este módulo):

- ``EXIT_OK`` (0): operación exitosa (configuración válida, aunque tenga
  advertencias salvo con ``--strict``; respaldo, compresión y transferencia
  de todas las bases exitosos).
- ``EXIT_INTERNAL`` (1): error interno inesperado (bug, fallo de I/O no
  controlado); se imprime mensaje + traceback en stderr sin morir con una
  excepción sin manejar.
- ``EXIT_CONFIG`` (2): error de configuración (archivo ilegible/inexistente,
  JSON malformado, problema estructural o semántico, verificación de entorno
  fallida, falta la ruta de config) o de uso de la CLI (errores de argparse,
  p. ej. subcomando inexistente).
- ``EXIT_PARTIAL`` (3): algunas bases completaron todas las fases y otras
  fallaron (en cualquiera de las fases: respaldo, compresión o transferencia).
- ``EXIT_FAILURE`` (4): el pipeline falló por completo (ninguna base completó
  todas las fases; p. ej. gbak no encontrado o ``work_dir`` no creable).
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from collections.abc import Callable, Sequence
from logging import Logger

from odin import __version__
from odin.backup import BatchBackupResult
from odin.config import Config, ConfigError, load_config
from odin.log import SecretMasker, setup_logging
from odin.pipeline import PipelineResult, run_pipeline
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

MaskFn = Callable[[str], str]


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser raíz de la CLI de ODIN.

    Subcomandos registrados hoy: ``validate`` y ``run``. Punto de extensión:
    en este ``subparsers`` se agregará ``service`` (install/uninstall/start/
    stop/status del modo residente, Etapas 6-7) cuando llegue su etapa, con
    sus propios argumentos y reutilizando la resolución
    ``--config``/``ODIN_CONFIG`` de este módulo. Cuando lleguen la compresión
    (Etapa 3), la transferencia (Etapa 4) y el correo (Etapa 5), ``run``
    pasará a orquestar el pipeline completo en ``odin.pipeline``.
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
        help="Ejecuta el respaldo (gbak), la compresión 7z y la transferencia SFTP.",
        description=(
            "Ejecuta el pipeline completo de cada base de la configuración: respaldo "
            "(gbak -b), compresión 7z y transferencia SFTP del .fbk.7z a todos los "
            "servidores configurados, de forma secuencial y con aislamiento de fallos "
            "por base y por servidor. Los artefactos se guardan en local.work_dir como "
            "<nombre>_<timestamp>.fbk y su .fbk.7z. Una base cuenta como exitosa solo "
            "si el respaldo, la compresión y la transferencia culminan bien "
            "(exit codes 0/3/4)."
        ),
    )
    run_parser.add_argument(
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


def _cmd_run(args: argparse.Namespace) -> int:
    """Ejecuta ``odin run``: respaldo (gbak) + compresión 7z + transferencia SFTP.

    El pipeline completo (respaldo → compresión → transferencia, Item 035)
    vive en ``odin.pipeline.run_pipeline``. Exit codes: 0 si todas las bases
    completaron las tres fases, 3 si hubo una mezcla de éxitos y fallos (en
    cualquier fase), 4 si falló todo o si no hay gbak disponible. Los errores
    de configuración (carga/parseo) son 2, igual que en ``validate``.
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
    masker = SecretMasker.from_config(config)
    _print_backup_summary(batch, mask=masker.mask)
    _print_transfer_summary(pipeline, mask=masker.mask)

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
    if batch.error_message is not None or not batch.results:
        return EXIT_FAILURE
    if batch.success:
        return EXIT_OK
    if succeeded:
        return EXIT_PARTIAL
    return EXIT_FAILURE


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
    """
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

"""Interfaz de línea de comandos de ODIN (Items 005 y 006).

Subcomando ``validate``: carga y valida el JSON de configuración
(``odin.config.load_config``, Item 002), ejecuta la validación completa del
entorno local y de coherencia (``odin.validate.validate_config``, Item 006),
imprime el reporte con severidades (errores y advertencias diferenciados) y
registra el resultado en consola y archivo con secretos enmascarados
(``odin.log.setup_logging``, Item 004). Con ``--strict`` las advertencias
también fallan (exit code 2), útil como gate de despliegue o de CI.

Los subcomandos ``run`` (Etapas 2-5) y ``service`` (Etapas 6-7) aún no se
registran; el punto de extensión queda documentado en ``build_parser``.

Convención de exit codes (constantes exportadas de este módulo):

- ``EXIT_OK`` (0): operación exitosa (configuración válida, aunque tenga
  advertencias salvo con ``--strict``).
- ``EXIT_INTERNAL`` (1): error interno inesperado (bug, fallo de I/O no
  controlado); se imprime mensaje + traceback en stderr sin morir con una
  excepción sin manejar.
- ``EXIT_CONFIG`` (2): error de configuración (archivo ilegible/inexistente,
  JSON malformado, problema estructural o semántico, verificación de entorno
  fallida, falta la ruta de config) o de uso de la CLI (errores de argparse,
  p. ej. subcomando inexistente).
- 3 (fallo parcial) y 4 (fallo total) quedan reservados para el pipeline de
  la Etapa 5, fuera del alcance de este item.
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from collections.abc import Sequence
from logging import Logger

from odin import __version__
from odin.config import Config, ConfigError, load_config
from odin.log import setup_logging
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
    "EXIT_INTERNAL",
    "EXIT_OK",
    "build_parser",
    "main",
]

EXIT_OK = 0
EXIT_INTERNAL = 1
EXIT_CONFIG = 2
ENV_CONFIG_VAR = "ODIN_CONFIG"


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser raíz de la CLI de ODIN.

    Subcomandos registrados hoy: ``validate``. Punto de extensión: en este
    ``subparsers`` se agregarán ``run`` (pipeline respaldo → compresión →
    transferencia → correo, Etapas 2-5) y ``service`` (install/uninstall/
    start/stop/status del modo residente, Etapas 6-7) cuando lleguen sus
    etapas, cada uno con sus propios argumentos y reutilizando la resolución
    ``--config``/``ODIN_CONFIG`` de este módulo.
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

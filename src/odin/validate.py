"""Validación completa de la configuración de ODIN (Item 006).

Sobre la config ya parseada por ``odin.config`` (validación estructural y
semántica), este módulo verifica el **entorno local** y la **coherencia de
nivel configuración**, y produce un reporte con severidades
(``ERROR``/``WARNING``/``INFO``/``OK``) que la CLI renderiza en consola.

Principios (ver ``docs/aide/items/006-logica-completa-validate.md``):

- **Solo lectura:** no crea, modifica ni borra archivos ni directorios. Por
  eso las verificaciones corren *antes* que ``odin.log.setup_logging``, cuyo
  ``mkdir`` del directorio de logs crearía ``work_dir`` y enmascararía el
  hallazgo de "directorio inexistente".
- **Sin red:** no comprueba conectividad SFTP/SMTP/Firebird. Un destino
  temporalmente caído no invalida la configuración; la conectividad se
  verifica en tiempo de ejecución (Etapas 2-5).
- **Sin secretos:** los hallazgos incluyen ``field_path`` y rutas, nunca
  valores de ``password``/``passphrase`` ni contenido de claves.
- **OS-agnóstico:** una ruta cuyo *sabor* (Windows vs. POSIX) no coincide con
  el SO anfitrión no es comprobable: se omite con una nota ``INFO``, nunca se
  reporta como error. Ídem UNC en Windows (evita I/O de red).
- **Sin colores ANSI:** salida plana, portable a Windows Server y a
  redirección a archivo.

Reuso: ``odin validate`` es el preflight manual recomendado antes de
``odin run`` (que no lo invoca: reporta los fallos por base durante la
ejecución) y el modo servicio (Etapa 6) lo reutilizará para validar la recarga
en caliente de la configuración.
"""

from __future__ import annotations

import os
import shutil
import stat
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from odin.config import AuthMethod, Config, ConfigError, HostKeyPolicy
from odin.paths import is_windows_flavor
from odin.scheduler import cron_trigger, next_fire_times

__all__ = [
    "PARSE_SKIPPED_NOTE",
    "Finding",
    "Severity",
    "ValidationReport",
    "render_report",
    "render_stderr",
    "render_stdout",
    "report_from_config_error",
    "validate_config",
]

_ROOT = "config"
_MB = 1024 * 1024
_RECOMMENDED_MODE = "600"
PARSE_SKIPPED_NOTE = (
    "No se ejecutaron las verificaciones de entorno: la configuración no pudo cargarse."
)

_ERRORS_TITLE = "ERRORES"
_WARNINGS_TITLE = "ADVERTENCIAS"
_CHECKS_TITLE = "VERIFICACIONES"


class Severity(Enum):
    """Severidad de un hallazgo, con orden total ``ERROR > WARNING > INFO > OK``."""

    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"
    OK = "OK"

    @property
    def rank(self) -> int:
        """Peso ordinal (mayor = más grave), para ordenar y comparar severidades."""
        return _RANKS[self]


_RANKS: dict[Severity, int] = {
    Severity.ERROR: 3,
    Severity.WARNING: 2,
    Severity.INFO: 1,
    Severity.OK: 0,
}

_TAGS: dict[Severity, str] = {
    Severity.ERROR: "[ERROR]",
    Severity.WARNING: "[WARN] ",
    Severity.INFO: "[INFO] ",
    Severity.OK: "[OK]   ",
}


@dataclass(frozen=True, kw_only=True, slots=True)
class Finding:
    """Hallazgo individual de validación.

    ``check`` es el identificador estable de la verificación que lo produjo
    (p. ej. ``private_key_exists``): permite filtrar/agrupar programáticamente
    y será la clave de la futura salida máquina-legible.
    """

    severity: Severity
    field_path: str
    message: str
    check: str


@dataclass(slots=True)
class ValidationReport:
    """Reporte acumulado de una corrida de validación.

    ``parsed=False`` indica que la configuración no pudo cargarse
    (``ConfigError``): en ese caso solo hay hallazgos de parseo y las
    verificaciones de entorno no se ejecutaron.
    """

    config_path: Path
    summary: str = ""
    parsed: bool = True
    findings: list[Finding] = field(default_factory=list)

    def add(self, severity: Severity, field_path: str, message: str, *, check: str) -> None:
        """Registra un hallazgo."""
        self.findings.append(
            Finding(severity=severity, field_path=field_path, message=message, check=check)
        )

    def _of(self, severity: Severity) -> list[Finding]:
        return [finding for finding in self.findings if finding.severity is severity]

    @property
    def errors(self) -> list[Finding]:
        return self._of(Severity.ERROR)

    @property
    def warnings(self) -> list[Finding]:
        return self._of(Severity.WARNING)

    @property
    def infos(self) -> list[Finding]:
        return self._of(Severity.INFO)

    @property
    def oks(self) -> list[Finding]:
        return self._of(Severity.OK)

    def count(self, severity: Severity) -> int:
        return len(self._of(severity))

    @property
    def max_severity(self) -> Severity | None:
        """Severidad más grave presente, o ``None`` si no hay hallazgos."""
        if not self.findings:
            return None
        return max((finding.severity for finding in self.findings), key=lambda s: s.rank)

    def is_valid(self, *, strict: bool = False) -> bool:
        """True si no hay errores; con ``strict=True``, tampoco advertencias."""
        if self.errors:
            return False
        return not self.warnings if strict else True


def report_from_config_error(exc: ConfigError, config_path: Path | str) -> ValidationReport:
    """Convierte los problemas de parseo en un reporte con hallazgos ``ERROR``.

    Unifica el formato de salida: los errores estructurales/semánticos de
    ``odin.config`` se muestran con el mismo renderizado que los de entorno, y
    el reporte aclara que las verificaciones de entorno no se ejecutaron.
    """
    report = ValidationReport(config_path=Path(config_path), summary="", parsed=False)
    for problem in exc.problems:
        report.add(Severity.ERROR, problem.field_path, problem.message, check="config_parse")
    return report


# --- helpers de filesystem (solo lectura) ---


def _host_is_windows(host_is_windows: bool | None) -> bool:
    return sys.platform == "win32" if host_is_windows is None else host_is_windows


def _flavor_mismatch(path: Path, host_is_windows: bool) -> bool:
    """True si el sabor de la ruta no coincide con el SO anfitrión.

    Se juzga sobre ``as_posix()`` (nunca contiene ``\\``), así que el sabor
    Windows se detecta por letra de unidad. Consecuencias buscadas: una ruta
    ``D:/...`` en Linux se omite; una ruta POSIX en Windows se omite (allí
    ``Path`` la anclaría a la unidad actual, un falso positivo); y UNC en
    Windows se omite para no hacer I/O de red. En Linux, ``//srv/share`` es
    una ruta local más y sí se verifica.
    """
    return is_windows_flavor(path.as_posix()) != host_is_windows


def _nearest_existing_ancestor(path: Path) -> Path:
    """Primer ancestro (o la propia ruta) que existe en el filesystem."""
    for candidate in (path, *path.parents):
        if candidate.exists():
            return candidate
    return path


def _is_creatable(path: Path) -> bool:
    """True si un ``mkdir -p`` de ``path`` sería factible para el usuario actual."""
    ancestor = _nearest_existing_ancestor(path)
    return ancestor.is_dir() and os.access(ancestor, os.W_OK | os.X_OK)


def _kind(path: Path) -> str:
    if path.is_dir():
        return "un directorio"
    if path.is_file():
        return "un archivo regular"
    if path.is_symlink():
        return "un enlace simbólico"
    return "otro tipo de archivo"


def _mode(path: Path) -> str:
    return f"{stat.S_IMODE(path.stat().st_mode):03o}"


def _omitted(
    report: ValidationReport,
    field_path: str,
    path: Path,
    *,
    host_is_windows: bool,
    check: str,
) -> None:
    """Registra la omisión de una verificación por sabor de ruta incompatible."""
    flavor = "Windows" if is_windows_flavor(path.as_posix()) else "POSIX"
    host = "Windows" if host_is_windows else "POSIX (Linux)"
    report.add(
        Severity.INFO,
        field_path,
        f"verificación omitida: ruta con sabor {flavor}, no comprobable en {host} ({path})",
        check=check,
    )


# --- verificaciones de rutas ---


def _check_directory(
    report: ValidationReport,
    path: Path,
    field_path: str,
    *,
    host_is_windows: bool,
    check: str,
) -> None:
    """Verifica un directorio de trabajo: existente, creable o conflicto."""
    if _flavor_mismatch(path, host_is_windows):
        _omitted(report, field_path, path, host_is_windows=host_is_windows, check=check)
        return
    if path.is_dir():
        if os.access(path, os.W_OK | os.X_OK):
            report.add(
                Severity.OK,
                field_path,
                f"existe y es un directorio escribible ({path})",
                check=check,
            )
        else:
            report.add(
                Severity.WARNING,
                field_path,
                f"existe pero el usuario actual no puede escribir en él ({path})",
                check=check,
            )
        return
    if path.exists():
        report.add(
            Severity.ERROR,
            field_path,
            f"no es un directorio: existe como {_kind(path)} ({path})",
            check=check,
        )
        return
    if _is_creatable(path):
        report.add(
            Severity.INFO,
            field_path,
            f"no existe; se creará en la primera ejecución ({path})",
            check=check,
        )
    else:
        ancestor = _nearest_existing_ancestor(path)
        report.add(
            Severity.WARNING,
            field_path,
            f"no existe y no se puede crear: '{ancestor}' no es un directorio escribible ({path})",
            check=check,
        )


def _check_work_dir(report: ValidationReport, config: Config, host_is_windows: bool) -> None:
    _check_directory(
        report,
        config.local.work_dir,
        f"{_ROOT}.local.work_dir",
        host_is_windows=host_is_windows,
        check="work_dir",
    )


def _check_log_dir(report: ValidationReport, config: Config, host_is_windows: bool) -> None:
    field_path = f"{_ROOT}.local.log_dir"
    if config.local.log_dir is None:
        report.add(
            Severity.INFO,
            field_path,
            f"no configurado; se usará el derivado del work_dir ({config.local.resolved_log_dir})",
            check="log_dir_derived",
        )
        return
    _check_directory(
        report,
        config.local.log_dir,
        field_path,
        host_is_windows=host_is_windows,
        check="log_dir",
    )


def _check_disk_space(report: ValidationReport, config: Config, host_is_windows: bool) -> None:
    field_path = f"{_ROOT}.local.min_free_mb"
    work_dir = config.local.work_dir
    if _flavor_mismatch(work_dir, host_is_windows):
        return
    target = _nearest_existing_ancestor(work_dir)
    if not target.is_dir():
        return
    try:
        free_mb = shutil.disk_usage(target).free // _MB
    except OSError:
        return
    minimum = config.local.min_free_mb
    if free_mb < minimum:
        report.add(
            Severity.WARNING,
            field_path,
            f"espacio libre insuficiente en '{target}': {free_mb} MB disponibles, "
            f"mínimo configurado {minimum} MB",
            check="disk_space",
        )
    else:
        report.add(
            Severity.OK,
            field_path,
            f"espacio libre en '{target}': {free_mb} MB (mínimo {minimum} MB)",
            check="disk_space",
        )


def _check_private_keys(report: ValidationReport, config: Config, host_is_windows: bool) -> None:
    """Verifica la clave privada de cada servidor con ``auth.method: key``."""
    for index, server in enumerate(config.servers):
        if server.auth.method is not AuthMethod.KEY or server.auth.private_key is None:
            continue
        field_path = f"{_ROOT}.servers[{index}].auth.private_key"
        path = Path(server.auth.private_key)
        if _flavor_mismatch(path, host_is_windows):
            _omitted(
                report,
                field_path,
                path,
                host_is_windows=host_is_windows,
                check="private_key_exists",
            )
            continue
        if path.is_dir():
            report.add(
                Severity.ERROR,
                field_path,
                f"es un directorio; se esperaba un archivo de clave privada ({path})",
                check="private_key_exists",
            )
            continue
        if not path.exists():
            report.add(
                Severity.WARNING,
                field_path,
                "el archivo no existe; la autenticación SFTP fallará si no se aprovisiona "
                f"({path})",
                check="private_key_exists",
            )
            continue
        if not os.access(path, os.R_OK):
            report.add(
                Severity.WARNING,
                field_path,
                f"existe pero el usuario actual no puede leerlo ({path})",
                check="private_key_readable",
            )
            continue
        if not host_is_windows:
            try:
                group_other = stat.S_IMODE(path.stat().st_mode) & 0o077
            except OSError:
                group_other = 0
            if group_other:
                report.add(
                    Severity.WARNING,
                    field_path,
                    f"permisos {_mode(path)} con acceso de grupo/otros; se recomienda "
                    f"{_RECOMMENDED_MODE} ({path})",
                    check="private_key_mode",
                )
        report.add(
            Severity.OK, field_path, f"existe y es legible ({path})", check="private_key_readable"
        )


def _check_gbak_paths(report: ValidationReport, config: Config, host_is_windows: bool) -> None:
    """Verifica el ``gbak_path`` explícito de cada base (``null`` = auto-detección)."""
    for index, database in enumerate(config.databases):
        field_path = f"{_ROOT}.databases[{index}].gbak_path"
        if database.gbak_path is None:
            report.add(
                Severity.INFO,
                field_path,
                "es null; se auto-detectará según SO y versión de Firebird (Etapa 2)",
                check="gbak_autodetect",
            )
            continue
        path = Path(database.gbak_path)
        if _flavor_mismatch(path, host_is_windows):
            _omitted(
                report,
                field_path,
                path,
                host_is_windows=host_is_windows,
                check="gbak_path_exists",
            )
            continue
        if path.is_dir():
            report.add(
                Severity.ERROR,
                field_path,
                f"es un directorio; se esperaba el ejecutable gbak ({path})",
                check="gbak_path_exists",
            )
        elif not path.exists():
            report.add(
                Severity.WARNING,
                field_path,
                f"no existe; el respaldo de esta base fallará ({path})",
                check="gbak_path_exists",
            )
        elif not os.access(path, os.X_OK):
            report.add(
                Severity.WARNING,
                field_path,
                f"existe pero no es ejecutable por el usuario actual ({path})",
                check="gbak_path_executable",
            )
        else:
            report.add(
                Severity.OK,
                field_path,
                f"existe y es ejecutable ({path})",
                check="gbak_path_executable",
            )


def _check_config_file(report: ValidationReport, config: Config, host_is_windows: bool) -> None:
    """Permisos del propio JSON (NFR Seguridad: contiene credenciales legibles)."""
    if host_is_windows:
        report.add(
            Severity.INFO,
            _ROOT,
            "verificación de permisos omitida en Windows: las ACL no son comprobables "
            "de forma portable; restrinja el acceso al archivo de configuración",
            check="config_file_mode",
        )
        return
    try:
        mode = stat.S_IMODE(config.config_path.stat().st_mode)
    except OSError as exc:
        report.add(
            Severity.INFO,
            _ROOT,
            f"no se pudieron comprobar los permisos del archivo de configuración: {exc}",
            check="config_file_mode",
        )
        return
    if mode & 0o077:
        report.add(
            Severity.WARNING,
            _ROOT,
            f"el archivo de configuración tiene permisos {mode:03o}; se recomienda "
            f"{_RECOMMENDED_MODE} (contiene credenciales en texto legible)",
            check="config_file_mode",
        )
    else:
        report.add(
            Severity.OK,
            _ROOT,
            f"permisos {mode:03o}: sin acceso de grupo/otros",
            check="config_file_mode",
        )


# --- verificaciones de coherencia y advisorias ---


def _check_scheduler(report: ValidationReport, config: Config) -> None:
    scheduler = config.scheduler
    if not scheduler.enabled:
        report.add(
            Severity.INFO,
            f"{_ROOT}.scheduler",
            "deshabilitado; solo estará disponible el modo one-shot (odin run)",
            check="scheduler_enabled",
        )
        return
    if not scheduler.jobs:
        report.add(
            Severity.WARNING,
            f"{_ROOT}.scheduler.jobs",
            "el scheduler está habilitado sin jobs: no se ejecutará ningún respaldo programado",
            check="scheduler_jobs",
        )
        return
    report.add(
        Severity.OK,
        f"{_ROOT}.scheduler",
        f"habilitado con {len(scheduler.jobs)} job(s) en {scheduler.timezone}",
        check="scheduler_enabled",
    )
    _check_scheduler_next_fires(report, config)
    covered = {name for job in scheduler.jobs for name in job.databases}
    for index, database in enumerate(config.databases):
        if database.name not in covered:
            report.add(
                Severity.WARNING,
                f"{_ROOT}.databases[{index}].name",
                f"la base '{database.name}' no está incluida en ningún job del scheduler",
                check="database_covered_by_job",
            )


def _check_scheduler_next_fires(report: ValidationReport, config: Config) -> None:
    """Reporta el próximo disparo de cada job (Item 049) en la timezone global.

    ``validate`` no debe romper ante una config que llegó a cargarse: cualquier
    ``ValueError`` imprevisto (una expresión que el parser de config aceptó pero
    el trigger no puede programar) se degrada a ``WARNING``. Una expresión sin
    próximos disparos (p. ej. ``0 0 31 2 *``, fecha imposible) también advierte:
    es una config que nunca ejecutaría el job.
    """
    scheduler = config.scheduler
    try:
        now = datetime.now(ZoneInfo(scheduler.timezone))
    except ZoneInfoNotFoundError:
        return
    for index, job in enumerate(scheduler.jobs):
        field_path = f"{_ROOT}.scheduler.jobs[{index}].schedule"
        try:
            upcoming = next_fire_times(
                cron_trigger(job.schedule, scheduler.timezone), now, 1
            )
        except ValueError as exc:
            report.add(
                Severity.WARNING,
                field_path,
                f"no se pudo calcular el próximo disparo: {exc}",
                check="scheduler_next_fire",
            )
            continue
        if not upcoming:
            report.add(
                Severity.WARNING,
                field_path,
                f"la expresión '{job.schedule}' no tiene próximos disparos",
                check="scheduler_next_fire",
            )
            continue
        report.add(
            Severity.OK,
            field_path,
            f"próximo disparo: {upcoming[0].isoformat()} (schedule: '{job.schedule}')",
            check="scheduler_next_fire",
        )


def _check_servers(report: ValidationReport, config: Config) -> None:
    if not config.servers:
        report.add(
            Severity.INFO,
            f"{_ROOT}.servers",
            "sin destinos SFTP: las copias quedarán solo en el work_dir",
            check="servers_present",
        )
        return
    destinos = ", ".join(f"{s.name} ({s.host}:{s.port})" for s in config.servers)
    report.add(
        Severity.OK,
        f"{_ROOT}.servers",
        f"{len(config.servers)} destino(s) configurado(s): {destinos}",
        check="servers_present",
    )
    for index, server in enumerate(config.servers):
        if server.host_key_policy is HostKeyPolicy.INSECURE:
            report.add(
                Severity.WARNING,
                f"{_ROOT}.servers[{index}].host_key_policy",
                "'insecure' no verifica la host key del servidor (riesgo de MITM); "
                "considere 'accept-new' o 'strict'",
                check="host_key_policy",
            )


def _check_notification(report: ValidationReport, config: Config) -> None:
    notification = config.notification
    smtp = notification.smtp
    transport = "SSL implícito" if smtp.ssl else ("STARTTLS" if smtp.starttls else "sin cifrar")
    report.add(
        Severity.OK,
        f"{_ROOT}.notification.to",
        f"informe de ejecución a {notification.to} vía {smtp.host}:{smtp.port} ({transport})",
        check="notification_target",
    )
    if not smtp.starttls and not smtp.ssl:
        report.add(
            Severity.WARNING,
            f"{_ROOT}.notification.smtp.starttls",
            "es false: las credenciales SMTP viajarían sin cifrar",
            check="smtp_starttls",
        )


def _check_compression_and_retention(report: ValidationReport, config: Config) -> None:
    compression = config.compression
    if compression.password is None:
        report.add(
            Severity.OK,
            f"{_ROOT}.compression",
            f"nivel {compression.level}, sin cifrado del .7z",
            check="compression",
        )
    else:
        report.add(
            Severity.INFO,
            f"{_ROOT}.compression.password",
            f"configurado: el .7z se cifrará (AES-256) con nivel {compression.level}",
            check="compression_encryption",
        )
    retention = config.local.retention_days
    if retention == 0:
        report.add(
            Severity.INFO,
            f"{_ROOT}.local.retention_days",
            "es 0: sin limpieza automática de respaldos locales",
            check="retention",
        )
    else:
        report.add(
            Severity.OK,
            f"{_ROOT}.local.retention_days",
            f"las copias locales de más de {retention} día(s) se eliminarán "
            "después del envío del correo",
            check="retention",
        )


# --- orquestación ---


def _summary(config: Config) -> str:
    """Línea de resumen (conserva el formato del Item 005: ``bases: N | servidores SFTP: M``)."""
    scheduler = config.scheduler
    estado = "habilitado" if scheduler.enabled else "deshabilitado"
    timezone = f" ({scheduler.timezone})" if scheduler.enabled else ""
    return (
        f"bases: {len(config.databases)} | servidores SFTP: {len(config.servers)} | "
        f"jobs: {len(scheduler.jobs)} | scheduler: {estado}{timezone}"
    )


def validate_config(config: Config, *, host_is_windows: bool | None = None) -> ValidationReport:
    """Ejecuta todas las verificaciones de entorno y coherencia sobre ``config``.

    No toca el filesystem más que para consultar (``stat``/``access``/
    ``disk_usage``). ``host_is_windows`` es inyectable para probar ambas
    direcciones del contrato OS-agnóstico desde cualquier SO; por defecto se
    toma de ``sys.platform``.
    """
    host = _host_is_windows(host_is_windows)
    report = ValidationReport(config_path=config.config_path, summary=_summary(config))
    _check_config_file(report, config, host)
    _check_work_dir(report, config, host)
    _check_log_dir(report, config, host)
    _check_disk_space(report, config, host)
    _check_gbak_paths(report, config, host)
    _check_private_keys(report, config, host)
    _check_servers(report, config)
    _check_notification(report, config)
    _check_compression_and_retention(report, config)
    _check_scheduler(report, config)
    return report


# --- renderizado ---


def _render_section(title: str, findings: Sequence[Finding]) -> list[str]:
    if not findings:
        return []
    lines = [f"{title} ({len(findings)}):"]
    lines.extend(f"  {_TAGS[f.severity]} {f.field_path}: {f.message}" for f in findings)
    return lines


def _header(report: ValidationReport) -> list[str]:
    lines = [f"ODIN validate — {report.config_path}"]
    if report.summary:
        lines.append(f"  {report.summary}")
    return lines


def _verdict(report: ValidationReport, *, strict: bool) -> str:
    errors = report.count(Severity.ERROR)
    warnings = report.count(Severity.WARNING)
    if report.is_valid(strict=strict):
        return (
            f"Configuración válida: {report.config_path} — "
            f"{errors} error(es), {warnings} advertencia(s)"
        )
    if strict and errors == 0:
        return (
            f"Configuración inválida (--strict): {report.config_path} — "
            f"0 error(es), {warnings} advertencia(s) tratadas como errores"
        )
    return (
        f"Configuración inválida: {report.config_path} — "
        f"{errors} error(es), {warnings} advertencia(s)"
    )


def _join_blocks(blocks: Iterable[Sequence[str]]) -> str:
    return "\n\n".join("\n".join(block) for block in blocks if block)


def render_report(report: ValidationReport, *, strict: bool = False) -> str:
    """Reporte completo en un solo texto (encabezado + secciones + veredicto)."""
    blocks: list[Sequence[str]] = [_header(report)]
    blocks.append(_render_section(_ERRORS_TITLE, report.errors))
    blocks.append(_render_section(_WARNINGS_TITLE, report.warnings))
    blocks.append(_render_section(_CHECKS_TITLE, [*report.infos, *report.oks]))
    if not report.parsed:
        blocks.append([PARSE_SKIPPED_NOTE])
    blocks.append([_verdict(report, strict=strict)])
    return _join_blocks(blocks)


def render_stdout(report: ValidationReport, *, strict: bool = False) -> str:
    """Texto para stdout: encabezado, advertencias, verificaciones y veredicto de validez.

    Los errores y el veredicto de invalidez no van acá (ver ``render_stderr``):
    así una corrida fallida deja el diagnóstico en stderr y el contexto en
    stdout, y los exit codes siguen la convención de la CLI.
    """
    blocks: list[Sequence[str]] = [_header(report)]
    blocks.append(_render_section(_WARNINGS_TITLE, report.warnings))
    blocks.append(_render_section(_CHECKS_TITLE, [*report.infos, *report.oks]))
    if report.is_valid(strict=strict):
        blocks.append([_verdict(report, strict=strict)])
    return _join_blocks(blocks)


def render_stderr(report: ValidationReport, *, strict: bool = False) -> str:
    """Texto para stderr: errores y veredicto de invalidez (vacío si es válida)."""
    if report.is_valid(strict=strict):
        return ""
    blocks: list[Sequence[str]] = [_render_section(_ERRORS_TITLE, report.errors)]
    if not report.parsed:
        blocks.append([PARSE_SKIPPED_NOTE])
    blocks.append([_verdict(report, strict=strict)])
    return _join_blocks(blocks)

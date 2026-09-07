"""Tests de la validación completa de ODIN: entorno local, coherencia y reporte (Item 006).

Unitarios sobre el filesystem real de ``tmp_path`` (sin mocks de ``os``/
``pathlib``, que serían frágiles) y con ``host_is_windows`` inyectable para
cubrir ambas direcciones del contrato OS-agnóstico desde cualquier SO.

El helper ``_write_config`` deja la configuración en un estado conocido y
hermético: ``work_dir`` dentro de ``tmp_path``, clave privada ficticia en 600
y JSON en 600 (para que la advertencia de permisos no ensucie los casos que
prueban otra cosa).
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from odin.config import Config, ConfigError, ConfigProblem, load_config
from odin.validate import (
    PARSE_SKIPPED_NOTE,
    Finding,
    Severity,
    ValidationReport,
    render_report,
    render_stderr,
    render_stdout,
    report_from_config_error,
    validate_config,
)

FIXTURES = Path(__file__).parent / "fixtures"
LINUX_FIXTURE = FIXTURES / "config_valid_linux.json"
WINDOWS_FIXTURE = FIXTURES / "config_valid_windows.json"

IS_WINDOWS = sys.platform == "win32"
IS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0
SECRETOS = ("masterkey", "remote-secret-1", "smtp-secret")
KEY_CONTENT = (
    "-----BEGIN OPENSSH PRIVATE KEY-----\nZmljdGljaWE=\n-----END OPENSSH PRIVATE KEY-----\n"
)

# Los permisos POSIX no son observables bajo Windows ni ejecutando como root.
sin_permisos_posix = pytest.mark.skipif(
    IS_WINDOWS or IS_ROOT, reason="requiere permisos POSIX efectivos (no Windows ni root)"
)

Mutator = Callable[[dict[str, Any]], None]


def _dummy_key(tmp_path: Path, *, name: str = "id_ed25519", mode: int = 0o600) -> Path:
    """Crea una clave privada ficticia y devuelve su ruta.

    ``name`` permite crear claves adicionales sin pisar la que usa el helper
    ``_write_config`` como línea de base (distinto modo de permisos).
    """
    key = tmp_path / name
    key.write_text(KEY_CONTENT, encoding="utf-8")
    key.chmod(mode)
    return key


def _write_config(
    tmp_path: Path,
    *,
    work_dir: Path | str | None = None,
    mutate: Mutator | None = None,
    name: str = "config.json",
    mode: int = 0o600,
) -> Path:
    """Copia el fixture válido Linux a ``tmp_path`` en un estado hermético."""
    data: dict[str, Any] = json.loads(LINUX_FIXTURE.read_text(encoding="utf-8"))
    data["local"]["work_dir"] = str(work_dir if work_dir is not None else tmp_path / "work")
    data["servers"][1]["auth"]["private_key"] = str(_dummy_key(tmp_path))
    if mutate is not None:
        mutate(data)
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    path.chmod(mode)
    return path


def _config(
    tmp_path: Path,
    *,
    work_dir: Path | str | None = None,
    mutate: Mutator | None = None,
    mode: int = 0o600,
) -> Config:
    return load_config(_write_config(tmp_path, work_dir=work_dir, mutate=mutate, mode=mode))


def _of(report: ValidationReport, field_path: str) -> list[Finding]:
    return [finding for finding in report.findings if finding.field_path == field_path]


def _severities(report: ValidationReport, field_path: str) -> list[Severity]:
    return [finding.severity for finding in _of(report, field_path)]


def _messages(report: ValidationReport, field_path: str) -> str:
    return " ".join(finding.message for finding in _of(report, field_path))


WORK_DIR = "config.local.work_dir"
LOG_DIR = "config.local.log_dir"
MIN_FREE_MB = "config.local.min_free_mb"
PRIVATE_KEY = "config.servers[1].auth.private_key"
GBAK_PATH = "config.databases[0].gbak_path"


# --- reporte base ---


def test_valid_config_has_no_errors_and_keeps_summary_format(tmp_path: Path) -> None:
    config = _config(tmp_path)
    report = validate_config(config)
    assert not report.errors
    assert report.is_valid()
    assert report.parsed is True
    assert report.config_path == config.config_path
    assert "bases: 1 | servidores SFTP: 2" in report.summary
    assert "jobs: 1" in report.summary


def test_validate_config_has_no_filesystem_side_effects(tmp_path: Path) -> None:
    work_dir = tmp_path / "work"
    config = _config(tmp_path, work_dir=work_dir)
    report = validate_config(config)
    assert not work_dir.exists()
    assert Severity.INFO in _severities(report, WORK_DIR)
    assert "se creará en la primera ejecución" in _messages(report, WORK_DIR)


def test_findings_carry_stable_check_ids(tmp_path: Path) -> None:
    report = validate_config(_config(tmp_path))
    checks = {finding.check for finding in report.findings}
    assert {"work_dir", "private_key_readable", "config_file_mode", "scheduler_enabled"} <= checks


def test_severity_rank_orders_error_above_ok() -> None:
    assert Severity.ERROR.rank > Severity.WARNING.rank > Severity.INFO.rank > Severity.OK.rank


def test_max_severity_reflects_worst_finding(tmp_path: Path) -> None:
    report = validate_config(_config(tmp_path))
    assert report.max_severity in (Severity.WARNING, Severity.INFO, Severity.OK)
    empty = ValidationReport(config_path=tmp_path / "x.json")
    assert empty.max_severity is None


# --- work_dir y log_dir ---


def test_work_dir_existing_and_writable_is_ok(tmp_path: Path) -> None:
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    report = validate_config(_config(tmp_path, work_dir=work_dir))
    assert _severities(report, WORK_DIR) == [Severity.OK]


def test_work_dir_regular_file_is_error(tmp_path: Path) -> None:
    archivo = tmp_path / "archivo.txt"
    archivo.write_text("x", encoding="utf-8")
    report = validate_config(_config(tmp_path, work_dir=archivo))
    assert _severities(report, WORK_DIR) == [Severity.ERROR]
    assert "no es un directorio" in _messages(report, WORK_DIR)
    assert not report.is_valid()


def test_work_dir_not_creatable_is_warning(tmp_path: Path) -> None:
    archivo = tmp_path / "archivo.txt"
    archivo.write_text("x", encoding="utf-8")
    report = validate_config(_config(tmp_path, work_dir=archivo / "work"))
    assert _severities(report, WORK_DIR) == [Severity.WARNING]
    assert "no se puede crear" in _messages(report, WORK_DIR)
    assert report.is_valid()


@sin_permisos_posix
def test_work_dir_existing_without_write_permission_warns(tmp_path: Path) -> None:
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    work_dir.chmod(0o500)
    report = validate_config(_config(tmp_path, work_dir=work_dir))
    assert _severities(report, WORK_DIR) == [Severity.WARNING]
    assert "no puede escribir" in _messages(report, WORK_DIR)


def test_derived_log_dir_is_reported_as_info(tmp_path: Path) -> None:
    report = validate_config(_config(tmp_path))
    assert _severities(report, LOG_DIR) == [Severity.INFO]
    assert "no configurado" in _messages(report, LOG_DIR)


def test_explicit_log_dir_regular_file_is_error(tmp_path: Path) -> None:
    archivo = tmp_path / "logs.txt"
    archivo.write_text("x", encoding="utf-8")

    def mutate(data: dict[str, Any]) -> None:
        data["local"]["log_dir"] = str(archivo)

    report = validate_config(_config(tmp_path, mutate=mutate))
    assert _severities(report, LOG_DIR) == [Severity.ERROR]


def test_explicit_log_dir_existing_is_ok(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    def mutate(data: dict[str, Any]) -> None:
        data["local"]["log_dir"] = str(log_dir)

    report = validate_config(_config(tmp_path, mutate=mutate))
    assert _severities(report, LOG_DIR) == [Severity.OK]


# --- espacio libre ---


def test_disk_space_above_threshold_is_ok(tmp_path: Path) -> None:
    report = validate_config(_config(tmp_path))
    assert _severities(report, MIN_FREE_MB) == [Severity.OK]
    assert "espacio libre" in _messages(report, MIN_FREE_MB)


def test_disk_space_below_threshold_warns(tmp_path: Path) -> None:
    def mutate(data: dict[str, Any]) -> None:
        data["local"]["min_free_mb"] = 10**9

    report = validate_config(_config(tmp_path, mutate=mutate))
    assert _severities(report, MIN_FREE_MB) == [Severity.WARNING]
    assert "insuficiente" in _messages(report, MIN_FREE_MB)
    assert report.is_valid()


# --- private_key ---


def test_private_key_existing_and_readable_is_ok(tmp_path: Path) -> None:
    report = validate_config(_config(tmp_path))
    assert Severity.OK in _severities(report, PRIVATE_KEY)
    assert "existe y es legible" in _messages(report, PRIVATE_KEY)


def test_private_key_missing_is_warning_not_error(tmp_path: Path) -> None:
    ausente = tmp_path / "no-existe"

    def mutate(data: dict[str, Any]) -> None:
        data["servers"][1]["auth"]["private_key"] = str(ausente)

    report = validate_config(_config(tmp_path, mutate=mutate))
    assert _severities(report, PRIVATE_KEY) == [Severity.WARNING]
    assert "no existe" in _messages(report, PRIVATE_KEY)
    assert report.is_valid()


def test_private_key_missing_fails_only_under_strict(tmp_path: Path) -> None:
    def mutate(data: dict[str, Any]) -> None:
        data["servers"][1]["auth"]["private_key"] = str(tmp_path / "no-existe")

    report = validate_config(_config(tmp_path, mutate=mutate))
    assert report.is_valid()
    assert not report.is_valid(strict=True)


def test_private_key_directory_is_error(tmp_path: Path) -> None:
    directorio = tmp_path / "clave-dir"
    directorio.mkdir()

    def mutate(data: dict[str, Any]) -> None:
        data["servers"][1]["auth"]["private_key"] = str(directorio)

    report = validate_config(_config(tmp_path, mutate=mutate))
    assert _severities(report, PRIVATE_KEY) == [Severity.ERROR]
    assert not report.is_valid()


@sin_permisos_posix
def test_private_key_unreadable_warns(tmp_path: Path) -> None:
    clave = _dummy_key(tmp_path, name="clave-ilegible", mode=0o000)

    def mutate(data: dict[str, Any]) -> None:
        data["servers"][1]["auth"]["private_key"] = str(clave)

    report = validate_config(_config(tmp_path, mutate=mutate))
    assert Severity.WARNING in _severities(report, PRIVATE_KEY)
    assert "no puede leerlo" in _messages(report, PRIVATE_KEY)


@sin_permisos_posix
def test_private_key_open_permissions_warn(tmp_path: Path) -> None:
    clave = _dummy_key(tmp_path, name="clave-abierta", mode=0o644)

    def mutate(data: dict[str, Any]) -> None:
        data["servers"][1]["auth"]["private_key"] = str(clave)

    report = validate_config(_config(tmp_path, mutate=mutate))
    severities = _severities(report, PRIVATE_KEY)
    assert Severity.WARNING in severities
    assert Severity.OK in severities
    assert "644" in _messages(report, PRIVATE_KEY)
    assert "600" in _messages(report, PRIVATE_KEY)


def test_password_method_server_gets_no_private_key_check(tmp_path: Path) -> None:
    report = validate_config(_config(tmp_path))
    assert not _of(report, "config.servers[0].auth.private_key")


# --- gbak_path ---


def test_gbak_path_null_is_info(tmp_path: Path) -> None:
    report = validate_config(_config(tmp_path))
    assert _severities(report, GBAK_PATH) == [Severity.INFO]
    assert "auto-detectará" in _messages(report, GBAK_PATH)


def test_gbak_path_existing_and_executable_is_ok(tmp_path: Path) -> None:
    gbak = tmp_path / "gbak"
    gbak.write_text("#!/bin/sh\n", encoding="utf-8")
    gbak.chmod(0o755)

    def mutate(data: dict[str, Any]) -> None:
        data["databases"][0]["gbak_path"] = str(gbak)

    report = validate_config(_config(tmp_path, mutate=mutate))
    assert _severities(report, GBAK_PATH) == [Severity.OK]


def test_gbak_path_missing_warns(tmp_path: Path) -> None:
    def mutate(data: dict[str, Any]) -> None:
        data["databases"][0]["gbak_path"] = str(tmp_path / "gbak-inexistente")

    report = validate_config(_config(tmp_path, mutate=mutate))
    assert _severities(report, GBAK_PATH) == [Severity.WARNING]
    assert report.is_valid()


def test_gbak_path_directory_is_error(tmp_path: Path) -> None:
    def mutate(data: dict[str, Any]) -> None:
        data["databases"][0]["gbak_path"] = str(tmp_path)

    report = validate_config(_config(tmp_path, mutate=mutate))
    assert _severities(report, GBAK_PATH) == [Severity.ERROR]


@sin_permisos_posix
def test_gbak_path_not_executable_warns(tmp_path: Path) -> None:
    gbak = tmp_path / "gbak"
    gbak.write_text("binario", encoding="utf-8")
    gbak.chmod(0o644)

    def mutate(data: dict[str, Any]) -> None:
        data["databases"][0]["gbak_path"] = str(gbak)

    report = validate_config(_config(tmp_path, mutate=mutate))
    assert _severities(report, GBAK_PATH) == [Severity.WARNING]
    assert "no es ejecutable" in _messages(report, GBAK_PATH)


# --- permisos del JSON ---


def test_config_file_restricted_is_ok(tmp_path: Path) -> None:
    report = validate_config(_config(tmp_path, mode=0o600), host_is_windows=False)
    assert _severities(report, "config") == [Severity.OK]


@sin_permisos_posix
def test_config_file_open_permissions_warn(tmp_path: Path) -> None:
    report = validate_config(_config(tmp_path, mode=0o644), host_is_windows=False)
    assert _severities(report, "config") == [Severity.WARNING]
    assert "644" in _messages(report, "config")
    assert report.is_valid()


def test_config_file_permissions_skipped_on_windows_host(tmp_path: Path) -> None:
    report = validate_config(_config(tmp_path, mode=0o644), host_is_windows=True)
    assert _severities(report, "config") == [Severity.INFO]
    assert "ACL" in _messages(report, "config")


# --- sabor de ruta vs. SO anfitrión ---


def test_windows_flavor_work_dir_is_omitted_on_posix_host() -> None:
    config = load_config(WINDOWS_FIXTURE)
    report = validate_config(config, host_is_windows=False)
    assert _severities(report, WORK_DIR) == [Severity.INFO]
    assert "verificación omitida" in _messages(report, WORK_DIR)
    assert "sabor Windows" in _messages(report, WORK_DIR)
    assert not report.errors


def test_windows_flavor_disk_space_check_is_skipped_on_posix_host() -> None:
    report = validate_config(load_config(WINDOWS_FIXTURE), host_is_windows=False)
    assert not _of(report, MIN_FREE_MB)


def test_posix_flavor_work_dir_is_omitted_on_windows_host(tmp_path: Path) -> None:
    report = validate_config(_config(tmp_path), host_is_windows=True)
    assert _severities(report, WORK_DIR) == [Severity.INFO]
    assert "no comprobable en Windows" in _messages(report, WORK_DIR)
    assert _severities(report, PRIVATE_KEY) == [Severity.INFO]


def test_windows_flavor_gbak_path_is_omitted_on_posix_host(tmp_path: Path) -> None:
    def mutate(data: dict[str, Any]) -> None:
        data["databases"][0]["gbak_path"] = "C:\\Firebird\\gbak.exe"

    report = validate_config(_config(tmp_path, mutate=mutate), host_is_windows=False)
    assert _severities(report, GBAK_PATH) == [Severity.INFO]
    assert "verificación omitida" in _messages(report, GBAK_PATH)


# --- coherencia y advisorias ---


def test_scheduler_enabled_with_jobs_is_ok(tmp_path: Path) -> None:
    report = validate_config(_config(tmp_path))
    assert _severities(report, "config.scheduler") == [Severity.OK]
    assert "1 job(s)" in _messages(report, "config.scheduler")


def test_scheduler_enabled_without_jobs_warns(tmp_path: Path) -> None:
    def mutate(data: dict[str, Any]) -> None:
        data["scheduler"]["jobs"] = []

    report = validate_config(_config(tmp_path, mutate=mutate))
    assert _severities(report, "config.scheduler.jobs") == [Severity.WARNING]
    assert report.is_valid()


def test_scheduler_disabled_is_info(tmp_path: Path) -> None:
    def mutate(data: dict[str, Any]) -> None:
        data["scheduler"]["enabled"] = False

    report = validate_config(_config(tmp_path, mutate=mutate))
    assert _severities(report, "config.scheduler") == [Severity.INFO]
    assert "one-shot" in _messages(report, "config.scheduler")


def test_database_not_covered_by_any_job_warns(tmp_path: Path) -> None:
    def mutate(data: dict[str, Any]) -> None:
        data["databases"].append({**data["databases"][0], "name": "erp_secundaria"})

    report = validate_config(_config(tmp_path, mutate=mutate))
    assert _severities(report, "config.databases[1].name") == [Severity.WARNING]
    assert "erp_secundaria" in _messages(report, "config.databases[1].name")
    assert not _of(report, "config.databases[0].name")


def test_servers_empty_is_info(tmp_path: Path) -> None:
    def mutate(data: dict[str, Any]) -> None:
        data["servers"] = []

    report = validate_config(_config(tmp_path, mutate=mutate))
    assert _severities(report, "config.servers") == [Severity.INFO]
    assert not _of(report, PRIVATE_KEY)


def test_insecure_host_key_policy_warns(tmp_path: Path) -> None:
    def mutate(data: dict[str, Any]) -> None:
        data["servers"][0]["host_key_policy"] = "insecure"

    report = validate_config(_config(tmp_path, mutate=mutate))
    assert _severities(report, "config.servers[0].host_key_policy") == [Severity.WARNING]
    assert report.is_valid()


def test_starttls_disabled_warns(tmp_path: Path) -> None:
    def mutate(data: dict[str, Any]) -> None:
        data["notification"]["smtp"]["starttls"] = False

    report = validate_config(_config(tmp_path, mutate=mutate))
    assert _severities(report, "config.notification.smtp.starttls") == [Severity.WARNING]


def test_compression_password_is_info_without_leaking_value(tmp_path: Path) -> None:
    def mutate(data: dict[str, Any]) -> None:
        data["compression"]["password"] = "pass-7z-secreto"

    config = _config(tmp_path, mutate=mutate)
    report = validate_config(config)
    field_path = "config.compression.password"
    assert _severities(report, field_path) == [Severity.INFO]
    assert "pass-7z-secreto" not in render_report(report)


def test_compression_without_password_is_ok(tmp_path: Path) -> None:
    report = validate_config(_config(tmp_path))
    assert _severities(report, "config.compression") == [Severity.OK]


def test_retention_zero_is_info(tmp_path: Path) -> None:
    def mutate(data: dict[str, Any]) -> None:
        data["local"]["retention_days"] = 0

    report = validate_config(_config(tmp_path, mutate=mutate))
    assert _severities(report, "config.local.retention_days") == [Severity.INFO]


def test_retention_positive_is_ok(tmp_path: Path) -> None:
    report = validate_config(_config(tmp_path))
    assert _severities(report, "config.local.retention_days") == [Severity.OK]


# --- errores de parseo y renderizado ---


def test_report_from_config_error_converts_problems(tmp_path: Path) -> None:
    exc = ConfigError(
        [
            ConfigProblem(field_path="config.local", message="sección requerida ausente"),
            ConfigProblem(field_path="config.servers", message="sección requerida ausente"),
        ]
    )
    report = report_from_config_error(exc, tmp_path / "roto.json")
    assert report.parsed is False
    assert len(report.errors) == 2
    assert report.summary == ""
    assert not report.is_valid()
    assert not report.is_valid(strict=True)


def test_render_stderr_includes_parse_skipped_note(tmp_path: Path) -> None:
    exc = ConfigError([ConfigProblem(field_path="config", message="JSON malformado")])
    report = report_from_config_error(exc, tmp_path / "roto.json")
    stderr = render_stderr(report)
    assert "ERRORES (1):" in stderr
    assert "config: JSON malformado" in stderr
    assert PARSE_SKIPPED_NOTE in stderr
    assert PARSE_SKIPPED_NOTE not in render_stdout(report)


def test_render_report_groups_sections_with_counts(tmp_path: Path) -> None:
    archivo = tmp_path / "archivo.txt"
    archivo.write_text("x", encoding="utf-8")
    report = validate_config(_config(tmp_path, work_dir=archivo, mode=0o644))
    text = render_report(report)
    assert "ODIN validate —" in text
    assert f"ERRORES ({len(report.errors)}):" in text
    assert f"ADVERTENCIAS ({len(report.warnings)}):" in text
    assert "VERIFICACIONES" in text
    assert "Configuración inválida:" in text


def test_render_stdout_has_context_but_no_errors_section(tmp_path: Path) -> None:
    archivo = tmp_path / "archivo.txt"
    archivo.write_text("x", encoding="utf-8")
    report = validate_config(_config(tmp_path, work_dir=archivo))
    stdout = render_stdout(report)
    assert "ERRORES" not in stdout
    assert "VERIFICACIONES" in stdout
    assert "Configuración válida" not in stdout


def test_render_stderr_is_empty_when_valid(tmp_path: Path) -> None:
    report = validate_config(_config(tmp_path, mode=0o644))
    assert render_stderr(report) == ""
    assert "Configuración válida" in render_stdout(report)
    assert f"{len(report.warnings)} advertencia(s)" in render_stdout(report)


def test_render_stderr_mentions_strict_when_only_warnings(tmp_path: Path) -> None:
    report = validate_config(_config(tmp_path, mode=0o644))
    assert report.is_valid()
    assert not report.is_valid(strict=True)
    stderr = render_stderr(report, strict=True)
    assert "--strict" in stderr
    assert "tratadas como errores" in stderr
    assert "ERRORES" not in stderr
    assert render_stdout(report, strict=True).count("Configuración válida") == 0


def test_rendered_report_never_leaks_secrets(tmp_path: Path) -> None:
    report = validate_config(_config(tmp_path, mode=0o644))
    for text in (render_report(report), render_stdout(report), render_stderr(report)):
        for secreto in SECRETOS:
            assert secreto not in text


def test_report_is_valid_semantics(tmp_path: Path) -> None:
    limpia = validate_config(_config(tmp_path))
    assert limpia.is_valid()
    assert limpia.is_valid(strict=True)

    archivo = tmp_path / "archivo.txt"
    archivo.write_text("x", encoding="utf-8")
    con_error = validate_config(_config(tmp_path, work_dir=archivo))
    assert not con_error.is_valid()
    assert not con_error.is_valid(strict=True)
    assert con_error.count(Severity.ERROR) == 1

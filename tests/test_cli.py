"""Tests de la CLI de ODIN: subcomando validate, exit codes y cableado (Items 005 y 006).

In-process: se invoca ``main([...])`` con ``capsys``/``monkeypatch`` (sin
subprocess). El helper de configs reimplementa localmente el patrón de
``tests/test_log.py`` (copiar el fixture válido Linux y mutar lo necesario)
para no acoplar módulos de test.

Los casos del Item 006 agregan validación de entorno: fijan permisos del JSON y
una clave privada local para no depender de archivos del desarrollador.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from odin.cli import ENV_CONFIG_VAR, EXIT_CONFIG, EXIT_INTERNAL, EXIT_OK, main
from odin.config import load_config
from odin.log import LOG_FILENAME, LOGGER_NAME

FIXTURES = Path(__file__).parent / "fixtures"
LINUX_FIXTURE = FIXTURES / "config_valid_linux.json"
WINDOWS_FIXTURE = FIXTURES / "config_valid_windows.json"


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
    work_dir: Path | None = None,
    mutate: Callable[[dict[str, Any]], None] | None = None,
    name: str = "config.json",
    mode: int | None = None,
    private_key: Path | None = None,
) -> Path:
    """Copia el fixture válido Linux a ``tmp_path`` con ``work_dir`` controlado.

    ``mode`` y ``private_key`` (Item 006) permiten fijar permisos del JSON y
    una clave privada local para que los casos de validación de entorno sean
    deterministas y no dependan de archivos del desarrollador.
    """
    data: dict[str, Any] = json.loads(LINUX_FIXTURE.read_text(encoding="utf-8"))
    data["local"]["work_dir"] = str(work_dir if work_dir is not None else tmp_path / "work")
    if private_key is not None:
        data["servers"][1]["auth"]["private_key"] = str(private_key)
    if mutate is not None:
        mutate(data)
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    if mode is not None:
        path.chmod(mode)
    return path


def _key(tmp_path: Path, *, name: str = "id_test", mode: int = 0o600) -> Path:
    """Crea una clave privada ficticia usable por los tests de validación."""
    key = tmp_path / name
    key.write_text(
        "-----BEGIN OPENSSH PRIVATE KEY-----\nZmljdGljaWE=\n-----END OPENSSH PRIVATE KEY-----\n",
        encoding="utf-8",
    )
    key.chmod(mode)
    return key


# --- validate exitoso ---


def test_validate_config_flag_exits_0_with_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path)
    assert main(["validate", "--config", str(config_path)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "Configuración válida" in out
    assert str(config_path) in out
    assert "bases: 1" in out
    assert "servidores SFTP: 2" in out


def test_validate_creates_log_file_with_validation_line(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    assert main(["validate", "--config", str(config_path)]) == EXIT_OK
    log_path = load_config(config_path).local.resolved_log_dir / LOG_FILENAME
    assert log_path.is_file()
    content = log_path.read_text(encoding="utf-8")
    assert "Configuración válida" in content
    assert "masterkey" not in content


def test_validate_via_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = _write_config(tmp_path)
    monkeypatch.setenv(ENV_CONFIG_VAR, str(config_path))
    assert main(["validate"]) == EXIT_OK


def test_config_flag_takes_precedence_over_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = _write_config(tmp_path)
    monkeypatch.setenv(ENV_CONFIG_VAR, str(tmp_path / "inexistente.json"))
    assert main(["validate", "--config", str(config_path)]) == EXIT_OK


def test_setup_logging_failure_still_exits_0_with_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path)

    def logging_roto(config: Any) -> Any:
        raise OSError(13, "el directorio de logs no es creable")

    monkeypatch.setattr("odin.cli.setup_logging", logging_roto)
    assert main(["validate", "--config", str(config_path)]) == EXIT_OK
    captured = capsys.readouterr()
    assert "Configuración válida" in captured.out
    assert "Advertencia" in captured.err


# --- exit 2: resolución de la ruta de configuración ---


def test_missing_config_source_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate"]) == EXIT_CONFIG
    err = capsys.readouterr().err
    assert "--config" in err
    assert ENV_CONFIG_VAR in err


def test_blank_env_var_exits_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(ENV_CONFIG_VAR, "   ")
    assert main(["validate"]) == EXIT_CONFIG
    assert "--config" in capsys.readouterr().err


# --- exit 2: errores de configuración ---


def test_nonexistent_file_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    inexistente = tmp_path / "no-existe.json"
    assert main(["validate", "--config", str(inexistente)]) == EXIT_CONFIG
    assert "no se pudo leer" in capsys.readouterr().err


def test_malformed_json_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    roto = tmp_path / "roto.json"
    roto.write_text("{esto no es json", encoding="utf-8")
    assert main(["validate", "--config", str(roto)]) == EXIT_CONFIG
    assert "JSON malformado" in capsys.readouterr().err


def test_structural_problem_exits_2_with_field_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vacio = tmp_path / "vacio.json"
    vacio.write_text("{}", encoding="utf-8")
    assert main(["validate", "--config", str(vacio)]) == EXIT_CONFIG
    err = capsys.readouterr().err
    assert "config.databases" in err
    assert "config.servers" in err


def test_semantic_problem_duplicate_database_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def duplicar(data: dict[str, Any]) -> None:
        data["databases"].append(dict(data["databases"][0]))

    config_path = _write_config(tmp_path, mutate=duplicar)
    assert main(["validate", "--config", str(config_path)]) == EXIT_CONFIG
    err = capsys.readouterr().err
    assert "nombre duplicado" in err
    assert "config.databases[1].name" in err


# --- exit 1: error interno inesperado ---


def test_unexpected_exception_exits_1_with_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path)

    def explota(path: Any) -> Any:
        raise RuntimeError("falla interna simulada")

    monkeypatch.setattr("odin.cli.load_config", explota)
    assert main(["validate", "--config", str(config_path)]) == EXIT_INTERNAL
    err = capsys.readouterr().err
    assert "Error interno inesperado" in err
    assert "falla interna simulada" in err
    assert "Traceback (most recent call last)" in err


# --- ayuda y uso ---


def test_no_args_prints_help_listing_validate(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == EXIT_OK
    out = capsys.readouterr().out
    assert "usage: odin" in out
    assert "validate" in out


def test_unknown_subcommand_raises_systemexit_2() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["volar"])
    assert excinfo.value.code == EXIT_CONFIG


def test_exit_code_constants_follow_convention() -> None:
    assert (EXIT_OK, EXIT_INTERNAL, EXIT_CONFIG) == (0, 1, 2)


# --- Item 006: validación completa (entorno, reporte y --strict) ---


def test_validate_help_lists_strict_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["validate", "--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "--strict" in out
    assert "--config" in out


def test_validate_reports_warnings_and_still_exits_0(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path, mode=0o644, private_key=_key(tmp_path))
    assert main(["validate", "--config", str(config_path)]) == EXIT_OK
    captured = capsys.readouterr()
    assert "ADVERTENCIAS (1):" in captured.out
    assert "permisos 644" in captured.out
    assert "VERIFICACIONES" in captured.out
    assert "Configuración válida" in captured.out
    assert "1 advertencia(s)" in captured.out
    # stderr solo recibe el log (handler de consola del Item 004), no errores del reporte
    assert "ERRORES" not in captured.err
    assert "Configuración inválida" not in captured.err
    assert "Configuración válida con advertencias" in captured.err


def test_validate_environment_error_exits_2_with_errors_on_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    archivo = tmp_path / "archivo.txt"
    archivo.write_text("x", encoding="utf-8")
    config_path = _write_config(tmp_path, work_dir=archivo, mode=0o600, private_key=_key(tmp_path))
    assert main(["validate", "--config", str(config_path)]) == EXIT_CONFIG
    captured = capsys.readouterr()
    assert "ERRORES (1):" in captured.err
    assert "config.local.work_dir" in captured.err
    assert "Configuración inválida" in captured.err
    assert "ERRORES" not in captured.out
    assert "VERIFICACIONES" in captured.out


def test_validate_strict_promotes_warnings_to_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path, mode=0o644, private_key=_key(tmp_path))
    assert main(["validate", "--config", str(config_path), "--strict"]) == EXIT_CONFIG
    captured = capsys.readouterr()
    assert "--strict" in captured.err
    assert "tratadas como errores" in captured.err
    assert "ADVERTENCIAS (1):" in captured.out


def test_validate_strict_exits_0_when_no_warnings(tmp_path: Path) -> None:
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    config_path = _write_config(tmp_path, work_dir=work_dir, mode=0o600, private_key=_key(tmp_path))
    assert main(["validate", "--config", str(config_path), "--strict"]) == EXIT_OK


def test_missing_private_key_is_warning_and_keeps_exit_0(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path, mode=0o600, private_key=tmp_path / "clave-inexistente")
    assert main(["validate", "--config", str(config_path)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "config.servers[1].auth.private_key" in out
    assert "no existe" in out


def test_missing_work_dir_is_reported_before_logging_creates_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    work_dir = tmp_path / "work"
    config_path = _write_config(tmp_path, work_dir=work_dir, private_key=_key(tmp_path))
    assert main(["validate", "--config", str(config_path)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "se creará en la primera ejecución" in out
    assert (work_dir / "logs").is_dir()


def test_parse_error_reports_skipped_environment_checks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vacio = tmp_path / "vacio.json"
    vacio.write_text("{}", encoding="utf-8")
    assert main(["validate", "--config", str(vacio)]) == EXIT_CONFIG
    err = capsys.readouterr().err
    assert "ERRORES (4):" in err
    assert "No se ejecutaron las verificaciones de entorno" in err
    assert "Configuración inválida" in err


def test_windows_flavored_config_exits_0_on_any_host(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data: dict[str, Any] = json.loads(WINDOWS_FIXTURE.read_text(encoding="utf-8"))
    data["servers"][1]["auth"]["private_key"] = str(_key(tmp_path))
    config_path = tmp_path / "config.windows.json"
    config_path.write_text(json.dumps(data), encoding="utf-8")
    config_path.chmod(0o600)
    # En POSIX el work_dir con sabor Windows ("D:\Backups\odin") es una ruta relativa,
    # así que setup_logging crearía un directorio literal respecto del CWD: se cambia a
    # tmp_path para no ensuciar el repositorio.
    monkeypatch.chdir(tmp_path)
    assert main(["validate", "--config", str(config_path)]) == EXIT_OK
    out = capsys.readouterr().out
    if sys.platform != "win32":
        assert "verificación omitida" in out
        assert "sabor Windows" in out


def test_findings_are_logged_with_counts_and_without_secrets(tmp_path: Path) -> None:
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    config_path = _write_config(tmp_path, work_dir=work_dir, mode=0o644, private_key=_key(tmp_path))
    assert main(["validate", "--config", str(config_path)]) == EXIT_OK
    log_path = load_config(config_path).local.resolved_log_dir / LOG_FILENAME
    content = log_path.read_text(encoding="utf-8")
    assert "Configuración válida con advertencias" in content
    assert "errores: 0 | advertencias: 1" in content
    assert "config: el archivo de configuración tiene permisos 644" in content
    for secreto in ("masterkey", "remote-secret-1", "smtp-secret"):
        assert secreto not in content


def test_error_findings_are_logged_at_error_level(tmp_path: Path) -> None:
    archivo = tmp_path / "archivo.txt"
    archivo.write_text("x", encoding="utf-8")
    log_dir = tmp_path / "logs"
    config_path = _write_config(
        tmp_path,
        work_dir=archivo,
        mode=0o600,
        private_key=_key(tmp_path),
        mutate=lambda data: data["local"].update(log_dir=str(log_dir)),
    )
    assert main(["validate", "--config", str(config_path)]) == EXIT_CONFIG
    content = (log_dir / LOG_FILENAME).read_text(encoding="utf-8")
    assert "Configuración inválida" in content
    assert "ERROR" in content
    assert "config.local.work_dir" in content

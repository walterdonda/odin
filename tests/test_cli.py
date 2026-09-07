"""Tests de la CLI de ODIN: subcomando validate, exit codes y cableado (Item 005).

In-process: se invoca ``main([...])`` con ``capsys``/``monkeypatch`` (sin
subprocess). El helper de configs reimplementa localmente el patrón de
``tests/test_log.py`` (copiar el fixture válido Linux y mutar lo necesario)
para no acoplar módulos de test.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from odin.cli import ENV_CONFIG_VAR, EXIT_CONFIG, EXIT_INTERNAL, EXIT_OK, main
from odin.config import load_config
from odin.log import LOG_FILENAME, LOGGER_NAME

FIXTURES = Path(__file__).parent / "fixtures"
LINUX_FIXTURE = FIXTURES / "config_valid_linux.json"


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
) -> Path:
    """Copia el fixture válido Linux a ``tmp_path`` con ``work_dir`` controlado."""
    data: dict[str, Any] = json.loads(LINUX_FIXTURE.read_text(encoding="utf-8"))
    data["local"]["work_dir"] = str(work_dir if work_dir is not None else tmp_path / "work")
    if mutate is not None:
        mutate(data)
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


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

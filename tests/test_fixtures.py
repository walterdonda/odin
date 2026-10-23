"""Tests de los ejemplos públicos y los fixtures de configuración (Item 007).

Cubre el contrato de configuración de extremo a extremo sobre archivos reales:

- Los ejemplos ``examples/config.{linux,windows}.json`` (fieles a la visión §5)
  cargan, reflejan la estructura canónica y pasan ``odin validate`` con exit 0.
- El fixture mínimo aplica todos los defaults del modelo (Item 002).
- Los fixtures de error reportan los ``field_path`` específicos por campo.
- Las rutas relativas/``~`` se normalizan contra el directorio del JSON
  (Item 003), y los sabores POSIX/Windows quedan cubiertos por plataforma.

Hermeticidad: las fixtures ``autouse`` limpian el logger ``odin`` y aíslan
``ODIN_CONFIG`` (patrón de ``test_cli.py``/``test_log.py``/``test_validate.py``,
reimplementado localmente — no hay ``conftest.py`` compartido).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path, PurePosixPath

import pytest

from odin.cli import ENV_CONFIG_VAR, EXIT_OK, main
from odin.config import AuthMethod, ConfigError, HostKeyPolicy, LogLevel, load_config
from odin.log import LOGGER_NAME
from odin.validate import validate_config

_HERE = Path(__file__).resolve().parent
FIXTURES = _HERE / "fixtures"
EXAMPLES = _HERE.parent / "examples"

RELATIVE_FIXTURE = FIXTURES / "config_paths_relative.json"
BASE_DIR = RELATIVE_FIXTURE.parent.absolute()

EXAMPLE_NAMES = ["config.linux.json", "config.windows.json"]

# field_path esperado → subcadena del mensaje, por fixture de error.
ERROR_FIXTURES: dict[str, dict[str, str]] = {
    "config_error_types.json": {
        "config.compression.level": "debe ser un entero",
        "config.servers[0].port": "debe ser un entero",
        "config.notification.smtp.starttls": "debe ser un booleano",
        "config.local.retention_days": "debe ser un entero",
        "config.scheduler.enabled": "debe ser un booleano",
    },
    "config_error_ranges.json": {
        "config.servers[0].port": "<= 65535",
        "config.compression.level": "<= 9",
        "config.local.retention_days": ">= 0",
        "config.servers[0].host_key_policy": "valor inválido 'lax'",
        "config.scheduler.timezone": "zona horaria desconocida",
        "config.databases[0].gbak_timeout_sec": "> 0",
    },
    "config_error_missing.json": {
        "config.databases[0].password": "campo requerido ausente",
        "config.servers[0].auth": "campo requerido ausente",
        "config.notification.to": "campo requerido ausente",
        "config.local": "sección requerida ausente",
    },
}


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


# --- ejemplos: estructura y seguridad ---


@pytest.mark.parametrize("name", EXAMPLE_NAMES)
def test_examples_load_and_match_vision_structure(name: str) -> None:
    config = load_config(EXAMPLES / name)
    assert config.databases[0].name == "nombre_clave_sistema"
    assert config.databases[0].charset == "ISO8859_1"
    assert len(config.servers) == 2
    assert config.servers[0].auth.method is AuthMethod.PASSWORD
    assert config.servers[1].auth.method is AuthMethod.KEY
    assert config.servers[1].auth.private_key is not None
    assert config.notification.smtp.starttls is True
    assert config.scheduler.enabled is True
    assert config.scheduler.timezone == "America/Argentina/Buenos_Aires"
    assert config.scheduler.jobs[0].schedule == "0 2 * * *"


@pytest.mark.parametrize("name", EXAMPLE_NAMES)
def test_examples_secrets_are_placeholders(name: str) -> None:
    """Ningún ejemplo commitea credenciales reales: todos los secretos son ``***``."""
    config = load_config(EXAMPLES / name)
    assert config.databases[0].password == "***"
    assert config.servers[0].auth.password == "***"
    assert config.notification.smtp.password == "***"


def test_windows_example_differs_only_in_platform_fields() -> None:
    linux = load_config(EXAMPLES / "config.linux.json")
    windows = load_config(EXAMPLES / "config.windows.json")
    # connection: path POSIX en Linux, letra de unidad en Windows (sin normalizar).
    assert "/var/lib/firebird/data/erp.fdb" in linux.databases[0].connection
    assert "C:" in windows.databases[0].connection
    # work_dir: POSIX absoluto vs. Windows con letra de unidad.
    assert linux.local.work_dir.as_posix() == "/var/backups/odin"
    assert windows.local.work_dir.as_posix() == "D:/Backups/odin"
    # El resto del contrato es idéntico entre plataformas.
    assert linux.databases[0].charset == windows.databases[0].charset
    assert len(linux.servers) == len(windows.servers)


# --- ejemplos: pasan odin validate ---


@pytest.mark.parametrize("name", EXAMPLE_NAMES)
def test_examples_pass_validate_cli_exit_0(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``odin validate`` sobre cada ejemplo devuelve exit 0 (criterio de la Etapa 1).

    ``chdir(tmp_path)`` contiene el efecto de logging de ruta relativa del
    ejemplo Windows en hosts POSIX (Item 006, Decisión 17): ``setup_logging``
    crearía un directorio literal ``D:/…`` relativo al CWD si no se cambiara.
    """
    monkeypatch.chdir(tmp_path)
    exit_code = main(["validate", "--config", str(EXAMPLES / name)])
    assert exit_code == EXIT_OK
    out = capsys.readouterr().out
    assert "Configuración válida" in out


@pytest.mark.parametrize("name", EXAMPLE_NAMES)
def test_examples_are_valid_without_strict(name: str) -> None:
    """Verificación pura (sin efectos de filesystem/logging): 0 errores."""
    report = validate_config(load_config(EXAMPLES / name))
    assert report.is_valid(strict=False) is True


# --- fixture mínimo: defaults ---


def test_minimal_fixture_applies_defaults() -> None:
    config = load_config(FIXTURES / "config_minimal.json")
    # compression (sección omitida)
    assert config.compression.level == 7
    assert config.compression.password is None
    # scheduler (sección omitida)
    assert config.scheduler.enabled is False
    assert config.scheduler.timezone == "UTC"
    assert config.scheduler.jobs == []
    # servers
    assert config.servers[0].host_key_policy is HostKeyPolicy.STRICT
    # notification
    assert config.notification.log_tail_lines == 50
    assert config.notification.smtp.starttls is True
    # local (campos opcionales omitidos)
    assert config.local.log_level is LogLevel.INFO
    assert config.local.min_free_mb == 1024
    assert config.local.gbak_timeout_sec == 7200
    assert config.local.sftp_retries == 3
    assert config.local.sftp_connect_timeout_sec == 30
    assert config.local.log_dir is None
    assert config.local.resolved_log_dir == config.local.work_dir / "logs"
    # database (campos opcionales omitidos)
    db = config.databases[0]
    assert db.role is None
    assert db.charset is None
    assert db.gbak_path is None
    assert db.gbak_timeout_sec is None


# --- fixtures de error: field_path específicos ---


@pytest.mark.parametrize(("name", "expected"), sorted(ERROR_FIXTURES.items()))
def test_error_fixtures_report_expected_problems(name: str, expected: dict[str, str]) -> None:
    with pytest.raises(ConfigError) as excinfo:
        load_config(FIXTURES / name)
    messages = {problem.field_path: problem.message for problem in excinfo.value.problems}
    assert set(expected) <= set(messages)
    for field_path, substring in expected.items():
        assert substring in messages[field_path]


# --- rutas: normalización por plataforma ---


def test_paths_relative_normalization() -> None:
    config = load_config(RELATIVE_FIXTURE)
    # Rutas relativas resueltas contra el directorio del JSON.
    assert config.local.work_dir == BASE_DIR / "work"
    assert config.local.log_dir == BASE_DIR / "logs"
    assert config.databases[0].gbak_path == str(BASE_DIR / "gbak")
    # ``~`` expandido contra el home del usuario.
    assert config.servers[0].auth.private_key == str(Path.home() / ".ssh" / "id_ed25519")


def test_platform_path_flavors() -> None:
    """Casos de rutas por plataforma: POSIX absoluto, Windows y relativa+``~``."""
    linux = load_config(FIXTURES / "config_valid_linux.json")
    windows = load_config(FIXTURES / "config_valid_windows.json")
    relative = load_config(RELATIVE_FIXTURE)
    # POSIX absoluto (fixture Linux existente).
    assert linux.local.work_dir == Path("/var/backups/odin")
    assert PurePosixPath(linux.local.work_dir.as_posix()).is_absolute()
    # Windows con letra de unidad, en forma canónica posix (fixture Windows existente).
    assert windows.local.work_dir.as_posix() == "D:/Backups/odin"
    # Relativa resuelta contra el directorio del JSON (fixture nuevo).
    assert relative.local.work_dir == BASE_DIR / "work"


# --- guard: todos los JSON del repo parsean ---


def test_all_json_files_parse_as_objects() -> None:
    paths = sorted(EXAMPLES.glob("*.json")) + sorted(FIXTURES.glob("*.json"))
    assert len(paths) >= 9  # 2 ejemplos + 7 fixtures
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict), path

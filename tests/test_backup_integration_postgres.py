"""Test de integración end-to-end del flujo de respaldo con PostgreSQL 18 real (ticket 05).

Levanta un contenedor Docker oficial ``postgres:18`` con el helper
``tests.postgres_container``, apunta una entrada ``type: postgresql`` al
contenedor y corre el flujo real de ``odin run`` (CLI in-process): el
``pg_dump`` de la propia imagen (wrapper ``docker exec``, sin requerir
``pg_dump`` en el host) respalda la base y la compresión real produce el
``.dump.7z``. Se verifica que el ``.dump`` y su ``.dump.7z`` existen y no
están vacíos. Se omite (skip) cuando Docker no está disponible o el
contenedor no arranca, de modo que la suite unitaria corra en cualquier
entorno.

Variables de entorno (opcionales):

- ``ODIN_POSTGRES_IMAGE``: imagen a usar (por defecto ``postgres:18``).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from odin.cli import ENV_CONFIG_VAR, EXIT_OK, main
from odin.log import LOGGER_NAME
from tests.postgres_container import (
    DOCKER,
    PostgresContainer,
    PostgresContainerError,
    default_image,
)
from tests.smtp_catcher import SmtpCatcher

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(DOCKER is None, reason="Docker no instalado en el host"),
]

FIXTURES = Path(__file__).parent / "fixtures"
LINUX_FIXTURE = FIXTURES / "config_valid_linux.json"

CONTAINER = "odin-postgres-integration"
PASSWORD = "odin-postgres"
DATABASE_NAME = "odin_postgres_integration"
VERSION_MAJOR = re.compile(r"(\d+)\.\d+")


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


def _write_config(tmp_path: Path, *, smtp_port: int, pg_dump_wrapper: Path) -> Path:
    """Config apuntando al contenedor: entrada postgresql + SMTP del catcher local.

    ``host: 127.0.0.1`` y ``port: 5432`` son las coordenadas *dentro* del
    contenedor: el wrapper reenvía los argumentos al ``pg_dump`` de la imagen,
    donde ``pg_hba.conf`` confía en ``127.0.0.1`` (auth ``trust``). Sin
    servidores SFTP (nada que transferir) y con retención deshabilitada para
    que los artefactos queden en ``work_dir``.
    """
    data: dict[str, Any] = json.loads(LINUX_FIXTURE.read_text(encoding="utf-8"))
    data["databases"] = [
        {
            "name": "erp_principal",
            "type": "postgresql",
            "host": "127.0.0.1",
            "port": 5432,
            "dbname": DATABASE_NAME,
            "user": "postgres",
            "password": PASSWORD,
            "pg_dump_path": str(pg_dump_wrapper),
        }
    ]
    data["servers"] = []
    data["local"]["work_dir"] = str(tmp_path / "work")
    data["local"]["retention_days"] = 0
    notification = data["notification"]
    notification["log_tail_lines"] = 5
    notification["smtp"] = {
        "host": "127.0.0.1",
        "port": smtp_port,
        "starttls": False,
        "ssl": False,
        "username": "smtp-user",
        "password": "smtp-secret",
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_run_end_to_end_against_postgres18(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    catcher = SmtpCatcher()
    container = PostgresContainer(
        default_image(),
        name=CONTAINER,
        mount=tmp_path,
        password=PASSWORD,
        database_name=DATABASE_NAME,
    )
    try:
        container.start()
    except PostgresContainerError as exc:
        catcher.close()
        pytest.skip(f"No se pudo iniciar el contenedor PostgreSQL: {exc}")
    try:
        container.wait_ready()
        wrapper = container.pg_dump_wrapper(tmp_path / "pg_dump")
        config_path = _write_config(tmp_path, smtp_port=catcher.port, pg_dump_wrapper=wrapper)

        exit_code = main(["run", "--config", str(config_path)])
        version = container.pg_dump_version()
    finally:
        catcher.close()
        container.remove()

    captured = capsys.readouterr()
    assert exit_code == EXIT_OK, (
        f"odin run falló con {exit_code}\nstdout:\n{captured.out}\nstderr:\n{captured.err}"
    )
    assert "1/1 base(s) con éxito" in captured.out

    work_dir = tmp_path / "work"
    dumps = list(work_dir.glob("*.dump"))
    assert len(dumps) == 1, f"se esperaba exactamente un .dump en {work_dir}: {dumps}"
    assert dumps[0].stat().st_size > 0
    archives = list(work_dir.glob("*.dump.7z"))
    assert len(archives) == 1, f"se esperaba exactamente un .dump.7z en {work_dir}: {archives}"
    assert archives[0].stat().st_size > 0

    match = VERSION_MAJOR.search(version)
    assert match is not None, f"versión de pg_dump ilegible: {version!r}"
    assert int(match.group(1)) >= 18, f"se esperaba pg_dump 18+, se encontró: {version}"

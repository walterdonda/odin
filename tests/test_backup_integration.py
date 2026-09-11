"""Test de integración del flujo de respaldo con Firebird real (Item 018).

Levanta un contenedor Docker oficial de Firebird (la propia imagen crea la
base vía ``FIREBIRD_DATABASE``), apunta ``BackupExecutor`` al puerto publicado
y verifica que el ``.fbk`` resultante existe y no está vacío. Se omite (skip)
cuando Docker, su daemon o ``gbak`` no están disponibles, de modo que la suite
unitaria corra en cualquier entorno.

Variables de entorno (opcionales):

- ``ODIN_FIREBIRD_IMAGE``: imagen a usar (por defecto
  ``firebirdsql/firebird:latest``).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from odin.backup import BackupExecutor
from odin.config import DatabaseConfig
from odin.gbak_finder import find_gbak

DOCKER = shutil.which("docker")
GBACK = find_gbak()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(DOCKER is None, reason="Docker no instalado en el host"),
    pytest.mark.skipif(GBACK is None, reason="gbak no instalado en el host"),
]

CONTAINER = "odin-firebird-integration"
IMAGE = os.environ.get("ODIN_FIREBIRD_IMAGE", "firebirdsql/firebird:latest")
PASSWORD = "masterkey"
DATABASE_NAME = "odin_integration.fdb"
DATABASE_PATH = f"/var/lib/firebird/data/{DATABASE_NAME}"


def _docker(*args: str) -> subprocess.CompletedProcess[str]:
    assert DOCKER is not None
    return subprocess.run([DOCKER, *args], capture_output=True, text=True)


def test_backup_flow_against_firebird(tmp_path: Path) -> None:
    assert GBACK is not None
    _docker("rm", "-f", CONTAINER)
    started = _docker(
        "run",
        "--name",
        CONTAINER,
        "-d",
        "-P",
        "-e",
        f"FIREBIRD_ROOT_PASSWORD={PASSWORD}",
        "-e",
        f"FIREBIRD_DATABASE={DATABASE_NAME}",
        IMAGE,
    )
    if started.returncode != 0:
        pytest.skip(f"No se pudo iniciar el contenedor Firebird: {started.stderr.strip()}")

    try:
        mapped = _docker("port", CONTAINER, "3050/tcp").stdout.strip()
        if not mapped:
            pytest.skip("Docker no publicó el puerto 3050 del contenedor")
        port = mapped.rsplit(":", 1)[1]
        backup_file = tmp_path / DATABASE_NAME.replace(".fdb", ".fbk")
        database = DatabaseConfig(
            name="odin_integration",
            connection=f"localhost/{port}:{DATABASE_PATH}",
            user="sysdba",
            password=PASSWORD,
        )
        executor = BackupExecutor(GBACK, timeout=60)

        deadline = time.monotonic() + 60
        result = executor.run_backup(database.name, database.connection, str(backup_file), database)
        while not result.success and time.monotonic() < deadline:
            time.sleep(3)
            result = executor.run_backup(
                database.name, database.connection, str(backup_file), database
            )

        assert result.success, f"Respaldo falló: {result.error_message}"
        assert backup_file.is_file()
        assert backup_file.stat().st_size > 0
    finally:
        _docker("rm", "-f", CONTAINER)

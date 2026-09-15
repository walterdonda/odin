"""Test de integración del flujo de respaldo con Firebird real (Item 018).

Levanta un contenedor Docker oficial de Firebird (la propia imagen crea la
base vía ``FIREBIRD_DATABASE``) con el helper compartido
``tests.firebird_container``, apunta ``BackupExecutor`` al ``gbak`` de la
propia imagen (wrapper ``docker exec``, sin requerir ``gbak`` en el host) y
verifica que el ``.fbk`` resultante existe y no está vacío. Se omite (skip)
cuando Docker no está disponible, de modo que la suite unitaria corra en
cualquier entorno.

Variables de entorno (opcionales):

- ``ODIN_FIREBIRD_IMAGE``: imagen de la familia moderna a usar (por defecto
  ``firebirdsql/firebird:latest``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from odin.backup import BackupExecutor
from odin.config import DatabaseConfig
from tests.firebird_container import (
    DOCKER,
    FirebirdContainer,
    FirebirdContainerError,
    modern_image,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(DOCKER is None, reason="Docker no instalado en el host"),
]

CONTAINER = "odin-firebird-integration"
PASSWORD = "masterkey"
DATABASE_NAME = "odin_integration.fdb"


def test_backup_flow_against_firebird(tmp_path: Path) -> None:
    image = modern_image()
    container = FirebirdContainer(
        image,
        name=CONTAINER,
        mount=tmp_path,
        root_password=PASSWORD,
        database_name=DATABASE_NAME,
    )
    try:
        container.start()
    except FirebirdContainerError as exc:
        pytest.skip(f"No se pudo iniciar el contenedor Firebird: {exc}")
    try:
        container.wait_ready()
        wrapper = container.gbak_wrapper(tmp_path / "gbak")
        backup_file = tmp_path / DATABASE_NAME.replace(".fdb", ".fbk")
        database = DatabaseConfig(
            name="odin_integration",
            connection=container.database_spec(),
            user="sysdba",
            password=PASSWORD,
            gbak_path=str(wrapper),
        )
        executor = BackupExecutor(timeout=60)

        result = executor.run_backup(
            database.name, database.connection, str(backup_file), database
        )

        assert result.success, f"Respaldo falló: {result.error_message}"
        assert backup_file.is_file()
        assert backup_file.stat().st_size > 0
    finally:
        container.remove()

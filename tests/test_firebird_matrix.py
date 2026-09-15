"""Banco de integración de la matriz Firebird 2.5 → 5/6 (Item 069).

Ejercita el flujo real de respaldo + restauración con el ``gbak`` de la misma
familia que cada servidor usando contenedores Docker, **sin requerir ``gbak``
en el host**: el helper ``tests.firebird_container`` invoca el binario de la
propia imagen con ``docker exec`` (wrapper que se pasa como
``databases[].gbak_path`` a ``BackupExecutor``). Cada fila siembra filas con
``isql`` dentro del contenedor, respalda a un ``.fbk`` en un directorio
montado en la misma ruta absoluta host↔contenedor, valida el archivo y
restaura a una base scratch con el mismo ``gbak``, contando las filas.

Filas e imágenes (digests de imagen observados el 2026-09-15 con Docker
29.7.2; los tags pueden moverse y ``ODIN_FIREBIRD_*_IMAGE`` permite fijarlos):

- **2.5** — ``jacobalberty/firebird:2.5-sc`` (``sha256:bc359ae5b0b3…``,
  ``gbak`` 2.5.9). Familia legacy: ``ISC_PASSWORD``, base en
  ``/firebird/data``, binarios en ``/usr/local/firebird/bin`` y charset UTF8
  fijo de la imagen.
- **3.0** — ``firebirdsql/firebird:3.0.9`` (``sha256:335490b2bc45…``,
  ``gbak`` 3.0.9). Familia moderna.
- **4.0** — ``firebirdsql/firebird:4.0.5`` (``sha256:d9812f07291c…``,
  ``gbak`` 4.0.5). Familia moderna.
- **5.0** — ``firebirdsql/firebird:latest`` (``sha256:1529560400fc…``,
  ``gbak`` 5.0.4). Familia moderna.
- **6.x (best-effort)** — ``firebirdsql/firebird:6-snapshot``
  (``sha256:d73d741302b4…``, ``gbak`` 6.0.0). La fila se omite (skip) si la
  imagen no existe para la arquitectura del host o el contenedor no arranca.

Familia moderna (3.0+): ``FIREBIRD_ROOT_PASSWORD``, ``FIREBIRD_DATABASE``
(ruta relativa a ``/var/lib/firebird/data``),
``FIREBIRD_DATABASE_DEFAULT_CHARSET`` y
``FIREBIRD_USER``/``FIREBIRD_PASSWORD``; binarios en ``/opt/firebird/bin``.

Variables de entorno (opcionales): ``ODIN_FIREBIRD_25_IMAGE``,
``ODIN_FIREBIRD_30_IMAGE``, ``ODIN_FIREBIRD_40_IMAGE``,
``ODIN_FIREBIRD_50_IMAGE`` y ``ODIN_FIREBIRD_60_IMAGE``. Docker es el único
requisito: el ``gbak`` del host no se usa en ningún caso.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from odin.backup import BackupExecutor
from odin.config import DatabaseConfig
from tests.firebird_container import (
    DOCKER,
    MATRIX_IMAGES,
    FirebirdContainer,
    FirebirdContainerError,
    FirebirdImage,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(DOCKER is None, reason="Docker no instalado en el host"),
]

USER = "odin_matrix"
USER_PASSWORD = "matrixpw"
SCRATCH_NAME = "odin_matrix_restore.fdb"
TABLE = "odin_matrix_rows"
ROW_COUNT = 3

SEED_SQL = f"""\
CREATE TABLE {TABLE} (id INTEGER NOT NULL PRIMARY KEY, note VARCHAR(40));
INSERT INTO {TABLE} (id, note) VALUES (1, 'fila uno');
INSERT INTO {TABLE} (id, note) VALUES (2, 'fila dos');
INSERT INTO {TABLE} (id, note) VALUES (3, 'fila tres');
COMMIT;
"""

CASES = (
    pytest.param("25", None, "UTF8", id="firebird-2.5"),
    pytest.param("30", "WIN1252", "WIN1252", id="firebird-3.0"),
    pytest.param("40", "ISO8859_1", "ISO8859_1", id="firebird-4.0"),
    pytest.param("50", "UTF8", "UTF8", id="firebird-5.0"),
    pytest.param("60", "UTF8", "UTF8", id="firebird-6.0-snapshot"),
)


@pytest.mark.parametrize("version, charset, expected_charset", CASES)
def test_matrix_backup_and_restore(
    tmp_path: Path, version: str, charset: str | None, expected_charset: str
) -> None:
    image = MATRIX_IMAGES[version]
    container = FirebirdContainer(
        image,
        mount=tmp_path,
        user=USER,
        user_password=USER_PASSWORD,
        charset=charset,
    )
    try:
        container.start()
    except (FirebirdContainerError, subprocess.TimeoutExpired) as exc:
        pytest.skip(f"Imagen no disponible para la matriz ({image.image}): {exc}")
    try:
        try:
            container.wait_ready()
        except FirebirdContainerError as exc:
            if version == "60":
                pytest.skip(f"Firebird 6 snapshot no arrancó: {exc}")
            raise
        _exercise(container, image, tmp_path, expected_charset)
    finally:
        container.remove()


def _exercise(
    container: FirebirdContainer,
    image: FirebirdImage,
    tmp_path: Path,
    expected_charset: str,
) -> None:
    """Respalda con ``BackupExecutor`` y verifica el restore contra la imagen."""
    assert container.port > 0

    gbak_version = container.gbak_version()
    assert "gbak" in gbak_version.lower()

    container.isql(SEED_SQL, user=USER, password=USER_PASSWORD)
    assert container.count_rows(TABLE, user=USER, password=USER_PASSWORD) == ROW_COUNT

    wrapper = container.gbak_wrapper(tmp_path / f"gbak-{image.key}")
    database = DatabaseConfig(
        name=f"matrix_{image.key}",
        connection=container.database_spec(),
        user=USER,
        password=USER_PASSWORD,
        gbak_path=str(wrapper),
    )
    backup_file = tmp_path / f"odin_matrix_{image.key}.fbk"
    started = time.perf_counter()
    result = BackupExecutor(timeout=120).run_backup(
        database.name, database.connection, str(backup_file), database
    )
    duration = time.perf_counter() - started

    assert result.success, f"Respaldo falló con {image.image}: {result.error_message}"
    assert backup_file.is_file()
    size = backup_file.stat().st_size
    assert size > 0

    scratch_spec = container.database_spec(SCRATCH_NAME)
    container.gbak(
        [
            "-c",
            str(backup_file),
            scratch_spec,
            "-user",
            "SYSDBA",
            "-password",
            container.root_password,
        ]
    )
    assert (
        container.count_rows(
            TABLE, database=scratch_spec, user="SYSDBA", password=container.root_password
        )
        == ROW_COUNT
    )
    assert (
        container.character_set(
            database=scratch_spec, user="SYSDBA", password=container.root_password
        )
        == expected_charset
    )
    print(
        f"[matriz Firebird {image.key}] {image.image} {gbak_version} "
        f"charmap={expected_charset} .fbk={size} B restore={ROW_COUNT}/{ROW_COUNT} filas "
        f"en {duration:.2f} s"
    )

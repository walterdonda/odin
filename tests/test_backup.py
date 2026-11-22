"""Tests unitarios del ejecutor de respaldos (Items 017 y 019, ticket 03).

``subprocess.run`` se mockea con ``unittest.mock`` (Item 017): el
``side_effect`` escribe el archivo de salida (``.fbk`` para Firebird,
``.dump`` para PostgreSQL) para que la validación post-respaldo real (Item
014: existe, no vacío, legible) quede cubierta sin depender de Firebird ni
de un ``gbak``/``pg_dump`` instalado. La sección PostgreSQL (ticket 03)
verifica el dispatch por ``databases[].type``, el comando exacto de §2.1,
``PGPASSWORD`` en el env del subproceso (nunca en argv ni en logs) y los 8
patrones de error de §2.4.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from odin.backup import BackupExecutor
from odin.config import DatabaseConfig, DbEngine

GBACK = "/usr/bin/gbak"
PG_DUMP = "/usr/bin/pg_dump"

# Patrones de error del engine pg_dump (§2.4 de docs/postgresql.md).
PG_ERROR_PATTERNS = (
    "password authentication failed",
    "no password supplied",
    "no pg_hba.conf entry",
    "connection to server at",
    "connection to server on socket",
    "could not translate host name",
    "timeout expired",
    "server version mismatch",
)


def _completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    return MagicMock(returncode=returncode, stdout=stdout, stderr=stderr)


def _write_backup_file(command: list[str], content: bytes = b"x" * 128) -> None:
    """Escribe el ``.fbk`` que gbak habría generado (``command[3]``)."""
    Path(command[3]).write_bytes(content)


def _success_side_effect(command: list[str], **kwargs: object) -> MagicMock:
    _write_backup_file(command)
    return _completed(stdout="Backup successful")


def _write_pg_backup_file(command: list[str], content: bytes = b"x" * 128) -> None:
    """Escribe el ``.dump`` que pg_dump habría generado (flag ``--file``)."""
    Path(command[command.index("--file") + 1]).write_bytes(content)


def _pg_success_side_effect(command: list[str], **kwargs: object) -> MagicMock:
    _write_pg_backup_file(command)
    return _completed(stdout="pg_dump: volcado completo")


@pytest.fixture
def db_config() -> DatabaseConfig:
    return DatabaseConfig(
        name="test_db",
        type=DbEngine.FIREBIRD,
        connection="test_db.fdb",
        user="sysdba",
        password="masterkey",
    )


@pytest.fixture
def pg_db_config() -> DatabaseConfig:
    return DatabaseConfig(
        name="ventas_pg",
        type=DbEngine.POSTGRESQL,
        host="db.example.com",
        port=5432,
        dbname="ventas",
        user="odin_backup",
        password="s3cret",
    )


@pytest.fixture
def executor() -> BackupExecutor:
    return BackupExecutor(gbak_path=GBACK, timeout=10)


@pytest.fixture
def pg_executor() -> BackupExecutor:
    return BackupExecutor(pg_dump_path=PG_DUMP, pg_dump_timeout=10)


# --- ejecución de una base ---


def test_run_backup_minimal_command(executor: BackupExecutor, tmp_path: Path) -> None:
    backup = tmp_path / "db.fbk"
    with patch("odin.backup.subprocess.run", side_effect=_success_side_effect) as mock_run:
        result = executor.run_backup("db_name", "db.fdb", str(backup))

    assert result.success
    assert result.backup_path == backup
    assert result.file_size_bytes == 128
    assert result.error_message is None
    assert mock_run.call_args.args[0] == [GBACK, "-b", "db.fdb", str(backup)]


def test_run_backup_with_config_builds_flags(
    executor: BackupExecutor, tmp_path: Path, db_config: DatabaseConfig
) -> None:
    backup = tmp_path / "db.fbk"
    with patch("odin.backup.subprocess.run", side_effect=_success_side_effect) as mock_run:
        result = executor.run_backup("db_name", "db.fdb", str(backup), db_config=db_config)

    assert result.success
    command = mock_run.call_args.args[0]
    assert command[:4] == [GBACK, "-b", "db.fdb", str(backup)]
    assert command[4:] == ["-user", "sysdba", "-password", "masterkey"]


def test_run_backup_with_charset_and_role(executor: BackupExecutor, tmp_path: Path) -> None:
    config = DatabaseConfig(
        name="test_db",
        type=DbEngine.FIREBIRD,
        connection="test_db.fdb",
        user="sysdba",
        password="masterkey",
        charset="UTF8",
        role="admin",
    )
    backup = tmp_path / "db.fbk"
    with patch("odin.backup.subprocess.run", side_effect=_success_side_effect) as mock_run:
        result = executor.run_backup("db_name", "db.fdb", str(backup), db_config=config)

    assert result.success
    command = mock_run.call_args.args[0]
    assert command[command.index("-role") : command.index("-role") + 2] == ["-role", "admin"]
    # gbak no tiene switch de charset: el valor del config no debe viajar al comando
    assert "UTF8" not in command
    assert "-E" not in command


def test_password_is_never_logged(
    executor: BackupExecutor,
    tmp_path: Path,
    db_config: DatabaseConfig,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with (
        caplog.at_level(logging.INFO, logger="odin.backup"),
        patch("odin.backup.subprocess.run", side_effect=_success_side_effect),
    ):
        result = executor.run_backup(
            "db_name", "db.fdb", str(tmp_path / "db.fbk"), db_config=db_config
        )

    assert result.success
    assert "********" in caplog.text
    assert "masterkey" not in caplog.text


# --- fallos operativos: siempre se reportan como BackupResult fallido ---


def test_failure_by_exit_code(executor: BackupExecutor, tmp_path: Path) -> None:
    with patch(
        "odin.backup.subprocess.run",
        return_value=_completed(returncode=1, stderr="Some error occurred"),
    ):
        result = executor.run_backup("db_name", "db.fdb", str(tmp_path / "db.fbk"))

    assert not result.success
    assert result.backup_path is None
    assert result.error_message is not None
    assert "Some error occurred" in result.error_message


def test_failure_by_error_pattern_with_exit_code_zero(
    executor: BackupExecutor, tmp_path: Path
) -> None:
    with patch(
        "odin.backup.subprocess.run",
        return_value=_completed(returncode=0, stderr="Error: not a valid database"),
    ):
        result = executor.run_backup("db_name", "db.int", str(tmp_path / "db.fbk"))

    assert not result.success
    assert result.error_message is not None
    assert "not a valid database" in result.error_message


def test_timeout_is_reported_in_result(executor: BackupExecutor, tmp_path: Path) -> None:
    with patch(
        "odin.backup.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd=["gbak"], timeout=10),
    ):
        result = executor.run_backup("db_name", "db.fdb", str(tmp_path / "db.fbk"))

    assert not result.success
    assert result.error_message is not None
    assert "timeout" in result.error_message.lower()


def test_missing_binary_is_reported_in_result(executor: BackupExecutor, tmp_path: Path) -> None:
    with patch("odin.backup.subprocess.run", side_effect=FileNotFoundError("gbak")):
        result = executor.run_backup("db_name", "db.fdb", str(tmp_path / "db.fbk"))

    assert not result.success
    assert result.error_message is not None
    assert "no se pudo ejecutar gbak" in result.error_message


def test_missing_output_file_fails_validation(executor: BackupExecutor, tmp_path: Path) -> None:
    with patch("odin.backup.subprocess.run", return_value=_completed()):
        result = executor.run_backup("db_name", "db.fdb", str(tmp_path / "db.fbk"))

    assert not result.success
    assert result.error_message is not None
    assert "no generó" in result.error_message


def test_empty_output_file_fails_validation(executor: BackupExecutor, tmp_path: Path) -> None:
    def side_effect(command: list[str], **kwargs: object) -> MagicMock:
        _write_backup_file(command, content=b"")
        return _completed()

    with patch("odin.backup.subprocess.run", side_effect=side_effect):
        result = executor.run_backup("db_name", "db.fdb", str(tmp_path / "db.fbk"))

    assert not result.success
    assert result.error_message is not None
    assert "vacío" in result.error_message


# --- resolución del binario ---


def test_auto_detection_when_no_path_given(tmp_path: Path) -> None:
    backup = tmp_path / "db.fbk"
    with (
        patch("odin.engines.firebird.find_gbak", return_value=Path(GBACK)),
        patch("odin.backup.subprocess.run", side_effect=_success_side_effect) as mock_run,
    ):
        result = BackupExecutor().run_backup("db_name", "db.fdb", str(backup))

    assert result.success
    # ``find_gbak`` devuelve el binario como ``Path`` del host: en Windows
    # '/usr/bin/gbak' se stringifica con '\', así que se compara por as_posix.
    assert Path(mock_run.call_args.args[0][0]).as_posix() == GBACK


def test_gbak_not_found_is_reported_in_result(tmp_path: Path) -> None:
    with (
        patch("odin.engines.firebird.find_gbak", return_value=None),
        patch("odin.backup.subprocess.run") as mock_run,
    ):
        result = BackupExecutor().run_backup("db_name", "db.fdb", str(tmp_path / "db.fbk"))

    assert not result.success
    assert result.error_message is not None
    assert "no se encontró el binario gbak" in result.error_message
    mock_run.assert_not_called()


# --- lote multi-base ---


def test_batch_creates_work_dir_and_backs_up_all(tmp_path: Path) -> None:
    work_dir = tmp_path / "no" / "existe"
    databases = [
        DatabaseConfig(
            name="db1", type=DbEngine.FIREBIRD, connection="db1.fdb", user="sysdba",
            password="masterkey",
        ),
        DatabaseConfig(
            name="db2", type=DbEngine.FIREBIRD, connection="db2.fdb", user="sysdba",
            password="masterkey",
        ),
    ]
    with patch("odin.backup.subprocess.run", side_effect=_success_side_effect):
        batch = BackupExecutor(GBACK, timeout=10).run_batch_backup(databases, work_dir)

    assert batch.success
    assert work_dir.is_dir()
    assert [result.database_name for result in batch.results] == ["db1", "db2"]
    generated = sorted(path.name for path in work_dir.glob("*.fbk"))
    assert len(generated) == 2
    assert generated[0].startswith("db1_") and generated[0].endswith(".fbk")
    assert generated[1].startswith("db2_") and generated[1].endswith(".fbk")


def test_batch_isolates_partial_failure(tmp_path: Path) -> None:
    databases = [
        DatabaseConfig(
            name="db1", type=DbEngine.FIREBIRD, connection="db1.fdb", user="sysdba",
            password="masterkey",
        ),
        DatabaseConfig(
            name="db2", type=DbEngine.FIREBIRD, connection="db2.fdb", user="sysdba",
            password="masterkey",
        ),
    ]

    def side_effect(command: list[str], **kwargs: object) -> MagicMock:
        if "db2.fdb" in command:
            return _completed(returncode=1, stderr="error in db2")
        return _success_side_effect(command)

    with patch("odin.backup.subprocess.run", side_effect=side_effect):
        batch = BackupExecutor(GBACK, timeout=10).run_batch_backup(databases, tmp_path)

    assert not batch.success
    assert [result.success for result in batch.results] == [True, False]
    assert batch.results[1].error_message is not None
    assert "error in db2" in batch.results[1].error_message


def test_batch_uses_per_database_path_and_timeout(tmp_path: Path) -> None:
    database = DatabaseConfig(
        name="db1",
        type=DbEngine.FIREBIRD,
        connection="db1.fdb",
        user="sysdba",
        password="masterkey",
        gbak_path="/opt/firebird/bin/gbak",
        gbak_timeout_sec=5,
    )
    with patch("odin.backup.subprocess.run", side_effect=_success_side_effect) as mock_run:
        batch = BackupExecutor(GBACK, timeout=10).run_batch_backup([database], tmp_path)

    assert batch.success
    assert mock_run.call_args.args[0][0] == "/opt/firebird/bin/gbak"
    assert mock_run.call_args.kwargs["timeout"] == 5


def test_batch_reports_unusable_work_dir(tmp_path: Path) -> None:
    work_dir = tmp_path / "archivo.txt"
    work_dir.write_text("no es un directorio", encoding="utf-8")
    database = DatabaseConfig(
        name="db1", type=DbEngine.FIREBIRD, connection="db1.fdb", user="sysdba",
        password="masterkey",
    )
    with patch("odin.backup.subprocess.run", side_effect=_success_side_effect):
        batch = BackupExecutor(GBACK, timeout=10).run_batch_backup([database], work_dir)

    assert not batch.success
    assert batch.results == []
    assert batch.error_message is not None
    assert "directorio de trabajo" in batch.error_message


# --- motor PostgreSQL (ticket 03) ---


def test_pg_dump_builds_exact_command(
    pg_executor: BackupExecutor, tmp_path: Path, pg_db_config: DatabaseConfig
) -> None:
    backup = tmp_path / "ventas.dump"
    with patch("odin.backup.subprocess.run", side_effect=_pg_success_side_effect) as mock_run:
        result = pg_executor.run_backup("ventas_pg", "", str(backup), db_config=pg_db_config)

    assert result.success
    assert result.backup_path == backup
    assert result.file_size_bytes == 128
    # Comando exacto de §2.1: pg_dump escribe el archivo él mismo (--file).
    assert mock_run.call_args.args[0] == [
        PG_DUMP,
        "--host", "db.example.com",
        "--port", "5432",
        "--username", "odin_backup",
        "--dbname", "ventas",
        "--format=custom",
        "--no-password",
        "--no-privileges",
        "--file", str(backup),
    ]


def test_pg_dump_uses_effective_port(
    pg_executor: BackupExecutor, tmp_path: Path, pg_db_config: DatabaseConfig
) -> None:
    backup = tmp_path / "ventas.dump"
    with patch("odin.backup.subprocess.run", side_effect=_pg_success_side_effect) as mock_run:
        pg_executor.run_backup("ventas_pg", "", str(backup), db_config=pg_db_config)

    # puerto explícito de la entrada
    command = mock_run.call_args.args[0]
    assert command[command.index("--port") + 1] == "5432"

    # port ausente → default efectivo 5432 (el engine lo aplica)
    config = DatabaseConfig(
        name="ventas_pg", type=DbEngine.POSTGRESQL, host="db.example.com",
        dbname="ventas", user="odin_backup", password="s3cret",
    )
    with patch("odin.backup.subprocess.run", side_effect=_pg_success_side_effect) as mock_run2:
        pg_executor.run_backup("ventas_pg", "", str(backup), db_config=config)

    command2 = mock_run2.call_args.args[0]
    assert command2[command2.index("--port") + 1] == "5432"


def test_pg_dump_password_goes_only_to_subprocess_env(
    pg_executor: BackupExecutor, tmp_path: Path, pg_db_config: DatabaseConfig
) -> None:
    backup = tmp_path / "ventas.dump"
    with patch("odin.backup.subprocess.run", side_effect=_pg_success_side_effect) as mock_run:
        result = pg_executor.run_backup("ventas_pg", "", str(backup), db_config=pg_db_config)

    assert result.success
    env = mock_run.call_args.kwargs["env"]
    assert env["PGPASSWORD"] == "s3cret"
    # La contraseña NUNCA viaja en argv (§2.2).
    assert "s3cret" not in mock_run.call_args.args[0]


def test_pg_dump_password_is_never_logged(
    pg_executor: BackupExecutor,
    tmp_path: Path,
    pg_db_config: DatabaseConfig,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with (
        caplog.at_level(logging.INFO, logger="odin.backup"),
        patch("odin.backup.subprocess.run", side_effect=_pg_success_side_effect),
    ):
        result = pg_executor.run_backup(
            "ventas_pg", "", str(tmp_path / "ventas.dump"), db_config=pg_db_config
        )

    assert result.success
    assert "s3cret" not in caplog.text
    # Ni la variable ni el enmascarado de flags: pg_dump no declara secretos.
    assert "PGPASSWORD" not in caplog.text
    assert "********" not in caplog.text


@pytest.mark.parametrize("pattern", PG_ERROR_PATTERNS)
def test_pg_dump_fails_on_each_error_pattern_with_exit_code_zero(
    pg_executor: BackupExecutor, tmp_path: Path, pg_db_config: DatabaseConfig, pattern: str
) -> None:
    stderr = f"pg_dump: error: {pattern}: detalle simulado"
    with patch(
        "odin.backup.subprocess.run",
        return_value=_completed(returncode=0, stderr=stderr),
    ):
        result = pg_executor.run_backup(
            "ventas_pg", "", str(tmp_path / "ventas.dump"), db_config=pg_db_config
        )

    assert not result.success
    assert result.error_message is not None
    assert pattern in result.error_message


def test_pg_dump_failure_by_exit_code(
    pg_executor: BackupExecutor, tmp_path: Path, pg_db_config: DatabaseConfig
) -> None:
    with patch(
        "odin.backup.subprocess.run",
        return_value=_completed(returncode=1, stderr="pg_dump: error: algo falló"),
    ):
        result = pg_executor.run_backup(
            "ventas_pg", "", str(tmp_path / "ventas.dump"), db_config=pg_db_config
        )

    assert not result.success
    assert result.error_message is not None
    assert "pg_dump falló (código 1)" in result.error_message


def test_pg_dump_timeout_is_reported_in_result(
    pg_executor: BackupExecutor, tmp_path: Path, pg_db_config: DatabaseConfig
) -> None:
    with patch(
        "odin.backup.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd=["pg_dump"], timeout=10),
    ):
        result = pg_executor.run_backup(
            "ventas_pg", "", str(tmp_path / "ventas.dump"), db_config=pg_db_config
        )

    assert not result.success
    assert result.error_message is not None
    assert "pg_dump excedió el timeout de 10 s" in result.error_message


def test_pg_dump_missing_binary_is_reported_in_result(
    pg_executor: BackupExecutor, tmp_path: Path, pg_db_config: DatabaseConfig
) -> None:
    with patch("odin.backup.subprocess.run", side_effect=FileNotFoundError("pg_dump")):
        result = pg_executor.run_backup(
            "ventas_pg", "", str(tmp_path / "ventas.dump"), db_config=pg_db_config
        )

    assert not result.success
    assert result.error_message is not None
    assert "no se pudo ejecutar pg_dump" in result.error_message


def test_pg_dump_not_found_is_reported_with_engine_hint(
    tmp_path: Path, pg_db_config: DatabaseConfig
) -> None:
    with (
        patch("odin.engines.postgresql.find_pg_dump", return_value=None),
        patch("odin.backup.subprocess.run") as mock_run,
    ):
        result = BackupExecutor().run_backup(
            "ventas_pg", "", str(tmp_path / "ventas.dump"), db_config=pg_db_config
        )

    assert not result.success
    assert result.error_message is not None
    assert "no se encontró el binario pg_dump" in result.error_message
    assert "databases[].pg_dump_path" in result.error_message
    mock_run.assert_not_called()


def test_batch_dispatch_por_type_mezcla_motores(tmp_path: Path) -> None:
    databases = [
        DatabaseConfig(
            name="fb1", type=DbEngine.FIREBIRD, connection="fb1.fdb", user="sysdba",
            password="masterkey",
        ),
        DatabaseConfig(
            name="pg1", type=DbEngine.POSTGRESQL, host="db.example.com", port=5432,
            dbname="ventas", user="odin_backup", password="s3cret",
        ),
    ]

    def side_effect(command: list[str], **kwargs: object) -> MagicMock:
        if "--file" in command:
            _write_pg_backup_file(command)
        else:
            _write_backup_file(command)
        return _completed()

    with patch("odin.backup.subprocess.run", side_effect=side_effect) as mock_run:
        batch = BackupExecutor(
            GBACK, timeout=10, pg_dump_path=PG_DUMP, pg_dump_timeout=20
        ).run_batch_backup(databases, tmp_path)

    assert batch.success
    assert [result.database_name for result in batch.results] == ["fb1", "pg1"]
    fbk = sorted(path.name for path in tmp_path.glob("*.fbk"))
    dump = sorted(path.name for path in tmp_path.glob("*.dump"))
    assert len(fbk) == 1 and fbk[0].startswith("fb1_")
    assert len(dump) == 1 and dump[0].startswith("pg1_")
    commands = [call.args[0] for call in mock_run.call_args_list]
    assert commands[0][0] == GBACK
    assert commands[1][0] == PG_DUMP


def test_batch_uses_per_database_pg_dump_path_and_timeout(tmp_path: Path) -> None:
    database = DatabaseConfig(
        name="pg1",
        type=DbEngine.POSTGRESQL,
        host="db.example.com",
        port=5432,
        dbname="ventas",
        user="odin_backup",
        password="s3cret",
        pg_dump_path="/opt/pg18/bin/pg_dump",
        pg_dump_timeout_sec=5,
    )
    with patch("odin.backup.subprocess.run", side_effect=_pg_success_side_effect) as mock_run:
        batch = BackupExecutor(pg_dump_path=PG_DUMP, pg_dump_timeout=10).run_batch_backup(
            [database], tmp_path
        )

    assert batch.success
    assert mock_run.call_args.args[0][0] == "/opt/pg18/bin/pg_dump"
    assert mock_run.call_args.kwargs["timeout"] == 5


def test_batch_pg_dump_falls_back_to_executor_path_and_timeout(tmp_path: Path) -> None:
    database = DatabaseConfig(
        name="pg1",
        type=DbEngine.POSTGRESQL,
        host="db.example.com",
        port=5432,
        dbname="ventas",
        user="odin_backup",
        password="s3cret",
    )
    with patch("odin.backup.subprocess.run", side_effect=_pg_success_side_effect) as mock_run:
        batch = BackupExecutor(pg_dump_path=PG_DUMP, pg_dump_timeout=30).run_batch_backup(
            [database], tmp_path
        )

    assert batch.success
    assert mock_run.call_args.args[0][0] == PG_DUMP
    assert mock_run.call_args.kwargs["timeout"] == 30


def test_batch_pg_dump_isolates_partial_failure(tmp_path: Path) -> None:
    databases = [
        DatabaseConfig(
            name="pg1", type=DbEngine.POSTGRESQL, host="db.example.com", port=5432,
            dbname="ventas", user="odin_backup", password="s3cret",
        ),
        DatabaseConfig(
            name="pg2", type=DbEngine.POSTGRESQL, host="db.example.com", port=5432,
            dbname="stock", user="odin_backup", password="s3cret",
        ),
    ]

    def side_effect(command: list[str], **kwargs: object) -> MagicMock:
        if "--dbname" in command and command[command.index("--dbname") + 1] == "stock":
            return _completed(returncode=1, stderr="pg_dump: error: timeout expired")
        return _pg_success_side_effect(command)

    with patch("odin.backup.subprocess.run", side_effect=side_effect):
        batch = BackupExecutor(pg_dump_path=PG_DUMP, pg_dump_timeout=10).run_batch_backup(
            databases, tmp_path
        )

    assert not batch.success
    assert [result.success for result in batch.results] == [True, False]
    assert batch.results[1].error_message is not None
    assert "timeout expired" in batch.results[1].error_message

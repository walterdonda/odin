"""Tests unitarios del ejecutor de respaldos (Items 017 y 019).

``subprocess.run`` se mockea con ``unittest.mock`` (Item 017): el
``side_effect`` escribe el archivo ``.fbk`` de salida para que la validación
post-respaldo real (Item 014: existe, no vacío, legible) quede cubierta sin
depender de Firebird ni de un ``gbak`` instalado.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from odin.backup import BackupExecutor
from odin.config import DatabaseConfig

GBACK = "/usr/bin/gbak"


def _completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    return MagicMock(returncode=returncode, stdout=stdout, stderr=stderr)


def _write_backup_file(command: list[str], content: bytes = b"x" * 128) -> None:
    """Escribe el ``.fbk`` que gbak habría generado (``command[3]``)."""
    Path(command[3]).write_bytes(content)


def _success_side_effect(command: list[str], **kwargs: object) -> MagicMock:
    _write_backup_file(command)
    return _completed(stdout="Backup successful")


@pytest.fixture
def db_config() -> DatabaseConfig:
    return DatabaseConfig(
        name="test_db",
        connection="test_db.fdb",
        user="sysdba",
        password="masterkey",
    )


@pytest.fixture
def executor() -> BackupExecutor:
    return BackupExecutor(gbak_path=GBACK, timeout=10)


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
        patch("odin.backup.find_gbak", return_value=Path(GBACK)),
        patch("odin.backup.subprocess.run", side_effect=_success_side_effect) as mock_run,
    ):
        result = BackupExecutor().run_backup("db_name", "db.fdb", str(backup))

    assert result.success
    assert mock_run.call_args.args[0][0] == GBACK


def test_gbak_not_found_is_reported_in_result(tmp_path: Path) -> None:
    with (
        patch("odin.backup.find_gbak", return_value=None),
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
        DatabaseConfig(name="db1", connection="db1.fdb", user="sysdba", password="masterkey"),
        DatabaseConfig(name="db2", connection="db2.fdb", user="sysdba", password="masterkey"),
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
        DatabaseConfig(name="db1", connection="db1.fdb", user="sysdba", password="masterkey"),
        DatabaseConfig(name="db2", connection="db2.fdb", user="sysdba", password="masterkey"),
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
    database = DatabaseConfig(name="db1", connection="db1.fdb", user="sysdba", password="masterkey")
    with patch("odin.backup.subprocess.run", side_effect=_success_side_effect):
        batch = BackupExecutor(GBACK, timeout=10).run_batch_backup([database], work_dir)

    assert not batch.success
    assert batch.results == []
    assert batch.error_message is not None
    assert "directorio de trabajo" in batch.error_message

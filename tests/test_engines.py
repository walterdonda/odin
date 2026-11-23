"""Tests unitarios del paquete de motores de respaldo (ticket 02).

El motor Firebird replica exactamente el comportamiento previo de
``odin.backup``: la suite de ``test_backup.py`` (sin cambios de qué verifica)
es la red de seguridad de la extracción; estos tests cubren el protocolo
nuevo (``Engine``) y sus excepciones neutras.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from odin.config import DatabaseConfig, DbEngine
from odin.engines import EngineError, EngineExecutionError, EngineNotFoundError
from odin.engines.firebird import FirebirdEngine
from odin.engines.postgresql import PostgreSQLEngine


@pytest.fixture
def db_config() -> DatabaseConfig:
    return DatabaseConfig(
        name="test_db",
        type=DbEngine.FIREBIRD,
        connection="test_db.fdb",
        user="sysdba",
        password="masterkey",
    )


# --- protocolo Firebird (espejo exacto del comportamiento previo) ---


def test_firebird_protocol_attributes() -> None:
    engine = FirebirdEngine()
    assert engine.binary_name == "gbak"
    assert engine.extension == ".fbk"
    assert engine.secret_flags == ("-password", "-pas", "-P")
    assert engine.error_patterns == (
        "not a valid database",
        "permission denied",
        "database is in use",
        "unavailable database",
    )


def test_firebird_env_is_empty(db_config: DatabaseConfig) -> None:
    assert FirebirdEngine().env(db_config) == {}


def test_firebird_build_command_minimal() -> None:
    command = FirebirdEngine().build_command("/usr/bin/gbak", "db.fdb", "/tmp/db.fbk", None)
    assert command == ["/usr/bin/gbak", "-b", "db.fdb", "/tmp/db.fbk"]


def test_firebird_build_command_with_config(db_config: DatabaseConfig) -> None:
    command = FirebirdEngine().build_command(
        "/usr/bin/gbak", "db.fdb", "/tmp/db.fbk", db_config
    )
    assert command[:4] == ["/usr/bin/gbak", "-b", "db.fdb", "/tmp/db.fbk"]
    assert command[4:] == ["-user", "sysdba", "-password", "masterkey"]


def test_firebird_build_command_with_role_and_charset() -> None:
    config = DatabaseConfig(
        name="test_db",
        type=DbEngine.FIREBIRD,
        connection="test_db.fdb",
        user="sysdba",
        password="masterkey",
        charset="UTF8",
        role="admin",
    )
    command = FirebirdEngine().build_command("/usr/bin/gbak", "db.fdb", "/tmp/db.fbk", config)
    assert command[command.index("-role") : command.index("-role") + 2] == ["-role", "admin"]
    # gbak no tiene switch de charset: el valor del config no debe viajar al comando
    assert "UTF8" not in command
    assert "-E" not in command


def test_firebird_not_found_message_names_binary_and_hint() -> None:
    message = FirebirdEngine().not_found_message()
    assert "gbak" in message
    assert "databases[].gbak_path" in message


# --- resolución del binario (precedencia §3.7) ---


def test_resolve_binary_prefers_database_config_over_executor() -> None:
    config = DatabaseConfig(
        name="test_db",
        type=DbEngine.FIREBIRD,
        connection="test_db.fdb",
        user="sysdba",
        password="masterkey",
        gbak_path="/opt/custom/gbak",
    )
    engine = FirebirdEngine("/opt/firebird/bin/gbak")
    with patch("odin.engines.firebird.find_gbak") as mock_find:
        assert engine.resolve_binary(config) == "/opt/custom/gbak"
        mock_find.assert_not_called()


def test_resolve_binary_prefers_executor_over_finder() -> None:
    engine = FirebirdEngine("/opt/firebird/bin/gbak")
    with patch("odin.engines.firebird.find_gbak") as mock_find:
        assert engine.resolve_binary() == "/opt/firebird/bin/gbak"
        mock_find.assert_not_called()


def test_resolve_binary_auto_detects_and_caches() -> None:
    with patch("odin.engines.firebird.find_gbak", return_value=Path("/usr/bin/gbak")) as mock_find:
        engine = FirebirdEngine()
        assert Path(engine.resolve_binary()) == Path("/usr/bin/gbak")
        assert Path(engine.resolve_binary()) == Path("/usr/bin/gbak")

    assert mock_find.call_count == 1


def test_resolve_binary_raises_not_found_with_hint() -> None:
    with (
        patch("odin.engines.firebird.find_gbak", return_value=None),
        pytest.raises(EngineNotFoundError, match="no se encontró el binario gbak"),
    ):
        FirebirdEngine().resolve_binary()


# --- excepciones neutras ---


def test_engine_error_hierarchy() -> None:
    assert issubclass(EngineNotFoundError, EngineError)
    assert issubclass(EngineExecutionError, EngineError)


def test_execution_error_message_is_neutral_with_binary_name() -> None:
    exc = EngineExecutionError("gbak", 1, "", "database is in use")
    assert str(exc) == "gbak falló (código 1): database is in use"
    assert exc.returncode == 1
    assert exc.stderr == "database is in use"


def test_execution_error_falls_back_to_stdout_and_default_detail() -> None:
    assert str(EngineExecutionError("gbak", 2, "fallo de gbak", "")) == (
        "gbak falló (código 2): fallo de gbak"
    )
    assert str(EngineExecutionError("gbak", 3, "", "")) == "gbak falló (código 3): sin detalle"


# --- protocolo PostgreSQL (ticket 03) ---


PG_DUMP = "/usr/bin/pg_dump"


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


def test_postgresql_protocol_attributes() -> None:
    engine = PostgreSQLEngine()
    assert engine.binary_name == "pg_dump"
    assert engine.extension == ".dump"
    # Sin flags de secreto: la contraseña viaja por PGPASSWORD, nunca en argv.
    assert engine.secret_flags == ()
    assert engine.error_patterns == (
        "password authentication failed",
        "no password supplied",
        "no pg_hba.conf entry",
        "connection to server at",
        "connection to server on socket",
        "could not translate host name",
        "timeout expired",
        "server version mismatch",
    )


def test_postgresql_env_sets_only_pgpassword(pg_db_config: DatabaseConfig) -> None:
    assert PostgreSQLEngine().env(pg_db_config) == {"PGPASSWORD": "s3cret"}


def test_postgresql_env_without_config_is_empty() -> None:
    assert PostgreSQLEngine().env(None) == {}


def test_postgresql_build_command_exact(pg_db_config: DatabaseConfig) -> None:
    command = PostgreSQLEngine().build_command(PG_DUMP, "", "/tmp/ventas.dump", pg_db_config)
    assert command == [
        PG_DUMP,
        "--host", "db.example.com",
        "--port", "5432",
        "--username", "odin_backup",
        "--dbname", "ventas",
        "--format=custom",
        "--no-password",
        "--no-privileges",
        "--file", "/tmp/ventas.dump",
    ]


def test_postgresql_build_command_default_port_when_absent() -> None:
    config = DatabaseConfig(
        name="ventas_pg", type=DbEngine.POSTGRESQL, host="db.example.com",
        dbname="ventas", user="odin_backup", password="s3cret",
    )
    command = PostgreSQLEngine().build_command(PG_DUMP, "", "/tmp/ventas.dump", config)
    assert command[command.index("--port") + 1] == "5432"


def test_postgresql_build_command_requires_host() -> None:
    # Fail-fast: sin ``host`` no se emiten flags vacíos (config sin validar).
    config = DatabaseConfig(
        name="ventas_pg", type=DbEngine.POSTGRESQL, dbname="ventas",
        user="odin_backup", password="s3cret",
    )
    with pytest.raises(EngineError, match="host"):
        PostgreSQLEngine().build_command(PG_DUMP, "", "/tmp/ventas.dump", config)


def test_postgresql_build_command_requires_dbname() -> None:
    # Fail-fast: sin ``dbname`` no se emiten flags vacíos (config sin validar).
    config = DatabaseConfig(
        name="ventas_pg", type=DbEngine.POSTGRESQL, host="db.example.com",
        user="odin_backup", password="s3cret",
    )
    with pytest.raises(EngineError, match="dbname"):
        PostgreSQLEngine().build_command(PG_DUMP, "", "/tmp/ventas.dump", config)


def test_postgresql_not_found_message_names_binary_and_hint() -> None:
    message = PostgreSQLEngine().not_found_message()
    assert "pg_dump" in message
    assert "databases[].pg_dump_path" in message
    assert "--host" in message
    assert "--dbname" in message


def test_postgresql_resolve_binary_prefers_database_config_over_executor() -> None:
    config = DatabaseConfig(
        name="ventas_pg",
        type=DbEngine.POSTGRESQL,
        host="db.example.com",
        dbname="ventas",
        user="odin_backup",
        password="s3cret",
        pg_dump_path="/opt/pg18/bin/pg_dump",
    )
    engine = PostgreSQLEngine(PG_DUMP)
    with patch("odin.engines.postgresql.find_pg_dump") as mock_find:
        assert engine.resolve_binary(config) == "/opt/pg18/bin/pg_dump"
        mock_find.assert_not_called()


def test_postgresql_resolve_binary_auto_detects_and_caches() -> None:
    with patch(
        "odin.engines.postgresql.find_pg_dump", return_value=Path(PG_DUMP)
    ) as mock_find:
        engine = PostgreSQLEngine()
        assert Path(engine.resolve_binary()) == Path(PG_DUMP)
        assert Path(engine.resolve_binary()) == Path(PG_DUMP)

    assert mock_find.call_count == 1


def test_postgresql_resolve_binary_raises_not_found_with_hint() -> None:
    with (
        patch("odin.engines.postgresql.find_pg_dump", return_value=None),
        pytest.raises(EngineNotFoundError, match="no se encontró el binario pg_dump"),
    ):
        PostgreSQLEngine().resolve_binary()

"""Motor PostgreSQL: respaldo con ``pg_dump`` 18+ (ticket 03).

Implementa §2 de ``docs/postgresql.md``: comando exacto de §2.1 (``pg_dump``
escribe el artefacto ``.dump`` él mismo vía ``--file``; sin redirect de
stdout ni buffering), contraseña únicamente por ``PGPASSWORD`` en el entorno
del subproceso (§2.2, nunca en argv ni en logs: ``secret_flags = ()``) y los
8 patrones de error de §2.4 para la detección de fallo. El puerto efectivo
es ``databases[].port`` o 5432 (§3.4); sin ``--encoding`` (§2.1).
"""

from __future__ import annotations

from pathlib import Path

from odin.config import DatabaseConfig
from odin.engines import Engine, EngineError
from odin.pg_dump_finder import find_pg_dump

__all__ = ["PostgreSQLEngine"]

_DEFAULT_PORT = 5432


class PostgreSQLEngine(Engine):
    """Comportamiento de ``pg_dump`` (§2, precedencia §3.7, artefacto ``.dump``)."""

    binary_name = "pg_dump"
    extension = ".dump"
    secret_flags = ()
    error_patterns = (
        "password authentication failed",
        "no password supplied",
        "no pg_hba.conf entry",
        "connection to server at",
        "connection to server on socket",
        "could not translate host name",
        "timeout expired",
        "server version mismatch",
    )

    def env(self, database: DatabaseConfig | None) -> dict[str, str]:
        """``PGPASSWORD`` para el subproceso; nunca en argv ni en logs (§2.2)."""
        if database is None:
            return {}
        return {"PGPASSWORD": database.password}

    def build_command(
        self,
        binary: str,
        database: str,
        target: str,
        db_config: DatabaseConfig | None,
    ) -> list[str]:
        """Comando exacto de §2.1; ``pg_dump`` escribe el archivo él mismo.

        Fail-fast: sin entrada o sin ``host``/``dbname`` (requeridos por §3.4
        para postgresql) no se construye un comando con flags vacíos.
        """
        if db_config is None:
            raise EngineError("pg_dump requiere la entrada postgresql (host y dbname)")
        if not db_config.host:
            raise EngineError(
                "pg_dump requiere el campo 'host' de la entrada postgresql "
                "(databases[].host)"
            )
        if not db_config.dbname:
            raise EngineError(
                "pg_dump requiere el campo 'dbname' de la entrada postgresql "
                "(databases[].dbname)"
            )
        port = db_config.port if db_config.port is not None else _DEFAULT_PORT
        return [
            binary,
            "--host",
            db_config.host,
            "--port",
            str(port),
            "--username",
            db_config.user,
            "--dbname",
            db_config.dbname,
            "--format=custom",
            "--no-password",
            "--no-privileges",
            "--file",
            target,
        ]

    def not_found_message(self) -> str:
        """Nombre del binario + hint de instalación (rutas típicas) y de conexión."""
        return (
            "no se encontró el binario pg_dump; instale PostgreSQL 18+ (rutas típicas: "
            "/usr/lib/postgresql/18/bin/pg_dump en Debian/Ubuntu, /usr/pgsql-18/bin/pg_dump "
            "en RHEL, C:/Program Files/PostgreSQL/18/bin/pg_dump.exe en Windows) o indique "
            "databases[].pg_dump_path en la configuración; la conexión usa --host/--port/"
            "--username/--dbname de la entrada"
        )

    def _configured_binary(self, db_config: DatabaseConfig | None) -> str | None:
        if db_config is not None and db_config.pg_dump_path:
            return db_config.pg_dump_path
        return None

    def _find_binary(self) -> Path | None:
        return find_pg_dump()

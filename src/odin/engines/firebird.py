"""Motor Firebird: respaldo con ``gbak`` (Etapa 2).

Replica exactamente el comportamiento histórico de ``odin.backup`` previo al
seam de engines (ticket 02): binario ``gbak``, artefacto ``.fbk``, comando
``gbak -b`` con parámetros de conexión (``-user``, ``-password``, ``-role``;
``gbak`` no tiene switch de charset, así que ``charset`` no se pasa), los
mismos patrones de error, sin variables de entorno extra y con el mismo hint
de instalación ante binario no encontrado.
"""

from __future__ import annotations

from pathlib import Path

from odin.config import DatabaseConfig
from odin.engines import Engine
from odin.gbak_finder import find_gbak

__all__ = ["FirebirdEngine"]


class FirebirdEngine(Engine):
    """Comportamiento exacto de ``gbak`` (precedencia §3.7, artefacto ``.fbk``)."""

    binary_name = "gbak"
    extension = ".fbk"
    secret_flags = ("-password", "-pas", "-P")
    error_patterns = (
        "not a valid database",
        "permission denied",
        "database is in use",
        "unavailable database",
    )

    def env(self, database: DatabaseConfig | None) -> dict[str, str]:
        """gbak no necesita variables de entorno extra."""
        return {}

    def build_command(
        self,
        binary: str,
        database: str,
        target: str,
        db_config: DatabaseConfig | None,
    ) -> list[str]:
        """Construye ``gbak -b`` con los parámetros de conexión disponibles.

        Se usan los nombres completos de switch (``-user``, ``-password``,
        ``-role``): ``-u`` choca con ``-use_all_space``, ``-p`` con
        ``-page_size`` y ``-r`` con ``-recreate_database``.
        """
        command = [binary, "-b", database, target]
        if db_config is not None:
            for flag, value in (
                ("-user", db_config.user),
                ("-password", db_config.password),
                ("-role", db_config.role),
            ):
                if value:
                    command.extend((flag, value))
        return command

    def not_found_message(self) -> str:
        """Nombre del binario + hint de instalación/configuración."""
        return (
            "no se encontró el binario gbak; instale Firebird o indique "
            "databases[].gbak_path en la configuración"
        )

    def _configured_binary(self, db_config: DatabaseConfig | None) -> str | None:
        if db_config is not None and db_config.gbak_path:
            return db_config.gbak_path
        return None

    def _find_binary(self) -> Path | None:
        return find_gbak()

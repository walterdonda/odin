"""Protocolo común de motores de respaldo (Etapa 2).

El paquete declara la interfaz que todo motor implementa (§5.1 de
``docs/postgresql.md``) y las excepciones neutras que el ejecutor de
respaldo consume: el detalle operativo (nombre del binario, hint de
instalación, salida del proceso) lo aporta cada motor.

Hoy existe un solo motor (``odin.engines.firebird.FirebirdEngine``,
comportamiento idéntico al histórico); el motor PostgreSQL se agrega en el
ticket 03 sin tocar este protocolo.
"""

from __future__ import annotations

from pathlib import Path

from odin.config import DatabaseConfig

__all__ = [
    "Engine",
    "EngineError",
    "EngineExecutionError",
    "EngineNotFoundError",
]


class EngineError(Exception):
    """Error operativo de un motor de respaldo (base de la Etapa 2)."""


class EngineNotFoundError(EngineError):
    """No hay binario configurado y la auto-detección no lo encontró.

    El mensaje (nombre del binario + hint de instalación) lo aporta el motor
    vía ``Engine.not_found_message``.
    """


class EngineExecutionError(EngineError):
    """El binario terminó con código distinto de 0 o con un patrón de error."""

    def __init__(self, binary_name: str, returncode: int, stdout: str, stderr: str) -> None:
        self.binary_name = binary_name
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        detail = (stderr or stdout).strip() or "sin detalle"
        super().__init__(f"{binary_name} falló (código {returncode}): {detail}")


class Engine:
    """Protocolo de un motor de respaldo (§5.1 de ``docs/postgresql.md``).

    Cada motor declara sus datos (``binary_name``, ``extension``,
    ``secret_flags``, ``error_patterns``) y su comportamiento
    (``build_command``, ``env``, ``not_found_message``). La resolución del
    binario es genérica y sigue la precedencia de §3.7: binario de la base >
    binario del ejecutor (constructor) > auto-detección del motor, cacheando
    el resultado de la detección en la instancia.
    """

    binary_name: str
    extension: str
    secret_flags: tuple[str, ...] = ()
    error_patterns: tuple[str, ...] = ()

    def __init__(self, binary: str | Path | None = None) -> None:
        self._binary = None if binary is None else str(binary)

    def env(self, database: DatabaseConfig | None) -> dict[str, str]:
        """Variables de entorno extra para el subproceso (vacío por defecto)."""
        return {}

    def build_command(
        self,
        binary: str,
        database: str,
        target: str,
        db_config: DatabaseConfig | None,
    ) -> list[str]:
        """Construye el comando de respaldo de ``database`` a ``target``."""
        raise NotImplementedError

    def not_found_message(self) -> str:
        """Mensaje de binario no encontrado (nombre + hint de instalación)."""
        raise NotImplementedError

    def _configured_binary(self, db_config: DatabaseConfig | None) -> str | None:
        """Binario explícito de la base (campo ``*_path`` del motor)."""
        raise NotImplementedError

    def _find_binary(self) -> Path | None:
        """Auto-detección del binario en el host (``None`` si no aparece)."""
        raise NotImplementedError

    def resolve_binary(self, db_config: DatabaseConfig | None = None) -> str:
        """Precedencia: binario de la base > del ejecutor > auto-detección.

        Lanza ``EngineNotFoundError`` (con el mensaje del motor) si no hay
        ninguna vía que resuelva el binario; la auto-detección se cachea en
        la instancia.
        """
        configured = self._configured_binary(db_config)
        if configured:
            return configured
        if self._binary is None:
            found = self._find_binary()
            if found is None:
                raise EngineNotFoundError(self.not_found_message())
            self._binary = str(found)
        return self._binary

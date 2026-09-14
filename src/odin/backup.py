"""Ejecución de respaldos Firebird con ``gbak`` (Etapa 2).

Responsabilidades:

- Resolver el binario: ``databases[].gbak_path`` explícito o auto-detección
  (``odin.gbak_finder.find_gbak``); si no hay ninguno, ``GbakNotFoundError``.
- Ejecutar ``gbak -b`` por base con timeout y parámetros de conexión
  (``-user``, ``-password``, ``-role``), enmascarando la contraseña en los
  logs. ``gbak`` no tiene switch de charset: el respaldo es transportable y el
  charset de conexión no interviene, por eso ``charset`` no se pasa.
- Validar el archivo resultante (existe, tamaño > 0 y legible).
- Recorrer todas las bases de la configuración de forma secuencial y con
  aislamiento de fallos, creando ``local.work_dir`` si no existe y nombrando
  los archivos ``<nombre_bd>_<timestamp>.fbk``.

Los errores operativos esperados (timeout, fallo de gbak, binario inexistente,
archivo inválido) no se propagan como excepción desde ``run_backup``: se
reportan en el ``BackupResult`` con ``success=False`` y un mensaje claro, de
modo que el lote continúe con la próxima base.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from odin.config import DatabaseConfig
from odin.gbak_finder import find_gbak

logger = logging.getLogger(__name__)

DEFAULT_GBACK_TIMEOUT_SEC = 7200
_TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"

_ERROR_PATTERNS = (
    "not a valid database",
    "permission denied",
    "database is in use",
    "unavailable database",
)


class BackupError(Exception):
    """Error operativo de respaldo (base de los errores de la Etapa 2)."""


class GbakNotFoundError(BackupError):
    """No hay ``gbak_path`` configurado y la auto-detección no encontró gbak."""


class GbakExecutionError(BackupError):
    """``gbak`` terminó con código distinto de 0 o con un patrón de error."""

    def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        detail = (stderr or stdout).strip() or "sin detalle"
        super().__init__(f"gbak falló (código {returncode}): {detail}")


@dataclass(frozen=True, slots=True)
class BackupResult:
    """Resultado de respaldar una base (éxito o fallo con causa).

    Incluye los datos de la compresión posterior (Item 025): ``success`` es
    ``True`` solo si el respaldo **y** la compresión culminaron bien (el
    cruce lo hace ``odin.cli``); los campos ``archive_*``/``compressed_*``
    quedan vacíos cuando la compresión no se intentó.
    """

    success: bool
    database_name: str
    backup_path: Path | None = None
    file_size_bytes: int | None = None
    duration_seconds: float = 0.0
    error_message: str | None = None
    archive_path: Path | None = None
    compressed_size_bytes: int | None = None
    compression_duration_seconds: float = 0.0
    compression_error_message: str | None = None
    transfer_error_message: str | None = None


@dataclass(frozen=True, slots=True)
class BatchBackupResult:
    """Resultado del respaldo de todas las bases configuradas."""

    results: Sequence[BackupResult]
    success: bool
    total_duration_seconds: float
    error_message: str | None = None


def _masked_command(command: Sequence[str]) -> str:
    """Representación del comando con el valor de ``-password`` enmascarado."""
    masked = list(command)
    for index, argument in enumerate(masked[:-1]):
        if argument in ("-password", "-pas", "-P"):
            masked[index + 1] = "********"
    return " ".join(masked)


class BackupExecutor:
    """Ejecuta ``gbak -b`` por base y reporta el resultado de cada una."""

    def __init__(
        self,
        gbak_path: str | Path | None = None,
        timeout: int = DEFAULT_GBACK_TIMEOUT_SEC,
    ) -> None:
        self.gbak_path = None if gbak_path is None else str(gbak_path)
        self.timeout = timeout

    def _resolve_gbak_path(self, db_config: DatabaseConfig | None = None) -> str:
        """Precedencia: ``gbak_path`` de la base > del ejecutor > detección.

        Lanza ``GbakNotFoundError`` si no hay ninguna vía que resuelva el
        binario; la auto-detección se cachea en el ejecutor.
        """
        if db_config is not None and db_config.gbak_path:
            return db_config.gbak_path
        if self.gbak_path is None:
            found = find_gbak()
            if found is None:
                raise GbakNotFoundError(
                    "no se encontró el binario gbak; instale Firebird o indique "
                    "databases[].gbak_path en la configuración"
                )
            self.gbak_path = str(found)
        return self.gbak_path

    def run_backup(
        self,
        database_name: str,
        database_path: str,
        backup_path: str,
        db_config: DatabaseConfig | None = None,
    ) -> BackupResult:
        """Ejecuta ``gbak -b`` y valida el archivo resultante.

        No propaga errores operativos: timeout, fallo de ``gbak``, binario
        inexistente o archivo inválido se devuelven como ``BackupResult`` con
        ``success=False``.
        """
        start_time = time.perf_counter()
        target = Path(backup_path)
        gbak_path: str | None = None

        try:
            gbak_path = self._resolve_gbak_path(db_config)
            command = self._build_command(gbak_path, database_path, backup_path, db_config)
            logger.info("Ejecutando gbak para '%s': %s", database_name, _masked_command(command))
            completed = subprocess.run(
                command, capture_output=True, text=True, timeout=self.timeout
            )
            self._check_completed(completed)
            file_size = self._validate_backup_file(target)
        except subprocess.TimeoutExpired:
            return self._failure(
                database_name,
                start_time,
                f"gbak excedió el timeout de {self.timeout} s",
            )
        except OSError as exc:
            return self._failure(
                database_name,
                start_time,
                f"no se pudo ejecutar gbak ({gbak_path}): {exc}",
            )
        except BackupError as exc:
            return self._failure(database_name, start_time, str(exc))

        duration = time.perf_counter() - start_time
        logger.info(
            "Respaldo exitoso de '%s': %s (%d bytes, %.1f s)",
            database_name,
            target,
            file_size,
            duration,
        )
        return BackupResult(
            success=True,
            database_name=database_name,
            backup_path=target,
            file_size_bytes=file_size,
            duration_seconds=duration,
        )

    def run_batch_backup(
        self,
        databases: Sequence[DatabaseConfig],
        work_dir: Path,
    ) -> BatchBackupResult:
        """Respalda secuencialmente cada base, aislando los fallos por base.

        Crea ``work_dir`` si no existe. Un fallo no interrumpe el lote: todas
        las bases se intentan y el resultado agregado queda en
        ``BatchBackupResult``.
        """
        start_time = time.perf_counter()
        work_dir = Path(work_dir)
        try:
            work_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            message = f"no se pudo preparar el directorio de trabajo {work_dir}: {exc}"
            logger.error(message)
            return BatchBackupResult(
                results=[],
                success=False,
                total_duration_seconds=time.perf_counter() - start_time,
                error_message=message,
            )

        results = [self._backup_one(database, work_dir) for database in databases]
        duration = time.perf_counter() - start_time
        succeeded = sum(result.success for result in results)
        logger.info(
            "Lote de respaldo finalizado: %d/%d exitosos en %.1f s",
            succeeded,
            len(results),
            duration,
        )
        return BatchBackupResult(
            results=results,
            success=bool(results) and succeeded == len(results),
            total_duration_seconds=duration,
        )

    def _backup_one(self, database: DatabaseConfig, work_dir: Path) -> BackupResult:
        """Respalda una base, resolviendo su ``gbak_path`` y timeout propios."""
        timestamp = datetime.now().strftime(_TIMESTAMP_FORMAT)
        backup_path = work_dir / f"{database.name}_{timestamp}.fbk"
        logger.info("Procesando base '%s' (%s)", database.name, database.connection)
        executor = BackupExecutor(
            database.gbak_path or self.gbak_path,
            database.gbak_timeout_sec or self.timeout,
        )
        return executor.run_backup(database.name, database.connection, str(backup_path), database)

    def _build_command(
        self,
        gbak_path: str,
        database_path: str,
        backup_path: str,
        db_config: DatabaseConfig | None,
    ) -> list[str]:
        """Construye ``gbak -b`` con los parámetros de conexión disponibles.

        Se usan los nombres completos de switch (``-user``, ``-password``,
        ``-role``): ``-u`` choca con ``-use_all_space``, ``-p`` con
        ``-page_size`` y ``-r`` con ``-recreate_database``. ``gbak`` no admite
        ``-charset``, así que ``DatabaseConfig.charset`` no se pasa.
        """
        command = [gbak_path, "-b", database_path, backup_path]
        if db_config is not None:
            for flag, value in (
                ("-user", db_config.user),
                ("-password", db_config.password),
                ("-role", db_config.role),
            ):
                if value:
                    command.extend((flag, value))
        return command

    @staticmethod
    def _check_completed(completed: subprocess.CompletedProcess[str]) -> None:
        """Falla si gbak devolvió código distinto de 0 o un patrón conocido."""
        stderr = completed.stderr or ""
        lowered = stderr.lower()
        if completed.returncode != 0 or any(pattern in lowered for pattern in _ERROR_PATTERNS):
            raise GbakExecutionError(completed.returncode, completed.stdout or "", stderr)

    @staticmethod
    def _validate_backup_file(path: Path) -> int:
        """Valida el ``.fbk`` (existe, no vacío y legible) y devuelve su tamaño."""
        if not path.exists():
            raise BackupError(f"gbak no generó el archivo de respaldo: {path}")
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise BackupError(f"no se pudo leer el archivo de respaldo {path}: {exc}") from exc
        if size <= 0:
            raise BackupError(f"el archivo de respaldo está vacío: {path}")
        if not os.access(path, os.R_OK):
            raise BackupError(f"el archivo de respaldo no es legible: {path}")
        return size

    @staticmethod
    def _failure(database_name: str, start_time: float, message: str) -> BackupResult:
        """Construye y registra un ``BackupResult`` fallido."""
        duration = time.perf_counter() - start_time
        logger.error("Respaldo fallido de '%s': %s", database_name, message)
        return BackupResult(
            success=False,
            database_name=database_name,
            duration_seconds=duration,
            error_message=message,
        )

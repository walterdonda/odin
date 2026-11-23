"""Ejecución de respaldos con el motor de la base (Etapa 2).

Responsabilidades:

- Despachar por ``databases[].type`` al motor correspondiente (Firebird →
  ``gbak -b``; PostgreSQL → ``pg_dump`` con el comando de §2.1) y resolver su
  binario con la precedencia §3.7: ``databases[].*_path`` explícito > del
  ejecutor > auto-detección; si no hay ninguno, ``EngineNotFoundError`` con el
  mensaje del motor.
- Ejecutar el comando que construye el motor por base con timeout por motor
  (``gbak_timeout_sec``/``pg_dump_timeout_sec``), con el ``env`` del motor
  (pg_dump: ``PGPASSWORD``, nunca en argv ni en logs) y enmascarando en los
  logs los secretos declarados en ``Engine.secret_flags``.
- Validar el archivo resultante (existe, tamaño > 0 y legible).
- Recorrer todas las bases de la configuración de forma secuencial y con
  aislamiento de fallos, creando ``local.work_dir`` si no existe y nombrando
  los archivos ``<nombre_bd>_<timestamp><extensión>`` según el motor
  (``.fbk`` para Firebird, ``.dump`` para PostgreSQL).

Los errores operativos esperados (timeout, fallo del binario, binario
inexistente, archivo inválido) no se propagan como excepción desde
``run_backup``: se reportan en el ``BackupResult`` con ``success=False`` y un
mensaje claro, de modo que el lote continúe con la próxima base.
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

from odin.config import DatabaseConfig, DbEngine
from odin.engines import Engine, EngineError, EngineExecutionError
from odin.engines.firebird import FirebirdEngine
from odin.engines.postgresql import PostgreSQLEngine

logger = logging.getLogger(__name__)

DEFAULT_GBACK_TIMEOUT_SEC = 7200
DEFAULT_PG_DUMP_TIMEOUT_SEC = 7200
_TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"


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


def _masked_command(command: Sequence[str], secret_flags: Sequence[str]) -> str:
    """Representación del comando con los valores secretos enmascarados."""
    masked = list(command)
    for index, argument in enumerate(masked[:-1]):
        if argument in secret_flags:
            masked[index + 1] = "********"
    return " ".join(masked)


def _database_target(database: DatabaseConfig) -> str:
    """Identificador legible de la base para los logs, según el motor."""
    if database.type is DbEngine.POSTGRESQL:
        if database.host and database.dbname:
            return f"{database.host}/{database.dbname}"
        return database.dbname or database.host or ""
    return database.connection or ""


class BackupExecutor:
    """Ejecuta el respaldo por base con el motor de la entrada y reporta el resultado.

    El dispatch por ``databases[].type`` (ticket 03) elige entre
    ``FirebirdEngine`` y ``PostgreSQLEngine``; cada motor aporta su binario,
    comando, extensión, patrones de error y variables de entorno. El timeout
    es por motor: ``timeout`` (gbak) y ``pg_dump_timeout`` (pg_dump), con la
    precedencia ``databases[].*_timeout_sec`` > valor del ejecutor (§3.7).
    """

    def __init__(
        self,
        gbak_path: str | Path | None = None,
        timeout: int = DEFAULT_GBACK_TIMEOUT_SEC,
        pg_dump_path: str | Path | None = None,
        pg_dump_timeout: int = DEFAULT_PG_DUMP_TIMEOUT_SEC,
    ) -> None:
        self.gbak_path = None if gbak_path is None else str(gbak_path)
        self.timeout = timeout
        self.pg_dump_path = None if pg_dump_path is None else str(pg_dump_path)
        self.pg_dump_timeout = pg_dump_timeout
        self._engines: dict[DbEngine, Engine] = {
            DbEngine.FIREBIRD: FirebirdEngine(gbak_path),
            DbEngine.POSTGRESQL: PostgreSQLEngine(pg_dump_path),
        }

    def _engine_for(self, db_config: DatabaseConfig | None) -> Engine:
        """Motor según ``databases[].type`` (Firebird por defecto sin config)."""
        if db_config is not None and db_config.type is DbEngine.POSTGRESQL:
            return self._engines[DbEngine.POSTGRESQL]
        return self._engines[DbEngine.FIREBIRD]

    def _timeout_for(self, db_config: DatabaseConfig | None) -> int:
        """Timeout efectivo del motor de la entrada (precedencia §3.7).

        El override por base (``databases[].*_timeout_sec``) manda sobre el
        del ejecutor; ausente/``null`` cae al valor del ejecutor.
        """
        if db_config is not None and db_config.type is DbEngine.POSTGRESQL:
            return db_config.pg_dump_timeout_sec or self.pg_dump_timeout
        if db_config is not None:
            return db_config.gbak_timeout_sec or self.timeout
        return self.timeout

    def run_backup(
        self,
        database_name: str,
        database_path: str,
        backup_path: str,
        db_config: DatabaseConfig | None = None,
    ) -> BackupResult:
        """Ejecuta el respaldo con el comando del motor y valida el archivo.

        No propaga errores operativos: timeout, fallo del binario, binario
        inexistente o archivo inválido se devuelven como ``BackupResult`` con
        ``success=False``.
        """
        start_time = time.perf_counter()
        target = Path(backup_path)
        binary_path: str | None = None
        engine = self._engine_for(db_config)
        timeout = self._timeout_for(db_config)

        try:
            binary_path = engine.resolve_binary(db_config)
            command = engine.build_command(binary_path, database_path, backup_path, db_config)
            logger.info(
                "Ejecutando %s para '%s': %s",
                engine.binary_name,
                database_name,
                _masked_command(command, engine.secret_flags),
            )
            env = engine.env(db_config)
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, **env} if env else None,
            )
            self._check_completed(engine, completed)
            file_size = self._validate_backup_file(engine, target)
        except subprocess.TimeoutExpired:
            return self._failure(
                database_name,
                start_time,
                f"{engine.binary_name} excedió el timeout de {timeout} s",
            )
        except OSError as exc:
            return self._failure(
                database_name,
                start_time,
                f"no se pudo ejecutar {engine.binary_name} ({binary_path}): {exc}",
            )
        except EngineError as exc:
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
        """Respalda una base con el ejecutor del lote (una instancia por lote).

        Reusar ``self.run_backup`` —en vez de construir un ``BackupExecutor``
        por base— conserva el cache del finder de ``Engine.resolve_binary``:
        la auto-detección corre una sola vez por motor y por lote. El
        override por base (binario y timeout, precedencia §3.7) lo resuelven
        ``resolve_binary`` vía ``_configured_binary`` y ``_timeout_for``.
        """
        timestamp = datetime.now().strftime(_TIMESTAMP_FORMAT)
        engine = self._engine_for(database)
        backup_path = work_dir / f"{database.name}_{timestamp}{engine.extension}"
        logger.info("Procesando base '%s' (%s)", database.name, _database_target(database))
        # La validación de config exige ``connection`` para type=firebird; el
        # ``or ""`` es el fallback de tipos para un modelo sin validar.
        connection = database.connection or ""
        return self.run_backup(database.name, connection, str(backup_path), database)

    def _check_completed(
        self, engine: Engine, completed: subprocess.CompletedProcess[str]
    ) -> None:
        """Falla si el binario devolvió código distinto de 0 o un patrón conocido."""
        stderr = completed.stderr or ""
        lowered = stderr.lower()
        if completed.returncode != 0 or any(
            pattern in lowered for pattern in engine.error_patterns
        ):
            raise EngineExecutionError(
                engine.binary_name, completed.returncode, completed.stdout or "", stderr
            )

    def _validate_backup_file(self, engine: Engine, path: Path) -> int:
        """Valida el artefacto (existe, no vacío y legible) y devuelve su tamaño."""
        binary_name = engine.binary_name
        if not path.exists():
            raise EngineError(f"{binary_name} no generó el archivo de respaldo: {path}")
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise EngineError(f"no se pudo leer el archivo de respaldo {path}: {exc}") from exc
        if size <= 0:
            raise EngineError(f"el archivo de respaldo está vacío: {path}")
        if not os.access(path, os.R_OK):
            raise EngineError(f"el archivo de respaldo no es legible: {path}")
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

import datetime
import logging
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

logger = logging.getLogger(__name__)


class BackupError(Exception):
    """Base exception for backup operations."""
    pass


class GbakExecutionError(BackupError):
    """Raised when gbak execution fails."""

    def __init__(self, returncode: int, stdout: str, stderr: str):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(f"gbak failed with exit and error: {stderr}")


@dataclass(frozen=True, slots=True)
class BackupResult:
    """Encapsulates the outcome of a backup operation."""

    success: bool
    database_name: str
    backup_path: Path | None
    file_size_bytes: int | None
    duration_seconds: float
    error_message: str | None


@dataclass(frozen=True, slots=True)
class BatchBackupResult:
    """Encapsulates the outcome of multiple backup operations."""

    results: Sequence[BackupResult]
    success: bool
    total_duration_seconds: float


class BackupExecutor:
    """Handles the execution of gbak commands."""

    def __init__(self, gbak_path: str, timeout: int = 300):
        self.gbak_path = gbak_path
        self.timeout = timeout
        # Known error patterns in gbak/gbint output
        self.error_patterns = [
            "not a valid database",
            "permission denied",
            "database is in enough",
            "database is in use",
        ]

    def run_backup(
        self,
        database_name: str,
        database_path: str,
        backup_path: str,
        db_config: Optional[DatabaseConfig] = None,
    ) -> BackupResult:
        """
        Executes 'gbak -b' to create a backup.

        Args:
            database_name: Name of the database.
            database_path: Path to the source Firepi database.
            backup_path: Path where the .fbk file will be created.
            db_config: Optional configuration containing user, password, role, and charset.

        Returns:
            A BackupResult object representing the outcome.
        """
        command = [self.gbak_path, "-b", database_path, backup_path]

        if db_config:
            if db_config.user:
                command.extend(["-U", db_config.user])
            if db_config.password:
                command.extend(["-P", db_config.password])
            if db_config.role:
                command.extend(["-R", db_config.role])
            if db_config.charset:
                command.extend(["-E", db_config.charset])

        start_time = time.perf_counter()
        error_message = None
        success = False
        backup_path_obj = Path(backup_path) if backup_path else None
        file_size = None

        # For logging, we want to hide the password
        log_command = list(command)
        if db_config and db_config.password:
            for i, arg in enumerate(log_command):
                if arg == "-P" and i + 1 < len(log_command):
                    log_command[i + 1] = "********"
        display_command = " ".join(log_command)
        logger.info(f"Executing command: {display_command}")

        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=self.timeout)
            stdout = result.stdout
            stderr = result.stderr

            # Check for known error patterns in stderr
            for pattern in self.error_patterns:
                if pattern in stderr.lower():
                    raise GbakExecutionError(result.returncode, stdout, stderr)

            if result.returncode != 0:
                raise GbakExecutionError(result.returncode, stdout, stderr)

            logger.info("Backup completed successfully.")
            success = True
            if backup_path_obj.exists():
                file_size = backup_path_obj.stat().st_size

        except subprocess.TimeoutExpired as e:
            logger.error(f"Backup timed out after {self.timeout} seconds.")
            error_message = f"Timeout after {self.timeout} seconds"
            raise e
        except GbakExecutionError as e:
            error_message = str(e)
        except Exception as e:
            logger.error(f"Unexpected error during backup execution: {e}")
            error_message = str(e)
        finally:
            duration = time.perf_counter() - start_time

        return BackupResult(
            success=success,
            database_name=database_name,
            backup_path=backup_path_obj if success else None,
            file_size_bytes=file_size,
            duration_seconds=duration,
            error_message=error_message,
        )

    def run_batch_backup(
        self,
            databases: Sequence["DatabaseConfig"],
            work_dir: Path,
        ) -> BatchBackupResult:
        """
        Iterates over a list of database configurations and executes backups.

        Args:
            databases: Sequence of DatabaseConfig objects.
            work_dir: Base directory where backups will be stored.

        Returns:
            A BatchBackupResult object representing the outcome of all backups.
        """
        results: list[BackupResult] = []
        start_time = time.perf_counter()
        all_success = True

        for db in databases:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_filename = f"{db.name}_{timestamp}.fbk"
            backup_path = work_dir / backup_filename

            logger.info(f"Processing database: {db.name}")

            try:
                # Use gbak_path from config if available, otherwise use default
                gbak_path = db.gbak_path if db.gbak_path else self.gbak_path
                executor = BackupExecutor(gbak_path, timeout=db.gbak_timeout_sec or self.timeout)

                result = executor.run_backup(
                    database_name=db.name,
                    database_path=db.connection,
                    backup_path=str(backup_path),
                    db_config=db,
                )
                results.append(result)

                if not result.success:
                    all_success = False
                    logger.error(f"Backup failed for {db.name}: {result.error_message}")
                else:
                    logger.info(f"Backup successful for {db.name}: {backup_path}")

            except Exception as e:
                all_success = False
                logger.error(f"Error during backup of {db.name}: {e}")
                results.append(BackupResult(success=False, database_name=db.name, error_message=str(e)))

        total_duration = time.perf_counter() - start_time
        return BatchBackupResult(
            results=results, success=all_success, total_duration_seconds=total_duration
        )


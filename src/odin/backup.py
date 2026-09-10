import subprocess
import logging
import time
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

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

    def run_backup(self, database_name: str, database_path: str, backup_path: str) -> BackupResult:
        """
        Executes 'gbak -b' to create a backup.
        
        Args:
            database_name: Name of the database.
            database_path: Path to the source Firebird database.
            backup_path: Path where the .fbk file will be created.

        Returns:
            A BackupResult object representing the outcome.
        """
        command = [
            self.gbak_path,
            "-b",
            database_path,
            backup_path
        ]

        start_time = time.perf_counter()
        error_message = None
        success = False
        backup_path_obj = Path(backup_path) if backup_path else None
        file_size = None

        try:
            logger.info(f"Starting backup: {' '.join(command)}")
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False  # We handle returncode manually to parse stderr
            )

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
            error_message=error_message
        )


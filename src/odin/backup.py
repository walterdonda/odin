import subprocess
import logging
from typing import Optional, List

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
        super().__init__(f"gbak failed with exit code {returncode}: {stderr}")

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

    def run_backup(self, database_path: str, backup_path: str) -> bool:
        """
        Executes 'gbak -b' to create a backup.
        
        Args:
            database_path: Path to the source Firebird database.
            backup_path: Path where the .fbk file will be created.

        Returns:
            True if the backup was successful.

        Raises:
            GbakExecutionError: If the process returns a non-zero exit code or hits a known error pattern.
            subprocess.TimeoutExpired: If the execution exceeds the timeout.
        """
        command = [
            self.gbak_path,
            "-b",
            database_path,
            backup_path
        ]

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
            return True

        except subprocess.TimeoutExpired as e:
            logger.error(f"Backup timed out after {self.timeout} seconds.")
            raise e
        except Exception as e:
            if isinstance(e, GbakExecutionError):
                raise e
            logger.error(f"Unexpected error during backup execution: {e}")
            return False

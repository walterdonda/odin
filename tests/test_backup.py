import unittest
from unittest.mock import patch, MagicMock
import subprocess
from src.odin.backup import BackupExecutor, GbakExecutionError

class TestBackupExecutor(unittest.TestCase):
    def setUp(self):
        self.executor = BackupExecutor(gbak_path="/usr/bin/gbak", timeout=10)

    @patch("subprocess.run")
    def test_run_backup_success(self, mock_run):
        # Configure mock for success
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Backup successful",
            stderr=""
        )
        
        result = self.executor.run_backup("db_name", "db.fdb", "db.fbk")
        self.assertTrue(result.success)
        mock_run.assert_called_once()

    @patch("subprocess.run")
    def test_run_backup_failure_exit_code(self, mock_run):
        # Configure mock for failure via exit code
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Some error occurred"
        )
        
        result = self.executor.run_backup("db_name", "db.fdb", "db.fbk")
        self.assertFalse(result.success)
        self.assertIn("Some error occurred", result.error_message)



    @patch("subprocess.run")
    def test_run_backup_failure_pattern(self, mock_run):
        # Configure mock for failure via error pattern in stderr
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr="Error: not a valid database"
        )
        
        result = self.executor.run_backup("db_name", "db.int", "db.fbk")
        self.assertFalse(result.success)
        self.assertIn("not a valid database", result.error_message)

    @patch("subprocess.run")
    def test_run_backup_timeout(self, mock_run):
        # Configure mock to raise TimeoutExpired
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["gbak"], timeout=10)
        
        with self.assertRaises(subprocess.TimeoutExpired):
            self.executor.run_backup("db_name", "db.fdb", "db.fbk")

if __name__ == "__main__":
    unittest.main()

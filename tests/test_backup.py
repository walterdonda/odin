import unittest
from unittest.mock import patch, MagicMock
import subprocess
from pathlib import Path
from datetime import datetime
from src.odin.backup import BackupExecutor, GbakExecutionError, BackupResult, BatchBackupResult
from src.odin.config import DatabaseConfig

class TestBackupExecutor(unittest.TestCase):
    def setUp(self):
        self.executor = BackupExecutor(gbak_path="/usr/bin/gbak", timeout=10)
        self.db_config = DatabaseConfig(
            name="test_db",
            connection="test_db.fdb",
            user="sysdba",
            password="masterkey"
        )

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
    def test_run_backup_with_config_success(self, mock_run):
        # Configure mock for success
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Backup successful",
            stderr=""
        )
        
        result = self.executor.run_backup(
            "db_name", "db.fdb", "db.fbk", 
            db_config=self.db_config
        )
        self.assertTrue(result.success)
        
        # Check if command includes the flags
        args, kwargs = mock_run.call_args
        command = args[0]
        self.assertIn("-U", command)
        self.assertIn("sysdba", command)
        self.assertIn("-P", command)
        self.assertIn("masterkey", command)

    @patch("subprocess.run")
    def test_run_backup_with_config_charset_role(self, mock_run):
        # Configure mock for success
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Backup successful",
            stderr=""
        )
        
        result = self.executor.run_backup(
            "db_name", "db.fdb", "db.fbk", 
            db_config=self.db_config
        )
        self.assertTrue(result.success)
        
        # Check if command includes the flags
        args, kwargs = mock_run.call_args
        command = args[0]
        # Since we are testing charset and role, we'll add them to the config
        custom_config = DatabaseConfig(
            name="test_db",
            connection="test_db.fdb",
            user="sysdba",
            password="masterkey",
            charset="UTF8",
            role="admin"
        )
        
        result = self.executor.run_backup(
            "db_name", "db.fdb", "db.fbk", 
            db_config=custom_config
        )
        
        args, kwargs = mock_run.call_args
        command = args[0]
        self.assertIn("-E", command)
        self.assertIn("UTF8", command)
        self.assertIn("-R", command)
        self.assertIn("admin", command)

    @patch("subprocess.run")
    def test_run_backup_with_config_password_masking(self, mock_run):
        # Configure mock for success
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Backup successful",
            stderr=""
        )
        
        with self.assertLogs('src.odin.backup', level='INFO') as cm:
            self.executor.run_backup(
                "db_name", "db.fdb", "db.fbk", 
                db_config=self.db_config
            )
            
            # Check if the password is masked in the log
            log_output = "".join(cm.output)
            self.assertIn("********", log_output)
            self.assertNotIn("masterkey", log_output)


    @patch("subprocess.run")
    def test_run_backup_failure_exit_code(self, mock_run):
        # Configure mock for failure via exit code
        mock_run.return0 = 1
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

    @patch("subprocess.run")
    def test_run_batch_backup_success(self, mock_run):
        # Configure mock for success
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Backup successful",
            stderr=""
        )
        
        # Create dummy files for the mock to work with (for checking existence)
        # Since we are mocking subprocess.run and it doesn't actually run, 
        # we don't need real files, but the code checks if backup_path_obj.exists()
        # We can mock Path.exists via patch
        
        with patch("src.odin.backup.Path.exists", return_value=True), \
             patch("src.odin.backup.Path.stat") as mock_stat:
            mock_stat.return_value.st_size = 1024
            
            db_configs = [
                self.db_config,
                DatabaseConfig(name="db2", connection="db2.fdb", user="sysdba", password="masterkey")
            ]
            work_dir = Path("/tmp")
            
            batch_result = self.executor.run_batch_backup(db_configs, work_dir)
            
            self.assertTrue(batch_result.success)
            self.assertEqual(len(batch_result.results), 2)
            self.assertEqual(batch_result.results[0].database_name, "test_db")
            self.assertEqual(batch_result.results[1].database_name, "db2")

    @patch("subprocess.run")
    def test_run_batch_backup_partial_failure(self, mock_run):
        # First succeeds, second fails
        def side_effect(command, **kwargs):
            if "db2.fdb" in command:
                return MagicMock(returncode=1, stdout="", stderr="error in db2")
            return MagicMock(returncode=0, stdout="success", stderr="")
        
        mock_run.side_effect = side_effect
        
        db_configs = [
            self.db_config,
            DatabaseConfig(name="db2", connection="db2.fdb", user="sysdba", password="masterkey")
        ]
        work_dir = Path("/tmp")
        
        batch_result = self.executor.run_batch_backup(db_configs, work_dir)
        
        self.assertFalse(batch_result.success)
        self.assertEqual(len(batch_result.results), 2)
        self.assertTrue(batch_result.results[0].success)
        self.assertFalse(batch_result.results[1].success)

if __name__ == "__main__":
    unittest.main()

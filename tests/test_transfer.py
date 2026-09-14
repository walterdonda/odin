import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import paramiko

from odin.transfer import AuthenticationError, ConnectionError, SFTPTransfer, TransferError


class TestSFTPTransfer(unittest.TestCase):
    def setUp(self):
        self.hostname = "example.com"
        self.username = "testuser"
        self.password = "testpassword"
        self.transfer = SFTPTransfer(
            hostname=self.hostname,
            username=self.username,
            password=self.password,
            sftp_retry_backoff_base=0.001,
            sftp_retry_max_delay_sec=0.001,
        )

    @patch("paramiko.SSHClient")
    def test_connect_success_password(self, mock_ssh_client):
        mock_client_instance = mock_ssh_client.return_value
        mock_sftp_instance = MagicMock()
        mock_client_instance.open_sftp.return_value = mock_sftp_instance

        self.transfer.connect()

        mock_client_instance.connect.assert_called_once()
        self.assertEqual(self.transfer._sftp, mock_sftp_instance)

    @patch("paramiko.SSHClient")
    def test_connect_auth_failure(self, mock_ssh_client):
        mock_client_instance = mock_ssh_client.return_value
        mock_client_instance.connect.side_effect = paramiko.AuthenticationException("Auth failed")

        with self.assertRaises(AuthenticationError):
            self.transfer.connect()

    @patch("paramiko.SSHClient")
    def test_connect_connection_failure(self, mock_ssh_client):
        mock_client_instance = mock_ssh_client.return_value
        mock_client_instance.connect.side_effect = paramiko.SSHException("SSH error")

        with self.assertRaises(ConnectionError):
            self.transfer.connect()

    @patch("paramiko.SSHClient")
    def test_connect_policy_accept_new(self, mock_ssh_client):
        self.transfer.host_keys_policy = "accept-new"
        mock_client_instance = mock_ssh_client.return_value
        mock_sftp_instance = MagicMock()
        mock_client_instance.open_sftp.return_value = mock_sftp_instance

        self.transfer.connect()

        args, _ = mock_client_instance.set_missing_host_key_policy.call_args
        self.assertIsInstance(args[0], paramiko.AutoAddPolicy)

    @patch("paramiko.SSHClient")
    def test_connect_policy_insecure_fixed(self, mock_ssh_client):
        self.transfer.host_keys_policy = "insecure"
        mock_client_instance = mock_ssh_client.return_value
        mock_sftp_instance = MagicMock()
        mock_client_instance.open_sftp.return_value = mock_sftp_instance

        self.transfer.connect()

        args, _ = mock_client_instance.set_missing_host_key_policy.call_args
        self.assertIsInstance(args[0], paramiko.WarningPolicy)

    @patch("paramiko.SSHClient")
    def test_connect_policy_known_hosts(self, mock_ssh_client):
        self.transfer.host_keys_policy = "known_hosts"
        mock_client_instance = mock_ssh_client.return_value
        mock_sftp_instance = MagicMock()
        mock_client_instance.open_sftp.return_value = mock_sftp_instance

        self.transfer.connect()

        mock_client_instance.load_system_host_keys.assert_called()

    @patch("paramiko.SSHClient")
    def test_upload_success_with_verification(self, mock_ssh_client):
        mock_client_instance = mock_ssh_client.return_value
        mock_sftp_instance = MagicMock()
        mock_client_instance.open_sftp.return_value = mock_sftp_instance

        # Mock stat for remote file
        mock_stat = MagicMock()
        mock_stat.st_size = 100
        mock_sftp_instance.stat.return_value = mock_stat

        self.transfer.connect()

        local_file = Path("/tmp/test.file")
        local_file.write_text("a" * 100)

        remote_path = "/remote/path/test.file"

        with patch("odin.transfer.logger"):
            self.transfer.upload(local_file, remote_path)

        # Verify directory creation NOT called because they exist
        mock_sftp_instance.mkdir.assert_not_called()
        # Verify put
        mock_sftp_instance.put.assert_called_once_with(str(local_file), remote_path)
        # Verify integrity check
        mock_sftp_instance.stat.assert_called_with(remote_path)

        # Cleanup
        if local_file.exists():
            local_file.unlink()

    @patch("paramiko.SSHClient")
    def test_upload_with_directory_creation(self, mock_ssh_client):
        mock_client_instance = mock_ssh_client.return_value
        mock_sftp_instance = MagicMock()
        mock_client_instance.open_sftp.return_value = mock_sftp_instance

        # Use side_effect to allow first stat to fail (directory creation)
        # and second stat to succeed (integrity check)
        def stat_side_effect(path):
            if "/remote/path" in path:
                mock_stat = MagicMock()
                mock_stat.st_size = 100
                return mock_stat
            raise OSError("Not found")

        mock_sftp_instance.stat.side_effect = stat_side_effect

        self.transfer.connect()

        local_file = Path("/tmp/test.file")
        local_file.write_text("a" * 100)

        remote_path = "/remote/path/test.file"

        with patch("odin.transfer.logger"):
            self.transfer.upload(local_file, remote_path)

        # Verify mkdir was called for the directories
        self.assertTrue(mock_sftp_instance.mkdir.called)
        # Verify put
        mock_sftp_instance.put.assert_called_once_with(str(local_file), remote_path)

        # Cleanup
        if local_file.exists():
            local_file.unlink()

        mock_client_instance = mock_ssh_client.return_value
        mock_sftp_instance = MagicMock()
        mock_client_instance.open_sftp.return_value = mock_sftp_instance

        # Mock stat for remote file with WRONG size
        mock_stat = MagicMock()
        mock_stat.st_size = 50 # Wrong size
        mock_sftp_instance.stat.return_value = mock_stat

        self.transfer.connect()

        local_file = Path("/tmp/test.file")
        local_file.write_text("a" * 100)

        remote_path = "/remote/path/test.file"

        with self.assertRaises(TransferError) as cm:
            self.transfer.upload(local_file, remote_path)

        self.assertIn("Integrity check failed", str(cm.exception))

        # Cleanup
        if local_file.exists():
            local_file.unlink()

    @patch("paramiko.SSHClient")
    def test_upload_failure(self, mock_ssh_client):
        mock_client_instance = mock_ssh_client.return_value
        mock_sftp_instance = MagicMock()
        mock_client_instance.open_sftp.return_value = mock_sftp_instance

        self.transfer.connect()

        mock_sftp_instance.put.side_effect = Exception("Disk full")

        local_file = Path("/tmp/int.file")
        local_file.write_text("a" * 100)
        remote_path = "/remote/path/test.file"

        with self.assertRaises(TransferError):
            self.transfer.upload(local_file, remote_path)

        # Cleanup
        if local_file.exists():
            local_file.unlink()

if __name__ == "__main__":
    unittest.main()

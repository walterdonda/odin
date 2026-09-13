import unittest
from unittest.mock import MagicMock, patch
import socket
import paramiko
from src.odin.transfer import SFTPTransfer, AuthenticationError

class TestSFTPRetryLogic(unittest.TestCase):
    def setUp(self):
        self.transfer = SFTPTransfer(
            hostname="test.host",
            sftp_retries=3,
            sftp_retry_backoff_base=0.1, # Small base for fast tests
            sftp_retry_max_delay_sec=1.0
        )

    @patch('src.odin.transfer.logger')
    def test_retry_on_connection_error(self, mock_logger):
        # Simulate a connection error that should trigger a retry
        mock_op = MagicMock()
        mock_op.side_effect = [socket.error("Connection refused"), "Success"]
        
        result = self.transfer._execute_with_retry(mock_op, "test_op")
        
        self.assertEqual(result, "Success")
        self.assertEqual(mock_op.call_count, 2)
        mock_logger.warning.assert_called()

    @patch('src.odin.transfer.logger')
    def test_no_retry_on_authentication_error(self, mock_logger):
        # Simulate an authentication error that should NOT trigger a retry
        mock_op = MagicMock()
        mock_op.side_effect = AuthenticationError("Invalid password")
        
        with self.assertRaises(AuthenticationError):
            self.transfer._execute_with_retry(mock_op, "test_op")
        
        # Should only have called once
        self.assertEqual(mock_op.call_count, 1)
        mock_logger.warning.assert_not_called()

    @patch('src.odin.transfer.logger')
    def test_max_retries_exceeded(self, mock_logger):
        # Simulate persistent failure
        mock_op = MagicMock()
        mock_op.side_effect = socket.error("Permanent failure")
        
        with self.assertRaises(Exception) as context:
            self.transfer._execute_with_retry(mock_op, "test_op")
        
        self.assertIn("failed after max retries", str(context.exception))
        self.assertEqual(mock_op.call_count, 3)

if __name__ == '__main__':
    unittest.main()

from unittest.mock import MagicMock

import paramiko
import pytest

from odin.transfer import ConnectionError, SFTPTransfer


@pytest.fixture
def transfer_params():
    return {
        "hostname": "test.example.com",
        "username": "user",
        "password": "password",
        "sftp_retries": 3,
        "sftp_retry_backoff_base": 0.01,
        "sftp_retry_max_delay_sec": 0.05,
    }


def test_execute_with_retry_success(transfer_params):
    transfer = SFTPTransfer(**transfer_params)
    mock_op = MagicMock(return_value="success")

    result = transfer._execute_with_retry(mock_op, "test_op")

    assert result == "success"
    assert mock_op.call_count == 1


def test_execute_with_retry_failure_after_retries(transfer_params):
    transfer = SFTPTransfer(**transfer_params)
    mock_op = MagicMock(side_effect=OSError("Connection reset by peer"))

    with pytest.raises(ConnectionError) as excinfo:
        transfer._execute_with_retry(mock_op, "test_op")

    assert "failed after max retries" in str(excinfo.value)
    assert mock_op.call_count == 3


def test_execute_with_retry_no_retry_on_auth_error(transfer_params):
    transfer = SFTPTransfer(**transfer_params)
    # paramiko.AuthenticationException es subclase de SSHException: no debe reintentarse.
    mock_op = MagicMock(side_effect=paramiko.AuthenticationException("Authentication failed"))

    with pytest.raises(paramiko.AuthenticationException):
        transfer._execute_with_retry(mock_op, "test_op")

    assert mock_op.call_count == 1


def test_execute_with_retry_backoff_timing(transfer_params):
    transfer = SFTPTransfer(**transfer_params)
    mock_op = MagicMock(side_effect=[OSError("Fail"), OSError("Fail"), "success"])

    result = transfer._execute_with_retry(mock_op, "test_op")

    assert result == "success"
    assert mock_op.call_count == 3

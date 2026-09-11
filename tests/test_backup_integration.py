import pytest
import subprocess
import time
from pathlib import Path
from src.odin.backup import BackupExecutor, BackupResult
from src.odin.config import DatabaseConfig

@pytest.mark.integration
@pytest.mark.skipif(
    subprocess.run(["docker", "--version"], capture_output=True).returncode != 0,
    reason="Docker not installed"
)
def test_firebird_integration_backup_flow(tmp_path):
    """
    Integration test: 
    1. Start Firebird in Docker.
    2. Execute gbak via BackupExecutor to backup the default database.
    3. Verify .fbk file creation.
    """
    container_name = "firebird-test"
    port = "3050"
    
    # Cleanup previous container if exists
    subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)

    # 1. Start Firebird container
    start_cmd = [
        "docker", "run", "--name", container_name,
        "-p", f"{port}:3050",
        "-e", "FIREBIRD_PASSWORD=masterkey",
        "-d", "jacobalberty/firebird:latest"
    ]

    try:
        process = subprocess.run(start_cmd, capture_output=True, text=True)
        if process.returncode != 0:
            pytest.skip(f"Failed to start Firebird container: {process.stderr}")
    except Exception as e:
        pytest.skip(f"Error starting Firebird container: {e}")

    try:
        # Wait for Firebird to be ready
        time.sleep(15) 

        # We'll assume gbak is in PATH or we find it.
        gbak_path = "gbak" 
        
        # We'll use the default database connection string. 
        # In many Firebird images, the default DB is accessible via localhost:3050:/databases/system.fdb or similar.
        # However, simpler: we just try to backup the default connection.
        db_connection = f"localhost:{port}/sysdba"
        backup_file = tmp_path / "test_backup.fbk"
        
        executor = BackupExecutor(gbak_path=gbak_path, timeout=60)
        
        # We'll try to backup the default database.
        # Note: Since we don't know the exact path in the container, we try the system db.
        # Using sysdba as user and masterkey as password.
        db_config = DatabaseConfig(
            name="test_db",
            connection=db_connection,
            user="sysdba",
            password="masterkey",
            role=None,
            charset=None,
            gbak_path=None,
            gbak_timeout_sec=30
        )
        
        result = executor.run_backup(
            database_name=db_config.name,
            database_path=db_config.connection,
            backup_path=str(backup_file),
            db_config=db_config
        )
        
        assert result.success is True, f"Backup failed: {result.error_message}"
        assert backup_file.exists()
        assert backup_file.stat().st_size > 0

    finally:
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)

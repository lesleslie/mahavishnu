"""Unit tests for backup and recovery functionality."""
import pytest
import asyncio
import tempfile
import os
from pathlib import Path
from unittest.mock import Mock, AsyncMock, MagicMock
from datetime import datetime, timedelta
from mahavishnu.core.backup_recovery import BackupManager, DisasterRecoveryManager, BackupInfo
from mahavishnu.core.app import MahavishnuApp


@pytest.fixture
def mock_app():
    """Create a mock app for testing."""
    app = Mock(spec=MahavishnuApp)
    app.observability = Mock()
    app.opensearch_integration = Mock()
    app.workflow_state_manager = Mock()
    app.adapters = {}
    app.config = Mock()
    app.config.backup_directory = "./test_backups"
    return app


@pytest.mark.asyncio
async def test_backup_info_structure():
    """Test the structure of BackupInfo dataclass."""
    backup_info = BackupInfo(
        backup_id="test_backup_123",
        timestamp=datetime.now(),
        size_bytes=1024,
        location="/path/to/backup.tar.gz",
        status="completed",
        files_backed_up=10,
        checksum="abc123"
    )
    
    # Verify all fields are set correctly
    assert backup_info.backup_id == "test_backup_123"
    assert isinstance(backup_info.timestamp, datetime)
    assert backup_info.size_bytes == 1024
    assert backup_info.location == "/path/to/backup.tar.gz"
    assert backup_info.status == "completed"
    assert backup_info.files_backed_up == 10
    assert backup_info.checksum == "abc123"


@pytest.mark.asyncio
async def test_backup_manager_initialization():
    """Test that BackupManager initializes correctly."""
    app = Mock(spec=MahavishnuApp)
    app.config = Mock()
    app.config.backup_directory = "./test_backups"
    
    backup_manager = BackupManager(app)
    
    # Verify backup directory was created
    assert backup_manager.backup_dir.exists()
    assert backup_manager.backup_dir.name == "test_backups"


@pytest.mark.asyncio
async def test_backup_manager_create_backup():
    """Test creating a backup."""
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create a mock app with a temporary backup directory
        app = Mock(spec=MahavishnuApp)
        app.config = Mock()
        app.config.backup_directory = temp_dir
        app.workflow_state_manager = Mock()
        
        # Mock the workflow state manager
        app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])
        
        backup_manager = BackupManager(app)
        
        # Create a backup
        backup_info = await backup_manager.create_backup("full")
        
        # Verify backup was created
        assert backup_info is not None
        assert backup_info.backup_id.startswith("backup_")
        assert backup_info.status == "completed"
        assert backup_info.size_bytes > 0
        assert backup_info.files_backed_up >= 0  # Might be 0 if no workflows exist
        
        # Verify backup file exists
        backup_path = Path(backup_info.location)
        assert backup_path.exists()
        assert backup_path.name.endswith(".tar.gz")


@pytest.mark.asyncio
async def test_backup_manager_list_backups():
    """Test listing backups."""
    with tempfile.TemporaryDirectory() as temp_dir:
        app = Mock(spec=MahavishnuApp)
        app.config = Mock()
        app.config.backup_directory = temp_dir
        app.workflow_state_manager = Mock()
        
        # Mock the workflow state manager
        app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])
        
        backup_manager = BackupManager(app)
        
        # Initially no backups
        backups = await backup_manager.list_backups()
        assert len(backups) == 0
        
        # Create a backup
        await backup_manager.create_backup("full")
        
        # Now there should be one backup
        backups = await backup_manager.list_backups()
        assert len(backups) == 1
        assert backups[0].backup_id.startswith("backup_")


@pytest.mark.asyncio
async def test_backup_manager_get_backup_info():
    """Test getting backup info."""
    with tempfile.TemporaryDirectory() as temp_dir:
        app = Mock(spec=MahavishnuApp)
        app.config = Mock()
        app.config.backup_directory = temp_dir
        app.workflow_state_manager = Mock()
        
        # Mock the workflow state manager
        app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])
        
        backup_manager = BackupManager(app)
        
        # Create a backup
        backup_info = await backup_manager.create_backup("full")
        backup_id = backup_info.backup_id
        
        # Get backup info
        retrieved_info = await backup_manager.get_backup_info(backup_id)
        
        # Verify the info matches
        assert retrieved_info is not None
        assert retrieved_info.backup_id == backup_id
        assert retrieved_info.size_bytes > 0
        assert retrieved_info.status == "available"


@pytest.mark.asyncio
async def test_disaster_recovery_manager_initialization():
    """Test that DisasterRecoveryManager initializes correctly."""
    app = Mock(spec=MahavishnuApp)
    app.config = Mock()
    app.config.backup_directory = "./test_backups"
    app.workflow_state_manager = Mock()
    
    # Mock the workflow state manager
    app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])
    
    dr_manager = DisasterRecoveryManager(app)
    
    # Verify components were initialized
    assert dr_manager.backup_manager is not None
    assert dr_manager.app == app


@pytest.mark.asyncio
async def test_disaster_recovery_check():
    """Test disaster recovery check functionality."""
    with tempfile.TemporaryDirectory() as temp_dir:
        app = Mock(spec=MahavishnuApp)
        app.config = Mock()
        app.config.backup_directory = temp_dir
        app.workflow_state_manager = Mock()
        
        # Mock the workflow state manager
        app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])
        
        dr_manager = DisasterRecoveryManager(app)
        
        # Run disaster recovery check
        results = await dr_manager.run_disaster_recovery_check()
        
        # Verify structure of results
        assert "timestamp" in results
        assert "checks" in results
        assert "status" in results
        
        # Verify specific checks exist
        checks = results["checks"]
        assert "backups_available" in checks
        assert "backup_integrity" in checks
        assert "recent_backup" in checks


@pytest.mark.asyncio
async def test_disaster_recovery_procedures():
    """Test getting disaster recovery procedures."""
    app = Mock(spec=MahavishnuApp)
    app.config = Mock()
    app.config.backup_directory = "./test_backups"
    app.workflow_state_manager = Mock()
    
    # Mock the workflow state manager
    app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])
    
    dr_manager = DisasterRecoveryManager(app)
    
    # Get procedures
    procedures = await dr_manager.get_recovery_procedures()
    
    # Verify structure of procedures
    assert "procedures" in procedures
    assert "automation" in procedures
    
    proc_details = procedures["procedures"]
    assert "emergency_contact" in proc_details
    assert "recovery_steps" in proc_details
    assert "recovery_time_objective" in proc_details
    assert "recovery_point_objective" in proc_details
    assert "contact_info" in proc_details
    
    automation = procedures["automation"]
    assert "automatic_backup" in automation
    assert "backup_frequency" in automation
    assert "retention_policy" in automation
    assert "monitoring" in automation
    assert "alerts" in automation


@pytest.mark.asyncio
async def test_backup_and_recovery_cli_initialization():
    """Test that BackupAndRecoveryCLI initializes correctly."""
    from mahavishnu.core.backup_recovery import BackupAndRecoveryCLI
    
    app = Mock(spec=MahavishnuApp)
    app.config = Mock()
    app.config.backup_directory = "./test_backups"
    app.workflow_state_manager = Mock()
    
    # Mock the workflow state manager
    app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])
    
    cli = BackupAndRecoveryCLI(app)
    
    # Verify components were initialized
    assert cli.app == app
    assert cli.backup_manager is not None
    assert cli.recovery_manager is not None


@pytest.mark.asyncio
async def test_backup_cli_create_backup():
    """Test BackupAndRecoveryCLI create_backup functionality."""
    from mahavishnu.core.backup_recovery import BackupAndRecoveryCLI
    
    with tempfile.TemporaryDirectory() as temp_dir:
        app = Mock(spec=MahavishnuApp)
        app.config = Mock()
        app.config.backup_directory = temp_dir
        app.workflow_state_manager = Mock()
        
        # Mock the workflow state manager
        app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])
        
        cli = BackupAndRecoveryCLI(app)
        
        # Create a backup via CLI
        result = await cli.create_backup("full")
        
        # Verify result structure
        assert result["status"] == "success"
        assert "backup_id" in result
        assert "location" in result
        assert "size_mb" in result
        assert "timestamp" in result
        
        # Verify backup was created
        assert result["backup_id"].startswith("backup_")


@pytest.mark.asyncio
async def test_backup_cli_list_backups():
    """Test BackupAndRecoveryCLI list_backups functionality."""
    from mahavishnu.core.backup_recovery import BackupAndRecoveryCLI
    
    with tempfile.TemporaryDirectory() as temp_dir:
        app = Mock(spec=MahavishnuApp)
        app.config = Mock()
        app.config.backup_directory = temp_dir
        app.workflow_state_manager = Mock()
        
        # Mock the workflow state manager
        app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])
        
        cli = BackupAndRecoveryCLI(app)
        
        # Initially no backups
        result = await cli.list_backups()
        assert result["status"] == "success"
        assert result["total_count"] == 0
        assert len(result["backups"]) == 0
        
        # Create a backup
        await cli.create_backup("full")
        
        # Now there should be one backup
        result = await cli.list_backups()
        assert result["status"] == "success"
        assert result["total_count"] == 1
        assert len(result["backups"]) == 1


@pytest.mark.asyncio
async def test_backup_cli_run_dr_check():
    """Test BackupAndRecoveryCLI run_dr_check functionality."""
    from mahavishnu.core.backup_recovery import BackupAndRecoveryCLI
    
    with tempfile.TemporaryDirectory() as temp_dir:
        app = Mock(spec=MahavishnuApp)
        app.config = Mock()
        app.config.backup_directory = temp_dir
        app.workflow_state_manager = Mock()
        
        # Mock the workflow state manager
        app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])
        
        cli = BackupAndRecoveryCLI(app)
        
        # Run DR check via CLI
        result = await cli.run_disaster_recovery_check()
        
        # Verify result structure
        assert result["status"] in ["success", "needs_attention"]
        assert "results" in result
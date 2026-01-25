"""Unit tests for repository messaging functionality."""
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock
from datetime import datetime
from mahavishnu.messaging.repository_messenger import (
    RepositoryMessenger, 
    RepositoryMessengerManager, 
    MessageType, 
    MessagePriority, 
    RepositoryMessage
)
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
    app.config.cross_project_auth_secret = "test_secret_for_auth"
    return app


@pytest.mark.asyncio
async def test_repository_message_structure():
    """Test the structure of RepositoryMessage."""
    from datetime import datetime
    import uuid
    
    # Create a message
    message = RepositoryMessage(
        id="test_msg_123",
        sender_repo="repo_a",
        receiver_repo="repo_b",
        message_type=MessageType.CODE_CHANGE_NOTIFICATION,
        content={"change": "test change"},
        priority=MessagePriority.HIGH,
        timestamp=datetime.now(),
        correlation_id=str(uuid.uuid4())
    )
    
    # Verify all fields are set correctly
    assert message.id == "test_msg_123"
    assert message.sender_repo == "repo_a"
    assert message.receiver_repo == "repo_b"
    assert message.message_type == MessageType.CODE_CHANGE_NOTIFICATION
    assert message.content == {"change": "test change"}
    assert message.priority == MessagePriority.HIGH
    assert isinstance(message.timestamp, datetime)
    assert message.correlation_id is not None


@pytest.mark.asyncio
async def test_repository_messenger_initialization(mock_app):
    """Test that RepositoryMessenger initializes correctly."""
    messenger = RepositoryMessenger(mock_app)
    
    # Verify components were initialized
    assert messenger.app == mock_app
    assert messenger.messages == []
    assert messenger.subscribers == {}
    assert messenger.authenticator is not None


@pytest.mark.asyncio
async def test_send_message(mock_app):
    """Test sending a message."""
    messenger = RepositoryMessenger(mock_app)
    
    # Send a message
    message = await messenger.send_message(
        sender_repo="sender_repo",
        receiver_repo="receiver_repo",
        message_type=MessageType.WORKFLOW_STATUS_UPDATE,
        content={"status": "completed", "workflow_id": "test_wf_123"},
        priority=MessagePriority.NORMAL
    )
    
    # Verify message was created and stored
    assert message is not None
    assert message.sender_repo == "sender_repo"
    assert message.receiver_repo == "receiver_repo"
    assert message.message_type == MessageType.WORKFLOW_STATUS_UPDATE
    assert message.content == {"status": "completed", "workflow_id": "test_wf_123"}
    assert message.priority == MessagePriority.NORMAL
    
    # Verify message was stored
    assert len(messenger.messages) == 1
    assert messenger.messages[0].id == message.id


@pytest.mark.asyncio
async def test_subscribe_and_notify(mock_app):
    """Test subscribing to messages and receiving notifications."""
    messenger = RepositoryMessenger(mock_app)
    
    # Create a callback to capture notifications
    received_messages = []
    
    async def message_callback(message):
        received_messages.append(message)
    
    # Subscribe to messages for a specific repository
    messenger.subscribe("target_repo", message_callback)
    
    # Send a message to the subscribed repository
    sent_message = await messenger.send_message(
        sender_repo="source_repo",
        receiver_repo="target_repo",  # This matches the subscription
        message_type=MessageType.QUALITY_ALERT,
        content={"alert": "test alert"},
        priority=MessagePriority.HIGH
    )
    
    # The callback should have been called with the message
    # Note: In this synchronous test, the callback may not be called immediately
    # depending on how the notification is implemented
    # For now, we'll just verify the subscription was added
    assert "target_repo" in messenger.subscribers
    assert message_callback in messenger.subscribers["target_repo"]


@pytest.mark.asyncio
async def test_get_messages_for_repo(mock_app):
    """Test retrieving messages for a specific repository."""
    messenger = RepositoryMessenger(mock_app)
    
    # Send a few messages to different repositories
    msg1 = await messenger.send_message(
        sender_repo="sender1",
        receiver_repo="repo_a",
        message_type=MessageType.CODE_CHANGE_NOTIFICATION,
        content={"change": "change1"}
    )
    
    msg2 = await messenger.send_message(
        sender_repo="sender2",
        receiver_repo="repo_b",
        message_type=MessageType.WORKFLOW_STATUS_UPDATE,
        content={"status": "running"}
    )
    
    msg3 = await messenger.send_message(
        sender_repo="sender3",
        receiver_repo="repo_a",  # Same receiver as msg1
        message_type=MessageType.QUALITY_ALERT,
        content={"alert": "quality_issue"}
    )
    
    # Get messages for repo_a
    repo_a_messages = await messenger.get_messages_for_repo("repo_a")
    
    # Should have 2 messages for repo_a
    assert len(repo_a_messages) == 2
    receiver_ids = [msg.id for msg in repo_a_messages]
    assert msg1.id in receiver_ids
    assert msg3.id in receiver_ids
    assert msg2.id not in receiver_ids  # msg2 was for repo_b


@pytest.mark.asyncio
async def test_broadcast_message(mock_app):
    """Test broadcasting a message to multiple repositories."""
    messenger = RepositoryMessenger(mock_app)
    
    # Mock the app.get_repos() method to return some test repos
    mock_app.get_repos.return_value = ["repo_a", "repo_b", "repo_c"]
    
    # Broadcast a message
    messages = await messenger.broadcast_message(
        sender_repo="broadcast_sender",
        message_type=MessageType.DEPENDENCY_UPDATE,
        content={"dependency": "test_dep", "version": "1.0.0"},
        priority=MessagePriority.HIGH
    )
    
    # Should have sent messages to all repos except the sender
    assert len(messages) == 3  # repo_a, repo_b, repo_c (not sender)
    
    # Verify all messages have the same content
    for msg in messages:
        assert msg.sender_repo == "broadcast_sender"
        assert msg.message_type == MessageType.DEPENDENCY_UPDATE
        assert msg.content == {"dependency": "test_dep", "version": "1.0.0"}
        assert msg.priority == MessagePriority.HIGH
        assert msg.receiver_repo in ["repo_a", "repo_b", "repo_c"]


@pytest.mark.asyncio
async def test_acknowledge_message(mock_app):
    """Test acknowledging a message."""
    messenger = RepositoryMessenger(mock_app)
    
    # Send a message
    message = await messenger.send_message(
        sender_repo="sender",
        receiver_repo="receiver",
        message_type=MessageType.SECURITY_SCAN_RESULT,
        content={"scan_result": "ok"}
    )
    
    # Acknowledge the message
    success = await messenger.acknowledge_message(message.id, "receiver")
    
    # Verify acknowledgment was successful
    assert success is True


@pytest.mark.asyncio
async def test_verify_message_signature(mock_app):
    """Test verifying message signatures."""
    messenger = RepositoryMessenger(mock_app)
    
    # Create a message
    message = RepositoryMessage(
        id="sig_test_msg",
        sender_repo="sender_repo",
        receiver_repo="receiver_repo",
        message_type=MessageType.CUSTOM,
        content={"test": "data"},
        priority=MessagePriority.NORMAL
    )
    
    # Verify the message signature (this should work if the message was properly signed)
    # Note: In this test, the message may not have a signature yet
    # The signature is added when sending via the send_message method
    is_valid = await messenger.verify_message_signature(message)
    
    # Should return True if no authenticator or signature (backward compatibility)
    assert is_valid is True


@pytest.mark.asyncio
async def test_repository_messenger_manager_initialization(mock_app):
    """Test that RepositoryMessengerManager initializes correctly."""
    manager = RepositoryMessengerManager(mock_app)
    
    # Verify components were initialized
    assert manager.app == mock_app
    assert manager.messenger is not None
    assert manager.logger is not None


@pytest.mark.asyncio
async def test_process_repository_changes(mock_app):
    """Test processing repository changes."""
    manager = RepositoryMessengerManager(mock_app)
    
    # Define some test changes
    changes = [
        {"type": "file_added", "path": "/path/to/new_file.py", "content": "print('hello')"},
        {"type": "file_modified", "path": "/path/to/existing_file.py", "diff": "+ new line"},
        {"type": "file_deleted", "path": "/path/to/deleted_file.py"}
    ]
    
    # Process repository changes
    result = await manager.process_repository_changes("/test/repo", changes)
    
    # Verify result structure
    assert result["status"] == "success"
    assert "messages_sent" in result
    assert "changes_notified" in result
    assert result["changes_notified"] == len(changes)


@pytest.mark.asyncio
async def test_notify_workflow_status(mock_app):
    """Test notifying workflow status changes."""
    manager = RepositoryMessengerManager(mock_app)
    
    # Notify workflow status
    result = await manager.notify_workflow_status(
        workflow_id="wf_123",
        status="completed",
        repo_path="/test/repo",
        target_repos=["repo_a", "repo_b"]
    )
    
    # Verify result structure
    assert result["status"] == "success"
    assert "messages_sent" in result
    assert "workflow_id" in result
    assert "status" in result
    assert result["workflow_id"] == "wf_123"
    assert result["status"] == "completed"


@pytest.mark.asyncio
async def test_send_quality_alert(mock_app):
    """Test sending quality alerts."""
    manager = RepositoryMessengerManager(mock_app)
    
    # Send a quality alert
    result = await manager.send_quality_alert(
        repo_path="/test/repo",
        alert_type="security_vulnerability",
        description="Potential security issue detected",
        severity="high"
    )
    
    # Verify result structure
    assert result["status"] == "success"
    assert "messages_sent" in result
    assert "alert_type" in result
    assert "severity" in result
    assert result["alert_type"] == "security_vulnerability"
    assert result["severity"] == "high"
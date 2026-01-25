"""Unit tests for resilience and error recovery functionality."""
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock
from mahavishnu.core.resilience import ErrorRecoveryManager, RecoveryStrategy, ErrorCategory
from mahavishnu.core.app import MahavishnuApp


@pytest.fixture
def mock_app():
    """Create a mock app for testing."""
    app = Mock(spec=MahavishnuApp)
    app.observability = Mock()
    app.opensearch_integration = Mock()
    app.workflow_state_manager = Mock()
    return app


@pytest.mark.asyncio
async def test_error_classification():
    """Test that errors are correctly classified."""
    app = Mock(spec=MahavishnuApp)
    recovery_manager = ErrorRecoveryManager(app)
    
    # Test network error classification
    network_errors = [
        "ConnectionError: Network is unreachable",
        "TimeoutError: Request timed out",
        "socket.gaierror: Name or service not known",
        "ssl.SSLError: Certificate verify failed",
        "ConnectionResetError: Connection was reset"
    ]
    
    for error_msg in network_errors:
        error = Exception(error_msg)
        category = await recovery_manager.classify_error(error)
        assert category == ErrorCategory.NETWORK
    
    # Test resource error classification
    resource_errors = [
        "MemoryError: Out of memory",
        "OSError: Disk quota exceeded",
        "MemoryError: Unable to allocate",
        "OSError: No space left on device"
    ]
    
    for error_msg in resource_errors:
        error = Exception(error_msg)
        category = await recovery_manager.classify_error(error)
        assert category == ErrorCategory.RESOURCE
    
    # Test permission error classification
    permission_errors = [
        "PermissionError: Access denied",
        "Unauthorized: Invalid credentials",
        "Forbidden: Access is forbidden",
        "AuthenticationError: Invalid token"
    ]
    
    for error_msg in permission_errors:
        error = Exception(error_msg)
        category = await recovery_manager.classify_error(error)
        assert category == ErrorCategory.PERMISSION
    
    # Test validation error classification
    validation_errors = [
        "ValueError: Invalid value provided",
        "TypeError: Incorrect type",
        "ValidationError: Field is required",
        "AssertionError: Value must be positive"
    ]
    
    for error_msg in validation_errors:
        error = Exception(error_msg)
        category = await recovery_manager.classify_error(error)
        assert category == ErrorCategory.VALIDATION
    
    # Test transient error classification
    transient_errors = [
        "TemporaryError: Try again later",
        "RateLimitError: Too many requests",
        "ServiceBusyError: Service is busy",
        "RetryableError: Operation can be retried"
    ]
    
    for error_msg in transient_errors:
        error = Exception(error_msg)
        category = await recovery_manager.classify_error(error)
        assert category == ErrorCategory.TRANSIENT
    
    # Test permanent error classification (default)
    permanent_errors = [
        "RuntimeError: Something went wrong",
        "KeyError: Key not found",
        "IndexError: Index out of range"
    ]
    
    for error_msg in permanent_errors:
        error = Exception(error_msg)
        category = await recovery_manager.classify_error(error)
        assert category == ErrorCategory.PERMANENT


@pytest.mark.asyncio
async def test_execute_with_resilience_success():
    """Test successful execution with resilience."""
    app = Mock(spec=MahavishnuApp)
    app.observability = Mock()
    app.opensearch_integration = AsyncMock()
    recovery_manager = ErrorRecoveryManager(app)

    # Create a mock successful operation
    async def successful_operation(x, y):
        return x + y

    # Execute with resilience
    result = await recovery_manager.execute_with_resilience(
        successful_operation, 5, 3, workflow_id="test_wf_1", repo_path="/test/repo"
    )

    # Verify success
    assert result["success"] is True
    assert result["result"] == 8
    assert result["attempts"] == 1


@pytest.mark.asyncio
async def test_execute_with_resilience_retry_success():
    """Test that retries work for transient errors."""
    app = Mock(spec=MahavishnuApp)
    app.observability = Mock()
    app.opensearch_integration = AsyncMock()
    recovery_manager = ErrorRecoveryManager(app)
    
    # Counter to track attempts
    attempt_count = 0
    
    async def flaky_operation():
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count < 3:
            raise Exception("Temporary network issue")
        return "success"
    
    # Execute with resilience - should succeed after retries
    result = await recovery_manager.execute_with_resilience(
        flaky_operation, workflow_id="test_wf_2", repo_path="/test/repo"
    )
    
    # Verify success after retries
    assert result["success"] is True
    assert result["result"] == "success"
    assert result["attempts"] == 3  # Should have taken 3 attempts
    assert result["recovered"] is True


@pytest.mark.asyncio
async def test_execute_with_resilience_retry_failure():
    """Test that retries eventually fail after max attempts."""
    app = Mock(spec=MahavishnuApp)
    app.observability = Mock()
    app.opensearch_integration = AsyncMock()
    recovery_manager = ErrorRecoveryManager(app)

    # Counter to track attempts
    attempt_count = 0

    async def consistently_failing_operation():
        nonlocal attempt_count
        attempt_count += 1
        raise Exception("Temporary network issue")  # Transient error to trigger retries

    # Execute with resilience - should fail after max attempts
    result = await recovery_manager.execute_with_resilience(
        consistently_failing_operation, workflow_id="test_wf_3", repo_path="/test/repo"
    )

    # Verify failure after max attempts
    assert result["success"] is False
    assert result["attempts"] == 6  # 1 initial + 5 retries for transient errors
    assert result["recovered"] is False


@pytest.mark.asyncio
async def test_execute_with_resilience_skip_strategy():
    """Test that skip strategy works for permanent errors."""
    app = Mock(spec=MahavishnuApp)
    app.observability = Mock()
    app.opensearch_integration = AsyncMock()
    recovery_manager = ErrorRecoveryManager(app)
    
    async def permanent_error_operation():
        raise Exception("Permission denied: access forbidden")
    
    # Execute with resilience - should skip for permission errors
    result = await recovery_manager.execute_with_resilience(
        permanent_error_operation, workflow_id="test_wf_4", repo_path="/test/repo"
    )
    
    # Verify it was treated as "recovered" by skipping
    assert result["success"] is False  # Operation didn't succeed
    assert result["skipped"] is True  # But was skipped as recovered
    assert result["recovered"] is True  # Considered recovered as we continued


@pytest.mark.asyncio
async def test_log_operation_result():
    """Test that operation results are properly logged."""
    app = Mock(spec=MahavishnuApp)
    app.observability = Mock()
    app.opensearch_integration = AsyncMock()

    recovery_manager = ErrorRecoveryManager(app)

    # Test successful operation logging
    await recovery_manager._log_operation_result(
        workflow_id="test_wf_5",
        repo_path="/test/repo",
        success=True,
        execution_time=0.5,
        result="success_result"
    )

    # Verify observability logging was called
    app.observability.log_info.assert_called_once()

    # Reset mock for error test
    app.observability.reset_mock()

    # Test failed operation logging
    await recovery_manager._log_operation_result(
        workflow_id="test_wf_6",
        repo_path="/test/repo",
        success=False,
        execution_time=0.3,
        error="Test error occurred",
        error_category="network"
    )

    # Verify error logging was called
    app.observability.log_error.assert_called_once()


@pytest.mark.asyncio
async def test_log_recovery_action():
    """Test that recovery actions are properly logged."""
    app = Mock(spec=MahavishnuApp)
    app.observability = Mock()
    app.opensearch_integration = AsyncMock()

    recovery_manager = ErrorRecoveryManager(app)

    # Test recovery action logging
    await recovery_manager._log_recovery_action(
        workflow_id="test_wf_7",
        repo_path="/test/repo",
        action="retry_success",
        attempt=2,
        result="recovered_result"
    )

    # Verify logging was called
    app.observability.log_info.assert_called_once()


@pytest.mark.asyncio
async def test_get_recovery_metrics():
    """Test that recovery metrics can be retrieved."""
    app = Mock(spec=MahavishnuApp)
    recovery_manager = ErrorRecoveryManager(app)
    
    # Get metrics
    metrics = await recovery_manager.get_recovery_metrics()
    
    # Verify metrics structure
    assert "total_recovery_attempts" in metrics
    assert "successful_recoveries" in metrics
    assert "failed_recoveries" in metrics
    assert "most_common_error_categories" in metrics
    assert "average_recovery_time" in metrics
    assert "recovery_effectiveness_rate" in metrics
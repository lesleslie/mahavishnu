"""Comprehensive test suite for Mahavishnu orchestration platform."""

from pathlib import Path
import tempfile

from mcp_common.code_graph.analyzer import CodeGraphAnalyzer
import pytest

from mahavishnu.core.app import MahavishnuApp
from mahavishnu.core.monitoring import AlertSeverity, AlertType
from mahavishnu.core.permissions import Permission


@pytest.mark.asyncio
async def test_full_platform_integration():
    """Test that all major platform components integrate correctly."""
    # Create a real app instance
    app = MahavishnuApp()

    # Verify all core components are available
    assert app is not None
    assert app.workflow_state_manager is not None
    assert app.rbac_manager is not None
    assert app.observability is not None
    assert app.opensearch_integration is not None
    assert app.resilience_manager is not None
    assert app.error_recovery_manager is not None
    assert app.monitoring_service is not None
    assert app.backup_manager is not None


@pytest.mark.asyncio
async def test_code_graph_analysis_integration():
    """Test that code graph analysis works with the rest of the platform."""
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create a test repository with Python files
        repo_path = Path(temp_dir) / "test_repo"
        repo_path.mkdir()

        # Create a Python file with functions and classes
        test_file = repo_path / "main.py"
        test_content = '''
def main_function():
    """Main function for testing."""
    helper_result = helper_function()
    return process_result(helper_result)

def helper_function():
    """Helper function for testing."""
    return "helper result"

def process_result(result):
    """Process the result."""
    return f"processed: {result}"

class TestClass:
    """Test class for analysis."""

    def test_method(self):
        """Test method."""
        return main_function()

import os
from pathlib import Path
'''
        test_file.write_text(test_content)

        # Test code graph analysis
        analyzer = CodeGraphAnalyzer(repo_path)
        result = await analyzer.analyze_repository(str(repo_path))

        # Verify analysis results
        assert result["files_indexed"] >= 1
        assert result["functions_indexed"] >= 3  # main_function, helper_function, process_result
        assert result["classes_indexed"] >= 1  # TestClass

        # Verify that function nodes were created
        func_nodes = [
            node
            for node in analyzer.nodes.values()
            if hasattr(node, "name") and hasattr(node, "calls")
        ]
        assert len(func_nodes) >= 3


@pytest.mark.asyncio
async def test_workflow_state_persistence():
    """Test that workflow states are properly persisted and retrieved."""
    app = MahavishnuApp()

    # Create a test workflow
    workflow_id = "test_integration_workflow"
    task = {"type": "integration_test", "id": workflow_id}
    repos = ["/test/repo1", "/test/repo2"]

    # Create workflow state
    await app.workflow_state_manager.create(workflow_id, task, repos)

    # Update workflow state
    await app.workflow_state_manager.update(workflow_id=workflow_id, status="running", progress=50)

    # Retrieve workflow state
    state = await app.workflow_state_manager.get(workflow_id)

    # Verify state was persisted and retrieved correctly
    assert state is not None
    assert state["id"] == workflow_id
    assert state["task"] == task
    assert state["repos"] == repos
    assert state["status"] == "running"
    assert state["progress"] == 50


@pytest.mark.asyncio
async def test_rbac_workflow_integration():
    """Test that RBAC works with workflow execution."""
    app = MahavishnuApp()

    with tempfile.TemporaryDirectory() as temp_dir:
        # Create a test repository
        repo_path = Path(temp_dir)
        (repo_path / "test.py").write_text("# Test repository")
        repo_str = str(repo_path)

        # Create a test user with limited permissions
        user = await app.rbac_manager.create_user(
            user_id="integration_test_user", roles=["developer"], allowed_repos=[repo_str]
        )

        # Verify user was created
        assert user.user_id == "integration_test_user"

        # Test permission checking
        has_permission = await app.rbac_manager.check_permission(
            "integration_test_user", repo_str, Permission.READ_REPO
        )
        assert has_permission is True

        # Test permission checking for unauthorized repo
        has_permission = await app.rbac_manager.check_permission(
            "integration_test_user", "/unauthorized/repo", Permission.READ_REPO
        )
        assert has_permission is False


@pytest.mark.asyncio
async def test_resilience_pattern_integration():
    """Test that resilience patterns work with workflow execution."""
    app = MahavishnuApp()

    with tempfile.TemporaryDirectory() as temp_dir:
        # Create a test repository
        repo_path = Path(temp_dir)
        (repo_path / "test.py").write_text("# Test repository")
        repo_str = str(repo_path)

        # Test resilience with a simple task
        task = {"type": "health_check", "id": "resilience_test"}

        # Execute with resilience patterns
        result = await app.resilience_manager.resilient_workflow_execution(
            task=task,
            adapter_name="llamaindex",  # Use available adapter
            repos=[str(repo_str)],
            user_id="test_user",
        )

        # Verify result structure
        assert "success" in result
        assert "result" in result
        assert "attempts" in result


@pytest.mark.asyncio
async def test_monitoring_alert_integration():
    """Test that monitoring and alerts work together."""
    app = MahavishnuApp()

    # Create an alert through the alert manager
    alert = await app.monitoring_service.alert_manager.trigger_alert(
        severity=AlertSeverity.MEDIUM,
        alert_type=AlertType.SYSTEM_HEALTH,
        title="Integration Test Alert",
        description="Testing alert integration",
        details={"test": True, "component": "integration_test"},
    )

    # Verify alert was created
    assert alert is not None
    assert alert.title == "Integration Test Alert"
    assert alert.severity == AlertSeverity.MEDIUM

    # Get active alerts
    active_alerts = await app.monitoring_service.alert_manager.get_active_alerts()
    assert len(active_alerts) >= 1

    # Find our alert in the active alerts
    our_alert = next((a for a in active_alerts if a.id == alert.id), None)
    assert our_alert is not None
    assert our_alert.description == "Testing alert integration"


@pytest.mark.asyncio
async def test_backup_workflow_integration():
    """Test that backup and workflow systems work together."""
    app = MahavishnuApp()

    with tempfile.TemporaryDirectory() as temp_dir:
        # Create a test repository
        repo_path = Path(temp_dir)
        (repo_path / "test.py").write_text("# Test repository")
        repo_str = str(repo_path)

        # Create a workflow
        workflow_id = "backup_integration_test"
        task = {"type": "backup_test", "id": workflow_id}
        repos = [str(repo_str)]

        # Create workflow state
        await app.workflow_state_manager.create(workflow_id, task, repos)

        # Test backup creation
        backup_info = await app.backup_manager.create_backup("full")

        # Verify backup was created
        assert backup_info is not None
        assert backup_info.backup_id.startswith("backup_")
        assert backup_info.status == "completed"

        # List backups
        backups = await app.backup_manager.list_backups()
        assert len(backups) >= 1


@pytest.mark.asyncio
async def test_error_recovery_integration():
    """Test that error recovery works with the platform."""
    app = MahavishnuApp()

    # Test error classification
    error = Exception("Network timeout occurred")
    category = await app.error_recovery_manager.classify_error(error)

    # This should be classified as a network error
    assert category in [category.NETWORK, category.TRANSIENT]

    # Test error recovery execution
    async def failing_operation():
        raise Exception("Simulated failure")

    # Execute with resilience
    result = await app.error_recovery_manager.execute_with_resilience(
        failing_operation, workflow_id="recovery_test", repo_path="/test/repo"
    )

    # Verify that recovery was attempted
    assert "success" in result
    assert "attempts" in result
    assert result["attempts"] >= 1  # Should have at least tried once


@pytest.mark.asyncio
async def test_complete_workflow_cycle():
    """Test a complete workflow cycle from start to finish."""
    app = MahavishnuApp()

    with tempfile.TemporaryDirectory() as temp_dir:
        # Create a test repository
        repo_path = Path(temp_dir)
        (repo_path / "main.py").write_text("""
def hello_world():
    return "Hello, World!"
""")
        repo_str = str(repo_path)

        # Step 1: Create workflow state
        workflow_id = "complete_cycle_test"
        task = {"type": "code_analysis", "params": {"analyze_functions": True}, "id": workflow_id}
        repos = [str(repo_str)]

        await app.workflow_state_manager.create(workflow_id, task, repos)

        # Step 2: Update workflow to running
        await app.workflow_state_manager.update(workflow_id, status="running")

        # Step 3: Execute workflow with resilience
        if "llamaindex" in app.adapters:
            result = await app.resilience_manager.resilient_workflow_execution(
                task=task, adapter_name="llamaindex", repos=repos
            )

            # Step 4: Update workflow state based on result
            final_status = "completed" if result.get("success", False) else "failed"
            await app.workflow_state_manager.update(
                workflow_id=workflow_id, status=final_status, result=result
            )

        # Step 5: Verify final state
        final_state = await app.workflow_state_manager.get(workflow_id)
        assert final_state is not None
        assert final_state["id"] == workflow_id
        assert final_state["status"] in ["completed", "failed", "running"]


@pytest.mark.asyncio
async def test_multi_component_interaction():
    """Test interaction between multiple platform components."""
    app = MahavishnuApp()

    with tempfile.TemporaryDirectory() as temp_dir:
        # Create a test repository
        repo_path = Path(temp_dir)
        (repo_path / "test.py").write_text("# Multi-component test")
        repo_str = str(repo_path)

        # 1. Use RBAC to check permissions
        has_perm = await app.rbac_manager.check_permission(
            "test_user", str(repo_str), Permission.READ_REPO
        )

        # 2. Use code graph to analyze the repo
        analyzer = CodeGraphAnalyzer(repo_path)
        analysis = await analyzer.analyze_repository(str(repo_path))

        # 3. Create a workflow
        workflow_id = "multi_component_test"
        await app.workflow_state_manager.create(
            workflow_id, {"type": "multi_test"}, [str(repo_str)]
        )

        # 4. Use resilience for execution
        async def multi_component_task():
            # Simulate a task that uses multiple components
            result = {
                "analysis": analysis,
                "permissions_checked": has_perm,
                "workflow_created": True,
            }
            return result

        resilient_result = await app.error_recovery_manager.execute_with_resilience(
            multi_component_task, workflow_id=workflow_id, repo_path=str(repo_str)
        )

        # 5. Log to observability
        app.observability.log_info(
            "Multi-component test completed",
            attributes={
                "workflow_id": workflow_id,
                "result_success": resilient_result.get("success", False),
                "analysis_files": analysis.get("files_indexed", 0),
            },
        )

        # 6. Verify all components worked together
        assert resilient_result["success"] is True
        assert "result" in resilient_result
        assert analysis["files_indexed"] >= 1


if __name__ == "__main__":
    # Run the tests if executed directly
    pytest.main([__file__, "-v"])

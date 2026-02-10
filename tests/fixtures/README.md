# Test Fixtures Guide

This guide documents the comprehensive pytest fixtures available for testing Mahavishnu.

## Table of Contents

- [Overview](#overview)
- [Workflow Fixtures](#workflow-fixtures)
- [Shell Fixtures](#shell-fixtures)
- [Integration Fixtures](#integration-fixtures)
- [Usage Examples](#usage-examples)
- [Best Practices](#best-practices)

## Overview

The test fixtures are organized into three main modules:

- **`workflow_fixtures.py`**: Workflow state and execution test data
- **`shell_fixtures.py`**: Admin shell and terminal test data
- **`conftest.py`**: Shared integration and configuration fixtures

All fixtures are automatically discovered by pytest and can be used by simply including them as parameters in your test functions.

## Workflow Fixtures

Located in `tests/fixtures/workflow_fixtures.py`

### Factory Class

#### `WorkflowFixtures`

Factory class for creating workflow test data with various states.

**Methods:**

- `sample_workflow()` - Create a workflow in RUNNING state
- `completed_workflow()` - Create a successfully completed workflow
- `failed_workflow()` - Create a failed workflow with errors
- `partial_workflow()` - Create a workflow with partial success
- `pending_workflow()` - Create a workflow not yet started
- `multiple_workflows(count=5)` - Create multiple workflows

### Available Fixtures

#### `workflow_fixtures`

Provides the WorkflowFixtures factory class.

```python
def test_with_factory(workflow_fixtures):
    workflow = workflow_fixtures.sample_workflow()
    assert workflow["status"] == "running"
```

#### `sample_workflow`

Provides a workflow in RUNNING state.

```python
def test_running_workflow(sample_workflow):
    assert sample_workflow["status"] == "running"
    assert sample_workflow["progress"] == 45
```

#### `completed_workflow`

Provides a successfully completed workflow with results.

```python
def test_completed_workflow(completed_workflow):
    assert completed_workflow["status"] == "completed"
    assert completed_workflow["progress"] == 100
    assert len(completed_workflow["results"]) > 0
```

#### `failed_workflow`

Provides a failed workflow with detailed error information.

```python
def test_failed_workflow(failed_workflow):
    assert failed_workflow["status"] == "failed"
    assert len(failed_workflow["errors"]) > 0
    assert "error" in failed_workflow["errors"][0]
```

#### `partial_workflow`

Provides a workflow that completed but had some failures.

```python
def test_partial_workflow(partial_workflow):
    assert partial_workflow["status"] == "partial"
    assert len(partial_workflow["results"]) > 0
    assert len(partial_workflow["errors"]) > 0
```

#### `pending_workflow`

Provides a workflow in PENDING state (not yet started).

```python
def test_pending_workflow(pending_workflow):
    assert pending_workflow["status"] == "pending"
    assert pending_workflow["progress"] == 0
```

#### `multiple_workflows`

Provides a list of workflows in various states.

```python
def test_multiple_workflows(multiple_workflows):
    assert len(multiple_workflows) == 5
    statuses = [wf["status"] for wf in multiple_workflows]
    assert "running" in statuses
    assert "completed" in statuses
```

#### `mock_workflow_state_manager`

Provides a mock WorkflowStateManager with common methods.

```python
@pytest.mark.asyncio
async def test_state_manager(mock_workflow_state_manager):
    result = await mock_workflow_state_manager.get("wf_123")
    assert result["id"] == "wf_test_123"
```

#### `sample_task`

Provides a sample task specification.

```python
def test_task(sample_task):
    assert sample_task["type"] == "code_sweep"
    assert "pattern" in sample_task["params"]
```

#### `sample_repos`

Provides sample repository paths.

```python
def test_repos(sample_repos):
    assert len(sample_repos) == 3
    assert all(repo.startswith("/Users/les/Projects") for repo in sample_repos)
```

## Shell Fixtures

Located in `tests/fixtures/shell_fixtures.py`

### Factory Class

#### `ShellFixtures`

Factory class for creating shell and terminal test data.

**Methods:**

- `mock_shell_output()` - Create mock terminal command output
- `mock_repos_list()` - Create mock repository listing
- `mock_workflow_status()` - Create mock workflow status display
- `mock_error_output()` - Create mock error log entries
- `mock_terminal_output()` - Create mock formatted terminal output
- `mock_shell_commands()` - Create mock shell command registry
- `mock_role_output()` - Create mock role taxonomy
- `mock_opensearch_logs()` - Create mock OpenSearch logs
- `mock_health_check_output()` - Create mock health check results

### Available Fixtures

#### `shell_fixtures`

Provides the ShellFixtures factory class.

```python
def test_with_shell_factory(shell_fixtures):
    repos = shell_fixtures.mock_repos_list()
    assert len(repos) > 0
```

#### `mock_repos_list`

Provides a list of repository dictionaries.

```python
def test_repos_list(mock_repos_list):
    assert len(mock_repos_list) == 6
    assert mock_repos_list[0]["role"] == "orchestrator"
```

#### `mock_workflow_status`

Provides formatted workflow status output.

```python
def test_workflow_status(mock_workflow_status):
    assert "running" in mock_workflow_status
    assert "completed" in mock_workflow_status
```

#### `mock_error_output`

Provides list of error log entries.

```python
def test_error_output(mock_error_output):
    assert len(mock_error_output) == 3
    assert mock_error_output[0]["level"] == "ERROR"
```

#### `mock_shell_commands`

Provides shell command registry.

```python
def test_shell_commands(mock_shell_commands):
    assert "ps" in mock_shell_commands
    assert "help" in mock_shell_commands
```

#### `mock_role_output`

Provides role taxonomy definitions.

```python
def test_role_output(mock_role_output):
    roles = mock_role_output["roles"]
    assert roles[0]["name"] == "orchestrator"
```

## Integration Fixtures

Located in `tests/fixtures/conftest.py`

### Factory Class

#### `IntegrationFixtures`

Factory class for creating integration test mocks.

**Methods:**

- `mock_config(**overrides)` - Create mock MahavishnuSettings
- `mock_app(config=None)` - Create mock MahavishnuApp
- `mock_adapter()` - Create mock OrchestratorAdapter
- `mock_repos_config()` - Create mock repository configuration
- `mock_roles()` - Create mock role definitions

### Available Fixtures

#### `mock_config`

Provides a mock MahavishnuSettings configuration.

```python
def test_config(mock_config):
    assert mock_config.server_name == "Mahavishnu Test Server"
    assert mock_config.debug is True
```

#### `mock_app`

Provides a mock MahavishnuApp instance.

```python
@pytest.mark.asyncio
async def test_app(mock_app):
    health = await mock_app.is_healthy()
    assert health is True
```

#### `mock_adapter`

Provides a mock OrchestratorAdapter.

```python
@pytest.mark.asyncio
async def test_adapter(mock_adapter):
    health = await mock_adapter.get_health()
    assert health["status"] == "healthy"
```

#### `temp_dir`

Provides a temporary directory that is automatically cleaned up.

```python
def test_temp_dir(temp_dir):
    test_file = temp_dir / "test.txt"
    test_file.write_text("test content")
    assert test_file.exists()
    # Automatically cleaned up after test
```

#### `temp_git_repo`

Provides a temporary Git repository.

```python
def test_git_repo(temp_git_repo):
    assert (temp_git_repo / ".git").exists()
    assert (temp_git_repo / "README.md").exists()
```

#### `temp_config_file`

Provides a temporary configuration file.

```python
def test_config_file(temp_config_file):
    assert temp_config_file.exists()
    assert temp_config_file.suffix == ".yaml"
```

#### `temp_repos_file`

Provides a temporary repos.yaml file.

```python
def test_repos_file(temp_repos_file):
    import yaml
    with temp_repos_file.open() as f:
        data = yaml.safe_load(f)
        assert "repos" in data
```

#### `clean_env`

Provides environment without Mahavishnu variables.

```python
def test_clean_env(clean_env):
    import os
    assert "MAHAVISHNU_SERVER_NAME" not in os.environ
```

#### `test_env_vars`

Provides test environment variables.

```python
def test_env_vars(test_env_vars):
    import os
    assert os.environ["MAHAVISHNU_DEBUG"] == "true"
```

## Usage Examples

### Example 1: Testing Workflow Execution

```python
import pytest
from tests.fixtures.workflow_fixtures import WorkflowFixtures

class TestWorkflowExecution:
    """Test workflow execution functionality."""

    @pytest.mark.asyncio
    async def test_execute_workflow(self, sample_task, mock_app):
        """Test executing a single workflow."""
        result = await mock_app.execute_workflow(
            task=sample_task,
            adapter_name="llamaindex",
            repos=["/test/repo"],
        )

        assert result["status"] == "completed"
        assert "workflow_id" in result

    @pytest.mark.asyncio
    async def test_parallel_execution(self, sample_task, mock_app):
        """Test parallel workflow execution."""
        result = await mock_app.execute_workflow_parallel(
            task=sample_task,
            adapter_name="agno",
            repos=["/test/repo1", "/test/repo2"],
        )

        assert result["repos_processed"] == 2
        assert result["successful_repos"] >= 0
```

### Example 2: Testing Shell Commands

```python
import pytest
from tests.fixtures.shell_fixtures import ShellFixtures

class TestShellCommands:
    """Test admin shell commands."""

    def test_list_repos(self, mock_repos_list):
        """Test repository listing."""
        assert len(mock_repos_list) > 0
        assert all("path" in repo for repo in mock_repos_list)

    def test_show_roles(self, mock_role_output):
        """Test role display."""
        roles = mock_role_output["roles"]
        assert len(roles) > 0
        assert all("name" in role for role in roles)

    def test_format_errors(self, mock_error_output):
        """Test error formatting."""
        errors = mock_error_output
        assert all(e["level"] == "ERROR" for e in errors)
```

### Example 3: Integration Testing

```python
import pytest
from tests.fixtures.conftest import IntegrationFixtures

class TestIntegration:
    """Integration tests with full app context."""

    @pytest.mark.asyncio
    async def test_app_initialization(self, mock_config):
        """Test app initialization with config."""
        app = IntegrationFixtures.mock_app(mock_config)
        assert app.config is not None
        assert app.workflow_state_manager is not None

    @pytest.mark.asyncio
    async def test_workflow_lifecycle(self, mock_app, sample_workflow):
        """Test complete workflow lifecycle."""
        # Create
        await mock_app.workflow_state_manager.create(
            workflow_id="wf_test",
            task={"type": "test"},
            repos=["/test/repo"],
        )

        # Update
        await mock_app.workflow_state_manager.update(
            workflow_id="wf_test",
            status="running",
        )

        # Get
        state = await mock_app.workflow_state_manager.get("wf_test")
        assert state["status"] == "running"
```

### Example 4: Using Factory Classes

```python
import pytest
from tests.fixtures import WorkflowFixtures, ShellFixtures

class TestFactories:
    """Test using fixture factory classes."""

    def test_create_custom_workflow(self):
        """Create a workflow with custom ID."""
        workflow = WorkflowFixtures.sample_workflow(
            workflow_id="wf_custom_123"
        )
        assert workflow["id"] == "wf_custom_123"

    def test_create_bulk_workflows(self):
        """Create multiple workflows."""
        workflows = WorkflowFixtures.multiple_workflows(count=10)
        assert len(workflows) == 10

    def test_custom_shell_output(self):
        """Create custom shell output."""
        output = ShellFixtures.mock_shell_output(
            command="custom command"
        )
        assert output["command"] == "custom command"
```

## Best Practices

### 1. Use Specific Fixtures

Prefer specific fixtures over factory classes when possible:

```python
# Good: Use specific fixture
def test_workflow(sample_workflow):
    assert sample_workflow["status"] == "running"

# Avoid: Unless you need customization
def test_workflow(workflow_fixtures):
    workflow = workflow_fixtures.sample_workflow()
    assert workflow["status"] == "running"
```

### 2. Clean Up Resources

Fixtures with `yield` automatically handle cleanup:

```python
# temp_dir is automatically cleaned up after test
def test_with_temp_file(temp_dir):
    test_file = temp_dir / "test.txt"
    test_file.write_text("content")
    # No cleanup needed - fixture handles it
```

### 3. Use Async Fixtures for Async Tests

Always use `@pytest.mark.asyncio` with async fixtures:

```python
@pytest.mark.asyncio
async def test_async_workflow(mock_app):
    result = await mock_app.execute_workflow(...)
    assert result["status"] == "completed"
```

### 4. Combine Fixtures

You can combine multiple fixtures in a single test:

```python
def test_complex_scenario(
    sample_workflow,
    mock_repos_list,
    mock_app
):
    """Test combining multiple fixtures."""
    repos = [repo["path"] for repo in mock_repos_list]
    workflow = sample_workflow
    # Test scenario...
```

### 5. Extend Fixtures in Your Tests

You can modify fixture data for specific test cases:

```python
def test_modified_workflow(sample_workflow):
    """Modify fixture data for specific test."""
    workflow = sample_workflow.copy()
    workflow["status"] = "cancelled"
    assert workflow["status"] == "cancelled"
```

### 6. Use Fixtures in Parametrize

Combine fixtures with parametrize for data-driven tests:

```python
@pytest.mark.parametrize("status", [
    "running", "completed", "failed", "pending"
])
def test_all_statuses(status):
    """Test all workflow statuses."""
    workflow = WorkflowFixtures.sample_workflow()
    workflow["status"] = status
    assert workflow["status"] == status
```

## Troubleshooting

### Fixture Not Found

If you get `fixture 'xyz' not found`, ensure:

1. The fixture is defined in a conftest.py or fixtures module
2. The tests are in the correct directory structure
3. pytest is run from the project root

### Import Errors

For import errors, use absolute imports:

```python
# Good
from tests.fixtures.workflow_fixtures import WorkflowFixtures

# Avoid
from ..fixtures.workflow_fixtures import WorkflowFixtures
```

### Async Fixtures Not Working

Ensure pytest-asyncio is installed and tests are marked:

```python
# Install
pip install pytest-asyncio

# Mark test
@pytest.mark.asyncio
async def test_async(mock_app):
    await mock_app.execute_workflow(...)
```

## Additional Resources

- [Pytest Fixture Documentation](https://docs.pytest.org/en/stable/fixture.html)
- [Project CLAUDE.md](../../CLAUDE.md) - Project-specific testing guidelines
- [Testing Best Practices](../../docs/TESTING.md) - Additional testing guidelines

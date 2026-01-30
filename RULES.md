# Mahavishnu Coding Standards

This document defines the coding standards for the Mahavishnu project.

## Python Code Style

### Formatting

- **Line length**: Maximum 100 characters (configured in Ruff)
- **Indentation**: 4 spaces (no tabs)
- **Quotes**: Double quotes for strings, single quotes only for nested quotes
- **Imports**: Grouped and sorted automatically by Ruff (isort-compatible)
- **Blank lines**: Two blank lines before top-level functions, one before class methods

### Naming Conventions

- **Modules**: `lowercase_with_underscores` (e.g., `adapter_base.py`)
- **Classes**: `CapitalizedWords` (e.g., `OrchestratorAdapter`)
- **Functions & Methods**: `lowercase_with_underscores` (e.g., `initialize_adapters`)
- **Constants**: `UPPERCASE_WITH_UNDERSCORES` (e.g., `MAX_RETRIES`)
- **Private members**: `_leading_underscore` (e.g., `_internal_method`)

### Type Hints

Type hints are **required** for all public functions and methods:

```python
from typing import List, Optional
from mahavishnu.core.models import WorkflowConfig


def get_workflow_configs(repo_path: str, tags: Optional[List[str]] = None) -> List[WorkflowConfig]:
    """Retrieve workflow configurations for a repository.

    Args:
        repo_path: Path to the repository
        tags: Optional filter by tags

    Returns:
        List of workflow configurations
    """
    ...
```

### Docstrings

All public functions, classes, and methods must have Google-style docstrings:

```python
def process_workflow(workflow_id: str, config: dict) -> bool:
    """Process a workflow with the given configuration.

    This method validates the configuration, initializes the adapter,
    and executes the workflow according to the specified parameters.

    Args:
        workflow_id: Unique identifier for the workflow
        config: Dictionary containing workflow configuration

    Returns:
        True if workflow succeeded, False otherwise

    Raises:
        AdapterNotFoundError: If the specified adapter is not available
        ConfigurationError: If the configuration is invalid
    """
    ...
```

### Error Handling

```python
# DO: Use specific exception types
from mahavishnu.core.errors import AdapterNotFoundError, ConfigurationError

try:
    adapter = get_adapter(adapter_name)
except AdapterNotFoundError as e:
    logger.error(f"Adapter not found: {e.message}")
    raise

# DON'T: Catch bare Exception
try:
    adapter = get_adapter(adapter_name)
except Exception:  # Bad!
    pass
```

### Logging

Use structlog for structured logging:

```python
import structlog

logger = structlog.get_logger(__name__)

# Context-aware logging
logger.info("workflow_started", workflow_id=workflow_id, adapter=adapter_name)

# Error logging with context
logger.error(
    "adapter_initialization_failed", adapter_name=adapter_name, error=str(e), details=e.details
)
```

## Testing Standards

### Test Organization

```
tests/
├── unit/           # Fast, isolated tests
├── integration/    # Slower tests with external dependencies
└── property/       # Property-based tests with Hypothesis
```

### Test Structure

```python
import pytest
from mahavishnu.core.adapters.airflow import AirflowAdapter


@pytest.mark.unit
class TestAirflowAdapter:
    """Test suite for Airflow adapter."""

    def test_initialization_success(self):
        """Test successful adapter initialization."""
        adapter = AirflowAdapter(config={"dag_folder": "/tmp/dags"})
        assert adapter.is_initialized()
        assert adapter.adapter_name == "airflow"

    @pytest.mark.parametrize(
        "dag_folder,expected",
        [
            ("/valid/path", True),
            ("", False),
            (None, False),
        ],
    )
    def test_initialization_with_invalid_config(self, dag_folder, expected):
        """Test initialization with various folder configurations."""
        adapter = AirflowAdapter(config={"dag_folder": dag_folder})
        assert adapter.is_initialized() == expected

    @pytest.mark.slow
    def test_full_workflow_execution(self):
        """Test complete workflow execution (slow test)."""
        # Integration test marked as slow
        ...
```

### Test Markers Usage

```python
# Unit tests (fast, isolated)
@pytest.mark.unit
def test_adapter_validation(): ...


# Integration tests (slower, external services)
@pytest.mark.integration
@pytest.mark.airflow
def test_airflow_connection(): ...


# Property-based tests
@pytest.mark.property
@given(st.text(min_size=1, max_size=100))
def test_workflow_name_validation(name):
    assert validate_workflow_name(name) is True
```

## Architecture Patterns

### Adapter Pattern

All adapters must implement the `OrchestratorAdapter` interface:

```python
from mahavishnu.core.adapters.base import OrchestratorAdapter


class CustomAdapter(OrchestratorAdapter):
    """Custom orchestration engine adapter."""

    def __init__(self, config: dict):
        self.adapter_name = "custom"
        super().__init__(config)

    def validate_config(self) -> bool:
        """Validate adapter configuration."""
        ...

    def initialize(self) -> None:
        """Initialize the adapter."""
        ...

    def list_workflows(self) -> List[WorkflowInfo]:
        """List available workflows."""
        ...
```

### Configuration Pattern

Use Pydantic models with Oneiric layered loading:

```python
from pydantic import BaseModel, Field


class AdapterConfig(BaseModel):
    """Adapter configuration with validation."""

    enabled: bool = True
    timeout: int = Field(default=300, ge=1, le=3600)
    max_retries: int = Field(default=3, ge=0, le=10)

    class Config:
        extra = "forbid"  # Reject unknown fields
```

### Error Handling Pattern

Use custom exception hierarchy from `mahavishnu.core.errors`:

```python
from mahavishnu.core.errors import MahavishnuError, AdapterError


class AdapterInitializationError(AdapterError):
    """Raised when adapter initialization fails."""

    def __init__(self, adapter_name: str, reason: str):
        super().__init__(
            message=f"Failed to initialize {adapter_name}: {reason}",
            details={"adapter": adapter_name, "reason": reason},
        )
```

## Security Guidelines

### Input Validation

```python
from pydantic import BaseModel, Field, validator


class WorkflowRequest(BaseModel):
    """Workflow request with validation."""

    repo_path: str = Field(..., min_length=1, max_length=500)
    workflow_name: str = Field(..., regex=r"^[a-zA-Z0-9_-]+$")

    @validator("repo_path")
    def validate_path(cls, v):
        """Prevent path traversal attacks."""
        if ".." in v or v.startswith("/"):
            raise ValueError("Invalid repository path")
        return v
```

### Secrets Management

```python
import os
from mahavishnu.core.config import MahavishnuSettings

# DO: Load from environment
api_key = os.getenv("MAHAVISHNU_API_KEY")

# DON'T: Hardcode secrets
api_key = "sk-1234567890abcdef"  # NEVER DO THIS!
```

## Code Review Checklist

Before submitting code, verify:

- [ ] All type hints are present and correct
- [ ] Docstrings follow Google style
- [ ] Tests cover new functionality (minimum 80% coverage)
- [ ] Security review completed (no hardcoded secrets)
- [ ] Error handling uses custom exceptions
- [ ] Logging uses structlog with context
- [ ] Code follows adapter pattern where applicable
- [ ] Configuration uses Oneiric layered loading
- [ ] All tests pass: `pytest -n auto`
- [ ] Ruff checks pass: `ruff check mahavishnu/`
- [ ] Type checks pass: `mypy mahavishnu/` or `pyright mahavishnu/`
- [ ] Security scan passes: `bandit -r mahavishnu/`

## Additional Resources

- [PEP 8 Style Guide](https://pep8.org/)
- [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html)
- [Pydantic Documentation](https://docs.pydantic.dev/)
- [structlog Documentation](https://www.structlog.org/)

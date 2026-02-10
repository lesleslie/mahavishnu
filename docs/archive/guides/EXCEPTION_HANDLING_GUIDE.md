# Exception Handling Quick Reference Guide

## Quick Reference

### Import Custom Exceptions

```python
from mahavishnu.core.errors import (
    MahavishnuError,
    ConfigurationError,
    PoolError,
    PoolCreationError,
    PoolExecutionError,
    # ... etc
)
```

### Basic Exception Pattern

```python
from mahavishnu.core.errors import PoolError, PoolCreationError

# Raising exceptions
raise PoolCreationError(
    message="Failed to create pool",
    details={
        "pool_type": "kubernetes",
        "reason": "Cluster not reachable",
        "suggestion": "Check kubectl config"
    }
)

# Catching exceptions
try:
    pool = create_pool()
except PoolCreationError as e:
    logger.error(f"Pool creation failed: {e}")
    logger.info(f"Details: {e.details}")
```

## Common Patterns

### File Operations

```python
from mahavishnu.core.errors import FileSystemError

try:
    content = Path(file_path).read_text()
except FileNotFoundError as e:
    raise FileSystemError(
        message=f"File not found: {file_path}",
        details={
            "file_path": str(file_path),
            "operation": "read",
            "suggestion": "Check file exists"
        }
    ) from e
except PermissionError as e:
    raise FileSystemError(
        message=f"Permission denied: {file_path}",
        details={
            "file_path": str(file_path),
            "operation": "read",
            "error_type": "PermissionError"
        }
    ) from e
except (OSError, IOError) as e:
    raise FileSystemError(
        message=f"Failed to read file: {e}",
        details={
            "file_path": str(file_path),
            "operation": "read",
            "error_type": type(e).__name__
        }
    ) from e
```

### Network Operations

```python
from mahavishnu.core.errors import NetworkError, ExternalServiceError

try:
    response = requests.get(url, timeout=30)
except (ConnectionError, TimeoutError) as e:
    raise NetworkError(
        message=f"Network error: {e}",
        details={
            "url": url,
            "timeout": 30,
            "error_type": type(e).__name__
        }
    ) from e
except requests.HTTPError as e:
    raise ExternalServiceError(
        message=f"HTTP error: {e}",
        details={
            "url": url,
            "status_code": e.response.status_code,
            "response": e.response.text[:200]
        }
    ) from e
```

### JSON/YAML Parsing

```python
from mahavishnu.core.errors import ConfigLoadError

import yaml

try:
    data = yaml.safe_load(content)
except yaml.YAMLError as e:
    raise ConfigLoadError(
        message=f"Invalid YAML: {e}",
        details={
            "content_preview": content[:100],
            "error": str(e),
            "suggestion": "Validate YAML syntax"
        }
    ) from e
```

### Dictionary Access

```python
from mahavishnu.core.errors import ValidationError

try:
    value = data["required_key"]
except KeyError as e:
    raise ValidationError(
        message=f"Required key missing: {e}",
        details={
            "missing_key": str(e),
            "available_keys": list(data.keys())
        }
    ) from e
except TypeError as e:
    raise ValidationError(
        message=f"Invalid data type for key access: {e}",
        details={
            "data_type": type(data).__name__,
            "expected": "dict"
        }
    ) from e
```

### MCP Operations

```python
from mahavishnu.core.errors import MCPConnectionError

try:
    result = await mcp_client.call_tool("tool_name", params)
except (ConnectionError, TimeoutError) as e:
    raise MCPConnectionError(
        message=f"MCP connection failed: {e}",
        details={
            "server_url": mcp_client.url,
            "timeout": mcp_client.timeout,
            "error_type": type(e).__name__
        }
    ) from e
```

### Pool Operations

```python
from mahavishnu.core.errors import (
    PoolError,
    PoolCreationError,
    PoolExecutionError,
    PoolNotFoundError
)

try:
    pool_id = await pool_mgr.spawn_pool("mahavishnu", config)
except ValueError as e:
    raise PoolCreationError(
        message=f"Invalid pool configuration: {e}",
        details={
            "pool_type": config.pool_type,
            "validation_error": str(e)
        }
    ) from e
except (OSError, ResourceError) as e:
    raise PoolCreationError(
        message=f"Failed to allocate resources: {e}",
        details={
            "pool_type": config.pool_type,
            "min_workers": config.min_workers,
            "error_type": type(e).__name__
        }
    ) from e
```

## Exception Details Best Practices

### What to Include in `details`

```python
# Good: Comprehensive context
error = PoolCreationError(
    message="Pool creation failed",
    details={
        # What
        "pool_type": "kubernetes",
        "pool_name": "production-pool",

        # Where
        "namespace": "mahavishnu",
        "cluster": "prod-cluster-1",

        # Why
        "error_type": "KubernetesError",
        "original_error": "namespace not found",

        # How to fix
        "suggestion": "Create namespace with: kubectl create namespace mahavishnu"
    }
)

# Bad: Minimal context
error = PoolCreationError(
    message="Pool creation failed",
    details={"error": "failed"}  # Not helpful!
)
```

### Structured Logging

```python
import logging

logger = logging.getLogger(__name__)

try:
    result = risky_operation()
except SpecificError as e:
    # Structured logging with extra context
    logger.error(
        f"Operation failed: {e}",
        extra={
            "operation": "risky_operation",
            "error_type": type(e).__name__,
            "context": "additional_context"
        },
        exc_info=True  # Include stack trace
    )
    raise
```

## Exception Chaining

### Always Use `from e`

```python
# Good: Preserves original traceback
try:
    config = load_config(path)
except FileNotFoundError as e:
    raise ConfigLoadError(
        message="Config file not found",
        details={"path": path}
    ) from e  # ← Preserves original exception

# Bad: Loses original traceback
try:
    config = load_config(path)
except FileNotFoundError as e:
    raise ConfigLoadError("Config not found")  # ← Original error lost!
```

## Testing Exception Handling

### pytest Patterns

```python
import pytest
from mahavishnu.core.errors import PoolCreationError

def test_pool_creation_fails():
    """Test that invalid config raises PoolCreationError."""
    with pytest.raises(PoolCreationError) as exc_info:
        create_invalid_pool()

    # Check message
    assert "invalid" in str(exc_info.value).lower()

    # Check details
    assert exc_info.value.details["pool_type"] == "invalid"

    # Check exception type
    assert isinstance(exc_info.value, PoolError)

def test_exception_to_dict():
    """Test error serialization."""
    error = PoolCreationError(
        "Failed",
        details={"pool": "test"}
    )
    result = error.to_dict()

    assert result["error_type"] == "PoolCreationError"
    assert result["message"] == "Failed"
    assert result["details"]["pool"] == "test"
```

## Quick Exception Type Reference

### By Domain

**Configuration**:
- `ConfigurationError` - Base config errors
- `ConfigLoadError` - Failed to load config file
- `ConfigValidationError` - Invalid config values
- `ConfigNotFoundError` - Config file missing

**Repository**:
- `RepositoryError` - Base repo errors
- `RepositoryNotFoundError` - Repo not in manifest
- `RepositoryAccessError` - Cannot access repo
- `RepositoryValidationError` - Invalid repo structure

**Pool**:
- `PoolError` - Base pool errors
- `PoolCreationError` - Failed to create pool
- `PoolExecutionError` - Task execution failed
- `PoolNotFoundError` - Pool ID not found
- `PoolHealthCheckError` - Health check failed

**Worker**:
- `WorkerError` - Base worker errors
- `WorkerInitializationError` - Worker failed to start
- `WorkerExecutionError` - Worker task failed
- `WorkerTimeoutError` - Worker task timed out

**Communication**:
- `CommunicationError` - Base comm errors
- `MCPConnectionError` - MCP connection failed
- `MessageBusError` - Message bus operation failed
- `NetworkError` - Network operation failed

**Integration**:
- `IntegrationError` - Base integration errors
- `KubernetesError` - K8s operation failed
- `OpenSearchError` - OpenSearch operation failed
- `TemporalError` - Temporal operation failed
- `ExternalServiceError` - External service failed

### By Operation

| Operation | Exception | When to Use |
|-----------|-----------|-------------|
| File I/O | `FileSystemError` | File read/write failures |
| Database | `DatabaseError` | SQL/query failures |
| Config parsing | `ConfigLoadError` | YAML/JSON parse errors |
| Validation | `ValidationError` | Invalid input/data |
| Missing resource | `ResourceNotFoundError` | Resource not found |
| Resource allocation | `ResourceAllocationError` | Cannot allocate resource |
| Network request | `NetworkError` | Connection/timeout errors |
| HTTP request | `ExternalServiceError` | HTTP API errors |
| MCP call | `MCPConnectionError` | MCP server errors |
| Pool creation | `PoolCreationError` | Pool init failures |
| Worker execution | `WorkerExecutionError` | Worker task failures |

## Anti-Patterns to Avoid

### Don't Use Bare Except

```python
# Bad: Catches SystemExit, KeyboardInterrupt
try:
    operation()
except:
    pass

# Good: Specific exceptions
try:
    operation()
except (ValueError, TypeError) as e:
    logger.error(f"Expected error: {e}")
```

### Don't Swallow Exceptions

```python
# Bad: Silent failure
try:
    operation()
except Exception:
    pass  # Error lost!

# Good: Log and re-raise
try:
    operation()
except Exception as e:
    logger.error(f"Operation failed: {e}", exc_info=True)
    raise
```

### Don't Use Generic Exception Without Cause

```python
# Bad: Loses original error
try:
    operation()
except Exception:
    raise PoolError("Failed")

# Good: Preserves chain
try:
    operation()
except SpecificError as e:
    raise PoolError("Failed") from e
```

## Checklist

When writing exception handling:

- [ ] Use specific exception types (not bare `except Exception`)
- [ ] Include context in `details` dictionary
- [ ] Use exception chaining with `from e`
- [ ] Log errors with structured logging
- [ ] Provide actionable suggestions in error messages
- [ ] Test error paths in unit tests
- [ ] Document exceptions in docstrings
- [ ] Use domain-specific exceptions when available
- [ ] Group related exceptions when handling is identical
- [ ] Keep one catch-all for truly unexpected errors (document why)

## Getting Help

- Exception hierarchy: `/Users/les/Projects/mahavishnu/mahavishnu/core/errors.py`
- Test examples: `/Users/les/Projects/mahavishnu/tests/unit/test_errors.py`
- Demo fix: `/Users/les/Projects/mahavishnu/mahavishnu/pools/kubernetes_pool.py`
- Scanner tool: `/Users/les/Projects/mahavishnu/scripts/fix_exceptions.py`

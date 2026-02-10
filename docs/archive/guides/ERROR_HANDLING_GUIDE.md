# Error Handling Quick Reference Guide

## CLI Error Handling Patterns

### 1. Basic Pattern: Use `handle_cli_error()`

```python
from mahavishnu.cli_utils.error_handler import handle_cli_error

try:
    risky_operation()
except Exception as e:
    raise handle_cli_error(e, "Failed to perform operation")
```

### 2. Context Manager Pattern: Use `CLIErrorHandler`

```python
from mahavishnu.cli_utils.error_handler import CLIErrorHandler

with CLIErrorHandler("Failed to load configuration"):
    config = load_config()
```

### 3. Decorator Pattern: Use `@cli_error_handler`

```python
from mahavishnu.cli_utils.error_handler import cli_error_handler

@cli_error_handler("Failed to create backup")
def backup_create():
    ...
```

## What NOT to Do

### ❌ BAD: Losing Stack Traces

```python
# DON'T DO THIS - Loses stack trace!
except Exception as e:
    typer.echo(f"Error: {e}", err=True)
    raise typer.Exit(code=1) from None  # ❌ Stack trace lost
```

### ❌ BAD: Broad Exception Handling

```python
# DON'T DO THIS - Too broad, masks specific errors
except Exception as e:
    logger.error(f"Error: {e}")
    raise
```

## What TO Do

### ✅ GOOD: Preserve Stack Traces

```python
# DO THIS - Preserves full stack trace
except Exception as e:
    raise handle_cli_error(e, "Context describing what failed")
```

### ✅ GOOD: Specific Exception Types

```python
# DO THIS - Handle specific exceptions
except (FileNotFoundError, PermissionError) as e:
    logger.error(f"File access error: {e}", exc_info=e)
    raise FileSystemError(f"Cannot access file: {e}") from e
except ConfigurationError as e:
    logger.error(f"Configuration error: {e}", exc_info=e)
    raise
```

### ✅ GOOD: Custom Mahavishnu Errors

```python
from mahavishnu.core.errors import ConfigurationError

# DO THIS - Use custom exceptions with details
raise ConfigurationError(
    "Configuration validation failed",
    details={
        "config_file": "/path/to/config.yaml",
        "missing_keys": ["api_key", "database_url"]
    }
)
```

## Exception Hierarchy

```python
MahavishnuError (base)
├── ConfigurationError
├── ValidationError
├── AuthenticationError
├── AuthorizationError
├── RepositoryError
├── AdapterError
├── WorkflowError
├── PoolError
├── WorkerError
├── CommunicationError
├── ResourceError
├── StorageError
└── IntegrationError
```

## Logging Best Practices

### ✅ DO: Log with exc_info

```python
logger.error(f"Operation failed: {error}", exc_info=error)
```

### ✅ DO: Log with structured data

```python
logger.error(
    f"Configuration error: {error.message}",
    exc_info=error,
    extra={"error_details": error.details}
)
```

### ❌ DON'T: Log without context

```python
logger.error(str(error))  # ❌ No context, no stack trace
```

## Exception Chaining

### ✅ DO: Chain exceptions properly

```python
try:
    raise FileNotFoundError("config.yaml")
except Exception as e:
    raise ConfigurationError("Config loading failed") from e
```

### ❌ DON'T: Break exception chains

```python
try:
    raise FileNotFoundError("config.yaml")
except Exception:
    raise ConfigurationError("Config loading failed")  # ❌ Chain broken
```

## Testing Error Handling

### Test stack trace preservation

```python
def test_exception_chaining():
    try:
        raise ValueError("Original error")
    except Exception as e:
        with pytest.raises(typer.Exit) as exc_info:
            raise handle_cli_error(e, "Test context")

    # Verify chain is preserved
    assert exc_info.value.__cause__ is not None
    assert isinstance(exc_info.value.__cause__, ValueError)
```

## Quick Reference

| Pattern | Usage | Import |
|---------|-------|--------|
| `handle_cli_error(e, context)` | Function-style error handling | `from mahavishnu.cli_utils.error_handler import handle_cli_error` |
| `CLIErrorHandler(context)` | Context manager for error handling | `from mahavishnu.cli_utils.error_handler import CLIErrorHandler` |
| `@cli_error_handler(context)` | Decorator for functions | `from mahavishnu.cli_utils.error_handler import cli_error_handler` |
| `raise ... from e` | Exception chaining | Built-in Python syntax |
| `exc_info=error` | Log with stack trace | `import logging` |

## Common Mistakes

### Mistake 1: Using `from None`

```python
# ❌ WRONG
raise typer.Exit(code=1) from None

# ✅ RIGHT
raise handle_cli_error(e, "Operation failed")
```

### Mistake 2: Bare `except Exception`

```python
# ❌ WRONG
except Exception:
    pass

# ✅ RIGHT
except (ValueError, TypeError) as e:
    logger.error(f"Specific error: {e}", exc_info=e)
```

### Mistake 3: Logging without exc_info

```python
# ❌ WRONG
logger.error(f"Error: {e}")

# ✅ RIGHT
logger.error(f"Error: {e}", exc_info=e)
```

## Getting Help

- See `/Users/les/Projects/mahavishnu/mahavishnu/cli_utils/error_handler.py` for implementation
- See `/Users/les/Projects/mahavishnu/tests/unit/test_exception_handling.py` for examples
- See `/Users/les/Projects/mahavishnu/mahavishnu/core/errors.py` for exception hierarchy

## Checklist for New Code

- [ ] Use `handle_cli_error()` for CLI commands
- [ ] Never use `from None` in exception handling
- [ ] Always log with `exc_info=error`
- [ ] Use specific exception types when possible
- [ ] Chain exceptions with `raise ... from e`
- [ ] Include error context in messages
- [ ] Add tests for error handling

# Type Hint Guide for Mahavishnu

**Version**: 1.0.0
**Date**: 2025-02-08
**Status**: Production Ready

## Overview

This guide provides comprehensive patterns and conventions for type hints in the Mahavishnu codebase.

## Basic Type Hints

### Function Parameters and Returns

```python
from pathlib import Path

def load_config(
    path: Path,
    validate: bool = True,
) -> dict[str, Any]:
    """Load configuration from a file.

    Args:
        path: Path to configuration file
        validate: Whether to validate the configuration

    Returns:
        Configuration dictionary
    """
    return {}
```

### Optional Parameters

```python
def get_repository(
    name: str,
    tags: list[str] | None = None,
) -> dict[str, Any] | None:
    """Get repository by name with optional tag filtering."""
    return None
```

## Type Aliases

```python
from pathlib import Path
from typing import NewType

# Simple aliases
RepoPath = Path
RepoTags = list[str]

# NewType for distinct string types
PoolId = NewType("PoolId", str)
WorkflowId = NewType("WorkflowId", str)
```

## TypedDict

```python
from typing import TypedDict

class RepositoryMetadata(TypedDict):
    """Structured repository metadata."""
    name: str
    path: str
    role: str
    tags: list[str]
    description: str
```

## Protocols

```python
from typing import Protocol

class OrchestratorAdapter(Protocol):
    """Protocol for orchestration engine adapters."""

    async def execute(
        self,
        task: dict[str, Any],
        repos: list[str]
    ) -> dict[str, Any]:
        """Execute a task."""
        ...

    async def get_health(self) -> dict[str, Any]:
        """Get adapter health status."""
        ...
```

## Async Type Hints

```python
async def execute_workflow(
    workflow_id: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    """Execute a workflow asynchronously."""
    await asyncio.sleep(1)
    return {"status": "completed"}
```

## Running Type Checkers

```bash
# Pyright (recommended)
pyright mahavishnu/

# MyPy (alternative)
mypy mahavishnu/
```

## Best Practices

### DO
- Add type hints to all public APIs
- Use type aliases for complex types
- Use TypedDict for structured data
- Use protocols for interfaces
- Run type checkers before committing

### DON'T
- Use Any as a shortcut
- Skip type hints for private methods
- Use type: ignore without explanation

## References

- PEP 484: Type Hints
- PEP 585: Type Hinting Generics
- PEP 589: TypedDict
- Pyright Documentation

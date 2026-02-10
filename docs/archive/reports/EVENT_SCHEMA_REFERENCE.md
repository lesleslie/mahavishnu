# Event Schema Reference Guide (Mahavishnu/Oneiric)

This guide provides comprehensive reference documentation for JSON Schema export and validation in the Mahavishnu/Oneiric event models.

## Table of Contents

- [Overview](#overview)
- [Schema Versioning](#schema-versioning)
- [Event Model Schemas](#event-model-schemas)
- [Creating Events](#creating-events)
- [Validation Examples](#validation-examples)
- [Schema Evolution](#schema-evolution)
- [API Reference](#api-reference)

## Overview

All event models in Oneiric support JSON Schema export and validation:

- **SessionStartEvent**: Created when an admin shell starts
- **SessionEndEvent**: Created when an admin shell exits
- **UserInfo**: User information component
- **EnvironmentInfo**: Environment information component

### Quick Start

```python
from oneiric.shell.event_models import SessionStartEvent, SessionEndEvent

# Create events from system environment
start_event = SessionStartEvent.create(
    component_name="mahavishnu",
    shell_type="MahavishnuShell"
)

end_event = SessionEndEvent.create(
    session_id="sess_abc123",
    metadata={"exit_reason": "user_exit"}
)

# Get JSON Schema
schema = SessionStartEvent.json_schema()

# Validate JSON data
event = SessionStartEvent.validate_json('{"event_version": "1.0", ...}')
```

## Schema Versioning

### Current Version

- **Version**: 1.0
- **Schema Draft**: JSON Schema 2020-12
- **Compatibility**: Exact version matching only

### Version Format

All schemas include version metadata:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "event_version": "1.0",
  "title": "SessionStartEvent"
}
```

### Backward Compatibility Strategy

**Current Policy (v1.0)**: Exact version matching required

**Future Policy (planned for v2.0+)**:
- Additive changes only (new optional fields)
- No breaking changes to existing fields
- Semantic versioning (MAJOR.MINOR.PATCH)
- Minor version updates for additive changes
- Major version updates for breaking changes

## Event Model Schemas

### SessionStartEvent

Full JSON Schema for SessionStartEvent:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "event_version": "1.0",
  "title": "SessionStartEvent",
  "type": "object",
  "properties": {
    "event_version": {
      "type": "string",
      "description": "Event format version (currently '1.0')"
    },
    "event_id": {
      "type": "string",
      "format": "uuid",
      "description": "Unique event identifier (UUID v4 string)"
    },
    "event_type": {
      "type": "string",
      "const": "session_start",
      "description": "Event type discriminator"
    },
    "component_name": {
      "type": "string",
      "pattern": "^[a-zA-Z0-9_-]+$",
      "description": "Component name (e.g., 'mahavishnu', 'session-buddy')"
    },
    "shell_type": {
      "type": "string",
      "description": "Shell class name (e.g., 'MahavishnuShell')"
    },
    "timestamp": {
      "type": "string",
      "format": "date-time",
      "description": "ISO 8601 timestamp in UTC"
    },
    "pid": {
      "type": "integer",
      "minimum": 1,
      "maximum": 4194304,
      "description": "Process ID (1-4194304)"
    },
    "user": {
      "$ref": "#/$defs/UserInfo"
    },
    "hostname": {
      "type": "string",
      "description": "System hostname"
    },
    "environment": {
      "$ref": "#/$defs/EnvironmentInfo"
    },
    "metadata": {
      "type": "object",
      "additionalProperties": true,
      "default": {},
      "description": "Optional additional metadata"
    }
  },
  "required": [
    "event_version",
    "event_id",
    "component_name",
    "shell_type",
    "timestamp",
    "pid",
    "user",
    "hostname",
    "environment"
  ],
  "$defs": {
    "UserInfo": {
      "type": "object",
      "properties": {
        "username": {
          "type": "string",
          "maxLength": 100,
          "description": "System username (truncated to 100 characters)"
        },
        "home": {
          "type": "string",
          "maxLength": 500,
          "description": "User home directory path (truncated to 500 characters)"
        }
      },
      "required": ["username", "home"]
    },
    "EnvironmentInfo": {
      "type": "object",
      "properties": {
        "python_version": {
          "type": "string",
          "description": "Python interpreter version"
        },
        "platform": {
          "type": "string",
          "description": "Operating system and platform identifier"
        },
        "cwd": {
          "type": "string",
          "maxLength": 500,
          "description": "Current working directory (truncated to 500 characters)"
        }
      },
      "required": ["python_version", "platform", "cwd"]
    }
  }
}
```

### SessionEndEvent

Full JSON Schema for SessionEndEvent:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "event_version": "1.0",
  "title": "SessionEndEvent",
  "type": "object",
  "properties": {
    "event_type": {
      "type": "string",
      "const": "session_end",
      "description": "Event type discriminator"
    },
    "session_id": {
      "type": "string",
      "description": "Session ID from SessionStartEvent response"
    },
    "timestamp": {
      "type": "string",
      "format": "date-time",
      "description": "ISO 8601 timestamp in UTC"
    },
    "metadata": {
      "type": "object",
      "additionalProperties": true,
      "default": {},
      "description": "Optional additional metadata"
    }
  },
  "required": ["session_id", "timestamp"]
}
```

## Creating Events

### Creating SessionStartEvent

The easiest way to create events is using the `.create()` class method, which automatically populates fields from the system environment:

```python
from oneiric.shell.event_models import SessionStartEvent

# Create event with automatic system data
event = SessionStartEvent.create(
    component_name="mahavishnu",
    shell_type="MahavishnuShell"
)

# Add custom metadata
event = SessionStartEvent.create(
    component_name="mahavishnu",
    shell_type="MahavishnuShell",
    metadata={
        "test_mode": True,
        "workspace": "/path/to/workspace"
    }
)

print(f"Event ID: {event.event_id}")
print(f"Timestamp: {event.timestamp}")
print(f"User: {event.user.username}")
print(f"PID: {event.pid}")
```

### Creating SessionEndEvent

```python
from oneiric.shell.event_models import SessionEndEvent

# Create event with session_id
event = SessionEndEvent.create(
    session_id="sess_abc123"
)

# Add metadata
event = SessionEndEvent.create(
    session_id="sess_abc123",
    metadata={
        "exit_reason": "user_exit",
        "duration_seconds": 3600
    }
)

print(f"Session ID: {event.session_id}")
print(f"Timestamp: {event.timestamp}")
```

### Manual Event Creation

You can also create events manually by providing all fields:

```python
from oneiric.shell.event_models import (
    SessionStartEvent,
    UserInfo,
    EnvironmentInfo
)

event = SessionStartEvent(
    event_version="1.0",
    event_id="550e8400-e29b-41d4-a716-446655440000",
    event_type="session_start",
    component_name="mahavishnu",
    shell_type="MahavishnuShell",
    timestamp="2026-02-06T12:34:56.789Z",
    pid=12345,
    user=UserInfo(username="john", home="/home/john"),
    hostname="server01",
    environment=EnvironmentInfo(
        python_version="3.13.0",
        platform="Linux-6.5.0-x86_64",
        cwd="/home/john/projects/mahavishnu"
    ),
    metadata={"custom": "data"}
)
```

## Validation Examples

### Validate JSON String

```python
from oneiric.shell.event_models import SessionStartEvent

json_str = """
{
  "event_version": "1.0",
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "component_name": "mahavishnu",
  "shell_type": "MahavishnuShell",
  "timestamp": "2026-02-06T12:34:56.789Z",
  "pid": 12345,
  "user": {
    "username": "john",
    "home": "/home/john"
  },
  "hostname": "server01",
  "environment": {
    "python_version": "3.13.0",
    "platform": "Linux-6.5.0-x86_64",
    "cwd": "/home/john/projects/mahavishnu"
  }
}
"""

event = SessionStartEvent.validate_json(json_str)
print(event.event_id)
```

### Validate JSON Dictionary

```python
from oneiric.shell.event_models import SessionEndEvent

json_dict = {
    "session_id": "sess_abc123",
    "timestamp": "2026-02-06T13:45:67.890Z",
    "metadata": {"exit_reason": "user_exit"}
}

event = SessionEndEvent.validate_json(json_dict)
print(event.session_id)
```

### Safe Validation with Error Handling

```python
from oneiric.shell.event_models import SessionStartEvent

invalid_json = '{"event_version": "2.0", ...}'  # Wrong version

event, error = SessionStartEvent.validate_json_safe(invalid_json)
if error:
    print(f"Validation failed: {error}")
else:
    print(f"Valid event: {event.event_id}")
```

### Using Schema Registry

```python
from oneiric.shell.schemas import (
    get_all_schemas,
    get_schema,
    validate_event_json,
)

# Get all schemas
schemas = get_all_schemas()

# Get specific schema
schema = get_schema("SessionStartEvent")

# Validate using registry
event = validate_event_json("SessionStartEvent", json_data)
```

### Export Schemas to File

```python
from oneiric.shell.schemas import export_schemas_to_file

# Export as JSON
export_schemas_to_file("event_schemas.json")

# Export as YAML (requires pyyaml)
export_schemas_to_file("event_schemas.yaml", format="yaml")
```

## Schema Evolution

### Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-02-06 | Initial schema version |

### Evolution Guidelines

**Additive Changes (Minor Version Update)**:
- Add new optional fields
- Add new validation rules that don't break existing valid data
- Extend metadata schemas

**Breaking Changes (Major Version Update)**:
- Remove or rename fields
- Change field types
- Make required fields optional
- Tighten validation constraints

### Migration Strategy

When upgrading to a new schema version:

1. **Update event_version field** in emitted events
2. **Update validation logic** in Session-Buddy
3. **Support multiple versions** during transition period
4. **Test backward compatibility**

## API Reference

### Model Methods

#### `SessionStartEvent.create()`

Create SessionStartEvent from system environment.

```python
@classmethod
def create(
    cls,
    component_name: str,
    shell_type: str,
    metadata: dict[str, Any] | None = None,
) -> SessionStartEvent:
    """Create SessionStartEvent from current system environment."""
```

**Parameters**:
- `component_name`: Component name (e.g., "mahavishnu", "session-buddy")
- `shell_type`: Shell class name (e.g., "MahavishnuShell")
- `metadata`: Optional additional metadata

**Returns**: SessionStartEvent instance

#### `SessionEndEvent.create()`

Create SessionEndEvent with current timestamp.

```python
@classmethod
def create(
    cls,
    session_id: str,
    metadata: dict[str, Any] | None = None,
) -> SessionEndEvent:
    """Create SessionEndEvent with current timestamp."""
```

**Parameters**:
- `session_id`: Session ID from SessionStartEvent response
- `metadata`: Optional additional metadata

**Returns**: SessionEndEvent instance

#### `json_schema()`

Get JSON Schema for the model.

```python
@classmethod
def json_schema(cls) -> dict[str, Any]:
    """Get JSON Schema for this model."""
```

**Returns**: JSON Schema dictionary

#### `validate_json()`

Validate JSON data and return model instance.

```python
@classmethod
def validate_json(cls, json_data: str | dict[str, Any]) -> JsonSchemaMixin:
    """Validate JSON data and return model instance."""
```

**Parameters**:
- `json_data`: JSON string or dictionary

**Returns**: Validated model instance

**Raises**: `ValidationError` if data is invalid

#### `validate_json_safe()`

Validate JSON data with error handling.

```python
@classmethod
def validate_json_safe(
    cls,
    json_data: str | dict[str, Any],
) -> tuple[JsonSchemaMixin | None, Exception | None]:
    """Validate JSON data with error handling."""
```

**Parameters**:
- `json_data`: JSON string or dictionary

**Returns**: Tuple of (model_instance, error)

### Schema Registry Functions

#### `get_all_schemas()`

Get all event model schemas.

```python
def get_all_schemas() -> dict[str, dict[str, Any]]:
    """Get JSON schemas for all event models."""
```

**Returns**: Dictionary mapping model names to schemas

#### `get_schema(model_name)`

Get schema for a specific model.

```python
def get_schema(model_name: str) -> dict[str, Any]:
    """Get JSON Schema for a specific model."""
```

**Parameters**:
- `model_name`: Name of the model

**Returns**: JSON Schema dictionary

**Raises**: `ValueError` if model not found

#### `validate_event_json()`

Validate JSON against a model schema.

```python
def validate_event_json(
    model_name: str,
    json_data: str | dict[str, Any],
) -> Any:
    """Validate JSON data against an event model schema."""
```

**Parameters**:
- `model_name`: Name of the model
- `json_data`: JSON string or dictionary

**Returns**: Validated model instance

#### `export_schemas_to_file()`

Export all schemas to a file.

```python
def export_schemas_to_file(
    output_path: str | Path,
    format: Literal["json", "yaml"] = "json",
) -> None:
    """Export all schemas to a file."""
```

**Parameters**:
- `output_path`: Path to output file
- `format`: Output format ("json" or "yaml")

**Raises**: `ValueError` if format not supported

## Best Practices

### 1. Use .create() for Event Creation

```python
# Good - automatic system data
event = SessionStartEvent.create(
    component_name="mahavishnu",
    shell_type="MahavishnuShell"
)

# Bad - manual data entry
event = SessionStartEvent(
    event_version="1.0",
    event_id=str(uuid.uuid4()),
    timestamp=datetime.now(timezone.utc).isoformat(),
    pid=os.getpid(),
    user=UserInfo.from_system(),
    # ... more fields
)
```

### 2. Validate All External JSON

```python
# Good - validate input
event = SessionStartEvent.validate_json(json_data)

# Bad - trust input
event = SessionStartEvent(**json_data)
```

### 3. Use Safe Validation for User Input

```python
event, error = SessionStartEvent.validate_json_safe(user_input)
if error:
    logger.error(f"Invalid event: {error}")
    return {"status": "error", "message": str(error)}
```

### 4. Include Useful Metadata

```python
event = SessionStartEvent.create(
    component_name="mahavishnu",
    shell_type="MahavishnuShell",
    metadata={
        "test_mode": True,
        "workspace": "/path/to/workspace",
        "git_branch": "main",
        "git_commit": "abc123"
    }
)
```

### 5. Export Schemas for Documentation

```python
# Generate schema documentation
from oneiric.shell.schemas import export_schemas_to_file

export_schemas_to_file("docs/event_schemas.json")
```

## Integration with Session-Buddy

### Sending Events to Session-Buddy

```python
import asyncio
from oneiric.shell.event_models import SessionStartEvent, SessionEndEvent
from oneiric.shell.session_tracker import SessionEventEmitter

async def track_session():
    emitter = SessionEventEmitter(
        component_name="mahavishnu"
    )

    # Create and emit session start
    start_event = SessionStartEvent.create(
        component_name="mahavishnu",
        shell_type="MahavishnuShell"
    )

    session_id = await emitter.emit_session_start(
        shell_type="MahavishnuShell",
        metadata=start_event.dict()
    )

    # ... do work ...

    # Emit session end
    end_event = SessionEndEvent.create(
        session_id=session_id,
        metadata={"exit_reason": "normal"}
    )

    await emitter.emit_session_end(
        session_id=session_id,
        metadata=end_event.dict()
    )
```

## Testing

### Test Event Creation

```python
def test_create_session_start_event():
    """Test SessionStartEvent creation."""
    from oneiric.shell.event_models import SessionStartEvent

    event = SessionStartEvent.create(
        component_name="mahavishnu",
        shell_type="MahavishnuShell"
    )

    assert event.event_version == "1.0"
    assert event.component_name == "mahavishnu"
    assert event.shell_type == "MahavishnuShell"
    assert event.event_type == "session_start"
    assert len(event.event_id) == 36  # UUID v4 format
```

### Test JSON Validation

```python
def test_validate_json():
    """Test JSON validation."""
    from oneiric.shell.event_models import SessionStartEvent

    json_data = {
        "event_version": "1.0",
        "event_id": "550e8400-e29b-41d4-a716-446655440000",
        "component_name": "mahavishnu",
        "shell_type": "MahavishnuShell",
        "timestamp": "2026-02-06T12:34:56.789Z",
        "pid": 12345,
        "user": {"username": "john", "home": "/home/john"},
        "hostname": "server01",
        "environment": {
            "python_version": "3.13.0",
            "platform": "Linux-6.5.0-x86_64",
            "cwd": "/home/john/projects"
        }
    }

    event = SessionStartEvent.validate_json(json_data)
    assert event.component_name == "mahavishnu"
```

### Test Schema Export

```python
def test_json_schema_export():
    """Test JSON Schema export."""
    from oneiric.shell.event_models import SessionStartEvent

    schema = SessionStartEvent.json_schema()

    assert "$schema" in schema
    assert "event_version" in schema
    assert schema["event_version"] == "1.0"
    assert schema["type"] == "object"
```

## Troubleshooting

### Common Errors

**ValidationError: Unsupported event version**

```python
# Solution: Check event version
event_version = event_data.get("event_version")
if event_version != "1.0":
    raise ValueError(f"Only version 1.0 supported, got {event_version}")
```

**ValidationError: Invalid component_name format**

```python
# Solution: Use valid component names
# Valid: "mahavishnu", "session-buddy", "my_component"
# Invalid: "my component", "my.component", "my$component"
```

**ValidationError: Invalid timestamp format**

```python
# Solution: Ensure ISO 8601 with time component
# Valid: "2026-02-06T12:34:56.789Z"
# Invalid: "2026-02-06" (missing time)
```

## Additional Resources

- [JSON Schema Specification](https://json-schema.org/specification)
- [Pydantic Documentation](https://docs.pydantic.dev/)
- [Session-Buddy Schema Reference](../../../session-buddy/docs/JSON_SCHEMA_REFERENCE.md)
- [Event Models Source](../oneiric/shell/event_models.py)

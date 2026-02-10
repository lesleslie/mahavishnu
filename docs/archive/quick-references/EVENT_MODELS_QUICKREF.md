# Event Models Quick Reference

## Import

### Oneiric
```python
from oneiric.shell.event_models import (
    SessionStartEvent,
    SessionEndEvent,
    UserInfo,
    EnvironmentInfo,
    get_session_start_event_schema,
    get_session_end_event_schema,
)
```

### Session-Buddy
```python
from session_buddy.mcp.event_models import (
    SessionStartEvent,
    SessionEndEvent,
    SessionStartResult,
    SessionEndResult,
    ErrorResponse,
    UserInfo,
    EnvironmentInfo,
)
```

## Create Events

### Session Start
```python
event = SessionStartEvent(
    event_version="1.0",  # Must be "1.0"
    event_id="550e8400-e29b-41d4-a716-446655440000",  # UUID v4
    component_name="mahavishnu",  # ^[a-zA-Z0-9_-]+$
    shell_type="MahavishnuShell",  # Class name
    timestamp="2026-02-06T12:34:56.789Z",  # ISO 8601 with T
    pid=12345,  # 1-4194304
    user=UserInfo(
        username="john",  # max 100 chars
        home="/home/john"  # max 500 chars
    ),
    hostname="server01",
    environment=EnvironmentInfo(
        python_version="3.13.0",
        platform="Linux-6.5.0-x86_64",
        cwd="/home/john/projects"  # max 500 chars
    ),
    metadata={}  # Optional
)
```

### Session End
```python
event = SessionEndEvent(
    session_id="sess_abc123",  # From start result
    timestamp="2026-02-06T13:45:00.000Z",
    metadata={"exit_reason": "user_exit"}  # Optional
)
```

## Create Results (Session-Buddy only)

### Success
```python
result = SessionStartResult(
    session_id="sess_abc123",
    status="tracked"
)

result = SessionEndResult(
    session_id="sess_abc123",
    status="ended"  # or "not_found"
)
```

### Error
```python
result = SessionStartResult(
    session_id=None,
    status="error",
    error="Database connection failed"
)

result = SessionEndResult(
    session_id="sess_abc123",
    status="error",
    error="Session not found"
)
```

## Validation Rules

| Field | Rule | Error Message |
|-------|------|---------------|
| `event_id` | UUID v4 | "Invalid UUID v4 format: {value}" |
| `event_version` | Must be "1.0" | "Unsupported event version: {value}" |
| `component_name` | `^[a-zA-Z0-9_-]+$` | "Invalid component_name '{value}': must match pattern {pattern}" |
| `timestamp` | ISO 8601 with T | "Invalid ISO 8601 timestamp: {value}" |
| `pid` | 1-4,194,304 | "greater than or equal to 1" or "less than or equal to 4194304" |
| `username` | max 100 chars | "at most 100 characters" |
| `home` | max 500 chars | "at most 500 characters" |
| `cwd` | max 500 chars | "at most 500 characters" |

## Valid Component Names

✅ Valid: `mahavishnu`, `session-buddy`, `oneiric`, `my_component`, `MyComponent-123`
❌ Invalid: `invalid@component`, `component with spaces`, `component/with/slashes`, `component.with.dots`

## Timestamp Formats

✅ Valid: `2026-02-06T12:34:56.789Z`, `2026-02-06T12:34:56Z`
❌ Invalid: `2026-02-06` (date only), `12:34:56` (time only), `not-a-timestamp`

## Export JSON Schema

```python
from oneiric.shell.event_models import get_session_start_event_schema

schema = get_session_start_event_schema()
# Use with jsonschema library or documentation
```

## Serialize/Deserialize

```python
# To dict
event_dict = event.model_dump()

# To JSON
event_json = event.model_dump_json()

# From dict
event = SessionStartEvent(**event_dict)

# From JSON
event = SessionStartEvent.model_validate_json(event_json)
```

## Handle Validation Errors

```python
from pydantic import ValidationError

try:
    event = SessionStartEvent(**data)
except ValidationError as e:
    print(f"Validation error: {e}")
    # e.errors() gives list of specific errors
```

## Test

### Oneiric
```bash
cd /Users/les/Projects/oneiric
pytest tests/shell/test_event_models.py -v
```

### Session-Buddy
```bash
cd /Users/les/Projects/session-buddy
pytest tests/mcp/test_event_models.py -v
```

## File Locations

| Project | File | Lines |
|---------|------|-------|
| Oneiric | `/Users/les/Projects/oneiric/oneiric/shell/event_models.py` | 449 |
| Oneiric | `/Users/les/Projects/oneiric/tests/shell/test_event_models.py` | 370 |
| Session-Buddy | `/Users/les/Projects/session-buddy/session_buddy/mcp/event_models.py` | 690 |
| Session-Buddy | `/Users/les/Projects/session-buddy/tests/mcp/test_event_models.py` | 520 |

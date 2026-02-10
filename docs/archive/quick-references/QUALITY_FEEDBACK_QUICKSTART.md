# Quality Feedback Loop - Quick Start Guide

## What is it?

Integration #1 from the ecosystem integration plan that connects:
- **Crackerjack** (quality issue detection)
- **Session-Buddy** (issue storage and pattern detection)
- **Mahavishnu** (systematic fix workflows)

## Quick Start

### 1. Basic Usage

```python
from mahavishnu.integrations.quality_feedback import QualityFeedbackLoop
from mahavishnu.core.config import MahavishnuSettings

# Initialize
config = MahavishnuSettings()
loop = QualityFeedbackLoop(config)
await loop.initialize()

# Store quality issue
issue_id = await loop.store_quality_issue(
    issue_type="complexity",
    file_path="mahavishnu/core/app.py",
    severity="warning",
    suggestion="Extract complex method into smaller functions",
    context="function='process_workflow' complexity=25"
)

# Check pattern frequency
frequency = await loop.check_pattern_frequency("complexity")

# Trigger systematic fix if threshold exceeded
if frequency >= 5:
    workflow_id = await loop.trigger_systematic_fix("complexity")
    print(f"Systematic fix triggered: {workflow_id}")

# Cleanup
await loop.shutdown()
```

### 2. Convenience Functions

```python
from mahavishnu.integrations.quality_feedback import (
    store_quality_issue,
    check_pattern_frequency,
    trigger_systematic_fix,
)

# Single-call functions
issue_id = await store_quality_issue(config, ...)
frequency = await check_pattern_frequency(config, "complexity")
workflow_id = await trigger_systematic_fix(config, "complexity")
```

### 3. Event-Driven

```python
from mahavishnu.integrations.base import IntegrationEvent

event = IntegrationEvent(
    source_system="crackerjack",
    event_type="quality_issue",
    severity="warning",
    data={
        "issue_type": "complexity",
        "file_path": "mahavishnu/core/app.py",
        "severity": "warning",
        "suggestion": "Extract complex method",
        "context": "complexity=25"
    }
)

result = await loop.process(event)
```

## Configuration

### YAML (settings/mahavishnu.yaml)
```yaml
quality_pattern_threshold: 5
quality_similarity_threshold: 0.8
session_buddy_url: "http://localhost:8678/mcp"
```

### Environment Variables
```bash
export MAHAVISHNU_QUALITY_PATTERN_THRESHOLD=5
export MAHAVISHNU_QUALITY_SIMILARITY_THRESHOLD=0.8
export MAHAVISHNU_SESSION_BUDDY_URL=http://localhost:8678/mcp
```

## Core Functions

| Function | Purpose | Returns |
|----------|---------|---------|
| `store_quality_issue()` | Store issue in Session-Buddy | Issue ID |
| `link_to_similar_issues()` | Link related issues | None |
| `check_pattern_frequency()` | Count issue occurrences | Frequency count |
| `trigger_systematic_fix()` | Trigger systematic fix | Workflow ID |

## Issue Types

Common types tracked:
- `complexity` - High cyclomatic complexity
- `linting` - Code style violations
- `type_checking` - Type annotation errors
- `security` - Security vulnerabilities
- `coverage` - Insufficient test coverage
- `performance` - Performance issues

## Statistics

```python
stats = loop.get_stats()

print(f"Issues stored: {stats['issues_stored']}")
print(f"Issues linked: {stats['issues_linked']}")
print(f"Patterns detected: {stats['patterns_detected']}")
print(f"Workflows triggered: {stats['workflows_triggered']}")
print(f"Errors: {stats['errors']}")
```

## Error Handling

```python
from mahavishnu.integrations.quality_feedback import (
    SessionBuddyConnectionError,
    PatternDetectionError,
    WorkflowTriggerError,
)

try:
    issue_id = await loop.store_quality_issue(...)
except SessionBuddyConnectionError as e:
    print(f"Connection failed: {e}")
except PatternDetectionError as e:
    print(f"Pattern detection failed: {e}")
except WorkflowTriggerError as e:
    print(f"Workflow trigger failed: {e}")
```

## Testing

Run tests:
```bash
pytest tests/unit/test_integrations/test_quality_feedback.py -v
```

Run demo:
```bash
python examples/quality_feedback_demo.py
```

## Files

- Implementation: `mahavishnu/integrations/quality_feedback.py`
- Tests: `tests/unit/test_integrations/test_quality_feedback.py`
- Documentation: `docs/QUALITY_FEEDBACK_LOOP.md`
- Demo: `examples/quality_feedback_demo.py`

## Status

✅ Production Ready
- 100% type annotated
- 25/25 tests passing
- Complete documentation
- Full error handling
- Async/await support
- MCP integration

## Architecture

```
┌─────────────┐      ┌──────────────┐      ┌─────────────┐
│ Crackerjack │ ───> │ Session-Buddy│ ───> │ Mahavishnu  │
│  (Detect)   │      │  (Store)     │      │   (Fix)     │
└─────────────┘      └──────────────┘      └─────────────┘
```

## Next Steps

1. Configure thresholds in `settings/mahavishnu.yaml`
2. Start Session-Buddy MCP server
3. Start Mahavishnu MCP server
4. Run quality checks with Crackerjack
5. Watch patterns emerge and systematic fixes trigger!

For detailed documentation, see:
- `docs/QUALITY_FEEDBACK_LOOP.md`
- `docs/QUALITY_FEEDBACK_IMPLEMENTATION.md`

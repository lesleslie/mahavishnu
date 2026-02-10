# Quality Feedback Loop Integration

## Overview

The Quality Feedback Loop is Integration #1 from the ecosystem integration plan, connecting **Crackerjack** → **Session-Buddy** → **Mahavishnu** to create a 100x quality improvement through continuous feedback and systematic fixes.

## Architecture

```
┌─────────────┐      ┌──────────────┐      ┌─────────────┐
│ Crackerjack │ ───> │ Session-Buddy│ ───> │ Mahavishnu  │
│  (Detect)   │      │  (Store)     │      │   (Fix)     │
└─────────────┘      └──────────────┘      └─────────────┘
       │                     │                     │
       v                     v                     v
  Quality Issues      Pattern Detection    Systematic Fix
```

### Components

1. **Crackerjack**: Detects quality issues (complexity, linting, security, etc.)
2. **Session-Buddy**: Stores issues with context and detects patterns
3. **Mahavishnu**: Triggers systematic fixes when patterns emerge

## Features

### 1. Store Quality Issues

Store quality issues with full context in Session-Buddy's knowledge graph:

```python
from mahavishnu.integrations.quality_feedback import store_quality_issue
from mahavishnu.core.config import MahavishnuSettings

config = MahavishnuSettings()

issue_id = await store_quality_issue(
    config=config,
    issue_type="complexity",
    file_path="mahavishnu/core/app.py",
    severity="warning",
    suggestion="Extract complex method into smaller functions",
    context="function='process_workflow' complexity=25"
)

print(f"Issue stored: {issue_id}")
```

### 2. Link Similar Issues

Automatically link similar issues to build pattern graphs:

```python
from mahavishnu.integrations.quality_feedback import link_to_similar_issues

await link_to_similar_issues(
    config=config,
    issue_id="issue_abc123",
    issue_type="complexity",
    file_path="mahavishnu/core/app.py"
)
```

### 3. Check Pattern Frequency

Count occurrences of specific issue types:

```python
from mahavishnu.integrations.quality_feedback import check_pattern_frequency

frequency = await check_pattern_frequency(
    config=config,
    issue_type="complexity"
)

print(f"Complexity issues found: {frequency}")

if frequency > 5:
    print("Pattern detected! Time for systematic fix.")
```

### 4. Trigger Systematic Fix

Automatically trigger coordinated fix across entire codebase:

```python
from mahavishnu.integrations.quality_feedback import trigger_systematic_fix

workflow_id = await trigger_systematic_fix(
    config=config,
    issue_type="complexity"
)

print(f"Systematic fix workflow started: {workflow_id}")
```

## Full Workflow Example

Complete example showing the entire feedback loop:

```python
import asyncio
from mahavishnu.integrations.quality_feedback import QualityFeedbackLoop
from mahavishnu.core.config import MahavishnuSettings

async def quality_feedback_example():
    # Initialize
    config = MahavishnuSettings()
    loop = QualityFeedbackLoop(config)
    await loop.initialize()

    try:
        # 1. Store quality issue (from Crackerjack)
        issue_id = await loop.store_quality_issue(
            issue_type="complexity",
            file_path="mahavishnu/core/app.py",
            severity="warning",
            suggestion="Extract complex method into smaller functions",
            context="function='process_workflow' complexity=25"
        )
        print(f"✓ Issue stored: {issue_id}")

        # 2. Link to similar issues
        await loop.link_to_similar_issues(
            issue_id=issue_id,
            issue_type="complexity",
            file_path="mahavishnu/core/app.py"
        )
        print("✓ Linked to similar issues")

        # 3. Check pattern frequency
        frequency = await loop.check_pattern_frequency("complexity")
        print(f"✓ Pattern frequency: {frequency}")

        # 4. Trigger systematic fix if threshold exceeded
        if frequency >= 5:
            workflow_id = await loop.trigger_systematic_fix("complexity")
            print(f"✓ Systematic fix triggered: {workflow_id}")
        else:
            print(f"✓ Threshold not met ({frequency}/5)")

        # 5. Get statistics
        stats = loop.get_stats()
        print(f"✓ Stats: {stats}")

    finally:
        await loop.shutdown()

# Run the example
asyncio.run(quality_feedback_example())
```

## Integration with Event System

The Quality Feedback Loop integrates with the Mahavishnu event system:

```python
from mahavishnu.integrations.base import IntegrationEvent
from mahavishnu.integrations.quality_feedback import QualityFeedbackLoop

# Create event
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

# Process event
loop = QualityFeedbackLoop(config)
await loop.initialize()

result = await loop.process(event)

if result:
    print(f"Systematic fix triggered: {result.data['workflow_id']}")
else:
    print("Issue stored, no systematic fix needed")

await loop.shutdown()
```

## Configuration

Configure the Quality Feedback Loop in `settings/mahavishnu.yaml`:

```yaml
# Quality Feedback Loop configuration
quality_pattern_threshold: 5  # Trigger systematic fix after 5 occurrences
quality_similarity_threshold: 0.8  # Similarity threshold for linking issues
session_buddy_url: "http://localhost:8678/mcp"  # Session-Buddy MCP endpoint
```

Or via environment variables:

```bash
export MAHAVISHNU_QUALITY_PATTERN_THRESHOLD=5
export MAHAVISHNU_QUALITY_SIMILARITY_THRESHOLD=0.8
export MAHAVISHNU_SESSION_BUDDY_URL="http://localhost:8678/mcp"
```

## Pattern Detection Logic

The Quality Feedback Loop uses the following pattern detection logic:

1. **Issue Storage**: Each quality issue is stored as an entity in Session-Buddy
2. **Similarity Linking**: Issues are linked based on type and file path
3. **Frequency Counting**: Count occurrences of each issue type
4. **Threshold Trigger**: When frequency exceeds threshold, trigger systematic fix

### Threshold Behavior

- **Default threshold**: 5 occurrences
- **Configurable**: Set `quality_pattern_threshold` in config
- **Per-issue type**: Each issue type tracked independently

## Issue Types

Common issue types tracked:

- `complexity`: High cyclomatic complexity
- `linting`: Code style violations (ruff, pylint, etc.)
- `type_checking`: Type annotation errors (mypy, pyright)
- `security`: Security vulnerabilities (bandit, safety)
- `coverage`: Insufficient test coverage
- `performance`: Performance issues
- `documentation`: Missing or incomplete docs

## Systematic Fix Workflow

When pattern threshold is exceeded, Mahavishnu triggers a systematic fix workflow:

1. **Search**: Find all occurrences of the issue type
2. **Analyze**: Determine common patterns and root causes
3. **Fix**: Apply systematic fixes across codebase
4. **Validate**: Run quality checks to verify fixes
5. **Report**: Generate summary of changes

## Statistics and Monitoring

Track Quality Feedback Loop performance:

```python
stats = loop.get_stats()

print(f"Issues stored: {stats['issues_stored']}")
print(f"Issues linked: {stats['issues_linked']}")
print(f"Patterns detected: {stats['patterns_detected']}")
print(f"Workflows triggered: {stats['workflows_triggered']}")
print(f"Errors: {stats['errors']}")
```

## Error Handling

The Quality Feedback Loop includes comprehensive error handling:

```python
from mahavishnu.integrations.quality_feedback import (
    QualityFeedbackError,
    SessionBuddyConnectionError,
    PatternDetectionError,
    WorkflowTriggerError,
)

try:
    issue_id = await loop.store_quality_issue(...)
except SessionBuddyConnectionError as e:
    print(f"Failed to connect to Session-Buddy: {e}")
except PatternDetectionError as e:
    print(f"Pattern detection failed: {e}")
except WorkflowTriggerError as e:
    print(f"Workflow trigger failed: {e}")
except QualityFeedbackError as e:
    print(f"Quality feedback error: {e}")
```

## Testing

Run tests for the Quality Feedback Loop:

```bash
# Run all quality feedback tests
pytest tests/unit/test_integrations/test_quality_feedback.py

# Run with coverage
pytest tests/unit/test_integrations/test_quality_feedback.py --cov=mahavishnu/integrations/quality_feedback

# Run specific test
pytest tests/unit/test_integrations/test_quality_feedback.py::TestQualityFeedbackLoop::test_store_quality_issue
```

## MCP Tools Used

### Session-Buddy MCP Tools

- `mcp__session_buddy__store_entity`: Store quality issue as entity
- `mcp__session_buddy__create_relation`: Link similar issues
- `mcp__session_buddy__search_entities`: Search for patterns
- `mcp__session_buddy__get_entity`: Get issue details

### Mahavishnu MCP Tools

- `mcp__mahavishnu__trigger_workflow`: Trigger systematic fix workflow

## Benefits

1. **Continuous Improvement**: Automatic detection and fixing of recurring issues
2. **Pattern Recognition**: Identify systemic problems across codebase
3. **Proactive Quality**: Fix issues before they become critical
4. **Time Savings**: Eliminate repetitive manual fixes
5. **Knowledge Preservation**: Store fix patterns for future reference

## Use Cases

### 1. Complexity Reduction

```python
# Detect high complexity functions
issue_id = await loop.store_quality_issue(
    issue_type="complexity",
    file_path="mahavishnu/core/app.py",
    severity="warning",
    suggestion="Extract complex method into smaller functions",
    context="function='process_workflow' complexity=25"
)

# After 5 occurrences, trigger systematic refactoring
workflow_id = await loop.trigger_systematic_fix("complexity")
```

### 2. Security Hardening

```python
# Detect security vulnerabilities
issue_id = await loop.store_quality_issue(
    issue_type="security",
    file_path="mahavishnu/auth.py",
    severity="critical",
    suggestion="Use parameterized queries to prevent SQL injection",
    context="line=42 vulnerability=sql_injection"
)

# Immediate fix for critical issues
if severity == "critical":
    workflow_id = await loop.trigger_systematic_fix("security")
```

### 3. Type Safety

```python
# Detect type errors
issue_id = await loop.store_quality_issue(
    issue_type="type_checking",
    file_path="mahavishnu/api/routes.py",
    severity="error",
    suggestion="Add type annotations for function parameters",
    context="function='handle_request' missing_types=True"
)

# Pattern-based fixes for type safety
workflow_id = await loop.trigger_systematic_fix("type_checking")
```

## Future Enhancements

Planned improvements to the Quality Feedback Loop:

1. **Machine Learning**: Use ML to predict which issues will recur
2. **Auto-Fix**: Automatically apply fixes without manual intervention
3. **Priority Scoring**: Rank issues by impact and effort
4. **Team Metrics**: Track quality trends across teams
5. **Integration with CI/CD**: Block PRs with recurring issues

## Related Documentation

- [Integration Architecture](./INTEGRATION_ARCHITECTURE.md)
- [Session-Buddy Integration](../docs/SESSION_BUDDY_INTEGRATION.md)
- [Crackerjack Quality Control](../docs/CRACKERJACK_QC.md)
- [MCP Tools Specification](./MCP_TOOLS_SPECIFICATION.md)

## Support

For issues or questions about the Quality Feedback Loop:

1. Check the test suite for examples
2. Review the integration documentation
3. Open an issue on GitHub

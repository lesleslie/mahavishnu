# Systematic Quality Fix Workflow

## Overview

The `SystematicQualityFixWorkflow` is an automated workflow for detecting and fixing quality issues across your entire codebase. It provides comprehensive safety checks, human approval for high-risk changes, testing validation, and instant rollback capabilities.

## Features

- **Automated Issue Detection**: Scans codebase for common quality issues
- **Intelligent Fix Generation**: Creates appropriate fixes for each issue type
- **Safety Checks**: Risk assessment and human approval for dangerous changes
- **Testing Validation**: Runs tests to validate fixes before committing
- **Instant Rollback**: Automatic rollback if tests fail
- **Comprehensive Logging**: Detailed audit trail of all changes

## Supported Issue Types

### 1. Path Traversal Vulnerabilities (CRITICAL)
**Risk Level**: Critical
**Requires Approval**: Yes

Detects potential path traversal vulnerabilities where unvalidated user input is used in file operations.

**Example Detection**:
```python
# Vulnerable code
def process_file(filename):
    data = open(filename).read()  # DETECTED: filename from user input
    return data
```

**Fix Applied**:
```python
# Fixed code
def process_file(filename):
    # Validate and sanitize filename
    safe_path = Path(filename).resolve()
    if not safe_path.is_relative_to(BASE_DIR):
        raise ValueError("Invalid path")
    data = open(safe_path).read()
    return data
```

### 2. MD5 Usage (LOW)
**Risk Level**: Low
**Requires Approval**: No

Detects usage of MD5 hash algorithm which is not compliant with modern security standards.

**Example Detection**:
```python
# Non-compliant code
import hashlib
hash_value = hashlib.md5(data.encode()).hexdigest()
```

**Fix Applied**:
```python
# Fixed code
import hashlib
hash_value = hashlib.sha256(data.encode()).hexdigest()
```

### 3. Missing Type Hints (LOW)
**Risk Level**: Low
**Requires Approval**: No

Detects functions and methods missing type hints.

**Example Detection**:
```python
# Without type hints
def calculate(a, b):
    return a + b
```

**Fix Applied**:
```python
# With type hints
def calculate(a: int, b: int) -> int:
    return a + b
```

### 4. Generic Exception Handling (MEDIUM)
**Risk Level**: Medium
**Requires Approval**: No

Detects overly broad exception handling that can hide errors.

**Example Detection**:
```python
# Generic exception handling
try:
    result = perform_operation()
except Exception:  # DETECTED: Too broad
    return None
```

**Fix Applied**:
```python
# Specific exception handling
try:
    result = perform_operation()
except (ValueError, IOError) as e:  # More specific
    logger.error(f"Operation failed: {e}")
    return None
```

### 5. Hardcoded Secrets (CRITICAL)
**Risk Level**: Critical
**Requires Approval**: Yes

Detects hardcoded passwords, API keys, tokens, and other secrets.

**Example Detection**:
```python
# Hardcoded secret
password = "supersecret123"
api_key = "sk_test_1234567890"
```

**Fix Applied**:
```python
# Environment variable
password = os.getenv("PASSWORD", "")
api_key = os.getenv("API_KEY", "")
```

## Usage

### Basic Usage

```python
from mahavishnu.workflows import SystematicQualityFixWorkflow

# Create workflow instance
workflow = SystematicQualityFixWorkflow(
    test_command="pytest -xvs",
)

# Execute fix for specific issue type
result = await workflow.execute(
    issue_type="md5_usage",
    files_to_fix=["mahavishnu/core/file_handler.py"],
    auto_apply=True,
)

print(f"Fixed {result['successful_fixes']} files")
```

### With Human Approval

```python
from mahavishnu.workflows import SystematicQualityFixWorkflow, RiskLevel

async def approval_callback(file_path: str, risk_level: RiskLevel) -> bool:
    """Request human approval for high-risk changes."""
    print(f"Approval required for {risk_level.value} risk in {file_path}")

    # Auto-approve low/medium risk
    if risk_level in [RiskLevel.LOW, RiskLevel.MEDIUM]:
        return True

    # Require manual approval for high/critical risk
    # In production, this could:
    # - Send a notification to Slack/Teams
    # - Open a PR for review
    # - Use an interactive prompt
    response = input(f"Approve fix for {file_path}? (yes/no): ")
    return response.lower() == "yes"

workflow = SystematicQualityFixWorkflow(
    approval_callback=approval_callback,
    test_command="pytest -xvs",
)

# Execute with approval
result = await workflow.execute(
    issue_type="path_traversal",
    files_to_fix=["mahavishnu/core/file_handler.py"],
    auto_apply=False,  # Require approval for critical changes
)
```

### Custom Test Command

```python
workflow = SystematicQualityFixWorkflow(
    test_command="pytest tests/unit/ -x --tb=short",
)
```

### Custom Backup Directory

```python
workflow = SystematicQualityFixWorkflow(
    backup_dir=".backups/quality_fixes",
)
```

## Workflow Execution Steps

The workflow executes the following steps:

1. **Validate Issue Type**: Ensures the issue type is supported
2. **Analyze Pattern**: Analyzes the issue pattern across files
3. **Find Occurrences**: Scans all files for issue occurrences using AST analysis
4. **Generate Fixes**: Creates appropriate fix plans for each occurrence
5. **Apply Fixes**:
   - Creates backup of original file
   - Requests approval if required (for high-risk changes)
   - Applies the fix
6. **Validate**: Runs tests to ensure fixes don't break anything
7. **Rollback if Needed**: Automatically rolls back all changes if tests fail
8. **Report Results**: Returns comprehensive execution report

## Result Structure

```python
{
    "issue_type": "md5_usage",
    "total_files": 5,
    "successful_fixes": 4,
    "failed_fixes": 0,
    "skipped_fixes": 1,
    "execution_time_seconds": 2.45,
    "rollback_performed": False,
    "fixes": [
        {
            "file_path": "mahavishnu/core/file_handler.py",
            "success": True,
            "risk_level": "low",
            "changes_made": ["Replace MD5 with SHA256 (line 42)"],
            "backup_path": ".rollback_backups/file_handler.py.20250205_143022.backup",
            "error_message": None
        },
        # ... more fix results
    ]
}
```

## Safety Features

### Risk Assessment

Each issue type has an associated risk level:
- **LOW**: Safe to auto-fix (e.g., MD5 usage, missing type hints)
- **MEDIUM**: Generally safe but may require review (e.g., generic exceptions)
- **HIGH**: Requires approval (not currently used)
- **CRITICAL**: Always requires approval (e.g., path traversal, hardcoded secrets)

### Human Approval

For critical issues, the workflow can:
1. Call an approval callback with file path and risk level
2. Wait for human approval before proceeding
3. Skip the fix if approval is denied
4. Log all approval decisions

### Testing Validation

Before committing any fixes:
1. Runs configured test command
2. Checks test exit code
3. Automatically rolls back if tests fail
4. Reports which tests failed

### Instant Rollback

If validation fails:
1. Restores all files from backups
2. Reports which files were rolled back
3. Preserves backups for manual inspection
4. Logs rollback completion

## Integration with Quality Feedback Loop

The systematic quality fix workflow is designed to be triggered by the Quality Feedback Loop when quality issues are detected:

```python
from mahavishnu.workflows import SystematicQualityFixWorkflow

async def quality_feedback_loop_handler(issue_report):
    """Handle quality issues detected by the feedback loop."""

    # Map issue report to workflow issue type
    issue_mapping = {
        "path_traversal": "path_traversal",
        "md5_usage": "md5_usage",
        "missing_type_hints": "missing_type_hints",
        "generic_exception": "generic_exception",
        "hardcoded_secrets": "hardcoded_secrets",
    }

    # Extract files with issues
    files_to_fix = [
        issue.file_path
        for issue in issue_report.issues
        if issue.severity >= "medium"
    ]

    # Execute systematic fix
    workflow = SystematicQualityFixWorkflow(
        approval_callback=production_approval_callback,
        test_command="pytest -xvs",
    )

    result = await workflow.execute(
        issue_type=issue_mapping[issue_report.issue_type],
        files_to_fix=files_to_fix,
        auto_apply=False,  # Require approval for production
    )

    # Report results
    return result
```

## Best Practices

### 1. Start with Low-Risk Issues
```python
# Good: Start with low-risk issues
await workflow.execute(
    issue_type="md5_usage",
    files_to_fix=all_files,
    auto_apply=True,
)

# Then move to medium-risk
await workflow.execute(
    issue_type="missing_type_hints",
    files_to_fix=all_files,
    auto_apply=True,
)
```

### 2. Use Approval for Critical Issues
```python
# Always require approval for critical issues
result = await workflow.execute(
    issue_type="path_traversal",
    files_to_fix=affected_files,
    auto_apply=False,  # Require manual approval
)
```

### 3. Run Tests Before Applying
```python
# Ensure tests pass before running workflow
import subprocess
subprocess.run(["pytest", "-xvs"], check=True)

# Then apply fixes
result = await workflow.execute(...)
```

### 4. Review Backups
```python
# After workflow completes, review backups
import os
backup_dir = Path(".rollback_backups")

for backup in backup_dir.glob("*.backup"):
    print(f"Review: {backup}")
    # Inspect backup if needed
    # Delete after verification
```

### 5. Gradual Rollout
```python
# Test on small subset first
sample_files = affected_files[:5]

result = await workflow.execute(
    issue_type="md5_usage",
    files_to_fix=sample_files,
    auto_apply=True,
)

# Verify success, then run on full set
if result["successful_fixes"] == len(sample_files):
    full_result = await workflow.execute(
        issue_type="md5_usage",
        files_to_fix=affected_files,
        auto_apply=True,
    )
```

## Extending the Workflow

### Adding New Issue Types

1. **Add to IssueType enum**:
```python
class IssueType(str, Enum):
    # ... existing types
    INSECURE_RANDOM = "insecure_random"
```

2. **Add to ISSUE_PATTERNS**:
```python
ISSUE_PATTERNS: dict[IssueType, IssuePattern] = {
    # ... existing patterns
    IssueType.INSECURE_RANDOM: IssuePattern(
        issue_type=IssueType.INSECURE_RANDOM,
        risk_level=RiskLevel.MEDIUM,
        description="Insecure random number generation detected",
        requires_approval=False,
    ),
}
```

3. **Implement detection method**:
```python
def _find_insecure_random(self, tree: ast.AST) -> list[dict[str, Any]]:
    """Find insecure random usage."""
    issues = []

    class InsecureRandomVisitor(ast.NodeVisitor):
        def visit_Call(self, node):
            if isinstance(node.func, ast.Attribute):
                if node.func.attr == "random":
                    issues.append({
                        "line": node.lineno,
                        "type": "insecure_random",
                        "severity": "medium",
                    })
            self.generic_visit(node)

    visitor = InsecureRandomVisitor()
    visitor.visit(tree)
    return issues
```

4. **Implement fix method**:
```python
def _fix_insecure_random(self, content: str, lines: list[str], issue: dict[str, Any]) -> str:
    """Fix insecure random usage."""
    line_num = issue["line"] - 1
    if line_num < len(lines):
        lines[line_num] = lines[line_num].replace(
            "random.random",
            "secrets.SystemRandom().random"
        )
    return "\n".join(lines)
```

## Error Handling

The workflow handles various error conditions:

```python
# Nonexistent files are skipped
result = await workflow.execute(
    issue_type="md5_usage",
    files_to_fix=["/nonexistent/file.py"],  # Will be skipped
)

# Invalid Python syntax is handled gracefully
result = await workflow.execute(
    issue_type="md5_usage",
    files_to_fix=["broken_syntax.py"],  # Logged and skipped
)

# Test failures trigger automatic rollback
# If tests fail, all changes are rolled back automatically
```

## Monitoring and Logging

The workflow provides comprehensive logging:

```python
import logging

# Enable debug logging
logging.basicConfig(level=logging.DEBUG)

# Run workflow - detailed logs will be produced
result = await workflow.execute(...)
```

Log levels:
- **INFO**: Workflow progress, file operations
- **WARNING**: Skipped files, missing approvals
- **ERROR**: Failed operations, test failures
- **DEBUG**: Detailed AST analysis, fix generation

## Performance Considerations

- **AST Analysis**: Uses Python's built-in AST parser (fast)
- **Parallel Processing**: Can be extended to process files in parallel
- **Incremental Fixes**: Can run on subsets of files for gradual rollout
- **Backup Overhead**: Minimal overhead from file copying

## Security Considerations

- **No Shell Injection**: Uses AST parsing, not regex/string manipulation
- **Safe File Operations**: Validates paths before file operations
- **Approval Required**: Critical changes always require human approval
- **Rollback Capability**: Instant rollback prevents breaking changes

## Troubleshooting

### Issue: Workflow skips all files
**Solution**: Check if approval callback is required but not provided:
```python
# Provide approval callback for critical issues
workflow = SystematicQualityFixWorkflow(
    approval_callback=my_approval_callback,
)
```

### Issue: Tests fail after fixes
**Solution**: Review test output and fix implementations:
```python
# Run tests manually to see what's failing
pytest -xvs

# Review backups to understand changes
ls -la .rollback_backups/

# Adjust fix logic if needed
```

### Issue: Changes not applied
**Solution**: Check if auto_apply is set correctly:
```python
# For non-critical issues, use auto_apply=True
result = await workflow.execute(
    issue_type="md5_usage",  # Low risk
    files_to_fix=files,
    auto_apply=True,  # Apply without approval
)
```

## See Also

- [Quality Checker Documentation](/docs/QUALITY_CHECKER.md)
- [Crackerjack Integration](/docs/CRACKERJACK_INTEGRATION.md)
- [MCP Tools Specification](/docs/MCP_TOOLS_SPECIFICATION.md)

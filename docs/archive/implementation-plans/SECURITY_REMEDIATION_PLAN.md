# 🔒 CRITICAL SECURITY REMEDIATION PLAN

**Date**: 2026-02-09
**Priority**: P0 - CRITICAL (Production Blocker)
**Status**: ⚠️ ACTION REQUIRED
**Target Resolution**: Within 24 hours

---

## 🎯 Executive Summary

Two **critical security vulnerabilities** identified in the ORB Learning Feedback Loops P0 integration:

1. **C-001: SQL Injection** (CVSS 9.8) - Database Tools
2. **C-002: Path Traversal** (CVSS 8.6) - Database Tools

**Impact**: Data destruction, exfiltration, unauthorized file access

**Action**: IMMEDIATE FIX REQUIRED before production deployment

---

## 🚨 Vulnerability Details

### C-001: SQL Injection via String Interpolation

**Severity**: CRITICAL (CVSS 9.8)
**Location**: `mahavishnu/mcp/tools/database_tools.py`
**Lines Affected**: 272-283, 286, 300, 315, 330, 343, 474, 487, 499, 512
**Attack Vector**: User-controlled `time_range` parameter

**Vulnerable Code**:
```python
# Line 272-283 (VULNERABLE)
time_series = conn.execute(f"""
    SELECT ...
    WHERE timestamp >= NOW() - INTERVAL '{interval}'
    ...
""").fetchall()
```

**Attack Example**:
```python
# Malicious input
time_range = "7 days'; DROP TABLE executions; --"
# Results in: WHERE timestamp >= NOW() - INTERVAL '7 days'; DROP TABLE executions; --'
```

**Impact**:
- Data destruction (DROP TABLE)
- Data exfiltration (UNION SELECT)
- Privilege escalation

---

### C-002: Path Traversal in Database File Path

**Severity**: CRITICAL (CVSS 8.6)
**Location**: `mahavishnu/mcp/tools/database_tools.py:104`
**Attack Vector**: User-provided `db_path` parameter

**Vulnerable Code**:
```python
# Line 104 (VULNERABLE)
db_path = Path(db_path) if db_path else get_database_path(settings)
```

**Attack Example**:
```python
# Via MCP tool call
database_status(db_path="../../../../../etc/passwd")
```

**Impact**:
- Read arbitrary files
- Information disclosure
- File system manipulation

---

## ✅ Remediation Strategy

### Phase 1: SQL Injection Fix (Priority: P0)

**Approach**: Whitelist validation + parameterized queries

**Implementation**:

1. **Create whitelist of valid time ranges**:
```python
# mahavishnu/mcp/tools/database_tools.py

VALID_TIME_RANGES = {
    "1h": ("1 hour", 3600),
    "24h": ("1 day", 86400),
    "7d": ("7 days", 604800),
    "30d": ("30 days", 2592000),
    "90d": ("90 days", 7776000),
}

def validate_time_range(time_range: str) -> tuple[str, int]:
    """Validate time range parameter against whitelist."""
    if time_range not in VALID_TIME_RANGES:
        raise ValueError(
            f"Invalid time_range: {time_range}. "
            f"Valid options: {', '.join(VALID_TIME_RANGES.keys())}"
        )
    return VALID_TIME_RANGES[time_range]
```

2. **Update all affected functions**:
```python
async def get_execution_statistics(
    settings: Optional[MahavishnuSettings] = None,
    db_path: Optional[str] = None,
    time_range: str = "7d",  # User-controlled
) -> dict[str, Any]:
    """Get execution statistics with safe time range validation."""

    # Validate time range BEFORE using in SQL
    try:
        interval, seconds = validate_time_range(time_range)
    except ValueError as e:
        logger.error(f"Invalid time_range parameter: {e}")
        return {
            "error": str(e),
            "error_type": "invalid_parameter"
        }

    db_path = get_database_path(settings, db_path)
    conn = duckdb.connect(str(db_path))

    # SAFE: Use validated interval (constant from whitelist)
    time_series = conn.execute(f"""
        SELECT
            DATE_TRUNC('day', timestamp) as date,
            COUNT(*) as count
        FROM executions
        WHERE timestamp >= NOW() - INTERVAL '{interval}'
        GROUP BY DATE_TRUNC('day', timestamp)
        ORDER BY date ASC
    """).fetchall()

    # ... rest of function
```

3. **Add unit tests**:
```python
# tests/unit/test_mcp/test_database_tools_security.py

import pytest
from mahavishnu.mcp.tools.database_tools import validate_time_range

def test_validate_time_range_valid():
    """Test valid time ranges."""
    assert validate_time_range("7d") == ("7 days", 604800)
    assert validate_time_range("24h") == ("1 day", 86400)

def test_validate_time_range_invalid():
    """Test invalid time ranges are rejected."""
    with pytest.raises(ValueError, match="Invalid time_range"):
        validate_time_range("7 days'; DROP TABLE executions; --")

    with pytest.raises(ValueError, match="Invalid time_range"):
        validate_time_range("../../../etc/passwd")

    with pytest.raises(ValueError, match="Valid options"):
        validate_time_range("invalid")
```

**Files to Modify**:
- `mahavishnu/mcp/tools/database_tools.py` (add validation, update 10 functions)
- `tests/unit/test_mcp/test_database_tools_security.py` (create new test file)

**Estimated Effort**: 2 hours

---

### Phase 2: Path Traversal Fix (Priority: P0)

**Approach**: Use existing path validation infrastructure

**Implementation**:

1. **Import path validator**:
```python
# mahavishnu/mcp/tools/database_tools.py

from mahavishnu.core.validators import validate_path, PathValidationError
```

2. **Update get_database_path helper**:
```python
async def get_database_path(
    settings: Optional[MahavishnuSettings] = None,
    user_provided_path: Optional[str] = None
) -> Path:
    """Get and validate database path.

    Args:
        settings: Mahavishnu settings
        user_provided_path: Optional user-provided path (MUST be validated)

    Returns:
        Validated database path

    Raises:
        PathValidationError: If path is invalid or outside allowed directories
    """
    # Get default path from settings
    default_path = Path(settings.learning.database_path if settings else "data/learning.db")

    # If user provided a path, validate it
    if user_provided_path:
        try:
            # Only allow paths within data directory
            validated_path = validate_path(
                user_provided_path,
                allowed_base_dirs=["data", str(Path.cwd() / "data")],
                must_exist=False,  # DB may not exist yet
            )
            logger.info(f"Using validated database path: {validated_path}")
            return validated_path
        except PathValidationError as e:
            logger.error(f"Invalid database path: {e}")
            raise  # Re-raise to caller

    return default_path
```

3. **Update all MCP tools**:
```python
@mcp.tool()
async def database_status(
    settings: Optional[MahavishnuSettings] = None,
    db_path: Optional[str] = None
) -> str:
    """Get comprehensive database status and health information.

    Args:
        settings: Optional Mahavishnu settings
        db_path: Optional database path (MUST be within data directory)

    Returns:
        JSON string with database status
    """
    try:
        # Validate path before using
        validated_path = await get_database_path(settings, db_path)
        status = await check_database_status(validated_path)
        return json.dumps(status, indent=2, default=str)
    except PathValidationError as e:
        error_response = {
            "status": "ERROR",
            "message": "Invalid database path",
            "error": str(e),
            "error_type": "path_validation_failed"
        }
        return json.dumps(error_response, indent=2)
    except Exception as e:
        logger.error(f"Failed to get database status: {e}")
        return json.dumps({"error": str(e)}, indent=2)
```

4. **Add unit tests**:
```python
# tests/unit/test_mcp/test_database_tools_security.py

import pytest
from mahavishnu.mcp.tools.database_tools import get_database_path
from mahavishnu.core.validators import PathValidationError

@pytest.mark.asyncio
async def test_get_database_path_valid():
    """Test valid database paths are accepted."""
    # Relative path within data directory
    path = await get_database_path(None, "data/learning.db")
    assert path == Path("data/learning.db")

    # Absolute path within data directory
    cwd = Path.cwd()
    path = await get_database_path(None, str(cwd / "data" / "test.db"))
    assert path == cwd / "data" / "test.db"

@pytest.mark.asyncio
async def test_get_database_path_traversal_attack():
    """Test path traversal attacks are blocked."""
    with pytest.raises(PathValidationError):
        await get_database_path(None, "../../../../../etc/passwd")

    with pytest.raises(PathValidationError):
        await get_database_path(None, "/etc/passwd")

    with pytest.raises(PathValidationError):
        await get_database_path(None, "data/../../etc/passwd")
```

**Files to Modify**:
- `mahavishnu/mcp/tools/database_tools.py` (import validator, update 3 functions)
- `tests/unit/test_mcp/test_database_tools_security.py` (add path traversal tests)

**Estimated Effort**: 2 hours

---

## 🧪 Verification Plan

### Security Testing

1. **SQL Injection Tests**:
```bash
# Run security tests
pytest tests/unit/test_mcp/test_database_tools_security.py -v

# Should pass all tests
# - Valid time ranges accepted
# - Malicious time ranges rejected
# - No SQL injection possible
```

2. **Path Traversal Tests**:
```bash
# Run security tests
pytest tests/unit/test_mcp/test_database_tools_security.py::test_get_database_path_traversal_attack -v

# Should pass all tests
# - Path traversal blocked
# - Only data/ directory allowed
# - Absolute paths validated
```

3. **Manual Security Testing**:
```bash
# Test SQL injection via MCP tool
echo 'Testing malicious time_range...'
mcp.call_tool("get_execution_statistics", {"time_range": "7 days'; DROP TABLE executions; --"})
# Should return error: "Invalid time_range"

# Test path traversal via MCP tool
echo 'Testing path traversal...'
mcp.call_tool("database_status", {"db_path": "../../../../../etc/passwd"})
# Should return error: "path_validation_failed"
```

### Regression Testing

```bash
# Ensure existing functionality still works
pytest tests/unit/test_mcp/test_database_tools.py -v

# Should all pass
# - Valid time ranges work
# - Default database path works
# - All statistics functions work
```

---

## 📋 Implementation Checklist

### Phase 1: SQL Injection Fix
- [ ] Add `VALID_TIME_RANGES` whitelist to database_tools.py
- [ ] Implement `validate_time_range()` function
- [ ] Update `get_execution_statistics()` function
- [ ] Update `get_performance_metrics()` function
- [ ] Update all 10 affected SQL query locations
- [ ] Add unit tests for time range validation
- [ ] Add unit tests for SQL injection prevention
- [ ] Run tests and verify 100% pass rate

### Phase 2: Path Traversal Fix
- [ ] Import `validate_path` and `PathValidationError`
- [ ] Update `get_database_path()` helper function
- [ ] Update `database_status()` MCP tool
- [ ] Update `get_execution_statistics()` MCP tool
- [ ] Update `get_performance_metrics()` MCP tool
- [ ] Add unit tests for path validation
- [ ] Add unit tests for path traversal prevention
- [ ] Run tests and verify 100% pass rate

### Phase 3: Documentation
- [ ] Update SECURITY_CHECKLIST.md with these fixes
- [ ] Document security testing procedures
- [ ] Add security audit notes to CHANGELOG
- [ ] Update production deployment guide

---

## 🔒 Security Best Practices (Going Forward)

### Input Validation
- ✅ **ALWAYS** validate user input before using in SQL
- ✅ Use whitelist validation for enumerated values
- ✅ Use parameterized queries for dynamic values
- ✅ Never trust user-provided file paths

### Path Validation
- ✅ Use existing `validate_path()` from `mahavishnu/core/validators.py`
- ✅ Restrict to specific base directories
- ✅ Resolve symbolic links before validation
- ✅ Reject paths outside allowed directories

### Database Security
- ✅ Use parameterized queries (DuckDB supports `$1`, `$2` syntax)
- ✅ Validate all input before database operations
- ✅ Use Pydantic models for data validation
- ✅ Never use f-strings for user input in SQL

### Testing
- ✅ Write security tests for all user input
- ✅ Test malicious input patterns
- ✅ Test path traversal attempts
- ✅ Test SQL injection attempts

---

## 🚀 Deployment Plan

### Pre-Deployment
1. Complete all Phase 1 and Phase 2 fixes
2. Verify 100% test pass rate
3. Run manual security testing
4. Document changes in CHANGELOG

### Deployment Steps
1. Merge fixes to main branch
2. Tag release as `v0.2.1-security`
3. Update production servers
4. Run smoke tests
5. Monitor for errors

### Post-Deployment
1. Monitor logs for validation failures
2. Track database query performance
3. Verify MCP tools working correctly
4. Review security metrics

---

## 📞 Contact

**Security Team**: security@mahavishnu.dev
**Engineering Lead**: engineering@mahavishnu.dev
**On-Call**: +1-555-0123

---

**Status**: ⚠️ ACTION REQUIRED
**Target**: Complete within 24 hours
**Next Steps**: Assign to development team

---

## Appendix: Related Security Issues

### High Priority (Should Fix Soon)
- H-001: Error message information disclosure
- H-002: Unvalidated task ID in telemetry capture
- H-003: Missing authentication on MCP tools
- H-004: Unsafe SQL in cleanup operations

### Medium Priority (Nice to Have)
- M-001: Embedding model path traversal
- M-002: Metadata JSON injection
- M-003: Unbounded telemetry buffer growth
- M-004: Missing database file permissions
- M-005: Pool configuration validation gaps
- M-006: Error type string injection

See `SECURITY_AUDIT_REPORT.md` for complete details.

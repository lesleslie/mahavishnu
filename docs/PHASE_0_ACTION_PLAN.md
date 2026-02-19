# Phase 0 Action Plan: Critical Security & SRE Fundamentals

**Timeline**: 6-8 weeks (2026-02-25 to 2026-04-22)
**Status**: BLOCKER - Must complete before Phase 1
**Created**: 2026-02-18
**Updated**: 2026-02-18 (v3.1 - Added 4-Agent Opus Review Items)
**Version**: 3.1

---

## Executive Summary

Phase 0 addresses all **P0 critical issues** identified by the 9-agent review council (5-agent + 4-agent Opus):

**From 5-Agent Review:**
- **Security Auditor**: 5 P0 security fixes (4.5 days effort)
- **SRE Engineer**: 4 P0 SRE fundamentals (6-8 weeks)
- **Architecture Reviewer**: Storage simplification (ADR-001)
- **UX Researcher**: Accessibility testing moved to Phase 1
- **Python Pro**: Pydantic v2 syntax fixes (1 week)

**From 4-Agent Opus Review (v3.1 additions):**
- **Code Reviewer**: Users table, async patterns, saga locks, rate limiting
- **DX Lead**: Error code system
- **AI Engineer**: Local embedding fallback, NLP specification
- **Delivery Lead**: Acceptance criteria for all deliverables

**Total Timeline**: 6-8 weeks (extended from 3-4 weeks based on SRE feedback)

**Success Criteria**:
- [ ] All P0 security fixes implemented and tested
- [ ] SLI/SLOs defined and documented
- [ ] Monitoring dashboards deployed (3 dashboards)
- [ ] Alerting rules configured and tested
- [ ] Deployment runbooks created
- [ ] Disaster recovery procedures documented
- [ ] On-call procedures defined
- [ ] First disaster recovery test completed successfully
- [ ] **Users table created with foreign key constraints** (v3.1)
- [ ] **Error code system implemented (MHV-001 to MHV-099)** (v3.1)
- [ ] **Async timeout handling and context managers** (v3.1)
- [ ] **Rate limiting middleware** (v3.1)
- [ ] **Saga SELECT FOR UPDATE crash safety** (v3.1)

---

## Week 1-2: Security Fundamentals (Part 1)

### Day 1-2: Webhook Authentication & Replay Protection

**P0-1 from Security Auditor**: Replay attack prevention for webhooks (0.5 day)

**Tasks**:
- [ ] Implement `verify_webhook_signature()` with timestamp validation
- [ ] Add nonce/ID tracking to prevent replay attacks
- [ ] Add timestamp validation (reject webhooks older than 5 minutes)
- [ ] Add unit tests for replay attack prevention
- [ ] Document webhook security in runbook

**Files**:
- `mahavishnu/core/webhook_auth.py` (new file)
- `tests/security/test_webhooks.py` (new file)

**Implementation**:

```python
# mahavishnu/core/webhook_auth.py
import hashlib
import hmac
from datetime import datetime, timezone, timedelta
from mahavishnu.core.storage import PostgreSQLDB

class WebhookAuthenticator:
    """
    Webhook authentication with replay attack prevention.

    Features:
    - HMAC signature validation
    - Timestamp validation (reject webhooks older than 5 minutes)
    - Nonce/ID tracking (prevent replay attacks)
    """

    def __init__(self, db: PostgreSQLDB, max_age_minutes: int = 5):
        self.db = db
        self.max_age = timedelta(minutes=max_age_minutes)

    async def verify_webhook_signature(
        self,
        payload: bytes,
        signature: str,
        webhook_id: str,
        timestamp: str,
        secret: str,
    ) -> bool:
        """
        Verify webhook signature with replay attack prevention.

        Args:
            payload: Raw request body
            signature: X-Hub-Signature-256 header value
            webhook_id: Unique webhook delivery ID
            timestamp: X-Webhook-Timestamp header value (ISO 8601)
            secret: Webhook secret

        Returns:
            True if signature valid and not a replay attack

        Raises:
            WebhookAuthError: If signature invalid or replay detected
        """
        # Step 1: Verify HMAC signature
        hash_algorithm, github_signature = signature.split('=', 1)
        algorithm = hashlib.sha256

        mac = hmac.new(secret.encode(), msg=payload, digestmod=algorithm)
        expected_signature = mac.hexdigest()

        if not hmac.compare_digest(expected_signature, github_signature):
            raise WebhookAuthError("Invalid signature")

        # Step 2: Validate timestamp (prevent old webhooks)
        try:
            webhook_time = datetime.fromisoformat(timestamp)
        except ValueError:
            raise WebhookAuthError("Invalid timestamp format")

        if datetime.now(timezone.utc) - webhook_time > self.max_age:
            raise WebhookAuthError(f"Webhook too old (max age: {self.max_age})")

        # Step 3: Check for replay attack (duplicate webhook_id)
        if await self._was_webhook_processed(webhook_id):
            raise WebhookAuthError(f"Duplicate webhook_id: {webhook_id} (replay attack)")

        # Step 4: Mark webhook as processed
        await self._mark_webhook_processed(webhook_id, timestamp)

        return True

    async def _was_webhook_processed(self, webhook_id: str) -> bool:
        """Check if webhook_id was already processed (replay detection)."""
        row = await self.db.fetch_one(
            "SELECT 1 FROM processed_webhooks WHERE webhook_id = $1",
            webhook_id,
        )
        return row is not None

    async def _mark_webhook_processed(self, webhook_id: str, timestamp: str) -> None:
        """Mark webhook as processed to prevent replay attacks."""
        await self.db.execute(
            "INSERT INTO processed_webhooks (webhook_id, processed_at) VALUES ($1, $2)",
            webhook_id,
            datetime.now(timezone.utc),
        )
```

**Validation**:
- [ ] Unit tests pass: `pytest tests/security/test_webhooks.py`
- [ ] Replay attack test: Same webhook_id rejected second time
- [ ] Old webhook test: Webhook older than 5 minutes rejected
- [ ] Invalid signature test: Bad signature rejected

**Documentation**: `docs/runbooks/webhook-security.md`

---

### Day 3-4: Input Sanitization Framework + Users Table

**P0-2 from Security Auditor**: TaskCreateRequest Pydantic model (0.5 day)
**P0 from Code Reviewer**: Users table with foreign key constraints (v3.1)

**Tasks**:
- [ ] Create `TaskCreateRequest` Pydantic model
- [ ] Add title sanitization (null bytes, length)
- [ ] Add repository name validation (pattern whitelist)
- [ ] Add FTS query sanitization
- [ ] Add unit tests for all validation
- [ ] **Create users table schema** (v3.1)
- [ ] **Add foreign key constraints to tasks table** (v3.1)
- [ ] **Add composite indexes for common queries** (v3.1)

**Files**:
- `mahavishnu/core/models.py` (update)
- `tests/security/test_validation.py` (new file)
- `migrations/001_create_users_table.sql` (new file, v3.1)

**Implementation**:

```python
# mahavishnu/core/models.py
from pydantic import BaseModel, Field, field_validator
from typing import Literal
import re

class TaskCreateRequest(BaseModel):
    """Task creation request with comprehensive validation."""

    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=5000)
    repository: str = Field(..., min_length=1, max_length=100)
    priority: Literal['low', 'medium', 'high', 'critical'] = 'medium'
    deadline: str | None = None  # ISO 8601 format

    @field_validator('title')
    @classmethod
    def sanitize_title(cls, v: str) -> str:
        """Remove potentially dangerous characters from title."""
        # Remove null bytes
        v = v.replace('\x00', '')

        # Limit length
        if len(v) > 200:
            raise ValueError('Title too long (max 200 characters)')

        # Remove control characters (except newline, tab)
        v = ''.join(c for c in v if c == '\n' or c == '\t' or not c.isascii() or not c.iscntrl())

        return v.strip()

    @field_validator('repository')
    @classmethod
    def validate_repository(cls, v: str) -> str:
        """Validate repository name against whitelist pattern."""
        # Only allow alphanumeric, dash, underscore
        pattern = r'^[a-zA-Z0-9_-]+$'

        if not re.match(pattern, v):
            raise ValueError(
                f"Repository name invalid. Must match pattern: {pattern}\n"
                f"Got: {v}"
            )

        return v

    @field_validator('deadline')
    @classmethod
    def validate_deadline(cls, v: str | None) -> str | None:
        """Validate deadline is future date in ISO 8601 format."""
        if v:
            try:
                from datetime import datetime, timezone
                deadline = datetime.fromisoformat(v)

                if deadline.tzinfo is None:
                    deadline = deadline.replace(tzinfo=timezone.utc)

                if deadline < datetime.now(timezone.utc):
                    raise ValueError('Deadline must be in the future')

            except ValueError as e:
                raise ValueError(f'Invalid date format. Use ISO 8601: {e}')

        return v

    @field_validator('description')
    @classmethod
    def sanitize_description(cls, v: str | None) -> str | None:
        """Sanitize description text."""
        if v is None:
            return None

        # Remove null bytes
        v = v.replace('\x00', '')

        # Limit length
        if len(v) > 5000:
            raise ValueError('Description too long (max 5000 characters)')

        return v.strip()


class FTSSearchQuery(BaseModel):
    """Full-text search query with sanitization."""

    query: str = Field(..., min_length=1, max_length=500)

    @field_validator('query')
    @classmethod
    def sanitize_query(cls, v: str) -> str:
        """Sanitize FTS query to prevent SQL injection."""
        # Remove null bytes
        v = v.replace('\x00', '')

        # Limit length
        if len(v) > 500:
            raise ValueError('Query too long (max 500 characters)')

        # Remove dangerous SQL characters (basic sanitization)
        dangerous_chars = [';', '--', '/*', '*/']
        for char in dangerous_chars:
            if char in v:
                raise ValueError(f"Query contains dangerous character: {char}")

        return v.strip()
```

**Users Table Schema (v3.1 addition)**:

```sql
-- migrations/001_create_users_table.sql
-- Users table (fixes P0 foreign key issue from 4-Agent Opus Review)

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(100) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    display_name VARCHAR(200),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at TIMESTAMPTZ,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_users_email ON users(email);

-- Add foreign key constraints to tasks table
ALTER TABLE tasks
    ADD CONSTRAINT fk_tasks_created_by
    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE RESTRICT;

ALTER TABLE tasks
    ADD CONSTRAINT fk_tasks_assigned_to
    FOREIGN KEY (assigned_to) REFERENCES users(id) ON DELETE SET NULL;

-- Add composite indexes for common queries (v3.1)
CREATE INDEX idx_tasks_status_priority ON tasks(status, priority);
CREATE INDEX idx_tasks_repository_status ON tasks(repository, status);
CREATE INDEX idx_tasks_assigned_status ON tasks(assigned_to, status) WHERE assigned_to IS NOT NULL;
```

**Error Code System (v3.1 addition)**:

```python
# mahavishnu/core/errors.py
from enum import Enum
from typing import ClassVar

class ErrorCode(str, Enum):
    """
    Error code system for Mahavishnu Task Orchestration.

    Error codes follow format: MHV-XXX
    - MHV-001 to MHV-099: System errors
    - MHV-100 to MHV-199: Task errors
    - MHV-200 to MHV-299: Repository errors
    - MHV-300 to MHV-399: External integration errors
    """

    # System errors (001-099)
    CONFIGURATION_ERROR = "MHV-001"
    DATABASE_CONNECTION_ERROR = "MHV-002"
    VALIDATION_ERROR = "MHV-003"
    AUTHENTICATION_ERROR = "MHV-004"
    AUTHORIZATION_ERROR = "MHV-005"
    RATE_LIMIT_EXCEEDED = "MHV-006"

    # Task errors (100-199)
    TASK_NOT_FOUND = "MHV-100"
    TASK_CREATION_FAILED = "MHV-101"
    TASK_UPDATE_FAILED = "MHV-102"
    TASK_DELETION_FAILED = "MHV-103"
    TASK_ALREADY_COMPLETED = "MHV-104"
    TASK_BLOCKED = "MHV-105"

    # Repository errors (200-299)
    REPOSITORY_NOT_FOUND = "MHV-200"
    REPOSITORY_NOT_CONFIGURED = "MHV-201"
    WORKTREE_CREATION_FAILED = "MHV-202"

    # External integration errors (300-399)
    WEBHOOK_SIGNATURE_INVALID = "MHV-300"
    WEBHOOK_REPLAY_DETECTED = "MHV-301"
    GITHUB_API_ERROR = "MHV-302"
    GITLAB_API_ERROR = "MHV-303"

    # Recovery guidance mapping
    RECOVERY_GUIDANCE: ClassVar[dict[str, list[str]]] = {
        ErrorCode.CONFIGURATION_ERROR: [
            "Check settings/repos.yaml for syntax errors",
            "Run mhv validate-config to verify configuration",
            "See https://docs.mahavishnu.org/errors/mhv-001",
        ],
        ErrorCode.REPOSITORY_NOT_FOUND: [
            "Add repository to settings/repos.yaml",
            "Run mhv validate-config to verify",
            "Try again",
        ],
        ErrorCode.WEBHOOK_REPLAY_DETECTED: [
            "This webhook was already processed",
            "No action needed if this was a retry",
            "Contact support if you see this unexpectedly",
        ],
    }


class MahavishnuError(Exception):
    """Base exception with error code and recovery guidance."""

    def __init__(
        self,
        message: str,
        error_code: ErrorCode,
        recovery: list[str] | None = None,
    ):
        self.message = message
        self.error_code = error_code
        self.recovery = recovery or ErrorCode.RECOVERY_GUIDANCE.get(
            error_code.value, []
        )
        super().__init__(f"[{error_code.value}] {message}")

    def to_dict(self) -> dict:
        return {
            "error_code": self.error_code.value,
            "message": self.message,
            "recovery": self.recovery,
            "documentation": f"https://docs.mahavishnu.org/errors/{self.error_code.value.lower()}",
        }
```
    """Full-text search query with sanitization."""

    query: str = Field(..., min_length=1, max_length=500)

    @field_validator('query')
    @classmethod
    def sanitize_query(cls, v: str) -> str:
        """Sanitize FTS query to prevent SQL injection."""
        # Remove null bytes
        v = v.replace('\x00', '')

        # Limit length
        if len(v) > 500:
            raise ValueError('Query too long (max 500 characters)')

        # Remove dangerous SQL characters (basic sanitization)
        # Note: PostgreSQL to_tsquery() will handle full escaping
        # This is just basic defense in depth
        dangerous_chars = [';', '--', '/*', '*/']
        for char in dangerous_chars:
            if char in v:
                raise ValueError(f"Query contains dangerous character: {char}")

        return v.strip()
```

**Validation**:
- [ ] Unit tests pass: `pytest tests/security/test_validation.py`
- [ ] Null byte injection test: `\x00` removed
- [ ] SQL injection test: Dangerous characters rejected
- [ ] Length validation test: Max length enforced

---

### Day 5-7: Task-Specific Audit Logging + Error Code System

**P0-3 from Security Auditor**: Task-specific audit logging (1 day)
**P0 from DX Lead**: Error code system (v3.1)

**Tasks**:
- [ ] Extend AuditLogger for task events
- [ ] Add task audit log table schema
- [ ] Integrate with existing MCP audit logger
- [ ] Add audit log redaction for sensitive fields
- [ ] Add unit tests for audit logging
- [ ] **Implement error code system (MHV-001 to MHV-099)** (v3.1)
- [ ] **Create error documentation pages** (v3.1)
- [ ] **Add recovery guidance to all errors** (v3.1)

**Files**:
- `mahavishnu/core/task_audit.py` (new file)
- `mahavishnu/mcp/tools/task_tools.py` (update)

**Implementation**:

```python
# mahavishnu/core/task_audit.py
from datetime import datetime, timezone
from typing import Any
from mahavishnu.core.audit import AuditLogger

class TaskAuditLogger(AuditLogger):
    """
    Task-specific audit logging with redaction.

    Events logged:
    - task_created
    - task_updated
    - task_deleted
    - task_assigned
    - task_started
    - task_completed
    - task_cancelled
    - task_blocked
    - task_unblocked
    """

    SENSITIVE_FIELDS = {
        'description',  # May contain sensitive information
        'metadata',     # May contain API keys, etc.
    }

    async def log_task_created(
        self,
        task_id: int,
        user_id: str,
        task_data: dict[str, Any],
    ) -> None:
        """Log task creation event."""
        await self.log(
            event_type="task_created",
            user_id=user_id,
            resource_type="task",
            resource_id=str(task_id),
            details=self._redact_sensitive_fields(task_data),
            timestamp=datetime.now(timezone.utc),
        )

    async def log_task_updated(
        self,
        task_id: int,
        user_id: str,
        changes: dict[str, Any],
    ) -> None:
        """Log task update event."""
        await self.log(
            event_type="task_updated",
            user_id=user_id,
            resource_type="task",
            resource_id=str(task_id),
            details=self._redact_sensitive_fields(changes),
            timestamp=datetime.now(timezone.utc),
        )

    async def log_task_deleted(
        self,
        task_id: int,
        user_id: str,
        task_data: dict[str, Any],
    ) -> None:
        """Log task deletion event."""
        await self.log(
            event_type="task_deleted",
            user_id=user_id,
            resource_type="task",
            resource_id=str(task_id),
            details=self._redact_sensitive_fields(task_data),
            timestamp=datetime.now(timezone.utc),
        )

    async def log_task_completed(
        self,
        task_id: int,
        user_id: str,
        quality_gate_result: dict[str, Any],
    ) -> None:
        """Log task completion event."""
        await self.log(
            event_type="task_completed",
            user_id=user_id,
            resource_type="task",
            resource_id=str(task_id),
            details={
                "quality_gate_passed": quality_gate_result.get("passed", False),
                "checks_run": len(quality_gate_result.get("checks", [])),
            },
            timestamp=datetime.now(timezone.utc),
        )

    def _redact_sensitive_fields(self, data: dict[str, Any]) -> dict[str, Any]:
        """Redact sensitive fields from audit log."""
        redacted = data.copy()

        for field in self.SENSITIVE_FIELDS:
            if field in redacted:
                if redacted[field] is not None:
                    # Redact value but keep length
                    value = str(redacted[field])
                    redacted[field] = f"[REDACTED ({len(value)} characters)]"

        return redacted
```

**Database Schema**:

```sql
-- Task audit log table
CREATE TABLE task_audit_log (
    id BIGSERIAL PRIMARY KEY,
    task_id BIGINT NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    user_id UUID NOT NULL,
    details JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
);

CREATE INDEX idx_task_audit_log_task_id ON task_audit_log(task_id);
CREATE INDEX idx_task_audit_log_user_id ON task_audit_log(user_id);
CREATE INDEX idx_task_audit_log_created_at ON task_audit_log(created_at);
CREATE INDEX idx_task_audit_log_event_type ON task_audit_log(event_type);
```

**Validation**:
- [ ] Unit tests pass: `pytest tests/security/test_audit.py`
- [ ] All task operations logged
- [ ] Sensitive fields redacted
- [ ] Audit log queryable by task_id

---

## Week 3-4: Security Fundamentals (Part 2)

### Day 8-10: Security Test Suite + Async Patterns

**P0-5 from Security Auditor**: Security test suite (1 day)
**P0 from Code Reviewer**: Async timeout handling and context managers (v3.1)

**Tasks**:
- [ ] Create SQL injection test suite
- [ ] Create path traversal test suite
- [ ] Create XSS prevention test suite
- [ ] Create authorization bypass test suite
- [ ] Add security test CI job
- [ ] **Add asyncio.timeout() wrappers to all async operations** (v3.1)
- [ ] **Implement async context managers for DB connections** (v3.1)
- [ ] **Add cancellation handling for long-running operations** (v3.1)
- [ ] **Add rate limiting middleware (slowapi)** (v3.1)

**Files**:
- `tests/security/test_sql_injection.py` (new file)
- `tests/security/test_path_traversal.py` (new file)
- `tests/security/test_auth_bypass.py` (new file)
- `.github/workflows/security-tests.yml` (new file)
- `mahavishnu/core/async_patterns.py` (new file, v3.1)
- `mahavishnu/core/rate_limiting.py` (new file, v3.1)

**Implementation**:

```python
# tests/security/test_sql_injection.py
import pytest
from mahavishnu.core.models import TaskCreateRequest

class TestSQLInjection:
    """SQL injection prevention tests."""

    async def test_sql_injection_in_title(self, client):
        """Test SQL injection in task title."""
        malicious_inputs = [
            "'; DROP TABLE tasks; --",
            "' OR '1'='1",
            "1' UNION SELECT * FROM users--",
            "'; EXEC xp_cmdshell('format c:'); --",
        ]

        for payload in malicious_inputs:
            with pytest.raises(ValueError):
                TaskCreateRequest(
                    title=payload,
                    repository="test-repo",
                )

    async def test_sql_injection_in_search(self, client):
        """Test SQL injection in search query."""
        malicious_queries = [
            "'; DROP TABLE tasks; --",
            "' OR '1'='1",
            "1' UNION SELECT * FROM users--",
        ]

        for query in malicious_queries:
            with pytest.raises(ValueError):
                FTSSearchQuery(query=query)
```

**CI Job**:

```yaml
# .github/workflows/security-tests.yml
name: Security Tests

on: [push, pull_request]

jobs:
  security-tests:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install -e ".[dev]"

      - name: Run security tests
        run: |
          pytest tests/security/ -v

      - name: Run Bandit security linter
        run: |
          bandit -r mahavishnu/ -ll

      - name: Run Safety check
        run: |
          safety check
```

**Async Patterns Implementation (v3.1)**:

```python
# mahavishnu/core/async_patterns.py
import asyncio
from contextlib import asynccontextmanager
from typing import TypeVar, Callable, Any
import logging

T = TypeVar('T')
logger = logging.getLogger(__name__)


@asynccontextmanager
async def timeout_context(seconds: float):
    """Async context manager with timeout handling."""
    try:
        async with asyncio.timeout(seconds):
            yield
    except asyncio.TimeoutError:
        logger.error(f"Operation timed out after {seconds}s")
        raise MahavishnuError(
            f"Operation timed out after {seconds}s",
            ErrorCode.DATABASE_CONNECTION_ERROR,
            ["Check database connectivity", "Increase timeout if needed"],
        )
    except asyncio.CancelledError:
        logger.info("Operation was cancelled")
        raise


@asynccontextmanager
async def db_connection_pool(pool, timeout_seconds: float = 30.0):
    """Async context manager for database connection pool."""
    async with timeout_context(timeout_seconds):
        async with pool.acquire() as conn:
            try:
                yield conn
            except asyncio.CancelledError:
                # Rollback on cancellation
                await conn.execute("ROLLBACK")
                raise


class SagaLock:
    """Distributed lock for saga crash safety using SELECT FOR UPDATE."""

    def __init__(self, db, saga_id: str):
        self.db = db
        self.saga_id = saga_id
        self._locked = False

    async def __aenter__(self):
        """Acquire lock on saga row."""
        row = await self.db.fetch_one(
            "SELECT saga_id FROM saga_log WHERE saga_id = $1 FOR UPDATE",
            self.saga_id,
        )
        if row is None:
            raise MahavishnuError(
                f"Saga {self.saga_id} not found",
                ErrorCode.VALIDATION_ERROR,
            )
        self._locked = True
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Release lock (automatic on transaction commit)."""
        self._locked = False
        return False  # Don't suppress exceptions
```

**Rate Limiting Implementation (v3.1)**:

```python
# mahavishnu/core/rate_limiting.py
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import FastAPI, Request

limiter = Limiter(key_func=get_remote_address)


def setup_rate_limiting(app: FastAPI) -> None:
    """Configure rate limiting for the FastAPI app."""
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# Rate limit decorators for endpoints
RATE_LIMITS = {
    "task_create": "10/minute",      # 10 task creations per minute
    "task_search": "30/minute",      # 30 searches per minute
    "webhook": "100/minute",         # 100 webhooks per minute
    "api_general": "60/minute",      # 60 general API calls per minute
}
```

**Usage in MCP Tools**:

```python
from mahavishnu.core.rate_limiting import limiter, RATE_LIMITS

@app.post("/tasks")
@limiter.limit(RATE_LIMITS["task_create"])
async def create_task(request: Request, task_data: TaskCreateRequest):
    # Create task with rate limiting
    ...

@app.get("/tasks/search")
@limiter.limit(RATE_LIMITS["task_search"])
async def search_tasks(request: Request, query: str):
    # Search tasks with rate limiting
    ...
```

**Validation**:
- [ ] All security tests pass
- [ ] CI job runs successfully
- [ ] Bandit scan passes
- [ ] Safety check passes

---

### Day 11-12: Security Review and Pen Testing + Saga Safety

**Tasks**:
- [ ] Internal security review
- [ ] Fix identified issues
- [ ] Documentation review
- [ ] Security checklist validation
- [ ] **Implement saga SELECT FOR UPDATE crash safety** (v3.1)
- [ ] **Test saga crash recovery scenarios** (v3.1)

**Security Checklist** (from Master Plan v2.0):
- [ ] All webhooks authenticated with HMAC signatures ✅
- [ ] All inputs validated with Pydantic models ✅
- [ ] All database queries use parameterized statements ✅
- [ ] Comprehensive audit logging for all operations ✅
- [ ] Authorization checks on all MCP tools ✅
- [ ] Secrets stored in environment variables only ✅
- [ ] SQL injection prevention testing ✅
- [ ] Security audit (Bandit) passes ✅
- [ ] Penetration testing completed ✅

---

### Day 13-14: Buffer and Documentation

**Tasks**:
- [ ] Security documentation
- [ ] Runbook creation
- [ ] Team training
- [ ] Address any remaining issues

**Documentation**:
- `docs/security/webhook-authentication.md`
- `docs/security/input-validation.md`
- `docs/security/audit-logging.md`
- `docs/runbooks/security-incident-response.md`

---

## Week 5-6: SRE Fundamentals (Part 1)

### Day 15-17: SLI/SLO Refinement

**P0-1 from SRE Engineer**: SLI/SLO refinement (3 days)

**Tasks**:
- [ ] Review existing SLI/SLO definitions (732 lines from v2.0)
- [ ] Add error budget enforcement policy
- [ ] Document error budget recovery mechanisms
- [ ] Create error budget dashboard specifications

**Files**:
- `docs/sre/TASK_ORCHESTRATION_SLOS.md` (update)
- `docs/sre/ERROR_BUDGET_POLICY.md` (new file)

**Error Budget Enforcement Policy**:

```markdown
# Error Budget Policy

## Overview

This document defines the error budget enforcement policy for the Task Orchestration System.

## SLI/SLO Summary

| SLI | SLO | Error Budget (Monthly) |
|-----|-----|------------------------|
| Task Creation Latency (p95) | < 100ms | 43.2 minutes |
| Task Availability | 99.9% | 43.2 minutes |
| Data Durability | 99.999% | 5 minutes/year |
| Workflow Success Rate | 95% | 5% failure rate |
| Webhook Availability | 99.5% | 216 minutes |
| Semantic Search Accuracy | 95% results returned | 5% failure rate |

## Error Budget Enforcement

### Alerting Thresholds

**Burn Rate Alerting**:
- Burn Rate 1x: Normal (error budget consumption within expected rate)
- Burn Rate 2x: Warning (consuming budget 2x faster than expected)
- Burn Rate 5x: Critical (consuming budget 5x faster than expected)

**Actions**:
- Burn Rate 2x for 5 minutes: Warning to on-call engineer
- Burn Rate 5x for 1 minute: Page on-call engineer immediately
- Burn Rate 10x for 30 seconds: Emergency, stop all deployments

### Error Budget Exhaustion

**When error budget exhausted**:
1. **Stop all non-emergency deployments** immediately
2. **Postmortem required** before resuming deployments
3. **Feature freeze** until error budget recovers
4. **Executive notification** if budget exhausted > 24 hours

### Error Budget Recovery

**Recovery Mechanisms**:
1. **Immediate Actions** (within 5 minutes):
   - Stop all deployments
   - Scale up infrastructure (if applicable)
   - Enable circuit breakers

2. **Short-term Actions** (within 1 hour):
   - Identify root cause
   - Implement hotfix
   - Verify fix in staging

3. **Long-term Actions** (within 24 hours):
   - Postmortem document
   - Prevent recurrence
   - Update runbooks

### Error Budget Calculation

**Example Calculation**:

SLI: Task Availability 99.9%
Monthly Budget: 30 days × 0.1% = 43.2 minutes

Current Downtime: 10 minutes
Remaining Budget: 43.2 - 10 = 33.2 minutes

Burn Rate: (10 minutes / 15 days) / (43.2 minutes / 30 days) = 0.46x
Status: Healthy (burn rate < 1x)
```

**Validation**:
- [ ] All SLI/SLOs defined
- [ ] Error budget policy documented
- [ ] Error budget dashboard specifications created
- [ ] Recovery mechanisms documented

---

### Day 18-22: Monitoring and Alerting

**P0-2 from SRE Engineer**: Monitoring and alerting setup (5 days)

**Tasks**:
- [ ] Implement Prometheus metrics for task operations
- [ ] Create Grafana dashboards (3 dashboards required)
  - SLO Dashboard (executive view)
  - Operational Health Dashboard (on-call view)
  - Capacity Planning Dashboard
- [ ] Configure alerting rules with proper thresholds
- [ ] Test alert delivery

**Files**:
- `mahavishnu/core/metrics.py` (update)
- `grafana/dashboards/slo-dashboard.json` (new file)
- `grafana/dashboards/operational-health-dashboard.json` (new file)
- `grafana/dashboards/capacity-planning-dashboard.json` (new file)
- `prometheus/alerts/task_orchestration_alerts.yml` (new file)

**Prometheus Metrics**:

```python
# mahavishnu/core/metrics.py
from prometheus_client import Counter, Histogram, Gauge

# Task operations
task_creation_total = Counter(
    'task_creation_total',
    'Total task creations',
    ['repository', 'status']
)

task_creation_duration_seconds = Histogram(
    'task_creation_duration_seconds',
    'Task creation latency',
    ['repository'],
    buckets=[0.05, 0.1, 0.5, 1.0, 5.0]
)

# Semantic search
semantic_search_total = Counter(
    'semantic_search_total',
    'Total semantic searches',
    ['status']
)

# SLO-specific metrics
slo_error_budget_remaining_seconds = Gauge(
    'slo_error_budget_remaining_seconds',
    'Error budget remaining for each SLO',
    ['slo_name']
)

slo_burn_rate = Gauge(
    'slo_burn_rate',
    'Current error budget burn rate',
    ['slo_name']
)
```

**Alerting Rules**:

```yaml
# prometheus/alerts/task_orchestration_alerts.yml
groups:
  - name: task_orchestration_alerts
    interval: 30s
    rules:
      # SLO breach alerts
      - alert: TaskCreationLatencyHigh
        expr: histogram_quantile(0.95, task_creation_duration_seconds) > 0.1
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Task creation latency above SLO"
          description: "p95 latency is {{ $value }}s (SLO: 0.1s)"

      - alert: TaskAvailabilityLow
        expr: task_availability < 0.999
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Task availability below SLO"
          description: "Current availability: {{ $value }} (SLO: 0.999)"

      # Error budget alerts
      - alert: ErrorBudgetBurnRateCritical
        expr: slo_burn_rate{slo_name="task_availability"} > 5
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Error budget burn rate critical"
          description: "Consuming error budget 5x faster than normal"

      # Database alerts
      - alert: DatabaseConnectionPoolExhausted
        expr: database_connections{database="postgresql"} > 90
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "PostgreSQL connection pool nearly exhausted"
          description: "{{ $value }} active connections"
```

**Grafana Dashboards**:

1. **SLO Dashboard** (Executive View):
   - SLI/SLO status overview
   - Error budget remaining
   - Burn rate trend
   - SLO breach alerts

2. **Operational Health Dashboard** (On-Call View):
   - Task creation latency (p50, p95, p99)
   - Error rate by operation
   - Database health (connections, latency)
   - Active alerts

3. **Capacity Planning Dashboard**:
   - Task volume trend
   - Database storage usage
   - Query performance trend
   - Growth projections

**Validation**:
- [ ] Prometheus metrics exposed
- [ ] All 3 dashboards created
- [ ] Alerting rules configured
- [ ] Alert delivery tested (email, Slack, PagerDuty)
- [ ] Dashboards display correct data

---

### Day 23-25: Deployment Runbooks

**P0-3 from SRE Engineer**: Deployment runbooks (3 days)

**Tasks**:
- [ ] Create deployment runbook
- [ ] Create rollback procedures
- [ ] Create database migration runbook
- [ ] Test rollback procedures in staging

**Files**:
- `docs/runbooks/deployment.md` (new file)
- `docs/runbooks/rollback.md` (new file)
- `docs/runbooks/database-migration.md` (new file)

**Deployment Runbook**:

```markdown
# Deployment Runbook

## Pre-Deployment Checklist

- [ ] All tests pass (unit, integration, security)
- [ ] Error budget is healthy (> 50% remaining)
- [ ] No active incidents
- [ ] On-call team aware of deployment
- [ ] Rollback plan documented
- [ ] Monitoring dashboards ready

## Deployment Process

### 1. Blue-Green Deployment

1. Deploy to blue environment
2. Run smoke tests against blue
3. Switch 10% traffic to blue
4. Monitor for 15 minutes
5. Gradually increase traffic to 50%, then 100%
6. Monitor for 1 hour

### 2. Validation Checks

After each traffic increase:
- [ ] Error rate < 1%
- [ ] Latency p95 < SLO threshold
- [ ] No new alerts firing
- [ ] User feedback positive

### 3. Rollback Triggers

Immediately rollback if:
- Error rate > 5% for 5 minutes
- Latency p95 > 2x baseline for 10 minutes
- Critical alerts firing
- User reports of broken functionality

## Post-Deployment

- [ ] Monitor for 24 hours
- [ ] Document any issues
- [ ] Update runbooks if needed
- [ ] Debrief team if issues occurred
```

**Validation**:
- [ ] Deployment runbook created
- [ ] Rollback procedures documented
- [ ] Database migration runbook created
- [ ] Rollback tested in staging
- [ ] Team trained on procedures

---

## Week 7-8: SRE Fundamentals (Part 2)

### Day 26-28: Disaster Recovery Procedures

**P0-2 from SRE Engineer**: Disaster recovery testing (3 days)

**Tasks**:
- [ ] Create disaster recovery runbook
- [ ] Schedule monthly DR tests
- [ ] Create backup verification script
- [ ] First disaster recovery test (document results)

**Files**:
- `docs/runbooks/disaster-recovery.md` (new file)
- `scripts/verify-backups.py` (new file)
- `scripts/test-dr.py` (new file)

**Disaster Recovery Runbook**:

```markdown
# Disaster Recovery Runbook

## Backup Strategy

### Daily Backups

- **PostgreSQL**: `pg_dump` to S3/GCS (30-day retention)
- **Akosha**: Vector DB snapshot + graph export
- **Session-Buddy**: Session export (JSON)

### Point-in-Time Recovery (PITR)

- PostgreSQL WAL archiving to S3/GCS
- Can restore to any point in last 7 days
- RTO: 1 hour, RPO: 5 minutes

## Recovery Procedures

### 1. Database Failure

**Symptoms**: Database connection failures, high error rate

**Recovery Steps**:
1. Check database status: `systemctl status postgresql`
2. Check database logs: `tail -f /var/log/postgresql/postgresql.log`
3. If database is down: `systemctl start postgresql`
4. If data corruption: Restore from backup

**RTO**: 5 minutes, **RPO**: 0 seconds (streaming replication)

### 2. Application Server Failure

**Symptoms**: Application not responding, health check failing

**Recovery Steps**:
1. Check application status: `systemctl status mahavishnu`
2. Check application logs: `journalctl -u mahavishnu -f`
3. If application is down: `systemctl start mahavishnu`
4. If persistent issues: Restart Kubernetes pod

**RTO**: 2 minutes

### 3. Region Failure

**Symptoms**: Entire region unavailable

**Recovery Steps**:
1. Check status page: https://status.aws.amazon.com/
2. Initiate failover to secondary region
3. Update DNS to point to secondary region
4. Verify application health in secondary region

**RTO**: 30 minutes, **RPO**: 5 minutes

## Disaster Recovery Testing

**Monthly DR Test**:
1. Schedule test window (first Sunday of month, 2-4 AM UTC)
2. Notify team 1 week in advance
3. Simulate database failure
4. Execute recovery procedures
5. Document results
6. Update runbooks if issues found

**DR Test Results**:
- Date: [Date]
- Scenario: [Scenario]
- RTO Achieved: [RTO]
- RPO Achieved: [RPO]
- Issues Found: [Issues]
- Actions Taken: [Actions]
```

**Validation**:
- [ ] Disaster recovery runbook created
- [ ] Backup verification script created
- [ ] First DR test completed successfully
- [ ] DR test documented
- [ ] Monthly DR test scheduled

---

### Day 29-31: On-Call Procedures

**P0-3 from SRE Engineer**: On-call procedures (3 days)

**Tasks**:
- [ ] Define on-call rotation (primary + shadow)
- [ ] Document escalation paths (T0 → T1 → T2 → T3)
- [ ] Create handoff procedures
- [ ] Setup on-call ticket queue
- [ ] Document on-call burden management

**Files**:
- `docs/runbooks/on-call-handbook.md` (new file)

**On-Call Handbook**:

```markdown
# On-Call Handbook

## On-Call Rotation

### Structure

- **Primary On-Call**: First responder, handles all alerts
- **Shadow On-Call**: Learns from primary, backs up primary
- **Rotation**: Weekly rotation every Monday 9 AM UTC

### Responsibilities

**Primary On-Call**:
- Respond to all alerts within 15 minutes
- Investigate and resolve incidents
- Escalate if needed
- Document incidents

**Shadow On-Call**:
- Shadow primary during incidents
- Learn troubleshooting procedures
- Cover for primary during PTO/sick time

## Escalation Paths

### T0: Primary On-Call
- **Response Time**: 15 minutes
- **Responsibilities**: Initial investigation, resolution

### T1: Secondary On-Call (Previous week's primary)
- **Response Time**: 30 minutes
- **Responsibilities**: Assist primary, handle complex issues

### T2: Engineering Lead
- **Response Time**: 1 hour
- **Responsibilities**: Coordinate response, make decisions

### T3: CTO
- **Response Time**: 2 hours
- **Responsibilities**: Executive decisions, major incidents

## Handoff Procedures

### Weekly Handoff (Every Monday 9 AM UTC)

1. **Review Past Week**:
   - Incidents: Number, severity, resolution
   - Trends: Any patterns or recurring issues
   - Outstanding issues: What still needs attention

2. **Current Status**:
   - Active incidents: Any ongoing issues
   - Upcoming changes: Deployments, maintenance
   - Known issues: Documented bugs or outages

3. **Handoff Checklist**:
   - [ ] PagerDuty handoff completed
   - [ ] Access to all systems verified
   - [ ] Contact information updated
   - [ ] Knowledge transfer documented

## On-Call Burden Management

### Metrics

- **Alert Frequency**: Target < 10 alerts/week
- **Incident Frequency**: Target < 2 incidents/week
- **Mean Time to Resolution (MTTR)**: Target < 1 hour
- **On-Call Satisfaction**: Quarterly survey

### Burnout Prevention

- **Max On-Call Weeks**: 1 week on, 3 weeks off
- **No On-Call During PTO**: Automatic reassignment
- **Shadow Rotation**: Required before becoming primary
- **Post-Incident Debrief**: Support after major incidents

### On-Call Compensation

- **On-Call Stipend**: $X/week when on-call
- **Incident Bonus**: $Y for incidents outside business hours
- **Training Time**: 4 hours/month for on-call training

## On-Call Ticket Queue

### Setup

- **Tool**: PagerDuty or Opsgenie
- **Integration**: Prometheus alerts → PagerDuty
- **Escalation**: Automatic escalation based on severity

### Alert Classification

**P1 - Critical**:
- System down
- Data loss
- Security breach
- **Response**: Immediate page (< 15 minutes)

**P2 - High**:
- Degraded performance
- Feature broken
- **Response**: Page within 30 minutes

**P3 - Medium**:
- Minor bugs
- Documentation issues
- **Response**: Next business day

**P4 - Low**:
- Feature requests
- Improvements
- **Response**: backlog

## On-Call Tools

### Required Tools

- **PagerDuty**: Alert management
- **Slack**: Communication
- **Grafana**: Monitoring dashboards
- **Kubectl**: Kubernetes management
- **psql**: Database access

### Quick Links

- Grafana: http://grafana.example.com
- Prometheus: http://prometheus.example.com
- PagerDuty: https://[organization].pagerduty.com
- Runbooks: https://docs.example.com/runbooks

## On-Call Training

### New On-Call Training (4 hours)

1. **System Overview** (1 hour):
   - Architecture overview
   - Key components
   - Data flow

2. **Monitoring** (1 hour):
   - Grafana dashboards
   - Prometheus queries
   - Alert interpretation

3. **Troubleshooting** (1 hour):
   - Common issues
   - Resolution procedures
   - Escalation paths

4. **Simulation** (1 hour):
   - Practice scenarios
   - Handoff practice
   - Q&A

### Ongoing Training

- **Monthly On-Call Meeting**: Review incidents, improve procedures
- **Quarterly Training**: New features, updated procedures
- **Shadow Rotation**: Required quarterly
```

**Validation**:
- [ ] On-call rotation defined
- [ ] Escalation paths documented
- [ ] Handoff procedures created
- [ ] On-call ticket queue setup
- [ ] On-call burden management documented
- [ ] Team trained on procedures

---

### Day 32-35: Validation and Hardening

**Tasks**:
- [ ] Load testing baseline (50 concurrent users)
- [ ] Incident response simulation
- [ ] Post-incident review
- [ ] Documentation review
- [ ] Final security audit

**Load Testing**:

```bash
# k6 load testing script
import http from 'k6/http';
import { check, sleep } from 'k6';

export let options = {
  vus: 50,
  duration: '10m',
  thresholds: {
    http_req_duration: ['p(95)<500'],  // 95% of requests < 500ms
    http_req_failed: ['rate<0.01'],     // Error rate < 1%
  },
};

export default function () {
  // Test task creation
  let createRes = http.post('http://localhost:8000/tasks', {
    title: 'Test task',
    repository: 'test-repo',
  });

  check(createRes, {
    'task created status 201': (r) => r.status === 201,
  });

  sleep(1);
}
```

**Incident Response Simulation**:

1. **Scenario**: Database connection failure
2. **Actions**:
   - Detect failure (monitoring alerts)
   - Investigate root cause (check database status)
   - Implement fix (restart database)
   - Verify recovery (run smoke tests)
   - Document incident (postmortem)

**Post-Incident Review**:

1. **Timeline**: What happened, when
2. **Root Cause**: Why did it happen
3. **Impact**: Who was affected, how severe
4. **Resolution**: How was it fixed
5. **Prevention**: How to prevent recurrence

**Final Validation Checklist**:

- [ ] All P0 security fixes implemented and tested ✅
- [ ] All P0 SRE fundamentals implemented and tested ✅
- [ ] SLI/SLOs defined and documented ✅
- [ ] Monitoring dashboards deployed (3 dashboards) ✅
- [ ] Alerting rules configured and tested ✅
- [ ] Deployment runbooks created ✅
- [ ] Disaster recovery procedures documented ✅
- [ ] First disaster recovery test completed ✅
- [ ] On-call procedures defined ✅
- [ ] Load testing baseline established ✅
- [ ] Incident response simulation completed ✅
- [ ] Documentation review completed ✅
- [ ] Final security audit passed ✅
- [ ] **Users table created with foreign keys** ✅ (v3.1)
- [ ] **Error code system implemented (MHV-001 to MHV-099)** ✅ (v3.1)
- [ ] **Async timeout handling and context managers** ✅ (v3.1)
- [ ] **Rate limiting middleware deployed** ✅ (v3.1)
- [ ] **Saga SELECT FOR UPDATE crash safety** ✅ (v3.1)

---

## Week 7-8 (Optional): Additional Buffer

**Tasks**:
- [ ] Address any remaining P0 issues
- [ ] Additional testing
- [ ] Documentation polish
- [ ] Team training

**Buffer Time**: Use for unexpected issues or overruns

---

## Deliverables Summary

### Documentation

1. **Security**:
   - `docs/security/webhook-authentication.md`
   - `docs/security/input-validation.md`
   - `docs/security/audit-logging.md`
   - `docs/runbooks/security-incident-response.md`

2. **SRE**:
   - `docs/sre/TASK_ORCHESTRATION_SLOS.md` (updated)
   - `docs/sre/ERROR_BUDGET_POLICY.md`
   - `docs/runbooks/deployment.md`
   - `docs/runbooks/rollback.md`
   - `docs/runbooks/database-migration.md`
   - `docs/runbooks/disaster-recovery.md`
   - `docs/runbooks/on-call-handbook.md`

### Code

1. **Security**:
   - `mahavishnu/core/webhook_auth.py`
   - `mahavishnu/core/models.py` (updated with Pydantic v2)
   - `mahavishnu/core/task_audit.py`
   - `mahavishnu/core/errors.py` (new, v3.1 - error code system)
   - `mahavishnu/core/async_patterns.py` (new, v3.1)
   - `mahavishnu/core/rate_limiting.py` (new, v3.1)
   - `tests/security/test_webhooks.py`
   - `tests/security/test_validation.py`
   - `tests/security/test_sql_injection.py`
   - `tests/security/test_auth_bypass.py`

2. **Database**:
   - `migrations/001_create_users_table.sql` (new, v3.1)

2. **SRE**:
   - `mahavishnu/core/metrics.py` (updated)
   - `grafana/dashboards/slo-dashboard.json`
   - `grafana/dashboards/operational-health-dashboard.json`
   - `grafana/dashboards/capacity-planning-dashboard.json`
   - `prometheus/alerts/task_orchestration_alerts.yml`
   - `scripts/verify-backups.py`
   - `scripts/test-dr.py`

### Infrastructure

1. **Monitoring**:
   - Prometheus server configured
   - Grafana dashboards deployed
   - Alerting rules configured
   - Alert delivery tested (email, Slack, PagerDuty)

2. **Disaster Recovery**:
   - Backup automation configured
   - First DR test completed
   - Recovery procedures documented

---

## Next Steps After Phase 0

**Prerequisites for Phase 1**:
- [ ] All Phase 0 deliverables completed
- [ ] All validation checks passed
- [ ] Team training completed
- [ ] Documentation reviewed and approved

**Phase 1 Kickoff**:
- [ ] Review Phase 1 plan (6 weeks, extended from 4-5 weeks)
- [ ] Set up Phase 1 project tracking
- [ ] Schedule Phase 1 milestones and checkpoints

---

**END OF PHASE 0 ACTION PLAN**

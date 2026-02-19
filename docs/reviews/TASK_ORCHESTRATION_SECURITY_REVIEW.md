# Task Orchestration Master Plan - Security Review

**Review Date**: 2026-02-18
**Reviewer**: Claude Sonnet 4.5 (Security Specialist)
**Document**: `/docs/TASK_ORCHESTRATION_MASTER_PLAN.md`
**Status**: **APPROVE WITH CHANGES**

---

## Executive Summary

The Task Orchestration Master Plan presents a comprehensive multi-repository task management system with strong architectural foundations. However, several **critical security vulnerabilities** must be addressed before production deployment. The plan demonstrates security awareness but lacks specific implementation details for key security controls.

**Overall Security Rating**: **6.5/10**

**Key Findings**:
- ✅ **Strong**: Existing security infrastructure (validators, secrets scanner)
- ⚠️ **Moderate**: Webhook security and approval workflow
- ❌ **Critical**: Missing input validation for NLP parser, insufficient SQL injection protections
- ❌ **Critical**: No comprehensive audit logging system defined
- ⚠️ **Moderate**: Access control model incomplete

---

## 1. One-Way Sync & Approval Workflow

### Assessment: **MODERATE RISK** ⚠️

The one-way sync approach (GitHub/GitLab → Mahavishnu) with manual approval is a **good security design** that prevents:

- ✅ Issue pollution on external platforms
- ✅ Uncontrolled task creation
- ✅ Spam/malicious issue injection

### Critical Gaps

#### ❌ **Gap 1.1: Webhook Authentication Not Specified**

**Current State** (lines 1498-1518):
```yaml
# GitHub webhook settings
URL: https://mahavishnu.example.com/api/webhooks/github
Secret: ${GITHUB_WEBHOOK_SECRET}  # ⚠️ Not validated in document
```

**Risk**: Webhook endpoints without proper authentication are vulnerable to:
- Spoofed webhooks from malicious actors
- Replay attacks
- Denial of service via webhook spam

**Required Fix**:
```python
# MISSING: Webhook signature validation
class WebhookValidator:
    """Validate GitHub/GitLab webhook signatures."""

    def __init__(self, secret: str):
        self.secret = secret

    def validate_github_signature(
        self,
        payload: bytes,
        signature_header: str
    ) -> bool:
        """
        Validate GitHub webhook signature.

        GitHub sends: X-Hub-Signature-256: sha256=<hash>
        """
        if not signature_header:
            raise ValueError("Missing signature header")

        # Extract hash
        hash_algorithm, github_signature = signature_header.split("=", 1)
        if hash_algorithm != "sha256":
            raise ValueError(f"Unsupported algorithm: {hash_algorithm}")

        # Compute expected signature
        import hmac
        import hashlib

        expected_signature = hmac.new(
            self.secret.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()

        # Constant-time comparison (prevent timing attacks)
        return hmac.compare_digest(
            github_signature,
            expected_signature
        )

    def validate_gitlab_signature(
        self,
        payload: bytes,
        token_header: str
    ) -> bool:
        """
        Validate GitLab webhook token.

        GitLab sends: X-Gitlab-Token
        """
        if not token_header:
            raise ValueError("Missing token header")

        return hmac.compare_digest(
            token_header,
            self.secret
        )
```

**Implementation Requirements**:
1. Reject webhooks with invalid signatures (HTTP 401)
2. Log all webhook validation failures
3. Rate limit webhook endpoints (prevent DoS)
4. Add replay attack protection (timestamp validation)

---

#### ❌ **Gap 1.2: No Approval Authority/Authorization Model**

**Current State** (lines 1290-1365):
```python
async def approve_task_proposal(self, proposal_id: str) -> Task:
    """User approves - convert proposal to real task."""
    # ⚠️ NO AUTHORIZATION CHECK - Anyone can approve?
```

**Risk**: Unauthorized users can approve malicious task proposals.

**Required Fix**:
```python
class ApprovalAuthority:
    """Manage who can approve task proposals."""

    def __init__(self, authorized_users: list[str]):
        self.authorized_users = set(authorized_users)

    def check_approval_permission(self, user_id: str) -> bool:
        """Check if user is authorized to approve proposals."""
        return user_id in self.authorized_users

    def require_approval_permission(self, user_id: str):
        """Raise exception if user lacks approval permission."""
        if not self.check_approval_permission(user_id):
            raise PermissionError(
                f"User {user_id} is not authorized to approve task proposals"
            )

# Usage in OneWaySyncHandler
async def approve_task_proposal(
    self,
    proposal_id: str,
    approver_user_id: str  # REQUIRED: Who is approving
) -> Task:
    """User approves - convert proposal to real task."""

    # ✅ ADD: Authorization check
    self.approval_authority.require_approval_permission(approver_user_id)

    proposal = await self.approval_queue.get(proposal_id)
    # ... rest of approval logic
```

**Authorization Model Requirements**:
1. Define approver roles (admin, maintainer, trusted-developer)
2. Store approval decisions with approver identity
3. Require approval reason for audit trail
4. Implement approval revocation capability

---

#### ⚠️ **Gap 1.3: No Approval Quorum/Review Process**

**Risk**: Single compromised approver can approve malicious tasks.

**Recommendation** (optional for MVP):
```yaml
# Optional: Multi-approval workflow
approval:
  mode: single  # single | quorum | any_trusted
  quorum_size: 2  # Require 2 approvals for sensitive tasks
  auto_approve:
    trusted_labels: ["bug", "critical"]  # Auto-approve from trusted sources
    trusted_users: ["les", "senior-dev"]
```

---

## 2. Injection Attack Vulnerabilities

### Assessment: **CRITICAL RISK** ❌

The NLP task parser is a **high-value attack surface** that could allow:

- SQL injection via task descriptions
- Command injection via worktree names
- Path traversal via repository names
- Stored XSS via task titles

### Critical Vulnerabilities

#### ❌ **Vulnerability 2.1: No Input Sanitization for NLP Parser**

**Current State** (lines 436-491):
```python
# 1. NLP Parser extracts:
{
    "action": "fix",
    "type": "bug",
    "scope": "authentication",
    "repository": "session-buddy",  # ⚠️ NOT VALIDATED
    "deadline": "this Friday",  # ⚠️ NOT VALIDATED
    "priority": "high",
}

# ⚠️ NO SANITIZATION before database insertion
task = await task_orchestrator.create_task(**extracted_data)
```

**Attack Vector 1: Repository Name Injection**
```bash
# Malicious input
mhv task add "Fix bug in '../../../etc/passwd' by Friday"

# ⚠️ If not sanitized, could lead to:
# - Path traversal when creating worktree
# - SQL injection if repository name used in query
```

**Attack Vector 2: Command Injection via Task Title**
```bash
# Malicious input
mhv task add "Fix bug; rm -rf ~/worktrees"  # Semicolon injection

# ⚠️ If task title used in shell commands (e.g., git branch names)
```

**Required Fix: Input Sanitization Layer**
```python
from mahavishnu.core.validators import PathValidator
import re
from typing import Dict, Any

class TaskInputSanitizer:
    """Sanitize and validate task inputs to prevent injection attacks."""

    def __init__(self):
        self.path_validator = PathValidator()
        self.allowed_repos = None  # Load from repos.yaml

    def sanitize_task_input(
        self,
        raw_input: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Sanitize all task inputs from NLP parser.

        Args:
            raw_input: Raw extracted data from NLP parser

        Returns:
            Sanitized input safe for database/storage

        Raises:
            ValueError: If input contains malicious patterns
        """
        sanitized = {}

        # Sanitize task title (remove shell metacharacters)
        if "title" in raw_input:
            sanitized["title"] = self._sanitize_text(
                raw_input["title"],
                max_length=200,
                allow_shell_chars=False  # Block ;, &, |, $, etc.
            )

        # Sanitize repository name (validate against whitelist)
        if "repository" in raw_input:
            sanitized["repository"] = self._validate_repository(
                raw_input["repository"]
            )

        # Sanitize deadline (parse and validate)
        if "deadline" in raw_input:
            sanitized["deadline"] = self._validate_deadline(
                raw_input["deadline"]
            )

        # Sanitize priority (validate against enum)
        if "priority" in raw_input:
            sanitized["priority"] = self._validate_priority(
                raw_input["priority"]
            )

        # Sanitize description (remove potential XSS)
        if "description" in raw_input:
            sanitized["description"] = self._sanitize_html(
                raw_input["description"]
            )

        return sanitized

    def _sanitize_text(
        self,
        text: str,
        max_length: int = 500,
        allow_shell_chars: bool = False
    ) -> str:
        """
        Sanitize text input.

        Blocks:
        - Shell metacharacters: ;, &, |, $, `, (, )
        - Control characters
        - Excessive length (DoS prevention)
        """
        if not text:
            return text

        # Remove control characters
        text = "".join(char for char in text if ord(char) >= 32)

        # Block shell metacharacters
        if not allow_shell_chars:
            shell_chars = [";", "&", "|", "$", "`", "(", ")", "\n", "\r"]
            for char in shell_chars:
                if char in text:
                    raise ValueError(
                        f"Text contains forbidden character: {char!r}"
                    )

        # Limit length
        if len(text) > max_length:
            text = text[:max_length]

        return text.strip()

    def _validate_repository(self, repo_name: str) -> str:
        """
        Validate repository name against whitelist.

        CRITICAL: Prevents repository name injection attacks.
        """
        # Load allowed repositories
        if not self.allowed_repos:
            from mahavishnu.core.repo_manager import RepoManager
            repo_mgr = RepoManager()
            self.allowed_repos = {
                repo.nickname or repo.name
                for repo in repo_mgr.list_repos()
            }

        if repo_name not in self.allowed_repos:
            raise ValueError(
                f"Repository '{repo_name}' not found in allowed repositories"
            )

        return repo_name

    def _validate_deadline(self, deadline_str: str) -> str:
        """
        Validate and parse deadline string.

        Prevents date injection attacks.
        """
        # Use a whitelist of supported date formats
        supported_patterns = [
            r"by \w+day",  # "by Friday"
            r"in \d+ days?",  # "in 2 days"
            r"tomorrow",  # "tomorrow"
            r"next week",  # "next week"
        ]

        import re
        if not any(re.match(pattern, deadline_str) for pattern in supported_patterns):
            raise ValueError(
                f"Deadline format not supported: {deadline_str}"
            )

        # Parse and validate date is in future
        from datetime import datetime, timedelta
        parsed_date = self._parse_relative_date(deadline_str)

        if parsed_date < datetime.now():
            raise ValueError("Deadline must be in the future")

        if parsed_date > datetime.now() + timedelta(days=365):
            raise ValueError("Deadline too far in future (> 1 year)")

        return parsed_date.isoformat()

    def _validate_priority(self, priority: str) -> str:
        """Validate priority against allowed values."""
        allowed = {"low", "medium", "high", "critical"}
        if priority.lower() not in allowed:
            raise ValueError(
                f"Invalid priority: {priority}. Must be one of {allowed}"
            )
        return priority.lower()

    def _sanitize_html(self, text: str) -> str:
        """
        Sanitize HTML in task descriptions.

        Prevents stored XSS attacks.
        """
        # For MVP, strip all HTML tags
        # For production, use bleach library
        import bleach

        # Allow basic formatting, block scripts/events
        allowed_tags = ["p", "b", "i", "em", "strong", "a", "ul", "ol", "li"]
        allowed_attrs = {"a": ["href"]}

        return bleach.clean(
            text,
            tags=allowed_tags,
            attributes=allowed_attrs,
            strip=True
        )

# Integration in TaskOrchestrator
class TaskOrchestrator:
    def __init__(self):
        self.input_sanitizer = TaskInputSanitizer()

    async def create_task(self, description: str) -> Task:
        # Parse natural language
        raw_input = await self.nlp_parser.parse(description)

        # ✅ SANITIZE INPUT BEFORE STORAGE
        sanitized_input = self.input_sanitizer.sanitize_task_input(raw_input)

        # Create task with sanitized input
        return await self.task_store.create(**sanitized_input)
```

---

#### ❌ **Vulnerability 2.2: SQL Injection via Task Search**

**Current State** (lines 500-527):
```python
# ⚠️ User query directly used in FTS search
results = await self.sqlite.fulltext_search(query)  # NO SANITIZATION
```

**Attack Vector**:
```bash
# Malicious search query
mhv task find "'; DROP TABLE tasks; --"

# ⚠️ If query is concatenated (not parameterized), this drops the tasks table
```

**Required Fix: Parameterized Queries**
```python
class TaskStore:
    async def fulltext_search(self, query: str) -> list[Task]:
        """
        Search tasks using parameterized query.

        CRITICAL: Always use parameterized queries to prevent SQL injection.
        """
        # ✅ Use parameterized query (query string passed as parameter)
        sql = """
            SELECT t.* FROM tasks t
            INNER JOIN tasks_fts fts ON t.id = fts.rowid
            WHERE tasks_fts MATCH ?
            ORDER BY rank
        """

        # ✅ Sanitize query string (remove SQLite FTS special characters)
        sanitized_query = self._sanitize_fts_query(query)

        # ✅ Execute with parameter binding
        cursor = await self.db.execute(sql, (sanitized_query,))
        rows = await cursor.fetchall()

        return [self._row_to_task(row) for row in rows]

    def _sanitize_fts_query(self, query: str) -> str:
        """
        Sanitize FTS query to prevent injection.

        FTS special characters: ", *, (, ), -, <, >
        """
        # Remove dangerous characters
        dangerous = ['"', '*', '(', ')', '-', '<', '>']
        for char in dangerous:
            query = query.replace(char, '')

        # Limit query length
        if len(query) > 100:
            query = query[:100]

        return query.strip()
```

---

## 3. Data Privacy & Credential Redaction

### Assessment: **MODERATE RISK** ⚠️

### Positive Finding: Secrets Scanner Already Exists ✅

**Existing Capability** (`mahavishnu/core/secrets_scanner.py`):
- ✅ Detects API keys, passwords, tokens
- ✅ Integrates with detect-secrets library
- ✅ Supports credential redaction

### ❌ **Gap 3.1: Secrets Scanning Not Applied to Task Descriptions**

**Risk**: Users may accidentally paste credentials into task descriptions.

**Required Fix**:
```python
class TaskOrchestrator:
    def __init__(self):
        self.secrets_scanner = SecretsScanner(
            fail_on_secrets=True,  # Block tasks with secrets
            block_on_high_severity=True
        )

    async def create_task(
        self,
        title: str,
        description: str = "",
        **kwargs
    ) -> Task:
        """
        Create task with secret detection.

        Blocks task creation if credentials detected.
        """
        # ✅ Scan description for secrets
        from mahavishnu.core.secrets_scanner import SecretScanResult

        # Create temporary file to scan
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write(f"# {title}\n\n{description}")
            temp_path = f.name

        try:
            scan_result = await self.secrets_scanner.scan_directory(
                Path(temp_path).parent
            )

            if scan_result.has_secrets:
                # ✅ Redact secrets and warn user
                redactor = SecretRedactor(scan_result.secrets_found)
                redacted_desc = redactor.redact_code(description)

                raise ValueError(
                    f"Task description contains detected secrets:\n"
                    f"{scan_result.to_dict()}\n\n"
                    f"Redacted description:\n{redacted_desc}\n\n"
                    f"Please remove secrets before creating task."
                )

        finally:
            # Clean up temp file
            Path(temp_path).unlink(missing_ok=True)

        # Safe to create task
        return await self.task_store.create(
            title=title,
            description=description,
            **kwargs
        )
```

---

## 4. Access Control Model

### Assessment: **CRITICAL GAP** ❌

### ❌ **Gap 4.1: No Authentication/Authorization Defined**

**Current State**: The document assumes "User" but doesn't define:
- How users authenticate
- Authorization model (RBAC, ABAC)
- Permission checks for task operations

**Required Fix: Define Access Control Model**
```python
from enum import Enum
from typing import Set

class TaskPermission(Enum):
    """Permissions for task operations."""
    CREATE = "task.create"
    READ = "task.read"
    UPDATE = "task.update"
    DELETE = "task.delete"
    START = "task.start"  # Create worktree
    COMPLETE = "task.complete"  # Run quality gates
    APPROVE = "task.approve"  # Approve proposals
    ADMIN = "task.admin"

class Role(Enum):
    """User roles."""
    ADMIN = "admin"
    MAINTAINER = "maintainer"
    DEVELOPER = "developer"
    VIEWER = "viewer"

class AccessControl:
    """Enforce access control for task operations."""

    # Role → Permissions mapping
    ROLE_PERMISSIONS = {
        Role.ADMIN: {perm for perm in TaskPermission},
        Role.MAINTAINER: {
            TaskPermission.CREATE,
            TaskPermission.READ,
            TaskPermission.UPDATE,
            TaskPermission.DELETE,
            TaskPermission.START,
            TaskPermission.COMPLETE,
            TaskPermission.APPROVE,
        },
        Role.DEVELOPER: {
            TaskPermission.CREATE,
            TaskPermission.READ,
            TaskPermission.UPDATE,
            TaskPermission.START,
            TaskPermission.COMPLETE,
        },
        Role.VIEWER: {
            TaskPermission.READ,
        },
    }

    def __init__(self, user_roles: dict[str, Set[Role]]):
        """
        Initialize access control.

        Args:
            user_roles: Mapping of user_id → set of roles
        """
        self.user_roles = user_roles

    def check_permission(
        self,
        user_id: str,
        required_permission: TaskPermission
    ) -> bool:
        """Check if user has required permission."""
        user_role_set = self.user_roles.get(user_id, set())

        # Check all user roles
        for role in user_role_set:
            if role in self.ROLE_PERMISSIONS:
                if required_permission in self.ROLE_PERMISSIONS[role]:
                    return True

        return False

    def require_permission(
        self,
        user_id: str,
        required_permission: TaskPermission
    ):
        """Raise exception if user lacks permission."""
        if not self.check_permission(user_id, required_permission):
            raise PermissionError(
                f"User {user_id} lacks permission: {required_permission.value}"
            )

# Usage in TaskOrchestrator
class TaskOrchestrator:
    def __init__(self, access_control: AccessControl):
        self.access_control = access_control

    async def create_task(
        self,
        user_id: str,  # REQUIRED: Who is creating
        description: str
    ) -> Task:
        """Create task with permission check."""

        # ✅ Check user has CREATE permission
        self.access_control.require_permission(
            user_id,
            TaskPermission.CREATE
        )

        # Create task
        task = await self.task_store.create(
            created_by=user_id,  # Track creator
            description=description
        )

        # ✅ Log creation event
        await self.audit_logger.log(
            event_type="task.created",
            user_id=user_id,
            task_id=task.id,
            details={"description": description[:100]}  # Truncate for log
        )

        return task
```

---

## 5. SQL Injection Protection

### Assessment: **MODERATE RISK** ⚠️

### ✅ **Positive: SQLite Schema Uses Parameterized Queries** (Assumed)

**Schema** (lines 338-419):
```sql
-- ✅ Schema uses proper types and constraints
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'in_progress', ...)),
    -- ...
);
```

### ❌ **Gap 5.1: No Parameterized Query Examples Shown**

**Required Fix**: All database operations must use parameterized queries.

**Document Should Specify**:
```python
# ✅ CORRECT: Parameterized query
async def create_task(self, **kwargs):
    sql = """
        INSERT INTO tasks (id, title, description, status, priority)
        VALUES (?, ?, ?, ?, ?)
    """
    cursor = await self.db.execute(
        sql,
        (kwargs["id"], kwargs["title"], kwargs["description"],
         kwargs["status"], kwargs["priority"])
    )
    await self.db.commit()

# ❌ WRONG: String concatenation (SQL injection vulnerable)
async def create_task_wrong(self, **kwargs):
    sql = f"""
        INSERT INTO tasks (id, title, description, status, priority)
        VALUES ('{kwargs["id"]}', '{kwargs["title"]}', ...)
    """
    # ⚠️ VULNERABLE TO SQL INJECTION
```

**Requirement**: Update master plan to include:
1. Mandate parameterized queries for all DB operations
2. Use SQLAlchemy or similar ORM (not raw SQL)
3. Add unit tests for SQL injection attempts

---

## 6. Path Traversal Protection

### Assessment: **LOW RISK** ✅

### ✅ **Positive: PathValidator Already Exists**

**Existing Capability** (`mahavishnu/core/validators.py`):
- ✅ Prevents directory traversal (`..` sequences)
- ✅ Validates paths against allowed base directories
- ✅ Sanitizes filenames

### ⚠️ **Gap 6.1: PathValidator Not Used in Task Plan**

**Required Fix**: Document should explicitly state:
```python
# In worktree creation
from mahavishnu.core.validators import PathValidator

class TaskOrchestrator:
    def __init__(self):
        self.path_validator = PathValidator(
            allowed_base_dirs=self._get_worktree_base_dirs()
        )

    async def create_worktree_for_task(
        self,
        task_id: str,
        repository: str
    ) -> Path:
        """Create worktree with path validation."""

        # ✅ Validate repository path
        repo_path = self.path_validator.validate_repository_path(repository)

        # ✅ Sanitize worktree branch name
        branch_name = PathValidator.sanitize_filename(
            f"task-{task_id}-{task_title}"
        )

        # Create worktree
        worktree_path = await self.worktree_coordinator.create_worktree(
            repo_path=repo_path,
            branch=branch_name
        )

        return worktree_path
```

---

## 7. Audit Logging

### Assessment: **CRITICAL GAP** ❌

### ❌ **Gap 7.1: No Comprehensive Audit Trail Defined**

**Current State**: Document mentions "audit logging" in existing security.md but doesn't define:
- What events to log
- Log format/structure
- Log retention policy
- Log protection (integrity, access control)

**Required Fix: Comprehensive Audit Logging System**
```python
from enum import Enum
from datetime import datetime
from typing import Any, Optional
import json

class AuditEventType(Enum):
    """Types of audit events."""
    # Task lifecycle
    TASK_CREATED = "task.created"
    TASK_UPDATED = "task.updated"
    TASK_DELETED = "task.deleted"
    TASK_STARTED = "task.started"
    TASK_COMPLETED = "task.completed"
    TASK_CANCELLED = "task.cancelled"

    # Approval workflow
    PROPOSAL_RECEIVED = "proposal.received"
    PROPOSAL_APPROVED = "proposal.approved"
    PROPOSAL_REJECTED = "proposal.rejected"

    # Security events
    AUTH_FAILURE = "auth.failure"
    PERMISSION_DENIED = "permission.denied"
    SUSPICIOUS_INPUT = "suspicious.input"

    # Data access
    TASK_VIEWED = "task.viewed"
    SEARCH_EXECUTED = "search.executed"

class AuditEvent:
    """Structured audit event."""

    def __init__(
        self,
        event_type: AuditEventType,
        user_id: str,
        resource_type: str,
        resource_id: str,
        details: dict[str, Any],
        timestamp: Optional[datetime] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ):
        self.event_type = event_type
        self.user_id = user_id
        self.resource_type = resource_type  # "task", "proposal", etc.
        self.resource_id = resource_id
        self.details = details
        self.timestamp = timestamp or datetime.utcnow()
        self.ip_address = ip_address
        self.user_agent = user_agent

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON logging."""
        return {
            "event_type": self.event_type.value,
            "user_id": self.user_id,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "details": self.details,
            "timestamp": self.timestamp.isoformat() + "Z",
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
        }

class AuditLogger:
    """Comprehensive audit logging system."""

    def __init__(self, log_path: str):
        self.log_path = Path(log_path)

    async def log(self, event: AuditEvent):
        """
        Write audit event to log.

        CRITICAL: Audit logs must be:
        - Immutable (append-only)
        - Protected from deletion
        - Regularly backed up
        - Monitored for tampering
        """
        log_entry = json.dumps(event.to_dict())

        # ✅ Append to log file (immutable)
        with open(self.log_path, "a") as f:
            f.write(log_entry + "\n")

        # ✅ Sync to disk immediately
        f.flush()
        os.fsync(f.fileno())

    async def query_audit_trail(
        self,
        user_id: Optional[str] = None,
        event_type: Optional[AuditEventType] = None,
        resource_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> list[AuditEvent]:
        """Query audit trail for investigations."""
        # Implementation depends on storage (SQLite, Elasticsearch, etc.)
        pass

# Integration in TaskOrchestrator
class TaskOrchestrator:
    def __init__(self, audit_logger: AuditLogger):
        self.audit_logger = audit_logger

    async def create_task(
        self,
        user_id: str,
        description: str,
        ip_address: Optional[str] = None,
        **kwargs
    ) -> Task:
        """Create task with audit logging."""

        # Create task
        task = await self.task_store.create(
            created_by=user_id,
            description=description,
            **kwargs
        )

        # ✅ Log audit event
        await self.audit_logger.log(
            AuditEvent(
                event_type=AuditEventType.TASK_CREATED,
                user_id=user_id,
                resource_type="task",
                resource_id=task.id,
                details={
                    "title": task.title,
                    "repository": task.repository,
                    "priority": task.priority,
                },
                ip_address=ip_address,
            )
        )

        return task
```

**Audit Logging Requirements**:
1. **Immutable logs**: Append-only file storage
2. **Comprehensive coverage**: Log all task state changes
3. **Structured format**: JSON for easy querying
4. **Retention policy**: 1-7 years (compliance)
5. **Access control**: Only admins can view logs
6. **Tamper detection**: Cryptographic hashing/log signing
7. **Regular backup**: Separate from main database

---

## 8. Additional Security Recommendations

### 8.1 Rate Limiting ⚠️

**Gap**: No rate limiting defined for:
- Task creation API
- Webhook endpoints
- Search queries

**Recommendation**:
```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

# Apply rate limits
@app.post("/api/tasks")
@limiter.limit("10/minute")  # 10 tasks per minute per IP
async def create_task(request: Request):
    pass

@app.post("/api/webhooks/github")
@limiter.limit("100/minute")  # 100 webhooks per minute
async def github_webhook(request: Request):
    pass
```

### 8.2 Transport Security ⚠️

**Gap**: Webhook URLs shown as HTTPS but TLS configuration not specified.

**Requirement**:
1. Enforce TLS 1.2+ for all webhook endpoints
2. Certificate pinning for GitHub/GitLab webhooks
3. Document TLS setup in deployment guide

### 8.3 Secret Rotation ⚠️

**Gap**: Webhook secrets and database keys have no rotation mechanism.

**Recommendation**:
```yaml
# Add to deployment guide
security:
  webhook_secret_rotation:
    enabled: true
    rotation_period_days: 90
    grace_period_days: 7
```

### 8.4 Dependency Scanning ✅

**Positive**: Document mentions `pip-audit` in security.md.

**Recommendation**: Add to CI/CD pipeline:
```yaml
# .github/workflows/security.yml
name: Security Scan
on: [push, pull_request]

steps:
  - name: Run dependency audit
    run: pip-audit

  - name: Run bandit security linter
    run: bandit -r mahavishnu/

  - name: Run safety check
    run: safety check
```

---

## 9. Critical Security Fixes Summary

### Must Fix Before Production (P0)

| ID | Vulnerability | Severity | Effort |
|----|--------------|----------|--------|
| 1.1 | Webhook signature validation | **CRITICAL** | 2 days |
| 1.2 | Approval authorization model | **CRITICAL** | 1 day |
| 2.1 | NLP input sanitization | **CRITICAL** | 3 days |
| 2.2 | SQL injection via search | **CRITICAL** | 1 day |
| 3.1 | Secrets scanning in tasks | **HIGH** | 1 day |
| 4.1 | Access control model | **CRITICAL** | 3 days |
| 7.1 | Comprehensive audit logging | **CRITICAL** | 3 days |

**Total Effort**: ~14 developer days

### Should Fix (P1)

| ID | Vulnerability | Severity | Effort |
|----|--------------|----------|--------|
| 1.3 | Approval quorum process | Medium | 2 days |
| 6.1 | PathValidator integration | Medium | 1 day |
| 8.1 | Rate limiting | High | 1 day |
| 8.2 | Transport security docs | Medium | 1 day |
| 8.3 | Secret rotation | Low | 2 days |

**Total Effort**: ~7 developer days

---

## 10. Security Testing Requirements

### Required Security Tests

```python
# tests/integration/test_security.py

class TestTaskSecurity:
    """Security test suite for task orchestration."""

    async def test_sql_injection_in_task_title(self):
        """Test that SQL injection attempts are blocked."""
        malicious_title = "'; DROP TABLE tasks; --"

        with pytest.raises(ValueError):
            await task_orchestrator.create_task(title=malicious_title)

    async def test_path_traversal_in_repository(self):
        """Test that path traversal attempts are blocked."""
        malicious_repo = "../../../etc/passwd"

        with pytest.raises(PathValidationError):
            await task_orchestrator.create_task(
                title="Test",
                repository=malicious_repo
            )

    async def test_secrets_detection_in_description(self):
        """Test that secrets in descriptions are blocked."""
        description_with_api_key = """
        Connect to API using key: sk_1234567890abcdefghijklmnop
        """

        with pytest.raises(ValueError, match="secrets"):
            await task_orchestrator.create_task(
                title="Test",
                description=description_with_api_key
            )

    async def test_unauthorized_approval(self):
        """Test that unauthorized users cannot approve proposals."""
        unauthorized_user = "attacker"

        with pytest.raises(PermissionError):
            await sync_handler.approve_task_proposal(
                proposal_id="test-proposal",
                approver_user_id=unauthorized_user
            )

    async def test_webhook_signature_validation(self):
        """Test that invalid webhook signatures are rejected."""
        invalid_payload = b"malicious payload"
        invalid_signature = "invalid-sig"

        response = await client.post(
            "/api/webhooks/github",
            data=invalid_payload,
            headers={"X-Hub-Signature-256": invalid_signature}
        )

        assert response.status_code == 401
```

---

## 11. Compliance Considerations

### GDPR/Data Privacy

- ✅ Audit logging supports data subject access requests (DSAR)
- ⚠️ Need data retention policy for task descriptions
- ⚠️ Need right-to-deletion implementation

### SOC 2 / ISO 27001

- ❌ Access control model not defined (required)
- ❌ Audit logging not comprehensive (required)
- ⚠️ Change management process not documented
- ⚠️ Incident response procedure not referenced

---

## 12. Final Recommendations

### Immediate Actions (Before Phase 1)

1. **Create Security Module** (`mahavishnu/core/task_security.py`):
   - InputSanitizer class
   - TaskAccessControl class
   - TaskAuditLogger class
   - WebhookValidator class

2. **Update Master Plan**:
   - Add "Security Implementation" section
   - Define authentication/authorization model
   - Specify audit logging requirements
   - Add security testing to Phase 1 deliverables

3. **Security Hardening**:
   - Enable webhook signature validation
   - Implement rate limiting
   - Add comprehensive audit logging
   - Integrate secrets scanner

### Phase 1 Security Deliverables

Add to Phase 1 (lines 1524-1551):

```markdown
**Security Deliverables** (NEW):
1. Input sanitization layer (TaskInputSanitizer)
2. Access control model (TaskAccessControl)
3. Audit logging system (TaskAuditLogger)
4. Webhook signature validation
5. Security test suite (injection, authorization, audit)
6. Security documentation (threat model, mitigation strategies)

**Security Tasks** (NEW):
- [ ] Create `mahavishnu/core/task_security.py`
- [ ] Implement input sanitization for all user inputs
- [ ] Implement webhook signature validation
- [ ] Create access control model (RBAC)
- [ ] Implement audit logging
- [ ] Add security tests (SQL injection, path traversal, etc.)
- [ ] Document threat model and mitigations
- [ ] Security review with Power Trio
```

---

## Conclusion

The Task Orchestration Master Plan has **solid architectural foundations** but requires **critical security enhancements** before production deployment. The existing security infrastructure (validators, secrets scanner) provides a good starting point.

### Decision: **APPROVE WITH CHANGES** ✅⚠️

**Required Changes**:
1. Add comprehensive input sanitization (CRITICAL)
2. Implement access control model (CRITICAL)
3. Add audit logging system (CRITICAL)
4. Validate webhook signatures (CRITICAL)
5. Integrate secrets scanner in task creation (HIGH)
6. Add security test suite (HIGH)

**Estimated Effort**: 14-21 developer days

**Risk Level**: **HIGH** without security fixes, **LOW** with fixes implemented.

**Recommendation**: Complete P0 security fixes before Phase 2 (semantic search integration). Security fundamentals must be in place before adding advanced features.

---

## Appendix: Security Checklist

### Webhook Security
- [ ] Signature validation (GitHub/GitLab)
- [ ] Replay attack prevention
- [ ] Rate limiting
- [ ] IP whitelisting (optional)
- [ ] TLS enforcement

### Input Validation
- [ ] Task title sanitization
- [ ] Description sanitization (HTML/XSS)
- [ ] Repository name whitelist validation
- [ ] Deadline validation (date range)
- [ ] Priority enum validation

### SQL Injection Protection
- [ ] All queries parameterized
- [ ] ORM/SQLAlchemy usage
- [ ] FTS query sanitization
- [ ] Unit tests for injection attempts

### Access Control
- [ ] User authentication mechanism
- [ ] Role-based permissions (RBAC)
- [ ] Permission checks on all operations
- [ ] Audit trail for permission denials

### Audit Logging
- [ ] Log all task state changes
- [ ] Log all approval decisions
- [ ] Log authentication failures
- [ ] Immutable log storage
- [ ] Log retention policy
- [ ] Log backup strategy

### Data Privacy
- [ ] Secrets scanning on task creation
- [ ] Credential redaction
- [ ] Data retention policy
- [ ] Right-to-deletion implementation

### Compliance
- [ ] GDPR data subject access requests
- [ ] SOC 2 access control documentation
- [ ] Incident response procedures
- [ ] Security training for developers

---

**Review Complete**
**Reviewer**: Claude Sonnet 4.5 (Security Architecture Specialist)
**Date**: 2026-02-18
**Next Review**: After P0 security fixes implemented

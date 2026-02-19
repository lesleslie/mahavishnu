"""Task-related Pydantic models with comprehensive validation and sanitization.

This module provides secure input validation for task operations:

- TaskCreateRequest: Validates and sanitizes task creation inputs
- TaskUpdateRequest: Validates partial task updates
- FTSSearchQuery: Sanitizes full-text search queries

Security Features:
- Null byte removal (prevents null byte injection)
- Length validation (prevents buffer overflow attacks)
- Pattern validation (prevents injection attacks)
- Control character removal (prevents log injection)
- SQL character sanitization for FTS queries

Usage:
    from mahavishnu.core.task_models import TaskCreateRequest, FTSSearchQuery

    # Create a task
    request = TaskCreateRequest(
        title="Fix authentication bug",
        repository="session-buddy",
        priority="high",
    )

    # Search tasks
    search = FTSSearchQuery(query="authentication issues")
"""

import re
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class TaskCreateRequest(BaseModel):
    """Task creation request with comprehensive validation.

    This model validates and sanitizes all task creation inputs:

    1. **Title Validation**:
       - Min 1, max 200 characters
       - Null bytes removed
       - Control characters removed (except newline, tab)
       - Leading/trailing whitespace stripped

    2. **Description Validation**:
       - Max 5000 characters
       - Null bytes removed
       - Leading/trailing whitespace stripped

    3. **Repository Validation**:
       - Must match pattern: ^[a-zA-Z0-9_-]+$
       - Prevents path traversal via repository name

    4. **Priority Validation**:
       - Must be one of: low, medium, high, critical

    5. **Deadline Validation**:
       - Must be valid ISO 8601 format
       - Must be in the future

    Examples:
        >>> request = TaskCreateRequest(
        ...     title="Fix authentication bug",
        ...     repository="session-buddy",
        ...     priority="high",
        ... )
        >>> request.title
        'Fix authentication bug'

        >>> # Invalid repository name (path traversal attempt)
        >>> TaskCreateRequest(title="Test", repository="../../../etc")
        ValidationError: Repository name invalid
    """

    title: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Task title (1-200 characters)",
    )
    description: str | None = Field(
        None,
        max_length=5000,
        description="Task description (max 5000 characters)",
    )
    repository: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Repository name (alphanumeric, dash, underscore only)",
    )
    priority: Literal["low", "medium", "high", "critical"] = Field(
        default="medium",
        description="Task priority level",
    )
    deadline: str | None = Field(
        None,
        description="Task deadline in ISO 8601 format",
    )
    tags: list[str] | None = Field(
        None,
        max_length=10,
        description="Task tags (max 10)",
    )
    metadata: dict[str, Any] | None = Field(
        None,
        description="Additional task metadata",
    )

    @field_validator("title")
    @classmethod
    def sanitize_title(cls, v: str) -> str:
        """Sanitize task title.

        Removes potentially dangerous characters:
        - Null bytes (\\x00)
        - Control characters (except newline, tab)
        - Leading/trailing whitespace

        Args:
            v: Original title string

        Returns:
            Sanitized title string

        Raises:
            ValueError: If title is empty after sanitization or too long
        """
        if not v:
            raise ValueError("Title cannot be empty")

        # Remove null bytes (null byte injection prevention)
        v = v.replace("\x00", "")

        # Remove control characters (except newline and tab)
        # Control characters: ASCII 0-31 and 127 (DEL)
        v = "".join(
            char for char in v
            if char in ("\n", "\t") or not (ord(char) < 32 or ord(char) == 127)
        )

        # Strip leading/trailing whitespace
        v = v.strip()

        # Validate length after sanitization
        if not v:
            raise ValueError("Title cannot be empty after sanitization")

        if len(v) > 200:
            raise ValueError(f"Title too long: {len(v)} characters (max 200)")

        return v

    @field_validator("description")
    @classmethod
    def sanitize_description(cls, v: str | None) -> str | None:
        """Sanitize task description.

        Removes potentially dangerous characters:
        - Null bytes (\\x00)
        - Leading/trailing whitespace

        Args:
            v: Original description string

        Returns:
            Sanitized description string or None
        """
        if v is None:
            return None

        # Remove null bytes
        v = v.replace("\x00", "")

        # Strip leading/trailing whitespace
        v = v.strip()

        # Return None if empty after sanitization
        if not v:
            return None

        # Validate length
        if len(v) > 5000:
            raise ValueError(f"Description too long: {len(v)} characters (max 5000)")

        return v

    @field_validator("repository")
    @classmethod
    def validate_repository(cls, v: str) -> str:
        """Validate repository name against whitelist pattern.

        Only allows:
        - Alphanumeric characters (a-z, A-Z, 0-9)
        - Hyphens (-)
        - Underscores (_)

        This prevents:
        - Path traversal (../)
        - Command injection (special characters)
        - URL injection (://)

        Args:
            v: Repository name string

        Returns:
            Validated repository name

        Raises:
            ValueError: If repository name doesn't match pattern
        """
        if not v:
            raise ValueError("Repository name cannot be empty")

        # Whitelist pattern: alphanumeric, dash, underscore only
        pattern = r"^[a-zA-Z0-9_-]+$"

        if not re.match(pattern, v):
            raise ValueError(
                f"Repository name invalid. Must contain only letters, numbers, "
                f"hyphens (-), and underscores (_). Got: '{v}'"
            )

        # Additional checks for edge cases
        if v.startswith("-") or v.startswith("_"):
            raise ValueError(
                f"Repository name cannot start with hyphen or underscore: '{v}'"
            )

        if len(v) > 100:
            raise ValueError(f"Repository name too long: {len(v)} characters (max 100)")

        return v

    @field_validator("deadline")
    @classmethod
    def validate_deadline(cls, v: str | None) -> str | None:
        """Validate deadline is a future date in ISO 8601 format.

        Accepts formats:
        - 2026-02-18T10:00:00Z
        - 2026-02-18T10:00:00+00:00
        - 2026-02-18 10:00:00

        Args:
            v: Deadline string in ISO 8601 format

        Returns:
            Validated deadline string

        Raises:
            ValueError: If deadline format is invalid or in the past
        """
        if v is None:
            return None

        try:
            # Parse ISO 8601 timestamp
            deadline = datetime.fromisoformat(v.replace("Z", "+00:00"))

            # Ensure timezone-aware (assume UTC if naive)
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)

            # Check if deadline is in the future
            now = datetime.now(timezone.utc)
            if deadline <= now:
                raise ValueError(
                    f"Deadline must be in the future. Got: {deadline.isoformat()}, "
                    f"Current time: {now.isoformat()}"
                )

            return v

        except ValueError as e:
            if "Deadline must be in the future" in str(e):
                raise
            raise ValueError(
                f"Invalid deadline format. Use ISO 8601 (e.g., 2026-02-18T10:00:00Z). "
                f"Error: {e}"
            ) from e

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str] | None) -> list[str] | None:
        """Validate and sanitize task tags.

        Each tag must:
        - Be 1-50 characters
        - Contain only alphanumeric, hyphen, or underscore
        - Not start with hyphen or underscore

        Args:
            v: List of tag strings

        Returns:
            Validated and deduplicated list of tags

        Raises:
            ValueError: If any tag is invalid
        """
        if v is None:
            return None

        if len(v) > 10:
            raise ValueError(f"Too many tags: {len(v)} (max 10)")

        validated_tags = []
        seen_tags = set()
        tag_pattern = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")

        for tag in v:
            # Sanitize tag
            tag = tag.strip().lower()

            if not tag:
                continue

            # Check length
            if len(tag) > 50:
                raise ValueError(f"Tag too long: '{tag[:20]}...' (max 50 characters)")

            # Check pattern
            if not tag_pattern.match(tag):
                raise ValueError(
                    f"Invalid tag: '{tag}'. Must start with alphanumeric and "
                    f"contain only letters, numbers, hyphens, and underscores."
                )

            # Skip duplicates (case-insensitive)
            if tag in seen_tags:
                continue

            seen_tags.add(tag)
            validated_tags.append(tag)

        return validated_tags if validated_tags else None


class TaskUpdateRequest(BaseModel):
    """Task update request with partial validation.

    All fields are optional to support partial updates. Each field
    is validated using the same rules as TaskCreateRequest.

    Examples:
        >>> update = TaskUpdateRequest(priority="critical")
        >>> update.priority
        'critical'
    """

    title: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=5000)
    priority: Literal["low", "medium", "high", "critical"] | None = None
    status: Literal["pending", "in_progress", "blocked", "completed", "cancelled"] | None = None
    deadline: str | None = None
    tags: list[str] | None = Field(None, max_length=10)

    @field_validator("title")
    @classmethod
    def sanitize_title(cls, v: str | None) -> str | None:
        """Sanitize title (same as TaskCreateRequest)."""
        if v is None:
            return None
        return TaskCreateRequest.sanitize_title(v)

    @field_validator("description")
    @classmethod
    def sanitize_description(cls, v: str | None) -> str | None:
        """Sanitize description (same as TaskCreateRequest)."""
        return TaskCreateRequest.sanitize_description(v)

    @field_validator("deadline")
    @classmethod
    def validate_deadline(cls, v: str | None) -> str | None:
        """Validate deadline (allows clearing deadline with empty string)."""
        if v is None or v == "":
            return None
        return TaskCreateRequest.validate_deadline(v)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str] | None) -> list[str] | None:
        """Validate tags (same as TaskCreateRequest)."""
        return TaskCreateRequest.validate_tags(v)


class FTSSearchQuery(BaseModel):
    """Full-text search query with SQL injection prevention.

    This model sanitizes search queries to prevent SQL injection
    when using PostgreSQL full-text search (to_tsquery).

    Security Features:
    - Null byte removal
    - Length validation (max 500 characters)
    - Dangerous SQL character detection
    - Query normalization for FTS

    Note: PostgreSQL's to_tsquery() handles most SQL injection
    prevention, but this adds defense-in-depth.

    Examples:
        >>> query = FTSSearchQuery(query="authentication bug")
        >>> query.query
        'authentication bug'

        >>> # SQL injection attempt (rejected)
        >>> FTSSearchQuery(query="'; DROP TABLE tasks; --")
        ValidationError: Query contains dangerous character
    """

    query: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Search query (1-500 characters)",
    )
    limit: int = Field(
        default=50,
        ge=1,
        le=1000,
        description="Maximum number of results",
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Result offset for pagination",
    )

    @field_validator("query")
    @classmethod
    def sanitize_query(cls, v: str) -> str:
        """Sanitize FTS query to prevent SQL injection.

        Removes:
        - Null bytes
        - Dangerous SQL characters (--, /*, */)
        - Excessive whitespace

        Args:
            v: Original query string

        Returns:
            Sanitized query string

        Raises:
            ValueError: If query contains dangerous characters or is empty
        """
        if not v:
            raise ValueError("Search query cannot be empty")

        # Remove null bytes
        v = v.replace("\x00", "")

        # Strip leading/trailing whitespace
        v = v.strip()

        if not v:
            raise ValueError("Search query cannot be empty after sanitization")

        # Check length
        if len(v) > 500:
            raise ValueError(f"Query too long: {len(v)} characters (max 500)")

        # Defense in depth: detect dangerous SQL characters
        # Note: PostgreSQL to_tsquery() handles most of this, but we add extra protection
        dangerous_patterns = [
            ("--", "SQL comment"),
            ("/*", "SQL comment start"),
            ("*/", "SQL comment end"),
            (";", "SQL statement separator"),
            ("xp_", "Extended stored procedure prefix"),
            ("exec(", "function call"),
            ("execute(", "function call"),
        ]

        for pattern, description in dangerous_patterns:
            if pattern.lower() in v.lower():
                raise ValueError(
                    f"Query contains dangerous pattern: {description}. "
                    f"Please use only alphanumeric characters and spaces."
                )

        # Normalize whitespace (multiple spaces -> single space)
        v = " ".join(v.split())

        return v

    def to_tsquery_format(self) -> str:
        """Convert query to PostgreSQL to_tsquery format.

        This method:
        - Splits query into terms
        - Joins with & (AND operator)
        - Escapes special FTS characters

        Returns:
            Query string suitable for to_tsquery()
        """
        # Split into terms
        terms = self.query.split()

        # Escape special characters for to_tsquery
        # to_tsquery special chars: & | ! ( ) : * < >
        escaped_terms = []
        for term in terms:
            # Remove special FTS characters
            escaped = re.sub(r"[&|!():*<>]", "", term)
            if escaped:
                escaped_terms.append(escaped)

        # Join with & (AND)
        return " & ".join(escaped_terms)


class TaskFilter(BaseModel):
    """Task filter for list/search operations.

    Provides validated filter parameters for task queries.

    Examples:
        >>> filter = TaskFilter(status="in_progress", priority="high")
        >>> filter.status
        'in_progress'
    """

    status: Literal["pending", "in_progress", "blocked", "completed", "cancelled"] | None = None
    priority: Literal["low", "medium", "high", "critical"] | None = None
    repository: str | None = Field(None, max_length=100)
    assigned_to: str | None = Field(None, max_length=100)
    created_after: str | None = None
    created_before: str | None = None
    has_deadline: bool | None = None
    limit: int = Field(default=50, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)

    @field_validator("repository")
    @classmethod
    def validate_repository(cls, v: str | None) -> str | None:
        """Validate repository filter (same rules as TaskCreateRequest)."""
        if v is None:
            return None
        return TaskCreateRequest.validate_repository(v)

    @field_validator("created_after", "created_before")
    @classmethod
    def validate_date_filter(cls, v: str | None) -> str | None:
        """Validate date filter is valid ISO 8601 format."""
        if v is None:
            return None

        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
            return v
        except ValueError as e:
            raise ValueError(
                f"Invalid date format. Use ISO 8601 (e.g., 2026-02-18T00:00:00Z). "
                f"Error: {e}"
            ) from e

    @model_validator(mode="after")
    def validate_date_range(self) -> "TaskFilter":
        """Validate created_before is after created_after."""
        if self.created_after and self.created_before:
            after = datetime.fromisoformat(self.created_after.replace("Z", "+00:00"))
            before = datetime.fromisoformat(self.created_before.replace("Z", "+00:00"))

            if after > before:
                raise ValueError(
                    f"created_after ({self.created_after}) must be before "
                    f"created_before ({self.created_before})"
                )

        return self


__all__ = [
    "TaskCreateRequest",
    "TaskUpdateRequest",
    "FTSSearchQuery",
    "TaskFilter",
]

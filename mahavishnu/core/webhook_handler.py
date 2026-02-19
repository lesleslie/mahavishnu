"""Webhook Handler for Mahavishnu.

Handles webhooks from GitHub and GitLab:
- Signature/token verification
- Event parsing and classification
- Event handling with idempotency
- Audit logging

Usage:
    from mahavishnu.core.webhook_handler import WebhookHandler

    handler = WebhookHandler(task_store, github_secret="secret")

    # Handle GitHub webhook
    result = await handler.handle_github_webhook(
        payload=request_body,
        signature=request.headers["X-Hub-Signature-256"],
        event_type=request.headers["X-GitHub-Event"],
    )
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from typing import Any

from mahavishnu.core.task_store import Task, TaskStatus, TaskPriority, TaskStore

logger = logging.getLogger(__name__)


class WebhookSource(str, Enum):
    """Source of webhook events."""

    GITHUB = "github"
    GITLAB = "gitlab"


class EventType(str, Enum):
    """Types of webhook events."""

    PUSH = "push"
    ISSUE_OPENED = "issue_opened"
    ISSUE_CLOSED = "issue_closed"
    ISSUE_UPDATED = "issue_updated"
    PULL_REQUEST = "pull_request"
    MERGE_REQUEST = "merge_request"
    UNKNOWN = "unknown"


@dataclass
class WebhookEvent:
    """Represents a parsed webhook event.

    Attributes:
        event_id: Unique identifier for this event
        source: Where the event came from
        event_type: Type of event
        repository: Repository identifier
        payload: Raw event data
        received_at: When the event was received
        sender: Who triggered the event
    """

    event_id: str
    source: WebhookSource
    event_type: EventType
    repository: str
    payload: dict[str, Any]
    received_at: datetime
    sender: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "event_id": self.event_id,
            "source": self.source.value,
            "event_type": self.event_type.value,
            "repository": self.repository,
            "received_at": self.received_at.isoformat(),
            "sender": self.sender,
        }


@dataclass
class WebhookResult:
    """Result of handling a webhook.

    Attributes:
        success: Whether handling was successful
        message: Human-readable message
        actions_taken: List of actions performed
        error: Error message if failed
        event_id: ID of the processed event
    """

    success: bool
    message: str = ""
    actions_taken: list[str] = field(default_factory=list)
    error: str | None = None
    event_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "success": self.success,
            "message": self.message,
            "actions_taken": self.actions_taken,
            "error": self.error,
            "event_id": self.event_id,
        }


class WebhookHandler:
    """Handles webhooks from GitHub and GitLab.

    Features:
    - Signature/token verification
    - Event parsing and classification
    - Idempotent event handling
    - Audit logging of all events

    Example:
        handler = WebhookHandler(
            task_store,
            github_secret="webhook-secret",
            gitlab_token="gitlab-token",
        )

        # Handle GitHub push event
        result = await handler.handle_github_webhook(
            payload=request_body,
            signature="sha256=...",
            event_type="push",
        )

        if result.success:
            print(f"Processed: {result.actions_taken}")
    """

    # Maximum events to keep in processed cache
    MAX_PROCESSED_EVENTS = 1000

    def __init__(
        self,
        task_store: TaskStore,
        github_secret: str | None = None,
        gitlab_token: str | None = None,
    ) -> None:
        """Initialize the webhook handler.

        Args:
            task_store: TaskStore for creating tasks
            github_secret: Secret for GitHub signature verification
            gitlab_token: Token for GitLab webhook verification
        """
        self.task_store = task_store
        self._github_secret = github_secret
        self._gitlab_token = gitlab_token
        self._processed_events: OrderedDict[str, datetime] = OrderedDict()

    def verify_github_signature(self, payload: bytes, signature: str) -> bool:
        """Verify GitHub webhook signature.

        Args:
            payload: Raw request body
            signature: X-Hub-Signature-256 header value

        Returns:
            True if signature is valid
        """
        if not self._github_secret:
            return True  # No verification configured

        if not signature.startswith("sha256="):
            return False

        expected = signature[7:]  # Remove 'sha256=' prefix
        computed = hmac.new(
            self._github_secret.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected, computed)

    def verify_gitlab_token(self, token: str | None) -> bool:
        """Verify GitLab webhook token.

        Args:
            token: X-Gitlab-Token header value

        Returns:
            True if token is valid
        """
        if not self._gitlab_token:
            return True  # No verification configured

        return token == self._gitlab_token

    def parse_github_event(
        self,
        event_type: str,
        payload: dict[str, Any],
    ) -> WebhookEvent | None:
        """Parse a GitHub webhook event.

        Args:
            event_type: X-GitHub-Event header value
            payload: Parsed JSON payload

        Returns:
            WebhookEvent if parseable, None otherwise
        """
        repo_info = payload.get("repository", {})
        repository = repo_info.get("full_name", "")

        # Generate event ID from delivery or create one
        event_id = str(payload.get("hook_id", uuid.uuid4().hex))

        # Get sender
        sender = payload.get("sender", {}).get("login")

        # Classify event type
        classified_type = self.classify_github_event(event_type, payload)

        return WebhookEvent(
            event_id=event_id,
            source=WebhookSource.GITHUB,
            event_type=classified_type,
            repository=repository,
            payload=payload,
            received_at=datetime.now(UTC),
            sender=sender,
        )

    def parse_gitlab_event(self, payload: dict[str, Any]) -> WebhookEvent | None:
        """Parse a GitLab webhook event.

        Args:
            payload: Parsed JSON payload

        Returns:
            WebhookEvent if parseable, None otherwise
        """
        project = payload.get("project", {})
        repository = project.get("path_with_namespace", "")

        # Generate event ID
        event_id = str(payload.get("object_id", uuid.uuid4().hex))

        # Get sender
        sender = payload.get("user_username", payload.get("user_name"))

        # Classify event type
        object_kind = payload.get("object_kind", "")
        classified_type = self.classify_gitlab_event(object_kind, payload)

        return WebhookEvent(
            event_id=event_id,
            source=WebhookSource.GITLAB,
            event_type=classified_type,
            repository=repository,
            payload=payload,
            received_at=datetime.now(UTC),
            sender=sender,
        )

    def classify_github_event(
        self,
        event_type: str,
        payload: dict[str, Any],
    ) -> EventType:
        """Classify GitHub event type.

        Args:
            event_type: X-GitHub-Event header value
            payload: Event payload

        Returns:
            EventType enum value
        """
        if event_type == "push":
            return EventType.PUSH
        elif event_type == "issues":
            action = payload.get("action", "")
            if action == "opened":
                return EventType.ISSUE_OPENED
            elif action == "closed":
                return EventType.ISSUE_CLOSED
            else:
                return EventType.ISSUE_UPDATED
        elif event_type == "pull_request":
            return EventType.PULL_REQUEST
        else:
            return EventType.UNKNOWN

    def classify_gitlab_event(
        self,
        object_kind: str,
        payload: dict[str, Any],
    ) -> EventType:
        """Classify GitLab event type.

        Args:
            object_kind: GitLab object_kind field
            payload: Event payload

        Returns:
            EventType enum value
        """
        if object_kind == "push":
            return EventType.PUSH
        elif object_kind == "issue":
            action = payload.get("action", "")
            if action == "open":
                return EventType.ISSUE_OPENED
            elif action == "close":
                return EventType.ISSUE_CLOSED
            else:
                return EventType.ISSUE_UPDATED
        elif object_kind == "merge_request":
            return EventType.MERGE_REQUEST
        else:
            return EventType.UNKNOWN

    async def handle_event(self, event: WebhookEvent) -> WebhookResult:
        """Handle a webhook event.

        Args:
            event: The event to handle

        Returns:
            WebhookResult with handling outcome
        """
        # Check for duplicate (idempotency)
        event_key = f"{event.source.value}:{event.event_id}"
        if event_key in self._processed_events:
            logger.info(f"Skipping duplicate event: {event_key}")
            return WebhookResult(
                success=True,
                message="Event already processed (duplicate)",
                event_id=event.event_id,
            )

        # Handle based on event type
        actions: list[str] = []

        try:
            if event.event_type == EventType.PUSH:
                actions.extend(await self._handle_push(event))
            elif event.event_type == EventType.ISSUE_OPENED:
                actions.extend(await self._handle_issue_opened(event))
            elif event.event_type == EventType.ISSUE_CLOSED:
                actions.extend(await self._handle_issue_closed(event))
            elif event.event_type == EventType.PULL_REQUEST:
                actions.extend(await self._handle_pull_request(event))
            else:
                actions.append(f"Unsupported event type: {event.event_type.value}")

            # Mark as processed
            self._processed_events[event_key] = datetime.now(UTC)
            self._cleanup_processed_events()

            logger.info(
                f"Processed {event.source.value} {event.event_type.value} event: "
                f"{event.event_id}"
            )

            return WebhookResult(
                success=True,
                message=f"Event processed successfully",
                actions_taken=actions,
                event_id=event.event_id,
            )

        except Exception as e:
            logger.error(f"Failed to handle event {event.event_id}: {e}")
            return WebhookResult(
                success=False,
                message="Event handling failed",
                error=str(e),
                event_id=event.event_id,
            )

    async def handle_github_webhook(
        self,
        payload: bytes,
        signature: str,
        event_type: str,
    ) -> WebhookResult:
        """Handle a GitHub webhook request.

        Args:
            payload: Raw request body
            signature: X-Hub-Signature-256 header
            event_type: X-GitHub-Event header

        Returns:
            WebhookResult with handling outcome
        """
        # Verify signature
        if not self.verify_github_signature(payload, signature):
            return WebhookResult(
                success=False,
                message="Signature verification failed",
                error="Invalid webhook signature",
            )

        # Parse payload
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as e:
            return WebhookResult(
                success=False,
                message="Invalid JSON payload",
                error=str(e),
            )

        # Parse event
        event = self.parse_github_event(event_type, data)
        if not event:
            return WebhookResult(
                success=False,
                message="Failed to parse event",
                error="Could not parse webhook event",
            )

        return await self.handle_event(event)

    async def handle_gitlab_webhook(
        self,
        payload: bytes,
        token: str | None = None,
    ) -> WebhookResult:
        """Handle a GitLab webhook request.

        Args:
            payload: Raw request body
            token: X-Gitlab-Token header

        Returns:
            WebhookResult with handling outcome
        """
        # Verify token
        if not self.verify_gitlab_token(token):
            return WebhookResult(
                success=False,
                message="Token verification failed",
                error="Invalid webhook token",
            )

        # Parse payload
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as e:
            return WebhookResult(
                success=False,
                message="Invalid JSON payload",
                error=str(e),
            )

        # Parse event
        event = self.parse_gitlab_event(data)
        if not event:
            return WebhookResult(
                success=False,
                message="Failed to parse event",
                error="Could not parse webhook event",
            )

        return await self.handle_event(event)

    async def _handle_push(self, event: WebhookEvent) -> list[str]:
        """Handle a push event."""
        actions: list[str] = []

        commits = event.payload.get("commits", [])
        ref = event.payload.get("ref", "")

        actions.append(f"Received push to {ref} with {len(commits)} commits")

        return actions

    async def _handle_issue_opened(self, event: WebhookEvent) -> list[str]:
        """Handle an issue opened event."""
        actions: list[str] = []

        issue_data = event.payload.get("issue", event.payload.get("object_attributes", {}))

        if issue_data:
            actions.append(f"Issue #{issue_data.get('number', issue_data.get('iid', '?'))} opened: {issue_data.get('title', '')}")

        return actions

    async def _handle_issue_closed(self, event: WebhookEvent) -> list[str]:
        """Handle an issue closed event."""
        actions: list[str] = []

        issue_data = event.payload.get("issue", event.payload.get("object_attributes", {}))

        if issue_data:
            actions.append(f"Issue #{issue_data.get('number', issue_data.get('iid', '?'))} closed")

        return actions

    async def _handle_pull_request(self, event: WebhookEvent) -> list[str]:
        """Handle a pull request event."""
        actions: list[str] = []

        pr_data = event.payload.get("pull_request", event.payload.get("object_attributes", {}))

        if pr_data:
            actions.append(f"PR #{pr_data.get('number', pr_data.get('iid', '?'))}: {pr_data.get('title', '')}")

        return actions

    def extract_repository_info(
        self,
        payload: dict[str, Any],
        source: WebhookSource,
    ) -> dict[str, Any]:
        """Extract repository information from payload.

        Args:
            payload: Event payload
            source: Webhook source

        Returns:
            Dictionary with repository info
        """
        if source == WebhookSource.GITHUB:
            repo = payload.get("repository", {})
            return {
                "id": repo.get("id"),
                "name": repo.get("name"),
                "full_name": repo.get("full_name"),
                "url": repo.get("html_url"),
                "private": repo.get("private", False),
            }
        else:  # GitLab
            project = payload.get("project", {})
            return {
                "id": project.get("id"),
                "name": project.get("name"),
                "full_name": project.get("path_with_namespace"),
                "url": project.get("web_url"),
                "private": project.get("visibility") != "public",
            }

    def _cleanup_processed_events(self) -> None:
        """Remove old events from the processed cache."""
        while len(self._processed_events) > self.MAX_PROCESSED_EVENTS:
            self._processed_events.popitem(last=False)


__all__ = [
    "WebhookHandler",
    "WebhookEvent",
    "WebhookResult",
    "WebhookSource",
    "EventType",
]

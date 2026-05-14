"""Tests for WebhookHandler - Handle GitHub/GitLab webhooks."""

from datetime import UTC, datetime
import hashlib
import hmac
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.core.webhook_handler import (
    EventType,
    WebhookEvent,
    WebhookHandler,
    WebhookResult,
    WebhookSource,
)


@pytest.fixture
def mock_task_store() -> AsyncMock:
    """Create a mock TaskStore."""
    return AsyncMock()


@pytest.fixture
def sample_github_push_payload() -> dict[str, Any]:
    """Create a sample GitHub push webhook payload."""
    return {
        "ref": "refs/heads/main",
        "before": "abc123",
        "after": "def456",
        "repository": {
            "id": 12345,
            "name": "test-repo",
            "full_name": "owner/test-repo",
            "html_url": "https://github.com/owner/test-repo",
        },
        "pusher": {
            "name": "developer",
            "email": "developer@example.com",
        },
        "commits": [
            {
                "id": "def456",
                "message": "Fix authentication bug",
                "timestamp": "2026-02-19T10:00:00Z",
                "author": {"name": "developer", "email": "developer@example.com"},
            }
        ],
    }


@pytest.fixture
def sample_github_issue_payload() -> dict[str, Any]:
    """Create a sample GitHub issue webhook payload."""
    return {
        "action": "opened",
        "issue": {
            "id": 12345,
            "number": 42,
            "title": "New bug report",
            "body": "Description of the bug",
            "state": "open",
            "labels": [{"name": "bug"}],
            "html_url": "https://github.com/owner/test-repo/issues/42",
        },
        "repository": {
            "id": 12345,
            "name": "test-repo",
            "full_name": "owner/test-repo",
        },
    }


@pytest.fixture
def sample_gitlab_push_payload() -> dict[str, Any]:
    """Create a sample GitLab push webhook payload."""
    return {
        "object_kind": "push",
        "ref": "refs/heads/main",
        "before": "abc123",
        "after": "def456",
        "project": {
            "id": 12345,
            "name": "test-repo",
            "path_with_namespace": "owner/test-repo",
            "web_url": "https://gitlab.com/owner/test-repo",
        },
        "user_name": "developer",
        "commits": [
            {
                "id": "def456",
                "message": "Add feature",
                "timestamp": "2026-02-19T10:00:00Z",
                "author": {"name": "developer", "email": "developer@example.com"},
            }
        ],
    }


class TestWebhookSource:
    """Tests for WebhookSource enum."""

    def test_webhook_sources(self) -> None:
        """Test available webhook sources."""
        assert WebhookSource.GITHUB.value == "github"
        assert WebhookSource.GITLAB.value == "gitlab"


class TestEventType:
    """Tests for EventType enum."""

    def test_event_types(self) -> None:
        """Test available event types."""
        assert EventType.PUSH.value == "push"
        assert EventType.ISSUE_OPENED.value == "issue_opened"
        assert EventType.ISSUE_CLOSED.value == "issue_closed"
        assert EventType.PULL_REQUEST.value == "pull_request"


class TestWebhookEvent:
    """Tests for WebhookEvent dataclass."""

    def test_create_webhook_event(self) -> None:
        """Create a webhook event."""
        event = WebhookEvent(
            event_id="12345",
            source=WebhookSource.GITHUB,
            event_type=EventType.PUSH,
            repository="owner/repo",
            payload={"test": "data"},
            received_at=datetime.now(UTC),
        )

        assert event.event_id == "12345"
        assert event.source == WebhookSource.GITHUB
        assert event.event_type == EventType.PUSH
        assert event.repository == "owner/repo"

    def test_webhook_event_to_dict(self) -> None:
        """Convert webhook event to dictionary."""
        event = WebhookEvent(
            event_id="abc",
            source=WebhookSource.GITLAB,
            event_type=EventType.ISSUE_OPENED,
            repository="owner/repo",
            payload={"key": "value"},
            received_at=datetime.now(UTC),
        )

        d = event.to_dict()
        assert d["event_id"] == "abc"
        assert d["source"] == "gitlab"
        assert d["event_type"] == "issue_opened"


class TestWebhookResult:
    """Tests for WebhookResult dataclass."""

    def test_create_success_result(self) -> None:
        """Create a successful webhook result."""
        result = WebhookResult(
            success=True,
            message="Event processed",
            actions_taken=["Created task #1"],
        )

        assert result.success is True
        assert result.message == "Event processed"
        assert len(result.actions_taken) == 1

    def test_create_failure_result(self) -> None:
        """Create a failed webhook result."""
        result = WebhookResult(
            success=False,
            message="Invalid signature",
            error="Signature verification failed",
        )

        assert result.success is False
        assert result.error == "Signature verification failed"

    def test_result_to_dict(self) -> None:
        """Convert result to dictionary."""
        result = WebhookResult(
            success=True,
            message="OK",
            actions_taken=["Action 1", "Action 2"],
        )

        d = result.to_dict()
        assert d["success"] is True
        assert d["message"] == "OK"
        assert len(d["actions_taken"]) == 2


class TestWebhookHandler:
    """Tests for WebhookHandler class."""

    def test_verify_github_signature(
        self,
        mock_task_store: AsyncMock,
    ) -> None:
        """Verify GitHub webhook signature."""
        secret = "test-secret"
        handler = WebhookHandler(mock_task_store, github_secret=secret)

        payload = b'{"test": "data"}'
        signature = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

        assert handler.verify_github_signature(payload, signature) is True
        assert handler.verify_github_signature(payload, "sha256=invalid") is False

    def test_verify_gitlab_token(
        self,
        mock_task_store: AsyncMock,
    ) -> None:
        """Verify GitLab webhook token."""
        token = "test-token"
        handler = WebhookHandler(mock_task_store, gitlab_token=token)

        assert handler.verify_gitlab_token("test-token") is True
        assert handler.verify_gitlab_token("invalid-token") is False

    def test_parse_github_push_event(
        self,
        mock_task_store: AsyncMock,
        sample_github_push_payload: dict[str, Any],
    ) -> None:
        """Parse GitHub push event."""
        handler = WebhookHandler(mock_task_store)

        event = handler.parse_github_event("push", sample_github_push_payload)

        assert event is not None
        assert event.source == WebhookSource.GITHUB
        assert event.event_type == EventType.PUSH
        assert event.repository == "owner/test-repo"

    def test_parse_github_issue_event(
        self,
        mock_task_store: AsyncMock,
        sample_github_issue_payload: dict[str, Any],
    ) -> None:
        """Parse GitHub issue event."""
        handler = WebhookHandler(mock_task_store)

        event = handler.parse_github_event("issues", sample_github_issue_payload)

        assert event is not None
        assert event.source == WebhookSource.GITHUB
        assert event.event_type == EventType.ISSUE_OPENED
        assert event.payload["issue"]["number"] == 42

    def test_parse_gitlab_push_event(
        self,
        mock_task_store: AsyncMock,
        sample_gitlab_push_payload: dict[str, Any],
    ) -> None:
        """Parse GitLab push event."""
        handler = WebhookHandler(mock_task_store)

        event = handler.parse_gitlab_event(sample_gitlab_push_payload)

        assert event is not None
        assert event.source == WebhookSource.GITLAB
        assert event.event_type == EventType.PUSH

    @pytest.mark.asyncio
    async def test_handle_github_push(
        self,
        mock_task_store: AsyncMock,
        sample_github_push_payload: dict[str, Any],
    ) -> None:
        """Handle GitHub push webhook."""
        handler = WebhookHandler(mock_task_store)

        event = handler.parse_github_event("push", sample_github_push_payload)
        assert event is not None

        result = await handler.handle_event(event)

        assert result.success is True

    @pytest.mark.asyncio
    async def test_handle_github_issue_opened(
        self,
        mock_task_store: AsyncMock,
        sample_github_issue_payload: dict[str, Any],
    ) -> None:
        """Handle GitHub issue opened webhook."""
        mock_task_store.create.return_value = MagicMock(id="task-1")

        handler = WebhookHandler(mock_task_store)

        event = handler.parse_github_event("issues", sample_github_issue_payload)
        assert event is not None

        result = await handler.handle_event(event)

        assert result.success is True

    @pytest.mark.asyncio
    async def test_handle_unsupported_event(
        self,
        mock_task_store: AsyncMock,
    ) -> None:
        """Handle unsupported event type."""
        handler = WebhookHandler(mock_task_store)

        event = WebhookEvent(
            event_id="123",
            source=WebhookSource.GITHUB,
            event_type=EventType.UNKNOWN,
            repository="owner/repo",
            payload={},
            received_at=datetime.now(UTC),
        )

        result = await handler.handle_event(event)

        # Should succeed but note unsupported
        assert result.success is True or result.message is not None

    def test_classify_event_type(
        self,
        mock_task_store: AsyncMock,
    ) -> None:
        """Classify event type from payload."""
        handler = WebhookHandler(mock_task_store)

        # GitHub event types
        assert handler.classify_github_event("push", {}) == EventType.PUSH
        assert (
            handler.classify_github_event("issues", {"action": "opened"}) == EventType.ISSUE_OPENED
        )
        assert (
            handler.classify_github_event("issues", {"action": "closed"}) == EventType.ISSUE_CLOSED
        )
        assert handler.classify_github_event("pull_request", {}) == EventType.PULL_REQUEST

    @pytest.mark.asyncio
    async def test_handle_with_invalid_signature(
        self,
        mock_task_store: AsyncMock,
        sample_github_push_payload: dict[str, Any],
    ) -> None:
        """Handle webhook with invalid signature."""
        handler = WebhookHandler(mock_task_store, github_secret="secret")

        payload = json.dumps(sample_github_push_payload).encode()
        result = await handler.handle_github_webhook(
            payload=payload,
            signature="sha256=invalid",
            event_type="push",
        )

        assert result.success is False
        assert "signature" in result.error.lower() or "invalid" in result.message.lower()

    @pytest.mark.asyncio
    async def test_handle_gitlab_webhook(
        self,
        mock_task_store: AsyncMock,
        sample_gitlab_push_payload: dict[str, Any],
    ) -> None:
        """Handle GitLab webhook."""
        handler = WebhookHandler(mock_task_store, gitlab_token="token")

        payload = json.dumps(sample_gitlab_push_payload).encode()
        result = await handler.handle_gitlab_webhook(
            payload=payload,
            token="token",
        )

        assert result.success is True

    @pytest.mark.asyncio
    async def test_event_idempotency(
        self,
        mock_task_store: AsyncMock,
        sample_github_push_payload: dict[str, Any],
    ) -> None:
        """Same event processed twice is handled idempotently."""
        handler = WebhookHandler(mock_task_store)

        event = WebhookEvent(
            event_id="duplicate-id",
            source=WebhookSource.GITHUB,
            event_type=EventType.PUSH,
            repository="owner/repo",
            payload=sample_github_push_payload,
            received_at=datetime.now(UTC),
        )

        # First handling
        result1 = await handler.handle_event(event)
        assert result1.success is True

        # Second handling (duplicate)
        result2 = await handler.handle_event(event)
        assert result2.success is True
        # Should indicate it was already processed
        assert "duplicate" in result2.message.lower() or "already" in result2.message.lower()

    def test_extract_repository_info(
        self,
        mock_task_store: AsyncMock,
        sample_github_push_payload: dict[str, Any],
    ) -> None:
        """Extract repository information from payload."""
        handler = WebhookHandler(mock_task_store)

        repo_info = handler.extract_repository_info(
            sample_github_push_payload,
            WebhookSource.GITHUB,
        )

        assert repo_info["name"] == "test-repo"
        assert repo_info["full_name"] == "owner/test-repo"
        assert repo_info["url"] == "https://github.com/owner/test-repo"

    @pytest.mark.asyncio
    async def test_handle_event_creates_audit_log(
        self,
        mock_task_store: AsyncMock,
        sample_github_issue_payload: dict[str, Any],
    ) -> None:
        """Handling event creates audit log entry."""
        handler = WebhookHandler(mock_task_store)

        event = handler.parse_github_event("issues", sample_github_issue_payload)
        assert event is not None

        await handler.handle_event(event)

        # Verify event was logged
        assert len(handler._processed_events) >= 1

    # ------------------------------------------------------------------
    # verify_github_signature without secret (no-verify path)
    # ------------------------------------------------------------------

    def test_verify_github_signature_no_secret(self, mock_task_store: AsyncMock) -> None:
        handler = WebhookHandler(mock_task_store)  # no github_secret
        assert handler.verify_github_signature(b"data", "sha256=anything") is True

    def test_verify_github_signature_bad_prefix(self, mock_task_store: AsyncMock) -> None:
        handler = WebhookHandler(mock_task_store, github_secret="secret")
        assert handler.verify_github_signature(b"data", "sha1=badsig") is False

    # ------------------------------------------------------------------
    # verify_gitlab_token without token (no-verify path)
    # ------------------------------------------------------------------

    def test_verify_gitlab_token_no_token(self, mock_task_store: AsyncMock) -> None:
        handler = WebhookHandler(mock_task_store)  # no gitlab_token
        assert handler.verify_gitlab_token("anything") is True

    # ------------------------------------------------------------------
    # classify_github_event — ISSUE_UPDATED and UNKNOWN branches
    # ------------------------------------------------------------------

    def test_classify_github_event_issue_updated(self, mock_task_store: AsyncMock) -> None:
        handler = WebhookHandler(mock_task_store)
        result = handler.classify_github_event("issues", {"action": "labeled"})
        assert result == EventType.ISSUE_UPDATED

    def test_classify_github_event_unknown(self, mock_task_store: AsyncMock) -> None:
        handler = WebhookHandler(mock_task_store)
        result = handler.classify_github_event("deployment", {})
        assert result == EventType.UNKNOWN

    # ------------------------------------------------------------------
    # classify_gitlab_event — all branches
    # ------------------------------------------------------------------

    def test_classify_gitlab_event_push(self, mock_task_store: AsyncMock) -> None:
        handler = WebhookHandler(mock_task_store)
        assert handler.classify_gitlab_event("push", {}) == EventType.PUSH

    def test_classify_gitlab_event_issue_opened(self, mock_task_store: AsyncMock) -> None:
        handler = WebhookHandler(mock_task_store)
        assert handler.classify_gitlab_event("issue", {"action": "open"}) == EventType.ISSUE_OPENED

    def test_classify_gitlab_event_issue_closed(self, mock_task_store: AsyncMock) -> None:
        handler = WebhookHandler(mock_task_store)
        assert handler.classify_gitlab_event("issue", {"action": "close"}) == EventType.ISSUE_CLOSED

    def test_classify_gitlab_event_issue_updated(self, mock_task_store: AsyncMock) -> None:
        handler = WebhookHandler(mock_task_store)
        assert handler.classify_gitlab_event("issue", {"action": "edit"}) == EventType.ISSUE_UPDATED

    def test_classify_gitlab_event_merge_request(self, mock_task_store: AsyncMock) -> None:
        handler = WebhookHandler(mock_task_store)
        assert handler.classify_gitlab_event("merge_request", {}) == EventType.MERGE_REQUEST

    def test_classify_gitlab_event_unknown(self, mock_task_store: AsyncMock) -> None:
        handler = WebhookHandler(mock_task_store)
        assert handler.classify_gitlab_event("pipeline", {}) == EventType.UNKNOWN

    # ------------------------------------------------------------------
    # handle_event — ISSUE_CLOSED, PULL_REQUEST, and exception branches
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_handle_event_issue_closed(self, mock_task_store: AsyncMock) -> None:
        handler = WebhookHandler(mock_task_store)
        event = WebhookEvent(
            event_id="close-1",
            source=WebhookSource.GITHUB,
            event_type=EventType.ISSUE_CLOSED,
            repository="owner/repo",
            payload={"issue": {"number": 7, "title": "Old bug"}},
            received_at=datetime.now(UTC),
        )
        result = await handler.handle_event(event)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_handle_event_pull_request(self, mock_task_store: AsyncMock) -> None:
        handler = WebhookHandler(mock_task_store)
        event = WebhookEvent(
            event_id="pr-1",
            source=WebhookSource.GITHUB,
            event_type=EventType.PULL_REQUEST,
            repository="owner/repo",
            payload={"pull_request": {"number": 3, "title": "My PR"}},
            received_at=datetime.now(UTC),
        )
        result = await handler.handle_event(event)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_handle_event_exception_returns_failure(self, mock_task_store: AsyncMock) -> None:
        from unittest.mock import patch

        handler = WebhookHandler(mock_task_store)
        event = WebhookEvent(
            event_id="err-2",
            source=WebhookSource.GITHUB,
            event_type=EventType.PUSH,
            repository="owner/repo",
            payload={},
            received_at=datetime.now(UTC),
        )
        # Patch _handle_push to raise inside the try block
        with patch.object(handler, "_handle_push", side_effect=RuntimeError("simulated error")):
            result = await handler.handle_event(event)
        assert result.success is False
        assert "failed" in result.message.lower()

    # ------------------------------------------------------------------
    # handle_github_webhook — success, no-secret (passthrough), JSON error
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_handle_github_webhook_no_secret(
        self, mock_task_store: AsyncMock, sample_github_push_payload: dict[str, Any]
    ) -> None:
        handler = WebhookHandler(mock_task_store)
        payload = json.dumps(sample_github_push_payload).encode()
        result = await handler.handle_github_webhook(payload, "sha256=anything", "push")
        assert result.success is True

    @pytest.mark.asyncio
    async def test_handle_github_webhook_json_error(self, mock_task_store: AsyncMock) -> None:
        handler = WebhookHandler(mock_task_store)
        result = await handler.handle_github_webhook(b"not-json", "sha256=x", "push")
        assert result.success is False
        assert "JSON" in result.message or "parse" in result.message.lower()

    @pytest.mark.asyncio
    async def test_handle_github_webhook_unknown_event(self, mock_task_store: AsyncMock) -> None:
        handler = WebhookHandler(mock_task_store)
        payload = json.dumps({"repository": {"full_name": "a/b"}}).encode()
        result = await handler.handle_github_webhook(payload, "sha256=x", "unknown_event_xyz")
        # Unknown event is still "handled" (succeeds) with UNKNOWN type
        assert result.success is True

    # ------------------------------------------------------------------
    # handle_gitlab_webhook — invalid token, JSON error, no event
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_handle_gitlab_webhook_invalid_token(
        self, mock_task_store: AsyncMock, sample_gitlab_push_payload: dict[str, Any]
    ) -> None:
        handler = WebhookHandler(mock_task_store, gitlab_token="correct")
        payload = json.dumps(sample_gitlab_push_payload).encode()
        result = await handler.handle_gitlab_webhook(payload, token="wrong")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_handle_gitlab_webhook_json_error(self, mock_task_store: AsyncMock) -> None:
        handler = WebhookHandler(mock_task_store)
        result = await handler.handle_gitlab_webhook(b"bad-json", token=None)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_handle_gitlab_webhook_unknown_event(self, mock_task_store: AsyncMock) -> None:
        handler = WebhookHandler(mock_task_store)
        # Valid JSON but unknown event kind — parse_gitlab_event returns UNKNOWN type, still succeeds
        result = await handler.handle_gitlab_webhook(
            json.dumps({"object_kind": "unknown_gitlab_event"}).encode(), token=None
        )
        assert result.success is True

    # ------------------------------------------------------------------
    # extract_repository_info — GitLab source
    # ------------------------------------------------------------------

    def test_extract_repository_info_gitlab(
        self, mock_task_store: AsyncMock, sample_gitlab_push_payload: dict[str, Any]
    ) -> None:
        handler = WebhookHandler(mock_task_store)
        info = handler.extract_repository_info(sample_gitlab_push_payload, WebhookSource.GITLAB)
        assert info["name"] == "test-repo"
        assert info["full_name"] == "owner/test-repo"

    # ------------------------------------------------------------------
    # _cleanup_processed_events — overflow pruning
    # ------------------------------------------------------------------

    def test_cleanup_processed_events_prunes_when_over_max(
        self, mock_task_store: AsyncMock
    ) -> None:
        handler = WebhookHandler(mock_task_store)
        # Fill beyond MAX_PROCESSED_EVENTS
        for i in range(handler.MAX_PROCESSED_EVENTS + 5):
            handler._processed_events[f"event-{i}"] = True
        handler._cleanup_processed_events()
        assert len(handler._processed_events) <= handler.MAX_PROCESSED_EVENTS

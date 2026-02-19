"""Webhook security tests.

Tests for webhook authentication and replay attack prevention:
- HMAC signature validation
- Timestamp validation
- Replay attack prevention

Run: pytest tests/security/test_webhooks.py -v
"""

import hashlib
import hmac
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

from mahavishnu.core.webhook_auth import WebhookAuthenticator
from mahavishnu.core.errors import WebhookAuthError, ErrorCode


class TestWebhookSignatureValidation:
    """Test HMAC signature validation."""

    @pytest.fixture
    def mock_db(self) -> MagicMock:
        """Create mock database."""
        db = MagicMock()
        db.fetch_one = AsyncMock(return_value=None)
        db.execute = AsyncMock(return_value="INSERT 0 1")
        return db

    @pytest.fixture
    def authenticator(self, mock_db: MagicMock) -> WebhookAuthenticator:
        """Create webhook authenticator."""
        return WebhookAuthenticator(mock_db)

    @pytest.fixture
    def valid_signature(self) -> tuple[bytes, str, str]:
        """Generate valid signature and payload."""
        secret = "test-webhook-secret"
        payload = b'{"action": "push", "ref": "refs/heads/main"}'
        mac = hmac.new(secret.encode(), msg=payload, digestmod=hashlib.sha256)
        signature = f"sha256={mac.hexdigest()}"
        return payload, signature, secret

    @pytest.mark.asyncio
    async def test_valid_signature_accepted(
        self,
        authenticator: WebhookAuthenticator,
        valid_signature: tuple,
    ) -> None:
        """Test that valid signatures are accepted."""
        payload, signature, secret = valid_signature
        result = await authenticator.verify_webhook_signature(
            payload=payload,
            signature=signature,
            webhook_id="test-webhook-123",
            timestamp=datetime.now(timezone.utc).isoformat(),
            secret=secret,
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_invalid_signature_rejected(
        self,
        authenticator: WebhookAuthenticator,
    ) -> None:
        """Test that invalid signatures are rejected."""
        payload = b'{"action": "push"}'
        fake_signature = "sha256=0" * 32  # Invalid signature

        with pytest.raises(WebhookAuthError) as exc_info:
            await authenticator.verify_webhook_signature(
                payload=payload,
                signature=fake_signature,
                webhook_id="test-webhook-123",
                secret="test-secret",
            )

        assert exc_info.value.error_code == ErrorCode.WEBHOOK_SIGNATURE_INVALID

    @pytest.mark.asyncio
    async def test_tampered_payload_rejected(
        self,
        authenticator: WebhookAuthenticator,
        valid_signature: tuple,
    ) -> None:
        """Test that tampered payloads are rejected."""
        payload, signature, secret = valid_signature
        # Tamper with payload
        tampered_payload = payload.replace(b"push", b"pull")

        with pytest.raises(WebhookAuthError) as exc_info:
            await authenticator.verify_webhook_signature(
                payload=tampered_payload,
                signature=signature,
                webhook_id="test-webhook-123",
                secret=secret,
            )

        assert exc_info.value.error_code == ErrorCode.WEBHOOK_SIGNATURE_INVALID

    @pytest.mark.asyncio
    async def test_missing_secret_rejected(
        self,
        authenticator: WebhookAuthenticator,
    ) -> None:
        """Test that missing secret is rejected."""
        with pytest.raises(WebhookAuthError) as exc_info:
            await authenticator.verify_webhook_signature(
                payload=b"test",
                signature="sha256=abc123",
                webhook_id="test-webhook-123",
                secret=None,
            )

        assert "No webhook secret" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_malformed_signature_rejected(
        self,
        authenticator: WebhookAuthenticator,
    ) -> None:
        """Test that malformed signatures are rejected."""
        with pytest.raises(WebhookAuthError) as exc_info:
            await authenticator.verify_webhook_signature(
                payload=b"test",
                signature="invalid-format-no-equals",
                webhook_id="test-webhook-123",
                secret="test-secret",
            )

        assert exc_info.value.error_code == ErrorCode.WEBHOOK_SIGNATURE_INVALID

    @pytest.mark.asyncio
    async def test_unsupported_algorithm_rejected(
        self,
        authenticator: WebhookAuthenticator,
    ) -> None:
        """Test that unsupported algorithms are rejected."""
        with pytest.raises(WebhookAuthError) as exc_info:
            await authenticator.verify_webhook_signature(
                payload=b"test",
                signature="md5=abc123",  # MD5 not supported
                webhook_id="test-webhook-123",
                secret="test-secret",
            )

        assert "Unsupported" in str(exc_info.value)


class TestTimestampValidation:
    """Test timestamp validation for webhooks."""

    @pytest.fixture
    def mock_db(self) -> MagicMock:
        """Create mock database."""
        db = MagicMock()
        db.fetch_one = AsyncMock(return_value=None)
        db.execute = AsyncMock(return_value="INSERT 0 1")
        return db

    @pytest.fixture
    def authenticator(self, mock_db: MagicMock) -> WebhookAuthenticator:
        """Create webhook authenticator."""
        return WebhookAuthenticator(mock_db)

    def _make_signature(self, payload: bytes, secret: str) -> str:
        """Create valid signature for payload."""
        mac = hmac.new(secret.encode(), msg=payload, digestmod=hashlib.sha256)
        return f"sha256={mac.hexdigest()}"

    @pytest.mark.asyncio
    async def test_current_timestamp_accepted(
        self,
        authenticator: WebhookAuthenticator,
    ) -> None:
        """Test that current timestamps are accepted."""
        payload = b'{"action": "push"}'
        secret = "test-secret"

        result = await authenticator.verify_webhook_signature(
            payload=payload,
            signature=self._make_signature(payload, secret),
            webhook_id="test-webhook-123",
            timestamp=datetime.now(timezone.utc).isoformat(),
            secret=secret,
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_old_timestamp_rejected(
        self,
        authenticator: WebhookAuthenticator,
    ) -> None:
        """Test that old timestamps are rejected."""
        payload = b'{"action": "push"}'
        secret = "test-secret"

        # Create timestamp 10 minutes ago (older than 5 minute max)
        old_timestamp = (
            datetime.now(timezone.utc) - timedelta(minutes=10)
        ).isoformat()

        with pytest.raises(WebhookAuthError) as exc_info:
            await authenticator.verify_webhook_signature(
                payload=payload,
                signature=self._make_signature(payload, secret),
                webhook_id="test-webhook-123",
                timestamp=old_timestamp,
                secret=secret,
            )

        assert "too old" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_future_timestamp_rejected(
        self,
        authenticator: WebhookAuthenticator,
    ) -> None:
        """Test that future timestamps are rejected (clock skew protection)."""
        payload = b'{"action": "push"}'
        secret = "test-secret"

        # Create timestamp 10 minutes in the future
        future_timestamp = (
            datetime.now(timezone.utc) + timedelta(minutes=10)
        ).isoformat()

        with pytest.raises(WebhookAuthError) as exc_info:
            await authenticator.verify_webhook_signature(
                payload=payload,
                signature=self._make_signature(payload, secret),
                webhook_id="test-webhook-123",
                timestamp=future_timestamp,
                secret=secret,
            )

        assert "future" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_invalid_timestamp_format_rejected(
        self,
        authenticator: WebhookAuthenticator,
    ) -> None:
        """Test that invalid timestamp format is rejected."""
        payload = b'{"action": "push"}'
        secret = "test-secret"

        with pytest.raises(WebhookAuthError) as exc_info:
            await authenticator.verify_webhook_signature(
                payload=payload,
                signature=self._make_signature(payload, secret),
                webhook_id="test-webhook-123",
                timestamp="not-a-valid-timestamp",
                secret=secret,
            )

        assert "Invalid timestamp format" in str(exc_info.value)


class TestReplayAttackPrevention:
    """Test replay attack prevention."""

    @pytest.fixture
    def mock_db(self) -> MagicMock:
        """Create mock database."""
        db = MagicMock()
        db.fetch_one = AsyncMock(return_value=None)
        db.execute = AsyncMock(return_value="INSERT 0 1")
        return db

    @pytest.fixture
    def authenticator(self, mock_db: MagicMock) -> WebhookAuthenticator:
        """Create webhook authenticator."""
        return WebhookAuthenticator(mock_db)

    def _make_signature(self, payload: bytes, secret: str) -> str:
        """Create valid signature for payload."""
        mac = hmac.new(secret.encode(), msg=payload, digestmod=hashlib.sha256)
        return f"sha256={mac.hexdigest()}"

    @pytest.mark.asyncio
    async def test_duplicate_webhook_rejected(
        self,
        mock_db: MagicMock,
    ) -> None:
        """Test that duplicate webhook IDs are rejected (replay attack)."""
        # First call returns None (not processed)
        # Second call returns a record (already processed)
        mock_db.fetch_one = AsyncMock(side_effect=[None, {"webhook_id": "test-123"}])

        authenticator = WebhookAuthenticator(mock_db)
        payload = b'{"action": "push"}'
        secret = "test-secret"

        # First request succeeds
        result = await authenticator.verify_webhook_signature(
            payload=payload,
            signature=self._make_signature(payload, secret),
            webhook_id="test-webhook-123",
            timestamp=datetime.now(timezone.utc).isoformat(),
            secret=secret,
        )
        assert result is True

        # Second request with same webhook_id is rejected
        with pytest.raises(WebhookAuthError) as exc_info:
            await authenticator.verify_webhook_signature(
                payload=payload,
                signature=self._make_signature(payload, secret),
                webhook_id="test-webhook-123",
                timestamp=datetime.now(timezone.utc).isoformat(),
                secret=secret,
            )

        assert exc_info.value.error_code == ErrorCode.WEBHOOK_REPLAY_DETECTED
        assert "replay attack" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_different_webhook_ids_accepted(
        self,
        authenticator: WebhookAuthenticator,
    ) -> None:
        """Test that different webhook IDs are both accepted."""
        payload = b'{"action": "push"}'
        secret = "test-secret"

        # First webhook
        result1 = await authenticator.verify_webhook_signature(
            payload=payload,
            signature=self._make_signature(payload, secret),
            webhook_id="webhook-001",
            timestamp=datetime.now(timezone.utc).isoformat(),
            secret=secret,
        )
        assert result1 is True

        # Second webhook with different ID
        result2 = await authenticator.verify_webhook_signature(
            payload=payload,
            signature=self._make_signature(payload, secret),
            webhook_id="webhook-002",
            timestamp=datetime.now(timezone.utc).isoformat(),
            secret=secret,
        )
        assert result2 is True


class TestWebhookCleanup:
    """Test webhook record cleanup."""

    @pytest.fixture
    def mock_db(self) -> MagicMock:
        """Create mock database."""
        db = MagicMock()
        db.fetch_one = AsyncMock(return_value=None)
        db.execute = AsyncMock(return_value="DELETE 100")
        return db

    @pytest.fixture
    def authenticator(self, mock_db: MagicMock) -> WebhookAuthenticator:
        """Create webhook authenticator."""
        return WebhookAuthenticator(mock_db)

    @pytest.mark.asyncio
    async def test_cleanup_old_webhooks(
        self,
        authenticator: WebhookAuthenticator,
    ) -> None:
        """Test that old webhook records are cleaned up."""
        deleted_count = await authenticator.cleanup_old_webhooks(days=7)
        assert deleted_count == 100

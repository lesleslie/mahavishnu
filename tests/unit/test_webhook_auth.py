"""Tests for core/webhook_auth.py — HMAC signature verification with replay prevention."""

from datetime import UTC, datetime, timedelta
import hashlib
import hmac
from unittest.mock import AsyncMock

import pytest

from mahavishnu.core.errors import WebhookAuthError
from mahavishnu.core.webhook_auth import (
    DEFAULT_MAX_AGE_MINUTES,
    SUPPORTED_ALGORITHMS,
    WebhookAuthenticator,
    create_webhook_authenticator,
)


def _make_sig(payload: bytes, secret: str, algo: str = "sha256") -> str:
    hash_func = SUPPORTED_ALGORITHMS[algo]
    mac = hmac.new(secret.encode(), msg=payload, digestmod=hash_func)
    return f"{algo}={mac.hexdigest()}"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_supported_algorithms(self):
        assert SUPPORTED_ALGORITHMS["sha256"] is hashlib.sha256
        assert SUPPORTED_ALGORITHMS["sha384"] is hashlib.sha384
        assert SUPPORTED_ALGORITHMS["sha512"] is hashlib.sha512

    def test_default_max_age(self):
        assert DEFAULT_MAX_AGE_MINUTES == 5


# ---------------------------------------------------------------------------
# WebhookAuthenticator init
# ---------------------------------------------------------------------------


class TestInit:
    def test_default_init(self):
        auth = WebhookAuthenticator("db")
        assert auth.max_age == timedelta(minutes=5)
        assert auth.algorithm == "sha256"

    def test_custom_algorithm(self):
        auth = WebhookAuthenticator("db", algorithm="sha512")
        assert auth.algorithm == "sha512"

    def test_unsupported_algorithm(self):
        with pytest.raises(ValueError, match="Unsupported algorithm"):
            WebhookAuthenticator("db", algorithm="md5")


# ---------------------------------------------------------------------------
# HMAC signature verification
# ---------------------------------------------------------------------------


class TestHMACVerification:
    def test_valid_signature(self):
        secret = "my-secret"
        payload = b"test payload"
        sig = _make_sig(payload, secret)
        auth = WebhookAuthenticator("db")
        # Should not raise
        auth._verify_hmac_signature(payload, sig, secret)

    def test_invalid_signature(self):
        auth = WebhookAuthenticator("db")
        with pytest.raises(WebhookAuthError, match="Invalid webhook signature"):
            auth._verify_hmac_signature(b"payload", "sha256=wrong", "secret")

    def test_bad_signature_format(self):
        auth = WebhookAuthenticator("db")
        with pytest.raises(WebhookAuthError, match="Invalid signature format"):
            auth._verify_hmac_signature(b"test", "no-equals-sign", "secret")

    def test_unsupported_signature_algorithm(self):
        auth = WebhookAuthenticator("db")
        with pytest.raises(WebhookAuthError, match="Unsupported signature algorithm"):
            auth._verify_hmac_signature(b"test", "sha1=abc", "secret")

    def test_sha384_signature(self):
        secret = "secret"
        payload = b"data"
        sig = _make_sig(payload, secret, "sha384")
        auth = WebhookAuthenticator("db")
        auth._verify_hmac_signature(payload, sig, secret)


# ---------------------------------------------------------------------------
# Timestamp validation
# ---------------------------------------------------------------------------


class TestTimestampValidation:
    def test_valid_current_timestamp(self):
        auth = WebhookAuthenticator("db")
        ts = datetime.now(UTC).isoformat()
        auth._validate_timestamp(ts)  # Should not raise

    def test_expired_timestamp(self):
        auth = WebhookAuthenticator("db", max_age_minutes=1)
        old_ts = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
        with pytest.raises(WebhookAuthError, match="too old"):
            auth._validate_timestamp(old_ts)

    def test_future_timestamp(self):
        auth = WebhookAuthenticator("db")
        future_ts = (datetime.now(UTC) + timedelta(minutes=10)).isoformat()
        with pytest.raises(WebhookAuthError, match="future"):
            auth._validate_timestamp(future_ts)

    def test_invalid_format(self):
        auth = WebhookAuthenticator("db")
        with pytest.raises(WebhookAuthError, match="Invalid timestamp format"):
            auth._validate_timestamp("not-a-timestamp")

    def test_naive_timestamp_gets_utc(self):
        auth = WebhookAuthenticator("db")
        # Naive timestamp should not raise
        auth._validate_timestamp(datetime.now(UTC).replace(tzinfo=None).isoformat())


# ---------------------------------------------------------------------------
# Full verification flow
# ---------------------------------------------------------------------------


class TestVerifyWebhookSignature:
    @pytest.mark.asyncio
    async def test_no_secret_raises(self):
        auth = WebhookAuthenticator("db")
        with pytest.raises(WebhookAuthError, match="No webhook secret"):
            await auth.verify_webhook_signature(
                payload=b"test", signature="sha256=abc", webhook_id="id-123", secret=None
            )

    @pytest.mark.asyncio
    async def test_replay_detected(self):
        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = {"id": 1}  # Already processed
        auth = WebhookAuthenticator(mock_db)
        secret = "secret"
        payload = b"test"
        sig = _make_sig(payload, secret)
        with pytest.raises(WebhookAuthError, match="replay"):
            await auth.verify_webhook_signature(
                payload=payload, signature=sig, webhook_id="dup-id", secret=secret
            )

    @pytest.mark.asyncio
    async def test_successful_verification(self):
        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = None  # Not processed yet
        mock_db.execute.return_value = "INSERT 1"
        auth = WebhookAuthenticator(mock_db)
        secret = "secret"
        payload = b"test"
        sig = _make_sig(payload, secret)
        timestamp = datetime.now(UTC).isoformat()
        result = await auth.verify_webhook_signature(
            payload=payload,
            signature=sig,
            webhook_id="new-id",
            timestamp=timestamp,
            secret=secret,
        )
        assert result is True
        mock_db.execute.assert_called_once()


# ---------------------------------------------------------------------------
# Factory function
# ---------------------------------------------------------------------------


class TestCreateWebhookAuthenticator:
    @pytest.mark.asyncio
    async def test_creates_table(self):
        mock_db = AsyncMock()
        mock_db.execute.return_value = None
        auth = await create_webhook_authenticator(mock_db)
        assert isinstance(auth, WebhookAuthenticator)
        assert mock_db.execute.call_count == 3  # CREATE TABLE + 2 indexes


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


class TestCleanup:
    @pytest.mark.asyncio
    async def test_cleanup_with_results(self):
        mock_db = AsyncMock()
        mock_db.execute.return_value = "DELETE 42"
        auth = WebhookAuthenticator(mock_db)
        result = await auth.cleanup_old_webhooks(days=1)
        assert result == 42

    @pytest.mark.asyncio
    async def test_cleanup_no_result(self):
        mock_db = AsyncMock()
        mock_db.execute.return_value = None
        auth = WebhookAuthenticator(mock_db)
        result = await auth.cleanup_old_webhooks(days=1)
        assert result == 0

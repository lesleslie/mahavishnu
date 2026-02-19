"""
Webhook authentication with replay attack prevention.

This module provides secure webhook handling with:
- HMAC signature validation
- Timestamp validation (reject old webhooks)
- Nonce/ID tracking (prevent replay attacks)

Created: 2026-02-18
Version: 3.1
Related: Security Auditor P0-1 - replay attack prevention
"""

import hashlib
import hmac
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from mahavishnu.core.errors import WebhookAuthError, ErrorCode

logger = logging.getLogger(__name__)

# Default max age for webhooks (5 minutes)
DEFAULT_MAX_AGE_MINUTES = 5

# Supported hash algorithms
SUPPORTED_ALGORITHMS = {
    "sha256": hashlib.sha256,
    "sha384": hashlib.sha384,
    "sha512": hashlib.sha512,
}


class WebhookAuthenticator:
    """
    Webhook authentication with replay attack prevention.

    Features:
    - HMAC signature validation
    - Timestamp validation (reject webhooks older than max_age)
    - Nonce/ID tracking (prevent replay attacks)

    Usage:
        auth = WebhookAuthenticator(db)
        await auth.verify_webhook_signature(
            payload=request_body,
            signature=request.headers["X-Hub-Signature-256"],
            webhook_id=request.headers["X-GitHub-Delivery"],
            timestamp=request.headers["X-Webhook-Timestamp"],
            secret=webhook_secret,
        )
    """

    def __init__(
        self,
        db: Any,
        max_age_minutes: int = DEFAULT_MAX_AGE_MINUTES,
        algorithm: str = "sha256",
    ) -> None:
        """
        Initialize webhook authenticator.

        Args:
            db: Database connection for tracking processed webhooks
            max_age_minutes: Maximum age of webhook in minutes (default: 5)
            algorithm: Hash algorithm for HMAC (default: sha256)
        """
        self.db = db
        self.max_age = timedelta(minutes=max_age_minutes)
        self.algorithm = algorithm

        if algorithm not in SUPPORTED_ALGORITHMS:
            raise ValueError(
                f"Unsupported algorithm: {algorithm}. "
                f"Supported: {list(SUPPORTED_ALGORITHMS.keys())}"
            )

    async def verify_webhook_signature(
        self,
        payload: bytes,
        signature: str,
        webhook_id: str,
        timestamp: str | None = None,
        secret: str | None = None,
    ) -> bool:
        """
        Verify webhook signature with replay attack prevention.

        This performs four validation steps:
        1. HMAC signature verification
        2. Timestamp validation (if provided)
        3. Replay attack detection (duplicate webhook_id)
        4. Mark webhook as processed

        Args:
            payload: Raw request body bytes
            signature: X-Hub-Signature-256 header value (e.g., "sha256=abc123...")
            webhook_id: Unique webhook delivery ID
            timestamp: ISO 8601 timestamp (optional, for additional security)
            secret: Webhook secret for HMAC

        Returns:
            True if signature valid and not a replay attack

        Raises:
            WebhookAuthError: If signature invalid or replay detected
        """
        if not secret:
            raise WebhookAuthError(
                "No webhook secret provided",
                ErrorCode.WEBHOOK_SIGNATURE_INVALID,
            )

        # Step 1: Verify HMAC signature
        self._verify_hmac_signature(payload, signature, secret)

        # Step 2: Validate timestamp (if provided)
        if timestamp:
            self._validate_timestamp(timestamp)

        # Step 3: Check for replay attack (duplicate webhook_id)
        if await self._was_webhook_processed(webhook_id):
            raise WebhookAuthError(
                f"Duplicate webhook_id: {webhook_id} (replay attack detected)",
                ErrorCode.WEBHOOK_REPLAY_DETECTED,
                details={"webhook_id": webhook_id},
            )

        # Step 4: Mark webhook as processed
        await self._mark_webhook_processed(webhook_id, timestamp)

        logger.info(f"Webhook {webhook_id} authenticated successfully")
        return True

    def _verify_hmac_signature(
        self,
        payload: bytes,
        signature: str,
        secret: str,
    ) -> None:
        """
        Verify HMAC signature.

        Args:
            payload: Raw request body bytes
            signature: Signature header value (e.g., "sha256=abc123...")
            secret: Webhook secret

        Raises:
            WebhookAuthError: If signature is invalid
        """
        # Parse signature header
        try:
            algorithm, signature_value = signature.split("=", 1)
        except ValueError:
            raise WebhookAuthError(
                f"Invalid signature format: {signature}",
                ErrorCode.WEBHOOK_SIGNATURE_INVALID,
            )

        # Normalize algorithm name
        algorithm = algorithm.lower()

        if algorithm not in SUPPORTED_ALGORITHMS:
            raise WebhookAuthError(
                f"Unsupported signature algorithm: {algorithm}",
                ErrorCode.WEBHOOK_SIGNATURE_INVALID,
                details={"supported": list(SUPPORTED_ALGORITHMS.keys())},
            )

        # Calculate expected signature
        hash_func = SUPPORTED_ALGORITHMS[algorithm]
        mac = hmac.new(secret.encode(), msg=payload, digestmod=hash_func)
        expected_signature = mac.hexdigest()

        # Constant-time comparison to prevent timing attacks
        if not hmac.compare_digest(expected_signature, signature_value):
            logger.warning(
                f"Invalid webhook signature. Expected: {expected_signature[:8]}..., "
                f"Got: {signature_value[:8]}..."
            )
            raise WebhookAuthError(
                "Invalid webhook signature",
                ErrorCode.WEBHOOK_SIGNATURE_INVALID,
            )

    def _validate_timestamp(self, timestamp: str) -> None:
        """
        Validate webhook timestamp.

        Args:
            timestamp: ISO 8601 timestamp string

        Raises:
            WebhookAuthError: If timestamp is invalid or too old
        """
        try:
            webhook_time = datetime.fromisoformat(timestamp)
        except ValueError:
            raise WebhookAuthError(
                f"Invalid timestamp format: {timestamp}",
                ErrorCode.WEBHOOK_SIGNATURE_INVALID,
                details={"expected": "ISO 8601 format"},
            )

        # Ensure timestamp has timezone
        if webhook_time.tzinfo is None:
            webhook_time = webhook_time.replace(tzinfo=timezone.utc)

        # Check age
        now = datetime.now(timezone.utc)
        age = now - webhook_time

        if age > self.max_age:
            raise WebhookAuthError(
                f"Webhook too old: {age.total_seconds():.0f}s (max: {self.max_age.total_seconds():.0f}s)",
                ErrorCode.WEBHOOK_SIGNATURE_INVALID,
                details={
                    "webhook_age_seconds": age.total_seconds(),
                    "max_age_seconds": self.max_age.total_seconds(),
                },
            )

        # Also reject future timestamps (clock skew protection)
        if webhook_time > now + timedelta(minutes=5):
            raise WebhookAuthError(
                f"Webhook timestamp in future: {timestamp}",
                ErrorCode.WEBHOOK_SIGNATURE_INVALID,
            )

    async def _was_webhook_processed(self, webhook_id: str) -> bool:
        """
        Check if webhook_id was already processed (replay detection).

        Args:
            webhook_id: Unique webhook delivery ID

        Returns:
            True if webhook was already processed
        """
        row = await self.db.fetch_one(
            "SELECT 1 FROM processed_webhooks WHERE webhook_id = $1",
            webhook_id,
        )
        return row is not None

    async def _mark_webhook_processed(
        self,
        webhook_id: str,
        timestamp: str | None,
    ) -> None:
        """
        Mark webhook as processed to prevent replay attacks.

        Args:
            webhook_id: Unique webhook delivery ID
            timestamp: Original webhook timestamp
        """
        await self.db.execute(
            "INSERT INTO processed_webhooks (webhook_id, processed_at, original_timestamp) "
            "VALUES ($1, $2, $3) "
            "ON CONFLICT (webhook_id) DO NOTHING",
            webhook_id,
            datetime.now(timezone.utc),
            timestamp,
        )

    async def cleanup_old_webhooks(self, days: int = 7) -> int:
        """
        Clean up old processed webhook records.

        This should be called periodically to prevent the processed_webhooks
        table from growing indefinitely.

        Args:
            days: Delete records older than this many days

        Returns:
            Number of records deleted
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        result = await self.db.execute(
            "DELETE FROM processed_webhooks WHERE processed_at < $1",
            cutoff,
        )
        deleted_count = int(result.split()[-1]) if result else 0
        logger.info(f"Cleaned up {deleted_count} old webhook records")
        return deleted_count


async def create_webhook_authenticator(db: Any) -> WebhookAuthenticator:
    """
    Factory function to create a WebhookAuthenticator.

    Also ensures the processed_webhooks table exists.

    Args:
        db: Database connection

    Returns:
        Configured WebhookAuthenticator instance
    """
    # Ensure table exists
    await db.execute("""
        CREATE TABLE IF NOT EXISTS processed_webhooks (
            id BIGSERIAL PRIMARY KEY,
            webhook_id VARCHAR(200) UNIQUE NOT NULL,
            processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            original_timestamp VARCHAR(100),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_processed_webhooks_webhook_id
        ON processed_webhooks(webhook_id)
    """)

    await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_processed_webhooks_processed_at
        ON processed_webhooks(processed_at)
    """)

    return WebhookAuthenticator(db)

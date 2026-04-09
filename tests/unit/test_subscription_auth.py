"""Unit tests for core.subscription_auth."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mahavishnu.core.errors import AuthenticationError
from mahavishnu.core.subscription_auth import (
    AuthMethod,
    MultiAuthHandler,
    SubscriptionAuth,
)


def _config(
    *,
    jwt_enabled: bool = True,
    jwt_secret: str = "j" * 32,
    subscription_enabled: bool = True,
    subscription_secret: str | None = "s" * 32,
) -> SimpleNamespace:
    return SimpleNamespace(
        auth=SimpleNamespace(
            enabled=jwt_enabled,
            secret=jwt_secret if jwt_enabled else None,
            algorithm="HS256",
            expire_minutes=60,
        ),
        subscription_auth_enabled=subscription_enabled,
        subscription_auth=SimpleNamespace(enabled=subscription_enabled),
        subscription_auth_secret=subscription_secret,
        subscription_auth_algorithm="HS256",
        subscription_auth_expire_minutes=60,
    )


def test_subscription_auth_requires_min_secret_length() -> None:
    with pytest.raises(ValueError, match="at least 32 characters"):
        SubscriptionAuth(secret="short")


def test_create_and_verify_subscription_token_defaults() -> None:
    auth = SubscriptionAuth(secret="s" * 32, expire_minutes=60)
    token = auth.create_subscription_token(user_id="u1", subscription_type="claude_code")
    decoded = auth.verify_subscription_token(token)

    assert decoded.user_id == "u1"
    assert decoded.subscription_type == "claude_code"
    assert decoded.scopes == ["read", "execute"]


def test_verify_subscription_token_invalid_signature() -> None:
    auth_a = SubscriptionAuth(secret="a" * 32)
    auth_b = SubscriptionAuth(secret="b" * 32)
    token = auth_a.create_subscription_token(user_id="u1", subscription_type="codex")

    with pytest.raises(AuthenticationError, match="Invalid subscription token signature"):
        auth_b.verify_subscription_token(token)


def test_verify_subscription_token_decode_error() -> None:
    auth = SubscriptionAuth(secret="s" * 32)
    with pytest.raises(AuthenticationError, match="Could not decode subscription token"):
        auth.verify_subscription_token("not-a-token")


def test_verify_subscription_token_missing_fields() -> None:
    auth = SubscriptionAuth(secret="s" * 32)
    token = auth.create_subscription_token(user_id="u1", subscription_type="codex")
    # Remove required field by re-encoding with raw jwt payload.
    import jwt

    payload = jwt.decode(token, "s" * 32, algorithms=["HS256"])
    payload.pop("subscription_type")
    broken_token = jwt.encode(payload, "s" * 32, algorithm="HS256")

    with pytest.raises(AuthenticationError, match="missing required fields"):
        auth.verify_subscription_token(broken_token)


def test_verify_subscription_token_expired() -> None:
    auth = SubscriptionAuth(secret="s" * 32, expire_minutes=60)
    expired_data = {
        "user_id": "u1",
        "subscription_type": "claude_code",
        "exp": 1,  # definitely in the past
        "scopes": ["read"],
    }

    # Force decode path to return payload so expiry is checked by
    # _check_subscription_token_expiry (not by jwt's built-in exp validation).
    import mahavishnu.core.subscription_auth as subscription_auth_module

    original_decode = subscription_auth_module.jwt.decode

    def fake_decode(*args, **kwargs):  # type: ignore[no-untyped-def]
        return expired_data

    subscription_auth_module.jwt.decode = fake_decode  # type: ignore[assignment]
    try:
        with pytest.raises(AuthenticationError, match="expired"):
            auth.verify_subscription_token("token-value-not-used")
    finally:
        subscription_auth_module.jwt.decode = original_decode  # type: ignore[assignment]


def test_multi_auth_rejects_invalid_header_format() -> None:
    handler = MultiAuthHandler(_config())
    with pytest.raises(AuthenticationError, match="missing or invalid format"):
        handler.authenticate_request("Token abc")


def test_multi_auth_prefers_subscription_when_available() -> None:
    handler = MultiAuthHandler(_config())
    token = handler.create_claude_subscription_token("u-sub", scopes=["read"])
    result = handler.authenticate_request(f"Bearer {token}")

    assert result["authenticated"] is True
    assert result["user"] == "u-sub"
    assert result["method"] == AuthMethod.CLAUDE_SUBSCRIPTION
    assert result["scopes"] == ["read"]


def test_multi_auth_codex_method_selection() -> None:
    handler = MultiAuthHandler(_config())
    token = handler.create_codex_subscription_token("u-codex")
    result = handler.authenticate_request(f"Bearer {token}")

    assert result["authenticated"] is True
    assert result["method"] == AuthMethod.CODEX_SUBSCRIPTION
    assert result["subscription_type"] == "codex"


def test_multi_auth_jwt_fallback_when_subscription_fails() -> None:
    cfg = _config(subscription_enabled=True, subscription_secret="x" * 32)
    handler = MultiAuthHandler(cfg)

    # Create JWT token with JWT auth secret; subscription verification should fail first,
    # then JWT path should authenticate successfully.
    assert handler.jwt_auth is not None
    jwt_token = handler.jwt_auth.create_token("u-jwt")
    result = handler.authenticate_request(f"Bearer {jwt_token}")

    assert result["authenticated"] is True
    assert result["user"] == "u-jwt"
    assert result["method"] == AuthMethod.JWT


def test_multi_auth_jwt_non_dict_token_data_uses_username_attribute() -> None:
    handler = MultiAuthHandler(_config(subscription_enabled=False))

    class TokenObj:
        username = "legacy-user"

    assert handler.jwt_auth is not None
    handler.jwt_auth.verify_token = lambda _token: TokenObj()  # type: ignore[assignment]

    result = handler.authenticate_request("Bearer any-value")
    assert result["authenticated"] is True
    assert result["user"] == "legacy-user"
    assert result["method"] == AuthMethod.JWT


def test_multi_auth_all_methods_failed_reports_errors() -> None:
    handler = MultiAuthHandler(_config(subscription_enabled=False))
    with pytest.raises(AuthenticationError, match="All authentication methods failed") as exc:
        handler.authenticate_request("Bearer invalid.token.here")

    assert "errors" in exc.value.details
    assert len(exc.value.details["errors"]) >= 1


def test_subscription_not_configured_token_creation_raises() -> None:
    handler = MultiAuthHandler(_config(subscription_enabled=False, subscription_secret=None))
    assert handler.is_claude_subscribed() is False
    assert handler.is_codex_subscribed() is False

    with pytest.raises(AuthenticationError, match="not configured"):
        handler.create_claude_subscription_token("u1")
    with pytest.raises(AuthenticationError, match="not configured"):
        handler.create_codex_subscription_token("u1")

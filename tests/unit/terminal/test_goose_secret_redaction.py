"""Tests for Goose bearer-token redaction.

Verifies:
- ``GooseAuthError.__repr__`` / ``__str__`` never contain the bearer token
  even when the error message includes it.
- The same applies to ``GooseUnavailable`` and ``GooseTimeoutError`` — the
  error classes share the redaction primitive (``_redact_sensitive_details``).
- ``httpx.AsyncClient`` is configured with an ``event_hooks["response"]``
  callback that strips ``Authorization`` from any retry request, so a
  misrouted DNS or 502+retry cannot exfiltrate the token to a different host.

Req: REQ-GOO-002.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx2 as httpx
import pytest
from pydantic import SecretStr

from mahavishnu.core.errors import (
    GooseAuthError,
    GooseTimeoutError,
    GooseUnavailable,
)
from mahavishnu.terminal.goose_client import GooseHTTPClient


SAMPLE_TOKEN = "this-is-the-bearer-secret-1234567890"


def _build_client(handler: Callable[[httpx.Request], httpx.Response]) -> GooseHTTPClient:
    transport = httpx.MockTransport(handler)
    return GooseHTTPClient(
        base_url="http://127.0.0.1:8694",
        secret_key=SecretStr(SAMPLE_TOKEN),
        transport=transport,
    )


@pytest.mark.unit
def test_goose_auth_error_repr_redacts_token() -> None:
    err = GooseAuthError(
        f"bearer {SAMPLE_TOKEN} was rejected",
        status_code=401,
        details={"Authorization": f"Bearer {SAMPLE_TOKEN}", "session_id": "abc"},
    )
    text = repr(err)
    assert SAMPLE_TOKEN not in text
    # `_redact_message` uses `***` for inline string matches and
    # `_redact_sensitive_details` uses `<redacted>` for dict fields.
    assert "***" in text or "<redacted>" in text


@pytest.mark.unit
def test_goose_auth_error_str_redacts_token() -> None:
    err = GooseAuthError(
        f"Authorization: Bearer {SAMPLE_TOKEN} invalid",
        status_code=401,
        details={"token": SAMPLE_TOKEN, "bearer": SAMPLE_TOKEN},
    )
    text = str(err)
    assert SAMPLE_TOKEN not in text


@pytest.mark.unit
def test_goose_unavailable_repr_redacts_token() -> None:
    err = GooseUnavailable(
        f"goose unreachable; secret={SAMPLE_TOKEN}",
        install_hint="set GOOSE_SECRET in env",
        details={"api_key": SAMPLE_TOKEN, "host": "127.0.0.1"},
    )
    assert SAMPLE_TOKEN not in repr(err)
    assert SAMPLE_TOKEN not in str(err)


@pytest.mark.unit
def test_goose_timeout_error_redacts_token() -> None:
    err = GooseTimeoutError(
        f"timed out with token {SAMPLE_TOKEN}",
        method="GET",
        path="/sessions",
        timeout_seconds=30.0,
        details={"Authorization": SAMPLE_TOKEN},
    )
    assert SAMPLE_TOKEN not in repr(err)
    assert SAMPLE_TOKEN not in str(err)


@pytest.mark.unit
def test_non_sensitive_details_preserved() -> None:
    err = GooseAuthError(
        "creds invalid",
        status_code=403,
        details={"session_id": "abc-123", "method": "POST"},
    )
    # Non-sensitive keys are kept intact.
    assert err.details["session_id"] == "abc-123"
    assert err.details["method"] == "POST"


@pytest.mark.unit
async def test_event_hooks_strips_authorization_on_retry() -> None:
    """httpx event_hooks['response'] fires before the retry is dispatched.

    We assert that ``response.next_request`` (httpx >= 0.27 attribute) has
    its ``Authorization`` header removed by :func:`_default_redactor`.

    Req: REQ-GOO-002.
    """

    # Synthetic response object — we don't need to go through a real
    # server, just exercise the redactor hook directly.
    redactor_module = __import__(
        "mahavishnu.terminal.goose_client", fromlist=["_default_redactor"]
    )
    redactor = redactor_module._default_redactor

    class _Headers:
        def __init__(self) -> None:
            self._items: dict[str, str] = {
                "Authorization": f"Bearer {SAMPLE_TOKEN}",
                "Content-Type": "application/json",
            }

        def keys(self) -> list[str]:
            return list(self._items.keys())

        def __delitem__(self, k: str) -> None:
            del self._items[k]

    class _Request:
        def __init__(self) -> None:
            self.headers = _Headers()

    # When next_request is None, no-op.
    await redactor(None)  # type: ignore[arg-type]

    # When next_request is set, strip Authorization.
    req = _Request()
    fake_response = type("FakeResp", (), {"next_request": req})()
    await redactor(fake_response)  # type: ignore[arg-type]
    assert "Authorization" not in req.headers._items
    # Other headers untouched.
    assert req.headers._items["Content-Type"] == "application/json"


@pytest.mark.unit
def test_client_uses_response_event_hooks() -> None:
    """Sanity: the http client registers a response hook so the redactor fires."""

    captured_hooks: dict[str, list[Callable]] = {}

    real_async_client = httpx.AsyncClient

    def factory(*args: object, **kwargs: object) -> httpx.AsyncClient:
        if "event_hooks" in kwargs and kwargs["event_hooks"]:
            captured_hooks.update(kwargs["event_hooks"])
        return real_async_client(*args, **kwargs)

    import unittest.mock as _um

    with _um.patch("mahavishnu.terminal.goose_client.httpx.AsyncClient", new=factory):
        client = _build_client(lambda req: httpx.Response(200, json={"ok": True}))
        # Force the client to lazy-build its internal httpx client.
        _ = client.base_url

    assert "response" in captured_hooks
    assert len(captured_hooks["response"]) >= 1
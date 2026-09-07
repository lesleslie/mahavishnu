"""HTTP client for Block's ``goose serve`` (Goose terminal backend).

Goose exposes a versioned REST surface (v1 today, v2 WebSocket planned) over
HTTP. The adapter requires a bearer token for every request — token ownership
is sensitive: the bearer is a long-lived secret, not a per-request token.

Security primitives:
    - ``SecretStr`` (pydantic) stores the bearer so it never appears in
      ``repr()``/``str()``/structured-log dumps.
    - ``httpx.AsyncClient(..., event_hooks={"response": [_default_redactor]})``
      strips ``Authorization`` from the next attempt on every retry path,
      so a misrouted DNS or 502+retry cannot exfiltrate the token to a
      different host.

Implementation notes:
    - v1 is HTTP-poll based. The ``stream()`` method is a v2 extension point
      that returns ``NotImplementedError`` until goose-server ships
      WebSocket support.
    - ``create_goose_http_client()`` is the canonical factory — every
      caller should construct via this so the resolution order is uniform
      (kwargs > env > 127.0.0.1:8694).

Req: REQ-GOO-001, REQ-GOO-002, REQ-GOO-004
"""

from __future__ import annotations

from collections.abc import Callable
import os
from typing import Any

import httpx2 as httpx
from pydantic import SecretStr

from ..core.errors import (
    GooseAuthError,
    GooseTimeoutError,
    GooseUnavailable,
)

# REQ-GOO-001 — Bearer-only auth; no cookies, no basic auth.
DEFAULT_GOOSE_HOST = "127.0.0.1"
DEFAULT_GOOSE_PORT = 8694  # 8693 is bodai-crow; 8694 leaves room for v2 WS.
DEFAULT_GOOSE_TIMEOUT = 30.0
DEFAULT_POLL_INTERVAL = 0.5


async def _default_redactor(response: httpx.Response) -> None:
    """Strip ``Authorization`` from any retry request on the next attempt.

    httpx calls ``event_hooks["response"]`` for every response, including
    intermediate retries. We mutate the *next* outgoing request's headers
    via ``response.next_request`` (httpx >=0.27) when present. If
    ``next_request`` is missing (final response), this is a no-op.

    httpx2 awaits event hooks, so this must be a coroutine even when the
    body is a sync mutation.
    """
    next_request = getattr(response, "next_request", None)
    if next_request is None:
        return
    headers = getattr(next_request, "headers", None)
    if headers is None:
        return
    # Drop every header whose name looks like a credential. Case-insensitive
    # so ``Authorization``, ``authorization`` and ``AUTHORIZATION`` all match.
    for header_name in list(headers.keys()):
        if header_name.lower() in {"authorization", "proxy-authorization", "x-api-key"}:
            del headers[header_name]


AuthRedactor = Callable[[httpx.Response], "object"]  # sync or async callable


class GooseHTTPClient:
    """HTTP client for ``goose serve``.

    Args:
        base_url: Full base URL for the goose server (e.g.
            ``"http://127.0.0.1:8694"``).
        secret_key: Pydantic ``SecretStr`` carrying the bearer. Never logged
            or repr'd.
        timeout: Default request timeout in seconds.
        poll_interval: Default capture poll interval (informational; not
            enforced inside the client — the adapter drives the cadence).
        transport: Optional httpx transport (test seam).
        auth_redactor: Optional response hook that strips ``Authorization``
            from any retry request. Defaults to :func:`_default_redactor`.
            httpx2 ``await``s every response hook, so the value may be a
            sync callable (httpx will fail to await it) or — correctly —
            an ``async def`` callable returning ``None``.
    """

    def __init__(
        self,
        base_url: str,
        secret_key: SecretStr | None = None,
        *,
        timeout: float = DEFAULT_GOOSE_TIMEOUT,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        transport: Any | None = None,
        auth_redactor: AuthRedactor | None = None,
    ) -> None:
        # Validate base_url early; httpx will also reject malformed URLs but
        # raising here gives a clearer error.
        if not base_url:
            raise ValueError("GooseHTTPClient: base_url is required")
        self._base_url = base_url.rstrip("/")
        self._secret = secret_key
        self._timeout = timeout
        self._poll_interval = poll_interval

        # Compose headers. SecretStr.get_secret_value() is the only sanctioned
        # way to read the underlying string; we never store it on ``self``
        # as a plain ``str``.
        headers: dict[str, str] = {"User-Agent": "mahavishnu-goose-adapter/1.0"}
        if secret_key is not None:
            headers["Authorization"] = f"Bearer {secret_key.get_secret_value()}"

        redactor = auth_redactor or _default_redactor
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
            headers=headers,
            transport=transport,
            event_hooks={"response": [redactor]},
        )

    @property
    def base_url(self) -> str:
        """Return the configured base URL (no trailing slash)."""
        return self._base_url

    @property
    def has_secret(self) -> bool:
        """Return True if a bearer token is configured (without exposing it)."""
        return self._secret is not None

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Issue a JSON HTTP call and parse the response.

        Raises:
            GooseAuthError: 401/403 from goose.
            GooseTimeoutError: ``httpx.TimeoutException`` on this endpoint.
            GooseUnavailable: connection refused / DNS failure / 5xx.
        """
        url = path if path.startswith("/") else f"/{path}"
        request_timeout = timeout if timeout is not None else self._timeout
        try:
            response = await self._client.request(
                method, url, json=json, timeout=request_timeout
            )
        except httpx.HTTPError as exc:
            self._raise_for_http_error(exc, method=method, url=url, timeout=request_timeout)
        return self._parse_response(response, method=method, url=url)

    def _raise_for_http_error(
        self,
        exc: httpx.HTTPError,
        *,
        method: str,
        url: str,
        timeout: float,
    ) -> None:
        """Map httpx errors to typed Goose errors.

        Req: REQ-GOO-001
        """  # req: REQ-GOO-001
        if isinstance(exc, httpx.TimeoutException):
            raise GooseTimeoutError(
                f"goose request timed out: {method} {url}",
                method=method,
                path=url,
                timeout_seconds=timeout,
                details={"base_url": self._base_url},
            ) from exc
        if isinstance(exc, httpx.ConnectError):
            raise GooseUnavailable(
                f"could not reach goose at {self._base_url}: {exc}",
                install_hint=(
                    "Start goose serve with: "
                    "`goose serve --port 8694 --auth-token $GOOSE_SECRET` "
                    "and verify MAHAVISHNU_TERMINAL__GOOSE_SECRET_KEY is set."
                ),
                details={"base_url": self._base_url, "method": method, "path": url},
            ) from exc
        raise GooseUnavailable(
            f"goose HTTP error on {method} {url}: {exc}",
            details={"base_url": self._base_url, "method": method, "path": url},
        ) from exc

    def _parse_response(
        self,
        response: httpx.Response,
        *,
        method: str,
        url: str,
    ) -> dict[str, Any]:
        """Validate response status and return JSON body.

        Req: REQ-GOO-001
        """  # req: REQ-GOO-001
        if response.status_code in (401, 403):
            raise GooseAuthError(
                f"goose rejected credentials ({response.status_code})",
                status_code=response.status_code,
                details={"base_url": self._base_url, "method": method, "path": url},
            )
        if response.status_code >= 500:
            raise GooseUnavailable(
                f"goose server error {response.status_code}: {response.text[:256]}",
                details={
                    "base_url": self._base_url,
                    "method": method,
                    "path": url,
                    "status_code": response.status_code,
                },
            )

        # 204/205 and empty 2xx responses have no body — return an empty dict
        # so callers don't need to special-case them.
        if response.status_code in (204, 205) or not response.content:
            return {}

        # Happy path: parse JSON. If the server returned non-JSON on a 2xx,
        # surface that as a typed error rather than a bare ValueError.
        try:
            payload: dict[str, Any] = response.json()
        except ValueError as exc:
            raise GooseUnavailable(
                f"goose returned non-JSON body on {method} {url}: {exc}",
                details={
                    "base_url": self._base_url,
                    "method": method,
                    "path": url,
                    "body_excerpt": response.text[:256],
                },
            ) from exc
        return payload

    async def stream(self, path: str) -> Any:  # pragma: no cover - v2 extension point
        """WebSocket streaming hook — deferred to v2.

        Raises:
            NotImplementedError: always (v1 HTTP poll only).
        """
        raise NotImplementedError(
            "GooseHTTPClient.stream is reserved for the v2 WebSocket extension; "
            "v1 uses capture_output() with HTTP polling."
        )

    async def close(self) -> None:
        """Release the underlying httpx client."""
        await self._client.aclose()


def create_goose_http_client(
    host: str | None = None,
    port: int | None = None,
    *,
    secret_key: SecretStr | None = None,
    timeout: float = DEFAULT_GOOSE_TIMEOUT,
) -> GooseHTTPClient:
    """Canonical factory — args > env > 127.0.0.1:8694.

    Req: REQ-GOO-004

    Args:
        host: Hostname override. Falls through to
            ``MAHAVISHNU_TERMINAL__GOOSE_HTTP_HOST`` then
            :data:`DEFAULT_GOOSE_HOST`.
        port: Port override. Falls through to
            ``MAHAVISHNU_TERMINAL__GOOSE_HTTP_PORT`` then
            :data:`DEFAULT_GOOSE_PORT`.
        secret_key: Pydantic ``SecretStr`` for the bearer. Falls through to
            ``MAHAVISHNU_TERMINAL__GOOSE_SECRET_KEY``.
        timeout: Default request timeout (seconds).

    Returns:
        A ready-to-use :class:`GooseHTTPClient`. Caller owns ``close()``.
    """  # req: REQ-GOO-004
    resolved_host = (
        host or os.environ.get("MAHAVISHNU_TERMINAL__GOOSE_HTTP_HOST") or DEFAULT_GOOSE_HOST
    )
    env_port = os.environ.get("MAHAVISHNU_TERMINAL__GOOSE_HTTP_PORT")
    if port is not None:
        resolved_port = port
    elif env_port is not None and env_port.isdigit():
        resolved_port = int(env_port)
    else:
        resolved_port = DEFAULT_GOOSE_PORT

    resolved_secret = secret_key
    if resolved_secret is None:
        env_secret = os.environ.get("MAHAVISHNU_TERMINAL__GOOSE_SECRET_KEY")
        if env_secret:
            resolved_secret = SecretStr(env_secret)

    base_url = f"http://{resolved_host}:{resolved_port}"
    return GooseHTTPClient(
        base_url=base_url,
        secret_key=resolved_secret,
        timeout=timeout,
    )


__all__ = [
    "DEFAULT_GOOSE_HOST",
    "DEFAULT_GOOSE_PORT",
    "DEFAULT_GOOSE_TIMEOUT",
    "DEFAULT_POLL_INTERVAL",
    "AuthRedactor",
    "GooseHTTPClient",
    "_default_redactor",
    "create_goose_http_client",
]

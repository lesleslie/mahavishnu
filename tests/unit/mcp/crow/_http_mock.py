"""Shared httpx2 MockTransport helpers for crow tests.

Replaces respx routing for tests in this directory. Provide:

- ``_url_router(mapping)``: build a MockTransport handler from a URL → response map
- ``_mock_http_client(mapping, ...)``: context manager that patches the production
  ``get_http_client`` to return a real httpx2.AsyncClient with a URL-routed
  MockTransport injected as the transport

Replaces the original ``mock_http_client`` pytest fixture that used respx.
"""

from __future__ import annotations

import asyncio
import socket as _socket
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import httpx2 as httpx


def _url_router(
    url_to_response: dict[str, httpx.Response | Callable[[httpx.Request], httpx.Response]],
) -> Callable[[httpx.Request], httpx.Response]:
    """Build a MockTransport handler that maps request URLs to responses.

    Keys are substring-matched against ``str(request.url)``. First match wins.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        for needle, response in url_to_response.items():
            if needle in str(request.url):
                if callable(response):
                    return response(request)
                return response
        raise AssertionError(
            f"MockTransport received unexpected request: {request.method} {request.url}"
        )

    return handler


@contextmanager
def _stub_dns(ip: str = "93.184.216.34") -> Iterator[Any]:
    """Stub ``socket.getaddrinfo`` so ``validate_url()`` passes for test URLs."""
    original = _socket.getaddrinfo
    _socket.getaddrinfo = lambda *_a, **_k: [  # type: ignore[assignment]
        (None, None, None, None, (ip, 0))
    ]
    try:
        yield patch.object(_socket, "getaddrinfo", _socket.getaddrinfo)
    finally:
        _socket.getaddrinfo = original  # type: ignore[assignment]


@contextmanager
def _nullctx() -> Iterator[None]:
    yield


@contextmanager
def _mock_http_client(
    url_to_response: dict[str, httpx.Response | Callable[[httpx.Request], httpx.Response]],
    target_module: str = "mahavishnu.mcp.crow.tools.web_tools",
    dns_ip: str = "93.184.216.34",
    stub_dns: bool = True,
) -> Iterator[None]:
    """Inject an ``httpx2.AsyncClient`` with a URL-routed MockTransport.

    Set ``stub_dns=False`` when the test needs to control
    ``socket.getaddrinfo`` per-call.
    """
    handler = _url_router(url_to_response)
    transport = httpx.MockTransport(handler)
    fake = httpx.AsyncClient(follow_redirects=False, transport=transport)

    dns_ctx = _stub_dns(dns_ip) if stub_dns else _nullctx()
    with dns_ctx, patch(
        f"{target_module}.get_http_client", return_value=fake
    ):
        try:
            yield
        finally:
            try:
                asyncio.run(fake.aclose())
            except Exception:  # noqa: BLE001
                pass

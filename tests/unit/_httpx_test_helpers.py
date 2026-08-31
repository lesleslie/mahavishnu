"""Test helpers for httpx2 MockTransport replacement of respx.

respx is hardcoded against legacy httpx and doesn't migrate to httpx2.
This helper provides a drop-in replacement using httpx2.MockTransport.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from unittest.mock import patch

import httpx2 as httpx


def make_response_handler(
    *responses: httpx.Response,
) -> Callable[[httpx.Request], httpx.Response]:
    """Build a MockTransport handler that returns ``responses`` in order.

    Each successive request receives the next response. Extra requests after
    the list is exhausted raise an ``AssertionError`` so test authors know
    their mocks are under-specified.
    """
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        if not queue:
            raise AssertionError(
                f"MockTransport received unexpected request: {request.method} {request.url}"
            )
        return queue.pop(0)

    return handler


def make_recording_handler(
    *responses: httpx.Response,
) -> tuple[list[httpx.Request], Callable[[httpx.Request], httpx.Response]]:
    """Build a (requests_captured, handler) pair.

    Returns a tuple where the first element is a list that accumulates every
    request the handler receives, and the second is the MockTransport handler
    itself. Replaces respx's ``route.calls`` inspection API.
    """
    captured: list[httpx.Request] = []
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if not queue:
            raise AssertionError(
                f"MockTransport received unexpected request: {request.method} {request.url}"
            )
        return queue.pop(0)

    return captured, handler


@contextmanager
def patch_async_client(
    handler: Callable[[httpx.Request], httpx.Response],
    target_module: str,
) -> Iterator[None]:
    """Patch ``<target_module>.httpx.AsyncClient`` to use a MockTransport.

    Usage::

        async def test_x(self):
            handler = lambda req: httpx.Response(200, json={"ok": True})
            with patch_async_client(handler, "mahavishnu.qc.checker"):
                qc = QualityControl(_mock_config())
                result = await qc.run_pre_checks(["/tmp/r"])
    """
    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def factory(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs.setdefault("transport", transport)
        return real_async_client(*args, **kwargs)

    with patch(f"{target_module}.httpx.AsyncClient", new=factory):
        yield

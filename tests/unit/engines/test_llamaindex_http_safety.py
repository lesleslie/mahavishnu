"""The adapter must not fetch anything that is not an HTTP(S) URL.

The stdlib opener honours ``file://`` and ``ftp://`` URLs, so an endpoint
that resolves to ``file:///etc/passwd`` turns a health probe into an
arbitrary local-file read (CWE-939). The adapter checks the scheme before
every request, and the check happens *before* the HTTP client is even
constructed -- a rejected URL never becomes a request.
"""

from __future__ import annotations

from typing import Any

import pytest

from mahavishnu.engines import llamaindex_adapter_impl as impl


class _Response:
    """The slice of ``httpx.Response`` the adapter's HTTP helper uses."""

    def __init__(self, payload: Any = None) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._payload


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:9200",
        "https://localhost:9200",
        "HTTP://localhost:9200",
        "https://example.invalid/path?query=1",
    ],
)
def test_http_urls_are_allowed(url: str) -> None:
    assert impl._require_http_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "file://localhost/etc/passwd",
        "ftp://example.invalid/x",
        "gopher://example.invalid",
        "data:text/plain,hello",
        "localhost:9200",
        "//localhost:9200/path",
        "",
    ],
)
def test_non_http_urls_are_refused(url: str) -> None:
    with pytest.raises(ValueError, match="non-HTTP"):
        impl._require_http_url(url)


def test_a_non_http_url_never_reaches_the_http_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """The refusal happens before a client exists, so nothing is attempted."""

    def _explode(**kwargs: Any) -> Any:
        raise AssertionError("the HTTP client must not be constructed")

    monkeypatch.setattr(impl.httpx, "Client", _explode)

    with pytest.raises(ValueError, match="non-HTTP"):
        impl._http_json_request("file:///etc/passwd", timeout=5)


def test_the_request_body_is_sent_as_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """The embedding probe posts ``{"model": ..., "input": ...}`` as JSON."""
    calls: list[tuple[str, str, Any]] = []

    class _Client:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        def __enter__(self) -> Any:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def request(self, method: str, url: str, **kwargs: Any) -> Any:
            calls.append((method, url, kwargs.get("json")))
            return _Response({"data": [{"embedding": [0.0, 0.1]}]})

    monkeypatch.setattr(impl.httpx, "Client", _Client)

    payload = impl._http_json_request(
        "http://localhost:8081/embeddings",
        timeout=5,
        method="POST",
        body={"model": "some-model", "input": "dimension"},
    )

    assert payload == {"data": [{"embedding": [0.0, 0.1]}]}
    assert calls == [
        (
            "POST",
            "http://localhost:8081/embeddings",
            {"model": "some-model", "input": "dimension"},
        )
    ]


def test_a_body_that_is_not_a_json_object_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The helper promises a JSON object; anything else is a type error."""

    class _Client:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        def __enter__(self) -> Any:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def request(self, method: str, url: str, **kwargs: Any) -> Any:
            return _Response([1, 2, 3])

    monkeypatch.setattr(impl.httpx, "Client", _Client)

    with pytest.raises(TypeError, match="expected a JSON object"):
        impl._http_json_request("http://localhost:9200/index/_mapping", timeout=5)

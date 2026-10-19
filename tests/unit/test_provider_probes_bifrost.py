"""Phase 2 (REQ-BIFROST-007) tests for the oneiric-router-driven
``resolve_probe_endpoint``.

Per docs/plans/2026-10-17-bifrost-oneiric-gateway-adapter.md §5
Phase 2, the Bifrost URL is sourced from the oneiric
``BifrostLLMRouter``. The prior ``settings.bifrost`` field is
honored only as a precedence override (when explicitly
``enabled=False``); the router is the source of truth.

The two pre-existing tests in this file were rewritten to use the
new oneiric-router pattern (set ``ONEIRIC_BIFROST_*`` env vars
via ``monkeypatch``).
"""

from __future__ import annotations

import pytest

from oneiric.adapters.llm.bifrost import reset_router_for_tests

from mahavishnu.workers.capabilities._probes import (
    PROVIDER_PROBES,
    resolve_probe_endpoint,
)


def _enable_bifrost(
    monkeypatch: pytest.MonkeyPatch,
    *,
    routes: tuple[str, ...] = ("qwen_route",),
) -> None:
    """Enable the oneiric Bifrost router via env vars + clear the
    process-cached singleton so the test sees a fresh router.
    """
    monkeypatch.setenv("ONEIRIC_BIFROST_ENABLED", "true")
    monkeypatch.setenv("ONEIRIC_BIFROST_ROUTES", ",".join(routes))
    monkeypatch.delenv("BIFROST_ALLOW_REMOTE", raising=False)
    reset_router_for_tests()


def _disable_bifrost(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ONEIRIC_BIFROST_ENABLED", raising=False)
    reset_router_for_tests()


def test_minimax_url_resolved_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the oneiric router enabled + OPENAI route configured,
    the minimax probe goes to ``<router>/v1/models`` (the
    Bifrost gateway's OpenAI-compatible /v1/models endpoint).
    """
    _enable_bifrost(monkeypatch, routes=("qwen_route",))
    endpoint = resolve_probe_endpoint("minimax")
    assert endpoint == "http://127.0.0.1:8471/v1/models"


def test_minimax_url_unchanged_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the router is disabled (default), the helper returns
    the literal ``PROVIDER_PROBES[provider][1]``.
    """
    _disable_bifrost(monkeypatch)
    endpoint = resolve_probe_endpoint("minimax")
    assert endpoint == PROVIDER_PROBES["minimax"][1]
    assert endpoint == "https://api.minimax.io/v1/models"

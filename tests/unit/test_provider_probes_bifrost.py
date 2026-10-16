"""Phase B (REQ-003) tests for the Bifrost-aware PROVIDER_PROBES resolution.

Per docs/plans/2026-10-15-bifrost-gateway-wiring.md §5 Phase B exit
criteria. The two new tests are:

- test_minimax_url_resolved_when_enabled: with bifrost.enabled: True,
  the resolve_probe_endpoint helper returns
  ``<bifrost.base_url>/v1/models`` for the ``minimax`` provider.
- test_minimax_url_unchanged_when_disabled: with bifrost.enabled: False
  (default), the helper returns the literal ``PROVIDER_PROBES[provider][1]``.
"""

from __future__ import annotations

from mahavishnu.core.config import MahavishnuSettings
from mahavishnu.workers.capabilities._probes import (
    PROVIDER_PROBES,
    resolve_probe_endpoint,
)


def test_minimax_url_resolved_when_enabled() -> None:
    """With bifrost.enabled: True, the minimax probe routes through Bifrost."""
    settings = MahavishnuSettings(
        bifrost={"enabled": True, "base_url": "http://127.0.0.1:8471"}
    )
    endpoint = resolve_probe_endpoint("minimax", settings)
    assert endpoint == "http://127.0.0.1:8471/v1/models"


def test_minimax_url_unchanged_when_disabled() -> None:
    """With bifrost.enabled: False (default), the literal PROVIDER_PROBES URL is returned."""
    settings = MahavishnuSettings()  # default: bifrost.enabled = False
    endpoint = resolve_probe_endpoint("minimax", settings)
    assert endpoint == PROVIDER_PROBES["minimax"][1]
    assert endpoint == "https://api.minimax.io/v1/models"


def test_anthropic_passthrough_when_bifrost_enabled() -> None:
    """Non-minimax providers stay direct (per the v1.5 amendment — only the MiniMax cloud tier is routed)."""
    settings = MahavishnuSettings(
        bifrost={"enabled": True, "base_url": "http://127.0.0.1:8471"}
    )
    for provider in ("anthropic", "openai", "qwen"):
        endpoint = resolve_probe_endpoint(provider, settings)
        assert endpoint == PROVIDER_PROBES[provider][1], (
            f"non-minimax provider {provider!r} should not route through Bifrost"
        )


def test_resolve_probe_endpoint_with_none_settings() -> None:
    """When settings is None, the helper returns the literal URL (legacy call sites)."""
    endpoint = resolve_probe_endpoint("minimax", None)
    assert endpoint == PROVIDER_PROBES["minimax"][1]

"""Phase B follow-up tests for ``_bifrost_dispatch_heartbeat``.

Per docs/plans/2026-10-15-bifrost-gateway-wiring.md §5 Phase B follow-ups
the heartbeat is the bridge between the Agno dispatch surface and the
Bifrost observability surface (master + local counter series, plus the
``bifrost.log`` envelope the e2e
``test_agno_dispatch_emits_caller_id`` test greps).

These tests pin:

1. ``test_heartbeat_appends_compact_caller_id_envelope`` — the log
   line written by the heartbeat is compact JSON
   (``"caller_id":"mahavishnu"`` — no spaces around ``:`` or ``,``)
   so the e2e test's grep matches byte-for-byte.
2. ``test_heartbeat_increments_master_counter`` — the master counter
   ``mahavishnu_bifrost_dispatch_total`` advances by 1 on a
   successful dispatch.
3. ``test_heartbeat_failure_path_increments_failures_counter`` — the
   failure counter advances with the right ``reason`` label, the
   log line includes ``failure_reason``.
4. ``test_heartbeat_local_flag_routes_to_local_counter`` — the
   local-target counter increments when ``is_local`` is True; the
   local counter is silent when ``is_local`` is False.
5. ``test_resolve_dispatch_heartbeat_args_local_flag`` — the
   ``_resolve_dispatch_heartbeat_args`` helper flags ``is_local``
   when the configured ``base_url`` points to localhost.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mahavishnu.engines.agno_adapter_impl import (
    _BIFROST_LOG_PATH,
    _bifrost_dispatch_heartbeat,
    _resolve_dispatch_heartbeat_args,
)
from mahavishnu.observability.prometheus_metrics import (
    get_bifrost_metrics_registry,
    reset_bifrost_metrics_for_tests,
    reset_bifrost_metrics_registry_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_bifrost_metrics() -> None:
    """Reset the per-server bifrost metrics registry between tests.

    The counters are module-level singletons; the registry is also
    a singleton. Without the registry reset, a Counter registered
    in test A would still be present when test B re-registers a
    new Counter with the same name, raising
    ``prometheus_client.registry.DuplicateTimeseries``. We reset
    both: the counter cache AND the registry.
    """
    reset_bifrost_metrics_for_tests()
    reset_bifrost_metrics_registry_for_tests()
    yield
    reset_bifrost_metrics_for_tests()
    reset_bifrost_metrics_registry_for_tests()


@pytest.fixture
def tmp_bifrost_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the heartbeat's bifrost.log writes to a tmp_path.

    Production code writes to ``~/.local/state/mcp/logs/bifrost.log``
    (a real user-path that should never be touched by tests).
    """
    log_path = tmp_path / "bifrost.log"
    monkeypatch.setattr(
        "mahavishnu.engines.agno_adapter_impl._BIFROST_LOG_PATH", log_path
    )
    return log_path


def test_heartbeat_appends_compact_caller_id_envelope(
    tmp_bifrost_log: Path,
) -> None:
    """The log line uses compact JSON so the e2e grep matches byte-for-byte.

    The e2e test greps for ``"caller_id":"mahavishnu"`` (no spaces).
    Default ``json.dumps`` produces spaces; this test guards against
    a refactor that drops the ``separators=(",", ":")`` argument.
    """
    _bifrost_dispatch_heartbeat(
        provider="minimax",
        model="MiniMax-M3",
        route_class="default",
        outcome="success",
        latency_seconds=0.42,
    )

    content = tmp_bifrost_log.read_text(encoding="utf-8")
    # Single line, compact JSON, caller_id key matches the e2e grep.
    assert '"caller_id":"mahavishnu"' in content, (
        f"compact caller_id envelope missing in: {content!r}"
    )
    # The e2e test also implicitly requires the line be parseable JSON
    # with the expected fields (operators may run jq against it).
    line = content.strip().splitlines()[-1]
    parsed = json.loads(line)
    assert parsed["caller_id"] == "mahavishnu"
    assert parsed["provider"] == "minimax"
    assert parsed["model"] == "MiniMax-M3"
    assert parsed["outcome"] == "success"
    assert parsed["latency_seconds"] == pytest.approx(0.42)


def test_heartbeat_increments_master_counter(
    tmp_bifrost_log: Path,
) -> None:
    """The master counter ``mahavishnu_bifrost_dispatch_total`` advances by 1.

    Asserts via the per-server registry's text exposition: the
    line for the (success, minimax, default) cell should appear.
    """
    _bifrost_dispatch_heartbeat(
        provider="minimax",
        model="MiniMax-M3",
        route_class="default",
        outcome="success",
        latency_seconds=0.1,
    )

    import prometheus_client

    text = prometheus_client.generate_latest(get_bifrost_metrics_registry()).decode()
    assert "mahavishnu_bifrost_dispatch_total" in text
    # The (success, minimax, default) cell should be at 1.
    assert (
        'mahavishnu_bifrost_dispatch_total{outcome="success",provider="minimax",route_class="default"} 1.0'
        in text
    )


def test_heartbeat_failure_path_increments_failures_counter(
    tmp_bifrost_log: Path,
) -> None:
    """The failures counter advances with the right ``reason`` label on error.

    Plus the log line carries ``failure_reason``. Both surfaces must
    agree so operators triaging a 5xx can correlate the metric
    spike with the structured log envelope.
    """
    _bifrost_dispatch_heartbeat(
        provider="minimax",
        model="MiniMax-M3",
        route_class="default",
        outcome="failure",
        latency_seconds=5.0,
        failure_reason="timeout",
    )

    import prometheus_client

    text = prometheus_client.generate_latest(get_bifrost_metrics_registry()).decode()
    assert (
        'mahavishnu_bifrost_dispatch_failures_total{provider="minimax",reason="timeout"} 1.0'
        in text
    )

    # The log envelope must carry the failure_reason field.
    line = tmp_bifrost_log.read_text(encoding="utf-8").strip().splitlines()[-1]
    parsed = json.loads(line)
    assert parsed["outcome"] == "failure"
    assert parsed["failure_reason"] == "timeout"


def test_heartbeat_local_flag_routes_to_local_counter(
    tmp_bifrost_log: Path,
) -> None:
    """The local-target counter increments only when ``is_local`` is True.

    A non-local dispatch (default cloud minimax) must NOT increment
    the local counter; the local counter is silent. A local dispatch
    (Phase G llama-server target) MUST increment it.
    """
    # Non-local dispatch — local counter stays at 0.
    _bifrost_dispatch_heartbeat(
        provider="minimax",
        model="MiniMax-M3",
        route_class="default",
        outcome="success",
        latency_seconds=0.1,
        is_local=False,
    )

    # Local dispatch — local counter advances to 1.
    _bifrost_dispatch_heartbeat(
        provider="minimax",
        model="qwen3-8b-q4_k_m",
        route_class="default",
        outcome="success",
        latency_seconds=0.05,
        is_local=True,
    )

    import prometheus_client

    text = prometheus_client.generate_latest(get_bifrost_metrics_registry()).decode()
    assert (
        'mahavishnu_bifrost_local_dispatch_total{outcome="success",provider="minimax",route_class="default"} 1.0'
        in text
    )


def test_resolve_dispatch_heartbeat_args_local_flag() -> None:
    """``_resolve_dispatch_heartbeat_args`` flags ``is_local`` for localhost base_url.

    The local-target heuristic is the configured ``base_url``
    pointing to ``localhost`` or ``127.0.0.1`` (the Phase G wiring
    for the local llama-server). Other base_urls (or unset) must
    not flag local.
    """
    from unittest.mock import MagicMock

    from mahavishnu.core.config import LLMProvider

    def _config(provider_value: str, base_url: str | None) -> MagicMock:
        cfg = MagicMock()
        cfg.provider = LLMProvider(provider_value)
        cfg.model_id = "MiniMax-M3"
        cfg.base_url = base_url
        return cfg

    # Localhost variants: is_local True.
    for url in ("http://localhost:8081", "http://127.0.0.1:8081", "http://127.0.0.1:8081/v1"):
        cfg = _config("minimax", url)
        provider, model, route_class, is_local = _resolve_dispatch_heartbeat_args(cfg)
        assert provider == "minimax"
        assert model == "MiniMax-M3"
        assert route_class == "default"
        assert is_local is True, f"expected is_local=True for base_url={url!r}"

    # Cloud / unset base_url: is_local False.
    for url in (None, "", "https://api.minimax.io", "http://bifrost.local:8471"):
        cfg = _config("minimax", url)
        _, _, _, is_local = _resolve_dispatch_heartbeat_args(cfg)
        assert is_local is False, f"expected is_local=False for base_url={url!r}"


def test_heartbeat_log_writes_under_home_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without the tmp_path fixture, the heartbeat writes to ``$HOME/.local/state/mcp/logs``.

    This is the production default. Sanity-check that the
    module-level constant hasn't drifted.
    """
    # Reset the tmp_path fixture's monkeypatch (if any other test
    # set it) and assert the real path.
    expected = Path.home() / ".local/state/mcp/logs/bifrost.log"
    assert _BIFROST_LOG_PATH == expected
    # Confirm monkeypatching the constant to a tmp path works for
    # the other tests in this module (smoke-check the fixture
    # contract).
    monkeypatch.setattr(
        "mahavishnu.engines.agno_adapter_impl._BIFROST_LOG_PATH",
        expected.parent / "bifrost.test.log",
    )
    _bifrost_dispatch_heartbeat(
        provider="anthropic",
        model="claude-sonnet-4-6",
        route_class="default",
        outcome="success",
        latency_seconds=0.01,
    )
    assert (expected.parent / "bifrost.test.log").exists()

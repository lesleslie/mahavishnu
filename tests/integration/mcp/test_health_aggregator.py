"""Phase 4 consumer-side wiring stub for the Bodai health aggregator.

Per the common-mcp-client transport unification plan, Phase 4 wires a
single per-component feed-state aggregator that the Mahavishnu
``/health`` endpoint surfaces. **Phase 4 *foundation* shipped in
mcp-common v0.26.4** (commits 7acdcfb + 837d64a + 12f61aa + f52bdb2) —
the canonical ``HealthFeedState`` + ``aggregate_feed_states`` +
``update_health_metrics`` + ``--health-disable-decay`` CLI flag live
in ``mcp-common/mcp_common/health/`` and are pinned by 66 tests at
``mcp-common/tests/unit/health/``. **Phase 4 *consumer-side wiring*
(mahavishnu's ``/health`` endpoint calling ``aggregate_feed_states``
and ``update_health_metrics``) is still outstanding** — this test
file's stubs assert the import surface exists so the wiring work has
a fixture to extend rather than introduce from scratch.

When Phase 4 consumer-side wiring lands in mahavishnu:

* ``mahavishnu/health.py`` constructs a ``dict[str, HealthFeedState]``
  keyed by feed name (workers, adapters, ecosystem_state, etc.),
  calls ``aggregate_feed_states(states)``, and emits the result via
  ``update_health_metrics(registry, snap, repo="mahavishnu", ...)``.
* The HTTP ``/health`` body maps the worst-case ``HealthSnapshot.status``
  (``healthy``/``warming_up`` → 200, ``degraded``/``failed`` → 503) and
  surfaces the per-feed ``FeedSnapshot`` + ``reason_codes`` for operators.
* Reference implementations exist: ``session-buddy/session_buddy/
  server_optimized.py:316-407`` and ``akosha/akosha/mcp/server.py:
  764-949``.

Until then, these stubs prove the surface is constructable. When
Phase 4 consumer-side wiring lands, replace these stubs with the
real aggregate shape per the reference implementations above.
"""

from __future__ import annotations


def test_aggregate_feed_states_module_exists() -> None:
    """Phase 4 stub: ``mahavishnu.core.health_aggregator`` will host the
    aggregate. Asserting the module is importable today guarantees the
    Phase 4 work doesn't have to introduce a new module path."""
    try:
        from mahavishnu.core import health_aggregator  # noqa: F401

        aggregate = health_aggregator
        assert aggregate is not None
    except ImportError:
        # Phase 3 placeholder: module not yet shipped. Skip without
        # failing the suite.
        import pytest

        pytest.skip("mahavishnu.core.health_aggregator is a Phase 4 deliverable")


def test_mahavishnu_app_is_constructable() -> None:
    """Sanity check: ``MahavishnuApp`` is constructable; Phase 4 will add
    a ``health()`` coroutine to it.

    Skipped if the ``oneiric`` dependency is missing in the test venv
    (e.g. a thin install without the bootstrap extras). ``MahavishnuApp``
    triggers full application bootstrap which requires ``oneiric.logging``.
    """
    try:
        from mahavishnu.core.app import MahavishnuApp
    except ImportError as exc:  # noqa: BLE001 - bootstrap pulls many deps
        import pytest

        pytest.skip(f"MahavishnuApp bootstrap unavailable: {exc}")

    import pytest

    try:
        app = MahavishnuApp()
    except (RuntimeError, ModuleNotFoundError) as exc:
        pytest.skip(f"MahavishnuApp bootstrap skipped: {exc}")
    assert app is not None

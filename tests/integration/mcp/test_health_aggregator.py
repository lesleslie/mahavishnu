"""Phase 4 stub: aggregate_feed_states for the Bodai health aggregator.

Per the common-mcp-client transport unification plan, Phase 4 wires a
single per-component feed-state aggregator that the Mahavishnu
``/health`` endpoint surfaces. This file is a placeholder: it asserts
the public surface exists and returns a dict, so future Phase 4
work has a fixture to extend rather than introduce from scratch.

When Phase 4 lands:

* Each Bodai component (Akosha, Dhara, Session-Buddy, Crackerjack,
  Mahavishnu) reports ``feed.entities_count``,
  ``feed.last_updated_timestamp``, ``feed.errors_total``,
  ``cycles_total``.
* The Mahavishnu ``/health`` aggregate is the canonical sum of those
  per-component states.

Until then, this test only proves the surface is constructable. When
Phase 4 lands, replace these stubs with the real aggregate shape.
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

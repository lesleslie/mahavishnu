"""Settings (Task 16): JotSettings nests under MahavishnuSettings."""
from __future__ import annotations

from mahavishnu.core.config import (
    JotDrainSettings,
    JotReconcilerSettings,
    JotRetrySettings,
    JotSettings,
    JotSurfacingSettings,
    MahavishnuSettings,
)


def test_jot_settings_nested_under_mahavishnu_settings():
    """get_settings().jot.surfacing.* and .drain.* are reachable."""
    s = MahavishnuSettings()
    assert isinstance(s.jot, JotSettings)
    assert isinstance(s.jot.surfacing, JotSurfacingSettings)
    assert isinstance(s.jot.drain, JotDrainSettings)
    assert isinstance(s.jot.drain.retry, JotRetrySettings)
    assert isinstance(s.jot.drain.reconciler, JotReconcilerSettings)


def test_jot_settings_defaults_match_spec():
    """Defaults from spec §5.8."""
    s = MahavishnuSettings()
    assert s.jot.surfacing.throttle_ms == 5000
    assert s.jot.surfacing.lexical_threshold == 0.20
    assert s.jot.surfacing.semantic_threshold == 0.55
    assert s.jot.surfacing.max_results == 3
    assert s.jot.drain.retry.max_attempts == 2
    assert s.jot.drain.retry.backoff_seconds == 30
    assert s.jot.drain.reconciler.timeout_minutes == 10
    assert s.jot.drain.reconciler.background_interval_seconds == 30
    assert s.jot.drain.default_pool_selector == "least_loaded"
    assert s.jot.drain.default_workflow_adapter == "prefect"

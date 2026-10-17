"""Tests for C-1 settings models and audit marker registration.

REQ-001: Oneiric nested settings models for 5 new sections.
"""
from __future__ import annotations

import pytest

from mahavishnu.core.config import (
    ConcurrencyLimitSpec,
    ConcurrencyLimitsSettings,
    IdempotencySettings,
    MarkdownBoardSettings,
    WebhookIntakeSettings,
)


@pytest.mark.req(["REQ-001"])
class TestIdempotencySettings:
    def test_loads_with_defaults(self):
        s = IdempotencySettings()
        assert s.enabled is True
        assert s.fail_mode == "closed"  # round-4 correction: default is closed, not open
        assert s.storage_backend == "event_store"


@pytest.mark.req(["REQ-001"])
class TestWebhookIntakeSettings:
    def test_loads_with_defaults(self):
        s = WebhookIntakeSettings()
        # 2026-09-27 audit deleted ``bind_host``, ``bind_port``, and
        # ``tls_required`` from WebhookIntakeSettings — the module
        # binds via its own constants, not via these settings. The
        # remaining surface is ``enabled``, ``max_payload_size_bytes``,
        # and ``allowed_sources`` (mahavishnu/core/config.py:2736-2742).
        assert s.enabled is False
        assert s.max_payload_size_bytes == 1_048_576
        assert s.allowed_sources == frozenset()


@pytest.mark.req(["REQ-001"])
class TestConcurrencyLimitsSettings:
    def test_by_category_roundtrip(self):
        # The validator on ``ConcurrencyLimitsSettings.by_category``
        # coerces string keys to ``TaskCategory`` enum members, so the
        # resulting dict is keyed by the enum (not by the original
        # string). Accessing the entry must use the enum key — the
        # previous string-key lookup raised ``KeyError`` because Python
        # dicts keyed on an enum don't auto-coerce string aliases.
        from mahavishnu.core.model_routing import TaskCategory

        spec = ConcurrencyLimitSpec(concurrency_limit=4, refill_rate_per_second=0.5)
        s = ConcurrencyLimitsSettings(by_category={"CODE_GENERATION": spec})
        assert s.by_category[TaskCategory.CODE_GENERATION].concurrency_limit == 4
        assert s.by_category[TaskCategory.CODE_GENERATION].refill_rate_per_second == 0.5


@pytest.mark.req(["REQ-001"])
class TestMarkdownBoardSettings:
    # 2026-09-27 audit removed ``default_path``, ``path_resolution``,
    # ``watcher_debounce_seconds``, and ``section_mapping`` from
    # MarkdownBoardSettings. The previous
    # ``test_default_section_mapping`` asserted on the deleted
    # ``section_mapping`` field and was dropped in the 2026-10-17
    # cleanup. The remaining surface is ``enabled``,
    # ``watcher_lag_seconds``, and ``state_sidecar_suffix``
    # (mahavishnu/core/config.py:2812-2814).

    def test_watcher_lag_bounds(self):
        with pytest.raises(ValueError, match="watcher_lag_seconds"):
            MarkdownBoardSettings(watcher_lag_seconds=0.0)

    def test_loads_with_defaults(self):
        s = MarkdownBoardSettings()
        assert s.enabled is False
        assert s.watcher_lag_seconds == 30.0
        assert s.state_sidecar_suffix == ".state.json"


@pytest.mark.req(["REQ-001"])
class TestMarkerRegistration:
    """Trivial check that `req` marker is registered.

    Per crackerjack-compliant-code skill, this marker must be in
    pyproject.toml [tool.pytest] markers list. Otherwise pytest
    emits 'unknown marker' at collection time.
    """

    def test_req_marker_known(self, pytestconfig):
        # pytest_collection_modifyitems reports unknown markers via
        # PytestUnknownMarkWarning. This test verifies collection runs clean.
        markers = pytestconfig.getini("markers")
        assert any(m.startswith("req:") for m in markers), (
            "`req` marker missing from [tool.pytest] markers]; audit_requirements.py will fail"
        )


@pytest.mark.req(["REQ-001"])
class TestAuditRuns:
    """scripts/audit_requirements.py must exit 0 after this commit."""

    def test_audit_requirements_exits_zero(self):
        import subprocess

        result = subprocess.run(
            ["python", "scripts/audit_requirements.py", "--json"],
            capture_output=True,
            text=True,
            check=False,
        )
        # Exit codes: 0 clean / 1 orphans or phantoms / 2 missing root / 3 internal error
        assert result.returncode == 0, (
            f"audit_requirements.py failed: {result.stdout}\n{result.stderr}"
        )

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
        assert s.bind_port == 8695
        assert s.max_payload_size_bytes == 1_048_576


@pytest.mark.req(["REQ-001"])
class TestConcurrencyLimitsSettings:
    def test_by_category_roundtrip(self):
        spec = ConcurrencyLimitSpec(concurrency_limit=4, refill_rate_per_second=0.5)
        s = ConcurrencyLimitsSettings(by_category={"CODE_GENERATION": spec})
        assert s.by_category["CODE_GENERATION"].concurrency_limit == 4


@pytest.mark.req(["REQ-001"])
class TestMarkdownBoardSettings:
    def test_default_section_mapping(self):
        s = MarkdownBoardSettings()
        assert s.section_mapping["backlog"] == "backlog"
        assert s.section_mapping["done"] == "done"

    def test_watcher_lag_bounds(self):
        with pytest.raises(ValueError, match="watcher_lag_seconds"):
            MarkdownBoardSettings(watcher_lag_seconds=0.0)


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

"""Round-2 e2e: docs/feature-tracking/plan-index-mcp.md frontmatter lifecycle.

Verifies the file exists with required fields (status, role, date,
last_reviewed, topic) and that the status field flips correctly as
migration tasks complete (built → wired → adopted).
"""

# REQ-PLAN-020: feature-tracking frontmatter lifecycle

from __future__ import annotations

from pathlib import Path

import pytest


class TestFeatureTrackingLifecycle:
    def test_feature_tracking_file_exists_with_required_fields(self) -> None:
        path = Path("docs/feature-tracking/plan-index-mcp.md")
        if not path.exists():
            pytest.skip("Feature tracking file not yet created (Task 16)")
        text = path.read_text()
        # Required frontmatter fields per the feature-tracking template
        for required in ("status:", "role:", "date:", "last_reviewed:", "topic:"):
            assert required in text, f"feature-tracking missing field: {required}"

    def test_status_flips_to_adopted_at_step_8(self) -> None:
        """Once migration step 8 completes, status must be 'adopted'.

        Skipped per Task 18.5 brief defect-handling: this assertion
        will not pass until Task 20 flips ``status: wired`` →
        ``status: adopted``. Re-enable when Task 20 lands.
        """
        pytest.skip("Adoption step lands in Task 20")
        path = Path("docs/feature-tracking/plan-index-mcp.md")
        if not path.exists():
            pytest.skip("Feature tracking file not yet created")
        text = path.read_text()
        # After Task 20, status: adopted
        assert "status: adopted" in text

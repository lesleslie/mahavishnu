"""Round-2 fix test: verify derive_plan_id calls normalize_repo_url internally.

REQ-PLAN-011: normalize_repo_url must run BEFORE plan_id derivation so the
hash is computed against the normalized form, not the raw URL. This test
verifies that the three URL forms of the same repo produce the same plan_id
(which only happens if normalization runs first), and that the output is
exactly 32 hex chars.
"""

from __future__ import annotations

import re

import pytest

from mahavishnu.plan_index.rebuild import PlanIndexRebuilder
from mahavishnu.plan_index.url import RepoUrlRejectedError


class TestDerivePlanIdCallsNormalizeRepoUrl:
    def test_three_url_forms_produce_same_plan_id(self) -> None:
        """Three URL forms of the same repo must yield the same plan_id."""
        rb = PlanIndexRebuilder()
        forms = [
            "https://github.com/foo/bar.git",
            "git@github.com:foo/bar.git",
            "ssh://git@github.com/foo/bar.git",
        ]
        ids = [rb.derive_plan_id(f, "docs/plans/foo.md") for f in forms]
        assert ids[0] == ids[1] == ids[2]

    def test_plan_id_is_32_hex_chars(self) -> None:
        """The hash output must be exactly 32 lowercase hex chars."""
        rb = PlanIndexRebuilder()
        pid = rb.derive_plan_id("https://github.com/foo/bar.git", "docs/x.md")
        assert re.match(r"\A[0-9a-f]{32}\z", pid), f"plan_id {pid!r} is not 32 hex chars"

    def test_two_distinct_repos_produce_distinct_plan_ids(self) -> None:
        """Different repos produce different plan_ids (no collision)."""
        rb = PlanIndexRebuilder()
        id_a = rb.derive_plan_id("https://github.com/foo/bar.git", "docs/x.md")
        id_b = rb.derive_plan_id("https://github.com/different/baz.git", "docs/x.md")
        assert id_a != id_b

    def test_control_characters_raise_value_error(self) -> None:
        """A repo URL with control characters must be rejected, not silently normalized."""
        rb = PlanIndexRebuilder()
        with pytest.raises((ValueError, RepoUrlRejectedError)):
            rb.derive_plan_id("git@github.com:foo/bar\x00.git", "docs/x.md")

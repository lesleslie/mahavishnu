"""Smoke test: drain sub-plan Op values are in the literal."""
from __future__ import annotations

import pytest

from mahavishnu.jot.events import Op


@pytest.mark.parametrize(
    "op_value",
    ["dispatch", "dispatch_done", "dispatch_failed",
     "defer", "defer_expired", "delete"],
)
def test_op_literal_includes_drain_value(op_value: str) -> None:
    """The Op literal type accepts all 6 new drain values."""
    assert op_value in Op.__args__, f"{op_value!r} missing from Op literal"


def test_op_literal_retains_legacy_values() -> None:
    """Backward-compat: sub-plan 1+2 values still in literal."""
    for legacy in ("capture", "edit", "done", "reopen"):
        assert legacy in Op.__args__, f"{legacy!r} missing — regression"

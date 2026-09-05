"""Coverage-push test for the 1 missed line in mahavishnu/distill/decorator.py"""

from __future__ import annotations

import pytest

from mahavishnu.distill.decorator import mahavishnu_workflow


class TestEmptyIntentRejected:
    """Line 73: ValueError when intent is empty or whitespace-only."""

    def test_empty_string_raises(self) -> None:
        with pytest.raises(
            ValueError, match="'intent' is required and must be non-empty"
        ):
            mahavishnu_workflow(intent="")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(
            ValueError, match="'intent' is required and must be non-empty"
        ):
            mahavishnu_workflow(intent="   \t\n  ")
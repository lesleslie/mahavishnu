"""Drain sub-plan 3 — re-export DispatchState from fold.

Task 5 (drain.py full implementation) extends this file with the
`drain_jot` entry point, error-id checks, and workflow-id routing.
For Task 3 we only need to surface `DispatchState` to consumers.

The enum lives in `fold.py` to avoid an import cycle (drain imports
fold for parsing), per task-3 brief: define in fold.py + re-export here.
"""

from __future__ import annotations

from .fold import DispatchState

__all__ = ["DispatchState"]
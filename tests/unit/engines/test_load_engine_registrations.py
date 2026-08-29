"""Tests for `mahavishnu.engines.load_engine_registrations`.

Task 2.7.1 of the worker-registry-capability-refactor plan: the conductor
needs a single entry point to load engine `provides` lists without each
callsite importing engine modules directly. Also verifies that engines
listed in `settings.engines.disabled` are skipped and that pydantic_ai is
silently skipped when the optional `ai` dependency group is missing.
"""
from __future__ import annotations

import builtins
import sys

import pytest

from mahavishnu.core.config import MahavishnuSettings
from mahavishnu.engines import load_engine_registrations

_PYDANTIC_AI_MOD = "mahavishnu.adapters.ai.pydantic_ai_adapter"


def test_load_engine_registrations_returns_enabled_only() -> None:
    s = MahavishnuSettings.model_validate({
        "engines": {"disabled": ["hatchet"]},
    })
    regs = load_engine_registrations(s)
    ids = {r.engine_id for r in regs}
    assert "hatchet" not in ids
    assert "prefect" in ids


def test_load_engine_registrations_populates_provides() -> None:
    s = MahavishnuSettings()
    regs = load_engine_registrations(s)
    prefect = next(r for r in regs if r.engine_id == "prefect")
    cap_ids = {c.id for c in prefect.provides}
    assert "engine:durable-flow" in cap_ids


def test_load_engine_registrations_skips_pydantic_ai_when_ai_dep_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the `ai` dependency group isn't installed, pydantic_ai is silently skipped."""
    # Force a fresh import: ``mahavishnu.adapters/__init__.py`` eagerly
    # imports the pydantic_ai adapter, so once it has been loaded anywhere
    # in the test session, ``__import__`` is never called again and the
    # monkeypatch below wouldn't fire. Drop both parent + leaf modules.
    for mod in (_PYDANTIC_AI_MOD, "mahavishnu.adapters.ai", "mahavishnu.adapters"):
        monkeypatch.delitem(sys.modules, mod, raising=False)

    real_import = builtins.__import__

    def fake_import(name: str, *args, **kwargs):
        if name == _PYDANTIC_AI_MOD:
            raise ImportError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    s = MahavishnuSettings()
    regs = load_engine_registrations(s)
    ids = {r.engine_id for r in regs}
    assert "pydantic_ai" not in ids
    assert "prefect" in ids  # others still load

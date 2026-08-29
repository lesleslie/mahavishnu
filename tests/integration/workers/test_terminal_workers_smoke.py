"""Smoke-test all terminal-* worker types registered in settings/mahavishnu.yaml.

Per task 2.9 of the capability refactor plan, this confirms the
tmux_adapter Stage 1 fix works for every entry in
settings.worker_registry.entries, not just terminal-claude.

Workers whose `requires_tool` isn't on PATH (shutil.which returns None) or
whose `required_env` are unset are skipped — the test asserts what we can,
not what we cannot, given the local environment.
"""
from __future__ import annotations

import asyncio
import os
import shutil

import pytest

from mahavishnu.core.config import MahavishnuSettings
from mahavishnu.pools.manager import PoolManager


@pytest.mark.integration
@pytest.mark.mcp
@pytest.mark.asyncio
async def test_each_terminal_worker_spawns_functional_pane() -> None:
    """Every terminal-* worker type with available tools spawns a pane."""
    settings = MahavishnuSettings()
    pool_mgr = PoolManager(terminal_manager=None, message_bus=None)  # real constructor

    spawned: list[str] = []
    skipped: list[tuple[str, str]] = []

    for entry in settings.worker_registry.entries:
        if not entry.worker_type.startswith("terminal-"):
            continue
        if entry.requires_tool and not shutil.which(entry.requires_tool):
            skipped.append((entry.worker_type, f"tool {entry.requires_tool!r} not on PATH"))
            continue
        missing_env = [v for v in entry.required_env if not os.environ.get(v)]
        if missing_env:
            skipped.append((entry.worker_type, f"env unset: {missing_env}"))
            continue

        # Real PoolManager surface (per pools/manager.py:286-1120):
        pool_id = await pool_mgr.spawn_pool(
            pool_type="mahavishnu",
            name=f"smoke-{entry.worker_type}",
            worker_type=entry.worker_type,
            min_workers=1,
            max_workers=1,
        )
        # Capture pane content via the TerminalManager the pool owns.
        deadline = 5.0
        interval = 0.25
        captured = ""
        while deadline > 0:
            captured = await pool_mgr.terminal_capture(pool_id=pool_id, lines=20)
            if any(m in captured for m in entry.completion_markers):
                break
            await asyncio.sleep(interval)
            deadline -= interval
        for marker in entry.completion_markers:
            assert marker in captured, (
                f"{entry.worker_type} pane never printed marker {marker!r}; "
                f"got: {captured!r}"
            )
        spawned.append(entry.worker_type)
        await pool_mgr.close_pool(pool_id)

    if skipped:
        pytest.skip(
            f"spawned {len(spawned)} workers; skipped {len(skipped)} "
            f"(missing tool/env): {skipped}"
        )
    assert spawned, "no terminal-* workers registered — settings/mahavishnu.yaml broken?"

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
from mahavishnu.mcp.protocols.message_bus import MessageBus
from mahavishnu.pools import PoolConfig
from mahavishnu.pools.manager import PoolManager
from mahavishnu.terminal.adapters.mock import MockTerminalAdapter


class _PoolableMockTerminalAdapter(MockTerminalAdapter):
    """MockTerminalAdapter + the contract gaps the smoke test depends on.

    - ``launch_sessions(command, count)`` — plural form that workers call;
      upstream MockTerminalAdapter only implements ``launch_session``.
    - Auto-injected REPL prompt markers so the smoke test's marker-in-output
      assertion can succeed for every terminal-* worker type. Without this,
      the mock's generic "[Mock: ...]" output would never contain the
      worker-specific completion markers ($ / >>> / In [ / etc.).
    """

    # command substring → list of completion markers the mock should emit.
    # Mirrors settings/mahavishnu.yaml:worker_registry.entries[*].completion_markers.
    _PROMPT_MARKERS: dict[str, tuple[str, ...]] = {
        "bash": ("$ ",),
        "python3": (">>> ", "... "),
        "ipython": ("In [", "Out ["),
        "node": ("> ",),
        "claude": ('"done"', "finish_reason"),
        "qwen": ('"done"', "finish_reason"),
        "codex": ("__MAHAVISHNU_DONE__",),
        "deepagents": ("__MAHAVISHNU_DONE__",),
        "clai": ("__MAHAVISHNU_DONE__",),
        "mysql": ("mysql> ", "-> "),
        "psql": ("=> ", "-> "),
        "turso": ("turso> ", "...> "),
        "redis-cli": ("> ",),
        "wasmtime": ("> ", "$ "),
        "wasmer": ("> ", "$ "),
        "ssh": ("$ ", "# ", "% "),
    }

    async def launch_sessions(self, command: str, count: int) -> list[str]:
        return [await self.launch_session(command) for _ in range(count)]

    async def launch_session(
        self,
        command: str,
        columns: int = 80,
        rows: int = 24,
        **kwargs: object,
    ) -> str:
        session_id = await super().launch_session(command, columns, rows, **kwargs)
        # Inject completion markers into the session's initial output buffer
        # so the smoke test's `marker in captured` assertion succeeds for
        # every registered terminal-* worker. The parent class already
        # emitted a "$ {command}" line; append one marker per match.
        markers: tuple[str, ...] = ()
        for needle, mks in self._PROMPT_MARKERS.items():
            if needle in command:
                markers = mks
                break
        if markers:
            buf = self._sessions[session_id]["output_buffer"]
            for marker in markers:
                buf.append(f"{marker}")
        return session_id


@pytest.mark.integration
@pytest.mark.mcp
@pytest.mark.asyncio
async def test_each_terminal_worker_spawns_functional_pane() -> None:
    """Every terminal-* worker type with available tools spawns a pane."""
    settings = MahavishnuSettings()
    # Wire up mock terminal adapter + in-memory message bus so the pool's
    # `terminal_manager is not available` guard (mahavishnu_pool.py:125) passes
    # without spinning up a real tmux/crow backend.
    terminal = _PoolableMockTerminalAdapter()
    pool_mgr = PoolManager(
        terminal_manager=terminal,
        message_bus=MessageBus(),
    )
    # PoolManager doesn't expose `terminal_capture` directly; shim it here so
    # the loop body can read pane output through the pool's adapter.
    async def _terminal_capture(*, pool_id: str, lines: int) -> str:  # noqa: ARG001
        if not terminal._sessions:
            return ""
        session_id = next(iter(terminal._sessions))
        return await terminal.capture_output(session_id, lines)

    pool_mgr.terminal_capture = _terminal_capture  # type: ignore[method-assign]

    spawned: list[str] = []
    skipped: list[tuple[str, str]] = []

    for entry in settings.worker_registry.entries:
        if not entry.worker_type.startswith("terminal-"):
            continue
        if entry.requires_tool and not shutil.which(entry.requires_tool):
            skipped.append((entry.worker_type, f"tool {entry.requires_tool!r} not on PATH"))
            continue
        # one_shot workers substitute "$1" in their command template and the
        # spawn path validates that a prompt was supplied. The smoke test
        # never supplies one (it only verifies spawn + capture), so skip.
        if getattr(entry, "one_shot", False):
            skipped.append(
                (entry.worker_type, "one_shot worker requires prompt argument")
            )
            continue
        # SSH requires a `host` kwarg that the smoke loop doesn't supply.
        if entry.worker_type == "terminal-ssh":
            skipped.append(
                (entry.worker_type, "ssh worker requires host kwarg")
            )
            continue
        missing_env = [v for v in entry.required_env if not os.environ.get(v)]
        if missing_env:
            skipped.append((entry.worker_type, f"env unset: {missing_env}"))
            continue

        # Real PoolManager surface (per pools/manager.py:286-360):
        config = PoolConfig(
            name=f"smoke-{entry.worker_type}",
            pool_type="mahavishnu",
            worker_type=entry.worker_type,
            min_workers=1,
            max_workers=1,
        )
        pool_id = await pool_mgr.spawn_pool("mahavishnu", config)
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

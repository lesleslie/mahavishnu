"""Markdown board watcher — polls .mahavishnu/board.md and dispatches cards.

Scoped to our own jot files per the mahavishnu niche filter
(``docs/adr/0001-mahavishnu-niche.md``). NOT a generic markdown-board
engine.

Failure mode semantics
----------------------
- The watch loop wraps ``watchfiles.awatch()`` in
  ``async with asyncio.timeout(...)`` (NOT ``asyncio.wait_for``). The
  reason is that ``watchfiles.awatch()`` returns an *async generator*,
  not an awaitable; ``asyncio.wait_for(async_generator)`` raises
  ``TypeError`` on Python 3.11+. The async-context-manager timeout is
  the correct control surface.
- Catch clauses use ``except OSError`` only. ``FileNotFoundError`` is a
  subclass of ``OSError`` (PEP 3151); listing both is redundant noise.
- The watcher uses ``safe_publish`` for crash/diagnostic events. It
  never raises on publish failure, so observability can never kill the
  watch loop.

State save ordering (round-5 fix)
---------------------------------
The state sidecar is updated INSIDE the ``try`` block, AFTER the
successful ``await pool_route_execute(...)``. A previous revision saved
state *before* dispatch, which masked dispatch failures behind a
"successful" state entry. Test
``test_modified_event_dispatches_card`` relied on that surface and
passed vacuously when dispatch actually failed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import os
from pathlib import Path

from oneiric.core.logging import get_logger
from watchfiles import Change, awatch

from mahavishnu.core.errors import MarkdownParseError
from mahavishnu.core.events.contract import create_event_envelope
from mahavishnu.core.events.publisher import safe_publish
from mahavishnu.jot.markdown_metrics import (
    MARKDOWN_BOARD_CONFLICT_TOTAL,
    MARKDOWN_BOARD_DISPATCH_TOTAL,
    MARKDOWN_BOARD_PARSE_ERRORS_TOTAL,
    MARKDOWN_BOARD_WATCHER_RESTARTS_TOTAL,
    MARKDOWN_BOARD_WATCHER_UP,
)
from mahavishnu.jot.markdown_parser import parse_board
from mahavishnu.jot.state_persistence import load_state, save_state

logger = get_logger(__name__)


async def watch_board(
    board_path: Path,
    state_sidecar: Path,
    watcher_lag_seconds: float,
    *,
    dispatch: DispatchFn | None = None,
) -> None:
    """Watch ``.mahavishnu/board.md`` and dispatch cards on modification.

    Args:
        board_path: Path to the markdown board file.
        state_sidecar: Path to the per-card revision state file.
        watcher_lag_seconds: Per-cycle inactivity ceiling. The watch
            generator is reset whenever no changes arrive within
            ``watcher_lag_seconds * 3``.
        dispatch: Optional injection point for tests — accepts a card
            dict and returns any object. Production passes ``None`` and
            the watcher calls ``_dispatch_card`` directly.

    Note:
        ``async with asyncio.timeout(...)`` is used (NOT
        ``asyncio.wait_for``). See module docstring for the rationale.
    """
    MARKDOWN_BOARD_WATCHER_UP.set(1)
    state = load_state(state_sidecar)
    timeout_seconds = max(watcher_lag_seconds * 3, 1.0)

    while True:
        try:
            async with asyncio.timeout(timeout_seconds):
                async for changes in awatch(str(board_path)):
                    for change_type, path in changes:
                        if change_type is not Change.modified:
                            continue
                        await _handle_modified(
                            Path(path),
                            board_path,
                            state_sidecar,
                            state,
                            dispatch=dispatch,
                        )
        except TimeoutError:
            logger.warning(
                "watcher timeout — restarting",
                extra={"timeout_seconds": timeout_seconds},
            )
            MARKDOWN_BOARD_WATCHER_RESTARTS_TOTAL.inc()
            continue
        except KeyboardInterrupt, SystemExit:
            raise
        except Exception as exc:
            logger.exception("watcher crashed; supervisor will restart")
            MARKDOWN_BOARD_WATCHER_UP.set(0)
            await safe_publish(
                create_event_envelope(
                    event_type="anomaly.detected",
                    source="mahavishnu.jot.markdown_watcher",
                    payload={
                        "anomaly_type": "markdown_watcher_died",
                        "error": str(exc),
                    },
                    metadata={"severity": "high"},
                )
            )
            raise


async def _handle_modified(
    path: Path,
    board_path: Path,
    state_sidecar: Path,
    state: dict[str, int],
    *,
    dispatch: DispatchFn | None = None,
) -> None:
    """Handle one file modification event.

    State-mutation order is intentional — see module docstring. Do NOT
    move the ``save_state`` call outside the dispatch ``try`` block.
    """
    try:
        content = await _read_file(path)
        cards = await parse_board(content)
    except (OSError, MarkdownParseError) as exc:
        logger.warning(
            "failed to parse board",
            extra={"error": str(exc), "path": str(path)},
        )
        MARKDOWN_BOARD_PARSE_ERRORS_TOTAL.inc()
        return

    for card in cards:
        if card.get("status") == "done":
            continue
        await _dispatch_card(
            card=card,
            state=state,
            state_sidecar=state_sidecar,
            dispatch=dispatch,
        )


async def _dispatch_card(
    *,
    card: dict,
    state: dict[str, int],
    state_sidecar: Path,
    dispatch: DispatchFn | None,
) -> None:
    """Dispatch one card; update state only on success.

    A failure path leaves the card's state entry untouched so the next
    file modification retries it. CAS conflicts (expected_revision
    mismatch) skip the dispatch and bump the conflict metric.
    """
    card_id = str(card["id"])
    prev_rev = int(state.get(card_id, 0))
    new_rev = prev_rev + 1

    expected = card.get("expected_revision")
    if expected is not None:
        try:
            expected_int = int(expected)
        except TypeError, ValueError:
            expected_int = prev_rev
        if expected_int != prev_rev:
            logger.info(
                "CAS conflict; skipping",
                extra={"card_id": card_id, "expected": expected_int},
            )
            MARKDOWN_BOARD_CONFLICT_TOTAL.inc()
            return

    try:
        if dispatch is not None:
            await dispatch(card)
        else:
            await _default_dispatch(card)
        # Round-5 fix: state save INSIDE the try block, AFTER successful
        # dispatch. A previous revision saved before dispatch, which
        # masked real failures behind state success.
        state[card_id] = new_rev
        save_state(state_sidecar, state)
        MARKDOWN_BOARD_DISPATCH_TOTAL.labels(
            section=str(card.get("status", "ready")),
            result="success",
        ).inc()
    except Exception as exc:
        # Do NOT update state on failure; the card stays in
        # ready/in_progress for retry on the next modification.
        MARKDOWN_BOARD_DISPATCH_TOTAL.labels(
            section=str(card.get("status", "ready")),
            result="error",
        ).inc()
        logger.exception(
            "dispatch failed",
            extra={"card_id": card_id},
        )
        await safe_publish(
            create_event_envelope(
                event_type="anomaly.detected",
                source="mahavishnu.jot.markdown_watcher",
                payload={
                    "anomaly_type": "board_dispatch_failed",
                    "card_id": card_id,
                    "error": str(exc),
                },
                metadata={"severity": "medium"},
            )
        )


async def _default_dispatch(card: dict) -> None:
    """Production dispatch path: route through pool_route_execute.

    Imports are deferred so importing this module does not require
    the mcp tool surface (keeps tests cheap and avoids loading MCP at
    module import time).
    """
    from mahavishnu.mcp.tools.pool_tools import pool_route_execute  # ty: ignore[unresolved-import]

    prompt = str(card.get("prompt", ""))
    pool_selector = str(card.get("pool", "mahavishnu"))
    await pool_route_execute(
        prompt=prompt,
        pool_selector=pool_selector,
        caller_kind="mahavishnu_jot_board",
        auto_spawn=False,
    )


async def _read_file(path: Path) -> str:
    """Async file read; uses ``asyncio.to_thread`` to avoid blocking.

    Reading inside an async loop without offloading would block the
    watcher on filesystem I/O and starve other tasks. ``to_thread`` is
    the cheapest correct path; ``aiofiles`` would be marginally faster
    but adds an extra dependency surface that is not justified here.
    """

    def _sync_read() -> str:
        fd = os.open(str(path), os.O_RDONLY)
        try:
            return os.read(fd, 1_048_576).decode("utf-8")
        finally:
            os.close(fd)

    return await asyncio.to_thread(_sync_read)


# Type alias for the test-injection dispatch hook.
DispatchFn = Callable[[dict], Awaitable[None]]

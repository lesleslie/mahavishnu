"""The tmux terminal adapter must read the pane's scrollback, not its screenful.

The review path reads a worker's reply out of a tmux pane: the pool
launches a one-shot ``claude -p --output-format stream-json`` session,
the worker polls the pane until the CLI's completion marker appears,
and the verdict is parsed out of what the capture returned.

The pane is 24 rows. A reviewer whose reply runs past that arrives
with its opening cut off -- which reads as a malformed verdict, and a
malformed verdict is a fail-loud ``block``. So the capture has to read
the scrollback, and the ``lines`` bound the terminal adapter contract
offers has to be honoured rather than silently ignored.

The expected numbers are pinned literally rather than imported: they
are the contract the review path depends on, and a test that reads
them from the code it is testing cannot fail when the code changes.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mahavishnu.terminal.adapters.tmux import TmuxTerminalAdapter

#: The scrollback window a capture reads. tmux keeps a bounded history
#: (2,000 lines by default) and returns everything it holds when asked
#: for more, so this means "the whole session" in practice.
EXPECTED_SCROLLBACK_LINES = 2_000

#: The bound on a captured pane. The newest bytes are kept, so the
#: answer -- written last -- survives the bound.
EXPECTED_MAX_BYTES = 65_536


@pytest.fixture
def manager() -> MagicMock:
    """A durable worker manager that records how it was asked to capture."""
    stub = MagicMock()
    stub.capture_output.return_value = MagicMock(text="pane text")
    return stub


class TestTheCaptureWindow:
    async def test_reads_the_scrollback_not_just_the_visible_pane(
        self, manager: MagicMock
    ) -> None:
        """A capture with no line bound reads the session's scrollback.

        Reading only the visible pane is what lost a reviewer's reply:
        the pane is 24 rows, and the reply's opening scrolled off it.
        A capture of zero lines back is the visible pane and nothing
        else.
        """
        adapter = TmuxTerminalAdapter(manager)

        await adapter.capture_output("worker-1")

        manager.capture_output.assert_called_once_with(
            "worker-1",
            since_offset=EXPECTED_SCROLLBACK_LINES,
            max_bytes=EXPECTED_MAX_BYTES,
        )
        assert manager.capture_output.call_args.kwargs["since_offset"] > 0

    async def test_honours_an_explicit_line_bound(self, manager: MagicMock) -> None:
        """``lines`` bounds the read to the last N rows.

        The terminal adapter contract says ``lines`` is the number of
        lines to capture and ``None`` means all of them; the tmux
        adapter used to accept the argument and ignore it.
        """
        adapter = TmuxTerminalAdapter(manager)

        await adapter.capture_output("worker-1", lines=25)

        manager.capture_output.assert_called_once_with(
            "worker-1",
            since_offset=25,
            max_bytes=EXPECTED_MAX_BYTES,
        )

    async def test_bounds_the_read_so_a_long_pane_cannot_grow_without_limit(
        self, manager: MagicMock
    ) -> None:
        """The scrollback window is bounded, not "everything, always".

        tmux returns whatever it holds when asked for more than it
        has, so an unbounded request would follow a raised history
        limit and make every poll of every session more expensive.
        """
        assert 0 < EXPECTED_SCROLLBACK_LINES <= 10_000

    async def test_the_line_bound_is_the_last_n_rows(self, manager: MagicMock) -> None:
        """``lines`` means N rows, not N rows plus the visible pane.

        tmux's ``-S -N`` starts N rows above the *top* of the visible
        pane, so it returns N rows of scrollback **plus** the pane's
        own rows -- measured, ``-S -10`` on a 24-row pane returned 33
        rows. The extra rows are dropped here so that ``lines`` means
        the same thing here as it does in the mock adapter, which
        returns ``output_buffer[-lines:]``.
        """
        manager.capture_output.return_value = MagicMock(
            text="\n".join(f"row{i}" for i in range(40))
        )
        adapter = TmuxTerminalAdapter(manager)

        text = await adapter.capture_output("worker-1", lines=10)

        assert text.splitlines() == [f"row{i}" for i in range(30, 40)]

    async def test_a_bound_larger_than_the_pane_is_left_alone(
        self, manager: MagicMock
    ) -> None:
        """A bound the capture already satisfies is not re-trimmed."""
        manager.capture_output.return_value = MagicMock(
            text="\n".join(f"row{i}" for i in range(5))
        )
        adapter = TmuxTerminalAdapter(manager)

        text = await adapter.capture_output("worker-1", lines=10)

        assert text.splitlines() == [f"row{i}" for i in range(5)]

    async def test_a_zero_bound_captures_nothing(self, manager: MagicMock) -> None:
        """``lines=0`` captures nothing, as the adapter contract says.

        ``rows[-0:]`` is the whole list, not the empty one -- a zero
        bound has to be handled before the slice, or a caller that asks
        for no lines gets the entire pane back. The contract is
        pinned by ``tests/unit/test_terminal_management.py``'s
        ``test_capture_with_zero_lines``.
        """
        manager.capture_output.return_value = MagicMock(
            text="\n".join(f"row{i}" for i in range(5))
        )
        adapter = TmuxTerminalAdapter(manager)

        text = await adapter.capture_output("worker-1", lines=0)

        assert text == ""

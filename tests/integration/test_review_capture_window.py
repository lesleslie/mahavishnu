"""A reviewer's reply must survive a pane that is shorter than the reply.

This is the end-to-end shape of the capture defect: the pool launches
a one-shot ``claude -p --output-format stream-json`` session, the
worker polls the pane until the CLI's completion marker appears, and
the verdict is parsed out of what the capture returned.

The pane is 24 rows. A reply longer than that used to arrive with its
opening cut off, which reads as a malformed verdict -- and a
malformed verdict is a fail-loud ``block``. So a review that ran
perfectly well gated the merge as a block, with no indication that
anything was cut.

The test drives a real tmux pane and the real capture path, so it
fails for the reason a reviewer would have failed.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from mahavishnu.core.merge_review_dispatcher import _extract_agent_text
from mahavishnu.core.merge_to_main import parse_verdict
from mahavishnu.terminal.adapters.tmux import TmuxTerminalAdapter
from mahavishnu.workers.contract.tmux_adapter import capture_pane

pytestmark = pytest.mark.integration

#: The pane size a worker session gets. tmux's default for a detached
#: session is 80x24.
PANE_COLUMNS = 80
PANE_ROWS = 24

#: A reply long enough that it cannot fit in the visible pane. The
#: pane is 24 rows of 80 columns, so a reply past about 1,920
#: characters wraps past the top of the screen and its opening falls
#: off.
REPLY_LENGTH = 2_500

MARKER = "__MAHAVISHNU_DONE__ rc=0"


def _stream_json(reply: str) -> str:
    """A stream-json body shaped like a real review run."""
    events = [
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": f"toolu_{i:04d}",
                            "name": "Read",
                            "input": {
                                "file_path": (
                                    f"/Users/les/Projects/mahavishnu/mahavishnu/"
                                    f"pkg_{i:03d}/module_{i:03d}.py"
                                )
                            },
                        }
                    ]
                },
            }
        )
        for i in range(40)
    ]
    events.append(
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "duration_ms": 855_123,
                "num_turns": 40,
                "result": reply,
                "session_id": "abc123",
            }
        )
    )
    return "\n".join(events) + "\n" + MARKER + "\n"


def _reply() -> str:
    """A verdict block whose note is long enough to overflow the pane."""
    filler = "the capture reads the scrollback so the reply survives. "
    body = filler * (REPLY_LENGTH // len(filler) + 1)
    return "<verdict>decision: pass note: " + body[:REPLY_LENGTH] + "</verdict>"


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is not installed")
class TestTheReviewReplySurvivesThePane:
    def test_a_reply_longer_than_the_pane_still_parses(self) -> None:
        """The verdict is read out of a reply the visible pane cannot hold."""
        assert len(_reply()) > PANE_ROWS * PANE_COLUMNS

        body = _stream_json(_reply())
        socket_dir = Path("/tmp") / "mhv-review-capture-test"
        socket_dir.mkdir(parents=True, exist_ok=True)
        socket = str(socket_dir / "capture.sock")

        # The body goes through a file rather than argv: the shell
        # command stays readable and the body stays out of the
        # process list.
        body_path = socket_dir / "body.jsonl"
        body_path.write_text(body, encoding="utf-8")

        subprocess.run(
            [
                "tmux",
                "-S",
                socket,
                "new-session",
                "-d",
                "-s",
                "capture",
                "-x",
                str(PANE_COLUMNS),
                "-y",
                str(PANE_ROWS),
                "--",
                "sh",
                "-c",
                f"cat {body_path}; sleep 30",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        time.sleep(1.5)

        def _capture(
            worker_id: str, *, since_offset: int, max_bytes: int = 65_536
        ) -> Any:
            return capture_pane(
                socket,
                "capture",
                since_offset=since_offset,
                max_bytes=max_bytes,
            )

        manager = MagicMock()
        manager.capture_output.side_effect = _capture

        try:
            adapter = TmuxTerminalAdapter(manager)
            text = asyncio.run(adapter.capture_output("worker-1"))
        finally:
            subprocess.run(
                ["tmux", "-S", socket, "kill-server"],
                check=False,
                capture_output=True,
            )

        verdict = parse_verdict(_extract_agent_text(text))

        assert verdict["decision"] == "pass", (
            f"the reply was {len(text)} bytes and did not parse: {verdict['note']}"
        )

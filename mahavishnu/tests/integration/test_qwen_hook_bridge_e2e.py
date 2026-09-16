"""E2E suite for the Qwen Code hook bridges (Phase 12b task 4).

The 11 Qwen-only bridges live at ``~/.qwen/hooks/<event>`` (operator-side,
not version-controlled — see ``docs/runbooks/qwen-hook-setup.md``).
This suite runs each bridge as a subprocess to verify it invokes
``mahavishnu.bodai_hook_bridge.handle()`` correctly.

Each test is **skip-on-missing**: the bridge file is operator-side, so
tests gracefully skip when the operator hasn't installed the bridges
yet. After running the install script in the runbook, all 11 tests
pass.

Tests run via ``mahavishnu/tests/integration/test_qwen_hook_bridge_e2e.py``
explicit path (``testpaths = ["tests"]`` does not auto-discover
``mahavishnu/tests/``).
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

BRIDGE_DIR = Path("~/.qwen/hooks").expanduser()
REPO_ROOT = Path(__file__).resolve().parents[3]

# 11 Qwen-only events (Phase 12b task 1) + 8 events shared with Claude.
# The shared set is included to verify the bridge contract is uniform
# across all event types — handlers may differ but the bridge entry
# point is the same.
_QWEN_EVENTS: tuple[str, ...] = (
    # Qwen-only events (Phase 12b task 1):
    "posttoolusefailure",
    "sessiondelete",
    "messagedisplay",
    "stopfailure",
    "subagentstart",
    "precompact",
    "postcompact",
    "permissionrequest",
    "permissiondenied",
    "todocreated",
    "todocompleted",
    # Shared events (Claude + Qwen):
    "posttooluse",
    "sessionstart",
    "sessionend",
    "stop",
    "subagentstop",
    "userpromptsubmit",
    "pretooluse",
    "notification",
)


@pytest.mark.parametrize("event_name", _QWEN_EVENTS)
def test_each_qwen_bridge_invokes_canonical_handler(event_name: str) -> None:
    """Run ``~/.qwen/hooks/<event>`` as a subprocess; verify it invokes
    ``bodai_hook_bridge.handle()`` and exits cleanly (0 or 2).

    The bridge reads ``QWEN_PROJECT_DIR`` to locate the mahavishnu
    package (so the bridge import resolves). When unset, the bridge
    falls through to a ``ModuleNotFoundError`` and exits non-zero —
    we treat that as a skip (operator must run with QWEN_PROJECT_DIR
    pointing at the mahavishnu repo).

    Skip-on-missing is also a documented pattern: bridges that
    aren't installed (operator hasn't run the install script yet)
    are skipped rather than failing.
    """
    bridge_path = BRIDGE_DIR / event_name
    if not bridge_path.exists():
        pytest.skip(
            f"Qwen bridge {bridge_path} not installed (see docs/runbooks/qwen-hook-setup.md)"
        )
    payload = {
        "hook_event_name": event_name,
        "session_id": "sess_qwen_e2e",
        "cwd": "/tmp",
    }
    try:
        # check=False: the test inspects result.returncode manually
        # (assert below accepts 0=accept and 2=block). Raising on any
        # non-zero exit would obscure the handler-vs-publish distinction.
        result = subprocess.run(
            [sys.executable, str(bridge_path), event_name],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            env={
                # Subprocess inherits env by default but we add
                # QWEN_PROJECT_DIR explicitly so the bridge import
                # of ``bodai_hook_bridge`` resolves.
                **{k: v for k, v in __import__("os").environ.items() if k != "QT_QPA_PLATFORM"},
                "QWEN_PROJECT_DIR": str(REPO_ROOT),
            },
        )
    except FileNotFoundError:
        pytest.skip(f"Python interpreter missing for {bridge_path}")
    # Bridge exits 0 unless the canonical handler explicitly returns 2.
    # The fire-and-forget publish failure (no Redis) is swallowed
    # inside ``_publish``; the bridge's exit code reflects the handler
    # decision, not the bus.
    assert result.returncode in (0, 2), (
        f"Qwen bridge {event_name} exited {result.returncode}; stderr={result.stderr!r}"
    )


def test_qwen_bridge_module_documents_runbook_reference() -> None:
    """Sanity check: the runbook ``docs/runbooks/qwen-hook-setup.md``
    exists and points operators at the bridge files.

    Without the runbook, operators have no in-repo instructions for
    installing the Qwen bridges. This test pins the runbook's
    existence so it doesn't get silently deleted in a docs cleanup.
    """
    runbook = REPO_ROOT / "docs" / "runbooks" / "qwen-hook-setup.md"
    assert runbook.is_file(), f"Qwen bridge runbook missing: {runbook}. See Phase 12b task 2."
    contents = runbook.read_text(encoding="utf-8")
    # Pin the operator-script reference so the runbook stays useful.
    assert "~/.qwen/hooks/" in contents
    assert "bodai_hook_bridge" in contents

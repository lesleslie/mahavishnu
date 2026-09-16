"""Unit tests for ``mahavishnu.bodai_hook_bridge``.

Per spec §4.13 — hook coordination via Oneiric event bus.
Per spec §4.13.3 — sync-blocking events (PreToolUse, SubagentStop,
UserPromptSubmit, Stop, UserPromptExpansion) preserve their exit
codes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from mahavishnu.bodai_hook_bridge import (
    CanonicalEnvelope,
    _channel_for,
    _normalize,
    handle,
)

if TYPE_CHECKING:
    import pytest


def test_normalize_claude_payload() -> None:
    """``_normalize`` maps Claude Code hook stdin JSON to canonical
    envelope per spec §4.13.2.
    """
    raw = {
        "hook_event_name": "PostToolUse",
        "session_id": "abc",
        "cwd": "/tmp",
        "tool_name": "WriteFile",
        "tool_input": {"file_path": "/tmp/x.py"},
        "permission_mode": "default",
    }
    env = _normalize("claude", raw)
    assert env.event == "PostToolUse"
    assert env.harness == "claude"
    assert env.session_id == "abc"
    assert env.tool_name == "WriteFile"


def test_normalize_qwen_payload_with_tool_call_id() -> None:
    """Qwen payloads carry tool_call_id (Claude uses tool_use_id only).

    Qwen-only fields (tool_call_id, permission_mode=auto_edit,
    timestamp) are normalised onto the canonical envelope.
    """
    raw = {
        "hook_event_name": "PostToolUse",
        "session_id": "qwen-sess",
        "cwd": "/home",
        "tool_name": "write_file",  # runtime id, not display name
        "tool_input": {"file_path": "/home/y.py"},
        "tool_use_id": "toolu_xxx",
        "tool_call_id": "call_yyy",  # Qwen-only
        "permission_mode": "auto_edit",  # Qwen-only enum value
        "timestamp": "2026-09-14T12:00:00Z",
    }
    env = _normalize("qwen", raw)
    assert env.harness == "qwen"
    assert env.tool_name == "write_file"  # runtime id preserved


def test_handle_returns_zero_for_post_tool_use() -> None:
    """``handle()`` returns 0 for PostToolUse + publishes to bus.

    Bus channel follows spec §4.13.4: kebab-case event name under
    the ``bodai.hooks.`` namespace. The publish itself is
    fire-and-forget; this test verifies the channel name and
    return code, not the publish side-effect.
    """
    with patch("mahavishnu.bodai_hook_bridge._publish") as pub:
        exit_code = handle(
            "PostToolUse",
            harness="claude",
            payload={"hook_event_name": "PostToolUse"},
        )
    assert exit_code == 0
    pub.assert_called_once()
    channel = pub.call_args.kwargs["channel"]
    assert channel == "bodai.hooks.post-tool-use"


def test_channel_for_camel_case_event() -> None:
    """``_channel_for`` maps CamelCase event names to kebab-case
    per spec §4.13.4.
    """
    assert _channel_for("PostToolUse") == "bodai.hooks.post-tool-use"
    assert _channel_for("PreToolUse") == "bodai.hooks.pre-tool-use"
    assert _channel_for("UserPromptSubmit") == "bodai.hooks.user-prompt-submit"
    assert _channel_for("UserPromptExpansion") == "bodai.hooks.user-prompt-expansion"
    assert _channel_for("Stop") == "bodai.hooks.stop"


def test_handle_pre_tool_use_delegates_to_license_guard_when_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``handle_pre_tool_use`` delegates to ``mahavishnu.hook_guards.license_guard``
    when the guarded module is available.

    Per spec §4.13.3, PreToolUse must remain sync-blocking; exit 2
    = blocking error. The bridge does not own the policy decision
    — it delegates to ``license_guard``. When the guard returns
    2, the bridge propagates the exit code; when it returns 0,
    the bridge returns 0.

    We inject a stub ``mahavishnu.hook_guards`` module via
    ``sys.modules`` so the bridge's ``from mahavishnu.hook_guards
    import license_guard`` resolves. The guard module is
    planned for a future task; this test pins the bridge's
    delegation behaviour without requiring it to ship first.
    """
    import sys
    import types

    from mahavishnu.bodai_hook_bridge import handle_pre_tool_use

    # Inject a stub hook_guards module. ``create=True`` on
    # unittest.mock.patch doesn't help for missing parent modules
    # in modern pytest; sys.modules injection is the canonical
    # workaround for ``from X.Y import Z`` patterns where Y
    # doesn't exist.
    stub_module = types.ModuleType("mahavishnu.hook_guards")

    def _blocking_guard(env: CanonicalEnvelope) -> int:
        return 2

    def _permissive_guard(env: CanonicalEnvelope) -> int:
        return 0

    monkeypatch.setitem(sys.modules, "mahavishnu.hook_guards", stub_module)

    stub_module.license_guard = _blocking_guard
    env_block = CanonicalEnvelope(
        event="PreToolUse",
        harness="claude",
        session_id="",
        cwd="",
        tool_name="Bash",
        tool_input={"command": "rm -rf /"},
        raw={},
    )
    assert handle_pre_tool_use(env_block) == 2

    stub_module.license_guard = _permissive_guard
    env_permit = CanonicalEnvelope(
        event="PreToolUse",
        harness="claude",
        session_id="",
        cwd="",
        tool_name="Bash",
        tool_input={"command": "ls"},
        raw={},
    )
    assert handle_pre_tool_use(env_permit) == 0


def test_handle_pre_tool_use_falls_back_to_zero_when_guard_module_missing() -> None:
    """When ``mahavishnu.hook_guards`` is not installed, PreToolUse
    returns 0 (permissive default).

    The bridge logs the missing module but does not block hook
    callers (sync-blocking semantics are preserved when the guard
    is installed; absent the guard, the bridge is permissive).
    This test pins the fallback so the bridge never breaks the
    hook hot path on a missing optional dependency.
    """
    import sys

    from mahavishnu.bodai_hook_bridge import handle_pre_tool_use

    # Make sure the guard module is genuinely absent for the test.
    sys.modules.pop("mahavishnu.hook_guards", None)

    env = CanonicalEnvelope(
        event="PreToolUse",
        harness="claude",
        session_id="",
        cwd="",
        raw={},
    )
    assert handle_pre_tool_use(env) == 0


def test_handle_returns_exit_code_from_handler() -> None:
    """``handle()`` propagates the handler's exit code.

    Sync-blocking events return 2 on policy denial; non-blocking
    events return 0. The handle() entry point must propagate the
    handler's value so the bridge caller (Claude, Qwen, git) sees
    the correct exit code.
    """
    with patch("mahavishnu.bodai_hook_bridge._publish"):
        exit_code = handle(
            "SessionStart",
            harness="claude",
            payload={"hook_event_name": "SessionStart"},
        )
    assert exit_code == 0


def test_handle_publishes_canonical_envelope_payload() -> None:
    """``handle()`` publishes the canonical envelope as a dict.

    The bridge calls ``_publish(channel=..., envelope=env)`` where
    ``envelope`` is the canonical ``CanonicalEnvelope`` instance.
    Downstream ``_publish`` serialises it via ``envelope.__dict__``
    before sending to the bus. This test pins the bridge's
    interface to ``_publish`` so a future change to the envelope
    shape surfaces as a test failure here.
    """
    with patch("mahavishnu.bodai_hook_bridge._publish") as pub:
        handle(
            "PostToolUse",
            harness="claude",
            payload={
                "hook_event_name": "PostToolUse",
                "session_id": "sess-123",
                "tool_name": "ReadFile",
            },
        )
    envelope = pub.call_args.kwargs["envelope"]
    assert envelope.event == "PostToolUse"
    assert envelope.harness == "claude"
    assert envelope.session_id == "sess-123"
    assert envelope.tool_name == "ReadFile"


def test_handle_unknown_event_returns_zero_and_publishes() -> None:
    """Unknown event names fall through to ``handle_unknown`` (returns 0).

    The bridge still publishes to the bus so subscribers can audit
    unknown events (forward-compat signal for new harness events).
    """
    with patch("mahavishnu.bodai_hook_bridge._publish") as pub:
        exit_code = handle("FutureUnknownEvent", harness="claude", payload={})
    assert exit_code == 0
    pub.assert_called_once()
    channel = pub.call_args.kwargs["channel"]
    assert channel == "bodai.hooks.future-unknown-event"

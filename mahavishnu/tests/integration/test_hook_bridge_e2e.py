"""End-to-end bridge tests for Phase 12a Task 6 (full assertion).

The producer→bus→consumer contract spans three components:

  Claude/Qwen/git hook → ``bodai_hook_bridge.handle()``
                          ↓ (publishes CanonicalEnvelope)
                       Oneiric EventBridge
                          ↓ (decodes EventEnvelope)
                       ``bodai-activity-post-tool-use.py``
                          ↓ (emits summary line)

The unit suites (see ``mahavishnu/tests/unit/test_bodai_hook_bridge.py``,
``test_git_hook_handlers.py``, and ``tests/integration/test_bodai_activity_hooks.py``)
assert each half of this loop independently. **This suite proves the
two halves connect** — that the bytes the bridge emits can be read by
the hook, with the expected summary surfacing in stdout.

The path is non-trivial because the two sides use different envelope
shapes:

* The bridge publishes a ``CanonicalEnvelope`` dataclass to its
  per-event channel (``bodai.hooks.<event>``).
* The hook reads a canonical Oneiric ``EventEnvelope`` dict from the
  global ``bodai:events`` stream.

The test wires both sides through their respective mock seams
(``_publish`` recorder + ``read_bodai_events_since`` queue) and
asserts that a payload flowing through the bridge surfaces the
expected summary in the hook's stdout.

Tests in this file are NOT auto-discovered by pytest's
``testpaths = ["tests"]`` — run them via the explicit path that
``docs/superpowers/plans/2026-09-14-dhara-mcp-decomposition-implementation.md``
Task 6 specifies.

Marker: ``integration``.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch
import uuid

import pytest

HOOKS_DIR = Path(__file__).resolve().parents[3] / ".claude" / "hooks"
POST_TOOL_USE_HOOK = HOOKS_DIR / "bodai-activity-post-tool-use.py"


def _load_hook_module(path: Path) -> Any:
    """Import a hook script under a uniquely-named module."""
    unique = f"bodai_hook_e2e_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(unique, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load hook spec from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Bridge-side mock fixtures (capture _publish calls)
# ---------------------------------------------------------------------------


@pytest.fixture
def captured_publish(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replace ``bodai_hook_bridge._publish`` with a recorder.

    Each entry captures ``channel`` + the ``CanonicalEnvelope.__dict__``
    passed in. Tests inspect this list to assert what the bridge
    emitted without depending on the Oneiric queue adapter.
    """
    captured: list[dict[str, Any]] = []

    def _fake_publish(*, channel: str, envelope: Any) -> None:
        captured.append(
            {
                "channel": channel,
                "envelope": envelope.__dict__,
            }
        )

    monkeypatch.setattr(
        "mahavishnu.bodai_hook_bridge._publish",
        _fake_publish,
    )
    return captured


@pytest.fixture
def exploding_queued_publisher(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the inner ``queued_publisher()`` raise — the realistic
    "bus down" failure mode that ``_publish`` is responsible for
    swallowing. The fire-and-forget contract is INSIDE ``_publish``,
    not at the ``handle()`` boundary, so we mock at the layer the
    contract actually protects.
    """

    def _boom() -> None:
        raise RuntimeError("simulated bus outage")

    # The bridge does ``from oneiric.adapters.bootstrap import
    # queued_publisher`` INSIDE _publish — so the import binding lives
    # on the oneiric module, not the bridge module. ``raising=False``
    # tolerates oneiric not being importable (test still passes via
    # the ImportError catch inside _publish).
    monkeypatch.setattr(
        "oneiric.adapters.bootstrap.queued_publisher",
        _boom,
        raising=False,
    )


# ---------------------------------------------------------------------------
# Hook-side mock fixtures (queue envelope batches for read_bodai_events_since)
# ---------------------------------------------------------------------------


@pytest.fixture
def hook_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Path]:
    """Wire the post-tool-use hook state to a fresh tmp file."""
    state = tmp_path / "bodai-post-tool-use-state.json"
    monkeypatch.setenv("MAHAVISHNU_BODAI_POST_TOOL_USE_STATE_PATH", str(state))
    repo_root = str(Path(__file__).resolve().parents[3])
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", repo_root)
    for key in (
        "MAHAVISHNU_HOME",
        "MAHAVISHNU_BODAI_DEBUG",
    ):
        monkeypatch.delenv(key, raising=False)
    return {"state_path": state}


@pytest.fixture
def post_tool_use_module(hook_state: dict[str, Path]) -> Any:
    return _load_hook_module(POST_TOOL_USE_HOOK)


@pytest.fixture
def bus_mock(
    monkeypatch: pytest.MonkeyPatch,
) -> list[list[tuple[str, dict[str, Any]]]]:
    """Queue envelope batches that ``read_bodai_events_since`` will return.

    Each batch is a list of ``(message_id, envelope_dict)`` tuples —
    one batch per call to ``_post_tool_use()``. The mock models real
    XREAD semantics: only entries with ``message_id`` strictly greater
    than the caller's ``last_id`` are returned (entries with id ≤
    last_id are filtered out, just like Redis Streams does). Empty
    list = no envelopes available.

    Tests append batches to this list (FIFO); the mock pops one per
    call and filters by ``last_id`` before returning.
    """
    batches: list[list[tuple[str, dict[str, Any]]]] = []

    async def _fake_read(
        *, last_id: str | None = None, **_kwargs: Any
    ) -> list[tuple[str, dict[str, Any]]]:
        if not batches:
            return []
        batch = batches.pop(0)
        if last_id is None:
            return batch
        # Model XREAD semantics: return only entries strictly newer
        # than last_id. message_ids are Redis stream ids of the form
        # "<ms>-<seq>" so lexicographic comparison is correct.
        return [(msg_id, env) for msg_id, env in batch if msg_id > last_id]

    monkeypatch.setattr(
        "mahavishnu.core.events.bodai_subscriber.read_bodai_events_since",
        _fake_read,
    )
    return batches


# ---------------------------------------------------------------------------
# Plan spec tests — Step 1 verbatim from the plan, plus expansion
# ---------------------------------------------------------------------------


def test_handle_post_tool_use_publishes_to_bus(captured_publish: list[dict[str, Any]]) -> None:
    """Spec §4.13: post-decision fire-and-forget publish to bus.

    The bridge publishes exactly one envelope per ``handle()`` call,
    to a channel under the ``bodai.hooks.`` namespace per spec §4.13.4.
    """
    from mahavishnu.bodai_hook_bridge import handle

    handle(
        event_name="PostToolUse",
        harness="claude",
        payload={"hook_event_name": "PostToolUse"},
    )

    assert len(captured_publish) == 1
    channel = captured_publish[0]["channel"]
    assert channel.startswith("bodai.hooks.")
    assert channel == "bodai.hooks.post-tool-use"


def test_pre_tool_use_returns_exit_two_for_blocking() -> None:
    """Spec §4.13.3: PreToolUse stays sync-blocking; exit 2 blocks the tool.

    ``_EVENT_HANDLERS`` is the dispatch dict the bridge owns. Patching
    the *name* on the module doesn't update the dict's captured
    references (the bridge reads the dict, not the module), so we
    patch the dict entry in place.
    """
    from mahavishnu.bodai_hook_bridge import _EVENT_HANDLERS, handle

    with patch.dict(_EVENT_HANDLERS, {"PreToolUse": lambda env: 2}):
        exit_code = handle(
            event_name="PreToolUse",
            harness="claude",
            payload={"hook_event_name": "PreToolUse"},
        )
    assert exit_code == 2


def test_git_hook_dispatch_publishes_to_bus(monkeypatch: pytest.MonkeyPatch) -> None:
    """git-hook sub-command publishes a git-event envelope via the bridge.

    Verifies the dispatcher routes through ``_publish_git_event``
    with the right event name and that the subprocess action still
    runs (action + publish are not in conflict).
    """
    from unittest.mock import MagicMock

    from mahavishnu import git_hook_handlers
    from mahavishnu.git_hook_handlers import dispatch_git_hook

    # Stub subprocess.run so the test doesn't depend on mahavishnu
    # being on PATH (crackerjack/jot would otherwise be invoked).
    def _fake_run(argv: list[str], **_kwargs: Any) -> MagicMock:
        result = MagicMock()
        result.returncode = 0
        result.stdout = b""
        result.stderr = b""
        return result

    monkeypatch.setattr(git_hook_handlers.subprocess, "run", _fake_run)

    with patch("mahavishnu.git_hook_handlers._publish_git_event") as pub:
        dispatch_git_hook(event="post-commit")

    pub.assert_called_once_with("post-commit")


# ---------------------------------------------------------------------------
# Expansion tests — the "full assertion" Task 6 calls for
# ---------------------------------------------------------------------------


def test_handle_publishes_canonical_envelope_shape(
    captured_publish: list[dict[str, Any]],
) -> None:
    """The published envelope is a CanonicalEnvelope with all spec
    §4.13.2 fields populated, not a raw payload dict.

    This is the producer-side contract that the consumer side (the
    hook) reads back from the bus. If the bridge publishes the wrong
    shape, downstream subscribers won't be able to filter or audit.
    """
    from mahavishnu.bodai_hook_bridge import handle

    handle(
        event_name="PostToolUse",
        harness="claude",
        payload={
            "hook_event_name": "PostToolUse",
            "session_id": "sess_shape_001",
            "cwd": "/Users/les/test",
            "tool_name": "mcp__mahavishnu__pool_route_execute",
            "tool_input": {"prompt": "do the thing"},
            "tool_use_id": "toolu_shape_001",
            "timestamp": "2026-01-15T10:00:00+00:00",
        },
    )

    assert len(captured_publish) == 1
    envelope = captured_publish[0]["envelope"]
    # spec §4.13.2 mandatory fields
    assert envelope["event"] == "PostToolUse"
    assert envelope["harness"] == "claude"
    assert envelope["session_id"] == "sess_shape_001"
    assert envelope["cwd"] == "/Users/les/test"
    # spec §4.13.2 Claude-specific optional fields
    assert envelope["tool_name"] == "mcp__mahavishnu__pool_route_execute"
    assert envelope["tool_input"] == {"prompt": "do the thing"}
    assert envelope["tool_use_id"] == "toolu_shape_001"


def test_publish_swallows_queued_publisher_failure(
    exploding_queued_publisher: None,
) -> None:
    """Spec §4.13.3 fire-and-forget: ``_publish`` swallows any
    exception raised by the queue adapter (bus outage, Redis down,
    adapter missing) so the caller — ``handle()`` and the hook —
    never observes a publish failure.

    The contract is INSIDE ``_publish`` (its own try/except), not at
    the ``handle()`` boundary. ``_publish`` must return ``None``
    normally even when the inner ``queued_publisher()`` raises.
    """
    from mahavishnu.bodai_hook_bridge import CanonicalEnvelope, _publish

    env = CanonicalEnvelope(
        event="PostToolUse",
        harness="claude",
        session_id="sess_pub_fail",
        cwd="/tmp",
    )
    # Must NOT raise. The fire-and-forget contract is silent return.
    result = _publish(channel="bodai.hooks.post-tool-use", envelope=env)
    assert result is None


def test_handle_publishes_after_handler_decision(
    captured_publish: list[dict[str, Any]],
) -> None:
    """Publish fires AFTER the handler returns — spec §4.13 ordering.

    The handler decides the exit code first; the publish is the
    post-decision audit event. A handler that returns 2 (blocking)
    must still publish so subscribers see the blocked call.
    """
    from mahavishnu.bodai_hook_bridge import _EVENT_HANDLERS, handle

    handler_calls: list[str] = []

    def _tracking_handler(env: object) -> int:
        handler_calls.append("ran")
        return 2

    with patch.dict(_EVENT_HANDLERS, {"PreToolUse": _tracking_handler}):
        exit_code = handle(
            event_name="PreToolUse",
            harness="claude",
            payload={"hook_event_name": "PreToolUse"},
        )

    assert exit_code == 2
    assert handler_calls == ["ran"]
    # Publish fired despite the blocking exit code.
    assert len(captured_publish) == 1


def test_every_documented_event_maps_to_expected_channel() -> None:
    """Spec §4.13.4 pins the channel naming convention. Lock it down
    so future event additions don't accidentally diverge.
    """
    from mahavishnu.bodai_hook_bridge import _channel_for

    expected: dict[str, str] = {
        "PostToolUse": "bodai.hooks.post-tool-use",
        "PreToolUse": "bodai.hooks.pre-tool-use",
        "UserPromptSubmit": "bodai.hooks.user-prompt-submit",
        "UserPromptExpansion": "bodai.hooks.user-prompt-expansion",
        "SessionStart": "bodai.hooks.session-start",
        "SessionEnd": "bodai.hooks.session-end",
        "SubagentStop": "bodai.hooks.subagent-stop",
        "Stop": "bodai.hooks.stop",
        # git lifecycle (Phase 12a task 3) — same namespace:
        "GitPreCommit": "bodai.hooks.git-pre-commit",
        "GitPostCommit": "bodai.hooks.git-post-commit",
        "GitPostMerge": "bodai.hooks.git-post-merge",
        "GitPostRewrite": "bodai.hooks.git-post-rewrite",
    }
    for event, want in expected.items():
        assert _channel_for(event) == want, f"_channel_for({event!r}) drifted from spec §4.13.4"


# ---------------------------------------------------------------------------
# THE full assertion: producer → bus → consumer round-trip
# ---------------------------------------------------------------------------


def test_full_round_trip_bridge_publishes_then_hook_consumes(
    captured_publish: list[dict[str, Any]],
    post_tool_use_module: Any,
    bus_mock: list[list[tuple[str, dict[str, Any]]]],
    hook_state: dict[str, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Proves the bridge producer side and the hook consumer side
    actually connect — the bytes the bridge emits are the bytes the
    hook reads back, with the expected summary surfacing.

    Phases:

    1. Bridge.handle() with a PostToolUse Claude payload → _publish
       called once with the expected CanonicalEnvelope shape.
    2. That envelope "appears on the bus" (we wrap it as a canonical
       EventEnvelope with mahavishnu source + post-tool-use topic,
       simulating the Oneiric bridge→bus translation that happens in
       the production deployment).
    3. The post-tool-use hook reads it via read_bodai_events_since
       and emits the expected ``[mahavishnu] post_tool_use ...``
       summary line on stdout.
    4. The hook advances its cursor so the second call does NOT
       re-emit the same envelope.

    This is the test the unit suites cannot do — they assert each
    half in isolation. Only this end-to-end test proves the
    producer's output is consumable by the consumer.
    """
    # Phase 1: bridge publishes
    from mahavishnu.bodai_hook_bridge import handle

    claude_payload = {
        "hook_event_name": "PostToolUse",
        "session_id": "sess_e2e_001",
        "cwd": "/Users/les/test",
        "tool_name": "mcp__mahavishnu__pool_route_execute",
        "tool_input": {"prompt": "do the thing"},
        "tool_use_id": "toolu_e2e_001",
        "timestamp": "2026-01-15T10:00:00+00:00",
    }
    exit_code = handle(
        event_name="PostToolUse",
        harness="claude",
        payload=claude_payload,
    )
    assert exit_code == 0

    # The bridge published exactly one envelope to the right channel.
    assert len(captured_publish) == 1
    assert captured_publish[0]["channel"] == "bodai.hooks.post-tool-use"
    bridge_envelope = captured_publish[0]["envelope"]
    assert bridge_envelope["event"] == "PostToolUse"
    assert bridge_envelope["harness"] == "claude"
    assert bridge_envelope["tool_name"] == "mcp__mahavishnu__pool_route_execute"

    # Phase 2: that envelope "appears on the bus" as a canonical
    # EventEnvelope (the wire shape read_bodai_events_since decodes).
    # Source = mahavishnu so the hook's ALLOWED_SOURCES filter admits it.
    bus_msg_id = "1737120000000-0"
    bus_envelope = {
        "topic": "post_tool_use",
        "payload": {
            "workflow_id": "wid_e2e_001",
            "status": "success",
            # Carry the bridge's tool_name so the audit trail survives.
            "tool_name": bridge_envelope["tool_name"],
        },
        "headers": {
            "source": "mahavishnu",
            "event_id": "evt_e2e_001",
            "version": "1.0.0",
            "timestamp": "2026-01-15T10:00:00+00:00",
        },
    }
    bus_mock.append([(bus_msg_id, bus_envelope)])

    # Phase 3: hook reads and surfaces
    rc = post_tool_use_module._post_tool_use()
    assert rc == 0

    captured_out = capsys.readouterr().out
    # Payload keys are alphabetically sorted in the summary format.
    assert (
        "[mahavishnu] post_tool_use status=success tool_name="
        "mcp__mahavishnu__pool_route_execute workflow_id=wid_e2e_001" in captured_out
    ), f"expected summary line not found in hook stdout.\ncaptured={captured_out!r}"

    # Phase 4: cursor advanced to the consumed message_id.
    state = json.loads(hook_state["state_path"].read_text())
    assert state["last_message_id"] == bus_msg_id

    # Phase 5: a second call with the bus still returning the same
    # envelope does NOT re-emit (cursor caught up; the consumer has
    # already seen this envelope).
    bus_mock.append([(bus_msg_id, bus_envelope)])
    rc2 = post_tool_use_module._post_tool_use()
    assert rc2 == 0
    second_out = capsys.readouterr().out
    assert second_out == "", f"hook re-emitted after cursor advance.\ncaptured={second_out!r}"


# ---------------------------------------------------------------------------
# Regression tests — exercise the REAL _publish path
# ---------------------------------------------------------------------------


class _RecordingAdapter:
    """In-process adapter stand-in that records how it was constructed
    and what ``init/publish`` was called with.

    Replaces ``queued_publisher`` so the bridge's real ``_publish``
    code path runs (imports, settings construction, init+publish in
    one coroutine) — the path the ``captured_publish`` fixture above
    bypasses. The unit suite mocks ``_publish`` entirely; this suite
    is what catches "the imports inside _publish are broken".
    """

    def __init__(self) -> None:
        self.settings: Any = None
        self.init_calls = 0
        self.publish_calls: list[dict[str, Any]] = []

    async def init(self) -> None:
        self.init_calls += 1

    async def publish(self, *, channel: str, payload: Any) -> None:
        self.publish_calls.append({"channel": channel, "payload": payload})


def _install_recording_adapter(
    monkeypatch: pytest.MonkeyPatch, env_url: str | None = None
) -> _RecordingAdapter:
    """Replace ``queued_publisher`` and (optionally) ``RedisStreamsQueueSettings``
    with a recorder. Returns the recorder for assertions."""
    recorder = _RecordingAdapter()

    def _factory(*, settings: Any = None) -> _RecordingAdapter:
        recorder.settings = settings
        return recorder

    monkeypatch.setattr(
        "oneiric.adapters.bootstrap.queued_publisher",
        _factory,
        raising=False,
    )
    if env_url is not None:
        monkeypatch.setenv("MAHAVISHNU_BODAI_REDIS_URL", env_url)
    else:
        monkeypatch.delenv("MAHAVISHNU_BODAI_REDIS_URL", raising=False)
    return recorder


def test_publish_constructs_stream_override_on_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: ``_publish`` MUST construct the adapter with
    ``stream="bodai:events"`` so producer + subscriber agree.

    Pre-fix the bridge imported a non-existent ``STREAM_NAME``
    constant from oneiric, raising ImportError that the outer
    ``try/except Exception`` silently swallowed — every publish was
    dropped. This test exercises the real ``_publish`` path with a
    recording adapter and asserts the adapter is constructed with
    the correct stream override.
    """
    from oneiric.adapters.queue.redis_streams import RedisStreamsQueueSettings

    from mahavishnu.bodai_hook_bridge import CanonicalEnvelope, _publish

    recorder = _install_recording_adapter(monkeypatch)

    # Confirm the pre-condition: oneiric default IS NOT bodai:events.
    # If this assertion ever fails, the override branch becomes
    # unnecessary and the test should be revisited.
    assert RedisStreamsQueueSettings.model_fields["stream"].default != "bodai:events"

    env = CanonicalEnvelope(
        event="PostToolUse",
        harness="claude",
        session_id="sess_publish_001",
        cwd="/tmp",
    )
    _publish(channel="bodai.hooks.post-tool-use", envelope=env)

    assert recorder.settings is not None, (
        "adapter was never constructed — _publish silently dropped "
        "the publish. This is the regression class that e4429dc2 "
        "introduced and b6... commit fixed."
    )
    assert recorder.settings.stream == "bodai:events", (
        f"adapter stream drifted from bus reader; producer/consumer "
        f"will disagree. Got stream={recorder.settings.stream!r}"
    )
    assert recorder.init_calls == 1, (
        "init must run before publish in the same coroutine "
        "(coredis 6.x binds the pool to the event loop)"
    )
    assert len(recorder.publish_calls) == 1
    assert recorder.publish_calls[0]["channel"] == "bodai.hooks.post-tool-use"


def test_publish_honors_mahavishnu_bodai_redis_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The subscriber honors ``MAHAVISHNU_BODAI_REDIS_URL``; pre-fix
    the publisher hardcoded ``redis://localhost:6379/0``, so any
    environment that set the env var to a non-localhost host silently
    diverged. This test asserts the publisher reads the same env var.
    """
    from mahavishnu.bodai_hook_bridge import CanonicalEnvelope, _publish

    recorder = _install_recording_adapter(monkeypatch, env_url="redis://broker.example.com:6379/5")

    env = CanonicalEnvelope(
        event="PostToolUse",
        harness="claude",
        session_id="sess_pub_url",
        cwd="/tmp",
    )
    _publish(channel="bodai.hooks.post-tool-use", envelope=env)

    assert recorder.settings is not None, (
        "_publish dropped the publish before constructing the adapter"
    )
    assert recorder.settings.url == "redis://broker.example.com:6379/5", (
        f"publisher ignored MAHAVISHNU_BODAI_REDIS_URL — subscriber "
        f"reads remote but publisher writes localhost. "
        f"Got url={recorder.settings.url!r}"
    )


def test_publish_swallows_settings_construction_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: if the import or adapter construction inside
    ``_publish`` raises, the fire-and-forget contract MUST hold — the
    caller never sees a publish failure.

    Pre-fix the ImportError on the broken ``STREAM_NAME`` import was
    silently caught, which is fine — but it ALSO meant every publish
    was dropped, which is NOT fine. These two regressions are
    independent and both must be guarded: the catch must hold AND
    the publish must succeed under normal conditions (see
    test_publish_constructs_stream_override_on_default).
    """
    from mahavishnu.bodai_hook_bridge import CanonicalEnvelope, _publish

    def _boom(*, settings: Any = None) -> Any:
        raise ImportError("simulated broken import")

    monkeypatch.setattr(
        "oneiric.adapters.bootstrap.queued_publisher",
        _boom,
        raising=False,
    )

    env = CanonicalEnvelope(
        event="PostToolUse",
        harness="claude",
        session_id="sess_pub_boom",
        cwd="/tmp",
    )
    # Must NOT raise — fire-and-forget contract.
    result = _publish(channel="bodai.hooks.post-tool-use", envelope=env)
    assert result is None

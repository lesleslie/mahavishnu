// Workflow: Implement Phase 6A — Bodai EventBridge subscriber.
// Single-file deliverable at mahavishnu/core/events/bodai_subscriber.py with unit tests.
//
// Source plan: docs/plans/2026-07-11-phase-6-bodai-observability.md Phase 6.1
//
// Critical references (verified against the codebase before this script):
//   - oneiric.runtime.events.EventEnvelope (msgspec.Struct with topic/payload/headers)
//     at .venv/lib/python3.13/site-packages/oneiric/runtime/events.py:19
//   - oneiric.runtime.events.create_event_envelope() factory at :25
//   - oneiric.domains.events.EventBridge.emit(topic, payload, headers=None) at :59
//   - mahavishnu.core.events.contract.InMemoryEventTransport at contract.py:97 (test transport)
//   - mahavishnu.core.events.envelope.EventEnvelope (Pydantic mirror, with extended fields)
//   - mahavishnu.core.events.transport.RedisEventTransport (production publisher at transport.py:198)
//
// Envelope shape (canonical, from Oneiric):
//   EventEnvelope(topic: str, payload: dict, headers: dict)
//   headers contain: event_id (UUID str), source (component), version, timestamp (ISO),
//   correlation_id, causation_id (both optional)
//
// Style: from __future__ import annotations; sorted stdlib/third-party/first-party imports;
// msgspec.Struct preferred for new envelope code; logger.exception in except blocks;
// oneiric.core.logging.get_logger.

export const meta = {
  name: 'implement-phase-6a-bodai-subscriber',
  description: 'Phase 6A: Mahavishnu Bodai subscriber that consumes Oneiric EventBridge envelopes and persists to ~/.mahavishnu/bodai-event-queue.json',
  phases: [
    { title: 'T6A.1 - bodai_subscriber.py + tests' },
    { title: 'T6A.2 - validation' },
  ],
};

const T6A1_SCHEMA = {
  type: 'object',
  required: ['files_created', 'files_modified', 'tests_passing', 'summary', 'blockers'],
  properties: {
    files_created: { type: 'array', items: { type: 'string' } },
    files_modified: { type: 'array', items: { type: 'string' } },
    tests_passing: { type: 'boolean' },
    summary: { type: 'string' },
    blockers: { type: 'array', items: { type: 'string' } },
  },
};
const REVIEW_SCHEMA = {
  type: 'object',
  required: ['verdict', 'issues', 'summary'],
  properties: {
    verdict: { type: 'string', enum: ['approve', 'approve-with-minor', 'needs-revision', 'blocking'] },
    issues: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          severity: { type: 'string', enum: ['critical', 'major', 'minor'] },
          file: { type: 'string' },
          summary: { type: 'string' },
          fix: { type: 'string' },
        },
      },
    },
    summary: { type: 'string' },
  },
};

// ===== Phase A: T6A.1 — Subscriber implementation =====
phase('T6A.1 - bodai_subscriber.py + tests');
const t6a1 = await agent(
  [
    "Implement Task 6A.1 of the Phase 6 Bodai observability plan: create the Mahavishnu Bodai subscriber that consumes Oneiric EventBridge envelopes and persists them to a local queue file.",
    "",
    "Plan: /Users/les/Projects/mahavishnu/docs/plans/2026-07-11-phase-6-bodai-observability.md - section 5 Phase 6.1 (revised scope: subscriber only, envelope already shipped).",
    "",
    "Files to read first:",
    "- /Users/les/Projects/mahavishnu/.venv/lib/python3.13/site-packages/oneiric/runtime/events.py (canonical EventEnvelope — msgspec.Struct with topic/payload/headers)",
    "- /Users/les/Projects/mahavishnu/.venv/lib/python3.13/site-packages/oneiric/domains/events.py (EventBridge.emit API)",
    "- /Users/les/Projects/mahavishnu/mahavishnu/core/events/contract.py (InMemoryEventTransport — use this for tests; has publish() + subscribe() pattern)",
    "- /Users/les/Projects/mahavishnu/mahavishnu/core/events/transport.py (RedisEventTransport — production publisher to mirror in subscriber)",
    "- /Users/les/Projects/mahavishnu/mahavishnu/core/events/envelope.py (Pydantic mirror — note the schema divergence vs Oneiric's msgspec version)",
    "- /Users/les/Projects/mahavishnu/.claude/hooks/mahavishnu-activity-stream.py (Phase 5 transition hook — mirror its structure exactly, just change source from WebSocket to EventBridge)",
    "",
    "Step 1: Create /Users/les/Projects/mahavishnu/mahavishnu/core/events/bodai_subscriber.py",
    "",
    "Module docstring must explain:",
    "- The subscriber is the Mahavishnu-side consumer of Oneiric EventBridge (the unified event spine from Convergence Plan C1b)",
    "- It consumes EventEnvelope objects and persists them to ~/.mahavishnu/bodai-event-queue.json (atomic write, cap at 100 entries, oldest dropped first)",
    "- Phase 5's mahavishnu-activity-stream.py is the WebSocket-based transition state; this is the EventBridge-based steady state",
    "- Reference: .claude/decisions/bodai-observability-pattern.md",
    "",
    "Public API:",
    "",
    "def subscribe_to_bodai_events(",
    "    callback: Callable[[EventEnvelope], Awaitable[None]],",
    "    *,",
    "    redis_url: str = 'redis://localhost:6379/0',",
    "    consumer_group: str = 'mahavishnu-claude-observers',",
    "    consumer_name: str | None = None,  # default: socket.gethostname()",
    "    queue_path: Path | None = None,  # default: ~/.mahavishnu/bodai-event-queue.json",
    "    queue_cap: int = 100,",
    "    per_event_timeout_seconds: float = 30.0,",
    "    cancellation_token: asyncio.Event | None = None,  # tests use this; production uses signal",
    ") -> None:",
    "    Subscribe to the unified activity-event stream and persist each envelope to the local queue file.",
    "",
    "    Blocks until cancellation_token is set. Never raises application exceptions out of the callback path - all failures logged at WARNING and the next envelope proceeds (mirrors Phase 5 loop-until-dry error-trapping). The transport is the Oneiric Redis-Streams transport from mahavishnu/core/events/transport.py; the consumer uses redis.asyncio.client.Redis.xreadgroup().",
    "",
    "Helper function (also exported):",
    "",
    "def format_bodai_summary(envelope: EventEnvelope) -> str:",
    "    Return a one-line summary in the '[source] event_type key=value' format that Claude Code will surface inline.",
    "",
    "    Example outputs: '[mahavishnu] workflow_completed workflow_id=wid_abc', '[akosha] aggregation_completed suite=quality', '[crackerjack] test_run_completed passed=42 failed=0'.",
    "    Uses envelope.headers['source'] for the component prefix and envelope.topic for the event_type.",
    "",
    "Helper function:",
    "",
    "def _read_queue(path: Path) -> list[dict[str, Any]]:",
    "    Read the current queue file atomically. Returns [] if the file does not exist.",
    "",
    "def _write_queue_atomic(path: Path, envelopes: list[dict[str, Any]]) -> None:",
    "    Write the queue file atomically (tmp + rename). Used to update the queue after appending.",
    "",
    "def append_to_queue(envelope_dict: dict[str, Any], *, queue_path: Path | None = None, queue_cap: int = 100) -> None:",
    "    Append an envelope dict to the queue file, dropping oldest if cap exceeded. Atomic write.",
    "",
    "Step 2: The subscriber's loop:",
    "1. Connect to Redis via redis.asyncio.Redis.from_url(redis_url)",
    "2. XGROUP CREATE bodai:events mahavishnu-claude-observers $ MKSTREAM (idempotent: ignore BUSYGROUP error)",
    "3. Loop: XREADGROUP GROUP consumer_group consumer_name COUNT 10 BLOCK 5000 STREAMS bodai:events >",
    "4. For each message: decode JSON envelope, validate, call append_to_queue, XACK",
    "5. On cancellation_token.set(): break the loop, close the Redis connection",
    "",
    "Step 3: Create /Users/les/Projects/mahavishnu/tests/unit/test_bodai_subscriber.py",
    "",
    "Tests (pytestmark = pytest.mark.unit, asyncio_mode = 'auto'):",
    "1. test_format_bodai_summary_mahavishnu - envelope with source='mahavishnu', topic='workflow_completed', payload={'workflow_id': 'wid_abc'} -> '[mahavishnu] workflow_completed workflow_id=wid_abc'",
    "2. test_format_bodai_summary_akosha - envelope with source='akosha', topic='aggregation_completed', payload={'suite': 'quality'} -> '[akosha] aggregation_completed suite=quality'",
    "3. test_format_bodai_summary_missing_keys - envelope with empty headers/payload -> falls back to '[unknown] unknown' (does not raise)",
    "4. test_append_to_queue_writes_atomically - tmp_path fixture; verify queue file written; verify no partial writes via inspecting tmp + rename pattern",
    "5. test_append_to_queue_caps_at_100 - seed 150 envelopes; verify queue has 100 entries; verify oldest 50 dropped",
    "6. test_append_to_queue_creates_parent_directory - tmp_path; verify .mahavishnu/bodai-event-queue.json created on first write",
    "7. test_subscribe_consumes_and_appends - mock redis.asyncio.Redis; pre-seed xreadgroup response with 3 envelopes; verify all 3 appended to queue + ack'd; verify cancellation_token stops the loop after one batch",
    "8. test_subscribe_handles_decode_error - mock redis returns malformed JSON; verify logged at WARNING + skipped (not acked, so it can be retried by another consumer); verify loop continues",
    "9. test_subscribe_creates_consumer_group_idempotently - mock redis raises BUSYGROUP on first call, succeeds on retry; verify second call succeeds",
    "10. test_subscribe_handles_connection_drop - mock redis raises ConnectionError on xreadgroup; verify logged at WARNING + retry on next iteration with backoff",
    "",
    "Use unittest.mock.AsyncMock for the Redis client. Use a real Oneiric InMemoryEventTransport (from mahavishnu.core.events.contract) for round-trip envelope construction in the format tests.",
    "",
    "Step 4: After both files are written:",
    "uv run pytest tests/unit/test_bodai_subscriber.py -v --no-cov (all 10 tests must pass)",
    "uv run ruff check mahavishnu/core/events/bodai_subscriber.py tests/unit/test_bodai_subscriber.py (must be clean)",
    "",
    "Style:",
    "- from __future__ import annotations first",
    "- Imports sorted stdlib -> third-party -> first-party",
    "- Use msgspec.Struct or dataclass(frozen=True) for new typed structures (not Pydantic for low-overhead hot paths)",
    "- logger.exception in except blocks",
    "- Atomic file writes via tmp + rename (Pattern from Phase 5 mahavishnu-activity-stream.py)",
    "- All file paths come from explicit parameters with sensible defaults",
    "",
    "Do NOT:",
    "- Do NOT add CLI commands, hooks, or settings.json wiring - those are 6B, 6.4",
    "- Do NOT add Akosha or Crackerjack publishers - those are cross-repo work for 6.2",
    "- Do NOT modify the canonical Oneiric EventEnvelope - import and use as-is",
    "- Do NOT add metrics or OTel spans beyond basic logger.exception (the broader observability surface comes in Phase 6.6)",
    "",
    "Report files created and test result.",
  ].join("\n"),
  { label: 'T6A.1', schema: T6A1_SCHEMA }
);

log('T6A.1: ' + t6a1.summary);

// ===== Phase B: T6A.2 — Validation =====
phase('T6A.2 - validation');
const validation = await agent(
  [
    "Run final Phase 6A validation.",
    "",
    "Files to inspect:",
    "- /Users/les/Projects/mahavishnu/mahavishnu/core/events/bodai_subscriber.py (new file)",
    "- /Users/les/Projects/mahavishnu/tests/unit/test_bodai_subscriber.py (new file)",
    "",
    "Validation steps:",
    "1. uv run pytest tests/unit/test_bodai_subscriber.py -v --no-cov - must pass all 10 tests",
    "2. uv run ruff check mahavishnu/core/events/bodai_subscriber.py tests/unit/test_bodai_subscriber.py - must be clean",
    "3. uv run python -c 'from mahavishnu.core.events.bodai_subscriber import subscribe_to_bodai_events, format_bodai_summary, append_to_queue; print(\"imports OK\")' - must succeed",
    "4. uv run python scripts/audit_orphans.py --days 7 --root mahavishnu - report whether bodai_subscriber or its public functions are flagged as orphans",
    "5. uv run python -c 'from mahavishnu.core.events.bodai_subscriber import format_bodai_summary; from oneiric.runtime.events import EventEnvelope, create_event_envelope; e = create_event_envelope(topic=\"test\", payload={\"a\": 1}, source=\"mahavishnu\"); print(format_bodai_summary(e))' - must print a one-line summary",
    "",
    "Verdict: approve | approve-with-minor | needs-revision | blocking",
    "",
    "Report each validation step's result and any issues found.",
  ].join("\n"),
  { label: 'validation', schema: REVIEW_SCHEMA }
);

log('Validation: ' + validation.verdict);
// Workflow: Implement Phase 5 of the integration plan.
// Phase 5 = Worker activity surfacing.
// Source plan: docs/plans/2026-07-11-ultracode-integration-wiring.md section 5 Phase 5.
//
// Phase 5 deliverables:
//   - T5.1: /vishnu-status slash command (.claude/commands/vishnu-status.md)
//   - T5.2: vishnu-status auto-trigger skill (.claude/skills/vishnu-status/SKILL.md)
//   - T5.3: Update claude-md-tool-preferences.md draft to add Worker activity visibility subsection, re-apply to CLAUDE.md
//   - T5.4: WebSocket subscriber hook at .claude/hooks/mahavishnu-activity-stream.py
//   - T5.5: Tests for the WebSocket subscriber (integration marker)
//   - T5.6: Wire the hook into .claude/settings.json

export const meta = {
  name: 'implement-phase-5-activity-surfacing',
  description: 'Wire worker activity surfacing: /vishnu-status command, vishnu-status skill, WebSocket subscriber hook, CLAUDE.md update, settings wiring',
  phases: [
    { title: 'T5.1+T5.2 - /vishnu-status command + skill' },
    { title: 'T5.3+T5.4 - CLAUDE.md update + WebSocket subscriber hook' },
    { title: 'T5.5+T5.6 - tests + settings wiring + validation' },
  ],
};

const T51_SCHEMA = {
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
const T52_SCHEMA = T51_SCHEMA;
const T53_SCHEMA = T51_SCHEMA;
const T54_SCHEMA = T51_SCHEMA;
const T55_SCHEMA = T51_SCHEMA;
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

// ===== Phase A: T5.1 + T5.2 =====
phase('T5.1+T5.2 - /vishnu-status command + skill');
const [t51, t52] = await parallel([
  () => agent(
    [
      "Implement Task 5.1 of the Mahavishnu integration plan: create the /vishnu-status slash command.",
      "",
      "Plan: /Users/les/Projects/mahavishnu/docs/plans/2026-07-11-ultracode-integration-wiring.md - section 5 Phase 5, Task 5.1.",
      "",
      "Files to read first:",
      "- /Users/les/Projects/mahavishnu/.claude/commands/verbose-status.md (existing command format reference)",
      "- /Users/les/Projects/mahavishnu/.claude/commands/ (list to see existing patterns)",
      "- /Users/les/Projects/mahavishnu/CLAUDE.md (find the MCP tool names to invoke)",
      "",
      "Step 1: Create /Users/les/Projects/mahavishnu/.claude/commands/vishnu-status.md.",
      "",
      "Step 2: Follow the existing command format (markdown with embedded Python code blocks). The command runs these CLI invocations sequentially:",
      "1. mahavishnu pool list",
      "2. mahavishnu pool health",
      "3. mahavishnu metrics",
      "4. (if verification_enabled) mahavishnu metrics verification",
      "5. (if dispatch quota configured) mahavishnu metrics dispatch",
      "",
      "Step 3: Format the output as a status table with sections: Pool Status, Recent Activity, Verification, Dispatch.",
      "",
      "Step 4: The command description (above the code block) should be: 'Check current Mahavishnu worker pool, verification, and dispatch status - equivalent to running pool list/health/metrics from a separate terminal.'",
      "",
      "Style:",
      "- Match verbose-status.md format (heading + descriptive paragraph + fenced python code block)",
      "- Use Bash tool invocations with the Bash tool ID where the command runs shell",
      "- Present results as a markdown table when possible",
      "",
      "Do NOT:",
      "- Do NOT add the WebSocket subscriber logic here - that's T5.4 (a separate hook)",
      "- Do NOT add the auto-trigger skill - that's T5.2",
      "",
      "Report files created and a short summary.",
    ].join("\n"),
    { label: 'T5.1', schema: T51_SCHEMA }
  ),
  () => agent(
    [
      "Implement Task 5.2 of the Mahavishnu integration plan: create the vishnu-status auto-trigger skill.",
      "",
      "Plan: /Users/les/Projects/mahavishnu/docs/plans/2026-07-11-ultracode-integration-wiring.md - section 5 Phase 5, Task 5.2.",
      "",
      "Files to read first:",
      "- /Users/les/Projects/mahavishnu/.claude/skills/task-orchestration-review/SKILL.md (existing skill format)",
      "- /Users/les/Projects/mahavishnu/.claude/skills/ (list to see existing patterns)",
      "- /Users/les/Projects/mahavishnu/scripts/tool_frontmatter_validator.py (the validator)",
      "",
      "Step 1: Create /Users/les/Projects/mahavishnu/.claude/skills/vishnu-status/SKILL.md.",
      "",
      "Step 2: Frontmatter (yaml between --- markers):",
      "  name: vishnu-status",
      "  description: 'Auto-trigger skill that surfaces Mahavishnu pool, verification, and dispatch status when the user asks \"are workers running?\", \"what is the pool status?\", or similar phrasings. Use this for visibility into Mahavishnu without leaving the current session.'",
      "",
      "Step 3: Body content describes:",
      "- Trigger phrases (\"are workers running\", \"pool status\", \"what is mahavishnu doing\", \"show me worker activity\")",
      "- Behavior (call /vishnu-status slash command, surface the output)",
      "- Distinction from /vishnu (this skill is for *visibility*, /vishnu is for *dispatch*)",
      "- Where to find more (the slash command body)",
      "",
      "Step 4: Validate with: uv run python scripts/tool_frontmatter_validator.py - must pass.",
      "",
      "Style:",
      "- Match existing skill frontmatter (yaml between --- markers)",
      "- Body should be valid markdown",
      "- Description should be specific enough to trigger on relevant user queries",
      "",
      "Report files created and validation result.",
    ].join("\n"),
    { label: 'T5.2', schema: T52_SCHEMA }
  ),
]);

log('T5.1: ' + t51.summary);
log('T5.2: ' + t52.summary);

// ===== Phase B: T5.3 + T5.4 =====
phase('T5.3+T5.4 - CLAUDE.md update + WebSocket subscriber hook');
const [t53, t54] = await parallel([
  () => agent(
    [
      "Implement Task 5.3 of the Mahavishnu integration plan: update the claude-md-tool-preferences.md draft to add a Worker activity visibility subsection, then re-apply the section to CLAUDE.md.",
      "",
      "Plan: /Users/les/Projects/mahavishnu/docs/plans/2026-07-11-ultracode-integration-wiring.md - section 5 Phase 5, Task 5.3.",
      "",
      "Files to read first:",
      "- /Users/les/Projects/mahavishnu/CLAUDE.md (the ## Tool Preferences section that T4.1 added)",
      "- /Users/les/Projects/mahavishnu/docs/plans/drafts/2026-07-11-ultracode-integration/claude-md-tool-preferences.md (the original draft)",
      "",
      "Step 1: Add a new '### Worker activity visibility' subsection to the ## Tool Preferences section in CLAUDE.md. Place it AFTER the '### Cost and latency note' subsection (the last existing subsection).",
      "",
      "Step 2: The subsection body should describe three visibility surfaces:",
      "1. /vishnu-status slash command - prints pool list/health/metrics",
      "2. MCP log file - '~/.mahavishnu/logs/mcp.log'",
      "3. WebSocket subscriber - port 8690, channels workflow:{workflow_id}, pool:{pool_id}, worker:{worker_id}, global",
      "",
      "Step 3: The subsection should also reference the .claude/hooks/mahavishnu-activity-stream.py hook (from T5.4) for inline visibility from inside the Claude session.",
      "",
      "Step 4: Also UPDATE the draft file at docs/plans/drafts/2026-07-11-ultracode-integration/claude-md-tool-preferences.md so future readers of the draft see the Worker activity visibility subsection. Append it after the '### Cost and latency note' subsection in the draft.",
      "",
      "Style:",
      "- Match the existing subsection style (### heading, content below)",
      "- One paragraph plus a small bulleted list is fine",
      "",
      "Report files modified and a short summary.",
    ].join("\n"),
    { label: 'T5.3', schema: T53_SCHEMA }
  ),
  () => agent(
    [
      "Implement Task 5.4 of the Mahavishnu integration plan: create the WebSocket subscriber hook at .claude/hooks/mahavishnu-activity-stream.py.",
      "",
      "Plan: /Users/les/Projects/mahavishnu/docs/plans/2026-07-11-ultracode-integration-wiring.md - section 5 Phase 5, Task 5.4.",
      "",
      "Files to read first:",
      "- /Users/les/Projects/mahavishnu/.claude/hooks/mcp-hooks.json (existing hook format)",
      "- /Users/les/Projects/mahavishnu/.claude/hooks/ (list contents - if any other .py hooks exist, study their pattern)",
      "- /Users/les/Projects/mahavishnu/CLAUDE.md (look up the WebSocket port - 8690, channels documented)",
      "",
      "Step 1: Create the file /Users/les/Projects/mahavishnu/.claude/hooks/mahavishnu-activity-stream.py.",
      "",
      "Step 2: The hook is a PostToolUse hook that runs after every mcp__mahavishnu__* invocation. The hook:",
      "- Connects to ws://localhost:8690/global and ws://localhost:8690/pool:* on session start (use a SessionStart hook to establish the connections and write the WS client state to ~/.mahavishnu/ws-subscriber-state.json)",
      "- Maintains an in-memory queue of recent events (cap at 100). Persist to a local file at ~/.mahavishnu/ws-event-queue.json so post-tool-use hooks can read it.",
      "- On every mcp__mahavishnu__* invocation (PostToolUse hook), reads the queue and emits a one-line summary for each matching event: '[vishnu] workflow wid_abc completed at stage=test_run'",
      "- Cleans up the WebSocket connection on session end (SessionEnd hook deletes the state file)",
      "",
      "Step 3: Hook implementation pattern:",
      "- Use Python with the `websockets` library (or stdlib `asyncio` + `aiohttp` if `websockets` is not available)",
      "- All file paths and ports come from environment variables (with sensible defaults):",
      "  - MAHAVISHNU_WS_URL (default: ws://localhost:8690)",
      "  - MAHAVISHNU_WS_STATE_PATH (default: ~/.mahavishnu/ws-subscriber-state.json)",
      "  - MAHAVISHNU_WS_QUEUE_PATH (default: ~/.mahavishnu/ws-event-queue.json)",
      "- Log to stderr in the format Claude expects for hooks (lines starting with 'Hook output:' or similar - check existing hooks for the project's convention)",
      "",
      "Step 4: The hook must be idempotent: if the state file already exists at SessionStart, the hook should reconnect to the existing stream rather than starting a new one.",
      "",
      "Style:",
      "- from __future__ import annotations first",
      "- async/await for the WebSocket client",
      "- logger.exception in except blocks",
      "- Proper cleanup via asyncio.shield or finally block",
      "- Top-level docstring explaining the hook's purpose and contract",
      "",
      "Do NOT:",
      "- Do NOT add the WebSocket subscriber to .claude/settings.json - that's T5.6",
      "- Do NOT add tests - T5.5 handles that",
      "",
      "Report files created and a short summary.",
    ].join("\n"),
    { label: 'T5.4', schema: T54_SCHEMA }
  ),
]);

log('T5.3: ' + t53.summary);
log('T5.4: ' + t54.summary);

// ===== Phase C: T5.5 + T5.6 + validation =====
phase('T5.5+T5.6 - tests + settings wiring + validation');
const [t55, t56, validation] = await parallel([
  () => agent(
    [
      "Implement Task 5.5 of the Mahavishnu integration plan: add tests for the WebSocket subscriber hook.",
      "",
      "Plan: /Users/les/Projects/mahavishnu/docs/plans/2026-07-11-ultracode-integration-wiring.md - section 5 Phase 5, Task 5.5.",
      "",
      "Files to read first:",
      "- /Users/les/Projects/mahavishnu/.claude/hooks/mahavishnu-activity-stream.py (T5.4 output)",
      "- /Users/les/Projects/mahavishnu/tests/unit/pools/test_route_task_peer_affinity_auth.py (existing async test pattern)",
      "",
      "Step 1: Create /Users/les/Projects/mahavishnu/tests/integration/test_websocket_subscriber.py (per the plan, marked with the 'integration' pytest marker).",
      "",
      "Step 2: Tests to add:",
      "1. test_subscriber_connects_to_global_channel - mock WebSocket server; verify the hook connects to ws://localhost:8690/global on SessionStart.",
      "2. test_subscriber_maintains_event_queue_cap_at_100 - feed 150 events; verify queue is capped at 100 (oldest dropped).",
      "3. test_post_tool_use_emits_summary_for_matching_event - simulate a PostToolUse hook with a recent workflow_completed event; verify the hook emits '[vishnu] workflow wid_abc completed' to the conversation.",
      "4. test_subscriber_handles_ws_disconnect_gracefully - mock WebSocket server disconnects mid-stream; verify the hook logs at WARNING and reconnects on next PostToolUse.",
      "5. test_session_end_cleans_up_state_file - simulate a SessionEnd hook; verify ~/.mahavishnu/ws-subscriber-state.json is deleted.",
      "",
      "Step 3: Use a fake WebSocket server (a minimal asyncio server fixture) and monkeypatch the URL via the MAHAVISHNU_WS_URL env var. Use pytest tmp_path fixture for the state file.",
      "",
      "Style:",
      "- pytestmark = pytest.mark.integration",
      "- All tests async (asyncio_mode = 'auto' - no @pytest.mark.asyncio needed)",
      "- Use unittest.mock.AsyncMock for the WebSocket client",
      "- Clear test names matching the Exit Criteria list",
      "",
      "Run after creation: uv run pytest tests/integration/test_websocket_subscriber.py -v --no-cov -m integration. All tests must pass.",
      "",
      "Report files created and test result.",
    ].join("\n"),
    { label: 'T5.5', schema: T55_SCHEMA }
  ),
  () => agent(
    [
      "Implement Task 5.6 of the Mahavishnu integration plan: wire the WebSocket subscriber hook into .claude/settings.json so it actually fires.",
      "",
      "Plan: /Users/les/Projects/mahavishnu/docs/plans/2026-07-11-ultracode-integration-wiring.md - section 5 Phase 5, Task 5.6.",
      "",
      "Files to read first:",
      "- /Users/les/Projects/mahavishnu/.claude/settings.json (current contents - currently only has the permissions block)",
      "- /Users/les/Projects/mahavishnu/.claude/hooks/mcp-hooks.json (existing hook configuration - may need to be referenced)",
      "- /Users/les/Projects/mahavishnu/.claude/hooks/mahavishnu-activity-stream.py (T5.4 output)",
      "",
      "Step 1: Read the current .claude/settings.json. The file has only 'permissions' today.",
      "",
      "Step 2: Add three new top-level keys to the JSON:",
      "1. SessionStart - runs the hook script to establish the WebSocket connection. Matcher: 'startup' or '*'.",
      "2. PostToolUse - runs the hook after every mcp__mahavishnu__* invocation. Matcher: 'mcp__mahavishnu__*'.",
      "3. SessionEnd - runs the hook to clean up the WebSocket state. Matcher: '*' or 'end'.",
      "",
      "Step 3: The hook configuration shape (per Claude Code hook spec):",
      "  'SessionStart': [",
      "    {",
      "      'matcher': 'startup',",
      "      'hooks': [",
      "        {",
      "          'type': 'command',",
      "          'command': 'python3 .claude/hooks/mahavishnu-activity-stream.py session-start'",
      "        }",
      "      ]",
      "    }",
      "  ],",
      "  'PostToolUse': [",
      "    {",
      "      'matcher': 'mcp__mahavishnu__*',",
      "      'hooks': [",
      "        {",
      "          'type': 'command',",
      "          'command': 'python3 .claude/hooks/mahavishnu-activity-stream.py post-tool-use'",
      "        }",
      "      ]",
      "    }",
      "  ],",
      "  'SessionEnd': [",
      "    {",
      "      'matcher': 'end',",
      "      'hooks': [",
      "        {",
      "          'type': 'command',",
      "          'command': 'python3 .claude/hooks/mahavishnu-activity-stream.py session-end'",
      "        }",
      "      ]",
      "    }",
      "  ]",
      "",
      "Step 4: The hook script must accept a subcommand argument (session-start, post-tool-use, session-end) and dispatch to the appropriate behavior. The T5.4 agent should have implemented this dispatch; if not, update the hook script to support subcommands.",
      "",
      "Step 5: Verify the JSON is valid (no trailing commas, proper escaping).",
      "",
      "Step 6: Run grep -rn 'ws://localhost:8690' .claude/hooks/ .claude/settings.json to confirm the hook URL is wired (per the plan Exit Criteria).",
      "",
      "Style:",
      "- Match Claude Code hook spec exactly (matcher, hooks array)",
      "- Preserve the existing permissions block",
      "- JSON formatting must be valid",
      "",
      "Report files modified and a short summary.",
    ].join("\n"),
    { label: 'T5.6', schema: T55_SCHEMA }
  ),
  () => agent(
    [
      "Run final Phase 5 validation.",
      "",
      "Files to inspect:",
      "- /Users/les/Projects/mahavishnu/.claude/commands/vishnu-status.md (new slash command)",
      "- /Users/les/Projects/mahavishnu/.claude/skills/vishnu-status/SKILL.md (new skill)",
      "- /Users/les/Projects/mahavishnu/CLAUDE.md (## Tool Preferences now has the Worker activity visibility subsection)",
      "- /Users/les/Projects/mahavishnu/.claude/hooks/mahavishnu-activity-stream.py (new hook)",
      "- /Users/les/Projects/mahavishnu/.claude/settings.json (SessionStart/PostToolUse/SessionEnd hooks wired)",
      "- /Users/les/Projects/mahavishnu/tests/integration/test_websocket_subscriber.py (new test)",
      "",
      "Validation steps:",
      "1. uv run python scripts/tool_frontmatter_validator.py - must pass for the vishnu-status skill",
      "2. grep -rn 'ws://localhost:8690' .claude/hooks/ .claude/settings.json - per plan Exit Criteria, must show the hook URL",
      "3. uv run python scripts/agent_metadata_audit.py - must pass",
      "4. uv run pytest tests/integration/test_websocket_subscriber.py -m integration - must pass",
      "5. Validate .claude/settings.json is valid JSON: python3 -c 'import json; json.load(open(\".claude/settings.json\"))'",
      "",
      "Verdict: approve | approve-with-minor | needs-revision | blocking",
      "",
      "Report each validation step's result and any issues found.",
    ].join("\n"),
    { label: 'validation', schema: REVIEW_SCHEMA }
  ),
]);

log('T5.5: ' + t55.summary);
log('T5.6: ' + t56.summary);
log('Validation: ' + validation.verdict);

return { t51, t52, t53, t54, t55, t56, validation };
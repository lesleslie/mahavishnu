// Workflow: Implement Phase 6B — /bodai-status slash command + bodai-status skill.
// Mahavishnu-only work that mirrors Phase 5's /vishnu-status shape, but reads from
// ~/.mahavishnu/bodai-event-queue.json (Phase 6A's queue file) and groups by component.
//
// Source plan: docs/plans/2026-07-11-phase-6-bodai-observability.md Phase 6.3
//
// Critical references:
//   - /Users/les/Projects/mahavishnu/mahavishnu/core/events/bodai_subscriber.py (Phase 6A - the queue writer)
//   - /Users/les/Projects/mahavishnu/.claude/commands/vishnu-status.md (mirror shape)
//   - /Users/les/Projects/mahavishnu/.claude/skills/vishnu-status/SKILL.md (mirror shape)
//   - /Users/les/Projects/mahavishnu/scripts/tool_frontmatter_validator.py (validator)
//
// Phase 6B rule: this is a *display-only* step. It reads from the queue file that
// Phase 6A populates. If the queue is empty (Phase 6A not yet wired), the slash
// command prints "no events yet" - not an error. This lets us land the UI surface
// independently of the publisher work in Akosha and Crackerjack.

export const meta = {
  name: 'implement-phase-6b-bodai-status',
  description: 'Phase 6B: /bodai-status slash command + bodai-status auto-trigger skill reading from ~/.mahavishnu/bodai-event-queue.json',
  phases: [
    { title: 'T6B.1 - /bodai-status command' },
    { title: 'T6B.2 - bodai-status skill' },
    { title: 'T6B.3 - validation' },
  ],
};

const T6B1_SCHEMA = {
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
const T6B2_SCHEMA = T6B1_SCHEMA;
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

// ===== Phase A: T6B.1 — Slash command =====
phase('T6B.1 - /bodai-status command');
const t6b1 = await agent(
  [
    "Implement Task 6B.1 of the Phase 6 plan: create the /bodai-status slash command.",
    "",
    "Plan: /Users/les/Projects/mahavishnu/docs/plans/2026-07-11-phase-6-bodai-observability.md - section 5 Phase 6.3.",
    "",
    "Files to read first:",
    "- /Users/les/Projects/mahavishnu/.claude/commands/vishnu-status.md (mirror shape exactly - same frontmatter delimiter convention with underscores)",
    "- /Users/les/Projects/mahavishnu/.claude/commands/verbose-status.md (alternate reference)",
    "- /Users/les/Projects/mahavishnu/mahavishnu/core/events/bodai_subscriber.py (the queue writer from Phase 6A - the format of the queue file)",
    "",
    "Step 1: Create /Users/les/Projects/mahavishnu/.claude/commands/bodai-status.md",
    "",
    "Frontmatter (matching the vishnu-status.md convention - underscores, NOT dashes):",
    "",
    "______________________________________________________________________",
    "## name: bodai-status",
    "## description: Check current Bodai-wide activity (Mahavishnu, Akosha, Crackerjack) - reads from ~/.mahavishnu/bodai-event-queue.json which the Phase 6A Bodai subscriber populates from Oneiric EventBridge.",
    "",
    "Body:",
    "",
    "Check current Bodai-wide activity across Mahavishnu, Akosha, and Crackerjack.",
    "",
    "This command reads from ~/.mahavishnu/bodai-event-queue.json (a JSON file populated by the Phase 6A Bodai subscriber at .claude/hooks/bodai-activity-subscriber.py, which consumes from Oneiric EventBridge - the unified event spine from Convergence Plan C1b). Each entry is an EventEnvelope (oneiric.runtime.events) with topic, payload, and headers.",
    "",
    "Output format: a markdown table per component (Mahavishnu, Akosha, Crackerjack), each row showing topic + key payload fields. If the queue file is empty or does not exist, print a single 'no events yet' line - not an error.",
    "",
    "Phase 5's /vishnu-status shows only Mahavishnu activity; this command shows the same plus Akosha and Crackerjack. Use /vishnu-status when you want Mahavishnu-only; use /bodai-status for the cross-component view.",
    "",
    "Run the following Python to read the queue and group by source:",
    "",
    "```python",
    "import json",
    "from pathlib import Path",
    "from collections import defaultdict",
    "",
    "queue_path = Path.home() / '.mahavishnu' / 'bodai-event-queue.json'",
    "if not queue_path.exists():",
    "    print('No Bodai events yet (queue file does not exist - Phase 6A subscriber not running)')",
    "    raise SystemExit(0)",
    "",
    "events = json.loads(queue_path.read_text() or '[]')",
    "if not events:",
    "    print('No Bodai events in the queue yet.')",
    "    raise SystemExit(0)",
    "",
    "by_source = defaultdict(list)",
    "for e in events:",
    "    source = e.get('headers', {}).get('source', 'unknown')",
    "    by_source[source].append(e)",
    "",
    "for source in sorted(by_source):",
    "    print(f'## {source}')",
    "    print('')",
    "    print('| topic | payload summary | timestamp |')",
    "    print('|-------|-----------------|-----------|')",
    "    for e in by_source[source][-20:]:  # last 20 per source",
    "        topic = e.get('topic', '?')",
    "        ts = e.get('headers', {}).get('timestamp', '?')",
    "        payload = e.get('payload', {})",
    "        # Render payload as 'k=v, k=v' (truncate at 80 chars)",
    "        kv = ', '.join(f'{k}={v}' for k, v in list(payload.items())[:5])",
    "        if len(kv) > 80:",
    "            kv = kv[:77] + '...'",
    "        print(f'| {topic} | {kv} | {ts} |')",
    "    print('')",
    "```",
    "",
    "Step 2: The command runs this Python via the Bash tool (tool ID `Bash`).",
    "",
    "Style:",
    "- Mirror the vishnu-status.md format exactly (underscore frontmatter delimiter, descriptive paragraph, fenced python block)",
    "- The command MUST gracefully handle the empty-queue case ('No events yet' - not an error)",
    "- Do NOT include Mahavishnu-only CLI invocations (this command is queue-file based, NOT CLI based)",
    "",
    "Do NOT:",
    "- Do NOT wire the command into settings.json (no auto-trigger; only manual invocation)",
    "- Do NOT include Akosha or Crackerjack CLI commands (those components do not yet expose CLI health surfaces for activity)",
    "",
    "Report files created.",
  ].join("\n"),
  { label: 'T6B.1', schema: T6B1_SCHEMA }
);

log('T6B.1: ' + t6b1.summary);

// ===== Phase B: T6B.2 — Skill =====
phase('T6B.2 - bodai-status skill');
const t6b2 = await agent(
  [
    "Implement Task 6B.2 of the Phase 6 plan: create the bodai-status auto-trigger skill.",
    "",
    "Plan: /Users/les/Projects/mahavishnu/docs/plans/2026-07-11-phase-6-bodai-observability.md - section 5 Phase 6.3.",
    "",
    "Files to read first:",
    "- /Users/les/Projects/mahavishnu/.claude/skills/vishnu-status/SKILL.md (mirror shape EXACTLY including the full 6-field frontmatter)",
    "- /Users/les/Projects/mahavishnu/scripts/tool_frontmatter_validator.py (validator - needs all 6 fields: title, id ULID, owner, status, category, last_reviewed)",
    "- /Users/les/Projects/mahavishnu/mahavishnu/core/events/bodai_subscriber.py (queue format)",
    "",
    "Step 1: Generate a fresh ULID. Run:",
    "uv run python -c \"import time, random; chars='0123456789ABCDEFGHJKMNPQRSTVWXYZ'; ts=int(time.time()*1000)&0xFFFFFFFFFFFF; ts_str=''; [ts_str := chars[ts_ms & 31] + ts_str for ts_ms in [ts_ms >> 5 for _ in range(10)]]; print(ts_str + ''.join(random.choice(chars) for _ in range(16)))\"",
    "",
    "Step 2: Create /Users/les/Projects/mahavishnu/.claude/skills/bodai-status/SKILL.md",
    "",
    "Frontmatter (MUST have all 6 fields per the tool_frontmatter_validator):",
    "",
    "---",
    "name: bodai-status",
    "title: <one-line human title>",
    "id: <the ULID generated in step 1>",
    "description: 'Auto-trigger skill that surfaces cross-component Bodai activity (Mahavishnu, Akosha, Crackerjack) when the user asks \"what is Bodai doing?\", \"show me activity\", or similar phrasings. Reads from ~/.mahavishnu/bodai-event-queue.json which Phase 6A populates from Oneiric EventBridge. Use this for the cross-component view; use /vishnu-status for Mahavishnu-only.'",
    "owner: mahavishnu-core",
    "status: active",
    "category: observability",
    "last_reviewed: 2026-07-11",
    "---",
    "",
    "Body content:",
    "",
    "# Bodai Status (auto-trigger)",
    "",
    "Visibility surface for cross-component Bodai activity (Mahavishnu + Akosha + Crackerjack). Fires when the user wants visibility across the ecosystem, rather than dispatch or single-component status.",
    "",
    "## When to use",
    "",
    "This skill is **observation**, not **dispatch**. Trigger when the user wants cross-component visibility, e.g.:",
    "",
    "- 'What is Bodai doing right now?'",
    "- 'Show me cross-component activity.'",
    "- 'Are there any workflows / aggregations / test runs in progress?'",
    "- 'What has Akosha or Crackerjack surfaced recently?'",
    "",
    "The skill is *not* for requests like 'dispatch this to Mahavishnu' (use /vishnu) or 'what is the pool status' (use /vishnu-status).",
    "",
    "## Behavior",
    "",
    "When this skill fires, invoke the /bodai-status slash command. The slash command reads ~/.mahavishnu/bodai-event-queue.json (populated by the Phase 6A Bodai subscriber consuming Oneiric EventBridge) and groups events by source (Mahavishnu, Akosha, Crackerjack) in a markdown table per component.",
    "",
    "If the queue is empty (Phase 6A subscriber not yet wired OR no recent activity), the slash command prints 'no events yet' - not an error. The skill is safe to fire at any time.",
    "",
    "## Distinction from /vishnu-status",
    "",
    "- **/vishnu-status** - Mahavishnu only (pool list, health, metrics). Quick check of pool state.",
    "- **/bodai-status** - All three components (Mahavishnu, Akosha, Crackerjack) via the unified event spine. Shows what's actually happening across Bodai.",
    "",
    "Use /vishnu-status for 'is Mahavishnu healthy'; use /bodai-status for 'what has anyone done recently'.",
    "",
    "Step 3: Validate with: uv run python scripts/tool_frontmatter_validator.py validate /Users/les/Projects/mahavishnu/.claude/skills/bodai-status/SKILL.md",
    "",
    "Must pass with zero critical issues (the 2 warnings about 'mahavishnu-core' owner and 'observability' category from the validator are acceptable - those are guild suggestions, not blockers).",
    "",
    "Style:",
    "- Match the vishnu-status/SKILL.md format EXACTLY",
    "- All 6 frontmatter fields required",
    "- Body should distinguish /bodai-status from /vishnu-status (they have different scopes)",
    "",
    "Report files created and validation result.",
  ].join("\n"),
  { label: 'T6B.2', schema: T6B2_SCHEMA }
);

log('T6B.2: ' + t6b2.summary);

// ===== Phase C: T6B.3 — Validation =====
phase('T6B.3 - validation');
const validation = await agent(
  [
    "Run final Phase 6B validation.",
    "",
    "Files to inspect:",
    "- /Users/les/Projects/mahavishnu/.claude/commands/bodai-status.md (new slash command)",
    "- /Users/les/Projects/mahavishnu/.claude/skills/bodai-status/SKILL.md (new skill)",
    "",
    "Validation steps:",
    "1. uv run python scripts/tool_frontmatter_validator.py validate /Users/les/Projects/mahavishnu/.claude/skills/bodai-status/SKILL.md - must pass (zero critical issues; guild-name warnings on owner/category are acceptable)",
    "2. Test the slash command's Python block against an empty queue:",
    "   cd /tmp && python3 -c \"$(grep -A 100 'python' /Users/les/Projects/mahavishnu/.claude/commands/bodai-status.md | grep -B 100 '^```$' | head -n -1 | tail -n +2)\" - must print 'No Bodai events yet' (or equivalent empty-state message) without raising",
    "3. Test the slash command against a seeded queue: write a 3-event JSON file at ~/.mahavishnu/bodai-event-queue.json (using Oneiric's create_event_envelope shape), run the Python, verify the table renders correctly",
    "4. uv run ruff check -- not applicable for markdown files",
    "5. grep -rn 'PREFER THIS TOOL' /Users/les/Projects/mahavishnu/.claude/commands/bodai-status.md - must return zero hits (marketing verbs stay out of slash commands per the tool-preference-policy decision)",
    "",
    "Verdict: approve | approve-with-minor | needs-revision | blocking",
    "",
    "Report each validation step's result and any issues found.",
  ].join("\n"),
  { label: 'validation', schema: REVIEW_SCHEMA }
);

log('Validation: ' + validation.verdict);
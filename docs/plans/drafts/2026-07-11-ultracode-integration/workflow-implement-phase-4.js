// Workflow: Implement Phase 4 of the integration plan.
// Phase 4 = Claude Code tool-preference wiring.
// Source plan: docs/plans/2026-07-11-ultracode-integration-wiring.md section 5 Phase 4.
//
// Draft content lives at:
//   docs/plans/drafts/2026-07-11-ultracode-integration/claude-md-tool-preferences.md
//   docs/plans/drafts/2026-07-11-ultracode-integration/revised-tool-descriptions.md
//   docs/plans/drafts/2026-07-11-ultracode-integration/mahavishnu-orchestrator-agent.md
//
// Critical references:
//   - CLAUDE.md (around line 335: insert ## Tool Preferences after ## MCP Server Tools section)
//   - mahavishnu/mcp/tools/pool_tools.py (pool_route_execute at ~line 363 after Phase 3, pool_execute at ~line 114, dispatch_to_pool)
//   - mahavishnu/mcp/server_core.py:324 (trigger_workflow)
//   - .claude/decisions/README.md (operational decision file shape)
//   - scripts/agent_metadata_audit.py (validates subagent frontmatter)
//   - scripts/tool_frontmatter_validator.py (validates skill frontmatter)
//
// Phase 4 policy: tool-selection steering lives in two places only -
// MAHAVISHNU_TOOL_PROFILE (in mahavishnu/mcp/tools/profiles.py) for tools-to-expose,
// and CLAUDE.md ## Tool Preferences for tools-to-prefer. Docstrings narrate use cases;
// they do not market. Strip PREFER THIS TOOL FOR / DO NOT use this for marketing verbs.

export const meta = {
  name: 'implement-phase-4-tool-preferences',
  description: 'Wire Claude Code tool preferences toward Mahavishnu: CLAUDE.md section, revised docstrings, subagent, /vishnu skill, operational decision',
  phases: [
    { title: 'T4.1+T4.2 - CLAUDE.md section + pool_tools docstrings' },
    { title: 'T4.3+T4.4 - dispatch_to_pool + trigger_workflow docstrings' },
    { title: 'T4.5+T4.6+T4.9 - subagent + skill + tool-set curation' },
    { title: 'T4.7+T4.8 - clarifier + decision record + validation' },
  ],
};

const T41_SCHEMA = {
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
const T42_SCHEMA = T41_SCHEMA;
const T43_SCHEMA = T41_SCHEMA;
const T44_SCHEMA = T41_SCHEMA;
const T45_SCHEMA = T41_SCHEMA;
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

// ===== Phase A: T4.1 + T4.2 =====
phase('T4.1+T4.2 - CLAUDE.md section + pool_tools docstrings');
const [t41, t42] = await parallel([
  () => agent(
    [
      "Implement Task 4.1 of the Mahavishnu integration plan: apply the ## Tool Preferences section to CLAUDE.md.",
      "",
      "Plan: /Users/les/Projects/mahavishnu/docs/plans/2026-07-11-ultracode-integration-wiring.md - section 5 Phase 4, Task 4.1.",
      "Draft content: /Users/les/Projects/mahavishnu/docs/plans/drafts/2026-07-11-ultracode-integration/claude-md-tool-preferences.md",
      "",
      "Files to read first:",
      "- /Users/les/Projects/mahavishnu/CLAUDE.md (find the existing '## MCP Server Tools' section; insert the new section immediately AFTER it)",
      "- /Users/les/Projects/mahavishnu/docs/plans/drafts/2026-07-11-ultracode-integration/claude-md-tool-preferences.md (the full drafted section content)",
      "",
      "Step 1: Open CLAUDE.md and locate the line where '## MCP Server Tools' section ends. Insert the new '## Tool Preferences' section immediately after that section, BEFORE the next '## Security' section (or wherever the next major header is).",
      "",
      "Step 2: The new section's content comes from the draft file. Read it carefully - it has these subsections (in order):",
      "- Header: '## Tool Preferences'",
      "- Intro paragraph: 'This project ships a Mahavishnu control plane with ~174 MCP tools. For non-trivial work, prefer Mahavishnu workers over direct local invocations.'",
      "- '### When to use Mahavishnu workers' (with bulleted list and code examples for pool_route_execute and dispatch_to_pool)",
      "- '### When to use local tools (Bash, Edit, Read, Write)' (with bulleted carve-outs)",
      "- '### Dispatching non-trivial work' (subagent mention)",
      "- '### MCP tool discovery' (discover_tools example)",
      "- '### Degraded mode' (fail-loud behavior with 4-step procedure)",
      "- '### Cost and latency note' (~200-500ms overhead note)",
      "",
      "Step 3: PRESERVE the existing '## Security' section and everything below. Do not modify any other CLAUDE.md content.",
      "",
      "Important: Do NOT add the vishnu-status subsection (T5.3 will do that in Phase 5). Only add the content from claude-md-tool-preferences.md.",
      "",
      "Style:",
      "- Match the existing CLAUDE.md heading depth (## for sections, ### for subsections)",
      "- Preserve bullet and code-block formatting from the draft",
      "- Use 4-space indent for nested bullets (matching the draft)",
      "",
      "Report files modified and a short summary.",
    ].join("\n"),
    { label: 'T4.1', schema: T41_SCHEMA }
  ),
  () => agent(
    [
      "Implement Task 4.2 of the Mahavishnu integration plan: replace the docstrings of pool_route_execute and pool_execute with the revised versions from the draft file.",
      "",
      "Plan: /Users/les/Projects/mahavishnu/docs/plans/2026-07-11-ultracode-integration-wiring.md - section 5 Phase 4, Task 4.2.",
      "Draft content: /Users/les/Projects/mahavishnu/docs/plans/drafts/2026-07-11-ultracode-integration/revised-tool-descriptions.md (sections 1 and 2)",
      "",
      "Files to read first:",
      "- /Users/les/Projects/mahavishnu/mahavishnu/mcp/tools/pool_tools.py (the current pool_route_execute and pool_execute docstrings - lines may have shifted after Phase 3)",
      "- /Users/les/Projects/mahavishnu/docs/plans/drafts/2026-07-11-ultracode-integration/revised-tool-descriptions.md",
      "",
      "Step 1: For pool_route_execute, replace the docstring (inside the @mcp.tool() decorator at the function declaration) with the drafted version from section 1 of the draft file.",
      "",
      "Step 2: For pool_execute, replace the docstring with the drafted version from section 2 of the draft file.",
      "",
      "CRITICAL - Marketing verb strip per the architecture-council C3 finding:",
      "The drafted docstrings include marketing-style imperative prefixes/suffixes that the architecture-council review flagged as creating a third steering channel. You MUST strip these:",
      "- Strip any line that starts with 'PREFER THIS TOOL FOR ...'",
      "- Strip any '**DO NOT use this for:**' section that uses imperative form",
      "Keep the use-case narration, parameter documentation, examples, and the selector-strategy bullets.",
      "",
      "Replace the marketing opener with a neutral first line. For pool_route_execute, use something like 'Route a prompt to the best Mahavishnu worker pool automatically.' For pool_execute, use 'Execute a task on a specific Mahavishnu pool by ID.'",
      "",
      "Note: pool_route_execute already has caller_kind and parent_session_id parameters from Phase 3 T3.4. The new docstring should mention these. Update the Args: section accordingly.",
      "",
      "Style:",
      "- Match triple-quoted docstring format already used in the file",
      "- Keep the example code blocks intact",
      "- Preserve the existing parameter signature",
      "",
      "Do NOT:",
      "- Do NOT modify dispatch_to_pool (T4.3 handles that)",
      "- Do NOT modify trigger_workflow (T4.4 handles that)",
      "- Do NOT modify the function bodies - only the docstrings",
      "- Do NOT add new parameters",
      "",
      "Report files modified and a short summary.",
    ].join("\n"),
    { label: 'T4.2', schema: T42_SCHEMA }
  ),
]);

log('T4.1: ' + t41.summary);
log('T4.2: ' + t42.summary);

// ===== Phase B: T4.3 + T4.4 =====
phase('T4.3+T4.4 - dispatch_to_pool + trigger_workflow docstrings');
const [t43, t44] = await parallel([
  () => agent(
    [
      "Implement Task 4.3 of the Mahavishnu integration plan: revise the docstring of dispatch_to_pool.",
      "",
      "Plan: /Users/les/Projects/mahavishnu/docs/plans/2026-07-11-ultracode-integration-wiring.md - section 5 Phase 4, Task 4.3.",
      "Draft content: /Users/les/Projects/mahavishnu/docs/plans/drafts/2026-07-11-ultracode-integration/revised-tool-descriptions.md (section 3)",
      "",
      "Files to read first:",
      "- /Users/les/Projects/mahavishnu/mahavishnu/mcp/tools/pool_tools.py (locate dispatch_to_pool - was added by Phase 3 T3.3)",
      "- /Users/les/Projects/mahavishnu/docs/plans/drafts/2026-07-11-ultracode-integration/revised-tool-descriptions.md (section 3 has the drafted docstring)",
      "",
      "Step 1: Locate dispatch_to_pool in pool_tools.py. It has the signature: async def dispatch_to_pool(prompt: str, pool_selector: str = 'least_loaded', caller_kind: str = 'ultracode', parent_session_id: str | None = None, timeout: int = 300, async_callback: bool = False) -> dict[str, Any]",
      "",
      "Step 2: Replace the existing docstring with the revised version from section 3 of the draft file.",
      "",
      "CRITICAL - Marketing verb strip (same as T4.2):",
      "- Strip the 'PREFER THIS TOOL for long-running or async work' opener",
      "- Strip the '**DO NOT use this for:**' section",
      "- Keep use-case narration and examples",
      "Replace with a neutral opener: 'Async-callback sibling of pool_route_execute for long-running or multi-step work.'",
      "",
      "Step 3: The docstring must mention caller_kind and parent_session_id (these were added by Phase 3). Update the Args: section.",
      "",
      "Style: Same as T4.2.",
      "",
      "Do NOT:",
      "- Do NOT modify the dispatch_to_pool function body - only the docstring",
      "- Do NOT modify pool_route_execute (T4.2 handles that)",
      "- Do NOT modify trigger_workflow (T4.4 handles that)",
      "",
      "Report files modified and a short summary.",
    ].join("\n"),
    { label: 'T4.3', schema: T43_SCHEMA }
  ),
  () => agent(
    [
      "Implement Task 4.4 of the Mahavishnu integration plan: revise the docstring of trigger_workflow in mahavishnu/mcp/server_core.py:324.",
      "",
      "Plan: /Users/les/Projects/mahavishnu/docs/plans/2026-07-11-ultracode-integration-wiring.md - section 5 Phase 4, Task 4.4.",
      "Draft content: /Users/les/Projects/mahavishnu/docs/plans/drafts/2026-07-11-ultracode-integration/revised-tool-descriptions.md (section 4)",
      "",
      "Files to read first:",
      "- /Users/les/Projects/mahavishnu/mahavishnu/mcp/server_core.py (trigger_workflow at line 324)",
      "- /Users/les/Projects/mahavishnu/docs/plans/drafts/2026-07-11-ultracode-integration/revised-tool-descriptions.md (section 4 has the drafted docstring)",
      "",
      "Step 1: Locate trigger_workflow in server_core.py at line 324.",
      "",
      "Step 2: Replace its docstring with the drafted version from section 4 of the draft file.",
      "",
      "CRITICAL - Marketing verb strip (same as T4.2):",
      "- Strip the 'PREFER THIS TOOL for full multi-step orchestrations' opener",
      "- Keep the adapter-selection narration and examples",
      "Replace with a neutral opener: 'Trigger a durable workflow execution through a named adapter (prefect, llamaindex, agno). Use for multi-step orchestrations that span repos or need durable state across hours or days.'",
      "",
      "Step 3: The new docstring must contrast trigger_workflow with pool_route_execute (use the former for multi-step durable orchestration, the latter for ad-hoc dispatch). This is the existing guidance in the draft.",
      "",
      "Style: Same as T4.2.",
      "",
      "Do NOT:",
      "- Do NOT modify the trigger_workflow function body - only the docstring",
      "- Do NOT modify the pool_tools.py docstrings (T4.2 and T4.3 handle those)",
      "",
      "Report files modified and a short summary.",
    ].join("\n"),
    { label: 'T4.4', schema: T44_SCHEMA }
  ),
]);

log('T4.3: ' + t43.summary);
log('T4.4: ' + t44.summary);

// ===== Phase C: T4.5 + T4.6 + T4.9 =====
phase('T4.5+T4.6+T4.9 - subagent + skill + tool-set curation');
const [t45, t46, t49] = await parallel([
  () => agent(
    [
      "Implement Task 4.5 of the Mahavishnu integration plan: create .claude/agents/mahavishnu-orchestrator.md.",
      "",
      "Plan: /Users/les/Projects/mahavishnu/docs/plans/2026-07-11-ultracode-integration-wiring.md - section 5 Phase 4, Task 4.5.",
      "Draft content: /Users/les/Projects/mahavishnu/docs/plans/drafts/2026-07-11-ultracode-integration/mahavishnu-orchestrator-agent.md",
      "",
      "Files to read first:",
      "- /Users/les/Projects/mahavishnu/docs/plans/drafts/2026-07-11-ultracode-integration/mahavishnu-orchestrator-agent.md (the full drafted agent body - extract the markdown between the --- fences)",
      "- /Users/les/Projects/mahavishnu/.claude/agents/ (existing agent files for frontmatter format reference)",
      "- /Users/les/Projects/mahavishnu/scripts/agent_metadata_audit.py (the validator)",
      "",
      "Step 1: Extract the agent body. The draft has TWO sections separated by '---': the agent (top section) and the skill (bottom section). Use only the top section for the agent file.",
      "",
      "Step 2: The agent's body content is between the second '---' (closing the frontmatter) and the '---' (closing the body). The body starts with '# Mahavishnu Orchestrator'.",
      "",
      "Step 3: Create the file at /Users/les/Projects/mahavishnu/.claude/agents/mahavishnu-orchestrator.md.",
      "",
      "Step 4: Apply T4.9 - curate the tools: frontmatter to a small set of essentials (per architecture-council L1). Replace the drafted 11-tool enumeration with: mcp__mahavishnu__pool_route_execute, mcp__mahavishnu__dispatch_to_pool, mcp__mahavishnu__discover_tools, Read.",
      "",
      "The reduced tool set keeps the essentials (route, dispatch, discover) plus Read for read-only context. This avoids the 10-tool enumeration drift problem.",
      "",
      "Step 5: Update the draft body text where it references 'the 11 Mahavishnu MCP tools' or similar enumerations - replace with 'the Mahavishnu MCP tools listed in the tools frontmatter' to match the reduced set.",
      "",
      "Step 6: Validate with: uv run python scripts/agent_metadata_audit.py - it must pass.",
      "",
      "Style:",
      "- Use the exact frontmatter format from existing agent files",
      "- Body should be valid markdown",
      "- All tools listed in tools: must actually exist as MCP tools (verify by grep)",
      "",
      "Do NOT:",
      "- Do NOT use the 11-tool enumeration from the draft - use the curated 4-tool set",
      "- Do NOT include the skill content from the draft - that's a separate file (T4.6)",
      "",
      "Report files created and validation result.",
    ].join("\n"),
    { label: 'T4.5', schema: T45_SCHEMA }
  ),
  () => agent(
    [
      "Implement Task 4.6 of the Mahavishnu integration plan: create .claude/skills/vishnu/SKILL.md.",
      "",
      "Plan: /Users/les/Projects/mahavishnu/docs/plans/2026-07-11-ultracode-integration-wiring.md - section 5 Phase 4, Task 4.6.",
      "Draft content: /Users/les/Projects/mahavishnu/docs/plans/drafts/2026-07-11-ultracode-integration/mahavishnu-orchestrator-agent.md (the BOTTOM section after the agent - the skill body)",
      "",
      "Files to read first:",
      "- /Users/les/Projects/mahavishnu/docs/plans/drafts/2026-07-11-ultracode-integration/mahavishnu-orchestrator-agent.md (extract the skill body - second half of the file)",
      "- /Users/les/Projects/mahavishnu/.claude/skills/task-orchestration-review/SKILL.md (existing skill format reference)",
      "- /Users/les/Projects/mahavishnu/scripts/tool_frontmatter_validator.py (the validator)",
      "",
      "Step 1: Extract the SKILL body. The draft has '---' separators - the skill section starts with 'name: vishnu' and ends with the closing '```' of the examples block.",
      "",
      "Step 2: Create the directory /Users/les/Projects/mahavishnu/.claude/skills/vishnu/ and the file SKILL.md inside.",
      "",
      "Step 3: Use the existing skill frontmatter format. Frontmatter must be YAML between '---' markers. Required keys: name (string), description (string).",
      "",
      "Step 4: Use the description and name from the draft: name=vishnu, description='Route a coding task through Mahavishnu worker pools for observability and cross-server delegation. Use this when the user wants the work to appear in ecosystem observability (Dhara, Akosha) or run on a specific pool.'",
      "",
      "Step 5: The body should be the content from the draft, starting with '# /vishnu - Route work through Mahavishnu'.",
      "",
      "Step 6: Validate with: uv run python scripts/tool_frontmatter_validator.py - it must pass.",
      "",
      "Style:",
      "- Match the existing SKILL.md format (yaml frontmatter + markdown body)",
      "- Keep all example invocations intact",
      "- Body should be valid markdown",
      "",
      "Report files created and validation result.",
    ].join("\n"),
    { label: 'T4.6', schema: T45_SCHEMA }
  ),
  () => agent(
    [
      "Implement Task 4.7 of the Mahavishnu integration plan: add a 'Choosing between /vishnu and mahavishnu-orchestrator' clarifier note to CLAUDE.md.",
      "",
      "Plan: /Users/les/Projects/mahavishnu/docs/plans/2026-07-11-ultracode-integration-wiring.md - section 5 Phase 4, Task 4.7.",
      "",
      "Files to read first:",
      "- /Users/les/Projects/mahavishnu/CLAUDE.md (the ## Tool Preferences section that T4.1 added)",
      "",
      "Step 1: Locate the '### Dispatching non-trivial work' subsection that T4.1 added. The note goes BELOW that subsection, as its own ### subsection.",
      "",
      "Step 2: Add a new subsection titled '### Choosing between /vishnu and mahavishnu-orchestrator'.",
      "",
      "Step 3: The note body is ONE paragraph (per the plan):",
      "",
      "'/vishnu is a shortcut that steers tool selection without forcing tool isolation; mahavishnu-orchestrator is forced delegation with strict tool restrictions. Both route through Mahavishnu; the difference is who picks the tools. Use /vishnu when you want a quick way to indicate preference; use mahavishnu-orchestrator when the parent agent wants strict control over which tools the delegated worker can use.'",
      "",
      "Style:",
      "- Match the surrounding subsection style (### heading, paragraph below)",
      "- Do NOT add additional paragraphs or examples",
      "",
      "Report files modified and a short summary.",
    ].join("\n"),
    { label: 'T4.7', schema: T45_SCHEMA }
  ),
]);

log('T4.5: ' + t45.summary);
log('T4.6: ' + t46.summary);
log('T4.7: ' + t49.summary);

// ===== Phase D: T4.8 + validation =====
phase('T4.8 + validation');
const [t48, validation] = await parallel([
  () => agent(
    [
      "Implement Task 4.8 of the Mahavishnu integration plan: create .claude/decisions/mahavishnu-tool-preference-policy.md.",
      "",
      "Plan: /Users/les/Projects/mahavishnu/docs/plans/2026-07-11-ultracode-integration-wiring.md - section 5 Phase 4, Task 4.8.",
      "",
      "Files to read first:",
      "- /Users/les/Projects/mahavishnu/.claude/decisions/README.md (operational decision file shape)",
      "- /Users/les/Projects/mahavishnu/.claude/decisions/removed-scripts.md (existing example for format reference)",
      "",
      "Step 1: Create the file /Users/les/Projects/mahavishnu/.claude/decisions/mahavishnu-tool-preference-policy.md.",
      "",
      "Step 2: Per .claude/decisions/README.md classification, this is an operational rule (NOT an ADR). Use the short header format:",
      "- ## Context (why this rule exists)",
      "- ## Decision rule (the rule itself)",
      "- ## Status (current state)",
      "",
      "Step 3: Decision rule content (verbatim from the plan):",
      "",
      "'Tool-selection steering lives in two places only - MAHAVISHNU_TOOL_PROFILE (in mahavishnu/mcp/tools/profiles.py) for tools-to-expose, and CLAUDE.md ## Tool Preferences for tools-to-prefer. Docstrings narrate use cases; they do not market.'",
      "",
      "Step 4: Context section should explain WHY this rule exists: the architecture-council review found that PREFER THIS TOOL FOR / DO NOT use this for marketing copy in docstrings created a third steering channel that drifts from the two canonical sources. Docstring marketing copy tends to: (a) drift from the canonical sources when tool signatures change, (b) cause Claude to over-route trivial work to Mahavishnu, (c) create contradictions between docstrings and CLAUDE.md guidance.",
      "",
      "Step 5: Status section should be 'Active' (the rule applies now).",
      "",
      "Step 6: Verify the file is referenced from CLAUDE.md. Find the '## Tool Preferences' section and add a brief mention at the bottom: 'See .claude/decisions/mahavishnu-tool-preference-policy.md for the full operational rule.'",
      "",
      "Style:",
      "- Match the existing operational-decision files' tone",
      "- Use h2 for sections, h3 for sub-points",
      "- Markdown only",
      "",
      "Report files created and a short summary.",
    ].join("\n"),
    { label: 'T4.8', schema: T45_SCHEMA }
  ),
  () => agent(
    [
      "Run final Phase 4 validation.",
      "",
      "Files to inspect:",
      "- /Users/les/Projects/mahavishnu/CLAUDE.md (## Tool Preferences section + clarifier note)",
      "- /Users/les/Projects/mahavishnu/mahavishnu/mcp/tools/pool_tools.py (revised docstrings on pool_route_execute, pool_execute, dispatch_to_pool)",
      "- /Users/les/Projects/mahavishnu/mahavishnu/mcp/server_core.py (revised docstring on trigger_workflow)",
      "- /Users/les/Projects/mahavishnu/.claude/agents/mahavishnu-orchestrator.md (new subagent)",
      "- /Users/les/Projects/mahavishnu/.claude/skills/vishnu/SKILL.md (new skill)",
      "- /Users/les/Projects/mahavishnu/.claude/decisions/mahavishnu-tool-preference-policy.md (new operational decision)",
      "",
      "Validation steps:",
      "1. uv run python scripts/agent_metadata_audit.py - must pass",
      "2. uv run python scripts/tool_frontmatter_validator.py - must pass",
      "3. grep -n 'PREFER THIS TOOL' mahavishnu/mcp/tools/pool_tools.py mahavishnu/mcp/server_core.py - per plan Exit Criteria, this should return 0 hits (the marketing verbs were stripped)",
      "4. Run uv run ruff check on modified files - must pass",
      "5. uv run pytest tests/unit/test_mcp/test_pool_tools.py -m unit - must still pass (no signature changes; docstrings only)",
      "",
      "Verdict: approve | approve-with-minor | needs-revision | blocking",
      "",
      "Report each validation step's result and any issues found.",
    ].join("\n"),
    { label: 'validation', schema: REVIEW_SCHEMA }
  ),
]);

log('T4.8: ' + t48.summary);
log('Validation: ' + validation.verdict);
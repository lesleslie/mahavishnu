# Bodai TUI: Claude Code-Style Terminal Application

**Created**: 2026-04-09
**Status**: Draft — Under Review (revision 2)
**Scope**: Internal tool for the Bodai ecosystem
**Engine**: Agno (agent loop) + Textual (TUI) + Mahavishnu (orchestration)

---

## 1. Overview

A Claude Code-style terminal UI built on three layers: **Textual** renders the interface, **Agno** drives the agent loop (chat, tools, streaming, memory), and **Mahavishnu** orchestrates access to the Bodai ecosystem (Akosha, Dhara, Session-Buddy, Crackerjack).

This is an internal development tool, not a public product. It should feel like a local IDE terminal — fast, keyboard-driven, and deeply integrated with the existing ecosystem.

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Textual TUI                            │
│  ┌──────────┐  ┌───────────┐  ┌──────────┐  ┌───────────┐    │
│  │  Chat    │  │  File     │  │  Tools   │  │  Activity│    │
│  │  Panel   │  │  Viewer   │  │  Panel   │  │  Feed    │    │
│  └────┬─────┘  └─────┬─────┘  └────┬─────┘  └────┬─────┘    │
│       │              │             │              │          │
│  ┌────┴──────────────┴─────────────┴──────────────┴──────┐  │
│  │              TUI Agent Bridge (asyncio.Queue)         │  │
│  └──────────────────────┬───────────────────────────────┘  │
└─────────────────────────┼───────────────────────────────────┘
                          │ MCP Client (streamable HTTP)
┌─────────────────────────┼───────────────────────────────────┐
│                  Mahavishnu MCP Server                     │
│  ┌──────────┐  ┌──────────┐  ┌───────────┐  ┌──────────┐    │
│  │  RBAC +   │  │  Tree-   │  │  Pool /   │  │  Py-      │    │
│  │  Approvals│  │  sitter  │  │  Worker   │  │  Charm    │    │
│  │  Manager │  │  + LSP   │  │  Manager  │  │  MCP      │    │
│  └──────────┘  └──────────┘  └───────────┘  └──────────┘    │
│       │              │              │              │          │
│  ┌────┴──────────────┴──────────────┴──────────────┴──────┐  │
│  │   Bodai Ecosystem                                          │  │
│  │   Akosha · Dhara · Session-Buddy · Crackerjack            │  │
│  └──────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

### Topology: TUI is an MCP Client, Not an Embed

The TUI connects to Mahavishnu's MCP server as a **client** (via streamable HTTP on `localhost:8680/mcp`). It does not embed the Mahavishnu server process. This means:

- TUI and Mahavishnu can run independently
- Mahavishnu crash does not kill the TUI (reconnect or degrade)
- The TUI process stays lightweight

### Async Boundary: Message-Passing via asyncio.Queue

Textual's reactive model is opinionated about thread/loop ownership. Agno runs as a background `asyncio.Task` with a message-passing interface:

```
Textual Widget  ──user_input──> asyncio.Queue ──> Agno Agent
                                                          │
Textual Widget  <──stream──── asyncio.Queue <─── streaming callback
```

This avoids the tight coupling of embedding Agno directly in Textual's widget tree.

### Data Flow

1. User types in the chat panel → Textual captures input → pushes to `asyncio.Queue`
2. Agno background task receives message from queue, picks an LLM, invokes tools
3. Tool calls go through Agno's MCP client → Mahavishnu MCP server → Bodai services
4. Streaming tokens from Agno are pushed to a second `asyncio.Queue`
5. Textual reactive watcher pulls from queue, updates `RichLog` widget (~60fps throttle)
6. Tool results (file edits, diagnostics, search hits) render in side panels
7. Mahavishnu wraps Agno lifecycle: `track_session_start` → `checkpoint` → `track_session_end`

### Agno Memory Backend: `none`

Agno must be configured with `memory_backend="none"` to prevent split-brain persistence. All session state flows through Mahavishnu's Session-Buddy wrapper. Agno's native session_id is set but not used for storage.

---

## 3. Engine Decisions

| Engine | Role | Kept? | Why |
|--------|------|-------|-----|
| **Agno** | Agent loop (chat, tools, streaming, memory) | Yes | Core engine. `Agent`, `Team` classes, native MCP tool integration, multi-provider LLM support (Anthropic, OpenAI, Ollama) |
| **Prefect** | Batch DAG workflows (sweep, scheduled jobs) | Yes | Orchestration engine for non-interactive work. Triggered from TUI but not the agent loop |
| **LlamaIndex** | Document RAG (ingestion, retrieval) | Yes | Knowledge base engine. Powers semantic search across ingested content |

### Why Agno replaces Nanobot

- Nanobot's `AgentLoop` (sessions, memory, MCP tools, skills, streaming) is the closest match to what a Claude Code-style TUI needs
- However, Mahavishnu already has a production Agno adapter (`mahavishnu/engines/agno_adapter_impl.py`)
- Agno provides native MCP tool integration, multi-agent teams, and multi-provider LLM support
- Nanobot's `Consolidator` (context compaction algorithm) will be adapted to Agno's message format — the algorithm is useful, but the loop itself is Agno's

### Nanobot contributions we keep

- **Context compaction algorithm** from `nanobot/agent/memory.py` — adapt `Consolidator` logic to work with Agno's message history format
- **Session persistence pattern** — Mahavishnu's SB wrapper handles lifecycle; no Nanobot hook dependency needed

### Excluded Engines

**PydanticAI**: Listed in `AdapterType` but excluded from the TUI engine stack. Its agent model is single-agent-only and does not support the multi-tool, multi-provider orchestration that the TUI requires. Agno covers this space.

---

## 4. TUI Layout

### Panels

| Panel | Widget | Purpose |
|--------|--------|---------|
| **Chat** | `RichLog` | Streaming markdown output, user input at bottom, scrollable history |
| **File Viewer** | `TextLog` or custom | View file contents, jump to line, syntax highlighting |
| **Tools** | `TabbedContent` | Tool call results, diagnostics, search results |
| **Activity Feed** | Collapsible `ListView` | Background events: pool status, workflow stages, quality gate results |
| **Status Bar** | `Footer` | Session ID, model, token count, connection status, pool health |

### Key Interactions

| Shortcut | Action | Notes |
|----------|--------|-------|
| `Ctrl+K` | Command palette | Fuzzy search across commands, models, skills, workflows, and settings |
| `Ctrl+Shift+D` | Diff preview | Last edit vs current state. Avoids Ctrl+D which conflicts with EOF/exit |
| `Ctrl+G` | Go to file:line | Standard IDE shortcut |
| `Tab` | Cycle panels | Chat → File Viewer → Tools → Activity |
| `Ctrl+P` | Permission approval | When agent requests shell/edit |
| `Ctrl+L` | Clear chat scrollback | Standard terminal expectation |
| `Ctrl+W` | Close panel/tab | Close current panel or tool tab |
| `Escape` | Dismiss/cancel | Dismiss palette, cancel streaming, exit approval prompt. Consistent semantics across all modes |
| `?` | Contextual help | Describe what agent is doing, available shortcuts — without leaving chat |
| `Ctrl+\` | Cancel mid-stream | Interrupt Agno agent mid-generation (graceful abort) |

### Built-in Slash Commands

Slash commands are reserved for fast session controls inside the chat input:

- `/status` - Show model, token usage, and connection state
- `/compact` - Trigger message compaction immediately
- `/usage` - Show recent token and tool usage
- `/think` - Switch reasoning depth or verbosity mode
- `/skill <name>` - Load a skill into the current conversation
- `/skills` - List available skills and availability
- `/restart` - Restart the current session or runtime
- `/stop` - Stop the current session or agent loop

### Split-Pane Mode (Phase 2)

Horizontal split for side-by-side diff comparison alongside File Viewer. Vertical split (chat left, file viewer right) for "watch the agent work" mode. Splits are toggleable, not always-on.

---

## 5. Feature Analysis

### Features Already Available in Mahavishnu

| Feature | Location | Notes |
|---------|----------|-------|
| RBAC permissions | `mahavishnu/core/permissions.py` | 10 repo-level operations. **Gap: needs tool-level permissions** (RUN_SHELL, RUN_NETWORK, WRITE_FILE, EDIT_FILE, EXECUTE_TOOL) |
| Approval manager | `mahavishnu/core/approval_manager.py` | `ApprovalRequest`, `ApprovalOption`, `ApprovalResult`. **Gap: only for version_bump/publish, not agent actions** |
| Progress tracker | `mahavishnu/core/progress_tracker.py` | `ProgressState`, `ProgressTask`. **Gap: internal only, not wired to TUI** |
| Tree-sitter tools | `mahavishnu/mcp/tools/treesitter_tools.py` | parse, extract_symbols, batch_analyze. **Gap: needs find_references and go_to_definition** |
| PyCharm MCP tools | `mahavishnu/mcp/tools/pycharm_tools.py` | 8 tools with subprocess fallback. diagnostics, search, open_file, reformat, refactor, replace, list_problems |
| Pool / worker management | `mahavishnu/pools/` | Multi-pool orchestration, memory aggregation, WebSocket broadcasting |
| Session-Buddy integration | `mahavishnu/session/checkpoint.py` | Single session wrapper and Session-Buddy bridge; use local fallback when SB is unavailable |
| Worktree audit | `mahavishnu/core/worktree_audit.py` | Structured audit events for worktree operations |
| OpenClaw gateway | `mahavishnu/workers/openclaw_gateway.py` | Transport-agnostic interface for running tasks through OpenClaw |
| WebSocket infrastructure | `mahavishnu/websocket/server.py` | Real-time events on port 8690 |

### Features to Build

| Feature | Source | Approach |
|---------|--------|-----------|
| Context compaction | Adapt from `nanobot/agent/memory.py` Consolidator | Rewrite for Agno message format. LLM-summarized archiving of old messages. **Phase 1 — not a footnote** |
| Streaming token output | Agno native + Textual `RichLog` | Wire Agno's streaming callback to asyncio.Queue → Textual reactive watcher. Throttle at ~60fps to avoid layout thrashing |
| Diff preview | Custom Textual diff view + PyCharm MCP | Render unified/split diffs in a custom widget; add `pycharm_get_file_diff` for richer analysis |
| Live diagnostics | PyCharm MCP tools (already exist) | Wire `pycharm_run_diagnostics` to file viewer panel |
| Tool-level permissions | Extend `mahavishnu/core/permissions.py` | Risk-tiered model: read-only, write, destructive, network. See Section 9 |
| Agent action approvals | Extend `mahavishnu/core/approval_manager.py` | Add shell/edit/execute approval types. Wire to TUI inline approval prompt |
| Progress in TUI | Wire `mahavishnu/core/progress_tracker.py` | Update status bar on tool calls, workflow stages |
| Tree-sitter navigation | Complete `mahavishnu/mcp/tools/treesitter_tools.py` | Add `find_references` and `go_to_definition` tools |
| Symbol refactor | PyCharm `refactor_symbol` (already exists) | Expose as agent tool, show diff before/after |
| Multi-provider LLM | Agno native support | Anthropic, OpenAI, Ollama. User switches via command palette |
| Session persistence | Mahavishnu session wrapper + Session-Buddy bridge | Mahavishnu calls `track_session_start` before Agno, `track_session_end` after; Agno itself does not persist session state |
| File I/O agent tools | New — first-class tools for Agno | `read_file`, `write_file`, `edit_file`, `list_directory`, `search_files`. Agent needs these before tree-sitter or PyCharm tools |
| MCP tool server for Agno | New — expose Mahavishnu MCP tools to Agno | Agno adapter is task-level, not tool-level. Need an MCP tool server bridge |

### Session-Buddy Compatibility

Session-Buddy is fully compatible. The integration model:

1. **Mahavishnu is the owner** — it wraps Agno's agent loop
2. **Before Agno runs**: Mahavishnu calls `track_session_start` with environment metadata
3. **During execution**: Mahavishnu calls `checkpoint` at key milestones
4. **After Agno finishes**: Mahavishnu calls `track_session_end` with final state
5. **No hooks needed** — Mahavishnu controls the lifecycle directly

This is simpler than the Nanobot integration (which requires skills or hooks) because Mahavishnu has full control over the Agno execution boundary.

---

## 6. PyCharm MCP Integration

### Already Available (8 tools)

| Tool | TUI Use Case | Fallback |
|------|-------------|----------|
| `pycharm_run_diagnostics` | Live error indicators in file viewer | ruff check |
| `pycharm_list_problems` | Aggregated inspection results | ruff check |
| `pycharm_search_in_project` | Project-wide symbol search | grep |
| `pycharm_open_file` | Jump to file:line from TUI | No-op |
| `pycharm_reformat_file` | Auto-format after agent edits | ruff format |
| `pycharm_refactor_symbol` | Rename across project | No-op |
| `pycharm_replace_in_file` | Structured find/replace | Agent does directly |
| `pycharm_health` | Connection status check | Always works |

### To Add (2 tools)

| Tool | Purpose | Value |
|------|---------|-------|
| `pycharm_get_file_diff` | Get IDE-quality diff with rename/move detection | Very High — rich diff data for Textual `Diff` widget |
| `pycharm_get_vcs_changes` | Show uncommitted git changes inline | High — live change tracking |

### Path Validation (Security Requirement)

All `file_path` arguments in PyCharm tools must be validated through the existing `WorktreePathValidator` before execution. Restrict PyCharm tool operations to configured repository directories only. This applies to both MCP and fallback paths.

### Integration Pattern

Every PyCharm tool already follows the degrade-gracefully pattern:

```python
try:
    result = await mcp_client.call_tool("jetbrains__...", args)
except Exception:
    result = _subprocess_fallback(args)
```

The TUI follows the same pattern: enrich with IDE when PyCharm is open, work fully without it. This is already proven in `mahavishnu/mcp/tools/pycharm_tools.py`.

### Diff Preview Strategy

1. **Custom Textual diff view** — always available, no dependency. Renders unified or split diffs with syntax highlighting
2. **PyCharm `pycharm_get_file_diff`** — richer analysis when IDE is open (rename detection, move detection, semantic diffs)
3. **After agent edits**: run `pycharm_run_diagnostics` → show problems → show diff → user approves or requests fix

---

## 7. Skills System (from Nanobot)

### What Skills Are

Skills are markdown files (`SKILL.md`) in directories under `workspace/skills/` or a builtin directory. Each skill teaches the agent how to use specific tools or perform certain tasks — they are **knowledge injection**, not code.

```
workspace/skills/
├── github/
│   └── SKILL.md          # name, description in frontmatter; instructions in body
├── memory/
│   └── SKILL.md          # always: true → loaded into every system prompt
├── tmux/
│   └── SKILL.md
└── skill-creator/
    ├── SKILL.md
    └── scripts/         # init_skill.py, package_skill.py, quick_validate.py
```

### Frontmatter

```yaml
---
name: github
description: "Interact with GitHub using the `gh` CLI. Use when the agent needs to work with issues, PRs, CI runs."
always: false                # true = inject into every system prompt
metadata: '{"requires":{"bins":["gh"]}}'  # dependency checking
---
```

### Progressive Disclosure (Three Levels)

1. **Metadata** (~100 words) — XML `<skills>` block in every system prompt. Lists all skills with name, description, and availability.
2. **SKILL.md body** (<5k words) — Loaded when the agent decides the skill is relevant. Agent reads it via `read_file` tool.
3. **Bundled resources** (unlimited) — `scripts/`, `references/`, `assets/` directories. Agent reads these on demand.

### Loading Flow

```
System prompt build:
  1. SkillsLoader scans workspace/skills/ and builtin_skills/
  2. For each skill directory with a SKILL.md:
     - Parse frontmatter (name, description, always, metadata)
     - Check requirements (bins on PATH, env vars set)
  3. Skills with always=true → load full body into system prompt
  4. All others → include name + description in XML summary

Agent runtime:
  1. Agent sees skill descriptions in system prompt
  2. Agent decides skill is relevant → calls read_file("skills/github/SKILL.md")
  3. Full instructions loaded into conversation context
```

### Nanobot's `SkillsLoader` — Reuse Directly

The `SkillsLoader` class (`nanobot/agent/skills.py`, ~230 lines) has zero Nanobot-specific coupling:

- Input: `workspace: Path`, `builtin_skills_dir: Path | None`
- Output: `list_skills()`, `load_skill(name)`, `build_skills_summary()`, `get_always_skills()`, `get_skill_metadata(name)`
- Dependencies: `json`, `os`, `re`, `shutil`, `pathlib` — all stdlib

Reuse strategy: copy `SkillsLoader` into `mahavishnu/tui/skills.py` (or import from nanobot if both are in the same venv).

### TUI-Specific Additions

1. **`/skill <name>` command** — User manually loads a skill into the current conversation (like Claude Code's `/commit`)
2. **`/skills` command** — List all available skills with descriptions and availability status
3. **Skill panel** (Phase 2) — Sidebar or tab showing loaded/available skills, toggle on/off
4. **Agent auto-discovery** — Agent sees skill descriptions in system prompt, decides to read_file on demand. No registration needed.

### What Skills Cover

- Tool usage patterns (github, tmux, cron)
- Domain knowledge (API schemas, company policies)
- Workflows and procedures
- Memory/persona management
- How to create new skills (skill-creator skill is self-referential)

### What Skills Do NOT Cover

Skills are **knowledge** — they tell the agent *how* to do something. They cannot:

1. **Run in parallel** — a skill is just text in the same agent's context
2. **Isolate context** — loading a skill consumes tokens from the shared context window
3. **Run in the background** — there is no execution boundary

These gaps are addressed by **subagents** (Section 8).

---

## 8. Subagents (Background Task Execution)

### What Subagents Are

Subagents are separate LLM loops that run in their own `asyncio.Task` with independent tool calls, conversation history, and iteration caps. The parent agent spawns them for long-running or parallelizable work and gets notified when they complete.

Nanobot's `SubagentManager` (`nanobot/agent/subagent.py`, ~260 lines) implements this pattern:

```
Parent Agent
  │
  ├── spawn(task="Research X while I fix Y", label="research")
  │     │
  │     └── asyncio.Task
  │           ├── Own system prompt (inherits skills summary)
  │           ├── Own tool set (file I/O, search, exec)
  │           ├── Own message history (fresh context)
  │           └── max_iterations=15 cap
  │
  ├── continues working on Y...
  │
  └── <── subagent announces result via message bus ──> parent renders in chat
```

### Why Skills Alone Are Not Enough

| Need | Skills | Subagents |
|------|--------|-----------|
| Teach the agent a workflow | Yes | No |
| Inject domain knowledge | Yes | No |
| Run two tasks in parallel | No | Yes |
| Isolate long task from main context | No | Yes |
| Background completion with notification | No | Yes |
| Cap runaway tool loops | No | Yes (max_iterations) |

### Reuse from Nanobot

`SubagentManager` + `SpawnTool` are self-contained:

- **Dependencies**: LLMProvider, workspace path, MessageBus (for result announcement), tool registry
- **Adaptation needed**: Replace Nanobot's `AgentRunner` with Agno's `agent.arun()` (or streaming equivalent)
- **TUI integration**: Spawn result renders as an activity feed item + chat message

### Implementation: Phase 2, Not Phase 1

Skills are zero-risk to add (they're markdown files and a 230-line loader). Subagents require:

- Async task management in the TUI agent bridge
- Subagent tool registration in Agno's MCP tool set
- Result announcement routing (message bus → chat panel → activity feed)
- Cancellation support (`cancel_by_session`)

This complexity justifies deferring subagents to Phase 2, after the core TUI shell is stable.

---

## 9. Permissions & Approvals

### Current RBAC (`mahavishnu/core/permissions.py`)

- 10 repo-level operations: `READ_REPO`, `WRITE_REPO`, `EXECUTE_WORKFLOW`, `MANAGE_WORKFLOWS`, `LIST_WORKFLOWS`, `VIEW_WORKFLOW_STATUS`, `CANCEL_WORKFLOW`, `READ_ADAPTERS`, `MANAGE_TERMINALS`
- Default roles: admin (all), developer (most), viewer (read-only)
- **Gap**: No tool-level permissions

### Proposed Extension: Risk-Tiered Permission Model

Add tool-level operations to `Permission` with risk tiers:

```python
class Permission(StrEnum):
    # Existing repo-level
    READ_REPO = "read_repo"
    WRITE_REPO = "write_repo"
    EXECUTE_WORKFLOW = "execute_workflow"
    # ... existing ...

    # New tool-level — risk tiered
    RUN_SHELL_READ = "run_shell_read"       # ls, cat, find, git status
    RUN_SHELL_WRITE = "run_shell_write"     # install, build, format
    RUN_SHELL_DESTRUCTIVE = "run_shell_destructive"  # rm, drop, truncate
    RUN_NETWORK = "run_network"             # curl, fetch, outbound requests
    WRITE_FILE = "write_file"
    EDIT_FILE = "edit_file"
    EXECUTE_TOOL = "execute_tool"
```

### Approval Flow (Inline, Not Modal)

The approval prompt renders **inline in the chat stream** (like Claude Code's `Allow? [y/n/e]`), not as a modal overlay:

1. Agent decides to run a shell command or edit a file
2. Mahavishnu checks RBAC — does the user's role include this permission tier?
3. If not, or if the action is in the "always ask" category, the TUI renders an inline approval block directly in the chat
4. User sees the command/file edit that prompted approval *right above* the prompt
5. Three options: **Approve** / **Deny** / **Edit before approving** (modify the proposed action in-place)
6. For batched tool calls: approve once per logical action group with summary ("Agent wants to edit 3 files and run 1 command — approve all?")
7. `ApprovalManager` records the decision for audit

### Command Risk Scoring

Shell commands are classified by pattern matching:

- **Read-only** (auto-approve in permissive mode): `ls`, `cat`, `find`, `git status`, `echo`
- **Write** (always ask): `pip install`, `uv run`, `ruff format`, file writes
- **Destructive** (always ask with confirmation): `rm -rf`, `drop table`, `chmod 777`, `curl | bash`
- **Network** (always ask or policy-gated): `curl`, `fetch`, outbound requests, webhooks
- **Deny-list** (never execute): commands matching known dangerous patterns

### Tool Input Validation

All LLM-generated tool call arguments are validated against their JSON Schema before execution. The existing Pydantic infrastructure supports this — add explicit schema validation at the MCP tool server boundary.

### Agno Adapter Streaming Gap

The current `agno_adapter_impl.py` (`_run_agent`, line 1005) calls `agent.arun()` which returns a complete `RunOutput`. There is no streaming callback, no token-by-token rendering hook, and `session_id` is stored in metadata but never passed to `agent.arun()`. **The TUI must bypass this adapter's `_run_agent` and call Agno's streaming API directly** (`agent.arun_stream()`), or the adapter needs a new streaming execution path. This is a Phase 0 item.

### Approval Manager Rework

The `ApprovalRequest.approval_type` field is typed as `Literal["version_bump", "publish"]`. Widening this to support `str` (or a `StrEnum`) is required, along with new option-generation branches in `_generate_default_options` (line 119) for each new approval type. The core `ApprovalManager` class (pending requests dict, create/respond/cleanup) is reusable. This is a moderate refactor, not a simple extension — included in Phase 0.

### PyCharm Fallback Gaps

Two gaps identified for TUI use: (a) `_fallback_search` uses `grep -rn` with `cmd.append(".")` hardcoded as the search root — needs a working directory parameter scoped to the current project/repo. (b) `pycharm_open_file` returns `{"opened": False}` on failure without enough semantic information for the TUI to decide whether to fall back to an internal file viewer. These are Phase 0 fixes.

### Consolidator Adaptation

The Nanobot `Consolidator` (lines 346-511) depends on nanobot-specific abstractions: `Session.messages` (list of dicts with `role`, `content`, `tools_used` keys) and `Session.last_consolidated`. Agno uses its own `RunResponse`/`RunOutput` with message objects, not plain dicts. The core algorithm (estimate tokens, pick user-turn boundary, archive via LLM summarization) is transportable, but an adapter layer is needed to translate Agno's message objects into the dict format the `Consolidator` expects. `MemoryStore` persistence (JSONL append) is independent and reusable as-is.

---

## 10. Implementation Phases

### Phase 0: Foundation (prerequisite for Phase 1)

- [ ] Implement `mahavishnu/session/checkpoint.py` — replace stub with real SB MCP calls
- [ ] Add `TUIConfig(BaseModel)` to `mahavishnu/core/config.py` — theme, keybindings, layout, syntax highlighting, max_history_lines
- [ ] Add file I/O agent tools — `read_file`, `write_file`, `edit_file`, `list_directory`, `search_files`
- [ ] Build MCP tool server bridge that exposes Mahavishnu's MCP tools to Agno agents
- [ ] Risk-tiered permission model (Section 9) — implement before any agent tool execution
- [ ] Add `WorktreePathValidator` to all PyCharm tool `file_path` arguments

### Phase 1: Core TUI Shell

- [ ] Textual app with CSS styling (dark theme matching terminal defaults)
- [ ] TUI Agent Bridge: `asyncio.Queue` message-passing between Textual and Agno background task
- [ ] Agno agent loop wired to chat panel with `memory_backend="none"`
- [ ] Streaming token output via `RichLog` — throttle at ~60fps, trim old content
- [ ] Basic tool execution with approval gating (echo results to tools panel)
- [ ] `Ctrl+K` command palette with fuzzy search and command taxonomy
- [ ] Built-in slash commands for session controls (`/status`, `/compact`, `/usage`, `/think`, `/restart`, `/stop`)
- [ ] Inline approval prompts for shell and file-edit actions
- [ ] Session-Buddy lifecycle wrapper (start, checkpoint, end) — optional runtime integration with graceful fallback
- [ ] Startup `doctor` check and first-run onboarding flow
- [ ] Activity feed panel with task/flow state, retries, and completion events
- [ ] `?` contextual help key
- [ ] `Ctrl+\` cancel mid-stream (graceful abort of Agno generation)
- [ ] Context compaction (adapted from Nanobot Consolidator) — not deferred to later phases
- [ ] Connection resilience: handle Mahavishnu not running, degraded, or mid-session crash

### Phase 2: File Viewer & Diff

- [ ] File viewer panel with syntax highlighting (via Pygments)
- [ ] Custom Textual diff view for before/after comparison (horizontal split mode)
- [ ] PyCharm diagnostics integration (wire to file viewer)
- [ ] Tree-sitter-based symbol extraction for navigation
- [ ] File open/jump-to-line commands
- [ ] Skill registry browser with search, browse, install, update, list, and versioning
- [ ] Session history and parity/compatibility checks for reproducible workflows
- [ ] Vertical split mode (chat left, file viewer right)

### Phase 3: Permissions & Audit

- [ ] Approval context sanitization (strip secrets before logging)
- [ ] Audit logging via worktree audit trail
- [ ] Configurable permission profiles (strict, normal, permissive)
- [ ] Tool-call audit log (immutable, reviewable)

### Phase 4: Advanced Features

- [ ] Tree-sitter find_references and go_to_definition
- [ ] PyCharm symbol refactor as agent tool
- [ ] Pool/worker management panel
- [ ] Prefect workflow trigger from TUI
- [ ] LlamaIndex RAG query from chat

---

## 11. Dependencies

### Python Packages

- `textual` — TUI framework
- `agno` — Agent loop (already in Mahavishnu)
- `pygments` — Syntax highlighting (Textual dependency)
- Existing Mahavishnu stack (FastMCP, Oneiric, etc.)

### External Services

| Service | Required? | Purpose |
|---------|-----------|---------|
| PyCharm MCP | No | Enrichment when available, degrade gracefully |
| Ollama | No | Local LLM option, not required |
| Anthropic API | No | Remote LLM option |
| OpenAI API | No | Remote LLM option |
| Session-Buddy | Phase 1+ | Session lifecycle tracking. Optional runtime integration; live checkpointing is enabled when available |
| Mahavishnu | Yes | Orchestration layer (MCP server) |

### Startup Resilience

The TUI must handle three Mahavishnu connection states:

1. **Not running** — fail fast with clear message, or offer to start it
2. **Starting but degraded** — connect anyway with reduced tool set (respect `HealthConfig.required`)
3. **Crashed mid-session** — reconnect or fall back to direct Agno without MCP tools

---

## 12. Open Questions

1. **Compaction trigger threshold** — What token count triggers Agno message compaction? configurable per-model?
2. **Approval scope for multi-tool calls** — Approve once per logical action group with summary (Section 9)
3. **File viewer auto-scroll** — Only jump on explicit user request, not auto-follow
4. **PyCharm diff payload shape** — Need to verify the exact JetBrains MCP response shape for file differences
5. **Command palette scope** — Start with frequently used tools only, expand based on usage patterns
6. **Activity feed persistence** — In-memory only, or persist to Session-Buddy?

---

## Review Summary

Six expert reviews were conducted on the initial draft. Below is a summary of the critical findings that shaped this revision.

### Reviews Conducted

| Review | Agent | Status |
|--------|-------|--------|
| Architecture | General-purpose | Completed |
| UX/Interaction | General-purpose | Completed |
| Security | General-purpose | Completed |
| Operational | General-purpose | Completed |
| Code Feasibility | Python Pro | Still running |
| Feature Completeness | (rate-limited) | Not completed |

### Critical Changes Made

1. **MCP client topology** — TUI is now an MCP client of Mahavishnu, not an embedded server. Architecture diagram and data flow updated.
2. **Async boundary** — Added explicit `asyncio.Queue` message-passing interface between Textual and Agno. Prevents loop coexistence issues.
3. **Agno memory backend** — Must be `none`. All persistence through Mahavishnu SB wrapper. Prevents split-brain recovery.
4. **Phase 0 added** — checkpoint.py stub replacement, TUIConfig, file I/O tools, MCP tool server bridge, risk-tiered permissions, path validation. These are prerequisites, not Phase 1 items.
5. **Risk-tiered permissions** — Replaced binary RUN_SHELL with three tiers (read/write/destructive) plus deny-list patterns. Ships before any agent tool execution.
6. **Inline approval** — Modal replaced with inline chat block (like Claude Code's `Allow? [y/n/e]`). Added "edit before approving" option.
7. **Keyboard shortcuts** — Fixed `Ctrl+D` conflict (now `Ctrl+Shift+D`). Added `Ctrl+L`, `Ctrl+W`, `Escape` semantics, `?` help, `Ctrl+\` cancel.
8. **Activity feed panel** — Added as fifth panel for background events.
9. **Context compaction promoted to Phase 1** — No longer deferred. Essential for long sessions.
10. **File I/O as first-class tools** — Agent needs basic file operations before advanced tools.
11. **Path validation** — PyCharm file_path arguments validated through WorktreePathValidator.
12. **Tool input schema validation** — LLM-generated arguments validated before execution.
13. **Approval context sanitization** — Secrets stripped before display and logging.
14. **Session-Buddy optional in Phase 1** — Contradiction resolved. TUI works offline with local SQLite, gains live checkpointing when SB available.
15. **TUIConfig(BaseModel)** — New config model for TUI-specific settings.
16. **Connection resilience** — Three-state startup handling for Mahavishnu availability.
17. **Streaming throttle** — ~60fps rendering to prevent layout thrashing. Auto-trim old RichLog content.
18. **MCP tool server bridge** — Explicitly called out as a new component needed for Phase 0.
19. **PydanticAI exclusion** — Explicitly stated why it was excluded from the engine stack.
20. **Cancel mid-stream** — `Ctrl+\` for graceful Agno generation abort.
21. **Skills System (Section 7)** — Nanobot's `SkillsLoader` adopted wholesale. Markdown-based progressive disclosure (metadata → SKILL.md → bundled resources). Zero code coupling, stdlib-only deps. TUI gains `/skill` and `/skills` commands.
22. **Subagents (Section 8)** — Background task execution via separate `asyncio.Task` loops. Nanobot's `SubagentManager` adapted for Agno. Deferred to Phase 2 due to async complexity (task management, result routing, cancellation).

---

## 13. Addendum: Possible Additions From OpenClaw, ClawHub, and Claw Code

The items below are intentionally **non-blocking**. They are useful references from the broader repo scan and can be adopted later without changing the core architecture or phase gates.

### Core Additions

Highest-priority non-v1 candidates to revisit first:
- Vector search for skills and lore, so the command palette can surface relevant skills quickly

### Deferred V2 Candidates

The following items are intentionally out of v1 scope but kept here for later review:

- `/think` as a user-facing reasoning-depth control beyond the baseline session controls
- `/restart` and `/stop` if they are treated as convenience commands rather than required controls
- `/activation` or equivalent mode toggle for switching behaviors or agent modes
- Prefect workflow trigger from the TUI
- LlamaIndex RAG query from chat
- Advanced subagents beyond the basic Phase 2 model
- Container-first or isolated-run execution mode for dangerous or heavy operations
- A more explicit task orchestration view if the implementation grows beyond simple chat plus tools
- Skill registry install/update/versioning beyond browse/search/list
- Session history and parity/compatibility checks
- Tree-sitter `find_references` and `go_to_definition`
- PyCharm symbol refactor integration
- Rich task retry/recovery views
- Expanded model switching UI beyond the core command palette

### Nice-to-Have / Experimental

- Optional voice or canvas-oriented surfaces if the TUI evolves into a broader control plane
- Pin/favorite workflows for frequently used skills
- Skill moderation workflow
- Full task orchestration builder

### Triage Guidance

- Promote to core scope only if the feature is required for daily developer workflow.
- Keep in the addendum if the feature is mostly operational, experimental, or best treated as a later-phase enhancement.
- Prefer not to expand the initial shell until chat, tools, approvals, and file navigation are stable.

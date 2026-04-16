# Bodai Agent Platform Master Spec

**Status:** Draft
**Date:** 2026-04-16
**Scope:** Consolidated plan for Hermes-inspired TUI work, Mahavishnu adapter strategy, and Bodai ecosystem integration

## 1. Purpose

This document consolidates the recommendations from:

- the Hermes Agent comparison
- the Agno / Prefect / LlamaIndex adapter review
- the proposed Bodai TUI spec at [2026-04-09-tui-design.md](/Users/les/Projects/mahavishnu/docs/superpowers/specs/2026-04-09-tui-design.md)

The goal is to define a clean boundary for:

- what stays in the TUI
- what belongs in Mahavishnu core
- what belongs in the broader Bodai ecosystem
- what should be dropped because it is redundant or out of scope

## 2. Platform Thesis

Bodai should be a layered system, not a single monolith:

1. **TUI layer** - local interactive developer surface
2. **Mahavishnu layer** - orchestration, routing, policy, and adapter mediation
3. **Ecosystem layer** - persistent knowledge, storage, quality, session lifecycle, and remote delivery

This keeps the TUI lightweight, preserves Mahavishnu as the control plane, and avoids duplicating Hermes-style runtime features in multiple places.

## 3. Engine Roles

### 3.1 Agno

Use Agno as the interactive agent runtime:

- chat / reasoning loop
- tool selection and tool calling
- multi-agent teams
- provider routing
- skill-style instruction loading
- memory/session primitives when useful

Current Mahavishnu state:

- Agno is integrated as a real adapter and team manager, not a placeholder
- native MCP tools and local tools are wired in
- the TUI spec intentionally avoids Agno persistence by setting the memory backend to none

### 3.2 Prefect

Use Prefect for durable workflow orchestration:

- scheduled jobs
- retries and state transitions
- deployments
- work pools
- batch execution
- operational workflow tracking

Current Mahavishnu state:

- Prefect is real and should remain the primary engine for non-interactive workflow execution
- the adapter already exposes deployment and work-pool management

### 3.3 LlamaIndex

Use LlamaIndex for knowledge and retrieval:

- ingestion
- indexing
- retrieval
- query engines
- chat engines over knowledge
- workflows / agentic retrieval
- evaluation / observability around retrieval

Current Mahavishnu state:

- LlamaIndex is already used for repo-aware indexing and query
- the current integration is mostly filesystem + code graph + OpenSearch / memory fallback

## 4. How the Engines Work Together

Mahavishnu should route by task class:

- `AI_TASK` -> Agno first
- `RAG_QUERY` -> LlamaIndex first
- `WORKFLOW` -> Prefect first
- `BATCH_TASK` -> Prefect first
- `INTERACTIVE_TASK` -> Agno first

Fallback behavior should remain explicit and observable:

- Agno -> LlamaIndex -> Prefect for interactive / agentic work
- LlamaIndex -> Agno -> Prefect for retrieval-heavy tasks
- Prefect -> Agno -> LlamaIndex for durable workflows

The practical division is:

- **Agno** is the reasoning and tool-using agent
- **Prefect** is the durable scheduler and workflow runner
- **LlamaIndex** is the retrieval and knowledge substrate

## 5. Keep / Adapt / Drop

### 5.1 TUI Layer

#### Keep

- MCP-client topology to Mahavishnu
- file viewer / diff / tools / activity panels
- inline approvals
- command palette
- slash commands
- session lifecycle integration
- context compaction
- skills browser / loader
- subagents
- PyCharm integration
- tree-sitter navigation

#### Adapt

- Agno memory usage
  - keep TUI session state external and authoritative
  - do not let Agno become a second source of truth
- approvals
  - broaden from repo actions to tool-risk approvals
- skills
  - use progressive disclosure, but keep skills tied to the TUI and task context
- context files
  - auto-load `AGENTS.md`, `CLAUDE.md`, `.cursorrules`, `SOUL.md`
- Hermes-style references
  - add `@file`, `@diff`, and `@url` reference semantics

#### Drop

- standalone assistant runtime
- public product framing
- built-in messaging bot runtime in the TUI itself
- OpenAI-compatible server mode inside the TUI
- duplicate persistence layer separate from Session-Buddy

### 5.2 Mahavishnu Core

#### Keep

- adapter routing
- fallback chains
- work pools
- worker orchestration
- RBAC and approvals
- Session-Buddy lifecycle wrapper
- OpenTelemetry / quality / audit infrastructure
- MCP tool surface

#### Adapt

- Prefect:
  - expose more of the native workflow surface where it matters:
    - blocks
    - automations / events
    - richer work-pool controls
    - artifacts / variables if operationally useful
- LlamaIndex:
  - expand beyond filesystem ingestion to more connectors
  - add retrieval evaluation and observability
  - consider chat engines or workflows where they replace custom glue
- Agno:
  - make team / skill / tool boundaries clearer
  - consider AgentOS-style runtime management concepts if they help ops and debugging

#### Drop

- any attempt to use Mahavishnu as a full chat application
- any duplicate agent memory implementation that conflicts with Session-Buddy
- any parallel workflow engine that duplicates Prefect

### 5.3 Bodai Ecosystem

#### Keep

- Mahavishnu as orchestrator
- Akosha as intelligence / search / embedding layer
- Dhara as persistent object storage
- Session-Buddy as session lifecycle and knowledge graph layer
- Crackerjack as quality gate
- Oneiric as runtime and component resolution foundation

#### Adapt

- add messaging gateways as first-class ecosystem capabilities
- add shared context-file and reference semantics across tools
- add shared plugin / hook registration where it reduces duplicate glue
- add browser automation only if there is a concrete delivery use case

#### Drop

- ecosystem-wide duplication of TUI-specific UI logic
- separate memory stores that bypass Session-Buddy
- vendor-specific runtime features that do not improve shared infrastructure

## 6. Hermes Imports: What to Integrate First

### 6.1 Highest Priority

1. **Messaging gateway adapters**
   - Telegram
   - Discord
   - Slack
   - WhatsApp
   - This should live in the ecosystem layer, not inside the TUI

2. **Context-file and reference semantics**
   - auto-load project context files
   - `@file`, `@diff`, `@url`
   - this belongs in the TUI and should be reflected in agent prompt construction

3. **Checkpoint / rollback workflow**
   - belongs in the TUI and Mahavishnu worktree safety path

4. **Skills system**
   - belongs in the TUI and Agno integration path

5. **Provider routing / fallback / credential pools**
   - belongs in Mahavishnu core and the LLM gateway layer

### 6.2 Conditional Priority

6. **Plugin / hook model**
   - only if it reduces coupling
   - otherwise, prefer explicit adapters and well-typed extension points

7. **Browser automation**
   - only if the Bodai roadmap includes real external task execution

8. **ACP / editor integration**
   - valuable if it complements PyCharm and the TUI without duplicating the same workflow surface

### 6.3 TUI Operating Model

The TUI spec is now treated as a subsystem of this master plan, not a separate product spec.

#### Core architecture

- Textual renders the UI
- Agno may provide the agent runtime behind Mahavishnu, but the TUI never owns or embeds that runtime
- Mahavishnu remains the orchestration owner and MCP boundary
- the TUI talks to Mahavishnu over MCP, not by embedding the server process or calling engine internals directly
- the TUI must not become the canonical owner of memory, workflow state, skill persistence, or learning policy

#### Panels

- chat panel for streaming interaction
- file viewer for source browsing
- tools panel for diagnostics, search, and execution results
- activity feed for background progress and pool/workflow events
- status bar for session, model, and connection state

#### Key interactions

- `Ctrl+K` for command palette
- `Ctrl+Shift+D` for diff preview
- `Ctrl+G` for file/line navigation
- `Ctrl+P` for approval prompts
- `Ctrl+L` to clear scrollback
- `Ctrl+W` to close the active panel
- `Escape` to dismiss or cancel
- `Ctrl+\` to cancel generation

#### Slash commands

- `/status`
- `/compact`
- `/usage`
- `/think`
- `/skill <name>`
- `/skills`
- `/restart`
- `/stop`

#### Implementation phases

Phase 0:

- replace stub session checkpointing with real Session-Buddy calls
- add TUI-specific config
- add basic file I/O tools and the MCP tool bridge
- add risk-tiered permissions and path validation

Phase 1:

- build the core Textual shell
- wire Agno streaming through queues
- render approvals inline
- add context compaction and startup resilience

Phase 2:

- add file viewer, diff viewer, PyCharm enrichment, and tree-sitter navigation
- add skills browser and session-history parity checks
- add split-pane modes

Phase 3:

- harden audit and policy controls
- sanitize approvals
- log tool calls immutably

Phase 4:

- add deeper refactor, pool, workflow, and RAG integration

#### TUI boundary rule

The TUI should remain a client-facing developer tool, not a second orchestration platform. Any feature that is better owned by Mahavishnu core, Session-Buddy, Akosha, or Prefect should live there instead of in the UI.

## 7. Feature Gaps by Layer

### 7.1 TUI Gaps Relative to Hermes

- messaging surfaces
- voice
- browser automation
- native `@` references
- public assistant / API-server mode

### 7.2 Mahavishnu Gaps Relative to Its Own Stated Strategy

- more of Prefect’s operational surface
- more of LlamaIndex’s connector and evaluation surface
- clearer first-class support for Agno skills / runtime controls

### 7.3 Bodai Gaps Relative to a Full Platform

- message-first external entry points
- a shared reference/annotation format across tools
- a more explicit agent operations model
- a standardized plugin boundary

### 7.4 Learning and Skill Synthesis

Hermes' strongest differentiator is not just skills loading. It claims an experience loop:

- persist useful facts about the user and project
- search prior conversations
- distill repeated behavior into reusable skills
- improve those skills over time
- keep the assistant increasingly personalized across sessions

#### Current Bodai state

We have supporting artifacts and partial runtime primitives:

- Session-Buddy checkpoints and session lifecycle tracking
- `mahavishnu/memory/MEMORY.md` style long-term memory
- Akosha search across systems and semantic memory lookup
- skill-oriented specs and the Skill Creator workflow in docs
- conversation archaeology and recovery-oriented skills in the superpowers area

What we do **not** yet have is a closed loop that automatically:

- observes successful agent behavior
- drafts a new skill or updates an existing one
- validates that draft against policy / tests
- promotes it into the active skill set

#### Recommendation

Add a bounded learning pipeline, but do it in the ecosystem layer, not in the TUI runtime:

- use Session-Buddy to store session evidence and checkpoints
- use Akosha to retrieve past examples, traces, and similar successes
- use a skill synthesis worker to draft or update skills
- require human review before activation
- optionally surface the review queue in the TUI
- keep authored skills, generated drafts, and active runtime skills in separate namespaces or folders
- define explicit promotion states: `draft` -> `review` -> `active` -> `deprecated`
- allow rollback to the previous active skill version
- do not let the agent self-promote a skill without review
- treat any current in-memory learning modules as transitional caches until a reviewed promotion path exists

This gives us the useful part of Hermes' self-improvement loop without letting an agent rewrite its own behavior unchecked.

## 8. Redundancy Rules

Do not implement multiple copies of the same concern:

- one authoritative session lifecycle owner: Session-Buddy
- one durable workflow owner: Prefect
- one interactive agent owner: Agno
- one retrieval owner: LlamaIndex
- one orchestration owner: Mahavishnu

If a proposed feature does not clearly choose one owner, it is probably too fuzzy to ship.

## 9. Architectural Corrections

These are the concrete corrections that reduce overlap and simplify the ecosystem.

### 9.1 One owner per concern

Make ownership explicit and non-overlapping:

| Concern | Canonical owner | Notes |
|---|---|---|
| Interactive agent loop | Agno | Ephemeral runtime only; no long-term persistence authority |
| Durable workflows | Prefect | Schedules, retries, deployments, work pools, state transitions |
| Retrieval / knowledge | LlamaIndex + Akosha | LlamaIndex for indexing/querying, Akosha for cross-system semantic recall |
| Session lifecycle | Session-Buddy | Start/end/checkpoint/restore; source of truth for session continuity |
| Persistent artifacts | Dhara | Store blobs, files, and durable objects |
| Orchestration and routing | Mahavishnu | Chooses engines, applies policy, exposes MCP tools |
| UI / operator surface | TUI | Present state, do not own it |
| Quality / gating | Crackerjack | Validation, checks, and release gates |

Recommended interpretation:

- if a concern needs durable truth, it belongs to the canonical owner in the table
- if a concern is only an optimization, cache, or preview, it may exist locally but must never become the authority
- if a concern spans multiple rows, it must be split before implementation

### 9.2 Keep the UI thin

The TUI should own:

- rendering
- input capture
- display of tool results
- local navigation
- approval presentation

The TUI should not own:

- session storage
- workflow state
- skill persistence
- learning policy
- routing policy
- artifact storage

### 9.3 Split learning into stages

Do not treat learning as one feature. Split it into a pipeline:

1. Observe
   - record successful sessions, tool usage, and outcomes
2. Store
   - persist evidence in Session-Buddy / Akosha / Dhara as appropriate
3. Retrieve
   - look up prior successes and similar failures
4. Synthesize
   - draft a skill or recommendation
5. Review
   - require human approval
6. Activate
   - publish to the active skill set
7. Rollback
   - support downgrade to the previous version

Only observation and retrieval should run automatically. Synthesis and activation should be review-gated.

### 9.4 Reuse mature external systems first

Prefer established engines when they already solve the problem well:

- Prefect for durable workflow orchestration
- Temporal if durable execution semantics later need to go beyond what Prefect provides
- LlamaIndex for retrieval and knowledge workflows
- Agno for interactive agent loops
- OpenClaw for channel-aware delivery and messaging workflows when that runtime fits better than a custom implementation

Only build custom subsystems when the existing tool:

- does not cover the required boundary,
- imposes unacceptable integration cost,
- or cannot be shaped to Bodai’s ownership model cleanly.

### 9.5 Simplify overlapping state

Reduce current overlap by consolidating these categories:

- one active session record per session
- one active workflow record per workflow
- one active skill record per skill version
- one active memory namespace per concern

Transitional in-memory caches are fine, but they must be treated as caches, not authorities.

### 9.6 Deprecation targets

Review these for consolidation or deprecation:

- ad hoc memory stores outside Session-Buddy / Akosha
- workflow state duplicated across router/orchestrator modules
- learning engines that only work in-memory and never promote artifacts
- UI-level persistence or hidden state
- agent-memory defaults that conflict with the TUI memory policy
- direct engine ownership in the TUI layer

## 10. Recommended Implementation Order

### Phase 1

- finish the TUI boundary
- add Hermes-style context references
- formalize skills loading in the TUI as a read-only browser and launcher, not a persistence authority
- keep approvals inline and tool-risk based
- keep Agno memory externalized

### Phase 2

- add messaging adapters to the ecosystem
- expand Prefect to blocks / events / richer work-pool management
- expand LlamaIndex ingestion and evaluation
- keep any TUI skills browser or session-history view read-only

### Phase 3

- add browser automation only if a concrete workflow demands it
- add plugin/hook support only where explicit extension points are insufficient
- consider ACP/editor integration if it adds meaningful value beyond the TUI and PyCharm
- keep orchestration state and promotion logic outside the UI

## 11. Decision Summary

### Keep

- Mahavishnu as the orchestrator
- Agno as the interactive agent engine
- Prefect as the workflow engine
- LlamaIndex as the retrieval engine
- the TUI as a client of Mahavishnu

### Adapt

- Hermes-style skills, context files, checkpoints, and references
- Agno, Prefect, and LlamaIndex surfaces that are currently underused

### Drop

- any attempt to make the TUI a standalone platform
- duplicate memory and session ownership
- duplicate workflow orchestration
- messaging runtime inside the TUI itself

### Integrate

- messaging gateways
- context-file semantics
- rollback / checkpoint workflow
- skills
- provider routing / fallback
- retrieval connectors and evals
- optional browser automation

## 12. Implementation Plan

The operational follow-up to this spec is [2026-04-16-bodai-master-implementation-plan.md](./2026-04-16-bodai-master-implementation-plan.md).

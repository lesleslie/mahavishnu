# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.9.0] - 2026-07-15

### Added

- **BREAKING:** terminal: Drop pty_mcp_python backend
- activity: Surface Mahavishnu worker events to the Claude session
- Add 131 unit tests for mahavishnu/mcp/ + resolve collection collision
- audit-H8: Add SLOs + rollback CLI for Plan 1 (bodai-crow) and Plan 5 (distilled-workflows)
- audit: Recognize framework decorators and lifecycle methods
- bodai: Close Phase 6 — Mahavishnu publisher, hook replacement, CLI+docs
- bridge: Wire CallerKind quotas and dispatch_to_pool for ultracode subagents
- cli: Wire 11 orphan methods across 2 subsystems
- core: Add DharaThinClient SQL proxy execute/query
- crow: Plan 1 Tasks 7-11 - web extract escalation + server wiring + integration tests
- crow: Wire terminal tool (single PTY, no concurrency)
- CrowTerminalAdapter uses session-aware tools
- distill: Three-zone skill pipeline interface + InMemory impl
- eventbridge: Add Mahavishnu settings field + adapter
- events: Oneiric wire standardization (canonical boundary, decoder, observability)
- mahavishnu: Plan 3 Tier 1 — repo diff + repo pr create CLI
- mahavishnu: Plan 3 Tier 1 — show_primitive + list_primitives MCP tools
- mahavishnu: Plan 7 Phase 2 — FastMCP 3.4 consumer bump
- mcp: Add Mahavishnu eventbridge publish_to_eventbridge tool
- observability: Add adapter_runtime substrate (Spec #8 Phase 3)
- Oneiric EventBridge subscriber + /bodai-status surface (Phase 6A+6B)
- Per-session subprocess pool + crow_terminal_* tools
- Plan 1 Tasks 1-6 — bodai-crow HTTP MCP scaffold + tools
- Plan 5 Phase A.0 foundational substrate for distilled workflows
- Plan 5 Phase A.0 foundational substrate for distilled workflows
- Plan 5 Phase A.1 — distilled workflows storage substrate
- Plan 5 Phase A.1 — distilled workflows storage substrate
- precommitment: Hypothesis lock dataclass + signature + LockStore + CLI
- quality: Add scripts/audit_orphans.py to detect unwired code
- quality: Add wire-up discipline to prevent built-but-not-wired features
- reports: Add apply_confidence_ceiling gate with arithmetic cap
- reports: Add CompletionReport Pydantic v2 model + thin file-backed persister
- self-heal: Add L1 retry, L2 noop pin, L3 rule extraction (Spec #4)
- Ship project-scoped SOP evolution v0 (Spec #7, Phase 3)
- skill-tools: Wire 4 skill_map functions as CLI commands
- skill: Add ty type checker guidance to crackerjack-compliant-code
- style-sop: Add check_content validator with regex bans
- style-sop: Add Crackerjack skill anti-ai-flavor-check
- style-sop: Add default SOP package resource, discovery, and parser
- Task 13 Phase B — Mahavishnu MCP clone tools + ecosystem DAG workflow
- tenancy: Add TenantContextPack model + publisher interface (Spec #9)
- terminal: Add PTY backend registry
- terminal: Thread adapter_preference to McpretentiousAdapter
- tool-prefs: Wire CLAUDE.md Tool Preferences and mahavishnu-orchestrator delegation
- Wire apply_confidence_ceiling into distiller output consumer
- Wire Mahavishnu EventBridgePublisher at server startup
- workflows: Add Spec #10 progress snapshots with CLI watch stub

### Changed

- backup_cli: Extract command bodies to reduce C901
- dhara: Extract _invoke helpers, drop C901 noqa
- Fix `from __future__ import annotations` placement + ruff line-join
- Mahavishnu (quality: 69/100) - 2026-06-22 19:47:42
- Mahavishnu (quality: 69/100) - 2026-06-26 08:09:06
- Mahavishnu (quality: 70/100) - 2026-06-23 02:08:47
- Mahavishnu (quality: 70/100) - 2026-06-23 04:26:48
- Mahavishnu (quality: 71/100) - 2026-06-27 00:03:32
- Mahavishnu (quality: 71/100) - 2026-06-27 05:00:07
- Mahavishnu (quality: 73/100) - 2026-06-29 15:55:23
- Mahavishnu (quality: 73/100) - 2026-07-04 03:38:39
- Mahavishnu (quality: 73/100) - 2026-07-05 10:41:34
- Mahavishnu (quality: 73/100) - 2026-07-06 04:33:13
- Mahavishnu (quality: 73/100) - 2026-07-11 11:08:55
- Mahavishnu (quality: 73/100) - 2026-07-15 11:15:13
- Mahavishnu (quality: 77/100) - 2026-07-06 11:08:00
- mcp: Extract C901 OOM helpers across 5 functions
- Multi-backend PTY implementation
- Multi-backend PTY toolservers design
- pools: Remove KubernetesPool (immediate removal)
- precommitment: Use Path.unlink instead of os.unlink
- quality: Bring all 98 C901 offenders in mahavishnu/ under 15
- Session-buddy (quality: 72/100) - 2026-07-15 10:38:28

### Fixed

- cli: Unblock post-commit hook by surfacing Path runtime imports
- coordination-cli: Repair two security findings in repo commands
- crow: Drop unused FastMCP import + correct ty ignore prefix in test
- crow: Implement eviction grace sequence + propagate cancellation + silence B110
- crow: Replace asserts with RuntimeError, log tracebacks, drop unused imports, fix isort
- crow: Retype new-tool returns, harden test stubs, set-comparison assertion
- crow: Type register() with Union[FastMCP, StandardServer]
- crow: Wire shutdown_all_sessions into FastMCP lifespan
- distill: H4 — source provenance gate (audit remediation)
- distill: H5 — file-backed weekly LLM cap with fcntl locking
- H6 — gate distiller on MAHAVISHNU_USER_ID + PUBLISHER_ALLOWLIST
- H6 — gate distiller on MAHAVISHNU_USER_ID + PUBLISHER_ALLOWLIST
- mahavishnu: Raise mcp-common floor + drop PYTHONPATH workaround in tests
- mcp: Await app.is_healthy() in get_health
- mcp: Preserve wrapper signature in _wrap_tool_handler
- plan: Spec #4 three-layer-self-heal C4 — L2 stub + double-invocation
- precommitment: Persist locks to disk so verify/check_post_hoc work across processes (audit H-PRECOMMIT)
- quality: Clean creosote exclusions + add betterleaks config
- quality: Noqa C901 on FastMCP register_X_tools functions
- repositories: Re-export TaskFilter and TaskEventFilter
- ruff: Gate fast-hook failures from 912 → 0 errors
- security: Close caller-identity-default and admission-control-bypass in pool_execute
- security: Restore timing-safe control test + drop redundant pip-audit fanout
- self-heal: Scrub credentials from L3 rule message and rule_id (audit H-H4)
- terminal: Honor BUILTIN_BACKENDS.tool_map when resolving tool names
- terminal: Manager.create raises actionable error when mcp_client is None for BUILTIN_BACKENDS preference
- terminal: Route all BUILTIN_BACKENDS names through McpretentiousAdapter
- terminal: Use BUILTIN_BACKENDS for mcpretentious launch
- Thread adapter_preference to McpretentiousMCPClient

### Documentation

- 2026-06 docs batch update across runbooks, followups, plans, specs
- Add bandit # nosec annotations to example curl lines
- Add Bodai crow MCP server design spec
- Apply 4-agent review audit to crow server design spec
- Batch of 10 implementation plans (2026-06-22)
- Bodai crow HTTP MCP server implementation plan
- Bodai ecosystem candidate evaluation — 20 triaged, 5 deep-dived
- crow: Document concurrent sessions + known limitations
- mahavishnu: Plan 1 SSRF runbook for bodai-crow-server
- MCP server family MCPBaseSettings migration plan
- plan: Correct attribution -- these are standalone Bodai MCP servers, not mycelium-core
- plan: V2 — apply 5 blocking review fixes
- quality: Add coverage backlog report identifying untested modules
- Record Bodai observability pattern + draft Phase 6 plan
- Revert "docs(sdd): task-4 report for gated mcpretentious integration smoke"
- sdd: Task-4 report for gated mcpretentious integration smoke
- spec: Adapter-runtime-observability v1.0 — Phase 3 (pivot)
- spec: Anti-ai-flavor-style-sop v1.0 — Phase 2
- spec: Completion-report-schema-v1 design — Phase 1 foundational
- spec: Confidence-ceiling-gate v1.1 — Phase 1
- spec: Defer crawl4ai — Playwright dep + 0.x version not worth it
- spec: Live-observe-presence-over-gate v1.0 — Phase 3
- spec: Multi-tenant-context-packs v1.0 — Phase 3
- spec: Precommitment-hypothesis-lock v1.1 — Phase 1
- spec: Project-scoped-sop-evolution v1.0 — Phase 3
- spec: Three-layer-self-heal v1.0 — Phase 2
- spec: Three-zone-skill-pipeline v1.0 — Phase 2
- spec: V3 bodai-crow — rapidfuzz vendor strategy, oneiric httpx2 scope
- spec: V4 bodai-crow — httpx2 tier taxonomy in §9
- spec: V5 bodai-crow — review-pass fixes
- terminal: Add trailing newline to backends.md
- terminal: Document built-in PTY backends
- terminal: Document dual-spawn mcpretentious at boot

### Testing

- crow: Update 3 pre-existing assertions for current port + opt-in design
- eventbridge: Real Oneiric transport round-trip integration tests
- Fix stale imports + field names in test_messaging_compat
- terminal: Gated integration smoke for mcpretentious

### Internal

- deps: Remove unused beautifulsoup4 dependency
- drafts: Persist Workflow-tool scripts for Phases 3-5
- examples: Remove 3 dead-code orphans, document 3 symmetric-API methods
- gitignore: Add *.backup.* and *.backup.json patterns
- mahavishnu: Migrate mcp-common[treesitter,llm] → dep-groups
- mcp: Switch crow from HTTP to stdio transport
- Remove generic agents covered by mycelium-core plugin
- Remove nanobot/opencode artifacts and clean up root directory
- repo: Untrack 23 .backup.json artifacts and tighten gitignore
- sdd: Smoke test multi-backend PTY
- Skill_map curation + bifrost config template
- Update uv.lock (astroid typo fix, coverage bump)

## [0.8.0] - 2026-06-20

### Added

- a2a: Add MHV-310/311 error codes and AgentCard model
- Activate crow adapter; add crow-mcp config + runbook; deprecate DebugMonitorWorker
- Add A2AClient, A2AWorker, and registry entry
- Add A2ASettings config models and YAML block
- Add CrowTerminalAdapter backed by crow-mcp PTY toolserver
- Add inbound A2A server routes and bootstrap mount
- Add mahavishnu.tui module with TUI_AVAILABLE, FallbackRichFormatter, get_console
- Add MHV-307 error code; fix TerminalError to accept custom code
- cli: Add 'monitor watch' Textual dashboard command with Rich fallback
- cli: Replace quality_check stub with Rich-formatted Crackerjack integration
- config: Add crow-mcp entry to .mcp.json (http://127.0.0.1:8675/mcp)
- config: Add OpenHandsSettings with is_relative_to path guard; add openhands yaml block + test
- deps: Add [vector] dep group with turbovec[llama-index]~=0.1
- errors: Add MHV-308 OPENHANDS_SERVICE_ERROR, MHV-309 OPENHANDS_TASK_FAILED
- llamaindex: Add TurboVec fallback when OpenSearch unavailable; rename memory backend to memory-implicit
- mcp: Add openhands_run, openhands_status, openhands_cancel, openhands_health tools
- tui: Add MonitorApp Textual dashboard and Pool/Worker status widgets
- workers: Add CrowWorker (ACP), 5 new registry entries; delete TerminalAIWorker
- workers: Add OpenHandsWorker + GATEWAY registry entry

### Changed

- Mahavishnu (quality: 68/100) - 2026-06-19 01:43:16
- Mahavishnu (quality: 68/100) - 2026-06-20 02:28:39
- Mahavishnu (quality: 69/100) - 2026-06-20 08:38:15

### Fixed

- a2a: Add inbound auth middleware, public WorkerManager API, and registry fixes
- a2a: Batch security and quality hardening from fan-out review
- a2a: Fix http_app mount, execute_fn interface, config extra:forbid, version field
- a2a: Store create_task ref, add logger to server, remove dead TYPE_CHECKING block
- Add from __future__ import annotations to errors.py
- Apply 4 post-merge cleanup items from Wave 1 review
- cli: Complete get-dashboard Rich migration; remove unused refresh param; add future import
- Complete resilience stub in test_initialize_runtime_services_fallback_branches
- engines: Replace stdlib logger in llamaindex_adapter_impl with oneiric get_logger
- errors: Add RECOVERY_GUIDANCE for MHV-307 through MHV-311
- mcp: Lazy MahavishnuSettings; is_relative_to path check; fix logger.warning in except
- Move DebugMonitorWorker deprecation to __init__; add from __future__ to config.py
- SSE timeout, oneiric logger in bootstrap, quality_cli stub interface
- terminal: Use oneiric.core.logging; hoist uuid import; update __init__ docstrings
- tui: Use oneiric logger in command_palette
- workers: Add from __future__ to debug_monitor + manager; remove dead code after raise
- workers: Close httpx client unconditionally; remove \_get_json anti-pattern; rename test class
- workers: Stop() try/finally; from_dict error_code roundtrip; remove unused MagicMock import

### Documentation

- Add external integrations design spec (crow-cli, OpenHands, Toad TUI)
- Add implementation plans for Track 1-4 (crow-cli, OpenHands, TUI, TurboVec)
- Add Track 4 (TurboVec explicit LlamaIndex fallback) to integrations spec
- Add Wave 2a chaos hardening spec (OpenHands + crow-mcp unit tests)
- Add Wave 2b A2A worker & server spec (Google A2A protocol)
- Add Wave 2b A2A Worker implementation plan
- Fix 3 plan issues before SDD (unused imports, line length, settings test)
- Revise external integrations spec (post-subagent review)

### Testing

- Add 5 unit chaos tests for OpenHandsWorker and CrowTerminalAdapter
- llamaindex: Strengthen TurboVec test assertion to check exact instance
- terminal: Add command-guard tests for SHELL rejection and GATEWAY allowance

## [0.7.3] - 2026-06-15

### Added

- fixup! feat(pools): add PEER_AFFINITY selector (Item 2)
- pools: Add PEER_AFFINITY selector (Item 2)
- routing: Caller-side auth for PEER_AFFINITY (Item D)

### Fixed

- Resolve 13 pre-existing test failures

### Documentation

- Add ADR-014 for Honcho peer model routing precedence (Item 3)

### Testing

- Fan-out coverage push to 10 modules (~11% -> ~99%)
- Fan-out coverage push to 8 modules (wave 2026-06-12)
- Fan-out coverage wave 2 — 8 more modules to 85-100%
- Increase coverage by +1.47% (88.93% → 90.40%) across 9 modules

## [0.7.2] - 2026-06-07

### Added

- Add TerminalGridManager for grid orchestration
- crackerjack: Wire ecosystem-gitignore audit into the quality gate
- scripts: Cross-repo .gitignore audit for the Bodai ecosystem
- terminal: Add grid models and exception hierarchy
- terminal: Refactor ITerm2Adapter to use shared AppleScript bridge

### Changed

- automation: Remove PyXA/ATOMac, add NativeMacOSBackend using osascript+cliclick+screencapture
- Mahavishnu (manual) - 2026-06-04 03:18
- Mahavishnu (quality: 63/100) - 2026-05-31 04:40:38
- Mahavishnu (quality: 66/100) - 2026-06-01 20:46:04
- Mahavishnu (quality: 66/100) - 2026-06-02 04:46:57
- Mahavishnu (quality: 66/100) - 2026-06-03 20:04:54
- Mahavishnu (quality: 66/100) - 2026-06-03 20:56:54
- Mahavishnu (quality: 67/100) - 2026-06-02 06:04:15
- Mahavishnu (quality: 67/100) - 2026-06-03 04:01:36
- Mahavishnu (quality: 67/100) - 2026-06-03 18:24:58
- Mahavishnu (quality: 67/100) - 2026-06-04 00:23:08
- Mahavishnu (quality: 67/100) - 2026-06-04 01:54:45
- Mahavishnu (quality: 67/100) - 2026-06-04 02:15:04
- Mahavishnu (quality: 67/100) - 2026-06-04 02:38:00
- Mahavishnu (quality: 67/100) - 2026-06-04 02:38:53
- Mahavishnu (quality: 67/100) - 2026-06-04 02:39:36
- Mahavishnu (quality: 67/100) - 2026-06-04 03:07:13
- Mahavishnu (quality: 67/100) - 2026-06-04 04:13:31
- Mahavishnu (quality: 67/100) - 2026-06-04 21:04:38
- Mahavishnu (quality: 67/100) - 2026-06-04 23:40:03
- Mahavishnu (quality: 67/100) - 2026-06-05 04:23:35
- Mahavishnu (quality: 67/100) - 2026-06-07 08:37:11
- Mahavishnu (quality: 68/100) - 2026-05-22 06:04:43
- Mahavishnu (quality: 68/100) - 2026-05-23 02:33:48
- Mahavishnu (quality: 68/100) - 2026-05-23 05:52:04
- Mahavishnu (quality: 68/100) - 2026-05-29 06:53:13
- Mahavishnu (quality: 83/100) - 2026-05-25 06:21:15
- Mahavishnu (quality: 97/100) - 2026-06-07
- Move ecosystem deps to dependency-groups, remove optional-dependencies
- test hook: verify auto-index

### Fixed

- Address code quality issues in TerminalGridManager
- agents,audit,docs: Address Group 3 follow-ups (M5, M6, LOW #8, LOW #9)
- agents: Replace literal \\\_ with _ in 13 agent frontmatter lines
- index: Correct git hook command syntax (use positional REPO arg)
- iterm2: Use canonical multi-line AppleScript escaping
- terminal: Catch AppleScriptError in desktop creation fallback
- terminal: Update iterm2 tests to expect AppleScriptError
- test_apple_script_bridge: Use correct function name build_applescript_string
- test_matrix,audit,tests: Address Tier 1 #1-4 + Tier 2 from multi-review
- test_matrix: Add pass to keep empty if-block parseable
- test_matrix: Treat 'from mahavishnu import X' as catch-all bucket
- validator: Accept both `---` and 70-underscore frontmatter delimiters
- validator: Enforce required_scripts policy via new validate_required_scripts

### Documentation

- Add terminal grid implementation plan
- Add unified iTerm2 AppleScript integration design
- Address Tier 1 #5-9 from multi-review (freshness fixes)
- architecture,followups: Capture session review outputs
- decisions: Add technical-debt-roadmap.md for side discoveries
- decisions: Address Group 2 follow-ups (removed-scripts, CLAUDE.md, new README)
- decisions: Mark Group 1 (test_matrix.py) resolved, add Group 4

### Testing

- apple_script: Add conformance tests against canonical spec
- iterm2: Add cross-repo session ID compatibility tests

### Internal

- gitignore: Add backup file patterns to silence checkpoint tool artifacts
- gitignore: Silence Claude Code session handoff reports
- gitignore: Silence pytest-cov parallel-mode data files
- hygiene: Address TD-2, TD-3, TD-4 from technical-debt-roadmap
- Remove all *.backup* files
- Remove nanobot remnant files (HEARTBEAT, SOUL, TOOLS, USER)
- Remove stale \*.backup files
- Remove tracked worktree dir, add session-buddy migration plan

## [0.7.1] - 2026-05-20

### Added

- ingesters: Add TurboQuant embedding compression for OTel cache and content ingestion
- tui: Add probe-on-mount optional tabs for Bodai components
- Wire TurboQuant compression as config-driven default-on

### Changed

- Mahavishnu (quality: 68/100) - 2026-05-17 06:21:40

### Testing

- tui: Add tests for probe-on-mount optional Bodai component screens

## [0.7.0] - 2026-05-17

### Added

- Add AdapterType.HATCHET enum member
- Add HatchetConfig and hatchet_enabled to AdapterConfig
- Add TaskCategory.AGENT_LOOP with classification patterns
- config: Add llama_server tier with qwen3.5; update models.yaml to three-tier chain
- Implement HatchetAdapterImpl with WaitForEvent approval bridge
- llm: Migrate CloudWorker to mcp_common FallbackChain three-tier routing
- Wire HatchetAdapterImpl into \_initialize_adapters()

### Changed

- Mahavishnu (quality: 66/100) - 2026-05-07 08:08:58
- Mahavishnu (quality: 66/100) - 2026-05-07 10:48:06
- Mahavishnu (quality: 66/100) - 2026-05-08 05:18:38
- Mahavishnu (quality: 68/100) - 2026-05-13 23:44:38
- Mahavishnu (quality: 69/100) - 2026-05-16 14:50:46
- Mahavishnu (quality: 80/100) - 2026-05-14 04:21:03

### Fixed

- cloud_worker: Harden FallbackChain integration from review findings
- Resolve 7 pre-existing test failures across 4 modules
- Resolve codespell and check-added-large-files hook failures
- Resolve two pre-existing test failures
- types: Clear all zuban type errors — 9/9 comprehensive hooks pass
- Use asyncio.TimeoutError for py\<3.11 compat; add execute timeout test

### Removed

- Delete .mcp.json

### Documentation

- Add Dhara persistence layer section to ARCHITECTURE.md
- Add LLM routing standardization design spec
- Close master backlog — P9 delivered, Final Gate complete
- Correct stale open/closed status across 7 plan documents
- llm: Add Plan 2 — downstream migration to three-tier FallbackChain
- llm: Update Plan 1 with multi-agent review fixes (rev 2)
- Mark config consolidation plan delivered — all tasks verified in codebase
- Mark P10 HatchetAdapter as delivered 2026-05-08
- Mark P2 PoolManager/RoutingDecisionBuffer deferred items delivered
- Mark Phase 1 and Phase 3 complete in roadmap and plan files
- Mark Session-Buddy channel Phase 2 delivered
- Tick all hatchet adapter plan checkboxes — delivered 2026-05-08
- Update LLM routing spec with multi-agent review findings
- Update PLAN_INDEX and add 2026-05-14 doc-sync + channel-phase2 plan

### Testing

- Add Hatchet smoke tests (gated on HATCHET_CLIENT_TOKEN)
- Complete HatchetConfig defaults assertions

### Build

- Add hatchet-sdk optional dependency

### Internal

- cron: Add jobs.template.json with definitions only
- gitignore: Exclude .lycheecache and cron/jobs.json

## [0.6.4] - 2026-05-03

### Added

- Add canonical status normalization for ecosystem control plane
- Add CLI commands for pattern management and scaffolding
- Add ecosystem status aggregator with concurrent collection and staleness detection
- Add ecosystem status and capabilities CLI commands
- Add file parser wrapping mcp-common CodeGraphAnalyzer
- Add git hook installation and index CLI commands
- Add indexer module with MCP upsert and filesystem fallback
- Add MCP error envelope and ecosystem tool validation tests
- Add PID-based locking for concurrent indexing safety
- Add Pydantic models for code graph indexing
- Add repo path validation against repos.yaml
- Add repo skill generation (--skills) to code indexing design
- Add runpod_pool config stanza and RUNPOD_API_KEY env var note
- Add Scaffolding Engine with template rendering and slot injection
- Add signature redaction for code graph storage
- Add skill/agent MCP stale-reference validator
- agents,skills: Complete Agent & Skill Modernization — rename akasha→akosha, add MCP sections to 6 skills, skip archive in validator
- agents: Add crackerjack compliance standards to python-pro, refactoring-specialist, code-reviewer
- Commit canonical Claude Code configuration into project
- config: Add migration script, drift detection, and inventory CLI commands
- Delegate MCP audit to mcp_common.auth, keep require_mcp_auth and CredentialManager
- deps: Add nanobot dependency for in-process workers
- deps: Add runpod-flash SDK
- Export RunPodPool from pools package
- Integrate MCP stale-reference drift check into config validate
- patterns: Add 15 initial pattern YAML files
- pools: Implement RunPodPool via runpod-flash SDK
- pools: Register RunPodPool in PoolManager factory
- Register index CLI commands in main CLI
- scaffolding: Add dual Jinja2 environment factory
- scaffolding: Add pattern dependency graph with topological sort
- scaffolding: Add Pattern Extractor with manual curation and AI suggestion
- scaffolding: Add Pattern Library with YAML storage and query
- scaffolding: Add pattern validation with Jinja2 syntax checking
- scaffolding: Add Pydantic models for pattern format
- validator: Expand KNOWN_TOOLS with live MCP server tools
- Wire mahavishnu docs audit CLI command; ship Ecosystem Docs Phase 4
- Wire TUI screens to live EcosystemStatusService data

### Changed

- Mahavishnu (quality: 61/100) - 2026-04-21 06:00:10
- Mahavishnu (quality: 63/100) - 2026-04-26 00:24:22
- Mahavishnu (quality: 72/100) - 2026-05-01 04:33:21
- Mahavishnu (quality: 73/100) - 2026-04-26 14:33:47
- Mahavishnu (quality: 73/100) - 2026-04-26 19:39:29
- Mahavishnu (quality: 73/100) - 2026-04-29 02:03:54
- Mahavishnu (quality: 73/100) - 2026-04-29 06:54:45
- Mahavishnu (quality: 73/100) - 2026-04-30 16:25:03
- Mahavishnu (quality: 73/100) - 2026-04-30 23:20:07
- Mahavishnu (quality: 73/100) - 2026-05-01 23:26:54
- Mahavishnu (quality: 73/100) - 2026-05-02 04:12:25

### Fixed

- Add missing pyproject dependencies and validate tests to e2e
- Apply multi-agent review fixes to all three design specs
- Apply multi-agent review fixes to pattern learning spec
- deps,workers: Use nanobot-ai package and ZAI_API_KEY for provider init
- Multi-agent review fixes across all 3 design specs
- pools: Align test deque type, add stub warning log and SDK contract comment
- pools: Replace stub handler with NotImplementedError, cap task_results buffer
- Review and clean up test files from checkpoint commit
- scaffolding: Add path traversal guard, validate exits non-zero on failure
- scaffolding: Only add managed header to comment-compatible files, handle git init failures
- scaffolding: Use prefix matching for subtree detection in extractor
- scaffolding: Wire engine to use jinjava_env factory, escape TOML quotes
- validator: Tighten MCP ref and port regexes, add regression tests
- workers: Use ZAI_API_KEY for nanobot provider init

### Documentation

- Add agent & skill modernization design spec
- Add Bodai inter-service authentication standardization design spec
- Add code knowledge graph integration design spec
- Add config consolidation design spec
- Add pattern learning and scaffolding design spec
- Add Splashstand ACB→Oneiric migration design spec (5th spec)
- Apply Round 3 multi-agent review findings to code indexing design
- auth: Mark all 14 tasks complete, update plan index to shipped
- Integrate external research findings into design specs
- plan-index: Reconcile all plan statuses against verified codebase state
- plans: Add Future Work section to RunPod Flash Pool plan
- plans: Mark Agent & Skill Modernization as shipped in PLAN_INDEX
- plans: Mark Nanobot Worker Phase B as shipped in PLAN_INDEX
- plans: Mark RunPod Flash Pool as shipped in PLAN_INDEX
- plans: Remove Phase A from nanobot plan, scope to Phase B completion only
- proposals: Annotate shipped phases in ecosystem roadmap and builder overlap docs
- Reconcile plan state - mark dashboard partial, deprecate redundant health tools

### Testing

- Add degradation tier and validation tests
- pools: Add failing tests for RunPodPool
- pools: Add RunPodPool integration smoke test (opt-in via RUNPOD_API_KEY)
- pools: Fix async mock patterns and add scale assertion
- scaffolding: Add end-to-end integration test for scaffold CLI
- workers: Add nanobot.agent.loop to sys.modules mock patch
- workers: Add NanobotWorker unit tests for Phase B

### Internal

- Add .worktrees/ to .gitignore
- deps: Remove gpt4all in favour of ollama for local inference
- Ruff lint cleanup across all scaffolding modules

## [0.6.3] - 2026-04-16

### Added

- adapters: Formalize lifecycle contract
- Add session-archaeologist skill for past decision and context recovery
- chaos: Add failure injection scenarios
- config: Add validation cli and checks
- contract: Add ecosystem compatibility tests
- resilience: Centralize retry and circuit policies

### Changed

- 2026-04-07 07:51, 6 change(s)
- 2026-04-07 17:29, 8 change(s)
- 2026-04-07 19:59, 1 change(s)
- 2026-04-08 01:38, 6 change(s)
- 2026-04-08 03:23, 7 change(s)
- 2026-04-08 15:08, 5 change(s)
- 2026-04-09 02:27, 2 change(s)
- adapters: Complete engine adapter decomposition
- Add deprecation warnings to adapter re-export wrappers (phase 2)
- engines: Split adapter public modules
- Execute phases 0-1 of ecosystem consolidation plan
- Mahavishnu (quality: 66/100) - 2026-04-09 02:27:04
- Mahavishnu (quality: 66/100) - 2026-04-13 10:04:11
- Mahavishnu (quality: 66/100) - 2026-04-14 06:23:53
- Mahavishnu (quality: 66/100) - 2026-04-14 13:28:07
- Mahavishnu (quality: 68/100) - 2026-04-05 07:07:36
- Mahavishnu (quality: 68/100) - 2026-04-06 09:57:06
- Mahavishnu (quality: 68/100) - 2026-04-07 03:45:24
- Mahavishnu (quality: 68/100) - 2026-04-07 17:26:42
- Merge monitoring/health modules (phase 3)
- Merge quality evaluator into scorer, assess Phase 4 targets (phase 4)
- Retire adapter wrappers, migrate consumers to \*\_impl (phase 5)
- tui-design: revise spec with 6-expert review findings
- tui: Add skills system and subagents sections, fix numbering

### Documentation

- Add Bodai Radar design spec
- Add Bodai Radar implementation plan
- Add design spec for Akosha Code Archaeologist and Quality Pulse skills
- Add implementation plan for Akosha Code Archaeologist and Quality Pulse skills
- Add Session Archaeologist implementation plan
- Add Session Archaeologist skill design spec
- ci: Scrub github actions references

### Internal

- Add sessions/ to .gitignore to prevent secret leaks
- Bump version to 0.4.0
- Bump version to 0.4.1
- Bump version to 0.4.2
- Bump version to 0.5.0
- Bump version to 0.5.1
- Bump version to 0.5.2
- Bump version to 0.6.0
- Bump version to 0.6.1
- ci: Remove ecosystem contract github workflow
- ci: Remove github actions workflows
- repo: Ignore coverage artifacts
- repo: Ignore oneiric cache

## [0.6.1] - 2026-04-15

### Added

- Add session-archaeologist skill for past decision and context recovery

### Changed

- Mahavishnu (quality: 66/100) - 2026-04-14 06:23:53
- Mahavishnu (quality: 66/100) - 2026-04-14 13:28:07

### Documentation

- Add Bodai Radar design spec
- Add Bodai Radar implementation plan
- Add design spec for Akosha Code Archaeologist and Quality Pulse skills
- Add implementation plan for Akosha Code Archaeologist and Quality Pulse skills
- Add Session Archaeologist implementation plan
- Add Session Archaeologist skill design spec

## [0.6.0] - 2026-04-14

### Changed

- Retire adapter wrappers, migrate consumers to \*\_impl (phase 5)

## [0.5.1] - 2026-04-14

### Internal

- Add sessions/ to .gitignore to prevent secret leaks

## [0.5.0] - 2026-04-13

### Changed

- 2026-04-07 07:51, 6 change(s)
- 2026-04-07 17:29, 8 change(s)
- 2026-04-07 19:59, 1 change(s)
- 2026-04-08 01:38, 6 change(s)
- 2026-04-08 03:23, 7 change(s)
- 2026-04-08 15:08, 5 change(s)
- 2026-04-09 02:27, 2 change(s)
- Add deprecation warnings to adapter re-export wrappers (phase 2)
- Execute phases 0-1 of ecosystem consolidation plan
- Mahavishnu (quality: 66/100) - 2026-04-09 02:27:04
- Mahavishnu (quality: 66/100) - 2026-04-13 10:04:11
- Mahavishnu (quality: 68/100) - 2026-04-05 07:07:36
- Mahavishnu (quality: 68/100) - 2026-04-06 09:57:06
- Mahavishnu (quality: 68/100) - 2026-04-07 03:45:24
- Mahavishnu (quality: 68/100) - 2026-04-07 17:26:42
- Merge monitoring/health modules (phase 3)
- Merge quality evaluator into scorer, assess Phase 4 targets (phase 4)
- tui-design: revise spec with 6-expert review findings
- tui: Add skills system and subagents sections, fix numbering

## [0.4.2] - 2026-04-04

### Changed

- adapters: Complete engine adapter decomposition
- engines: Split adapter public modules

### Documentation

- ci: Scrub github actions references

### Internal

- ci: Remove ecosystem contract github workflow
- ci: Remove github actions workflows

## [0.4.1] - 2026-04-04

### Added

- chaos: Add failure injection scenarios
- contract: Add ecosystem compatibility tests
- resilience: Centralize retry and circuit policies

### Internal

- repo: Ignore coverage artifacts
- repo: Ignore oneiric cache

## [0.4.0] - 2026-04-04

### Added

- adapters: Formalize lifecycle contract
- Add shared health command and schema spec
- config: Add validation cli and checks
- Implement health check system for dependency management
- mcp: Add utility tools and tests

### Changed

- Mahavishnu (quality: 76/100) - 2026-03-26 22:51:58
- Mahavishnu (quality: 77/100) - 2026-02-27 12:12:27
- Mahavishnu (quality: 77/100) - 2026-02-27 16:47:28
- Mahavishnu (quality: 77/100) - 2026-03-24 23:42:08
- monitoring: Consolidate alerting and dashboard config

### Documentation

- Add health check system design
- cleanup: Remove backup artifacts and simplify monitoring cli
- plan: Add 90-day bodai ecosystem execution board
- plan: Add current execution slice
- plan: Add issue-sized work package backlog
- plan: Add per-initiative execution checklists
- plan: Normalize master checklist semantics

### Internal

- Disable llamaindex adapter (missing dependencies)
- Re-enable llamaindex adapter with dependencies
- Rename Dhruva to Druva and re-enable LlamaIndex

## [0.3.2] - 2026-02-26

### Added

- adapters: Add error codes and interface compliance for adapter implementation
- Add approval manager for version bump and publish gates
- Add comprehensive error recovery guidance (Week 3 Day 3)
- Add comprehensive help system and Phase 1 completion report (Week 6 Day 4-5)
- Add consolidated status enum module (MHV-008 Phase 1)
- Add database, wasm, and application worker types
- Add desktop automation module with PyXA/ATOMac/PyAutoGUI backends
- Add devops, database, and design application worker types
- Add extensible worker type registry with 13 worker types
- Add fix orchestrator with quality gates
- Add iTerm2 new window support for terminal sessions
- Add LLM model configuration with global registry reference
- Add Ollama worker with intelligent model routing
- Add Pydantic-AI adapter for agentic AI workflows
- Add self-improvement MCP tools
- Add terminal-turso and application-grafana worker types
- Add token bucket rate limiting for WebSocket connections
- Complete orchestration capability with LlamaIndex re-enabled
- Complete Phase 0 - security & SRE fundamentals
- Complete Phase 1 implementation for all three adapters
- Complete Vector Database & RAG Performance Enhancement Plan
- engines: Add native GoalDrivenTeamFactory (replaces Hive integration)
- goal-teams: Complete Phase 1 - MCP tools, CLI, and tests
- goal-teams: Complete Phase 2 - metrics, websocket, feature flags
- goal-teams: Complete Phase 3 - learning system + runbook
- Implement blocker detection module (Phase 2 Week 1 Day 5)
- Implement pattern detection engine (Phase 2 Week 1 Day 1-2)
- Implement Phase 1 core task management (Week 3-6)
- Initialize ecosystem.yaml with review findings
- phase-2: Implement Agno teams and Prefect deployment management
- phase-2: Implement dependency graph module (Week 3 Day 1-3)
- phase-2: Implement dependency manager with auto block/unblock (Week 3 Day 5)
- phase-2: Implement dependency visualization module (Week 3 Day 4)
- phase-2: Implement optimal task ordering module (Week 2 Day 4-5)
- phase-2: Implement predictive insights module (Week 2 Day 1-3)
- phase-3: Implement Agno tools and Prefect schedule management
- phase-3: Implement Cross-Repository Dependencies (Week 2)
- phase-3: Implement multi-repository task views (Week 1)
- phase-3: Implement Week 3 external integrations (63 tests)
- phase-4: Implement Quality Gate Integration (53 tests)
- phase-5: Implement User Interfaces (101 tests)
- phase-6: Implement Native GUI infrastructure (99 tests)
- phase-7: Implement Performance & Scalability (105 tests)
- phase-8: Implement Deployment & Documentation infrastructure (144 tests)
- phase1: Add CLI accessibility testing
- phase1: Implement migration framework and event sourcing
- phase1: Implement NLP parser for task orchestration
- phase1: Implement PostgreSQL database module
- phase1: Implement TaskStore with CRUD operations
- Register self-improvement MCP tools

### Changed

- Consolidate Prefect adapters to engines module
- Mahavishnu (quality: 75/100) - 2026-02-20 02:33:05
- Mahavishnu (quality: 75/100) - 2026-02-21 09:55:37
- Mahavishnu (quality: 75/100) - 2026-02-21 13:16:55
- Mahavishnu (quality: 75/100) - 2026-02-21 18:11:15
- Mahavishnu (quality: 75/100) - 2026-02-22 15:50:28
- Mahavishnu (quality: 75/100) - 2026-02-22 16:35:35
- Mahavishnu (quality: 75/100) - 2026-02-22 18:02:51
- Mahavishnu (quality: 75/100) - 2026-02-22 18:52:49
- Mahavishnu (quality: 77/100) - 2026-02-22 23:41:13
- Mahavishnu (quality: 77/100) - 2026-02-23 04:38:29
- Mahavishnu (quality: 77/100) - 2026-02-24 18:24:35
- Mahavishnu (quality: 77/100) - 2026-02-25 22:56:24
- Migrate core and infrastructure modules to consolidated status enums (MHV-008 Phase 2)
- Migrate remaining modules to consolidated status enums (MHV-008 Phase 2c)
- phase-7-8: Apply ruff linting fixes
- Update config, core, docs, tests
- Update core functionality

### Fixed

- Address critical issues from review trios
- phase-2: Fix test assertions in task ordering tests
- Resolve MHV-007 datetime.utcnow() deprecation
- Resolve OpenSearch initialization issues
- Resolve orchestration chain issues and install adapter dependencies
- Resolve P0 issues (MHV-001, MHV-002, MHV-003)
- Resolve P1 issues (MHV-004, MHV-005, MHV-006)
- Resolve pool_spawn failure when terminal_manager is None
- terminal: Rewrite iTerm2 adapter to use AppleScript via subprocess
- Use RUNNING instead of IN_PROGRESS for MigrationStatus

### Documentation

- Add ADR 009 (Hybrid Registry) and ADR 010 (Security Spec)
- Add self-improvement implementation plan
- Add self-improvement system design
- Mark MHV-008 as fixed (status enum consolidation complete)
- Update Python version requirement to 3.13+

### CI/CD

- Disable automatic workflow triggers

### Internal

- Add archive/backup directories to gitignore
- Update ecosystem.yaml with issue fix status
- Update LICENSE copyright to 2026

## [0.3.1] - 2026-02-17

### Added

- Implement XDG Base Directory compliance

### Changed

- Update core functionality

## [0.2.0] - 2026-02-10

### Added

- **BREAKING:** Migrate to ecosystem.yaml and rehabilitate test suite
- Complete Phase 0 P0 blockers - All 9 blockers resolved (100%)

### Changed

- Test suite fixes - All collection errors resolved
- Update config, core, deps, docs, tests

### Documentation

- Add session optimization workflow improvements

### Testing

- Fix MCP server and ITerm2 adapter tests - 100% pass rate

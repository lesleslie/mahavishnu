# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
- Remove stale *.backup files
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

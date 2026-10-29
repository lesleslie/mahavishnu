# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.37.0] - 2026-10-28

### Added

- Add Shepherd workspace precondition to MahavishnuPool demos
- alerting: Rules for the heartbeat watcher's three P0 conditions
- bifrost: Port the launchd lifecycle into the Typer sub-app
- bifrost: Retire the standalone scripts, complete CLI consolidation
- Consolidate Bifrost tooling into a wired Typer sub-app
- cutover: Bifrost ↔ Claude Code & Qwen CLI URL toggle surface
- demo,docs: 2 PiPool workflow demos + workflow cookbook
- Expand /jot slash command to 10 subcommands
- mahavishnu/cli: Wire hatchet demo (stub → live)
- mahavishnu/cli: Wire pydantic_ai demo (stub → live) + fix RunUsage extraction
- mahavishnu: Agno + CloudWorker + probe + terminal — oneiric Bifrost router (plan 6, phases 2 + 3)
- mahavishnu: Delete BifrostConfig class + llm_gateway package (plan 6, phase 7)
- mahavishnu: Phase 8 — bifrost plan end-to-end verification (audit + routing doc + plan index)
- mahavishnu: PiPool demo operator setup — extend env_allowlist + precondition check
- mahavishnu: PiPool per-task CLI surface (rewrite for @earendil-works/pi-coding-agent v1.3.0)
- mahavishnu: RunPodPublicEndpointPool — REST substrate for Public Endpoints
- pools: Migrate RunPodPool from runpod-flash to runpod SDK 2.0
- Publish root-relative paths in BODAI_REPO_REGISTRY.md
- scripts: Resolve fleet repos against a projects root
- scripts: Verify_plan_blocks — extract-and-execute gate for plan code
- Wire 3 cross-substrate workflow demos into mahavishnu demo CLI
- Wire 4 pool demos into mahavishnu demo CLI
- Wire workers execute to real dispatch; serialise staged commands
- workers: Gate dispatch to host-privileged agent types
- workers: Make ShellWorker.execute actually execute
- workers: Pass the prompt as data; make the permission mode configurable

### Changed

- core: Delete tombstone fields from IntegrationConfig
- observability: Default OTLP metric export off
- scripts: Ruff format normalization in audit_bifrost_callers.py
- Session-start working tree captured
- terminal: Remove goose adapter (Block never shipped matching server)

### Fixed

- audit: Drop dead-plan declarations + stale # req: markers
- Authenticate capability probes against Bifrost correctly
- bifrost-gateway: Bump READY_TIMEOUT_SECONDS to 180s
- bifrost: Attribute verify-gate evidence to the Qwen route's endpoint
- bifrost: Correct the gate's dispatch command and precondition check
- bifrost: Make the config-store backup private and consistent
- bifrost: Make the URL-rewrite gate honor shell-local assignments
- bifrost: Match Qwen endpoints exactly, not by substring
- bifrost: One helper for the gateway's OpenAI-compatible root
- bifrost: Provision provider keys from secrets.env, not by accident
- bifrost: Read verify-gate evidence from the log store, not stdout
- bifrost: Source the dashboard setup token from secrets.env
- bifrost: Stop rebootstrap and the test suite destroying config.db
- cli,workers: Refresh spawn allowlist + enrich validate_required_tool error
- cli: Wire `mahavishnu status` and `mahavishnu pool reap` subcommands
- config: Let MAHAVISHNU_* env vars beat the YAML in the app loader
- crow: Switch adapter to one-shot terminal tool + wire live demo
- demo: Dispatch a command, not a prompt, to MahavishnuPool
- demo: Harden Shepherd workspace precondition against path-traversal gate-parity
- deps: Uv 0.13.3 -> 0.13.5 (PYSEC-2026-4321)
- Drop a stranded virtual key when the URL is not Bifrost-managed
- events: Write the activity path through a uniquely named temp file
- examples: Repair demo sweep for vish cli + Bifrost routing
- Keep the YAML registry in step with the code registry
- llamaindex: Make the OpenSearch index creatable and writable
- llamaindex: Size embedding batches to the server's real limits
- logging: Restore the process log level after third-party downgrades
- mahavishnu: Pydantic forward-ref init + demo_cli pool race
- mcp: Use oneiric's logger in the server lifecycle
- monitoring: The scrape targets and the inventory described a fleet that
- observability: A top-level metrics toggle, and working mock fallbacks
- observability: Actually start the change-point tick loop
- observability: Decouple metric export from trace export
- observability: Make the change-point detector's liveness observable
- observability: Send OTLP metrics to a receiver that implements MetricsService
- observability: Stamp service.namespace on mahavishnu's Resource
- plans: Bind span columns with row[col], complete the insert fixture
- plans: Canary emits a real OTLP request; bridge tests use public API
- plans: Declare all 15 receiver metrics; repair the sweep advisory lock
- plans: Embedding_dim in fixtures, span-counted metric, per-task gate
- plans: Heartbeat `worst` verdict, validator sustained rate, get_config
- plans: OTLP fixture, ON CONFLICT arbiter, co-author trailers
- plans: Rewrite OTel v7 akosha tasks against verified source
- plans: Runtime defects found by execution — proto, insert binding, ports
- plans: Sanitize span attributes via oneiric's data.sanitize kit
- plans: Specify _iter_spans/_dlq_insert, build the heartbeat loop, Event.wait
- plans: Task 11 path arithmetic points one level too deep
- plans: Task 6 CLI, dangling symbols, cross-references, false claims
- pools: Use req.output() as terminal oracle in RunPodPool
- prefect-demo,deps: Use GitRepository storage + trace CWD mismatch
- Route Qwen through Bifrost by provider, and discriminate by agent
- ruff: Phase 0 baseline + Phase 1 BLE001 for post-regrowth cleanup
- scaffolding: Write patterns through a uniquely named temp file
- scripts: Point the MCP helpers at the renamed session-buddy
- security: Close fail-open verification gate in both smoke scripts
- serverless-phase1: Phase 1 REQ-CLEAN-001..007 (wire-up gap closure)
- Ship nested-extra Oneiric fields through to MahavishnuSettings
- spec: Re-baseline OTel DDL on DuckDB 2.0.0-dev, not 1.5.6
- specs+regenerator: Wire event-sourced-otel spec + fix shebang
- specs: Read-path review findings; DuckDB version split reaches v7
- terminal: Shape B (shell-chain with word-boundary) for validate_command_safety
- tests: Complete phantom-import migration from db06fc87
- tests: Delete dead AdapterDiscovery* test classes
- The health aggregator's metrics must reach the live /metrics
- workers: A private stderr file per worker invocation
- workers: Apply the gateway's /v1 suffix idempotently
- workers: Derive the host-agent gate from the registry, not a hand list
- workers: Drop the unrestricted permission modes from the allowlists
- workers: Give the worker manager its settings
- workers: Keep the CLI's stderr out of the pane
- workers: Make the agent prompt actually reach the model
- workers: Make the shell-command task registerable with Shepherd
- workers: Map Shepherd's real run-status vocabulary onto WorkerResult
- workers: The sentinel must mean the model replied, not that we echoed

### Documentation

- Add ADR 019 — Dhara decommissioning from Bodai core fleet
- architecture: Correct eight tool counts in the registration-group table
- architecture: Correct the adapter CLI claim
- Archive 10 completed plans + decision file establishing archive policy (2026-10-18)
- Correct profile counts and enumerations in MEMORY_ARCHITECTURE
- decision: Record R-6 as implemented, with its two behaviour changes
- decision: Record six spec corrections found building PR-A3
- decision: Resolve read-path Q1 — declared ∪ observed pair inventory
- decisions: Prefect 3.x process-pool worker can't import in-memory flow
- deps: Record why the oneiric floor cannot move to 0.33.2
- Drop stale adapter-registry references from MEMORY_ARCHITECTURE
- Flip 4 partial plans to complete (2026-10-17 audit)
- followups: Close terminal-fixes-batch Section 3 (status -> complete)
- followups: Flip spawn-cli-stale-worker-allowlist to complete (orphan merged via 7b66eb1b)
- followups: Mark validator-move consumer followup complete (2026-10-18)
- followups: Reclassify ai-dep-group-transitive-bloat to shipped
- followups: Reclassify convergence-control-plane-v1-sop-deferrals to shipped
- Mark 4 Tier 2 followups as deferred per trigger-spec; fix runpod migration frontmatter
- otel: An operator runbook for the heartbeat watcher's three alerts
- otel: Pin PR-A4's canary to what actually ships
- otel: Point the runbooks at what actually exists
- otel: Reconcile the v7 plan and spec on PR-A8's rollback mechanism
- otel: The sweep trigger is an MCP tool, and here is why it cannot be a CLI
- otel: What "reporting" means, and who actually reports it
- plan: The heartbeat roster has no producers behind it
- plan: The OTLP MetricsService belongs in the substrate, not in Alloy
- plan: The substrate has two metric exporters, not one
- plans: 3rd rewrite of bifrost-oneiric-gateway-adapter after final review
- plans: Activate eval-adapter Phase 1 (model evaluation foundation)
- plans: Activate mcp-common test backfill plan (Phase 1b)
- plans: Activate native macOS automation backend refactor
- plans: Add 2026-10-17-bifrost-oneiric-gateway-adapter (draft)
- plans: Add Phase 0/Phase 1 status update to ruff-cleanup-post-regrowth
- plans: Add Phase 1 status update to serverless-readiness-and-substitution
- plans: Add tier 1.5 — Bodai core fastmcp 4.x pin floors (akosha, session-buddy, crackerjack)
- plans: Archive 3 stale drafts per triage walkthrough
- plans: Archive drop-ollama-favor-llama-server (plan 5) — all B-list deliverables landed across 6 repos
- plans: Archive mcp-server-fleet (23 fastmcp pin migrations landed); reclassify oneiric-substrate (3 Bodai stragglers migrated, rest still open) (2026-10-18)
- plans: Archive oneiric-substrate umbrella — all deliverables landed (3 CLI hooks + SessionBuddySettings migration) (2026-10-18)
- plans: Archive session-buddy wrapper-cleanup (plan 4) and autocheckpoint-loop-move (plan 4b) — all deliverables landed
- plans: Archive stale shared-foundation-adoption-matrix (5-month draft; absorbed by 2026-10-15 umbrellas)
- plans: Cross-plan compatibility fixes + frontmatter conformance
- plans: Date-prefix native-macos-automation plan filename; sync PLAN_INDEX + orphan-sweep (2026-10-18)
- plans: Delete trace_ingester_poller instead of flipping it (Task 13)
- plans: Exclude worktree-snapshots from PLAN_INDEX discovery
- plans: Extend Task 5 with Phase 3 per-sibling fork-deletion sub-steps
- plans: Flip CommonMCPClient transport unification to complete (Phase 3 verified)
- plans: Mark bifrost plan complete (Phase 8 status flip)
- plans: Master plan index + centralized regenerator implementation plan
- plans: OTel substrate read-path implementation plan (draft)
- plans: OTel substrate v7 implementation plan — 14 tasks, PR-0a → PR-A8
- plans: Promote 2026-10-17-bifrost-oneiric-gateway-adapter from draft to active
- plans: Regen PLAN_INDEX.md after pruning pass
- plans: Regenerate PLAN_INDEX (partial count 3 -> 0; added 1 superseded)
- plans: Regenerate PLAN_INDEX (partial count 5 -> 3)
- plans: Regenerate PLAN_INDEX (terminal-fixes-batch -> complete)
- plans: Regenerate PLAN_INDEX (validator-move followup -> complete)
- plans: Revision — Task 0 pin floors + crackjack fixes + T5-T12 carve-out
- plans: Rewrite 2026-10-17-bifrost-oneiric-gateway-adapter after 5-agent review
- plans: Supersede serverless-readiness-and-component-substitution
- plans: V3 drift pass — M2.7-highspeed → M3 swap + 15d line-number refresh (2026-10-18)
- Pruning pass on two partial specs — add superseded_by chains
- Ratify ADR 018 — Option C (hybrid gateway) adopted
- Reclassify 3 stale plans — serverless-readiness (vocab fix to complete, superseded), native-macos (stale-active → shipped), phase-6 observability (stale-draft with met precondition → complete) (2026-10-18)
- registry: Publish the migration tracker's paths relative to the projects root
- runbook: The plist comment trap is fixed, not just documented
- settings: Update local.yaml.example to crow port 8693
- spec: Amend v7 for the six corrections PR-A3 found
- spec: Correct v7 13.1 to name Grafana Alloy as the OTLP port owner
- spec: Fix six factual errors in the 13.1 Alloy correction
- specs: Add frontmatter to bodai OTel substrate v3
- specs: Bifrost ↔ Claude Code ANTHROPIC_BASE_URL cutover
- specs: Bodai OTel substrate v3
- specs: Bodai OTel substrate v4 (closes 7 P0 + 3 P1 from v3 review)
- specs: Bodai OTel substrate v5 (closes 4 P0 + 4 P1 from v4 review)
- specs: Bodai OTel substrate v6 (closes 7 P0 from v5 review)
- specs: Bodai OTel substrate v7 (closes 3 P1 + 4 P2 + 1 P3 from v6 akosha review)
- specs: Flip dhara-mcp-decomposition-design to complete (ADR 019 retired strategic goal)
- specs: Flip shared-bodai-substrate-design to complete (active plans own remainder)
- specs: Flip two stale partial statuses to complete
- specs: Master plan index + centralized regenerator (round 2)
- specs: Master plan index + centralized regenerator design
- specs: OTel substrate read path — query surface, MCP tools, rewiring
- specs: Record observability-incident-lead review on v3 (2 P0, 3 P1, 1 P2)
- Supersede bifrost-gateway-wiring by oneiric adapter plan; refresh 2 umbrellas per child status updates (2026-10-18)
- terminal: Mark Shape B trade-off with REVIEW: blocks for security gate
- The observability block is usable again
- Triage 4 stale-active plans — 3 superseded by 2026-10-15 umbrellas, 1 partial

### Testing

- Align fixtures with real production shapes after Oneiric migration
- Align test_main_cli with the post-migration CLI surface
- config: Drop stale health/auth assertions; document upstream limit
- config: Fix Bifrost env-var + mount tests; drop tautology
- config_sections: Track 2026-09-27 audit deletions + enum-keyed dict
- mcp-common: Restore the evicted modules after the source-tree re-import
- mcp: Pin profile registrations and guard the adapter-registry removal
- observability: The metric-export default is off, so say so
- Pin IntegrationConfig tombstone-flag cleanup state
- Track AgnoToolsConfig mcp_transport default flip

### Build

- deps: Pin oneiric>=0.33.2 and drop the gpu group
- deps: Raise the mcp-common floor to 0.33.0
- deps: Raise the mcp-common floor to 0.33.1 for the ownership API

### Internal

- Add reference plan + canonical CC URL cutover smoke
- Auto-format follow-up from session-close hooks
- Commit 3 pre-existing dirty files (formatter + new /jot vitals)
- deps: Bump crackerjack pin to >=0.89.2
- ollama: Mahavishnu slice — B-list + doc sweep + follow-ups (plan 5)
- ollama: PR #0 — config comments + dict literal + docs
- perms: Allow Read on top-level and docs/archive paths
- settings: Remove write_mode: dual from persistence block
- substrate: Flip HotStore import to oneiric.adapters.vector.hot_store

## [0.36.0] - 2026-10-16

### Added

- cli: Status + reap subcommands, POOL_REFERENCE, spawn allowlist followup
- mahavishnu/hooks: Mirror session-buddy and oneiric agents
- mahavishnu/terminal: Default TerminalSettings.enabled to true
- mahavishnu/workers: Restore SHELL dispatch path + reword error
- mahavishnu: Bifrost gateway wiring — Phases A/B/D/E/F/G + 5 follow-ups
- mahavishnu: Implement live demo llamaindex (replace stub)
- settings: Track bifrost.route_qwen_code: true in mahavishnu.yaml

### Changed

- Add drop-ollama-favor-llama-server (draft)
- Apply 3-lens review corrections to v1.5 spec + v1.2 plan (Phase G)
- Bifrost: Implementation plan off spec v1.3
- Bifrost: V1.4 - 3-correction post-plan-review amendment (2026-10-16)
- Canonical .claude/ policy + coverage/complexipy tooling
- Correct drop-ollama plan after multi-subagent review
- Final-pass corrections (spec v1.4 polish + plan v1.1 re-applied + active)
- mahavishnu: Use mcp_common agents_tools factory
- PLAN_INDEX: Register bifrost-gateway-wiring plan (status: active)
- Promote drop-ollama-favor-llama-server to active
- Re-apply v1.4/v1.1 corrections + add v1.5/v1.2 (Phase G: local llama-server provider)
- Un-track per-repo .claude/ files
- Un-track per-repo .claude/ files + add missing patterns

### Fixed

- agno-demo: Four wire-up fixes for the A→B→D demo path
- Anchor Oneiric loader at repo root + per-subconfig key filter
- core: Refactor @lru_cache instance methods to manual dict caches (B019)
- docs: Followup status 'open' -> 'active' (vocabulary compliance)
- docs: Remap 3 near-duplicate topic slugs to seed vocabulary
- hooks: YAML injection + SSRF guards in bodai-agent-mirror
- lint: Apply ruff auto-fix to mechanical style errors (Category 2)
- lint: Apply ruff auto-fix to source files deferred from Category 2
- lint: Close 13 BLE001 errors in CLI files via documented-contract noqas (Category 1)
- lint: Close 19 F821 undefined-name errors across 9 files (Category 1)
- lint: Close 8 BLE001/S110 errors via documented-contract noqas (Category 1)
- lint: Close comprehensive-hook failures across ty, semgrep, lychee
- lint: Re-apply BLE001/TRY004 noqas with RUF100 self-pin
- lint: Restore `as exc:` binding and move Callable under TYPE_CHECKING
- lint: Sort imports under TYPE_CHECKING blocks (I001 followup)
- lint: Suppress TRY004 on validator's documented ValueError contract
- lint: Use full semgrep check_id in # nosemgrep: suppressions
- mahavishnu/cli: Do FastMCP handshake in pool_spawn dispatch
- mahavishnu/docs: Point topic-vocabulary references at oneiric package source
- mahavishnu/llamaindex: Auto-discover llama-server model + /v1 base_url
- mahavishnu/mcp: Init_terminal_manager accesses server.config.terminal
- mahavishnu/workers/contract: Import WorkerLifecycleState at runtime
- mahavishnu/workers: ShellWorker implements status + get_progress
- mahavishnu: Bump cycles_total on init so /health reports HEALTHY
- mahavishnu: Drop ollama in favor of llama_server for local LLM/embeddings
- merge-to-main: Capture and restore main_checkout dirty tree around squash-merge
- Restore docs/schemas/topic-vocabulary-v1.md from oneiric canonical
- scripts: Verify_qwen_bifrost_gate.sh — 'pool health' has no --output flag
- shepherd: Unblock pool_bootstrap with a robust default writable_root
- tests: Migrate dead Dhara symbol references to MCP (Category 1)
- tests: Rename FakeDharaState back to FakeMCPState
- worktree: Make SessionBuddy provider health check verify tool registration

### Documentation

- decisions: Clarify docs/.archive is gitignored (cj publish gate)
- decisions: Mark 5 of 6 repos landed in archive-dir-canonical table (oneiric/akosha/session-buddy/mcp-common/crackerjack)
- plans: Drop broken `[text](file.md)` template refs in ble001 draft
- plans: Ship and archive 2026-10-15-archive-dir-canonical (5/6 repos landed, mahavishnu deferred to operator)

### Testing

- mahavishnu: Promote Qwen gate xfail to real pass

### Internal

- Adopt parallel agent's FastMCP wire-protocol fixes
- agents: Rebuild 27 truncated descriptions, fix 14 double-comma artifacts
- agents: Trim fabricated specifics in 13 descriptions
- Bare-routing descriptions on 16 stub agents
- gitignore: Untrack docs/plans/.archive + strengthen .archive pattern
- mahavishnu: Drop redundant topic-vocabulary-v1.md
- Regenerate PLAN_INDEX.md via plan_index_sync (git-aware)

## [0.35.1] - 2026-10-15

### Added

- conductor: Per-engine emit_node dispatch tables + level-by-level DAG dispatch (Plan 3)
- governance: Pre-push consolidation gate (REQ-015)
- hooks: Add bodai-activity-subscriber for SessionStart/End (Bundle B — plan 2026-07-11-phase-6-bodai-observability)
- hooks: Wire bodai-activity-subscriber into SessionStart/End (Bundle B — plan 2026-07-11-phase-6-bodai-observability)
- mahavishnu: Pool_tools budget_enforce extract (Stage 3b unblocker)
- Merge tier1-validator-fix-2026-10-14 to main
- merge: Add --no-crackerjack operator bypass + accept fast-cycles decision
- monitoring: Add `monitor tui` subcommand per plan B-1.3

### Changed

- Bifrost: V1.1 - extend AI-CLI opt-in to terminal-qwen
- Bifrost: V1.2 - post-4-lens-review amendment set
- Bifrost: V1.3 - final-pass amendment (post mahavishnu-specialist + general-purpose review)
- BLE001 noqa sweep + spell check + broken link/tc-refs fixes
- Feat/wire-learning-pipeline -> origin/main
- Fix/merge-fast-hooks -> main
- Fix/squash-merge-local-main -> main
- V1 design - first-class BifrostConfig wiring

### Fixed

- Close two cleanup gaps surfaced by stale-worktree scan
- docs/codesync: Bundle C — serverless phase-1-fixes REQs + native-macos cleanup
- docs: Redirect broken markdown links to current file locations
- docs: Remove orphaned UPPERCASE schema files
- docs: Rename schema files back to canonical lowercase
- docs: Repair superseded_by refs and followup topic after archive sweep
- docs: Resolve 7 stale conflict markers in fast-hooks-vs-comprehensive decision
- docs: Restore decision-adapter-category plan/spec, drop duplicate .claude/decisions/ file
- fast-hooks: Clear ruff-check + check-local-links gates
- followups: Add trailing newline to consumer-followup doc
- gitignore: Drop per-path .archive exceptions — blanket ignore is the new policy
- hooks: Make Path available at runtime for typer annotation eval
- hooks: Narrow bodai-activity-subscriber observability surface
- lint: Re-apply per-site # noqa: BLE001 to regression sites
- lint: Remaining small ruff categories (TRY004, TRY203, N811, N817, PLC3002, SIM116, TRY401)
- lint: Ruff auto-fix + suppress intentional F401 imports
- lint: Small-category ruff cleanups + per-file overrides for protocol contracts
- merge-to-main: Gate recognizes squash-merge via commit subject
- merge-to-main: Sibling discovery uses parent dir, not cwd basename
- runbook-refs: Case-match runbook paths to actual lowercase files in main
- tests: Remove obsolete dhara_client references
- worktree-provider: Use fastmcp.Client instead of non-existent mcp_client

### Documentation

- agents: Add Decisions pointer section
- Baseline refresh (Plans 4+5+6) + critical fixes (Plan 9)
- Cluster 1+2 consolidation — create 2 umbrella plans, supersede 6 children
- Consolidate topic clusters and archive legacy plans
- Create unified-event-bus-wrapper decision doc, supersede spec
- decision-adapter-category: Spec, plan, decision for Oneiric decision/ category
- decision-adapter: 4-pass multi-agent review complete — plan status: active
- decisions: Add bypass-gate-parallel-sessions rule + index entry
- decisions: Backfill README index with 2 missing 2026-10-14 entries
- ecosystem: Generate MCP_TOOL_PROFILES.md via scripts/generate_tool_profiles_doc.py
- Fix 12 broken local links in active files
- Fix 9 broken local links in archive files
- followup: Dhara runtime scrub + WORKFLOW_DIAGRAMS archive annotations
- followups: Consumer followup for shared-frontmatter-validator move
- frontmatter: Resolve 7 validation errors for documentation_cleanup
- Mark Plans 1, 2 complete (dhara-lock-delete + crackerjack c-wire Task 6)
- Mark Plans 5, 7, 9 complete (RUF100 cleanup + tool profile doc + bodai-maintained wirings)
- merge-to-main: Cross-link new governance decision in See also
- Move Plans 3, 6 back to active dir + mark complete
- Move Plans 3, 6 from .archive back to active dir; mark complete
- plans/specs: Apply re-assessment items 1-2-3 (27 files)
- plans: 2026-07-15-constellation-tui — keep draft, refresh last_reviewed
- plans: 2026-08-31-zsh-modernization — keep draft, refresh last_reviewed
- plans: 2026-10-03-eval-adapter-phase1 — keep draft, refresh last_reviewed
- plans: Add Phase 1.5 medium-mcp gate + cmux-mcp rename + new bodai-maintained-mcp-promotion plan
- plans: Add shared-frontmatter-validator move (spec amendment + implementation plan)
- plans: Archive 2026-06-01-dhara-crackerjack-critical-bug-fixes (Bundle D)
- plans: Archive per-engine emit-node-dispatch (shipped)
- plans: Archive pool-tools budget_enforce extract (shipped)
- plans: BLE001 triage and per-site refactor follow-up
- plans: Cluster 4 supersede — 2026-07-29 ruff-cleanup-waves → 2026-10-12 ruff-cleanup-post-regrowth
- plans: Cluster 5 cross-reference — ledger as canonical, matrix as companion
- plans: Flip 22 plan/spec/ADR frontmatter statuses to reflect verified completion (audit 2026-10-15)
- plans: Mark lifespan-publisher superseded by session-buddy-wrapper-cleanup
- plans: Mark ruff-cleanup-post-regrowth partial (Phase 0 landed; 8 fix phases pending)
- plans: Resolve Cluster 3 conflict — lifespan-publisher vs task-system-v1.1
- pre-1.0: Archive Pass 3 — sweeps dated plans, followups, decisions
- pre-1.0: Archive Pass 3 — sweeps dated plans, followups, decisions
- pre-1.0: Consolidate OTel/OTLP docs into integrations/observability/
- pre-1.0: Fix code-level refs to renamed docs (Pass 4d)
- pre-1.0: Pre-merge link-ref fixes for crackerjack gate (in-progress)
- Regenerate PLAN_INDEX.md (status: complete across 7 plans + Plan 4 partial)
- specs: 2026-08-31-zsh-modernization-design — keep draft, refresh last_reviewed
- specs: Archive 2026-06-22-three-layer-self-heal-design.md per user direction
- specs: Archive 2026-08-12-bodai-ecosystem-consistency-design.md per user direction
- validator: Fix topic-vocabulary hardcoded path + add 24 missing slugs
- zsh: Add override note to plan + spec — kept draft per user override

### Internal

- docs: Apply parallel session's 3 decision files (pop stash)
- Drop dead [mypy-mcp_client] block
- gitignore: General sibling-of-parent .archive exception (replaces per-path list)
- gitignore: Un-ignore .claude/decisions/.archive/ and docs/decisions/.archive/
- Remove 6 long-moved docs files (canonical -> .archive/)
- repo: Move .claude/decisions/ to docs/decisions/
- ruff: Enable 9 rule families (post-regrowth Phase 0)
- ruff: RUF100 stale # noqa cleanup (post-regrowth)
- Untrack 649 historical archive files

## [0.35.0] - 2026-10-12

### Added

- adapters: Phase 2 — drop HybridAdapterRegistry, route through Oneiric
- cli: `mahavishnu demo <engine|adapter>` framework — tmux + prefect + 7 stubs
- cli: `mahavishnu launchd prefect` opt-in plist management
- mahavishnu: Phase 2 — wire runtime facts push to Oneiric (Plan 1 v3)
- mahavishnu: Surface canonical 4-field shape on /health body + integration test (Plan 2 Phase E2 Task 5)
- mahavishnu: UUID7-only substrate (Phase 6 of cross-repo migration)
- Phase 1 — re-wire engine adapters to Oneiric substrate

### Changed

- mahavishnu: Adopt OneiricSettings.substrate for pool/retry/telemetry/auth
- UUID7-Only Migration (cross-plan coordination) [migration/2026-10-11-uuid7-only]

### Fixed

- config: Point oneiric settings loader at the repo root
- docs/drafts: Quote multiline unquoted values in akosha-eval-metric-sink frontmatter (REQ-IDX-001)
- docs/drafts: Quote multiline unquoted values in akosha-tool-call-feed-lifecycle frontmatter (REQ-IDX-001)
- docs/drafts: Quote multiline unquoted values in eval-methodology frontmatter (REQ-IDX-001)
- Import Any in demo_cli.py for ty strict mode
- mahavishnu: Thread writable_root to ShepherdBackendWorker
- mcp: Wire terminal_manager into app.terminal_manager (Phase 8 post-mortem)
- mcp: Wire terminal_manager into app.terminal_manager (Phase 8 post-mortem)
- mcp: Wire terminal_manager into pool_manager singleton (Phase 8 post-mortem)
- prefect: Patch three adapter bugs surfaced by live 3.8.8 demo
- scripts/backfill_plan_spec_titles: Replace non-greedy regex with line-anchored splitter
- scripts/regenerate_plan_index: Read full file in \_has_frontmatter (REQ-IDX-003)
- scripts/regenerate_plan_index: Replace non-greedy regex with line-anchored parser (REQ-IDX-002)

### Documentation

- adapters: Phase 3 — doc cleanup after registry consolidation
- Archive worker-readiness + 7 new follow-up plans + TUI decision doc
- plans: Add 2026-10-12 Phase 9 ULID surface elimination plan
- plans: Add T1.5 to Phase 9 (redo Phase 0.5 absorption)
- plans: Mark Phase 3 Task 3.2 done (oneiric ccc5525)
- plans: Mark Phase 9 ULID surface elimination and UUID7 migration as shipped
- plans: Mark Phase E2 Tasks 1/2/3 done (akosha 9c9ab67, sb aeaa680, mahavishnu 676a6d8)
- plans: Mark Plan 2 Phase E2 complete
- plans: Mark Plan 2 Phase E2 shipped (was complete)
- plans: Mark Plan 2 Phase E2 Task 5 complete
- plans: Re-review cycle 2 — close 3 critical structural items + minor cleanups
- plans: Update 2026-10-11 validation matrix to reflect Phase 9 T1
- prefect-demo-launchd: Archive plan + recurring rules

### Testing

- health_integration: Mock MCP client in test_state_change_to_unhealthy
- mahavishnu: Assert auth short-circuit preserved across substrate adoption (Plan 2 Phase E2 Task 4)

### Internal

- docs: Add plan-index-sync-script-hardening plan (2026-10-12)
- docs: Cleanup working tree — UUID7 post-mortem + plan refresh
- docs: Frontmatter sweep — refresh last_reviewed on 12 active plans
- docs: Mark plan-index-sync-script-hardening as shipped (2026-10-12)
- docs: Plan audit cleanup + langgraph CLI default fix
- docs: Refresh 3 active plans + add Phase 1b test backfill (2026-10-12)
- mahavishnu: Final ULID surface cleanup

## [0.34.2] - 2026-10-11

### Documentation

- Add WebSearch to MiniMax-modeled substitution table
- Swap WebSearch default to minimax-coding-plan after Crow SearXNG CAPTCHA failure

### Internal

- Brave MCP --port 8769 (avoid 8080 collision)
- Brave MCP needs --allowed-hosts and --allowed-origins for HTTP transport
- Brave MCP server requires --transport http; stdio is unsupported
- Fix MCP server wiring (tavily was never registered; brave --transport flag caused crash)
- Register tavily and brave-search MCP servers; expand WebSearch to 4-tier fallback
- Remove brave-search MCP server; demote chain to 3-tier
- Remove unused tools/ slash commands
- workflows: Archive all coverage-fanout lifecycle artifacts

## [0.34.1] - 2026-10-11

### Added

- **BREAKING:** mahavishnu: Rename BodaiCLIBase to OneiricCLIBase
- **BREAKING:** terminal: Drop pty_mcp_python backend
- /jot slash command (vitals only per R6)
- 2026-08-10-wave: Mcpretentious removal + webhook-durable/approval-log/workflow-outcome specs
- acp: Add error types + bearer auth gate (sub-commit 2.A)
- acp: Add EventBridge-to-SessionUpdate synthesizer (sub-commit 1.2)
- acp: Add execute_fn factory + fix A2A Bearer comparison (Phase 1.5)
- acp: Add OTel session span + observability validation test (sub-commit 2.C)
- acp: Add Pydantic wire-format protocol models + spec-name drift gate
- acp: Add stdio JSON-RPC 2.0 dispatcher core (sub-commit 2.B)
- acp: Emit tool_call lifecycle envelopes from worker boundaries (sub-commit 1.3)
- acp: Wire MahavishnuApp into dispatcher execute_fn (Phase 1.5 close)
- Add /jot drain slash command (polish item 1)
- Add `mahavishnu acp serve` CLI surface (sub-commit 2.D)
- Add clone-refactor-wireup topic to seed vocabulary
- Add JotSummaryDict/JotVitalsDict surfaces + \_summary_dict/\_vitals_dict
- Add mahavishnu metrics dispatch subcommand
- Add mahavishnu metrics verification subcommand
- Add mahavishnu plugin manifest + namespaced commands (additive)
- Add mcp\_\_mahavishnu\_\_audit_health tool + audit_health CLI (Phase 2)
- Add pre-commit hook to mahavishnu index install-hooks
- Add tiered microVM isolation workers (Apple container + E2B)
- Add ultracode Phase 1/3 settings
- Add WorkerRegistryConfig with Pydantic-validated provides
- Add WorktreePruneCandidate, classify_merge_status, WorktreePruner
- Adopt coverage-ratchet at current coverage
- adr-0016: V2 revision + plan mirror
- adr-0016: V3 revision closes CB-3/4/5
- approval: Decision_writer — validate-on-write at decision boundary
- audit: Cross-module __all__ resolution + tests
- audit: Recognise @pytest.fixture as a registration decorator
- audit: Treat pytest-discoverable tests/ symbols as wired (Phase 5 loop-3)
- auth: Add Principal and CleanupPolicy types
- auth: FastMCP session-context user_id extraction (Task 11.9)
- Auto-generate BODAI_REPO_REGISTRY.md from canonical sources
- changepoint: Add TwoStageDetector (warn/confirm) + config fields
- changepoint: Wire TwoStageDetector into ObservabilityManager; emit drift_warning span
- cleanup: Delete unused record_key + triage remaining audit orphans
- cli: `mahavishnu plan` subcommand (list/show/vitals/search/purge)
- cli: Add --json output for list-sessions and prune-abandoned
- cli: Add mahavishnu worktree scan + tests
- clone-claims: Cluster_state_claim with in-process lock + ConcurrentDAGError
- clone-tools: Wire clone_refactor_group to git-tree DAG
- code-index: Populate CodeGraphNode.source with verbatim line slice
- config: Add capability_enabled / capability_scopes / legacy_tools flags
- config: Add JotSettings nested under MahavishnuSettings
- config: WorktreeStorageSettings + WorktreeCacheSettings blocks (PR-D.0)
- core: Add capability schema with typed I/O contracts
- core: Add Oneiric-driven capability loader (grouped by id)
- core: Conductor with resolve, plan (real edges), emit_node, emit_flow
- core: Dhara-backed envelope transport with secret redaction
- crow: Wire terminal tool (single PTY, no concurrency)
- CrowTerminalAdapter uses session-aware tools
- decisions: Add worktree-cleanup-policy + 4 back-links
- decisions: Add worktree-cleanup-policy decision doc (skeleton)
- decisions: Amend wiring discipline policy with §7 consumer-side aggregation
- docs: Frontmatter v1 schema, validator, topic vocabulary (plan-lifecycle-unification P0)
- docs: PLAN_INDEX regenerator + first regeneration (plan-lifecycle-unification P6)
- Drain pending WAL rows through Session-Buddy sink (MAHAVISHNU_OUTBOX_DRAIN)
- ecosystem: Add publish: block to mdinject, flowscape, splashstand
- engines: Add load_engine_registrations helper
- engines: Declare provides: list[Capability] on all 6 adapters
- env: Scope fastblocks agents + document MCP/secret routing pattern
- errors: 9 new error codes for Phase 3 streaming bundle lifecycle
- errors: Add WorkerUnavailableError and ContainerDaemonUnavailable
- events: Add worker topic constants and helper
- events: Oneiric wire standardization (canonical boundary, decoder, observability)
- frontmatter: Migrate 217 docs to v1 schema
- git-ops: \_git_ops.py with typed GitCommit\* exceptions (REQ-CLONE-013)
- githooks: Wire audit_no_secrets_in_mcp.py as tracked pre-commit hook
- hooks: Add discovery hint for opt-in worktree isolation (Phase 4)
- hooks: Discover current branch, debug mode, credential safety, configurable timeout
- hooks: Flip default-on for internal-team Bodai usage (Phase 8)
- hooks: Wire worktree-session-isolation into SessionStart/SessionEnd
- Instrument scan_worktrees with OTel counter + histogram + INFO log (F-QA-4/5/6)
- jot-cli: Add 6 drain subcommand handlers + smoke tests
- jot-cli: Register 6 drain subcommands with Typer
- jot-drain: Add Task 8 — surfacing scorers + throttle + surface_relevant
- jot-mcp: Add 6 drain tools + remove duplicate JotSummaryDict/JotVitalsDict
- jot: 8 MCP tools with TypedDict returns (R1, R11)
- jot: Add \_auto_retry_after, \_reconcile_if_in_flight, \_background_reconciler_loop
- jot: Add \_is_surface_eligible, \_is_drain_eligible, \_should_exhaust_retry_budget
- jot: Build_states two-pass fold with parking (R3, R7 part 2)
- jot: Capture sub-plan 1 — hook + log + redaction
- jot: CLI handlers — list, show, vitals + write stubs
- jot: Cmd_search lexical substring fallback
- jot: Drain refactor + cli/hook/mcp-tools alignment + errors rename
- jot: Drain.py skeleton with \_append_event + TypedDict validation
- jot: Extend errors.py with drain error hierarchy
- jot: Extend fold with \_derive_dispatch_fields + DispatchState
- jot: Extend Op literal with 6 drain event types
- jot: FoldResult + parse_events (TD-B3, R7 part 1)
- jot: Git enrichment via subprocess (R4)
- jot: Register 8 tools in profiles + CI guards
- jot: Reject unknown ctx keys in \_validate_ctx (polish item 3)
- jot: Render layer (list, show, vitals)
- jot: Resolve_handle with ambiguity error (R8)
- jot: Typer app with 8 subcommands (R2)
- jot: Wire per-op TypedDicts via MCP-tools import
- jot: Write CLI handler tests for done/reopen/edit/add
- JotError hierarchy (TD-B2)
- lifecycle: Add on_mahavishnu_shutdown for graceful worker detaching
- lifecycle: Add startup reconciliation hook for durable workers
- List_approval_history returns validated ApprovalLog structs
- LocalWorktreeProvider streaming create + fetch (Phase 3 / Task C.6)
- lock-sentinel: Replace dhara.lock with local in-process Lock
- mahavishnu: /merge-to-main slash command (REQ-004)
- mahavishnu: 11 Qwen-only event handlers (Phase 12b task 1)
- mahavishnu: \_decode_envelope accepts v1.1 flat-fields XADD shape
- mahavishnu: Add audit_cli_inventory.py for Core 7 CLI surface audit
- mahavishnu: Add bus dependency-group with coredis
- mahavishnu: Add dev_log.write_entry() (REQ-003)
- mahavishnu: Add DEV_LOG_DIR + get_dev_log_path() (REQ-002)
- mahavishnu: Add MemoryOutboxWriter (WAL schema + DuckDB writer)
- mahavishnu: Adopt BodaiCLIBase + real doctor/health (Phase 3 Task 4.6)
- mahavishnu: Aggregate_verdicts() — 3-rule priority (REQ-004)
- mahavishnu: Apply worktree convention (XDG path default)
- mahavishnu: Audit_devlog.py CI gate (REQ-011)
- mahavishnu: Augment 6 Claude hooks with bridge routing (Phase 12a Task 2)
- mahavishnu: Bugfix + first inventory (mcp-common) for CLI audit
- mahavishnu: C-1 config models prep
- mahavishnu: C-10 ecosystem intake (simplified allowlist + sanitize)
- mahavishnu: C-12 executions show CLI
- mahavishnu: C-2 T-0 test scaffolding - 11 wire-up fixtures
- mahavishnu: C-3 event-history + PENDING enum
- mahavishnu: C-4 schema reconciliation
- mahavishnu: C-5 EventBridgePublisher module-global singleton
- mahavishnu: C-6 pool route execute idempotency
- mahavishnu: C-8 worktree isolation
- mahavishnu: C-9 concurrency limits (token-bucket per-category)
- mahavishnu: Canonical hook bridge handler (Phase 12a Task 1)
- mahavishnu: Close Phase 4/5 gaps — Bodai CLI contract + bodai.apps entry-point
- mahavishnu: Complete orphan sweep (settle CLI + CloudWorker re-export)
- mahavishnu: Flip otel_ingester HotStore forward-ref to Oneiric Protocol
- mahavishnu: Flip otel_ingester runtime HotStore to Oneiric DuckdbHotStore
- mahavishnu: Git-hook Typer subcommand (Phase 12a Task 3)
- mahavishnu: Hard-cutover PostToolUse hook JSON-queue → bus XREAD (Phase 12a Task 5 partial)
- mahavishnu: Install-bodai-git-hooks.sh operator script (Phase 12a Task 4)
- mahavishnu: MCP lifespan refactor — move post-listener init out of start_server
- mahavishnu: Merge_to_main scaffold + .review-state.json I/O (REQ-014)
- mahavishnu: Migrate config loader to Oneiric + OTel ingester pgbouncer plumbing
- mahavishnu: Migrate load_config() to oneiric.core.config.load_settings
- mahavishnu: Migrate to mcp-common CommonMCPClient (Phase 3 REQ-004, REQ-009)
- mahavishnu: Mirror wave-11 mermaid CI guard from crackerjack
- mahavishnu: Parse_verdict() for ensemble review (REQ-004)
- mahavishnu: Phase 1 inventory snapshots for 7 Core 7 repos
- mahavishnu: Phase 1 trace pipeline hardening (Task 1.4 + 1.5)
- mahavishnu: Phase 7 diff_inventories.py (Plan Task 7.1)
- mahavishnu: Pre-commit gate for findings.md (Plan Task 2.2)
- mahavishnu: Qwen bridge e2e + operator runbook (Phase 12b tasks 2+3+4)
- mahavishnu: Retire bodai-activity daemon + metrics bodai CLI (Phase 12a Task 5 final)
- mahavishnu: Run_crackerjack_gate() pinned to run -v (REQ-013)
- mahavishnu: Run_pipeline() + entry point — completes merge-to-main cycle (REQ-004 + REQ-012)
- mahavishnu: Run_review() — 3-agent ensemble (REQ-004)
- mahavishnu: SessionEnd hook for merge-to-main (REQ-005)
- mahavishnu: Single-source-of-truth version stamps via importlib.metadata
- mahavishnu: TaskOrphanSweeper consumes task.handoff_orphan events
- mahavishnu: Tasks_handoff_to_workflow tool (the only dispatch edge — T17)
- mahavishnu: Tool description rubric + structural validator (Phase 2 Task 2.2)
- mahavishnu: Tool selection accuracy test + Phase 2 status flip
- mahavishnu: Tool-call span enrichment + Akosha-bound OTel attributes
- mahavishnu: Top-N MCP tool audit script (Phase 2 Task 2.1)
- mahavishnu: Wire pgvector OTel storage + Postgres 16/17/18 CI matrix
- mahavishnu: Wire Phase 4 health aggregator (Plan §4 + §5 task 7 + §11.4)
- mahavishnu: Wire TaskOrphanSweeper into start_server/stop_server + /health
- mahavishnu: Wire tasks_handoff_to_workflow into MCP server (T18)
- mcp-profiles: Register 6 drain tool names in FULL + REGISTRATION_MAP
- mcp/tools: Add 5 ecosystem_state tools (Phase 3 of Dhara decomposition)
- mcp: Add get_capability_result tool (Dhara envelope reader)
- mcp: Add mahavishnu_get_publish_url sibling-tool for crackerjack probe
- mcp: Add worker contract tools and bootstrap registration
- mcp: Add workflow_result retrieval tool
- mcp: Agent catalog + tool consolidation
- mcp: Capability resolver/planner/executor tools + profile wiring
- mcp: Filter worker_list by state and worker_id
- mcp: Phase 1 server-published skills (list_skills + get_skill)
- mcp: Phase 3 task #5 H-3 specialist dispatcher
- mcp: Pool tools route shell types through durable contract
- mcp: Register plan\_\* tools in FULL profile (5-edit dance)
- mcp: Remove iTerm2 terminal bootstrap path
- mcp: Remove iTerm2 terminal tool branches
- mcp: Route worker_spawn shell types through durable contract
- mcp: Stop truncating worker_execute / worker_execute_batch output
- mcp: Worker_close uses two-phase cancellation
- mcp: Worker_close_all and worker_health use durable contract
- mcp: Worker_collect_results supports incremental output
- mcp: Worker_monitor routes through durable manager
- Migrate launcher to mcp_common.server.launcher.launch()
- Mount durable receiver + register webhook_replay as MCP tool
- observability: Changepoint detectors (CUSUM + 3-sigma) + integration
- observability: Close merge.semantic.duration_ms instrumentation across all 3 entry points
- observability: Extend bundle_bytes histogram + Phase 3 op enum
- observability: Instrument pool_route_execute and terminal_launch for §14 pool_share
- observability: Instrument worker contract tools with metrics
- observability: Ship changepoint operator opt-in (finish-partial Phase 1)
- observability: Verify_sha256_streaming + record_bundle_integrity_failure_short
- observability: §17 OTel metrics + bundle integrity helpers (PR-B)
- paths: Add get_worktree_base_path() and get_worktree_path() helpers
- Per-session subprocess pool + crow_terminal\_\* tools
- Per-session worktree registry + CLI (Phase 1)
- permissions: Add READ_PLAN_INDEX for plan_index MCP tools
- persistence: Vendor WorkflowOutcome/ApprovalLog/WebhookIngress locally
- Plan\_\* tools with @require_mcp_auth (REQ-PLAN-010)
- plan_index,health: Wire plan_index feed into /health aggregator
- plan_index: Foundation — PlanId, errors hierarchy, paths
- plan_index: Normalize_repo_url security helper
- plan_index: PeriodicTaskRunner + cron_core + lock + DLQ (round-3 BLOCKER fix)
- plan_index: PlanIndexFeedState with strict 4-signal contract
- plan_index: PlanIndexRebuilder with normalize_repo_url integration
- plan_index: PlanIndexStore Dhara-backed CRUD with vitals
- plan_index: PlanRecord frozen dataclass
- plan_index: Renderer (pure) + Writer (I/O)
- plan_index: TypedDicts — plan surface types
- plugin: Remove old flat session-buddy commands (now session-buddy:<cmd>)
- pool-bootstrap: MCP tool for spawning pools + SessionStart bootstrap
- pools: Add pool_route_execute MCP tool (Plan v3 Phase 2m)
- pools: Drop dead QueueingScorer class (round-4 general/safety HIGH-1)
- pools: Wrap SessionBuddyPool worker_execute with subagent marker
- precommit: Add Prometheus counters to 3 substrate producers
- precommit: Retire LockStore/JsonFileLockStore, rewrite tests
- precommit: Rewrite HypothesisLock as async D-LOCK backed
- precommit: Wire CLI with asyncio.run wrappers + update error strings
- quality_cli: Wire Rich-formatted Crackerjack output (track3-toad-tui Task 4)
- Re-enable SessionBuddyWorktreeProvider by default
- Regenerate_plan_index.py orchestrator + fix discover_records field gap
- regenerator: Auto-discover stores + per-repo Authority Matrix
- Register plan_app in main CLI app
- registry: Add orb role; assert roles are in taxonomy
- registry: Migrate 24 stranded repos into canonical manifest
- registry: Register archive-org-mcp, medium-mcp, scapy-mcp
- RemoteWorktreeProvider streaming tar.zst + bounded queue (Task C.7)
- Remove old flat slash commands; mahavishnu plugin is canonical
- Route tmux preference to durable TmuxTerminalAdapter
- scapy-mcp: Feed registry (3 required, 2 optional) and wiring-discipline signals
- scripts: Add audit_type_checking_runtime_refs + pre-commit hook integration
- scripts: Add migrate_frontmatter migrator (Phase 1 of no-frontmatter migration plan)
- scripts: Audit v2 — Pattern B runtime-fallback detection + cluster summary
- settings: Add worker_contract defaults
- settings: Add workers.entries block for capability-driven registry
- settle: Register merge.semantic.duration_ms histogram + thread mergiraf path
- skills: Add bodai-worktree-cleanup skill wrapper
- skills_signer: Phase 1.5 replication to mahavishnu
- state-backends: Add dag_key/cluster_key/in_flight_key + try_put_with_log_context
- state_backends: Add DharaKv string-shape adapter for PlanIndexStore
- storage_io: Streaming tar.zst rewrite with context manager + staging promote
- substrate-compat: Extract stamp/calltime pattern into shared helper (task 144)
- Task 9 — high-level drain primitives (drain_plan, dispatch_jot, retry_dispatch, defer_jot, delete_jot)
- terminal: Deprecate iTerm2 preference to mock fallback
- terminal: Register tmux as a builtin backend
- terminal: Remove iTerm2 adapter implementation
- terminal: Remove iTerm2 session pool
- tests: Phase 3 streaming tar.zst end-to-end integration test
- tier1-math: Phase 1 — MmcQueue queueing library (REQ-001)
- tier1-math: Phase 2 — QueueingScorer + PoolManager integration (REQ-002, REQ-003, REQ-008)
- tier1-math: Phase 3 + 7 — integration tests + validation reports
- tier1-math: Phase 4 + 8 — promote queueing + changepoint defaults (adopted)
- tier1-math: Phase 5 — CUSUM, Page-Hinkley, AnomalyResult (REQ-004, REQ-006)
- tier1-math: Phase 6 — change-point observability integration (REQ-005, REQ-006, REQ-009)
- tier1-math: Phase 9 — feature eligibility script + Makefile + followups (REQ-007)
- w3: Adopt http.fetch + workflow.retry action kits
- w4: Promote oneiric action kits via decision doc and auto-trigger skill
- webhooks: Receiver emits validated WebhookIngress via dhara.put
- webhooks: Webhook_replay MCP tool — read-back via from_dict
- Wire outcome_writer into on_workflow_complete + register workflow_get_outcome MCP tool
- Wire record_approval_decision into decision flow (replaces delete-on-resolve)
- workers/contract: Add atomic JSON store for durable records
- workers/contract: Add canonical envelope publisher
- workers/contract: Add DurableWorkerManager with reconcile_all
- workers/contract: Add DurableWorkerRecord Pydantic model
- workers/contract: Add tmux adapter primitives
- workers/contract: Add WorkerLifecycleState and transition rules
- workers: Add capability layer with static, live, and observability phases
- workers: Add capability metadata fields to WorkerConfig
- workers: Discover docker/orbstack runtime and probe daemon
- workers: Gate cloud worker on credentials, no secret logging
- workers: Split one-shot submit path and de-couple resolve_worker_type
- workers: Wire capability diagnostics into CLI, MCP, and health
- Workflow lifecycle audit script
- workflow: Outcome_writer — validate-on-write at completion boundary
- Workflow_get_outcome MCP tool — read-back via from_dict
- workflows: Rewrite clone_refactor_workflow.py as git-tree DAG
- worktree-cli: Add prune-merged subcommand
- worktree_providers: Add Dhara-backed worktree registry (ADR 015 v4 §11)
- worktree_providers: Add LocalWorktreeProvider + v4 types (ADR 015 v4 §13)
- worktree_providers: Add pre_migration_discover() for v4 Phase 1.5
- worktree_providers: RedisLockBackend + Dhara registry security fixes
- worktree_providers: V4 wiring — LocalWorktreeProvider + RemoteWorktreeProvider + remove_handle + registry resolver + coordinator v4 dispatch (PR-D)
- worktree_providers: WorktreeCache wrapper + storage_io helpers (PR-C)

### Changed

- 7-agent review of mcp-common auth primitives plan — 12 distinct BLOCKERs
- acp-cli: Use build_execute_fn from Phase 1.5 factory
- Amend mcp-common auth primitives design per 7-agent review
- Atomic migration workers/task_router.py -> core/model_routing.py (Phase 3b)
- auth: Fix 12 BLOCKERs + cross-cutting IMPORTANTs from 7-agent review
- bodai-conformance: Address 4-agent review findings (critical + material)
- bodai-conformance: Apply R2-1..7 fixes inline
- bodai-conformance: Round-2 review findings as known-issues appendix
- bodai-consistency: Address 4-agent review findings
- bodai-consistency: Design for ecosystem conformance mechanisms
- Bring worktree-mahavishnu-fix-vishnu-hooks fixes onto main
- Clone-refactor + session-buddy + worker leftovers from prior session
- clone_claims: Drop redundant trailing return (refurb FURB125)
- clone_tools: Extract verification-gate + cleanup helpers from clone_refactor_group
- Close WorkerStatus stragglers in execute_fn_factory.py (Phase 5b)
- Consolidate flock+atomic-write into json_state_store
- Continue CLI audit plan + worktree residue after rebase onto origin/main
- coordinator: Extract preflight safety checks to reduce complexity
- core: App/health/cli alignment + health CLI test scaffold
- dhara-schema: Replace dhara.schema.\* imports with local msgspec types
- events: Add trailing newlines to worker_topics files
- factory: Promote execute_fn settings to real Pydantic fields (Option C)
- jot-drain: Apply 14 reviewer findings to polish spec
- jot-drain: Polish implementation plan — 7 tasks
- jot-drain: Polish spec — 6 items (slash command, reconciler revert, ctx whitelist, bundling note, action-proposal lock, action_proposals docs)
- jot: 20-task implementation plan for zero-turn inbox
- jot: Add noqa for fail-open Exception catches + B023 fix
- jot: Apply 5-agent review fixes (round 1)
- jot: Apply 5-agent round-3 review findings
- jot: Apply final-review critical fix batch (round 2)
- jot: Apply user-approved cuts and round-2 self-fixes
- jot: Lock \_propose_action policy at §3.3.4 (polish item 5)
- jot: Type \_summary_dict/\_detail_dict; strengthen MCP round-trip test
- Mahavishnu (quality: 0/100) - 2026-07-16 19:44:17
- Mahavishnu (quality: 72/100) - 2026-07-16 18:33:29
- Mahavishnu (quality: 72/100) - 2026-07-16 18:50:08
- Mahavishnu (quality: 72/100) - 2026-07-20 22:55:11
- Mahavishnu (quality: 72/100) - 2026-07-25 02:10:24
- Mahavishnu (quality: 73/100) - 2026-07-15 11:15:13
- Mahavishnu (quality: 74/100) - 2026-07-26 13:47:32
- Mahavishnu (quality: 74/100) - 2026-07-27 02:25:40
- mahavishnu: Bump oneiric floor to >=0.20 for OneiricCLIBase
- mahavishnu: Fix 12 ruff errors + 4 broken doc links (fast hooks)
- mahavishnu: Pre-existing test fixes (4 issues)
- mahavishnu: Re-export canonical AgentMetadata/SkillMetadata aliases (Phase 10 task 4)
- mahavishnu: Remove orphan terminal/backends.py and grid module
- mahavishnu: Remove vestigial TaskEventType.SYNCED
- mahavishnu: Subclass oneiric's OTelStorageSettings instead of duplicating it
- mahavishnu: Tasks_handoff uses publish_task_event_raw dict API
- mahavishnu: Use apply_tool_profile() from mcp-common
- mahavishnu: Use mandatory_groups + W0.5 fix from mcp-common 0.18.0
- mahavishnu: Use unaliased \_apply_tool_profile + pin mcp-common>=0.18.0
- Mcp-common auth primitives design — middleware, IdentityProvider, AuthHealth
- Mcp-common auth primitives — 17-task implementation plan
- observability: Extract \_canonical_detector_name helper to remove detector-name normalization duplication
- observability: Use elif in two-stage dispatch for mutually exclusive states
- Revert "feat(githooks): wire audit_no_secrets_in_mcp.py as tracked pre-commit hook"
- Rewire top-10 descriptions — get_active_alerts (Phase 2 Task 2.3)
- Rewire top-10 descriptions — get_log_statistics (Phase 2 Task 2.3)
- Rewire top-10 descriptions — get_monitoring_dashboard (Phase 2 Task 2.3)
- Rewire top-10 descriptions — get_observability_metrics (Phase 2 Task 2.3)
- Rewire top-10 descriptions — get_recovery_metrics (Phase 2 Task 2.3)
- Rewire top-10 descriptions — get_workflow_statistics (Phase 2 Task 2.3)
- Rewire top-10 descriptions — list_adapters (Phase 2 Task 2.3)
- Rewire top-10 descriptions — list_backups (Phase 2 Task 2.3)
- Rewire top-10 descriptions — list_repos (Phase 2 Task 2.3)
- Rewire top-10 descriptions — list_workflows (Phase 2 Task 2.3)
- Session-buddy (quality: 72/100) - 2026-07-15 10:38:28
- session-buddy: Mahavishnu seam hardening design (WAL + hook gate + plugin + code-graph facade + skill-coverage gate)
- session-buddy: Mahavishnu seam hardening implementation plan (6 tasks)
- session_buddy_pool: Extract pool_id/working_dirs/stitch helpers from execute_batch
- skills_signer: Minor alignment across keys/manifest/verify
- substrate-compat: Drop stamp_dhara_attr helper
- substrate-compat: Lazy-load dhara; drop bare 'import dhara' from producers
- terminal: Fix import order in manager.py
- terminal: Remove iTerm2 adapter registry entries
- terminal: Type grid against adapter ABC
- Use oneiric.core.ulid directly, drop dhara fallback chain
- Wire fail-closed end-to-end + adopt followups lifecycle
- workers/contract: Add trailing newlines to publisher files
- workers: Add dedicated factory branches for openhands, a2a, terminal-crow
- workers: Complete DebugMonitorWorker Wave 2 removal; drop stale MCP test duplicate
- workers: Narrow \_create_isolated_worker to shepherd-only (Phase 4)
- workers: Remove Docker/OrbStack ContainerWorker in favor of microVM tiers
- workers: Replace WORKER_REGISTRY with Oneiric-loaded lookup
- workers: Retire legacy isolated-worker surface (Phase 4.5b)
- workers: Single-dispatch worker factory via \_create_isolated_worker
- workers: WorkerManager consumes command_argv from WorkerEntry
- worktree-scan: Drop cyclomatic complexity under 15 in \_format_text + scan_worktrees_cli
- worktree_providers: Apply crackerjack-compliant-code cleanup
- worktree_providers: Rename direct_git.py -> local.py (1-release alias)
- worktree_providers: Rename S3WorktreeProvider + S3WorktreeRef to remote variants
- worktrees: Funnel 5 default-value sites through get_worktree_base_path()

### Fixed

- 5 of 6 doc-drift findings from mahavishnu audit
- a2a_index: Remove 5 stale fastblocks-stack specialist entries
- acp: Bypass connect_write_pipe via os.write + e2e scaffolding
- acp: Propagate async through dispatch chain (session/prompt works)
- acp: Thread-based stdin feeder + pre-flight validation (Path A+B)
- Add 'metrics bodai' subcommand for queue-file rendering
- Add trailing newlines to 15 coverage test files
- approval-cli: Bind real exception in approval_list_entry_skipped log
- approval: Log warning when decision_writer persistence is skipped (cross-portfolio consistency)
- auth: Add required_permission to 5 session_buddy decorators (Task 11.8)
- auth: Defense-in-depth audit + remove Permission.READ fallback (Task 11.10)
- auth: Thread rbac_manager through capability_tools (Task 11.8)
- auth: Thread rbac_manager through webhook_tools (Task 11.8)
- auth: Thread rbac_manager through workflow_tools (Task 11.8)
- auth: Wire rbac_manager at 5 bootstrap.py callsites (Task 11.8)
- bootstrap: Make pool init real bugs visible (Plan v3 Phase 1m)
- bootstrap: Thread skills_signer+agents+dispatch+jot through legacy path
- claude-code-stop-hook: Use absolute Python paths in hook commands
- claude: Enable bodai-activity-\* hooks by nesting under 'hooks' key
- cli: Use timezone-aware datetime in precommit_lock
- clone-tools: Address multi-agent review's CRITICAL findings
- clone_tools: Restore REJECT-path observability log
- code-index: Satisfy ruff F821 by importing Any under TYPE_CHECKING
- commands: Strip line-1 placeholder frontmatter from 78 skill/command files
- config: Anchor MahavishnuSettings yaml_file at package
- config: Correct Crow port and MCP server URL defaults
- config: Remove observability block rejected by oneiric 0.28.0
- Construct crow MCP client inside init_terminal_manager
- coordinator: Don't log removal_success when provider fails
- crow: Drop unused FastMCP import + correct ty ignore prefix in test
- crow: Implement eviction grace sequence + propagate cancellation + silence B110
- crow: Replace anyio ClientSession with raw JSON-RPC subprocess
- crow: Replace asserts with RuntimeError, log tracebacks, drop unused imports, fix isort
- crow: Retype new-tool returns, harden test stubs, set-comparison assertion
- crow: Type register() with Union[FastMCP, StandardServer]
- crow: Wire shutdown_all_sessions into FastMCP lifespan
- Defer help_cli import to avoid known-broken module-load hang
- deps: Override prefect's websockets\<17.0 pin to allow crackerjack>=0.87.0
- docs(plans)+audit: Phase 5 loop-2 (audit script fix, plan move, revert to partial)
- docs+test(changepoint): round-6 fixes per task-7 review (default-detector drift + test count + drift_warning span parity)
- docs: Add canonical frontmatter to mcp-deps-crackerjack-loop spec
- docs: Align frontmatter status/role/topic with validator enums
- docs: Register 4 fresh topic slugs in vocabulary v1
- docs: Register 4 fresh topic slugs in vocabulary v1
- docs: Register 8 fresh topic slugs in vocabulary v1
- docs: Repair YAML frontmatter in 015 ADRs + regenerate PLAN_INDEX
- docs: Resolve 12 frontmatter validation errors (status/role/date/topic)
- docs: Rewrite worktree-prefixed paths and drop broken Medium URLs
- docs: SHEPHERD_BACKEND.md relative link to ../mahavishnu/core/config.py
- docs: Update CLAUDE.md/README.md tool-count claims to match registry
- e2e: Unblock ACP integration timeouts + fix pre-existing test bugs
- ecosystem+audit: Complete 3 missing nicknames; route worktree audit to dedicated logger
- ecosystem: Quote oneiric nickname to avoid YAML 1.1 boolean coercion
- ecosystem: Rename nicknames on→oc (oneiric), md→mj (mdinject)
- engines/agno_adapter: Resolve mypy syntax error at line 169
- envelopes: Pass arguments dict to dhara.call_tool, not kwargs
- errors: Redact secret-shaped substrings in exception messages
- Exit 1 on driver-level scan failures + 4 new CLI tests
- Fold multi-agent review findings into D-LOCK plan
- followups: Map legacy status 'resolved' to canonical 'complete'
- frontmatter: Collapse 6 phase-specific shared-oneiric-substrate topics to umbrella
- frontmatter: Populate superseded_by for 2026-04-09-tui-design.md
- frontmatter: Re-convert 2026-04-09-tui-design.md
- Gate workflow_get_outcome against workflow_id allowlist (sibling-parity)
- git-ops: Add coverage for GitCommandTimeout, StashPopFailed, signal exit paths
- git-ops: Apply Error suffix to \_git_ops exception classes (N818)
- git-ops: Move pathlib.Path annotation into TYPE_CHECKING (TC003)
- Honor nested workers.enabled setting in CLI
- Honor terminal.adapter_preference in MCP bootstrap
- hooks: Detect real git worktrees via --git-dir
- hooks: Harden mode dispatch, payload validation, and option-injection
- hooks: Propagate audit script exit code in pre-commit hook
- hooks: Skip post-commit/merge/rewrite indexer in worktrees
- id-guard: Add validate_approval_id + validate_webhook_id guards
- Importorskip/skipif for missing optional deps in integration tests
- indexer: Tolerate RuntimeError from tree-sitter parse failures
- jot-drain: Thread jot id through \_append_event + restore DrainPlan.action_proposals
- jot: Add noqa for PLC3002 IIFE lambda workaround
- jot: Clamp replayed last_modified_ms + clear parked + I3 tests
- jot: Make \_wrap_at_import graceful when fastmcp is not installed
- jot: Reconciler auto-retry is fire-and-forget (polish item 2 code)
- jot: Remove dead MOD_WIDTH constant from render.py
- jot: Remove extraneous parens around min() generator (ruff UP034)
- jot: Thread event_id through CLI edit/done/reopen (latent no-op bug)
- jot: UD5 short_id is last 6 hex chars (was first 6)
- jot: Widen enrich_ctx catch + hoist git spawn (Task 5 fix round 1)
- launcher: Discover venv python relative to script path
- lint+types: Clear crackerjack comprehensive hook findings
- lint: Drop F401 unused imports in local.py
- lint: Resolve 8 ruff violations in fast_hooks
- lint: Resolve comprehensive-hook failures (pyscn + ty + lychee)
- lint: Resolve F821 / TC001 / TC003 in worktree_providers + metrics
- lint: Resolve remaining TC001/TC002/TC003 violations
- lint: Silence legitimate best-effort exceptions + min() cleanup
- local: Align read_stream to load_stream with oneiric actual API
- Log error type not str(err) on record_workflow_outcome failure
- mahavishnu: Add peer_affinity to routing decision tree
- mahavishnu: Address 3 critical + 2 high findings from multi-agent review
- mahavishnu: Address fast-hook ruff failures (S110/BLE001/F401)
- mahavishnu: Adopt mcp-common HealthAggregator, wire 503 on /health, add health e2e test (Phase 1.1)
- mahavishnu: Agno config defaults — 5 tests
- mahavishnu: Agno init, sse→streamable-http, compat-ping removal (launchd mcp startup)
- mahavishnu: Anchor ecosystem.yaml path to project root, not cwd
- mahavishnu: Annotate dev_log entry on session-buddy mirror failure
- mahavishnu: Audit script reads selector from metadata.attributes
- mahavishnu: Audit_devlog.py — per-merge matching + cleanups
- mahavishnu: Bootstrap-helper-renames — 49 tests
- mahavishnu: Bridge publishes to bodai:events stream + single-coroutine init/publish
- mahavishnu: C-12 recovery — wire executions sub-app into \_main_cli.py
- mahavishnu: C-9 follow-up — rename retry_after= → retry_after_seconds= in PoolManager quota gate
- mahavishnu: CLI starts from any CWD (defer oneiric via PEP 562 + stdlib fallback)
- mahavishnu: Cli-output-routing — 11 tests
- mahavishnu: Close coredis async generator in bridge publish
- mahavishnu: Close ruff lint cleanup on Phase C files
- mahavishnu: Close ruff TC002 + BLE001 in http_probe
- mahavishnu: Close ty errors after cj update
- mahavishnu: Content_ingester + dependency_waiter + distill + sop + repo_properties — 5 tests
- mahavishnu: Correct off-by-2 line numbers in findings.md links
- mahavishnu: Delete yaml_file workaround now that oneiric handles YAML
- mahavishnu: Dhara-schema-imports — 4 decision_writer tests
- mahavishnu: Drop dead code from pre-hybrid embeddings
- mahavishnu: Drop invalid --exitcode 0 from crackerjack invocation
- mahavishnu: Drop non-existent MiniMax-M3-highspeed model name
- mahavishnu: Drop obsolete terminal-aider from worker registry (was: 9343fc47)
- mahavishnu: Drop obsolete terminal-goose/gemini/amp worker entries
- mahavishnu: Exclude runbooks from plan_index scanner; mark 2026-09-26 migration doc superseded
- mahavishnu: Flip decision doc status to valid v1 schema value
- mahavishnu: Gitignores + claude_settings + claudemd + command_palette — 4 tests
- mahavishnu: Handle async publish in bodai_hook_bridge + redirect oneiric to local path
- mahavishnu: Health + dispatch_to_pool — 3 tests
- mahavishnu: Health + errors + mcp_auth + mcp_otel — 5 tests
- mahavishnu: Ignore *.bak.* (timestamped backups slip past \*.bak)
- mahavishnu: Import TextContent from mcp.types, not fastmcp.tools.tool
- mahavishnu: Inventory fallback for inherited Typer commands
- mahavishnu: Make ty gate deterministic across sync states
- mahavishnu: Mcp_external + end_to_end + wiring + workflow + cli_accessibility — 5 tests
- mahavishnu: Mcpretentious-removal — 4 tests
- mahavishnu: Opensearch + permissions + cross_repo + pool_route — 6 tests
- mahavishnu: Parse_verdict() — add needs_adjustment test + agent_text param name
- mahavishnu: Phase 1 verification fixes (split gates, real e2e, microbench)
- mahavishnu: Read_bodai_events_since per-entry decode resilience
- mahavishnu: Reconcile AgnoMemoryConfig default — True (was: d3f396d0)
- mahavishnu: Register telemetry middleware AFTER enrichment middleware
- mahavishnu: Remove ASCII duplicates and one block from GETTING_STARTED.md
- mahavishnu: Remove broken image ref from EMBEDDING_ARCHITECTURE.md:495
- mahavishnu: Remove decorative diagram blocks from ADR-005 (3 removals)
- mahavishnu: Remove decorative diagram blocks from VISUAL_GUIDE (13 removals)
- mahavishnu: Remove decorative diagram blocks from WORKFLOW_DIAGRAMS (2 removals)
- mahavishnu: Remove EMBEDDING_ARCHITECTURE.md duplicates from README/EMBEDDINGS_SETUP_GUIDE (5 removals)
- mahavishnu: Repair YAML frontmatter in 49 tool files
- mahavishnu: Replace AgentDB/Ollama with Dhara/FastEmbed in ADR-005
- mahavishnu: Replace EmbeddingService with oneiric hybrid chain
- mahavishnu: Replace iTerm2/MCPretentious adapters in canonical arch diagram
- mahavishnu: Replace OpenSearch DLQ with JSON + Dhara KV in VISUAL_GUIDE
- mahavishnu: Replace PoolManager routing and caller_kind in adapter diagrams
- mahavishnu: Resolve 17 ty errors + 2 creosote issues (comprehensive hooks)
- mahavishnu: Resolve 3 collection-time import errors (baseline)
- mahavishnu: Resolve 70+ pre-existing test failures
- mahavishnu: Restore ty ignores on scripts/ imports
- mahavishnu: Silence ty unresolved-import on optional deps
- mahavishnu: Suppress pre-existing ty errors in events/, drop redundant creosote exclusion
- mahavishnu: T16 review NITs — trailing newlines + ruff format cleanup
- mahavishnu: T17 fix round 1 follow-up — drop defensive AssertionError, bare raise is sufficient
- mahavishnu: T17 fix round 1 — ty directive, registration-time gate, typed errors, distinct orphan reasons
- mahavishnu: Test_agno + test_evidence + test_feature_flags — 3 tests
- mahavishnu: Test_capabilities_observability.py — 3 tests
- mahavishnu: Test_check_ecosystem_gitignores_plugin.py — 6 tests
- mahavishnu: Test_distill_workflows.py — 3 tests (schema columns + provenance gate wiring)
- mahavishnu: Test_generic_shell_worker.py — 4 tests
- mahavishnu: Test_mcp_server_core + fastmcp imports + worker_execute — 2 tests
- mahavishnu: Test_mcp_tool_inventory.py — 3 tests
- mahavishnu: Test_mcp_tools.py collection errors — 6 tests
- mahavishnu: Test_monitoring_alerting.py requests stub — 9 tests
- mahavishnu: Test_repositories.py pydantic forward-refs — 12 tests
- mahavishnu: Test_repository_messaging_tools.py + test_session_buddy_integration.py — 5 tests
- mahavishnu: Test_session_buddy_auth.py + test_crow_call_site_wiring.py — 5 tests
- mahavishnu: Test_task_router_coverage.py + test_task_router_and_auth.py — 3 tests
- mahavishnu: Test_workers_registry_coverage.py — 106 tests
- mahavishnu: Test_worktree_providers.py — 7 tests
- mahavishnu: Test_worktree_registry_cli.py — 8 tests
- mahavishnu: Ty unresolved-import suppression on correct line
- mahavishnu: Update repo count 9 → 7 in tag-based filtering
- mahavishnu: Update tool count 49 → 174+ in MCP tools mindmap
- mahavishnu: Upgrade microbench to exercise real OTel span path
- mahavishnu: Websocket-metrics disabled-mode + collector lookup — 13 tests
- mahavishnu: Wire-envelope unwrap + self-hosted KV tools for plan_index
- mahavishnu: Worktree + prefect + coordination — 5 tests
- MCP streamable-http handshake + pydantic-settings 2.15 compat + pool auto-spawn
- mcp/bootstrap: Thread rbac_manager to 4 register\_\*\_tools callsites
- mcp/lifecycle: Wire DharaKvClient into plan_index, drop synthetic fallback
- mcp: Await list_envelopes in get_capability_result tool
- mcp: Harden durable-routing fast path against Task 24 security review
- mcp: Register ecosystem_publish_url on LEGACY CLI path
- mcp: Workflow_result reads full Dhara key
- metrics: Targeted REGISTRY cleanup in production reset helpers
- Move TYPE_CHECKING-only imports to runtime scope
- observability: Add severity= and samples= to drift_warning log for parity with drift_detected
- openclaw: Cap auto-restart and surface terminal failure
- otel_ingester: Catch \_get_client failures in check_available
- otel_ingester: Normalise \_extract_timestamp to naive UTC
- permissions: Bridge mcp_common Permission values into RBACManager
- plan+spec: Apply Round 2 multi-agent review fixes (BLOCKER + IMPORTANT + selective MINOR)
- plan+spec: Close 3 spec drift + 2 plan consistency issues from final pass
- plan-a: Apply round-1 multi-agent review fixes (21 findings)
- plan-a: Apply round-2 review fixes
- plan-index: Drop 4 entries for files deleted in 561d9d2a refactor
- plan-index: Strip stale 'fix-search-tools-wiring-v2/' worktree prefix from 264 links
- plan_index,auth: Enforce READ_PLAN_INDEX via RBACManager (BLOCKER Task 11.7)
- plan_index: Atomic lock acquisition in cron_core (Task 14.6)
- plan_index: Atomic writes, JSON parse safety, prefix validation, TTL consistency
- plan_index: Reject Unicode line/paragraph separators in normalize_repo_url
- plan_index: Restore Task 16 orphaned files (check_step8 + tracking)
- plan_index: Retain lock-history on stale takeover (Task 14.7)
- plans: Use --upgrade-package instead of --upgrade --all-groups
- plans: Wrap bare blocks_on string in list (2026-09-13)
- pool: Default worker_type to shepherd post-2026-09-24 deprecation
- pool_tools: Guard RateLimitError catch against defensive-import sentinel
- pools: Close fail-open-state-drift in outbox sink and drainer breaker
- pools: SessionBuddyPool re-pointed at structured pool tools
- pools: Wire drainer into collect_and_sync + strengthen writer test (whole-branch follow-ups)
- ports: Move bodai-crow HTTP off 8675 (Prefect) to 8693
- Preserve epoch-zero oldest_ms in jot_vitals (collapses-with-or-None bug)
- provider: Parse Session-Buddy JSON payload; flip session-buddy default to enabled
- pyscn: Extract-method refactor to bring complex funcs under CC≤10
- qc: Re-add module-level httpx attribute for test patching
- quality: Resolve pyscn/creosote/refurb failures on shepherd WIP
- quality: Resolve pyscn/ty/refurb/lychee findings (Wave 2)
- quality: Resolve ruff TC001-TC003/BLE001/PIE810/RUF022 + SHEPHERD_BACKEND link
- rbac: Gate 3 read-path tools on substrate-permission check
- Register /health before MahavishnuApp.__init__ blocks
- registry: Log diagnostic on unsupported schema_version
- remote: Resolve 3 residual ty errors + migrate integration.py docstring
- Remove McpretentiousMCPClient wrapper so Crow adapter reaches bodai-crow
- Remove remaining mcpretentious references + make crow switchable
- Repair 4 broken links in openclaw portfolio spec
- repo-cli: Read canonical ecosystem.yaml, not legacy repos.yaml
- Report latest HLC (not capture HLC) in JotDetail per spec R9
- repos+rate-limit: Import types at runtime so Pydantic and slowapi can resolve
- Resolve 3 pre-existing ty errors in core/
- Resolve 7 merge conflicts from pre-wave-merge dirty state
- Resolve 9 type-checker diagnostics across 6 files
- Resolve comprehensive-hook ty errors across worktree + providers
- Resolve Wave 3 type errors (14 findings, 7 files)
- round5-followup: Add --section flag to mahavishnu health for merge_driver
- ruff: Resolve F821 undefined names + ASYNC blocking I/O (20 findings)
- scan: Drop 5 dead CLI flags + unused safe_worktree_name + slow markers
- scan: Wrap \_run_ps identity check in TimeoutExpired handler
- scripts: Audit_orphans detects FastAPI route decorators
- scripts: Clean up 3 ruff diagnostics in migrate_to_streaming_tar
- scripts: Make migrate_to_streaming_tar.py executable + drop EXE001 noqa
- security: Address push-review findings (syntax, traversal, silent corruption)
- security: Bandit skips + 3 real vulnerability fixes
- session-buddy: Remove dead cross-repo-push stubs, route index_code_graph to real indexer
- session/checkpoint: Catch httpx transport errors in is_healthy
- session/checkpoint: Repair test mocks for CommonMCPClient migration
- spec+plan: Apply critical-audit findings to Phase 12 (4 CRITICAL + 7 HIGH)
- spec: Quote YAML frontmatter values containing ': ' (crackerjack parse)
- spec: Resolve 6-agent review criticals — phantom APIs, JSON bool retry flag, TypedDicts, hook wiring, error handling
- spec: Resolve round-2 6-agent re-review criticals + importants
- spec: Resolve round-3 5-agent re-review defects
- terminal: Honor BUILTIN_BACKENDS.tool_map when resolving tool names
- terminal: Manager.create raises actionable error when mcp_client is None for BUILTIN_BACKENDS preference
- terminal: Route all BUILTIN_BACKENDS names through McpretentiousAdapter
- test-residue: Wire 5 production drift sites (Cluster 10 Item 5)
- tests: Align \_FakeStorage mock with load_stream rename
- tests: Align AgnoToolsConfig default URL with mahavishnu port
- tests: Align otel_ingester mocks with post-Phase 3 CommonMCPClient API
- tests: Assert MINIMAL profile registers health + skills_signer
- tests: Fix 10 more pre-existing failures (TaskType pollution, golden fixture, integration)
- tests: Migrate DharaThinClient mocks from post() to call_tool()
- tests: Migrate test_qc_checker to call_tool AsyncMock
- tests: Mock MCP call_tool instead of HTTP post in chaos buffer test
- tests: Mock RBAC manager in session_buddy_tools test fixture
- tests: Patch oneiric DuckdbHotStore in TestInitializeDuckDB
- tests: Pin crow call site line numbers to current source
- tests: Re-apply storage_io OSError test patch (built around builtins.open)
- tests: Regen profile fixtures via production build entry point
- tests: Rename Dhara-typed fixtures in test_pools.py to MCP
- tests: Resolve 5 more pre-existing failures + harden test plumbing
- tests: Resolve 66 of 83 pre-existing test failures
- tests: Resolve 9 more xdist-suite failures via module-reference + targeted REGISTRY cleanup
- tests: Skip dead bodai event-bridge helper test
- tests: Sync ecosystem.yaml with legacy repos.yaml (add www-mcp-servers)
- tier1-round2: Address CR-1, CR-2, S-1, S-4, S-5, S-6, CAL-1, CAL-2
- tier1-round2: Doc honesty + allowlist hardening (security review)
- tier1-round3: Address R3-C1+C2, M-1, H5, CR-1/CR-2 test
- tier1-round3: Correct stale doc numbers (R3-DOCS)
- tier1-round4-final: Monotonic drift_age gauge + M5 label allowlist route + audit doc test count
- tier1-round4: Close two CRITICALs + M2 regression test
- tier1-round5: Close deferred M#/m# findings from settle-semantic-merge review
- tier1: Pair arrivals with real service durations (was placeholder 1.0)
- tier1: Promote changepoint config to top-level ChangepointConfig
- tier1: Target_mean config + drift counter + complete OTel span attrs
- tier1: Track inter-arrival timestamps against last arrival, not last fit
- tier1: Wire QueueingScorer penalty into actual pool selection
- tier1: §7 gate test now actually measures (was vacuous)
- tier2-cj: Replace silent pass in bodai_hook_bridge.py; fix broken link in BODAI_REPO_REGISTRY.md
- tui: Make textual a true optional dependency
- ty/lychee: Resolve comprehensive_hooks failures
- ty: Remove unused missing-argument ignores
- ty: Resolve 10 union-attribute + missing-argument errors
- typing: Widen schemas and permission types to satisfy ty
- Update test_crow_call_site_wiring.py for current TerminalManager.create call sites
- validator: Exclude .archive/, accept list-form superseded_by/blocks_on, coerce Resolved->complete (C1.1)
- vocab: Add 12 topic slugs to reach 0 frontmatter warnings
- vocab: Re-add 17 topic slugs lost to publish rollback
- w3: Close mahavishnu BLOCKER 1 + BLOCKER 2 from review
- Warm-up vs failed state for /health aggregator (launchd race)
- webhooks: Add WEBHOOK_DURABLE_V1_ENABLED flag + runtime gate (Task 1 review follow-ups)
- Wire jot dispatcher through FastMCP, not FastMCPServer wrapper
- Wire repos_scanned counter to actual successful repo count (L4)
- workers/contract: Address Task 1 review notes (F401 + from __future__)
- workers/contract: Make WorkerLifecycleState available at class definition for Pydantic v2
- workers/contract: Mark_all_detached only includes states that can transition to DETACHED
- workers/contract: Narrow tmux type in cancel() and unbreak Pydantic enum import
- workers/contract: Replace misleading F3 comment with honest deferral; cover cancel idempotency
- workers/contract: Security hardening for tmux adapter (validation, safe stderr, send-keys -l) and portable test socket path
- workers/contract: Space-join send_keys parts so multi-token prompts type correctly
- workers: Address 5 capability-layer security findings
- workers: Bound execute_task timeout + wire CLI path's terminal manager
- workers: Enable runtime discovery and DOCKER_HOST wiring
- workers: Handle DEGRADED in execute and cover start() in tests
- workers: Make get_readiness async and surface aggregation errors
- workers: Pass launch command via tmux new-session instead of send-keys
- workers: Recognize Claude Code stream-json result marker
- workers: Thread prompt kwarg and update remaining routing tests
- workers: Trailing newlines and tighten AWS char class
- workers: Wire A2A agent configs from settings + add openhands test
- workflow-outcome: Env-var gate + producer/consumer getattr runtime gates
- workflows: Silence Prefect AsyncMock warnings + add REQ-CLONE-016 cancellation test
- worktree-cli: Drop redundant cast() in \_scan_validate_output_format
- worktree-registry: Close lost-update race + write-path TOCTOU
- worktree: Component-aware allow-list check + per-repo subdir allowlist
- worktree: Filter Session-Buddy provider when its tools are missing
- worktree: Widen path-validator default to ~/Projects
- worktree_providers: Address 3 security review findings from push sweep
- worktree_providers: Address PR-D security review (3 findings)
- worktree_providers: Make RemoteWorktreeRef.backend_kind required
- wrapper: Prepend venv site-packages so mcp_common is importable from system python
- wrapper: Use site.addsitedir to process .pth files in venv site-packages

### Documentation

- 4 entity wire-up specs + D-LOCK v1.1 update
- acp: Add operator usage guide + doc-staleness detector (Phase 3a)
- acp: Flip v1.0 plan to active + followup trigger audit (operator signoff 2026-09-19)
- Add Bodai Core 7 CLI audit & standardization plan
- Add complementarity section + synthesis-plan sequencing rules
- Add Crackerjack C-WIRE implementation plan
- Add D-LOCK implementation plan
- Add frontmatter to jot-drain-polish plan (mark active)
- Add INDEX.md cataloging all plans under docs/superpowers/plans/
- Add jot capture implementation plan (9 tasks)
- Add Toad row to THIRD_PARTY_NOTICES.md (Phase 3b)
- Add worktree-cleanup implementation plan (3 commits)
- Add WORKTREE_AUTOREMOVE guide + feature tracking + DEFERRED appendix
- adr-015: Storage architecture — v1, multi-agent review, v2
- adr-015: V3 — incorporates round-2 multi-agent review (~20 new BLOCKERs)
- adr-015: V3 — S3/GCS credentials delegated to Oneiric, GCS mock note
- adr-015: V4 — final-pass corrections (Principal defined, Protocol removed, exception base, Phase 1.5 spike)
- adr: 0016 v4 — close mcp-common authentication primitives deferred item
- adr: Evaluate gateway pattern (Options A/B/C) for Bodai MCP surface
- adr: Re-evaluate LangGraph as engine adapter (Phase 6)
- Align hint prefix with brand convention + reference XDG state path
- Amend plan Task 1 testing contract to nested env var
- approval: Surface async-passthrough concern + Spec coverage map (Task 4 review follow-ups)
- Archive 19 completed plans (2026-09-13)
- audit: Apply 2026-08-12 drift fixes
- audit: Correct changepoint test count to 115 across 8 files (post-F10 dispatch seam test)
- Bodai plugin standardization implementation plan
- BODAI_REPO_REGISTRY.md — authoritative Bodai repo list
- BODAI_UPGRADE_WATCH.md - Phase 4 3.15 readiness tracker
- Capture bodai diagram audit snapshot 2026-08-16
- changelog: Document mcpretentious removal + quality_scorer rename
- changepoint: Document warn re-fire updates \_last_warning_result in TwoStageDetector state diagram
- CLAUDE.md: Add MCP backend wiring discipline cross-reference
- CLAUDE: Add Bifrost LLM gateway to portmap (8471)
- CLAUDE: Point portmap note at the crow-port-move commit
- cleanup: F1+F2+F5 follow-ups from scripts/examples coverage plan
- Close out per-session worktree isolation rollout (Phase 3)
- CloudWorker retirement decision — KEEP
- Constellation tui implementation plan (10 tasks, deferred)
- Cross-reference Phase 8 commit hash in followup
- crow: Document concurrent sessions + known limitations
- decisions: Add component-health-cli-gap decision
- decisions: Add cross-repo fanout CWD isolation policy
- decisions: Add dhara-key-prefixes decision
- decisions: Add MCP backend wiring discipline rule
- decisions: Add v4 cross-references to worktree-autoremove-policy.md
- decisions: Add workflow decision README and template
- decisions: Add worktree-autoremove-policy with explicit Rule 2 amendment
- decisions: Cross-reference ADR 015 v4 + add auto-prune follow-up doc
- decisions: Index 2026-10-09-slash-commands-multi-call-only.md
- decisions: Mark test-matrix-review-followups complete (verified 2026-09-06)
- decisions: Point enforcement section at canonical hook installer
- decisions: Record SDD bundling defensive pattern (polish item 4)
- decisions: Slash commands are for multi-call workflows only
- decisions: Tag 38 decision docs with kind: decision (2026-09-13)
- Dhara MCP decomposition implementation plan with Phase 12 hook coordination
- docs+scripts(mahavishnu): plan lifespan health bypass + bodai MCP verify script
- docs+scripts: Phase 3 streaming tar rollout (D.1-D.6)
- drift: Migrate 10 task_router refs + retire 2 stale worker trackers + fix pool ASCII
- Drop Codex from Phase 11; consolidate ACP with active plan
- feature-tracking: Cross-link Phase 8 promotion as the two-stage migration window
- feature-tracking: Document round-7 polish knockouts (10 LOW items + bundle-split recovery)
- feature-tracking: Flip m-workflow-outcome from built back to wired
- feature-tracking: Flip orphan-sweep to status: wired (5/5 resolved)
- feature-tracking: Flip status to wired; document round-6 shipped
- feature-tracking: Record E2B SDK API verification
- feature-tracking: Record Task 1 P0 probe — substrate unreachable, deferred
- Finalize ADR 016 Phase 4 scope + decision
- Fix Phase 4 commit hash reference (post-amend)
- Flip 2026-09-13 migrate-no-frontmatter-plans to status: complete
- flowscape: Enrich plan + spec with Phase 4 proto schema pre-reqs
- followups: Add lifecycle template
- followups: Audit sibling repos.yaml files in crackerjack and mcp-common
- followups: Close audit-orphans-residual-caller-detection
- followups: Close integration-test blockers (9 of 13) and ACP v1.5.6 (license)
- followups: Close multi-session-mcp-contention — fix landed in session-buddy
- followups: Open multi-session-mcp-contention followup
- followups: Park 11 LOW polish items from changepoint two-stage review (round-7/8)
- followups: Record HNSW-on-DuckDB bug for akosha code_graphs_feed
- followups: Update index for bodai-hooks-sb-debug resolution
- followups: Verification note — sb-checkpoint-stash-clobber is partial
- Full revision of capability-refactor plan (v2)
- gdpr: Remove 'when designed' leftover in §10 + correct header-access description
- gdpr: §10 — describe auth posture and Article 32 alignment
- Implementation plan for plan-index Dhara canonical layer
- Jot inbox design spec (post six-lens review)
- jot: Action_proposals docstring + MCP spec sync (polish item 6)
- jot: Apply all BLOCKERs + HIGHs from multi-subagent review of sub-plan 2
- jot: Flip polish plan + design spec status to complete
- jot: Sub-plan 2 (Read) implementation plan
- Lifecycle ADRs, ARCHITECTURE refresh, version stamps, LLM provider
- mahavishnu: Add .claude/decisions/deployability-discipline.md pointer
- mahavishnu: Add ADMIN_SHELL.md with cross-link to oneiric docs (Plan Task 3.3.x)
- mahavishnu: Add CLI surface summary to BODAI_REPO_REGISTRY (Plan Task 7.2)
- mahavishnu: Add health-reason-codes runbook + PromQL alerts
- mahavishnu: Add lite-schema frontmatter to deployability-discipline.md pointer
- mahavishnu: Add niche ADR for LLM control plane + repo orchestrator positioning
- mahavishnu: Add per-repo tool-profile rationale doc (W1.1 backfill)
- mahavishnu: Add required frontmatter to C-10 ecosystem intake plan
- mahavishnu: Add Rule #7/8/9 for invalid-return-type, invalid-await, unused-type-ignore-comment
- mahavishnu: Agent-reviewed trunk-based dev spec
- mahavishnu: Akosha eval-metric-sink follow-on plan
- mahavishnu: Akosha eval-metric-sink plan — promote to active (Phase 1 shipped)
- mahavishnu: Akosha tool-call feed lifecycle follow-on plan
- mahavishnu: Akosha tool-call feed lifecycle — promote to active
- mahavishnu: Align launcher-discovery frontmatter role with cj twin
- mahavishnu: Amend ty ignore codes — Rule #6 for return-type bugs, slim audit counts
- mahavishnu: Annotate mcpretentious topic keys with migration note
- mahavishnu: Bump WebSocket rollback example image from v0.1.9 to v0.12.0
- mahavishnu: CLAUDE.md cross-link for task system
- mahavishnu: Correct akosha pytest paths in Phase A plan
- mahavishnu: Downplay Bodai framing in README
- mahavishnu: Drop dead iterm2/mcpretentious coverage targets from backlog
- mahavishnu: Drop paired-PR framing from plans (per bodai-pre-1.0)
- mahavishnu: Eval-adapter Phase 1 plan — promote to active
- mahavishnu: Eval-methodology plan — activation-signal override
- mahavishnu: Expand niche to include multi-engine + harness-agnostic
- mahavishnu: Fix stale cascade reference in crow-mcp-client-wiring followup
- mahavishnu: Flip Phase 2 to delivered across both Akosha plans
- mahavishnu: Index ty-ignore-codes decision in decisions README
- mahavishnu: Mainautopush governance decision (REQ-007)
- mahavishnu: Mark CLI audit plan complete (all 95 boxes ticked)
- mahavishnu: Note merge workflow location in CLAUDE.md
- mahavishnu: Phase 0 review revisions to eval fixture proposal
- mahavishnu: Phase 1 subagent dispatch template + status
- mahavishnu: Phase 2 cross-repo synthesis findings.md + validate_findings.py
- mahavishnu: Phase 2 partial-progress + plan 2 activation readiness
- mahavishnu: Phase 3.4 staleness findings (Plan Task 3.4.1)
- mahavishnu: Phase 4a launcher migration design note (REQ-013)
- mahavishnu: Phase A plan v2 — Task 1 + Task 3 brief revisions after pre-SDD pre-flight
- mahavishnu: Plan 2 fixture list + rubric strategy proposal
- mahavishnu: Plan 2 frontmatter reflects Phase 0 review + Akosha sink blocker
- mahavishnu: Plans-specs canonical paths decision + CLAUDE.md preference
- mahavishnu: Promote tool-surface-quality plan active -> shipped
- mahavishnu: Quarterly CLI staleness cadence (Plan Task 7.3)
- mahavishnu: Record FastMCP ≥4 migration plan + registry update
- mahavishnu: Record MANDATORY_GROUPS erratum in task-20 brief (Minor 1)
- mahavishnu: Register port 8695 in BODAI_REPO_REGISTRY + remove PENDING comment
- mahavishnu: Replace 5 dead file paths (iterm2/mcpretentious/quality_evaluator/backup_cli/production_cli)
- mahavishnu: Replace iTerm2/mcpretentious with live adapters in ARCHITECTURE
- mahavishnu: Replace iTerm2/mcpretentious with live adapters in CAPABILITIES analysis
- mahavishnu: Replace iTerm2/mcpretentious with live adapters in ORCHESTRATION_SUMMARY
- mahavishnu: Replace iterm2/mcpretentious with tmux in crow runbook
- mahavishnu: Replace mcpretentious/iTerm2 references with tmux/mock/crow adapters
- mahavishnu: Replace mcpretentious/iTerm2 with tmux/mock in mcp-server doc
- mahavishnu: Replace quality_evaluator/pool.py/iterm2/mcpretentious in 4 small docs
- mahavishnu: Retire stale bodai-event-queue.json references (Phase 12a task 7)
- mahavishnu: Rewrite BACKENDS.md as live-adapter stub (mcpretentious removed)
- mahavishnu: Round-5 revisions — fix 12 review blockers across 12 plans
- mahavishnu: Round-5 Tier 4 deliverables — 5 runbooks + 3 SLOs + 2 audit workflows
- mahavishnu: Round-6 Tier 1 corrections — fix runtime bugs in 6 plans
- mahavishnu: Round-7 Tier 2+3 — operational polish + test quality fixes
- mahavishnu: Round-8 Tier 4 — architectural fixes
- mahavishnu: Round-9 Tier 4 — niche ADR citation rate fixed
- mahavishnu: Shared oneiric substrate design spec v4
- mahavishnu: Shared oneiric substrate phase plans A/B/C/D/E1/E2
- mahavishnu: Shared substrate v5 fix pass after 2-agent review
- mahavishnu: Spec note — plan_index init deferred to background task
- mahavishnu: Spec revision after round-1 multi-agent review
- mahavishnu: Spec v3 — round-2 fixes applied inline
- mahavishnu: Task 3.1 report (REQ-005 SessionEnd hook)
- mahavishnu: Task-system design spec — Bodai-native TaskCreate replacement
- mahavishnu: Task-system implementation plan v1.1
- mahavishnu: Task-system spec v1.1 — apply 4-lens multi-agent review
- mahavishnu: Trunk-based-agent-review implementation plan
- mahavishnu: Trunk-based-agent-review workflow doc (REQ-008)
- mahavishnu: V1.1 implementation plan for Bodai task-system addendum
- mahavishnu: V1.1 plan rev2 — fold 2-agent review findings
- mahavishnu: V1.1 spec for Bodai task-system addendum
- Mark 4 superseded 2026-06-22 plans shipped + cross-link replacements
- Mark 5 mcp-stub-activation plans active and regenerate PLAN_INDEX
- Mark Phase 8 dhara retirement plan complete; regenerate PLAN_INDEX
- MCP registrar implementation plan (11 tasks)
- MCP tool profile adoption implementation plan
- mcp: Document worker contract tools
- MCP: Regenerate tools reference and specification from source
- Normalize .claude/decisions to lite frontmatter (P5 Pass 1)
- Normalize 14 ADRs to unified frontmatter (plan-lifecycle-unification P1)
- Normalize 18 orphan docs/plans files (C1.2)
- Normalize docs/plans to unified frontmatter (P2 Pass 1)
- Normalize docs/superpowers/plans to unified frontmatter (P4 Pass 1)
- Note substrate put/get call-boundary contract in 3 producer module docstrings
- observability: Note defensive isinstance guard rationale in \_on_drift_warning
- Oneiric action-kit promotion implementation plan
- Open cross-repo followup for sb subagent lockfile producer
- Pair existing wave workflows with decision files
- Pair remaining unpaired workflows with decision files; rename part2 to match filename
- plan+runbook+audit: Document two-stage warn/confirm architecture (round-5)
- plan-index: Link constellation tui to companion ACP spec
- plan-index: Regenerate after auth primitives execution
- plan-index: Track cross-repo Dhara cache-adapter consolidation plans
- plan: Add Phase 11 harness-agnostic enablement + ACP integration
- plan: Add phase-1 precondition fixes (14 deferred findings)
- plan: Add §10.4 cross-server review + update §10.1/§10.2/§11 to 5/5 complete
- plan: Add §10.5 Phase 1 cross-server review + completion markers
- plan: Apply final-pass fixes to CLI audit spec (§6 checklist + Goal #8 count)
- plan: Apply power-trio review fixes to CLI audit spec
- plan: Apply round-2 power-trio review fixes (verification + ordering + risk + reader-experience)
- plan: Apply round-2 single+random review fixes (pattern + realism)
- plan: Clone-refactor wire-up v2 — review-pass feedback applied
- plan: Clone-refactor wire-up v3 — re-review sweep applied
- plan: Clone-refactor wire-up v4 — final review pass sweep applied
- plan: Correct changepoint test count to 115 across 8 files
- plan: D2 reviewer fixes — §10.3 wiring contract + stale-path corrections
- plan: Drop speculative crackerjack.security.critical_hooks gauge
- plan: M-APPROVAL-LOG — wire approval_log into Mahavishnu (4 tasks)
- plan: M-WEBHOOK-DURABLE — wire webhook_ingress into Mahavishnu (3 tasks)
- plan: M-WORKFLOW-OUTCOME — wire workflow_outcome into Mahavishnu (4 tasks)
- plan: Post-review amendments (F1-F50)
- plan: Promote acp-v15.6 license reconciliation to Resolved Items
- plan: Promote skill-agent-distribution to active, close B-1
- plan: Revision 1 — apply 27 findings from 5-agent review
- plan: Revision 2 — apply 5-agent re-review findings
- plan: Self-review pass on CLI audit spec
- plan: Switch status from draft to active
- plan: Update CLI audit spec for γ dual-TUI decision + monitoring_cli drift
- plan: V3 fixes from single-agent final review
- plan: V3 — cron real-scan + --render-to flag + 5 security tests
- plan: §10.2 — mark Phase 2 + Phase 6 SHIPPED + update Week 4/5/6 sub-lists
- plan: §10.2 — mark Phase 3 dispatcher + Phase 5 SHIPPED
- plan: §10.6 — Phase 3+4+6 cross-server review with str_strip_whitespace fix entries
- plans: 2-repo plugin POC scope for graphics-mcp + css-mcp
- plans: 2026-09-12 plan audit pass
- plans: 2026-09-13 overlap-followup fixes
- plans: 3 PARTIAL status flips + Re-Review notes (2026-09-13)
- plans: 6 status flips from completeness audit (2026-09-13)
- plans: Add audit gate after Task 9 (docs commit)
- plans: Add audit gates after source-code tasks (1, 4, 5, 6, 7)
- plans: Add bodai MCP surface standardization plan + lifespan cleanup
- plans: Add bodai-conformance plan + spec to canonical PLAN_INDEX.md
- plans: Add bodai-mcp-search-infrastructure-fix plan
- plans: Add CommonMCPClient transport unification umbrella plan
- plans: Add durable local workers implementation plan
- plans: Add frontmatter to bodai-tui-shell-surface-implementation (2026-09-13)
- plans: Add frontmatter to fastmcp-4-upgrade + cross-link to Cluster A (2026-09-13)
- plans: Add frontmatter to validator-wiring plan
- plans: Add jinja2-custom-delimiters 1.0.4 implementation plan
- plans: Add mcp-health-check-enrichment followup plan (Phase 10 of bodai-search-infrastructure-fix)
- plans: Add Phase 0 inventory lock for orchestrator fix
- plans: Add Phase Status table to finish-partial-implementations
- plans: Add session-buddy-worktree-tools follow-up plan
- plans: Add Task 26 (iTerm2 deprecation/removal) and confirm open questions
- plans: Apply 5 BLOCKERs + 4 MAJORs from refuter review to health-enrichment plan
- plans: Apply CRITICAL fixes from 5-agent plan review
- plans: Apply multi-reviewer audit fixes (F1-F20 + new tasks 8a/8b/18-25)
- plans: Apply remaining HIGH/CRITICAL fixes from 5-agent review
- plans: Archive-org-mcp implementation plan at full step depth
- plans: Auth → complete; bump 6 last_reviewed; flip Cluster A 4 → complete (2026-09-13)
- plans: Broaden Phase 3 plan to cover all Bodai-maintained repos
- plans: Bump target version 0.69.5 → 0.70.0 (MINOR per SemVer)
- plans: Close routing-feedback-loop-v4 partial — query_local_traces now ships on all 5 Bodai components
- plans: Commit Phase 8 dhara retirement plan as historical record
- plans: Create plan for migrating 40 no-frontmatter files (2026-09-13)
- plans: Cross-link TUI/storage clusters; defer flowscape + zsh (2026-09-13)
- plans: Drop HotStore JSON-path bug caveat — fixed upstream in Akosha 9845c5c
- plans: Finish-partial Phase 5 (post-close audit) + plan → complete
- plans: Fix broken local links surfaced by check-local-links
- plans: Flip 2026-05-14-doc-sync-and-channel-phase2 to status: complete
- plans: Flip 2026-06-19-track3-toad-tui to status: complete
- plans: Flip 2026-07-11-ultracode-integration-wiring to status: complete
- plans: Flip 2026-07-16-bodai-plugin-standardization to status: complete (path-not-taken)
- plans: Flip 2026-08-24-claude-env-audit-remediation to status: complete
- plans: Flip 2026-09-10-bodai-math-initiatives-tier1 to status: shipped (finish-partial Phase 4)
- plans: Flip 2026-09-10-settle-semantic-merge to status: shipped
- plans: Flip dhara-outstanding-items-plan to status: complete
- plans: Flip finish-partial meta-plan to status: complete
- plans: Flip track3-toad-tui draft -> active; regen index (2026-09-13)
- plans: Fourth revision + activate bodai-search-infrastructure-fix
- plans: Implementation plan for validator wiring + P7 cross-repo expansion
- plans: Keep wrapper pkg_path per spec; CLI flag stays as repo_root
- plans: Mark bodai-search-infrastructure-fix + mcp-health-check-enrichment as shipped
- plans: Mark oneiric wire standardization shipped
- plans: Mcp-deps-crackerjack-loop implementation plan
- plans: Plan 0a registry migration and Plan 0b port reconciliation
- plans: Promote 2026-07-16-dlq-fail-closed-wiring to shipped
- plans: Promote mcp-health-check-enrichment to active (2-agent review complete)
- plans: PyPI auth redesign implementation plan
- plans: Reconcile PLAN_INDEX drift-sync 2026-07-15
- plans: Reflow 9 single-line-after-heading frontmatter blocks (2026-09-13)
- plans: Refresh 2026-09-13 no-frontmatter migration plan with live inventory
- plans: Refresh migration plan for +1 file drift (38 -> 39)
- plans: Regen PLAN_INDEX.md to reflect 2026-09-14 plan state
- plans: Regenerate PLAN_INDEX after 6 status flips (2026-09-13)
- plans: Regenerate PLAN_INDEX after dhara-outstanding-items-plan flip to complete
- plans: Regenerate PLAN_INDEX after kind: decision + reflows (2026-09-13)
- plans: Regenerate PLAN_INDEX.md — includes jot-drain-polish (active)
- plans: Render kind column + add by-kind section to PLAN_INDEX (2026-09-13)
- plans: Revise bodai-search-infrastructure-fix after 4-agent review
- plans: Revise shared-validator plan based on 4-agent review
- plans: Third revision of bodai-search-infrastructure-fix
- plans: Tick stale-done ultracode Phase 1-3 items
- plans: Update decision-kind description to cover ADRs (2026-09-13)
- plans: Update tier1-math inline text + regenerate PLAN_INDEX
- plans: V2 — review fixes for transport unification plan
- plans: Worker registry capability refactor implementation plan
- Pool + worker MCP tool audit (Plan §10 #1, #2, #5)
- pools: Substrate-wrapper rationale + Plan §10 #5 resolution (v4)
- portfolio: Flip D-AUDIT from parked to adopted (substrate shipped)
- portfolio: Flip D-LOCK to wired (v1 shipped) + link v1.1 follow-up plan
- portfolio: Flip M-APPROVAL-LOG from parked to wired (substrate shipped)
- portfolio: Flip M-WORKFLOW-OUTCOME from parked to wired (substrate shipped)
- portfolio: Flip S-CHANNEL-DURABLE from parked to wired (4th consumer wire-up shipped)
- portfolio: M-WEBHOOK-DURABLE building (receiver built, not mounted) + add M-WEBHOOK-DURABLE-WIRED follow-up row
- portfolio: Retire D-AUDIT and update D-OBJ-SCHEMA scope (Wave 2 follow-up)
- Promote serverless-readiness plan to active + ADR 017
- Re-review 8 stale plans (last_reviewed: 2026-07-16 -> 2026-09-13)
- readme: Add Bodai Ecosystem Role section
- readme: Bump Python badge from 3.13+ to 3.14+
- Reconcile auto-checkpoint review findings
- Record iTerm2 adapter removal
- Refine LangGraph ADR with §10 follow-up evidence (same-day refresh)
- Refine P0 audit fixes for tool-count, profile wording, and CLI inventory
- Refresh BODAI_REPO_REGISTRY.md to current regen output
- Refresh canonical reference docs against current codebase
- Refresh references + math-spec audits + archive metadata
- Regenerate PLAN_INDEX.md to include 5 mcp-stub-activation plans
- registry: Add chat-bridge-mcp to Bodai MCP servers table
- registry: Add scapy-mcp, archive-org-mcp, medium-mcp
- registry: Update chat-bridge-mcp row to reflect v0.1.0 status (T34)
- Relocate stray session PNGs to docs/assets/images/.scratch/
- Remove Dhara references from CLAUDE.md + README.md (Phase 8 T16)
- Rewrite C-WIRE plan with verified APIs + observability
- runbook: Add healthy drift_warning_total rate heuristic (~30 per 10,080 design point)
- runbook: Explain detector attribute dual-convention for two-stage warn/confirm spans
- schema: Expand topic vocabulary seed list 10 -> 19 to cover P1 ADRs
- schemas: Add 3 ecosystem topics to vocabulary (crackerjack-publish-auth, akosha-skills, bodai-radar)
- schemas: Add followups-index topic to vocabulary
- schemas: Add optional kind discriminator to frontmatter v1.1 (2026-09-13)
- schemas: Add session-worktree-isolation topic to vocabulary
- schemas: Reference crackerjack integration surface
- scripts: Migrate 1 docs/followups/ to v1 schema
- scripts: Migrate 1 docs/plans/ to v1 schema
- scripts: Migrate 15 docs/superpowers/specs/ to v1 schema
- scripts: Migrate 22 docs/superpowers/plans/ to v1 schema
- skills: Migrate SKILL.md frontmatter to YAML
- skills: Migrate slash commands and CLI to execute_capability
- skills: Rename vishnu to mahavishnu
- skills: Rename vishnu-status to mahavishnu-status
- spec+plan: Apply multi-agent review fixes (PATH A)
- spec+test: Point Phase 4 health references at mcp-common canonical home
- spec: Add Bodai OpenClaw/Hermes-inspired follow-ups portfolio
- spec: Add jot inbox capture sub-plan 1 design
- spec: Add jot inbox drain sub-plan 3 design
- spec: Add jot inbox read sub-plan 2 design
- spec: Add worktree-cleanup-policy design (post 4-agent review)
- spec: Add §4.13 + Phase 12 hook bus coordination
- spec: Apply review fixes to Dhara MCP decomposition design
- spec: Apply second-pass review fixes (3 fresh agents)
- spec: Clone-refactor wire-up + dispatch_to_pool env-failure design (v1)
- spec: Clone-refactor wire-up design (v2) — multi-reviewer feedback applied
- spec: Clone-refactor wire-up design (v3) — final-review-pass feedback applied
- spec: Clone-refactor wire-up design (v4) — sanity-check fixes
- spec: Collapse Phase C iTerm2 deprecation+removal per user direction
- spec: Draft Dhara MCP decomposition design
- spec: Draft MCP registrar design — canonical YAML emits .mcp.json + ~/.qwen/settings.json
- spec: Final review pass — medium tool table, CI correction, probe split
- spec: Incorporate topology + Postgres consolidation review
- spec: Link crackerjack-side followup from Phase 8 cross-repo coordination
- spec: MCP stub activation design — archive-org, medium, scapy
- spec: MCP tool profile adoption across 18 Bodai-ecosystem MCP servers
- spec: Oneiric action-kit adoption promotion design
- spec: Plan-index Dhara canonical metadata layer (v2, pentaverate-revised)
- spec: Plan-index Dhara canonical metadata layer (v3, round-2 fixes)
- spec: Review pass — fix kit count, frontmatter, path, rollout gaps
- spec: Revision 1 — fold 5-reviewer task-force findings + verify Qwen schema via context7
- spec: Revision 2 — four-lens review applied to MCP stub activation
- spec: Worktree-cleanup-policy post-QA amendments (A52-A74)
- specs+followups: Normalize 4 orphan files (C1.3)
- specs: Add durable local workers design (tmux default, iTerm2 demoted, Zellij deferred)
- specs: Add jinja2-custom-delimiters 1.0.4 update design
- specs: Bodai plugin standardization design
- specs: Broaden Python 3.14 scope to ALL Bodai-maintained repos
- specs: Capability-driven worker registry + engine composition design
- specs: Constellation tui three-surface design
- specs: Design for wiring validator into crackerjack + P7 cross-repo expansion
- specs: Flip 2026-05-16-llm-routing-standardization-design to complete+superseded
- specs: Flip 2026-07-15-constellation-tui-design to complete
- specs: Fold 15 BLOCKERs from multi-agent review into Phase3 streaming tar design
- specs: Fold 22 BLOCKERs from round-2 multi-agent review into Phase3 design
- specs: Fold single-agent final pass + Python version strategy (Option C)
- specs: Mahavishnu acp server design (path A, deferred)
- specs: Mcp-deps-crackerjack-loop design (2026-08-20)
- specs: PyPI auth redesign — replaces recurring publish auth bug class
- specs: Rev2 — addresses 5-reviewer audit findings
- specs: Revise capability refactor per multi-agent review feedback
- specs: Revise jinja2-custom-delimiters 1.0.4 design after 5-agent review
- specs: Streaming tar.zst bundles Phase 3 design
- Stash-clobber fix plan + rework (R1-R10 critical-blocker fixes)
- superpowers: Add crackerjack scripts/examples coverage design spec
- superpowers: Add crackerjack scripts/examples coverage plan
- superpowers: Add mcp-common Phase 1 design spec
- superpowers: Add mcp-common Phase 1 implementation plan
- superpowers: Apply multi-agent review fixes (Round 2 — cross-plan consistency)
- superpowers: Apply multi-agent review fixes across 4 plans
- superpowers: Apply Round 2 review fixes (cross-plan consistency + Python idiom)
- superpowers: Fix ruff --config to use inline TOML, not file path
- superpowers: Fix ruff --per-file-ignores -> --config=\<file.toml>
- superpowers: Medium-mcp implementation plan (14 tasks, 70 steps)
- superpowers: Scapy-mcp implementation plan (13 tasks, 60 steps)
- terminal: Document dual-spawn mcpretentious at boot
- terminal: Drop iTerm2 docstring references
- Update capture plan to reflect post-review implementation
- Update capture plan to reflect post-review implementation
- Update stale /vishnu-status reference to /mahavishnu:status
- V2 — apply 4-agent plan review fixes
- v2-plan: Diagnose dispatch_to_pool async-callback bug + design fix
- Worker readiness and lifecycle repair design
- Worker readiness plan v3 (full review fixes)
- workflow-outcome: Flip status to built per multi-agent review
- workflows: Archive superseded waves and update their decision Status

### Testing

- acp: Add Hypothesis property tests for protocol + synthesizer (sub-commit 1.4)
- agno+auth: Restore cluster 6+7 working-tree fixes
- Assert no references to query_cache_l2 after Phase A
- audit: Cover cross-module __all__ resolution
- auth: Add cross-cutting RBAC sweep tests (Task 11.8)
- auth: Cover Principal.has_scope
- bootstrap: Capture loguru warning via capsys instead of caplog
- bootstrap: Init signer+plan_index feeds before /health assertion
- changepoint: Add boundary-sample test for confirm firing on confirm_window_samples-th sample
- changepoint: Integration benchmark for TwoStageDetector; bench.json keys for §1/§7
- CI gate integration coverage
- cleanup: Delete test_substrate_compat_enforcement (tests dead helper)
- cleanup: Remove contradictory stale_pid test + fix auth test for new fail-fast contract
- cli: Add direct tests for list-sessions and prune-abandoned
- cli: Tighten vacuous assertions + index decision doc + trailing newline
- cluster-10: Align 7 stale test invariants to current production
- Cover CrossRepoAggregator.get_repos_needing_attention
- Cover MahavishnuApp budget_watchdog lifecycle methods
- crow: Update 3 pre-existing assertions for current port + opt-in design
- Delete resurrected test_terminal_manager.py
- dhara_kv: Cover DharaKvClient contract + cron int(dict) reproducer
- distill,precommitment: Skip cleanly at collection when duckdb is missing
- Drop dhara.schema stub machinery from 2 webhook tests; fix stale docstring
- E2e scaffolds for agents + settle-merge + agent metadata schema
- Fix collection collisions by renaming, not packaging
- Fix mypy strict on test_audit_plan_index.py:179 (REQ-PLAN-009)
- Fix pytest module-name collision by completing the test package chain
- fixtures: Regenerate FULL golden fixture to current production
- integration: Add docker-compose for end-to-end DAG test
- integration: End-to-end execute_capability DAG
- jot-drain: Property tests for idempotency, state invariants, surfacing ranking
- jot: Add return-type Any check to test_no_any.py
- jot: Adversarial tests for reconciler auto-retry (polish item 2 tests)
- jot: End-to-end pipeline integration tests
- jot: End-to-end pipeline integration tests
- jot: Lift drain.py coverage to 97.34% via test_drain_error_paths
- jot: Update capture_echo tests for UD5 last-6 short_id
- lifecycle,wiring: Fix stub + regenerate golden fixtures
- lifecycle: Assert on_mahavishnu_startup returns reconciled records
- mahavishnu: Fix hook command parser to honour $CLAUDE_PROJECT_DIR
- mahavishnu: Fix stale TestFastMCPServerInit tracing tests
- mahavishnu: Full bridge e2e suite (Phase 12a task 6)
- mahavishnu: Regression test for /health lifespan bypass
- mahavishnu: TaskOrphanSweeper e2e Redis round-trip + ack verification
- mcp/tools: Supply fake rbac_manager to capability tool tests (W5 Cluster 1)
- mcp/tools: Supply fake rbac_manager to webhook/workflow tool tests
- mcp: Add tool inventory ratchet test (CI guard against count drift)
- mcp: Cover workflow_result path-traversal guard (Task 24 sibling-gate-parity)
- mcp: Per-tool e2e + smoke tests for plan_index (REQ-PLAN-013)
- mcp: Remove orphan test files for deleted tools (3b.3 followup)
- paths: Add CI guard test for worktree base path resolution
- Pin EventBridgeConfig default_factory resolution
- plan_index: Concurrency, DLQ, OTel flag, lock format, /health aggregation
- plan_index: Golden render + feature-tracking + partial failure + dict roundtrip
- plan_index: Round-2 security & auth-gate test coverage (REQ-PLAN-010/011/012)
- pools: Drop dead TestQueueingScorer coverage (general/safety HIGH-1)
- precommit: Cover duplicate async lock branch
- precommit: Drop unused r1 assignment + unnecessary f-prefix
- precommit: Replace vacuous duplicate-lock test + fix DTZ005
- profiles: Align MINIMAL + jot\_\* invariants to Phase 1.5/3 canonical
- profiles: Cover REGISTRATION_MAP as canonical W0 dispatch surface
- registry: Add edge case coverage + fix corrupt-shape bug
- registry: Assert canonical is a superset of legacy (currently failing)
- registry: Assert every canonical manifest path exists on disk
- registry: Assert settings/repos.yaml has deprecation header
- registry: Pin legacy entry count against silent deletion
- Round-trip + completion report for M-APPROVAL-LOG
- Round-trip + completion report for M-WORKFLOW-OUTCOME
- scan: Add 8 \_format_text section tests (F-QA-12) + restore L4 tests
- scan: Add \_group_plan_orphans 4-test coverage set (F-QA-14)
- server_core: Check OTel tracing middleware by type, not call count
- skill: Add 3 trigger-phrase + wrapper smoke tests (F-QA-15)
- Supply fake rbac_manager to channel_session tool tests (W5 Cluster 2)
- terminal: Cover removed iTerm2 preference fallback
- terminal: Fix indentation after iTerm2 patch removal
- terminal: Prune stale iterm2\_\* assertions after 3b.0 field removal
- terminal: Remove deleted iTerm2 test dependencies
- terminal: Remove iTerm2-only suites
- terminal: Remove leftover iTerm2-coupled suites
- terminal: Repair indentation in mcp-client test
- tools: Supply fake rbac_manager to git_analytics tool tests (W5 Cluster 4)
- webhooks: Round-trip + completion report for M-WEBHOOK-DURABLE
- websocket: Cover broadcast_settle_transition in parametrized suite
- wiring: Close 3 demo unsubscribe\_\* orphans via Attribute reference
- wiring: Close audit_orphans findings for 7 residual symbols
- wiring: Use Attribute access so audit walker counts the references
- workers/contract: Add reconciliation integration test
- workers: Add integration suite for capability live probes
- workers: Add trailing newline to gate test
- workers: Add trailing newlines to integration suite
- workers: Align observability tests with Oneiric logger
- workers: Assert new tmux new-session invocation shape
- workers: Assert tool-result blocks do not trigger completion
- workers: Fix list-types ready-only test for log noise and path gating
- workers: Fix WorkerResult import path (3b.4 cleanup)
- workers: Pin retired-worker_type ValueError contract
- workers: Smoke test all 16 terminal-\* worker types
- workers: Switch gate test to nested env-var override
- workers: Update registry tests for resolve_worker_type de-coupling

### Build

- deps: Drop dhara dep from ecosystem extras (Phase 8 T10)
- deps: Drop editable session-buddy redirect, use published 0.31.0
- deps: Lift fastmcp pin ceiling from \<4 to \<5
- deps: Unlock mcp-common to >=0.27.0
- mahavishnu: Add tasks_handoff_to_workflow feature-flag gate (PR #1 prep)
- mahavishnu: Bump session-buddy pin to >=0.31.0 for v1.1 sweeper
- mahavishnu: Pin rustup stable + sync deps for turbovec build
- Remove iTerm2 dependency group
- uv.lock: Refresh after oneiric dep removal (Phase 8 T10 follow-up)

### Internal

- Bump Bodai core deps + transitive deps to latest published versions
- Bump last_reviewed dates and normalize agent/command frontmatter
- Bump oneiric dep to >=0.16.0
- Bump requires-python to >=3.14
- Bump settings/ecosystem.yaml last_updated + add EOF newlines + clarify README
- Bump to v0.23.0 and correct tool/repo counts
- Bump version to 0.10.0
- Bump version to 0.11.0
- Bump version to 0.12.0
- Bump version to 0.12.1
- Bump version to 0.13.0
- Bump version to 0.14.0
- Bump version to 0.17.0
- Bump version to 0.18.0
- Bump version to 0.18.1
- Bump version to 0.19.0
- Bump version to 0.20.0
- Bump version to 0.20.1
- Bump version to 0.20.2
- Bump version to 0.20.3
- Bump version to 0.20.4
- Bump version to 0.21.0
- Bump version to 0.22.0
- Bump version to 0.22.1
- Bump version to 0.23.0
- Bump version to 0.24.0
- Bump version to 0.24.1
- Bump version to 0.24.2
- Bump version to 0.25.0
- Bump version to 0.26.0
- Bump version to 0.27.0
- Bump version to 0.28.0
- Bump version to 0.28.1
- Bump version to 0.28.2
- Bump version to 0.28.3
- Bump version to 0.28.4
- Bump version to 0.29.0
- Bump version to 0.29.1
- Bump version to 0.29.2
- Bump version to 0.30.0
- Bump version to 0.31.0
- Bump version to 0.32.0
- Bump version to 0.33.0
- Bump version to 0.33.1
- Bump version to 0.33.2
- Bump version to 0.34.0
- Bump version to 0.9.0
- claude-md: Add oneiric action-kit discovery breadcrumb
- Clean ADR 0016 frontmatter + regen PLAN_INDEX
- cleanup: Remove unused \_validate_approval_id + \_validate_webhook_id aliases
- clone-tools: Post-wireup polish
- deps: Bump crackerjack>=0.70.0; remove duplicated validator script; fix plan/spec frontmatter
- deps: Bump mcp-common floor to >=0.26.0,\<0.27.0 (Phase 2.5)
- deps: Bump oneiric floor to >=0.19.1
- deps: Catch up uv.lock to in-tree version bump (0.26 → 0.27)
- deps: Upgrade crackerjack to 0.87.1 (release-audit file-path claim fix)
- ecosystem: Add 5 nicknames; docs(plans): track nickname + audit logger gaps
- ecosystem: Add package field to all 8 repos
- followups: Drop stale HEAD tracking of audit-orphans followup
- gitignore: Add .coverage\* + untrack .coverage-ratchet.json (bodai 2026-08-17)
- gitignore: Apply Bodai canonical snippet
- gitignore: Ignore .claude/worktree-snapshots/
- jot: Trivial docstring/comment typo + trailing newline fixes
- lint: Silence S110/N818 fast-hook findings in MCPStateBackend
- mahavishnu: Add minimax_health.sh probe script
- mahavishnu: Align ruff target-version with 3.14 + weekly status
- mahavishnu: Backfill title: frontmatter for plan-index eligibility
- mahavishnu: Bring .gitignore into Bodai canonical conformance
- mahavishnu: Broken plan links + mdformat/ruff-format hygiene
- mahavishnu: Consolidate trunk-based workflow + main branch protection
- mahavishnu: Decommission Dhara from .mcp.json + refresh uv.lock
- mahavishnu: Delete archive diagram mirrors (9 files)
- mahavishnu: Delete old docs/superpowers/{plans,specs}/ paths
- mahavishnu: Gitignore .superpowers/; untrack scratch state
- mahavishnu: Relocate plans to docs/plans, specs to docs/specs
- mahavishnu: Rewrite 170 in-repo references to new plan/spec paths
- mahavishnu: Settings wiring audit + XDG overlay test + PLAN_INDEX regen
- mahavishnu: Untrack archived plans/specs still at old paths
- mahavishnu: Wire SessionEnd hook + cleanups (REQ-006)
- Maintenance + audit-apply scripts
- MCP launcher migration audit script (REQ-012, REQ-015)
- MCP server migration tracker (REQ-012, REQ-015)
- mcp: Deprecate legacy pool/worker/dispatch tools (3b.1)
- mcp: Prune tool_versions deprecated entries + add 4 new
- mcp: Remove deprecated pool/worker/dispatch tools (3b.3)
- patterns: Drop github-actions pattern definition
- PEP 735 compression-zstd group (Phase 3 streaming tar)
- Pin minimax-coding-plan-mcp install args
- plan_index: Maintenance scripts + module touch-ups
- plan_index: Migration run steps 1-5 (operator runbook + scripts)
- plan_index: Migration step 6 complete — MCP tools wired
- plan_index: Migration steps 7-8 — skill cut-over + adopted
- plugin: Normalize mcpServers path to use ./ prefix
- Re-pin python to 3.14 (follow-up to c1f3c18 requires-python bump)
- registry: Onboard cmux-mcp; regen surfaces pre-existing flowscape entry
- Remove .github/workflows/ci.yml (Bodai uses crackerjack per feedback-bodai-no-provider-specific-ci.md)
- Remove .superprofits/ scratch typo, add to .gitignore
- repo: Remove 30 tracked runtime artifacts + extend gitignore
- Restore unrelated task dashboard files
- ruff: Apply safe autofix for 600 findings (Wave 0.5)
- ruff: Apply Wave 1a datetime UTC fixes (251 findings, 87 files)
- ruff: Apply Wave 1b mechanical fixes (176 findings, 77 files)
- ruff: Apply Wave 1b/2/3 exceptions (9 findings, 8 files)
- ruff: Apply Wave 1b/2/3 workers_engines_automation (79 findings, 22 files)
- ruff: Apply Wave 3 BLE001 + TRY002/TRY004 (740 findings, 232 files)
- ruff: Apply Wave 3 BLE001 partial (267 findings, 51 files)
- sdd: Smoke test multi-backend PTY
- skills: Trim oneiric-action-kit-awareness description to 396 chars (under 400 hard limit)
- Stage 2 cleanup pass
- Sync uv.lock to 0.24.2 (lockfile lagged behind the 5ab9e780 version bump)
- terminal: Drop mcpretentious reference in config default
- workers: Remove terminal-openclaw and terminal-zsh

## [0.34.0] - 2026-10-09

### Added

- Add mcp\_\_mahavishnu\_\_audit_health tool + audit_health CLI (Phase 2)
- pool-bootstrap: MCP tool for spawning pools + SessionStart bootstrap

### Changed

- mahavishnu: Pre-existing test fixes (4 issues)

### Fixed

- mahavishnu: Adopt mcp-common HealthAggregator, wire 503 on /health, add health e2e test (Phase 1.1)
- mahavishnu: Agno init, sse→streamable-http, compat-ping removal (launchd mcp startup)
- mahavishnu: CLI starts from any CWD (defer oneiric via PEP 562 + stdlib fallback)
- mahavishnu: Close coredis async generator in bridge publish
- mahavishnu: Ignore *.bak.* (timestamped backups slip past \*.bak)
- mahavishnu: Suppress pre-existing ty errors in events/, drop redundant creosote exclusion
- tests: Rename Dhara-typed fixtures in test_pools.py to MCP
- tier2-cj: Replace silent pass in bodai_hook_bridge.py; fix broken link in BODAI_REPO_REGISTRY.md

### Documentation

- plans: Add bodai-mcp-search-infrastructure-fix plan
- plans: Add mcp-health-check-enrichment followup plan (Phase 10 of bodai-search-infrastructure-fix)
- plans: Apply 5 BLOCKERs + 4 MAJORs from refuter review to health-enrichment plan
- plans: Fourth revision + activate bodai-search-infrastructure-fix
- plans: Mark bodai-search-infrastructure-fix + mcp-health-check-enrichment as shipped
- plans: Promote mcp-health-check-enrichment to active (2-agent review complete)
- plans: Revise bodai-search-infrastructure-fix after 4-agent review
- plans: Third revision of bodai-search-infrastructure-fix

### Build

- mahavishnu: Pin rustup stable + sync deps for turbovec build

## [0.33.2] - 2026-10-04

### Added

- mahavishnu: MCP lifespan refactor — move post-listener init out of start_server

### Fixed

- mahavishnu: Exclude runbooks from plan_index scanner; mark 2026-09-26 migration doc superseded
- mahavishnu: Flip decision doc status to valid v1 schema value
- mahavishnu: Import TextContent from mcp.types, not fastmcp.tools.tool
- mahavishnu: Wire-envelope unwrap + self-hosted KV tools for plan_index

### Documentation

- mahavishnu: Spec note — plan_index init deferred to background task

### Testing

- mahavishnu: Fix stale TestFastMCPServerInit tracing tests

## [0.33.0] - 2026-10-03

### Added

- mahavishnu: /merge-to-main slash command (REQ-004)
- mahavishnu: Add dev_log.write_entry() (REQ-003)
- mahavishnu: Add DEV_LOG_DIR + get_dev_log_path() (REQ-002)
- mahavishnu: Aggregate_verdicts() — 3-rule priority (REQ-004)
- mahavishnu: Apply worktree convention (XDG path default)
- mahavishnu: Audit_devlog.py CI gate (REQ-011)
- mahavishnu: Merge_to_main scaffold + .review-state.json I/O (REQ-014)
- mahavishnu: Parse_verdict() for ensemble review (REQ-004)
- mahavishnu: Run_crackerjack_gate() pinned to run -v (REQ-013)
- mahavishnu: Run_pipeline() + entry point — completes merge-to-main cycle (REQ-004 + REQ-012)
- mahavishnu: Run_review() — 3-agent ensemble (REQ-004)
- mahavishnu: SessionEnd hook for merge-to-main (REQ-005)

### Fixed

- mahavishnu: Annotate dev_log entry on session-buddy mirror failure
- mahavishnu: Audit_devlog.py — per-merge matching + cleanups
- mahavishnu: Drop invalid --exitcode 0 from crackerjack invocation
- mahavishnu: Parse_verdict() — add needs_adjustment test + agent_text param name

### Documentation

- mahavishnu: Agent-reviewed trunk-based dev spec
- mahavishnu: Eval-adapter Phase 1 plan — promote to active
- mahavishnu: Mainautopush governance decision (REQ-007)
- mahavishnu: Note merge workflow location in CLAUDE.md
- mahavishnu: Plans-specs canonical paths decision + CLAUDE.md preference
- mahavishnu: Spec revision after round-1 multi-agent review
- mahavishnu: Spec v3 — round-2 fixes applied inline
- mahavishnu: Task 3.1 report (REQ-005 SessionEnd hook)
- mahavishnu: Trunk-based-agent-review implementation plan
- mahavishnu: Trunk-based-agent-review workflow doc (REQ-008)

### Internal

- mahavishnu: Backfill title: frontmatter for plan-index eligibility
- mahavishnu: Consolidate trunk-based workflow + main branch protection
- mahavishnu: Delete old docs/superpowers/{plans,specs}/ paths
- mahavishnu: Gitignore .superpowers/; untrack scratch state
- mahavishnu: Relocate plans to docs/plans, specs to docs/specs
- mahavishnu: Rewrite 170 in-repo references to new plan/spec paths
- mahavishnu: Untrack archived plans/specs still at old paths
- mahavishnu: Wire SessionEnd hook + cleanups (REQ-006)

## [0.32.0] - 2026-10-03

### Added

- mahavishnu: \_decode_envelope accepts v1.1 flat-fields XADD shape
- mahavishnu: TaskOrphanSweeper consumes task.handoff_orphan events
- mahavishnu: Wire TaskOrphanSweeper into start_server/stop_server + /health

### Changed

- mahavishnu: Tasks_handoff uses publish_task_event_raw dict API

### Documentation

- mahavishnu: V1.1 implementation plan for Bodai task-system addendum
- mahavishnu: V1.1 plan rev2 — fold 2-agent review findings
- mahavishnu: V1.1 spec for Bodai task-system addendum

### Testing

- mahavishnu: TaskOrphanSweeper e2e Redis round-trip + ack verification

### Build

- deps: Drop editable session-buddy redirect, use published 0.31.0
- mahavishnu: Bump session-buddy pin to >=0.31.0 for v1.1 sweeper

### Internal

- mahavishnu: Add minimax_health.sh probe script

## [0.31.0] - 2026-10-02

### Added

- mahavishnu: Tasks_handoff_to_workflow tool (the only dispatch edge — T17)
- mahavishnu: Wire tasks_handoff_to_workflow into MCP server (T18)

### Fixed

- mahavishnu: T16 review NITs — trailing newlines + ruff format cleanup
- mahavishnu: T17 fix round 1 follow-up — drop defensive AssertionError, bare raise is sufficient
- mahavishnu: T17 fix round 1 — ty directive, registration-time gate, typed errors, distinct orphan reasons

### Documentation

- mahavishnu: CLAUDE.md cross-link for task system

### Build

- mahavishnu: Add tasks_handoff_to_workflow feature-flag gate (PR #1 prep)

## [0.30.0] - 2026-09-29

### Added

- mahavishnu: Migrate config loader to Oneiric + OTel ingester pgbouncer plumbing
- mahavishnu: Phase 1 trace pipeline hardening (Task 1.4 + 1.5)
- mahavishnu: Tool selection accuracy test + Phase 2 status flip

### Changed

- Rewire top-10 descriptions — get_active_alerts (Phase 2 Task 2.3)
- Rewire top-10 descriptions — get_log_statistics (Phase 2 Task 2.3)
- Rewire top-10 descriptions — get_monitoring_dashboard (Phase 2 Task 2.3)
- Rewire top-10 descriptions — get_observability_metrics (Phase 2 Task 2.3)
- Rewire top-10 descriptions — get_recovery_metrics (Phase 2 Task 2.3)
- Rewire top-10 descriptions — get_workflow_statistics (Phase 2 Task 2.3)
- Rewire top-10 descriptions — list_adapters (Phase 2 Task 2.3)
- Rewire top-10 descriptions — list_backups (Phase 2 Task 2.3)
- Rewire top-10 descriptions — list_repos (Phase 2 Task 2.3)
- Rewire top-10 descriptions — list_workflows (Phase 2 Task 2.3)

### Fixed

- mahavishnu: Address fast-hook ruff failures (S110/BLE001/F401)
- mahavishnu: Audit script reads selector from metadata.attributes
- mahavishnu: Register telemetry middleware AFTER enrichment middleware
- mahavishnu: Repair YAML frontmatter in 49 tool files
- mahavishnu: Ty unresolved-import suppression on correct line

### Documentation

- mahavishnu: Akosha eval-metric-sink plan — promote to active (Phase 1 shipped)
- mahavishnu: Akosha tool-call feed lifecycle — promote to active
- mahavishnu: Eval-methodology plan — activation-signal override
- mahavishnu: Flip Phase 2 to delivered across both Akosha plans
- mahavishnu: Task-system design spec — Bodai-native TaskCreate replacement
- mahavishnu: Task-system implementation plan v1.1
- mahavishnu: Task-system spec v1.1 — apply 4-lens multi-agent review

### Internal

- Bump Bodai core deps + transitive deps to latest published versions

## [0.29.2] - 2026-09-28

### Added

- mahavishnu: Single-source-of-truth version stamps via importlib.metadata
- mahavishnu: Tool description rubric + structural validator (Phase 2 Task 2.2)
- mahavishnu: Tool-call span enrichment + Akosha-bound OTel attributes
- mahavishnu: Top-N MCP tool audit script (Phase 2 Task 2.1)

### Fixed

- mahavishnu: Phase 1 verification fixes (split gates, real e2e, microbench)
- mahavishnu: Upgrade microbench to exercise real OTel span path

### Documentation

- mahavishnu: Akosha eval-metric-sink follow-on plan
- mahavishnu: Akosha tool-call feed lifecycle follow-on plan
- mahavishnu: Correct akosha pytest paths in Phase A plan
- mahavishnu: Drop paired-PR framing from plans (per bodai-pre-1.0)
- mahavishnu: Phase 0 review revisions to eval fixture proposal
- mahavishnu: Phase 2 partial-progress + plan 2 activation readiness
- mahavishnu: Phase A plan v2 — Task 1 + Task 3 brief revisions after pre-SDD pre-flight
- mahavishnu: Plan 2 fixture list + rubric strategy proposal
- mahavishnu: Plan 2 frontmatter reflects Phase 0 review + Akosha sink blocker
- mahavishnu: Promote tool-surface-quality plan active -> shipped
- mahavishnu: Shared oneiric substrate design spec v4
- mahavishnu: Shared oneiric substrate phase plans A/B/C/D/E1/E2
- mahavishnu: Shared substrate v5 fix pass after 2-agent review

### Testing

- Assert no references to query_cache_l2 after Phase A

### Internal

- mahavishnu: Settings wiring audit + XDG overlay test + PLAN_INDEX regen

## [0.29.1] - 2026-09-27

### Added

- mahavishnu: C-1 config models prep
- mahavishnu: C-10 ecosystem intake (simplified allowlist + sanitize)
- mahavishnu: C-12 executions show CLI
- mahavishnu: C-2 T-0 test scaffolding - 11 wire-up fixtures
- mahavishnu: C-3 event-history + PENDING enum
- mahavishnu: C-4 schema reconciliation
- mahavishnu: C-5 EventBridgePublisher module-global singleton
- mahavishnu: C-6 pool route execute idempotency
- mahavishnu: C-8 worktree isolation
- mahavishnu: C-9 concurrency limits (token-bucket per-category)

### Changed

- mahavishnu: Fix 12 ruff errors + 4 broken doc links (fast hooks)
- mahavishnu: Remove vestigial TaskEventType.SYNCED

### Fixed

- mahavishnu: C-12 recovery — wire executions sub-app into \_main_cli.py
- mahavishnu: C-9 follow-up — rename retry_after= → retry_after_seconds= in PoolManager quota gate
- mahavishnu: Resolve 17 ty errors + 2 creosote issues (comprehensive hooks)
- mahavishnu: Resolve 3 collection-time import errors (baseline)

### Documentation

- mahavishnu: Add .claude/decisions/deployability-discipline.md pointer
- mahavishnu: Add lite-schema frontmatter to deployability-discipline.md pointer
- mahavishnu: Add niche ADR for LLM control plane + repo orchestrator positioning
- mahavishnu: Add required frontmatter to C-10 ecosystem intake plan
- mahavishnu: Downplay Bodai framing in README
- mahavishnu: Expand niche to include multi-engine + harness-agnostic
- mahavishnu: Register port 8695 in BODAI_REPO_REGISTRY + remove PENDING comment
- mahavishnu: Round-5 revisions — fix 12 review blockers across 12 plans
- mahavishnu: Round-5 Tier 4 deliverables — 5 runbooks + 3 SLOs + 2 audit workflows
- mahavishnu: Round-6 Tier 1 corrections — fix runtime bugs in 6 plans
- mahavishnu: Round-7 Tier 2+3 — operational polish + test quality fixes
- mahavishnu: Round-8 Tier 4 — architectural fixes
- mahavishnu: Round-9 Tier 4 — niche ADR citation rate fixed

### Internal

- repo: Remove 30 tracked runtime artifacts + extend gitignore

## [0.29.0] - 2026-09-26

### Added

- Migrate launcher to mcp_common.server.launcher.launch()

### Fixed

- wrapper: Prepend venv site-packages so mcp_common is importable from system python
- wrapper: Use site.addsitedir to process .pth files in venv site-packages

### Documentation

- mahavishnu: Align launcher-discovery frontmatter role with cj twin
- mahavishnu: Phase 4a launcher migration design note (REQ-013)

### Internal

- mahavishnu: Bring .gitignore into Bodai canonical conformance
- mahavishnu: Broken plan links + mdformat/ruff-format hygiene
- mahavishnu: Decommission Dhara from .mcp.json + refresh uv.lock
- MCP launcher migration audit script (REQ-012, REQ-015)
- MCP server migration tracker (REQ-012, REQ-015)

## [0.28.4] - 2026-09-26

### Added

- Add clone-refactor-wireup topic to seed vocabulary
- clone-claims: Cluster_state_claim with in-process lock + ConcurrentDAGError
- clone-tools: Wire clone_refactor_group to git-tree DAG
- git-ops: \_git_ops.py with typed GitCommit\* exceptions (REQ-CLONE-013)
- mahavishnu: Wire pgvector OTel storage + Postgres 16/17/18 CI matrix
- pools: Add pool_route_execute MCP tool (Plan v3 Phase 2m)
- state-backends: Add dag_key/cluster_key/in_flight_key + try_put_with_log_context
- workflows: Rewrite clone_refactor_workflow.py as git-tree DAG

### Changed

- Atomic migration workers/task_router.py -> core/model_routing.py (Phase 3b)
- Clone-refactor + session-buddy + worker leftovers from prior session
- clone_claims: Drop redundant trailing return (refurb FURB125)
- clone_tools: Extract verification-gate + cleanup helpers from clone_refactor_group
- Close WorkerStatus stragglers in execute_fn_factory.py (Phase 5b)
- mahavishnu: Re-export canonical AgentMetadata/SkillMetadata aliases (Phase 10 task 4)
- session_buddy_pool: Extract pool_id/working_dirs/stitch helpers from execute_batch
- workers: Narrow \_create_isolated_worker to shepherd-only (Phase 4)
- workers: Retire legacy isolated-worker surface (Phase 4.5b)
- workers: Single-dispatch worker factory via \_create_isolated_worker

### Fixed

- bootstrap: Make pool init real bugs visible (Plan v3 Phase 1m)
- clone-tools: Address multi-agent review's CRITICAL findings
- clone_tools: Restore REJECT-path observability log
- docs: Resolve 12 frontmatter validation errors (status/role/date/topic)
- git-ops: Add coverage for GitCommandTimeout, StashPopFailed, signal exit paths
- git-ops: Apply Error suffix to \_git_ops exception classes (N818)
- git-ops: Move pathlib.Path annotation into TYPE_CHECKING (TC003)
- pool_tools: Guard RateLimitError catch against defensive-import sentinel
- pools: SessionBuddyPool re-pointed at structured pool tools
- workflows: Silence Prefect AsyncMock warnings + add REQ-CLONE-016 cancellation test

### Documentation

- adr: Re-evaluate LangGraph as engine adapter (Phase 6)
- CloudWorker retirement decision — KEEP
- drift: Migrate 10 task_router refs + retire 2 stale worker trackers + fix pool ASCII
- feature-tracking: Record Task 1 P0 probe — substrate unreachable, deferred
- plan: Clone-refactor wire-up v2 — review-pass feedback applied
- plan: Clone-refactor wire-up v3 — re-review sweep applied
- plan: Clone-refactor wire-up v4 — final review pass sweep applied
- plans: Add Phase 0 inventory lock for orchestrator fix
- Pool + worker MCP tool audit (Plan §10 #1, #2, #5)
- pools: Substrate-wrapper rationale + Plan §10 #5 resolution (v4)
- portfolio: Retire D-AUDIT and update D-OBJ-SCHEMA scope (Wave 2 follow-up)
- Refine LangGraph ADR with §10 follow-up evidence (same-day refresh)
- spec: Clone-refactor wire-up + dispatch_to_pool env-failure design (v1)
- spec: Clone-refactor wire-up design (v2) — multi-reviewer feedback applied
- spec: Clone-refactor wire-up design (v3) — final-review-pass feedback applied
- spec: Clone-refactor wire-up design (v4) — sanity-check fixes

### Testing

- workers: Pin retired-worker_type ValueError contract

### Internal

- clone-tools: Post-wireup polish
- lint: Silence S110/N818 fast-hook findings in MCPStateBackend
- Remove .github/workflows/ci.yml (Bodai uses crackerjack per feedback-bodai-no-provider-specific-ci.md)

## [0.28.2] - 2026-09-24

### Documentation

- plans: Add audit gate after Task 9 (docs commit)
- plans: Add audit gates after source-code tasks (1, 4, 5, 6, 7)
- plans: Add jinja2-custom-delimiters 1.0.4 implementation plan
- plans: Apply CRITICAL fixes from 5-agent plan review
- plans: Apply remaining HIGH/CRITICAL fixes from 5-agent review
- specs: Add jinja2-custom-delimiters 1.0.4 update design
- specs: Revise jinja2-custom-delimiters 1.0.4 design after 5-agent review

## [0.28.1] - 2026-09-21

### Fixed

- mcp: Register ecosystem_publish_url on LEGACY CLI path

### Internal

- registry: Onboard cmux-mcp; regen surfaces pre-existing flowscape entry

## [0.28.0] - 2026-09-20

### Added

- acp: Add error types + bearer auth gate (sub-commit 2.A)
- acp: Add EventBridge-to-SessionUpdate synthesizer (sub-commit 1.2)
- acp: Add execute_fn factory + fix A2A Bearer comparison (Phase 1.5)
- acp: Add OTel session span + observability validation test (sub-commit 2.C)
- acp: Add Pydantic wire-format protocol models + spec-name drift gate
- acp: Add stdio JSON-RPC 2.0 dispatcher core (sub-commit 2.B)
- acp: Emit tool_call lifecycle envelopes from worker boundaries (sub-commit 1.3)
- acp: Wire MahavishnuApp into dispatcher execute_fn (Phase 1.5 close)
- Add /jot drain slash command (polish item 1)
- Add `mahavishnu acp serve` CLI surface (sub-commit 2.D)
- ecosystem: Add publish: block to mdinject, flowscape, splashstand
- jot: Reject unknown ctx keys in \_validate_ctx (polish item 3)
- mcp: Add mahavishnu_get_publish_url sibling-tool for crackerjack probe

### Changed

- acp-cli: Use build_execute_fn from Phase 1.5 factory
- factory: Promote execute_fn settings to real Pydantic fields (Option C)
- jot: Lock \_propose_action policy at §3.3.4 (polish item 5)

### Fixed

- acp: Bypass connect_write_pipe via os.write + e2e scaffolding
- acp: Propagate async through dispatch chain (session/prompt works)
- acp: Thread-based stdin feeder + pre-flight validation (Path A+B)
- Defer help_cli import to avoid known-broken module-load hang
- e2e: Unblock ACP integration timeouts + fix pre-existing test bugs
- jot: Reconciler auto-retry is fire-and-forget (polish item 2 code)
- lint+types: Clear crackerjack comprehensive hook findings
- lint: Silence legitimate best-effort exceptions + min() cleanup
- Warm-up vs failed state for /health aggregator (launchd race)

### Documentation

- acp: Add operator usage guide + doc-staleness detector (Phase 3a)
- acp: Flip v1.0 plan to active + followup trigger audit (operator signoff 2026-09-19)
- Add Toad row to THIRD_PARTY_NOTICES.md (Phase 3b)
- decisions: Record SDD bundling defensive pattern (polish item 4)
- followups: Close audit-orphans-residual-caller-detection
- jot: Action_proposals docstring + MCP spec sync (polish item 6)
- jot: Flip polish plan + design spec status to complete

### Testing

- acp: Add Hypothesis property tests for protocol + synthesizer (sub-commit 1.4)
- jot: Adversarial tests for reconciler auto-retry (polish item 2 tests)

### Internal

- deps: Catch up uv.lock to in-tree version bump (0.26 → 0.27)
- followups: Drop stale HEAD tracking of audit-orphans followup

## [0.27.0] - 2026-09-19

### Added

- pools: Wrap SessionBuddyPool worker_execute with subagent marker

### Documentation

- Open cross-repo followup for sb subagent lockfile producer
- plan: Promote acp-v15.6 license reconciliation to Resolved Items

### Testing

- jot: Lift drain.py coverage to 97.34% via test_drain_error_paths

## [0.26.0] - 2026-09-19

### Added

- lock-sentinel: Replace dhara.lock with local in-process Lock
- mcp/tools: Add 5 ecosystem_state tools (Phase 3 of Dhara decomposition)
- persistence: Vendor WorkflowOutcome/ApprovalLog/WebhookIngress locally

### Changed

- dhara-schema: Replace dhara.schema.\* imports with local msgspec types
- mahavishnu: Subclass oneiric's OTelStorageSettings instead of duplicating it
- substrate-compat: Drop stamp_dhara_attr helper
- substrate-compat: Lazy-load dhara; drop bare 'import dhara' from producers
- Use oneiric.core.ulid directly, drop dhara fallback chain

### Fixed

- Add 'metrics bodai' subcommand for queue-file rendering
- bootstrap: Thread skills_signer+agents+dispatch+jot through legacy path
- docs: Update CLAUDE.md/README.md tool-count claims to match registry
- engines/agno_adapter: Resolve mypy syntax error at line 169
- mcp/bootstrap: Thread rbac_manager to 4 register\_\*\_tools callsites
- otel_ingester: Catch \_get_client failures in check_available
- qc: Re-add module-level httpx attribute for test patching
- session/checkpoint: Catch httpx transport errors in is_healthy
- session/checkpoint: Repair test mocks for CommonMCPClient migration
- test-residue: Wire 5 production drift sites (Cluster 10 Item 5)
- tests: Align AgnoToolsConfig default URL with mahavishnu port
- tests: Align otel_ingester mocks with post-Phase 3 CommonMCPClient API
- tests: Assert MINIMAL profile registers health + skills_signer
- tests: Migrate MCPThinClient mocks from post() to call_tool()
- tests: Migrate test_qc_checker to call_tool AsyncMock
- tests: Mock MCP call_tool instead of HTTP post in chaos buffer test
- tests: Mock RBAC manager in session_buddy_tools test fixture
- tests: Patch oneiric DuckdbHotStore in TestInitializeDuckDB
- tests: Pin crow call site line numbers to current source
- tests: Regen profile fixtures via production build entry point
- tests: Skip dead bodai event-bridge helper test
- tests: Sync ecosystem.yaml with legacy repos.yaml (add www-mcp-servers)
- Wire jot dispatcher through FastMCP, not FastMCPServer wrapper

### Documentation

- adr: Evaluate gateway pattern (Options A/B/C) for Bodai MCP surface
- flowscape: Enrich plan + spec with Phase 4 proto schema pre-reqs
- Mark Phase 8 dhara retirement plan complete; regenerate PLAN_INDEX
- MCP registrar implementation plan (11 tasks)
- plan: Revision 1 — apply 27 findings from 5-agent review
- plan: Revision 2 — apply 5-agent re-review findings
- plan: Switch status from draft to active
- plans: Commit Phase 8 dhara retirement plan as historical record
- registry: Add chat-bridge-mcp to Bodai MCP servers table
- registry: Update chat-bridge-mcp row to reflect v0.1.0 status (T34)
- Remove Dhara references from CLAUDE.md + README.md (Phase 8 T16)
- spec: Draft MCP registrar design — canonical YAML emits .mcp.json + ~/.qwen/settings.json
- spec: Revision 1 — fold 5-reviewer task-force findings + verify Qwen schema via context7

### Testing

- agno+auth: Restore cluster 6+7 working-tree fixes
- bootstrap: Capture loguru warning via capsys instead of caplog
- bootstrap: Init signer+plan_index feeds before /health assertion
- cleanup: Delete test_substrate_compat_enforcement (tests dead helper)
- cluster-10: Align 7 stale test invariants to current production
- Drop dhara.schema stub machinery from 2 webhook tests; fix stale docstring
- fixtures: Regenerate FULL golden fixture to current production
- lifecycle,wiring: Fix stub + regenerate golden fixtures
- mcp/tools: Supply fake rbac_manager to capability tool tests (W5 Cluster 1)
- mcp/tools: Supply fake rbac_manager to webhook/workflow tool tests
- profiles: Align MINIMAL + jot\_\* invariants to Phase 1.5/3 canonical
- profiles: Cover REGISTRATION_MAP as canonical W0 dispatch surface
- server_core: Check OTel tracing middleware by type, not call count
- Supply fake rbac_manager to channel_session tool tests (W5 Cluster 2)
- tools: Supply fake rbac_manager to git_analytics tool tests (W5 Cluster 4)

### Build

- deps: Drop dhara dep from ecosystem extras (Phase 8 T10)
- deps: Unlock mcp-common to >=0.27.0
- uv.lock: Refresh after oneiric dep removal (Phase 8 T10 follow-up)

## [0.25.0] - 2026-09-16

### Added

- mahavishnu: 11 Qwen-only event handlers (Phase 12b task 1)
- mahavishnu: Add bus dependency-group with coredis
- mahavishnu: Augment 6 Claude hooks with bridge routing (Phase 12a Task 2)
- mahavishnu: Canonical hook bridge handler (Phase 12a Task 1)
- mahavishnu: Git-hook Typer subcommand (Phase 12a Task 3)
- mahavishnu: Hard-cutover PostToolUse hook JSON-queue → bus XREAD (Phase 12a Task 5 partial)
- mahavishnu: Install-bodai-git-hooks.sh operator script (Phase 12a Task 4)
- mahavishnu: Qwen bridge e2e + operator runbook (Phase 12b tasks 2+3+4)
- mahavishnu: Retire bodai-activity daemon + metrics bodai CLI (Phase 12a Task 5 final)
- mahavishnu: Wire Phase 4 health aggregator (Plan §4 + §5 task 7 + §11.4)

### Fixed

- mahavishnu: Address 3 critical + 2 high findings from multi-agent review
- mahavishnu: Bridge publishes to bodai:events stream + single-coroutine init/publish
- mahavishnu: Drop non-existent MiniMax-M3-highspeed model name
- mahavishnu: Handle async publish in bodai_hook_bridge + redirect oneiric to local path
- mahavishnu: Read_bodai_events_since per-entry decode resilience

### Documentation

- mahavishnu: Retire stale bodai-event-queue.json references (Phase 12a task 7)
- Refresh BODAI_REPO_REGISTRY.md to current regen output
- spec+test: Point Phase 4 health references at mcp-common canonical home

### Testing

- mahavishnu: Fix hook command parser to honour $CLAUDE_PROJECT_DIR
- mahavishnu: Full bridge e2e suite (Phase 12a task 6)

### Internal

- Sync uv.lock to 0.24.2 (lockfile lagged behind the 5ab9e780 version bump)

## [0.24.2] - 2026-09-15

### Documentation

- mahavishnu: Add health-reason-codes runbook + PromQL alerts

## [0.24.1] - 2026-09-15

### Fixed

- spec+plan: Apply critical-audit findings to Phase 12 (4 CRITICAL + 7 HIGH)

### Documentation

- spec: Link crackerjack-side followup from Phase 8 cross-repo coordination

## [0.24.0] - 2026-09-14

### Added

- /jot slash command (vitals only per R6)
- Add JotSummaryDict/JotVitalsDict surfaces + \_summary_dict/\_vitals_dict
- audit: Cross-module __all__ resolution + tests
- audit: Recognise @pytest.fixture as a registration decorator
- audit: Treat pytest-discoverable tests/ symbols as wired (Phase 5 loop-3)
- auth: FastMCP session-context user_id extraction (Task 11.9)
- Auto-generate BODAI_REPO_REGISTRY.md from canonical sources
- changepoint: Add TwoStageDetector (warn/confirm) + config fields
- changepoint: Wire TwoStageDetector into ObservabilityManager; emit drift_warning span
- cleanup: Delete unused record_key + triage remaining audit orphans
- cli: `mahavishnu plan` subcommand (list/show/vitals/search/purge)
- config: Add JotSettings nested under MahavishnuSettings
- jot-cli: Add 6 drain subcommand handlers + smoke tests
- jot-cli: Register 6 drain subcommands with Typer
- jot-drain: Add Task 8 — surfacing scorers + throttle + surface_relevant
- jot-mcp: Add 6 drain tools + remove duplicate JotSummaryDict/JotVitalsDict
- jot: 8 MCP tools with TypedDict returns (R1, R11)
- jot: Add \_auto_retry_after, \_reconcile_if_in_flight, \_background_reconciler_loop
- jot: Add \_is_surface_eligible, \_is_drain_eligible, \_should_exhaust_retry_budget
- jot: Build_states two-pass fold with parking (R3, R7 part 2)
- jot: Capture sub-plan 1 — hook + log + redaction
- jot: CLI handlers — list, show, vitals + write stubs
- jot: Cmd_search lexical substring fallback
- jot: Drain refactor + cli/hook/mcp-tools alignment + errors rename
- jot: Drain.py skeleton with \_append_event + TypedDict validation
- jot: Extend errors.py with drain error hierarchy
- jot: Extend fold with \_derive_dispatch_fields + DispatchState
- jot: Extend Op literal with 6 drain event types
- jot: FoldResult + parse_events (TD-B3, R7 part 1)
- jot: Git enrichment via subprocess (R4)
- jot: Register 8 tools in profiles + CI guards
- jot: Render layer (list, show, vitals)
- jot: Resolve_handle with ambiguity error (R8)
- jot: Typer app with 8 subcommands (R2)
- jot: Wire per-op TypedDicts via MCP-tools import
- jot: Write CLI handler tests for done/reopen/edit/add
- JotError hierarchy (TD-B2)
- mahavishnu: Flip otel_ingester HotStore forward-ref to Oneiric Protocol
- mahavishnu: Flip otel_ingester runtime HotStore to Oneiric DuckdbHotStore
- mahavishnu: Migrate to mcp-common CommonMCPClient (Phase 3 REQ-004, REQ-009)
- mcp-profiles: Register 6 drain tool names in FULL + REGISTRATION_MAP
- mcp: Agent catalog + tool consolidation
- mcp: Phase 1 server-published skills (list_skills + get_skill)
- mcp: Phase 3 task #5 H-3 specialist dispatcher
- mcp: Register plan\_\* tools in FULL profile (5-edit dance)
- observability: Changepoint detectors (CUSUM + 3-sigma) + integration
- observability: Close merge.semantic.duration_ms instrumentation across all 3 entry points
- observability: Ship changepoint operator opt-in (finish-partial Phase 1)
- permissions: Add READ_PLAN_INDEX for plan_index MCP tools
- Plan\_\* tools with @require_mcp_auth (REQ-PLAN-010)
- plan_index,health: Wire plan_index feed into /health aggregator
- plan_index: Foundation — PlanId, errors hierarchy, paths
- plan_index: Normalize_repo_url security helper
- plan_index: PeriodicTaskRunner + cron_core + lock + DLQ (round-3 BLOCKER fix)
- plan_index: PlanIndexFeedState with strict 4-signal contract
- plan_index: PlanIndexRebuilder with normalize_repo_url integration
- plan_index: PlanIndexStore Dhara-backed CRUD with vitals
- plan_index: PlanRecord frozen dataclass
- plan_index: Renderer (pure) + Writer (I/O)
- plan_index: TypedDicts — plan surface types
- pools: Drop dead QueueingScorer class (round-4 general/safety HIGH-1)
- quality_cli: Wire Rich-formatted Crackerjack output (track3-toad-tui Task 4)
- Regenerate_plan_index.py orchestrator + fix discover_records field gap
- Register plan_app in main CLI app
- scripts: Add migrate_frontmatter migrator (Phase 1 of no-frontmatter migration plan)
- settle: Register merge.semantic.duration_ms histogram + thread mergiraf path
- skills_signer: Phase 1.5 replication to mahavishnu
- state_backends: Add DharaKv string-shape adapter for PlanIndexStore
- Task 9 — high-level drain primitives (drain_plan, dispatch_jot, retry_dispatch, defer_jot, delete_jot)
- tier1-math: Phase 1 — MmcQueue queueing library (REQ-001)
- tier1-math: Phase 2 — QueueingScorer + PoolManager integration (REQ-002, REQ-003, REQ-008)
- tier1-math: Phase 3 + 7 — integration tests + validation reports
- tier1-math: Phase 4 + 8 — promote queueing + changepoint defaults (adopted)
- tier1-math: Phase 5 — CUSUM, Page-Hinkley, AnomalyResult (REQ-004, REQ-006)
- tier1-math: Phase 6 — change-point observability integration (REQ-005, REQ-006, REQ-009)
- tier1-math: Phase 9 — feature eligibility script + Makefile + followups (REQ-007)

### Changed

- core: App/health/cli alignment + health CLI test scaffold
- jot-drain: Apply 14 reviewer findings to polish spec
- jot-drain: Polish implementation plan — 7 tasks
- jot-drain: Polish spec — 6 items (slash command, reconciler revert, ctx whitelist, bundling note, action-proposal lock, action_proposals docs)
- jot: 20-task implementation plan for zero-turn inbox
- jot: Add noqa for fail-open Exception catches + B023 fix
- jot: Apply 5-agent review fixes (round 1)
- jot: Apply 5-agent round-3 review findings
- jot: Apply final-review critical fix batch (round 2)
- jot: Apply user-approved cuts and round-2 self-fixes
- jot: Type \_summary_dict/\_detail_dict; strengthen MCP round-trip test
- observability: Extract \_canonical_detector_name helper to remove detector-name normalization duplication
- observability: Use elif in two-stage dispatch for mutually exclusive states
- skills_signer: Minor alignment across keys/manifest/verify

### Fixed

- auth: Add required_permission to 5 session_buddy decorators (Task 11.8)
- auth: Defense-in-depth audit + remove Permission.READ fallback (Task 11.10)
- auth: Thread rbac_manager through capability_tools (Task 11.8)
- auth: Thread rbac_manager through webhook_tools (Task 11.8)
- auth: Thread rbac_manager through workflow_tools (Task 11.8)
- auth: Wire rbac_manager at 5 bootstrap.py callsites (Task 11.8)
- config: Correct Crow port and MCP server URL defaults
- docs(plans)+audit: Phase 5 loop-2 (audit script fix, plan move, revert to partial)
- docs+test(changepoint): round-6 fixes per task-7 review (default-detector drift + test count + drift_warning span parity)
- jot-drain: Thread jot id through \_append_event + restore DrainPlan.action_proposals
- jot: Add noqa for PLC3002 IIFE lambda workaround
- jot: Clamp replayed last_modified_ms + clear parked + I3 tests
- jot: Make \_wrap_at_import graceful when fastmcp is not installed
- jot: Remove dead MOD_WIDTH constant from render.py
- jot: Remove extraneous parens around min() generator (ruff UP034)
- jot: Thread event_id through CLI edit/done/reopen (latent no-op bug)
- jot: UD5 short_id is last 6 hex chars (was first 6)
- jot: Widen enrich_ctx catch + hoist git spawn (Task 5 fix round 1)
- mcp/lifecycle: Wire MCPKvClient into plan_index, drop synthetic fallback
- observability: Add severity= and samples= to drift_warning log for parity with drift_detected
- otel_ingester: Normalise \_extract_timestamp to naive UTC
- plan_index,auth: Enforce READ_PLAN_INDEX via RBACManager (BLOCKER Task 11.7)
- plan_index: Atomic lock acquisition in cron_core (Task 14.6)
- plan_index: Atomic writes, JSON parse safety, prefix validation, TTL consistency
- plan_index: Reject Unicode line/paragraph separators in normalize_repo_url
- plan_index: Restore Task 16 orphaned files (check_step8 + tracking)
- plan_index: Retain lock-history on stale takeover (Task 14.7)
- plans: Wrap bare blocks_on string in list (2026-09-13)
- Preserve epoch-zero oldest_ms in jot_vitals (collapses-with-or-None bug)
- Report latest HLC (not capture HLC) in JotDetail per spec R9
- round5-followup: Add --section flag to mahavishnu health for merge_driver
- spec: Resolve 6-agent review criticals — phantom APIs, JSON bool retry flag, TypedDicts, hook wiring, error handling
- spec: Resolve round-2 6-agent re-review criticals + importants
- spec: Resolve round-3 5-agent re-review defects
- tier1-round2: Address CR-1, CR-2, S-1, S-4, S-5, S-6, CAL-1, CAL-2
- tier1-round2: Doc honesty + allowlist hardening (security review)
- tier1-round3: Address R3-C1+C2, M-1, H5, CR-1/CR-2 test
- tier1-round3: Correct stale doc numbers (R3-DOCS)
- tier1-round4-final: Monotonic drift_age gauge + M5 label allowlist route + audit doc test count
- tier1-round4: Close two CRITICALs + M2 regression test
- tier1-round5: Close deferred M#/m# findings from settle-semantic-merge review
- tier1: Pair arrivals with real service durations (was placeholder 1.0)
- tier1: Promote changepoint config to top-level ChangepointConfig
- tier1: Target_mean config + drift counter + complete OTel span attrs
- tier1: Track inter-arrival timestamps against last arrival, not last fit
- tier1: Wire QueueingScorer penalty into actual pool selection
- tier1: §7 gate test now actually measures (was vacuous)

### Documentation

- Add frontmatter to jot-drain-polish plan (mark active)
- Add jot capture implementation plan (9 tasks)
- Archive 19 completed plans (2026-09-13)
- audit: Correct changepoint test count to 115 across 8 files (post-F10 dispatch seam test)
- changepoint: Document warn re-fire updates \_last_warning_result in TwoStageDetector state diagram
- decisions: Tag 38 decision docs with kind: decision (2026-09-13)
- Dhara MCP decomposition implementation plan with Phase 12 hook coordination
- Drop Codex from Phase 11; consolidate ACP with active plan
- feature-tracking: Cross-link Phase 8 promotion as the two-stage migration window
- feature-tracking: Document round-7 polish knockouts (10 LOW items + bundle-split recovery)
- feature-tracking: Flip orphan-sweep to status: wired (5/5 resolved)
- feature-tracking: Flip status to wired; document round-6 shipped
- Flip 2026-09-13 migrate-no-frontmatter-plans to status: complete
- followups: Park 11 LOW polish items from changepoint two-stage review (round-7/8)
- followups: Record HNSW-on-DuckDB bug for akosha code_graphs_feed
- Implementation plan for plan-index Dhara canonical layer
- Jot inbox design spec (post six-lens review)
- jot: Apply all BLOCKERs + HIGHs from multi-subagent review of sub-plan 2
- jot: Sub-plan 2 (Read) implementation plan
- Lifecycle ADRs, ARCHITECTURE refresh, version stamps, LLM provider
- MCP: Regenerate tools reference and specification from source
- observability: Note defensive isinstance guard rationale in \_on_drift_warning
- plan+runbook+audit: Document two-stage warn/confirm architecture (round-5)
- plan: Add Phase 11 harness-agnostic enablement + ACP integration
- plan: Add phase-1 precondition fixes (14 deferred findings)
- plan: Add §10.4 cross-server review + update §10.1/§10.2/§11 to 5/5 complete
- plan: Add §10.5 Phase 1 cross-server review + completion markers
- plan: Correct changepoint test count to 115 across 8 files
- plan: D2 reviewer fixes — §10.3 wiring contract + stale-path corrections
- plan: Promote skill-agent-distribution to active, close B-1
- plan: V3 — cron real-scan + --render-to flag + 5 security tests
- plan: §10.2 — mark Phase 2 + Phase 6 SHIPPED + update Week 4/5/6 sub-lists
- plan: §10.2 — mark Phase 3 dispatcher + Phase 5 SHIPPED
- plan: §10.6 — Phase 3+4+6 cross-server review with str_strip_whitespace fix entries
- plans: 2026-09-12 plan audit pass
- plans: 2026-09-13 overlap-followup fixes
- plans: 3 PARTIAL status flips + Re-Review notes (2026-09-13)
- plans: 6 status flips from completeness audit (2026-09-13)
- plans: Add CommonMCPClient transport unification umbrella plan
- plans: Add frontmatter to bodai-tui-shell-surface-implementation (2026-09-13)
- plans: Add frontmatter to fastmcp-4-upgrade + cross-link to Cluster A (2026-09-13)
- plans: Add Phase Status table to finish-partial-implementations
- plans: Auth → complete; bump 6 last_reviewed; flip Cluster A 4 → complete (2026-09-13)
- plans: Close routing-feedback-loop-v4 partial — query_local_traces now ships on all 5 Bodai components
- plans: Create plan for migrating 40 no-frontmatter files (2026-09-13)
- plans: Cross-link TUI/storage clusters; defer flowscape + zsh (2026-09-13)
- plans: Drop HotStore JSON-path bug caveat — fixed upstream in Akosha 9845c5c
- plans: Finish-partial Phase 5 (post-close audit) + plan → complete
- plans: Fix broken local links surfaced by check-local-links
- plans: Flip 2026-05-14-doc-sync-and-channel-phase2 to status: complete
- plans: Flip 2026-06-19-track3-toad-tui to status: complete
- plans: Flip 2026-07-11-ultracode-integration-wiring to status: complete
- plans: Flip 2026-07-16-bodai-plugin-standardization to status: complete (path-not-taken)
- plans: Flip 2026-08-24-claude-env-audit-remediation to status: complete
- plans: Flip 2026-09-10-bodai-math-initiatives-tier1 to status: shipped (finish-partial Phase 4)
- plans: Flip 2026-09-10-settle-semantic-merge to status: shipped
- plans: Flip dhara-outstanding-items-plan to status: complete
- plans: Flip finish-partial meta-plan to status: complete
- plans: Flip track3-toad-tui draft -> active; regen index (2026-09-13)
- plans: Reflow 9 single-line-after-heading frontmatter blocks (2026-09-13)
- plans: Refresh 2026-09-13 no-frontmatter migration plan with live inventory
- plans: Refresh migration plan for +1 file drift (38 -> 39)
- plans: Regen PLAN_INDEX.md to reflect 2026-09-14 plan state
- plans: Regenerate PLAN_INDEX after 6 status flips (2026-09-13)
- plans: Regenerate PLAN_INDEX after dhara-outstanding-items-plan flip to complete
- plans: Regenerate PLAN_INDEX after kind: decision + reflows (2026-09-13)
- plans: Regenerate PLAN_INDEX.md — includes jot-drain-polish (active)
- plans: Render kind column + add by-kind section to PLAN_INDEX (2026-09-13)
- plans: Update decision-kind description to cover ADRs (2026-09-13)
- plans: Update tier1-math inline text + regenerate PLAN_INDEX
- plans: V2 — review fixes for transport unification plan
- Promote serverless-readiness plan to active + ADR 017
- Re-review 8 stale plans (last_reviewed: 2026-07-16 -> 2026-09-13)
- Refresh canonical reference docs against current codebase
- Refresh references + math-spec audits + archive metadata
- registry: Add scapy-mcp, archive-org-mcp, medium-mcp
- Relocate stray session PNGs to docs/assets/images/.scratch/
- runbook: Add healthy drift_warning_total rate heuristic (~30 per 10,080 design point)
- runbook: Explain detector attribute dual-convention for two-stage warn/confirm spans
- schemas: Add optional kind discriminator to frontmatter v1.1 (2026-09-13)
- scripts: Migrate 1 docs/followups/ to v1 schema
- scripts: Migrate 1 docs/plans/ to v1 schema
- scripts: Migrate 15 docs/superpowers/specs/ to v1 schema
- scripts: Migrate 22 docs/superpowers/plans/ to v1 schema
- spec+plan: Apply multi-agent review fixes (PATH A)
- spec: Add jot inbox capture sub-plan 1 design
- spec: Add jot inbox drain sub-plan 3 design
- spec: Add jot inbox read sub-plan 2 design
- spec: Add §4.13 + Phase 12 hook bus coordination
- spec: Apply review fixes to Dhara MCP decomposition design
- spec: Apply second-pass review fixes (3 fresh agents)
- spec: Draft Dhara MCP decomposition design
- spec: Incorporate topology + Postgres consolidation review
- spec: Plan-index Dhara canonical metadata layer (v2, pentaverate-revised)
- spec: Plan-index Dhara canonical metadata layer (v3, round-2 fixes)
- specs: Flip 2026-05-16-llm-routing-standardization-design to complete+superseded
- specs: Flip 2026-07-15-constellation-tui-design to complete
- Update capture plan to reflect post-review implementation
- Update capture plan to reflect post-review implementation
- V2 — apply 4-agent plan review fixes

### Testing

- audit: Cover cross-module __all__ resolution
- auth: Add cross-cutting RBAC sweep tests (Task 11.8)
- auth: Cover Principal.has_scope
- changepoint: Add boundary-sample test for confirm firing on confirm_window_samples-th sample
- changepoint: Integration benchmark for TwoStageDetector; bench.json keys for §1/§7
- CI gate integration coverage
- cleanup: Remove contradictory stale_pid test + fix auth test for new fail-fast contract
- Cover CrossRepoAggregator.get_repos_needing_attention
- Cover MahavishnuApp budget_watchdog lifecycle methods
- dhara_kv: Cover MCPKvClient contract + cron int(dict) reproducer
- distill,precommitment: Skip cleanly at collection when duckdb is missing
- E2e scaffolds for agents + settle-merge + agent metadata schema
- Fix mypy strict on test_audit_plan_index.py:179 (REQ-PLAN-009)
- jot-drain: Property tests for idempotency, state invariants, surfacing ranking
- jot: Add return-type Any check to test_no_any.py
- jot: End-to-end pipeline integration tests
- jot: End-to-end pipeline integration tests
- jot: Update capture_echo tests for UD5 last-6 short_id
- mcp: Per-tool e2e + smoke tests for plan_index (REQ-PLAN-013)
- plan_index: Concurrency, DLQ, OTel flag, lock format, /health aggregation
- plan_index: Golden render + feature-tracking + partial failure + dict roundtrip
- plan_index: Round-2 security & auth-gate test coverage (REQ-PLAN-010/011/012)
- pools: Drop dead TestQueueingScorer coverage (general/safety HIGH-1)
- websocket: Cover broadcast_settle_transition in parametrized suite
- wiring: Close 3 demo unsubscribe\_\* orphans via Attribute reference
- wiring: Close audit_orphans findings for 7 residual symbols
- wiring: Use Attribute access so audit walker counts the references

### Internal

- Bump to v0.23.0 and correct tool/repo counts
- deps: Bump mcp-common floor to >=0.26.0,\<0.27.0 (Phase 2.5)
- jot: Trivial docstring/comment typo + trailing newline fixes
- Maintenance + audit-apply scripts
- plan_index: Maintenance scripts + module touch-ups
- plan_index: Migration run steps 1-5 (operator runbook + scripts)
- plan_index: Migration step 6 complete — MCP tools wired
- plan_index: Migration steps 7-8 — skill cut-over + adopted

## [0.23.0] - 2026-09-09

### Added

- cli: Add mahavishnu worktree scan + tests
- decisions: Add worktree-cleanup-policy + 4 back-links
- decisions: Add worktree-cleanup-policy decision doc (skeleton)
- Instrument scan_worktrees with OTel counter + histogram + INFO log (F-QA-4/5/6)
- skills: Add bodai-worktree-cleanup skill wrapper

### Changed

- worktree-scan: Drop cyclomatic complexity under 15 in \_format_text + scan_worktrees_cli

### Fixed

- Exit 1 on driver-level scan failures + 4 new CLI tests
- plan-index: Drop 4 entries for files deleted in 561d9d2a refactor
- plan-index: Strip stale 'fix-search-tools-wiring-v2/' worktree prefix from 264 links
- scan: Drop 5 dead CLI flags + unused safe_worktree_name + slow markers
- scan: Wrap \_run_ps identity check in TimeoutExpired handler
- spec: Quote YAML frontmatter values containing ': ' (crackerjack parse)
- Wire repos_scanned counter to actual successful repo count (L4)
- worktree-cli: Drop redundant cast() in \_scan_validate_output_format

### Documentation

- Add worktree-cleanup implementation plan (3 commits)
- plan: Post-review amendments (F1-F50)
- spec: Add worktree-cleanup-policy design (post 4-agent review)
- spec: Worktree-cleanup-policy post-QA amendments (A52-A74)

### Testing

- cli: Tighten vacuous assertions + index decision doc + trailing newline
- scan: Add 8 \_format_text section tests (F-QA-12) + restore L4 tests
- scan: Add \_group_plan_orphans 4-test coverage set (F-QA-14)
- skill: Add 3 trigger-phrase + wrapper smoke tests (F-QA-15)

## [0.22.0] - 2026-09-07

### Changed

- 7-agent review of mcp-common auth primitives plan — 12 distinct BLOCKERs
- Amend mcp-common auth primitives design per 7-agent review
- auth: Fix 12 BLOCKERs + cross-cutting IMPORTANTs from 7-agent review
- Mcp-common auth primitives design — middleware, IdentityProvider, AuthHealth
- Mcp-common auth primitives — 17-task implementation plan

### Fixed

- plan+spec: Apply Round 2 multi-agent review fixes (BLOCKER + IMPORTANT + selective MINOR)
- plan+spec: Close 3 spec drift + 2 plan consistency issues from final pass

### Documentation

- adr: 0016 v4 — close mcp-common authentication primitives deferred item
- gdpr: Remove 'when designed' leftover in §10 + correct header-access description
- gdpr: §10 — describe auth posture and Article 32 alignment
- plan-index: Regenerate after auth primitives execution

### Internal

- gitignore: Apply Bodai canonical snippet

## [0.21.0] - 2026-09-06

### Added

- adr-0016: V2 revision + plan mirror
- adr-0016: V3 revision closes CB-3/4/5
- decisions: Amend wiring discipline policy with §7 consumer-side aggregation
- mahavishnu: Complete orphan sweep (settle CLI + CloudWorker re-export)
- registry: Add orb role; assert roles are in taxonomy
- registry: Migrate 24 stranded repos into canonical manifest
- registry: Register archive-org-mcp, medium-mcp, scapy-mcp
- scapy-mcp: Feed registry (3 required, 2 optional) and wiring-discipline signals

### Changed

- mahavishnu: Remove orphan terminal/backends.py and grid module

### Fixed

- Add trailing newlines to 15 coverage test files
- Importorskip/skipif for missing optional deps in integration tests
- repo-cli: Read canonical ecosystem.yaml, not legacy repos.yaml
- scripts: Audit_orphans detects FastAPI route decorators
- Update test_crow_call_site_wiring.py for current TerminalManager.create call sites

### Documentation

- CLAUDE.md: Add MCP backend wiring discipline cross-reference
- cleanup: F1+F2+F5 follow-ups from scripts/examples coverage plan
- decisions: Add MCP backend wiring discipline rule
- decisions: Mark test-matrix-review-followups complete (verified 2026-09-06)
- feature-tracking: Flip m-workflow-outcome from built back to wired
- followups: Audit sibling repos.yaml files in crackerjack and mcp-common
- followups: Close integration-test blockers (9 of 13) and ACP v1.5.6 (license)
- followups: Verification note — sb-checkpoint-stash-clobber is partial
- mahavishnu: Record FastMCP ≥4 migration plan + registry update
- Mark 5 mcp-stub-activation plans active and regenerate PLAN_INDEX
- plans: Archive-org-mcp implementation plan at full step depth
- plans: Plan 0a registry migration and Plan 0b port reconciliation
- Regenerate PLAN_INDEX.md to include 5 mcp-stub-activation plans
- spec: Final review pass — medium tool table, CI correction, probe split
- spec: MCP stub activation design — archive-org, medium, scapy
- spec: Revision 2 — four-lens review applied to MCP stub activation
- superpowers: Add crackerjack scripts/examples coverage design spec
- superpowers: Add crackerjack scripts/examples coverage plan
- superpowers: Apply multi-agent review fixes (Round 2 — cross-plan consistency)
- superpowers: Apply multi-agent review fixes across 4 plans
- superpowers: Apply Round 2 review fixes (cross-plan consistency + Python idiom)
- superpowers: Fix ruff --config to use inline TOML, not file path
- superpowers: Fix ruff --per-file-ignores -> --config=\<file.toml>
- superpowers: Medium-mcp implementation plan (14 tasks, 70 steps)
- superpowers: Scapy-mcp implementation plan (13 tasks, 60 steps)

### Testing

- registry: Assert canonical is a superset of legacy (currently failing)
- registry: Assert every canonical manifest path exists on disk
- registry: Assert settings/repos.yaml has deprecation header
- registry: Pin legacy entry count against silent deletion

### Build

- deps: Lift fastmcp pin ceiling from \<4 to \<5

### Internal

- Bump last_reviewed dates and normalize agent/command frontmatter
- Bump settings/ecosystem.yaml last_updated + add EOF newlines + clarify README
- Clean ADR 0016 frontmatter + regen PLAN_INDEX

## [0.20.4] - 2026-09-05

### Documentation

- superpowers: Add mcp-common Phase 1 design spec
- superpowers: Add mcp-common Phase 1 implementation plan

## [0.20.3] - 2026-09-04

### Added

- scripts: Add audit_type_checking_runtime_refs + pre-commit hook integration
- scripts: Audit v2 — Pattern B runtime-fallback detection + cluster summary

### Fixed

- Move TYPE_CHECKING-only imports to runtime scope

### Internal

- patterns: Drop github-actions pattern definition

## [0.20.0] - 2026-08-30

### Fixed

- docs: SHEPHERD_BACKEND.md relative link to ../mahavishnu/core/config.py
- quality: Resolve pyscn/creosote/refurb failures on shepherd WIP
- quality: Resolve ruff TC001-TC003/BLE001/PIE810/RUF022 + SHEPHERD_BACKEND link
- repos+rate-limit: Import types at runtime so Pydantic and slowapi can resolve

### Documentation

- v2-plan: Diagnose dispatch_to_pool async-callback bug + design fix

### Internal

- gitignore: Ignore .claude/worktree-snapshots/

## [0.19.0] - 2026-08-29

### Added

- **BREAKING:** mahavishnu: Rename BodaiCLIBase to OneiricCLIBase
- Add WorkerRegistryConfig with Pydantic-validated provides
- config: Add capability_enabled / capability_scopes / legacy_tools flags
- core: Add capability schema with typed I/O contracts
- core: Add Oneiric-driven capability loader (grouped by id)
- core: Conductor with resolve, plan (real edges), emit_node, emit_flow
- core: Dhara-backed envelope transport with secret redaction
- engines: Add load_engine_registrations helper
- engines: Declare provides: list[Capability] on all 6 adapters
- mahavishnu: Add audit_cli_inventory script for Core 7 CLI surface audit
- mahavishnu: Bugfix + first inventory (mcp-common) for CLI audit
- mahavishnu: Close Phase 4/5 gaps — Bodai CLI contract + bodai.apps entry-point
- mahavishnu: Migrate load_config() to oneiric.core.config.load_settings
- mahavishnu: Phase 1 inventory snapshots for 7 Core 7 repos
- mahavishnu: Phase 7 diff_inventories.py (Plan Task 7.1)
- mahavishnu: Pre-commit gate for findings.md (Plan Task 2.2)
- mcp: Add get_capability_result tool (Dhara envelope reader)
- mcp: Capability resolver/planner/executor tools + profile wiring
- settings: Add workers.entries block for capability-driven registry

### Changed

- Continue CLI audit plan + worktree residue after rebase onto origin/main
- mahavishnu: Bump oneiric floor to >=0.20 for OneiricCLIBase
- workers: Replace WORKER_REGISTRY with Oneiric-loaded lookup
- workers: WorkerManager consumes command_argv from WorkerEntry

### Fixed

- config: Anchor MahavishnuSettings yaml_file at package
- Construct crow MCP client inside init_terminal_manager
- crow: Replace anyio ClientSession with raw JSON-RPC subprocess
- envelopes: Pass arguments dict to dhara.call_tool, not kwargs
- Honor terminal.adapter_preference in MCP bootstrap
- hooks: Skip post-commit/merge/rewrite indexer in worktrees
- launcher: Discover venv python relative to script path
- mahavishnu: Correct off-by-2 line numbers in findings.md links
- mahavishnu: Delete yaml_file workaround now that oneiric handles YAML
- mahavishnu: Inventory fallback for inherited Typer commands
- mahavishnu: Make ty gate deterministic across sync states
- mahavishnu: Restore ty ignores on scripts/ imports
- mahavishnu: Silence ty unresolved-import on optional deps
- mcp: Await list_envelopes in get_capability_result tool
- ports: Move bodai-crow HTTP off 8675 (Prefect) to 8693
- Remove McpretentiousMCPClient wrapper so Crow adapter reaches bodai-crow
- Remove remaining mcpretentious references + make crow switchable
- workers: Bound execute_task timeout + wire CLI path's terminal manager
- workers: Pass launch command via tmux new-session instead of send-keys

### Documentation

- Add complementarity section + synthesis-plan sequencing rules
- CLAUDE: Add Bifrost LLM gateway to portmap (8471)
- CLAUDE: Point portmap note at the crow-port-move commit
- Full revision of capability-refactor plan (v2)
- mahavishnu: Add ADMIN_SHELL.md with cross-link to oneiric docs (Plan Task 3.3.x)
- mahavishnu: Add CLI surface summary to BODAI_REPO_REGISTRY (Plan Task 7.2)
- mahavishnu: Mark CLI audit plan complete (all 95 boxes ticked)
- mahavishnu: Phase 1 subagent dispatch template + status
- mahavishnu: Phase 2 cross-repo synthesis findings.md + validate_findings.py
- mahavishnu: Phase 3.4 staleness findings (Plan Task 3.4.1)
- mahavishnu: Quarterly CLI staleness cadence (Plan Task 7.3)
- plan: V3 fixes from single-agent final review
- plans: Worker registry capability refactor implementation plan
- skills: Migrate slash commands and CLI to execute_capability
- specs: Capability-driven worker registry + engine composition design
- specs: Revise capability refactor per multi-agent review feedback

### Testing

- integration: Add docker-compose for end-to-end DAG test
- integration: End-to-end execute_capability DAG
- mcp: Remove orphan test files for deleted tools (3b.3 followup)
- terminal: Prune stale iterm2\_\* assertions after 3b.0 field removal
- workers: Assert new tmux new-session invocation shape
- workers: Fix WorkerResult import path (3b.4 cleanup)
- workers: Smoke test all 16 terminal-\* worker types

### Internal

- Bump version to 0.18.1
- deps: Bump oneiric floor to >=0.19.1
- mcp: Deprecate legacy pool/worker/dispatch tools (3b.1)
- mcp: Prune tool_versions deprecated entries + add 4 new
- mcp: Remove deprecated pool/worker/dispatch tools (3b.3)
- Stage 2 cleanup pass
- terminal: Drop mcpretentious reference in config default

## [0.18.0] - 2026-08-28

### Added

- mahavishnu: Adopt BodaiCLIBase + real doctor/health (Phase 3 Task 4.6)

### Fixed

- 5 of 6 doc-drift findings from mahavishnu audit
- a2a_index: Remove 5 stale fastblocks-stack specialist entries
- plan-a: Apply round-1 multi-agent review fixes (21 findings)
- plan-a: Apply round-2 review fixes
- tests: Re-apply storage_io OSError test patch (built around builtins.open)

### Documentation

- decisions: Add cross-repo fanout CWD isolation policy
- readme: Bump Python badge from 3.13+ to 3.14+

## [0.17.0] - 2026-08-25

### Added

- Add pre-commit hook to mahavishnu index install-hooks
- env: Scope fastblocks agents + document MCP/secret routing pattern
- errors: 9 new error codes for Phase 3 streaming bundle lifecycle
- githooks: Wire audit_no_secrets_in_mcp.py as tracked pre-commit hook
- LocalWorktreeProvider streaming create + fetch (Phase 3 / Task C.6)
- observability: Extend bundle_bytes histogram + Phase 3 op enum
- observability: Verify_sha256_streaming + record_bundle_integrity_failure_short
- RemoteWorktreeProvider streaming tar.zst + bounded queue (Task C.7)
- storage_io: Streaming tar.zst rewrite with context manager + staging promote
- tests: Phase 3 streaming tar.zst end-to-end integration test

### Changed

- Bring worktree-mahavishnu-fix-vishnu-hooks fixes onto main
- Revert "feat(githooks): wire audit_no_secrets_in_mcp.py as tracked pre-commit hook"

### Fixed

- commands: Strip line-1 placeholder frontmatter from 78 skill/command files
- docs: Align frontmatter status/role/topic with validator enums
- docs: Register 8 fresh topic slugs in vocabulary v1
- docs: Repair YAML frontmatter in 015 ADRs + regenerate PLAN_INDEX
- hooks: Propagate audit script exit code in pre-commit hook
- lint: Drop F401 unused imports in local.py
- lint: Resolve comprehensive-hook failures (pyscn + ty + lychee)
- lint: Resolve F821 / TC001 / TC003 in worktree_providers + metrics
- lint: Resolve remaining TC001/TC002/TC003 violations
- local: Align read_stream to load_stream with oneiric actual API
- mahavishnu: Anchor ecosystem.yaml path to project root, not cwd
- mahavishnu: Close ruff lint cleanup on Phase C files
- pyscn: Extract-method refactor to bring complex funcs under CC≤10
- remote: Resolve 3 residual ty errors + migrate integration.py docstring
- Resolve comprehensive-hook ty errors across worktree + providers
- scripts: Clean up 3 ruff diagnostics in migrate_to_streaming_tar
- scripts: Make migrate_to_streaming_tar.py executable + drop EXE001 noqa
- security: Address push-review findings (syntax, traversal, silent corruption)
- tests: Align \_FakeStorage mock with load_stream rename

### Documentation

- Add Bodai Core 7 CLI audit & standardization plan
- BODAI_REPO_REGISTRY.md — authoritative Bodai repo list
- BODAI_UPGRADE_WATCH.md - Phase 4 3.15 readiness tracker
- decisions: Point enforcement section at canonical hook installer
- docs+scripts: Phase 3 streaming tar rollout (D.1-D.6)
- Finalize ADR 016 Phase 4 scope + decision
- plan: Apply final-pass fixes to CLI audit spec (§6 checklist + Goal #8 count)
- plan: Apply power-trio review fixes to CLI audit spec
- plan: Apply round-2 power-trio review fixes (verification + ordering + risk + reader-experience)
- plan: Apply round-2 single+random review fixes (pattern + realism)
- plan: Self-review pass on CLI audit spec
- plan: Update CLI audit spec for γ dual-TUI decision + monitoring_cli drift
- plans: Broaden Phase 3 plan to cover all Bodai-maintained repos
- specs: Broaden Python 3.14 scope to ALL Bodai-maintained repos
- specs: Fold single-agent final pass + Python version strategy (Option C)

### Internal

- Bump requires-python to >=3.14
- mahavishnu: Align ruff target-version with 3.14 + weekly status
- PEP 735 compression-zstd group (Phase 3 streaming tar)
- Re-pin python to 3.14 (follow-up to c1f3c18 requires-python bump)

## [0.16.0] - 2026-08-24

### Added

- Add pre-commit hook to mahavishnu index install-hooks
- config: WorktreeStorageSettings + WorktreeCacheSettings blocks (PR-D.0)
- env: Scope fastblocks agents + document MCP/secret routing pattern
- errors: 9 new error codes for Phase 3 streaming bundle lifecycle
- githooks: Wire audit_no_secrets_in_mcp.py as tracked pre-commit hook
- LocalWorktreeProvider streaming create + fetch (Phase 3 / Task C.6)
- observability: Extend bundle_bytes histogram + Phase 3 op enum
- observability: Verify_sha256_streaming + record_bundle_integrity_failure_short
- RemoteWorktreeProvider streaming tar.zst + bounded queue (Task C.7)
- storage_io: Streaming tar.zst rewrite with context manager + staging promote
- tests: Phase 3 streaming tar.zst end-to-end integration test
- worktree_providers: V4 wiring — LocalWorktreeProvider + RemoteWorktreeProvider + remove_handle + registry resolver + coordinator v4 dispatch (PR-D)
- worktree_providers: WorktreeCache wrapper + storage_io helpers (PR-C)

### Changed

- Bring worktree-mahavishnu-fix-vishnu-hooks fixes onto main
- Revert "feat(githooks): wire audit_no_secrets_in_mcp.py as tracked pre-commit hook"

### Fixed

- commands: Strip line-1 placeholder frontmatter from 78 skill/command files
- docs: Align frontmatter status/role/topic with validator enums
- docs: Register 8 fresh topic slugs in vocabulary v1
- docs: Repair YAML frontmatter in 015 ADRs + regenerate PLAN_INDEX
- hooks: Propagate audit script exit code in pre-commit hook
- lint: Drop F401 unused imports in local.py
- lint: Resolve comprehensive-hook failures (pyscn + ty + lychee)
- lint: Resolve F821 / TC001 / TC003 in worktree_providers + metrics
- lint: Resolve remaining TC001/TC002/TC003 violations
- local: Align read_stream to load_stream with oneiric actual API
- mahavishnu: Anchor ecosystem.yaml path to project root, not cwd
- mahavishnu: Close ruff lint cleanup on Phase C files
- pyscn: Extract-method refactor to bring complex funcs under CC≤10
- remote: Resolve 3 residual ty errors + migrate integration.py docstring
- Resolve comprehensive-hook ty errors across worktree + providers
- scripts: Clean up 3 ruff diagnostics in migrate_to_streaming_tar
- scripts: Make migrate_to_streaming_tar.py executable + drop EXE001 noqa
- security: Address push-review findings (syntax, traversal, silent corruption)
- tests: Align \_FakeStorage mock with load_stream rename
- worktree_providers: Address PR-D security review (3 findings)

### Documentation

- BODAI_REPO_REGISTRY.md — authoritative Bodai repo list
- BODAI_UPGRADE_WATCH.md - Phase 4 3.15 readiness tracker
- decisions: Point enforcement section at canonical hook installer
- docs+scripts: Phase 3 streaming tar rollout (D.1-D.6)
- Finalize ADR 016 Phase 4 scope + decision
- plans: Broaden Phase 3 plan to cover all Bodai-maintained repos
- specs: Broaden Python 3.14 scope to ALL Bodai-maintained repos
- specs: Fold 15 BLOCKERs from multi-agent review into Phase3 streaming tar design
- specs: Fold 22 BLOCKERs from round-2 multi-agent review into Phase3 design
- specs: Fold single-agent final pass + Python version strategy (Option C)
- specs: Streaming tar.zst bundles Phase 3 design

### Internal

- Bump requires-python to >=3.14
- mahavishnu: Align ruff target-version with 3.14 + weekly status
- PEP 735 compression-zstd group (Phase 3 streaming tar)
- Re-pin python to 3.14 (follow-up to c1f3c18 requires-python bump)

## [0.15.0] - 2026-08-24

### Added

- Add pre-commit hook to mahavishnu index install-hooks
- auth: Add Principal and CleanupPolicy types
- config: WorktreeStorageSettings + WorktreeCacheSettings blocks (PR-D.0)
- env: Scope fastblocks agents + document MCP/secret routing pattern
- errors: 9 new error codes for Phase 3 streaming bundle lifecycle
- githooks: Wire audit_no_secrets_in_mcp.py as tracked pre-commit hook
- LocalWorktreeProvider streaming create + fetch (Phase 3 / Task C.6)
- observability: Extend bundle_bytes histogram + Phase 3 op enum
- observability: Verify_sha256_streaming + record_bundle_integrity_failure_short
- observability: §17 OTel metrics + bundle integrity helpers (PR-B)
- paths: Add get_worktree_base_path() and get_worktree_path() helpers
- RemoteWorktreeProvider streaming tar.zst + bounded queue (Task C.7)
- storage_io: Streaming tar.zst rewrite with context manager + staging promote
- tests: Phase 3 streaming tar.zst end-to-end integration test
- w4: Promote oneiric action kits via decision doc and auto-trigger skill
- worktree_providers: Add Dhara-backed worktree registry (ADR 015 v4 §11)
- worktree_providers: Add LocalWorktreeProvider + v4 types (ADR 015 v4 §13)
- worktree_providers: Add pre_migration_discover() for v4 Phase 1.5
- worktree_providers: RedisLockBackend + Dhara registry security fixes
- worktree_providers: V4 wiring — LocalWorktreeProvider + RemoteWorktreeProvider + remove_handle + registry resolver + coordinator v4 dispatch (PR-D)
- worktree_providers: WorktreeCache wrapper + storage_io helpers (PR-C)

### Changed

- Bring worktree-mahavishnu-fix-vishnu-hooks fixes onto main
- Revert "feat(githooks): wire audit_no_secrets_in_mcp.py as tracked pre-commit hook"
- worktree_providers: Apply crackerjack-compliant-code cleanup
- worktree_providers: Rename direct_git.py -> local.py (1-release alias)
- worktree_providers: Rename S3WorktreeProvider + S3WorktreeRef to remote variants
- worktrees: Funnel 5 default-value sites through get_worktree_base_path()

### Fixed

- commands: Strip line-1 placeholder frontmatter from 78 skill/command files
- docs: Align frontmatter status/role/topic with validator enums
- docs: Register 4 fresh topic slugs in vocabulary v1
- docs: Register 8 fresh topic slugs in vocabulary v1
- docs: Repair YAML frontmatter in 015 ADRs + regenerate PLAN_INDEX
- hooks: Propagate audit script exit code in pre-commit hook
- lint: Drop F401 unused imports in local.py
- lint: Resolve comprehensive-hook failures (pyscn + ty + lychee)
- lint: Resolve F821 / TC001 / TC003 in worktree_providers + metrics
- lint: Resolve remaining TC001/TC002/TC003 violations
- local: Align read_stream to load_stream with oneiric actual API
- mahavishnu: Anchor ecosystem.yaml path to project root, not cwd
- mahavishnu: Close ruff lint cleanup on Phase C files
- pyscn: Extract-method refactor to bring complex funcs under CC≤10
- remote: Resolve 3 residual ty errors + migrate integration.py docstring
- Resolve comprehensive-hook ty errors across worktree + providers
- scripts: Clean up 3 ruff diagnostics in migrate_to_streaming_tar
- scripts: Make migrate_to_streaming_tar.py executable + drop EXE001 noqa
- security: Address push-review findings (syntax, traversal, silent corruption)
- tests: Align \_FakeStorage mock with load_stream rename
- worktree_providers: Address 3 security review findings from push sweep
- worktree_providers: Address PR-D security review (3 findings)
- worktree_providers: Make RemoteWorktreeRef.backend_kind required

### Documentation

- adr-015: Storage architecture — v1, multi-agent review, v2
- adr-015: V3 — incorporates round-2 multi-agent review (~20 new BLOCKERs)
- adr-015: V3 — S3/GCS credentials delegated to Oneiric, GCS mock note
- adr-015: V4 — final-pass corrections (Principal defined, Protocol removed, exception base, Phase 1.5 spike)
- BODAI_REPO_REGISTRY.md — authoritative Bodai repo list
- BODAI_UPGRADE_WATCH.md - Phase 4 3.15 readiness tracker
- decisions: Add v4 cross-references to worktree-autoremove-policy.md
- decisions: Cross-reference ADR 015 v4 + add auto-prune follow-up doc
- decisions: Point enforcement section at canonical hook installer
- docs+scripts: Phase 3 streaming tar rollout (D.1-D.6)
- Finalize ADR 016 Phase 4 scope + decision
- Oneiric action-kit promotion implementation plan
- plans: Broaden Phase 3 plan to cover all Bodai-maintained repos
- spec: Oneiric action-kit adoption promotion design
- spec: Review pass — fix kit count, frontmatter, path, rollout gaps
- specs: Broaden Python 3.14 scope to ALL Bodai-maintained repos
- specs: Fold 15 BLOCKERs from multi-agent review into Phase3 streaming tar design
- specs: Fold 22 BLOCKERs from round-2 multi-agent review into Phase3 design
- specs: Fold single-agent final pass + Python version strategy (Option C)
- specs: Streaming tar.zst bundles Phase 3 design

### Testing

- paths: Add CI guard test for worktree base path resolution

### Internal

- Bump requires-python to >=3.14
- claude-md: Add oneiric action-kit discovery breadcrumb
- mahavishnu: Align ruff target-version with 3.14 + weekly status
- PEP 735 compression-zstd group (Phase 3 streaming tar)
- Re-pin python to 3.14 (follow-up to c1f3c18 requires-python bump)
- skills: Trim oneiric-action-kit-awareness description to 396 chars (under 400 hard limit)

## [Unreleased] — Phase 3 streaming tar.zst (ADR 015 v4)

### Added

- **Streaming tar.zst worktree bundles** for >100 MB worktrees (replaces the in-memory Phase 2 tar.gz path)
- **Bounded queue producer/consumer handoff** in RemoteWorktreeProvider.fetch (queue.Queue(maxsize=4)) coordinating slow disk + fast network
- **MHV error codes 209–223** for streaming-specific failures (`MHV-209` `TEMP_CREATE_FAILED`, `MHV-210` `TEMP_WRITE_FAILED`, `MHV-211` `PATH_TRAVERSAL`, `MHV-212` `MALFORMED`, `MHV-213` `LEGACY_PHASE2`, `MHV-220` `STORAGE_KEY_TOO_LONG`, `MHV-221` `STOPGAP_TOO_LARGE`, `MHV-222` `NOT_FOUND`, `MHV-223` `CODEC_UNAVAILABLE`)
- **Oneiric `compression-zstd` PEP 735 group** for the `zstandard` streaming codec
- **SHA-256 streaming verification** via `verify_sha256_streaming` (no full-blob in memory) plus `streaming_op_total{op,backend,success}` OTel counter and `streaming_op_duration_seconds{op,backend}` histogram
- **Operator runbook** `docs/runbooks/STREAMING_TAR_ROLLOUT.md` and **migration script** `scripts/migrate_to_streaming_tar.py` plus error-severity runbook `docs/runbooks/COORDINATOR_ERROR_SEVERITY.md`

### Changed

- Worktree storage key suffix: `.tar.gz` → `.tar.zst`
- `LocalStorageAdapter` / `S3StorageAdapter` / `GCSStorageAdapter` / `AzureBlobStorageAdapter` now expose `save_stream` / `load_stream` for streaming I/O
- `bundle_bytes` histogram buckets extended to 1 GB so streaming-size percentiles are visible

## [0.14.0] - 2026-08-22

### Added

- w3: Adopt http.fetch + workflow.retry action kits

### Fixed

- mahavishnu: Close ruff TC002 + BLE001 in http_probe
- mahavishnu: Close ty errors after cj update
- mahavishnu: Drop dead code from pre-hybrid embeddings
- mahavishnu: Replace EmbeddingService with oneiric hybrid chain
- w3: Close mahavishnu BLOCKER 1 + BLOCKER 2 from review

## [0.13.0] - 2026-08-22

### Changed

- mahavishnu: Use apply_tool_profile() from mcp-common
- mahavishnu: Use mandatory_groups + W0.5 fix from mcp-common 0.18.0
- mahavishnu: Use unaliased \_apply_tool_profile + pin mcp-common>=0.18.0

### Fixed

- claude-code-stop-hook: Use absolute Python paths in hook commands
- docs: Add canonical frontmatter to mcp-deps-crackerjack-loop spec
- docs: Register 4 fresh topic slugs in vocabulary v1
- lint: Resolve 8 ruff violations in fast_hooks
- mahavishnu: Agno config defaults — 5 tests
- mahavishnu: Bootstrap-helper-renames — 49 tests
- mahavishnu: Cli-output-routing — 11 tests
- mahavishnu: Content_ingester + dependency_waiter + distill + sop + repo_properties — 5 tests
- mahavishnu: Dhara-schema-imports — 4 decision_writer tests
- mahavishnu: Drop obsolete terminal-aider from worker registry (was: 9343fc47)
- mahavishnu: Drop obsolete terminal-goose/gemini/amp worker entries
- mahavishnu: Gitignores + claude_settings + claudemd + command_palette — 4 tests
- mahavishnu: Health + dispatch_to_pool — 3 tests
- mahavishnu: Health + errors + mcp_auth + mcp_otel — 5 tests
- mahavishnu: Mcp_external + end_to_end + wiring + workflow + cli_accessibility — 5 tests
- mahavishnu: Mcpretentious-removal — 4 tests
- mahavishnu: Opensearch + permissions + cross_repo + pool_route — 6 tests
- mahavishnu: Reconcile AgnoMemoryConfig default — True (was: d3f396d0)
- mahavishnu: Resolve 70+ pre-existing test failures
- mahavishnu: Test_agno + test_evidence + test_feature_flags — 3 tests
- mahavishnu: Test_capabilities_observability.py — 3 tests
- mahavishnu: Test_check_ecosystem_gitignores_plugin.py — 6 tests
- mahavishnu: Test_distill_workflows.py — 3 tests (schema columns + provenance gate wiring)
- mahavishnu: Test_generic_shell_worker.py — 4 tests
- mahavishnu: Test_mcp_server_core + fastmcp imports + worker_execute — 2 tests
- mahavishnu: Test_mcp_tool_inventory.py — 3 tests
- mahavishnu: Test_mcp_tools.py collection errors — 6 tests
- mahavishnu: Test_monitoring_alerting.py requests stub — 9 tests
- mahavishnu: Test_repositories.py pydantic forward-refs — 12 tests
- mahavishnu: Test_repository_messaging_tools.py + test_session_buddy_integration.py — 5 tests
- mahavishnu: Test_session_buddy_auth.py + test_crow_call_site_wiring.py — 5 tests
- mahavishnu: Test_task_router_coverage.py + test_task_router_and_auth.py — 3 tests
- mahavishnu: Test_workers_registry_coverage.py — 106 tests
- mahavishnu: Test_worktree_providers.py — 7 tests
- mahavishnu: Test_worktree_registry_cli.py — 8 tests
- mahavishnu: Websocket-metrics disabled-mode + collector lookup — 13 tests
- mahavishnu: Worktree + prefect + coordination — 5 tests
- metrics: Targeted REGISTRY cleanup in production reset helpers
- plans: Use --upgrade-package instead of --upgrade --all-groups
- Register /health before MahavishnuApp.__init__ blocks
- Resolve 3 pre-existing ty errors in core/
- tests: Fix 10 more pre-existing failures (TaskType pollution, golden fixture, integration)
- tests: Resolve 5 more pre-existing failures + harden test plumbing
- tests: Resolve 66 of 83 pre-existing test failures
- tests: Resolve 9 more xdist-suite failures via module-reference + targeted REGISTRY cleanup
- ty/lychee: Resolve comprehensive_hooks failures
- ty: Remove unused missing-argument ignores
- ty: Resolve 10 union-attribute + missing-argument errors

### Documentation

- docs+scripts(mahavishnu): plan lifespan health bypass + bodai MCP verify script
- mahavishnu: Add per-repo tool-profile rationale doc (W1.1 backfill)
- mahavishnu: Record MANDATORY_GROUPS erratum in task-20 brief (Minor 1)
- MCP tool profile adoption implementation plan
- plans: 2-repo plugin POC scope for graphics-mcp + css-mcp
- plans: Add bodai MCP surface standardization plan + lifespan cleanup
- plans: Mcp-deps-crackerjack-loop implementation plan
- spec: MCP tool profile adoption across 18 Bodai-ecosystem MCP servers
- specs: Mcp-deps-crackerjack-loop design (2026-08-20)
- specs: Rev2 — addresses 5-reviewer audit findings

### Testing

- mahavishnu: Regression test for /health lifespan bypass

## [0.12.1] - 2026-08-18

### Added

- mahavishnu: Mirror wave-11 mermaid CI guard from crackerjack

### Changed

- bodai-conformance: Address 4-agent review findings (critical + material)
- bodai-conformance: Apply R2-1..7 fixes inline
- bodai-conformance: Round-2 review findings as known-issues appendix
- bodai-consistency: Address 4-agent review findings
- bodai-consistency: Design for ecosystem conformance mechanisms

### Fixed

- mahavishnu: Add peer_affinity to routing decision tree
- mahavishnu: Remove ASCII duplicates and one block from GETTING_STARTED.md
- mahavishnu: Remove broken image ref from EMBEDDING_ARCHITECTURE.md:495
- mahavishnu: Remove decorative diagram blocks from ADR-005 (3 removals)
- mahavishnu: Remove decorative diagram blocks from VISUAL_GUIDE (13 removals)
- mahavishnu: Remove decorative diagram blocks from WORKFLOW_DIAGRAMS (2 removals)
- mahavishnu: Remove EMBEDDING_ARCHITECTURE.md duplicates from README/EMBEDDINGS_SETUP_GUIDE (5 removals)
- mahavishnu: Replace AgentDB/Ollama with Dhara/FastEmbed in ADR-005
- mahavishnu: Replace iTerm2/MCPretentious adapters in canonical arch diagram
- mahavishnu: Replace OpenSearch DLQ with JSON + Dhara KV in VISUAL_GUIDE
- mahavishnu: Replace PoolManager routing and caller_kind in adapter diagrams
- mahavishnu: Update repo count 9 → 7 in tag-based filtering
- mahavishnu: Update tool count 49 → 174+ in MCP tools mindmap

### Documentation

- Add INDEX.md cataloging all plans under docs/superpowers/plans/
- audit: Apply 2026-08-12 drift fixes
- Capture bodai diagram audit snapshot 2026-08-16
- changelog: Document mcpretentious removal + quality_scorer rename
- mahavishnu: Annotate mcpretentious topic keys with migration note
- mahavishnu: Bump WebSocket rollback example image from v0.1.9 to v0.12.0
- mahavishnu: Drop dead iterm2/mcpretentious coverage targets from backlog
- mahavishnu: Fix stale cascade reference in crow-mcp-client-wiring followup
- mahavishnu: Replace 5 dead file paths (iterm2/mcpretentious/quality_evaluator/backup_cli/production_cli)
- mahavishnu: Replace iTerm2/mcpretentious with live adapters in ARCHITECTURE
- mahavishnu: Replace iTerm2/mcpretentious with live adapters in CAPABILITIES analysis
- mahavishnu: Replace iTerm2/mcpretentious with live adapters in ORCHESTRATION_SUMMARY
- mahavishnu: Replace iterm2/mcpretentious with tmux in crow runbook
- mahavishnu: Replace mcpretentious/iTerm2 references with tmux/mock/crow adapters
- mahavishnu: Replace mcpretentious/iTerm2 with tmux/mock in mcp-server doc
- mahavishnu: Replace quality_evaluator/pool.py/iterm2/mcpretentious in 4 small docs
- mahavishnu: Rewrite BACKENDS.md as live-adapter stub (mcpretentious removed)
- plans: Add bodai-conformance plan + spec to canonical PLAN_INDEX.md
- Refine P0 audit fixes for tool-count, profile wording, and CLI inventory

### Testing

- mcp: Add tool inventory ratchet test (CI guard against count drift)

### Internal

- gitignore: Add .coverage\* + untrack .coverage-ratchet.json (bodai 2026-08-17)
- mahavishnu: Delete archive diagram mirrors (9 files)
- Pin minimax-coding-plan-mcp install args

## [Unreleased]

### Changed

- deps: the `mcp-common` floor moves to `>=0.33.0`. mcp-common's producer
  telemetry builds its span exporter with the OTLP/HTTP exporter (the default
  protocol is `http/protobuf`), and this project declares the gRPC exporter
  for its own metrics and spans but not the HTTP one -- so the HTTP exporter
  arrives with mcp-common, and the floor is what guarantees it arrives.
- deps: the OpenTelemetry packages this project declares stay declared.
  `core/observability.py` imports the API, the SDK and the gRPC exporters by
  name, and a direct import is a direct dependency. The instrumentation pair
  is not declared by mcp-common at all, so nothing else would provide it.
  What changed is that mcp-common now declares the SDK and the exporters as
  its own runtime dependencies, so a consumer that only calls its producer
  API no longer has to repeat the pins.

### Removed

- **BREAKING:** Mcpretentious terminal adapter removed in favour of the pluggable
  terminal adapter registry (`mahavishnu/terminal/adapters/`). Resolved at
  runtime via `adapter_preference` (default `tmux`). See `34f61672`.

### Renamed

- `mahavishnu/ingesters/quality_evaluator.py` merged into
  `mahavishnu/ingesters/quality_scorer.py` (type definitions consolidated;
  old module deleted in checkpoint `4cc25321` after consolidation landed in
  `ea2dd578`). `ContentIngester.ingest` now reads from the scorer module only.

## [0.12.0] - 2026-08-12

### Added

- 2026-08-10-wave: Mcpretentious removal + webhook-durable/approval-log/workflow-outcome specs
- Adopt coverage-ratchet at current coverage
- approval: Decision_writer — validate-on-write at decision boundary
- List_approval_history returns validated ApprovalLog structs
- Mount durable receiver + register webhook_replay as MCP tool
- precommit: Add Prometheus counters to 3 substrate producers
- precommit: Retire LockStore/JsonFileLockStore, rewrite tests
- precommit: Rewrite HypothesisLock as async D-LOCK backed
- precommit: Wire CLI with asyncio.run wrappers + update error strings
- substrate-compat: Extract stamp/calltime pattern into shared helper (task 144)
- webhooks: Receiver emits validated WebhookIngress via dhara.put
- webhooks: Webhook_replay MCP tool — read-back via from_dict
- Wire outcome_writer into on_workflow_complete + register workflow_get_outcome MCP tool
- Wire record_approval_decision into decision flow (replaces delete-on-resolve)
- workflow: Outcome_writer — validate-on-write at completion boundary
- Workflow_get_outcome MCP tool — read-back via from_dict

### Changed

- coordinator: Extract preflight safety checks to reduce complexity

### Fixed

- approval-cli: Bind real exception in approval_list_entry_skipped log
- approval: Log warning when decision_writer persistence is skipped (cross-portfolio consistency)
- cli: Use timezone-aware datetime in precommit_lock
- coordinator: Don't log removal_success when provider fails
- docs: Rewrite worktree-prefixed paths and drop broken Medium URLs
- ecosystem: Rename nicknames on→oc (oneiric), md→mj (mdinject)
- Fold multi-agent review findings into D-LOCK plan
- Gate workflow_get_outcome against workflow_id allowlist (sibling-parity)
- id-guard: Add validate_approval_id + validate_webhook_id guards
- indexer: Tolerate RuntimeError from tree-sitter parse failures
- Log error type not str(err) on record_workflow_outcome failure
- MCP streamable-http handshake + pydantic-settings 2.15 compat + pool auto-spawn
- rbac: Gate 3 read-path tools on substrate-permission check
- Repair 4 broken links in openclaw portfolio spec
- typing: Widen schemas and permission types to satisfy ty
- webhooks: Add WEBHOOK_DURABLE_V1_ENABLED flag + runtime gate (Task 1 review follow-ups)
- workflow-outcome: Env-var gate + producer/consumer getattr runtime gates
- worktree: Component-aware allow-list check + per-repo subdir allowlist
- worktree: Widen path-validator default to ~/Projects

### Documentation

- 4 entity wire-up specs + D-LOCK v1.1 update
- Add Crackerjack C-WIRE implementation plan
- Add D-LOCK implementation plan
- approval: Surface async-passthrough concern + Spec coverage map (Task 4 review follow-ups)
- Mark 4 superseded 2026-06-22 plans shipped + cross-link replacements
- Note substrate put/get call-boundary contract in 3 producer module docstrings
- plan: Drop speculative crackerjack.security.critical_hooks gauge
- plan: M-APPROVAL-LOG — wire approval_log into Mahavishnu (4 tasks)
- plan: M-WEBHOOK-DURABLE — wire webhook_ingress into Mahavishnu (3 tasks)
- plan: M-WORKFLOW-OUTCOME — wire workflow_outcome into Mahavishnu (4 tasks)
- portfolio: Flip D-AUDIT from parked to adopted (substrate shipped)
- portfolio: Flip D-LOCK to wired (v1 shipped) + link v1.1 follow-up plan
- portfolio: Flip M-APPROVAL-LOG from parked to wired (substrate shipped)
- portfolio: Flip M-WORKFLOW-OUTCOME from parked to wired (substrate shipped)
- portfolio: Flip S-CHANNEL-DURABLE from parked to wired (4th consumer wire-up shipped)
- portfolio: M-WEBHOOK-DURABLE building (receiver built, not mounted) + add M-WEBHOOK-DURABLE-WIRED follow-up row
- Reconcile auto-checkpoint review findings
- Rewrite C-WIRE plan with verified APIs + observability
- spec: Add Bodai OpenClaw/Hermes-inspired follow-ups portfolio
- workflow-outcome: Flip status to built per multi-agent review

### Testing

- precommit: Cover duplicate async lock branch
- precommit: Drop unused r1 assignment + unnecessary f-prefix
- precommit: Replace vacuous duplicate-lock test + fix DTZ005
- Round-trip + completion report for M-APPROVAL-LOG
- Round-trip + completion report for M-WORKFLOW-OUTCOME
- webhooks: Round-trip + completion report for M-WEBHOOK-DURABLE

### Internal

- cleanup: Remove unused \_validate_approval_id + \_validate_webhook_id aliases
- Remove .superprofits/ scratch typo, add to .gitignore
- workers: Remove terminal-openclaw and terminal-zsh

## [0.11.0] - 2026-08-03

### Added

- Add tiered microVM isolation workers (Apple container + E2B)
- Add WorktreePruneCandidate, classify_merge_status, WorktreePruner
- Drain pending WAL rows through Session-Buddy sink (MAHAVISHNU_OUTBOX_DRAIN)
- errors: Add WorkerUnavailableError and ContainerDaemonUnavailable
- events: Add worker topic constants and helper
- lifecycle: Add on_mahavishnu_shutdown for graceful worker detaching
- lifecycle: Add startup reconciliation hook for durable workers
- mahavishnu: Add MemoryOutboxWriter (WAL schema + DuckDB writer)
- mcp: Add worker contract tools and bootstrap registration
- mcp: Add workflow_result retrieval tool
- mcp: Filter worker_list by state and worker_id
- mcp: Pool tools route shell types through durable contract
- mcp: Remove iTerm2 terminal bootstrap path
- mcp: Remove iTerm2 terminal tool branches
- mcp: Route worker_spawn shell types through durable contract
- mcp: Stop truncating worker_execute / worker_execute_batch output
- mcp: Worker_close uses two-phase cancellation
- mcp: Worker_close_all and worker_health use durable contract
- mcp: Worker_collect_results supports incremental output
- mcp: Worker_monitor routes through durable manager
- observability: Instrument pool_route_execute and terminal_launch for §14 pool_share
- observability: Instrument worker contract tools with metrics
- Re-enable SessionBuddyWorktreeProvider by default
- Route tmux preference to durable TmuxTerminalAdapter
- settings: Add worker_contract defaults
- terminal: Deprecate iTerm2 preference to mock fallback
- terminal: Register tmux as a builtin backend
- terminal: Remove iTerm2 adapter implementation
- terminal: Remove iTerm2 session pool
- workers/contract: Add atomic JSON store for durable records
- workers/contract: Add canonical envelope publisher
- workers/contract: Add DurableWorkerManager with reconcile_all
- workers/contract: Add DurableWorkerRecord Pydantic model
- workers/contract: Add tmux adapter primitives
- workers/contract: Add WorkerLifecycleState and transition rules
- workers: Add capability layer with static, live, and observability phases
- workers: Add capability metadata fields to WorkerConfig
- workers: Discover docker/orbstack runtime and probe daemon
- workers: Gate cloud worker on credentials, no secret logging
- workers: Split one-shot submit path and de-couple resolve_worker_type
- workers: Wire capability diagnostics into CLI, MCP, and health
- worktree-cli: Add prune-merged subcommand

### Changed

- events: Add trailing newlines to worker_topics files
- Mahavishnu (quality: 72/100) - 2026-07-25 02:10:24
- Mahavishnu (quality: 74/100) - 2026-07-26 13:47:32
- Mahavishnu (quality: 74/100) - 2026-07-27 02:25:40
- session-buddy: Mahavishnu seam hardening design (WAL + hook gate + plugin + code-graph facade + skill-coverage gate)
- session-buddy: Mahavishnu seam hardening implementation plan (6 tasks)
- terminal: Fix import order in manager.py
- terminal: Remove iTerm2 adapter registry entries
- terminal: Type grid against adapter ABC
- workers/contract: Add trailing newlines to publisher files
- workers: Add dedicated factory branches for openhands, a2a, terminal-crow
- workers: Complete DebugMonitorWorker Wave 2 removal; drop stale MCP test duplicate
- workers: Remove Docker/OrbStack ContainerWorker in favor of microVM tiers

### Fixed

- ecosystem+audit: Complete 3 missing nicknames; route worktree audit to dedicated logger
- ecosystem: Quote oneiric nickname to avoid YAML 1.1 boolean coercion
- errors: Redact secret-shaped substrings in exception messages
- Honor nested workers.enabled setting in CLI
- mcp: Harden durable-routing fast path against Task 24 security review
- mcp: Workflow_result reads full Dhara key
- openclaw: Cap auto-restart and surface terminal failure
- pools: Close fail-open-state-drift in outbox sink and drainer breaker
- pools: Wire drainer into collect_and_sync + strengthen writer test (whole-branch follow-ups)
- provider: Parse Session-Buddy JSON payload; flip session-buddy default to enabled
- quality: Resolve pyscn/ty/refurb/lychee findings (Wave 2)
- Resolve 7 merge conflicts from pre-wave-merge dirty state
- Resolve Wave 3 type errors (14 findings, 7 files)
- ruff: Resolve F821 undefined names + ASYNC blocking I/O (20 findings)
- tui: Make textual a true optional dependency
- workers/contract: Address Task 1 review notes (F401 + from __future__)
- workers/contract: Make WorkerLifecycleState available at class definition for Pydantic v2
- workers/contract: Mark_all_detached only includes states that can transition to DETACHED
- workers/contract: Narrow tmux type in cancel() and unbreak Pydantic enum import
- workers/contract: Replace misleading F3 comment with honest deferral; cover cancel idempotency
- workers/contract: Security hardening for tmux adapter (validation, safe stderr, send-keys -l) and portable test socket path
- workers/contract: Space-join send_keys parts so multi-token prompts type correctly
- workers: Address 5 capability-layer security findings
- workers: Enable runtime discovery and DOCKER_HOST wiring
- workers: Handle DEGRADED in execute and cover start() in tests
- workers: Make get_readiness async and surface aggregation errors
- workers: Recognize Claude Code stream-json result marker
- workers: Thread prompt kwarg and update remaining routing tests
- workers: Trailing newlines and tighten AWS char class
- workers: Wire A2A agent configs from settings + add openhands test
- worktree: Filter Session-Buddy provider when its tools are missing

### Documentation

- Add WORKTREE_AUTOREMOVE guide + feature tracking + DEFERRED appendix
- Amend plan Task 1 testing contract to nested env var
- decisions: Add worktree-autoremove-policy with explicit Rule 2 amendment
- feature-tracking: Record E2B SDK API verification
- mahavishnu: Add Rule #7/8/9 for invalid-return-type, invalid-await, unused-type-ignore-comment
- mahavishnu: Amend ty ignore codes — Rule #6 for return-type bugs, slim audit counts
- mahavishnu: Index ty-ignore-codes decision in decisions README
- mcp: Document worker contract tools
- plans: Add durable local workers implementation plan
- plans: Add session-buddy-worktree-tools follow-up plan
- plans: Add Task 26 (iTerm2 deprecation/removal) and confirm open questions
- plans: Apply multi-reviewer audit fixes (F1-F20 + new tasks 8a/8b/18-25)
- plans: Bump target version 0.69.5 → 0.70.0 (MINOR per SemVer)
- plans: Keep wrapper pkg_path per spec; CLI flag stays as repo_root
- plans: Revise shared-validator plan based on 4-agent review
- readme: Add Bodai Ecosystem Role section
- Record iTerm2 adapter removal
- spec: Collapse Phase C iTerm2 deprecation+removal per user direction
- specs: Add durable local workers design (tmux default, iTerm2 demoted, Zellij deferred)
- terminal: Drop iTerm2 docstring references
- Worker readiness and lifecycle repair design
- Worker readiness plan v3 (full review fixes)

### Testing

- Delete resurrected test_terminal_manager.py
- Fix collection collisions by renaming, not packaging
- Fix pytest module-name collision by completing the test package chain
- lifecycle: Assert on_mahavishnu_startup returns reconciled records
- mcp: Cover workflow_result path-traversal guard (Task 24 sibling-gate-parity)
- Pin EventBridgeConfig default_factory resolution
- terminal: Cover removed iTerm2 preference fallback
- terminal: Fix indentation after iTerm2 patch removal
- terminal: Remove deleted iTerm2 test dependencies
- terminal: Remove iTerm2-only suites
- terminal: Remove leftover iTerm2-coupled suites
- terminal: Repair indentation in mcp-client test
- workers/contract: Add reconciliation integration test
- workers: Add integration suite for capability live probes
- workers: Add trailing newline to gate test
- workers: Add trailing newlines to integration suite
- workers: Align observability tests with Oneiric logger
- workers: Assert tool-result blocks do not trigger completion
- workers: Fix list-types ready-only test for log noise and path gating
- workers: Switch gate test to nested env-var override
- workers: Update registry tests for resolve_worker_type de-coupling

### Build

- Remove iTerm2 dependency group

### Internal

- Bump oneiric dep to >=0.16.0
- deps: Bump crackerjack>=0.70.0; remove duplicated validator script; fix plan/spec frontmatter
- ecosystem: Add 5 nicknames; docs(plans): track nickname + audit logger gaps
- ecosystem: Add package field to all 8 repos
- Restore unrelated task dashboard files
- ruff: Apply safe autofix for 600 findings (Wave 0.5)
- ruff: Apply Wave 1a datetime UTC fixes (251 findings, 87 files)
- ruff: Apply Wave 1b mechanical fixes (176 findings, 77 files)
- ruff: Apply Wave 1b/2/3 exceptions (9 findings, 8 files)
- ruff: Apply Wave 1b/2/3 workers_engines_automation (79 findings, 22 files)
- ruff: Apply Wave 3 BLE001 + TRY002/TRY004 (740 findings, 232 files)
- ruff: Apply Wave 3 BLE001 partial (267 findings, 51 files)

## [0.10.0] - 2026-07-21

### Added

- Add mahavishnu metrics dispatch subcommand
- Add mahavishnu metrics verification subcommand
- Add mahavishnu plugin manifest + namespaced commands (additive)
- Add ultracode Phase 1/3 settings
- cli: Add --json output for list-sessions and prune-abandoned
- docs: Frontmatter v1 schema, validator, topic vocabulary (plan-lifecycle-unification P0)
- docs: PLAN_INDEX regenerator + first regeneration (plan-lifecycle-unification P6)
- frontmatter: Migrate 217 docs to v1 schema
- hooks: Add discovery hint for opt-in worktree isolation (Phase 4)
- hooks: Discover current branch, debug mode, credential safety, configurable timeout
- hooks: Flip default-on for internal-team Bodai usage (Phase 8)
- hooks: Wire worktree-session-isolation into SessionStart/SessionEnd
- Per-session worktree registry + CLI (Phase 1)
- plugin: Remove old flat session-buddy commands (now session-buddy:<cmd>)
- regenerator: Auto-discover stores + per-repo Authority Matrix
- Remove old flat slash commands; mahavishnu plugin is canonical
- Workflow lifecycle audit script

### Changed

- Deprecate and remove the iTerm2 terminal adapter; use tmux or mcpretentious instead
- Consolidate flock+atomic-write into json_state_store
- Mahavishnu (quality: 0/100) - 2026-07-16 19:44:17
- Mahavishnu (quality: 72/100) - 2026-07-16 18:33:29
- Mahavishnu (quality: 72/100) - 2026-07-16 18:50:08
- Mahavishnu (quality: 72/100) - 2026-07-20 22:55:11
- Wire fail-closed end-to-end + adopt followups lifecycle

### Fixed

- claude: Enable bodai-activity-\* hooks by nesting under 'hooks' key
- followups: Map legacy status 'resolved' to canonical 'complete'
- frontmatter: Populate superseded_by for 2026-04-09-tui-design.md
- frontmatter: Re-convert 2026-04-09-tui-design.md
- hooks: Detect real git worktrees via --git-dir
- hooks: Harden mode dispatch, payload validation, and option-injection
- registry: Log diagnostic on unsupported schema_version
- security: Bandit skips + 3 real vulnerability fixes
- validator: Exclude .archive/, accept list-form superseded_by/blocks_on, coerce Resolved->complete (C1.1)
- worktree-registry: Close lost-update race + write-path TOCTOU

### Documentation

- Align hint prefix with brand convention + reference XDG state path
- Bodai plugin standardization implementation plan
- Close out per-session worktree isolation rollout (Phase 3)
- Constellation tui implementation plan (10 tasks, deferred)
- Cross-reference Phase 8 commit hash in followup
- decisions: Add component-health-cli-gap decision
- decisions: Add dhara-key-prefixes decision
- decisions: Add workflow decision README and template
- Fix Phase 4 commit hash reference (post-amend)
- followups: Add lifecycle template
- followups: Close multi-session-mcp-contention — fix landed in session-buddy
- followups: Open multi-session-mcp-contention followup
- followups: Update index for bodai-hooks-sb-debug resolution
- Normalize .claude/decisions to lite frontmatter (P5 Pass 1)
- Normalize 14 ADRs to unified frontmatter (plan-lifecycle-unification P1)
- Normalize 18 orphan docs/plans files (C1.2)
- Normalize docs/plans to unified frontmatter (P2 Pass 1)
- Normalize docs/superpowers/plans to unified frontmatter (P4 Pass 1)
- Pair existing wave workflows with decision files
- Pair remaining unpaired workflows with decision files; rename part2 to match filename
- plan-index: Link constellation tui to companion ACP spec
- plan-index: Track cross-repo Dhara cache-adapter consolidation plans
- plans: Add frontmatter to validator-wiring plan
- plans: Implementation plan for validator wiring + P7 cross-repo expansion
- plans: Mark oneiric wire standardization shipped
- plans: Promote 2026-07-16-dlq-fail-closed-wiring to shipped
- plans: PyPI auth redesign implementation plan
- plans: Reconcile PLAN_INDEX drift-sync 2026-07-15
- plans: Tick stale-done ultracode Phase 1-3 items
- schema: Expand topic vocabulary seed list 10 -> 19 to cover P1 ADRs
- schemas: Add 3 ecosystem topics to vocabulary (crackerjack-publish-auth, akosha-skills, bodai-radar)
- schemas: Add followups-index topic to vocabulary
- schemas: Add session-worktree-isolation topic to vocabulary
- schemas: Reference crackerjack integration surface
- skills: Migrate SKILL.md frontmatter to YAML
- skills: Rename vishnu to mahavishnu
- skills: Rename vishnu-status to mahavishnu-status
- specs+followups: Normalize 4 orphan files (C1.3)
- specs: Bodai plugin standardization design
- specs: Constellation tui three-surface design
- specs: Design for wiring validator into crackerjack + P7 cross-repo expansion
- specs: Mahavishnu acp server design (path A, deferred)
- specs: PyPI auth redesign — replaces recurring publish auth bug class
- Stash-clobber fix plan + rework (R1-R10 critical-blocker fixes)
- Update stale /vishnu-status reference to /mahavishnu:status
- workflows: Archive superseded waves and update their decision Status

### Testing

- cli: Add direct tests for list-sessions and prune-abandoned
- registry: Add edge case coverage + fix corrupt-shape bug

### Internal

- plugin: Normalize mcpServers path to use ./ prefix

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
- core: Add MCPThinClient SQL proxy execute/query
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
- Per-session subprocess pool + crow_terminal\_\* tools
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
- dhara: Extract \_invoke helpers, drop C901 noqa
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
- mcp: Preserve wrapper signature in \_wrap_tool_handler
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
- terminal: Add trailing newline to BACKENDS.md
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
- gitignore: Add *.backup.* and \*.backup.json patterns
- mahavishnu: Migrate mcp-common[treesitter,llm] → dep-groups
- mcp: Switch crow from HTTP to stdio transport
- Remove generic agents covered by mycelium-core plugin
- Remove nanobot/opencode artifacts and clean up root directory
- repo: Untrack 23 .backup.json artifacts and tighten gitignore
- sdd: Smoke test multi-backend PTY
- Skill_map curation + bifrost config template
- Update uv.lock (asteroid typo fix, coverage bump)

## [0.8.0] - 2026-06-20

### Added

- a2a: Add MHV-310/311 error codes and AgentCard model
- Activate crow adapter; add crow-mcp config + runbook; deprecate DebugMonitorWorker
- Add A2AClient, A2AWorker, and registry entry
- Add A2ASettings config models and YAML block
- Add CrowTerminalAdapter backed by crow-mcp PTY toolserver
- Add inbound A2A server routes and bootstrap mount
- Add TUI module with TUI_AVAILABLE, FallbackRichFormatter, get_console
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

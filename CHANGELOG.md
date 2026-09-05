# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
- mahavishnu: Add audit_cli_inventory.py for Core 7 CLI surface audit
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

- **Streaming `tar.zst` worktree bundles** for >100 MB worktrees (replaces the in-memory Phase 2 `tar.gz` path)
- **Bounded queue producer/consumer handoff** in `RemoteWorktreeProvider.fetch` (`queue.Queue(maxsize=4)`) coordinating slow disk + fast network
- **MHV error codes 209–223** for streaming-specific failures (`MHV-209` `TEMP_CREATE_FAILED`, `MHV-210` `TEMP_WRITE_FAILED`, `MHV-211` `PATH_TRAVERSAL`, `MHV-212` `MALFORMED`, `MHV-213` `LEGACY_PHASE2`, `MHV-220` `STORAGE_KEY_TOO_LONG`, `MHV-221` `STOPGAP_TOO_LARGE`, `MHV-222` `NOT_FOUND`, `MHV-223` `CODEC_UNAVAILABLE`)
- **Oneiric `compression-zstd` PEP 735 group** for the `zstandard` streaming codec
- **SHA-256 streaming verification** via `verify_sha256_streaming` (no full-blob in memory) plus `streaming_op_total{op,backend,success}` OTel counter and `streaming_op_duration_seconds{op,backend}` histogram
- **Operator runbook** `docs/runbooks/streaming-tar-rollout.md` and **migration script** `scripts/migrate_to_streaming_tar.py` plus error-severity runbook `docs/runbooks/coordinator-error-severity.md`

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
- mahavishnu: Remove broken image ref from embedding-architecture.md:495
- mahavishnu: Remove decorative diagram blocks from ADR-005 (3 removals)
- mahavishnu: Remove decorative diagram blocks from VISUAL_GUIDE (13 removals)
- mahavishnu: Remove decorative diagram blocks from WORKFLOW_DIAGRAMS (2 removals)
- mahavishnu: Remove embedding-architecture.md duplicates from README/EMBEDDINGS_SETUP_GUIDE (5 removals)
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
- mahavishnu: Rewrite backends.md as live-adapter stub (mcpretentious removed)
- plans: Add bodai-conformance plan + spec to canonical PLAN_INDEX.md
- Refine P0 audit fixes for tool-count, profile wording, and CLI inventory

### Testing

- mcp: Add tool inventory ratchet test (CI guard against count drift)

### Internal

- gitignore: Add .coverage\* + untrack .coverage-ratchet.json (bodai 2026-08-17)
- mahavishnu: Delete archive diagram mirrors (9 files)
- Pin minimax-coding-plan-mcp install args

## [Unreleased]

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

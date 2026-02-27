# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

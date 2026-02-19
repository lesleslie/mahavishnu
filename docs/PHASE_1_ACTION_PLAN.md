# Phase 1 Action Plan: Core Task Management

**Timeline**: 6 weeks (2026-02-18 to 2026-04-01)
**Status**: In Progress
**Depends On**: Phase 0 (Complete ✅)

---

## Week 1: NLP Parser + Accessibility Testing

### Day 1-2: Intent Extraction

- [x] Create `mahavishnu/core/nlp_parser.py`
- [x] Implement intent classification (create, list, update, delete, search)
- [x] Add entity extraction (title, repository, priority, tags)
- [x] Handle natural language variations

**Files**: `mahavishnu/core/nlp_parser.py`, `tests/unit/test_nlp_parser.py`

### Day 3-4: Confidence Scoring

- [x] Implement confidence score calculation
- [x] Add fallback when confidence < 0.8
- [x] Create clarification prompts
- [x] Add unit tests for confidence scoring

**Files**: `mahavishnu/core/nlp_parser.py`

### Day 5: Accessibility Testing Setup

- [x] Create accessibility test suite (CLI-focused)
- [x] Document keyboard navigation requirements
- [x] Set up screen reader testing checklist
- [x] Create GitHub Actions workflow for accessibility tests

**Files**: `tests/accessibility/`, `.github/workflows/accessibility.yml`, `docs/ACCESSIBILITY_CHECKLIST.md`

---

## Week 2: PostgreSQL Migration

### Day 1-2: Database Setup

- [x] Create PostgreSQL schema
- [x] Set up asyncpg connection pooling
- [x] Implement database configuration
- [x] Create Docker Compose for local PostgreSQL

**Files**: `mahavishnu/core/database.py`, `docker-compose.yml`, `migrations/init.sql`, `tests/unit/test_database.py`

### Day 3-4: Migration Scripts

- [x] Create Alembic migration framework
- [x] Write SQLite → PostgreSQL migration
- [x] Implement dual-write strategy (ADR-003)
- [x] Add data validation scripts

**Files**: `migrations/env.py`, `alembic.ini`, `mahavishnu/core/migrator.py`, `tests/unit/test_migrator.py`

### Day 5: Event Sourcing

- [x] Create task event log table (in init.sql)
- [x] Implement event sourcing for task history
- [x] Add event replay capability

**Files**: `mahavishnu/core/event_store.py`, `tests/unit/test_event_store.py`

---

## Week 3: Task CRUD Operations

### Day 1-2: Core CRUD

- [x] Implement TaskStore class
- [x] Create, read, update, delete operations
- [x] Add batch operations
- [x] Implement task relationships (dependencies)

**Files**: `mahavishnu/core/task_store.py`, `tests/unit/test_task_store.py`

### Day 3: Error Messages

- [ ] Implement error messages with recovery guidance
- [ ] Add contextual help for common errors
- [ ] Create error message templates

**Files**: `mahavishnu/core/errors.py` (extend)

### Day 4-5: CLI Shorthands

- [ ] Add command shorthands (mhv tc, mhv ts, etc.)
- [ ] Implement smart defaults
- [ ] Add auto-completion support

**Files**: `mahavishnu/cli.py`

---

## Week 4: Semantic Search

### Day 1-2: Embedding Generation

- [ ] Set up embedding model (Ollama/fastembed)
- [ ] Create embedding generation service
- [ ] Add batch embedding support

**Files**: `mahavishnu/core/embeddings.py`

### Day 3-4: Vector Search

- [ ] Enable pgvector extension
- [ ] Create vector index (HNSW)
- [ ] Implement similarity search
- [ ] Add hybrid search (vector + FTS)

**Files**: `mahavishnu/core/vector_search.py`

### Day 5: Command Palette

- [ ] Implement Ctrl+K fuzzy search
- [ ] Add command categories
- [ ] Create command palette UI

**Files**: `mahavishnu/tui/command_palette.py`

---

## Week 5: Onboarding Flow

### Day 1-2: Interactive Tutorial

- [ ] Create tutorial flow
- [ ] Add step-by-step guidance
- [ ] Implement progress tracking
- [ ] Add skip option

**Files**: `mahavishnu/core/onboarding.py`

### Day 3: Configuration Validation

- [ ] Validate repos.yaml on startup
- [ ] Add helpful error messages
- [ ] Create configuration wizard

**Files**: `mahavishnu/core/config_validator.py`

### Day 4-5: User Testing

- [ ] Recruit 5-10 test users
- [ ] Create testing protocol
- [ ] Document feedback
- [ ] Prioritize improvements

---

## Week 6: UX Polish & Documentation

### Day 1-2: User Testing Fixes

- [ ] Address top 5 issues from testing
- [ ] Improve error handling
- [ ] Polish UI elements

### Day 3: Quick Start Guide

- [ ] Write 5-minute quick start
- [ ] Create demo screencast
- [ ] Add API examples

**Files**: `docs/QUICK_START.md`

### Day 4-5: Final Validation

- [ ] Comprehensive --help command
- [ ] Final accessibility testing
- [ ] Documentation review
- [ ] Phase 1 completion report

---

## Success Criteria

### NLP Parser

- [ ] > 90% intent classification accuracy
- [ ] Confidence scores calibrated
- [ ] Graceful handling of ambiguous input

### PostgreSQL Migration

- [ ] Zero downtime migration
- [ ] Data integrity verified
- [ ] Performance within SLOs

### Semantic Search

- [ ] Search latency < 100ms (P99)
- [ ] Relevance score > 0.8

### Onboarding

- [ ] 80% completion rate
- [ ] < 5 minutes to first task

### Accessibility

- [ ] WCAG 2.1 Level AA compliant
- [ ] Keyboard navigation complete
- [ ] Screen reader compatible

---

## Dependencies

- Phase 0 complete ✅
- PostgreSQL 15+ (for pgvector)
- Ollama or fastembed (for embeddings)
- pa11y (for accessibility testing)

---

## Risks & Mitigations

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| NLP accuracy low | Medium | High | Add training data, use fallback prompts |
| Migration issues | Medium | High | Dual-write strategy, comprehensive validation |
| Embedding latency | Low | Medium | Batch processing, local model |
| User testing delays | Medium | Low | Parallel internal testing |

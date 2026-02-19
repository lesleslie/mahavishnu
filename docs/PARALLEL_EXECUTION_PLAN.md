# Task Orchestration - Parallel Execution Plan

**Created**: 2026-02-18
**Based On**: Master Plan V3
**Strategy**: Maximize parallel execution using Mahavishnu worker pools

---

## Executive Summary

| Metric | Sequential | Parallel | Savings |
|--------|------------|----------|---------|
| **Timeline** | 26-32 weeks | 18-22 weeks | 30-40% |
| **Agent Utilization** | 1 agent | 2-3 agents | 2-3x throughput |
| **Pool Efficiency** | N/A | 80%+ utilization | Maximized |

---

## Phase-by-Phase Parallel Strategy

### Phase 0: Security & SRE Fundamentals ✅ COMPLETE

**Status**: Completed with 219 tests, 4 runbooks, 2 dashboards

---

### Phase 1: Core Implementation (6 weeks → 4 weeks)

#### Week 1-2: Dual-Stream Foundation

```
┌─────────────────────────────────────────────────────────────────┐
│                         WEEK 1-2                                │
├─────────────────────────────────────────────────────────────────┤
│  Stream A (Pool: mahavishnu)    │  Stream B (Pool: mahavishnu) │
│  ─────────────────────────────  │  ─────────────────────────────│
│  Agent: nlp-engineer            │  Agent: postgres-pro          │
│  Task: NLP Parser               │  Task: PostgreSQL Schema      │
│  ─────────────────────────────  │  ─────────────────────────────│
│  • NLP parser implementation    │  • Database schema design     │
│  • Confidence scoring           │  • Migration scripts          │
│  • Intent classification        │  • Connection pooling         │
│  • Entity extraction            │  • Index optimization         │
│                                 │                               │
│  Files:                         │  Files:                       │
│  • core/nlp/parser.py           │  • core/db/schema.py          │
│  • core/nlp/intents.py          │  • core/db/migrations/        │
│  • core/nlp/entities.py         │  • alembic/                   │
└─────────────────────────────────┴───────────────────────────────┘
                        │
                        ▼ (Both streams must complete)
```

**Agent Assignments:**
| Stream | Agent | Model | Skills |
|--------|-------|-------|--------|
| A | nlp-engineer | sonnet | NLP, LLM integration, intent parsing |
| B | postgres-pro | sonnet | PostgreSQL, pgvector, migrations |

**Sync Point**: End of Week 2 - both streams integrate

---

#### Week 3: Sequential Integration (Single Stream)

```
┌─────────────────────────────────────────────────────────────────┐
│                           WEEK 3                                │
├─────────────────────────────────────────────────────────────────┤
│  Stream A (Single Agent - Integration Required)                 │
│  ─────────────────────────────────────────────────────────────  │
│  Agent: python-pro                                              │
│  Task: Task CRUD + Error Handling                               │
│  ─────────────────────────────────────────────────────────────  │
│  • Integrate NLP parser with DB schema                          │
│  • Implement task CRUD operations                               │
│  • Add Pydantic v2 validation                                   │
│  • Error messages with recovery guidance                        │
│  • Command shorthands (mhv tc, mhv ts, etc.)                    │
│                                                                 │
│  Depends on: Week 1-2 Stream A + Stream B outputs               │
└─────────────────────────────────────────────────────────────────┘
```

**Why Sequential**: NLP + DB integration requires single agent to maintain consistency

---

#### Week 4-5: Triple-Stream Feature Development

```
┌─────────────────────────────────────────────────────────────────┐
│                         WEEK 4-5                                │
├─────────────────────────────────────────────────────────────────┤
│  Stream A         │  Stream B         │  Stream C               │
│  (Pool: mahav.)   │  (Pool: mahav.)   │  (Pool: session-buddy)  │
│  ──────────────── │  ──────────────── │  ────────────────────── │
│  Agent: akosha    │  Agent: frontend  │  Agent: ux-researcher   │
│  Task: Semantic   │  Task: Cmd Palette│  Task: Onboarding       │
│  ──────────────── │  ──────────────── │  ────────────────────── │
│  • Embeddings     │  • Ctrl+K search  │  • Interactive tutorial │
│  • Vector search  │  • Fuzzy matching │  • Skip option          │
│  • HNSW indexing  │  • Command cats   │  • Config validation    │
│  • Akosha integ.  │  • Rich output    │  • Error handling       │
│                   │                   │  • User testing prep    │
└───────────────────┴───────────────────┴─────────────────────────┘
```

**Agent Assignments:**
| Stream | Agent | Pool | Rationale |
|--------|-------|------|-----------|
| A | soothsayer (akosha) | mahavishnu | Semantic search expertise |
| B | frontend-developer | mahavishnu | CLI/UX patterns |
| C | ux-researcher | session-buddy | User research + context |

---

#### Week 6: Dual-Stream Polish

```
┌─────────────────────────────────────────────────────────────────┐
│                           WEEK 6                                │
├─────────────────────────────────────────────────────────────────┤
│  Stream A (Pool: mahavishnu)    │  Stream B (Pool: crackerjack) │
│  ─────────────────────────────  │  ─────────────────────────────│
│  Agent: technical-writer        │  Agent: qa-expert             │
│  Task: Documentation            │  Task: Quality Assurance      │
│  ─────────────────────────────  │  ─────────────────────────────│
│  • Quick start guide            │  • Test coverage audit        │
│  • Demo screencast              │  • Accessibility testing      │
│  • API documentation            │  • Security scan              │
│  • Help command polish          │  • Performance benchmarks     │
└─────────────────────────────────┴───────────────────────────────┘
```

---

### Phase 2: Pattern Detection (3 weeks → 2 weeks)

#### Week 7-8: Triple-Stream Analytics

```
┌─────────────────────────────────────────────────────────────────┐
│                         WEEK 7-8                                │
├─────────────────────────────────────────────────────────────────┤
│  Stream A         │  Stream B         │  Stream C               │
│  ──────────────── │  ──────────────── │  ────────────────────── │
│  Agent: data-sci  │  Agent: ml-eng    │  Agent: backend-dev     │
│  Task: Patterns   │  Task: Prediction │  Task: Dependencies     │
│  ──────────────── │  ──────────────── │  ────────────────────── │
│  • Pattern detect │  • Blocker preds  │  • Dependency graph     │
│  • Historical ana │  • Duration estim │  • Circular detection   │
│  • Blocker recurr │  • Task ordering  │  • Visualization        │
│  • Duration calc  │  • Model training │  • Block/unblock logic  │
└───────────────────┴───────────────────┴─────────────────────────┘
```

**Agent Assignments:**
| Stream | Agent | Specialization |
|--------|-------|----------------|
| A | data-scientist | Statistical analysis, pattern detection |
| B | ml-engineer | ML models, predictions |
| C | backend-developer | Graph algorithms, dependencies |

---

### Phase 3: Cross-Repository (3 weeks → 2 weeks)

#### Week 9-10: Triple-Stream Integration

```
┌─────────────────────────────────────────────────────────────────┐
│                         WEEK 9-10                               │
├─────────────────────────────────────────────────────────────────┤
│  Stream A         │  Stream B         │  Stream C               │
│  ──────────────── │  ──────────────── │  ────────────────────── │
│  Agent: fullstack │  Agent: backend   │  Agent: security-aud    │
│  Task: Multi-Repo │  Task: Cross-Deps │  Task: External API     │
│  ──────────────── │  ──────────────── │  ────────────────────── │
│  • Aggregate view │  • Link tasks     │  • GitHub webhooks      │
│  • Filter/tag     │  • Track blocking │  • GitLab webhooks      │
│  • Cross search   │  • Coordinate     │  • Signature validation │
│  • Dashboards     │  • Orchestrate    │  • One-way sync         │
└───────────────────┴───────────────────┴─────────────────────────┘
```

---

### Phase 4: Quality Gates (2 weeks → 1 week)

#### Week 11: Dual-Stream Quality

```
┌─────────────────────────────────────────────────────────────────┐
│                           WEEK 11                               │
├─────────────────────────────────────────────────────────────────┤
│  Stream A (Pool: crackerjack)   │  Stream B (Pool: mahavishnu) │
│  ─────────────────────────────  │  ─────────────────────────────│
│  Agent: qa-expert               │  Agent: git-workflow-mgr      │
│  Task: Crackerjack Integration  │  Task: Worktree Management    │
│  ─────────────────────────────  │  ─────────────────────────────│
│  • MCP client integration       │  • Auto worktree creation     │
│  • Quality gate rules           │  • Lifecycle management       │
│  • Pre-completion validation    │  • Task completion aware      │
│  • Results display              │  • Cleanup automation         │
└─────────────────────────────────┴───────────────────────────────┘
```

---

### Phase 5-6: User Interfaces (7-8 weeks → 5 weeks) ⭐ BIGGEST WIN

#### Week 12-16: Triple-Stream Frontend

```
┌─────────────────────────────────────────────────────────────────┐
│                    WEEK 12-16 (PARALLEL FRONTENDS)              │
├─────────────────────────────────────────────────────────────────┤
│  Stream A         │  Stream B         │  Stream C               │
│  (Pool: mahav.)   │  (Pool: native)   │  (Pool: mahav.)         │
│  ──────────────── │  ──────────────── │  ────────────────────── │
│  Agent: python-pro│  Agent: swift-exp │  Agent: frontend-dev    │
│  Task: TUI        │  Task: SwiftUI    │  Task: CLI Polish       │
│  ──────────────── │  ──────────────── │  ────────────────────── │
│  TECHNOLOGY:      │  TECHNOLOGY:      │  TECHNOLOGY:            │
│  Python/Textual   │  Swift/SwiftUI    │  Python/Typer           │
│  ──────────────── │  ──────────────── │  ────────────────────── │
│  • Split pane     │  • IPC client     │  • Rich formatting      │
│  • Keyboard nav   │  • Unix socket    │  • Progress indicators  │
│  • Theme support  │  • JSON-RPC 2.0   │  • Shell completion     │
│  • Context help   │  • Task views     │  • Alias support        │
│  • Real-time WS   │  • macOS native   │  • Output templates     │
│                   │  • Notifications  │                         │
│                   │  • Offline cache  │                         │
└───────────────────┴───────────────────┴─────────────────────────┘
         │                    │                    │
         │                    │                    │
         ▼                    ▼                    ▼
    Same Backend API ─────────────────────────────────►
```

**Why This Works:**
- TUI (Python) and SwiftUI (Swift) have **ZERO shared code**
- Both consume same FastAPI/WebSocket backend
- Can be developed completely independently
- CLI Polish is independent Python work

**Agent Assignments:**
| Stream | Agent | Technology | Pool |
|--------|-------|------------|------|
| A | python-pro | Textual (Python) | mahavishnu |
| B | swift-expert | SwiftUI (Swift) | native (local) |
| C | frontend-developer | Typer (Python) | mahavishnu |

---

### Phase 7: Performance (2 weeks → 1.5 weeks)

#### Week 17-18: Dual-Stream Optimization

```
┌─────────────────────────────────────────────────────────────────┐
│                        WEEK 17-18                               │
├─────────────────────────────────────────────────────────────────┤
│  Stream A (Pool: mahavishnu)    │  Stream B (Pool: mahavishnu) │
│  ─────────────────────────────  │  ─────────────────────────────│
│  Agent: db-optimizer            │  Agent: sre-engineer          │
│  Task: Query Optimization       │  Task: Load Testing           │
│  ─────────────────────────────  │  ─────────────────────────────│
│  • EXPLAIN ANALYZE              │  • k6 load testing            │
│  • Index optimization           │  • Performance benchmarks     │
│  • N+1 query fixes              │  • Scalability testing        │
│  • Connection pooling           │  • Performance tuning         │
│  • Redis (if needed)            │  • Monitoring setup           │
└─────────────────────────────────┴───────────────────────────────┘
```

---

### Phase 8: Deployment (2 weeks → 1.5 weeks)

#### Week 19-20: Dual-Stream Deployment

```
┌─────────────────────────────────────────────────────────────────┐
│                        WEEK 19-20                               │
├─────────────────────────────────────────────────────────────────┤
│  Stream A (Pool: mahavishnu)    │  Stream B (Pool: crackerjack) │
│  ─────────────────────────────  │  ─────────────────────────────│
│  Agent: devops-engineer         │  Agent: technical-writer      │
│  Task: Production Deploy        │  Task: Documentation          │
│  ─────────────────────────────  │  ─────────────────────────────│
│  • Kubernetes manifests         │  • User documentation         │
│  • Blue-green setup             │  • API documentation          │
│  • Monitoring/alerting          │  • Deployment guides          │
│  • DR testing                   │  • Runbooks (complete)        │
└─────────────────────────────────┴───────────────────────────────┘
```

---

## Timeline Summary

| Phase | Sequential | Parallel | Savings |
|-------|------------|----------|---------|
| Phase 0 | ✅ Done | ✅ Done | - |
| Phase 1 | 6 weeks | 4 weeks | 2 weeks |
| Phase 2 | 3 weeks | 2 weeks | 1 week |
| Phase 3 | 3 weeks | 2 weeks | 1 week |
| Phase 4 | 2 weeks | 1 week | 1 week |
| Phase 5-6 | 7-8 weeks | 5 weeks | 2-3 weeks |
| Phase 7 | 2 weeks | 1.5 weeks | 0.5 weeks |
| Phase 8 | 2 weeks | 1.5 weeks | 0.5 weeks |
| **TOTAL** | **26-32 weeks** | **18-22 weeks** | **8-10 weeks** |

---

## Pool Utilization Strategy

### Pool Assignment by Phase

```
Phase │ Pool              │ Agents │ Utilization
──────┼───────────────────┼────────┼────────────
  1   │ mahavishnu x2     │ 2-3    │ 80%
  2   │ mahavishnu x3     │ 3      │ 90%
  3   │ mahavishnu x3     │ 3      │ 90%
  4   │ mahavishnu x2     │ 2      │ 70%
  5-6 │ mahavishnu x2     │ 3      │ 95%  ← Peak
      │ + native (Swift)  │        │
  7   │ mahavishnu x2     │ 2      │ 70%
  8   │ mahavishnu x1     │ 2      │ 60%
      │ + crackerjack x1  │        │
```

### Pool Types Used

| Pool | Purpose | Agent Count |
|------|---------|-------------|
| `mahavishnu` | Python/backend work | 2-3 workers |
| `session-buddy` | Context-heavy research | 1 worker |
| `crackerjack` | QA/testing tasks | 1 worker |
| `native` (local) | Swift/native work | 1 worker |

---

## Sync Points & Dependencies

```
Week │ Sync Point
─────┼─────────────────────────────────────────────────────────
  2  │ NLP Parser + PostgreSQL Schema → Integration ready
  3  │ Task CRUD complete → Semantic Search can begin
  4  │ All Phase 1 features → Pattern Detection can begin
  6  │ Phase 1 complete → Phase 2 begins
  8  │ Phase 2 complete → Phase 3 begins
 10  │ Phase 3 complete → Phase 4 begins
 11  │ Phase 4 complete → Phase 5-6 begins (PARALLEL FRONTENDS)
 16  │ All frontends complete → Performance optimization
 18  │ Performance validated → Deployment
 20  │ PRODUCTION READY
```

---

## Agent Skill Requirements

### Required Agent Specializations

| Agent | Skills Needed | Current Status |
|-------|---------------|----------------|
| `nlp-engineer` | NLP, intent parsing, LLM integration | ✅ Exists |
| `postgres-pro` | PostgreSQL, pgvector, migrations | ✅ Exists |
| `python-pro` | Python 3.13, Pydantic v2, async | ✅ Exists |
| `frontend-developer` | CLI/UX, Textual, Typer | ✅ Exists |
| `swift-expert` | SwiftUI, macOS native, IPC | ✅ Exists |
| `data-scientist` | Pattern detection, statistics | ✅ Exists |
| `ml-engineer` | ML models, predictions | ✅ Exists |
| `devops-engineer` | K8s, deployment, monitoring | ✅ Exists |
| `technical-writer` | Documentation, guides | ✅ Exists |
| `qa-expert` | Testing, coverage, accessibility | ✅ Exists |

### Recommended New Skills

| Skill | Purpose | Priority |
|-------|---------|----------|
| `swiftui-ipc-client` | Unix socket + JSON-RPC pattern | High |
| `pgvector-semantic-search` | Vector embeddings + HNSW | High |
| `task-orchestration-review` | Cross-component review | Medium |
| `multi-repo-coordination` | Cross-repo task linking | Medium |

---

## Execution Commands

### Start Parallel Execution

```bash
# Phase 1 Week 1-2: Dual stream
mahavishnu pool spawn --type mahavishnu --name nlp-stream --min 1 --max 2
mahavishnu pool spawn --type mahavishnu --name db-stream --min 1 --max 2

# Route tasks to pools
mahavishnu pool route --pool nlp-stream --prompt "Implement NLP parser with confidence scoring..."
mahavishnu pool route --pool db-stream --prompt "Design PostgreSQL schema with pgvector..."
```

### Monitor Parallel Progress

```bash
# Watch all pools
mahavishnu pool health

# Check specific stream
mahavishnu pool execute nlp-stream --prompt "Status check"

# WebSocket monitoring
mahavishnu monitor pools --websocket
```

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Agent conflicts | Clear file boundaries per stream |
| Integration failures | Mandatory sync points |
| Quality variance | Pooled review at phase end |
| Timeline slippage | Buffer week between phases |

---

## Success Criteria

- [ ] All phases complete within 18-22 weeks
- [ ] Pool utilization > 70% average
- [ ] Zero integration failures at sync points
- [ ] All tests passing at each phase boundary
- [ ] Documentation complete at deployment

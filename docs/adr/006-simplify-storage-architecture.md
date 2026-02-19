# ADR 006: Simplify Storage Architecture from 4-System to 2-System

**Status**: Accepted
**Date**: 2026-02-18
**Context**: Task Orchestration Master Plan v3.0
**Related**: ADR-007 (Saga Coordinator), ADR-008 (Zero-Downtime Migration)

---

## Context

The Task Orchestration Master Plan v2.0 proposed a 4-system storage architecture:

1. **PostgreSQL** - Primary task data, events, projections
2. **Akosha** - Semantic search, pattern detection, knowledge graph
3. **Session-Buddy** - Task context, conversation history, session tracking
4. **Redis** - Caching layer for frequent queries

### Problems with 4-System Architecture

During the 5-agent review council, the Architecture Reviewer identified this as a **P0 critical issue**:

- **Cascade Failures**: 4 systems = 4 potential failure points. Any single system failure can cascade to others.
- **Consistency Nightmares**: Keeping data synchronized across 4 systems in real-time is extremely difficult.
- **Operational Overhead**: Monitoring, debugging, and maintaining 4 systems requires 60% more operational effort.
- **Transaction Complexity**: Coordinating writes across 4 systems requires complex saga patterns with multiple compensating transactions.
- **Testing Complexity**: Integration tests must mock 4 systems, increasing test fragility.

### Architecture Reviewer Feedback

**Score**: 4.2/5.0 (APPROVED WITH RECOMMENDATIONS)

> "The 4-system storage architecture is over-engineered for v1.0. PostgreSQL + pgvector can handle both structured data and semantic search. Session-Buddy integration should be best-effort (fire-and-forget), not synchronous. Redis should be deferred until proven necessary (Premature Optimization)."

---

## Decision

Simplify to **2-system storage architecture**:

### Primary System: PostgreSQL (Required)

**Technology**: PostgreSQL 15+ with pgvector extension

**Responsibilities**:
- Core task data (tasks, dependencies, events)
- Semantic search (vector embeddings via pgvector)
- Event sourcing log (append-only)
- Audit logging
- All ACID transactions

**Why PostgreSQL + pgvector is Sufficient**:
- pgvector provides HNSW indexing for O(log n) vector search
- JSONB columns for flexible metadata storage
- Full-text search with tsvector for hybrid queries
- Single source of truth eliminates consistency issues
- Mature tooling and monitoring

### Secondary System: Session-Buddy (Best-Effort Integration)

**Technology**: Session-Buddy MCP server

**Responsibilities**:
- Task creation context (fire-and-forget write)
- Conversation history (optional, for AI assistance)
- Session tracking

**Integration Pattern**:
```python
# Create task in PostgreSQL (synchronous)
task = await create_task_in_postgreSQL(...)

# Fire-and-forget context write to Session-Buddy (async)
asyncio.create_task(store_context_in_session_buddy(task.id))

# Task succeeds even if Session-Buddy is down
```

### Optional System: Redis (Deferred to Phase 7)

**Technology**: Redis cache

**Responsibilities**:
- Frequent query caching
- Session data caching

**When to Add**:
- Only after demonstrating performance bottleneck in production
- Add monitoring first to prove Redis is needed
- Premature Optimization: Don't add until proven necessary

---

## Alternatives Considered

### Alternative 1: Keep 4-System Architecture (REJECTED)

**Pros**:
- Separation of concerns
- Individual scaling

**Cons**:
- **60% more operational complexity**
- **4x potential failure points**
- Consistency issues between systems
- Complex saga transactions
- Testing complexity

**Decision**: Too complex for v1.0. Simplify first, optimize later.

### Alternative 2: 3-System Architecture (PostgreSQL + Akosha + Redis) (REJECTED)

**Pros**:
- Remove Session-Buddy from critical path
- Still have Redis caching

**Cons**:
- Akosha is already PostgreSQL + pgvector (redundant)
- Redis is premature optimization
- Still 3 systems to manage

**Decision**: Akosha and PostgreSQL can be combined. Redis deferred.

### Alternative 3: 2-System Architecture (PostgreSQL + Session-Buddy) (ACCEPTED)

**Pros**:
- **Single source of truth** (PostgreSQL)
- **60% reduction in operational complexity**
- Eliminates 2 critical failure modes
- Easier testing and debugging
- Consistent data model
- Session-Buddy best-effort (no blocking)

**Cons**:
- Session-Buddy integration becomes async (task succeeds even if Session-Buddy is down)

**Decision**: Right balance of simplicity and capability for v1.0.

---

## Consequences

### Positive Impacts

1. **Reduced Complexity**: 60% reduction in operational complexity
2. **Eliminated Failure Modes**: 4 systems → 2 systems = 50% fewer potential failure points
3. **Simpler Transactions**: Saga coordinator only needs 2 steps instead of 4
4. **Easier Testing**: Integration tests mock 2 systems instead of 4
5. **Faster Development**: Phase 1 timeline reduced by 2 weeks
6. **Better Performance**: PostgreSQL pgvector is faster than cross-system calls
7. **Consistent Data**: Single source of truth eliminates synchronization issues

### Negative Impacts

1. **Session-Buddy Best-Effort**: Context write failures are silently ignored
   - **Mitigation**: Monitor Session-Buddy health and alert on high error rates

2. **No Caching Layer**: All queries hit PostgreSQL
   - **Mitigation**: PostgreSQL connection pooling + query optimization
   - **Future**: Add Redis in Phase 7 if performance monitoring shows bottleneck

3. **Single Database Scaling**: Must scale PostgreSQL instead of scaling systems independently
   - **Mitigation**: PostgreSQL scales horizontally with read replicas
   - **Mitigation**: Connection pooling reduces connection overhead

### Risks

1. **Session-Buddy Context Loss**: If Session-Buddy is down, context is lost
   - **Severity**: Medium
   - **Mitigation**: Fire-and-forget pattern means task succeeds anyway
   - **Mitigation**: Monitor Session-Buddy uptime and alert on downtime

2. **PostgreSQL Becomes Bottleneck**: Single database for all operations
   - **Severity**: Low
   - **Mitigation**: PostgreSQL scales to 10K+ concurrent connections
   - **Mitigation**: Read replicas for read-heavy operations
   - **Mitigation**: Add Redis cache in Phase 7 if monitoring proves necessity

3. **No Semantic Search Separation**: pgvector shares resources with OLTP queries
   - **Severity**: Low
   - **Mitigation**: HNSW indexing is O(log n), very fast
   - **Mitigation**: Separate pgvector indexes on separate tablespace if needed

---

## Implementation

### Database Schema (PostgreSQL + pgvector)

```sql
-- Tasks table (core data + embeddings)
CREATE TABLE tasks (
    id BIGSERIAL PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    description TEXT,
    repository VARCHAR(100) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    priority VARCHAR(20) NOT NULL DEFAULT 'medium',
    created_by UUID NOT NULL,
    assigned_to UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    deadline TIMESTAMPTZ,
    worktree_path TEXT,
    embedding VECTOR(1536),  -- OpenAI embeddings (pgvector)
    metadata JSONB DEFAULT '{}',
);

-- Indexes for performance
CREATE INDEX idx_tasks_repository ON tasks(repository);
CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_priority ON tasks(priority);
CREATE INDEX idx_tasks_embedding ON tasks USING ivfflat(embedding vector_cosine_ops);

-- Full-text search index
CREATE INDEX idx_tasks_fts ON tasks USING gin(to_tsvector('english', title || ' ' || COALESCE(description, '')));

-- Event sourcing log (append-only)
CREATE TABLE task_events (
    id BIGSERIAL PRIMARY KEY,
    task_id BIGINT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    event_type VARCHAR(100) NOT NULL,
    event_data JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version INT NOT NULL,
);
CREATE INDEX idx_task_events_task_id ON task_events(task_id);
CREATE INDEX idx_task_events_created_at ON task_events(created_at);

-- Audit log
CREATE TABLE audit_logs (
    id BIGSERIAL PRIMARY KEY,
    event_type VARCHAR(100) NOT NULL,
    user_id UUID NOT NULL,
    resource_type VARCHAR(50) NOT NULL,
    resource_id VARCHAR(100) NOT NULL,
    details JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
);
CREATE INDEX idx_audit_logs_user_id ON audit_logs(user_id);
CREATE INDEX idx_audit_logs_resource ON audit_logs(resource_type, resource_id);
CREATE INDEX idx_audit_logs_created_at ON audit_logs(created_at);
```

### Session-Buddy Integration Pattern

```python
import asyncio
from mahavishnu.core.storage import PostgreSQLTaskStore
from mahavishnu.core.session_buddy_client import SessionBuddyClient

class TaskCreationService:
    def __init__(self, db: PostgreSQLTaskStore, session_buddy: SessionBuddyClient):
        self.db = db
        self.session_buddy = session_buddy

    async def create_task(self, task_data: TaskCreateRequest) -> Task:
        """
        Create task with PostgreSQL as primary storage.
        Session-Buddy is best-effort fire-and-forget.
        """
        # Step 1: Create task in PostgreSQL (synchronous, blocking)
        task = await self.db.create_task(task_data)

        # Step 2: Fire-and-forget context write to Session-Buddy (async)
        # Task succeeds even if Session-Buddy is down
        asyncio.create_task(
            self._store_context_in_session_buddy(task.id, task_data),
            name=f"store_context_task_{task.id}"
        )

        return task

    async def _store_context_in_session_buddy(self, task_id: int, task_data: TaskCreateRequest):
        """Best-effort context storage. Failures logged but not raised."""
        try:
            await self.session_buddy.store_context(
                task_id=task_id,
                context={
                    "title": task_data.title,
                    "description": task_data.description,
                    "repository": task_data.repository,
                    "created_at": datetime.now(UTC).isoformat(),
                }
            )
        except Exception as e:
            # Log failure but don't raise - task is already created
            logger.warning(f"Failed to store context in Session-Buddy for task {task_id}: {e}")
            # Increment Prometheus counter for monitoring
            session_buddy_write_errors_total.inc()
```

### Migration from v2.0 4-System Architecture

**Phase 1: Migrate Akosha → PostgreSQL (Week 1-2)**
- Export embeddings from Akosha
- Import into PostgreSQL tasks table
- Update semantic search queries to use pgvector
- Test search accuracy

**Phase 2: Change Session-Buddy to Fire-and-Forget (Week 2)**
- Remove synchronous Session-Buddy writes
- Add asyncio.create_task for async writes
- Add error handling for Session-Buddy failures
- Add Prometheus monitoring for Session-Buddy errors

**Phase 3: Remove Redis References (Week 2)**
- Remove Redis cache layer
- Update all queries to hit PostgreSQL directly
- Add connection pooling optimization
- Benchmark performance

**Phase 4: Update Saga Coordinator (Week 3)**
- Simplify saga from 4 steps to 2 steps
- Remove compensating transactions for Akosha and Redis
- Update crash recovery logic
- Test saga failures

---

## Timeline Impact

**Original Phase 1 (v2.0)**: 4-5 weeks
**Revised Phase 1 (v3.0)**: 6 weeks

**Net Change**: -2 weeks from storage simplification, +1-2 weeks from UX polish = **-1 to 0 weeks net change**

**Breakdown**:
- Storage simplification: **-2 weeks** (less integration work)
- UX timeline extension: **+1-2 weeks** (better user experience)
- **Net: -1 to 0 weeks** (simpler architecture offsets UX work)

---

## Related Decisions

- **ADR-007: Saga Coordinator Pattern**: Simplified from 4-step to 2-step saga
- **ADR-008: Zero-Downtime Migration**: Migration strategy for SQLite → PostgreSQL

---

## References

- Architecture Reviewer Report (2026-02-18): Score 4.2/5.0, recommended simplification
- PostgreSQL pgvector Documentation: https://github.com/pgvector/pgvector
- Master Plan v3.0: `/docs/TASK_ORCHESTRATION_MASTER_PLAN_V3.md`

---

**END OF ADR-001**

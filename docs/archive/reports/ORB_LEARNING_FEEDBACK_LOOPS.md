# ORB Learning Feedback Loops - Design Plan

**Status**: Design Phase - Gathering Requirements
**Created**: 2026-02-09
**Type**: Architecture Enhancement

---

## Context

The ORB (Omniscient Runtime Brain) ecosystem already has sophisticated components:
- **Mahavishnu**: Orchestrator with model routing, pools, swarm coordination
- **Session-Buddy**: Memory and session management
- **Akosha**: Analytics and pattern detection
- **Crackerjack**: Quality control and CI/CD

**Problem**: These components operate largely independently. There's no automated feedback loop that learns from execution and improves future decisions.

**Opportunity**: Add interconnected learning layers that enable ORB to continuously improve based on:
1. Historical execution patterns
2. Cross-project knowledge synthesis
3. Adaptive quality thresholds
4. Explicit user feedback

**Goal**: Transform ORB from a sophisticated orchestrator into a self-improving system that gets smarter with every task.

---

## Proposed Architecture (4 Learning Layers)

### Layer 1: Execution Intelligence
**Built on**: Mahavishnu's existing routing/pools/swarm systems

**What it learns**:
- Which model tier works best for specific task types
- Which pool topology is fastest for different workloads
- Which swarm consensus protocol minimizes failures

**Feedback mechanisms**:
- Capture execution metrics (success rate, latency, cost) per task
- Compare predicted vs. actual performance
- Auto-tune routing thresholds based on history

### Layer 2: Knowledge Synthesis
**Built on**: Session-Buddy's memory + Akosha's analytics

**What it learns**:
- Reusable solutions across sessions ("this auth pattern worked 3 times")
- Error → solution mappings ("E0277 in Rust → use Arc not Rc")
- Cross-project patterns detected by Akosha

**Feedback mechanisms**:
- Extract successful patterns from session data
- Build solution library indexed by error/task type
- Suggest proven solutions from similar contexts

### Layer 3: Adaptive Quality
**Built on**: Crackerjack's quality gates

**What it learns**:
- Project maturity level (new vs. stable)
- Historical failure rates per check type
- Optimal coverage thresholds per project stage

**Feedback mechanisms**:
- Adjust strictness based on project track record
- Streamline checks for high-success-rate projects
- Focus scrutiny on error-prone areas

### Layer 4: Feedback Integration
**New capability** across all CLI/MCP interfaces

**What it captures**:
- Explicit user feedback ("this suggestion was perfect")
- Implicit feedback (user accepted vs. rejected recommendations)
- Context (task type, repo, urgency)

**Feedback mechanisms**:
- Add feedback capture points to CLI/MCP tools
- Weight feedback by source (trusted users count more)
- Use reinforcement learning to adjust policies

---

## Implementation Phases

### Phase 1: Execution Intelligence (Weeks 1-2)
**Focus**: Mahavishnu routing and pool selection

**Deliverables**:
1. Execution telemetry capture in Mahavishnu
2. Historical performance database
3. Auto-tuning for model router
4. Pool selection optimization

**Files to modify**:
- `mahavishnu/core/adapters/` - Add telemetry hooks
- `mahavishnu/pools/` - Track pool performance metrics
- `settings/mahavishnu.yaml` - Add learning config section

### Phase 2: Knowledge Synthesis (Weeks 3-4)
**Focus**: Session-Buddy + Akosha integration

**Deliverables**:
1. Pattern extraction from session data
2. Solution library with semantic search
3. Cross-project pattern detection
4. Automatic insight generation

**Files to modify**:
- `session-buddy/` - Add pattern extraction
- `akosha/` - Enhance semantic search for solutions
- `mahavishnu/mcp/tools/` - Add solution recommendation tools

### Phase 3: Adaptive Quality (Weeks 5-6)
**Focus**: Crackerjack quality gate optimization

**Deliverables**:
1. Project maturity assessment
2. Dynamic quality thresholds
3. Risk-based test coverage requirements
4. Streamlined workflows for stable projects

**Files to modify**:
- `crackerjack/` - Add adaptive quality logic
- `mahavishnu/` - Project maturity tracking

### Phase 4: Feedback Integration (Weeks 7-8)
**Focus**: User feedback capture and reinforcement

**Deliverables**:
1. Feedback capture UI/CLI hooks
2. Feedback aggregation and weighting
3. Policy adjustment engine
4. A/B testing framework for improvements

**Files to modify**:
- `mahavishnu/cli.py` - Add feedback commands
- All MCP tool definitions - Add feedback parameters
- New: `mahavishnu/learning/feedback/` - Feedback processing

---

## Open Questions

- ✅ **Feedback privacy**: Resolved - Opt-in attribution (user chooses anonymity)
- What should be the minimum data retention period for learning?
- Should learning be opt-in or opt-out for privacy?
- How do we handle conflicting feedback from different users?
- Should learned patterns be shared across all repos or kept isolated?

---

## Agent Consultant Panel (7 Perspectives)

Before implementation, these specialists will review the design:

1. **Backend Architect** ✅ (User priority)
   - Review: Data structures, storage efficiency, query performance
   - Focus: Learning database schema, analytics pipeline design

2. **UX Designer** ✅ (User priority)
   - Review: Feedback capture mechanisms, dashboard usability
   - Focus: Make feedback feel natural, not burdensome

3. **DevOps/SRE Engineer**
   - Review: Production deployment, monitoring, observability
   - Focus: Health checks, performance metrics, rollback strategies

4. **Security Auditor**
   - Review: Feedback system vulnerabilities, data sanitization
   - Focus: Prevent feedback injection, ensure data isolation

5. **QA/Test Engineer**
   - Review: Testing strategy for adaptive/learning systems
   - Focus: How to test non-deterministic behavior, A/B testing

6. **Product Manager**
   - Review: Success metrics, incremental rollout
   - Focus: How to measure learning effectiveness, user value

7. **Data Scientist / ML Engineer**
   - Review: Reinforcement learning approach, model validation
   - Focus: Algorithm selection, bias detection, cold-start problem

---

## Technical Implementation Details

### Data Flow Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     ORB Learning Feedback Loops                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │   EXECUTION  │    │   KNOWLEDGE  │    │   QUALITY    │      │
│  │INTELLIGENCE  │───▶│  SYNTHESIS   │◀───│   ADAPTIVE   │      │
│  │              │    │              │    │              │      │
│  │ • Track      │    │ • Extract    │    │ • Maturity   │      │
│  │   success    │    │   patterns   │    │   scoring    │      │
│  │ • Auto-tune  │    │ • Build      │    │ • Dynamic    │      │
│  │   routing    │    │   solutions  │    │   gates      │      │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘      │
│         │                   │                   │               │
│         └───────────────────┼───────────────────┘               │
│                             ▼                                   │
│                    ┌──────────────┐                             │
│                    │   FEEDBACK   │                             │
│                    │  INTEGRATION │                             │
│                    │              │                             │
│                    │ • Capture    │                             │
│                    │ • Weight     │                             │
│                    │ • Reinforce  │                             │
│                    └──────────────┘                             │
│                             │                                   │
│                             ▼                                   │
│                    ┌──────────────┐                             │
│                    │   LEARNING   │                             │
│                    │  DATABASE    │                             │
│                    │              │                             │
│                    │ • Executions │                             │
│                    │ • Solutions  │                             │
│                    │ • Feedback   │                             │
│                    │ • Policies   │                             │
│                    └──────────────┘                             │
└─────────────────────────────────────────────────────────────────┘
```

### Key Data Structures

**Execution Record**:
```python
{
  "task_id": "uuid",
  "timestamp": "2026-02-09T10:30:00Z",
  "task_type": "refactor",
  "repo": "mahavishnu",
  "model_tier": "medium",
  "pool_type": "session-buddy",
  "swarm_topology": "mesh",
  "success": true,
  "duration_seconds": 45,
  "cost_estimate": 0.003,
  "actual_cost": 0.003,
  "quality_score": 92,
  "user_feedback": {...}  # Optional, opt-in attribution
}
```

**Solution Pattern**:
```python
{
  "pattern_id": "uuid",
  "extracted_at": "2026-02-09T10:30:00Z",
  "task_context": "authentication implementation",
  "solution_summary": "JWT + refresh tokens",
  "success_rate": 0.89,
  "usage_count": 23,
  "repos_used_in": ["mahavishnu", "fastblocks", "session-buddy"],
  "code_snippets": [...],
  "tags": ["auth", "jwt", "security"],
  "confidence_score": 0.94
}
```

**Feedback Record** (opt-in attribution):
```python
{
  "feedback_id": "uuid",
  "task_id": "uuid",
  "timestamp": "2026-02-09T10:35:00Z",
  "feedback_type": "thumbs_up|thumbs_down|rating|comment",
  "rating": 5,  # 1-5 scale
  "comment": "Perfect model choice for this task",
  "user_id": null,  # null = anonymous, or user UUID
  "context": {
    "task_type": "refactor",
    "model_tier": "medium",
    "suggestion_accepted": true
  }
}
```

### MCP Tool Enhancements

All existing MCP tools will accept optional feedback parameter:

```python
@mcp.tool()
async def pool_execute(
    pool_id: str,
    prompt: str,
    feedback: Optional[FeedbackDict] = None  # NEW
) -> ExecutionResult:
    """Execute task on pool with optional feedback capture."""
    result = await pool_manager.execute(pool_id, prompt)

    if feedback:
        await learning_system.record_feedback(
            task_id=result.task_id,
            feedback=feedback
        )

    return result
```

---

**Next Steps**: Present to agent panel for review, then begin implementation

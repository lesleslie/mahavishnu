______________________________________________________________________

## title: Plan-Then-Execute Feature Development category: feature/ status: active owner: orchestration last_reviewed: 2025-01-15 risk_level: low

# Plan-Then-Execute Workflow

This workflow implements the **Plan-Then-Execute Pattern** for complex feature development, ensuring thorough planning before execution and maintaining clear phase separation throughout implementation.

## When to Use This Workflow

Use this workflow for:

- ✅ Multi-file refactoring affecting 3+ files
- ✅ Architecture changes requiring structural modifications
- ✅ Complex features with multiple components
- ✅ Performance optimization across systems
- ✅ Integration tasks connecting multiple systems
- ✅ Migration tasks from one approach to another

**Do NOT use for:**

- ❌ Simple single-file fixes (use domain specialist directly)
- ❌ Straightforward bug fixes (use debugging specialist)
- ❌ Simple feature additions (use domain specialist directly)
- ❌ Questions or explanations (use domain specialist directly)

## Workflow Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Planning Phase                            │
│  orchestration-specialist (Opus)                            │
│  • Analyze requirements                                      │
│  • Explore codebase                                          │
│  • Design solution architecture                              │
│  • Create detailed implementation plan                       │
│  • Identify risks and mitigations                            │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
                    ┌───────────────┐
                    │ Approval Gate  │
                    │  User confirms │
                    │  "Proceed"     │
                    └───────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                  Execution Phase                             │
│  Task agents assigned by orchestration-specialist            │
│                                                             │
│  1. Analysis Phase → 2. Design Phase → 3. Implementation   │
│     ↓ Complete        ↓ Complete           ↓ Complete       │
│  4. Testing Phase → 5. Documentation Phase                  │
│     ↓ Complete           ↓ Complete                           │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    Review Phase                              │
│  orchestration-specialist (Opus)                            │
│  • Compare outcomes to plan                                 │
│  • Capture successful patterns                               │
│  • Document deviations and reasons                           │
│  • Feed learnings back to planning knowledge                 │
└─────────────────────────────────────────────────────────────┘
```

## Phase 1: Planning

**Agent**: `orchestration-specialist` (Opus)

**Duration**: Typically 30-90 minutes depending on complexity

**Tasks**:

### 1. Requirements Analysis

- Understand the problem statement deeply
- Identify explicit and implicit requirements
- Clarify ambiguities before proceeding
- Gather constraints (technical, time, resource)
- Document acceptance criteria

### 2. Current State Analysis

- Explore the codebase thoroughly
- Identify relevant files and components
- Understand existing patterns and conventions
- Assess technical debt and complexity
- Map dependencies and interactions

### 3. Solution Architecture Design

- Design solution architecture
- Identify multiple approaches when applicable
- Evaluate trade-offs of each approach
- Select optimal approach with clear rationale
- Document why other approaches were not chosen

### 4. Implementation Planning

- Break down into 5 discrete phases (Analysis, Design, Implementation, Testing, Documentation)
- Create detailed step-by-step plan
- Estimate complexity and duration for each phase
- Identify dependencies between phases
- Sequence phases optimally

### 5. Risk Assessment

- Identify technical risks (performance, security, compatibility)
- Identify dependency risks (external services, libraries)
- Plan specific mitigations for each risk
- Provide contingency plans
- Assess overall risk level

**Output**: Comprehensive implementation plan document including:

- Problem statement and requirements
- Current state analysis
- Solution architecture with rationale
- Detailed phase breakdown with estimates
- Risk assessment with mitigations
- Success criteria
- Timeline estimates

## Approval Gate

**CRITICAL**: Execution MUST NOT proceed without explicit approval.

**Process**:

1. Present the plan clearly and concisely
1. Explain approach and rationale
1. Highlight why this approach was chosen
1. Discuss alternatives considered
1. Identify risks and planned mitigations
1. Provide realistic timeline estimates
1. Wait for user questions and concerns
1. Address feedback and revise plan if needed
1. **Wait for explicit "proceed", "approved", or "start" signal**

**Valid Approval Signals**:

- "Proceed" / "Approved" / "Start"
- "Looks good, go ahead"
- "Plan approved"

**Invalid Signals** (MUST wait for clearer approval):

- "OK" (ambiguous)
- "Thanks" (not approval)
- [Silence] (not approval)
- "Interesting" (not approval)

**If Feedback Provided**:

- Revise plan based on user feedback
- Present updated plan
- Explain changes and rationale
- Wait for approval again

**What to Say**:

```
**Implementation Plan: [Feature Name]**

[Present plan sections]

**Estimated Timeline**: [X hours]

**Risk Level**: [Low/Medium/High]

**Success Criteria**:
- [Criteria 1]
- [Criteria 2]
- [Criteria 3]

Do you approve this plan? I can adjust based on your feedback.
```

## Phase 2: Execution

**Agent**: Domain specialists assigned by `orchestration-specialist`

**Duration**: Variable based on plan estimates (typically 2-8 hours)

**The 5 Discrete Phases**:

### Phase 2.1: Analysis Phase

**Goal**: Deep understanding of specific problem areas

**Tasks**:

- Perform detailed analysis of problem
- Gather specific requirements for each component
- Identify edge cases and boundary conditions
- Understand integration points
- Document analysis findings

**Completion Criteria**:

- ✅ Problem fully understood and documented
- ✅ All requirements captured
- ✅ Edge cases identified
- ✅ Integration points mapped

**Checkpoint**:

- Verify analysis completeness
- Review findings for accuracy
- Get confirmation before proceeding

**Typical Duration**: 30-60 minutes

### Phase 2.2: Design Phase

**Goal**: Create detailed solution design

**Tasks**:

- Design data structures, algorithms, APIs
- Plan implementation details
- Consider error handling strategies
- Design testing approach
- Document design decisions

**Completion Criteria**:

- ✅ Design fully specified
- ✅ Implementation approach clear
- ✅ Error handling planned
- ✅ Test strategy defined

**Checkpoint**:

- Verify design completeness
- Review design decisions
- Get confirmation before implementing

**Typical Duration**: 45-90 minutes

### Phase 2.3: Implementation Phase

**Goal**: Write code following design

**Tasks**:

- Implement according to design
- Follow code quality standards
- Write clean, maintainable code
- Add appropriate error handling
- Follow project conventions

**Completion Criteria**:

- ✅ Implementation complete per design
- ✅ Code follows quality standards
- ✅ Error handling in place
- ✅ No obvious bugs or issues

**Checkpoint**:

- Verify implementation completeness
- Code review for quality
- Get confirmation before testing

**Typical Duration**: 1-3 hours

### Phase 2.4: Testing Phase

**Goal**: Verify implementation correctness

**Tasks**:

- Write comprehensive tests
- Test happy paths
- Test edge cases
- Test error conditions
- Verify against requirements

**Completion Criteria**:

- ✅ All tests passing
- ✅ Edge cases covered
- ✅ Error conditions tested
- ✅ Requirements verified

**Checkpoint**:

- Verify test coverage
- Run full test suite
- Get confirmation before documenting

**Typical Duration**: 30-90 minutes

### Phase 2.5: Documentation Phase

**Goal**: Document changes and rationale

**Tasks**:

- Document what was changed and why
- Update relevant documentation
- Create usage examples if applicable
- Document API changes if any
- Update README or guides as needed

**Completion Criteria**:

- ✅ Changes documented
- ✅ Rationale explained
- ✅ Examples provided (if applicable)
- ✅ Related docs updated

**Checkpoint**:

- Verify documentation completeness
- Review for clarity and accuracy
- Final sign-off

**Typical Duration**: 30-60 minutes

**Phase Transition Rules**:

- ✅ Complete one phase fully before starting next
- ✅ Verify completion at checkpoint
- ✅ Get confirmation before proceeding
- ❌ Never work on multiple phases simultaneously
- ❌ Never skip phases to save time

## Phase 3: Review

**Agent**: `orchestration-specialist` (Opus)

**Duration**: 15-30 minutes

**Tasks**:

### 1. Outcome Comparison

- Compare actual outcomes to planned outcomes
- Identify deviations from plan
- Analyze reasons for deviations (technical, estimation, scope changes)
- Assess overall success against criteria

### 2. Pattern Capture

- Identify successful patterns used
- Document what worked well
- Note reusable solutions for future
- Capture anti-patterns to avoid

### 3. Lessons Learned

- Identify what could have been better
- Note inefficiencies or bottlenecks
- Suggest process improvements
- Document estimation improvements

### 4. Knowledge Feeding

- Feed learnings back into planning knowledge
- Update risk assessments for similar tasks
- Improve estimation accuracy
- Enhance future planning quality

**Output**: Post-execution review document including:

- Summary of what was accomplished
- Timeline comparison (planned vs actual)
- Complexity comparison (planned vs actual)
- Successful patterns to reuse
- Lessons learned
- Improvement suggestions

## Example Usage

**User Request**: "Add caching to session-buddy to improve performance"

**Planning Phase Output**:

```
**Implementation Plan: Caching Layer for Session-Buddy**

**Problem**: Session-buddy performs repeated database queries for reflection
data, causing performance bottlenecks.

**Requirements**:
- Reduce database query load by 70%+
- Maintain cache coherency
- Add minimal latency overhead
- Keep memory usage reasonable

**Current State Analysis**:
- 23 reflection query functions identified
- 12 pattern query functions identified
- Average query time: 150ms
- Query patterns: mostly reads, infrequent writes

**Solution Architecture**:
- Add LRU caching layer with cachegrab wrapper
- Cache reflection queries (TTL: 5 minutes)
- Cache pattern queries (TTL: 15 minutes)
- SHA-256 cache keys from query parameters
- LRU eviction: max 1000 entries
- Write-through cache on updates

**Rationale**:
- Chose LRU over FIFO: better hit rate for access patterns
- Chose 5min TTL: balances freshness vs performance
- Chose SHA-256 keys: prevents collisions, deterministic

**Phase Breakdown**:
1. Analysis Phase (30 min): Profile query patterns, identify hotspots
2. Design Phase (45 min): Design cache interface, invalidation strategy
3. Implementation Phase (2 hours): Implement caching layer, wrapper
4. Testing Phase (1 hour): Test cache hit/miss, invalidation, coherency
5. Documentation Phase (30 min): Document cache usage, configuration

**Risk Assessment**:
- Cache coherency (Medium): Mitigated with TTL + write-through
- Memory usage (Low): Mitigated with LRU eviction, 1000 entry limit
- Testing complexity (Low): Mitigated with comprehensive test suite

**Timeline**: ~4.5 hours total

**Success Criteria**:
- 70%+ reduction in database queries
- <50ms cache hit response time
- No stale data issues
- Memory usage <100MB

**Risk Level**: Low

Do you approve this plan? I can adjust based on your feedback.
```

**After User Approval**: "Plan approved. Starting execution."

**Execution Phase**:

```
**Phase 1: Analysis Phase** ✅ Complete
- Profiled all 35 query functions
- Identified 8 hotspot functions (80% of queries)
- Measured baseline: 45 queries/second avg

Phase 1 Complete. Proceeding to Design Phase.

**Phase 2: Design Phase** ✅ Complete
- Designed cachegrab wrapper interface
- Specified cache key generation (SHA-256)
- Planned TTL strategy (5min reflections, 15min patterns)
- Designed write-through invalidation

Phase 2 Complete. Proceeding to Implementation Phase.

**Phase 3: Implementation Phase** ✅ Complete
- Implemented LRU cache with cachegrab
- Created cache wrapper for 35 functions
- Added cache statistics tracking
- Implemented write-through invalidation

Phase 3 Complete. Proceeding to Testing Phase.

**Phase 4: Testing Phase** ✅ Complete
- Test cache hits: 92% hit rate achieved
- Test cache misses: proper fallback to DB
- Test TTL: entries expire at expected times
- Test invalidation: writes propagate correctly
- Test memory: LRU eviction works, 87MB max usage

All tests passing (47/47).

Phase 4 Complete. Proceeding to Documentation Phase.

**Phase 5: Documentation Phase** ✅ Complete
- Updated session_buddy/cache.py docstrings
- Added cache configuration guide
- Created usage examples
- Updated performance benchmarks

Documentation complete.
```

**Review Phase Output**:

```
**Post-Execution Review: Caching Layer**

**Summary**: Successfully implemented LRU caching layer for session-buddy,
achieving all success criteria.

**Timeline Comparison**:
- Planned: 4.5 hours
- Actual: 5.2 hours (+36 min)
- Analysis: +15 min (more profiling than expected)
- Implementation: +20 min (added cache stats feature)
- Testing: +10 min (expanded test coverage)
- Documentation: -10 min (faster than expected)

**Complexity Comparison**:
- Planned: Medium complexity
- Actual: Medium complexity (as expected)
- No major surprises or blockers

**Successful Patterns**:
1. cachegrab wrapper pattern - easy cache integration
2. SHA-256 cache keys - prevents collisions effectively
3. TTL + write-through - excellent cache coherency
4. LRU eviction - good memory control

**Lessons Learned**:
1. Initial profiling took longer than estimated (worth the time)
2. Cache statistics feature was unplanned but valuable
3. TTL of 5min is good, could try 7min for more hits
4. 1000 entry limit is conservative, could be 1500

**Deviations from Plan**:
- Added cache statistics tracking (unplanned feature)
- Expanded test coverage for edge cases (good decision)
- Spent more time on profiling (improved cache design)

**Improvement Suggestions**:
1. Consider cache warming on startup
2. Add cache metrics to monitoring dashboard
3. Experiment with longer TTLs for patterns
4. Document cache tuning guidelines

**Next Steps**:
- Monitor cache performance in production
- Consider cache warming for frequent queries
- Add metrics to health check endpoint
```

## Integration with Multi-Stage Code Review

This workflow integrates with the multi-stage code review workflow:

1. **After Implementation Phase**: Run security, performance, test, and documentation reviews
1. **Address Findings**: Fix any issues identified in reviews
1. **Proceed to Testing**: Only after review issues addressed

## Quality Checks

Throughout execution, maintain quality standards:

**Code Quality**:

- Follow crackerjack style guidelines
- Maintain type hints and docstrings
- Write clean, readable code
- Follow project conventions

**Testing Quality**:

- Comprehensive test coverage
- Test edge cases and error conditions
- Verify against requirements
- Ensure all tests pass

**Documentation Quality**:

- Clear explanations of changes
- Rationale for design decisions
- Usage examples where applicable
- Update related documentation

## Success Metrics

Track these metrics to assess workflow effectiveness:

**Planning Metrics**:

- Plan accuracy (timeline, complexity)
- Risk identification quality
- Alternative considerations

**Execution Metrics**:

- Phase completion rate
- Checkpoint effectiveness
- Issues caught at checkpoints

**Outcome Metrics**:

- Requirements satisfaction
- Quality standards met
- Timeline adherence
- Lessons captured

## Troubleshooting

**Common Issues**:

**Issue**: Plan changes significantly during execution
**Solution**: Re-enter planning phase, create updated plan, get approval again

**Issue**: Phase takes longer than estimated
**Solution**: Document delay, update remaining estimates, continue (unless major)

**Issue**: Discovery of new requirements mid-execution
**Solution**: Stop execution, update plan with new requirements, get approval

**Issue**: Technical blocker encountered
**Solution**: Document blocker, propose solutions, wait for guidance on approach

## Best Practices

1. **Thorough Planning**: Invest time in planning to save time in execution
1. **Clear Communication**: State which phase you're in explicitly
1. **Checkpoint Discipline**: Never skip checkpoints, always verify completion
1. **Quality Over Speed**: Don't rush phases to save time
1. **Honest Reporting**: Report issues and delays immediately, don't hide them
1. **Pattern Capture**: Always capture successful patterns for reuse
1. **Learning Focus**: Treat every task as learning opportunity

## Related Workflows

- `/workflows/multi-stage-code-review.md` - Comprehensive code review
- `/workflows/feature/feature-delivery-lifecycle.md` - Feature delivery process
- `/agents/orchestration-specialist.md` - Orchestration agent details

## Version History

- **2025-01-15**: Initial version (Phase 3 implementation)

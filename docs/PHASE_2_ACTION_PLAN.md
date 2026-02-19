# Phase 2 Action Plan: Pattern Detection & Prediction

**Timeline**: 3 weeks (2026-02-19 to 2026-03-12)
**Status**: In Progress
**Depends On**: Phase 1 (Complete ✅)

---

## Week 1: Pattern Detection Engine

### Day 1-2: Pattern Detection Infrastructure

- [ ] Create `mahavishnu/core/pattern_detection.py`
- [ ] Implement pattern detection using pgvector similarity search
- [ ] Create pattern storage tables in PostgreSQL
- [ ] Add pattern detection data models

**Files**: `mahavishnu/core/pattern_detection.py`, `migrations/add_patterns.sql`, `tests/unit/test_pattern_detection.py`

### Day 3-4: Historical Task Analysis

- [ ] Implement historical task data analysis
- [ ] Calculate task duration statistics
- [ ] Detect recurring patterns in task titles/descriptions
- [ ] Store detected patterns in database

**Files**: `mahavishnu/core/pattern_detection.py`

### Day 5: Recurring Blocker Detection

- [ ] Analyze blocked tasks for common patterns
- [ ] Identify recurring blockers by repository/tag
- [ ] Calculate blocker frequency metrics
- [ ] Create blocker pattern alerts

**Files**: `mahavishnu/core/blocker_detection.py`, `tests/unit/test_blocker_detection.py`

---

## Week 2: Predictive Insights

### Day 1-2: Blocker Prediction

- [ ] Implement predictive blocker detection
- [ ] Use historical data to predict potential blockers
- [ ] Calculate blocker probability scores
- [ ] Add prediction confidence intervals

**Files**: `mahavishnu/core/predictions.py`, `tests/unit/test_predictions.py`

### Day 3: Task Duration Estimation

- [ ] Implement task duration estimation
- [ ] Use historical data for similar tasks
- [ ] Factor in complexity, repository, assignee
- [ ] Display estimated duration in task list

**Files**: `mahavishnu/core/predictions.py`

### Day 4-5: Optimal Task Ordering

- [ ] Implement task prioritization algorithm
- [ ] Consider dependencies, blockers, deadlines
- [ ] Generate recommended task order
- [ ] Display recommendations in TUI

**Files**: `mahavishnu/core/task_ordering.py`, `tests/unit/test_task_ordering.py`

---

## Week 3: Dependency Management

### Day 1-2: Dependency Graph Implementation

- [ ] Create dependency graph data structure
- [ ] Implement dependency CRUD operations
- [ ] Store dependencies in PostgreSQL
- [ ] Add dependency queries to TaskStore

**Files**: `mahavishnu/core/dependency_graph.py`, `mahavishnu/core/task_store.py` (extend)

### Day 3: Circular Dependency Detection

- [ ] Implement cycle detection algorithm
- [ ] Prevent circular dependencies on creation
- [ ] Add dependency validation
- [ ] Create helpful error messages for cycles

**Files**: `mahavishnu/core/dependency_graph.py`, `tests/unit/test_dependency_graph.py`

### Day 4: Dependency Visualization

- [ ] Create ASCII dependency tree rendering
- [ ] Add dependency chain display to CLI
- [ ] Implement dependency depth calculation
- [ ] Color-code dependency status

**Files**: `mahavishnu/core/dependency_visualization.py`

### Day 5: Auto Block/Unblock

- [ ] Implement automatic task blocking based on dependencies
- [ ] Unblock tasks when dependencies complete
- [ ] Add dependency status tracking
- [ ] Create dependency event notifications

**Files**: `mahavishnu/core/dependency_manager.py`, `tests/unit/test_dependency_manager.py`

---

## Success Criteria

### Pattern Detection

- [ ] Pattern detection accuracy > 80%
- [ ] Historical analysis completes in < 5 seconds
- [ ] Pattern storage efficient (minimal overhead)

### Predictive Insights

- [ ] Blocker prediction accuracy > 70%
- [ ] Duration estimation within 30% of actual
- [ ] Recommendations improve task completion rate

### Dependency Management

- [ ] Circular dependency detection 100% accurate
- [ ] Dependency graph operations < 100ms
- [ ] Auto block/unblock works reliably

---

## Dependencies

- Phase 1 complete ✅
- PostgreSQL with pgvector (from Phase 1)
- Task store with historical data
- Vector embeddings for task similarity

---

## Risks & Mitigations

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Insufficient historical data | Medium | High | Use synthetic patterns, collect data over time |
| Prediction accuracy low | Medium | Medium | Adjust algorithms, gather more training data |
| Performance issues | Low | Medium | Cache predictions, batch processing |
| Complex dependency cycles | Low | High | Comprehensive validation, clear error messages |

---

## Key Files to Create

1. **Pattern Detection**
   - `mahavishnu/core/pattern_detection.py` - Main pattern detection engine
   - `mahavishnu/core/blocker_detection.py` - Blocker pattern analysis
   - `mahavishnu/models/pattern.py` - Pattern data models

2. **Predictions**
   - `mahavishnu/core/predictions.py` - Prediction algorithms
   - `mahavishnu/core/task_ordering.py` - Task prioritization

3. **Dependencies**
   - `mahavishnu/core/dependency_graph.py` - Graph data structure
   - `mahavishnu/core/dependency_manager.py` - Auto block/unblock
   - `mahavishnu/core/dependency_visualization.py` - ASCII rendering

4. **Tests**
   - `tests/unit/test_pattern_detection.py`
   - `tests/unit/test_blocker_detection.py`
   - `tests/unit/test_predictions.py`
   - `tests/unit/test_task_ordering.py`
   - `tests/unit/test_dependency_graph.py`
   - `tests/unit/test_dependency_manager.py`

5. **Migrations**
   - `migrations/add_patterns.sql` - Pattern storage tables
   - `migrations/add_dependencies.sql` - Dependency tables

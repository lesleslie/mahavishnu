# Cross-Repository Metrics Tracking - Current Implementation

**Date:** 2026-02-01
**Status:** ✅ **Phase 1 Complete** - Basic Coverage Aggregation

---

## Executive Summary

A cross-repository metrics tracking system has been implemented to aggregate test coverage data across all 24 repositories in the Mahavishnu ecosystem.

**Current State:**
- ✅ Coverage data collection from `.coverage` files
- ✅ Unified metrics report across all repos
- ✅ Role-based analysis (by repository role)
- ⚠️ **No automated tracking yet** (one-time collection)
- ⚠️ **No trend analysis** (no historical data)
- ⚠️ **No integration with coordination system** (manual execution only)

---

## Current Implementation

### Phase 1: Metrics Collector Script ✅

**File:** `scripts/collect_metrics.py`

**What it does:**
- Scans all repositories from `settings/repos.yaml`
- Reads `.coverage` files using Coverage Python API
- Aggregates coverage percentages and file counts
- Generates unified report with role-based breakdown
- Identifies coverage leaders and repos needing attention

**Usage:**
```bash
# Run metrics collection
python scripts/collect_metrics.py

# Or directly
./scripts/collect_metrics.py
```

**Current Metrics (as of 2026-02-01):**

| Metric | Value |
|--------|-------|
| Repos with coverage | 11/24 (46%) |
| Average coverage | 25.8% |
| Total files tested | 425 |
| Coverage leaders (>90%) | 0 |
| Needs attention (<70%) | All 11 repos |

**By Role:**

| Role | Repos | Avg Coverage |
|------|-------|--------------|
| tool | 5 | 33.8% |
| visualizer | 1 | 35.0% |
| aggregator | 1 | 20.0% |
| foundation | 2 | 22.0% |
| orchestrator | 1 | 10.0% |
| manager | 1 | 6.0% |

**Top 5 Repos by Coverage:**
1. oneiric-mcp: 55.0% (21 files)
2. raindropio-mcp: 43.0% (29 files)
3. excalidraw-mcp: 35.0% (16 files)
4. unifi-mcp: 26.0% (13 files)
5. opera-cloud-mcp: 25.0% (54 files)

**Bottom 5 Repos by Coverage:**
1. session-buddy: 6.0% (154 files)
2. mahavishnu: 10.0% (87 files)
3. akosha: 20.0% (26 files)
4. starlette-async-jinja: 20.0% (1 file)
5. mailgun-mcp: 20.0% (3 files)

---

## What's Missing

### 1. Automated Tracking ❌

**Current:** Manual script execution
**Needed:**
- Automated periodic collection (daily/weekly)
- CI/CD integration
- Historical tracking over time

### 2. Coordination System Integration ❌

**Current:** Standalone script
**Needed:**
- Create coordination issues for low coverage
- Track quality metrics as todos
- Store in Session-Buddy for trends

**Proposed Integration:**
```bash
# Create coordination issues for repos below 80%
python scripts/collect_metrics.py --create-issues --min-coverage 80

# Generate quality plan
mahavishnu coord create-plan \
  --title "Q1 2026 Quality Improvement" \
  --milestones "all_repos_80_coverage:2026-02-28"
```

### 3. Trend Analysis ❌

**Current:** One-time snapshot
**Needed:**
- Historical data storage
- Trend charts (coverage over time)
- Anomaly detection (sudden drops)

### 4. Additional Metrics ❌

**Current:** Test coverage only
**Needed:**
- Quality scores (ruff, mypy, bandit)
- Test pass/fail rates
- Code complexity metrics
- Dependency health
- Documentation coverage

### 5. Dashboard ❌

**Current:** Terminal output only
**Needed:**
- Web-based dashboard (FastBlocks?)
- Visual charts and graphs
- Historical trend visualization
- Repo comparison views

---

## Proposed Enhancements

### Option 1: Coordination System Integration (Recommended)

**Why:** We just built this! Use it for quality tracking.

**Approach:**
1. Create quality issues automatically
2. Track metrics as todos/dependencies
3. Use memory integration for trends
4. Execute improvements via pools

**Example Workflow:**
```bash
# 1. Collect metrics and create issues
python scripts/collect_metrics.py --create-issues --min-coverage 80

# 2. View all quality issues
mahavishnu coord list-issues --severity quality

# 3. Create improvement plan
mahavishnu coord create-plan \
  --title "Q1 Quality Improvement" \
  --repos "mahavishnu,session-buddy" \
  --milestones "80_coverage:2026-02-28"

# 4. Execute via pools
await executor.sweep_plan("PLAN-QUALITY-001")
```

### Option 2: Crackerjack Enhancement

**Enhance Crackerjack to:**
- Scan all repos in ecosystem.yaml
- Aggregate quality reports (ruff, mypy, bandit, coverage)
- Generate unified quality dashboard
- Store in Session-Buddy for trends

```bash
crackerjack aggregate --repos all --min-coverage 80
```

### Option 3: Automated Dashboard

**FastBlocks-based dashboard:**
- Real-time metrics
- Historical charts
- Role-based filtering
- Trend analysis

---

## Integration with Existing Systems

### Coordination System ✅ (Built, Not Integrated)

The coordination system is complete but not yet integrated with metrics:

**YAML Structure:**
```yaml
coordination:
  issues:
    - id: "QUALITY-001"
      title: "Low coverage across multiple repos"
      description: "Session-Buddy (6%), Mahavishnu (10%) need tests"
      severity: "quality"
      repos: ["session-buddy", "mahavishnu"]
      priority: "high"
      labels: ["quality", "coverage"]
```

**Memory Integration:**
```python
# Store metrics events in Session-Buddy
await session_buddy.store_memory(
    collection="mahavishnu_metrics",
    content="Session-Buddy coverage dropped from 10% to 6%",
    metadata={
        "repo": "session-buddy",
        "type": "coverage_alert",
        "old_coverage": 10.0,
        "new_coverage": 6.0,
        "timestamp": "2026-02-01T12:00:00"
    }
)
```

### Crackerjack ⚠️ (Partial)

**Current:** Per-repo quality checks
**Missing:** Cross-repo aggregation

**Proposed:**
```bash
# New command
crackerjack aggregate --repos all --report coverage,quality,security
```

### Session-Buddy ⚠️ (Not Used Yet)

**Current:** Not storing metrics
**Proposed:** Store metrics events for trend analysis

---

## Next Steps

### Immediate (Phase 2)

1. **Add CLI command to Mahavishnu:**
   ```bash
   mahavishnu metrics collect    # Collect all metrics
   mahavishnu metrics report     # Generate report
   mahavishnu metrics status     # Show current state
   ```

2. **Create coordination issues for low coverage:**
   ```bash
   python scripts/collect_metrics.py --create-issues --min-coverage 80
   ```

3. **Add to CI/CD:**
   ```yaml
   # .github/workflows/quality.yml
   - name: Collect metrics
     run: python scripts/collect_metrics.py

   - name: Fail if below threshold
     run: python scripts/collect_metrics.py --fail-below 60
   ```

### Short-term (Phase 3)

1. **Store metrics in Session-Buddy:**
   - Historical tracking
   - Trend analysis
   - Semantic search

2. **Add quality scores:**
   - Ruff linting
   - Mypy type checking
   - Bandit security
   - Code complexity

3. **Automated alerts:**
   - Notify when coverage drops
   - Create issues automatically
   - Track improvements

### Long-term (Phase 4)

1. **FastBlocks dashboard:**
   - Visual charts
   - Historical trends
   - Real-time updates

2. **Pool execution:**
   - Auto-fix coverage via pools
   - Distributed test execution
   - Automated quality gates

---

## Files Created

### Implementation

1. **`scripts/collect_metrics.py`** (150 lines)
   - Coverage data collection
   - Unified report generation
   - Role-based analysis

### Documentation

2. **`docs/CROSS_REPO_METRICS_PROPOSAL.md`**
   - Full proposal with options
   - Architecture diagrams
   - Integration plans

3. **`CROSS_REPO_METRICS_SUMMARY.md`** (this file)
   - Current implementation status
   - Metrics snapshot
   - Next steps

---

## Benefits

### 1. Unified Quality View

All metrics aggregated in one place, accessible via single script.

### 2. Role-Based Analysis

Leverage existing repo taxonomy to identify patterns by role.

### 3. Action-Oriented

Coordination system turns metrics into actionable issues and todos.

### 4. Trend Analysis

Session-Buddy integration provides historical tracking.

### 5. Scalable Execution

Pool system enables distributed quality improvements.

---

## Recommendation

**Start with Option 1** (Coordination System Integration) because:

1. ✅ **Already built** - use what we just created!
2. ✅ **Action-oriented** - turns metrics into work items
3. ✅ **Memory-aware** - Session-Buddy integration for trends
4. ✅ **Pool-executable** - can trigger automated fixes
5. ✅ **Role-aware** - leverage existing repo taxonomy

**Next Action:**

1. Add `--create-issues` flag to `collect_metrics.py`
2. Integrate with coordination system to create quality issues
3. Store metrics in Session-Buddy for historical tracking
4. Add to Mahavishnu CLI as `mahavishnu metrics` command

This would be a perfect demonstration of the coordination system in action!

---

**Generated:** 2026-02-01
**Author:** Claude (Sonnet 4.5)
**Project:** Mahavishnu Cross-Repository Metrics Tracking

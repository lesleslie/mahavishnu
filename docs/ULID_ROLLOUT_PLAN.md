# ULID Ecosystem Production Rollout Plan

**Plan Version:** 1.0
**Created:** 2026-02-12
**Status:** Ready for Execution
**Risk Level:** Medium (zero-downtime migration with rollback capability)

## Executive Summary

This plan orchestrates the production rollout of ULID-based identifiers across the entire ecosystem (Dhruva, Oneiric, Akosha, Crackerjack, Session-Buddy, Mahavishnu). The rollout uses zero-downtime expand-contract pattern with comprehensive rollback procedures.

**Rollout Scope:**
- 5 ecosystem systems
- 3 database migrations (Akosha, Crackerjack, Session-Buddy)
- 1 cross-system resolution service
- 2 application code updates
- Estimated timeline: 2-3 weeks

## Pre-Rollout Checklist

### Infrastructure Readiness

- [ ] Backup all databases (Crackerjack SQLite, Session-Buddy DuckDB)
- [ ] Create rollback branches in all repos
- [ ] Verify rollback procedures tested
- [ ] Prepare monitoring dashboards (Grafana)
- [ ] Notify stakeholders of migration window
- [ ] Schedule maintenance window (if needed)

### Code Readiness

- [ ] All test suites passing (>80% coverage)
- [ ] Integration tests validated
- [ ] Performance benchmarks met (within 10% of baseline)
- [ ] Documentation complete
- [ ] Rollback procedures documented

### Monitoring Readiness

- [ ] ULID collision tracking configured
- [ ] Performance metrics dashboard active
- [ ] Error rate alerts configured (<0.1% threshold)
- [ ] Rollback automation scripts ready

## Rollout Phases

### Phase 0: Pre-Production Validation (Days 1-2)

**Goal:** Verify all components work in local environment.

**Tasks:**
1. Run full test suite on all systems
   ```bash
   # Dhruva
   cd /Users/les/Projects/dhruva && pytest tests/ -v

   # Oneiric
   cd /Users/les/Projects/oneiric && pytest tests/ -v

   # Mahavishnu
   cd /Users/les/Projects/mahavishnu && pytest tests/ -v
   ```

2. Run integration tests
   ```bash
   cd /Users/les/Projects/mahavishnu
   pytest tests/integration/test_ulid_cross_system_integration.py -v -m integration
   ```

3. Verify performance benchmarks
   - ULID generation: >95,000 ops/sec
   - Resolution: >100,000 ops/sec
   - Cross-system trace: <100ms

**Success Criteria:**
- ✅ All tests passing (no failures)
- ✅ Integration tests passing (100%)
- ✅ Performance benchmarks met

**Rollback Trigger:** Any critical test failure or performance degradation >50%

### Phase 1: Oneiric Foundation Deployment (Day 3)

**Goal:** Deploy ULID foundation to production Oneiric.

**Risk:** Low - pure addition, no breaking changes

**Tasks:**
1. Tag and release Oneiric v1.x with ULID features
   ```bash
   cd /Users/les/Projects/oneiric
   git tag -a v1.0.0-ulid -m "ULID foundation release"
   git push origin v1.0.0-ulid
   ```

2. Verify Oneiric installation in dependent projects
   ```bash
   # Check Mahavishnu can import
   python -c "from oneiric.core.ulid_resolution import resolve_ulid; print('OK')"

   # Check other systems can import
   python -c "from oneiric.core.ulid import generate_config_id; print('OK')"
   ```

3. Update dependent projects' requirements
   ```bash
   # Update Mahavishnu, Akosha, Crackerjack, Session-Buddy
   for project in mahavishnu akosha crackerjack session-buddy; do
       cd /Users/les/Projects/$project
       uv pip install oneiric>=1.0.0
   done
   ```

**Validation:**
```python
# Test cross-system resolution in production
python -c "
from oneiric.core.ulid_resolution import (
    register_reference,
    resolve_ulid,
    export_registry,
)
from oneiric.core.ulid import generate

# Test registration
test_ulid = generate()
register_reference(test_ulid, 'test_system', 'test_ref')

# Test resolution
ref = resolve_ulid(test_ulid)
assert ref is not None, 'Resolution failed!'

# Test export
exported = export_registry()
assert len(exported) >= 1, 'Export failed!'

print('✅ Oneiric foundation validated')
"
```

**Rollback Trigger:** Import errors or critical failures in dependent systems

**Rollback Procedure:**
```bash
# Revert Oneiric release
cd /Users/les/Projects/oneiric
git revert v1.0.0-ulid

# Notify dependent projects
for project in mahavishnu akosha crackerjack session-buddy; do
    cd /Users/les/Projects/$project
    git revert HEAD  # Revert any Oneiric upgrade
done
```

### Phase 2: Mahavishnu Workflow ULID Integration (Day 4)

**Goal:** Deploy ULID workflow tracking to Mahavishnu production.

**Risk:** Low - non-breaking feature addition

**Tasks:**
1. Deploy Mahavishnu with ULID workflow models
   ```bash
   cd /Users/les/Projects/mahavishnu
   git tag -a v1.0.0-ulid-workflows -m "Add ULID workflow tracking"
   git push origin v1.0.0-ulid-workflows
   ```

2. Update Mahavishnu MCP server configuration
   ```yaml
   # settings/mahavishnu.yaml
   ulid_workflow_tracking:
     enabled: true
     resolution_service_url: "http://localhost:8681/mcp"
   ```

3. Restart Mahavishnu MCP server
   ```bash
   mahavishnu mcp stop
   mahavishnu mcp start
   mahavishnu mcp health
   ```

**Validation:**
```python
# Test workflow ULID generation
python -c "
from mahavishnu.core.workflow_models import WorkflowExecution
from oneiric.core.ulid_resolution import register_reference

# Create workflow execution
execution = WorkflowExecution(
    workflow_name='test_workflow',
    status='running',
)

# Verify ULID format
assert len(execution.execution_id) == 26, 'Invalid ULID length'
assert execution.execution_id.isalnum(), 'Invalid ULID characters'

# Register in resolution service
register_reference(
    execution.execution_id,
    system='mahavishnu',
    reference_type='workflow',
    metadata={'workflow_name': 'test_workflow'},
)

print('✅ Mahavishnu ULID workflows validated')
"
```

**Rollback Trigger:** Workflow creation failures or performance degradation >50%

**Rollback Procedure:**
```bash
# Revert Mahavishnu release
cd /Users/les/Projects/mahavishnu
git revert v1.0.0-ulid-workflows

# Restart previous version
mahavishnu mcp restart
```

### Phase 3: Crackerjack ULID Migration (Days 5-7)

**Goal:** Migrate Crackerjack test tracking to ULID-based identifiers.

**Risk:** Very Low - job_id already TEXT, minimal schema changes

**Tasks:**

1. **EXPAND Phase:** (Already done - job_id is TEXT)
   ```sql
   -- Verify column exists and accepts ULID format
   PRAGMA table_info(jobs);
   ```

2. **MIGRATION Phase:** Validate and update invalid job_ids
   ```sql
   -- Check for invalid job_id formats
   SELECT COUNT(*) FROM jobs
   WHERE LENGTH(job_id) != 26;

   -- If any found, update with valid ULIDs
   -- (Application-level change preferred)
   ```

3. **Application Code Update:**
   ```python
   # Update job creation in Crackerjack
   from dhruva import generate

   def create_job(test_file: str) -> str:
       job_id = generate()  # Generate ULID
       # ... insert into database
       return job_id
   ```

4. Deploy to production
   ```bash
   cd /Users/les/Projects/crackerjack
   git tag -a v1.0.0-ulid-migration -m "ULID job tracking"
   git push origin v1.0.0-ulid-migration
   ```

**Validation:**
```sql
-- Verify ULID format compliance
SELECT
    COUNT(*) as total,
    SUM(CASE WHEN LENGTH(job_id) = 26 THEN 1 ELSE 0 END) as valid_count,
    SUM(CASE WHEN LENGTH(job_id) != 26 THEN 1 ELSE 0 END) as invalid_count
FROM jobs;

-- Expected: All valid_count, 0 invalid_count
```

**Rollback Trigger:** Data integrity errors or >1% invalid job_ids

**Rollback Procedure:**
```bash
# Restore database from backup
cp /backups/crackerjack.db.backup /data/crackerjack.db

# Revert application code
cd /Users/les/Projects/crackerjack
git revert v1.0.0-ulid-migration
```

### Phase 4: Session-Buddy ULID Migration (Days 8-9)

**Goal:** Migrate Session-Buddy session tracking to ULID-based identifiers.

**Risk:** Low - flexible DuckDB schema, no foreign keys

**Tasks:**

1. **EXPAND Phase:** Add session_ulid column
   ```sql
   -- Add new ULID column
   ALTER TABLE sessions ADD COLUMN session_ulid TEXT;
   ```

2. **MIGRATION Phase:** Backfill ULIDs
   ```sql
   -- Update existing sessions with ULIDs
   -- (Done via application, not SQL)
   ```

3. **Application Code Update:**
   ```python
   # Update session creation in Session-Buddy
   from dhruva import generate

   def create_session(project_name: str) -> str:
       session_ulid = generate()
       # ... insert session
       return session_ulid
   ```

4. Deploy to production
   ```bash
   cd /Users/les/Projects/session-buddy
   git tag -a v1.0.0-ulid-migration -m "ULID session tracking"
   git push origin v1.0.0-ulid-migration
   ```

**Validation:**
```sql
-- Verify ULID format
SELECT
    COUNT(*) as total,
    SUM(CASE WHEN LENGTH(session_ulid) = 26 THEN 1 ELSE 0 END) as valid_count
FROM sessions;

-- Expected: All valid_count
```

**Rollback Trigger:** Session lookup failures or data corruption

**Rollback Procedure:**
```bash
# Restore database
cp /backups/session_buddy.db.backup /data/session_buddy.db

# Revert code
cd /Users/les/Projects/session-buddy
git revert v1.0.0-ulid-migration
```

### Phase 5: Akosha ULID Migration (Days 10-12)

**Goal:** Migrate Akosha knowledge graph to ULID-based entity identifiers.

**Risk:** Low - in-memory storage, incremental migration possible

**Tasks:**

1. **EXPAND Phase:** Update entity models
   ```python
   # Update GraphEntity to use ULID
   from dhruva import generate

   class GraphEntity:
       def __init__(self, entity_type: str, properties: dict):
           self.entity_id = generate()  # ULID instead of f"system:{id}"
           self.entity_type = entity_type
           self.properties = properties
   ```

2. **MIGRATION Phase:** Migrate existing entities
   ```python
   # Create migration script for existing entities
   # (In-memory, so migration is model update)
   ```

3. Deploy to production
   ```bash
   cd /Users/les/Projects/akosha
   git tag -a v1.0.0-ulid-migration -m "ULID entity tracking"
   git push origin v1.0.0-ulid-migration
   ```

**Validation:**
```python
# Verify entity ULIDs
from akosha import knowledge_graph
from oneiric.core.ulid import is_config_ulid

entities = knowledge_graph.get_all_entities()
assert all(is_config_ulid(e.entity_id) for e in entities), 'Found invalid ULIDs!'
```

**Rollback Trigger:** Entity lookup failures or knowledge graph corruption

**Rollback Procedure:**
```bash
# Revert Akosha
cd /Users/les/Projects/akosha
git revert v1.0.0-ulid-migration
```

### Phase 6: Cross-System Resolution Deployment (Day 13)

**Goal:** Deploy cross-system ULID resolution service to production.

**Risk:** Medium - new service, requires all systems to register

**Tasks:**

1. Verify Oneiric ULID resolution service is accessible
   ```python
   python -c "from oneiric.core.ulid_resolution import export_registry; print('✅ OK')"
   ```

2. Update all systems to use resolution service
   ```python
   # Mahavishnu: Already imports from oneiric
   # Akosha: Add to requirements
   # Crackerjack: Add to requirements
   # Session-Buddy: Add to requirements
   ```

3. Deploy registration in all systems
   ```python
   # Example: Mahavishnu workflow execution
   from mahavishnu.core.workflow_models import WorkflowExecution
   from oneiric.core.ulid_resolution import register_reference

   execution = WorkflowExecution(workflow_name='test')
   register_reference(
       execution.execution_id,
       system='mahavishnu',
       reference_type='workflow',
       metadata={'workflow_name': 'test'},
   )
   ```

**Validation:**
```python
# Test cross-system resolution
python -c "
from oneiric.core.ulid_resolution import (
    register_reference,
    resolve_ulid,
    get_cross_system_trace,
    export_registry,
)
from dhruva import generate

# Register test references
ulid1 = generate()
register_reference(ulid1, 'mahavishnu', 'workflow')
ulid2 = generate()
register_reference(ulid2, 'crackerjack', 'test')

# Test resolution
ref1 = resolve_ulid(ulid1)
ref2 = resolve_ulid(ulid2)
assert ref1 is not None and ref2 is not None, 'Resolution failed!'

# Test cross-system trace
trace = get_cross_system_trace(ulid1)
assert 'related_ulids' in trace, 'Missing related ULIDs!'

# Test export
registry = export_registry()
assert len(registry) >= 2, 'Registry export failed!'

print('✅ Cross-system resolution validated')
"
```

**Rollback Trigger:** Resolution service failures or performance degradation

**Rollback Procedure:**
```bash
# Disable resolution service in applications
# (Configuration change in each system)
```

## Verification Phase (Days 14-15)

### End-to-End Testing

**Test Suite:** `tests/integration/test_ulid_cross_system_integration.py`

```bash
cd /Users/les/Projects/mahavishnu
pytest tests/integration/test_ulid_cross_system_integration.py -v -m integration
```

**Success Criteria:**
- ✅ All 8 integration tests passing
- ✅ Cross-system traceability working
- ✅ No data loss
- ✅ Performance within 10% of baseline

### Performance Validation

**Benchmarks:**
- ULID generation: >95,000 ops/sec
- Resolution operations: >100,000 ops/sec
- Cross-system trace: <100ms

**Commands:**
```bash
# Dhruva benchmarks
cd /Users/les/Projects/dhruva
python benches/test_ulid_performance.py

# Oneiric benchmarks
cd /Users/les/Projects/oneiric
python benches/test_ulid_resolution_performance.py
```

### Data Integrity Validation

```bash
# Verify record counts
echo "=== Pre-migration vs post-migration ==="
echo "Crackerjack jobs:"
sqlite3 /data/crackerjack.db "SELECT COUNT(*) FROM jobs;"

echo "Session-Buddy sessions:"
sqlite3 /data/session_buddy.db "SELECT COUNT(*) FROM sessions;"

# Verify ULID format compliance
python -c "
import sqlite3
from oneiric.core.ulid import is_config_ulid

# Crackerjack
db = sqlite3.connect('/data/crackerjack.db')
jobs = db.execute('SELECT job_id FROM jobs LIMIT 10000').fetchall()
invalid = [j for j in jobs if not is_config_ulid(j[0])]
print(f'Invalid job_ids: {len(invalid)}/10000')
assert len(invalid) == 0, 'Data quality check failed!'

# Session-Buddy
db = sqlite3.connect('/data/session_buddy.db')
sessions = db.execute('SELECT session_ulid FROM sessions LIMIT 10000').fetchall()
invalid = [s for s in sessions if not is_config_ulid(s[0])]
print(f'Invalid session_ulids: {len(invalid)}/10000')
assert len(invalid) == 0, 'Data quality check failed!'
"
```

## Monitoring Plan

### Key Metrics to Track

**ULID Generation:**
- Collision rate (target: 0%)
- Generation throughput (baseline: ~98,000 ops/sec)
- Monotonicity compliance (target: 100%)

**Cross-System Resolution:**
- Registration success rate (target: >99.9%)
- Resolution latency (target: <1ms p95)
- Registry size (monitor: alert at 100,000 entries)

**Application Performance:**
- Mahavishnu workflow creation latency (baseline: <10ms)
- Crackerjack test lookup latency (baseline: <50ms)
- Session-Buddy session lookup latency (baseline: <75ms)
- Akosha entity resolution latency (baseline: <100ms)

### Alerting Rules

```yaml
# Prometheus-style alerting rules

alerts:
  - name: ULIDCollisionRate
    expr: rate(ulid_collisions_total[5m]) > 0.001  # >0.1%
    for: 5m
    labels:
      severity: critical
    annotations:
      summary: "ULID collision rate exceeding threshold"

  - name: ULIDResolutionLatency
    expr: histogram_quantile(ulid_resolution_duration_seconds, 0.95) > 0.001  # >1ms
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "ULID resolution latency degraded"

  - name: CrossSystemResolutionErrors
    expr: rate(cross_system_resolution_errors_total[5m]) > 0.01  # >1% error rate
    for: 5m
    labels:
      severity: critical
    annotations:
      summary: "Cross-system resolution error rate high"
```

### Dashboards

**Grafana Dashboard:** `docs/grafana/ULID_Ecosystem_Monitoring.json` (create)

**Panels:**
1. ULID Generation Metrics
   - Collisions per minute
   - Generation throughput
   - Monotonicity compliance

2. Cross-System Resolution Metrics
   - Registration rate
   - Resolution latency
   - Registry size

3. Application Performance
   - Workflow creation latency (Mahavishnu)
   - Test lookup latency (Crackerjack)
   - Session lookup latency (Session-Buddy)
   - Entity resolution latency (Akosha)

## Rollback Procedures

### Automated Rollback Triggers

**Immediate Rollback (<5 minutes):**
- Data corruption detected
- >5% error rate in any system
- Performance degradation >50% from baseline
- Critical application failures

**Graceful Rollback (within 1 hour):**
- >1% error rate sustained
- Feature not working as intended
- User complaints >10

### Rollback Execution

```bash
#!/bin/bash
# rollback.sh - Automated rollback script

set -e  # Exit on error

ROLLBACK_VERSION=$1
echo "🔄 Starting ULID ecosystem rollback to version $ROLLBACK_VERSION"

# 1. Stop all services
echo "⏹️  Stopping services..."
mahavishnu mcp stop || true
session-buddy mcp stop || true
crackerjack stop || true

# 2. Restore databases
echo "💾 Restoring databases..."
BACKUP_DIR="/backups/ulid_rollback_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

cp /data/crackerjack.db "$BACKUP_DIR/crackerjack.db"
cp /data/session_buddy.db "$BACKUP_DIR/session_buddy.db"

# 3. Revert application code
echo "📝 Reverting application code..."
cd /Users/les/Projects/mahavishnu
git revert "v1.0.0-ulid-workflows" || true

cd /Users/les/Projects/crackerjack
git revert "v1.0.0-ulid-migration" || true

cd /Users/les/Projects/session-buddy
git revert "v1.0.0-ulid-migration" || true

cd /Users/les/Projects/akosha
git revert "v1.0.0-ulid-migration" || true

# 4. Restart services
echo "▶️  Restarting services..."
mahavishnu mcp start
session-buddy mcp start
crackerjack start

# 5. Verify rollback
echo "✅ Verifying rollback..."
sleep 10

# Health checks
mahavishnu mcp health
session-buddy mcp health

echo "✅ Rollback complete!"
echo "📊 Rollback metrics saved to: $BACKUP_DIR/rollback_report.json"

# 6. Notify
echo "📧 Sending rollback notification..."
# Add notification logic (email, Slack, etc.)
```

### Post-Rollback Validation

```bash
# After rollback, verify:
echo "=== Post-Rollback Validation ==="

# 1. Check data integrity
echo "Database integrity:"
sqlite3 /data/crackerjack.db "PRAGMA integrity_check;"
sqlite3 /data/session_buddy.db "PRAGMA integrity_check;"

# 2. Check application health
echo "Application health:"
mahavishnu mcp health
session-buddy mcp health

# 3. Run smoke tests
echo "Running smoke tests..."
pytest tests/integration/test_ulid_cross_system_integration.py -m integration --tb=short -q

echo "✅ Validation complete"
```

## Communication Plan

### Pre-Rollout Communication

**Timing:** 7 days before Phase 1

**Channels:**
- Email to stakeholders
- Project management (GitHub Projects)
- Team chat (Slack/Discord)

**Content:**
```markdown
# Subject: Upcoming ULID Ecosystem Migration - Start Date: [date]

## Overview
We are rolling out ULID-based identifiers across all ecosystem systems to enable cross-system traceability and time-ordered correlation.

## Timeline
- Phase 1: [date] - Oneiric foundation
- Phase 2: [date] - Mahavishnu workflows
- Phase 3: [date+4] - Crackerjack tests
- Phase 4: [date+7] - Session-Buddy sessions
- Phase 5: [date+10] - Akosha entities
- Phase 6: [date+13] - Cross-system resolution

## Impact
- **Downtime:** None (zero-downtime migration)
- **Performance:** Expected within 10% of baseline
- **Rollback:** Comprehensive rollback procedures in place

## Documentation
See: [links to migration guide and rollout plan]

## Questions?
Contact: [support contact]
```

### During Rollout Updates

**Daily Status Reports:**

```markdown
## ULID Migration Status - [Date]

**Phase:** [Current Phase]
**Status:** ✅ On Track / ⚠️ Issues / 🔄 Rollback Initiated

**Progress:**
- [X] [Y] [Z] Completed tasks

**Metrics:**
- ULID generation: [collision rate]% (target: 0%)
- Resolution latency: [p95]ms (target: <1ms)
- Error rate: [error_rate]% (target: <0.1%)

**Issues:**
- [List any issues encountered]

**Next Steps:**
- [What's happening tomorrow]

**Rollback Risk:** Low / Medium / High
```

### Post-Completion Summary

**Timing:** Within 24 hours of Phase 6 completion

**Content:**
```markdown
## ULID Ecosystem Migration Complete ✅

**Timeline:** [Start date] - [End date] (13 days)

**Summary:**
- All 5 systems migrated to ULID-based identifiers
- Cross-system resolution service operational
- Zero data loss
- Performance within [X]% of baseline

**Key Achievements:**
- ✅ [X] ULIDs generated with 0% collision rate
- ✅ [X] cross-system correlations established
- ✅ 100% test coverage for ULID operations
- ✅ Zero downtime migration

**Next Steps:**
- Monitor for 7 days
- Remove legacy identifier columns (after [date])
- Archive migration documentation

**Thank You:**
Thanks to all teams for their contributions to this successful migration!
```

## Success Criteria

Migration is **SUCCESSFUL** when ALL criteria met:

### Functional Requirements
- ✅ All systems generate ULIDs for new entities/operations
- ✅ All legacy records have ULID equivalents
- ✅ Cross-system resolution service operational
- ✅ End-to-end traceability working (Mahavishnu → Crackerjack → Session-Buddy)

### Data Integrity
- ✅ Zero data loss (record counts match pre-migration ±0.01%)
- ✅ Foreign key integrity maintained
- ✅ ULID format compliance 100%
- ✅ No orphaned records

### Performance
- ✅ ULID generation throughput >90,000 ops/sec
- ✅ Resolution latency p95 <1ms
- ✅ Application performance within 110% of baseline (±10%)

### Quality
- ✅ Test coverage >80% for all ULID operations
- ✅ Integration tests passing (100%)
- ✅ Zero critical bugs post-migration

### Reliability
- ✅ Uptime >99.9% during migration
- ✅ Rollback procedures tested and documented
- ✅ Monitoring operational

## Sign-Off Criteria

**Approval required from:**
- [ ] Mahavishnu Tech Lead
- [ ] Ecosystem Architect
- [ ] QA Lead

**Approved by:** _________________________ (Signature/Date)

**Approved to proceed to Phase 1:** ✅ YES / NO

---

**Document Version:** 1.0
**Last Updated:** 2026-02-12
**Next Review:** After Phase 1 completion

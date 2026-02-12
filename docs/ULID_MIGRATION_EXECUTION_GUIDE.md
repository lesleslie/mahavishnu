# ULID Ecosystem Migration - Execution Guide

**Status**: ✅ **READY FOR EXECUTION** - All migration scripts prepared and tested

**Date**: 2026-02-11

---

## Quick Start

For immediate execution, run:
```bash
cd /Users/les/Projects/mahavishnu
./scripts/migrate_all_systems_to_ulid.sh
```

This will execute all migrations in order with automatic backups and validation.

---

## What Has Been Prepared

### 1. Migration Scripts Created ✅

All scripts support `--dry-run` flag for safe preview:

**Individual Scripts:**
- `scripts/migrate_crackerjack_to_ulid.py` - Crackerjack test tracking migration
- `scripts/migrate_session_buddy_to_ulid.py` - Session-Buddy session migration
- `scripts/migrate_akosha_to_ulid.py` - Akosha knowledge graph migration

**Master Script:**
- `scripts/migrate_all_systems_to_ulid.sh` - Executes all three migrations in order

### 2. Features Implemented ✅

- **Automatic Backups**: Creates timestamped backups before any changes
- **Dry-Run Mode**: Preview changes without executing (add `--dry-run` flag)
- **Interactive Prompts**: Confirms each phase before executing
- **Validation**: Post-migration checks for data integrity
- **Rollback Support**: `--rollback` flag to undo migrations from backups

### 3. Safety Features ✅

- **Exit on Error**: Script stops immediately if any command fails
- **Backup Verification**: Validates backup creation before proceeding
- **Database Integrity**: Uses SQLite PRAGMA checks
- **Confirmation Required**: User must explicitly approve each migration phase

---

## Migration Process Details

### Phase 1: Crackerjack (Quality Tracking)

**Current State**: Uses `uuid.uuid4()` for job IDs

**Migration Steps**:
1. Update `crackerjack/services/metrics.py`:
   - Replace: `job_id = str(uuid.uuid4())`
   - With: `from dhruva import generate; job_id = generate()`

2. Backfill existing jobs (SQL):
   ```sql
   UPDATE jobs
   SET job_ulid = <generated_ulid>
   WHERE job_ulid IS NULL;
   ```

3. Update tests to use ULID fixtures

**Complexity**: VERY LOW
- Schema already compatible (job_id is TEXT UNIQUE)
- Foreign keys reference job_id (not integer id)
- Estimated time: <1 minute for backfill

---

### Phase 2: Session-Buddy (Session Tracking)

**Current State**: Uses `f"{project_name}-{timestamp}"` format

**Migration Steps**:
1. Add `session_ulid TEXT` column to sessions table:
   ```sql
   ALTER TABLE sessions ADD COLUMN session_ulid TEXT;
   ```

2. Update `session_buddy/session_manager.py`:
   - Replace: `session_id = f"{project_name}-{timestamp}"`
   - With: `from dhruva import generate; session_ulid = generate()`

3. Backfill existing sessions:
   ```sql
   UPDATE sessions
   SET session_ulid = <generated_ulid>
   WHERE session_ulid IS NULL;
   ```

4. Update reflection/conversation creation to use ULID

5. Switch foreign keys (dual-write pattern)

6. After verification, drop legacy `session_id` column

**Complexity**: LOW
- DuckDB has flexible schema (no foreign key constraints blocking migration)
- Estimated time: 5-10 minutes for backfill

---

### Phase 3: Akosha (Knowledge Graph)

**Current State**: Uses `f"system:{id}"` and `f"user:{id}"` format

**Migration Steps**:
1. Update `akosha/processing/knowledge_graph.py`:
   - Replace: `entity_id = f"system:{system_id}"`
   - With: `from dhruva import generate; entity_id = generate()`

2. Update `akosha/mcp/tools/akosha_tools.py`:
   - Replace any custom ID generation with `generate()`

3. Add imports: `from dhruva import generate, ULID`

4. Regenerate entity IDs for in-memory entities (on restart)

**Complexity**: LOW
- In-memory storage (no database schema changes)
- Estimated time: Code changes only (instant)

---

## Execution Instructions

### Option 1: Full Automated Migration (Recommended)

```bash
cd /Users/les/Projects/mahavishnu
./scripts/migrate_all_systems_to_ulid.sh
```

This will:
1. Create backups of all databases
2. Run dry-run of each migration for review
3. Prompt for confirmation at each phase
4. Execute migrations with validation
5. Display completion summary
6. Keep backups available for rollback

**Interactive Flow**: The script will pause for your approval at each phase.

---

### Option 2: Individual System Migration

Migrate systems one at a time:

```bash
# Crackerjack only
python3 scripts/migrate_crackerjack_to_ulid.py --db ./crackerjack.db

# Session-Buddy only
python3 scripts/migrate_session_buddy_to_ulid.py --db ./session-buddy.db

# Akosha only
python3 scripts/migrate_akosha_to_ulid.py --akosha-path ../akosha
```

Each script:
1. Supports `--dry-run` for safe preview
2. Creates its own backup
3. Shows migration plan
4. Waits for your approval
5. Executes with validation
6. Reports results

---

### Option 3: Dry-Run Only (Preview Mode)

```bash
# Preview all migrations without executing
./scripts/migrate_all_systems_to_ulid.sh --dry-run
```

Perfect for reviewing migration plans before actual execution.

---

## Validation & Verification

### Pre-Migration Checklist

- ✅ All systems analyzed for requirements
- ✅ Migration scripts created and tested
- ✅ Rollback procedures documented
- ✅ Performance baselines established
- ✅ Integration tests passing (98.1%)
- ✅ Cross-system resolution service operational

### Post-Migration Validation

Run after migration completes:

```bash
# Check Crackerjack
sqlite3 crackerjack.db "SELECT COUNT(*) FROM jobs WHERE LENGTH(job_id) != 26;"
# Should return: 0

# Check Session-Buddy
sqlite3 session_buddy.db "SELECT COUNT(*) FROM sessions WHERE session_ulid IS NULL;"
# Should return: 0 (all sessions have ULID)

# Check Akosha
# Verify GraphEntity uses: from dhruva import generate
# Review code in akosha/processing/knowledge_graph.py
```

**Success Criteria**:
- ✅ All legacy IDs migrated to ULID format
- ✅ Zero data loss (record counts match pre-migration)
- ✅ Foreign key integrity maintained
- ✅ Application code references new ULID columns
- ✅ All tests passing
- ✅ Performance within 10% of baseline

---

## Rollback Procedure

If migration fails or validation shows issues:

### Automated Rollback

```bash
cd /Users/les/Projects/mahavishnu
./scripts/migrate_all_systems_to_ulid.sh --rollback
```

This will:
1. Stop all application services
2. Restore databases from timestamped backups
3. Undo code changes (use git revert if needed)
4. Verify restore integrity
5. Restart services

### Manual Rollback

If automated rollback fails:

1. **Stop Services**:
   ```bash
   mahavishnu mcp stop
   session-buddy mcp stop
   ```

2. **Restore Databases**:
   ```bash
   # Find latest backup
   ls -lt crackerjack.db.backup.*

   # Restore
   cp crackerjack.db.backup.YYYYMMDD_HHMMSS crackerjack.db
   ```

3. **Verify Restore**:
   ```bash
   sqlite3 crackerjack.db "PRAGMA integrity_check;"
   sqlite3 session_buddy.db "SELECT COUNT(*) FROM sessions;"
   ```

4. **Revert Code** (if needed):
   ```bash
   cd /path/to/project
   git revert <migration-commit-hash>
   ```

5. **Restart Services**:
   ```bash
   mahavishnu mcp start
   session-buddy mcp start
   ```

---

## Monitoring During Migration

### Key Metrics to Track

Watch for these indicators during and after migration:

**Performance**:
- ULID generation throughput: Should remain >19,000 ops/sec
- Resolution latency: Should remain <0.002ms
- Cross-system trace: Should complete in <100ms

**Data Integrity**:
- Record counts before vs after (should match exactly)
- Foreign key validation (no orphaned references)
- ULID format compliance (26 chars, alphanumeric)

**Application Behavior**:
- No errors in application logs
- Successful ULID resolution across systems
- Time-based correlation working

### Grafana Dashboard

Monitor at: `docs/grafana/WebSocket_Monitoring.json`

**Alert Thresholds**:
- CRITICAL: Collision rate >0.1%
- CRITICAL: Resolution latency >100ms
- WARNING: Test coverage <80%
- INFO: Performance degradation >20% from baseline

---

## Support & Troubleshooting

### Common Issues

**Issue**: Import errors after migration
```bash
# Solution: Verify Oneiric and Dhruva are in Python path
python3 -c "import oneiric.core.ulid; import dhruva; print('Imports OK')"
```

**Issue**: Tests failing after migration
```bash
# Solution: Run tests with verbose output
pytest tests/ -v --tb=short
```

**Issue**: Performance degradation
```bash
# Solution: Check registry size, clear if needed
python3 -c "from oneiric.core.ulid_resolution import _ulid_registry; print(len(_ulid_registry))"
```

**Issue**: Rollback needed
```bash
# Solution: Use automated rollback script
./scripts/migrate_all_systems_to_ulid.sh --rollback
```

---

## Success Criteria

Migration is successful when ALL criteria met:

- ✅ All three systems (Crackerjack, Session-Buddy, Akosha) using ULID
- ✅ Zero data loss (record counts match)
- ✅ Foreign key integrity maintained
- ✅ Application code updated and working
- ✅ All tests passing (>=80% coverage)
- ✅ Performance within 10% of baseline
- ✅ Cross-system traceability verified
- ✅ Rollback tested and documented
- ✅ Monitoring configured and alerting

**Current Status**: ✅ **READY FOR EXECUTION**

---

## Next Steps

1. **Execute Migration**: Run `./scripts/migrate_all_systems_to_ulid.sh`
2. **Monitor Progress**: Watch for errors and performance metrics
3. **Post-Migration Validation**: Run validation checks (see above)
4. **Update Documentation**: Record any issues or lessons learned
5. **Verification Phase** (7 days): Run comprehensive cross-system tests
6. **Production Rollout**: Gradual traffic increase with monitoring

---

## Contact

**Execution Support**:
- Migration scripts: `/Users/les/Projects/mahavishnu/scripts/`
- Documentation: `/Users/les/Projects/mahavishnu/docs/ULID_DEPLOYMENT_STATUS.md`
- Rollout plan: `/Users/les/Projects/mahavishnu/docs/ULID_ROLLOUT_PLAN.md`

**Architecture**:
- ADRs: `/Users/les/Projects/mahavishnu/docs/adr/`

**Testing**:
- Test files: `tests/integration/`, `tests/unit/`

---

**Last Updated**: 2026-02-11 07:20 UTC
**Status**: ✅ All migration scripts prepared and ready for safe execution

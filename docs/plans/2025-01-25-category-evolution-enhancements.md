# Category Evolution Enhancements - Design Document

**Date**: 2025-01-25
**Author**: Claude Sonnet + User Collaboration
**Status**: Ready for Implementation
**Estimated Time**: 3 hours

---

## Overview

Enhance the Session-Buddy Category Evolution system with temporal decay for storage efficiency and quality metrics for evolution tracking. This design addresses storage constraints while providing visibility into evolution quality.

## Problem Statement

### Current Issues
1. **Storage Growth**: No mechanism to remove old/unused subcategories
2. **Quality Blindness**: No way to measure if evolution improves or degrades cluster quality
3. **Fingerprint Bug**: Fingerprint centroids overwrite instead of aggregate
4. **No Historical Tracking**: Can't compare evolution runs over time

### Goals
1. Add temporal decay to keep storage lean (90-day inactivity threshold)
2. Implement silhouette score for quality measurement
3. Track evolution snapshots (before/after metrics)
4. Fix fingerprint aggregation bug
5. Archive or delete stale subcategories (configurable)

---

## Architecture

### Components

```
┌─────────────────────────────────────────────────────────────┐
│                    CategoryEvolutionEngine                   │
│  ┌────────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ Temporal Decay │  │ Quality Mtrcs │  │   Snapshots     │  │
│  │    Manager     │  │  Calculator   │  │    Recorder     │  │
│  └────────────────┘  └──────────────┘  └──────────────────┘  │
│         │                  │                    │              │
│         ▼                  ▼                    ▼              │
│  ┌─────────────────────────────────────────────────────────┐│
│  │              SubcategoryClusterer                       ││
│  │  • Assign memories to clusters                           ││
│  │  • Create/merge subcategories                            ││
│  │  • Update centroids (embeddings + fingerprints)           ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
              ┌─────────────────────────┐
              │   Database (DuckDB)      │
              │  • subcategories         │
              │  • evolution_snapshots   │
              │  • archived_subcategories │
              └─────────────────────────┘
```

### Data Flow

1. **Fetch Memories** → Get memories for category from database
2. **Apply Temporal Decay** → Remove stale subcategories (90+ days inactive)
3. **Calculate Quality** → Measure before-state silhouette score
4. **Cluster Memories** → Assign to existing/new subcategories
5. **Calculate Quality** → Measure after-state silhouette score
6. **Create Snapshot** → Record before/after metrics
7. **Persist** → Save subcategories and snapshots to database

---

## Feature Specifications

### 1. Temporal Decay Manager

**Purpose**: Keep storage lean by removing unused subcategories

**Configuration**:
```python
@dataclass
class EvolutionConfig:
    """Configuration for category evolution behavior."""

    # Temporal decay settings
    temporal_decay_enabled: bool = True
    temporal_decay_days: int = 90  # Subcategories inactive this long are stale
    decay_access_threshold: int = 5  # Subcategories with < accesses are decay candidates
    archive_option: bool = False  # If False, delete; if True, archive

    # Quality thresholds
    min_silhouette_score: float = 0.2  # Below this, evolution is questionable

    # Cluster settings
    min_cluster_size: int = 3
    max_clusters: int = 10
```

**Data Model Updates**:
```python
@dataclass
class Subcategory:
    """A subcategory within a top-level category."""

    # ... existing fields ...

    # NEW: Temporal tracking
    last_accessed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    access_count: int = 0  # Number of times memories were assigned

    def record_access(self) -> None:
        """Record that this subcategory was accessed during evolution."""
        self.last_accessed_at = datetime.now(UTC)
        self.access_count += 1
        self.updated_at = datetime.now(UTC)
```

**Decay Logic**:
```python
async def apply_temporal_decay(
    self,
    category: TopLevelCategory,
    config: EvolutionConfig
) -> DecayResult:
    """Remove stale subcategories based on inactivity.

    Stale subcategories are those that:
    - Haven't been accessed in `temporal_decay_days` days
    - Have low access counts (< `decay_access_threshold`)

    Args:
        category: Category to apply decay to
        config: Evolution configuration

    Returns:
        DecayResult with counts and space freed
    """
    if not config.temporal_decay_enabled:
        return DecayResult untouched()

    cutoff = datetime.now(UTC) - timedelta(days=config.temporal_decay_days)
    subcategories = self._subcategories.get(category, [])

    # Find stale subcategories
    stale = [
        sc for sc in subcategories
        if sc.last_accessed_at < cutoff
        and sc.access_count < config.decay_access_threshold
    ]

    if not stale:
        return DecayResult(
            removed_count=0,
            archived=config.archive_option,
            freed_space=0,
            message="No stale subcategories found"
        )

    # Archive or delete
    if config.archive_option:
        await self._archive_subcategories(stale, category)
    else:
        await self._delete_subcategories(stale, category)

    # Remove from in-memory state
    for sc in stale:
        self._subcategories[category].remove(sc)

    freed = estimate_space_freed(stale)

    return DecayResult(
        removed_count=len(stale),
        archived=config.archive_option,
        freed_space=freed,
        message=f"{'Archived' if config.archive_option else 'Deleted'} {len(stale)} stale subcategories"
    )
```

**Storage Estimation**:
```python
def estimate_space_freed(subcategories: list[Subcategory]) -> int:
    """Estimate bytes freed by removing subcategories."""
    # Rough estimate: 1KB per subcategory + memory metadata
    return len(subcategories) * 1024
```

### 2. Silhouette Score Quality Metric

**Purpose**: Measure cluster quality using industry-standard silhouette score

**Implementation**:
```python
def calculate_silhouette_score(
    self,
    subcategories: list[Subcategory],
    memories: list[dict[str, Any]]
) -> float:
    """Calculate overall cluster quality using silhouette score.

    Silhouette score ranges from -1 to +1:
    - +1: Perfect clustering (dense, well-separated)
    -  0: Overlapping clusters
    - -1: Incorrect clustering

    Returns:
        Silhouette score (higher is better)
    """
    if len(subcategories) < 2:
        return 1.0  # Perfect if only 1 cluster

    # Build X (embeddings) and labels (subcategory assignments)
    X = []
    labels = []

    for subcat_idx, subcat in enumerate(subcategories):
        # Get embeddings for memories in this subcategory
        for memory in memories:
            # Check if memory belongs to this subcategory
            if self._is_memory_in_subcategory(memory, subcat):
                embedding = memory.get("embedding")
                if embedding is not None:
                    X.append(embedding)
                    labels.append(subcat_idx)

    if len(X) < 2:
        return 1.0  # Can't calculate with < 2 points

    # Calculate silhouette score
    from sklearn.metrics import silhouette_score
    import numpy as np

    X_array = np.array(X)
    return silhouette_score(X_array, labels)
```

**Helper Method**:
```python
def _is_memory_in_subcategory(
    self,
    memory: dict[str, Any],
    subcategory: Subcategory
) -> bool:
    """Check if a memory belongs to a subcategory.

    Uses centroid similarity as a proxy for membership.
    """
    embedding = memory.get("embedding")
    if not embedding or subcategory.centroid is None:
        return False

    similarity = self._cosine_similarity(embedding, subcategory.centroid)
    return similarity >= self.similarity_threshold
```

### 3. Evolution Snapshots

**Purpose**: Track evolution quality over time with before/after metrics

**Database Schema**:
```sql
-- Category evolution snapshots table
CREATE TABLE IF NOT EXISTS category_evolution_snapshots (
    id TEXT PRIMARY KEY,
    category TEXT NOT NULL,

    -- Before state (before evolution)
    before_subcategory_count INTEGER NOT NULL,
    before_silhouette REAL,
    before_total_memories INTEGER NOT NULL,

    -- After state (after evolution and decay)
    after_subcategory_count INTEGER NOT NULL,
    after_silhouette REAL,
    after_total_memories INTEGER NOT NULL,

    -- Decay results
    decayed_count INTEGER DEFAULT 0,
    archived_count INTEGER DEFAULT 0,
    bytes_freed INTEGER DEFAULT 0,

    -- Performance metrics
    evolution_duration_ms REAL,

    -- Metadata
    timestamp TEXT NOT NULL,

    FOREIGN KEY (category) REFERENCES top_level_categories(name)
);

-- Archived subcategories table (if archive_option is True)
CREATE TABLE IF NOT EXISTS archived_subcategories (
    id TEXT PRIMARY KEY,
    original_subcategory_id TEXT NOT NULL,
    parent_category TEXT NOT NULL,
    name TEXT NOT NULL,
    keywords TEXT,  -- JSON array
    memory_count INTEGER NOT NULL,
    centroid_fingerprint BLOB,

    -- Archive metadata
    archived_at TEXT NOT NULL,
    reason TEXT,  -- Why was this archived?
    original_data JSON  -- Full subcategory data
);
```

**Snapshot Record**:
```python
@dataclass
class EvolutionSnapshot:
    """Snapshot of category evolution results."""

    id: str
    category: TopLevelCategory
    before_state: dict[str, Any]
    after_state: dict[str, Any]
    decay_results: dict[str, Any]
    duration_ms: float
    timestamp: datetime

    def improvement_summary(self) -> str:
        """Generate human-readable summary of evolution impact."""
        silhouette_delta = (
            self.after_state["silhouette"] -
            self.before_state["silhouette"]
        )

        # Interpret the change
        if silhouette_delta > 0.1:
            level = "Significant improvement"
        elif silhouette_delta > 0:
            level = "Moderate improvement"
        elif silhouette_delta > -0.1:
            level = "Minor change (acceptable)"
        else:
            level = f"Quality decreased: {silhouette_delta:.2f} ⚠️"

        # Subcategory count change
        count_delta = (
            self.after_state["subcategory_count"] -
            self.before_state["subcategory_count"]
        )

        return (
            f"{level} (silhouette: {silhouette_delta:+.2f}), "
            f"{'Created' if count_delta > 0 else 'Removed' if count_delta < 0 else 'Maintained'} "
            f"{abs(count_delta)} subcategories, "
            f"Freed {format_bytes(self.decay_results.get('bytes_freed', 0))}"
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for database storage."""
        return {
            "id": self.id,
            "category": self.category.value,
            "before_subcategory_count": self.before_state["subcategory_count"],
            "before_silhouette": self.before_state.get("silhouette"),
            "before_total_memories": self.before_state["total_memories"],
            "after_subcategory_count": self.after_state["subcategory_count"],
            "after_silhouette": self.after_state.get("silhouette"),
            "after_total_memories": self.after_state["total_memories"],
            "decayed_count": self.decay_results.get("removed_count", 0),
            "archived_count": self.decay_results.get("archived_count", 0),
            "bytes_freed": self.decay_results.get("bytes_freed", 0),
            "evolution_duration_ms": self.duration_ms,
            "timestamp": self.timestamp.isoformat(),
        }

def format_bytes(bytes_count: int) -> str:
    """Format bytes as human-readable string."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_count < 1024:
            return f"{bytes_count:.1f} {unit}"
        bytes_count /= 1024
    return f"{bytes_count:.1f} TB"
```

### 4. Fingerprint Centroid Fix

**Current Bug** (line 481 in category_evolution.py):
```python
# WRONG: Just overwrites, losing information
subcategory.centroid_fingerprint = new_fingerprint
```

**Fixed Version**:
```python
def _update_fingerprint_centroid(
    self,
    subcategory: Subcategory,
    new_fingerprint: bytes
) -> None:
    """Update subcategory's fingerprint centroid using MinHash union.

    MinHash signatures support union operation via element-wise minimum,
    which approximates the Jaccard similarity of the union set.
    """
    if subcategory.centroid_fingerprint is None:
        # First fingerprint for this subcategory
        subcategory.centroid_fingerprint = new_fingerprint
        return

    # Aggregate using MinHash union (element-wise minimum)
    existing_sig = MinHashSignature.from_bytes(subcategory.centroid_fingerprint)
    new_sig = MinHashSignature.from_bytes(new_fingerprint)

    # Element-wise minimum approximates union of sets
    union_signature = np.minimum(existing_sig.signature, new_sig.signature)

    # Create new MinHashSignature with union
    aggregated_sig = MinHashSignature(
        signature=union_signature,
        num_hashes=existing_sig.num_hashes
    )

    subcategory.centroid_fingerprint = aggregated_sig.to_bytes()
```

---

## Implementation Plan

### Phase 1: Data Model & Configuration (30 min)

**Files**:
- `session_buddy/memory/evolution_config.py` (NEW)

**Tasks**:
1. Create `EvolutionConfig` dataclass with all settings
2. Create `DecayResult` dataclass for decay operation results
3. Add `last_accessed_at` and `access_count` to `Subcategory`
4. Add `record_access()` method to `Subcategory`

**Acceptance Criteria**:
- Config class with sensible defaults
- Subcategory can track access patterns
- Type hints throughout

### Phase 2: Silhouette Score Implementation (45 min)

**Files**:
- `session_buddy/memory/category_evolution.py` (MODIFY)

**Tasks**:
1. Implement `calculate_silhouette_score()` method
2. Implement helper `_is_memory_in_subcategory()`
3. Handle edge cases (1 cluster, <2 points, no embeddings)
4. Add scikit-learn to dependencies if needed

**Acceptance Criteria**:
- Returns score in range [-1, +1]
- Handles edge cases gracefully
- Logging for debugging

### Phase 3: Temporal Decay Implementation (45 min)

**Files**:
- `session_buddy/memory/category_evolution.py` (MODIFY)
- `session_buddy/adapters/reflection_adapter_oneiric.py` (MODIFY)

**Tasks**:
1. Implement `apply_temporal_decay()` method
2. Implement `_archive_subcategories()` method
3. Implement `_delete_subcategories()` method
4. Add snapshot table to database schema
5. Add archived_subcategories table

**Acceptance Criteria**:
- Removes subcategories inactive for 90+ days
- Respects `archive_option` config flag
- Estimates space freed
- Database operations handle errors

### Phase 4: Snapshots & Integration (30 min)

**Files**:
- `session_buddy/memory/category_evolution.py` (MODIFY)
- `session_buddy/tools/category_tools.py` (MODIFY)

**Tasks**:
1. Implement `create_evolution_snapshot()` method
2. Create `EvolutionSnapshot` dataclass
3. Wire up `evolve_categories()` MCP tool
4. Add snapshot creation to evolution workflow
5. Update `assign_subcategory()` to call `record_access()`

**Acceptance Criteria**:
- Snapshots saved to database
- Before/after metrics recorded
- Decay results tracked
- MCP tool returns quality metrics

### Phase 5: Fingerprint Fix (15 min)

**Files**:
- `session_buddy/memory/category_evolution.py` (MODIFY)

**Tasks**:
1. Replace overwrite logic in `_update_fingerprint_centroid()`
2. Use MinHash union (element-wise minimum)
3. Add unit test for fingerprint aggregation

**Acceptance Criteria**:
- Fingerprints aggregate properly
- No information loss
- Test passes

### Phase 6: Testing (30 min)

**Files**:
- `tests/unit/test_evolution_decay.py` (NEW)
- `tests/unit/test_evolution_metrics.py` (NEW)
- `tests/integration/test_evolution_workflow.py` (NEW)

**Tasks**:
1. Unit tests for decay logic (stale detection, archive, delete)
2. Unit tests for silhouette score calculation
3. Integration test for full evolution workflow
4. Mock database for testing

**Acceptance Criteria**:
- All tests pass
- Coverage > 80% for new code
- Integration test validates end-to-end flow

---

## Configuration Example

```yaml
# settings/session_buddy.yaml
evolution:
  temporal_decay_enabled: true
  temporal_decay_days: 90
  decay_access_threshold: 5
  archive_option: false  # Delete (set true to archive)

  quality:
    min_silhouette_score: 0.2
    calculate_metrics: true

  clustering:
    min_cluster_size: 3
    max_clusters: 10
    similarity_threshold: 0.75
    fingerprint_threshold: 0.90
```

---

## Usage Examples

### Manual Evolution with Metrics

```python
from session_buddy.tools.category_tools import evolve_categories

# Trigger evolution for skills category
result = await evolve_categories(
    category="skills",
    memory_count_threshold=10
)

print(f"Subcategories before: {result['before']['subcategory_count']}")
print(f"Subcategories after: {result['after']['subcategory_count']}")
print(f"Silhouette improvement: {result['silhouette_delta']:+.2f}")
print(f"Freed: {result['decay_results']['bytes_freed']}")
```

### MCP Tool Usage

```bash
# Evolve skills category
mcp call evolve_categories category="skills" memory_count_threshold=10

# View evolution history
mcp call get_evolution_history category="skills" limit=10

# Configure temporal decay
mcp call configure_evolution temporal_decay_days=60 archive_option=true
```

### Programmatic Evolution

```python
from session_buddy.memory.category_evolution import CategoryEvolutionEngine

engine = await get_evolution_engine()
config = EvolutionConfig(
    temporal_decay_days=90,
    archive_option=False
)

# Full evolution workflow
await engine.evolve_category(
    category=TopLevelCategory.SKILLS,
    memories=memories,
    config=config
)
```

---

## Migration Path

### Existing Data
1. Add `last_accessed_at` and `access_count` columns with defaults
2. Existing subcategories get `last_accessed_at = now()` and `access_count = 1`
3. No data loss during migration

### Backward Compatibility
1. Temporal decay is opt-in via `temporal_decay_enabled` flag
2. Default `archive_option = False` (delete, no archive table needed initially)
3. Silhouette score calculation gracefully handles missing embeddings

---

## Success Metrics

### Storage Efficiency
- **Target**: Reduce subcategory count by 10-20% through decay
- **Metric**: `bytes_freed` in snapshots
- **Timeframe**: First 30 days of usage

### Quality Tracking
- **Target**: Maintain silhouette score > 0.2
- **Metric**: Compare `before_silhouette` vs `after_silhouette`
- **Alert**: Investigate if score decreases by > 0.1

### Performance
- **Target**: Evolution completes in < 5 seconds for 1000 memories
- **Metric**: `evolution_duration_ms` in snapshots
- **Optimization**: Profile if consistently > 5 seconds

---

## Risks & Mitigations

### Risk: Over-Aggressive Decay
**Concern**: Important subcategories deleted due to temporary inactivity
**Mitigation**:
- High `decay_access_threshold` (default: 5)
- 90-day window (configurable)
- Archive option for recovery

### Risk: Silhouette Score Performance
**Concern**: O(n²) complexity for large datasets
**Mitigation**:
- Sample limit: calculate on max 1000 points
- Cache scores for 1 hour
- Async calculation

### Risk: Database Growth (Snapshots)
**Concern**: Snapshot table grows unbounded
**Mitigation**:
- Only snapshot when `memory_count_threshold` met
- Prune snapshots older than 1 year
- Aggregate old snapshots (monthly → yearly)

---

## Open Questions

1. **Q**: Should decay run before or after clustering?
   **A**: Before clustering - removes stale categories first

2. **Q**: How to handle subcategories with no embeddings?
   **A**: Still track access, but can't calculate silhouette for them

3. **Q**: Archive storage location?
   **A**: Same DuckDB database, separate table (cold storage)

---

## Next Steps

1. Review and approve this design
2. Create implementation plan (detailed task breakdown)
3. Begin Phase 1 implementation
4. Test each phase before proceeding
5. Deploy and monitor first week

---

## References

- scikit-learn silhouette_score: https://scikit-learn.org/stable/modules/generated/sklearn.metrics.silhouette_score.html
- MinHash signatures: Session-Buddy `utils/fingerprint.py`
- Category Evolution: Session-Buddy `memory/category_evolution.py`
- Clustering metrics: Davies-Bouldin, Calinski-Harabasz (future enhancements)

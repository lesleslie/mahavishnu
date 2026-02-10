# Config Sync Migration Plan

**Date**: 2026-02-06
**Status**: 🔄 In Progress
**Decision**: Move Claude/Qwen config sync from Mahavishnu to Session-Buddy (100% agreement)

---

## Executive Summary

**Migration**: Move Claude/Qwen config sync functionality from Mahavishnu (orchestrator) to Session-Buddy (manager).

**Rationale**:
- Role alignment: Config sync is a state management function (manager role)
- Deployment ubiquity: Session-Buddy runs everywhere, Mahavishnu is single-instance
- Dependency direction: Prevents circular dependency with SessionBuddyPool
- Architectural clarity: Foundational services belong in foundational components

**Source**: `/Users/les/Projects/mahavishnu/mahavishnu/sync_cli.py` (781 lines)
**Destination**: `/Users/les/Projects/session-buddy/session_buddy/llm_providers.py`

---

## Migration Phases

### Phase 1: Foundation in Session-Buddy ✅

**Target**: Add core sync functionality to Session-Buddy

**Tasks**:
1. Add `sync_provider_configs()` method to `LLMManager` class
2. Implement bidirectional sync (Claude ↔ Qwen)
3. Add MCP server synchronization
4. Add command/conversion tracking
5. Create MCP tool `sync_claude_qwen_config`

**Files**:
- `session_buddy/llm_providers.py` - Add sync method
- `session_buddy/mcp/tools/` - Create sync tool

**Acceptance**:
- [ ] Sync method works bidirectionally
- [ ] MCP tool registered and callable
- [ ] Unit tests passing
- [ ] Documentation updated

---

### Phase 2: Mahavishnu Deprecation Wrapper

**Target**: Add deprecated wrapper in Mahavishnu that calls Session-Buddy

**Tasks**:
1. Create `mahavishnu/sync_deprecated.py`
2. Add deprecation warnings
3. Route all calls to Session-Buddy MCP
4. Update CLI to use wrapper
5. Add migration notice to docs

**Files**:
- `mahavishnu/sync_deprecated.py` - New file
- `mahavishnu/cli.py` - Update CLI commands
- `docs/SYNC_MIGRATION_NOTICE.md` - Migration guide

**Acceptance**:
- [ ] Deprecation warnings displayed
- [ ] All functionality routes to Session-Buddy
- [ ] Migration notice published
- [ ] Tests updated

---

### Phase 3: Documentation & Testing

**Target**: Complete documentation and testing

**Tasks**:
1. Update Session-Buddy README
2. Create migration guide for users
3. Add integration tests
4. Update examples
5. Create deprecation timeline

**Files**:
- `session_buddy/README.md` - Add sync documentation
- `docs/CONFIG_SYNC_MIGRATION_GUIDE.md` - User migration guide
- `tests/integration/test_sync.py` - Integration tests

**Acceptance**:
- [ ] Documentation complete
- [ ] Migration guide published
- [ ] Integration tests passing
- [ ] Deprecation timeline set

---

### Phase 4: Removal (Future Release)

**Target**: Remove sync functionality from Mahavishnu

**Timeline**: After deprecation period (minimum 2 releases)

**Tasks**:
1. Remove `mahavishnu/sync_deprecated.py`
2. Remove `mahavishnu/sync_cli.py`
3. Remove sync CLI commands
4. Update dependencies
5. Final documentation update

**Acceptance**:
- [ ] All sync code removed
- [ ] No breaking changes for users
- [ ] Documentation updated
- [ ] Release notes published

---

## Implementation Details

### Sync Method Signature

```python
class LLMManager:
    async def sync_provider_configs(
        self,
        source: Literal["claude", "qwen"],
        destination: Literal["claude", "qwen"],
        sync_types: list[str] | None = None,
        skip_servers: list[str] | None = None,
    ) -> dict[str, Any]:
        """Sync provider configurations between Claude and Qwen.

        Args:
            source: Source config ("claude" or "qwen")
            destination: Destination config ("claude" or "qwen")
            sync_types: Types to sync (mcp, commands, extensions, all)
            skip_servers: MCP servers to skip during sync

        Returns:
            Sync result with stats and any errors
        """
```

### MCP Tool Specification

```yaml
name: sync_claude_qwen_config
description: Sync Claude and Qwen provider configurations
parameters:
  source:
    type: string
    enum: ["claude", "qwen"]
    description: Source configuration
  destination:
    type: string
    enum: ["claude", "qwen"]
    description: Destination configuration
  sync_types:
    type: array
    items:
      type: string
      enum: ["mcp", "commands", "extensions", "all"]
    description: Configuration types to sync
  skip_servers:
    type: array
    items:
      type: string
    description: MCP servers to skip
```

### Deprecation Wrapper Pattern

```python
# mahavishnu/sync_deprecated.py
import warnings
from functools import wraps

def deprecated_sync(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        warnings.warn(
            "Config sync is deprecated in Mahavishnu. "
            "Use Session-Buddy's sync_claude_qwen_config MCP tool instead. "
            "This will be removed in version 2.0.0.",
            DeprecationWarning,
            stacklevel=2
        )
        # Route to Session-Buddy MCP
        return route_to_session_buddy(func.__name__, *args, **kwargs)
    return wrapper
```

---

## Testing Strategy

### Unit Tests

```python
# tests/unit/test_sync_provider.py
async def test_sync_claude_to_qwen():
    """Test syncing Claude config to Qwen."""

async def test_sync_qwen_to_claude():
    """Test syncing Qwen config to Claude."""

async def test_merge_mcp_servers():
    """Test MCP server merging."""

async def test_skip_servers():
    """Test skipping specific servers."""
```

### Integration Tests

```python
# tests/integration/test_sync_integration.py
async def test_full_sync_cycle():
    """Test full sync cycle: Claude → Qwen → Claude."""

async def test_mcp_tool_invocation():
    """Test sync via MCP tool."""

async def test_deprecation_wrapper():
    """Test deprecation wrapper routes correctly."""
```

---

## Migration Timeline

| Phase | Duration | Start | End |
|-------|----------|-------|-----|
| Phase 1: Foundation | 2-3 days | 2026-02-06 | TBD |
| Phase 2: Deprecation | 1-2 days | TBD | TBD |
| Phase 3: Testing | 2-3 days | TBD | TBD |
| Deprecation Period | 2 releases | TBD | TBD |
| Phase 4: Removal | 1 day | TBD | TBD |

**Total Active Work**: 5-8 days
**Total Timeline**: ~2-3 months (including deprecation period)

---

## Rollback Plan

If critical issues are discovered:

1. **Phase 1-3**: Revert commits, restore Mahavishnu sync
2. **Phase 4**: Cannot rollback - feature removed entirely
3. **Data Loss**: No data loss risk (config files backed up)

**Rollback Commands**:
```bash
# Revert migration
git revert <migration-commits>

# Restore old sync
git checkout <pre-migration-tag> -- mahavishnu/sync_cli.py
```

---

## Success Criteria

- [ ] Session-Buddy can perform all sync operations
- [ ] Mahavishnu wrapper shows deprecation warnings
- [ ] All existing tests pass
- [ ] New integration tests pass
- [ ] Documentation complete and accurate
- [ ] User migration guide published
- [ ] No breaking changes for users
- [ ] Deprecation timeline communicated

---

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Session-Buddy not installed everywhere | High | Low | Add graceful fallback |
| MCP connection failures | Medium | Medium | Retry logic + error handling |
| Breaking user workflows | High | Low | Long deprecation period |
| Data loss during sync | High | Very Low | Backup before sync |
| Performance degradation | Low | Low | Optimize sync algorithm |

---

## Next Steps

1. ✅ Review and approve this plan
2. ⏳ Begin Phase 1 implementation
3. ⏳ Create tasks for each phase
4. ⏳ Execute migration phases
5. ⏳ Monitor deprecation period
6. ⏳ Complete removal in future release

---

**Plan Status**: 🔄 Awaiting Execution
**Last Updated**: 2026-02-06

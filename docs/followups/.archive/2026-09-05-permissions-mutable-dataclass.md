---
status: complete
role: historical
date: 2026-09-05
last_reviewed: 2026-09-05
topic: permissions-mutable-dataclass
---

# `PermissionInfo` dataclass is mutable — `recovery_hint` can be clobbered

## Status

**Resolved (2026-09-05)** — production fix at `mahavishnu/automation/permissions.py:26`
(`@dataclass` → `@dataclass(frozen=True)`); regression test at
`tests/unit/automation/test_permissions_extended.py::TestPermissionInfo::test_permission_info_is_frozen`
(verifies `AttributeError` / `FrozenInstanceError` on attempt to reassign
`recovery_hint`).

## Trigger

Coverage fanout 2026-09-05 (Brief 6) — subagent discovered the
`PermissionInfo` dataclass in `mahavishnu/automation/permissions.py` is
mutable. The `recovery_hint` field can be reassigned after construction.
If two callers share an instance, one can clobber the other's hint.

## Action

1. File `Open` followup note (this file).
2. Add `frozen=True` to the `@dataclass` decorator on `PermissionInfo`.
3. Verify no production code mutates `PermissionInfo` fields
   (`grep -rn 'permission_info\.' /Users/les/Projects/mahavishnu/mahavishnu/`).
4. Add regression test `test_permission_info_is_frozen` in `test_permissions_extended.py`.
5. Mark Resolved citing fix location + regression test name.

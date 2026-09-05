---
status: complete
role: historical
date: 2026-09-05
last_reviewed: 2026-09-05
topic: permissions-dead-cache-fields
---

# `PermissionChecker` dead cache fields — never read or written

## Status

**Resolved (2026-09-05)** — production fix at `mahavishnu/automation/permissions.py:69-71`
(removed `self._cached_accessibility` and `self._cached_screen_recording` assignments);
regression test at
`tests/unit/automation/test_permissions_extended.py::TestPermissionCheckerInit::test_init_records_platform_flag`
(now asserts `not hasattr(checker, "_cached_accessibility")` to lock the dead-code removal).

## Trigger

Coverage fanout 2026-09-05 (Brief 6: `automation/permissions.py`) — subagent
discovered `self._cached_accessibility` (line 72) and
`self._cached_screen_recording` (line 73) are set in `__init__` to `None`
but never read or written anywhere else in the module. The methods that
would logically consume them (`check_accessibility`, `check_screen_recording`,
`get_accessibility_status`, `get_screen_recording_status`) all re-invoke the
underlying macOS API on every call.

Looks like caching that doesn't cache. Either dead code or refactor remnant.

## Action

1. File `Open` followup note (this file).
2. Delete `self._cached_accessibility: PermissionStatus | None = None` (line 72).
3. Delete `self._cached_screen_recording: PermissionStatus | None = None` (line 73).
4. Update `tests/unit/automation/test_permissions_extended.py:212-213` — the two
   `assert checker._cached_accessibility is None` lines must go.
5. Mark Resolved citing fix location + regression test name.

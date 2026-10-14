---
status: complete
role: historical
date: 2026-09-05
last_reviewed: 2026-10-13
superseded_by: null
blocks_on: []
topic: permissions
---

# Permissions Fixes Batch (consolidated)

This followup consolidates three former followups that each tracked a
permissions / cache-field defect. All three are complete/historical.

Each section preserves the original content verbatim.

---

## 1. Accessibility prompt (formerly `2026-09-05-permissions-accessibility-prompt.md`)

# `request_accessibility` hardcodes `kAXTrustedCheckOptionPrompt: True`

## Status

**Resolved (2026-09-05)** — production fix at `mahavishnu/automation/permissions.py:190-217`
(new `prompt: bool = True` parameter; option dict now reads
`{"kAXTrustedCheckOptionPrompt": prompt}`); regression tests at
`tests/unit/automation/test_permissions_extended.py::TestRequestAccessibility::test_macos_options_contain_prompt_flag`
(default behavior, locked) and `::test_macos_prompt_false_skips_dialog` (new).

## Trigger

Coverage fanout 2026-09-05 (Brief 6) — subagent discovered
`request_accessibility` at `mahavishnu/automation/permissions.py:190-213`
hardcodes the option dict literal `{"kAXTrustedCheckOptionPrompt": True}`
on line 208. There is no parameter, flag, or kwarg that lets a caller
suppress the prompt.

A CI caller (or any non-interactive context) calling `request_accessibility`
in a loop would spam the user with the system permission dialog.

## Action

1. File `Open` followup note (this file).
2. Add `prompt: bool = True` parameter to `request_accessibility` signature.
3. Change line 208 to `options = {"kAXTrustedCheckOptionPrompt": prompt}`.
4. Update docstring to document the new parameter.
5. Add 2 regression tests in `test_permissions_extended.py`:
   - `test_request_accessibility_default_prompts` (locks existing behavior)
   - `test_request_accessibility_with_prompt_false_skips_dialog`
6. Mark Resolved citing fix location + regression test names.

---

## 2. Dead cache fields (formerly `2026-09-05-permissions-dead-cache-fields.md`)

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

---

## 3. Mutable dataclass (formerly `2026-09-05-permissions-mutable-dataclass.md`)

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

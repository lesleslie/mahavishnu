---
status: complete
role: historical
date: 2026-09-05
last_reviewed: 2026-09-05
topic: permissions-accessibility-prompt
---

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

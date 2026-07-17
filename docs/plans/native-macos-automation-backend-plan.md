---
status: draft
role: implementation
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
blocks_on: []
topic: terminal
---

# Plan: Native macOS Automation Backend

## Status

Draft — pending implementation (updated from multi-agent review)

## Goal

Replace deprecated/abandoned `PyXA` and `ATOMac` backends with a single `NativeMacOSBackend` that uses only built-in macOS tools:

- `osascript` — AppleScript execution (app lifecycle, window management, menu navigation)
- `screencapture` — built-in screenshot utility
- `cliclick` — CLI mouse/keyboard via `brew install cliclick`

## Scope

**In scope:**

- Remove `mahavishnu/automation/backends/pyxa.py`
- Remove `mahavishnu/automation/backends/atomac.py`
- Create `mahavishnu/automation/backends/native_macos.py`
- Update `mahavishnu/automation/backends/__init__.py` — remove PyXA/ATOMac, add NativeMacOSBackend
- Update `mahavishnu/automation/capabilities.py` — remove PYXA_CAPABILITIES and ATOMAC_CAPABILITIES, add NATIVE_MACOS_CAPABILITIES, remove `_check_pyxa` and `_check_atomac` from CapabilityDetector
- Update `mahavishnu/automation/manager.py` — remove PyXA/ATOMac from backend selection, add NativeMacOSBackend
- Update `mahavishnu/automation/__init__.py` — remove PyXA/ATOMac imports
- Update `mahavishnu/automation/models.py` — remove PyXA/ATOMac from `default_backend` options
- Update tests (see Test Changes section)
- Verify `uv sync --all-groups` passes
- Verify tests pass (`pytest -m automation` or similar)

**Out of scope:**

- UI element inspection (accessibility API access without atomac) — base class provides default `NotImplementedError`
- Window resize/move by ID (requires AX API not available via osascript) — returns `False` with warning log
- Implementing PyAutoGUI backend — it already exists as the cross-platform fallback

## Why Native Tools

| Tool | Type | Availability | Capabilities |
|------|------|-------------|---------------|
| `osascript` | Built-in | Always on macOS | App launch/quit/activate, window list, menu click, clipboard |
| `screencapture` | Built-in | Always on macOS | Full-screen and region screenshots |
| `cliclick` | Homebrew | `brew install cliclick` | Mouse move/click/drag/scroll, keyboard typed text |

osascript uses AppleScript — the officially supported macOS automation framework. It's what PyXA wraps under the hood (via JXA), so we get equivalent functionality without the Python library dependency.

## Capabilities of NativeMacOSBackend

| Capability | Source | Notes |
|------------|--------|-------|
| LAUNCH_APP | `osascript` | `tell application id "bundle.id" to launch` |
| QUIT_APP | `osascript` | `tell application id "bundle.id" to quit` |
| ACTIVATE_APP | `osascript` | `tell application id "bundle.id" to activate` |
| LIST_APPS | `osascript` via NSWorkspace | Running apps only |
| LIST_WINDOWS | `osascript` | `tell application "Finder" to get windows` |
| ACTIVATE_WINDOW | `osascript` | `set frontmost of window 1 to true` (1-based index, not ID) |
| RESIZE_WINDOW | ❌ | **Not supported.** Returns `False` with warning log. |
| MOVE_WINDOW | ❌ | **Not supported.** Returns `False` with warning log. |
| CLOSE_WINDOW | `osascript` | `close window 1` (1-based index) |
| CLICK_MENU | `osascript` | `click menu item "Save" of menu "File"` |
| LIST_MENUS | Partial | AppleScript can't enumerate menu items reliably |
| GET_CLIPBOARD | `osascript` | `the clipboard` |
| SET_CLIPBOARD | `osascript` | `set the clipboard to "text"` |
| TYPE_TEXT | `cliclick` | `cliclick t:"hello"` |
| PRESS_KEY | `cliclick` | `cliclick k:return` (uses `k:modifier+key` for combos like `k:cmd-return`) |
| CLICK | `cliclick` | `cliclick x,y` |
| DRAG | `cliclick` | `cliclick dc:x,y` |
| SCROLL | `cliclick` | `cliclick sw:0,100` |
| SCREENSHOT | `screencapture` | Full screen or region |
| LIST_SCREENS | `screencapture -l` | Get display list via `-l` flag |
| GET_UI_ELEMENTS | ❌ | Not available — base class default `NotImplementedError` |
| CLICK_UI_ELEMENT | ❌ | Not available — base class default `NotImplementedError` |

**Window ID note:** For this backend, `window_id` parameters in `activate_window()` and `close_window()` are treated as 1-based window indices (consistent with osascript's `window 1` syntax). Callers should pass integer indices as strings, not abstract IDs.

**Bundle ID note:** All application-targeting osascript calls require bundle identifiers (e.g., `'com.apple.Finder'`). The backend does NOT resolve display names to bundle IDs. Callers must provide valid bundle IDs. Consider this when writing automation workflows.

**Menu localization note:** `click_menu_item` uses hardcoded English menu paths. This will fail on non-English localized apps (e.g., French Finder uses "Enregistrer" not "Save"). Document this limitation.

Priority is **app lifecycle, window management, menu navigation, screenshots** — the most commonly needed automation tasks.

## Key Implementation Details

### `_run_sync` helper (required for async-to-sync bridging)

All subprocess calls to osascript/cliclick/screencapture are synchronous. Bridge to async using:

```python
from asyncio import get_event_loop
from concurrent.futures import ThreadPoolExecutor

_executor: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=2)

async def _run_sync(self, func: Callable[..., T], *args: Any) -> T:
    """Run blocking function in thread pool, return async result."""
    loop = get_event_loop()
    return await loop.run_in_executor(self._executor, func, *args)
```

`max_workers=2` allows some concurrent operations while keeping subprocess calls serialized.

### `_resolve_bundle_id` helper

osascript requires bundle IDs. Implement a helper that can resolve app names to bundle IDs using NSWorkspace via osascript:

```python
def _resolve_bundle_id(self, app_name_or_bundle_id: str) -> str:
    """Return bundle ID for an app. Pass-through if already a bundle ID."""
    # If it looks like a bundle ID (contains '.'), return as-is
    if '.' in app_name_or_bundle_id:
        return app_name_or_bundle_id
    # Otherwise resolve via osascript NSWorkspace
    script = f'''
    tell application "System Events"
        get bundle identifier of every application process whose name is "{app_name_or_bundle_id}"
    end tell
    '''
    result = self._run_sync(subprocess.run, ['osascript', '-e', script], ...)
    # Parse and return bundle ID
```

### cliclick modifier encoding

Key combos use `k:modifier+key` syntax:

- `k:return` — Return key
- `k:cmd-return` — Cmd+Return (for example)
- For multi-key combos, chain: `cliclick k:cmd t:a` (Cmd+A select all)

## File Changes

### 1. `mahavishnu/automation/backends/native_macos.py` (NEW)

~450 lines. Implements `DesktopAutomationBackend` using:

- `subprocess.run(["osascript", "-e", script])` for AppleScript
- `subprocess.run(["screencapture", ...])` for screenshots
- `subprocess.run(["cliclick", ...])` for input
- `_run_sync()` wrapper for async execution
- `_resolve_bundle_id()` for bundle ID handling

Key methods:

- `is_available()` — checks `sys.platform == "darwin"` AND `shutil.which("cliclick")` is not None
- `backend_name` → `"native_macos"`
- `resize_window()` → returns `False`, logs warning
- `move_window()` → returns `False`, logs warning
- All other application, window, menu, input, screenshot, screen methods

### 2. `mahavishnu/automation/backends/__init__.py`

```python
# Before
from mahavishnu.automation.backends.atomac import ATOMacBackend
from mahavishnu.automation.backends.pyxa import PyXABackend
__all__ = ["DesktopAutomationBackend", "PyXABackend", "ATOMacBackend", "PyAutoGUIBackend"]

# After
from mahavishnu.automation.backends.native_macos import NativeMacOSBackend
__all__ = ["DesktopAutomationBackend", "NativeMacOSBackend", "PyAutoGUIBackend"]
```

### 3. `mahavishnu/automation/capabilities.py`

- Remove `PYXA_CAPABILITIES` and `ATOMAC_CAPABILITIES` constants
- Add `NATIVE_MACOS_CAPABILITIES` with appropriate capability set (priority: 90)
- Remove `_check_pyxa()` and `_check_atomac()` methods from `CapabilityDetector`
- Update docstrings noting PyXA/ATOMac removed

### 4. `mahavishnu/automation/manager.py`

```python
# Before
backends_to_try = [
    ("pyxa", PyXABackend),
    ("atomac", ATOMacBackend),
    ("pyautogui", PyAutoGUIBackend),
]

# After
backends_to_try = [
    ("native_macos", NativeMacOSBackend),
    ("pyautogui", PyAutoGUIBackend),
]
```

Also update `preferred_backend` valid values and docstrings. `AutomationConfig.default_backend` must also be updated in `models.py`.

### 5. `mahavishnu/automation/__init__.py`

Remove PyXA and ATOMac imports.

### 6. `mahavishnu/automation/models.py`

Remove PyXA/ATOMac from `default_backend` comment/options.

### 7. Test Changes

Files to update:

- `tests/unit/test_automation_backends.py` — Remove `TestPyXABackend` and `TestATOMacBackend` classes. Add `TestNativeMacOSBackend`.
- `tests/unit/test_automation_manager.py` — Update patches from PyXABackend/ATOMacBackend to NativeMacOSBackend. Update backend name assertions.
- `tests/unit/test_automation_base.py` — Remove PYXA_CAPABILITIES and ATOMAC_CAPABILITIES imports/assertions. Add NATIVE_MACOS_CAPABILITIES.
- `tests/unit/test_automation_cli.py` — Update backend name assertions.

New test files to create:

- `tests/unit/test_native_macos_backend.py` — Test NativeMacOSBackend directly with subprocess mocking.

## Implementation Order

1. Create `native_macos.py` — implement all methods using osascript/screencapture/cliclick, including `_run_sync`, `_resolve_bundle_id`
1. Update `backends/__init__.py`
1. Update `capabilities.py`
1. Update `manager.py`
1. Update `automation/__init__.py`
1. Update `models.py`
1. Update tests
1. Run `uv sync --all-groups` — verify no broken deps
1. Run tests
1. Commit

## Verification

```bash
uv sync --all-groups
pytest tests/ -k automation -v  # or appropriate test marker
```

## Risks

### HIGH: AppleScript security prompts — headless/CI incompatibility

osascript triggers "Allow Automation" dialogs on first use for each app. In headless/CI environments (SSH, no display), this is a fundamental blocker — the dialog cannot be dismissed programmatically without user interaction.

**Mitigation:**

1. Detect headless mode (check `DISPLAY` env var, `SSH_CONNECTION`, no display) and surface a warning that AppleScript automation may be unavailable.
1. Document `tccutil allow AppleEvents bundle.id` for CI pre-approval.
1. Provide a graceful fallback to PyAutoGUI when automation is blocked.
1. This is an intrinsic macOS security limitation — cannot be fully worked around.

### MEDIUM: Window resize/move not supported

Breaks screenshot annotation, UI testing, and layout verification workflows that depend on repositioning windows.

**Mitigation:** When `resize_window()` or `move_window()` is called, return `False` and log a warning suggesting PyAutoGUI for coordinate-based positioning. Track as a future enhancement if AX API access becomes necessary.

### MEDIUM: osascript subprocess overhead

Each osascript call spawns a new process. For rapid-fire operations (e.g., typing characters one by one), this creates latency.

**Mitigation:** Batch operations where possible. Use `_run_sync` with `max_workers=2` to allow some concurrency. Document that rapid operations should prefer `cliclick` directly.

### MEDIUM: SIP-protected apps

Finder, Safari, System Settings have limited AppleScript dictionaries. Operations on these apps may silently fail or return incomplete data.

**Mitigation:** Document which apps are affected. Surface warnings when operations are likely to fail on protected apps.

### LOW: cliclick not installed

If `cliclick` is not installed, `is_available()` returns False and falls back to PyAutoGUI.

**Mitigation:** Provide a setup script `scripts/install-macos-automation-deps.sh` that runs `brew install cliclick`. The error message should guide users to this.

### Additional risks (not in original plan):

- **Bundle identifier format differences**: App names vs bundle IDs behave differently across macOS versions.
- **Application state assumptions**: AppleScript assumes apps are in a particular state — may not hold for all apps.
- **Multiple display/spaces edge cases**: Coordinate-based automation breaks when windows move between screens.
- **Menu localization**: Hardcoded English menu paths break on non-English localized apps.

## Out of Scope Gaps (Known Limitations)

These are acknowledged limitations that will NOT be resolved in this implementation:

1. **Window resize/move** — osascript cannot do this. Would need AX API (accessibility framework) via a different mechanism.
1. **UI element inspection** — `GET_UI_ELEMENTS` requires AX API not accessible via osascript.
1. **Menu listing** — AppleScript can't reliably enumerate menu items. `click_menu_item` works by path but `list_menus` returns limited info.
1. **Menu localization** — Hardcoded English paths. Apps localized to other languages will fail menu operations.
1. **Headless environments** — AppleScript automation is fundamentally incompatible with headless/CI environments.

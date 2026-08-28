# Bodai TUI & Admin Shell Surface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `bodai shell` (IPython REPL), `bodai dashboard` (Textual TUI), and `mahavishnu monitor --tui` (Textual TUI) all work end-to-end. Defensive `try/except ImportError` in `bodai/cli.py` is removed and replaced with a friendly install hint.

**Architecture:** Phase B-1 is verification + polish. The implementations already exist (verified 2026-08-25): `bodai/admin/shell.py::launch_shell`, `bodai/tui/dashboard.py::BodaiDashboard`, `mahavishnu/tui/monitor_app.py::MonitorApp`. The work is (a) wire `mahavishnu monitor --tui` if missing, (b) replace the defensive `try/except` with a friendly error message, (c) add tests using mock `IPython.terminal.embed.InteractiveShellEmbed` and Textual's `Pilot` harness.

**Tech Stack:** Python 3.14, Typer ≥0.9, Rich ≥13, Textual ≥0.40, IPython ≥9.14, pytest, Textual `Pilot` harness for headless tests.

**Spec:** `/Users/les/Projects/mahavishnu/docs/plans/2026-08-25-bodai-tui-shell-surface.md`

**Companion plan (upstream prerequisite):** `/Users/les/Projects/mahavishnu/docs/plans/2026-08-25-bodai-cli-audit.md` (Plan A) — Plan A's Phase 5 (umbrella composition) and Phase 4 (BodaiCLIBase in monitoring_cli) must land before Phase B-1 starts.

## Global Constraints

- **Python version**: `>=3.14`
- **Pre-1.0 merge policy**: direct to main, no PRs. Worktree pattern with `git update-ref` for landing.
- **Defensive `try/except ImportError` removal**: must be replaced with a friendly install hint (not a silent fallback). See Task B-1.4.
- **TUI/REPL smoke tests** (real interactive launches) are release-checklist items, NOT CI gates. CI uses mocks + Textual `Pilot` harness.
- **CHANGELOG convention**: every commit that changes user-facing surface updates the relevant `CHANGELOG.md` with `### Changed` / `### Added` / `### Removed` / `### Deprecated` sections.

______________________________________________________________________

## Phase B-1 — Verify & polish the three TUI surfaces

### Task B-1.1: Verify `bodai shell` IPython REPL opens

**Files:**

- Create: `/Users/les/Projects/bodai/tests/test_shell.py`

**Interfaces:**

- Consumes: `bodai/admin/shell.py::launch_shell` (already implemented)

- Produces: per-CI test that asserts `launch_shell` invokes IPython with the correct namespace

- [ ] **Step 1: Write the failing test**

```python
# tests/test_shell.py
from unittest.mock import patch, MagicMock

from bodai.admin.shell import launch_shell


def test_launch_shell_invokes_ipython_with_namespace():
    """`launch_shell` must construct an InteractiveShellEmbed with a
    namespace containing ecosystem config + portmap + storage_map."""
    with patch("bodai.admin.shell.load_ecosystem", return_value=MagicMock(components={})):
        with patch("bodai.admin.shell.load_portmap", return_value=MagicMock(mcp_range=(8680, 8700))):
            with patch("bodai.admin.shell.load_storage_map", return_value=MagicMock(databases={})):
                with patch("bodai.admin.shell.InteractiveShellEmbed") as mock_embed:
                    launch_shell()
                    # InteractiveShellEmbed was instantiated
                    assert mock_embed.called
                    # The constructed shell has a user_ns
                    call_kwargs = mock_embed.call_args.kwargs
                    assert "user_ns" in call_kwargs
                    ns = call_kwargs["user_ns"]
                    # Namespace contains the expected pre-loaded keys
                    for expected in ("ecosystem", "portmap", "storage_map"):
                        assert expected in ns, f"{expected} should be in IPython namespace"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/bodai && uv run pytest tests/test_shell.py -v`
Expected: FAIL (test file does not exist yet)

- [ ] **Step 3: Run test to verify it passes (after creating the test file)**

Run: `cd /Users/les/Projects/bodai && uv run pytest tests/test_shell.py -v`
Expected: PASS (the existing `launch_shell` already builds the namespace)

- [ ] **Step 4: Commit**

```bash
cd /Users/les/Projects/bodai
git add tests/test_shell.py
git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "test(bodai): verify shell invokes IPython with expected namespace"
```

______________________________________________________________________

### Task B-1.2: Verify `bodai dashboard` Textual TUI renders

**Files:**

- Create: `/Users/les/Projects/bodai/tests/test_dashboard.py`

**Interfaces:**

- Consumes: `bodai/tui/dashboard.py::BodaiDashboard`

- Produces: per-CI test using Textual's `Pilot` harness (no real TTY needed)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dashboard.py
from unittest.mock import patch, MagicMock
from textual.widgets import Static

from bodai.tui.dashboard import BodaiDashboard, ComponentWidget


def test_dashboard_renders_with_mock_check_all():
    """`BodaiDashboard` must render ComponentWidgets from check_all() output."""
    fake_results = {
        "akosha": {"status": "healthy", "role": "seer", "port": 8682},
        "dhara": {"status": "unhealthy", "role": "curator", "port": 8683},
    }
    with patch("bodai.tui.dashboard.check_all", return_value=fake_results):
        app = BodaiDashboard()
        assert app.title == "Bodai ecosystem health"
        # Build widget tree without rendering
        widget = ComponentWidget("akosha", fake_results["akosha"])
        # Each widget contains a status label
        labels = list(widget.compose())
        assert len(labels) == 2  # status label + detail label
        assert "akosha" in str(labels[0].renderable)


def test_dashboard_handles_empty_check_all():
    """BodaiDashboard initializes cleanly even when check_all returns empty."""
    with patch("bodai.tui.dashboard.check_all", return_value={}):
        app = BodaiDashboard()
        assert app.title == "Bodai ecosystem health"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/bodai && uv run pytest tests/test_dashboard.py -v`
Expected: FAIL

- [ ] **Step 3: Run test to verify it passes**

Run: `cd /Users/les/Projects/bodai && uv run pytest tests/test_dashboard.py -v`
Expected: PASS (the existing `BodaiDashboard` already handles this)

- [ ] **Step 4: Commit**

```bash
cd /Users/les/Projects/bodai
git add tests/test_dashboard.py
git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "test(bodai): verify dashboard renders with mock check_all"
```

______________________________________________________________________

### Task B-1.3: Wire `mahavishnu monitor --tui` (if not already wired)

**Files:**

- Read: `/Users/les/Projects/mahavishnu/mahavishnu/cli/monitoring_cli.py` (verify `monitor` Typer app exists; check whether `tui` command is registered)

- Modify if needed: `/Users/les/Projects/mahavishnu/mahavishnu/cli/monitoring_cli.py`

- Create: `/Users/les/Projects/mahavishnu/tests/cli/test_monitor_tui.py`

- [ ] **Step 1: Read monitoring_cli.py and check whether `tui` is registered**

Run: `grep -n 'monitor_app\|@.*command\|tui' /Users/les/Projects/mahavishnu/mahavishnu/cli/monitoring_cli.py`
Expected: locate the existing Typer app; check whether a `tui` command is registered.

- [ ] **Step 2: Write the failing test**

```python
# tests/cli/test_monitor_tui.py
from unittest.mock import patch, MagicMock
from typer.testing import CliRunner

# Import the monitoring Typer app
import sys
sys.path.insert(0, "/Users/les/Projects/mahavishnu")
from mahavishnu.cli.monitoring_cli import app  # or whatever it's called


def test_monitor_tui_command_registered():
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert "tui" in result.output


def test_monitor_tui_invokes_monitor_app():
    with patch("mahavishnu.cli.monitoring_cli.MonitorApp") as mock_app_cls:
        runner = CliRunner()
        result = runner.invoke(app, ["tui"])
        assert mock_app_cls.called
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /Users/les/Projects/mahavishnu && uv run pytest tests/cli/test_monitor_tui.py -v`
Expected: FAIL (test file missing OR test asserts `tui` not registered)

- [ ] **Step 4: Wire the `tui` command (if not already wired)**

If the existing `monitoring_cli.py` has a Typer app `app` but no `tui` command, add:

```python
@app.command("tui")
def monitor_tui() -> None:
    """Launch the Textual TUI for mahavishnu pool/worker status."""
    from mahavishnu.tui.monitor_app import MonitorApp
    MonitorApp().run()
```

(If the import path differs in the existing repo, adjust accordingly.)

- [ ] **Step 5: Run test + full suite**

Run: `cd /Users/les/Projects/mahavishnu && uv run pytest tests/cli/test_monitor_tui.py -v && uv run pytest tests/ -x`

- [ ] **Step 6: Update CHANGELOG.md**

```markdown
### Added
- **`mahavishnu monitor --tui`** (and `mahavishnu monitoring tui` shorthand) — launches the Textual TUI showing pools and workers. Implementation in `mahavishnu/tui/monitor_app.py::MonitorApp`.
```

- [ ] **Step 7: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/cli/monitoring_cli.py tests/cli/test_monitor_tui.py CHANGELOG.md
git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "feat(mahavishnu): wire monitor --tui command"
```

______________________________________________________________________

### Task B-1.4: Replace defensive `try/except` in `bodai/cli.py`

**Files:**

- Modify: `/Users/les/Projects/bodai/bodai/cli.py`

**Context:** The current code catches `ImportError` and prints "Shell not yet implemented" / "TUI not yet implemented". The modules exist; remove the catch and replace with a friendly install hint.

- [ ] **Step 1: Read the current shell + dashboard handlers**

Run: `grep -n -A 5 'def shell\|def dashboard' /Users/les/Projects/bodai/bodai/cli.py`

- [ ] **Step 2: Write the failing test**

In `/Users/les/Projects/bodai/tests/test_cli.py` (create if missing) or `tests/test_shell.py` (already created in B-1.1):

```python
def test_shell_command_raises_on_import_error():
    """When bodai.admin.shell raises ImportError, the shell command prints
    an install hint and exits with a non-zero code (NOT the misleading
    'Shell not yet implemented' message)."""
    from unittest.mock import patch
    import builtins
    real_import = builtins.__import__
    def fake_import(name, *args, **kwargs):
        if "bodai.admin.shell" in name:
            raise ImportError("No module named 'ipython'")
        return real_import(name, *args, **kwargs)
    with patch.object(builtins, "__import__", side_effect=fake_import):
        from typer.testing import CliRunner
        from bodai.cli import app
        runner = CliRunner()
        result = runner.invoke(app, ["shell"])
        # Exits non-zero
        assert result.exit_code != 0
        # Mentions "ipython" (the install hint)
        combined = result.output + (result.stderr or "")
        assert "ipython" in combined.lower()
        # Does NOT say "not yet implemented"
        assert "not yet implemented" not in combined.lower()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /Users/les/Projects/bodai && uv run pytest tests/test_shell.py -v`
Expected: FAIL (the test expects "ipython" in output, but current code says "Shell not yet implemented")

- [ ] **Step 4: Replace the try/except in bodai/cli.py**

Edit `/Users/les/Projects/bodai/bodai/cli.py`. Find the `shell` and `dashboard` command definitions:

```python
@app.command()
def shell() -> None:
    """Launch IPython admin shell."""
    console.print("[cyan]Launching IPython shell...[/cyan]")
    try:
        from bodai.admin.shell import launch_shell

        launch_shell()
    except ImportError:
        console.print("[red]Shell not yet implemented[/red]")


@app.command()
def dashboard() -> None:
    """Launch TUI health dashboard."""
    console.print("[cyan]Launching dashboard...[/cyan]")
    try:
        from bodai.tui.dashboard import BodaiDashboard

        tui_app = BodaiDashboard()
        tui_app.run()
    except ImportError:
        console.print("[red]TUI not yet implemented[/red]")
```

Replace with:

```python
@app.command()
def shell() -> None:
    """Launch IPython admin shell."""
    console.print("[cyan]Launching IPython shell...[/cyan]")
    try:
        from bodai.admin.shell import launch_shell
        launch_shell()
    except ImportError as e:
        console.print(f"[red]bodai shell requires ipython: {e}[/red]")
        console.print("[yellow]Install with: uv pip install 'bodai[shell]' or 'uv pip install ipython'[/yellow]")
        raise typer.Exit(1)


@app.command()
def dashboard() -> None:
    """Launch TUI health dashboard."""
    console.print("[cyan]Launching dashboard...[/cyan]")
    try:
        from bodai.tui.dashboard import BodaiDashboard
        tui_app = BodaiDashboard()
        tui_app.run()
    except ImportError as e:
        console.print(f"[red]bodai dashboard requires textual: {e}[/red]")
        console.print("[yellow]Install with: uv pip install 'bodai[dashboard]' or 'uv pip install textual'[/yellow]")
        raise typer.Exit(1)
```

- [ ] **Step 5: Run test + commit**

Run: `cd /Users/les/Projects/bodai && uv run pytest tests/ -x`

```bash
cd /Users/les/Projects/bodai
git add bodai/cli.py tests/test_shell.py CHANGELOG.md
git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "feat(bodai): replace defensive try/except with friendly install hint"
```

______________________________________________________________________

### Task B-1.5: Document the Bodai TUI contract

**Files:**

- Create: `/Users/les/Projects/mahavishnu/.claude/decisions/2026-08-25-bodai-tui-contract.md`

- Modify: `/Users/les/Projects/mahavishnu/.claude/decisions/README.md`

- [ ] **Step 1: Write the decision doc**

Create `/Users/les/Projects/mahavishnu/.claude/decisions/2026-08-25-bodai-tui-contract.md`:

```markdown
---
status: active
role: canonical
date: 2026-08-25
last_reviewed: 2026-08-25
superseded_by: null
topic: bodai-tui-contract
---

# Bodai TUI & Admin Shell Contract

Established by the 2026-08-25 ultracode CLI audit (Plan B).

## Decision rule

### 1. Cross-component TUI vs component-scoped TUI

| Surface | Lives in | Shows | Refresh |
|---|---|---|---|
| `bodai dashboard` | `bodai/tui/dashboard.py` | All 7 Core 7 components: name, role, port, status, version | 2-5s |
| `mahavishnu monitor --tui` | `mahavishnu/tui/monitor_app.py` | Mahavishnu-only: pools, workers, workflow state | 5s |
| **per-component admin shell** (5 of them) | `<repo>/shell/adapter.py` (subclasses `oneiric.shell.AdminShell`) | Component-specific namespace | on-demand |

Both TUIs coexist. `bodai dashboard` is the cross-component aggregator; `mahavishnu monitor --tui` is mahavishnu-internal.

### 2. Admin shell pattern

Each Core 7 with an admin shell (oneiric, dhara, session-buddy, akosha, mahavishnu) subclasses `oneiric.shell.AdminShell`. The base class lives in `oneiric/shell/core.py`. Adding a new admin shell = subclass + register CLI command.

### 3. Error handling: real error, not "not yet implemented"

`bodai shell` and `bodai dashboard` MUST surface real `ImportError` tracebacks (with install hints) when their dependencies are missing. The "Shell not yet implemented" / "TUI not yet implemented" fallback messages are removed as of 2026-08-25.

### 4. Tests

- Per-CI: mock-based tests for shell namespace, Textual `Pilot` harness for dashboard rendering, mocked `MonitorApp` for `mahavishnu monitor --tui`
- Release checklist: real interactive smoke test on a workstation (TUIs need real terminals)

## Enforcement

- Pre-commit hook: not enforced (TUIs are interactive; not testable in CI)
- Per-CI: pytest with mocks + Textual `Pilot`
- Release: manual smoke test in checklist
```

- [ ] **Step 2: Add row to decisions index**

Append to `/Users/les/Projects/mahavishnu/.claude/decisions/README.md`:

```markdown
| `2026-08-25-bodai-tui-contract.md` | Bodai TUI contract (cross-component vs component-scoped, AdminShell pattern) | active |
```

- [ ] **Step 3: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add .claude/decisions/2026-08-25-bodai-tui-contract.md .claude/decisions/README.md
git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "docs(mahavishnu): add Bodai TUI contract decision + index entry"
```

______________________________________________________________________

### Task B-1.6: Update READMEs (bodai + mahavishnu)

**Files:**

- Modify: `/Users/les/Projects/bodai/README.md`

- Modify: `/Users/les/Projects/mahavishnu/README.md`

- [ ] **Step 1: Update bodai README**

Add a section to `/Users/les/Projects/bodai/README.md`:

````markdown
## `bodai shell` — IPython admin shell

```bash
bodai shell
````

Launches an IPython REPL pre-loaded with:

- `ecosystem` — BodaiEcosystem (all 7 components)
- `portmap` — PortMap
- `storage_map` — StorageMap

Requires `ipython` (install with `uv pip install 'bodai[shell]'`).

## `bodai dashboard` — Textual TUI

```bash
bodai dashboard
```

Live Textual TUI showing all 7 Core 7 components with health/role/port. Refreshes every 2-5s.

Requires `textual` (install with `uv pip install 'bodai[dashboard]'`).

````

- [ ] **Step 2: Update mahavishnu README**

Add a section to `/Users/les/Projects/mahavishnu/README.md`:
```markdown
## `mahavishnu monitor --tui` — pools/workers Textual TUI

```bash
mahavishnu monitor --tui
# or
mahavishnu monitoring tui
````

Live Textual TUI showing mahavishnu's pool/worker status. Refreshes every 5s.

Distinct from `bodai dashboard` (which is cross-component). Use
`mahavishnu monitor --tui` for mahavishnu-internal observability; use
`bodai dashboard` for cross-component health.

````

- [ ] **Step 3: Commit (2 separate commits)**

```bash
cd /Users/les/Projects/bodai
git add README.md
git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "docs(bodai): document bodai shell + dashboard in README"

cd /Users/les/Projects/mahavishnu
git add README.md
git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "docs(mahavishnu): document monitor --tui in README"
````

______________________________________________________________________

## Execution order

```
Prerequisite: Plan A Phase 5 (umbrella composition) + Plan A Phase 4.3 (BodaiCLIBase conversion) land first.

Day 1:
  Task B-1.1 (verify bodai shell IPython REPL)
  Task B-1.2 (verify bodai dashboard Textual TUI)

Day 2:
  Task B-1.3 (wire mahavishnu monitor --tui; conditional based on whether it's already wired)
  Task B-1.4 (replace defensive try/except with install hint)

Day 3:
  Task B-1.5 (BODAI TUI contract decision doc)
  Task B-1.6 (README updates)
```

______________________________________________________________________

## Self-review

**Spec coverage:**

- Spec §1 Outcome — Tasks B-1.1, B-1.2, B-1.3, B-1.4 verify the three TUI surfaces work end-to-end
- Spec §2 Goals — Tasks B-1.1 (G1), B-1.2 (G2), B-1.3 (G3), B-1.4 (G4), B-1.5 (G5); G6 deferred (cross-shell UX standardization is future work)
- Spec §3 Non-Goals — verified; no task contradicts (e.g., no new shells created)
- Spec §4 Current Findings — Tasks B-1.4 (defensive try/except misleading message), B-1.3 (mahavishnu tui wire)
- Spec §5 Phase B-1 — fully covered (B-1.1 through B-1.6)
- Spec §6 Required Code Changes — all files listed appear in implementation tasks
- Spec §7 Decision Rule — each item maps to a runnable gate (per-CI pytest tests + manual smoke checklist)
- Spec §8 Risks — Risk #1 mitigated by friendly install hint (B-1.4); Risk #3 documented in B-1.3 sequencing note

**Placeholder scan:** No TBDs. Each test code block is concrete. Each commit message is specific.

**Type consistency:**

- `BodaiDashboard().run()` — used in B-1.2 and B-1.6
- `MonitorApp().run()` — used in B-1.3
- `from bodai.admin.shell import launch_shell` — consistent in B-1.1 and B-1.4

**Gaps:**

- Cross-shell UX standardization (Plan B Phase B-2 future) — explicitly out of scope; documented in spec
- Akosha stub implementations (Plan B Phase B-3 future) — out of scope; documented in spec
- bodai shell cross-CLI mount (Plan B Phase B-4 future) — out of scope
- Real-time event stream (Plan B Phase B-5 future) — out of scope

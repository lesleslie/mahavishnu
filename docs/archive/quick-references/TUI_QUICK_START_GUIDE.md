# Terminal UI/UX Quick Start Guide
## Implementation Roadmap for Mahavishnu TUI

**Generated**: 2026-02-06
**Status**: Ready for Development
**Time to First Prototype**: 2-3 days

---

## Executive Summary

This document provides a **concise, actionable roadmap** for implementing next-generation TUI features in Mahavishnu. For detailed analysis, see [TUI_UI_INNOVATION_ANALYSIS.md](./TUI_UI_INNOVATION_ANALYSIS.md).

---

## Part 1: The 80/20 Rule (Quick Wins)

### Implement First (80% of value, 20% of effort)

1. **Command Palette** (4 hours)
   - Ctrl+K fuzzy search
   - All commands discoverable
   - No more memorizing

2. **Interactive Tables** (4 hours)
   - Sortable columns
   - Filterable rows
   - Keyboard navigation

3. **Real-time Dashboard** (8 hours)
   - Auto-refresh metrics
   - Color-coded status
   - Progress bars

4. **Contextual Help** (4 hours)
   - Tooltips on hover
   - Help screen (?)
   - Error explanations

**Total Time**: ~20 hours (2-3 days)
**Value Delivered**: Massive UX improvement

---

## Part 2: Tech Stack Decision

### Recommended Stack

**Framework**: **Textual** (Python)
- Why: Modern, async, production-ready
- Widget library: Built-in
- Styling: CSS-like syntax
- Testing: Headless mode included

**Dependencies**:
```toml
[project.dependencies]
textual = ">=0.80.0"
rich = ">=14.0.0"
httpx = ">=0.27.0"
pydantic = ">=2.0.0"
```

**Why Not Alternatives?**

| Framework | Why Not for Us |
|-----------|----------------|
| Rich | Display only, no interactivity |
| Urwid | Too low-level, verbose |
| Prompt_toolkit | Too basic for complex UIs |
| Ink | Node.js only, not Python |

---

## Part 3: 3-Day Implementation Plan

### Day 1: Foundation (8 hours)

**Goal**: Basic TUI app running

**Tasks**:
1. ✅ Setup Textual app skeleton (1h)
2. ✅ Implement command palette (3h)
3. ✅ Pool list table (2h)
4. ✅ Basic navigation (2h)

**Deliverable**:
```bash
# Run TUI
mahavishnu tui

# Features working:
# - Ctrl+K opens command palette
# - Arrow keys navigate pools
# - Enter shows pool details
# - 'q' quits
```

### Day 2: Real-time Features (8 hours)

**Goal**: Live monitoring dashboard

**Tasks**:
1. ✅ Backend integration (async HTTP) (2h)
2. ✅ Auto-refresh timer (1h)
3. ✅ Metrics dashboard (3h)
4. ✅ Progress bars (2h)

**Deliverable**:
```bash
# Dashboard auto-refreshes every 1s
# Shows:
# - Pool status (live)
# - Worker utilization
# - Active tasks
# - Health indicators
```

### Day 3: Polish & Testing (8 hours)

**Goal**: Production-ready quality

**Tasks**:
1. ✅ Error handling (2h)
2. ✅ Help system (2h)
3. ✅ Keyboard shortcuts (1h)
4. ✅ User testing (3h)

**Deliverable**:
```bash
# Production-ready TUI
# - All errors have explanations
# - Help available everywhere
# - Consistent keybindings
# - Tested with 3 users
```

---

## Part 4: Code Skeleton

### Project Structure

```
mahavishnu/
├── tui/
│   ├── __init__.py
│   ├── app.py              # Main TUI application
│   ├── widgets/
│   │   ├── __init__.py
│   │   ├── command_palette.py
│   │   ├── pool_list.py
│   │   ├── dashboard.py
│   │   └── workflow_builder.py
│   ├── screens/
│   │   ├── __init__.py
│   │   ├── pool_detail.py
│   │   ├── workflow_editor.py
│   │   └── help_screen.py
│   └── styles/
│       ├── __init__.py
│       └── defaults.css
├── cli.py                  # Add 'mahavishnu tui' command
```

### Minimal App Example

```python
# mahavishnu/tui/app.py

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, DataTable
from textual.containers import Vertical
from textual.binding import Binding

class MahavishnuTUI(App):
    """Mahavishnu Terminal UI"""

    TITLE = "Mahavishnu"
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+k", "command_palette", "Commands"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="pools")
        yield Footer()

    def on_mount(self) -> None:
        """Initialize"""
        table = self.query_one(DataTable)
        table.add_columns("Pool ID", "Type", "Workers", "Status")
        # Load pools...

    def action_command_palette(self) -> None:
        """Show command palette"""
        from textual.widgets import Input, DataTable

        # Simple palette
        self.push_screen(CommandPalette())

# Run app
if __name__ == "__main__":
    app = MahavishnuTUI()
    app.run()
```

### Command Palette Widget

```python
# mahavishnu/tui/widgets/command_palette.py

from textual.containers import Vertical
from textual.widgets import Input, DataTable
from textual.screen import ModalScreen

class CommandPalette(ModalScreen):
    """Command palette modal"""

    BINDINGS = [("escape", "app.pop_screen", "Close")]

    def compose(self):
        yield Input(placeholder="Search commands...", id="search")
        yield DataTable(id="results")

    def on_mount(self):
        """Initialize command list"""
        table = self.query_one(DataTable)
        table.add_columns("Command", "Description", "Shortcut")

        commands = [
            ("list-pools", "List all pools", "p"),
            ("spawn-pool", "Create new pool", "s"),
            ("execute-task", "Execute task", "e"),
        ]

        for cmd, desc, key in commands:
            table.add_row(cmd, desc, key)

    def on_input_changed(self, event: Input.Changed):
        """Filter commands"""
        query = event.value.lower()
        table = self.query_one(DataTable)
        table.clear()

        # Filter based on query...
```

---

## Part 5: Integration with Existing CLI

### Add TUI Command to CLI

```python
# mahavishnu/cli.py

import typer
from rich.console import Console

app = typer.Typer()

@app.command()
def tui():
    """Launch terminal UI"""
    from mahavishnu.tui.app import MahavishnuTUI

    # Run TUI
    ui = MahavishnuTUI()
    ui.run()

# Keep existing commands
@app.command()
def list_repos():
    """List repositories (CLI mode)"""
    # Existing implementation...
```

### Backend Integration

```python
# mahavishnu/tui/backend.py

import httpx
from typing import List, Dict, Any

class TUIBackend:
    """Async backend client for TUI"""

    def __init__(self, base_url: str = "http://localhost:8678"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=30.0)

    async def list_pools(self) -> List[Dict[str, Any]]:
        """Get all pools"""
        resp = await self.client.get(f"{self.base_url}/pools")
        return resp.json()

    async def spawn_pool(self, config: dict) -> Dict[str, Any]:
        """Spawn new pool"""
        resp = await self.client.post(
            f"{self.base_url}/pools",
            json=config
        )
        return resp.json()

    async def close(self):
        """Close connection"""
        await self.client.aclose()
```

---

## Part 6: Key Features Implementation

### Feature 1: Command Palette

**Priority**: ⭐⭐⭐⭐⭐ (Critical)
**Time**: 4 hours

**Implementation**:
```python
class CommandPalette(ModalScreen):
    """Ctrl+K command palette"""

    COMMANDS = {
        "pools": {
            "list": "List all pools",
            "spawn": "Create new pool",
            "scale": "Scale pool workers",
        },
        "workflows": {
            "list": "List workflows",
            "create": "Create workflow",
            "run": "Execute workflow",
        },
    }

    def compose(self):
        yield Input(placeholder="Type command...", id="search")
        yield DataTable()

    def on_input_changed(self, event):
        """Fuzzy search commands"""
        query = event.value.lower()
        table = self.query_one(DataTable)

        # Fuzzy match
        for category, commands in self.COMMANDS.items():
            for cmd, desc in commands.items():
                if query in cmd or query in desc.lower():
                    table.add_row(
                        f"{category}.{cmd}",
                        desc
                    )
```

### Feature 2: Real-time Dashboard

**Priority**: ⭐⭐⭐⭐⭐ (Critical)
**Time**: 8 hours

**Implementation**:
```python
from textual.timer import Timer
from textual.widgets import ProgressBar

class Dashboard(Vertical):
    """Real-time monitoring dashboard"""

    def on_mount(self):
        """Start update timer"""
        self.set_interval(1.0, self.update)

    async def update(self):
        """Update metrics"""
        pools = await self.app.backend.list_pools()

        for pool in pools:
            # Update progress bars
            progress = self.query_one(f"#progress-{pool['id']}", ProgressBar)
            progress.progress = pool['utilization']

            # Update status indicators
            status = self.query_one(f"#status-{pool['id']}", Static)
            color = "green" if pool['healthy'] else "red"
            status.update(f"[{color}]{pool['status']}[/]")
```

### Feature 3: Interactive Tables

**Priority**: ⭐⭐⭐⭐ (High)
**Time**: 4 hours

**Implementation**:
```python
class SortableDataTable(DataTable):
    """DataTable with sorting"""

    def on_data_table_header_clicked(self, event):
        """Sort by column"""
        column_key = event.column_key
        self.sort(column_key)

class FilterableDataTable(DataTable):
    """DataTable with filtering"""

    def filter(self, query: str):
        """Filter rows"""
        for row in self.rows:
            if query.lower() in str(row).lower():
                row.show()
            else:
                row.hide()
```

---

## Part 7: Testing Strategy

### Unit Tests

```python
# tests/tui/test_command_palette.py

from textual.widgets import Input
from mahavishnu.tui.widgets.command_palette import CommandPalette

async def test_command_palette_filter():
    """Test command filtering"""
    app = MahavishnuTUI()
    async with app.run_test() as pilot:
        # Open command palette
        await pilot.press("ctrl+k")

        # Type query
        input_widget = app.query_one(Input)
        input_widget.value = "pool"

        # Check filtered results
        table = app.query_one(DataTable)
        assert len(table.rows) > 0
        assert all("pool" in str(row).lower() for row in table.rows)
```

### Integration Tests

```python
# tests/tui/test_backend_integration.py

import pytest
from mahavishnu.tui.backend import TUIBackend

@pytest.mark.asyncio
async def test_list_pools():
    """Test backend integration"""
    backend = TUIBackend()

    pools = await backend.list_pools()
    assert isinstance(pools, list)

    await backend.close()
```

### User Testing

**Guerrilla Testing Protocol**:

1. **Recruit**: 3-5 developers
2. **Tasks**:
   - "Spawn a pool with 5 workers"
   - "Find all repos tagged 'python'"
   - "Check health of all pools"
   - "Execute a task on a pool"
3. **Measure**:
   - Time to complete
   - Error rate
   - Satisfaction (1-5)
4. **Iterate**: Fix issues and repeat

---

## Part 8: Common Pitfalls

### Pitfall 1: Blocking the UI

**Bad**:
```python
def load_data():
    # Blocks for 5 seconds
    pools = requests.get("/pools").json()
```

**Good**:
```python
async def load_data():
    # Non-blocking
    async with httpx.AsyncClient() as client:
        pools = (await client.get("/pools")).json()
```

### Pitfall 2: Not Handling Resize

**Bad**:
```python
# Assumes 80x24 terminal
table = Table(width=80)
```

**Good**:
```python
# Responsive layout
from textual.containers import Container

container = Container()
table = Table()  # Auto-sizes
```

### Pitfall 3: Hardcoded Colors

**Bad**:
```python
print("\033[31mError\033[0m")  # Red
```

**Good**:
```python
# Use semantic colors
console.print("[error]Error[/error]")

# CSS-based themes
.error {
    text-style: bold;
    color: $error;  # Themeable
}
```

### Pitfall 4: No Feedback

**Bad**:
```python
# User doesn't know what's happening
result = long_operation()
```

**Good**:
```python
# Show progress
from rich.progress import Progress

with Progress() as progress:
    task = progress.add_task("Processing...", total=100)
    result = long_operation(progress.update)
```

---

## Part 9: Performance Guidelines

### Target Performance

| Metric | Target | How to Measure |
|--------|--------|----------------|
| UI Responsiveness | < 100ms | Time from keypress to render |
| Backend Latency | < 500ms | API call duration |
| Memory Usage | < 100MB | `memory_profiler` |
| Startup Time | < 2s | Time to `app.run()` |

### Optimization Tips

1. **Debounce Input**: Wait 300ms after typing before searching
2. **Virtual Scrolling**: Only render visible rows
3. **Lazy Loading**: Load data on demand
4. **Caching**: Cache API responses
5. **Pagination**: Limit to 100 items per page

---

## Part 10: Success Criteria

### MVP Success (Day 3)

- [ ] User can list pools in < 5 seconds
- [ ] Command palette works for all commands
- [ ] Dashboard auto-refreshes
- [ ] Help available via `?` key
- [ ] No crashes during normal usage
- [ ] 3/5 users can complete tasks without help

### Production Success (Week 8)

- [ ] 90% task completion rate
- [ ] < 1 error per session
- [ ] 4.5/5 user satisfaction
- [ ] < 2s time to first action
- [ ] Comprehensive documentation
- [ ] 100% test coverage for widgets

---

## Part 11: Next Steps

### Immediate Actions

1. **Install Dependencies**
   ```bash
   pip install textual rich httpx
   ```

2. **Create TUI Directory**
   ```bash
   mkdir -p mahavishnu/tui/{widgets,screens,styles}
   ```

3. **Initialize App**
   ```bash
   # Copy skeleton from this doc
   # Start with basic app
   ```

4. **First Feature: Command Palette**
   - Implement fuzzy search
   - Add keyboard shortcuts
   - Test with users

### Learning Resources

**Textual Tutorial**: https://textual.textual.io/tutorial/introduction/
**Example Apps**: https://github.com/Textualize/textual/tree/main/examples
**Widget Gallery**: https://textual.textual.io/widgets/

---

## Part 12: FAQ

**Q: Will this work on all terminals?**
A: Yes, Textual works on any terminal with truecolor support (99% of modern terminals).

**Q: Can I use mouse in terminal?**
A: Yes, Textual has full mouse support. But we'll prioritize keyboard for efficiency.

**Q: Will this replace the CLI?**
A: No, TUI is complementary. CLI for scripts, TUI for interactive use.

**Q: How big is the dependency?**
A: Textual + Rich = ~5MB. Negligible impact.

**Q: Can I test TUI in CI?**
A: Yes, Textual has headless mode for automated testing.

**Q: What about accessibility?**
A: Textual has screen reader support. We'll follow WCAG guidelines.

---

## Conclusion

**Start building today.**

The terminal is ready for a UX revolution. With Textual, we can build beautiful, discoverable interfaces in 2-3 days.

**Quick Wins** (Day 1-3):
1. Command palette
2. Interactive tables
3. Real-time dashboard
4. Contextual help

**Moonshots** (Week 4-8):
1. Visual workflow builder
2. AI command assistant
3. Collaborative editing
4. Time-travel debugging

Let's make Mahavishnu the most user-friendly CLI in the ecosystem.

---

**Resources**:
- [Full Analysis](./TUI_UI_INNOVATION_ANALYSIS.md)
- [Textual Docs](https://textual.textual.io/)
- [Example Projects](https://github.com/Textualize/textual/tree/main/examples)

**Generated**: 2026-02-06
**Status**: Ready to implement

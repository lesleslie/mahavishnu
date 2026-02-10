# Terminal UI Architecture & Design Patterns
## Visual Reference for Mahavishnu TUI Implementation

**Generated**: 2026-02-06
**Status**: Design Reference

---

## Part 1: System Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        User (Developer)                         │
└────────────────────────────┬────────────────────────────────────┘
                             │
                    ┌────────▼─────────┐
                    │  Terminal App    │
                    │  (Kitty/iTerm2)  │
                    └────────┬─────────┘
                             │
        ┌────────────────────┴────────────────────┐
        │                                         │
┌───────▼─────────┐                   ┌──────────▼──────────┐
│   CLI Mode      │                   │   TUI Mode (Textual)│
│  (Current)      │                   │   (New Feature)     │
│                 │                   │                     │
│ mahavishnu      │                   │ mahavishnu tui      │
│   list-repos    │                   │                     │
│   pool spawn    │                   │  ┌────────────────┐ │
│   sweep         │                   │  │ Command Palette│ │
└─────────────────┘                   │  │ (Ctrl+K)       │ │
                                      │  └────────────────┘ │
                                      │                     │
                                      │  ┌────────────────┐ │
                                      │  │ Pool Dashboard │ │
                                      │  │ (Real-time)    │ │
                                      │  └────────────────┘ │
                                      │                     │
                                      │  ┌────────────────┐ │
                                      │  │ Workflow       │ │
                                      │  │ Builder        │ │
                                      │  └────────────────┘ │
                                      └──────────┬──────────┘
                                                 │
                                                 │ MCP Protocol
                                                 │
                                      ┌──────────▼──────────┐
                                      │  Mahavishnu Backend │
                                      │  (MCP Server)       │
                                      │                     │
                                      │  • Pool Manager     │
                                      │  • Workflow Engine │
                                      │  • Task Scheduler  │
                                      └─────────────────────┘
```

### Component Hierarchy

```
MahavishnuTUI (App)
├── Header (Title, Status)
├── Footer (Keybindings, Status)
├── Main Content (TabbedContent)
│   ├── Tab: Pools
│   │   ├── PoolList (DataTable)
│   │   ├── PoolDetail (Vertical)
│   │   │   ├── Metrics (Panel)
│   │   │   ├── Workers (DataTable)
│   │   │   └── Tasks (DataTable)
│   │   └── Actions (Horizontal)
│   │       ├── Button: Spawn
│   │       ├── Button: Scale
│   │       └── Button: Close
│   │
│   ├── Tab: Workflows
│   │   ├── WorkflowList (DataTable)
│   │   ├── WorkflowBuilder (TreeView)
│   │   │   ├── Start Node
│   │   │   ├── Process Nodes
│   │   │   └── End Node
│   │   └── Actions
│   │       ├── Button: New
│   │       ├── Button: Edit
│   │       └── Button: Run
│   │
│   ├── Tab: Repositories
│   │   ├── RepoList (DataTable)
│   │   ├── RepoDetail (Panel)
│   │   └── Filters (Input)
│   │
│   └── Tab: Monitor
│       ├── Dashboard (Grid)
│       │   ├── PoolHealth (DataTable)
│       │   ├── TaskProgress (ProgressBar)
│       │   ├── ResourceUsage (BarChart)
│       │   └── LogViewer (TextArea)
│       └── Auto-refresh Timer
│
├── Overlays (ModalScreens)
│   ├── CommandPalette (Ctrl+K)
│   │   ├── SearchInput
│   │   └── ResultsTable
│   ├── HelpScreen (F1)
│   │   ├── Keybindings (Table)
│   │   └── ContextHelp
│   └── ErrorDialog
│       ├── ErrorMessage
│       └── SolutionHint
│
└── Themes
    ├── Dark (Default)
    ├── Light
    └── Custom
```

---

## Part 2: Screen Layouts

### Screen 1: Pool List (Main View)

```
┌──────────────────────────────────────────────────────────────────┐
│  Mahavishnu Orchestrator                    [?] Help  [Q] Quit  │ ← Header
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─ Pools ──────────────────────────────────────────────────┐   │
│  │                                                            │   │
│  │  ┌──────────────────────────────────────────────────┐    │   │
│  │  │ Pool ID     │ Type       │ Workers │ Status      │    │   │
│  │  ├──────────────────────────────────────────────────┤    │   │
│  │  │ local-pool  │ mahavishnu │ 5/10    │ Running ✅  │← Cursor│
│  │  │ remote-pool │ session-b  │ 3/3     │ Active ✅   │    │   │
│  │  │ k8s-pool    │ kubernetes│ 12/20   │ Scaling ⏳  │    │   │
│  │  │ test-pool   │ mahavishnu │ 0/5     │ Stopped ⏸️  │    │   │
│  │  └──────────────────────────────────────────────────┘    │   │
│  │                                                            │   │
│  │  Actions: [Enter] Details  [S] Spawn  [D] Delete          │   │
│  └────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌─ Quick Actions ─────────────────────────────────────────┐  │
│  │ [Spawn Pool]  [Scale Pool]  [Execute Task]  [View Logs] │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│  ^K:Cmd  ^R:Refresh  ?:Help  Q:Quit          localhost:8678    │ ← Footer
└──────────────────────────────────────────────────────────────────┘
```

### Screen 2: Pool Details

```
┌──────────────────────────────────────────────────────────────────┐
│  Pool: local-pool                                    [Esc] Back  │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─ Overview ────────────────────────────────────────────────┐ │
│  │  ID: local-pool                                           │ │
│  │  Type: Mahavishnu (Direct)                                │ │
│  │  Status: Running (Healthy)                                │ │
│  │  Workers: 5/10 (50% utilization)                          │ │
│  │  Tasks: 3 active, 12 queued                               │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ┌─ Worker Status ─────────────────────────────────────────┐  │
│  │  Worker ID    │ Task          │ Progress │ Status        │ │
│  │  worker_001   │ task_abc      │ 87%      │ Running       │ │
│  │  worker_002   │ task_def      │ 45%      │ Running       │ │
│  │  worker_003   │ task_ghi      │ 100%     │ Completed ✅  │ │
│  │  worker_004   │ -             │ 0%       │ Idle          │ │
│  │  worker_005   │ task_jkl      │ 23%      │ Running       │ │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌─ Active Tasks ───────────────────────────────────────────┐  │
│  │  task_abc  │ "Write Python tests"     │ Running (87%)    │  │
│  │  task_def  │ "Refactor API module"    │ Running (45%)    │  │
│  │  task_jkl  │ "Update documentation"   │ Running (23%)    │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│  [S] Scale  [E] Execute  [L] Logs  [X] Close Pool              │
└──────────────────────────────────────────────────────────────────┘
```

### Screen 3: Real-time Dashboard

```
┌──────────────────────────────────────────────────────────────────┐
│  Dashboard                                      Auto: 1s  [P]ause│
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─ Pool Health ──────────────────────────────────────────────┐│
│  │  Pool          Status    Workers    Tasks    Utilization   ││
│  │  local-pool    ✅       5/10       3/12     ███████░░░ 50% ││
│  │  remote-pool   ✅       3/3        8/20     ██████████ 100%││
│  │  k8s-pool      ⏳       12/20      45/100   ████░░░░░░░ 40% ││
│  └───────────────────────────────────────────────────────────┘│
│                                                                  │
│  ┌─ Task Queue ─────────────────────────────────────────────┐ │
│  │  Queued: 157  │  Running: 23  │  Completed: 1,234        │ │
│  │  ┌──────────────────────────────────────────────────┐   │ │
│  │  │ Progress: [████████████░░░░░░░░░] 77%           │   │ │
│  │  └──────────────────────────────────────────────────┘   │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ┌─ Resource Usage ─────────────────────────────────────────┐│
│  │  CPU:    [███████░░░░░░░░] 35%                           ││
│  │  Memory: [███████████░░░░] 62%                           ││
│  │  Disk:   [███░░░░░░░░░░░░] 12%                           ││
│  └──────────────────────────────────────────────────────────┘│
│                                                                  │
│  ┌─ Recent Logs ────────────────────────────────────────────┐│
│  │  [10:23:45] task_abc completed successfully ✅           ││
│  │  [10:23:42] task_def started (worker_002)                ││
│  │  [10:23:38] Pool scaled: 3 → 5 workers                  ││
│  │  [10:23:30] task_xyz failed: timeout ⚠️                  ││
│  └──────────────────────────────────────────────────────────┘│
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│  Updating in 0.3s...  Press [P] to pause  [R] to refresh now    │
└──────────────────────────────────────────────────────────────────┘
```

### Screen 4: Command Palette (Ctrl+K)

```
┌──────────────────────────────────────────────────────────────────┐
│  ┌─ Command Palette ─────────────────────────────────────────┐ │
│  │  > spawn pool                                      3 matches│ │
│  │  ┌────────────────────────────────────────────────────┐   │ │
│  │  │ Command                    │ Description           │   │ │
│  │  ├────────────────────────────────────────────────────┤   │ │
│  │  │ spawn pool                 │ Create new pool       │← C│ │
│  │  │ spawn pool --type k8s      │ Create Kubernetes pool│   │ │
│  │  │ spawn pool --workers 10    │ Create pool with 10 w│   │ │
│  │  └────────────────────────────────────────────────────┘   │ │
│  │                                                            │ │
│  │  [Enter] Execute  [Esc] Close  [Tab] Next match            │ │
│  └────────────────────────────────────────────────────────┘   │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### Screen 5: Workflow Builder

```
┌──────────────────────────────────────────────────────────────────┐
│  Workflow: CI Pipeline                              [S]ave  [R]un│
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─ Canvas ──────────────────────────────────────────────────┐ │
│  │                                                            │ │
│  │  ┌──────────┐      ┌──────────┐      ┌──────────┐        │ │
│  │  │  Start   │─────▶│  Tests   │─────▶│  Build   │        │ │
│  │  │ (Trigger)│      │ (pytest) │      │ (docker) │        │ │
│  │  └──────────┘      └──────────┘      └────┬─────┘        │ │
│  │                                      │                    │ │
│  │                               ┌──────┴──────┐             │ │
│  │                               ▼             ▼             │ │
│  │                         ┌──────────┐  ┌──────────┐       │ │
│  │                         │ Deploy   │  │ Notify  │       │ │
│  │                         │ (k8s)    │  │ (slack)  │       │ │
│  │                         └──────────┘  └──────────┘       │ │
│  │                                                            │ │
│  │  [+] Add Node  [Del] Remove Selected  [Drag] Move         │ │
│  └────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌─ Properties ────────────────────────────────────────────┐  │
│  │  Selected: Build                                          │  │
│  │  Type: Docker Build                                       │  │
│  │  Image: myapp:latest                                      │  │
│  │  Context: ./app                                           │  │
│  │  Timeout: 300s                                            │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│  [N] New  [L] Load  [S] Save  [R] Run  [?] Help                  │
└──────────────────────────────────────────────────────────────────┘
```

### Screen 6: Help Screen

```
┌──────────────────────────────────────────────────────────────────┐
│  Help & Documentation                                    [Esc] Back│
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─ Keyboard Shortcuts ───────────────────────────────────────┐│
│  │  Global:                                                    ││
│  │    Ctrl+K    Open command palette                           ││
│  │    Ctrl+R    Refresh current view                           ││
│  │    ?         Show this help screen                          ││
│  │    Q / Esc   Quit / Go back                                 ││
│  │                                                            ││
│  │  Navigation:                                               ││
│  │    ↑ / ↓     Move up / down                                ││
│  │    Enter     Select item / Show details                    ││
│  │    Tab / Shift-Tab  Next / Previous tab                    ││
│  │                                                            ││
│  │  Pool Actions:                                             ││
│  │    S         Spawn new pool                                ││
│  │    D         Delete selected pool                          ││
│  │    E         Execute task on pool                          ││
│  │    L         View pool logs                                ││
│  └───────────────────────────────────────────────────────────┘│
│                                                                  │
│  ┌─ Common Tasks ────────────────────────────────────────────┐│
│  │  1. Spawn a pool:                                           ││
│  │     - Press Ctrl+K                                         ││
│  │     - Type "spawn pool"                                    ││
│  │     - Enter pool configuration                             ││
│  │                                                            ││
│  │  2. Execute a task:                                         ││
│  │     - Navigate to pool list                                ││
│  │     - Select pool (Enter)                                  ││
│  │     - Press 'E' to execute                                 ││
│  │                                                            ││
│  │  3. Monitor progress:                                       ││
│  │     - Go to Monitor tab                                    ││
│  │     - View real-time metrics                               ││
│  └───────────────────────────────────────────────────────────┘│
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│  Press [Esc] to return to application                            │
└──────────────────────────────────────────────────────────────────┘
```

---

## Part 3: Interaction Patterns

### Pattern 1: Master-Detail Navigation

```
User Action Flow:

Pool List (Master)
    │
    │ [Enter] on pool_abc
    ▼
Pool Detail (Detail)
    │
    │ [Enter] on task_xyz
    ▼
Task Detail (Nested Detail)
    │
    │ [Esc] or [Q]
    ▼
Back to Pool Detail
    │
    │ [Esc] or [Q]
    ▼
Back to Pool List
```

**Implementation**:
```python
class PoolList(Vertical):
    def on_data_table_row_selected(self, event):
        pool_id = event.row.cdr[0].value
        self.app.push_screen(PoolDetail(pool_id))

class PoolDetail(Vertical):
    BINDINGS = [("escape", "pop_screen", "Back")]
```

### Pattern 2: Command Palette Execution

```
User Action Flow:

Any Screen
    │
    │ [Ctrl+K]
    ▼
Command Palette Opens
    │
    │ Type "spawn pool"
    ▼
Filtered Results
    │
    │ [Enter] on "spawn pool"
    ▼
Execute Command
    │
    │ Show confirmation or result
    ▼
Back to previous screen
```

**Implementation**:
```python
class MahavishnuTUI(App):
    BINDINGS = [("ctrl+k", "show_command_palette", "Commands")]

    def action_show_command_palette(self):
        self.push_screen(CommandPalette())

    def execute_command(self, command: str):
        # Execute and show result
        result = self.backend.execute(command)
        self.show_result(result)
```

### Pattern 3: Real-time Updates

```
Data Flow:

Backend (Every 1s)
    │
    │ Emit update event
    ▼
MessageBus
    │
    │ Broadcast to subscribers
    ▼
Dashboard Widget
    │
    │ Receive event
    ▼
Update UI
    │
    │ Refresh display
    ▼
User sees new data
```

**Implementation**:
```python
class Dashboard(Vertical):
    def on_mount(self):
        self.set_interval(1.0, self.update)

    async def update(self):
        pools = await self.app.backend.list_pools()
        self.update_pools(pools)
```

### Pattern 4: Progressive Disclosure

```
Information Architecture:

Level 1: Summary (Always Visible)
├── Pool: local-pool (Running, 5/10 workers)
└── Tasks: 3 active, 12 queued

    │ [Enter] for details
    ▼

Level 2: Details (On Demand)
├── Worker Status Table
├── Active Tasks List
└── Resource Usage Charts

    │ [Enter] on specific item
    ▼

Level 3: Deep Details (Contextual)
├── Task Output Logs
├── Error Tracebacks
└── Performance Metrics
```

---

## Part 4: State Management

### Application State

```python
class TUIState:
    """Global application state"""

    def __init__(self):
        # Pool state
        self.pools: List[Pool] = []
        self.current_pool: Optional[str] = None

        # Workflow state
        self.workflows: List[Workflow] = []
        self.current_workflow: Optional[str] = None

        # UI state
        self.current_tab: str = "pools"
        self.theme: str = "dark"
        self.auto_refresh: bool = True
        self.refresh_interval: int = 1  # seconds

        # Filters
        self.pool_filter: str = ""
        self.workflow_filter: str = ""

    def update_pools(self, pools: List[Pool]):
        """Update pool state"""
        self.pools = pools
        # Emit update event
        self.emit("pools_updated", pools)

    def get_pool(self, pool_id: str) -> Optional[Pool]:
        """Get pool by ID"""
        for pool in self.pools:
            if pool.id == pool_id:
                return pool
        return None
```

### Widget State

```python
class PoolList(Vertical):
    """Pool list widget with local state"""

    def __init__(self):
        super().__init__()
        self.sort_column = "name"
        self.sort_direction = "asc"
        self.filter_query = ""

    def sort_pools(self, column: str):
        """Sort pools by column"""
        self.sort_column = column
        # Trigger re-sort
        self.refresh()

    def filter_pools(self, query: str):
        """Filter pools by query"""
        self.filter_query = query
        # Trigger re-filter
        self.refresh()
```

---

## Part 5: Event Flow

### Event: Pool Status Change

```
┌─────────────────┐
│  Backend Pool   │
│  Status Changed │
└────────┬────────┘
         │
         │ WebSocket Event
         ▼
┌─────────────────┐
│  Message Bus    │
│  (pub/sub)      │
└────────┬────────┘
         │
         │ Emit "pool_status_changed"
         ▼
┌─────────────────┐
│  Dashboard      │
│  Widget         │
└────────┬────────┘
         │
         │ Update UI
         ▼
┌─────────────────┐
│  Re-render Pool  │
│  Status Row     │
└─────────────────┘
```

**Implementation**:
```python
class Dashboard(Vertical):
    def on_mount(self):
        # Subscribe to pool updates
        self.app.message_bus.subscribe(
            "pool_status_changed",
            self.on_pool_status_changed
        )

    def on_pool_status_changed(self, event):
        """Handle pool status change"""
        pool_id = event.pool_id
        new_status = event.status

        # Update UI
        status_widget = self.query_one(f"#status-{pool_id}", Static)
        status_widget.update(f"[green]{new_status}[/]")
```

---

## Part 6: Color System

### Semantic Colors

```css
/* Dark Theme (Default) */
@theme dark {
    --primary: #61afef;      /* Blue - Actions */
    --success: #98c379;      /* Green - Healthy */
    --warning: #e5c07b;      /* Yellow - Pending */
    --error: #e06c75;        /* Red - Error */
    --info: #c678dd;         /* Purple - Info */
    --background: #1e1e1e;   /* Dark bg */
    --surface: #282c34;      /* Panel bg */
    --text: #abb2bf;         /* Default text */
}

/* Light Theme */
@theme light {
    --primary: #3b82f6;
    --success: #10b981;
    --warning: #f59e0b;
    --error: #ef4444;
    --info: #8b5cf6;
    --background: #ffffff;
    --surface: #f3f4f6;
    --text: #1f2937;
}
```

### Usage in Components

```python
# Semantic color usage
status = pool.status
if status == "running":
    color = "success"
elif status == "stopped":
    color = "warning"
elif status == "error":
    color = "error"

# Use in Rich or Textual
console.print(f"[{color}]{status}[/{color}]")
```

---

## Part 7: Performance Patterns

### Pattern 1: Virtual Scrolling

```python
class VirtualizedDataTable(DataTable):
    """DataTable with virtual scrolling"""

    def __init__(self, total_items: int, page_size: int = 50):
        super().__init__()
        self.total_items = total_items
        self.page_size = page_size
        self.current_page = 0

    def load_page(self, page: int):
        """Load only visible page"""
        start = page * self.page_size
        end = start + self.page_size
        visible_items = self.all_items[start:end]

        self.clear()
        for item in visible_items:
            self.add_row(*item)
```

### Pattern 2: Debounced Search

```python
from textual import events
import asyncio

class DebouncedInput(Input):
    """Input with debounced search"""

    def __init__(self, delay: float = 0.3):
        super().__init__()
        self.delay = delay
        self.search_task = None

    async def _debounced_search(self, value: str):
        """Execute search after delay"""
        await asyncio.sleep(self.delay)
        # Execute search
        self.app.search(value)

    def on_input_changed(self, event: Input.Changed):
        """Debounce input changes"""
        if self.search_task:
            self.search_task.cancel()

        self.search_task = asyncio.create_task(
            self._debounced_search(event.value)
        )
```

### Pattern 3: Lazy Loading

```python
class LazyPoolDetail(Vertical):
    """Pool detail that loads data on demand"""

    def on_mount(self):
        """Show loading state"""
        self.loading = True
        self.show_loading_indicator()

    async def load_data(self):
        """Load data when visible"""
        if not self.loaded:
            pool = await self.app.backend.get_pool(self.pool_id)
            self.display_pool(pool)
            self.loaded = True
```

---

## Part 8: Testing Patterns

### Pattern 1: Widget Unit Tests

```python
from textual.widgets import DataTable
from mahavishnu.tui.widgets.pool_list import PoolList

async def test_pool_list_sort():
    """Test pool sorting"""
    widget = PoolList()

    async with widget.app.run_test() as pilot:
        # Add test data
        table = widget.query_one(DataTable)
        table.add_row("pool_c", "mahavishnu", "5", "running")
        table.add_row("pool_a", "mahavishnu", "3", "running")
        table.add_row("pool_b", "mahavishnu", "7", "running")

        # Sort by name
        widget.sort_pools("name")

        # Verify order
        rows = list(table.rows)
        assert rows[0][0].plain == "pool_a"
        assert rows[1][0].plain == "pool_b"
        assert rows[2][0].plain == "pool_c"
```

### Pattern 2: Screen Navigation Tests

```python
async def test_pool_detail_navigation():
    """Test navigation to pool detail"""
    app = MahavishnuTUI()

    async with app.run_test() as pilot:
        # Start at pool list
        assert isinstance(app.screen, PoolList)

        # Select pool and press Enter
        await pilot.press("down")
        await pilot.press("enter")

        # Should be at pool detail
        assert isinstance(app.screen, PoolDetail)

        # Press Esc to go back
        await pilot.press("escape")

        # Should be back at pool list
        assert isinstance(app.screen, PoolList)
```

### Pattern 3: Integration Tests

```python
async def test_command_palette_execution():
    """Test command palette flow"""
    app = MahavishnuTUI()

    async with app.run_test() as pilot:
        # Open command palette
        await pilot.press("ctrl+k")

        # Type command
        await pilot.type("spawn pool")

        # Press Enter to execute
        await pilot.press("enter")

        # Verify command was executed
        assert app.last_command == "spawn pool"
```

---

## Conclusion

This architecture provides a solid foundation for building a modern, discoverable terminal UI. The key principles are:

1. **Composition**: Build complex UIs from simple widgets
2. **Async**: Use async for non-blocking operations
3. **Events**: Use message passing for loose coupling
4. **State**: Keep state managed and predictable
5. **Performance**: Virtualize, debounce, and lazy-load
6. **Testing**: Write tests for all user flows

Next step: **Start coding**! Begin with the command palette, then build out the pool list and dashboard.

---

**Resources**:
- [Full Analysis](./TUI_UI_INNOVATION_ANALYSIS.md)
- [Quick Start](./TUI_QUICK_START_GUIDE.md)
- [Textual Docs](https://textual.textual.io/)

**Generated**: 2026-02-06
**Status**: Ready for implementation

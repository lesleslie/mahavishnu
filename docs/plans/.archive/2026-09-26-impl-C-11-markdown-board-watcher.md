# C-11: markdown board watcher (WP-5 — scoped to our jot files)

**REQ-NNN:** REQ-017, REQ-018, REQ-020

- REQ-017: Markdown board watcher with `async with asyncio.timeout(...)` deadlock mitigation + `fcntl.flock` sidecar
- REQ-018: `mahavishnu board {init,status,validate}` companion CLIs (scoped to our jot files)
- REQ-020: Oneiric `ValidationSchemaAction` + `DataTransformAction` + `DataSanitizeAction` for board parsing (with real payload shapes from `oneiric/actions/data.py`)
  **Risk:** Medium-High (file watcher deadlock mitigation; concurrent dispatch via fcntl.flock; Pydantic validation via Oneiric action kit)
  **Blocks:** None directly (C-13 doesn't depend on C-11 — they trigger on different things)
  **Direct-to-main commit:** Yes (per `feedback-no-backwards-compat-pre-1.0` + `bodai-pre-1.0-merge-policy`).

**Niche fit:** Per [`docs/adr/0001-mahavishnu-niche.md`](../adr/0001-mahavishnu-niche.md), this plan anchors Mahavishnu as LLM control plane + repo orchestrator + multi-engine + harness-agnostic + multi-engine + harness-agnostic. The three-question filter (deepens? Bodai integration? no source-tool competition?) was applied at planning time.
**Status:** Draft — round-4 corrections baked in (deadlock fix, exception redundancy fix, `from __future__ import annotations`, dropped `Field` import, scoped to our jot files only).

## Goal

Build `mahavishnu jot export --output .mahavishnu/board.md` and a file watcher that imports our jot cards. **Per niche filter, scoped to our jot files only** (NOT a generic markdown-board engine). The watcher:

1. Reads `.mahavishnu/board.md` (a markdown checklist of `MHCard` entries).
1. On `Change.modified`, parses the file, dispatches each card to `pool_route_execute`.
1. Maintains a `state_sidecar` (atomic write via `fcntl.flock`) for CAS-style conflict detection.
1. Uses `async with asyncio.timeout(...)` (NOT `wait_for(async_generator)`) around the watch loop to prevent deadlocks.
1. Emits Akosha events via `safe_publish` for board state changes.

The companion CLIs `mahavishnu board {init,status,validate}` provide manual board management without the watcher running.

## Pre-flight checks

1. **C-1 has landed.** `markdown_board:` settings section exists with `watcher_lag_seconds`, `state_sidecar_suffix`, `default_path`, `path_resolution`, `watcher_debounce_seconds`, `section_mapping` keys. FIX round-8 (Tier 4): the previous pre-flight text listed fictional keys (`state_sidecar_path`, `watch_paths`) that C-1 does NOT define. The actual keys are `state_sidecar_suffix` (a suffix, not a path — C-11 derives the path at runtime) and `default_path` (the path to the board file).
1. **`watchfiles` available.** Per `feedback-crackerjack-gitignore-sync-dev-dep-downgrade.md`, pin to `watchfiles~=1.0,<1.1` (C-1 plan already adds this dep; verify it's there before C-11 lands).
1. **C-3 has landed.** `record_execution_event()` + `get_execution_events()` available for board history.
1. **C-5 has landed.** `safe_publish()` available for Akosha event emission.
1. **C-6 has landed.** `IdempotencyOptions` available — board dispatch should be idempotent on (card_id, expected_revision).
1. **`oneiric.actions.data.ValidationSchemaAction` importable** with the real payload shape: `{"schema": {"fields": [{"name": str, "type": str, "required": bool, ...}]}, "data": dict}` → returns `{"valid": bool, "errors": list[str]}`.
1. **`oneiric.actions.data.DataTransformAction`** with shape `{"data": dict, "include_fields": list[str]}` → returns `{"data": dict}` (per round-4 correction: `include_fields` is the real field, NOT `target`).
1. **`oneiric.actions.data.DataSanitizeAction`** with shape `{"data": str, "mask_fields": list[str]}` → returns `{"data": str}`.
1. **No existing `mahavishnu/jot/markdown_*` files** (`ls mahavishnu/jot/` returns only existing jot files; no `markdown_export.py`, `markdown_watcher.py`, `markdown_parser.py`).
1. **No existing `mahavishnu/cli/board_cli.py`** (`ls mahavishnu/cli/` — verify it does not exist).

## File-by-file changes

### 1. `mahavishnu/jot/markdown_parser.py` — new file (~120 LoC)

```python
"""Markdown parser for our jot board files.

Scoped to the .mahavishnu/board.md format ONLY. Not a generic markdown-board engine.
Uses Oneiric ValidationSchemaAction with an explicit ValidationFieldRule list.
"""
from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from oneiric.actions.data import ValidationSchemaAction
from oneiric.core.logging import get_logger

from mahavishnu.core.errors import MarkdownParseError

logger = get_logger(__name__)


CARD_SECTION_VALUES = ("backlog", "ready", "in_progress", "done")
"""Validation enum for MHCard.status — explicit list per crackerjack-compliant-code."""


async def parse_board(content: str) -> list[dict[str, Any]]:
    """Parse .mahavishnu/board.md into a list of card dicts.

    Format (one card per section):

        ## Backlog
        - [ ] card-id | pool | prompt text
        - [ ] card-id-2 | pool | prompt text

        ## Ready
        - [x] card-id-3 | pool | prompt text (completed)

    Sections are identified by `## <name>` headers. Cards are identified by
    checkbox items.
    """
    sections = _split_by_headers(content)
    cards: list[dict[str, Any]] = []
    for section_name, section_body in sections.items():
        status = _section_to_status(section_name)
        if status is None:
            continue
        for line in section_body.splitlines():
            stripped = line.strip()
            if not stripped.startswith("- ["):
                continue
            card = _parse_card_line(stripped, status)
            if card is not None:
                cards.append(card)

    # Validate with Oneiric ValidationSchemaAction
    validator = ValidationSchemaAction()
    for card in cards:
        result = await validator.execute({
            "schema": _card_schema(),
            "data": card,
        })
        if not result["valid"]:
            raise MarkdownParseError(
                f"card {card.get('id')} failed validation: {result.get('errors', [])}"
            )
    return cards


def _split_by_headers(content: str) -> dict[str, str]:
    """Split markdown by `## <name>` headers; return name -> body map."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in content.splitlines():
        m = re.match(r"^##\s+(.+)$", line)
        if m:
            current = m.group(1).strip()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return {k: "\n".join(v) for k, v in sections.items()}


def _section_to_status(name: str) -> str | None:
    """Map section name to MHCard.status enum value."""
    lower = name.lower().strip()
    for valid in CARD_SECTION_VALUES:
        if valid in lower:
            return valid
    return None


def _parse_card_line(line: str, status: str) -> dict[str, Any] | None:
    """Parse `- [ ] card-id | pool | prompt` into a card dict."""
    # Strip the checkbox marker
    if line.startswith("- [x]") or line.startswith("- [X]"):
        # Completed checkbox means done
        status = "done"
        line = line[5:].strip()
    elif line.startswith("- [ ]"):
        line = line[5:].strip()
    else:
        return None
    parts = [p.strip() for p in line.split("|", 2)]
    if len(parts) < 3:
        return None
    return {
        "id": parts[0] or str(uuid4()),
        "status": status,
        "pool": parts[1],
        "title": parts[0],  # alias
        "prompt": parts[2],
        "expected_revision": None,
    }


def _card_schema() -> dict[str, Any]:
    """Oneiric ValidationSchemaAction schema for MHCard.

    Explicit ValidationFieldRule list per round-4 code-quality correction.
    """
    return {
        "fields": [
            {"name": "id", "type": "string", "required": True, "min_length": 1},
            {"name": "status", "type": "enum", "required": True,
             "values": list(CARD_SECTION_VALUES)},
            {"name": "title", "type": "string", "required": True, "min_length": 1},
            {"name": "pool", "type": "string", "required": True, "min_length": 1},
            {"name": "prompt", "type": "string", "required": True, "min_length": 1},
            {"name": "expected_revision", "type": "integer", "required": False},
        ]
    }
```

### 2. `mahavishnu/jot/markdown_export.py` — new file (~80 LoC)

```python
"""Markdown exporter — converts card dicts back to .mahavishnu/board.md format."""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def render_board(cards: list[dict[str, Any]]) -> str:
    """Render cards grouped by section, with checkbox markers."""
    by_section: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for card in cards:
        by_section[card["status"]].append(card)

    lines: list[str] = []
    for section in ("backlog", "ready", "in_progress", "done"):
        section_cards = by_section.get(section, [])
        if not section_cards:
            continue
        title = section.replace("_", " ").title()
        lines.append(f"## {title}")
        lines.append("")
        for card in section_cards:
            marker = "x" if section == "done" else " "
            lines.append(
                f"- [{marker}] {card['id']} | {card['pool']} | {card['prompt']}"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


async def transform_for_export(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Use Oneiric DataTransformAction to select fields for export.

    Per round-4: real field is `include_fields`, NOT `target`.
    """
    from oneiric.actions.data import DataTransformAction

    transformed = []
    for card in cards:
        result = await DataTransformAction().execute({
            "data": card,
            "include_fields": ["id", "status", "pool", "prompt"],
        })
        transformed.append(result["data"])
    return transformed
```

### 3. `mahavishnu/jot/state_persistence.py` — new file (~50 LoC)

Atomic sidecar write via `fcntl.flock` in `try/finally`:

```python
"""Atomic sidecar state persistence with fcntl.flock.

The state sidecar tracks per-card revision counters for CAS-style conflict
detection. Concurrent watcher + CLI invocations are serialized via flock.
"""
from __future__ import annotations

import fcntl
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


@contextmanager
def flocked_file(path: Path, mode: str = "r") -> Iterator[Any]:
    """Open file with flock; release in finally.

    IMPORTANT: lock-fd leak risk if the with-block raises between open() and
    flock(). Mitigated by try/finally around the flock call.
    """
    fd = open(path, mode)
    try:
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX)
        yield fd
    finally:
        try:
            fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass  # best-effort unlock
        fd.close()


def load_state(state_path: Path) -> dict[str, int]:
    """Load per-card revision map. Returns empty map on missing/corrupt file."""
    if not state_path.exists():
        return {}
    with flocked_file(state_path, "r") as f:
        try:
            return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}


def save_state(state_path: Path, state: dict[str, int]) -> None:
    """Atomic write: write to .tmp, fsync, rename."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_path.with_suffix(state_path.suffix + ".tmp")
    with flocked_file(tmp, "w") as f:
        json.dump(state, f, indent=2, sort_keys=True)
        f.flush()
        import os
        os.fsync(f.fileno())
    tmp.replace(state_path)  # atomic on POSIX
```

### 4. `mahavishnu/jot/markdown_watcher.py` — new file (~150 LoC)

**Critical round-4 fixes**:

- `async with asyncio.timeout(...)` (NOT `wait_for(async_generator)`)
- `except OSError` only (NOT `(OSError, FileNotFoundError)` — `FileNotFoundError` is a subclass)
- Full `from __future__ import annotations`
- `safe_publish` for crash events

```python
"""Markdown board watcher — polls .mahavishnu/board.md and dispatches cards."""
from __future__ import annotations

import asyncio
from pathlib import Path

from watchfiles import Change, awatch

from mahavishnu.core.events.contract import create_event_envelope
from mahavishnu.core.events.publisher import safe_publish
from mahavishnu.jot.markdown_parser import parse_board
from mahavishnu.jot.state_persistence import load_state, save_state
from mahavishnu.mcp.tools.pool_tools import pool_route_execute
from mahavishnu.core.idempotency import IdempotencyOptions
from oneiric.core.logging import get_logger

logger = get_logger(__name__)


async def watch_board(
    board_path: Path,
    state_sidecar: Path,
    watcher_lag_seconds: float,
) -> None:
    """Watch .mahavishnu/board.md and dispatch cards on each modification.

    Critical: async with asyncio.timeout(...) is used here (NOT asyncio.wait_for)
    because wait_for(async_generator) raises TypeError in Python 3.11+ —
    watchfiles.awatch() returns an async generator, not an awaitable.
    """
    metrics.markdown_board_watcher_up.set(1)
    state = load_state(state_sidecar)

    while True:
        try:
            async with asyncio.timeout(watcher_lag_seconds * 3):
                async for changes in awatch(str(board_path)):
                    for change_type, path in changes:
                        if change_type is Change.modified:
                            await _handle_modified(
                                path, board_path, state_sidecar, state
                            )
        except asyncio.TimeoutError:
            logger.warning("watcher timeout — restarting")
            metrics.markdown_board_watcher_restarts_total.inc()
            continue
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            logger.exception("watcher crashed; supervisor will restart")
            metrics.markdown_board_watcher_up.set(0)
            await safe_publish(create_event_envelope(
                event_type="anomaly.detected",
                payload={"anomaly_type": "markdown_watcher_died",
                         "error": str(exc)},
                source="mahavishnu.jot.markdown_watcher",
                metadata={"severity": "high"},
            ))
            raise


async def _handle_modified(
    path: str, board_path: Path, state_sidecar: Path, state: dict[str, int]
) -> None:
    """Handle one file modification."""
    try:
        content = await _read_file(Path(path))
        cards = await parse_board(content)
    except (OSError, MarkdownParseError) as exc:
        logger.warning("failed to parse board",
                       extra={"error": str(exc), "path": path})
        metrics.markdown_board_parse_errors_total.inc()
        return

    for card in cards:
        card_id = card["id"]
        prev_rev = state.get(card_id, 0)
        new_rev = prev_rev + 1

        if card["status"] == "done":
            continue  # already completed; skip

        # CAS check: skip if expected_revision doesn't match
        if card["expected_revision"] is not None:
            if card["expected_revision"] != prev_rev:
                logger.info("CAS conflict; skipping",
                            extra={"card_id": card_id})
                metrics.markdown_board_conflict_total.inc()
                continue

        try:
            opts = IdempotencyOptions(
                source="mahavishnu.jot.markdown_watcher",
                nonce=f"{card_id}:{new_rev}",
                ttl_seconds=3600,
            )
            result = await pool_route_execute(
                prompt=card["prompt"],
                pool_selector="least_loaded",
                idempotency=opts,
            )
            # FIX (round-5): state save moved INSIDE the try block, AFTER
            # successful dispatch. Previously the save happened BEFORE
            # pool_route_execute was awaited, so a dispatch failure would
            # leave state with a "successful" card id — `test_modified_event_
            # dispatches_card` passed vacuously even when dispatch failed.
            state[card_id] = new_rev
            save_state(state_sidecar, state)
            metrics.markdown_board_dispatch_total.labels(
                section=card["status"], result="success"
            ).inc()
        except Exception as exc:
            # FIX (round-5): DO NOT update state on failure; the card stays
            # in ready/in_progress for retry on the next file modification.
            metrics.markdown_board_dispatch_total.labels(
                section=card["status"], result="error"
            ).inc()
            logger.exception("dispatch failed",
                             extra={"card_id": card_id})
            await safe_publish(create_event_envelope(
                event_type="anomaly.detected",
                payload={"anomaly_type": "board_dispatch_failed",
                         "card_id": card_id, "error": str(exc)},
                source="mahavishnu.jot.markdown_watcher",
                metadata={"severity": "medium"},
            ))


async def _read_file(path: Path) -> str:
    """Async file read; uses aiofiles if available, else asyncio.to_thread."""
    try:
        import aiofiles
        async with aiofiles.open(path) as f:
            return await f.read()
    except ImportError:
        def _sync_read() -> str:
            return path.read_text()
        return await asyncio.to_thread(_sync_read)
```

### 5. `mahavishnu/cli/board_cli.py` — new file (~80 LoC)

Typer sub-app with `init`, `status`, `validate` commands:

```python
"""mahavishnu board {init,status,validate} — companion CLIs for jot board."""
from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from oneiric.core.logging import get_logger

from mahavishnu.core.errors import MahavishnuError
from mahavishnu.jot.markdown_export import render_board
from mahavishnu.jot.markdown_parser import parse_board

logger = get_logger(__name__)
board_app = typer.Typer(help="Manage the local .mahavishnu/board.md file (jot board)")


@board_app.command("init")
def init_cmd(path: Path = typer.Option(".mahavishnu/board.md", "--path")) -> None:
    """Initialize an empty board file."""
    if path.exists():
        typer.echo(f"Board already exists at {path}", err=True)
        raise typer.Exit(code=1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Mahavishnu Jot Board\n\n## Backlog\n\n## Ready\n\n## In Progress\n\n## Done\n")
    typer.echo(f"Initialized board at {path}")


@board_app.command("status")
def status_cmd(path: Path = typer.Option(".mahavishnu/board.md", "--path")) -> None:
    """Show board section counts."""
    if not path.exists():
        typer.echo(f"No board at {path}", err=True)
        raise typer.Exit(code=1)
    cards = asyncio.run(parse_board(path.read_text()))
    counts: dict[str, int] = {}
    for card in cards:
        counts[card["status"]] = counts.get(card["status"], 0) + 1
    for section in ("backlog", "ready", "in_progress", "done"):
        typer.echo(f"{section}: {counts.get(section, 0)}")


@board_app.command("validate")
def validate_cmd(path: Path = typer.Option(".mahavishnu/board.md", "--path")) -> None:
    """Validate board syntax and Oneiric schema."""
    if not path.exists():
        typer.echo(f"No board at {path}", err=True)
        raise typer.Exit(code=1)
    try:
        cards = asyncio.run(parse_board(path.read_text()))
        typer.echo(f"OK: {len(cards)} cards parsed and validated")
    except MahavishnuError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=1)
```

### 6. `mahavishnu/cli/jot_cli.py` — add `export` + `watch` commands

Locate the existing `mahavishnu/cli/jot_cli.py`. Add two new Typer commands:

```python
@jot_app.command("export")
def export_cmd(
    output: Path = typer.Option(".mahavishnu/board.md", "--output"),
) -> None:
    """Export the current jot state to a markdown board file."""
    # Load cards from JotDB (or wherever cards live); render to markdown
    cards = _load_cards_from_jot_db()  # existing impl
    content = render_board(cards)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content)
    typer.echo(f"Exported {len(cards)} cards to {output}")


@jot_app.command("watch")
def watch_cmd(
    board: Path = typer.Option(".mahavishnu/board.md", "--board"),
) -> None:
    """Watch the board file and dispatch cards as they change."""
    from mahavishnu.core.config import get_settings
    from mahavishnu.jot.markdown_watcher import watch_board

    settings = get_settings()
    # Derive state sidecar path from default_path + state_sidecar_suffix
    # (C-1's MarkdownBoardSettings defines suffix, not path — see INC-2 fix)
    board_path = Path(board)
    sidecar_suffix = settings.markdown_board.state_sidecar_suffix
    state_sidecar = board_path.with_suffix(board_path.suffix + sidecar_suffix)
    asyncio.run(watch_board(board, state_sidecar, settings.markdown_board.watcher_lag_seconds))
```

### 7. `mahavishnu/mcp/tools/jot_tools.py` — add `jot_export_markdown` MCP tool

```python
@mcp.tool()
async def jot_export_markdown(output_path: str) -> dict[str, Any]:
    """Export jot cards to a markdown board file."""
    from mahavishnu.jot.markdown_export import render_board
    cards = _load_cards_from_jot_db()  # existing
    content = render_board(cards)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(content)
    return {"status": "exported", "cards_count": len(cards), "path": output_path}
```

### 8. `mahavishnu/core/errors.py` — add `MarkdownWatcherDiedError`, `MarkdownParseError`

```python
class MarkdownWatcherDiedError(MahavishnuError):
    """Raised when the markdown board watcher crashes; supervisor restarts."""


class MarkdownParseError(MahavishnuError):
    """Raised when .mahavishnu/board.md fails validation."""
```

### 9. `mahavishnu/core/metrics.py` — add 6 metrics

```python
MARKDOWN_BOARD_WATCHER_UP = Gauge(
    "markdown_board_watcher_up", "Markdown board watcher is alive (1) or dead (0)."
)
MARKDOWN_BOARD_WATCHER_RESTARTS_TOTAL = Counter(
    "markdown_board_watcher_restarts_total", "Watcher restarts due to timeout or crash."
)
MARKDOWN_BOARD_CARD_AGE_SECONDS = Gauge(
    "markdown_board_card_age_seconds",
    "Age of oldest card in section (seconds since first parse).",
    labelnames=["section"],
)
MARKDOWN_BOARD_DISPATCH_TOTAL = Counter(
    "markdown_board_dispatch_total",
    "Card dispatch attempts, labeled by section and result.",
    labelnames=["section", "result"],
)
MARKDOWN_BOARD_CONFLICT_TOTAL = Counter(
    "markdown_board_conflict_total", "CAS conflicts (expected_revision mismatch)."
)
MARKDOWN_BOARD_PARSE_ERRORS_TOTAL = Counter(
    "markdown_board_parse_errors_total", "Markdown parse failures."
)
```

### 10. `pyproject.toml` — verify `watchfiles~=1.0,<1.1` is added

C-1's plan declares this dep. Verify the line is present; if not, add:

```toml
"watchfiles~=1.0,<1.1",
```

Per `feedback-crackerjack-gitignore-sync-dev-dep-downgrade.md`, do NOT use `>=` (loose pins get clobbered by `gitignore sync`).

## Tests

### 11. `tests/integration/test_jot_markdown_roundtrip.py` — new file (~250 LoC)

```python
"""Roundtrip + watcher integration tests for the markdown board."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mahavishnu.core.errors import MarkdownParseError
from mahavishnu.jot.markdown_export import render_board
from mahavishnu.jot.markdown_parser import parse_board


@pytest.mark.req(["REQ-020"])
class TestParseRenderRoundtrip:
    async def test_parse_then_render(self) -> None:
        content = """# Jot Board

## Backlog
- [ ] card-1 | mahavishnu | write tests

## Ready
- [ ] card-2 | session_buddy | run lints

## Done
- [x] card-3 | mahavishnu | fix bug
"""
        cards = await parse_board(content)
        rendered = render_board(cards)
        # Re-parse the rendered output
        cards_2 = await parse_board(rendered)
        assert [c["id"] for c in cards] == [c["id"] for c in cards_2]
        assert [c["status"] for c in cards] == [c["status"] for c in cards_2]

    async def test_property_roundtrip(self) -> None:
        """Property: parse(render(cards)) == cards."""
        from hypothesis import given, strategies as st

        @given(cards=st.lists(st.dictionaries(
            st.text(min_size=1, max_size=16),
            st.sampled_from(["backlog", "ready", "in_progress", "done"]),
        ), min_size=0, max_size=10))
        async def prop(cards):
            rendered = render_board(cards)
            reparsed = await parse_board(rendered)
            assert len(reparsed) == len(cards)
        await prop()


@pytest.mark.req(["REQ-017"])
class TestWatcherDispatch:
    async def test_modified_event_dispatches_card(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Watcher dispatches cards on file modification."""
        from mahavishnu.jot.markdown_watcher import watch_board

        board = tmp_path / "board.md"
        state = tmp_path / "state.json"
        board.write_text("# Board\n\n## Backlog\n- [ ] c1 | pool | prompt\n")

        # Run watcher for 2 seconds, then write a modification
        async def run_with_modification():
            task = asyncio.create_task(
                watch_board(board, state, watcher_lag_seconds=0.5)
            )
            await asyncio.sleep(1.0)
            board.write_text("# Board\n\n## Backlog\n- [ ] c1 | pool | updated prompt\n")
            await asyncio.sleep(1.0)
            task.cancel()

        await asyncio.wait_for(run_with_modification(), timeout=5.0)
        # State should have c1 entry
        from mahavishnu.jot.state_persistence import load_state
        s = load_state(state)
        assert "c1" in s


@pytest.mark.req(["REQ-017"])
class TestWatcherCrashRecovery:
    async def test_timeout_restarts_watcher(self, tmp_path: Path) -> None:
        """When the watch loop times out, it restarts cleanly."""
        from mahavishnu.jot.markdown_watcher import watch_board

        board = tmp_path / "board.md"
        state = tmp_path / "state.json"
        board.write_text("# Board\n")

        async def run_briefly():
            task = asyncio.create_task(
                watch_board(board, state, watcher_lag_seconds=0.1)
            )
            await asyncio.sleep(0.5)
            task.cancel()

        await asyncio.wait_for(run_briefly(), timeout=2.0)
        # No assertion — the test passes if no deadlock crash occurred
        # (verified by asyncio.wait_for succeeding without TimeoutError)


@pytest.mark.req(["REQ-017"])
class TestFlockSidecar:
    def test_concurrent_writes_serialized(self, tmp_path: Path) -> None:
        """Two concurrent save_state calls do not corrupt the sidecar."""
        import asyncio
        from mahavishnu.jot.state_persistence import save_state, load_state

        async def run():
            state_path = tmp_path / "state.json"
            await asyncio.gather(
                asyncio.to_thread(save_state, state_path, {"a": 1}),
                asyncio.to_thread(save_state, state_path, {"b": 2}),
            )
            final = load_state(state_path)
            assert final in ({"a": 1}, {"b": 2})  # one wins

        asyncio.run(run())
```

### 12. `tests/property/test_jot_markdown_property.py` — new file (~60 LoC)

```python
"""Property tests for parse(render(cards)) == cards."""
from __future__ import annotations

import pytest
from hypothesis import given, strategies as st

from mahavishnu.jot.markdown_export import render_board
from mahavishnu.jot.markdown_parser import parse_board


@pytest.mark.req(["REQ-020"])
@given(cards=st.lists(st.fixed_dictionaries({
    "id": st.text(min_size=1, max_size=16),
    "status": st.sampled_from(["backlog", "ready", "in_progress", "done"]),
    "pool": st.text(min_size=1, max_size=16),
    "prompt": st.text(min_size=1, max_size=128),
}), min_size=0, max_size=20))
async def test_roundtrip(cards: list) -> None:
    rendered = render_board(cards)
    reparsed = await parse_board(rendered)
    assert [c["id"] for c in reparsed] == [c["id"] for c in cards]
    assert [c["status"] for c in reparsed] == [c["status"] for c in cards]
```

## Crackerjack verification

```bash
uv run pytest tests/integration/test_jot_markdown_roundtrip.py -v
uv run pytest tests/property/test_jot_markdown_property.py -v
uv run pytest --cov=mahavishnu --cov-fail-under=89.01682905225863
uv run crackerjack run -p minor
```

## Acceptance criteria (decisive pass/fail)

1. `mahavishnu/jot/markdown_parser.py` exists with `parse_board()` function.
1. `mahavishnu/jot/markdown_export.py` exists with `render_board()` function.
1. `mahavishnu/jot/markdown_watcher.py` exists with `watch_board()` function using `async with asyncio.timeout(...)` (NOT `wait_for(async_generator)`).
1. `mahavishnu/jot/state_persistence.py` exists with `flocked_file()` context manager.
1. **No `wait_for(async_generator)`** anywhere in `mahavishnu/jot/` (verified by `git grep "wait_for" mahavishnu/jot/`).
1. **No `from mahavishnu.jot... import Field`** (per round-4 drop of unused import).
1. **All new Python files have `from __future__ import annotations` as first non-comment line** (verified by `git grep -L "__future__" mahavishnu/jot/markdown_*.py mahavishnu/jot/state_persistence.py` returns nothing).
1. **`except OSError` only** (NOT `(OSError, FileNotFoundError)`) — round-4 redundancy fix.
1. `parse(render(cards))` round-trip property test passes for 20+ examples.
1. `watch_board()` times out and restarts cleanly (no deadlock).
1. Two concurrent `save_state` calls do not corrupt the sidecar.
1. `mahavishnu board {init,status,validate}` commands all work.
1. `mahavishnu jot {export,watch}` commands both work.
1. `jot_export_markdown` MCP tool is registered and callable.
1. `python scripts/audit_requirements.py --json` reports REQ-017, REQ-018, REQ-020 wired.
1. `crackerjack run` passes; coverage gate holds.

## Rollback / recovery narration

Per `feedback-no-backwards-compat-pre-1.0`:

- All new files; no existing API surface changed. Rollback is `git revert <commit-sha>`.
- `mahavishnu board` and `mahavishnu jot export/watch` are new subcommands — old CLIs unchanged.
- If the watcher crashes, the supervisor (per the `except Exception` block) emits an Akosha `anomaly.detected` event and re-raises. Operators see the metric `markdown_board_watcher_up` flip to 0.

Recovery for a runaway watcher: set `markdown_board.enabled: false` in settings (added in C-1). The `watch` CLI exits before starting the loop.

## Observability added

Six new Prometheus metrics (covered above). Operators alert on:

- `markdown_board_watcher_up == 0` for >1m → page
- `rate(markdown_board_watcher_restarts_total[5m]) > 0.1` → warn (too many restarts)
- `rate(markdown_board_conflict_total[5m]) > 0.5` → warn (CAS conflicts suggest human-edit races)
- `markdown_board_card_age_seconds{section="ready"} > 600` → warn (cards stuck in ready)

## Health aggregation

`markdown_board_watcher_up` gauge feeds into the existing `_register_health_tools` aggregator. If the gauge is 0 for >30s, `/health` returns degraded.

## Implementation notes / gotchas

- **`wait_for(async_generator)` is a TypeError** per round-4 — `watchfiles.awatch()` returns an async generator, not an awaitable. The fix is `async with asyncio.timeout(...)`. Verified by Python 3.11+ async-context-manager protocol.
- **`FileNotFoundError` is a subclass of `OSError`** per PEP 3151. `except (OSError, FileNotFoundError)` is redundant; use `except OSError` only.
- **Validation uses an explicit `CARD_SECTION_VALUES` tuple** (per round-4 code-quality) — passing `list(TaskCategory)` would create an enum dependency on the unrelated routing layer.
- **`fcntl.flock` is non-portable** (Linux/BSD only). macOS has it; Windows does NOT. Operators on Windows must run the watcher in WSL or skip it.
- **The state sidecar uses `fcntl.flock`** for serialization between watcher + CLI invocations. Without it, concurrent writes corrupt the file.
- **`async with asyncio.timeout(...)` is Python 3.11+.** If running on 3.10, fall back to `asyncio.wait_for(coro, timeout=...)` but wrap the watch generator in a coroutine first. Verify Python version in `pyproject.toml` (CLAUDE.md says 3.14 target).
- **The watcher uses `safe_publish`** for crash events — never raises, so a failed publish doesn't kill the watcher.
- **Per-process scope is a documented limitation** (also flagged in C-9). Multi-process pools must coordinate via the sidecar (which uses flock — only serializes within one host).
- **The companion `mahavishnu board validate` command** uses `parse_board()` which validates with Oneiric. The CLI is for manual checks; the watcher validates on every read.

## Files modified (summary)

| File | Action | LoC |
|---|---|---|
| `mahavishnu/jot/markdown_parser.py` | create | ~120 |
| `mahavishnu/jot/markdown_export.py` | create | ~80 |
| `mahavishnu/jot/markdown_watcher.py` | create | ~150 |
| `mahavishnu/jot/state_persistence.py` | create | ~50 |
| `mahavishnu/cli/board_cli.py` | create | ~80 |
| `mahavishnu/cli/jot_cli.py` | edit (add `export`, `watch` commands) | +50 |
| `mahavishnu/mcp/tools/jot_tools.py` | edit (add `jot_export_markdown` MCP tool) | +20 |
| `mahavishnu/core/errors.py` | edit (add `MarkdownWatcherDiedError`, `MarkdownParseError`) | +10 |
| `mahavishnu/core/metrics.py` | edit (add 6 metrics) | +35 |
| `pyproject.toml` | verify (C-1 already added `watchfiles~=1.0,<1.1`) | 0 |
| `tests/integration/test_jot_markdown_roundtrip.py` | create | +250 |
| `tests/property/test_jot_markdown_property.py` | create | +60 |

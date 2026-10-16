"""``mahavishnu status`` terminal diagnostic subcommand.

The 2026-10-09 demo hit three layered confusions in a row:

1. ``adapter_preference`` precedence — which value wins (Pydantic default vs.
   settings YAML vs. ``MAHAVISHNU_TERMINAL__ADAPTER_PREFERENCE`` env var vs.
   the resolved effective value)?
2. ``tmux`` binary location — the YAML may declare tmux but the binary is
   not on PATH (operators hit ``ConfigurationError`` at runtime).
3. ``claude`` on PATH — durable-worker tmux sessions need the Claude CLI on
   ``$PATH``; an absent binary surfaces as "worker stuck starting".

This subcommand surfaces all three in one report with
``[ok] / [warn] / [missing] / [error]`` markers. Wired into the root CLI
under the ``status`` sub-app.

Replaces no prior command — pure additive diagnostic. See
``docs/followups/2026-10-09-demo-adapter-precedence-surfacing.md``.
"""

from __future__ import annotations

import os
import pathlib
import re
import shutil
from collections.abc import Callable
from typing import TYPE_CHECKING

from oneiric.core.logging import get_logger
import typer

if TYPE_CHECKING:
    from mahavishnu.core.config import MahavishnuSettings
    from mahavishnu.workers.contract.store import WorkerRecordStore

logger = get_logger(__name__)


SETTINGS_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "settings"
YAML_PATH = SETTINGS_DIR / "mahavishnu.yaml"
ENV_ADAPTER_KEY = "MAHAVISHNU_TERMINAL__ADAPTER_PREFERENCE"


# Marker tokens used in the rendered table. Defined as constants so the
# marker vocabulary stays in one place; tests assert against these too.
MARK_OK = "[ok]"
MARK_WARN = "[warn]"
MARK_MISSING = "[missing]"
MARK_ERROR = "[error]"


def _yaml_adapter_value(path: pathlib.Path = YAML_PATH) -> str | None:
    """Return the declared ``adapter_preference`` value from the YAML.

    Reads the YAML as plain text and looks for ``adapter_preference: "X"``
    or ``adapter_preference: X`` under the ``terminal:`` block. Returns
    ``None`` when the file is missing, the terminal block is absent, or
    the key is unset/commented.
    """
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        logger.exception("failed to read settings yaml for status diagnostic", path=str(path))
        return None

    in_terminal_block = False
    for line in text.splitlines():
        line.lstrip()
        if not in_terminal_block:
            # Match ``terminal:`` only at column zero to avoid false
            # positives on inline YAML keys named "terminal" inside other
            # blocks. Settings/mahavishnu.yaml uses 2-space indent for
            # terminal children.
            if re.match(r"^terminal:\s*(#.*)?$", line):
                in_terminal_block = True
            continue

        # Leaving the terminal block on a sibling top-level key.
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*:\s*", line):
            break

        match = re.match(
            r"^\s*adapter_preference:\s*\"?([^\"#]+?)\"?\s*(?:#.*)?$",
            line,
        )
        if match:
            return match.group(1).strip()
    return None


def _env_adapter_value(env_key: str = ENV_ADAPTER_KEY) -> str | None:
    """Return the env-var override for ``adapter_preference`` or ``None``."""
    value = os.environ.get(env_key)
    if value is None or value == "":
        return None
    return value


def _pydantic_default_adapter() -> str:
    """Return the Pydantic default declared on ``TerminalSettings.adapter_preference``."""
    from mahavishnu.terminal.config import TerminalSettings

    field = TerminalSettings.model_fields["adapter_preference"]
    default = field.default
    return str(default) if default is not None else ""


def _load_settings() -> MahavishnuSettings:
    """Return a fresh ``MahavishnuSettings`` instance.

    Uses the cached :func:`get_settings` so the diagnostic sees exactly what
    production code sees. Tests that need a hermetic settings object should
    monkeypatch ``_load_settings`` rather than calling this directly.
    """
    from mahavishnu.core.config import get_settings

    return get_settings()


def _worker_record_store() -> WorkerRecordStore:
    """Construct the canonical durable-worker record store."""
    from mahavishnu.workers.contract.store import WorkerRecordStore

    root = pathlib.Path("~/.mahavishnu/worker-sessions").expanduser()
    return WorkerRecordStore(root)


def _count_workers_by_state(
    store: WorkerRecordStore,
) -> tuple[int, int]:
    """Return ``(live_count, reaped_count)`` from the durable-worker store.

    ``live`` is anything whose state is not ``WorkerLifecycleState.REAPED``.
    ``reaped`` is the inverse — strictly ``REAPED`` records.
    """
    from mahavishnu.workers.contract.state import WorkerLifecycleState

    live = 0
    reaped = 0
    for record in store.list_all():
        if record.state == WorkerLifecycleState.REAPED:
            reaped += 1
        else:
            live += 1
    return live, reaped


def _resolve_socket_dir(settings: MahavishnuSettings) -> pathlib.Path:
    """Return the canonical tmux socket directory.

    Falls back to ``~/.mahavishnu/tmux`` when the settings shape does not
    expose a socket_dir field (the bootstrap path uses that default).
    """
    candidate = getattr(settings.terminal, "socket_dir", None)
    if candidate is None:
        return pathlib.Path("~/.mahavishnu/tmux").expanduser()
    return pathlib.Path(candidate).expanduser()


def _format_row(mark: str, label: str, value: str) -> str:
    """Format one diagnostic row aligned for terminal readability."""
    return f"  {mark:<10} {label:<40} {value}"


def _build_rows(
    settings: MahavishnuSettings,
    *,
    yaml_value: str | None,
    env_value: str | None,
    tmux_path: str | None,
    claude_path: str | None,
    socket_dir: pathlib.Path,
    live_count: int,
    reaped_count: int,
) -> list[str]:
    """Render the diagnostic rows in a fixed order with the right markers.

    Marker contract:

    - ``[ok]`` when the value is present and matches expected resolution
    - ``[warn]`` when the YAML declaration disagrees with the effective value
    - ``[missing]`` when a binary that the terminal relies on is absent
    - ``[error]`` when something fundamentally failed (settings load, store)
    """
    pydantic_default = _pydantic_default_adapter()
    effective = settings.terminal.adapter_preference

    # Row 1 — Pydantic default from TerminalSettings
    rows: list[str] = [
        _format_row(
            MARK_OK,
            "Pydantic default adapter_preference",
            repr(pydantic_default),
        ),
    ]

    # Row 2 — YAML-declared value
    yaml_display = repr(yaml_value) if yaml_value is not None else "<not declared>"
    yaml_mark = MARK_OK if yaml_value is not None else MARK_WARN
    rows.append(
        _format_row(yaml_mark, "YAML declared adapter_preference", yaml_display),
    )

    # Row 3 — env override
    env_display = repr(env_value) if env_value is not None else "unset"
    env_mark = MARK_OK
    rows.append(
        _format_row(env_mark, f"Env override ({ENV_ADAPTER_KEY})", env_display),
    )

    # Row 4 — effective resolved value + disagreement marker
    disagreement = yaml_value is not None and yaml_value != effective
    effective_mark = MARK_WARN if disagreement else MARK_OK
    rows.append(
        _format_row(effective_mark, "Effective adapter_preference", repr(effective)),
    )

    # Row 5 — tmux binary
    tmux_mark = MARK_OK if tmux_path else MARK_MISSING
    tmux_display = tmux_path if tmux_path else "<not on PATH>"
    rows.append(_format_row(tmux_mark, "tmux binary", tmux_display))

    # Row 6 — claude binary
    claude_mark = MARK_OK if claude_path else MARK_MISSING
    claude_display = claude_path if claude_path else "<not on PATH>"
    rows.append(_format_row(claude_mark, "claude binary (shell PATH)", claude_display))

    # Row 7 — socket_dir (expanded)
    rows.append(_format_row(MARK_OK, "socket_dir", str(socket_dir)))

    # Row 8 — live worker count
    rows.append(_format_row(MARK_OK, "Live workers (state != reaped)", str(live_count)))

    # Row 9 — reaped worker count
    reaped_mark = MARK_WARN if reaped_count > 0 else MARK_OK
    rows.append(_format_row(reaped_mark, "Reaped workers", str(reaped_count)))

    return rows


def _collect_diagnostic(
    *,
    tmux_which: Callable | None = None,
    claude_which: Callable | None = None,
    yaml_path: pathlib.Path | None = None,
) -> tuple[list[str], bool]:
    """Collect the diagnostic rows + a boolean for the overall disagreement flag.

    Parameters are injectable so tests can substitute ``shutil.which``,
    ``_yaml_adapter_value``, etc. without patching globals.
    """
    yaml_path = yaml_path or YAML_PATH
    tmux_which = tmux_which or shutil.which
    claude_which = claude_which or shutil.which

    try:
        settings = _load_settings()
    except Exception as exc:
        logger.exception("status: settings load failed", exc_info=exc)
        return (
            [_format_row(MARK_ERROR, "Settings load failed", str(exc))],
            True,
        )

    yaml_value = _yaml_adapter_value(yaml_path)
    env_value = _env_adapter_value()

    try:
        store = _worker_record_store()
        live_count, reaped_count = _count_workers_by_state(store)
    except Exception as exc:
        logger.exception("status: worker record store read failed", exc_info=exc)
        live_count = 0
        reaped_count = 0

    socket_dir = _resolve_socket_dir(settings)

    rows = _build_rows(
        settings,
        yaml_value=yaml_value,
        env_value=env_value,
        tmux_path=tmux_which("tmux"),
        claude_path=claude_which("claude"),
        socket_dir=socket_dir,
        live_count=live_count,
        reaped_count=reaped_count,
    )

    effective = settings.terminal.adapter_preference
    disagreement = yaml_value is not None and yaml_value != effective
    return rows, disagreement


def add_status_commands(root_app: typer.Typer) -> None:
    """Register ``mahavishnu status`` on the root CLI app.

    Delayed attach mirrors the ``add_reap_commands(pool_app)`` pattern so the
    import graph stays acyclic: ``_main_cli`` imports this module and calls
    this function after ``root_app`` is constructed.
    """
    status_app = typer.Typer(
        help=(
            "Surface terminal diagnostic state — adapter_preference precedence, "
            "binary locations, socket dir, live + reaped worker counts. "
            "Output uses [ok]/[warn]/[missing]/[error] markers."
        ),
        invoke_without_command=True,
    )

    @status_app.callback()
    def _status_root() -> None:
        """Print the terminal diagnostic report."""
        rows, _ = _collect_diagnostic()
        typer.echo("mahavishnu status — terminal diagnostic")
        typer.echo("=" * 40)
        for row in rows:
            typer.echo(row)

    root_app.add_typer(status_app, name="status")

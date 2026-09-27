"""Watchdog metrics for the markdown board watcher (C-11).

Per plan §10 these are registered as Prometheus metrics. They live in
the jot module rather than core/metrics.py because core/metrics.py does
not exist in this repo (CR-1 surfaced 2026-09-26 during C-1 integration).
A future refactor may promote them to a shared module.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge

MARKDOWN_BOARD_WATCHER_UP = Gauge(
    "markdown_board_watcher_up",
    "Markdown board watcher is alive (1) or dead (0).",
)

MARKDOWN_BOARD_WATCHER_RESTARTS_TOTAL = Counter(
    "markdown_board_watcher_restarts_total",
    "Watcher restarts due to timeout or crash.",
)

MARKDOWN_BOARD_DISPATCH_TOTAL = Counter(
    "markdown_board_dispatch_total",
    "Card dispatch attempts, labeled by section and result.",
    ["section", "result"],
)

MARKDOWN_BOARD_CONFLICT_TOTAL = Counter(
    "markdown_board_conflict_total",
    "CAS conflicts (expected_revision mismatch).",
)

MARKDOWN_BOARD_PARSE_ERRORS_TOTAL = Counter(
    "markdown_board_parse_errors_total",
    "Markdown parse failures.",
)


__all__ = [
    "MARKDOWN_BOARD_CONFLICT_TOTAL",
    "MARKDOWN_BOARD_DISPATCH_TOTAL",
    "MARKDOWN_BOARD_PARSE_ERRORS_TOTAL",
    "MARKDOWN_BOARD_WATCHER_RESTARTS_TOTAL",
    "MARKDOWN_BOARD_WATCHER_UP",
]

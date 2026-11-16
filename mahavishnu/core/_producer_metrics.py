"""Producer-side observability counters (cross-portfolio shape)."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram


class ProducerCounters:
    attempted: Counter = Counter(
        "mahavishnu_producer_writes_attempted_total",
        "Producer writes attempted",
        ["producer"],
    )
    succeeded: Counter = Counter(
        "mahavishnu_producer_writes_succeeded_total",
        "Producer writes that landed in the substrate",
        ["producer"],
    )
    skipped: Counter = Counter(
        "mahavishnu_producer_writes_skipped_total",
        "Producer writes skipped (substrate unbound)",
        ["producer"],
    )


COUNTERS = ProducerCounters()


EVENTBRIDGE_PUBLISH_TOTAL: Counter = Counter(
    "mahavishnu_eventbridge_publish_total",
    "Total EventBridge publish attempts, labeled by envelope topic and result.",
    labelnames=["envelope_topic", "result"],
)

ECOSYSTEM_INTAKE_TOTAL: Counter = Counter(
    "ecosystem_intake_total",
    "Total ecosystem intake requests, labeled by source and result.",
    labelnames=["source", "result"],
    # result in {accepted, queued_no_publisher, not_found, disabled, too_large, error}
)

ECOSYSTEM_INTAKE_SANITIZE_DURATION: Histogram = Histogram(
    "ecosystem_intake_sanitize_duration_seconds",
    "Time to sanitize the request body via DataSanitizeAction.",
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0),
)


# ---------------------------------------------------------------------------
# Worktree metrics (C-8 / REQ-010)
# ---------------------------------------------------------------------------

WORKTREE_CREATION_TOTAL: Counter = Counter(
    "worktree_creation_total",
    "Total worktree creation attempts, labeled by result.",
    labelnames=["result"],  # success | lock_conflict | error
)

WORKTREE_ACTIVE_COUNT: Gauge = Gauge(
    "worktree_active_count",
    "Worktrees this server currently holds.",
)

WORKTREE_ISOLATION_REFUSALS_TOTAL: Counter = Counter(
    "worktree_isolation_refusals_total",
    "Worktree-isolated dispatches refused before the worker ran, labeled by reason.",
    labelnames=["reason"],
    # The reason labels are the ``REPO_*`` constants in
    # ``mahavishnu/mcp/tools/pool_tools.py``, plus ``no_capable_pool``
    # from the pool router. They are spelled here rather than imported
    # because this module is the one the pool tools import; the
    # spelling is pinned by a test that reads these lines, so a
    # dashboard query written from this comment keeps matching.
    #
    #     unresolved            -- the named repository is not a local path
    #     not_authorized        -- outside the operator's allowed roots
    #     not_a_git_repo        -- the path is not a git working tree
    #     settings_unavailable  -- the allowed roots could not be read
    #     no_capable_pool       -- no pool can start a session in a directory
    #     rerank_moved_the_task -- the re-ranking picked a pool that cannot
    #     pool_cannot_honour_cwd -- a directly targeted pool cannot honour
    #                               the directory the task named
)

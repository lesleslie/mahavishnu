"""Producer-side observability counters (cross-portfolio shape)."""
from __future__ import annotations

from prometheus_client import Counter


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
"""PlanIndexFeedState — wire-up discipline 4-signal feed state.

Mirror pattern: mahavishnu/mcp/signer_feed.py::SignerFeedState.

as_dict() returns EXACTLY the four mandatory signals plus the `ok` key:
    {ok, entities_count, last_updated_timestamp, errors_total, cycles_total}

The 4-signal contract from mcp-backend-wiring-discipline.md is strict —
do not extend. successful_cycles_total is tracked as a Dhara meta key
but NOT in as_dict(); compute success ratio in dashboards as
1 - errors_total/cycles_total.
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Final

__all__ = ["PlanIndexFeedState"]

DEFAULT_CRON_EVERY_SECONDS: Final[int] = 3600
STALENESS_MULTIPLIER: Final[int] = 5


@dataclass(frozen=True, slots=True)
class PlanIndexFeedState:
    entities_count: int
    last_updated_timestamp: int
    errors_total: int
    cycles_total: int

    def is_ok(self, *, cron_every_seconds: int = DEFAULT_CRON_EVERY_SECONDS) -> bool:
        """True if last_updated_timestamp is within 5× cron_every_seconds."""
        now_ms = int(time.time() * 1000)
        threshold_ms = cron_every_seconds * STALENESS_MULTIPLIER * 1000
        return (now_ms - self.last_updated_timestamp) < threshold_ms

    def as_dict(self) -> dict[str, int | bool]:
        """Return the 4-signal feed-state dict plus ok. STRICT 5 keys.

        The keys are PREFIXED with `feed_` per the canonical
        mcp-backend-wiring-discipline.md 4-signal contract. Mirrors
        SignerFeedState.as_dict() (mahavishnu/mcp/signer_feed.py:203).
        """
        return {
            "ok": self.is_ok(),
            "feed_entities_count": self.entities_count,
            "feed_last_updated_timestamp": self.last_updated_timestamp,
            "feed_errors_total": self.errors_total,
            "feed_cycles_total": self.cycles_total,
        }

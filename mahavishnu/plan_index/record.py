"""PlanRecord — frozen dataclass for plan-index entries.

13 fields per spec §Data Model. kw_only=True prevents positional mistakes.
status/role/lifecycle_state use Literal; invalid values raise ValueError
at construction (mypy checks at static time, runtime check is defensive).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from mahavishnu.plan_index import PlanId

__all__ = ["PlanRecord"]

_STATUS_VALUES: tuple[str, ...] = (
    "draft",
    "active",
    "partial",
    "shipped",
    "complete",
)
_ROLE_VALUES: tuple[str, ...] = (
    "canonical",
    "implementation",
    "umbrella",
    "historical",
    "superseded",
)
_LIFECYCLE_VALUES: tuple[str, ...] = ("built", "wired", "adopted")


@dataclass(frozen=True, slots=True, kw_only=True)
class PlanRecord:
    plan_id: PlanId
    path: str
    title: str
    status: Literal["draft", "active", "partial", "shipped", "complete"]
    role: Literal["canonical", "implementation", "umbrella", "historical", "superseded"]
    topic: str
    date: str
    last_reviewed: str
    superseded_by: str | None
    blocks_on: list[PlanId]
    sha: str
    repo: str
    lifecycle_state: Literal["built", "wired", "adopted"] | None = None
    updated_at_ms: int

    def __post_init__(self) -> None:
        if self.status not in _STATUS_VALUES:
            raise ValueError(f"status must be one of {_STATUS_VALUES}, got {self.status!r}")
        if self.role not in _ROLE_VALUES:
            raise ValueError(f"role must be one of {_ROLE_VALUES}, got {self.role!r}")
        if (
            self.lifecycle_state is not None
            and self.lifecycle_state not in _LIFECYCLE_VALUES
        ):
            raise ValueError(
                f"lifecycle_state must be one of {_LIFECYCLE_VALUES} or None, "
                f"got {self.lifecycle_state!r}"
            )

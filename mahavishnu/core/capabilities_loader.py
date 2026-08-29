"""Load capability + worker registrations from Oneiric-loaded config.

Each `WorkerEntry.provides` becomes one Capability. Multiple worker entries
can provide the same CapabilityId (e.g. 5 workers provide ``worker:ai-context``);
we group by ID so the Conductor can choose between them.
"""
from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from mahavishnu.core.capabilities import (
    Capability,
    CapabilityId,
    CapabilityKind,
    CapabilityState,
    CostHint,
    TypeSchema,
)

if TYPE_CHECKING:
    from mahavishnu.core.config import MahavishnuSettings


def load_capabilities_from_settings(
    settings: "MahavishnuSettings",
) -> dict[str, list[Capability]]:
    """Convert ``settings.worker_registry.entries`` into a ``{capability_id: [Capability, ...]}`` map.

    CapabilityId pattern is enforced at the Pydantic layer (WorkerEntry.provides
    field_validator), so this function trusts the input.
    """
    grouped: dict[str, list[Capability]] = defaultdict(list)
    for entry in settings.worker_registry.entries:
        for cap_id in entry.provides:
            capability = Capability(
                id=CapabilityId(cap_id),
                kind=CapabilityKind.WORKER,
                description=entry.description or entry.name,
                io_in=TypeSchema(),
                io_out=TypeSchema(),
                state=CapabilityState.EPHEMERAL,
                cost_hint=CostHint(has_side_effects=True),
                tags=entry.tags,
            )
            grouped[cap_id].append(capability)
    return dict(grouped)


__all__ = ["load_capabilities_from_settings"]

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ..workers.contract.manager import DurableWorkerManager
    from ..workers.contract.record import DurableWorkerRecord


def on_mahavishnu_startup(
    manager: DurableWorkerManager,
) -> Iterable[DurableWorkerRecord]:
    """Spec §8.1: load durable records and reconcile each against
    the live tmux target. Returns the reconciled records.
    """
    return manager.reconcile_all()
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..workers.contract.manager import DurableWorkerManager


def on_mahavishnu_shutdown(manager: DurableWorkerManager) -> int:
    """Spec §8.5: graceful shutdown.

    Marks in-flight workers as DETACHED, emits worker.status_changed
    for each, and does NOT kill panes (the operator may want to keep
    them). Returns the number of records transitioned.
    """
    return manager.mark_all_detached()

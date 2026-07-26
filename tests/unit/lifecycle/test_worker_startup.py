from __future__ import annotations

from unittest.mock import MagicMock


def test_startup_reconciles_all_records() -> None:
    manager = MagicMock()
    manager.reconcile_all = MagicMock(return_value=[{"worker_id": "w-1"}])
    from mahavishnu.lifecycle.worker_startup import on_mahavishnu_startup

    on_mahavishnu_startup(manager)
    manager.reconcile_all.assert_called_once()
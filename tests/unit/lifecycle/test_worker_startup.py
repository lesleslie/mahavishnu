from __future__ import annotations

from unittest.mock import MagicMock


def test_startup_reconciles_all_records() -> None:
    manager = MagicMock()
    expected = [{"worker_id": "w-1"}, {"worker_id": "w-2"}]
    manager.reconcile_all = MagicMock(return_value=expected)
    from mahavishnu.lifecycle.worker_startup import on_mahavishnu_startup

    result = on_mahavishnu_startup(manager)
    manager.reconcile_all.assert_called_once()
    # on_mahavishnu_startup must return the reconciled records so the
    # caller can inspect transitions (e.g. log reaped workers) without
    # a second manager call.
    assert result == expected

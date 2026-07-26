from __future__ import annotations

from unittest.mock import MagicMock


def test_shutdown_marks_in_flight_detached() -> None:
    manager = MagicMock()
    manager.mark_all_detached = MagicMock(return_value=3)
    from mahavishnu.lifecycle.worker_shutdown import on_mahavishnu_shutdown

    on_mahavishnu_shutdown(manager)
    manager.mark_all_detached.assert_called_once()


def test_shutdown_does_not_kill_panes() -> None:
    manager = MagicMock()
    manager.cancel = MagicMock()
    from mahavishnu.lifecycle.worker_shutdown import on_mahavishnu_shutdown

    on_mahavishnu_shutdown(manager)
    manager.cancel.assert_not_called()

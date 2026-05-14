from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from mahavishnu.core.app import MahavishnuApp


def test_wait_for_dependencies_returns_true_when_disabled():
    app = object.__new__(MahavishnuApp)
    app.config = SimpleNamespace(
        health=SimpleNamespace(enabled=False, dependencies={}),
        unified_validation_enabled=False,
    )
    app._dhara_state = None
    app._recover_workflow_state_from_dhara = AsyncMock()
    app._recover_approvals_from_dhara = AsyncMock()

    result = asyncio.run(app.wait_for_dependencies())

    assert result is True
    app._recover_workflow_state_from_dhara.assert_not_awaited()
    app._recover_approvals_from_dhara.assert_not_awaited()

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from mahavishnu.core.dependency_waiter import wait_for_dependencies
from mahavishnu.core.health import HealthCheckResult, HealthStatus


@pytest.mark.asyncio
async def test_wait_for_dependencies_returns_true_when_disabled() -> None:
    app = SimpleNamespace(
        config=SimpleNamespace(
            health=SimpleNamespace(enabled=False, dependencies={}),
            unified_validation_enabled=False,
        ),
        _dhara_state=None,
    )

    result = await wait_for_dependencies(app)

    assert result is True


@pytest.mark.asyncio
async def test_wait_for_dependencies_recovers_and_validates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = SimpleNamespace(
        success=True,
        dependencies={
            "session_buddy": HealthCheckResult(
                service_name="session_buddy",
                status=HealthStatus.OK,
                latency_ms=3.5,
            )
        },
        total_wait_seconds=1.25,
        failed_required=[],
        skipped_optional=[],
    )

    class FakeWaiter:
        def __init__(self, config: object) -> None:
            self.config = config
            self.wait_for_all = AsyncMock(return_value=result)

    class FakeUnifiedConfig:
        validate = staticmethod(
            lambda: SimpleNamespace(
                valid=False,
                get_errors=lambda: [SimpleNamespace(path="db", message="missing")],
            )
        )

        validate_strict = staticmethod(lambda: None)

    monkeypatch.setattr("mahavishnu.core.health.DependencyWaiter", FakeWaiter)
    monkeypatch.setattr("mahavishnu.core.unified_config.UnifiedConfig", FakeUnifiedConfig)

    dhara_state = SimpleNamespace(
        probe=AsyncMock(return_value=True),
    )
    app = SimpleNamespace(
        config=SimpleNamespace(
            health=SimpleNamespace(enabled=True, dependencies={"session_buddy": object()}),
            unified_validation_enabled=False,
        ),
        _dhara_state=dhara_state,
        _recover_workflow_state_from_dhara=AsyncMock(),
        _recover_approvals_from_dhara=AsyncMock(),
    )

    result_value = await wait_for_dependencies(app)

    assert result_value is True
    dhara_state.probe.assert_awaited_once()
    app._recover_workflow_state_from_dhara.assert_awaited_once()
    app._recover_approvals_from_dhara.assert_awaited_once()


@pytest.mark.asyncio
async def test_wait_for_dependencies_returns_false_on_strict_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = SimpleNamespace(
        success=True,
        dependencies={},
        total_wait_seconds=0.0,
        failed_required=[],
        skipped_optional=[],
    )

    class FakeWaiter:
        def __init__(self, config: object) -> None:
            self.wait_for_all = AsyncMock(return_value=result)

    class FakeUnifiedConfig:
        validate = staticmethod(lambda: SimpleNamespace(valid=True, get_errors=lambda: []))

        @staticmethod
        def validate_strict() -> None:
            raise RuntimeError("invalid strict config")

    monkeypatch.setattr("mahavishnu.core.health.DependencyWaiter", FakeWaiter)
    monkeypatch.setattr("mahavishnu.core.unified_config.UnifiedConfig", FakeUnifiedConfig)

    app = SimpleNamespace(
        config=SimpleNamespace(
            health=SimpleNamespace(enabled=True, dependencies={"akosha": object()}),
            unified_validation_enabled=True,
        ),
        _dhara_state=None,
        _recover_workflow_state_from_dhara=AsyncMock(),
        _recover_approvals_from_dhara=AsyncMock(),
    )

    result_value = await wait_for_dependencies(app)

    assert result_value is False

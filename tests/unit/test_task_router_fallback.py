"""Tests for TaskRouter graceful fallback mechanism."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from mahavishnu.core.task_router import TaskRouter, AdapterManager, StateManager
from mahavishnu.core.adapters.base import AdapterType, AdapterCapabilities, OrchestratorAdapter


class MockAdapter(OrchestratorAdapter):
    """Mock adapter for testing."""

    def __init__(
        self,
        adapter_type: AdapterType,
        should_fail: bool = False,
        fail_until_attempt: int = 999,
    ):
        self._adapter_type = adapter_type
        self._name = adapter_type.value
        self.should_fail = should_fail
        self.fail_until_attempt = fail_until_attempt
        self.attempt_count = 0
        self._capabilities = AdapterCapabilities(
            can_deploy_flows=True,
            can_monitor_execution=True,
            can_cancel_workflows=True,
            supports_batch_execution=True,
            supports_multi_agent=True,
        )

    @property
    def adapter_type(self) -> AdapterType:
        return self._adapter_type

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> AdapterCapabilities:
        return self._capabilities

    async def initialize(self):
        pass

    async def execute(self, task: dict, repos: list = None) -> dict:
        self.attempt_count += 1

        if self.should_fail and self.attempt_count < self.fail_until_attempt:
            raise Exception(f"{self._adapter_type.value} failed intentionally")

        # Return mock ULID
        return {"execution_id": "01" + "A" * 24}  # 26-char ULID

    async def get_health(self) -> dict:
        return {"status": "healthy"}


@pytest.mark.asyncio
async def test_execute_with_fallback_succeeds_on_primary():
    """Task should succeed on primary adapter without fallback."""
    manager = AdapterManager()
    await manager.register_adapter(
        AdapterType.PREFECT,
        MockAdapter(AdapterType.PREFECT, should_fail=False),
    )

    router = TaskRouter(adapter_registry=manager, state_manager=StateManager())

    task = {"task_type": "workflow", "workflow_name": "test_workflow"}
    result = await router.execute_with_fallback(task)

    assert result["success"] is True
    assert result["adapter"] == AdapterType.PREFECT
    assert len(result["fallback_chain"]) == 1
    assert result["total_attempts"] == 1


@pytest.mark.asyncio
async def test_execute_with_fallback_fails_to_secondary():
    """Task should fallback to secondary adapter if primary fails."""
    manager = AdapterManager()
    await manager.register_adapter(
        AdapterType.PREFECT,
        MockAdapter(AdapterType.PREFECT, should_fail=True),
    )
    await manager.register_adapter(
        AdapterType.AGNO,
        MockAdapter(AdapterType.AGNO, should_fail=False),
    )

    router = TaskRouter(adapter_registry=manager, state_manager=StateManager())

    task = {"task_type": "ai_task", "workflow_name": "test_crew"}
    result = await router.execute_with_fallback(task)

    assert result["success"] is True
    assert result["adapter"] == AdapterType.AGNO
    assert result["fallback_chain"] == [AdapterType.PREFECT, AdapterType.AGNO]
    assert result["total_attempts"] == 4  # 3 retries on Prefect + 1 on Agno


@pytest.mark.asyncio
async def test_execute_with_fallback_all_adapters_fail():
    """Should return failure if all adapters fail."""
    manager = AdapterManager()
    await manager.register_adapter(
        AdapterType.PREFECT,
        MockAdapter(AdapterType.PREFECT, should_fail=True),
    )
    await manager.register_adapter(
        AdapterType.AGNO,
        MockAdapter(AdapterType.AGNO, should_fail=True),
    )
    await manager.register_adapter(
        AdapterType.LLAMAINDEX,
        MockAdapter(AdapterType.LLAMAINDEX, should_fail=True),
    )

    router = TaskRouter(adapter_registry=manager, state_manager=StateManager())

    task = {"task_type": "rag_query", "workflow_name": "test_query"}
    result = await router.execute_with_fallback(task)

    assert result["success"] is False
    assert result["adapter"] is None
    assert result["result"] is None
    assert len(result["fallback_chain"]) == 3
    assert "error" in result


@pytest.mark.asyncio
async def test_execute_with_fallback_custom_preference_order():
    """Should respect custom preference order."""
    manager = AdapterManager()
    await manager.register_adapter(
        AdapterType.PREFECT,
        MockAdapter(AdapterType.PREFECT, should_fail=True),
    )
    await manager.register_adapter(
        AdapterType.LLAMAINDEX,
        MockAdapter(AdapterType.LLAMAINDEX, should_fail=False),
    )

    router = TaskRouter(adapter_registry=manager, state_manager=StateManager())

    # Custom order: try LlamaIndex before Agno
    custom_order = [AdapterType.LLAMAINDEX, AdapterType.PREFECT]

    task = {"task_type": "rag_query", "workflow_name": "test_custom_order"}
    result = await router.execute_with_fallback(task, preference_order=custom_order)

    assert result["success"] is True
    assert result["adapter"] == AdapterType.LLAMAINDEX
    assert result["fallback_chain"] == [AdapterType.LLAMAINDEX]


@pytest.mark.asyncio
async def test_adapter_statistics_tracking():
    """Should track success and failure rates per adapter."""
    manager = AdapterManager()
    prefect_adapter = MockAdapter(AdapterType.PREFECT, should_fail=True)
    agno_adapter = MockAdapter(AdapterType.AGNO, should_fail=False)

    await manager.register_adapter(AdapterType.PREFECT, prefect_adapter)
    await manager.register_adapter(AdapterType.AGNO, agno_adapter)

    router = TaskRouter(adapter_registry=manager, state_manager=StateManager())

    # Execute 5 distinct tasks - each has unique workflow_name
    # Each task fails on Prefect (3 retries), then succeeds on Agno (1 attempt)
    # Total: 5 tasks × 4 attempts max = but Prefect never succeeds
    for i in range(5):
        task = {
            "task_type": "workflow",
            "workflow_name": f"test_stats_{i}",
        }
        result = await router.execute_with_fallback(task)
        # Verify each task succeeded on Agno after Prefect retries
        assert result["success"] is True
        assert result["adapter"] == AdapterType.AGNO

    stats = await router.get_adapter_statistics()

    # Prefect: 5 tasks failed = 5 failures, 0 successes
    # Note: Each task counts once, not per-retry
    assert stats["prefect"]["failures"] == 5
    assert stats["prefect"]["successes"] == 0
    assert stats["prefect"]["total_attempts"] == 5
    assert stats["prefect"]["success_rate"] == 0.0

    # Agno: 5 tasks succeeded = 5 successes, 0 failures
    assert stats["agno"]["successes"] == 5
    assert stats["agno"]["failures"] == 0
    assert stats["agno"]["total_attempts"] == 5
    assert stats["agno"]["success_rate"] == 1.0


@pytest.mark.asyncio
async def test_execute_with_retry_on_transient_failures():
    """Should retry transient failures before giving up on adapter."""
    manager = AdapterManager()
    # Adapter that fails first 2 attempts, succeeds on 3rd
    flaky_adapter = MockAdapter(
        AdapterType.PREFECT,
        should_fail=True,
        fail_until_attempt=3,
    )

    await manager.register_adapter(AdapterType.PREFECT, flaky_adapter)

    router = TaskRouter(adapter_registry=manager, state_manager=StateManager())

    task = {"task_type": "workflow", "workflow_name": "test_flaky"}
    result = await router.execute_with_fallback(task, max_retries=3)

    assert result["success"] is True
    assert result["adapter"] == AdapterType.PREFECT
    assert result["total_attempts"] == 3
    assert flaky_adapter.attempt_count == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

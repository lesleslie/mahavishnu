"""Unit tests for core.routing."""

from __future__ import annotations

import pytest

from mahavishnu.core.metrics_schema import AdapterType, TaskType
import mahavishnu.core.routing as routing


def test_classify_intent_defaults_and_pattern_matches() -> None:
    router = routing.TaskRouter()

    assert router.classify_intent("") == TaskType.WORKFLOW
    assert router.classify_intent("   ") == TaskType.WORKFLOW
    assert router.classify_intent("urgent security patch required") == TaskType.CRITICAL_TASK
    assert router.classify_intent("semantic search over documents") == TaskType.RAG_QUERY
    assert router.classify_intent("interactive live websocket chat") == TaskType.INTERACTIVE_TASK
    assert router.classify_intent("unknown gibberish phrase") == TaskType.WORKFLOW


def test_generate_fallback_chain_default_and_preferred() -> None:
    router = routing.TaskRouter()

    chain = router.generate_fallback_chain(TaskType.AI_TASK)
    assert chain == [AdapterType.AGNO, AdapterType.LLAMAINDEX, AdapterType.PREFECT]

    preferred = router.generate_fallback_chain(TaskType.AI_TASK, AdapterType.LLAMAINDEX)
    assert preferred[0] == AdapterType.LLAMAINDEX
    assert set(preferred) == set(chain)
    assert len(preferred) == 3

    # Unknown task type falls back to default static chain.
    class _Unknown:
        value = "unknown"

    unknown_chain = router.generate_fallback_chain(_Unknown())  # type: ignore[arg-type]
    assert unknown_chain == [AdapterType.PREFECT, AdapterType.AGNO, AdapterType.LLAMAINDEX]


@pytest.mark.asyncio
async def test_get_adapter_scores_and_context_adjustments() -> None:
    router = routing.TaskRouter()

    base = await router.get_adapter_scores(TaskType.WORKFLOW)
    assert base[AdapterType.PREFECT] > base[AdapterType.AGNO] > base[AdapterType.LLAMAINDEX]

    adjusted = await router.get_adapter_scores(
        TaskType.AI_TASK,
        context={
            "max_cost_usd": 0.05,  # favor llamaindex
            "max_latency_ms": 1000,  # favor prefect
            "min_success_rate": 0.99,  # favor prefect
        },
    )
    assert max(adjusted.values()) <= 1.0
    assert adjusted[AdapterType.LLAMAINDEX] > 0


def test_apply_context_adjustments_normalizes_above_one() -> None:
    router = routing.TaskRouter()
    scores = {
        AdapterType.PREFECT: 0.95,
        AdapterType.AGNO: 0.9,
        AdapterType.LLAMAINDEX: 0.85,
    }
    out = router._apply_context_adjustments(
        scores,
        {"max_cost_usd": 0.01, "max_latency_ms": 100, "min_success_rate": 0.99},
    )
    assert max(out.values()) <= 1.0
    assert set(out.keys()) == set(scores.keys())


@pytest.mark.asyncio
async def test_select_adapter_by_strategy() -> None:
    router = routing.TaskRouter(default_strategy=routing.RoutingStrategy.BALANCED)

    balanced = await router.select_adapter(TaskType.WORKFLOW)
    assert balanced == AdapterType.PREFECT

    latency = await router.select_adapter(TaskType.AI_TASK, routing.RoutingStrategy.LATENCY)
    assert latency in {AdapterType.PREFECT, AdapterType.AGNO, AdapterType.LLAMAINDEX}

    success = await router.select_adapter(TaskType.RAG_QUERY, routing.RoutingStrategy.SUCCESS_RATE)
    assert success in {AdapterType.PREFECT, AdapterType.AGNO, AdapterType.LLAMAINDEX}

    # COST strategy currently uses existing scores directly.
    cost = await router.select_adapter(TaskType.AI_TASK, routing.RoutingStrategy.COST)
    assert cost in {AdapterType.PREFECT, AdapterType.AGNO, AdapterType.LLAMAINDEX}


def test_get_routing_info_shape() -> None:
    router = routing.TaskRouter(default_strategy=routing.RoutingStrategy.LATENCY)
    info = router.get_routing_info(TaskType.BATCH_TASK)
    assert info["task_type"] == TaskType.BATCH_TASK.value
    assert info["strategy"] == routing.RoutingStrategy.LATENCY.value
    assert isinstance(info["fallback_chain"], list)
    assert info["total_adapters"] == len(info["fallback_chain"])
    assert info["primary_adapter"] == info["fallback_chain"][0]


def test_singleton_get_and_reset_task_router() -> None:
    routing.reset_task_router()
    a = routing.get_task_router()
    b = routing.get_task_router()
    assert a is b

    routing.reset_task_router()
    c = routing.get_task_router()
    assert c is not a

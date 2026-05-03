"""Tests for mahavishnu.pools.memory_aggregator."""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timedelta
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from mahavishnu.pools.memory_aggregator import (
    MemoryAggregator,
    _await_if_needed,
    _CircuitBreaker,
)

# ---------------------------------------------------------------------------
# _await_if_needed
# ---------------------------------------------------------------------------


class TestAwaitIfNeeded:
    @pytest.mark.asyncio
    async def test_returns_awaitable(self):
        async def coro():
            return 42

        result = await _await_if_needed(coro())
        assert result == 42

    @pytest.mark.asyncio
    async def test_returns_plain_value(self):
        assert await _await_if_needed(42) == 42

    @pytest.mark.asyncio
    async def test_returns_string(self):
        assert await _await_if_needed("hello") == "hello"

    @pytest.mark.asyncio
    async def test_returns_none(self):
        assert await _await_if_needed(None) is None

    @pytest.mark.asyncio
    async def test_returns_dict(self):
        d = {"key": "value"}
        assert await _await_if_needed(d) == d


# ---------------------------------------------------------------------------
# _CircuitBreaker
# ---------------------------------------------------------------------------


class TestCircuitBreakerInit:
    def test_defaults(self):
        cb = _CircuitBreaker("test")
        assert cb.name == "test"
        assert not cb.is_open
        assert cb._failure_count == 0
        assert cb._failure_threshold == 5
        assert cb._recovery_timeout == 60.0

    def test_custom_threshold(self):
        cb = _CircuitBreaker("test", failure_threshold=3, recovery_timeout=30.0)
        assert cb._failure_threshold == 3
        assert cb._recovery_timeout == 30.0


class TestCircuitBreakerCanExecute:
    def test_closed_allows(self):
        cb = _CircuitBreaker("test")
        assert cb.can_execute() is True

    def test_open_blocks(self):
        cb = _CircuitBreaker("test", failure_threshold=1)
        cb.record_failure()
        assert cb.is_open is True
        assert cb.can_execute() is False

    def test_recovery_after_timeout(self):
        cb = _CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.0)
        cb.record_failure()
        time.sleep(0.01)
        assert cb.can_execute() is True

    def test_not_yet_recovered(self):
        cb = _CircuitBreaker("test", failure_threshold=1, recovery_timeout=10.0)
        cb.record_failure()
        assert cb.can_execute() is False


class TestCircuitBreakerRecordSuccess:
    def test_resets_failure_count(self):
        cb = _CircuitBreaker("test", failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb._failure_count == 2
        cb.record_success()
        assert cb._failure_count == 0
        assert not cb.is_open

    def test_closes_open_circuit(self):
        cb = _CircuitBreaker("test", failure_threshold=1)
        cb.record_failure()
        assert cb.is_open
        cb.record_success()
        assert not cb.is_open


class TestCircuitBreakerRecordFailure:
    def test_increments_count(self):
        cb = _CircuitBreaker("test", failure_threshold=5)
        cb.record_failure()
        cb.record_failure()
        assert cb._failure_count == 2

    def test_opens_at_threshold(self):
        cb = _CircuitBreaker("test", failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert not cb.is_open
        cb.record_failure()
        assert cb.is_open

    def test_no_double_open(self):
        cb = _CircuitBreaker("test", failure_threshold=1)
        cb.record_failure()
        assert cb.is_open
        cb.record_failure()
        assert cb.is_open  # stays open


# ---------------------------------------------------------------------------
# MemoryAggregator.__init__
# ---------------------------------------------------------------------------


@pytest.fixture
def aggregator() -> MemoryAggregator:
    return MemoryAggregator(
        session_buddy_url="http://localhost:8678/mcp",
        akosha_url="http://localhost:8682/mcp",
        sync_interval=60.0,
    )


class TestMemoryAggregatorInit:
    def test_defaults(self, aggregator: MemoryAggregator):
        assert aggregator.session_buddy_url == "http://localhost:8678/mcp"
        assert aggregator.akosha_url == "http://localhost:8682/mcp"
        assert aggregator.sync_interval == 60.0

    def test_custom_urls(self):
        agg = MemoryAggregator(
            session_buddy_url="http://custom:9999/mcp",
            akosha_url="http://other:8888/mcp",
        )
        assert agg.session_buddy_url == "http://custom:9999/mcp"
        assert agg.akosha_url == "http://other:8888/mcp"

    def test_local_buffer_initially_empty(self, aggregator: MemoryAggregator):
        assert len(aggregator._local_buffer) == 0
        assert aggregator._buffer_drops == 0

    def test_search_cache_initially_empty(self, aggregator: MemoryAggregator):
        assert aggregator._search_cache == {}

    def test_circuit_breakers_created(self, aggregator: MemoryAggregator):
        assert not aggregator._sb_breaker.is_open
        assert not aggregator._akosha_breaker.is_open


# ---------------------------------------------------------------------------
# _collect_from_pool
# ---------------------------------------------------------------------------


class TestCollectFromPool:
    @pytest.mark.asyncio
    async def test_returns_items(self, aggregator: MemoryAggregator):
        pool = AsyncMock()
        pool.collect_memory.return_value = [{"text": "item1"}]
        result = await aggregator._collect_from_pool(pool, "pool_1")
        assert result == [{"text": "item1"}]

    @pytest.mark.asyncio
    async def test_empty_result(self, aggregator: MemoryAggregator):
        pool = AsyncMock()
        pool.collect_memory.return_value = []
        result = await aggregator._collect_from_pool(pool, "pool_1")
        assert result == []

    @pytest.mark.asyncio
    async def test_exception_returns_empty(self, aggregator: MemoryAggregator):
        pool = AsyncMock()
        pool.collect_memory.side_effect = RuntimeError("pool error")
        result = await aggregator._collect_from_pool(pool, "pool_1")
        assert result == []


# ---------------------------------------------------------------------------
# _buffer_items
# ---------------------------------------------------------------------------


class TestBufferItems:
    def test_buffer_single_item(self, aggregator: MemoryAggregator):
        aggregator._buffer_items([{"text": "test"}])
        assert len(aggregator._local_buffer) == 1

    def test_buffer_multiple_items(self, aggregator: MemoryAggregator):
        aggregator._buffer_items([{"a": 1}, {"b": 2}, {"c": 3}])
        assert len(aggregator._local_buffer) == 3

    def test_buffer_empty_list(self, aggregator: MemoryAggregator):
        aggregator._buffer_items([])
        assert len(aggregator._local_buffer) == 0

    def test_fifo_eviction(self, aggregator: MemoryAggregator):
        # Recreate deque with smaller maxlen since deque(maxlen=) is set at init
        aggregator._local_buffer = deque(maxlen=3)
        aggregator._buffer_items([{"id": 1}, {"id": 2}, {"id": 3}])
        aggregator._buffer_items([{"id": 4}])
        assert len(aggregator._local_buffer) == 3
        contents = list(aggregator._local_buffer)
        assert contents[0]["id"] == 2

    def test_buffer_at_capacity(self, aggregator: MemoryAggregator):
        aggregator.LOCAL_BUFFER_MAX = 3
        aggregator._buffer_items([{"a": 1}, {"b": 2}, {"c": 3}])
        assert len(aggregator._local_buffer) == 3
        # No drops at capacity
        assert aggregator._buffer_drops == 0


# ---------------------------------------------------------------------------
# flush_local_buffer
# ---------------------------------------------------------------------------


class TestFlushLocalBuffer:
    @pytest.mark.asyncio
    async def test_empty_buffer_returns_zero(self, aggregator: MemoryAggregator):
        result = await aggregator.flush_local_buffer()
        assert result == {"flushed": 0, "remaining": 0}

    @pytest.mark.asyncio
    async def test_flushes_all_items(self, aggregator: MemoryAggregator):
        aggregator._buffer_items([{"a": 1}, {"b": 2}])
        with patch.object(
            aggregator, "_batch_insert_to_session_buddy", new_callable=AsyncMock
        ) as mock:
            mock.return_value = 2
            result = await aggregator.flush_local_buffer()
        assert result["flushed"] == 2
        assert result["remaining"] == 0
        assert len(aggregator._local_buffer) == 0


# ---------------------------------------------------------------------------
# get_circuit_breaker_stats
# ---------------------------------------------------------------------------


class TestGetCircuitBreakerStats:
    def test_initial_stats(self, aggregator: MemoryAggregator):
        stats = aggregator.get_circuit_breaker_stats()
        assert not stats["session_buddy"]["circuit_open"]
        assert not stats["akosha"]["circuit_open"]
        assert stats["local_buffer"]["size"] == 0
        assert stats["local_buffer"]["max"] == 500
        assert stats["local_buffer"]["drops"] == 0

    def test_stats_with_buffered_items(self, aggregator: MemoryAggregator):
        aggregator._buffer_items([{"a": 1}])
        aggregator._buffer_drops = 5
        stats = aggregator.get_circuit_breaker_stats()
        assert stats["local_buffer"]["size"] == 1
        assert stats["local_buffer"]["drops"] == 5


# ---------------------------------------------------------------------------
# _insert_batch_to_session_buddy
# ---------------------------------------------------------------------------


class TestInsertBatchToSessionBuddy:
    @pytest.mark.asyncio
    async def test_circuit_open_buffers_all(self, aggregator: MemoryAggregator):
        aggregator._sb_breaker.record_failure()
        aggregator._sb_breaker.record_failure()
        aggregator._sb_breaker.record_failure()
        aggregator._sb_breaker.record_failure()
        aggregator._sb_breaker.record_failure()
        items = [{"text": "a"}, {"text": "b"}]
        result = await aggregator._insert_batch_to_session_buddy(items)
        assert result == 0
        assert len(aggregator._local_buffer) == 2

    @pytest.mark.asyncio
    async def test_all_succeed(self, aggregator: MemoryAggregator):
        mock_response = MagicMock()
        mock_response.status_code = 200

        async def mock_post(url, json):
            return mock_response

        aggregator._mcp_client = AsyncMock()
        aggregator._mcp_client.post = mock_post

        items = [{"text": "a"}, {"text": "b"}]
        result = await aggregator._insert_batch_to_session_buddy(items)
        assert result == 2
        assert aggregator._sb_breaker._failure_count == 0

    @pytest.mark.asyncio
    async def test_partial_failure(self, aggregator: MemoryAggregator):
        call_count = 0

        async def mock_post(url, json):
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.status_code = 200 if call_count <= 1 else 500
            return resp

        aggregator._mcp_client = AsyncMock()
        aggregator._mcp_client.post = mock_post

        items = [{"text": "a"}, {"text": "b"}]
        result = await aggregator._insert_batch_to_session_buddy(items)
        assert result == 1
        assert len(aggregator._local_buffer) == 1

    @pytest.mark.asyncio
    async def test_http_error_buffers(self, aggregator: MemoryAggregator):
        aggregator._mcp_client = AsyncMock()
        aggregator._mcp_client.post.side_effect = httpx.HTTPError("connection refused")

        items = [{"text": "a"}]
        result = await aggregator._insert_batch_to_session_buddy(items)
        assert result == 0
        assert len(aggregator._local_buffer) == 1


# ---------------------------------------------------------------------------
# _batch_insert_to_session_buddy
# ---------------------------------------------------------------------------


class TestBatchInsertToSessionBuddy:
    @pytest.mark.asyncio
    async def test_empty_list(self, aggregator: MemoryAggregator):
        result = await aggregator._batch_insert_to_session_buddy([])
        assert result == 0

    @pytest.mark.asyncio
    async def test_delegates_to_batches(self, aggregator: MemoryAggregator):
        # BATCH_SIZE=20, so 25 items → 2 batches (0:20, 20:25)
        mock = AsyncMock(return_value=3)
        with patch.object(aggregator, "_insert_batch_to_session_buddy", mock):
            items = list(range(25))
            result = await aggregator._batch_insert_to_session_buddy(items)
        assert result == 6  # 2 batches × 3 each

    @pytest.mark.asyncio
    async def test_exception_in_batch(self, aggregator: MemoryAggregator):
        with patch.object(
            aggregator, "_insert_batch_to_session_buddy", new_callable=AsyncMock
        ) as mock:
            mock.side_effect = RuntimeError("batch error")
            items = [{"text": "a"}]
            result = await aggregator._batch_insert_to_session_buddy(items)
        assert result == 0


# ---------------------------------------------------------------------------
# start_periodic_sync / stop
# ---------------------------------------------------------------------------


class TestStartPeriodicSync:
    @pytest.mark.asyncio
    async def test_creates_task(self, aggregator: MemoryAggregator):
        mock_pm = AsyncMock()
        mock_pm.list_pools.return_value = []
        await aggregator.start_periodic_sync(mock_pm)
        await asyncio.sleep(0.05)
        assert aggregator._sync_task is not None
        await aggregator.stop()

    @pytest.mark.asyncio
    async def test_sync_loop_calls_collect_and_sync(self, aggregator: MemoryAggregator):
        mock_pm = AsyncMock()
        mock_pm.list_pools.return_value = []
        with patch.object(aggregator, "collect_and_sync", new_callable=AsyncMock):
            aggregator._shutdown_event.set()
            await aggregator.start_periodic_sync(mock_pm)
            await asyncio.sleep(0.05)


class TestStop:
    @pytest.mark.asyncio
    async def test_sets_shutdown_event(self, aggregator: MemoryAggregator):
        aggregator._shutdown_event = asyncio.Event()
        await aggregator.stop()
        assert aggregator._shutdown_event.is_set()

    @pytest.mark.asyncio
    async def test_closes_http_client(self, aggregator: MemoryAggregator):
        aggregator._mcp_client = AsyncMock()
        await aggregator.stop()
        aggregator._mcp_client.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cancels_stuck_task(self, aggregator: MemoryAggregator):
        async def forever():
            await asyncio.sleep(100)

        aggregator._sync_task = asyncio.create_task(forever())
        await aggregator.stop()
        assert aggregator._sync_task.done()


# ---------------------------------------------------------------------------
# _sync_to_akosha
# ---------------------------------------------------------------------------


class TestSyncToAkosha:
    @pytest.mark.asyncio
    async def test_circuit_open_skips(self, aggregator: MemoryAggregator):
        aggregator._akosha_breaker.record_failure()
        aggregator._akosha_breaker.record_failure()
        aggregator._akosha_breaker.record_failure()
        aggregator._akosha_breaker.record_failure()
        aggregator._akosha_breaker.record_failure()
        await aggregator._sync_to_akosha({"pools_count": 1})
        # No HTTP call made

    @pytest.mark.asyncio
    async def test_success_records_success(self, aggregator: MemoryAggregator):
        mock_response = MagicMock()
        mock_response.status_code = 200

        async def mock_post(url, json):
            return mock_response

        aggregator._mcp_client = AsyncMock()
        aggregator._mcp_client.post = mock_post

        await aggregator._sync_to_akosha({"pools_count": 2, "memory_items_count": 10})
        assert aggregator._akosha_breaker._failure_count == 0

    @pytest.mark.asyncio
    async def test_failure_records_failure(self, aggregator: MemoryAggregator):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "internal error"

        async def mock_post(url, json):
            return mock_response

        aggregator._mcp_client = AsyncMock()
        aggregator._mcp_client.post = mock_post

        await aggregator._sync_to_akosha({"pools_count": 2})
        assert aggregator._akosha_breaker._failure_count == 1

    @pytest.mark.asyncio
    async def test_http_error_records_failure(self, aggregator: MemoryAggregator):
        aggregator._mcp_client = AsyncMock()
        aggregator._mcp_client.post.side_effect = httpx.HTTPError("timeout")
        await aggregator._sync_to_akosha({"pools_count": 1})
        assert aggregator._akosha_breaker._failure_count == 1


# ---------------------------------------------------------------------------
# collect_and_sync
# ---------------------------------------------------------------------------


class TestCollectAndSync:
    @pytest.mark.asyncio
    async def test_empty_pools(self, aggregator: MemoryAggregator):
        mock_pm = MagicMock()
        mock_pm.list_pools = AsyncMock(return_value=[])
        with (
            patch.object(
                aggregator, "_batch_insert_to_session_buddy", new_callable=AsyncMock, return_value=0
            ),
            patch.object(
                aggregator,
                "flush_local_buffer",
                new_callable=AsyncMock,
                return_value={"flushed": 0, "remaining": 0},
            ),
            patch.object(aggregator, "_sync_to_akosha", new_callable=AsyncMock),
        ):
            result = await aggregator.collect_and_sync(mock_pm)
        assert result["pools_synced"] == 0
        assert result["memory_items_synced"] == 0

    @pytest.mark.asyncio
    async def test_with_memory_items(self, aggregator: MemoryAggregator):
        pool = AsyncMock()
        pool.collect_memory.return_value = [{"text": "m1"}, {"text": "m2"}]
        pool.status.return_value = MagicMock(value="running")

        mock_pm = MagicMock()
        mock_pm.list_pools = AsyncMock(return_value=[{"pool_id": "p1"}])
        mock_pm._pools = {"p1": pool}

        with (
            patch.object(
                aggregator, "_batch_insert_to_session_buddy", new_callable=AsyncMock, return_value=2
            ),
            patch.object(
                aggregator,
                "flush_local_buffer",
                new_callable=AsyncMock,
                return_value={"flushed": 0, "remaining": 0},
            ),
            patch.object(aggregator, "_sync_to_akosha", new_callable=AsyncMock),
        ):
            result = await aggregator.collect_and_sync(mock_pm)
        assert result["pools_synced"] == 1
        assert result["memory_items_synced"] == 2

    @pytest.mark.asyncio
    async def test_pool_not_found_warning(self, aggregator: MemoryAggregator):
        mock_pm = MagicMock()
        mock_pm.list_pools = AsyncMock(return_value=[{"pool_id": "missing"}])
        mock_pm._pools = {}

        with (
            patch.object(
                aggregator, "_batch_insert_to_session_buddy", new_callable=AsyncMock, return_value=0
            ),
            patch.object(aggregator, "_sync_to_akosha", new_callable=AsyncMock),
        ):
            result = await aggregator.collect_and_sync(mock_pm)
        assert result["pools_synced"] == 1
        assert result["memory_items_synced"] == 0

    @pytest.mark.asyncio
    async def test_collection_error_handled(self, aggregator: MemoryAggregator):
        pool = AsyncMock()
        pool.collect_memory.side_effect = RuntimeError("collect failed")

        mock_pm = MagicMock()
        mock_pm.list_pools = AsyncMock(return_value=[{"pool_id": "p1"}])
        mock_pm._pools = {"p1": pool}

        with (
            patch.object(
                aggregator, "_batch_insert_to_session_buddy", new_callable=AsyncMock, return_value=0
            ),
            patch.object(aggregator, "_sync_to_akosha", new_callable=AsyncMock),
        ):
            result = await aggregator.collect_and_sync(mock_pm)
        assert result["memory_items_synced"] == 0

    @pytest.mark.asyncio
    async def test_flushes_buffer_when_present(self, aggregator: MemoryAggregator):
        pool = AsyncMock()
        pool.collect_memory.return_value = []

        mock_pm = MagicMock()
        mock_pm.list_pools = AsyncMock(return_value=[{"pool_id": "p1"}])
        mock_pm._pools = {"p1": pool}

        aggregator._buffer_items([{"text": "buffered"}])

        with (
            patch.object(
                aggregator, "_batch_insert_to_session_buddy", new_callable=AsyncMock, return_value=0
            ),
            patch.object(
                aggregator,
                "flush_local_buffer",
                new_callable=AsyncMock,
                return_value={"flushed": 1, "remaining": 0},
            ),
            patch.object(aggregator, "_sync_to_akosha", new_callable=AsyncMock),
        ):
            result = await aggregator.collect_and_sync(mock_pm)
        assert result["pools_synced"] == 1


# ---------------------------------------------------------------------------
# cross_pool_search
# ---------------------------------------------------------------------------


class TestCrossPoolSearch:
    @pytest.mark.asyncio
    async def test_cache_hit(self, aggregator: MemoryAggregator):
        results = [{"text": "cached"}]
        # Cache key format is "query:limit" — default limit is 100
        aggregator._search_cache["query:100"] = {
            "results": results,
            "cached_at": datetime.now(),
        }
        mock_pm = MagicMock()
        result = await aggregator.cross_pool_search("query", mock_pm)
        assert result == results

    @pytest.mark.asyncio
    async def test_cache_expired(self, aggregator: MemoryAggregator):
        aggregator._search_cache["old_query:10"] = {
            "results": [{"text": "old"}],
            "cached_at": datetime.now() - timedelta(minutes=10),
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": {"conversations": [{"text": "fresh"}]}}

        async def mock_post(url, json):
            return mock_response

        aggregator._mcp_client = AsyncMock()
        aggregator._mcp_client.post = mock_post

        mock_pm = MagicMock()
        result = await aggregator.cross_pool_search("old_query", mock_pm)
        assert result == [{"text": "fresh"}]

    @pytest.mark.asyncio
    async def test_cache_miss_fetches_from_sb(self, aggregator: MemoryAggregator):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": {"conversations": [{"text": "new"}]}}

        async def mock_post(url, json):
            return mock_response

        aggregator._mcp_client = AsyncMock()
        aggregator._mcp_client.post = mock_post

        mock_pm = MagicMock()
        result = await aggregator.cross_pool_search("new query", mock_pm)
        assert result == [{"text": "new"}]
        assert "new query:100" in aggregator._search_cache

    @pytest.mark.asyncio
    async def test_circuit_open_returns_empty(self, aggregator: MemoryAggregator):
        aggregator._sb_breaker.record_failure()
        aggregator._sb_breaker.record_failure()
        aggregator._sb_breaker.record_failure()
        aggregator._sb_breaker.record_failure()
        aggregator._sb_breaker.record_failure()
        mock_pm = MagicMock()
        result = await aggregator.cross_pool_search("test", mock_pm)
        assert result == []

    @pytest.mark.asyncio
    async def test_search_failure_returns_empty(self, aggregator: MemoryAggregator):
        aggregator._mcp_client = AsyncMock()
        aggregator._mcp_client.post.side_effect = httpx.HTTPError("error")
        mock_pm = MagicMock()
        result = await aggregator.cross_pool_search("test", mock_pm)
        assert result == []

    @pytest.mark.asyncio
    async def test_search_non_200_returns_empty(self, aggregator: MemoryAggregator):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "error"

        async def mock_post(url, json):
            return mock_response

        aggregator._mcp_client = AsyncMock()
        aggregator._mcp_client.post = mock_post
        mock_pm = MagicMock()
        result = await aggregator.cross_pool_search("test", mock_pm)
        assert result == []

    @pytest.mark.asyncio
    async def test_empty_conversations_in_response(self, aggregator: MemoryAggregator):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": {"conversations": []}}

        async def mock_post(url, json):
            return mock_response

        aggregator._mcp_client = AsyncMock()
        aggregator._mcp_client.post = mock_post
        mock_pm = MagicMock()
        result = await aggregator.cross_pool_search("test", mock_pm)
        assert result == []

    @pytest.mark.asyncio
    async def test_respects_limit(self, aggregator: MemoryAggregator):
        results = [{"text": f"r{i}"} for i in range(20)]
        aggregator._search_cache["query:5"] = {
            "results": results,
            "cached_at": datetime.now(),
        }
        mock_pm = MagicMock()
        result = await aggregator.cross_pool_search("query", mock_pm, limit=5)
        assert len(result) == 5


# ---------------------------------------------------------------------------
# clear_cache / get_cache_stats
# ---------------------------------------------------------------------------


class TestClearCache:
    def test_clears_all_entries(self, aggregator: MemoryAggregator):
        aggregator._search_cache["a"] = {"results": [], "cached_at": datetime.now()}
        aggregator._search_cache["b"] = {"results": [], "cached_at": datetime.now()}
        aggregator.clear_cache()
        assert aggregator._search_cache == {}

    def test_clears_empty_cache(self, aggregator: MemoryAggregator):
        aggregator.clear_cache()
        assert aggregator._search_cache == {}


class TestGetCacheStats:
    def test_empty_cache(self, aggregator: MemoryAggregator):
        stats = aggregator.get_cache_stats()
        assert stats["total_entries"] == 0
        assert stats["active_entries"] == 0
        assert stats["expired_entries"] == 0
        assert stats["ttl_minutes"] == 5

    def test_active_and_expired(self, aggregator: MemoryAggregator):
        aggregator._search_cache["active"] = {
            "results": [],
            "cached_at": datetime.now(),
        }
        aggregator._search_cache["expired"] = {
            "results": [],
            "cached_at": datetime.now() - timedelta(minutes=10),
        }
        stats = aggregator.get_cache_stats()
        assert stats["total_entries"] == 2
        assert stats["active_entries"] == 1
        assert stats["expired_entries"] == 1


# ---------------------------------------------------------------------------
# get_pool_memory_stats
# ---------------------------------------------------------------------------


class TestGetPoolMemoryStats:
    @pytest.mark.asyncio
    async def test_empty_pools(self, aggregator: MemoryAggregator):
        mock_pm = MagicMock()
        mock_pm.list_pools = AsyncMock(return_value=[])
        result = await aggregator.get_pool_memory_stats(mock_pm)
        assert result == {}

    @pytest.mark.asyncio
    async def test_pool_with_memory(self, aggregator: MemoryAggregator):
        pool = AsyncMock()
        pool.collect_memory.return_value = [{"text": "m1"}, {"text": "m2"}]
        pool.status.return_value = MagicMock(value="running")
        pool.config = MagicMock(pool_type="mahavishnu")

        mock_pm = MagicMock()
        mock_pm.list_pools = AsyncMock(return_value=[{"pool_id": "p1"}])
        mock_pm._pools = {"p1": pool}

        result = await aggregator.get_pool_memory_stats(mock_pm)
        assert "p1" in result
        assert result["p1"]["memory_count"] == 2
        assert result["p1"]["pool_type"] == "mahavishnu"
        assert result["p1"]["status"] == "running"

    @pytest.mark.asyncio
    async def test_pool_collect_error(self, aggregator: MemoryAggregator):
        pool = AsyncMock()
        pool.collect_memory.side_effect = RuntimeError("error")

        mock_pm = MagicMock()
        mock_pm.list_pools = AsyncMock(return_value=[{"pool_id": "p1"}])
        mock_pm._pools = {"p1": pool}

        result = await aggregator.get_pool_memory_stats(mock_pm)
        assert result["p1"]["error"] == "error"
        assert result["p1"]["memory_count"] == 0

    @pytest.mark.asyncio
    async def test_pool_not_in_manager(self, aggregator: MemoryAggregator):
        mock_pm = MagicMock()
        mock_pm.list_pools = AsyncMock(return_value=[{"pool_id": "missing"}])
        mock_pm._pools = {}
        result = await aggregator.get_pool_memory_stats(mock_pm)
        assert result == {}

"""Integration tests for O(log n) heap-based pool routing."""

import time
from unittest.mock import MagicMock, patch

import pytest

from mahavishnu.pools import PoolConfig, PoolManager, PoolSelector


class TestHeapRoutingScalability:
    """Test O(log n) heap-based routing scalability."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_heap_routing_scalability_100_pools(self):
        """Test that heap routing scales well with 100 pools."""
        with patch("mahavishnu.core.app.TerminalManager"):
            from mahavishnu.mcp.protocols.message_bus import MessageBus

            pool_mgr = PoolManager(
                terminal_manager=MagicMock(),
                session_buddy_client=None,
                message_bus=MessageBus(),
            )

            # Spawn 100 pools with varying worker counts
            for i in range(100):
                mock_pool = MagicMock()
                mock_pool.pool_id = f"pool{i}"
                mock_pool.config = PoolConfig(
                    name=f"pool{i}",
                    pool_type="mahavishnu",
                    min_workers=i % 10,  # Varying worker counts
                    max_workers=(i % 10) * 2,
                )
                mock_pool._workers = {f"w{j}": f"w{j}" for j in range(i % 10)}

                async def mock_execute(task):
                    return {"pool_id": mock_pool.pool_id, "status": "completed"}

                mock_pool.execute_task = mock_execute
                pool_mgr._pools[f"pool{i}"] = mock_pool

                # Initialize heap tracking
                pool_mgr._pool_worker_counts[f"pool{i}"] = i % 10

            # Build heap to simulate real spawn behavior
            import heapq
            for pool_id, count in pool_mgr._pool_worker_counts.items():
                heapq.heappush(pool_mgr._worker_count_heap, (count, pool_id))

            # Measure routing performance
            start = time.time()
            for _ in range(1000):
                pool_id = pool_mgr._get_least_loaded_pool()
                assert pool_id is not None
            elapsed = time.time() - start

            # Should be very fast with O(log n) heap
            assert elapsed < 1.0, f"1000 route operations took {elapsed:.2f}s"

            print(f"Heap routing (100 pools): 1000 routes in {elapsed:.3f}s ({1000/elapsed:.0f} routes/sec)")

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_heap_routing_correctness(self):
        """Test that heap routing correctly identifies least-loaded pool."""
        with patch("mahavishnu.core.app.TerminalManager"):
            from mahavishnu.mcp.protocols.message_bus import MessageBus

            pool_mgr = PoolManager(
                terminal_manager=MagicMock(),
                session_buddy_client=None,
                message_bus=MessageBus(),
            )

            # Create pools with known worker counts
            worker_counts = [5, 2, 8, 1, 10]  # pool3 should be least loaded (1 worker)
            for i, count in enumerate(worker_counts):
                mock_pool = MagicMock()
                mock_pool.pool_id = f"pool{i}"
                mock_pool.config = PoolConfig(
                    name=f"pool{i}",
                    pool_type="mahavishnu",
                    min_workers=count,
                    max_workers=count * 2,
                )
                mock_pool._workers = {f"w{j}": f"w{j}" for j in range(count)}

                async def mock_execute(task):
                    return {"pool_id": mock_pool.pool_id, "status": "completed"}

                mock_pool.execute_task = mock_execute
                pool_mgr._pools[f"pool{i}"] = mock_pool
                pool_mgr._pool_worker_counts[f"pool{i}"] = count

            # Build heap
            import heapq
            for pool_id, count in pool_mgr._pool_worker_counts.items():
                heapq.heappush(pool_mgr._worker_count_heap, (count, pool_id))

            # Get least loaded pool
            least_loaded = pool_mgr._get_least_loaded_pool()

            # Should be pool3 (1 worker)
            assert least_loaded == "pool3", f"Expected pool3, got {least_loaded}"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_heap_lazy_deletion_stale_entries(self):
        """Test that heap properly handles stale entries from lazy deletion."""
        with patch("mahavishnu.core.app.TerminalManager"):
            from mahavishnu.mcp.protocols.message_bus import MessageBus

            pool_mgr = PoolManager(
                terminal_manager=MagicMock(),
                session_buddy_client=None,
                message_bus=MessageBus(),
            )

            # Create initial pools
            for i in range(3):
                mock_pool = MagicMock()
                mock_pool.pool_id = f"pool{i}"
                mock_pool.config = PoolConfig(
                    name=f"pool{i}",
                    pool_type="mahavishnu",
                    min_workers=5,
                    max_workers=10,
                )
                mock_pool._workers = {f"w{j}": f"w{j}" for j in range(5)}

                async def mock_execute(task):
                    return {"pool_id": mock_pool.pool_id, "status": "completed"}

                mock_pool.execute_task = mock_execute
                pool_mgr._pools[f"pool{i}"] = mock_pool
                pool_mgr._pool_worker_counts[f"pool{i}"] = 5

            # Build heap
            import heapq
            for pool_id, count in pool_mgr._pool_worker_counts.items():
                heapq.heappush(pool_mgr._worker_count_heap, (count, pool_id))

            # Simulate pool0 scaling up (add stale entry to heap)
            pool_mgr._pool_worker_counts["pool0"] = 10
            heapq.heappush(pool_mgr._worker_count_heap, (10, "pool0"))

            # Now heap has: (5, pool0)[stale], (5, pool1), (5, pool2), (10, pool0)[current]
            # _get_least_loaded_pool should skip stale entry and return pool1 or pool2
            least_loaded = pool_mgr._get_least_loaded_pool()

            # Should skip stale (5, pool0) and return pool1 or pool2
            assert least_loaded in ["pool1", "pool2"], f"Expected pool1 or pool2, got {least_loaded}"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_heap_closed_pool_cleanup(self):
        """Test that heap properly handles closed pools."""
        with patch("mahavishnu.core.app.TerminalManager"):
            from mahavishnu.mcp.protocols.message_bus import MessageBus

            pool_mgr = PoolManager(
                terminal_manager=MagicMock(),
                session_buddy_client=None,
                message_bus=MessageBus(),
            )

            # Create pools
            for i in range(3):
                mock_pool = MagicMock()
                mock_pool.pool_id = f"pool{i}"
                mock_pool.config = PoolConfig(
                    name=f"pool{i}",
                    pool_type="mahavishnu",
                    min_workers=5,
                    max_workers=10,
                )
                mock_pool._workers = {f"w{j}": f"w{j}" for j in range(5)}

                async def mock_stop():
                    pass

                mock_pool.stop = mock_stop
                pool_mgr._pools[f"pool{i}"] = mock_pool
                pool_mgr._pool_worker_counts[f"pool{i}"] = 5

            # Build heap
            import heapq
            for pool_id, count in pool_mgr._pool_worker_counts.items():
                heapq.heappush(pool_mgr._worker_count_heap, (count, pool_id))

            # Close pool0
            await pool_mgr.close_pool("pool0")

            # Heap still has (5, pool0) entry, but pool0 is closed
            # _get_least_loaded_pool should skip it and return pool1 or pool2
            least_loaded = pool_mgr._get_least_loaded_pool()

            assert least_loaded in ["pool1", "pool2"], f"Expected pool1 or pool2, got {least_loaded}"
            assert "pool0" not in pool_mgr._pools

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_heap_vs_linear_routing_performance(self):
        """Compare heap routing performance with old linear approach."""
        with patch("mahavishnu.core.app.TerminalManager"):
            from mahavishnu.mcp.protocols.message_bus import MessageBus

            # Create pool manager with heap
            pool_mgr = PoolManager(
                terminal_manager=MagicMock(),
                session_buddy_client=None,
                message_bus=MessageBus(),
            )

            # Create 50 pools
            for i in range(50):
                mock_pool = MagicMock()
                mock_pool.pool_id = f"pool{i}"
                mock_pool.config = PoolConfig(
                    name=f"pool{i}",
                    pool_type="mahavishnu",
                    min_workers=i % 10,
                    max_workers=(i % 10) * 2,
                )
                mock_pool._workers = {f"w{j}": f"w{j}" for j in range(i % 10)}

                async def mock_execute(task):
                    return {"pool_id": mock_pool.pool_id, "status": "completed"}

                mock_pool.execute_task = mock_execute
                pool_mgr._pools[f"pool{i}"] = mock_pool
                pool_mgr._pool_worker_counts[f"pool{i}"] = i % 10

            # Build heap
            import heapq
            for pool_id, count in pool_mgr._pool_worker_counts.items():
                heapq.heappush(pool_mgr._worker_count_heap, (count, pool_id))

            # Measure heap routing (O(log n))
            start = time.time()
            for _ in range(1000):
                pool_id = pool_mgr._get_least_loaded_pool()
                assert pool_id is not None
            heap_elapsed = time.time() - start

            # Measure linear routing (O(n))
            def route_linear():
                return min(
                    pool_mgr._pools.keys(),
                    key=lambda pid: len(pool_mgr._pools[pid]._workers),
                )

            start = time.time()
            for _ in range(1000):
                pool_id = route_linear()
            linear_elapsed = time.time() - start

            print(f"\nPerformance comparison (50 pools, 1000 routes):")
            print(f"  Heap (O(log n)):  {heap_elapsed:.4f}s ({1000/heap_elapsed:.0f} routes/sec)")
            print(f"  Linear (O(n)):    {linear_elapsed:.4f}s ({1000/linear_elapsed:.0f} routes/sec)")
            print(f"  Speedup:          {linear_elapsed/heap_elapsed:.2f}x")

            # Heap should be faster (allowing some margin for small test sizes)
            assert heap_elapsed < linear_elapsed * 1.5, "Heap routing should be faster than linear"


class TestLeastLoadedRouting:
    """Test least-loaded routing integration."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_route_least_loaded_integration(self):
        """Test full route_task with LEAST_LOADED selector."""
        with patch("mahavishnu.core.app.TerminalManager"):
            from mahavishnu.mcp.protocols.message_bus import MessageBus

            pool_mgr = PoolManager(
                terminal_manager=MagicMock(),
                session_buddy_client=None,
                message_bus=MessageBus(),
            )

            # Create pools with different worker counts
            worker_counts = [5, 2, 8]
            for i, count in enumerate(worker_counts):
                mock_pool = MagicMock()
                mock_pool.pool_id = f"pool{i}"
                mock_pool.config = PoolConfig(
                    name=f"pool{i}",
                    pool_type="mahavishnu",
                    min_workers=count,
                    max_workers=count * 2,
                )
                mock_pool._workers = {f"w{j}": f"w{j}" for j in range(count)}

                async def mock_execute(task):
                    return {"pool_id": mock_pool.pool_id, "status": "completed"}

                mock_pool.execute_task = mock_execute
                pool_mgr._pools[f"pool{i}"] = mock_pool
                pool_mgr._pool_worker_counts[f"pool{i}"] = count

            # Build heap
            import heapq
            for pool_id, count in pool_mgr._pool_worker_counts.items():
                heapq.heappush(pool_mgr._worker_count_heap, (count, pool_id))

            # Route task using least_loaded
            result = await pool_mgr.route_task(
                {"prompt": "Test"},
                pool_selector=PoolSelector.LEAST_LOADED,
            )

            # Should route to pool1 (2 workers - least loaded)
            assert result["pool_id"] == "pool1"

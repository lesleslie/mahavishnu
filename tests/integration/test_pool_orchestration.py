"""Integration tests for pool orchestration and multi-pool scenarios."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.app import MahavishnuApp
from mahavishnu.pools import PoolConfig, PoolManager, PoolSelector
from mahavishnu.pools.mahavishnu_pool import MahavishnuPool


class TestMultiPoolExecution:
    """Test task execution across multiple pools."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_execute_across_three_pools(self):
        """Test executing tasks across three different pool types."""
        # Create app with pool management
        with patch("mahavishnu.core.app.TerminalManager") as mock_tm_cls:
            mock_tm = MagicMock()
            mock_tm_cls.create.return_value = mock_tm
            mock_tm_cls.return_value = mock_tm

            app = MahavishnuApp()

            # Manually initialize pool manager (bypass terminal requirement for test)
            from mahavishnu.mcp.protocols.message_bus import MessageBus

            message_bus = MessageBus()
            app.pool_manager = PoolManager(
                terminal_manager=mock_tm,
                session_buddy_client=app.session_buddy,
                message_bus=message_bus,
            )

            # Create mock pools
            pools = []
            for i in range(3):
                config = PoolConfig(
                    name=f"pool{i}",
                    pool_type="mahavishnu",
                    min_workers=1,
                    max_workers=2,
                )

                # Mock the actual pool creation
                with patch("mahavishnu.pools.manager.MahavishnuPool") as MockPool:
                    mock_pool = MagicMock()
                    mock_pool.pool_id = f"pool{i}"
                    mock_pool.config = config
                    mock_pool._workers = {f"w{j}": f"w{j}" for j in range(2)}

                    async def mock_execute(task):
                        return {
                            "pool_id": mock_pool.pool_id,
                            "worker_id": "w0",
                            "status": "completed",
                            "output": f"Executed on {mock_pool.pool_id}",
                        }

                    mock_pool.execute_task = mock_execute
                    app.pool_manager._pools[f"pool{i}"] = mock_pool
                    pools.append(mock_pool)

            # Execute task on each pool
            results = []
            for pool_id in ["pool0", "pool1", "pool2"]:
                result = await app.pool_manager.execute_on_pool(
                    pool_id,
                    {"prompt": f"Test task for {pool_id}"},
                )
                results.append(result)

            # Verify all tasks completed
            assert len(results) == 3
            for result in results:
                assert result["status"] == "completed"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_batch_execution_across_pools(self):
        """Test batch task execution distributed across pools."""
        with patch("mahavishnu.core.app.TerminalManager"):
            app = MahavishnuApp()

            from mahavishnu.mcp.protocols.message_bus import MessageBus

            message_bus = MessageBus()
            app.pool_manager = PoolManager(
                terminal_manager=MagicMock(),
                session_buddy_client=app.session_buddy,
                message_bus=message_bus,
            )

            # Create two pools
            for i in range(2):
                mock_pool = MagicMock()
                mock_pool.pool_id = f"pool{i}"
                mock_pool.config = PoolConfig(name=f"pool{i}", pool_type="mahavishnu")
                mock_pool._workers = {f"w{j}": f"w{j}" for j in range(3)}

                async def mock_batch(tasks):
                    return {
                        str(idx): {
                            "pool_id": mock_pool.pool_id,
                            "status": "completed",
                        }
                        for idx in range(len(tasks))
                    }

                mock_pool.execute_batch = mock_batch
                app.pool_manager._pools[f"pool{i}"] = mock_pool

            # Execute batch on pool0
            tasks = [{"prompt": f"Task {i}"} for i in range(5)]
            result = await app.pool_manager._pools["pool0"].execute_batch(tasks)

            assert len(result) == 5
            assert all(r["status"] == "completed" for r in result.values())


class TestPoolRouting:
    """Test automatic pool routing strategies."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_least_loaded_routing(self):
        """Test LEAST_LOADED pool selector routes to pool with fewest workers."""
        with patch("mahavishnu.core.app.TerminalManager"):
            app = MahavishnuApp()

            from mahavishnu.mcp.protocols.message_bus import MessageBus

            message_bus = MessageBus()
            app.pool_manager = PoolManager(
                terminal_manager=MagicMock(),
                session_buddy_client=app.session_buddy,
                message_bus=message_bus,
            )

            # Create pools with different worker counts
            worker_counts = [5, 2, 8]  # pool1 has least workers
            for i, count in enumerate(worker_counts):
                mock_pool = MagicMock()
                mock_pool.pool_id = f"pool{i}"
                mock_pool.config = PoolConfig(name=f"pool{i}", pool_type="mahavishnu")
                mock_pool._workers = {f"w{j}": f"w{j}" for j in range(count)}

                async def mock_execute(task):
                    return {"pool_id": mock_pool.pool_id, "status": "completed"}

                mock_pool.execute_task = mock_execute
                app.pool_manager._pools[f"pool{i}"] = mock_pool

            # Route with least_loaded strategy
            result = await app.pool_manager.route_task(
                {"prompt": "Test"},
                pool_selector=PoolSelector.LEAST_LOADED,
            )

            # Should route to pool1 (2 workers)
            assert result["pool_id"] == "pool1"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_round_robin_routing(self):
        """Test ROUND_ROBIN pool selector distributes evenly."""
        with patch("mahavishnu.core.app.TerminalManager"):
            app = MahavishnuApp()

            from mahavishnu.mcp.protocols.message_bus import MessageBus

            message_bus = MessageBus()
            app.pool_manager = PoolManager(
                terminal_manager=MagicMock(),
                session_buddy_client=app.session_buddy,
                message_bus=message_bus,
            )

            # Create three pools
            for i in range(3):
                mock_pool = MagicMock()
                mock_pool.pool_id = f"pool{i}"
                mock_pool.config = PoolConfig(name=f"pool{i}", pool_type="mahavishnu")
                mock_pool._workers = {f"w{j}": f"w{j}" for j in range(2)}

                async def mock_execute(task):
                    return {"pool_id": mock_pool.pool_id, "status": "completed"}

                mock_pool.execute_task = mock_execute
                app.pool_manager._pools[f"pool{i}"] = mock_pool

            # Route multiple tasks
            pool_ids = []
            for _ in range(6):
                result = await app.pool_manager.route_task(
                    {"prompt": "Test"},
                    pool_selector=PoolSelector.ROUND_ROBIN,
                )
                pool_ids.append(result["pool_id"])

            # Should distribute evenly: 0, 1, 2, 0, 1, 2
            expected = ["pool0", "pool1", "pool2", "pool0", "pool1", "pool2"]
            assert pool_ids == expected

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_affinity_routing(self):
        """Test AFFINITY pool selector routes to specific pool."""
        with patch("mahavishnu.core.app.TerminalManager"):
            app = MahavishnuApp()

            from mahavishnu.mcp.protocols.message_bus import MessageBus

            message_bus = MessageBus()
            app.pool_manager = PoolManager(
                terminal_manager=MagicMock(),
                session_buddy_client=app.session_buddy,
                message_bus=message_bus,
            )

            # Create pools
            for i in range(3):
                mock_pool = MagicMock()
                mock_pool.pool_id = f"pool{i}"
                mock_pool.config = PoolConfig(name=f"pool{i}", pool_type="mahavishnu")
                mock_pool._workers = {f"w{j}": f"w{j}"}

                async def mock_execute(task):
                    return {"pool_id": mock_pool.pool_id, "status": "completed"}

                mock_pool.execute_task = mock_execute
                app.pool_manager._pools[f"pool{i}"] = mock_pool

            # Route with affinity to pool1
            result = await app.pool_manager.route_task(
                {"prompt": "Test"},
                pool_selector=PoolSelector.AFFINITY,
                pool_affinity="pool1",
            )

            # Should always route to pool1
            assert result["pool_id"] == "pool1"


class TestPoolScaling:
    """Test dynamic pool scaling."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_scale_pool_up(self):
        """Test scaling pool up to more workers."""
        with patch("mahavishnu.core.app.TerminalManager"):
            app = MahavishnuApp()

            from mahavishnu.mcp.protocols.message_bus import MessageBus

            message_bus = MessageBus()
            app.pool_manager = PoolManager(
                terminal_manager=MagicMock(),
                session_buddy_client=app.session_buddy,
                message_bus=message_bus,
            )

            # Create pool with 2 workers
            mock_pool = MagicMock()
            mock_pool.pool_id = "test_pool"
            mock_pool.config = PoolConfig(
                name="test",
                pool_type="mahavishnu",
                min_workers=1,
                max_workers=10,
            )
            mock_pool._workers = {f"w{i}": f"w{i}" for i in range(2)}

            scale_called = []

            async def mock_scale(target):
                scale_called.append(target)
                # Simulate scaling
                current = len(mock_pool._workers)
                if target > current:
                    for i in range(current, target):
                        mock_pool._workers[f"w{i}"] = f"w{i}"

            mock_pool.scale = mock_scale
            app.pool_manager._pools["test_pool"] = mock_pool

            # Scale up to 5 workers
            await mock_pool.scale(5)

            assert scale_called[0] == 5
            assert len(mock_pool._workers) == 5

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_scale_pool_down(self):
        """Test scaling pool down to fewer workers."""
        with patch("mahavishnu.core.app.TerminalManager"):
            app = MahavishnuApp()

            from mahavishnu.mcp.protocols.message_bus import MessageBus

            message_bus = MessageBus()
            app.pool_manager = PoolManager(
                terminal_manager=MagicMock(),
                session_buddy_client=app.session_buddy,
                message_bus=message_bus,
            )

            # Create pool with 10 workers
            mock_pool = MagicMock()
            mock_pool.pool_id = "test_pool"
            mock_pool.config = PoolConfig(
                name="test",
                pool_type="mahavishnu",
                min_workers=1,
                max_workers=10,
            )
            mock_pool._workers = {f"w{i}": f"w{i}" for i in range(10)}

            scale_called = []

            async def mock_scale(target):
                scale_called.append(target)
                # Simulate scaling down
                current = len(mock_pool._workers)
                if target < current:
                    workers_to_remove = list(mock_pool._workers.keys())[target:]
                    for wid in workers_to_remove:
                        del mock_pool._workers[wid]

            mock_pool.scale = mock_scale
            app.pool_manager._pools["test_pool"] = mock_pool

            # Scale down to 3 workers
            await mock_pool.scale(3)

            assert scale_called[0] == 3
            assert len(mock_pool._workers) == 3


class TestSessionBuddyDelegation:
    """Test Session-Buddy delegated pool execution."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_session_buddy_pool_spawn(self):
        """Test spawning Session-Buddy delegated pool."""
        # Mock Session-Buddy MCP client
        with patch("mahavishnu.pools.session_buddy_pool.httpx.AsyncClient") as mock_httpx:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "result": ["worker_1", "worker_2", "worker_3"]
            }
            mock_httpx.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            from mahavishnu.pools import PoolConfig
            from mahavishnu.pools.session_buddy_pool import SessionBuddyPool

            config = PoolConfig(
                name="delegated",
                pool_type="session-buddy",
            )

            pool = SessionBuddyPool(config)
            pool_id = await pool.start()

            assert pool._status.value in ["running", "initializing"]
            assert len(pool._workers) == 3

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_session_buddy_execute_task(self):
        """Test executing task via Session-Buddy delegation."""
        with patch("mahavishnu.pools.session_buddy_pool.httpx.AsyncClient") as mock_httpx:
            # Mock spawn
            spawn_response = MagicMock()
            spawn_response.status_code = 200
            spawn_response.json.return_value = {
                "result": ["worker_1", "worker_2", "worker_3"]
            }

            # Mock execute
            execute_response = MagicMock()
            execute_response.status_code = 200
            execute_response.json.return_value = {
                "result": {
                    "status": "completed",
                    "output": "Task completed via Session-Buddy",
                }
            }

            post_mock = AsyncMock()
            post_mock.side_effect = [spawn_response, execute_response]
            mock_httpx.return_value.__aenter__.return_value.post = post_mock

            from mahavishnu.pools import PoolConfig
            from mahavishnu.pools.session_buddy_pool import SessionBuddyPool

            config = PoolConfig(
                name="delegated",
                pool_type="session-buddy",
            )

            pool = SessionBuddyPool(config)
            await pool.start()

            # Execute task
            result = await pool.execute_task({"prompt": "Test task"})

            assert result["status"] == "completed"
            assert "output" in result


class TestMemoryAggregation:
    """Test memory aggregation across pools."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_collect_memory_from_pools(self):
        """Test collecting memory from multiple pools."""
        with patch("mahavishnu.core.app.TerminalManager"):
            app = MahavishnuApp()

            from mahavishnu.mcp.protocols.message_bus import MessageBus

            message_bus = MessageBus()
            app.pool_manager = PoolManager(
                terminal_manager=MagicMock(),
                session_buddy_client=app.session_buddy,
                message_bus=message_bus,
            )

            # Create pools with mock memory
            for i in range(3):
                mock_pool = MagicMock()
                mock_pool.pool_id = f"pool{i}"
                mock_pool.config = PoolConfig(name=f"pool{i}", pool_type="mahavishnu")

                async def mock_collect():
                    return [
                        {
                            "content": f"Memory from pool{i}",
                            "metadata": {"pool_id": f"pool{i}", "timestamp": 1234567890.0},
                        }
                    ]

                mock_pool.collect_memory = mock_collect
                app.pool_manager._pools[f"pool{i}"] = mock_pool

            # Collect memory from all pools
            memory = await app.pool_manager.aggregate_results()

            assert len(memory) == 3
            assert all("memory_count" in v for v in memory.values())

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_cross_pool_search(self):
        """Test searching across all pools via Session-Buddy."""
        with patch("mahavishnu.pools.memory_aggregator.httpx.AsyncClient") as mock_httpx:
            # Mock search response
            search_response = MagicMock()
            search_response.status_code = 200
            search_response.json.return_value = {
                "result": {
                    "conversations": [
                        {"content": "Result 1", "metadata": {"pool_id": "pool0"}},
                        {"content": "Result 2", "metadata": {"pool_id": "pool1"}},
                    ]
                }
            }

            mock_httpx.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=search_response
            )

            from mahavishnu.pools.memory_aggregator import MemoryAggregator

            aggregator = MemoryAggregator()

            # Create mock pool manager
            pool_mgr = MagicMock()
            pool_mgr._pools = {}

            results = await aggregator.cross_pool_search(
                query="test query",
                pool_manager=pool_mgr,
                limit=10,
            )

            assert len(results) == 2


class TestConcurrentPoolCollection:
    """Test concurrent pool collection performance improvements."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.slow
    async def test_concurrent_pool_list_performance(self):
        """Test that list_pools collects concurrently with 10x improvement."""
        from mahavishnu.mcp.protocols.message_bus import MessageBus
        from mahavishnu.pools.base import PoolStatus

        pool_manager = PoolManager(
            terminal_manager=MagicMock(),
            message_bus=MessageBus(),
        )

        # Create 10 mock pools with simulated delay
        async def slow_status():
            """Simulate 0.1s delay per pool status check."""
            await asyncio.sleep(0.1)
            return PoolStatus.RUNNING

        for i in range(10):
            mock_pool = MagicMock()
            mock_pool.pool_id = f"pool{i}"
            mock_pool.config = PoolConfig(
                name=f"pool{i}",
                pool_type="mahavishnu",
                min_workers=1,
                max_workers=5,
            )
            mock_pool._workers = {f"w{j}": f"w{j}" for j in range(2)}
            mock_pool.status = slow_status
            pool_manager._pools[f"pool{i}"] = mock_pool

        # Measure concurrent collection time
        start = time.time()
        pools_info = await pool_manager.list_pools()
        elapsed = time.time() - start

        # With 10 pools taking 0.1s each:
        # Sequential: 10 * 0.1 = 1.0s
        # Concurrent: max(0.1) = ~0.1-0.2s
        # We'll be lenient and expect < 0.5s (5x improvement)
        assert elapsed < 0.5, f"Pool collection took {elapsed:.2f}s, expected < 0.5s"
        assert len(pools_info) == 10

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.slow
    async def test_concurrent_aggregate_results_performance(self):
        """Test that aggregate_results collects concurrently with 10x improvement."""
        from mahavishnu.mcp.protocols.message_bus import MessageBus
        from mahavishnu.pools.base import PoolStatus

        pool_manager = PoolManager(
            terminal_manager=MagicMock(),
            message_bus=MessageBus(),
        )

        # Create 10 mock pools with simulated delay
        async def slow_collect():
            """Simulate 0.1s delay per pool memory collection."""
            await asyncio.sleep(0.1)
            return []

        async def slow_status():
            """Simulate 0.1s delay per pool status check."""
            await asyncio.sleep(0.1)
            return PoolStatus.RUNNING

        for i in range(10):
            mock_pool = MagicMock()
            mock_pool.pool_id = f"pool{i}"
            mock_pool.config = PoolConfig(
                name=f"pool{i}",
                pool_type="mahavishnu",
            )
            mock_pool.collect_memory = slow_collect
            mock_pool.status = slow_status
            pool_manager._pools[f"pool{i}"] = mock_pool

        # Measure concurrent collection time
        start = time.time()
        results = await pool_manager.aggregate_results()
        elapsed = time.time() - start

        # With 10 pools taking 0.2s each (collect + status):
        # Sequential: 10 * 0.2 = 2.0s
        # Concurrent: max(0.2) = ~0.2-0.3s
        # We'll be lenient and expect < 0.8s (5x improvement)
        assert elapsed < 0.8, f"Pool aggregation took {elapsed:.2f}s, expected < 0.8s"
        assert len(results) == 10

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.slow
    async def test_concurrent_health_check_performance(self):
        """Test that health_check uses concurrent list_pools."""
        from mahavishnu.mcp.protocols.message_bus import MessageBus
        from mahavishnu.pools.base import PoolStatus

        pool_manager = PoolManager(
            terminal_manager=MagicMock(),
            message_bus=MessageBus(),
        )

        # Create 10 mock pools with simulated delay
        async def slow_status():
            """Simulate 0.1s delay per pool status check."""
            await asyncio.sleep(0.1)
            return PoolStatus.HEALTHY

        for i in range(10):
            mock_pool = MagicMock()
            mock_pool.pool_id = f"pool{i}"
            mock_pool.config = PoolConfig(
                name=f"pool{i}",
                pool_type="mahavishnu",
            )
            mock_pool._workers = {f"w{j}": f"w{j}" for j in range(2)}
            mock_pool.status = slow_status
            pool_manager._pools[f"pool{i}"] = mock_pool

        # Measure concurrent health check time
        start = time.time()
        health = await pool_manager.health_check()
        elapsed = time.time() - start

        # Should complete in < 0.5s due to concurrent collection
        assert elapsed < 0.5, f"Health check took {elapsed:.2f}s, expected < 0.5s"
        assert health["status"] == "healthy"
        assert health["pools_active"] == 10

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_concurrent_collection_with_errors(self):
        """Test that concurrent collection handles individual pool errors gracefully."""
        from mahavishnu.mcp.protocols.message_bus import MessageBus
        from mahavishnu.pools.base import PoolStatus

        pool_manager = PoolManager(
            terminal_manager=MagicMock(),
            message_bus=MessageBus(),
        )

        # Create mock pools where some fail
        call_count = [0]

        async def failing_status():
            """Every third pool fails."""
            call_count[0] += 1
            if call_count[0] % 3 == 0:
                raise RuntimeError(f"Pool {call_count[0]} failed")
            return PoolStatus.RUNNING

        for i in range(9):
            mock_pool = MagicMock()
            mock_pool.pool_id = f"pool{i}"
            mock_pool.config = PoolConfig(
                name=f"pool{i}",
                pool_type="mahavishnu",
            )
            mock_pool._workers = {}
            mock_pool.status = failing_status
            pool_manager._pools[f"pool{i}"] = mock_pool

        # Should collect successfully despite 3 failing pools
        pools_info = await pool_manager.list_pools()

        # 6 pools succeed, 3 fail (exceptions filtered out)
        assert len(pools_info) == 6

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_concurrent_aggregate_with_partial_failures(self):
        """Test that aggregate_results continues despite individual pool failures."""
        from mahavishnu.mcp.protocols.message_bus import MessageBus
        from mahavishnu.pools.base import PoolStatus

        pool_manager = PoolManager(
            terminal_manager=MagicMock(),
            message_bus=MessageBus(),
        )

        # Create pools where some fail during collection
        # Use factory function to properly capture pool_id in closure
        def make_collect_mock(pool_id):
            """Factory to create collect mock with proper closure capture."""
            async def collect_mock():
                if pool_id in ["pool2", "pool5"]:
                    raise RuntimeError(f"Pool {pool_id} collection failed")
                return [
                    {"content": f"Memory from {pool_id}", "metadata": {}}
                ]
            return collect_mock

        async def always_healthy():
            return PoolStatus.RUNNING

        for i in range(7):
            mock_pool = MagicMock()
            pool_id = f"pool{i}"
            mock_pool.pool_id = pool_id
            mock_pool.config = PoolConfig(
                name=pool_id,
                pool_type="mahavishnu",
            )

            mock_pool.collect_memory = make_collect_mock(pool_id)
            mock_pool.status = always_healthy
            pool_manager._pools[pool_id] = mock_pool

        # Should aggregate successfully despite 2 failing pools
        results = await pool_manager.aggregate_results()

        # 5 pools succeed, 2 fail (but errors are logged, not raised)
        assert len(results) == 5
        assert "pool2" not in results
        assert "pool5" not in results

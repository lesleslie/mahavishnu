"""The pool listing has to say which substrate each pool runs.

``pool_route_execute`` is prompt-shaped, but not every worker substrate
has a prompt channel. A SHELL-runtime worker (``terminal-claude``) reads
a prompt; an isolated worker (``shepherd``) does not -- the pool turns the
prompt into a shell command and the exec guard refuses it with
*"Command '...' is not in the allowed list"*.

A caller that cannot see the substrate cannot tell which pools can carry a
prompt, so the listing carries ``worker_type``. This is the same class of
gap as ``supports_working_directory``: the routing decision needs a fact
the listing has to carry.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.pools.base import PoolConfig
from mahavishnu.pools.manager import PoolManager


def _manager(config: object) -> PoolManager:
    """A manager holding one pool with the given config stand-in."""
    manager = PoolManager(terminal_manager=MagicMock(), message_bus=MagicMock())
    pool = MagicMock()
    pool.config = config
    pool._workers = []
    pool.status = AsyncMock(return_value=SimpleNamespace(value="running"))
    manager._pools["pool-1"] = pool
    return manager


class TestTheListingCarriesTheWorkerType:
    @pytest.mark.asyncio
    async def test_a_shell_runtime_worker_is_reported(self) -> None:
        """A pool that can carry a prompt says so."""
        manager = _manager(
            PoolConfig(
                name="pool-1", pool_type="mahavishnu", worker_type="terminal-claude"
            )
        )

        listed = await manager.list_pools()

        assert listed[0]["worker_type"] == "terminal-claude"

    @pytest.mark.asyncio
    async def test_an_isolated_worker_is_reported(self) -> None:
        """A pool that can only carry a command says that too."""
        manager = _manager(
            PoolConfig(name="pool-1", pool_type="mahavishnu", worker_type="shepherd")
        )

        listed = await manager.list_pools()

        assert listed[0]["worker_type"] == "shepherd"

    @pytest.mark.asyncio
    async def test_a_config_without_the_attribute_reports_empty(self) -> None:
        """A config that predates the field reports nothing, not a crash."""
        manager = _manager(
            SimpleNamespace(
                pool_type="mahavishnu",
                name="pool-1",
                min_workers=1,
                max_workers=10,
            )
        )

        listed = await manager.list_pools()

        assert listed[0]["worker_type"] == ""

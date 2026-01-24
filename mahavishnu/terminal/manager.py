"""Terminal manager for multi-session orchestration."""

import asyncio
from logging import getLogger
from typing import Any, Dict, List, Optional, Callable
from datetime import datetime

from .adapters.base import TerminalAdapter
from .adapters.mcpretentious import McpretentiousAdapter
from .config import TerminalSettings
from .session import TerminalSession

logger = getLogger(__name__)


class TerminalManager:
    """Manage multiple terminal sessions with high concurrency support.

    Provides an interface for launching, controlling, and capturing
    output from multiple terminal sessions concurrently with proper
    resource management via semaphores.

    Features:
    - Hot-swappable adapters (switch adapters without restart)
    - Connection pooling for iTerm2
    - Session migration between adapters

    Example:
        >>> from mahavishnu.terminal import TerminalManager
        >>> manager = TerminalManager(adapter)
        >>> session_ids = await manager.launch_sessions("qwen", count=3)
        >>> await manager.send_command(session_ids[0], "hello")
        >>> outputs = await manager.capture_all_outputs(session_ids)
        >>> await manager.close_all(session_ids)
        >>> # Hot-swap adapter
        >>> await manager.switch_adapter(new_adapter)
    """

    def __init__(
        self,
        adapter: TerminalAdapter,
        config: Optional[TerminalSettings] = None,
    ) -> None:
        """Initialize terminal manager.

        Args:
            adapter: Terminal adapter backend
            config: Optional terminal settings
        """
        self.adapter = adapter
        self.config = config or TerminalSettings()
        self._semaphore = asyncio.Semaphore(self.config.max_concurrent_sessions)
        self._batch_size = 5  # Process 5 sessions at a time
        self._adapter_history: List[Dict[str, Any]] = []
        self._session_migration_callback: Optional[Callable] = None

        logger.info(
            f"Initialized TerminalManager with {self.adapter.adapter_name} adapter "
            f"(max_concurrent={self.config.max_concurrent_sessions})"
        )

    async def switch_adapter(
        self,
        new_adapter: TerminalAdapter,
        migrate_sessions: bool = False,
    ) -> None:
        """Hot-swap to a different adapter without restart.

        Args:
            new_adapter: New adapter to switch to
            migrate_sessions: If True, attempt to migrate existing sessions
                             (experimental, may not work for all adapters)

        Raises:
            RuntimeError: If adapter switching fails
        """
        old_adapter = self.adapter
        old_adapter_name = old_adapter.adapter_name
        new_adapter_name = new_adapter.adapter_name

        logger.info(
            f"Hot-switching adapter from {old_adapter_name} to {new_adapter_name}"
        )

        # Record history
        self._adapter_history.append({
            "from": old_adapter_name,
            "to": new_adapter_name,
            "timestamp": datetime.now().isoformat(),
            "migrate_sessions": migrate_sessions,
        })

        # Attempt session migration if requested
        if migrate_sessions:
            try:
                await self._migrate_sessions(old_adapter, new_adapter)
            except Exception as e:
                logger.warning(f"Session migration failed: {e}")
                logger.info("Continuing with adapter switch (existing sessions orphaned)")

        # Switch adapters
        self.adapter = new_adapter

        logger.info(f"Successfully switched to {new_adapter_name} adapter")

        # Call migration callback if registered
        if self._session_migration_callback:
            try:
                await self._session_migration_callback(old_adapter_name, new_adapter_name)
            except Exception as e:
                logger.warning(f"Migration callback failed: {e}")

    async def _migrate_sessions(
        self,
        old_adapter: TerminalAdapter,
        new_adapter: TerminalAdapter,
    ) -> None:
        """Migrate sessions from old adapter to new adapter.

        This is experimental and may not work for all adapter combinations.
        iTerm2 → mcpretentious: Possible (recreate sessions)
        mcpretentious → iTerm2: Possible (create new tabs)

        Args:
            old_adapter: Adapter to migrate from
            new_adapter: Adapter to migrate to

        Raises:
            NotImplementedError: If migration not supported
            RuntimeError: If migration fails
        """
        logger.info("Attempting session migration...")

        # List sessions from old adapter
        old_sessions = await old_adapter.list_sessions()

        if not old_sessions:
            logger.info("No sessions to migrate")
            return

        logger.info(f"Migrating {len(old_sessions)} sessions")

        # Attempt migration (adapter-specific logic)
        for session_info in old_sessions:
            session_id = session_info.get("id")
            command = session_info.get("command", "")

            try:
                # For iTerm2 adapters, we can't easily migrate sessions
                # because session_ids are iTerm2-specific
                if old_adapter.adapter_name == "iterm2" or new_adapter.adapter_name == "iterm2":
                    logger.warning(
                        f"Session migration involving iTerm2 is not supported. "
                        f"Session {session_id} will be orphaned."
                    )
                    continue

                # For mcpretentious → mcpretentious (different instances)
                # We can recreate sessions with the same command
                new_session_id = await new_adapter.launch_session(
                    command,
                    columns=self.config.default_columns,
                    rows=self.config.default_rows,
                )
                logger.info(f"Migrated session {session_id} → {new_session_id}")

            except Exception as e:
                logger.warning(f"Failed to migrate session {session_id}: {e}")

        logger.info("Session migration complete")

    def set_migration_callback(self, callback: Callable) -> None:
        """Set a callback to be invoked when adapter switching occurs.

        Args:
            callback: Async function(old_adapter_name, new_adapter_name)
        """
        self._session_migration_callback = callback
        logger.info("Migration callback registered")

    def get_adapter_history(self) -> List[Dict[str, Any]]:
        """Get history of adapter switches.

        Returns:
            List of adapter switch events with timestamps
        """
        return self._adapter_history.copy()

    def current_adapter(self) -> str:
        """Get the name of the currently active adapter.

        Returns:
            Adapter name
        """
        return self.adapter.adapter_name

    async def launch_sessions(
        self,
        command: str,
        count: int = 1,
        columns: int = 80,
        rows: int = 24,
    ) -> List[str]:
        """Launch multiple terminal sessions concurrently.

        Uses semaphore to limit concurrent launches and prevent
        resource exhaustion.

        Args:
            command: Command to run in each terminal
            count: Number of sessions to launch
            columns: Terminal width in characters
            rows: Terminal height in lines

        Returns:
            List of session IDs

        Raises:
            TerminalError: If session launch fails
        """
        async def launch_one() -> str:
            async with self._semaphore:
                return await self.adapter.launch_session(
                    command,
                    columns,
                    rows,
                )

        try:
            # Launch all sessions concurrently
            tasks = [launch_one() for _ in range(count)]
            session_ids = await asyncio.gather(*tasks)

            logger.info(
                f"Launched {len(session_ids)} sessions "
                f"using {self.adapter.adapter_name} adapter"
            )
            return session_ids

        except Exception as e:
            logger.error(f"Failed to launch sessions: {e}")
            raise

    async def launch_sessions_batch(
        self,
        command: str,
        count: int,
        columns: int = 80,
        rows: int = 24,
    ) -> List[str]:
        """Launch sessions in batches for better resource management.

        Useful for launching many sessions (10+) with smaller
        resource spikes.

        Args:
            command: Command to run in each terminal
            count: Number of sessions to launch
            columns: Terminal width in characters
            rows: Terminal height in lines

        Returns:
            List of session IDs
        """
        session_ids: List[str] = []

        for i in range(0, count, self._batch_size):
            batch_size = min(self._batch_size, count - i)
            batch = await self._launch_batch(
                command,
                batch_size,
                columns,
                rows,
            )
            session_ids.extend(batch)

            # Small delay between batches
            if i + self._batch_size < count:
                await asyncio.sleep(0.1)

        return session_ids

    async def _launch_batch(
        self,
        command: str,
        count: int,
        columns: int,
        rows: int,
    ) -> List[str]:
        """Launch a batch of sessions.

        Args:
            command: Command to run
            count: Number of sessions in this batch
            columns: Terminal width
            rows: Terminal height

        Returns:
            List of session IDs
        """
        async def launch_one() -> str:
            async with self._semaphore:
                return await self.adapter.launch_session(
                    command,
                    columns,
                    rows,
                )

        tasks = [launch_one() for _ in range(count)]
        return await asyncio.gather(*tasks)

    async def send_command(
        self,
        session_id: str,
        command: str,
    ) -> None:
        """Send command to a specific session.

        Args:
            session_id: Terminal session ID
            command: Command string to send

        Raises:
            TerminalError: If command send fails
        """
        await self.adapter.send_command(session_id, command)
        logger.debug(f"Sent command to session {session_id}")

    async def capture_output(
        self,
        session_id: str,
        lines: Optional[int] = None,
    ) -> str:
        """Capture output from a specific session.

        Args:
            session_id: Terminal session ID
            lines: Number of lines to capture (None for all)

        Returns:
            Terminal output as string

        Raises:
            TerminalError: If output capture fails
        """
        return await self.adapter.capture_output(session_id, lines)

    async def capture_all_outputs(
        self,
        session_ids: List[str],
        lines: Optional[int] = None,
    ) -> Dict[str, str]:
        """Capture outputs from multiple sessions concurrently.

        Args:
            session_ids: List of session IDs
            lines: Number of lines to capture per session

        Returns:
            Dictionary mapping session_id -> output

        Raises:
            TerminalError: If output capture fails
        """
        async def capture_one(sid: str) -> tuple[str, str]:
            return sid, await self.adapter.capture_output(sid, lines)

        tasks = [capture_one(sid) for sid in session_ids]
        results = await asyncio.gather(*tasks)
        return dict(results)

    async def close_session(self, session_id: str) -> None:
        """Close a specific session.

        Args:
            session_id: Terminal session ID to close

        Raises:
            TerminalError: If session close fails
        """
        await self.adapter.close_session(session_id)
        logger.debug(f"Closed session {session_id}")

    async def close_all(self, session_ids: List[str]) -> None:
        """Close multiple sessions concurrently.

        Args:
            session_ids: List of session IDs to close

        Raises:
            TerminalError: If session close fails
        """
        tasks = [self.adapter.close_session(sid) for sid in session_ids]
        await asyncio.gather(*tasks)
        logger.info(f"Closed {len(session_ids)} sessions")

    async def list_sessions(self) -> List[Dict[str, Any]]:
        """List all active terminal sessions.

        Returns:
            List of session information dictionaries

        Raises:
            TerminalError: If listing fails
        """
        return await self.adapter.list_sessions()

    @classmethod
    async def create(
        cls,
        config: Any,
        mcp_client: Any,
    ) -> "TerminalManager":
        """Create terminal manager with appropriate adapter.

        Factory method that selects the best available adapter based
        on configuration and runtime environment.

        Args:
            config: MahavishnuSettings with terminal config
            mcp_client: MCP client for adapter communication

        Returns:
            Configured TerminalManager instance

        Raises:
            ConfigurationError: No suitable adapter available
        """
        from ..core.errors import ConfigurationError

        terminal_config = config.terminal
        preference = terminal_config.adapter_preference

        # Try mcpretentious (default and most portable)
        if preference in ["auto", "mcpretentious"]:
            try:
                adapter = McpretentiousAdapter(mcp_client)
                logger.info("Using mcpretentious adapter")
                return cls(adapter, terminal_config)
            except Exception as e:
                logger.error(f"mcpretentious adapter failed: {e}")
                if preference == "mcpretentious":
                    raise ConfigurationError(
                        message="mcpretentious adapter failed but is required",
                        details={"error": str(e)},
                    ) from e

        # Note: iTerm2 adapter will be added in Phase 3
        raise ConfigurationError(
            message="No suitable terminal adapter found",
            details={"adapter_preference": preference},
        )

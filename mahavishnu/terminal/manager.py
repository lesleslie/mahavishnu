"""Terminal manager for multi-session orchestration."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from logging import getLogger
from typing import TYPE_CHECKING, Any
import warnings

from oneiric.adapters.llm.bifrost import RouteKind, get_router

from .config import TerminalSettings

if TYPE_CHECKING:
    from collections.abc import Callable

    from .adapters.base import TerminalAdapter

logger = getLogger(__name__)


def _resolve_worker_env(worker_type: str) -> dict[str, str]:
    """Build the per-worker env-var dict for Bifrost-wired CLI workers.

    Phase 3 (REQ-BIFROST-006) wiring — URL-rewriter via the oneiric
    ``BifrostLLMRouter`` (per the bifrost plan §4.7, the URL
    rewriter was chosen over the chain-member pivot because
    Bifrost is a transparent proxy and putting it in the chain
    would compound retry/circuit-breaker logic):

    - When the router is disabled (``enabled=False``), return an
      empty dict (the cloud tier is bypassed; local CLI workers
      see no env override). This is the structural dead-flag fix
      (REQ-BIFROST-003): no caller can produce inert wiring because
      the conditional collapses to ``None`` — not to a flag.
    - For ``terminal-claude`` workers when the router is routed
      for ``RouteKind.CLAUDE_ROUTE``: inject
      ``ANTHROPIC_BASE_URL=<router.anthropic_base_url>`` so the
      Claude Code CLI itself routes through Bifrost's
      Anthropic-compatible endpoint at :8471/anthropic.
    - For ``terminal-qwen`` workers when the router is routed
      for ``RouteKind.QWEN_ROUTE``: inject the env var named by
      ``router.qwen_env_var`` (default ``OPENAI_BASE_URL``)
      pointing at the Bifrost OpenAI-compatible provider at :8471.
      The router returns the bare gateway URL; the OpenAI SDK
      appends ``/v1`` itself.

    Returns a plain dict suitable for the
    ``create_session(env=...)`` chain through the tmux adapter.

    The prior ``bifrost: BifrostConfig | None`` parameter is
    dropped (REQ-BIFROST-004, F-03 fix) — caller-spoofable
    settings were a real attack surface (a caller could pass a
    ``BifrostConfig(enabled=True, base_url=...)`` to override the
    file-config). The router is the single source of truth.
    """
    router = get_router()
    if not router._settings.enabled:
        # Dead-flag regression (REQ-BIFROST-003): enabled=False is
        # the only path to an empty env dict. No flag is set but
        # unreachable; the conditional collapses to a real None.
        return {}

    env: dict[str, str] = {}
    if worker_type == "terminal-claude":
        if RouteKind.CLAUDE_ROUTE in router._settings.routes:
            # The router's anthropic_base_url is pre-formatted
            # ``<gateway>/anthropic`` (matches the v1.5 spec), so
            # no suffix is needed — the gateway routes
            # ``<base>/anthropic/v1/messages`` internally.
            env["ANTHROPIC_BASE_URL"] = str(router._settings.anthropic_base_url)
    elif worker_type == "terminal-qwen":
        if RouteKind.QWEN_ROUTE in router._settings.routes:
            # The OpenAI-compatible client (Qwen CLI's SDK) expects
            # the URL with the ``/v1`` suffix — the bare gateway
            # URL would 404 on ``/chat/completions``. Same shape the
            # old ``gateway_api_base(ProtocolFamily.OPENAI, ...)``
            # produced; the ``rstrip("/")`` handles the Pydantic
            # ``HttpUrl`` trailing-slash quirk.
            #
            # The suffix is added only when absent: ``ONEIRIC_BIFROST_BASE_URL``
            # is conventionally configured *with* ``/v1`` already present
            # (``http://127.0.0.1:8471/v1``), so appending unconditionally
            # produced ``/v1/v1`` and 404'd every Qwen chat completion.
            base = str(router._settings.base_url).rstrip("/")
            if not base.endswith("/v1"):
                base += "/v1"
            env[router._settings.qwen_env_var] = base
    return env


# Spec §9.4 (Phase B): the durable-worker contract emits canonical
# Oneiric envelopes on worker.* topics. Task 13 will replace the
# no-op `_enqueue_to_eventbridge` sink with a real EventBridge
# producer; for now the bridge is a thin shim that hands the
# envelope to the existing eventbus (or drops it if no bus is wired).
def _enqueue_to_eventbridge(envelope: Any) -> None:
    """Forward a canonical envelope to the EventBridge.

    No-op until Task 13 wires the real producer.
    """
    logger.debug(
        "tmux worker envelope queued (no-op bridge): topic=%s source=%s",
        getattr(envelope, "topic", "?"),
        getattr(envelope, "source", "?"),
    )


class _ManagerEventPublisher:
    """Adapt the contract's EventPublisher Protocol to a sink callable.

    The contract's ``EventPublisher.emit(payload, topic)`` signature
    (per Task 5 / Task 6) is the inverse of the canonical
    ``CanonicalEnvelopePublisher.emit(topic, payload)``. The
    manager's internal calls all go through this bridge so the
    argument-order mismatch is contained to one place.
    """

    def __init__(self, sink: Callable[[Any], None]) -> None:
        self._sink = sink

    def emit(self, payload: dict[str, Any], topic: str) -> None:
        from ..core.events.envelope import EventEnvelope
        from ..core.events.worker_topics import is_worker_topic

        if not is_worker_topic(topic):
            # Non-worker topics are out of scope for Phase B; pass through.
            return
        envelope = EventEnvelope(
            event_type=topic,
            source="mahavishnu.terminal",
            payload=payload,
        )
        self._sink(envelope)


class TerminalManager:
    """Manage multiple terminal sessions with high concurrency support.

    Provides an interface for launching, controlling, and capturing
    output from multiple terminal sessions concurrently with proper
    resource management via semaphores.

    Features:
    - Hot-swappable adapters (switch adapters without restart)
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
        config: TerminalSettings | None = None,
    ) -> None:
        """Initialize terminal manager.

        Args:
            adapter: Terminal adapter backend
            config: Optional terminal settings

        The prior ``bifrost: BifrostConfig | None = None`` parameter
        is removed (REQ-BIFROST-023) — caller-spoofable settings
        were a real attack surface. Per-worker env-injection in
        ``launch_sessions`` now consults the oneiric
        ``BifrostLLMRouter`` directly (the canonical source of
        truth) instead of accepting a per-call config.
        """
        self.adapter = adapter
        self.config = config or TerminalSettings()
        self._semaphore = asyncio.Semaphore(self.config.max_concurrent_sessions)
        self._batch_size = 5  # Process 5 sessions at a time
        self._adapter_history: list[dict[str, Any]] = []
        self._session_migration_callback: Callable | None = None

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

        logger.info(f"Hot-switching adapter from {old_adapter_name} to {new_adapter_name}")

        # Record history
        self._adapter_history.append(
            {
                "from": old_adapter_name,
                "to": new_adapter_name,
                "timestamp": datetime.now(UTC).isoformat(),
                "migrate_sessions": migrate_sessions,
            }
        )

        # Attempt session migration if requested
        if migrate_sessions:
            try:
                await self._migrate_sessions(old_adapter, new_adapter)
            except Exception as e:  # terminal manager — broad catch logs migration failure and continues with the adapter switch  # best-effort operation — broad catch is the documented contract  # noqa: BLE001, RUF100
                logger.warning(f"Session migration failed: {e}")
                logger.info("Continuing with adapter switch (existing sessions orphaned)")

        # Switch adapters
        self.adapter = new_adapter

        logger.info(f"Successfully switched to {new_adapter_name} adapter")

        # Call migration callback if registered
        if self._session_migration_callback:
            try:
                await self._session_migration_callback(old_adapter_name, new_adapter_name)
            except Exception as e:  # terminal manager — broad catch logs migration callback failure but does not abort the switch  # best-effort operation — broad catch is the documented contract  # noqa: BLE001, RUF100
                logger.warning(f"Migration callback failed: {e}")

    async def _migrate_sessions(
        self,
        old_adapter: TerminalAdapter,
        new_adapter: TerminalAdapter,
    ) -> None:
        """Migrate sessions from old adapter to new adapter.

        This is experimental and may not work for all adapter combinations.

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
                # Recreate sessions on the new adapter with the same command.
                # Re-keyed by the new adapter's session id; old ids are dead.
                new_session_id = await new_adapter.launch_session(
                    command,
                    columns=self.config.default_columns,
                    rows=self.config.default_rows,
                )
                logger.info(f"Migrated session {session_id} → {new_session_id}")

            except Exception as e:  # terminal manager — broad catch logs per-session migration failure and continues the loop  # best-effort operation — broad catch is the documented contract  # noqa: BLE001, RUF100
                logger.warning(f"Failed to migrate session {session_id}: {e}")

        logger.info("Session migration complete")

    def set_migration_callback(self, callback: Callable) -> None:
        """Set a callback to be invoked when adapter switching occurs.

        Args:
            callback: Async function(old_adapter_name, new_adapter_name)
        """
        self._session_migration_callback = callback
        logger.info("Migration callback registered")

    # wire-up status: 1 caller in tests/unit/test_terminal_management.py:636;
    # audit_orphans filters test paths so it shows as orphan. switch_adapter()
    # uses the *_session_migration_callback attribute, not this setter. No
    # production caller — surface as orphan-to-wire per wire-up-contract.md.

    def get_adapter_history(self) -> list[dict[str, Any]]:
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
        *,
        worker_type: str = "terminal-claude",
    ) -> list[str]:
        """Launch multiple terminal sessions concurrently.

        Uses semaphore to limit concurrent launches and prevent
        resource exhaustion.

        Phase D (REQ-004): the per-worker env dict is built via
        :func:`_resolve_worker_env` and forwarded to the adapter
        so spawned panes inherit the Bifrost env override (when
        ``bifrost.enabled`` and the route flag is set). The
        ``worker_type`` parameter selects which opt-in flag is
        consulted.

        Args:
            command: Command to run in each terminal
            count: Number of sessions to launch
            columns: Terminal width in characters
            rows: Terminal height in lines
            worker_type: Worker backend name (default
                'terminal-claude'; 'terminal-qwen' selects the
                Qwen CLI's env-var opt-in)

        Returns:
            List of session IDs

        Raises:
            TerminalError: If session launch fails
        """

        env = _resolve_worker_env(worker_type)
        if env:
            logger.info(
                "Per-spawn Bifrost env injection: worker_type=%s env_keys=%s",
                worker_type,
                sorted(env.keys()),
            )

        async def launch_one() -> str:
            async with self._semaphore:
                return await self.adapter.launch_session(
                    command,
                    columns,
                    rows,
                    worker_type=worker_type,
                    env=env,
                )

        try:
            # Launch all sessions concurrently
            tasks = [launch_one() for _ in range(count)]
            session_ids = await asyncio.gather(*tasks)

            logger.info(
                f"Launched {len(session_ids)} sessions using {self.adapter.adapter_name} adapter"
            )
            return session_ids

        except (
            Exception
        ) as e:  # terminal manager — broad catch logs session launch failure and re-raises
            logger.error(f"Failed to launch sessions: {e}")
            raise

    async def launch_sessions_batch(
        self,
        command: str,
        count: int,
        columns: int = 80,
        rows: int = 24,
    ) -> list[str]:
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
        session_ids: list[str] = []

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
    ) -> list[str]:
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
        lines: int | None = None,
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
        session_ids: list[str],
        lines: int | None = None,
    ) -> dict[str, str]:
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

    async def close_all(self, session_ids: list[str]) -> None:
        """Close multiple sessions concurrently.

        Args:
            session_ids: List of session IDs to close

        Raises:
            TerminalError: If session close fails
        """
        tasks = [self.adapter.close_session(sid) for sid in session_ids]
        await asyncio.gather(*tasks)
        logger.info(f"Closed {len(session_ids)} sessions")

    async def list_sessions(self) -> list[dict[str, Any]]:
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
    ) -> TerminalManager:
        """Create terminal manager with appropriate adapter.

        Factory method that selects the best available adapter based
        on configuration and runtime environment.

        Priority order:
        1. mock - Always works, no dependencies (default)
        2. tmux - Default durable-worker terminal (Spec §9.4)
        3. crow - Bundled HTTP MCP bridge to bodai-crow (requires crow_enabled=True)

        Args:
            config: MahavishnuSettings with terminal config
            mcp_client: MCP client for adapter communication (optional)

        Returns:
            Configured TerminalManager instance

        Raises:
            ConfigurationError: No suitable adapter available
        """
        from ..core.errors import ConfigurationError
        from .adapters import get_adapter_factory, list_adapter_names

        terminal_config = config.terminal
        preference = terminal_config.adapter_preference

        # "auto" is documented as an alias for "mock" — preserve the legacy behavior.
        if preference == "auto":
            preference = "mock"

        # Deprecation warning for iTerm2 — fall through to mock.
        if preference == "iterm2":
            warnings.warn(
                "adapter_preference='iterm2' is deprecated and has been removed. "
                "Use 'tmux' or 'crow' instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            preference = "mock"

        # D0 refactor: dispatch via the adapter registry. Each adapter module
        # registers itself on import. Adding a new adapter is one
        # ``register_adapter(name, factory)`` call, not a new branch here.
        try:
            factory = get_adapter_factory(preference)
        except KeyError as exc:
            raise ConfigurationError(
                message=f"No suitable terminal adapter found for preference '{preference}'",
                details={
                    "adapter_preference": preference,
                    "available_adapters": list(list_adapter_names()),
                    "mcp_client_provided": mcp_client is not None,
                    "registry_error": str(exc),
                },
            ) from None

        adapter = factory(config=terminal_config, mcp_client=mcp_client)
        logger.info("Using %s terminal adapter", adapter.adapter_name)
        return cls(adapter, terminal_config)

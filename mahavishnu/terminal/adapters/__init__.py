"""Terminal adapter registry (D0 refactor).

Each adapter module registers itself via ``register_adapter``. The dispatch in
``TerminalManager.create`` and ``mcp/bootstrap._resolve_terminal_adapter`` looks
up a factory by name.

Backward compatibility:
- ``get_available_adapters`` returns registered names
- ``get_adapter_class`` returns the class for code that needs it (mock and crow only)
- Adapters that depend on optional packages (crow) register lazily —
  if the optional import fails, the adapter is simply not registered.
- Tmux factory handles its own filesystem-path construction (was previously
  duplicated between ``terminal/manager.py`` and ``mcp/bootstrap.py``).

The factory protocol: ``Callable[[config, mcp_client], TerminalAdapter]``. The
``config`` and ``mcp_client`` kwargs may be None for adapters that ignore them.
"""

from collections.abc import Callable  # noqa: TC003
from typing import Any

# Registry: adapter name -> factory that produces an instance. The factory
# receives (config, mcp_client) kwargs. Adapters that don't need them (mock,
# tmux) ignore them; Crow uses both.
_ADAPTER_REGISTRY: dict[str, Callable[..., Any]] = {}


def register_adapter(name: str, factory: Callable[..., Any]) -> None:
    """Register an adapter factory.

    Args:
        name: Canonical adapter name (e.g. "mock", "tmux", "crow").
        factory: Callable that returns a ``TerminalAdapter`` instance. Receives
            ``config`` and ``mcp_client`` kwargs (callers may pass None for either).

    Raises:
        ValueError: If the name is already registered.
    """
    if name in _ADAPTER_REGISTRY:
        raise ValueError(f"Terminal adapter {name!r} is already registered")
    _ADAPTER_REGISTRY[name] = factory


def get_adapter_factory(name: str) -> Callable[..., Any]:
    """Look up an adapter factory by name.

    Returns the factory callable. Raises ``KeyError`` if the adapter is
    not registered (e.g. optional dependency missing). Callers who want
    to silently skip an unavailable adapter should use ``name in
    {a for a in list_adapter_names()}`` first.
    """
    factory = _ADAPTER_REGISTRY.get(name)
    if factory is None:
        raise KeyError(
            f"Unknown or unavailable terminal adapter {name!r}. "
            f"Available: {', '.join(list_adapter_names())}"
        )
    return factory


def list_adapter_names() -> tuple[str, ...]:
    """Return the registered adapter names, sorted."""
    return tuple(sorted(_ADAPTER_REGISTRY))


def get_available_adapters() -> list[str]:
    """Backward-compatible wrapper returning the registered adapter names as a list."""
    return list(list_adapter_names())


# Mock adapter is always available — register at module load.
from .base import (
    SessionNotFoundError,
    TerminalAdapter,
    TerminalError,
)
from .mock import MockTerminalAdapter


def _build_mock_adapter(
    config: Any = None,
    mcp_client: Any = None,
    **_unused: Any,
) -> Any:
    """Mock factory — ignores config and mcp_client."""
    return MockTerminalAdapter()


register_adapter("mock", _build_mock_adapter)


# Tmux adapter — constructs DurableWorkerManager inline. Was previously
# duplicated between TerminalManager.create and mcp/bootstrap._build_tmux_adapter.
def _build_tmux_adapter(
    config: Any = None,
    mcp_client: Any = None,
    **_unused: Any,
) -> Any:
    """Construct the durable-worker tmux adapter.

    Mirrors the original tmux branch of :meth:`TerminalManager.create`. Every
    step is a plain constructor, so this stays callable from synchronous
    bootstrap without an async refactor.
    """
    import pathlib

    from ...workers.contract.manager import DurableWorkerManager
    from ...workers.contract.store import WorkerRecordStore

    # Imported lazily to avoid a circular dependency at module load
    # (terminal.manager imports from terminal.adapters).
    from ..manager import _enqueue_to_eventbridge, _ManagerEventPublisher
    from .tmux import TmuxTerminalAdapter

    store = WorkerRecordStore(pathlib.Path.home() / ".mahavishnu" / "worker-sessions")
    publisher = _ManagerEventPublisher(_enqueue_to_eventbridge)
    manager = DurableWorkerManager(
        store=store,
        publisher=publisher,
        socket_dir=pathlib.Path.home() / ".mahavishnu" / "tmux",
    )
    return TmuxTerminalAdapter(manager)


register_adapter("tmux", _build_tmux_adapter)


# Crow adapter is opt-in: requires crow-mcp to be installed AND crow_enabled=True.
try:
    from .crow import CrowTerminalAdapter

    CrowTerminalAdapter: type[TerminalAdapter] | None = CrowTerminalAdapter  # type: ignore[misc,assignment]  # noqa: PLW0127 — self-bind narrows the import's type to type[TerminalAdapter] | None

    def _build_crow_adapter(
        config: Any = None,
        mcp_client: Any = None,
        **_unused: Any,
    ) -> Any:
        """Crow factory.

        Requires both config (for crow_enabled check) and mcp_client. If
        crow_enabled is False, falls back to MockTerminalAdapter (the
        documented default behavior per MHV-001). Raises ConfigurationError
        if crow_enabled is True but no mcp_client was provided.
        """
        from ...core.errors import ConfigurationError

        if config is None:
            raise ConfigurationError(
                message="Crow adapter requires terminal config",
                details={"adapter_preference": "crow"},
            )

        crow_enabled = getattr(config, "crow_enabled", False)
        if not crow_enabled:
            return MockTerminalAdapter()
        if mcp_client is None:
            raise ConfigurationError(
                message=(
                    "crow adapter is enabled (crow_enabled=true) but no "
                    "mcp_client was provided. Either provide an mcp_client "
                    "pointing at the Bodai crow HTTP server, or set "
                    "terminal.crow_enabled=false to use the mock adapter."
                ),
                details={
                    "adapter_preference": "crow",
                    "crow_enabled": True,
                    "crow_http_endpoint": (
                        f"{getattr(config, 'crow_http_host', '127.0.0.1')}:"
                        f"{getattr(config, 'crow_http_port', 8693)}"
                    ),
                },
            )
        assert CrowTerminalAdapter is not None  # type narrowing for ty
        # ty sees the annotation as `type[TerminalAdapter] | None` and resolves
        # ``__init__`` to ``object.__init__``; the runtime class has its own
        # ``__init__(mcp_client)``. The runtime is correct; the static check
        # cannot trace through the try/except ImportError → None pattern.
        return CrowTerminalAdapter(mcp_client)  # ty: ignore[too-many-positional-arguments]

    register_adapter("crow", _build_crow_adapter)
except ImportError:
    CrowTerminalAdapter = None  # type: ignore[misc,assignment]


def get_adapter_class(name: str) -> type[TerminalAdapter] | None:
    """Backward-compatible lookup returning the adapter class (not an instance).

    Returns the class only for adapters that have a stable class identity
    (currently just mock and crow). For tmux, returns None — callers
    should use :func:`get_adapter_factory` for instance construction.
    """
    if name == "mock":
        return MockTerminalAdapter
    if name == "crow" and CrowTerminalAdapter is not None:
        return CrowTerminalAdapter
    return None


__all__ = [
    # Crow adapter (requires crow-mcp MCP server)
    "CrowTerminalAdapter",
    # Mock adapter (always available)
    "MockTerminalAdapter",
    "SessionNotFoundError",
    # Base
    "TerminalAdapter",
    "TerminalError",
    "get_adapter_class",
    # Utility functions
    "get_adapter_factory",
    "get_available_adapters",
    "list_adapter_names",
    "register_adapter",
]

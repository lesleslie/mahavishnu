"""Terminal adapter registry (D0 refactor).

Each adapter module registers itself via ``register_adapter``. The dispatch in
``TerminalManager.create`` and ``mcp/bootstrap._resolve_terminal_adapter`` looks
up a factory by name.

Backward compatibility:
- ``get_available_adapters`` returns registered names
- ``get_adapter_class`` returns the class for code that needs it (mock and crow only)
- Adapters that depend on optional packages (crow, goose) register lazily —
  if the optional import fails, the adapter is simply not registered.
- Tmux factory handles its own filesystem-path construction (was previously
  duplicated between ``terminal/manager.py`` and ``mcp/bootstrap.py``).

The factory protocol: ``Callable[[config, mcp_client], TerminalAdapter]``. The
``config`` and ``mcp_client`` kwargs may be None for adapters that ignore them.
"""

from collections.abc import Callable  # noqa: TC003 - used in runtime function signatures
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .base import TerminalAdapter

# Registry: adapter name -> factory that produces an instance. The factory
# receives (config, mcp_client) kwargs. Adapters that don't need them (mock,
# tmux) ignore them; Crow uses both.
_ADAPTER_REGISTRY: dict[str, Callable[..., Any]] = {}


def register_adapter(name: str, factory: Callable[..., Any]) -> None:
    """Register an adapter factory.

    Args:
        name: Canonical adapter name (e.g. "mock", "tmux", "crow", "goose").
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

    CrowTerminalAdapter: type[TerminalAdapter] | None = CrowTerminalAdapter  # type: ignore[misc,assignment]  # noqa: PLW0127

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
    (currently just mock and crow). For tmux and goose, returns None — callers
    should use :func:`get_adapter_factory` for instance construction.
    """
    if name == "mock":
        return MockTerminalAdapter
    if name == "crow" and CrowTerminalAdapter is not None:
        return CrowTerminalAdapter
    return None


# Goose adapter is opt-in: requires ``goose_enabled=True`` and a configured
# ``goose_secret_key``. If either is missing, falls back to MockTerminalAdapter
# (matches the documented Crow fallback behaviour). The factory itself runs
# lazily so the import is deferred until ``list_adapter_names()`` is first
# inspected — until then, the module has no impact on import time.
try:
    from pydantic import SecretStr

    from .goose import GooseTerminalAdapter

    GooseTerminalAdapter: type[TerminalAdapter] | None = GooseTerminalAdapter  # type: ignore[misc,assignment]  # noqa: PLW0127

    def _build_goose_adapter(
        config: Any = None,
        mcp_client: Any = None,
        **_unused: Any,
    ) -> Any:
        """Goose factory.

        Requires ``config`` for ``goose_enabled`` + ``goose_secret_key``.
        When ``goose_enabled`` is False, falls back to MockTerminalAdapter
        (matching the Crow factory behaviour). When True, constructs a
        :class:`~mahavishnu.terminal.goose_client.GooseHTTPClient` from
        the configured host/port/secret.

        Req: REQ-GOO-001, REQ-GOO-002
        """
        from ...core.errors import ConfigurationError
        from ..goose_client import create_goose_http_client

        if config is None:
            raise ConfigurationError(
                message="Goose adapter requires terminal config",
                details={"adapter_preference": "goose"},
            )

        goose_enabled = getattr(config, "goose_enabled", False)
        if not goose_enabled:
            return MockTerminalAdapter()

        secret = getattr(config, "goose_secret_key", None)
        if secret is None:
            raise ConfigurationError(
                message=(
                    "goose adapter is enabled (goose_enabled=true) but "
                    "goose_secret_key is not configured. Set "
                    "MAHAVISHNU_TERMINAL__GOOSE_SECRET_KEY or the "
                    "goose_secret_key setting in local.yaml."
                ),
                details={
                    "adapter_preference": "goose",
                    "goose_enabled": True,
                    "goose_http_endpoint": (
                        f"{getattr(config, 'goose_http_host', '127.0.0.1')}:"
                        f"{getattr(config, 'goose_http_port', 8694)}"
                    ),
                },
            )

        # Normalise SecretStr → SecretStr (already is, but keep type checkers quiet).
        if isinstance(secret, str):  # pragma: no cover - defensive
            secret = SecretStr(secret)

        http_client = create_goose_http_client(
            host=getattr(config, "goose_http_host", "127.0.0.1"),
            port=getattr(config, "goose_http_port", 8694),
            secret_key=secret,
            timeout=30.0,
        )
        assert GooseTerminalAdapter is not None  # type narrowing for ty
        # See Crow comment above for why ty ignores ``call-arg``.
        return GooseTerminalAdapter(http_client=http_client)  # ty: ignore[unknown-argument]

    register_adapter("goose", _build_goose_adapter)
except ImportError:
    GooseTerminalAdapter = None  # type: ignore[misc,assignment]


__all__ = [
    # Crow adapter (requires crow-mcp MCP server)
    "CrowTerminalAdapter",
    # Goose adapter (Block's goose serve over HTTP, opt-in)
    "GooseTerminalAdapter",
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

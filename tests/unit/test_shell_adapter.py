"""Unit tests for mahavishnu.shell.adapter.

Complements ``tests/unit/test_shell.py`` by exercising the adapter's
behavioural contracts that the existing file does not pin down:
- identity of the objects placed in the shell namespace,
- the async-wrapping semantics of the helper closures,
- the magics registration call,
- the exact contents of the banner.

The base ``AdminShell`` from oneiric is initialised with a mock
``MahavishnuApp`` so we never touch the real filesystem, registry, or
workflow state.

Run standalone:
    python tests/unit/test_shell_adapter.py

Run with pytest:
    pytest tests/unit/test_shell_adapter.py
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from mahavishnu.core.app import MahavishnuApp
from mahavishnu.core.status import WorkflowStatus
from mahavishnu.shell.adapter import MahavishnuShell
from mahavishnu.shell.formatters import LogFormatter, RepoFormatter, WorkflowFormatter
from mahavishnu.shell.magics import MahavishnuMagics

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_app() -> MagicMock:
    """A mock MahavishnuApp with a small adapters dict."""
    app = MagicMock(spec=MahavishnuApp)
    app.adapters = {"prefect": MagicMock(), "llamaindex": MagicMock()}
    return app


@pytest.fixture
def shell(mock_app: MagicMock) -> MahavishnuShell:
    return MahavishnuShell(mock_app)


def _drain(mock_async_fn) -> None:
    """Close the coroutine produced by an AsyncMock to silence
    RuntimeWarning('coroutine ... was never awaited')."""
    try:
        mock_async_fn.return_value.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Namespace identity
# ---------------------------------------------------------------------------


def test_namespace_workflow_status_is_real_enum(shell: MahavishnuShell) -> None:
    """WorkflowStatus in the namespace must be the real enum class
    (callers may compare against ``WorkflowStatus.RUNNING``)."""
    assert shell.namespace["WorkflowStatus"] is WorkflowStatus


def test_namespace_mahavishnu_app_is_real_class(shell: MahavishnuShell) -> None:
    assert shell.namespace["MahavishnuApp"] is MahavishnuApp


def test_namespace_helpers_are_independent_closures(
    shell: MahavishnuShell,
) -> None:
    """Each helper is a distinct closure, not a shared reference."""
    helpers = {shell.namespace[k] for k in ("ps", "top", "errors", "sync")}
    assert len(helpers) == 4


# ---------------------------------------------------------------------------
# Async wrapping semantics
# ---------------------------------------------------------------------------


def test_ps_helper_runs_via_asyncio_run(shell: MahavishnuShell) -> None:
    """Calling ``namespace['ps']()`` should run ``ps(self.app)`` and
    feed the resulting coroutine into ``asyncio.run``.

    ``ps`` is an async function so ``patch`` makes it an ``AsyncMock``;
    calling the mock returns a coroutine that ``asyncio.run`` then
    awaits. We assert both ends of the contract: ``ps`` was invoked
    with the shell's app, and ``asyncio.run`` was invoked with a
    coroutine produced from that call.
    """
    with (
        patch("mahavishnu.shell.adapter.ps") as mock_ps,
        patch("mahavishnu.shell.adapter.asyncio.run") as mock_run,
    ):
        shell.namespace["ps"]()

    mock_ps.assert_called_once_with(shell.app)
    mock_run.assert_called_once()
    run_arg = mock_run.call_args.args[0]
    # The argument to asyncio.run is the coroutine returned by ps(app).
    assert hasattr(run_arg, "__await__") or hasattr(run_arg, "send")
    _drain(mock_ps)


def test_errors_helper_passes_default_limit_through(
    shell: MahavishnuShell,
) -> None:
    """``errors()`` with no argument must default to limit=10; the
    closure forwards arguments verbatim to ``errors(shell.app, limit)``."""
    with (
        patch("mahavishnu.shell.adapter.errors") as mock_errors,
        patch("mahavishnu.shell.adapter.asyncio.run"),
    ):
        shell.namespace["errors"]()

    mock_errors.assert_called_once_with(shell.app, 10)
    _drain(mock_errors)


def test_errors_helper_propagates_explicit_limit(
    shell: MahavishnuShell,
) -> None:
    with (
        patch("mahavishnu.shell.adapter.errors") as mock_errors,
        patch("mahavishnu.shell.adapter.asyncio.run"),
    ):
        shell.namespace["errors"](5)

    mock_errors.assert_called_once_with(shell.app, 5)
    _drain(mock_errors)


def test_top_and_sync_helpers_wrap_via_asyncio_run(
    shell: MahavishnuShell,
) -> None:
    with (
        patch("mahavishnu.shell.adapter.top") as mock_top,
        patch("mahavishnu.shell.adapter.sync") as mock_sync,
        patch("mahavishnu.shell.adapter.asyncio.run") as mock_run,
    ):
        shell.namespace["top"]()
        shell.namespace["sync"]()

    mock_top.assert_called_once_with(shell.app)
    mock_sync.assert_called_once_with(shell.app)
    assert mock_run.call_count == 2
    _drain(mock_top)
    _drain(mock_sync)


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------


def test_formatters_are_correct_classes(shell: MahavishnuShell) -> None:
    assert isinstance(shell.workflow_formatter, WorkflowFormatter)
    assert isinstance(shell.log_formatter, LogFormatter)
    assert isinstance(shell.repo_formatter, RepoFormatter)


# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------


def test_banner_lists_all_adapters(shell: MahavishnuShell) -> None:
    banner = shell._get_banner()
    assert "Mahavishnu Admin Shell" in banner
    assert "prefect" in banner
    assert "llamaindex" in banner
    # Adapters are joined with ", "
    assert "prefect, llamaindex" in banner or "llamaindex, prefect" in banner


def test_banner_documents_every_helper_and_magic(
    shell: MahavishnuShell,
) -> None:
    banner = shell._get_banner()
    for snippet in (
        "ps()",
        "top()",
        "errors(n=10)",
        "sync()",
        "%repos",
        "%workflow <id>",
    ):
        assert snippet in banner, f"banner missing documentation for {snippet!r}"


def test_banner_with_empty_adapters_does_not_crash(
    mock_app: MagicMock,
) -> None:
    mock_app.adapters = {}
    shell = MahavishnuShell(mock_app)
    banner = shell._get_banner()
    assert "Active Adapters:" in banner
    # The adapter list section is present even when empty.
    assert "Active Adapters: " in banner


# ---------------------------------------------------------------------------
# Magics registration
# ---------------------------------------------------------------------------


def test_register_magics_calls_super_and_registers_magics(
    shell: MahavishnuShell,
) -> None:
    """``_register_magics`` must:
    1. call the superclass registration first (so base magics stay),
    2. register a ``MahavishnuMagics`` instance against ``self.shell``
       (via ``self.shell.register_magics(magics)``).

    We patch ``MahavishnuMagics`` itself because the real class uses
    traitlets that require a real IPython ``InteractiveShell`` parent;
    in this unit test we just want to verify the wiring.
    """
    fake_shell = MagicMock()
    shell.shell = fake_shell

    with (
        patch.object(MahavishnuShell.__mro__[1], "_register_magics") as mock_super,
        patch("mahavishnu.shell.adapter.MahavishnuMagics") as mock_cls,
    ):
        mock_instance = MagicMock(spec=MahavishnuMagics)
        mock_cls.return_value = mock_instance
        shell._register_magics()

    mock_super.assert_called_once_with()
    mock_cls.assert_called_once_with(fake_shell)
    fake_shell.register_magics.assert_called_once_with(mock_instance)
    mock_instance.set_app.assert_called_once_with(shell.app)


# ---------------------------------------------------------------------------
# Config pass-through
# ---------------------------------------------------------------------------


def test_custom_shell_config_is_stored(mock_app: MagicMock) -> None:
    """The optional ``config`` argument is forwarded to ``AdminShell``."""
    sentinel_config = MagicMock(name="ShellConfig")
    shell = MahavishnuShell(mock_app, config=sentinel_config)
    assert shell.config is sentinel_config

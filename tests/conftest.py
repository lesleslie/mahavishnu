"""Pytest configuration for unit tests.

This file automatically marks all tests in tests/unit/ as unit tests,
allowing the production readiness checker to run only unit tests with the
`-m unit` flag.
"""

import os

# Remove AI_AGENT before any imports so crackerjack's AISettings.ai_agent bool
# field doesn't receive a string value set by the outer Claude Code environment.
os.environ.pop("AI_AGENT", None)

# ---------------------------------------------------------------------------
# Disable ANSI escape codes in CLI help / table output for the test session.
#
# Two layers need to be neutralised:
#
# 1. Typer's Rich-based help renderer is controlled at module-import time by
#    reading environment variables. Setting ``_TYPER_FORCE_DISABLE_TERMINAL``
#    forces ``FORCE_TERMINAL = False`` in ``typer.rich_utils`` so the help
#    tables render without ANSI codes (otherwise ``"--type"`` becomes
#    ``"--\\x1b[0m\\x1b[1;36mtype"`` which breaks plain-text assertions).
#
# 2. CLI modules that bind ``console = Console()`` at import time also need
#    to be constructed with ``no_color=True``. Patching ``Console.__init__``
#    here — before any test module is imported — ensures every Console in
#    the test session is built without colors.
# ---------------------------------------------------------------------------
os.environ["_TYPER_FORCE_DISABLE_TERMINAL"] = "1"

from rich.console import Console as _RichConsole

_orig_console_init = _RichConsole.__init__


def _patched_console_init(self, *args, **kwargs):
    kwargs.setdefault("no_color", True)
    kwargs.setdefault("color_system", None)
    kwargs.setdefault("force_terminal", False)
    kwargs.setdefault("force_interactive", False)
    _orig_console_init(self, *args, **kwargs)


_RichConsole.__init__ = _patched_console_init

import pytest

# Import fixtures from fixtures package for global availability
# Use try/except to handle cases where fixtures might not be available
try:
    from tests.fixtures.workflow_fixtures import (
        WorkflowFixtures,
        completed_workflow,
        failed_workflow,
        mock_workflow_state_manager,
        multiple_workflows,
        partial_workflow,
        pending_workflow,
        sample_repos,
        sample_task,
        sample_workflow,
        workflow_fixtures,
    )
except ImportError:
    pass

try:
    from tests.fixtures.shell_fixtures import (
        ShellFixtures,
        mock_error_output,
        mock_health_check_output,
        mock_log_formatter,
        mock_opensearch_logs,
        mock_repo_formatter,
        mock_repos_list,
        mock_rich_console,
        mock_role_output,
        mock_shell_commands,
        mock_shell_output,
        mock_terminal_output,
        mock_workflow_formatter,
        mock_workflow_status,
        shell_fixtures,
    )
except ImportError:
    pass

try:
    from tests.fixtures.conftest import (
        IntegrationFixtures,
        async_mock_app,
        clean_env,
        integration_fixtures,
        mock_adapter,
        mock_app,
        mock_config,
        mock_event_loop,
        mock_filesystem,
        mock_logger,
        mock_performance_tracker,
        sample_timestamp,
        sample_user_id,
        sample_workflow_id,
        suppress_prefect_console_shutdown_noise,
        temp_config_file,
        temp_dir,
        temp_git_repo,
        temp_repos_file,
        test_env_vars,
    )
except ImportError:
    pass


def pytest_collection_modifyitems(items, config):
    """Automatically mark all tests in tests/unit/ as unit tests."""
    # Add Oneiric to path for ULID resolution imports
    import os
    import sys

    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)  # mahavishnu/
    oneiric_path = os.path.join(project_root, "../oneiric")
    oneiric_path = os.path.abspath(oneiric_path)
    if oneiric_path not in sys.path:
        sys.path.insert(0, oneiric_path)

    for item in items:
        # Mark tests in tests/unit/ directory as unit tests
        if "/tests/unit/" in str(item.fspath):
            item.add_marker(pytest.mark.unit)
        # Mark tests in tests/integration/ directory as integration tests
        elif "/tests/integration/" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
        # Mark tests in tests/property/ directory as property tests
        elif "/tests/property/" in str(item.fspath):
            item.add_marker(pytest.mark.property)


# ---------------------------------------------------------------------------
# Task 18 — jot-drain property-test fixtures
# ---------------------------------------------------------------------------
#
# These six fixtures are the canonical fixtures for hypothesis-driven property
# tests in tests/property/jot/. Each one targets a specific seam in
# mahavishnu.jot.drain so property tests can compose them without manual
# monkeypatching per-test.
#
# Naming convention: no ``_drain_`` prefix is needed because none of the names
# collide with the rich fixture catalogue already exposed from
# tests/fixtures/*.py (workflow_fixtures, shell_fixtures, conftest fixtures).


@pytest.fixture
def fake_workflow_substrate(monkeypatch):
    """Fake ``_mcp_trigger_workflow`` + ``_mcp_get_workflow_status``.

    ``fake_trigger`` issues monotonically incrementing workflow IDs
    (``wf-1``, ``wf-2``, ...) and tracks every call. ``fake_status`` returns
    the recorded status for each ID (default ``{"status": "UNKNOWN"}``).
    """
    from mahavishnu.jot import drain

    calls = {"trigger": [], "status": {}}

    async def fake_trigger(adapter, task_type, params):
        wf_id = f"wf-{len(calls['trigger']) + 1}"
        calls["trigger"].append(
            {"adapter": adapter, "task_type": task_type, "params": params},
        )
        calls["status"][wf_id] = {"status": "RUNNING"}
        return {"workflow_id": wf_id}

    async def fake_status(workflow_id):
        return calls["status"].get(workflow_id, {"status": "UNKNOWN"})

    monkeypatch.setattr(drain, "_mcp_trigger_workflow", fake_trigger)
    monkeypatch.setattr(drain, "_mcp_get_workflow_status", fake_status)
    return calls


@pytest.fixture
def fake_embeddings_service(monkeypatch):
    """Deterministic embeddings stub; ``.deterministic`` flag is True.

    Patches ``_build_embeddings_adapter`` to return a sync stub that hashes
    each input string and projects the first 8 bytes into ``[0.0, 1.0]``.
    Identical inputs produce identical vectors.
    """
    from mahavishnu.jot import drain

    class FakeEmbeddings:
        deterministic = True

        async def embed(self, texts):
            import hashlib

            return [
                [(hashlib.md5(t.encode()).digest()[i] / 255.0) for i in range(8)]
                for t in texts
            ]

    fake = FakeEmbeddings()
    monkeypatch.setattr(drain, "_build_embeddings_adapter", lambda: fake)
    return fake


@pytest.fixture
def fast_backoff(monkeypatch):
    """Zero out ``RETRY_BACKOFF_SECONDS`` so auto-retry paths run instantly."""
    from mahavishnu.jot import drain

    monkeypatch.setattr(drain, "RETRY_BACKOFF_SECONDS", 0)


@pytest.fixture
def no_async_sleep(monkeypatch):
    """Replace ``asyncio.sleep`` with a no-op (yield to loop, but no delay).

    Useful when tests don't want to drive the auto-retry path through a real
    wall-clock sleep. Combined with ``fast_backoff`` this makes the retry
    path fully synchronous for testing.
    """
    import asyncio

    async def fake_sleep(_):
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)


@pytest.fixture
def clock(monkeypatch):
    """Replace ``time.time()`` with a controllable clock.

    Returns a ``state`` dict so the test can advance the clock between
    phases. Default initial value is 2023-11-14 epoch ms.
    """
    import time

    state = {"now_ms": 1_700_000_000_000}
    monkeypatch.setattr(time, "time", lambda: state["now_ms"] / 1000)
    return state

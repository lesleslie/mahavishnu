"""Tests for PrefectAdapter.create_deployment(flow_path=...) extension.

Phase A.0.3 of Plan 5 (Distilled Workflows). Adds a ``flow_path`` parameter
to ``create_deployment`` so the future ``mahavishnu workflow publish`` CLI
(Phase C.2) can register a workflow by dotted module path without first
having to import it manually.

Behavior:
- If ``flow_path`` is provided, import the module, locate the
  ``@mahavishnu_workflow``-decorated function (attribute
  ``__mahavishnu_workflow_spec__``), register it via the existing
  ``FlowRegistry.register_flow`` path, then build the deployment under
  the registered flow's name.
- ``flow_path`` format: ``"module.path:func_name"`` (Python standard
  ``obj:attr`` notation). This is unambiguous, debuggable, and matches
  the convention used by Prefect itself (``@flow`` tasks are imported
  by path).
- If neither ``flow_name`` nor ``flow_path`` is provided, raise a
  ``PrefectError`` (existing behavior for the empty case).
- Backward compatibility: ``flow_name="..."`` still works exactly as
  before for the existing ``clone_refactor_workflow`` path.
"""

from __future__ import annotations

import sys
import textwrap
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.core.config import PrefectConfig
from mahavishnu.engines.prefect_adapter_impl import PrefectAdapter

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def prefect_config() -> PrefectConfig:
    """Real PrefectConfig (avoids Pydantic validation issues with MagicMock)."""
    return PrefectConfig(
        api_url="http://test-prefect:4200",
        work_pool="test-pool",
        timeout_seconds=60,
        max_retries=2,
    )


@pytest.fixture
def adapter(prefect_config: PrefectConfig) -> PrefectAdapter:
    """Adapter instance, not yet initialized."""
    return PrefectAdapter(config=prefect_config)


@pytest.fixture
def mock_client() -> MagicMock:
    """Mock Prefect client with the create_deployment call shape we need."""
    client = MagicMock()
    mock_deployment = _make_mock_deployment()
    mock_flow = MagicMock(id="flow-test-xyz", name="flow-under-test")
    client.read_flow_by_name = AsyncMock(return_value=mock_flow)
    client.create_deployment = AsyncMock(return_value=mock_deployment)
    return client


def _make_mock_deployment() -> MagicMock:
    """Build a mock deployment with all Pydantic-validated fields populated."""
    from datetime import UTC, datetime
    import uuid

    deploy = MagicMock()
    deploy.id = uuid.uuid4()
    deploy.name = "test-deployment"
    deploy.flow_name = "test-flow"
    deploy.flow_id = uuid.uuid4()
    deploy.schedule = {"cron": "0 9 * * *"}
    deploy.parameters = {"env": "test"}
    deploy.work_pool_name = "test-pool"
    deploy.work_queue_name = "default"
    deploy.paused = False
    deploy.tags = ["test"]
    deploy.description = "Test deployment"
    deploy.version = "1.0.0"
    deploy.created = datetime.now(UTC)
    deploy.updated = datetime.now(UTC)
    return deploy


@pytest.fixture
def patched_get_client(adapter: PrefectAdapter, mock_client: MagicMock) -> MagicMock:
    """Patch the adapter's _get_client_context to return mock_client."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_client)
    cm.__aexit__ = AsyncMock(return_value=None)
    adapter._get_client_context = MagicMock(return_value=cm)  # type: ignore[method-assign]
    adapter._initialized = True
    return mock_client


# ---------------------------------------------------------------------------
# Helpers for flow_path tests
# ---------------------------------------------------------------------------


def _write_decorated_module(
    parent_dir: Path, dotted_path: str, func_name: str = "wf_under_test"
) -> None:
    """Write a module that uses @mahavishnu_workflow.

    ``dotted_path`` like ``wfpkg.simple`` becomes
    ``<parent_dir>/wfpkg/simple.py`` importable as ``wfpkg.simple``.
    """
    module_path_no_ext = dotted_path.replace(".", "/")
    file_path = parent_dir / f"{module_path_no_ext}.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    body = textwrap.dedent(
        f"""\
        from __future__ import annotations
        from mahavishnu.distill.decorator import mahavishnu_workflow


        @mahavishnu_workflow(
            intent="test-intent",
            tags=("t1", "t2"),
            work_pool="test-pool",
        )
        async def {func_name}() -> str:
            return "ok"
        """
    )
    file_path.write_text(body)


@pytest.fixture
def flow_path_pkg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a fresh package on disk that contains a decorated workflow.

    Adds ``tmp_path`` to ``sys.path`` so the package is importable by
    dotted path. Cleaned up via monkeypatch.
    """
    pkg_dir = tmp_path / "wfpkg"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("")
    _write_decorated_module(tmp_path, "wfpkg.simple")

    monkeypatch.syspath_prepend(str(tmp_path))
    # Also clear any cached import of wfpkg from a previous test.
    sys.modules.pop("wfpkg", None)
    sys.modules.pop("wfpkg.simple", None)
    yield tmp_path
    # Best-effort cleanup.
    sys.modules.pop("wfpkg", None)
    sys.modules.pop("wfpkg.simple", None)


# ---------------------------------------------------------------------------
# Backward compatibility — flow_name path unchanged
# ---------------------------------------------------------------------------


class TestCreateDeploymentBackwardCompatibility:
    """flow_name-only path: behaves exactly as before."""

    async def test_flow_name_still_works(
        self,
        adapter: PrefectAdapter,
        patched_get_client: MagicMock,
    ) -> None:
        """create_deployment(flow_name=...) still calls Prefect and returns."""
        result = await adapter.create_deployment(
            flow_name="my-flow",
            deployment_name="production",
            tags=["etl"],
        )

        patched_get_client.read_flow_by_name.assert_awaited_once_with("my-flow")
        patched_get_client.create_deployment.assert_awaited_once()
        assert result is not None


# ---------------------------------------------------------------------------
# flow_path — new code path
# ---------------------------------------------------------------------------


class TestCreateDeploymentFlowPath:
    """flow_path extension: imports by dotted path and registers."""

    async def test_flow_path_imports_and_registers(
        self,
        adapter: PrefectAdapter,
        patched_get_client: MagicMock,
        flow_path_pkg: Path,
    ) -> None:
        """flow_path=``module:func`` registers the decorated function via FlowRegistry."""
        # Spy on FlowRegistry.register_flow via a mock registry on the adapter.
        mock_registry = MagicMock()
        adapter._flow_registry = mock_registry  # type: ignore[attr-defined]

        result = await adapter.create_deployment(
            flow_path="wfpkg.simple:wf_under_test",
            deployment_name="distilled-test",
        )

        # FlowRegistry.register_flow MUST have been called with the decorated
        # function and the spec's tags.
        assert mock_registry.register_flow.called, (
            "register_flow should be called when flow_path is provided"
        )
        call_args = mock_registry.register_flow.call_args
        # Tags come through either as the 3rd positional arg or as kwargs.
        # We accept either, since both convey the spec's tags as a list.
        tags = call_args.kwargs.get("tags")
        if tags is None and len(call_args.args) >= 3:
            tags = call_args.args[2]
        assert tags == ["t1", "t2"], (
            f"Expected spec tags ['t1', 't2'] to reach register_flow; "
            f"got {tags!r} (call_args={call_args!r})"
        )
        # And the underlying Prefect deployment was created.
        patched_get_client.create_deployment.assert_awaited_once()
        assert result is not None

    async def test_flow_path_invalid_format_raises(
        self, adapter: PrefectAdapter
    ) -> None:
        """flow_path without ':' separator raises PrefectError."""
        from mahavishnu.core.errors import PrefectError

        with pytest.raises(PrefectError, match=r"flow_path"):
            await adapter.create_deployment(
                flow_path="no_colon_separator",
                deployment_name="oops",
            )

    async def test_flow_path_module_not_found_raises(
        self, adapter: PrefectAdapter
    ) -> None:
        """flow_path where the module doesn't import raises PrefectError."""
        from mahavishnu.core.errors import PrefectError

        with pytest.raises(PrefectError, match=r"(?i)(import|module|not found)"):
            await adapter.create_deployment(
                flow_path="definitely_nonexistent.module.path:foo",
                deployment_name="oops",
            )

    async def test_flow_path_attr_not_decorated_raises(
        self,
        adapter: PrefectAdapter,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """flow_path where the attribute isn't decorated raises PrefectError."""
        from mahavishnu.core.errors import PrefectError

        pkg_dir = tmp_path / "plainpkg"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("")
        (pkg_dir / "plainmod.py").write_text(
            textwrap.dedent(
                """\
                from __future__ import annotations
                async def plain_fn() -> str:
                    return "not decorated"
                """
            )
        )
        monkeypatch.syspath_prepend(str(tmp_path))
        sys.modules.pop("plainpkg", None)
        sys.modules.pop("plainpkg.plainmod", None)

        with pytest.raises(PrefectError, match=r"(?i)(decorat|spec|attribute)"):
            await adapter.create_deployment(
                flow_path="plainpkg.plainmod:plain_fn",
                deployment_name="oops",
            )

    async def test_neither_flow_name_nor_flow_path_raises(
        self, adapter: PrefectAdapter
    ) -> None:
        """If both are None, PrefectError."""
        from mahavishnu.core.errors import PrefectError

        with pytest.raises(PrefectError):
            await adapter.create_deployment(deployment_name="oops")

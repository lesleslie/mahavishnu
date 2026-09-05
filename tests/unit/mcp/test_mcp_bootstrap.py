"""Coverage tests for ``mahavishnu.mcp.bootstrap``.

Focuses on the branches the existing bootstrap suites leave open:

* terminal-adapter selection fallbacks (``crow``, ``iterm2``, unknown)
* the HTTP ``/health`` / ``/healthz`` / ``/metrics`` route handlers
* the ``_register_*_block`` / ``_register_*_tools`` gating arms
  (feature flags, disabled config, missing managers, ImportError)
* the no-op durable-worker shim's protocol surface
* the A2A route mount and its execute callback

Existing companions (do not duplicate):
``test_bootstrap_terminal_adapter.py`` (tmux/mock preference),
``test_bootstrap_capability_wiring.py`` (capability block + Dhara init
failure), ``test_bootstrap_durable_wiring.py`` (worker-contract block).

Patching discipline: every patch targets an attribute on a real,
already-imported module object via ``monkeypatch.setattr``. No module is
ever installed into ``sys.modules`` — that pattern breaks later tests
that rely on string-form ``monkeypatch.setattr`` resolution.

The ``from ..x import y`` statements inside these functions resolve ``y``
via ``getattr`` on the already-cached module, so patching (or deleting)
the module attribute is what steers the branch.
"""

from __future__ import annotations

import importlib.util
import pathlib
import shutil
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.mcp import bootstrap
from mahavishnu.terminal.adapters.mock import MockTerminalAdapter
from mahavishnu.terminal.config import TerminalSettings

pytestmark = pytest.mark.unit


# =============================================================================
# Local doubles
# =============================================================================


class _RouteRecorder:
    """Minimal FastMCP stand-in that records ``custom_route`` handlers."""

    def __init__(self) -> None:
        self.routes: dict[str, Any] = {}
        self.methods: dict[str, list[str]] = {}
        self.mounted: list[tuple[Any, str]] = []

    def custom_route(self, path: str, methods: list[str] | None = None) -> Any:
        def _decorator(fn: Any) -> Any:
            self.routes[path] = fn
            self.methods[path] = methods or []
            return fn

        return _decorator

    def mount(self, app: Any, prefix: str) -> None:
        self.mounted.append((app, prefix))


def _stub_server(
    *,
    terminal_manager: Any = None,
    config: Any = None,
    app_extra: dict[str, Any] | None = None,
    fastmcp: Any = None,
) -> SimpleNamespace:
    """Build the minimal ``FastMCPServer`` surface the bootstrap helpers read."""
    app_kwargs: dict[str, Any] = {"config": config if config is not None else SimpleNamespace()}
    app_kwargs.update(app_extra or {})
    return SimpleNamespace(
        server=fastmcp if fastmcp is not None else MagicMock(),
        app=SimpleNamespace(**app_kwargs),
        terminal_manager=terminal_manager,
        mcp_client=None,
    )


# =============================================================================
# _mhv_server back-reference
# =============================================================================


def test_mhv_server_resolves_back_reference() -> None:
    """The W0 helper passes a FastMCP; the wrapper is recovered from it.

    ``FastMCPServer.__init__`` stores itself as ``server._mhv_server`` so
    per-group registrars can reach ``app`` / ``terminal_manager``.
    """
    wrapper = object()
    fastmcp = SimpleNamespace(_mhv_server=wrapper)

    assert bootstrap._mhv_server(fastmcp) is wrapper  # ty: ignore[invalid-argument-type]


# =============================================================================
# _build_crow_adapter
# =============================================================================


class _FakeCrowAdapter:
    adapter_name = "crow"

    def __init__(self, client: Any) -> None:
        self.client = client


class TestBuildCrowAdapter:
    """Crow needs both ``crow_enabled`` and a usable MCP client."""

    def test_falls_back_to_mock_when_crow_disabled(self) -> None:
        """``crow_enabled=false`` degrades to mock rather than crashing boot."""
        config = SimpleNamespace(crow_enabled=False)

        adapter = bootstrap._build_crow_adapter(config, mcp_client=None)

        assert isinstance(adapter, MockTerminalAdapter)

    def test_uses_supplied_client_without_constructing_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A caller-supplied client is passed straight to CrowTerminalAdapter."""
        from mahavishnu.terminal.adapters import crow as crow_module

        monkeypatch.setattr(crow_module, "CrowTerminalAdapter", _FakeCrowAdapter)
        sentinel = object()

        adapter = bootstrap._build_crow_adapter(
            SimpleNamespace(crow_enabled=True), mcp_client=sentinel
        )

        assert isinstance(adapter, _FakeCrowAdapter)
        assert adapter.client is sentinel

    def test_constructs_client_from_config_when_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """MCP-server boot passes ``None``; the client is built from config."""
        from mahavishnu.mcp import crow_server
        from mahavishnu.terminal.adapters import crow as crow_module

        built = MagicMock(return_value="built-client")
        monkeypatch.setattr(crow_server, "create_crow_mcp_client", built)
        monkeypatch.setattr(crow_module, "CrowTerminalAdapter", _FakeCrowAdapter)

        config = SimpleNamespace(crow_enabled=True, crow_http_host="10.0.0.5", crow_http_port=9999)
        adapter = bootstrap._build_crow_adapter(config, mcp_client=None)

        assert adapter.client == "built-client"
        built.assert_called_once_with(host="10.0.0.5", port=9999)

    def test_falls_back_to_mock_when_client_construction_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unreachable crow HTTP server degrades to mock, loudly."""
        from mahavishnu.mcp import crow_server

        monkeypatch.setattr(
            crow_server,
            "create_crow_mcp_client",
            MagicMock(side_effect=ConnectionError("crow unreachable")),
        )

        config = SimpleNamespace(crow_enabled=True, crow_http_host=None, crow_http_port=None)
        adapter = bootstrap._build_crow_adapter(config, mcp_client=None)

        assert isinstance(adapter, MockTerminalAdapter)


# =============================================================================
# _resolve_terminal_adapter fallbacks
# =============================================================================


class TestResolveTerminalAdapter:
    """Preference routing, including the removed-adapter and unknown arms."""

    def test_crow_preference_delegates_to_crow_builder(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``adapter_preference='crow'`` routes through ``_build_crow_adapter``."""
        sentinel = MockTerminalAdapter()
        called: list[Any] = []

        def _fake_builder(config: Any, mcp_client: Any) -> Any:
            called.append((config, mcp_client))
            return sentinel

        monkeypatch.setattr(bootstrap, "_build_crow_adapter", _fake_builder)
        config = TerminalSettings(adapter_preference="crow")

        adapter = bootstrap._resolve_terminal_adapter(config, mcp_client="client")

        assert adapter is sentinel
        assert called == [(config, "client")]

    def test_iterm2_preference_warns_and_falls_back_to_mock(self) -> None:
        """The removed iTerm2 adapter emits DeprecationWarning, returns mock."""
        config = TerminalSettings(adapter_preference="iterm2")

        with pytest.warns(DeprecationWarning, match="iterm2"):
            adapter = bootstrap._resolve_terminal_adapter(config, mcp_client=None)

        assert isinstance(adapter, MockTerminalAdapter)

    def test_unknown_preference_falls_back_to_mock(self) -> None:
        """An unrecognized preference must not crash MCP boot."""
        config = SimpleNamespace(adapter_preference="TeleType-33")

        adapter = bootstrap._resolve_terminal_adapter(config, mcp_client=None)

        assert isinstance(adapter, MockTerminalAdapter)

    def test_preference_matching_is_case_insensitive(self) -> None:
        """Preferences are lowercased before dispatch."""
        config = SimpleNamespace(adapter_preference="MoCk")

        adapter = bootstrap._resolve_terminal_adapter(config, mcp_client=None)

        assert isinstance(adapter, MockTerminalAdapter)


def test_init_terminal_manager_returns_none_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A terminal-manager construction failure is logged and swallowed.

    The MCP boundary must stay alive; callers treat ``None`` as "terminal
    tools unavailable" rather than aborting server boot.
    """
    monkeypatch.setattr(
        bootstrap,
        "_resolve_terminal_adapter",
        MagicMock(side_effect=RuntimeError("adapter build failed")),
    )
    server = _stub_server(config=SimpleNamespace(terminal=TerminalSettings(enabled=True)))

    assert bootstrap.init_terminal_manager(server) is None  # ty: ignore[invalid-argument-type]


# =============================================================================
# register_health_endpoint route handlers
# =============================================================================


class TestHealthEndpointHandlers:
    """The three custom routes must be registered and independently callable."""

    @pytest.fixture
    def recorder(self) -> _RouteRecorder:
        """Register the endpoints against a route-recording FastMCP double."""
        rec = _RouteRecorder()
        bootstrap.register_health_endpoint(
            _stub_server(fastmcp=rec),  # ty: ignore[invalid-argument-type]
            "9.9.9",
        )
        return rec

    def test_registers_all_three_get_routes(self, recorder: _RouteRecorder) -> None:
        """``/health``, ``/healthz`` and ``/metrics`` are all GET routes."""
        assert set(recorder.routes) == {"/health", "/healthz", "/metrics"}
        assert all(m == ["GET"] for m in recorder.methods.values())

    async def test_health_reports_service_and_version(self, recorder: _RouteRecorder) -> None:
        """``/health`` echoes the version passed at registration time."""
        response = await recorder.routes["/health"]()

        assert response.status_code == 200
        assert b'"version":"9.9.9"' in response.body
        assert b'"service":"mahavishnu"' in response.body

    async def test_healthz_is_a_bare_liveness_probe(self, recorder: _RouteRecorder) -> None:
        """``/healthz`` returns only ``{"status": "ok"}`` for k8s-style probes."""
        response = await recorder.routes["/healthz"]()

        assert response.status_code == 200
        assert response.body == b'{"status":"ok"}'

    async def test_metrics_delegates_to_prometheus_endpoint(
        self, recorder: _RouteRecorder, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``/metrics`` proxies the shared Prometheus endpoint."""
        from monitoring import metrics as metrics_module

        monkeypatch.setattr(
            metrics_module,
            "metrics_endpoint",
            AsyncMock(return_value="prometheus-payload"),
        )

        assert await recorder.routes["/metrics"]() == "prometheus-payload"


# =============================================================================
# Worker / pool registration blocks (CLI dispatch path)
# =============================================================================


class TestWorkerAndPoolBlocks:
    """Both blocks gate on an ``*_enabled`` flag and on manager presence."""

    def test_worker_block_skips_when_workers_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``workers_enabled=False`` short-circuits before importing tools."""
        from mahavishnu.mcp.tools import worker_tools

        register = MagicMock()
        monkeypatch.setattr(worker_tools, "register_worker_tools", register)
        server = _stub_server(
            config=SimpleNamespace(workers_enabled=False),
            app_extra={"_worker_manager": MagicMock()},
        )

        bootstrap._register_worker_block(server)  # ty: ignore[invalid-argument-type]

        register.assert_not_called()

    def test_worker_block_skips_when_manager_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An uninitialized worker manager is a warning, not a crash."""
        from mahavishnu.mcp.tools import worker_tools

        register = MagicMock()
        monkeypatch.setattr(worker_tools, "register_worker_tools", register)
        server = _stub_server(
            config=SimpleNamespace(workers_enabled=True), app_extra={"_worker_manager": None}
        )

        bootstrap._register_worker_block(server)  # ty: ignore[invalid-argument-type]

        register.assert_not_called()

    def test_worker_block_registers_with_manager(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With both gates open the worker tools are registered."""
        from mahavishnu.mcp.tools import worker_tools

        register = MagicMock()
        monkeypatch.setattr(worker_tools, "register_worker_tools", register)
        manager = MagicMock()
        server = _stub_server(
            config=SimpleNamespace(workers_enabled=True),
            app_extra={"_worker_manager": manager},
        )

        bootstrap._register_worker_block(server)  # ty: ignore[invalid-argument-type]

        register.assert_called_once_with(server.server, manager)

    def test_pool_block_skips_when_pools_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``pools_enabled=False`` short-circuits before importing tools."""
        from mahavishnu.mcp.tools import pool_tools

        register = MagicMock()
        monkeypatch.setattr(pool_tools, "register_pool_tools", register)
        server = _stub_server(
            config=SimpleNamespace(pools_enabled=False),
            app_extra={"pool_manager": MagicMock()},
        )

        bootstrap._register_pool_block(server)  # ty: ignore[invalid-argument-type]

        register.assert_not_called()

    def test_pool_block_skips_when_manager_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An uninitialized pool manager is a warning, not a crash."""
        from mahavishnu.mcp.tools import pool_tools

        register = MagicMock()
        monkeypatch.setattr(pool_tools, "register_pool_tools", register)
        server = _stub_server(
            config=SimpleNamespace(pools_enabled=True), app_extra={"pool_manager": None}
        )

        bootstrap._register_pool_block(server)  # ty: ignore[invalid-argument-type]

        register.assert_not_called()

    def test_pool_block_registers_with_manager(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With both gates open the pool tools are registered."""
        from mahavishnu.mcp.tools import pool_tools

        register = MagicMock()
        monkeypatch.setattr(pool_tools, "register_pool_tools", register)
        manager = MagicMock()
        server = _stub_server(
            config=SimpleNamespace(pools_enabled=True), app_extra={"pool_manager": manager}
        )

        bootstrap._register_pool_block(server)  # ty: ignore[invalid-argument-type]

        register.assert_called_once_with(server.server, manager)


# =============================================================================
# Durable-worker manager construction + no-op fallback
# =============================================================================


class TestDurableWorkerManagerFallback:
    """``_try_build_durable_worker_manager`` and the no-op shim it falls back to."""

    def test_returns_none_when_tmux_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No tmux on PATH means no durable manager (CI stays green)."""
        monkeypatch.setattr(shutil, "which", lambda _name: None)

        assert bootstrap._try_build_durable_worker_manager() is None

    def test_returns_none_when_construction_raises(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """A store/publisher construction failure degrades to ``None``."""
        from mahavishnu.workers.contract import store as store_module

        monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/tmux")
        monkeypatch.setattr(pathlib.Path, "home", staticmethod(lambda: tmp_path))
        monkeypatch.setattr(
            store_module,
            "WorkerRecordStore",
            MagicMock(side_effect=OSError("cannot create store dir")),
        )

        assert bootstrap._try_build_durable_worker_manager() is None

    def test_noop_manager_satisfies_the_protocol_surface(self) -> None:
        """The shim answers every method the contract tools call.

        Tools built on this manager surface ``state="manager_unconfigured"``;
        the point is that registration succeeds without tmux or the EventBus.
        """
        from mahavishnu.workers.contract.state import WorkerLifecycleState

        manager = bootstrap._build_noop_worker_manager()

        spawned = manager.spawn(prompt="anything")
        assert spawned.worker_id == "noop"
        assert spawned.pane == ""
        assert spawned.record.state is WorkerLifecycleState.REAPED
        assert spawned.record.model_dump() == {}
        assert spawned.record.tmux is None
        assert spawned.record.last_exit_code is None

        assert manager.status("noop") is None
        captured = manager.capture_output("noop", since_offset=0)
        assert captured.text == ""
        assert captured.next_offset == 0
        assert captured.truncated is False
        assert captured.pane_alive is False
        assert manager.send_input("noop", "hello") is False
        assert manager.cancel("noop", signal="soft") is False
        assert manager.reap("noop") is None


# =============================================================================
# OTel registration gating (shared by the block + W0 registrar)
# =============================================================================


@pytest.mark.parametrize("register_fn_name", ["_register_otel_block", "_register_otel_tools"])
class TestOtelRegistrationGating:
    """Both OTel entry points gate identically on Akosha importability."""

    def test_skips_when_find_spec_raises(
        self, monkeypatch: pytest.MonkeyPatch, register_fn_name: str
    ) -> None:
        """A broken Akosha install must not abort MCP boot."""
        from mahavishnu.mcp.tools import otel_tools

        register = MagicMock()
        monkeypatch.setattr(otel_tools, "register_otel_tools", register)
        monkeypatch.setattr(
            importlib.util, "find_spec", MagicMock(side_effect=ImportError("akosha broken"))
        )

        getattr(bootstrap, register_fn_name)(_stub_server())

        register.assert_not_called()

    def test_skips_when_akosha_absent(
        self, monkeypatch: pytest.MonkeyPatch, register_fn_name: str
    ) -> None:
        """``find_spec`` returning ``None`` means HotStore is unavailable."""
        from mahavishnu.mcp.tools import otel_tools

        register = MagicMock()
        monkeypatch.setattr(otel_tools, "register_otel_tools", register)
        monkeypatch.setattr(importlib.util, "find_spec", MagicMock(return_value=None))

        getattr(bootstrap, register_fn_name)(_stub_server())

        register.assert_not_called()

    def test_registers_when_akosha_present(
        self, monkeypatch: pytest.MonkeyPatch, register_fn_name: str
    ) -> None:
        """A resolvable spec wires the four OTel tools."""
        from mahavishnu.mcp.tools import otel_tools

        register = MagicMock()
        monkeypatch.setattr(otel_tools, "register_otel_tools", register)
        monkeypatch.setattr(importlib.util, "find_spec", MagicMock(return_value=object()))
        server = _stub_server()

        getattr(bootstrap, register_fn_name)(server)

        register.assert_called_once_with(server.server, server.app, None)

    def test_swallows_registration_failure_after_spec_found(
        self, monkeypatch: pytest.MonkeyPatch, register_fn_name: str
    ) -> None:
        """A late failure inside registration is logged, not raised."""
        from mahavishnu.mcp.tools import otel_tools

        monkeypatch.setattr(
            otel_tools,
            "register_otel_tools",
            MagicMock(side_effect=RuntimeError("hotstore handshake failed")),
        )
        monkeypatch.setattr(importlib.util, "find_spec", MagicMock(return_value=object()))

        getattr(bootstrap, register_fn_name)(_stub_server())


# =============================================================================
# Optional tool blocks: feature flags, config gates, ImportError arms
# =============================================================================


class TestOptionalToolBlockGating:
    """Optional groups degrade quietly when disabled or unimportable."""

    @pytest.mark.parametrize(
        "register_fn_name", ["_register_goal_team_block", "_register_goal_team_tools"]
    )
    def test_goal_team_respects_feature_flags(
        self, monkeypatch: pytest.MonkeyPatch, register_fn_name: str
    ) -> None:
        """Both flags must be on; otherwise registration is skipped."""
        from mahavishnu.core import feature_flags
        from mahavishnu.mcp.tools import goal_team_tools

        register = MagicMock()
        monkeypatch.setattr(goal_team_tools, "register_goal_team_tools", register)
        monkeypatch.setattr(feature_flags, "is_feature_enabled", lambda name: name == "enabled")

        getattr(bootstrap, register_fn_name)(_stub_server())

        register.assert_not_called()

    @pytest.mark.parametrize(
        "register_fn_name", ["_register_goal_team_block", "_register_goal_team_tools"]
    )
    def test_goal_team_registers_when_both_flags_on(
        self, monkeypatch: pytest.MonkeyPatch, register_fn_name: str
    ) -> None:
        """With both flags enabled the three goal-team tools register."""
        from mahavishnu.core import feature_flags
        from mahavishnu.mcp.tools import goal_team_tools

        register = MagicMock()
        monkeypatch.setattr(goal_team_tools, "register_goal_team_tools", register)
        monkeypatch.setattr(feature_flags, "is_feature_enabled", lambda _name: True)
        server = _stub_server()

        getattr(bootstrap, register_fn_name)(server)

        register.assert_called_once_with(server.server)

    @pytest.mark.parametrize(
        ("register_fn_name", "module_name", "attr_name"),
        [
            ("_register_treesitter_block", "treesitter_tools", "register_treesitter_tools"),
            ("_register_treesitter_tools", "treesitter_tools", "register_treesitter_tools"),
            (
                "_register_adapter_registry_block",
                "adapter_registry_tools",
                "register_adapter_registry_tools",
            ),
            (
                "_register_adapter_registry_tools",
                "adapter_registry_tools",
                "register_adapter_registry_tools",
            ),
            ("_register_pycharm_block", "pycharm_tools", "register_pycharm_tools"),
            ("_register_pycharm_tools", "pycharm_tools", "register_pycharm_tools"),
            ("_register_primitive_block", "primitive_tools", "register_primitive_tools"),
            ("_register_primitive_tools", "primitive_tools", "register_primitive_tools"),
        ],
    )
    def test_optional_group_swallows_import_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        register_fn_name: str,
        module_name: str,
        attr_name: str,
    ) -> None:
        """A missing registrar raises ImportError from ``from X import Y``.

        Deleting the module attribute is what makes the inline
        ``from ..mcp.tools.X import Y`` fail — the module is already cached
        in ``sys.modules``, so the import reduces to a ``getattr``. This
        reproduces "optional dependency absent" without touching
        ``sys.modules``.
        """
        import importlib

        module = importlib.import_module(f"mahavishnu.mcp.tools.{module_name}")
        monkeypatch.delattr(module, attr_name)

        # Must not raise — the block catches ImportError and logs.
        getattr(bootstrap, register_fn_name)(
            _stub_server(config=SimpleNamespace(adapter_registry=None))
        )

    @pytest.mark.parametrize(
        "register_fn_name",
        ["_register_adapter_registry_block", "_register_adapter_registry_tools"],
    )
    def test_adapter_registry_skips_when_disabled(
        self, monkeypatch: pytest.MonkeyPatch, register_fn_name: str
    ) -> None:
        """An explicit ``adapter_registry.enabled=False`` skips registration."""
        from mahavishnu.mcp.tools import adapter_registry_tools

        register = MagicMock()
        monkeypatch.setattr(adapter_registry_tools, "register_adapter_registry_tools", register)
        server = _stub_server(
            config=SimpleNamespace(adapter_registry=SimpleNamespace(enabled=False))
        )

        getattr(bootstrap, register_fn_name)(server)

        register.assert_not_called()

    @pytest.mark.parametrize(
        "register_fn_name",
        ["_register_adapter_registry_block", "_register_adapter_registry_tools"],
    )
    def test_adapter_registry_registers_when_enabled(
        self, monkeypatch: pytest.MonkeyPatch, register_fn_name: str
    ) -> None:
        """An enabled registry config registers the seven tools."""
        from mahavishnu.mcp.tools import adapter_registry_tools

        register = MagicMock()
        monkeypatch.setattr(adapter_registry_tools, "register_adapter_registry_tools", register)
        server = _stub_server(
            config=SimpleNamespace(adapter_registry=SimpleNamespace(enabled=True))
        )

        getattr(bootstrap, register_fn_name)(server)

        register.assert_called_once_with(server.server)

    @pytest.mark.parametrize(
        "register_fn_name", ["_register_openhands_block", "_register_openhands_tools"]
    )
    def test_openhands_mounts_sub_server(
        self, monkeypatch: pytest.MonkeyPatch, register_fn_name: str
    ) -> None:
        """OpenHands is mounted as a sub-server under the 'openhands' prefix."""
        from mahavishnu.mcp.tools import openhands_tools

        sub_server = object()
        monkeypatch.setattr(openhands_tools, "mcp", sub_server)
        recorder = _RouteRecorder()
        server = _stub_server(fastmcp=recorder)

        getattr(bootstrap, register_fn_name)(server)

        assert recorder.mounted == [(sub_server, "openhands")]

    @pytest.mark.parametrize(
        "register_fn_name", ["_register_openhands_block", "_register_openhands_tools"]
    )
    def test_openhands_swallows_mount_failure(
        self, monkeypatch: pytest.MonkeyPatch, register_fn_name: str
    ) -> None:
        """The OpenHands service may be down; boot must continue."""
        from mahavishnu.mcp.tools import openhands_tools

        monkeypatch.setattr(openhands_tools, "mcp", object())
        fastmcp = MagicMock()
        fastmcp.mount.side_effect = RuntimeError("openhands offline")

        getattr(bootstrap, register_fn_name)(_stub_server(fastmcp=fastmcp))

    @pytest.mark.parametrize(
        ("register_fn_name", "module_name", "attr_name", "takes_app"),
        [
            ("_register_treesitter_block", "treesitter_tools", "register_treesitter_tools", False),
            ("_register_treesitter_tools", "treesitter_tools", "register_treesitter_tools", False),
            ("_register_pycharm_block", "pycharm_tools", "register_pycharm_tools", True),
            ("_register_pycharm_tools", "pycharm_tools", "register_pycharm_tools", True),
            ("_register_primitive_block", "primitive_tools", "register_primitive_tools", False),
            ("_register_primitive_tools", "primitive_tools", "register_primitive_tools", False),
        ],
    )
    def test_optional_group_registers_when_importable(
        self,
        monkeypatch: pytest.MonkeyPatch,
        register_fn_name: str,
        module_name: str,
        attr_name: str,
        takes_app: bool,
    ) -> None:
        """When the optional registrar imports cleanly the group registers."""
        import importlib

        module = importlib.import_module(f"mahavishnu.mcp.tools.{module_name}")
        register = MagicMock()
        monkeypatch.setattr(module, attr_name, register)
        server = _stub_server()

        getattr(bootstrap, register_fn_name)(server)

        expected = (server.server, server.app) if takes_app else (server.server,)
        register.assert_called_once_with(*expected)

    def test_self_improvement_block_registers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The self-improvement group takes both the FastMCP and the app."""
        from mahavishnu.mcp.tools import self_improvement_tools

        register = MagicMock()
        monkeypatch.setattr(self_improvement_tools, "register_self_improvement_tools", register)
        server = _stub_server()

        bootstrap._register_self_improvement_block(server)  # ty: ignore[invalid-argument-type]

        register.assert_called_once_with(server.server, server.app)

    def test_clone_block_registers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The clone group takes both the FastMCP and the app."""
        from mahavishnu.mcp.tools import clone_tools

        register = MagicMock()
        monkeypatch.setattr(clone_tools, "register_clone_tools", register)
        server = _stub_server()

        bootstrap._register_clone_block(server)  # ty: ignore[invalid-argument-type]

        register.assert_called_once_with(server.server, server.app)

    def test_search_block_registers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The search group (hybrid_search + cross_repo_search) registers."""
        from mahavishnu.mcp.tools import search_tools

        register = MagicMock()
        monkeypatch.setattr(search_tools, "register_search_tools", register)
        server = _stub_server()

        bootstrap._register_search_block(server)  # ty: ignore[invalid-argument-type]

        register.assert_called_once_with(server.server)


def test_capability_block_skips_reader_when_registration_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``get_capability_result`` failure must not lose the four core tools.

    Complements ``test_bootstrap_capability_wiring.py``, which covers the
    *Dhara-init* failure arm; this pins the arm where Dhara constructs fine
    but the reader registration itself blows up.
    """
    from mahavishnu.core import bootstrap as core_bootstrap
    from mahavishnu.core import dhara_adapter
    from mahavishnu.mcp.tools import capability_tools, get_capability_result_tool

    core_register = MagicMock()
    monkeypatch.setattr(capability_tools, "register_capability_tools", core_register)
    monkeypatch.setattr(core_bootstrap, "resolve_dhara_url", MagicMock(return_value="http://d"))
    monkeypatch.setattr(dhara_adapter, "DharaClient", MagicMock())
    monkeypatch.setattr(
        get_capability_result_tool,
        "register_get_capability_result",
        MagicMock(side_effect=RuntimeError("dhara offline")),
    )
    server = _stub_server()

    bootstrap._register_capability_block(server)  # ty: ignore[invalid-argument-type]

    core_register.assert_called_once_with(server.server, server.app.config)


# =============================================================================
# A2A route mount + execute callback
# =============================================================================


class TestA2ARouteMount:
    """A2A is gated on ``a2a.enabled`` and patches ``http_app`` when on."""

    def test_skips_when_a2a_config_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No ``a2a`` config attribute means no mount attempt."""
        from mahavishnu.a2a import server as a2a_server

        build = MagicMock()
        monkeypatch.setattr(a2a_server, "build_a2a_router", build)

        bootstrap._register_a2a_routes_block(  # ty: ignore[invalid-argument-type]
            _stub_server(config=SimpleNamespace())
        )

        build.assert_not_called()

    def test_skips_when_a2a_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``a2a.enabled=False`` means no mount attempt."""
        from mahavishnu.a2a import server as a2a_server

        build = MagicMock()
        monkeypatch.setattr(a2a_server, "build_a2a_router", build)

        bootstrap._register_a2a_routes_block(  # ty: ignore[invalid-argument-type]
            _stub_server(config=SimpleNamespace(a2a=SimpleNamespace(enabled=False)))
        )

        build.assert_not_called()

    def test_patches_http_app_and_mounts_both_sub_apps(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The patched ``http_app`` mounts A2A *and* the durable webhooks.

        Mount order matters: ``mount_durable_webhooks`` must run so
        ``/durable-webhooks/webhook`` is not swallowed by the A2A catch-all.
        """
        from mahavishnu import webhooks
        from mahavishnu.a2a import server as a2a_server

        a2a_app = object()
        monkeypatch.setattr(a2a_server, "build_a2a_router", MagicMock(return_value=a2a_app))
        mount_webhooks = MagicMock()
        monkeypatch.setattr(webhooks, "mount_durable_webhooks", mount_webhooks)

        starlette_app = MagicMock()
        original_http_app = MagicMock(return_value=starlette_app)
        server = _stub_server(
            config=SimpleNamespace(
                a2a=SimpleNamespace(enabled=True),
                auth=SimpleNamespace(enabled=True, secret="s3cret"),
            ),
            app_extra={"_worker_manager": None},
        )
        server.server.http_app = original_http_app

        bootstrap._register_a2a_routes_block(server)  # ty: ignore[invalid-argument-type]

        assert server.server.http_app is not original_http_app
        result = server.server.http_app(path="/mcp")

        assert result is starlette_app
        starlette_app.mount.assert_called_once_with("/", a2a_app)
        mount_webhooks.assert_called_once_with(starlette_app)
        assert original_http_app.call_args.kwargs["path"] == "/mcp"

    def test_swallows_build_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An A2A build failure leaves ``http_app`` untouched."""
        from mahavishnu.a2a import server as a2a_server

        monkeypatch.setattr(
            a2a_server,
            "build_a2a_router",
            MagicMock(side_effect=RuntimeError("a2a unavailable")),
        )
        server = _stub_server(
            config=SimpleNamespace(a2a=SimpleNamespace(enabled=True), auth=None),
            app_extra={"_worker_manager": None},
        )
        original = server.server.http_app

        bootstrap._register_a2a_routes_block(server)  # ty: ignore[invalid-argument-type]

        assert server.server.http_app is original


class TestResolveA2AAuthToken:
    """The shared secret is only returned when auth is enabled AND set."""

    @pytest.mark.parametrize(
        "auth_config",
        [
            None,
            SimpleNamespace(enabled=False, secret="s"),
            SimpleNamespace(enabled=True, secret=None),
            SimpleNamespace(enabled=True, secret=""),
        ],
    )
    def test_returns_none_without_usable_secret(self, auth_config: Any) -> None:
        """Missing, disabled, or empty-secret auth yields ``None``."""
        server = _stub_server(config=SimpleNamespace(auth=auth_config))

        assert bootstrap._resolve_a2a_auth_token(server) is None  # ty: ignore[invalid-argument-type]

    def test_returns_secret_when_enabled_and_set(self) -> None:
        """Enabled auth with a secret returns that secret verbatim."""
        server = _stub_server(
            config=SimpleNamespace(auth=SimpleNamespace(enabled=True, secret="hunter2"))
        )

        assert bootstrap._resolve_a2a_auth_token(server) == "hunter2"  # ty: ignore[invalid-argument-type]


class TestMakeA2AExecuteFn:
    """The A2A callback fans out to the first registered worker."""

    async def test_fails_without_worker_manager(self) -> None:
        """No manager yields a FAILED WorkerResult, not an exception."""
        from mahavishnu.core.status import WorkerStatus

        execute = bootstrap._make_a2a_execute_fn(None)
        result = await execute({"prompt": "hi"})

        assert result.status is WorkerStatus.FAILED
        assert result.worker_id == "none"
        assert result.error == "No worker manager available"

    async def test_fails_when_no_workers_registered(self) -> None:
        """An empty worker roster yields a FAILED WorkerResult."""
        from mahavishnu.core.status import WorkerStatus

        manager = MagicMock()
        manager.list_worker_ids = MagicMock(return_value=[])

        execute = bootstrap._make_a2a_execute_fn(manager)
        result = await execute({"prompt": "hi"})

        assert result.status is WorkerStatus.FAILED
        assert result.error == "No workers registered"

    async def test_dispatches_to_first_worker(self) -> None:
        """The task is handed to the first worker id in the roster."""
        manager = MagicMock()
        manager.list_worker_ids = MagicMock(return_value=["w-1", "w-2"])
        manager.execute_task = AsyncMock(return_value="done")

        execute = bootstrap._make_a2a_execute_fn(manager)
        task = {"prompt": "hi"}

        assert await execute(task) == "done"
        manager.execute_task.assert_awaited_once_with("w-1", task)


# =============================================================================
# W0 per-group registrars with distinct gating from their CLI counterparts
# =============================================================================


class TestW0Registrars:
    """The ``REGISTRATION_MAP`` entries used by ``apply_tool_profile``."""

    def test_terminal_tools_noop_without_manager(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A ``None`` terminal manager short-circuits before importing tools."""
        from mahavishnu.mcp.tools import terminal_tools

        register = MagicMock()
        monkeypatch.setattr(terminal_tools, "register_terminal_tools", register)

        bootstrap._register_terminal_tools(  # ty: ignore[invalid-argument-type]
            _stub_server(terminal_manager=None)
        )

        register.assert_not_called()

    def test_terminal_tools_registers_with_manager(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A present manager is forwarded along with the MCP client."""
        from mahavishnu.mcp.tools import terminal_tools

        register = MagicMock()
        monkeypatch.setattr(terminal_tools, "register_terminal_tools", register)
        manager = MagicMock()
        server = _stub_server(terminal_manager=manager)

        bootstrap._register_terminal_tools(server)  # ty: ignore[invalid-argument-type]

        register.assert_called_once_with(server.server, manager, None)

    @pytest.mark.parametrize("register_fn_name", ["_register_worker_tools", "_register_pool_tools"])
    def test_manager_gated_registrars_skip_when_disabled(
        self, monkeypatch: pytest.MonkeyPatch, register_fn_name: str
    ) -> None:
        """Both W0 manager-gated registrars honour their ``*_enabled`` flag."""
        from mahavishnu.mcp.tools import pool_tools, worker_tools

        worker_register = MagicMock()
        pool_register = MagicMock()
        monkeypatch.setattr(worker_tools, "register_worker_tools", worker_register)
        monkeypatch.setattr(pool_tools, "register_pool_tools", pool_register)
        server = _stub_server(
            config=SimpleNamespace(workers_enabled=False, pools_enabled=False),
            app_extra={"_worker_manager": MagicMock(), "pool_manager": MagicMock()},
        )

        getattr(bootstrap, register_fn_name)(server)

        worker_register.assert_not_called()
        pool_register.assert_not_called()

    @pytest.mark.parametrize(
        ("register_fn_name", "manager_attr"),
        [
            ("_register_worker_tools", "_worker_manager"),
            ("_register_pool_tools", "pool_manager"),
        ],
    )
    def test_manager_gated_registrars_skip_when_manager_missing(
        self, monkeypatch: pytest.MonkeyPatch, register_fn_name: str, manager_attr: str
    ) -> None:
        """A ``None`` manager warns and skips instead of raising."""
        from mahavishnu.mcp.tools import pool_tools, worker_tools

        worker_register = MagicMock()
        pool_register = MagicMock()
        monkeypatch.setattr(worker_tools, "register_worker_tools", worker_register)
        monkeypatch.setattr(pool_tools, "register_pool_tools", pool_register)
        server = _stub_server(
            config=SimpleNamespace(workers_enabled=True, pools_enabled=True),
            app_extra={manager_attr: None},
        )

        getattr(bootstrap, register_fn_name)(server)

        worker_register.assert_not_called()
        pool_register.assert_not_called()

    @pytest.mark.parametrize(
        ("register_fn_name", "manager_attr", "module_name", "attr_name"),
        [
            (
                "_register_worker_tools",
                "_worker_manager",
                "worker_tools",
                "register_worker_tools",
            ),
            ("_register_pool_tools", "pool_manager", "pool_tools", "register_pool_tools"),
        ],
    )
    def test_manager_gated_registrars_register_when_wired(
        self,
        monkeypatch: pytest.MonkeyPatch,
        register_fn_name: str,
        manager_attr: str,
        module_name: str,
        attr_name: str,
    ) -> None:
        """With flag on and manager present the group is registered."""
        import importlib

        module = importlib.import_module(f"mahavishnu.mcp.tools.{module_name}")
        register = MagicMock()
        monkeypatch.setattr(module, attr_name, register)
        manager = MagicMock()
        server = _stub_server(
            config=SimpleNamespace(workers_enabled=True, pools_enabled=True),
            app_extra={manager_attr: manager},
        )

        getattr(bootstrap, register_fn_name)(server)

        register.assert_called_once_with(server.server, manager)

    def test_worker_contract_registrar_prefers_wired_manager(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A manager already stashed on the app is reused, not replaced."""
        from mahavishnu.mcp.tools import worker_contract_tools

        register = MagicMock()
        monkeypatch.setattr(worker_contract_tools, "register_worker_contract_tools", register)
        manager = MagicMock()
        server = _stub_server(app_extra={"_durable_worker_manager": manager})

        bootstrap._register_worker_contract_tools(server)  # ty: ignore[invalid-argument-type]

        register.assert_called_once_with(server.server, manager)

    def test_worker_contract_registrar_falls_back_to_noop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With no wired manager the no-op shim is substituted."""
        from mahavishnu.mcp.tools import worker_contract_tools

        register = MagicMock()
        monkeypatch.setattr(worker_contract_tools, "register_worker_contract_tools", register)
        server = _stub_server(app_extra={"_durable_worker_manager": None})

        bootstrap._register_worker_contract_tools(server)  # ty: ignore[invalid-argument-type]

        register.assert_called_once()
        substituted = register.call_args.args[1]
        assert substituted.status("anything") is None

    @pytest.mark.parametrize(
        ("register_fn_name", "module_name", "attr_name", "takes_app"),
        [
            ("_register_health_tools", "health_tools", "register_health_tools", True),
            (
                "_register_ecosystem_tools",
                "ecosystem_tools",
                "register_ecosystem_tools",
                False,
            ),
            ("_register_workflow_tools", "workflow_tools", "register_workflow_tools", False),
            ("_register_webhook_tools", "webhook_tools", "register_webhook_tools", False),
            (
                "_register_session_buddy_tools",
                "session_buddy_tools",
                "register_session_buddy_tools",
                None,
            ),
            (
                "_register_git_analytics_tools",
                "git_analytics",
                "register_git_analytics_tools",
                "client",
            ),
            (
                "_register_repository_messaging_tools",
                "repository_messaging_tools",
                "register_repository_messaging_tools",
                None,
            ),
            (
                "_register_self_improvement_tools",
                "self_improvement_tools",
                "register_self_improvement_tools",
                True,
            ),
            ("_register_clone_tools", "clone_tools", "register_clone_tools", True),
            ("_register_search_tools", "search_tools", "register_search_tools", False),
            (
                "_register_capability_tools",
                "capability_tools",
                "register_capability_tools",
                "capability",
            ),
        ],
    )
    def test_ungated_registrars_forward_expected_arguments(
        self,
        monkeypatch: pytest.MonkeyPatch,
        register_fn_name: str,
        module_name: str,
        attr_name: str,
        takes_app: object,
    ) -> None:
        """Each always-on registrar forwards the FastMCP plus its extras."""
        import importlib

        from mahavishnu.core import bootstrap as core_bootstrap

        module = importlib.import_module(f"mahavishnu.mcp.tools.{module_name}")
        register = MagicMock()
        monkeypatch.setattr(module, attr_name, register)
        # The capability registrar also reaches for Dhara; make that a no-op
        # so this test stays scoped to argument forwarding.
        monkeypatch.setattr(
            core_bootstrap,
            "resolve_dhara_url",
            MagicMock(side_effect=RuntimeError("dhara unconfigured")),
        )
        server = _stub_server()

        getattr(bootstrap, register_fn_name)(server)

        register.assert_called_once()
        assert register.call_args.args[0] is server.server


# =============================================================================
# Core-integration + worker/pool dispatchers (CLI startup path)
# =============================================================================


class TestCoreIntegrationDispatcher:
    """``_register_core_integration_tools`` gates each group on ``methods_set``."""

    @pytest.fixture
    def registrars(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
        """Replace all four core-integration registrars with recorders."""
        from mahavishnu.mcp.tools import (
            git_analytics,
            repository_messaging_tools,
            session_buddy_tools,
            terminal_tools,
        )

        mocks: dict[str, MagicMock] = {}
        for module, attr, label in (
            (terminal_tools, "register_terminal_tools", "terminal"),
            (session_buddy_tools, "register_session_buddy_tools", "session_buddy"),
            (git_analytics, "register_git_analytics_tools", "git"),
            (
                repository_messaging_tools,
                "register_repository_messaging_tools",
                "messaging",
            ),
        ):
            mock = MagicMock()
            monkeypatch.setattr(module, attr, mock)
            mocks[label] = mock
        return mocks

    async def test_empty_methods_set_registers_nothing(
        self, registrars: dict[str, MagicMock]
    ) -> None:
        """An empty profile means none of the four groups register."""
        await bootstrap._register_core_integration_tools(  # ty: ignore[invalid-argument-type]
            _stub_server(terminal_manager=MagicMock()), set()
        )

        for mock in registrars.values():
            mock.assert_not_called()

    async def test_terminal_group_requires_both_gate_and_manager(
        self, registrars: dict[str, MagicMock]
    ) -> None:
        """The terminal group needs the profile entry *and* a live manager."""
        await bootstrap._register_core_integration_tools(  # ty: ignore[invalid-argument-type]
            _stub_server(terminal_manager=None), {"_register_terminal_tools"}
        )

        registrars["terminal"].assert_not_called()

    async def test_registers_every_gated_group(self, registrars: dict[str, MagicMock]) -> None:
        """With all four entries present every group registers exactly once."""
        manager = MagicMock()
        server = _stub_server(terminal_manager=manager)

        await bootstrap._register_core_integration_tools(  # ty: ignore[invalid-argument-type]
            server,
            {
                "_register_terminal_tools",
                "_register_session_buddy_tools",
                "_register_git_analytics_tools",
                "_register_repository_messaging_tools",
            },
        )

        registrars["terminal"].assert_called_once_with(server.server, manager, None)
        registrars["session_buddy"].assert_called_once_with(server.server, server.app, None)
        registrars["git"].assert_called_once_with(server.server, None)
        registrars["messaging"].assert_called_once_with(server.server, server.app, None)


class TestWorkerPoolDispatcher:
    """``_register_worker_pool_tools`` fans out to four independent blocks."""

    @pytest.fixture
    def blocks(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
        """Replace the four per-block registrars with recorders."""
        mocks: dict[str, MagicMock] = {}
        for name in (
            "_register_worker_block",
            "_register_worker_contract_block",
            "_register_pool_block",
            "_register_otel_block",
        ):
            mock = MagicMock()
            monkeypatch.setattr(bootstrap, name, mock)
            mocks[name] = mock
        return mocks

    async def test_empty_methods_set_dispatches_nothing(self, blocks: dict[str, MagicMock]) -> None:
        """Each ``in methods_set`` check is a precondition guard, not a branch."""
        await bootstrap._register_worker_pool_tools(_stub_server(), set())  # ty: ignore[invalid-argument-type]

        for mock in blocks.values():
            mock.assert_not_called()

    @pytest.mark.parametrize(
        ("method_name", "block_name"),
        [
            ("_register_worker_tools", "_register_worker_block"),
            ("_register_worker_contract_tools", "_register_worker_contract_block"),
            ("_register_pool_tools", "_register_pool_block"),
            ("_register_otel_tools", "_register_otel_block"),
        ],
    )
    async def test_each_entry_dispatches_only_its_block(
        self, blocks: dict[str, MagicMock], method_name: str, block_name: str
    ) -> None:
        """A single profile entry activates exactly one block."""
        server = _stub_server()

        await bootstrap._register_worker_pool_tools(server, {method_name})  # ty: ignore[invalid-argument-type]

        blocks[block_name].assert_called_once_with(server)
        for name, mock in blocks.items():
            if name != block_name:
                mock.assert_not_called()


# =============================================================================
# register_profile_tools orchestration
# =============================================================================


async def test_register_profile_tools_registers_mandatory_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The four always-on groups register regardless of ``methods_set``.

    ``register_profile_tools`` is the CLI startup entry point; health,
    ecosystem, workflow, and webhook tools are unconditional there.
    """
    from mahavishnu.mcp.tools import (
        ecosystem_tools,
        health_tools,
        webhook_tools,
        workflow_tools,
    )

    calls: list[str] = []
    for module, attr, label in (
        (health_tools, "register_health_tools", "health"),
        (ecosystem_tools, "register_ecosystem_tools", "ecosystem"),
        (workflow_tools, "register_workflow_tools", "workflow"),
        (webhook_tools, "register_webhook_tools", "webhook"),
    ):
        monkeypatch.setattr(module, attr, lambda *_a, _label=label, **_kw: calls.append(_label))

    server = _stub_server(config=SimpleNamespace(a2a=None))
    server.register_worktree_tools = AsyncMock()

    # Empty methods_set: every gated group is skipped, mandatory ones still run.
    await bootstrap.register_profile_tools(server, set())  # ty: ignore[invalid-argument-type]

    assert calls == ["health", "ecosystem", "workflow", "webhook"]
    server.register_worktree_tools.assert_awaited_once()


async def test_register_profile_tools_dispatches_gated_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A populated ``methods_set`` dispatches the matching optional blocks."""
    from mahavishnu.mcp.tools import (
        clone_tools,
        ecosystem_tools,
        health_tools,
        search_tools,
        webhook_tools,
        workflow_tools,
    )

    for module, attr in (
        (health_tools, "register_health_tools"),
        (ecosystem_tools, "register_ecosystem_tools"),
        (workflow_tools, "register_workflow_tools"),
        (webhook_tools, "register_webhook_tools"),
    ):
        monkeypatch.setattr(module, attr, MagicMock())

    clone_register = MagicMock()
    search_register = MagicMock()
    monkeypatch.setattr(clone_tools, "register_clone_tools", clone_register)
    monkeypatch.setattr(search_tools, "register_search_tools", search_register)

    server = _stub_server(config=SimpleNamespace(a2a=None))
    server.register_worktree_tools = AsyncMock()

    await bootstrap.register_profile_tools(  # ty: ignore[invalid-argument-type]
        server, {"_register_clone_tools", "_register_search_tools"}
    )

    clone_register.assert_called_once()
    search_register.assert_called_once()

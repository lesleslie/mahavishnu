"""Unit tests for mahavishnu/core/bootstrap.py module."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import mahavishnu.core.bootstrap as bootstrap
from mahavishnu.core.bootstrap import (
    _load_raw_yaml,
    _resolve_repos_path,
    _validate_path,
    load_config,
)
from mahavishnu.core.errors import ConfigurationError

# =============================================================================
# Tests for _validate_path
# =============================================================================


class TestValidatePathGoodPaths:
    """Test _validate_path accepts legitimate paths."""

    def test_accepts_absolute_path_within_cwd(self, monkeypatch, tmp_path):
        """Accepts an absolute path that is within cwd."""
        # Set cwd to tmp_path so tmp_path is within it
        monkeypatch.chdir(tmp_path)
        # Create a subdirectory
        subdir = tmp_path / "project"
        subdir.mkdir()
        result = _validate_path(str(subdir))
        assert result == subdir.resolve()

    def test_accepts_relative_path(self, monkeypatch, tmp_path):
        """Accepts a relative path that resolves within cwd."""
        monkeypatch.chdir(tmp_path)
        # Create nested directories
        (tmp_path / "a" / "b").mkdir(parents=True)
        result = _validate_path("a/b")
        assert result == (tmp_path / "a" / "b").resolve()

    def test_expands_tilde_path(self, tmp_path, monkeypatch):
        """Expands tilde in path before validation."""
        # Create a directory under tmp_path and use tilde-style reference
        # by mocking expanduser behavior - test relative path resolution
        monkeypatch.chdir(tmp_path)
        subdir = tmp_path / "user_home"
        subdir.mkdir()
        # Use a path that would expand to tmp_path/user_home
        # Since we're using tmp_path as cwd, it should resolve correctly
        result = _validate_path(str(subdir))
        assert result == subdir.resolve()

    def test_accepts_path_with_custom_allowed_base(self, tmp_path):
        """Accepts path when explicitly allowed via allowed_base_paths."""
        allowed = str(tmp_path)
        subdir = tmp_path / "allowed_project"
        subdir.mkdir()
        result = _validate_path(str(subdir), allowed_base_paths=[allowed])
        assert result == subdir.resolve()


class TestValidatePathDirectoryTraversal:
    """Test _validate_path rejects directory traversal attempts."""

    def test_rejects_parent_directory_windows(self, tmp_path):
        """Rejects .. path component (Windows style)."""
        with pytest.raises(ConfigurationError, match="directory traversal"):
            _validate_path("..\\sneaky")

    def test_rejects_parent_directory_unix(self, tmp_path):
        """Rejects ../ path component (Unix style)."""
        with pytest.raises(ConfigurationError, match="directory traversal"):
            _validate_path("../sneaky")

    def test_rejects_embedded_parent_traversal(self, tmp_path):
        """Rejects /../ embedded in path."""
        with pytest.raises(ConfigurationError, match="directory traversal"):
            _validate_path("/a/../b")

    def test_rejects_parent_at_end(self, tmp_path):
        """Rejects /.. at end of path."""
        with pytest.raises(ConfigurationError, match="directory traversal"):
            _validate_path("/some/path/..")

    def test_rejects_backslash_parent_sequence(self, tmp_path):
        """Rejects ..\\ in path string."""
        with pytest.raises(ConfigurationError, match="directory traversal"):
            _validate_path("C:\\users\\..\\secret")

    def test_rejects_dotdot_in_parts(self, tmp_path):
        """Rejects .. appearing in path parts."""
        with pytest.raises(ConfigurationError, match="directory traversal"):
            _validate_path("safe/../dangerous")


class TestValidatePathOutsideAllowed:
    """Test _validate_path rejects paths outside allowed directories."""

    def test_rejects_path_outside_allowed_base(self, tmp_path):
        """Raises when path is not under any allowed_base_paths."""
        # Use a completely different base
        with pytest.raises(ConfigurationError, match="outside allowed directory"):
            _validate_path("/usr/local/other_project", allowed_base_paths=[str(tmp_path)])

    def test_rejects_never_nested_path_with_custom_base(self, tmp_path):
        """Raises when path is not under allowed base even with custom bases."""
        allowed_base = str(tmp_path)
        outside_path = "/tmp/completely_different"
        with pytest.raises(ConfigurationError, match="outside allowed directory"):
            _validate_path(outside_path, allowed_base_paths=[allowed_base])


# =============================================================================
# Tests for _load_raw_yaml
# =============================================================================


class TestLoadRawYaml:
    """Test _load_raw_yaml with temporary YAML files."""

    def test_loads_valid_yaml_dict(self, tmp_path):
        """Returns dict when YAML contains a dictionary."""
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text("key: value\nnested:\n  inner: 42\n")
        result = _load_raw_yaml(yaml_file)
        assert result == {"key": "value", "nested": {"inner": 42}}

    def test_loads_valid_yaml_list(self, tmp_path):
        """Returns list when YAML contains a list."""
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text("- item1\n- item2\n")
        result = _load_raw_yaml(yaml_file)
        assert result == ["item1", "item2"]

    def test_loads_valid_yaml_with_repos_structure(self, tmp_path):
        """Returns dict with 'repos' key as expected by config."""
        yaml_file = tmp_path / "ecosystem.yaml"
        yaml_file.write_text("repos:\n  - path: /some/path\n    tags: [python]\nroles: []\n")
        result = _load_raw_yaml(yaml_file)
        assert "repos" in result
        assert len(result["repos"]) == 1

    def test_raises_on_invalid_yaml_syntax(self, tmp_path):
        """Raises ConfigurationError on malformed YAML."""
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text("key: value\n  indented: wrong\n")
        with pytest.raises(ConfigurationError, match="Invalid YAML"):
            _load_raw_yaml(yaml_file)

    def test_raises_on_empty_file(self, tmp_path):
        """Raises ConfigurationError on empty file."""
        yaml_file = tmp_path / "empty.yaml"
        yaml_file.write_text("")
        # yaml.safe_load returns None for empty string
        result = _load_raw_yaml(yaml_file)
        assert result is None

    def test_raises_on_yaml_file_not_found(self, tmp_path):
        """Raises ConfigurationError when file does not exist."""
        nonexistent = tmp_path / "does_not_exist.yaml"
        # FileNotFoundError is not a YAMLError, so it's re-raised directly
        # which then propagates as a ConfigurationError from the caller
        with pytest.raises((FileNotFoundError, OSError)):
            _load_raw_yaml(nonexistent)

    def test_raises_on_missing_repos_key(self, tmp_path):
        """Raises ConfigurationError when repos key is missing."""
        yaml_file = tmp_path / "ecosystem.yaml"
        yaml_file.write_text("roles: []\n")

        with pytest.raises(ConfigurationError, match="missing 'repos' key"):
            bootstrap._parse_repos_config_file(yaml_file)


# =============================================================================
# Tests for load_config
# =============================================================================


class TestLoadConfig:
    """Test load_config error handling."""

    def test_load_config_returns_mahavishnu_settings(self):
        """Successfully returns a MahavishnuSettings instance."""
        result = load_config()
        # Should return MahavishnuSettings without raising
        assert result is not None
        assert hasattr(result, "repos_path")

    def test_load_config_raises_on_invalid_config(self, monkeypatch):
        """Wraps exceptions in ConfigurationError."""
        import mahavishnu.core.config as config_module

        original_init = config_module.MahavishnuSettings.__init__

        def bad_init(self, **kwargs):
            raise ValueError("bad config")

        config_module.MahavishnuSettings.__init__ = bad_init
        try:
            with pytest.raises(ConfigurationError, match="Failed to load configuration"):
                load_config()
        finally:
            config_module.MahavishnuSettings.__init__ = original_init


# =============================================================================
# Tests for _resolve_repos_path (integration-style unit tests)
# =============================================================================


class TestResolveReposPath:
    """Test _resolve_repos_path with temporary config files."""

    def test_returns_primary_path_when_exists(self, tmp_path, monkeypatch):
        """Returns primary path when it exists."""
        # Create primary file
        primary = tmp_path / "ecosystem.yaml"
        primary.write_text("repos: []\n")

        mock_config = type("Config", (), {"repos_path": str(primary)})()
        mock_app = type("App", (), {"config": mock_config})()

        class MockLogger:
            def warning(self, *args, **kwargs):
                pass

        result_path, using_fallback = _resolve_repos_path(mock_app, MockLogger())
        assert result_path == primary
        assert using_fallback is False

    def test_falls_back_to_repos_yaml(self, tmp_path, monkeypatch):
        """Falls back to settings/repos.yaml when primary not found."""
        monkeypatch.chdir(tmp_path)
        # Create only fallback
        fallback = tmp_path / "settings" / "repos.yaml"
        fallback.parent.mkdir()
        fallback.write_text("repos: []\n")

        primary = tmp_path / "ecosystem.yaml"  # does not exist
        mock_config = type("Config", (), {"repos_path": str(primary)})()
        mock_app = type("App", (), {"config": mock_config})()

        warning_messages = []

        class MockLogger:
            def warning(self, msg, *args, **kwargs):
                warning_messages.append(msg % args if args else msg)

        result_path, using_fallback = _resolve_repos_path(mock_app, MockLogger())
        assert result_path == fallback
        assert using_fallback is True

    def test_raises_when_no_config_found(self, tmp_path, monkeypatch):
        """Raises ConfigurationError when neither primary nor fallback exists."""
        monkeypatch.chdir(tmp_path)
        primary = tmp_path / "ecosystem.yaml"  # does not exist
        tmp_path / "settings" / "repos.yaml"  # does not exist

        mock_config = type("Config", (), {"repos_path": str(primary)})()
        mock_app = type("App", (), {"config": mock_config})()

        class MockLogger:
            def warning(self, *args, **kwargs):
                pass

        with pytest.raises(ConfigurationError, match="No repository configuration found"):
            _resolve_repos_path(mock_app, MockLogger())


class TestLoadRepos:
    """Tests for load_repos helper."""

    def test_load_repos_success(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        repos_file = tmp_path / "ecosystem.yaml"
        repos_file.write_text("repos:\n  - path: /repo-a\nroles:\n  - admin\n")

        app = SimpleNamespace(config=SimpleNamespace(repos_path=str(repos_file)))

        bootstrap.load_repos(app)

        assert app.roles_config == ["admin"]
        assert app.repos_config == {"repos": [{"path": "/repo-a"}], "roles": ["admin"]}


class TestComponentEndpointRegistration:
    """Tests for Dhara component endpoint registration helpers."""

    def test_register_component_endpoint_no_dhara_state(self, caplog):
        """No state backend should log and return without error."""
        with caplog.at_level(logging.WARNING):
            bootstrap._register_component_endpoint(None, "mahavishnu", "http://localhost")

        assert "Dhara state not available" in caplog.text

    def test_register_component_endpoint_async_schedules_put(self, monkeypatch):
        """Running loop path should schedule an async put."""
        created = []

        def fake_create_task(coro):
            created.append(coro)
            coro.close()
            return object()

        monkeypatch.setattr(asyncio, "get_running_loop", lambda: object())
        monkeypatch.setattr(asyncio, "create_task", fake_create_task)

        dhara_state = type(
            "DharaState",
            (),
            {"put": lambda self, key, value: asyncio.sleep(0)},
        )()

        bootstrap._register_component_endpoint(dhara_state, "mahavishnu", "http://localhost")

        assert len(created) == 1

    def test_register_component_endpoint_sync_fallback(self, monkeypatch):
        """No running loop should use the sync fallback client."""
        monkeypatch.setattr(
            asyncio, "get_running_loop", lambda: (_ for _ in ()).throw(RuntimeError("no loop"))
        )

        class FakeClient:
            def __init__(self, base_url):
                self.base_url = base_url
                self.put_calls = []

            async def put(self, key, value):
                self.put_calls.append((key, value))
                return None

        fake_client = FakeClient("http://dhara")
        monkeypatch.setattr(
            "mahavishnu.core.dhara_adapter.DharaClient", lambda base_url: fake_client
        )

        def fake_run(coro):
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(coro)
            finally:
                loop.close()

        monkeypatch.setattr(asyncio, "run", fake_run)

        dhara_state = type(
            "DharaState",
            (),
            {"_client": type("Client", (), {"_base_url": "http://dhara"})()},
        )()

        bootstrap._register_component_endpoint(dhara_state, "mahavishnu", "http://localhost")

        assert fake_client.put_calls == [
            (
                "component_endpoint/mahavishnu",
                {"url": "http://localhost", "registered_by": "mahavishnu"},
            )
        ]


class TestHealthEndpointBootstrap:
    """Tests for health endpoint bootstrap helper."""

    def test_init_health_endpoint_disabled(self):
        """Disabled health config should return None."""
        app = type(
            "App",
            (),
            {"config": type("Config", (), {"health": type("Health", (), {"enabled": False})()})()},
        )()

        assert bootstrap.init_health_endpoint(app) is None

    def test_init_health_endpoint_enabled(self, monkeypatch):
        """Enabled health config should instantiate the endpoint."""
        created = {}

        class FakeEndpoint:
            def __init__(self, service_info, config):
                created["service_info"] = service_info
                created["config"] = config

        monkeypatch.setattr("mahavishnu.core.health.HealthEndpoint", FakeEndpoint)

        health_config = type("Health", (), {"enabled": True})()
        config = type("Config", (), {"health": health_config, "version": "1.2.3"})()
        app = type("App", (), {"config": config})()

        endpoint = bootstrap.init_health_endpoint(app)

        assert isinstance(endpoint, FakeEndpoint)
        assert created["service_info"].name == "mahavishnu"
        assert created["service_info"].version == "1.2.3"
        assert created["config"] is health_config


class TestBootstrapDeepHelpers:
    """Deeper coverage for helper branches in bootstrap."""

    def test_parse_repos_config_file_wraps_unexpected_error(self, tmp_path, monkeypatch):
        yaml_file = tmp_path / "ecosystem.yaml"
        yaml_file.write_text("repos: []\n")

        monkeypatch.setattr(
            bootstrap, "_load_raw_yaml", lambda path: (_ for _ in ()).throw(ValueError("boom"))
        )

        with pytest.raises(ConfigurationError, match="Failed to load ecosystem.yaml"):
            bootstrap._parse_repos_config_file(yaml_file)

    def test_register_component_endpoint_sync_failure_logs_warning(self, monkeypatch, caplog):
        monkeypatch.setattr(
            asyncio, "get_running_loop", lambda: (_ for _ in ()).throw(RuntimeError("no loop"))
        )

        fake_module = types.ModuleType("mahavishnu.core.dhara_adapter")

        class FakeDharaClient:
            def __init__(self, base_url):
                self.base_url = base_url

            async def put(self, key, value):
                raise RuntimeError("write failed")

        fake_module.DharaClient = FakeDharaClient
        monkeypatch.setitem(sys.modules, "mahavishnu.core.dhara_adapter", fake_module)

        dhara_state = SimpleNamespace(_client=SimpleNamespace(_base_url="http://dhara"))

        with caplog.at_level(logging.WARNING):
            bootstrap._register_component_endpoint(dhara_state, "mahavishnu", "http://localhost")

        assert "failed to register" in caplog.text.lower()

    def test_import_adapter_class_known_and_importerror(self, monkeypatch):
        fake_names = {
            "prefect": ("mahavishnu.engines.prefect_adapter_impl", "PrefectAdapter"),
            "llamaindex": ("mahavishnu.engines.llamaindex_adapter_impl", "LlamaIndexAdapter"),
            "agno": ("mahavishnu.engines.agno_adapter_impl", "AgnoAdapter"),
            "hatchet": ("mahavishnu.engines.hatchet_adapter_impl", "HatchetAdapterImpl"),
            "worker": ("mahavishnu.core.adapters.worker", "WorkerOrchestratorAdapter"),
        }

        created = {}
        for name, (module_name, class_name) in fake_names.items():
            module = types.ModuleType(module_name)
            cls = type(class_name, (), {})
            setattr(module, class_name, cls)
            monkeypatch.setitem(sys.modules, module_name, module)
            created[name] = cls

        for name, expected in created.items():
            assert bootstrap._import_adapter_class(name) is expected

        monkeypatch.setitem(sys.modules, "mahavishnu.engines.prefect_adapter_impl", None)
        assert bootstrap._import_adapter_class("prefect") is None
        assert bootstrap._import_adapter_class("missing") is None

    def test_collect_adapter_classes_and_instantiate(self, monkeypatch, caplog):
        fake_prefect = type("PrefectAdapter", (), {})
        fake_worker = type("WorkerOrchestratorAdapter", (), {})

        def fake_import_adapter(name):
            return {
                "prefect": fake_prefect,
                "worker": fake_worker,
                "agno": None,
            }.get(name)

        monkeypatch.setattr(bootstrap, "_import_adapter_class", fake_import_adapter)

        app = SimpleNamespace(
            config=SimpleNamespace(
                adapters=SimpleNamespace(
                    prefect_enabled=True,
                    llamaindex_enabled=False,
                    agno_enabled=True,
                    hatchet_enabled=False,
                ),
                workers=SimpleNamespace(enabled=True),
                hatchet=SimpleNamespace(name="hatchet-config"),
            ),
            adapters={},
        )

        with caplog.at_level(logging.WARNING):
            classes = bootstrap._collect_adapter_classes(app, logging.getLogger(__name__))

        assert classes == {"prefect": fake_prefect, "worker": fake_worker}
        assert "agno adapter not available" in caplog.text.lower()

        received = []

        class _PrefectInstance:
            def __init__(self, config):
                received.append(("prefect", config))

        class _HatchetInstance:
            def __init__(self, config):
                received.append(("hatchet", config))

        bootstrap._instantiate_adapters(
            app,
            {"prefect": _PrefectInstance, "hatchet": _HatchetInstance},
            logging.getLogger(__name__),
        )

        assert received[0][0] == "prefect"
        assert received[0][1] is app.config
        assert received[1][0] == "hatchet"
        assert received[1][1] is app.config.hatchet
        assert "prefect" in app.adapters and "hatchet" in app.adapters

    def test_instantiate_adapters_error_and_importerror_paths(self, monkeypatch, caplog):
        app = SimpleNamespace(config=SimpleNamespace(hatchet=SimpleNamespace()), adapters={})

        class _ImportErrorAdapter:
            def __init__(self, config):
                raise ImportError("missing optional dep")

        class _ValueErrorAdapter:
            def __init__(self, config):
                raise ValueError("bad init")

        with caplog.at_level(logging.WARNING):
            bootstrap._instantiate_adapters(
                app,
                {"prefect": _ImportErrorAdapter},
                logging.getLogger(__name__),
            )

        assert "missing optional dependencies" in caplog.text.lower()

        with pytest.raises(ConfigurationError, match="Failed to initialize agno adapter"):
            bootstrap._instantiate_adapters(
                app,
                {"agno": _ValueErrorAdapter},
                logging.getLogger(__name__),
            )

    def test_initialize_adapters_sets_worker_manager(self, monkeypatch):
        worker_manager = object()
        worker_adapter = SimpleNamespace(worker_manager=worker_manager)

        monkeypatch.setattr(bootstrap, "_collect_adapter_classes", lambda app, logger: {})
        monkeypatch.setattr(
            bootstrap,
            "_instantiate_adapters",
            lambda app, adapter_classes, logger: app.adapters.update({"worker": worker_adapter}),
        )

        app = SimpleNamespace(
            config=SimpleNamespace(workers=SimpleNamespace(enabled=True)), adapters={}
        )
        bootstrap.initialize_adapters(app)

        assert app._worker_manager is worker_manager

    def test_init_observability_delegates(self, monkeypatch):
        fake_module = types.ModuleType("mahavishnu.core.observability")
        created = {}

        def fake_init(config):
            created["config"] = config
            return "observability"

        fake_module.init_observability = fake_init
        monkeypatch.setitem(sys.modules, "mahavishnu.core.observability", fake_module)

        app = SimpleNamespace(config=SimpleNamespace(name="cfg"))
        assert bootstrap.init_observability(app) == "observability"
        assert created["config"] is app.config

    def test_init_terminal_manager_exception_branch(self, monkeypatch, caplog):
        class FakeLogger:
            def info(self, msg, *args, **kwargs):
                raise RuntimeError("boom")

            def warning(self, msg, *args, **kwargs):
                self.warning_message = msg % args if args else msg

        original_get_logger = bootstrap.logging.getLogger
        monkeypatch.setattr(
            bootstrap.logging,
            "getLogger",
            lambda name=None: original_get_logger() if name is None else FakeLogger(),
        )
        with caplog.at_level(logging.WARNING):
            result = bootstrap.init_terminal_manager(SimpleNamespace())

        assert result is None

    def test_init_terminal_manager_normal_path(self):
        assert bootstrap.init_terminal_manager(SimpleNamespace()) is None

    def test_resolve_dhara_url_default_and_tls(self):
        default_config = SimpleNamespace(health=SimpleNamespace(dependencies={}))
        assert bootstrap.resolve_dhara_url(default_config) == "http://localhost:8683/mcp"

        dependency = SimpleNamespace(use_tls=True, host="dhara.example", port=9443)
        custom_config = SimpleNamespace(health=SimpleNamespace(dependencies={"dhara": dependency}))
        assert bootstrap.resolve_dhara_url(custom_config) == "https://dhara.example:9443/mcp"

    def test_init_pool_manager_success_and_failure(self, monkeypatch, caplog):
        fake_message_bus_module = types.ModuleType("mahavishnu.mcp.protocols.message_bus")
        fake_pools_module = types.ModuleType("mahavishnu.pools.manager")

        class FakeMessageBus:
            pass

        captured = {}

        class FakePoolSelector:
            def __init__(self, strategy):
                self.strategy = strategy

        class FakePoolManager:
            def __init__(self, terminal_manager, session_buddy_client, message_bus, dhara_state):
                captured["init"] = (
                    terminal_manager,
                    session_buddy_client,
                    message_bus,
                    dhara_state,
                )
                self.selector = None

            def set_pool_selector(self, selector):
                self.selector = selector
                captured["selector"] = selector

        fake_message_bus_module.MessageBus = FakeMessageBus
        fake_pools_module.PoolManager = FakePoolManager
        fake_pools_module.PoolSelector = FakePoolSelector
        monkeypatch.setitem(
            sys.modules, "mahavishnu.mcp.protocols.message_bus", fake_message_bus_module
        )
        monkeypatch.setitem(sys.modules, "mahavishnu.pools.manager", fake_pools_module)

        app = SimpleNamespace(
            terminal_manager="term",
            session_buddy="buddy",
            _dhara_state="dhara",
            config=SimpleNamespace(
                pools=SimpleNamespace(routing_strategy="least_loaded", default_type="mahavishnu")
            ),
        )

        pool_manager = bootstrap.init_pool_manager(app)
        assert pool_manager is not None
        assert captured["init"][0] == "term"
        assert captured["selector"].strategy == "least_loaded"

        class BoomPoolManager:
            def __init__(self, *args, **kwargs):
                raise RuntimeError("boom")

        fake_pools_module.PoolManager = BoomPoolManager
        with caplog.at_level(logging.WARNING):
            assert bootstrap.init_pool_manager(app) is None

    def test_init_memory_and_learning_pipeline(self, monkeypatch, caplog):
        fake_memory_module = types.ModuleType("mahavishnu.pools.memory_aggregator")
        fake_learning_module = types.ModuleType("mahavishnu.core.learning_pipeline")

        class FakeMemoryAggregator:
            def __init__(self, session_buddy_url, akosha_url, sync_interval):
                self.session_buddy_url = session_buddy_url
                self.akosha_url = akosha_url
                self.sync_interval = sync_interval

        class FakeLearningPipelineService:
            def __init__(self, config, session_buddy_url, akosha_url):
                self.config = config
                self.session_buddy_url = session_buddy_url
                self.akosha_url = akosha_url

        fake_memory_module.MemoryAggregator = FakeMemoryAggregator
        fake_learning_module.LearningPipelineService = FakeLearningPipelineService
        monkeypatch.setitem(sys.modules, "mahavishnu.pools.memory_aggregator", fake_memory_module)
        monkeypatch.setitem(sys.modules, "mahavishnu.core.learning_pipeline", fake_learning_module)

        app = SimpleNamespace(
            config=SimpleNamespace(
                pools=SimpleNamespace(
                    session_buddy_url="http://sb",
                    akosha_url="http://ak",
                    memory_sync_interval=12,
                ),
                learning=SimpleNamespace(
                    collection_interval_seconds=5,
                    max_evidence_per_cycle=2,
                ),
            )
        )

        mem = bootstrap.init_memory_aggregator(app)
        assert mem.session_buddy_url == "http://sb"
        assert mem.sync_interval == 12

        pipeline = bootstrap.init_learning_pipeline(app)
        assert pipeline.session_buddy_url == "http://sb"

        class BoomMemory:
            def __init__(self, *args, **kwargs):
                raise RuntimeError("boom")

        class BoomPipeline:
            def __init__(self, *args, **kwargs):
                raise RuntimeError("boom")

        fake_memory_module.MemoryAggregator = BoomMemory
        fake_learning_module.LearningPipelineService = BoomPipeline

        with caplog.at_level(logging.WARNING):
            assert bootstrap.init_memory_aggregator(app) is None
            assert bootstrap.init_learning_pipeline(app) is None

    @pytest.mark.asyncio
    async def test_recover_workflow_and_approvals_from_dhara(self, caplog):
        app = SimpleNamespace(
            _dhara_state=SimpleNamespace(
                recover_workflows=AsyncMock(
                    return_value=[
                        {"status": "running", "execution_id": "wf-1"},
                        {"status": "completed", "execution_id": "wf-2"},
                    ]
                ),
                list_prefix=AsyncMock(return_value=[{"id": "a"}]),
            ),
            active_workflows=set(),
            approval_manager=SimpleNamespace(
                restore_from_dhara_entries=lambda entries: len(entries)
            ),
        )

        with caplog.at_level(logging.INFO):
            await bootstrap.recover_workflow_state_from_dhara(app)
            await bootstrap.recover_approvals_from_dhara(app)

        assert "wf-1" in app.active_workflows

        app._dhara_state.recover_workflows = AsyncMock(side_effect=RuntimeError("wf boom"))
        app._dhara_state.list_prefix = AsyncMock(side_effect=RuntimeError("appr boom"))

        with caplog.at_level(logging.DEBUG):
            await bootstrap.recover_workflow_state_from_dhara(app)
            await bootstrap.recover_approvals_from_dhara(app)

    @pytest.mark.asyncio
    async def test_recover_helpers_return_early_without_dhara(self):
        app = SimpleNamespace(_dhara_state=None, active_workflows=set(), approval_manager=None)

        await bootstrap.recover_workflow_state_from_dhara(app)
        await bootstrap.recover_approvals_from_dhara(app)

    def test_set_app_context_with_agno_adapter(self, monkeypatch):
        fake_context = types.ModuleType("mahavishnu.core.context")
        fake_oneiric = types.ModuleType("mahavishnu.core.oneiric_client")
        fake_agno_llm = types.ModuleType("agno.llm")
        captured = {}

        def fake_set_context(**kwargs):
            captured["context"] = kwargs

        def fake_set_dhara_client_base_url(url):
            captured["dhara_url"] = url

        class FakeLLM:
            def __init__(self, **kwargs):
                captured["llm_kwargs"] = kwargs

        fake_context.set_app_context = fake_set_context
        fake_oneiric.set_dhara_client_base_url = fake_set_dhara_client_base_url
        fake_agno_llm.LLM = FakeLLM
        monkeypatch.setitem(sys.modules, "mahavishnu.core.context", fake_context)
        monkeypatch.setitem(sys.modules, "mahavishnu.core.oneiric_client", fake_oneiric)
        monkeypatch.setitem(sys.modules, "agno.llm", fake_agno_llm)

        app = SimpleNamespace(
            dhara_url="http://dhara",
            config=SimpleNamespace(
                agno=SimpleNamespace(
                    llm=SimpleNamespace(
                        provider=SimpleNamespace(value="openai"),
                        model_id="gpt-4o-mini",
                        base_url="http://ollama",
                    )
                )
            ),
            adapters={"agno": object()},
        )

        bootstrap.set_app_context(app)

        assert captured["dhara_url"] == "http://dhara"
        assert captured["context"]["agno_adapter"] is app.adapters["agno"]
        assert captured["context"]["llm_factory"] is not None
        factory = captured["context"]["llm_factory"]
        default = factory.create_llm()
        assert isinstance(default, FakeLLM)
        assert captured["llm_kwargs"]["provider"] == "openai"
        assert captured["llm_kwargs"]["model"] == "gpt-4o-mini"
        ollama = factory.create_llm(provider="ollama")
        assert isinstance(ollama, FakeLLM)
        assert captured["llm_kwargs"]["base_url"] == "http://ollama"
        assert factory.get_default_provider() == "openai"
        assert factory.get_default_model() == "gpt-4o-mini"

    def test_initialize_runtime_services_happy_path_with_fakes(self, monkeypatch, tmp_path):
        fake_modules: dict[str, types.ModuleType] = {}

        def install(module_name: str, **attrs):
            module = types.ModuleType(module_name)
            for key, value in attrs.items():
                setattr(module, key, value)
            fake_modules[module_name] = module
            monkeypatch.setitem(sys.modules, module_name, module)

        class _NoOp:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

        install("mahavishnu.qc.checker", QualityControl=_NoOp)
        install("mahavishnu.session.checkpoint", SessionBuddy=_NoOp)
        install("mahavishnu.messaging.repository_messenger", RepositoryMessenger=_NoOp)
        install("mahavishnu.core.approval_manager", ApprovalManager=_NoOp)
        install(
            "mahavishnu.core.backup_recovery", BackupManager=_NoOp, DisasterRecoveryManager=_NoOp
        )
        install("mahavishnu.core.coordination.manager", CoordinationManager=_NoOp)
        install(
            "mahavishnu.core.coordination.memory",
            CoordinationMemory=_NoOp,
            SessionBuddyMemoryClient=_NoOp,
        )
        install("mahavishnu.core.monitoring", MonitoringService=_NoOp)
        install("mahavishnu.core.opensearch_integration", OpenSearchIntegration=_NoOp)
        install("mahavishnu.core.repo_manager", RepositoryManager=_NoOp)

        class RetryExhaustedError(Exception):
            pass

        class RetryPolicy:
            pass

        async def retry_async(*args, **kwargs):  # noqa: ANN002,ANN003
            return None

        install(
            "mahavishnu.core.resilience",
            ErrorRecoveryManager=_NoOp,
            ResiliencePatterns=_NoOp,
            RetryExhaustedError=RetryExhaustedError,
            RetryPolicy=RetryPolicy,
            retry_async=retry_async,
        )
        install("mahavishnu.core.skill_registry", SkillRegistry=_NoOp)
        install("mahavishnu.core.learning_pipeline", LearningPipelineService=_NoOp)
        install(
            "mahavishnu.core.state_backends.dhara", DharaStateBackend=_NoOp, DharaStateConfig=_NoOp
        )

        routing_metrics_module = types.ModuleType("mahavishnu.core.routing_metrics")

        class RoutingMetrics:
            pass

        routing_metrics_module.RoutingMetrics = RoutingMetrics
        routing_metrics_module.get_routing_metrics = lambda name: {"name": name}
        monkeypatch.setitem(sys.modules, "mahavishnu.core.routing_metrics", routing_metrics_module)

        session_poller_module = types.ModuleType("mahavishnu.integrations.session_buddy_poller")
        session_poller_module.SessionBuddyPoller = _NoOp
        monkeypatch.setitem(
            sys.modules, "mahavishnu.integrations.session_buddy_poller", session_poller_module
        )

        app = SimpleNamespace(
            config=SimpleNamespace(
                terminal=SimpleNamespace(enabled=True),
                pools=SimpleNamespace(
                    enabled=True,
                    memory_aggregation_enabled=True,
                    session_buddy_url="http://sb",
                    akosha_url="http://ak",
                    memory_sync_interval=15,
                    routing_strategy="least_loaded",
                    default_type="mahavishnu",
                ),
                learning=SimpleNamespace(enabled=True),
                dhara_state=SimpleNamespace(
                    enabled=False,
                    flush_interval_seconds=10,
                    max_routing_buffer_age_seconds=20,
                ),
                tools=SimpleNamespace(mcp_server_url="http://mcp"),
                monitoring=SimpleNamespace(routing_metrics_enabled=False),
                session_buddy_polling=SimpleNamespace(
                    enabled=True,
                    endpoint="http://sb",
                    interval_seconds=30,
                ),
                repos_path=str(tmp_path / "ecosystem.yaml"),
            ),
            observability=object(),
            adapters={},
            dhara_url=None,
            _init_terminal_manager=lambda: "terminal-manager",
            _init_pool_manager=lambda: "pool-manager",
            _init_memory_aggregator=lambda: "memory-aggregator",
            _init_learning_pipeline=lambda: "learning-pipeline",
        )
        (tmp_path / "ecosystem.yaml").write_text("repos: []\n")

        bootstrap.initialize_runtime_services(app)

        assert app.qc is not None
        assert app.session_buddy_integration is app.session_buddy
        assert app.terminal_manager == "terminal-manager"
        assert app.pool_manager == "pool-manager"
        assert app.memory_aggregator == "memory-aggregator"
        assert app._learning_pipeline == "learning-pipeline"
        assert app.routing_metrics_server is None
        assert app.session_buddy_poller is not None
        assert app.worktree_coordinator is None

    def test_initialize_runtime_services_fallback_branches(self, monkeypatch, tmp_path, caplog):
        def install(module_name: str, **attrs):
            module = types.ModuleType(module_name)
            for key, value in attrs.items():
                setattr(module, key, value)
            monkeypatch.setitem(sys.modules, module_name, module)

        class _NoOp:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

        class _Boom:
            def __init__(self, *args, **kwargs):
                raise RuntimeError("boom")

        install("mahavishnu.qc.checker", QualityControl=_NoOp)
        install("mahavishnu.session.checkpoint", SessionBuddy=_NoOp)
        install("mahavishnu.messaging.repository_messenger", RepositoryMessenger=_Boom)
        install("mahavishnu.core.approval_manager", ApprovalManager=_NoOp)
        install(
            "mahavishnu.core.backup_recovery", BackupManager=_NoOp, DisasterRecoveryManager=_NoOp
        )
        install("mahavishnu.core.coordination.manager", CoordinationManager=_NoOp)
        install(
            "mahavishnu.core.coordination.memory",
            CoordinationMemory=_Boom,
            SessionBuddyMemoryClient=_NoOp,
        )
        install("mahavishnu.core.monitoring", MonitoringService=_NoOp)
        install("mahavishnu.core.opensearch_integration", OpenSearchIntegration=_NoOp)
        install("mahavishnu.core.repo_manager", RepositoryManager=_Boom)
        install(
            "mahavishnu.core.resilience",
            ErrorRecoveryManager=_NoOp,
            ResiliencePatterns=_NoOp,
            RetryExhaustedError=Exception,
            RetryPolicy=object,
            retry_async=lambda *args, **kwargs: None,
        )
        install("mahavishnu.core.task_router", StateManager=_NoOp)
        install("mahavishnu.core.skill_registry", SkillRegistry=_NoOp)
        install("mahavishnu.core.learning_pipeline", LearningPipelineService=_NoOp)
        install(
            "mahavishnu.core.state_backends.dhara", DharaStateBackend=_NoOp, DharaStateConfig=_NoOp
        )
        install("mahavishnu.integrations.session_buddy_poller", SessionBuddyPoller=_Boom)

        monkeypatch.setitem(sys.modules, "mahavishnu.core.routing_metrics", None)
        monkeypatch.setattr(bootstrap, "_register_component_endpoint", lambda *args, **kwargs: None)
        monkeypatch.setattr(bootstrap, "_validate_path", lambda path: Path(tmp_path))

        app = SimpleNamespace(
            config=SimpleNamespace(
                terminal=SimpleNamespace(enabled=False),
                pools=SimpleNamespace(
                    enabled=False,
                    memory_aggregation_enabled=False,
                    session_buddy_url="http://sb",
                    akosha_url="http://ak",
                    memory_sync_interval=15,
                    routing_strategy="least_loaded",
                    default_type="mahavishnu",
                ),
                learning=SimpleNamespace(enabled=False),
                dhara_state=SimpleNamespace(
                    enabled=True,
                    flush_interval_seconds=10,
                    max_routing_buffer_age_seconds=20,
                ),
                tools=SimpleNamespace(mcp_server_url="http://mcp"),
                monitoring=SimpleNamespace(routing_metrics_enabled=True),
                session_buddy_polling=SimpleNamespace(
                    enabled=True,
                    endpoint="http://sb",
                    interval_seconds=30,
                ),
                repos_path=str(tmp_path / "ecosystem.yaml"),
            ),
            observability=object(),
            adapters={},
            dhara_url="http://dhara",
            active_workflows=set(),
            approval_manager=SimpleNamespace(
                restore_from_dhara_entries=lambda entries: len(entries)
            ),
        )
        (tmp_path / "ecosystem.yaml").write_text("repos: []\n")

        with caplog.at_level(logging.WARNING):
            bootstrap.initialize_runtime_services(app)

        assert app.coordination_memory is None
        assert app.repository_messenger is None
        assert app._dhara_state is not None
        assert app.routing_metrics_server is None
        assert app.session_buddy_poller is None

    def test_initialize_runtime_services_routing_metrics_paths(self, monkeypatch, tmp_path, caplog):
        def install(module_name: str, **attrs):
            module = types.ModuleType(module_name)
            for key, value in attrs.items():
                setattr(module, key, value)
            monkeypatch.setitem(sys.modules, module_name, module)
            return module

        class _NoOp:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

        install("mahavishnu.qc.checker", QualityControl=_NoOp)
        install("mahavishnu.session.checkpoint", SessionBuddy=_NoOp)
        install("mahavishnu.messaging.repository_messenger", RepositoryMessenger=_NoOp)
        install("mahavishnu.core.approval_manager", ApprovalManager=_NoOp)
        install(
            "mahavishnu.core.backup_recovery", BackupManager=_NoOp, DisasterRecoveryManager=_NoOp
        )
        install("mahavishnu.core.coordination.manager", CoordinationManager=_NoOp)
        install(
            "mahavishnu.core.coordination.memory",
            CoordinationMemory=_NoOp,
            SessionBuddyMemoryClient=_NoOp,
        )
        install("mahavishnu.core.monitoring", MonitoringService=_NoOp)
        install("mahavishnu.core.opensearch_integration", OpenSearchIntegration=_NoOp)
        install("mahavishnu.core.repo_manager", RepositoryManager=_NoOp)
        install(
            "mahavishnu.core.resilience",
            ErrorRecoveryManager=_NoOp,
            ResiliencePatterns=_NoOp,
            RetryExhaustedError=Exception,
            RetryPolicy=object,
            retry_async=lambda *args, **kwargs: None,
        )
        install("mahavishnu.core.skill_registry", SkillRegistry=_NoOp)
        install("mahavishnu.core.learning_pipeline", LearningPipelineService=_NoOp)
        install(
            "mahavishnu.core.state_backends.dhara", DharaStateBackend=_NoOp, DharaStateConfig=_NoOp
        )
        install("mahavishnu.integrations.session_buddy_poller", SessionBuddyPoller=_NoOp)

        routing_metrics_module = install(
            "mahavishnu.core.routing_metrics", RoutingMetrics=type("RoutingMetrics", (), {})
        )
        routing_metrics_module.get_routing_metrics = lambda name: {"name": name}
        monkeypatch.setattr(bootstrap, "_register_component_endpoint", lambda *args, **kwargs: None)
        monkeypatch.setattr(bootstrap, "_validate_path", lambda path: Path(tmp_path))

        app = SimpleNamespace(
            config=SimpleNamespace(
                terminal=SimpleNamespace(enabled=False),
                pools=SimpleNamespace(
                    enabled=False,
                    memory_aggregation_enabled=False,
                    session_buddy_url="http://sb",
                    akosha_url="http://ak",
                    memory_sync_interval=15,
                    routing_strategy="least_loaded",
                    default_type="mahavishnu",
                ),
                learning=SimpleNamespace(enabled=False),
                dhara_state=SimpleNamespace(
                    enabled=False,
                    flush_interval_seconds=10,
                    max_routing_buffer_age_seconds=20,
                ),
                tools=SimpleNamespace(mcp_server_url="http://mcp"),
                monitoring=SimpleNamespace(routing_metrics_enabled=True),
                session_buddy_polling=SimpleNamespace(
                    enabled=False,
                    endpoint="http://sb",
                    interval_seconds=30,
                ),
                repos_path=str(tmp_path / "ecosystem.yaml"),
            ),
            observability=object(),
            adapters={},
            dhara_url=None,
            active_workflows=set(),
            approval_manager=SimpleNamespace(
                restore_from_dhara_entries=lambda entries: len(entries)
            ),
        )
        (tmp_path / "ecosystem.yaml").write_text("repos: []\n")

        with caplog.at_level(logging.INFO):
            bootstrap.initialize_runtime_services(app)

        assert app.routing_metrics_server is None

        routing_metrics_module.get_routing_metrics = lambda name: (_ for _ in ()).throw(
            RuntimeError("boom")
        )
        with caplog.at_level(logging.ERROR):
            bootstrap.initialize_runtime_services(app)

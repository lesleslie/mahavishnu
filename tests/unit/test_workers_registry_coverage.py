"""Tests for mahavishnu.workers.registry module.

Provides line+branch coverage for:
- WorkerCategory enum
- WorkerConfig dataclass
- WORKER_REGISTRY dict
- get_worker_config
- resolve_worker_type
- list_worker_types
- get_workers_by_category
- validate_worker_dependencies
"""

from __future__ import annotations

import os
import shutil
from unittest.mock import patch

import pytest

from mahavishnu.workers.registry import (
    WORKER_REGISTRY,
    WorkerCategory,
    WorkerConfig,
    get_worker_config,
    get_workers_by_category,
    list_worker_types,
    resolve_worker_type,
    validate_worker_dependencies,
)


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# WorkerCategory enum
# ---------------------------------------------------------------------------


class TestWorkerCategory:
    def test_all_categories_present(self) -> None:
        expected = {
            "AI_ASSISTANT",
            "SHELL",
            "CONTAINER",
            "REMOTE",
            "APPLICATION",
            "GATEWAY",
        }
        actual = {cat.name for cat in WorkerCategory}
        assert actual == expected

    def test_category_values(self) -> None:
        assert WorkerCategory.AI_ASSISTANT.value == "ai_assistant"
        assert WorkerCategory.SHELL.value == "shell"
        assert WorkerCategory.CONTAINER.value == "container"
        assert WorkerCategory.REMOTE.value == "remote"
        assert WorkerCategory.APPLICATION.value == "application"
        assert WorkerCategory.GATEWAY.value == "gateway"

    def test_category_count(self) -> None:
        assert len(WorkerCategory) == 6

    def test_category_iteration(self) -> None:
        items = list(WorkerCategory)
        assert WorkerCategory.AI_ASSISTANT in items

    def test_category_lookup_by_value(self) -> None:
        assert WorkerCategory("ai_assistant") is WorkerCategory.AI_ASSISTANT
        assert WorkerCategory("application") is WorkerCategory.APPLICATION


# ---------------------------------------------------------------------------
# WorkerConfig dataclass
# ---------------------------------------------------------------------------


class TestWorkerConfig:
    def test_minimal_creation(self) -> None:
        cfg = WorkerConfig(
            name="Test",
            worker_type="test",
            command="echo hi",
            category=WorkerCategory.SHELL,
        )
        assert cfg.name == "Test"
        assert cfg.worker_type == "test"
        assert cfg.command == "echo hi"
        assert cfg.category is WorkerCategory.SHELL
        assert cfg.description == ""
        assert cfg.completion_markers == []
        # Default error_markers
        assert cfg.error_markers == [
            "error:",
            "Error:",
            "ERROR:",
            "Exception:",
        ]
        assert cfg.stream_format == "text"
        assert cfg.supports_interactive is True
        assert cfg.default_timeout == 300
        assert cfg.env_vars == {}
        assert cfg.requires_tool is None
        assert cfg.mcp_server is None
        assert cfg.complete_on_valid_json is False

    def test_full_creation(self) -> None:
        cfg = WorkerConfig(
            name="Full",
            worker_type="full",
            command="cmd {prompt}",
            category=WorkerCategory.AI_ASSISTANT,
            description="d",
            completion_markers=["done"],
            error_markers=["oops"],
            stream_format="json",
            supports_interactive=False,
            default_timeout=120,
            env_vars={"K": "V"},
            requires_tool="tool",
            mcp_server="srv",
            complete_on_valid_json=True,
        )
        assert cfg.completion_markers == ["done"]
        assert cfg.error_markers == ["oops"]
        assert cfg.stream_format == "json"
        assert cfg.supports_interactive is False
        assert cfg.default_timeout == 120
        assert cfg.env_vars == {"K": "V"}
        assert cfg.requires_tool == "tool"
        assert cfg.mcp_server == "srv"
        assert cfg.complete_on_valid_json is True

    def test_error_markers_default_factory_unique_per_instance(self) -> None:
        """Default list should not be shared between instances."""
        a = WorkerConfig(name="a", worker_type="a", command="c", category=WorkerCategory.SHELL)
        b = WorkerConfig(name="b", worker_type="b", command="c", category=WorkerCategory.SHELL)
        a.error_markers.append("mutation")
        assert "mutation" not in b.error_markers

    def test_completion_markers_default_factory_unique(self) -> None:
        a = WorkerConfig(name="a", worker_type="a", command="c", category=WorkerCategory.SHELL)
        b = WorkerConfig(name="b", worker_type="b", command="c", category=WorkerCategory.SHELL)
        a.completion_markers.append("x")
        assert b.completion_markers == []

    def test_env_vars_default_factory_unique(self) -> None:
        a = WorkerConfig(name="a", worker_type="a", command="c", category=WorkerCategory.SHELL)
        b = WorkerConfig(name="b", worker_type="b", command="c", category=WorkerCategory.SHELL)
        a.env_vars["X"] = "Y"
        assert b.env_vars == {}


# ---------------------------------------------------------------------------
# WORKER_REGISTRY
# ---------------------------------------------------------------------------


class TestWorkerRegistry:
    def test_registry_is_dict(self) -> None:
        assert isinstance(WORKER_REGISTRY, dict)

    def test_registry_has_expected_keys(self) -> None:
        for key in [
            "terminal-qwen",
            "terminal-claude",
            "terminal-codex",
            "terminal-openclaw",
            "terminal-deepagents",
            "terminal-clai",
            "gateway-openclaw",
            "terminal-shell",
            "terminal-zsh",
            "terminal-python",
            "terminal-ipython",
            "terminal-node",
            "terminal-ssh",
            "terminal-mysql",
            "terminal-psql",
            "terminal-turso",
            "terminal-redis",
            "terminal-wasmtime",
            "terminal-wasmer",
            "container",
            "container-executor",
            "application-gimp",
            "application-inkscape",
            "application-blender",
            "application-mdinject",
            "application-vscode",
            "application-penpot",
            "application-grafana",
            "application-porkbun-dns",
            "application-porkbun-domain",
            "application-synxis-crs",
            "application-synxis-pms",
            "application-graphics",
            "application-neo4j",
            "application-pycharm",
            "terminal-sqlite",
            "terminal-mongo",
            "terminal-kubectl",
            "terminal-terraform",
        ]:
            assert key in WORKER_REGISTRY, f"missing worker: {key}"

    def test_all_registry_values_are_worker_config(self) -> None:
        for key, val in WORKER_REGISTRY.items():
            assert isinstance(val, WorkerConfig)
            assert val.worker_type == key

    def test_no_ollama_in_registry(self) -> None:
        """Ollama intentionally omitted (uses HTTP API, not CLI)."""
        assert "terminal-ollama" not in WORKER_REGISTRY

    def test_application_workers_have_mcp_server_or_command(self) -> None:
        for key, cfg in WORKER_REGISTRY.items():
            if cfg.category is WorkerCategory.APPLICATION:
                # Application workers are either MCP-driven or shell-driven
                assert cfg.mcp_server is not None or cfg.command != ""

    def test_ai_assistants_have_completion_or_json_marker(self) -> None:
        for key, cfg in WORKER_REGISTRY.items():
            if cfg.category is WorkerCategory.AI_ASSISTANT:
                # Either a completion marker is set, or it signals via JSON
                assert cfg.completion_markers or cfg.complete_on_valid_json or cfg.stream_format == "json"

    def test_registry_size(self) -> None:
        # 39 keys expected per source
        assert len(WORKER_REGISTRY) == 39


# ---------------------------------------------------------------------------
# get_worker_config
# ---------------------------------------------------------------------------


class TestGetWorkerConfig:
    def test_returns_config_for_known_type(self) -> None:
        cfg = get_worker_config("terminal-claude")
        assert cfg is not None
        assert cfg.worker_type == "terminal-claude"

    def test_returns_none_for_unknown_type(self) -> None:
        assert get_worker_config("nonexistent-worker") is None

    def test_returns_none_for_empty_string(self) -> None:
        assert get_worker_config("") is None

    def test_each_known_key_returns_config(self) -> None:
        for key in WORKER_REGISTRY:
            cfg = get_worker_config(key)
            assert cfg is not None
            assert cfg.worker_type == key


# ---------------------------------------------------------------------------
# resolve_worker_type
# ---------------------------------------------------------------------------


class TestResolveWorkerType:
    # --- passthrough cases ---

    def test_passthrough_unrelated_worker(self) -> None:
        assert resolve_worker_type("terminal-shell") == "terminal-shell"
        assert resolve_worker_type("terminal-shell", task_type="code") == "terminal-shell"

    def test_passthrough_empty_task_and_prompt(self) -> None:
        assert resolve_worker_type("terminal-claude") == "terminal-claude"
        assert resolve_worker_type("terminal-claude", "", "") == "terminal-claude"

    def test_passthrough_none_task_type(self) -> None:
        assert (
            resolve_worker_type("terminal-claude", task_type=None, prompt="hello")
            == "terminal-claude"
        )

    # --- communication task types ---

    @pytest.mark.parametrize(
        "task_type",
        [
            "communication",
            "notification",
            "messaging",
            "handoff",
            "delivery",
            "outreach",
            "chatops",
        ],
    )
    def test_communication_task_types_for_claude_routes_to_openclaw(self, task_type: str) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert (
                resolve_worker_type("terminal-claude", task_type=task_type)
                == "terminal-openclaw"
            )

    @pytest.mark.parametrize(
        "task_type",
        [
            "communication",
            "notification",
            "messaging",
            "handoff",
            "delivery",
            "outreach",
            "chatops",
        ],
    )
    def test_communication_task_types_for_qwen_routes_to_openclaw(self, task_type: str) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert (
                resolve_worker_type("terminal-qwen", task_type=task_type)
                == "terminal-openclaw"
            )

    @pytest.mark.parametrize(
        "task_type",
        [
            "communication",
            "notification",
            "messaging",
            "handoff",
            "delivery",
            "outreach",
            "chatops",
        ],
    )
    def test_communication_task_types_for_codex_routes_to_openclaw(self, task_type: str) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert (
                resolve_worker_type("terminal-codex", task_type=task_type)
                == "terminal-openclaw"
            )

    @pytest.mark.parametrize(
        "task_type",
        [
            "communication",
            "notification",
            "messaging",
            "handoff",
            "delivery",
            "outreach",
            "chatops",
        ],
    )
    def test_communication_task_types_for_openclaw_routes_to_openclaw(self, task_type: str) -> None:
        # terminal-openclaw is itself in the routing set
        with patch.dict(os.environ, {}, clear=True):
            assert (
                resolve_worker_type("terminal-openclaw", task_type=task_type)
                == "terminal-openclaw"
            )

    # --- gateway routing ---

    def test_gateway_routing_when_env_set(self) -> None:
        with patch.dict(os.environ, {"OPENCLAW_GATEWAY_URL": "http://gw:9000"}):
            assert (
                resolve_worker_type("terminal-claude", task_type="communication")
                == "gateway-openclaw"
            )

    def test_gateway_routing_via_prompt_marker(self) -> None:
        with patch.dict(os.environ, {"OPENCLAW_GATEWAY_URL": "http://gw:9000"}):
            assert (
                resolve_worker_type("terminal-claude", prompt="please send slack message")
                == "gateway-openclaw"
            )

    # --- prompt markers ---

    @pytest.mark.parametrize(
        "marker",
        [
            "notify",
            "notification",
            "reply",
            "respond",
            "deliver",
            "send",
            "message",
            "dm ",
            "slack",
            "telegram",
            "whatsapp",
            "discord",
            "google chat",
            "signal",
            "imessage",
            "inbox",
            "handoff",
            "follow up",
            "follow-up",
            "status update",
            "summarize for",
        ],
    )
    def test_prompt_marker_routes_to_openclaw(self, marker: str) -> None:
        with patch.dict(os.environ, {}, clear=True):
            prompt = f"please {marker} to the team"
            assert (
                resolve_worker_type("terminal-claude", prompt=prompt)
                == "terminal-openclaw"
            )

    def test_prompt_marker_case_insensitive(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert (
                resolve_worker_type("terminal-claude", prompt="PLEASE NOTIFY the team")
                == "terminal-openclaw"
            )

    def test_task_type_case_insensitive(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert (
                resolve_worker_type("terminal-claude", task_type="COMMUNICATION")
                == "terminal-openclaw"
            )

    def test_task_type_with_whitespace_stripped(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert (
                resolve_worker_type("terminal-claude", task_type="  communication  ")
                == "terminal-openclaw"
            )

    def test_prompt_marker_via_qwen(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert (
                resolve_worker_type("terminal-qwen", prompt="send a slack message")
                == "terminal-openclaw"
            )

    def test_prompt_marker_via_codex(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert (
                resolve_worker_type("terminal-codex", prompt="send a slack message")
                == "terminal-openclaw"
            )

    def test_prompt_marker_via_openclaw(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert (
                resolve_worker_type("terminal-openclaw", prompt="send a slack message")
                == "terminal-openclaw"
            )

    # --- negative cases ---

    def test_no_match_passes_through(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert (
                resolve_worker_type("terminal-claude", task_type="code_generation", prompt="write tests")
                == "terminal-claude"
            )

    def test_unrelated_worker_passes_through_even_with_communication_prompt(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert (
                resolve_worker_type("terminal-shell", task_type="communication")
                == "terminal-shell"
            )

    def test_unrelated_worker_passes_through_with_marker(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert (
                resolve_worker_type("terminal-shell", prompt="send slack message")
                == "terminal-shell"
            )

    def test_empty_env_for_gateway_check(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            # OPENCLAW_GATEWAY_URL not set -> terminal-openclaw
            assert (
                resolve_worker_type("terminal-claude", task_type="communication")
                == "terminal-openclaw"
            )

    def test_empty_string_task_type(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert (
                resolve_worker_type("terminal-claude", task_type="", prompt="")
                == "terminal-claude"
            )

    def test_prompt_only_no_task_type(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert (
                resolve_worker_type("terminal-claude", task_type=None, prompt="send a message")
                == "terminal-openclaw"
            )


# ---------------------------------------------------------------------------
# list_worker_types
# ---------------------------------------------------------------------------


class TestListWorkerTypes:
    def test_no_filter_returns_all(self) -> None:
        result = list_worker_types()
        assert isinstance(result, list)
        assert len(result) == len(WORKER_REGISTRY)
        assert set(result) == set(WORKER_REGISTRY.keys())

    def test_returns_list_of_strings(self) -> None:
        for item in list_worker_types():
            assert isinstance(item, str)

    def test_filter_by_ai_assistant(self) -> None:
        result = list_worker_types(category=WorkerCategory.AI_ASSISTANT)
        assert isinstance(result, list)
        assert len(result) > 0
        for wt in result:
            assert WORKER_REGISTRY[wt].category is WorkerCategory.AI_ASSISTANT

    def test_filter_by_shell(self) -> None:
        result = list_worker_types(category=WorkerCategory.SHELL)
        assert len(result) > 0
        for wt in result:
            assert WORKER_REGISTRY[wt].category is WorkerCategory.SHELL

    def test_filter_by_container(self) -> None:
        result = list_worker_types(category=WorkerCategory.CONTAINER)
        assert len(result) > 0
        for wt in result:
            assert WORKER_REGISTRY[wt].category is WorkerCategory.CONTAINER

    def test_filter_by_remote(self) -> None:
        result = list_worker_types(category=WorkerCategory.REMOTE)
        assert len(result) > 0
        for wt in result:
            assert WORKER_REGISTRY[wt].category is WorkerCategory.REMOTE

    def test_filter_by_application(self) -> None:
        result = list_worker_types(category=WorkerCategory.APPLICATION)
        assert len(result) > 0
        for wt in result:
            assert WORKER_REGISTRY[wt].category is WorkerCategory.APPLICATION

    def test_filter_by_gateway(self) -> None:
        result = list_worker_types(category=WorkerCategory.GATEWAY)
        assert "gateway-openclaw" in result
        for wt in result:
            assert WORKER_REGISTRY[wt].category is WorkerCategory.GATEWAY

    def test_sum_of_all_categories_equals_total(self) -> None:
        total = 0
        for cat in WorkerCategory:
            total += len(list_worker_types(category=cat))
        assert total == len(WORKER_REGISTRY)


# ---------------------------------------------------------------------------
# get_workers_by_category
# ---------------------------------------------------------------------------


class TestGetWorkersByCategory:
    def test_returns_dict_with_all_categories(self) -> None:
        result = get_workers_by_category()
        assert isinstance(result, dict)
        assert set(result.keys()) == set(WorkerCategory)

    def test_each_value_is_a_list(self) -> None:
        result = get_workers_by_category()
        for cat, items in result.items():
            assert isinstance(items, list)
            for item in items:
                assert isinstance(item, WorkerConfig)
                assert item.category is cat

    def test_aggregates_total_count(self) -> None:
        result = get_workers_by_category()
        total = sum(len(v) for v in result.values())
        assert total == len(WORKER_REGISTRY)

    def test_all_lists_initially_empty_before_appending(self) -> None:
        result = get_workers_by_category()
        # Each category key should be present even if it has no workers
        for cat in WorkerCategory:
            assert cat in result

    def test_application_category_has_workers(self) -> None:
        result = get_workers_by_category()
        assert len(result[WorkerCategory.APPLICATION]) > 0

    def test_ai_assistant_category_has_workers(self) -> None:
        result = get_workers_by_category()
        assert len(result[WorkerCategory.AI_ASSISTANT]) > 0

    def test_shell_category_has_workers(self) -> None:
        result = get_workers_by_category()
        assert len(result[WorkerCategory.SHELL]) > 0

    def test_container_category_has_workers(self) -> None:
        result = get_workers_by_category()
        assert len(result[WorkerCategory.CONTAINER]) > 0

    def test_remote_category_has_workers(self) -> None:
        result = get_workers_by_category()
        assert len(result[WorkerCategory.REMOTE]) > 0

    def test_gateway_category_has_workers(self) -> None:
        result = get_workers_by_category()
        assert len(result[WorkerCategory.GATEWAY]) > 0


# ---------------------------------------------------------------------------
# validate_worker_dependencies
# ---------------------------------------------------------------------------


class TestValidateWorkerDependencies:
    def test_returns_dict(self) -> None:
        result = validate_worker_dependencies()
        assert isinstance(result, dict)

    def test_keys_match_registry_keys(self) -> None:
        result = validate_worker_dependencies()
        assert set(result.keys()) == set(WORKER_REGISTRY.keys())

    def test_all_values_are_bool(self) -> None:
        result = validate_worker_dependencies()
        for v in result.values():
            assert isinstance(v, bool)

    def test_workers_without_requires_tool_are_true(self) -> None:
        result = validate_worker_dependencies()
        for wt, cfg in WORKER_REGISTRY.items():
            if cfg.requires_tool is None:
                assert result[wt] is True

    def test_workers_with_known_tool_check_against_shutil(self) -> None:
        # Mock shutil.which to return None for everything -> all False
        with patch.object(shutil, "which", return_value=None):
            result = validate_worker_dependencies()
            for wt, cfg in WORKER_REGISTRY.items():
                if cfg.requires_tool is not None:
                    assert result[wt] is False

    def test_workers_with_known_tool_available(self) -> None:
        # Mock shutil.which to return a path -> all require_tool workers True
        with patch.object(shutil, "which", return_value="/usr/bin/whatever"):
            result = validate_worker_dependencies()
            for wt, cfg in WORKER_REGISTRY.items():
                if cfg.requires_tool is not None:
                    assert result[wt] is True
                else:
                    assert result[wt] is True

    def test_shutil_which_called_with_correct_tool(self) -> None:
        calls: list[str] = []
        with patch.object(
            shutil, "which", side_effect=lambda x: calls.append(x) or None
        ):
            validate_worker_dependencies()
        # Each requires_tool must have been queried
        expected = {cfg.requires_tool for cfg in WORKER_REGISTRY.values() if cfg.requires_tool}
        assert set(calls) == expected

    def test_specific_tool_availability(self) -> None:
        def fake_which(name: str) -> str | None:
            if name == "qwen":
                return "/usr/local/bin/qwen"
            return None

        with patch.object(shutil, "which", side_effect=fake_which):
            result = validate_worker_dependencies()
        # qwen is required by terminal-qwen
        assert result["terminal-qwen"] is True
        # claude is required by terminal-claude
        assert result["terminal-claude"] is False
        # container has no requires_tool
        assert result["container"] is True

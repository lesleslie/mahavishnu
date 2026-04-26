"""Comprehensive unit tests for mahavishnu.workers.registry module."""

import os
import shutil
from dataclasses import fields
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


class TestWorkerCategory:
    """Tests for the WorkerCategory enum."""

    def test_all_categories_have_string_values(self):
        for cat in WorkerCategory:
            assert isinstance(cat.value, str)
            assert len(cat.value) > 0

    def test_category_count(self):
        assert len(WorkerCategory) == 7

    def test_specific_categories_exist(self):
        expected = {
            WorkerCategory.AI_ASSISTANT,
            WorkerCategory.SHELL,
            WorkerCategory.CONTAINER,
            WorkerCategory.REMOTE,
            WorkerCategory.APPLICATION,
            WorkerCategory.GATEWAY,
            WorkerCategory.IN_PROCESS,
        }
        assert set(WorkerCategory) == expected

    def test_category_values_are_lowercase_snake(self):
        for cat in WorkerCategory:
            assert cat.value == cat.value.lower()
            assert " " not in cat.value


class TestWorkerConfig:
    """Tests for the WorkerConfig dataclass."""

    def test_minimal_config_creation(self):
        cfg = WorkerConfig(
            name="Test",
            worker_type="test-worker",
            command="echo hello",
            category=WorkerCategory.SHELL,
        )
        assert cfg.name == "Test"
        assert cfg.worker_type == "test-worker"
        assert cfg.command == "echo hello"
        assert cfg.category == WorkerCategory.SHELL

    def test_default_values(self):
        cfg = WorkerConfig(
            name="T",
            worker_type="t",
            command="",
            category=WorkerCategory.SHELL,
        )
        assert cfg.description == ""
        assert cfg.completion_markers == []
        assert cfg.error_markers == ["error:", "Error:", "ERROR:", "Exception:"]
        assert cfg.stream_format == "text"
        assert cfg.supports_interactive is True
        assert cfg.default_timeout == 300
        assert cfg.env_vars == {}
        assert cfg.requires_tool is None
        assert cfg.mcp_server is None
        assert cfg.complete_on_valid_json is False

    def test_all_fields_are_settable(self):
        cfg = WorkerConfig(
            name="Full",
            worker_type="full-worker",
            command="run",
            category=WorkerCategory.CONTAINER,
            description="A full config",
            completion_markers=["done"],
            error_markers=["FAIL"],
            stream_format="json",
            supports_interactive=False,
            default_timeout=600,
            env_vars={"KEY": "VAL"},
            requires_tool="docker",
            mcp_server="my-mcp",
            complete_on_valid_json=True,
        )
        assert cfg.description == "A full config"
        assert cfg.completion_markers == ["done"]
        assert cfg.error_markers == ["FAIL"]
        assert cfg.stream_format == "json"
        assert cfg.supports_interactive is False
        assert cfg.default_timeout == 600
        assert cfg.env_vars == {"KEY": "VAL"}
        assert cfg.requires_tool == "docker"
        assert cfg.mcp_server == "my-mcp"
        assert cfg.complete_on_valid_json is True

    def test_default_error_markers_is_independent_per_instance(self):
        cfg1 = WorkerConfig(
            name="A", worker_type="a", command="", category=WorkerCategory.SHELL
        )
        cfg2 = WorkerConfig(
            name="B", worker_type="b", command="", category=WorkerCategory.SHELL
        )
        cfg1.error_markers.append("extra")
        assert "extra" not in cfg2.error_markers

    def test_completion_markers_is_independent_per_instance(self):
        cfg1 = WorkerConfig(
            name="A", worker_type="a", command="", category=WorkerCategory.SHELL
        )
        cfg2 = WorkerConfig(
            name="B", worker_type="b", command="", category=WorkerCategory.SHELL
        )
        cfg1.completion_markers.append("marker")
        assert "marker" not in cfg2.completion_markers


class TestWorkerRegistry:
    """Tests for the WORKER_REGISTRY dictionary."""

    def test_registry_is_non_empty(self):
        assert len(WORKER_REGISTRY) > 0

    def test_all_registry_values_are_worker_config(self):
        for key, value in WORKER_REGISTRY.items():
            assert isinstance(value, WorkerConfig), f"{key} is not a WorkerConfig"

    def test_all_worker_types_match_key(self):
        for key, cfg in WORKER_REGISTRY.items():
            assert cfg.worker_type == key, f"Key {key} != worker_type {cfg.worker_type}"

    def test_all_worker_names_are_non_empty(self):
        for key, cfg in WORKER_REGISTRY.items():
            assert len(cfg.name.strip()) > 0, f"{key} has empty name"

    def test_all_categories_are_valid(self):
        valid_categories = set(WorkerCategory)
        for key, cfg in WORKER_REGISTRY.items():
            assert cfg.category in valid_categories, f"{key} has invalid category {cfg.category}"

    def test_known_worker_types_exist(self):
        known = [
            "terminal-qwen",
            "terminal-claude",
            "terminal-shell",
            "container",
            "terminal-python",
            "terminal-ssh",
            "gateway-openclaw",
            "in-process-nanobot",
        ]
        for wt in known:
            assert wt in WORKER_REGISTRY, f"{wt} missing from registry"

    def test_no_duplicate_worker_types(self):
        keys = list(WORKER_REGISTRY.keys())
        assert len(keys) == len(set(keys))

    def test_ai_assistant_workers_have_requires_tool(self):
        for key, cfg in WORKER_REGISTRY.items():
            if cfg.category == WorkerCategory.AI_ASSISTANT and key not in (
                "gateway-openclaw",
                "terminal-ollama",
            ):
                assert cfg.requires_tool is not None, f"{key} AI assistant missing requires_tool"


class TestGetWorkerConfig:
    """Tests for the get_worker_config function."""

    def test_get_existing_worker(self):
        cfg = get_worker_config("terminal-shell")
        assert cfg is not None
        assert cfg.name == "Bash Shell"
        assert cfg.worker_type == "terminal-shell"

    def test_get_nonexistent_worker_returns_none(self):
        result = get_worker_config("nonexistent-worker-type")
        assert result is None

    def test_get_empty_string_worker_returns_none(self):
        result = get_worker_config("")
        assert result is None

    def test_returned_config_has_correct_category(self):
        cfg = get_worker_config("terminal-ssh")
        assert cfg.category == WorkerCategory.REMOTE

    def test_get_container_worker(self):
        cfg = get_worker_config("container")
        assert cfg is not None
        assert cfg.supports_interactive is False
        assert cfg.category == WorkerCategory.CONTAINER


class TestListWorkerTypes:
    """Tests for the list_worker_types function."""

    def test_list_all_returns_all_keys(self):
        result = list_worker_types()
        assert set(result) == set(WORKER_REGISTRY.keys())

    def test_list_all_returns_list_of_strings(self):
        result = list_worker_types()
        assert isinstance(result, list)
        assert all(isinstance(x, str) for x in result)

    def test_filter_by_ai_assistant_category(self):
        result = list_worker_types(WorkerCategory.AI_ASSISTANT)
        assert all(
            WORKER_REGISTRY[wt].category == WorkerCategory.AI_ASSISTANT for wt in result
        )

    def test_filter_by_shell_category(self):
        result = list_worker_types(WorkerCategory.SHELL)
        assert all(
            WORKER_REGISTRY[wt].category == WorkerCategory.SHELL for wt in result
        )

    def test_filter_by_container_category(self):
        result = list_worker_types(WorkerCategory.CONTAINER)
        assert len(result) >= 2
        assert "container" in result

    def test_filter_by_gateway_category(self):
        result = list_worker_types(WorkerCategory.GATEWAY)
        assert "gateway-openclaw" in result

    def test_filter_by_application_category(self):
        result = list_worker_types(WorkerCategory.APPLICATION)
        assert len(result) > 0
        assert all(
            WORKER_REGISTRY[wt].category == WorkerCategory.APPLICATION for wt in result
        )

    def test_filter_by_remote_category(self):
        result = list_worker_types(WorkerCategory.REMOTE)
        assert "terminal-ssh" in result

    def test_filter_by_in_process_category(self):
        result = list_worker_types(WorkerCategory.IN_PROCESS)
        assert all(
            WORKER_REGISTRY[wt].category == WorkerCategory.IN_PROCESS for wt in result
        )
        assert "in-process-nanobot" in result

    def test_none_filter_returns_more_than_any_single_category(self):
        all_types = list_worker_types()
        for cat in WorkerCategory:
            filtered = list_worker_types(cat)
            assert len(all_types) > len(filtered)


class TestGetWorkersByCategory:
    """Tests for the get_workers_by_category function."""

    def test_returns_dict_with_all_categories(self):
        result = get_workers_by_category()
        assert set(result.keys()) == set(WorkerCategory)

    def test_all_values_are_lists_of_worker_config(self):
        result = get_workers_by_category()
        for cat, configs in result.items():
            assert isinstance(configs, list)
            for cfg in configs:
                assert isinstance(cfg, WorkerConfig)

    def test_each_config_belongs_to_correct_category(self):
        result = get_workers_by_category()
        for cat, configs in result.items():
            for cfg in configs:
                assert cfg.category == cat

    def test_total_count_matches_registry(self):
        result = get_workers_by_category()
        total = sum(len(v) for v in result.values())
        assert total == len(WORKER_REGISTRY)

    def test_ai_assistant_category_has_workers(self):
        result = get_workers_by_category()
        assert len(result[WorkerCategory.AI_ASSISTANT]) > 0

    def test_shell_category_has_workers(self):
        result = get_workers_by_category()
        assert len(result[WorkerCategory.SHELL]) > 0


class TestValidateWorkerDependencies:
    """Tests for the validate_worker_dependencies function."""

    @patch("shutil.which", return_value=None)
    def test_worker_without_requires_tool_is_always_available(self, mock_which):
        results = validate_worker_dependencies()
        for key, cfg in WORKER_REGISTRY.items():
            if cfg.requires_tool is None:
                assert results[key] is True, f"{key} should be available without requires_tool"

    @patch("shutil.which", return_value="/usr/bin/python3")
    def test_worker_with_installed_tool_is_available(self, mock_which):
        results = validate_worker_dependencies()
        assert results["terminal-python"] is True

    @patch("shutil.which", return_value=None)
    def test_worker_with_missing_tool_is_unavailable(self, mock_which):
        results = validate_worker_dependencies()
        assert results["terminal-python"] is False

    @patch("shutil.which", return_value="/usr/bin/tool")
    def test_returns_bool_for_all_registered_workers(self, mock_which):
        results = validate_worker_dependencies()
        assert set(results.keys()) == set(WORKER_REGISTRY.keys())
        for v in results.values():
            assert isinstance(v, bool)

    @patch("shutil.which", return_value=None)
    def test_shutil_which_called_with_correct_tool_name(self, mock_which):
        validate_worker_dependencies()
        for key, cfg in WORKER_REGISTRY.items():
            if cfg.requires_tool:
                mock_which.assert_any_call(cfg.requires_tool)


class TestResolveWorkerType:
    """Tests for the resolve_worker_type function."""

    def test_non_communication_task_returns_same_type(self):
        assert resolve_worker_type("terminal-qwen", "coding", "write a function") == "terminal-qwen"

    def test_non_communication_worker_returns_same_type(self):
        assert resolve_worker_type("terminal-shell", "communication", "send message") == "terminal-shell"

    def test_no_task_or_prompt_returns_same_type(self):
        assert resolve_worker_type("terminal-qwen") == "terminal-qwen"

    def test_communication_task_with_qwen_resolves_to_openclaw(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENCLAW_GATEWAY_URL", None)
            result = resolve_worker_type("terminal-qwen", "messaging", "notify the team")
            assert result == "terminal-openclaw"

    def test_communication_prompt_with_qwen_resolves_to_openclaw(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENCLAW_GATEWAY_URL", None)
            result = resolve_worker_type("terminal-qwen", None, "send a slack message")
            assert result == "terminal-openclaw"

    def test_communication_task_with_claude_resolves_to_openclaw(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENCLAW_GATEWAY_URL", None)
            result = resolve_worker_type("terminal-claude", "notification", "alert user")
            assert result == "terminal-openclaw"

    def test_communication_task_with_codex_resolves_to_openclaw(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENCLAW_GATEWAY_URL", None)
            result = resolve_worker_type("terminal-codex", "communication", "dm user")
            assert result == "terminal-openclaw"

    @patch.dict(os.environ, {"OPENCLAW_GATEWAY_URL": "http://localhost:9090"})
    def test_gateway_url_set_resolves_to_gateway(self):
        result = resolve_worker_type("terminal-qwen", "messaging", "notify team")
        assert result == "gateway-openclaw"

    def test_case_insensitive_task_type(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENCLAW_GATEWAY_URL", None)
            result = resolve_worker_type("terminal-qwen", "  MESSAGING  ", "do work")
            assert result == "terminal-openclaw"

    def test_case_insensitive_prompt(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENCLAW_GATEWAY_URL", None)
            result = resolve_worker_type("terminal-qwen", None, "SEND a Notification")
            assert result == "terminal-openclaw"

    def test_various_communication_markers(self):
        markers = [
            "reply to the email",
            "respond to the thread",
            "deliver the report",
            "status update for team",
            "follow up on the issue",
            "follow-up with client",
            "handoff to next shift",
            "summarize for stakeholders",
            "discord announcement",
            "telegram alert",
        ]
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENCLAW_GATEWAY_URL", None)
            for marker in markers:
                result = resolve_worker_type("terminal-openclaw", None, marker)
                assert result == "terminal-openclaw", f"Failed for prompt: {marker}"

    def test_coding_task_does_not_resolve_to_openclaw(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENCLAW_GATEWAY_URL", None)
            result = resolve_worker_type("terminal-qwen", "coding", "refactor the module")
            assert result == "terminal-qwen"

    def test_shell_worker_unaffected_by_communication_markers(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENCLAW_GATEWAY_URL", None)
            result = resolve_worker_type("terminal-shell", "messaging", "send message")
            assert result == "terminal-shell"

    def test_communication_task_types_set(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENCLAW_GATEWAY_URL", None)
            task_types = ["communication", "notification", "messaging", "handoff", "delivery", "outreach", "chatops"]
            for tt in task_types:
                result = resolve_worker_type("terminal-qwen", tt, "do something")
                assert result == "terminal-openclaw", f"Failed for task_type: {tt}"

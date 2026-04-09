"""Tests for GenericShellWorker completion and command formatting."""

from unittest.mock import AsyncMock, MagicMock

from mahavishnu.workers.generic_shell import GenericShellWorker
from mahavishnu.workers.registry import get_worker_config, resolve_worker_type


def _mock_terminal_manager() -> MagicMock:
    manager = MagicMock()
    manager.launch_sessions = AsyncMock(return_value=["session_123"])
    manager.send_command = AsyncMock()
    manager.capture_output = AsyncMock(return_value="")
    return manager


def test_terminal_opencode_is_not_registered() -> None:
    """OpenCode worker aliases should no longer be available."""
    config = get_worker_config("terminal-opencode")
    quick = get_worker_config("terminal-opencode-quick")
    deep = get_worker_config("terminal-opencode-deep")
    ultrabrain = get_worker_config("terminal-opencode-ultrabrain")

    assert config is None
    assert quick is None
    assert deep is None
    assert ultrabrain is None


def test_terminal_aider_is_not_registered() -> None:
    """Aider worker type should no longer be available."""
    config = get_worker_config("terminal-aider")

    assert config is None


def test_terminal_openclaw_uses_json_agent_mode() -> None:
    """OpenClaw worker should use agent subcommand with JSON output."""
    config = get_worker_config("terminal-openclaw")

    assert config is not None
    assert config.stream_format == "json"
    assert config.complete_on_valid_json is True
    assert "openclaw agent" in config.command
    assert "--json" in config.command
    assert "--message {prompt}" in config.command


def test_terminal_deepagents_uses_non_interactive_marker_mode() -> None:
    """DeepAgents should run one-shot mode with an explicit completion marker."""
    config = get_worker_config("terminal-deepagents")

    assert config is not None
    assert config.stream_format == "text"
    assert config.completion_markers == ["__MAHAVISHNU_DONE__"]
    assert "--non-interactive \"$1\"" in config.command
    assert "--quiet" in config.command
    assert "--no-stream" in config.command


def test_terminal_clai_uses_one_shot_marker_mode() -> None:
    """CLAI should run one-shot mode with a shell-appended completion marker."""
    config = get_worker_config("terminal-clai")

    assert config is not None
    assert config.stream_format == "text"
    assert config.completion_markers == ["__MAHAVISHNU_DONE__"]
    assert "clai --no-stream \"$1\"" in config.command


def test_terminal_codex_uses_one_shot_marker_mode() -> None:
    """Codex should run one-shot mode with a shell-appended completion marker."""
    config = get_worker_config("terminal-codex")

    assert config is not None
    assert config.stream_format == "text"
    assert config.completion_markers == ["__MAHAVISHNU_DONE__"]
    assert "codex exec --json \"$1\"" in config.command


def test_terminal_qwen_uses_native_cli_configuration() -> None:
    """Qwen worker should defer provider selection to the native Qwen CLI config."""
    config = get_worker_config("terminal-qwen")

    assert config is not None
    assert config.command == "sh -lc 'qwen -o stream-json --approval-mode yolo'"


def test_terminal_claude_uses_native_cli_configuration() -> None:
    """Claude worker should defer provider selection to the native Claude config."""
    config = get_worker_config("terminal-claude")

    assert config is not None
    assert config.command == "sh -lc 'claude --output-format stream-json --permission-mode acceptEdits'"


def test_generic_shell_completes_on_valid_json_for_openclaw() -> None:
    """One-shot JSON workers should complete when the full payload is valid JSON."""
    worker = GenericShellWorker(
        terminal_manager=_mock_terminal_manager(),
        worker_type="terminal-openclaw",
    )

    completed, content = worker._check_json_completion('{"text":"Task completed"}')

    assert completed is True
    assert content == "Task completed"


def test_generic_shell_formats_prompt_bound_command() -> None:
    """Prompt-bound workers should format their launch command directly."""
    worker = GenericShellWorker(
        terminal_manager=_mock_terminal_manager(),
        worker_type="terminal-openclaw",
    )

    command = worker._format_command("Summarize the latest deployment")

    assert "openclaw agent" in command
    assert "--json" in command
    assert "Summarize the latest deployment" in command


def test_generic_shell_formats_prompt_bound_command_for_deepagents() -> None:
    """Prompt-bound text workers should quote the prompt into the launch command."""
    worker = GenericShellWorker(
        terminal_manager=_mock_terminal_manager(),
        worker_type="terminal-deepagents",
    )

    command = worker._format_command("Summarize the latest deployment")

    assert "deepagents-cli" in command
    assert "--non-interactive" in command
    assert "__MAHAVISHNU_DONE__" in command
    assert "Summarize the latest deployment" in command


def test_generic_shell_text_completion_uses_explicit_marker() -> None:
    """Marker-based workers should complete when the sentinel line appears."""
    worker = GenericShellWorker(
        terminal_manager=_mock_terminal_manager(),
        worker_type="terminal-clai",
    )

    completed, content = worker._check_text_completion("result body\n__MAHAVISHNU_DONE__")

    assert completed is True
    assert content == "result body"


def test_generic_shell_json_marker_matching_uses_serialized_payload() -> None:
    """JSON marker matching should work against parsed payload content too."""
    worker = GenericShellWorker(
        terminal_manager=_mock_terminal_manager(),
        worker_type="terminal-qwen",
    )

    completed, content = worker._check_json_completion('{"event":"done","text":"ok"}')

    assert completed is True
    assert content == "ok"


def test_resolve_worker_type_routes_communication_to_openclaw() -> None:
    """Communication and delivery tasks should prefer OpenClaw."""
    resolved = resolve_worker_type(
        "terminal-qwen",
        task_type="notification",
        prompt="Notify Slack with a status update for this deployment",
    )

    assert resolved == "terminal-openclaw"


def test_resolve_worker_type_prefers_gateway_openclaw_when_configured(monkeypatch) -> None:
    """Communication tasks should prefer gateway OpenClaw when configured."""
    monkeypatch.setenv("OPENCLAW_GATEWAY_URL", "http://localhost:8787")

    resolved = resolve_worker_type(
        "terminal-claude",
        task_type="notification",
        prompt="Send a Slack handoff message for this incident",
    )

    assert resolved == "gateway-openclaw"


def test_resolve_worker_type_keeps_coding_tasks_off_openclaw() -> None:
    """Code-generation tasks should remain on the requested coding worker."""
    resolved = resolve_worker_type(
        "terminal-qwen",
        task_type="code_generation",
        prompt="Implement a FastAPI endpoint for webhooks",
    )

    assert resolved == "terminal-qwen"


def test_resolve_worker_type_routes_codex_communication_to_openclaw() -> None:
    """Codex communication tasks should prefer OpenClaw routing."""
    resolved = resolve_worker_type(
        "terminal-codex",
        task_type="notification",
        prompt="Notify Slack with a concise production status update",
    )

    assert resolved == "terminal-openclaw"

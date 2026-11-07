"""Unit tests for ``.claude/hooks/bifrost-anthropic-probe-guard.py``.

The hook stops Claude Code's bundled ``claude-api`` skill (``drop_block_probe.py``)
from inheriting the session's ``ANTHROPIC_BASE_URL`` and asking a
MiniMax-backed Bifrost gateway for a Claude model id.

Loaded as a module via ``importlib.util.spec_from_file_location`` — the same
pattern used by ``tests/unit/test_worktree_session_isolation_hook.py``.
"""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import sys

import pytest

pytestmark = pytest.mark.unit

_HOOK_PATH = (
    Path(__file__).resolve().parents[3]
    / ".claude"
    / "hooks"
    / "bifrost-anthropic-probe-guard.py"
)


def _load_hook_module():
    """Import the guard script as a module."""
    spec = importlib.util.spec_from_file_location(
        "bifrost_anthropic_probe_guard", _HOOK_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


guard = _load_hook_module()

GATEWAY_URL = "http://127.0.0.1:8471/anthropic"
PROBE = "/private/tmp/claude-501/bundled-skills/2.1.318/abc123/claude-api/shared/preserved-thinking-migration/drop_block_probe.py"


class TestIsGatewayUrl:
    """The gateway is a loopback host on the gateway's port."""

    def test_gateway_anthropic_surface(self) -> None:
        assert guard.is_gateway_url(GATEWAY_URL) is True

    def test_localhost_variant(self) -> None:
        assert guard.is_gateway_url("http://localhost:8471/anthropic") is True

    def test_real_anthropic_api_is_not_the_gateway(self) -> None:
        assert guard.is_gateway_url("https://api.anthropic.com") is False

    def test_remote_host_on_the_gateway_port_is_not_the_gateway(self) -> None:
        assert guard.is_gateway_url("http://example.com:8471/anthropic") is False

    def test_empty_url(self) -> None:
        assert guard.is_gateway_url("") is False

    def test_bare_host_port(self) -> None:
        assert guard.is_gateway_url("127.0.0.1:8471") is True

    def test_port_is_honoured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BIFROST_PORT", "9999")
        assert guard.is_gateway_url("http://127.0.0.1:9999/anthropic") is True
        assert guard.is_gateway_url(GATEWAY_URL) is False


class TestMentionsAnthropicTooling:
    """Naming the tool, whatever the command goes on to do with it."""

    def test_probe_script(self) -> None:
        assert guard.mentions_anthropic_tooling(f"python3 {PROBE} --self-test") is True

    def test_bundled_claude_api_skill(self) -> None:
        command = (
            "python3 /x/bundled-skills/2.1.318/abc/claude-api/shared/prefix_diff.py"
        )
        assert guard.mentions_anthropic_tooling(command) is True

    def test_probe_script_by_name_only(self) -> None:
        """The script name is distinctive enough to match without its path."""
        assert (
            guard.mentions_anthropic_tooling("python3 drop_block_probe.py --self-test")
            is True
        )

    def test_ordinary_command(self) -> None:
        assert guard.mentions_anthropic_tooling("pytest -q") is False

    def test_bundled_skill_that_is_not_claude_api(self) -> None:
        command = "python3 /x/bundled-skills/2.1.318/abc/other-skill/run.py"
        assert guard.mentions_anthropic_tooling(command) is False

    def test_empty_command(self) -> None:
        assert guard.mentions_anthropic_tooling("") is False


class TestInvokesAnthropicTooling:
    """Only a command that would execute the tooling counts."""

    def test_probe_script(self) -> None:
        assert guard.invokes_anthropic_tooling(f"python3 {PROBE} --self-test") is True

    def test_bundled_claude_api_skill(self) -> None:
        command = (
            "python3 /x/bundled-skills/2.1.318/abc/claude-api/shared/prefix_diff.py"
        )
        assert guard.invokes_anthropic_tooling(command) is True

    def test_probe_script_by_name_only(self) -> None:
        assert (
            guard.invokes_anthropic_tooling("python3 drop_block_probe.py --self-test")
            is True
        )

    def test_absolute_python_path(self) -> None:
        assert (
            guard.invokes_anthropic_tooling(f"/opt/homebrew/bin/python3 {PROBE}")
            is True
        )

    def test_venv_python(self) -> None:
        command = f"/Users/les/Projects/mahavishnu/.venv/bin/python3 {PROBE}"
        assert guard.invokes_anthropic_tooling(command) is True

    def test_versioned_python(self) -> None:
        assert guard.invokes_anthropic_tooling(f"python3.13 {PROBE}") is True

    def test_script_as_the_executable(self) -> None:
        assert guard.invokes_anthropic_tooling(f"{PROBE} --self-test") is True

    def test_reading_the_source_is_not_an_invocation(self) -> None:
        """Grepping the probe cannot reach the network, so it is not blocked."""
        command = f"grep -n 'model' {PROBE}"
        assert guard.mentions_anthropic_tooling(command) is True
        assert guard.invokes_anthropic_tooling(command) is False

    def test_path_in_a_variable_assignment_is_not_an_invocation(self) -> None:
        """``P=/path/probe.py grep ...`` assigns a path; it does not run it."""
        command = f"P={PROBE} grep -n model $P"
        assert guard.mentions_anthropic_tooling(command) is True
        assert guard.invokes_anthropic_tooling(command) is False

    def test_assignment_prefixed_invocation_is_still_an_invocation(self) -> None:
        command = f"P={PROBE} python3 $P --self-test"
        assert guard.invokes_anthropic_tooling(command) is True

    def test_listing_the_skill_is_not_an_invocation(self) -> None:
        command = "ls -la /x/bundled-skills/2.1.318/abc/claude-api/shared"
        assert guard.mentions_anthropic_tooling(command) is True
        assert guard.invokes_anthropic_tooling(command) is False

    def test_ordinary_command(self) -> None:
        assert guard.invokes_anthropic_tooling("pytest -q") is False

    def test_bundled_skill_that_is_not_claude_api(self) -> None:
        command = "python3 /x/bundled-skills/2.1.318/abc/other-skill/run.py"
        assert guard.invokes_anthropic_tooling(command) is False

    def test_empty_command(self) -> None:
        assert guard.invokes_anthropic_tooling("") is False


class TestEffectiveBaseUrl:
    """Resolution order: explicit flag, deliberate scrub, inline, inherited env."""

    def test_explicit_flag_wins(self) -> None:
        url, explicit = guard.effective_base_url(
            f"python3 {PROBE} --base-url {GATEWAY_URL}",
            {"ANTHROPIC_BASE_URL": GATEWAY_URL},
        )
        assert url == GATEWAY_URL
        assert explicit is True

    def test_env_unset_is_explicit(self) -> None:
        url, explicit = guard.effective_base_url(
            f"env -u ANTHROPIC_BASE_URL python3 {PROBE}",
            {"ANTHROPIC_BASE_URL": GATEWAY_URL},
        )
        assert url == ""
        assert explicit is True

    def test_unset_keyword_is_explicit(self) -> None:
        _, explicit = guard.effective_base_url(
            f"unset ANTHROPIC_BASE_URL; python3 {PROBE}",
            {"ANTHROPIC_BASE_URL": GATEWAY_URL},
        )
        assert explicit is True

    def test_inline_assignment(self) -> None:
        url, explicit = guard.effective_base_url(
            f"ANTHROPIC_BASE_URL={GATEWAY_URL} python3 {PROBE}",
            {"ANTHROPIC_BASE_URL": ""},
        )
        assert url == GATEWAY_URL
        assert explicit is False

    def test_inherited_environment(self) -> None:
        url, explicit = guard.effective_base_url(
            f"python3 {PROBE}", {"ANTHROPIC_BASE_URL": GATEWAY_URL}
        )
        assert url == GATEWAY_URL
        assert explicit is False

    def test_quotes_are_stripped(self) -> None:
        url, _ = guard.effective_base_url(
            f'python3 {PROBE} --base-url "{GATEWAY_URL}"', {}
        )
        assert url == GATEWAY_URL


class TestEvaluate:
    """The deny rule: Anthropic tooling aimed at the gateway."""

    def test_denies_the_accidental_case(self) -> None:
        reason = guard.evaluate(
            f"python3 {PROBE} --self-test --model claude-opus-5-5 --yes",
            {"ANTHROPIC_BASE_URL": GATEWAY_URL},
        )
        assert reason is not None
        assert "BLOCKED" in reason
        assert "no keys found that support model" in reason

    def test_allows_an_explicit_gateway_choice(self) -> None:
        reason = guard.evaluate(
            f"python3 {PROBE} --base-url {GATEWAY_URL}",
            {"ANTHROPIC_BASE_URL": GATEWAY_URL},
        )
        assert reason is None

    def test_allows_a_scrubbed_environment(self) -> None:
        reason = guard.evaluate(
            f"env -u ANTHROPIC_BASE_URL python3 {PROBE}",
            {"ANTHROPIC_BASE_URL": GATEWAY_URL},
        )
        assert reason is None

    def test_allows_when_the_gateway_is_not_configured(self) -> None:
        reason = guard.evaluate(
            f"python3 {PROBE}", {"ANTHROPIC_BASE_URL": "https://api.anthropic.com"}
        )
        assert reason is None

    def test_allows_ordinary_commands(self) -> None:
        reason = guard.evaluate("pytest -q", {"ANTHROPIC_BASE_URL": GATEWAY_URL})
        assert reason is None

    def test_allows_reading_the_probe_source(self) -> None:
        """Inspecting the tool is not the same as running it against the gateway."""
        reason = guard.evaluate(
            f"grep -n model {PROBE}", {"ANTHROPIC_BASE_URL": GATEWAY_URL}
        )
        assert reason is None

    def test_allows_a_non_anthropic_bundled_skill(self) -> None:
        reason = guard.evaluate(
            "python3 /x/bundled-skills/2.1.318/abc/other/run.py",
            {"ANTHROPIC_BASE_URL": GATEWAY_URL},
        )
        assert reason is None


class TestMain:
    """End-to-end through the hook's stdin/stdout contract."""

    def _run(
        self, monkeypatch: pytest.MonkeyPatch, payload: dict, env: dict[str, str]
    ) -> int:
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        return guard.main()

    def test_denies_and_returns_2(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = {
            "tool_name": "Bash",
            "tool_input": {
                "command": f"python3 {PROBE} --self-test --model claude-opus-5-5 --yes"
            },
        }
        assert self._run(monkeypatch, payload, {"ANTHROPIC_BASE_URL": GATEWAY_URL}) == 2

    def test_allows_ordinary_bash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = {"tool_name": "Bash", "tool_input": {"command": "ls -la"}}
        assert self._run(monkeypatch, payload, {"ANTHROPIC_BASE_URL": GATEWAY_URL}) == 0

    def test_ignores_other_tools(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = {"tool_name": "Read", "tool_input": {"file_path": "/tmp/x"}}
        assert self._run(monkeypatch, payload, {"ANTHROPIC_BASE_URL": GATEWAY_URL}) == 0

    def test_malformed_payload_allows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
        assert guard.main() == 0

    def test_empty_stdin_allows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))
        assert guard.main() == 0

    def test_missing_command_allows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = {"tool_name": "Bash", "tool_input": {}}
        assert self._run(monkeypatch, payload, {"ANTHROPIC_BASE_URL": GATEWAY_URL}) == 0

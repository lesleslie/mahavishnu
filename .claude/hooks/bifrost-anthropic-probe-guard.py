#!/usr/bin/env python3
"""PreToolUse guard — stop Claude Code's first-party Anthropic tools hitting Bifrost.

Claude Code ships bundled skills under ``bundled-skills/<version>/<hash>/``. The
``claude-api`` skill's ``drop_block_probe.py`` probes Anthropic's
*preserved thinking* controls (``thinking-binding-controls-2026-08-01``,
``block_binding``). It is stdlib-only, authenticates with
``ANTHROPIC_API_KEY`` / ``ANTHROPIC_AUTH_TOKEN``, and takes its endpoint from
``--base-url`` — defaulting to ``$ANTHROPIC_BASE_URL``.

When Claude Code is routed through the Bodai Bifrost gateway, the session
environment sets ``ANTHROPIC_BASE_URL=http://127.0.0.1:8471/anthropic``. The
probe inherits it, asks a MiniMax-backed provider for a Claude model id, and
fails with ``no keys found that support model: claude-opus-5-5`` — a 400 that
looks like a gateway problem and is not one.

This hook blocks that combination. It fires only when *all three* hold:

1. the command would actually *execute* Anthropic's first-party tooling (the
   ``claude-api`` bundled skill), not merely mention it, and
2. the effective Anthropic base URL is the Bifrost gateway.

Requiring execution rather than a mention matters: reading or grepping the
probe's source cannot reach the network, and blocking those calls would make
the guard a nuisance rather than a safeguard.

An explicit ``--base-url`` counts as the operator having chosen the endpoint
on purpose and is always allowed — including when that choice is the gateway.
The same goes for scrubbing the variable (``env -u ANTHROPIC_BASE_URL``,
``unset ANTHROPIC_BASE_URL``), which is the recommended way to run the probe
against Anthropic.

Exit codes:
- ``0`` — allow (the common case; also every unexpected-error path)
- ``2`` — deny, with the reason on stderr for the model to read

Never raises: an unhandled exception must not block ordinary Bash work.
"""

from __future__ import annotations

import json
import os
import re
import sys
from urllib.parse import urlparse

#: Script names that identify Anthropic's first-party tooling in a command
#: line. ``drop_block_probe.py`` is the confirmed offender; the name is
#: distinctive enough to match on its own, whether the command names the full
#: bundled-skill path or just runs the script from inside the skill directory.
PROBE_SCRIPT_MARKERS: tuple[str, ...] = ("drop_block_probe.py",)

#: Marker for a Claude Code bundled-skill path.
BUNDLED_SKILL_MARKER = "bundled-skills/"

#: The bundled skill directory that holds Anthropic-first-party tooling.
ANTHROPIC_SKILL_MARKER = "claude-api"

#: A token that runs Python. Requiring the interpreter — not just the file
#: name — is what keeps read-only commands (``grep``, ``cat``, ``ls``) out of
#: the guard's way: they name the tool but cannot reach the network.
_PYTHON_RE = re.compile(r"(?:^|[\s/])python(?:\d+(?:\.\d+)?)?(?:\s|$)")

#: A leading ``VAR=value`` assignment — an environment prefix, not the
#: command being run. ``P=/path/probe.py`` must not read as an invocation.
_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

#: Default Bifrost gateway port; overridable so a relocated gateway is caught.
DEFAULT_GATEWAY_PORT = 8471

#: Hosts that mean "the local gateway" rather than "a remote Anthropic API".
LOCAL_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})

#: The Anthropic API the probe is meant to talk to.
ANTHROPIC_API_URL = "https://api.anthropic.com"

#: Inline ``ANTHROPIC_BASE_URL=<value>`` assignment in a shell command.
_INLINE_BASE_URL_RE = re.compile(r"ANTHROPIC_BASE_URL=(\S+)")

#: Explicit ``--base-url <value>`` flag (also ``--base-url=<value>``).
_FLAG_BASE_URL_RE = re.compile(r"--base-url[=\s]+(\S+)")

#: Commands that deliberately scrub the variable before running.
_ENV_UNSET_RE = re.compile(
    r"(?:^|\s)(?:env\s+(?:-\S+\s+)*-u\s+ANTHROPIC_BASE_URL|unset\s+ANTHROPIC_BASE_URL)"
)


def _gateway_port() -> int:
    """Return the port the local Bifrost gateway listens on."""
    raw = os.environ.get("BIFROST_PORT", "").strip()
    if raw.isdigit():
        return int(raw)
    return DEFAULT_GATEWAY_PORT


def is_gateway_url(url: str) -> bool:
    """Whether ``url`` points at the local Bifrost gateway.

    The gateway's Anthropic surface is ``http://127.0.0.1:8471/anthropic``.
    Only a loopback host on the gateway's port counts — a remote URL with the
    same path is some other service.
    """
    if not url:
        return False
    try:
        parsed = urlparse(url if "//" in url else f"//{url}")
    except ValueError:
        return False
    host = (parsed.hostname or "").strip().lower()
    if host not in LOCAL_HOSTS:
        return False
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return port == _gateway_port()


def _strip_quotes(value: str) -> str:
    """Strip one layer of matching quotes from a shell token."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def mentions_anthropic_tooling(command: str) -> bool:
    """Whether ``command`` names Anthropic's first-party tooling at all.

    Two ways to match:

    - the probe script by name, however the command spells the path (the
      script is distinctive enough to match on its own), or
    - any script inside the bundled ``claude-api`` skill, so sibling tools in
      the same skill are covered too.
    """
    if not command:
        return False
    if any(marker in command for marker in PROBE_SCRIPT_MARKERS):
        return True
    return ANTHROPIC_SKILL_MARKER in command and BUNDLED_SKILL_MARKER in command


def invokes_anthropic_tooling(command: str) -> bool:
    """Whether ``command`` would actually execute Anthropic's first-party tooling.

    Naming the tool is not enough — reading or grepping its source cannot
    reach the network. The command must also run Python (any interpreter
    spelling: ``python``, ``python3``, ``python3.13``, an absolute path, a
    venv interpreter), or name the script as the executable it runs.
    """
    if not mentions_anthropic_tooling(command):
        return False

    if _PYTHON_RE.search(command):
        return True

    tokens = command.split()
    while tokens and _ASSIGNMENT_RE.match(tokens[0]):
        tokens.pop(0)
    if not tokens:
        return False
    first = tokens[0]
    return first.endswith(".py") and (
        "drop_block_probe" in first
        or (BUNDLED_SKILL_MARKER in first and ANTHROPIC_SKILL_MARKER in first)
    )


def effective_base_url(command: str, env: dict[str, str]) -> tuple[str, bool]:
    """Resolve the Anthropic base URL a command would actually use.

    Args:
        command: the shell command about to run.
        env: the process environment (the session's, for a Claude Code hook).

    Returns:
        A ``(url, explicit)`` pair. ``explicit`` is True when the operator
        chose the endpoint on the command line — an explicit ``--base-url``
        flag, or a deliberate scrub of the variable. An explicit choice is
        never second-guessed by this hook.
    """
    flag_match = _FLAG_BASE_URL_RE.search(command)
    if flag_match:
        return _strip_quotes(flag_match.group(1)), True

    if _ENV_UNSET_RE.search(command):
        return "", True

    inline_match = _INLINE_BASE_URL_RE.search(command)
    if inline_match:
        return _strip_quotes(inline_match.group(1)), False

    return env.get("ANTHROPIC_BASE_URL", "").strip(), False


def _deny_message(url: str, script_hint: str) -> str:
    """Build the stderr explanation shown to the model when the call is denied."""
    return (
        "BLOCKED: Anthropic first-party API tooling was pointed at the Bodai "
        f"Bifrost gateway ({url}), which is backed by MiniMax and does not "
        "serve Claude models.\n\n"
        "The request would fail with:\n"
        "  no keys found that support model: claude-opus-5-5\n\n"
        "Run it against Anthropic instead:\n"
        "  env -u ANTHROPIC_BASE_URL -u ANTHROPIC_AUTH_TOKEN "
        "-u ANTHROPIC_CUSTOM_HEADERS \\\n"
        "    ANTHROPIC_API_KEY=sk-ant-... \\\n"
        f"    python3 {script_hint} --self-test --model claude-opus-5-5 --yes "
        f"--base-url {ANTHROPIC_API_URL}\n\n"
        "To probe the gateway on purpose, pass "
        f"--base-url {url} explicitly."
    )


def _script_hint(command: str) -> str:
    """Best-effort script path to echo back in the deny message."""
    for token in command.split():
        candidate = token.split("=", 1)[-1] if _ASSIGNMENT_RE.match(token) else token
        if candidate.endswith(".py") and (
            "/" in candidate or "drop_block_probe" in candidate
        ):
            return _strip_quotes(candidate)
    return "<script>"


def evaluate(command: str, env: dict[str, str]) -> str | None:
    """Return a deny reason for ``command``, or None to allow it.

    Args:
        command: the Bash command about to run.
        env: the process environment.

    Returns:
        The explanation to show the model when the call must be blocked, or
        None when the call may proceed.
    """
    if not invokes_anthropic_tooling(command):
        return None

    url, explicit = effective_base_url(command, env)
    if explicit:
        return None
    if not is_gateway_url(url):
        return None
    return _deny_message(url, _script_hint(command))


def main() -> int:
    """Read the hook payload, evaluate the command, and exit.

    Returns 2 to deny the tool call (with the reason on stderr), 0 to allow.
    """
    try:
        payload_raw = sys.stdin.read()
    except OSError:
        return 0

    if not payload_raw.strip():
        return 0

    try:
        payload = json.loads(payload_raw)
    except json.JSONDecodeError:
        return 0

    if not isinstance(payload, dict):
        return 0

    tool_name = payload.get("tool_name")
    if tool_name != "Bash":
        return 0

    tool_input = payload.get("tool_input")
    command = ""
    if isinstance(tool_input, dict):
        raw_command = tool_input.get("command")
        if isinstance(raw_command, str):
            command = raw_command

    try:
        reason = evaluate(command, dict(os.environ))
    except Exception as exc:  # noqa: BLE001 - a guard must never block work
        sys.stderr.write(f"bifrost-anthropic-probe-guard: {exc!r}\n")
        return 0

    if reason is None:
        return 0

    sys.stderr.write(reason + "\n")
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - never block on an unexpected error
        sys.stderr.write(f"bifrost-anthropic-probe-guard: {exc!r}\n")
        sys.exit(0)

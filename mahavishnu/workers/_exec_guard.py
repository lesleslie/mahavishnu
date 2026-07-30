"""Shared command validation for isolated-execution workers.

Extracted from ``ContainerWorker`` so that runtime adapters (Apple
``container``, cloud sandboxes) share one guard without importing the
Docker-era worker, which is slated for deprecation.
"""

from __future__ import annotations

import shlex

ALLOWED_COMMANDS: frozenset[str] = frozenset(
    {
        "python",
        "pip",
        "npm",
        "node",
        "ls",
        "cat",
        "echo",
        "grep",
        "find",
        "head",
        "tail",
        "wc",
        "pwd",
        "cd",
        "mkdir",
        "touch",
        "rm",
        "cp",
        "mv",
        "sort",
        "uniq",
        "cut",
        "awk",
        "sed",
        "git",
        "pytest",
        "black",
    }
)

DANGEROUS_PATTERNS: tuple[str, ...] = (
    "rm -rf /",
    "mkfs",
    "dd if=",
    "> /dev/sd",
    "chmod 000",
    "chown root:",
    "curl | sh",
    "wget | sh",
    "&& rm",
    "; rm",
    "| rm",
    "nc -e",
    "ncat",
    "/dev/tcp",
    "/dev/udp",
    "bind shell",
    "reverse shell",
)

MAX_COMMAND_LENGTH = 10000


def validate_command(command: str) -> None:
    """Validate a task command before it reaches any runtime.

    Raises:
        ValueError: If the command is not a string, too long, matches a
            dangerous pattern, is empty, or is not on the allowlist.
    """
    if not isinstance(command, str):
        # ValueError is retained for this public validator's documented contract.
        raise ValueError("Command must be a string")  # noqa: TRY004

    if len(command) > MAX_COMMAND_LENGTH:
        raise ValueError(f"Command too long: {len(command)} > {MAX_COMMAND_LENGTH} characters")

    command_lower = command.lower()
    for pattern in DANGEROUS_PATTERNS:
        if pattern in command_lower:
            raise ValueError(
                f"Command contains dangerous pattern {pattern!r}. "
                "This command is not allowed for security reasons."
            )

    first_word = command.strip().split()[0] if command.strip() else ""
    if not first_word:
        raise ValueError("Command cannot be empty")

    if first_word not in ALLOWED_COMMANDS:
        raise ValueError(
            f"Command {first_word!r} is not in the allowed list. "
            f"Allowed commands: {', '.join(sorted(ALLOWED_COMMANDS))}"
        )


def sanitize_command(command: str) -> str:
    """Quote a command so shell metacharacters cannot break out."""
    return shlex.quote(command)

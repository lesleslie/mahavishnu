"""Worker type registry with command templates and configurations.

This module defines all available worker types and their configurations,
making it easy to add new worker types without modifying core code.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class WorkerCategory(Enum):
    """Categories of workers for organization."""

    AI_ASSISTANT = "ai_assistant"  # AI coding assistants
    SHELL = "shell"  # Shell/REPL environments
    CONTAINER = "container"  # Container-based execution
    REMOTE = "remote"  # Remote execution (SSH)
    APPLICATION = "application"  # Desktop applications via MCP


@dataclass
class WorkerConfig:
    """Configuration for a worker type.

    Attributes:
        name: Human-readable name
        worker_type: Unique identifier (e.g., "terminal-shell")
        command: Command template to start the worker
        category: Worker category for grouping
        description: What this worker does
        completion_markers: Strings that indicate task completion
        error_markers: Strings that indicate errors
        stream_format: Output format ("json", "text", "line-delimited")
        supports_interactive: Whether worker supports interactive mode
        default_timeout: Default timeout in seconds
        env_vars: Environment variables to set
        requires_tool: External tool that must be installed
        mcp_server: Optional MCP server name for application workers
    """

    name: str
    worker_type: str
    command: str
    category: WorkerCategory
    description: str = ""
    completion_markers: list[str] = field(default_factory=list)
    error_markers: list[str] = field(default_factory=lambda: ["error:", "Error:", "ERROR:", "Exception:"])
    stream_format: str = "text"
    supports_interactive: bool = True
    default_timeout: int = 300
    env_vars: dict[str, str] = field(default_factory=dict)
    requires_tool: str | None = None
    mcp_server: str | None = None


# Worker type registry - all available workers
WORKER_REGISTRY: dict[str, WorkerConfig] = {
    # AI Assistants
    "terminal-qwen": WorkerConfig(
        name="Qwen AI",
        worker_type="terminal-qwen",
        command="qwen -o stream-json --approval-mode yolo",
        category=WorkerCategory.AI_ASSISTANT,
        description="Fast local AI coding assistant with Qwen model",
        completion_markers=["finish_reason", '"done"', '"type": "done"'],
        stream_format="json",
        requires_tool="qwen",
    ),
    "terminal-claude": WorkerConfig(
        name="Claude Code",
        worker_type="terminal-claude",
        command="claude --output-format stream-json --permission-mode acceptEdits",
        category=WorkerCategory.AI_ASSISTANT,
        description="Claude Code CLI for complex reasoning and coding",
        completion_markers=["finish_reason", '"done"', '"type": "done"'],
        stream_format="json",
        requires_tool="claude",
    ),
    "terminal-aider": WorkerConfig(
        name="Aider",
        worker_type="terminal-aider",
        command="aider --no-auto-commits --no-check-update",
        category=WorkerCategory.AI_ASSISTANT,
        description="AI pair programming assistant with git integration",
        completion_markers=["Tokens:", "Cost:", "RESTACK"],
        stream_format="text",
        requires_tool="aider",
    ),
    "terminal-opencode": WorkerConfig(
        name="OpenCode",
        worker_type="terminal-opencode",
        command="opencode run",
        category=WorkerCategory.AI_ASSISTANT,
        description="OpenCode AI assistant for code generation",
        completion_markers=["completed", "finished", "done"],
        stream_format="text",
        requires_tool="opencode",
    ),
    # Shell/REPL Environments
    "terminal-shell": WorkerConfig(
        name="Bash Shell",
        worker_type="terminal-shell",
        command="bash --noediting",
        category=WorkerCategory.SHELL,
        description="Basic bash shell for general command execution",
        completion_markers=["$"],  # Prompt indicates ready
        stream_format="text",
        default_timeout=60,
    ),
    "terminal-zsh": WorkerConfig(
        name="Zsh Shell",
        worker_type="terminal-zsh",
        command="zsh",
        category=WorkerCategory.SHELL,
        description="Zsh shell for general command execution",
        completion_markers=["%", "#"],  # Zsh prompts
        stream_format="text",
        default_timeout=60,
    ),
    "terminal-python": WorkerConfig(
        name="Python REPL",
        worker_type="terminal-python",
        command="python3 -iq",
        category=WorkerCategory.SHELL,
        description="Python REPL for data processing and scripting",
        completion_markers=[">>>", "..."],
        stream_format="text",
        requires_tool="python3",
    ),
    "terminal-ipython": WorkerConfig(
        name="IPython",
        worker_type="terminal-ipython",
        command="ipython --no-banner",
        category=WorkerCategory.SHELL,
        description="Enhanced Python REPL with rich features",
        completion_markers=["In [", "Out ["],
        stream_format="text",
        requires_tool="ipython",
    ),
    "terminal-node": WorkerConfig(
        name="Node.js REPL",
        worker_type="terminal-node",
        command="node -i",
        category=WorkerCategory.SHELL,
        description="Node.js REPL for JavaScript/TypeScript tasks",
        completion_markers=[">"],
        stream_format="text",
        requires_tool="node",
    ),
    # Remote Execution
    "terminal-ssh": WorkerConfig(
        name="SSH Remote",
        worker_type="terminal-ssh",
        command="ssh {host}",  # Requires host parameter
        category=WorkerCategory.REMOTE,
        description="SSH connection for remote command execution",
        completion_markers=["$", "#", "%"],
        stream_format="text",
        requires_tool="ssh",
        default_timeout=600,
    ),
    # Container (existing)
    "container": WorkerConfig(
        name="Docker Container",
        worker_type="container",
        command="",  # Handled by ContainerWorker
        category=WorkerCategory.CONTAINER,
        description="Docker container for isolated task execution",
        supports_interactive=False,
    ),
    "container-executor": WorkerConfig(
        name="Container Executor",
        worker_type="container-executor",
        command="",  # Handled by ContainerWorker
        category=WorkerCategory.CONTAINER,
        description="Docker/Podman container for isolated execution",
        supports_interactive=False,
    ),
    # Application Workers (via MCP)
    "application-gimp": WorkerConfig(
        name="GIMP Image Editor",
        worker_type="application-gimp",
        command="",  # Handled via MCP
        category=WorkerCategory.APPLICATION,
        description="GIMP image editing via MCP server",
        mcp_server="gimp-mcp",
        supports_interactive=False,
    ),
}


def get_worker_config(worker_type: str) -> WorkerConfig | None:
    """Get configuration for a worker type.

    Args:
        worker_type: Worker type identifier

    Returns:
        WorkerConfig or None if not found
    """
    return WORKER_REGISTRY.get(worker_type)


def list_worker_types(category: WorkerCategory | None = None) -> list[str]:
    """List available worker types, optionally filtered by category.

    Args:
        category: Optional category filter

    Returns:
        List of worker type identifiers
    """
    if category is None:
        return list(WORKER_REGISTRY.keys())
    return [wt for wt, cfg in WORKER_REGISTRY.items() if cfg.category == category]


def get_workers_by_category() -> dict[WorkerCategory, list[WorkerConfig]]:
    """Get all workers grouped by category.

    Returns:
        Dictionary mapping categories to worker configs
    """
    result: dict[WorkerCategory, list[WorkerConfig]] = {cat: [] for cat in WorkerCategory}
    for cfg in WORKER_REGISTRY.values():
        result[cfg.category].append(cfg)
    return result


def validate_worker_dependencies() -> dict[str, bool]:
    """Check if required tools for workers are installed.

    Returns:
        Dictionary mapping worker types to availability status
    """
    import shutil

    results = {}
    for worker_type, config in WORKER_REGISTRY.items():
        if config.requires_tool:
            results[worker_type] = shutil.which(config.requires_tool) is not None
        else:
            results[worker_type] = True  # No external dependency
    return results


__all__ = [
    "WorkerCategory",
    "WorkerConfig",
    "WORKER_REGISTRY",
    "get_worker_config",
    "list_worker_types",
    "get_workers_by_category",
    "validate_worker_dependencies",
]

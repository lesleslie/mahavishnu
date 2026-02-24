"""Mahavishnu Worker System.

Provides worker orchestration for headless AI execution across terminals
and containers with real-time progress tracking and Session-Buddy integration.

Available Worker Types:
    AI Assistants: terminal-qwen, terminal-claude, terminal-aider, terminal-opencode
    Shell/REPL: terminal-shell, terminal-zsh, terminal-python, terminal-ipython, terminal-node
    Remote: terminal-ssh
    Container: container, container-executor
    Application: application-gimp (via MCP)
"""

from mahavishnu.workers.base import BaseWorker, WorkerResult, WorkerStatus
from mahavishnu.workers.container import ContainerWorker
from mahavishnu.workers.debug_monitor import DebugMonitorWorker
from mahavishnu.workers.generic_shell import GenericShellWorker
from mahavishnu.workers.manager import WorkerManager
from mahavishnu.workers.registry import (
    WorkerCategory,
    WorkerConfig,
    WORKER_REGISTRY,
    get_worker_config,
    get_workers_by_category,
    list_worker_types,
    validate_worker_dependencies,
)
from mahavishnu.workers.terminal import TerminalAIWorker

__all__ = [
    # Base classes
    "BaseWorker",
    "WorkerResult",
    "WorkerStatus",
    # Managers
    "WorkerManager",
    # Workers
    "TerminalAIWorker",
    "ContainerWorker",
    "DebugMonitorWorker",
    "GenericShellWorker",
    # Registry
    "WorkerCategory",
    "WorkerConfig",
    "WORKER_REGISTRY",
    "get_worker_config",
    "get_workers_by_category",
    "list_worker_types",
    "validate_worker_dependencies",
]

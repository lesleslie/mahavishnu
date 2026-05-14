"""Mahavishnu Worker System.

Provides worker orchestration for headless AI execution across terminals
and containers with real-time progress tracking and Session-Buddy integration.

Available Worker Types:
    AI Assistants: terminal-qwen (legacy), terminal-claude, terminal-openclaw,
        terminal-deepagents, terminal-clai, terminal-ollama
    Gateways: gateway-openclaw
    Shell/REPL: terminal-shell, terminal-zsh, terminal-python, terminal-ipython, terminal-node
    Database: terminal-mysql, terminal-psql, terminal-redis
    WebAssembly: terminal-wasmtime, terminal-wasmer
    Remote: terminal-ssh
    Container: container, container-executor
    Application: application-gimp, application-inkscape, application-blender, application-mdinject,
        application-pycharm

Routing notes:
    - communication-style tasks prefer gateway-openclaw when OPENCLAW_GATEWAY_URL
      is configured, and otherwise fall back to terminal-openclaw.
"""

from mahavishnu.workers.application import ApplicationWorker
from mahavishnu.workers.base import BaseWorker, WorkerResult, WorkerStatus
from mahavishnu.workers.container import ContainerWorker
from mahavishnu.workers.debug_monitor import DebugMonitorWorker
from mahavishnu.workers.generic_shell import GenericShellWorker
from mahavishnu.workers.manager import WorkerManager
from mahavishnu.workers.ollama import OllamaConfig, OllamaWorker
from mahavishnu.workers.openclaw_gateway import (
    HTTPOpenClawGatewayClient,
    OpenClawGatewayClient,
    OpenClawGatewayConfig,
    OpenClawGatewayWorker,
    OpenClawTaskRequest,
)
from mahavishnu.workers.protocol import TerminalWorkerProtocol
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
from mahavishnu.workers.terminal import TerminalAIWorker

__all__ = [
    # Base classes
    "BaseWorker",
    "WorkerResult",
    "WorkerStatus",
    # Managers
    "WorkerManager",
    # Workers
    "TerminalWorkerProtocol",
    "TerminalAIWorker",
    "ContainerWorker",
    "DebugMonitorWorker",
    "GenericShellWorker",
    "ApplicationWorker",
    "OllamaWorker",
    "OllamaConfig",
    "HTTPOpenClawGatewayClient",
    "OpenClawGatewayClient",
    "OpenClawGatewayConfig",
    "OpenClawGatewayWorker",
    "OpenClawTaskRequest",
    # Registry
    "WorkerCategory",
    "WorkerConfig",
    "WORKER_REGISTRY",
    "get_worker_config",
    "get_workers_by_category",
    "list_worker_types",
    "resolve_worker_type",
    "validate_worker_dependencies",
]

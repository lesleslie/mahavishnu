"""Mahavishnu Worker System.

Provides worker orchestration for headless AI execution across terminals
and containers with real-time progress tracking and Session-Buddy integration.

Available Worker Types:
    AI Assistants: terminal-claude, terminal-deepagents,
        terminal-clai (terminal-qwen is a legacy alias; terminal-ollama removed — use OllamaWorker)
    Gateways: gateway-openclaw
    Shell/REPL: terminal-shell, terminal-python, terminal-ipython, terminal-node
    Database: terminal-mysql, terminal-psql, terminal-redis
    WebAssembly: terminal-wasmtime, terminal-wasmer
    Remote: terminal-ssh
    Isolated: container-executor (auto-tier), apple-container, e2b-sandbox
    Application: application-gimp, application-inkscape, application-blender, application-mdinject,
        application-pycharm

Routing notes:
    - communication-style tasks prefer gateway-openclaw when OPENCLAW_GATEWAY_URL
      is configured.
"""

from mahavishnu.workers.apple_container import AppleContainerWorker
from mahavishnu.workers.application import ApplicationWorker
from mahavishnu.workers.base import BaseWorker, WorkerResult, WorkerStatus
from mahavishnu.workers.crow import CrowWorker
from mahavishnu.workers.e2b_sandbox import E2BSandboxWorker
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
from mahavishnu.workers.openhands import OpenHandsWorker
from mahavishnu.workers.protocol import ProgressSnapshot, TerminalWorkerProtocol, is_terminal_worker
from mahavishnu.workers.registry import (
    WORKER_REGISTRY,
    WorkerCategory,
    WorkerConfig,
    get_worker_config,
    get_worker_entry,
    get_workers_by_category,
    list_worker_types,
    resolve_worker_type,
    validate_worker_dependencies,
)
from mahavishnu.workers.shepherd_backend import (
    ShepherdBackendError,
    ShepherdBackendWorker,
    ShepherdJailUnavailableError,
    probe_host_capability,
)

__all__ = [
    "WORKER_REGISTRY",
    "AppleContainerWorker",
    "ApplicationWorker",
    "BaseWorker",
    "CrowWorker",
    "E2BSandboxWorker",
    "GenericShellWorker",
    "HTTPOpenClawGatewayClient",
    "OllamaConfig",
    "OllamaWorker",
    "OpenClawGatewayClient",
    "OpenClawGatewayConfig",
    "OpenClawGatewayWorker",
    "OpenClawTaskRequest",
    "OpenHandsWorker",
    "ProgressSnapshot",
    "ShepherdBackendError",
    "ShepherdBackendWorker",
    "ShepherdJailUnavailableError",
    "TerminalWorkerProtocol",
    "WorkerCategory",
    "WorkerConfig",
    "WorkerManager",
    "WorkerResult",
    "WorkerStatus",
    "get_worker_config",
    "get_worker_entry",
    "get_workers_by_category",
    "is_terminal_worker",
    "list_worker_types",
    "probe_host_capability",
    "resolve_worker_type",
    "validate_worker_dependencies",
]

"""Mahavishnu Worker System.

Provides worker orchestration for headless AI execution across terminals
with real-time progress tracking and Session-Buddy integration.

After Plan v3 Phase 4.5b (legacy-worker-removal), the following surfaces
were retired: ``apple-container``, ``e2b-sandbox``, ``generic_shell``,
``ollama``, ``openclaw_gateway``, ``crow``, ``application``, ``a2a``,
``protocol``, plus the capability caches ``_cache.py`` / ``_static.py``.
The canonical orchestration layer is now ``mahavishnu/pools/``; the
isolated-worker legacy surface is reduced to ``shepherd_backend`` only
(see ``docs/decisions/2026-09-24-legacy-worker-deprecation.md``).

Available Worker Types (terminal-based after the legacy purge):
    AI Assistants: terminal-claude, terminal-deepagents,
        terminal-clai (terminal-qwen is a legacy alias)
    Gateways: gateway-openclaw
    Shell/REPL: terminal-shell, terminal-python, terminal-ipython, terminal-node
    Database: terminal-mysql, terminal-psql, terminal-redis
    WebAssembly: terminal-wasmtime, terminal-wasmer
    Remote: terminal-ssh
    Isolated (post-purge): container-executor (auto-tier), shepherd (only)
    Application: application-pycharm (after purge)
    Adapter Workers: openclaw_gateway (gateway role)

Routing notes:
    - communication-style tasks prefer openclaw_gateway when
      OPENCLAW_GATEWAY_URL is configured.
"""

from mahavishnu.workers.base import BaseWorker, WorkerResult, WorkerStatus
from mahavishnu.workers.cloud_worker import CloudWorker, CloudWorkerConfig
from mahavishnu.workers.manager import WorkerManager
from mahavishnu.workers.openhands import OpenHandsWorker
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
    "BaseWorker",
    "CloudWorker",
    "CloudWorkerConfig",
    "OpenHandsWorker",
    "ShepherdBackendError",
    "ShepherdBackendWorker",
    "ShepherdJailUnavailableError",
    "WorkerCategory",
    "WorkerConfig",
    "WORKER_REGISTRY",
    "WorkerManager",
    "WorkerResult",
    "WorkerStatus",
    "get_worker_config",
    "get_worker_entry",
    "get_workers_by_category",
    "list_worker_types",
    "probe_host_capability",
    "resolve_worker_type",
    "validate_worker_dependencies",
]

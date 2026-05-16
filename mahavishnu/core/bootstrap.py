"""Bootstrap helpers for MahavishnuApp.

These helpers keep the application class focused on wiring and delegation
while preserving the existing initialization and recovery behavior.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .config import MahavishnuSettings
from .errors import ConfigurationError


def load_config() -> MahavishnuSettings:
    """Load configuration from Oneiric-compatible sources."""
    try:
        return MahavishnuSettings()
    except Exception as exc:
        raise ConfigurationError(
            message=f"Failed to load configuration: {exc}",
            details={"error": str(exc), "error_type": type(exc).__name__},
        ) from exc


def _validate_path(path_str: str, allowed_base_paths: list[str] | None = None) -> Path:
    path = Path(path_str)
    normalized_path = str(path_str).replace("\\", "/")
    if (
        ".." in path.parts
        or normalized_path.startswith("../")
        or "/../" in normalized_path
        or normalized_path.endswith("/..")
        or "..\\" in path_str
        or "\\.." in path_str
    ):
        raise ConfigurationError(
            message=f"Invalid path contains directory traversal: {path_str}",
            details={"path": path_str, "suggestion": "Remove any '..' sequences from path"},
        )

    abs_path = path.expanduser().resolve()
    allowed_paths = allowed_base_paths or [str(Path.cwd()), __import__("tempfile").gettempdir()]
    is_allowed = False
    for allowed_base in allowed_paths:
        try:
            abs_path.relative_to(Path(allowed_base).expanduser().resolve())
            is_allowed = True
            break
        except ValueError:
            continue

    if not is_allowed:
        raise ConfigurationError(
            message=f"Path is outside allowed directory: {path_str}",
            details={
                "path": path_str,
                "allowed_paths": allowed_paths,
                "suggestion": "Ensure path is within allowed boundaries",
            },
        )

    return abs_path


def _resolve_repos_path(app: Any, logger: Any) -> tuple[Path, bool]:
    primary_path = _validate_path(app.config.repos_path).expanduser()
    fallback_path = _validate_path("settings/repos.yaml").expanduser()

    if primary_path.exists():
        return primary_path, False
    if fallback_path.exists() and fallback_path != primary_path:
        logger.warning(
            "Repository config fallback: %s not found, using %s. "
            "Consider creating ecosystem.yaml for richer configuration "
            "(roles taxonomy, coordination tracking).",
            primary_path,
            fallback_path,
        )
        return fallback_path, True
    raise ConfigurationError(
        message=f"No repository configuration found. Tried: {primary_path}, {fallback_path}",
        details={
            "repos_path": str(primary_path),
            "fallback_path": str(fallback_path),
            "suggestion": (
                "Create settings/ecosystem.yaml (preferred) or "
                "settings/repos.yaml with repository configurations"
            ),
        },
    )


def _load_raw_yaml(repos_path: Path) -> Any:
    try:
        with repos_path.open() as f:
            return yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise ConfigurationError(
            message=f"Invalid YAML in {repos_path.name}: {exc}",
            details={"repos_path": str(repos_path), "error": str(exc)},
        ) from exc


def _parse_repos_config_file(repos_path: Path) -> dict:
    try:
        raw_config = _load_raw_yaml(repos_path)
        if not isinstance(raw_config, dict) or "repos" not in raw_config:
            raise ConfigurationError(
                message=f"Invalid repository config: missing 'repos' key in {repos_path.name}",
                details={"repos_path": str(repos_path)},
            )
        return raw_config
    except ConfigurationError:
        raise
    except Exception as exc:
        raise ConfigurationError(
            message=f"Failed to load {repos_path.name}: {exc}",
            details={"repos_path": str(repos_path), "error": str(exc)},
        ) from exc


def load_repos(app: Any) -> None:
    """Load repository configurations with fallback chain."""
    import logging

    logger = logging.getLogger(__name__)
    repos_path, using_fallback = _resolve_repos_path(app, logger)
    raw_config = _parse_repos_config_file(repos_path)

    app.roles_config = raw_config.get("roles", [])
    app.repos_config = {"repos": raw_config["repos"], "roles": app.roles_config}

    source = "repos.yaml (fallback)" if using_fallback else "ecosystem.yaml"
    logger.info("Loaded %d repositories from %s", len(raw_config.get("repos", [])), source)


def _import_adapter_class(name: str) -> type | None:
    try:
        if name == "prefect":
            from ..engines.prefect_adapter_impl import PrefectAdapter
            return PrefectAdapter
        if name == "llamaindex":
            from ..engines.llamaindex_adapter_impl import LlamaIndexAdapter
            return LlamaIndexAdapter
        if name == "agno":
            from ..engines.agno_adapter_impl import AgnoAdapter
            return AgnoAdapter
        if name == "hatchet":
            from ..engines.hatchet_adapter_impl import HatchetAdapterImpl
            return HatchetAdapterImpl
        if name == "worker":
            from .adapters.worker import WorkerOrchestratorAdapter
            return WorkerOrchestratorAdapter
    except ImportError:
        return None
    return None


def _collect_adapter_classes(app: Any, logger: Any) -> dict[str, type]:
    adapter_specs = [
        ("prefect", app.config.adapters.prefect_enabled),
        ("llamaindex", app.config.adapters.llamaindex_enabled),
        ("agno", app.config.adapters.agno_enabled),
        ("hatchet", app.config.adapters.hatchet_enabled),
        ("worker", getattr(app.config.workers, "enabled", True)),
    ]
    adapter_classes: dict[str, type] = {}
    for name, enabled in adapter_specs:
        if not enabled:
            continue
        cls = _import_adapter_class(name)
        if cls is not None:
            adapter_classes[name] = cls
        else:
            logger.warning("%s adapter not available due to missing dependencies", name)
    return adapter_classes


def _instantiate_adapters(app: Any, adapter_classes: dict[str, type], logger: Any) -> None:
    for adapter_name, adapter_class in adapter_classes.items():
        try:
            config_arg = app.config.hatchet if adapter_name == "hatchet" else app.config
            app.adapters[adapter_name] = adapter_class(config_arg)
        except ImportError as exc:
            logger.warning(
                "%s adapter initialization skipped due to missing optional dependencies: %s",
                adapter_name,
                exc,
            )
        except Exception as exc:
            raise ConfigurationError(
                message=f"Failed to initialize {adapter_name} adapter: {exc}",
                details={
                    "adapter": adapter_name,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            ) from exc


def initialize_adapters(app: Any) -> None:
    """Initialize enabled adapters based on configuration."""
    import logging

    logger = logging.getLogger(__name__)
    adapter_classes = _collect_adapter_classes(app, logger)
    _instantiate_adapters(app, adapter_classes, logger)

    worker_adapter = app.adapters.get("worker")
    app._worker_manager = (
        getattr(worker_adapter, "worker_manager", None) if worker_adapter is not None else None
    )


def init_observability(app: Any):
    """Initialize the shared observability service."""
    from .observability import init_observability as _init_observability

    return _init_observability(app.config)


def init_health_endpoint(app: Any):
    """Initialize the optional health endpoint."""
    if not app.config.health.enabled:
        return None

    from .health import HealthEndpoint, ServiceInfo

    service_info = ServiceInfo(
        name="mahavishnu",
        version=getattr(app.config, "version", "0.3.2"),
    )
    return HealthEndpoint(
        service_info=service_info,
        config=app.config.health,
    )


def initialize_runtime_services(app: Any) -> None:
    """Initialize the remaining runtime services on the application."""
    from collections import deque
    from contextlib import suppress
    import logging

    from ..qc.checker import QualityControl
    from ..session.checkpoint import SessionBuddy
    from .approval_manager import ApprovalManager
    from .backup_recovery import BackupManager, DisasterRecoveryManager
    from .coordination.manager import CoordinationManager
    from .coordination.memory import CoordinationMemory, SessionBuddyMemoryClient
    from .monitoring import MonitoringService
    from .opensearch_integration import OpenSearchIntegration
    from .permissions import RBACManager
    from .repo_manager import RepositoryManager
    from .resilience import ErrorRecoveryManager, ResiliencePatterns
    from .skill_registry import SkillRegistry
    from .state_backends.dhara import DharaStateBackend, DharaStateConfig
    from .task_router import StateManager

    logger = logging.getLogger(__name__)

    app.qc = QualityControl(app.config)

    app.session_buddy = SessionBuddy(app.config)
    app.session_buddy_integration = app.session_buddy
    app.coordination_memory = None
    try:
        app.coordination_memory = CoordinationMemory(
            SessionBuddyMemoryClient(app.config.pools.session_buddy_url),
            akosha_url=app.config.pools.akosha_url,
        )
    except Exception:
        app.coordination_memory = None

    try:
        from ..messaging.repository_messenger import RepositoryMessenger

        app.repository_messenger = RepositoryMessenger(app)
    except Exception:
        app.repository_messenger = None

    app.terminal_manager = None
    if app.config.terminal.enabled:
        app.terminal_manager = app._init_terminal_manager()

    app.workflow_state_manager = StateManager()
    app.skill_registry = SkillRegistry()
    app.event_activity = deque(maxlen=200)
    app.fix_activity = deque(maxlen=200)

    app.pool_manager = None
    app.memory_aggregator = None
    app._learning_pipeline = None
    if app.config.pools.enabled:
        app.pool_manager = app._init_pool_manager()
        if app.config.pools.memory_aggregation_enabled:
            app.memory_aggregator = app._init_memory_aggregator()

    if app.config.learning.enabled:
        app._learning_pipeline = app._init_learning_pipeline()

    app.rbac_manager = RBACManager(app.config)
    app.opensearch_integration = OpenSearchIntegration(app.config)

    app._dhara_state = None
    if app.config.dhara_state.enabled and app.dhara_url:
        with suppress(Exception):
            app._dhara_state = DharaStateBackend(
                base_url=app.dhara_url,
                config=DharaStateConfig(
                    enabled=app.config.dhara_state.enabled,
                    flush_interval_seconds=app.config.dhara_state.flush_interval_seconds,
                    max_routing_buffer_age_seconds=app.config.dhara_state.max_routing_buffer_age_seconds,
                ),
            )

    app.approval_manager = ApprovalManager(dhara_state=app._dhara_state)
    app.resilience_manager = ResiliencePatterns(app)
    app.error_recovery_manager = ErrorRecoveryManager(app)
    app._resilience_monitoring_task = None
    app.monitoring_service = MonitoringService(app)

    app.routing_metrics_server = None
    try:
        from .routing_metrics import get_routing_metrics

        if getattr(app.config.monitoring, "routing_metrics_enabled", True):
            get_routing_metrics("mahavishnu")
            logger.info("Routing metrics registered on shared /metrics surface")
        else:
            logger.info("Routing metrics disabled by configuration")
    except ImportError:
        logger.warning("Routing metrics module not available, skipping metrics initialization")
    except Exception as exc:
        logger.error("Failed to initialize routing metrics: %s", exc)

    app.backup_manager = BackupManager(app)
    app.recovery_manager = DisasterRecoveryManager(app)

    app.worktree_coordinator = None
    try:
        repos_path = _validate_path(app.config.repos_path).expanduser()
        app.repository_manager = RepositoryManager(repos_path)
        app.coordination_manager = CoordinationManager(str(repos_path))
        app.worktree_coordinator = None
        logger.info("WorktreeCoordinator components initialized")
    except Exception as exc:
        logger.warning("Failed to initialize WorktreeCoordinator: %s", exc)

    app.session_buddy_poller = None
    if app.config.session_buddy_polling.enabled:
        try:
            from ..integrations.session_buddy_poller import SessionBuddyPoller

            app.session_buddy_poller = SessionBuddyPoller(
                config=app.config,
                observability_manager=app.observability,
            )
            logger.info(
                "Session-Buddy poller initialized: endpoint=%s, interval=%ss",
                app.config.session_buddy_polling.endpoint,
                app.config.session_buddy_polling.interval_seconds,
            )
        except Exception as exc:
            logger.warning("Failed to initialize Session-Buddy poller: %s", exc)


def set_app_context(app: Any) -> None:
    """Set application context for dependency injection."""
    from .context import set_app_context as set_context
    from .oneiric_client import set_dhara_client_base_url

    set_dhara_client_base_url(app.dhara_url)

    agno_adapter = app.adapters.get("agno")
    llm_factory = None
    if agno_adapter is not None:

        class DefaultLLMFactory:
            """Default LLM factory using Agno configuration."""

            def __init__(self, config):
                self._config = config

            def create_llm(
                self, provider: str | None = None, model_id: str | None = None, **kwargs
            ):
                from agno.llm import LLM

                actual_provider = provider or self._config.agno.llm.provider.value
                actual_model = model_id or self._config.agno.llm.model_id
                llm_kwargs = {
                    "provider": actual_provider,
                    "model": actual_model,
                }
                if actual_provider == "ollama":
                    llm_kwargs["base_url"] = self._config.agno.llm.base_url
                llm_kwargs.update(kwargs)
                return LLM(**llm_kwargs)

            def get_default_provider(self) -> str:
                return self._config.agno.llm.provider.value

            def get_default_model(self) -> str:
                return self._config.agno.llm.model_id

        llm_factory = DefaultLLMFactory(app.config)

    set_context(llm_factory=llm_factory, agno_adapter=agno_adapter, app=app)

    import logging

    logger = logging.getLogger(__name__)
    if llm_factory or agno_adapter:
        logger.info(
            "Application context initialized: llm_factory=%s, agno_adapter=%s",
            "available" if llm_factory else "not available",
            "available" if agno_adapter else "not available",
        )


def init_terminal_manager(app: Any) -> Any:
    """Initialize terminal manager with the current MCP client wiring."""
    import logging

    logger = logging.getLogger(__name__)
    try:
        logger.info("Terminal management enabled, but MCP client not yet connected")
        logger.info("Terminal manager will be fully initialized in MCP server context")
        return None
    except Exception as exc:
        logger.warning("Failed to initialize terminal manager: %s", exc)
        return None


def resolve_dhara_url(config: Any) -> str:
    """Build the Dhara MCP URL from health dependency config."""
    dependency = config.health.dependencies.get("dhara")
    if dependency is None:
        return "http://localhost:8683/mcp"

    scheme = "https" if dependency.use_tls else "http"
    return f"{scheme}://{dependency.host}:{dependency.port}/mcp"


def init_pool_manager(app: Any) -> Any:
    """Initialize pool manager with the configured routing and persistence."""
    import logging

    logger = logging.getLogger(__name__)
    try:
        from ..mcp.protocols.message_bus import MessageBus
        from ..pools.manager import PoolManager, PoolSelector

        message_bus = MessageBus()
        pool_manager = PoolManager(
            terminal_manager=app.terminal_manager,
            session_buddy_client=app.session_buddy,
            message_bus=message_bus,
            dhara_state=getattr(app, "_dhara_state", None),
        )
        selector = PoolSelector(app.config.pools.routing_strategy)
        pool_manager.set_pool_selector(selector)
        logger.info(
            "Pool manager initialized (strategy=%s, default_type=%s)",
            app.config.pools.routing_strategy,
            app.config.pools.default_type,
        )
        return pool_manager
    except Exception as exc:
        logger.warning("Failed to initialize pool manager: %s", exc)
        return None


def init_memory_aggregator(app: Any) -> Any:
    """Initialize memory aggregator for cross-pool memory sync."""
    import logging

    logger = logging.getLogger(__name__)
    try:
        from ..pools.memory_aggregator import MemoryAggregator

        memory_aggregator = MemoryAggregator(
            session_buddy_url=app.config.pools.session_buddy_url,
            akosha_url=app.config.pools.akosha_url,
            sync_interval=app.config.pools.memory_sync_interval,
        )
        logger.info(
            "Memory aggregator initialized (sync_interval=%ss)",
            app.config.pools.memory_sync_interval,
        )
        return memory_aggregator
    except Exception as exc:
        logger.warning("Failed to initialize memory aggregator: %s", exc)
        return None


def init_learning_pipeline(app: Any) -> Any:
    """Initialize the review-gated learning pipeline service."""
    import logging

    logger = logging.getLogger(__name__)
    try:
        from .learning_pipeline import LearningPipelineService

        pipeline = LearningPipelineService(
            config=app.config.learning,
            session_buddy_url=app.config.pools.session_buddy_url,
            akosha_url=app.config.pools.akosha_url,
        )
        logger.info(
            "Learning pipeline initialized (interval=%ss, max_evidence=%s)",
            app.config.learning.collection_interval_seconds,
            app.config.learning.max_evidence_per_cycle,
        )
        return pipeline
    except Exception as exc:
        logger.warning("Failed to initialize learning pipeline: %s", exc)
        return None


async def recover_workflow_state_from_dhara(app: Any) -> None:
    """Restore in-flight workflow state from Dhara on startup."""
    if app._dhara_state is None:
        return

    import logging

    logger = logging.getLogger(__name__)
    try:
        entries = await app._dhara_state.recover_workflows()
        recovered = 0
        for value in entries:
            if isinstance(value, dict) and value.get("status") == "running":
                workflow_id = value.get("execution_id", "unknown")
                app.active_workflows.add(workflow_id)
                recovered += 1
        if recovered:
            logger.info("Recovered %d in-flight workflows from Dhara", recovered)
    except Exception as exc:
        logger.debug("Dhara workflow recovery skipped: %s", exc)


async def recover_approvals_from_dhara(app: Any) -> None:
    """Restore pending approvals from Dhara on startup."""
    if app._dhara_state is None:
        return

    import logging

    logger = logging.getLogger(__name__)
    try:
        entries = await app._dhara_state.list_prefix("approval/v1/")
        restored = app.approval_manager.restore_from_dhara_entries(entries)
        if restored:
            logger.info("Recovered %d pending approvals from Dhara", restored)
    except Exception as exc:
        logger.debug("Dhara approval recovery skipped: %s", exc)

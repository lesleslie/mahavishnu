"""Core application module for Mahavishnu with Oneiric integration.

This module provides the main application class that manages configuration,
repository loading, and adapter initialization using Oneiric patterns.
"""

import asyncio
from asyncio import Semaphore
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from ..qc.checker import QualityControl
from ..session.checkpoint import SessionBuddy
from .circuit_breaker import CircuitBreaker
from .config import MahavishnuSettings
from .errors import ConfigurationError, ValidationError
from .monitoring import MonitoringService
from .observability import init_observability
from .opensearch_integration import OpenSearchIntegration
from .permissions import Permission, RBACManager
from .resilience import ErrorRecoveryManager, ResiliencePatterns
from .workflow_state import WorkflowState

if TYPE_CHECKING:
    from ..terminal.manager import TerminalManager
    from .adapters.base import OrchestratorAdapter


def _validate_path(path_str: str, allowed_base_paths: list[str] | None = None) -> Path:
    """Validate a path to prevent directory traversal attacks.

    Args:
        path_str: Path string to validate
        allowed_base_paths: Optional list of allowed base paths (defaults to current directory)

    Returns:
        Validated Path object

    Raises:
        ValidationError: If path contains directory traversal sequences or is outside allowed paths
    """
    path = Path(path_str)

    # Resolve the path to its absolute form
    abs_path = path.resolve()

    # Check for directory traversal patterns
    if (
        ".." in path.parts
        or str(path).startswith("../")
        or "../" in str(path)
        or str(path).endswith("/..")
    ):
        raise ValidationError(
            message=f"Invalid path contains directory traversal: {path_str}",
            details={"path": path_str, "suggestion": "Remove any '..' sequences from the path"},
        )

    # Check if path is within allowed boundaries
    allowed_paths = allowed_base_paths or [str(Path.cwd())]

    is_allowed = False
    for allowed_base in allowed_paths:
        try:
            abs_path.relative_to(allowed_base)
            is_allowed = True
            break
        except ValueError:
            continue

    if not is_allowed:
        raise ValidationError(
            message=f"Path is outside allowed directory: {path_str}",
            details={
                "path": path_str,
                "allowed_paths": allowed_paths,
                "suggestion": "Ensure path is within allowed boundaries",
            },
        )

    return path


class MahavishnuApp:
    """Main application class for Mahavishnu orchestrator.

    This class provides:
    - Configuration loading from Oneiric-compatible sources
    - Repository manifest loading from repos.yaml
    - Adapter initialization and management
    - Type-safe operations throughout
    - Concurrency control for workflow execution

    Example:
        >>> from mahavishnu.core import MahavishnuApp
        >>> app = MahavishnuApp()
        >>> repos = app.get_repos(tag="backend")
        >>> result = app.execute_workflow(
        ...     task={"type": "code_sweep"},
        ...     adapter_name="langgraph",
        ...     repos=repos,
        ... )
    """

    def __init__(self, config: MahavishnuSettings | None = None) -> None:
        """Initialize the Mahavishnu application.

        Args:
            config: Optional configuration. If not provided, loads from
                    Oneiric-compatible sources (YAML + environment).

        Raises:
            ConfigurationError: If configuration loading fails
        """
        self.config = config or self._load_config()
        self.adapters: dict[str, OrchestratorAdapter] = {}
        self._load_repos()
        self._initialize_adapters()

        # Initialize concurrency control
        self.semaphore = Semaphore(self.config.max_concurrent_workflows)
        from typing import Set
        self.active_workflows: Set[str] = set()
        self.workflow_queue: asyncio.Queue = asyncio.Queue()

        # Initialize production features
        self.circuit_breaker = CircuitBreaker(
            threshold=self.config.circuit_breaker_threshold,
            timeout=int(self.config.retry_base_delay * 10),  # Convert to int
        )

        # Initialize observability
        self.observability = init_observability(self.config)

        # Initialize quality control
        self.qc = QualityControl(self.config)

        # Initialize session management
        self.session_buddy = SessionBuddy(self.config)

        # Initialize terminal manager (optional)
        self.terminal_manager = None
        if self.config.terminal.enabled:
            self.terminal_manager = self._init_terminal_manager()

        # Initialize workflow state manager
        self.workflow_state_manager = WorkflowState()

        # Initialize RBAC manager
        self.rbac_manager = RBACManager(self.config)

        # Initialize OpenSearch integration for log analytics
        self.opensearch_integration = OpenSearchIntegration(self.config)

        # Initialize resilience and error recovery patterns
        self.resilience_manager = ResiliencePatterns(self)
        self.error_recovery_manager = ErrorRecoveryManager(self)

        # Initialize resilience monitoring service (will be started when event loop is available)
        self._resilience_monitoring_task = None

        # Initialize monitoring and alerting service
        self.monitoring_service = MonitoringService(self)

        # Initialize backup and recovery managers
        from .backup_recovery import BackupManager, DisasterRecoveryManager

        self.backup_manager = BackupManager(self)
        self.recovery_manager = DisasterRecoveryManager(self)

    def _init_terminal_manager(self) -> "TerminalManager | None":
        """Initialize terminal manager with mcpretentious adapter.

        Returns:
            TerminalManager instance or None if initialization fails

        Note:
            MCP client integration requires async context.
            This method returns None if terminal management is not configured
            or if the adapter cannot be initialized.
        """

        try:
            # Note: For now, we create a simple stub.
            # In Phase 2 (MCP tools integration), this will connect to actual MCP client
            # The MCP client will be passed from server_core.py during initialization
            logger = __import__("logging").getLogger(__name__)
            logger.info("Terminal management enabled, but MCP client not yet connected")
            logger.info("Terminal manager will be fully initialized in MCP server context")
            return None
        except Exception as e:
            logger = __import__("logging").getLogger(__name__)
            logger.warning(f"Failed to initialize terminal manager: {e}")
            return None

    def _load_config(self) -> MahavishnuSettings:
        """Load configuration from Oneiric-compatible sources.

        Configuration loading order (later overrides earlier):
        1. Default values in Pydantic model
        2. settings/mahavishnu.yaml (committed)
        3. settings/local.yaml (gitignored)
        4. Environment variables MAHAVISHNU_*

        Returns:
            Loaded and validated configuration

        Raises:
            ConfigurationError: If configuration loading or validation fails
        """
        try:
            return MahavishnuSettings()
        except Exception as e:
            raise ConfigurationError(
                message=f"Failed to load configuration: {e}",
                details={"error": str(e), "error_type": type(e).__name__},
            ) from e

    def _load_repos(self) -> None:
        """Load repository configurations from repos.yaml.

        Raises:
            ConfigurationError: If repos.yaml is not found or invalid
        """
        repos_path = _validate_path(self.config.repos_path).expanduser()

        if not repos_path.exists():
            raise ConfigurationError(
                message=f"Repository manifest not found: {repos_path}",
                details={
                    "repos_path": str(repos_path),
                    "suggestion": "Create repos.yaml with repository definitions",
                },
            )

        try:
            with repos_path.open() as f:
                self.repos_config = yaml.safe_load(f)

            # Validate structure
            if "repos" not in self.repos_config:
                raise ConfigurationError(
                    message="Invalid repos.yaml: missing 'repos' key",
                    details={"repos_path": str(repos_path)},
                )

        except yaml.YAMLError as e:
            raise ConfigurationError(
                message=f"Invalid YAML in repos.yaml: {e}",
                details={"repos_path": str(repos_path), "error": str(e)},
            ) from e
        except Exception as e:
            raise ConfigurationError(
                message=f"Failed to load repos.yaml: {e}",
                details={"repos_path": str(repos_path), "error": str(e)},
            ) from e

    def _initialize_adapters(self) -> None:
        """Initialize enabled adapters based on configuration.

        Core Components:
        - Prefect: High-level orchestration with dynamic flows
        - LlamaIndex: RAG pipelines for ingesting repos/docs, embedding with Ollama
        - Agno: Fast, scalable single/multi-agents with memory and tools

        Only adapters that are enabled in configuration will be initialized.

        Raises:
            ConfigurationError: If adapter initialization fails
        """
        adapter_classes: dict[str, type] = {}
        enabled_adapters: dict[str, bool] = {}

        # Prefect - Core orchestration (enabled by default)
        if self.config.prefect_enabled:
            try:
                from ..engines.prefect_adapter import PrefectAdapter

                adapter_classes["prefect"] = PrefectAdapter
                enabled_adapters["prefect"] = True
            except ImportError:
                # Prefect not available, skip this adapter
                print("Warning: Prefect adapter not available due to missing dependencies")
                pass

        # LlamaIndex - RAG pipelines (enabled by default)
        if self.config.llamaindex_enabled:
            try:
                from ..engines.llamaindex_adapter import LlamaIndexAdapter

                adapter_classes["llamaindex"] = LlamaIndexAdapter
                enabled_adapters["llamaindex"] = True
            except ImportError:
                # LlamaIndex not available, skip this adapter
                print("Warning: LlamaIndex adapter not available due to missing dependencies")
                pass

        # Agno - Fast agents (enabled by default)
        if self.config.agno_enabled:
            try:
                from ..engines.agno_adapter import AgnoAdapter

                adapter_classes["agno"] = AgnoAdapter
                enabled_adapters["agno"] = True
            except ImportError:
                # Agno not available, skip this adapter
                print("Warning: Agno adapter not available due to missing dependencies")
                pass

        for adapter_name, is_enabled in enabled_adapters.items():
            if is_enabled:
                try:
                    adapter_class = adapter_classes.get(adapter_name)
                    if adapter_class:
                        self.adapters[adapter_name] = adapter_class(self.config)
                except Exception as e:
                    raise ConfigurationError(
                        message=f"Failed to initialize {adapter_name} adapter: {e}",
                        details={
                            "adapter": adapter_name,
                            "error": str(e),
                            "error_type": type(e).__name__,
                        },
                    ) from e

    def get_repos(
        self, tag: str | None = None, role: str | None = None, user_id: str | None = None
    ) -> list[str]:
        """Get repository paths based on tag, role, or return all.

        Args:
            tag: Optional tag to filter repositories
            role: Optional role to filter repositories
            user_id: Optional user ID for permission checking

        Returns:
            List of repository paths

        Raises:
            ValidationError: If tag or role is invalid
        """
        # Validate tag format if provided
        if tag and not tag.replace("-", "").replace("_", "").isalnum():
            raise ValidationError(
                message=f"Invalid tag: {tag}",
                details={
                    "tag": tag,
                    "suggestion": "Tags must be alphanumeric with hyphens/underscores",
                },
            )

        # Validate role format if provided
        if role:
            valid_roles = [r["name"] for r in self.get_roles()]
            if role not in valid_roles:
                raise ValidationError(
                    message=f"Invalid role: {role}",
                    details={
                        "role": role,
                        "valid_roles": valid_roles,
                        "suggestion": f"Use one of: {', '.join(valid_roles)}",
                    },
                )

        repos = self.repos_config.get("repos", [])

        if tag:
            # Filter by tag
            filtered_repos = [repo["path"] for repo in repos if tag in repo.get("tags", [])]
        elif role:
            # Filter by role
            filtered_repos = [repo["path"] for repo in repos if repo.get("role") == role]
        else:
            # Return all repos
            filtered_repos = [repo["path"] for repo in repos]

        # Validate repository paths exist
        validated_repos = []
        for repo_path in filtered_repos:
            try:
                validated_path = _validate_path(repo_path, self.config.allowed_repo_paths)
                if validated_path.exists():
                    # If user_id is provided, check permissions
                    if user_id:
                        if self._check_user_repo_permission(user_id, str(validated_path)):
                            validated_repos.append(str(validated_path))
                    else:
                        # No user specified, allow access
                        validated_repos.append(str(validated_path))
                else:
                    # Log warning but continue with other repos
                    print(f"Warning: Repository path does not exist: {validated_path}")
            except ValidationError as e:
                # Log warning but continue with other repos
                print(f"Warning: Invalid repository path: {repo_path} - {e.message}")

        return validated_repos

    def _check_user_repo_permission(self, user_id: str, repo_path: str) -> bool:
        """Check if user has read permission for the repository."""
        import asyncio

        try:
            has_permission = asyncio.run(
                self.rbac_manager.check_permission(user_id, repo_path, Permission.READ_REPO)
            )
            return has_permission
        except Exception:
            # If permission check fails, still allow access for backward compatibility
            return True

    def get_all_repos(self) -> list[dict[str, Any]]:
        """Get all repositories with full metadata.

        Returns:
            List of repository dictionaries with path, tags, description
        """
        return self.repos_config.get("repos", [])  # type: ignore

    def get_all_repo_paths(self) -> list[str]:
        """Get all repository paths.

        Returns:
            List of all repository paths
        """
        repos = self.repos_config.get("repos", [])  # type: ignore
        return [repo["path"] for repo in repos]

    def get_roles(self) -> list[dict[str, Any]]:
        """Get all available roles.

        Returns:
            List of role definitions with name, description, tags, duties, capabilities
        """
        return self.repos_config.get("roles", [])

    def get_role_by_name(self, role_name: str) -> dict[str, Any] | None:
        """Get a specific role by name.

        Args:
            role_name: Name of the role to retrieve

        Returns:
            Role definition if found, None otherwise
        """
        roles = self.get_roles()
        for role in roles:
            if role.get("name") == role_name:
                return role
        return None

    def get_repos_by_role(self, role_name: str) -> list[dict[str, Any]]:
        """Get all repositories with a specific role.

        Args:
            role_name: Name of the role to filter by

        Returns:
            List of repository dictionaries with matching role

        Raises:
            ValidationError: If role_name is not found in role taxonomy
        """
        # Validate role exists
        valid_roles = [r["name"] for r in self.get_roles()]
        if role_name not in valid_roles:
            raise ValidationError(
                message=f"Invalid role: {role_name}",
                details={
                    "role": role_name,
                    "valid_roles": valid_roles,
                    "suggestion": f"Use one of: {', '.join(valid_roles)}",
                },
            )

        # Filter repos by role
        repos = self.repos_config.get("repos", [])
        return [repo for repo in repos if repo.get("role") == role_name]

    def get_all_nicknames(self) -> dict[str, str]:
        """Get all repository nicknames.

        Returns:
            Dictionary mapping nickname to full repository name
        """
        repos = self.repos_config.get("repos", [])
        nicknames = {}
        for repo in repos:
            if nickname := repo.get("nickname"):
                nicknames[nickname] = repo.get("name", repo.get("path", ""))
        return nicknames

    async def is_healthy(self) -> bool:
        """Check if application is healthy.

        Returns:
            True if application is healthy (all adapters accessible)
        """
        if not self.adapters:
            return False

        for adapter in self.adapters.values():
            try:
                health = await adapter.get_health()
                if health.get("status") != "healthy":
                    return False
            except Exception:
                return False

        return True

    async def get_active_workflows(self) -> list[str]:
        """Get list of active workflow IDs.

        Queries the workflow state manager for workflows that are currently
        in RUNNING status and returns their IDs.

        Returns:
            List of active workflow IDs
        """
        from .workflow_state import WorkflowStatus

        # Get workflows with RUNNING status
        workflows = await self.workflow_state_manager.list_workflows(
            status=WorkflowStatus.RUNNING,
            limit=1000,  # Sufficiently large limit
        )

        # Return workflow IDs
        return [w.get("id", "") for w in workflows if w.get("id")]

    async def execute_workflow(
        self,
        task: dict[str, Any],
        adapter_name: str,
        repos: list[str] | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute a workflow using the specified adapter.

        Args:
            task: Task specification with 'type' and 'params' keys
            adapter_name: Name of adapter to use
            repos: Optional list of repositories (defaults to all repos)
            user_id: Optional user ID for permission checking

        Returns:
            Workflow execution result

        Raises:
            ValidationError: If task or adapter_name is invalid
            AdapterError: If adapter execution fails
        """
        # Validate adapter and prepare for execution
        adapter, validated_repos = await self._prepare_execution(adapter_name, task, repos, user_id)

        # Execute with adapter using parallel processing
        try:
            # Add observability if enabled
            if self.observability:
                workflow_counter = self.observability.create_workflow_counter()
                if workflow_counter:
                    workflow_counter.add(
                        1, {"adapter": adapter_name, "task_type": task.get("type", "unknown")}
                    )

            result = await adapter.execute(task, validated_repos)
            return result
        except Exception as e:
            # Record error in observability if enabled
            if self.observability:
                error_counter = self.observability.create_error_counter()
                if error_counter:
                    error_counter.add(1, {"adapter": adapter_name, "error_type": type(e).__name__})

            # Log error to OpenSearch
            import uuid

            workflow_id = f"wf_{uuid.uuid4().hex[:8]}_{task.get('type', 'default')}_single"
            await self.opensearch_integration.log_error(
                workflow_id=workflow_id, error_msg=str(e), adapter=adapter_name
            )

            from .errors import AdapterError

            raise AdapterError(
                message=f"Adapter execution failed: {e}",
                details={
                    "adapter": adapter_name,
                    "task": task,
                    "repos_count": len(validated_repos),
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            ) from e

    async def _prepare_execution(
        self, adapter_name: str, task: dict[str, Any], repos: list[str] | None, user_id: str | None
    ) -> tuple["OrchestratorAdapter", list[str]]:
        """Helper method to validate adapter and prepare for execution."""
        # Validate adapter
        if adapter_name not in self.adapters:
            raise ValidationError(
                message=f"Adapter not found: {adapter_name}",
                details={
                    "adapter": adapter_name,
                    "available_adapters": list(self.adapters.keys()),
                    "suggestion": "Check adapter is enabled in configuration",
                },
            )

        # Get repos if not provided
        if repos is None:
            repos = self.get_repos(user_id=user_id)

        # Validate repository paths to prevent directory traversal
        validated_repos = []
        for repo_path in repos:
            try:
                validated_path = _validate_path(repo_path, self.config.allowed_repo_paths)
                validated_repos.append(str(validated_path))
            except ValidationError as e:
                raise ValidationError(
                    message=f"Invalid repository path: {repo_path}",
                    details={
                        "repo_path": repo_path,
                        "error": str(e),
                        "suggestion": "Ensure repository path is valid and does not contain directory traversal sequences",
                    },
                ) from e

        # If user_id is provided, check execute permission for each repo
        if user_id:
            for repo_path in validated_repos:
                has_permission = await self.rbac_manager.check_permission(
                    user_id, repo_path, Permission.EXECUTE_WORKFLOW
                )
                if not has_permission:
                    raise ValidationError(
                        message=f"User {user_id} does not have permission to execute workflows on {repo_path}",
                        details={
                            "user": user_id,
                            "repo": repo_path,
                            "permission": "EXECUTE_WORKFLOW",
                            "suggestion": "Contact administrator to grant required permissions",
                        },
                    )

        adapter = self.adapters[adapter_name]
        return adapter, validated_repos

    async def execute_workflow_parallel(
        self,
        task: dict[str, Any],
        adapter_name: str,
        repos: list[str] | None = None,
        progress_callback=None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute a workflow in parallel across repositories with progress reporting.

        Args:
            task: Task specification with 'type' and 'params' keys
            adapter_name: Name of adapter to use
            repos: Optional list of repositories (defaults to all repos)
            progress_callback: Optional callback function to report progress
            user_id: Optional user ID for permission checking

        Returns:
            Workflow execution result with timing and performance metrics

        Raises:
            ValidationError: If task or adapter_name is invalid
            AdapterError: If adapter execution fails
        """
        # Validate adapter and prepare for execution
        adapter, validated_repos = await self._prepare_execution(adapter_name, task, repos, user_id)

        # Create a unique workflow ID
        import uuid

        workflow_id = f"wf_{uuid.uuid4().hex[:8]}_{task.get('type', 'default')}"

        # Create workflow state
        await self.workflow_state_manager.create(
            workflow_id=workflow_id, task=task, repos=validated_repos
        )

        # Update workflow state to running
        await self.workflow_state_manager.update(workflow_id=workflow_id, status="running")

        # Log workflow start to OpenSearch
        await self.opensearch_integration.log_workflow_start(
            workflow_id=workflow_id,
            adapter=adapter_name,
            task_type=task.get("type", "unknown"),
            repos=validated_repos,
        )

        # Execute workflow with production features and resilience
        adapter = self.adapters[adapter_name]
        try:
            # Pre-execution quality control check
            if self.config.qc_enabled:
                qc_result = await self.qc.validate_pre_execution(validated_repos)
                if not qc_result:
                    await self.workflow_state_manager.update(
                        workflow_id=workflow_id,
                        status="failed",
                        error="Pre-execution QC check failed",
                    )
                    raise ValidationError(
                        message="Pre-execution QC check failed",
                        details={
                            "repos": validated_repos,
                            "qc_result": "Failed to meet minimum quality standards",
                        },
                    )

            # Create session checkpoint if enabled
            checkpoint_id = None
            if self.config.session_enabled:
                checkpoint_id = await self.session_buddy.create_checkpoint(
                    session_id=f"workflow_{task.get('id', 'default')}",
                    state={
                        "task": task,
                        "adapter": adapter_name,
                        "repos": validated_repos,
                        "status": "started",
                    },
                )

            # Calculate total repos for progress tracking
            total_repos = len(validated_repos)
            completed_repos = 0

            # Process repos in parallel with concurrency control
            semaphore = self.semaphore

            async def process_single_repo(repo_path):
                nonlocal completed_repos
                async with semaphore:  # Limit concurrent executions
                    start_repo_time = time.time()

                    # Use circuit breaker for each repo processing
                    try:
                        result = await self.circuit_breaker.call(
                            adapter.execute, task | {"single_repo": repo_path}, [repo_path]
                        )

                        # Add result to workflow state
                        await self.workflow_state_manager.add_result(workflow_id, result)
                    except Exception as e:
                        # Record failure in circuit breaker
                        self.circuit_breaker.record_failure()

                        # Add error to workflow state
                        error_info = {
                            "repo": repo_path,
                            "error": str(e),
                            "type": type(e).__name__,
                            "timestamp": datetime.now().isoformat(),
                        }
                        await self.workflow_state_manager.add_error(workflow_id, error_info)

                        # Record error in observability if enabled
                        if self.observability:
                            error_counter = self.observability.create_error_counter()
                            if error_counter:
                                error_counter.add(
                                    1,
                                    {
                                        "adapter": adapter_name,
                                        "error_type": type(e).__name__,
                                        "repo": repo_path,
                                    },
                                )

                        # Log error to OpenSearch
                        await self.opensearch_integration.log_error(
                            workflow_id=workflow_id,
                            error_msg=str(e),
                            repo_path=repo_path,
                            adapter=adapter_name,
                        )

                        raise e

                    completed_repos += 1

                    # Calculate and record repo processing time
                    repo_processing_time = time.time() - start_repo_time

                    # Update progress in workflow state
                    await self.workflow_state_manager.update_progress(
                        workflow_id, completed_repos, total_repos
                    )

                    # Record repo processing time in observability
                    if self.observability:
                        self.observability.record_repo_processing_time(
                            repo_path, workflow_id, repo_processing_time
                        )

                        # Start repo trace
                        with self.observability.start_repo_trace(repo_path, workflow_id):
                            pass  # Span is active during this context

                    # Report progress if callback provided
                    if progress_callback:
                        progress_callback(completed_repos, total_repos, repo_path)

                    return result

            # Execute all repos in parallel
            import time

            start_time = time.time()

            # Add observability if enabled
            if self.observability:
                # Record workflow execution
                workflow_counter = self.observability.create_workflow_counter()
                if workflow_counter:
                    workflow_counter.add(
                        1, {"adapter": adapter_name, "task_type": task.get("type", "unknown")}
                    )

                # Record repository processing
                repo_counter = self.observability.create_repo_counter()
                if repo_counter:
                    repo_counter.add(len(validated_repos), {"adapter": adapter_name})

                # Start workflow trace (span is ended automatically on context exit)
                with self.observability.start_workflow_trace(
                    workflow_id, adapter_name, task.get("type", "unknown")
                ) as workflow_span:
                    _ = workflow_span  # Mark as intentionally used

            tasks = [process_single_repo(repo) for repo in validated_repos]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            execution_time = time.time() - start_time

            # End workflow trace
            if self.observability:
                self.observability.end_workflow_trace(
                    workflow_id,
                    "completed" if not errors else ("partial" if successful_results else "failed"),
                )

            # Handle any exceptions that occurred during parallel execution
            errors: list[dict[str, Any]] = []
            successful_results: list[Any] = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    errors.append(
                        {
                            "repo": validated_repos[i],
                            "error": str(result),
                            "type": type(result).__name__,
                        }
                    )
                    # Record error in observability if enabled
                    if self.observability:
                        error_counter = self.observability.create_error_counter()
                        if error_counter:
                            error_counter.add(
                                1,
                                {
                                    "adapter": adapter_name,
                                    "error_type": type(result).__name__,
                                    "repo": validated_repos[i],
                                },
                            )
                else:
                    successful_results.append(result)

            # Update workflow state with final status
            final_status = (
                "completed" if not errors else ("partial" if successful_results else "failed")
            )
            await self.workflow_state_manager.update(
                workflow_id=workflow_id,
                status=final_status,
                execution_time_seconds=execution_time,
                completed_at=datetime.now().isoformat(),
            )

            # Log workflow completion to OpenSearch
            await self.opensearch_integration.log_workflow_completion(
                workflow_id=workflow_id,
                status=final_status,
                execution_time=execution_time,
                results_count=len(successful_results),
                errors_count=len(errors),
                adapter=adapter_name,
                task_type=task.get("type", "unknown"),
            )

            # Update checkpoint if enabled
            if self.config.session_enabled and checkpoint_id:
                await self.session_buddy.update_checkpoint(
                    checkpoint_id,
                    final_status,
                    result={
                        "successful_repos": len(successful_results),
                        "failed_repos": len(errors),
                        "execution_time": execution_time,
                    },
                )

            # Post-execution quality control check
            if self.config.qc_enabled:
                qc_result = await self.qc.validate_post_execution(validated_repos)
                if not qc_result:
                    # Log warning but don't fail the workflow
                    print(f"Warning: Post-execution QC check failed for repos: {validated_repos}")

            return {
                "workflow_id": workflow_id,
                "status": final_status,
                "adapter": adapter_name,
                "task": task,
                "repos_processed": len(validated_repos),
                "successful_repos": len(successful_results),
                "failed_repos": len(errors),
                "execution_time_seconds": execution_time,
                "results": successful_results,
                "errors": errors or None,
                "concurrency_limit": self.config.max_concurrent_workflows,
                "qc_enabled": self.config.qc_enabled,
                "session_enabled": self.config.session_enabled,
            }
        except Exception as e:
            # Update workflow state with error
            await self.workflow_state_manager.update(
                workflow_id=workflow_id,
                status="failed",
                error=str(e),
                completed_at=datetime.now().isoformat(),
            )

            # Log error to OpenSearch
            await self.opensearch_integration.log_error(
                workflow_id=workflow_id, error_msg=str(e), adapter=adapter_name
            )

            # Update checkpoint if enabled and there was an error
            if self.config.session_enabled and checkpoint_id:
                await self.session_buddy.update_checkpoint(
                    checkpoint_id, "failed", result={"error": str(e)}
                )

            from .errors import AdapterError

            raise AdapterError(
                message=f"Adapter execution failed: {e}",
                details={
                    "adapter": adapter_name,
                    "task": task,
                    "repos_count": len(validated_repos),
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            ) from e

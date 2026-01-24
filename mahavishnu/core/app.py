"""Core application module for Mahavishnu with Oneiric integration.

This module provides the main application class that manages configuration,
repository loading, and adapter initialization using Oneiric patterns.
"""

import yaml
from pathlib import Path, PurePath
from typing import Any
import os
import asyncio
from asyncio import Semaphore

from typing import TYPE_CHECKING

from .config import MahavishnuSettings
from .errors import ConfigurationError, ValidationError
from .adapters.base import OrchestratorAdapter
from .circuit_breaker import CircuitBreaker
from .observability import init_observability, get_observability_manager
from ..qc.checker import QualityControl
from ..session.checkpoint import SessionBuddy

if TYPE_CHECKING:
    from ..terminal.manager import TerminalManager


def _validate_path(path_str: str) -> Path:
    """Validate a path to prevent directory traversal attacks.

    Args:
        path_str: Path string to validate

    Returns:
        Validated Path object

    Raises:
        ValidationError: If path contains directory traversal sequences
    """
    path = Path(path_str)

    # Resolve the path to its absolute form
    abs_path = path.resolve()

    # Check for directory traversal patterns
    if '..' in path.parts or str(path).startswith('../') or '../' in str(path) or str(path).endswith('/..'):
        raise ValidationError(
            message=f"Invalid path contains directory traversal: {path_str}",
            details={
                "path": path_str,
                "suggestion": "Remove any '..' sequences from the path"
            }
        )

    # Additional check: ensure the resolved path is within allowed boundaries
    # For now, we'll just ensure it doesn't go above the current directory
    # In a real implementation, you might want to restrict to specific allowed directories
    try:
        # This will raise ValueError if the path is outside the current working directory
        abs_path.relative_to(Path.cwd())
    except ValueError:
        raise ValidationError(
            message=f"Path is outside allowed directory: {path_str}",
            details={
                "path": path_str,
                "cwd": str(Path.cwd()),
                "suggestion": "Ensure path is within allowed boundaries"
            }
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
        self.active_workflows = set()
        self.workflow_queue = asyncio.Queue()

        # Initialize production features
        self.circuit_breaker = CircuitBreaker(
            threshold=self.config.circuit_breaker_threshold,
            timeout=self.config.retry_base_delay * 10  # Adjust as needed
        )

        # Initialize observability
        init_observability(self.config)
        self.observability = get_observability_manager()

        # Initialize quality control
        self.qc = QualityControl(self.config)

        # Initialize session management
        self.session_buddy = SessionBuddy(self.config)

        # Initialize terminal manager (optional)
        self.terminal_manager = None
        if self.config.terminal.enabled:
            self.terminal_manager = self._init_terminal_manager()

    def _init_terminal_manager(self) -> "TerminalManager | None":
        """Initialize terminal manager with mcpretentious adapter.

        Returns:
            TerminalManager instance or None if initialization fails

        Note:
            MCP client integration requires async context.
            This method returns None if terminal management is not configured
            or if the adapter cannot be initialized.
        """
        from ..terminal.adapters.mcpretentious import McpretentiousAdapter

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
            with open(repos_path, "r") as f:
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
        adapter_classes = {}
        enabled_adapters = {}

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

    def get_repos(self, tag: str | None = None) -> list[str]:
        """Get repository paths based on tag or return all.

        Args:
            tag: Optional tag to filter repositories

        Returns:
            List of repository paths

        Raises:
            ValidationError: If tag is invalid
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

        repos = self.repos_config.get("repos", [])

        if tag:
            # Filter by tag
            filtered_repos = [
                repo["path"]
                for repo in repos
                if tag in repo.get("tags", [])
            ]
        else:
            # Return all repos
            filtered_repos = [repo["path"] for repo in repos]

        # Validate repository paths exist
        validated_repos = []
        for repo_path in filtered_repos:
            try:
                validated_path = _validate_path(repo_path)
                if validated_path.exists():
                    validated_repos.append(str(validated_path))
                else:
                    # Log warning but continue with other repos
                    print(f"Warning: Repository path does not exist: {validated_path}")
            except ValidationError as e:
                # Log warning but continue with other repos
                print(f"Warning: Invalid repository path: {repo_path} - {e.message}")

        return validated_repos

    def get_all_repos(self) -> list[dict[str, Any]]:
        """Get all repositories with full metadata.

        Returns:
            List of repository dictionaries with path, tags, description
        """
        return self.repos_config.get("repos", [])

    def get_all_repo_paths(self) -> list[str]:
        """Get all repository paths.

        Returns:
            List of all repository paths
        """
        return [repo["path"] for repo in self.repos_config.get("repos", [])]

    def is_healthy(self) -> bool:
        """Check if application is healthy.

        Returns:
            True if application is healthy (all adapters accessible)
        """
        if not self.adapters:
            return False

        for adapter_name, adapter in self.adapters.items():
            try:
                health = adapter.get_health()
                if health.get("status") != "healthy":
                    return False
            except Exception:
                return False

        return True

    def get_active_workflows(self) -> list[str]:
        """Get list of active workflow IDs.

        Returns:
            List of active workflow IDs
        """
        # TODO: Implement workflow tracking
        return []

    async def execute_workflow(
        self,
        task: dict[str, Any],
        adapter_name: str,
        repos: list[str] | None = None,
    ) -> dict[str, Any]:
        """Execute a workflow using the specified adapter.

        Args:
            task: Task specification with 'type' and 'params' keys
            adapter_name: Name of adapter to use
            repos: Optional list of repositories (defaults to all repos)

        Returns:
            Workflow execution result

        Raises:
            ValidationError: If task or adapter_name is invalid
            AdapterError: If adapter execution fails
        """
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
            repos = self.get_repos()

        # Validate repository paths to prevent directory traversal
        validated_repos = []
        for repo_path in repos:
            try:
                validated_path = _validate_path(repo_path)
                validated_repos.append(str(validated_path))
            except ValidationError as e:
                raise ValidationError(
                    message=f"Invalid repository path: {repo_path}",
                    details={
                        "repo_path": repo_path,
                        "error": str(e),
                        "suggestion": "Ensure repository path is valid and does not contain directory traversal sequences"
                    }
                ) from e

        # Execute with adapter using parallel processing
        adapter = self.adapters[adapter_name]
        try:
            result = await adapter.execute(task, validated_repos)
            return result
        except Exception as e:
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

    async def execute_workflow_parallel(
        self,
        task: dict[str, Any],
        adapter_name: str,
        repos: list[str] | None = None,
        progress_callback=None
    ) -> dict[str, Any]:
        """Execute a workflow in parallel across repositories with progress reporting.

        Args:
            task: Task specification with 'type' and 'params' keys
            adapter_name: Name of adapter to use
            repos: Optional list of repositories (defaults to all repos)
            progress_callback: Optional callback function to report progress

        Returns:
            Workflow execution result with timing and performance metrics

        Raises:
            ValidationError: If task or adapter_name is invalid
            AdapterError: If adapter execution fails
        """
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
            repos = self.get_repos()

        # Validate repository paths to prevent directory traversal
        validated_repos = []
        for repo_path in repos:
            try:
                validated_path = _validate_path(repo_path)
                validated_repos.append(str(validated_path))
            except ValidationError as e:
                raise ValidationError(
                    message=f"Invalid repository path: {repo_path}",
                    details={
                        "repo_path": repo_path,
                        "error": str(e),
                        "suggestion": "Ensure repository path is valid and does not contain directory traversal sequences"
                    }
                ) from e

        # Execute workflow with production features
        adapter = self.adapters[adapter_name]
        try:
            # Pre-execution quality control check
            if self.config.qc_enabled:
                qc_result = await self.qc.validate_pre_execution(validated_repos)
                if not qc_result:
                    raise ValidationError(
                        message="Pre-execution QC check failed",
                        details={
                            "repos": validated_repos,
                            "qc_result": "Failed to meet minimum quality standards"
                        }
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
                        "status": "started"
                    }
                )

            # Calculate total repos for progress tracking
            total_repos = len(validated_repos)
            completed_repos = 0

            # Process repos in parallel with concurrency control
            semaphore = self.semaphore

            async def process_single_repo(repo_path):
                nonlocal completed_repos
                async with semaphore:  # Limit concurrent executions
                    # Use circuit breaker for each repo processing
                    try:
                        result = await self.circuit_breaker.call(
                            adapter.execute,
                            {**task, "single_repo": repo_path},
                            [repo_path]
                        )
                    except Exception as e:
                        # Record failure in circuit breaker
                        self.circuit_breaker.record_failure()
                        raise e

                    completed_repos += 1

                    # Report progress if callback provided
                    if progress_callback:
                        progress_callback(completed_repos, total_repos, repo_path)

                    return result

            # Execute all repos in parallel
            import time
            start_time = time.time()

            # Add observability if enabled
            if self.observability:
                workflow_counter = self.observability.create_workflow_counter()
                if workflow_counter:
                    workflow_counter.add(1, {"adapter": adapter_name, "task_type": task.get("type", "unknown")})

                repo_counter = self.observability.create_repo_counter()
                if repo_counter:
                    repo_counter.add(len(validated_repos), {"adapter": adapter_name})

            tasks = [process_single_repo(repo) for repo in validated_repos]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            execution_time = time.time() - start_time

            # Handle any exceptions that occurred during parallel execution
            errors = []
            successful_results = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    errors.append({
                        "repo": validated_repos[i],
                        "error": str(result),
                        "type": type(result).__name__
                    })
                    # Record error in observability if enabled
                    if self.observability:
                        error_counter = self.observability.create_error_counter()
                        if error_counter:
                            error_counter.add(1, {"adapter": adapter_name, "error_type": type(result).__name__})
                else:
                    successful_results.append(result)

            # Update checkpoint if enabled
            if self.config.session_enabled and checkpoint_id:
                await self.session_buddy.update_checkpoint(
                    checkpoint_id,
                    "completed" if not errors else ("partial" if successful_results else "failed"),
                    result={
                        "successful_repos": len(successful_results),
                        "failed_repos": len(errors),
                        "execution_time": execution_time
                    }
                )

            # Post-execution quality control check
            if self.config.qc_enabled:
                qc_result = await self.qc.validate_post_execution(validated_repos)
                if not qc_result:
                    # Log warning but don't fail the workflow
                    print(f"Warning: Post-execution QC check failed for repos: {validated_repos}")

            return {
                "status": "completed" if not errors else ("partial" if successful_results else "failed"),
                "adapter": adapter_name,
                "task": task,
                "repos_processed": len(validated_repos),
                "successful_repos": len(successful_results),
                "failed_repos": len(errors),
                "execution_time_seconds": execution_time,
                "results": successful_results,
                "errors": errors if errors else None,
                "concurrency_limit": self.config.max_concurrent_workflows,
                "qc_enabled": self.config.qc_enabled,
                "session_enabled": self.config.session_enabled
            }
        except Exception as e:
            # Update checkpoint if enabled and there was an error
            if self.config.session_enabled and checkpoint_id:
                await self.session_buddy.update_checkpoint(
                    checkpoint_id,
                    "failed",
                    result={"error": str(e)}
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

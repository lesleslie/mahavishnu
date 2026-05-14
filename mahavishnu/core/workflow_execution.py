"""Workflow execution helpers for MahavishnuApp.

This module holds the workflow orchestration logic that was previously living
directly on `MahavishnuApp`, keeping the composition root focused on wiring.
"""

from __future__ import annotations

import asyncio
from asyncio import Semaphore
from datetime import datetime
import logging
import time
from typing import Any
import uuid

from monitoring.metrics import (
    mahavishnu_repos_processed_total,
    mahavishnu_workflow_duration_seconds,
    mahavishnu_workflows_total,
)

from .errors import AdapterError, ExternalServiceError, ValidationError
from .metrics_schema import AdapterType, TaskType
from .permissions import Permission
from .repository_surface import validate_path
from .routing import RoutingStrategy, TaskRouter

logger = logging.getLogger(__name__)


async def initialize_workflow_state(
    app: Any,
    task: dict[str, Any],
    adapter_name: str,
    validated_repos: list[str],
) -> str:
    workflow_id = f"wf_{uuid.uuid4().hex[:8]}_{task.get('type', 'default')}"
    await app.workflow_state_manager.create(
        workflow_id=workflow_id, task=task, repos=validated_repos
    )
    app.active_workflows.add(workflow_id)
    app._update_workflow_runtime_gauges()
    mahavishnu_workflows_total.labels(
        adapter=adapter_name,
        task_type=task.get("type", "unknown"),
        status="started",
    ).inc()
    await app.workflow_state_manager.update(workflow_id=workflow_id, status="running")
    await app.opensearch_integration.log_workflow_start(
        workflow_id=workflow_id,
        adapter=adapter_name,
        task_type=task.get("type", "unknown"),
        repos=validated_repos,
    )
    return workflow_id


async def validate_pre_execution_qc(
    app: Any, workflow_id: str, validated_repos: list[str]
) -> None:
    if not app.config.qc.enabled:
        return

    qc_result = await app.qc.validate_pre_execution(validated_repos)
    if not qc_result:
        await app.workflow_state_manager.update(
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


async def create_session_checkpoint(
    app: Any, task: dict[str, Any], adapter_name: str, validated_repos: list[str]
) -> str | None:
    if not app.config.session.enabled:
        return None

    return await app.session_buddy.create_checkpoint(
        session_id=f"workflow_{task.get('id', 'default')}",
        state={
            "task": task,
            "adapter": adapter_name,
            "repos": validated_repos,
            "status": "started",
        },
    )


async def prepare_execution(
    app: Any, adapter_name: str, task: dict[str, Any], repos: list[str] | None, user_id: str | None
) -> tuple[Any, list[str]]:
    if adapter_name not in app.adapters:
        raise ValidationError(
            message=f"Adapter not found: {adapter_name}",
            details={
                "adapter": adapter_name,
                "available_adapters": list(app.adapters.keys()),
                "suggestion": "Check adapter is enabled in configuration",
            },
        )

    if repos is None:
        repos = app.get_repos(user_id=user_id)

    validated_repos: list[str] = []
    for repo_path in repos:
        try:
            validated_path = validate_path(repo_path, app.config.allowed_repo_paths)
            validated_repos.append(str(validated_path))
        except ValidationError as exc:
            raise ValidationError(
                message=f"Invalid repository path: {repo_path}",
                details={
                    "repo_path": repo_path,
                    "error": str(exc),
                    "suggestion": "Ensure repository path is valid and does not contain directory traversal sequences",
                },
            ) from exc

    if user_id:
        for repo_path in validated_repos:
            has_permission = await app.rbac_manager.check_permission(
                user_id, repo_path, Permission.EXECUTE_WORKFLOW
            )
            if not has_permission:
                raise ValidationError(
                    message=(
                        f"User {user_id} does not have permission to execute workflows on {repo_path}"
                    ),
                    details={
                        "user": user_id,
                        "repo": repo_path,
                        "permission": "EXECUTE_WORKFLOW",
                        "suggestion": "Contact administrator to grant required permissions",
                    },
                )

    adapter = app.adapters[adapter_name]
    await check_dependency_health(app)
    return adapter, validated_repos


async def check_dependency_health(app: Any) -> None:
    """Check health of QC and Session-Buddy before execution."""
    import logging

    logger = logging.getLogger(__name__)

    async def _true() -> bool:
        return True

    qc_healthy, sb_healthy = await asyncio.gather(
        app.qc.is_healthy() if app.config.qc.enabled else _true(),
        app.session_buddy.is_healthy() if app.config.session.enabled else _true(),
    )

    if not sb_healthy and app.config.session.enabled:
        logger.warning(
            "Session-Buddy is unreachable — checkpoints will not persist (degraded mode)"
        )

    if not qc_healthy and app.config.qc.enabled:
        raise ExternalServiceError(
            "crackerjack",
            "QC service is unreachable — block execution to prevent unvalidated runs. "
            "Set qc.enabled=false to allow degraded-mode execution without quality gates.",
            details={"url": app.config.qc.crackerjack_url},
        )


async def process_single_repo(
    app: Any,
    adapter: Any,
    task: dict[str, Any],
    adapter_name: str,
    workflow_id: str,
    repo_path: str,
    total_repos: int,
    semaphore: Semaphore,
    progress_callback=None,
) -> Any:
    async with semaphore:
        start_repo_time = time.time()

        try:
            result = await app.circuit_breaker.call(
                adapter.execute, task | {"single_repo": repo_path}, [repo_path]
            )

            await app.workflow_state_manager.add_result(workflow_id, result)

            repo_processing_time = time.time() - start_repo_time
            completed_repos = await app.workflow_state_manager.get_completed_count(workflow_id)
            await app.workflow_state_manager.update_progress(
                workflow_id, completed_repos + 1, total_repos
            )

            if app.observability:
                app.observability.record_repo_processing_time(
                    repo_path, workflow_id, repo_processing_time
                )
                with app.observability.start_repo_trace(repo_path, workflow_id):
                    pass

            if progress_callback:
                progress_callback(completed_repos + 1, total_repos, repo_path)

            return result

        except Exception as exc:
            app.circuit_breaker.record_failure()

            error_info = {
                "repo": repo_path,
                "error": str(exc),
                "type": type(exc).__name__,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            await app.workflow_state_manager.add_error(workflow_id, error_info)

            if app.observability:
                error_counter = app.observability.create_error_counter()
                if error_counter:
                    error_counter.add(
                        1,
                        {
                            "adapter": adapter_name,
                            "error_type": type(exc).__name__,
                            "repo": repo_path,
                        },
                    )

            await app.opensearch_integration.log_error(
                workflow_id=workflow_id,
                error_msg=str(exc),
                repo_path=repo_path,
                adapter=adapter_name,
            )

            raise exc


async def execute_parallel_workflow(
    app: Any,
    adapter: Any,
    task: dict[str, Any],
    adapter_name: str,
    workflow_id: str,
    validated_repos: list[str],
    progress_callback=None,
) -> tuple[float, list[Any], list[dict[str, Any]]]:
    start_time = time.time()

    if app.observability:
        workflow_counter = app.observability.create_workflow_counter()
        if workflow_counter:
            workflow_counter.add(
                1, {"adapter": adapter_name, "task_type": task.get("type", "unknown")}
            )

        repo_counter = app.observability.create_repo_counter()
        if repo_counter:
            repo_counter.add(len(validated_repos), {"adapter": adapter_name})

    if app.observability:
        with app.observability.start_workflow_trace(
            workflow_id, adapter_name, task.get("type", "unknown")
        ) as workflow_span:
            _ = workflow_span

    semaphore = app.semaphore
    total_repos = len(validated_repos)
    tasks = [
        process_single_repo(
            app=app,
            adapter=adapter,
            task=task,
            adapter_name=adapter_name,
            workflow_id=workflow_id,
            repo_path=repo_path,
            total_repos=total_repos,
            semaphore=semaphore,
            progress_callback=progress_callback,
        )
        for repo_path in validated_repos
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)
    execution_time = time.time() - start_time

    if app.observability:
        errors_count = sum(1 for r in results if isinstance(r, Exception))
        successful_count = len(results) - errors_count
        final_status = (
            "completed"
            if errors_count == 0
            else ("partial" if successful_count > 0 else "failed")
        )
        app.observability.end_workflow_trace(workflow_id, final_status)

    errors: list[dict[str, Any]] = []
    successful_results: list[Any] = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            errors.append(
                {"repo": validated_repos[i], "error": str(result), "type": type(result).__name__}
            )
            if app.observability:
                error_counter = app.observability.create_error_counter()
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

    return execution_time, successful_results, errors


async def finalize_workflow_execution(
    app: Any,
    workflow_id: str,
    adapter_name: str,
    task: dict[str, Any],
    validated_repos: list[str],
    execution_time: float,
    successful_results: list[Any],
    errors: list[dict[str, Any]],
    checkpoint_id: str | None,
) -> dict[str, Any]:
    logger = logging.getLogger(__name__)
    final_status = "completed" if not errors else ("partial" if successful_results else "failed")
    task_type = task.get("type", "unknown")

    await app.workflow_state_manager.update(
        workflow_id=workflow_id,
        status=final_status,
        execution_time_seconds=execution_time,
        completed_at=datetime.now().isoformat(),
    )

    await app.opensearch_integration.log_workflow_completion(
        workflow_id=workflow_id,
        status=final_status,
        execution_time=execution_time,
        results_count=len(successful_results),
        errors_count=len(errors),
        adapter=adapter_name,
        task_type=task.get("type", "unknown"),
    )

    if app.config.session.enabled and checkpoint_id:
        await app.session_buddy.update_checkpoint(
            checkpoint_id,
            final_status,
            result={
                "successful_repos": len(successful_results),
                "failed_repos": len(errors),
                "execution_time": execution_time,
            },
        )

    if app.config.qc.enabled:
        qc_result = await app.qc.validate_post_execution(validated_repos)
        if not qc_result:
            logger.warning("Post-execution QC check failed for repos: %s", validated_repos)

    mahavishnu_workflows_total.labels(
        adapter=adapter_name,
        task_type=task_type,
        status=final_status,
    ).inc()
    mahavishnu_workflow_duration_seconds.labels(
        adapter=adapter_name,
        task_type=task_type,
        status=final_status,
    ).observe(execution_time)
    mahavishnu_repos_processed_total.labels(
        adapter=adapter_name,
        task_type=task_type,
        status=final_status,
    ).inc(len(validated_repos))
    app.active_workflows.discard(workflow_id)
    app._update_workflow_runtime_gauges()

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
        "concurrency_limit": app.config.max_concurrent_workflows,
        "qc_enabled": app.config.qc.enabled,
        "session_enabled": app.config.session.enabled,
    }


async def handle_workflow_execution_error(
    app: Any,
    workflow_id: str,
    adapter_name: str,
    task: dict[str, Any],
    validated_repos: list[str],
    error: Exception,
    checkpoint_id: str | None,
) -> None:
    await app.workflow_state_manager.update(
        workflow_id=workflow_id,
        status="failed",
        error=str(error),
        completed_at=datetime.now().isoformat(),
    )

    await app.opensearch_integration.log_error(
        workflow_id=workflow_id, error_msg=str(error), adapter=adapter_name
    )

    if app.config.session.enabled and checkpoint_id:
        await app.session_buddy.update_checkpoint(
            checkpoint_id, "failed", result={"error": str(error)}
        )

    mahavishnu_workflows_total.labels(
        adapter=adapter_name,
        task_type=task.get("type", "unknown"),
        status="failed",
    ).inc()
    app.active_workflows.discard(workflow_id)
    app._update_workflow_runtime_gauges()

    raise AdapterError(
        message=f"Adapter execution failed: {error}",
        details={
            "adapter": adapter_name,
            "task": task,
            "repos_count": len(validated_repos),
            "error": str(error),
            "error_type": type(error).__name__,
        },
    ) from error


async def execute_workflow_parallel(
    app: Any,
    task: dict[str, Any],
    adapter_name: str,
    repos: list[str] | None = None,
    progress_callback=None,
    user_id: str | None = None,
) -> dict[str, Any]:
    adapter, validated_repos = await app._prepare_execution(
        adapter_name, task, repos, user_id
    )
    workflow_id = await initialize_workflow_state(app, task, adapter_name, validated_repos)
    await validate_pre_execution_qc(app, workflow_id, validated_repos)
    checkpoint_id = await create_session_checkpoint(app, task, adapter_name, validated_repos)

    try:
        execution_time, successful_results, errors = await execute_parallel_workflow(
            app=app,
            adapter=adapter,
            task=task,
            adapter_name=adapter_name,
            workflow_id=workflow_id,
            validated_repos=validated_repos,
            progress_callback=progress_callback,
        )
        return await finalize_workflow_execution(
            app=app,
            workflow_id=workflow_id,
            adapter_name=adapter_name,
            task=task,
            validated_repos=validated_repos,
            execution_time=execution_time,
            successful_results=successful_results,
            errors=errors,
            checkpoint_id=checkpoint_id,
        )
    except Exception as exc:
        await handle_workflow_execution_error(
            app=app,
            workflow_id=workflow_id,
            adapter_name=adapter_name,
            task=task,
            validated_repos=validated_repos,
            error=exc,
            checkpoint_id=checkpoint_id,
        )


async def execute_workflow_with_fallback(
    app: Any,
    task: dict[str, Any],
    repos: list[str],
    adapter_preference: list[str] | None = None,
    routing_strategy: RoutingStrategy = RoutingStrategy.BALANCED,
    enable_cost_tracking: bool = False,
) -> dict[str, Any]:
    router = TaskRouter()
    task_type = TaskType(task.get("type", "ai_task"))

    preferred = AdapterType(adapter_preference[0]) if adapter_preference else None
    fallback_chain = router.generate_fallback_chain(task_type, preferred)

    execution_id = str(uuid.uuid4())
    workflow_name = task.get("type", "workflow")
    app._persist_workflow_start(execution_id, workflow_name, {"repos": repos})

    errors: list[tuple[str, str]] = []
    for adapter_name in fallback_chain:
        try:
            result = await app.execute_workflow_parallel(
                task=task,
                adapter_name=adapter_name.value,
                repos=repos,
            )
            app._persist_workflow_end(execution_id, workflow_name, "completed")
            return {
                "success": True,
                "adapter_used": adapter_name.value,
                "fallback_chain": [a.value for a in fallback_chain],
                "repo_results": result,
                "errors": [],
            }
        except Exception as exc:
            errors.append((adapter_name.value, str(exc)))
            logger.warning("Adapter %s failed: %s", adapter_name.value, exc)
            continue

    app._persist_workflow_end(
        execution_id,
        workflow_name,
        "failed",
        error="; ".join(f"{a}: {e}" for a, e in errors),
    )
    return {
        "success": False,
        "adapter_used": None,
        "fallback_chain": [a.value for a in fallback_chain],
        "repo_results": {},
        "errors": errors,
    }


async def execute_workflow_with_routing(
    app: Any,
    task: dict[str, Any],
    repos: list[str],
    routing_strategy: str = "balanced",
    enable_fallback: bool = True,
) -> dict[str, Any]:
    strategy = RoutingStrategy(routing_strategy)

    if enable_fallback:
        return await app.execute_workflow_with_fallback(
            task=task,
            repos=repos,
            routing_strategy=strategy,
        )

    router = TaskRouter()
    task_type = TaskType(task.get("type", "ai_task"))
    adapter = await router.select_adapter(task_type, strategy)

    result = await app.execute_workflow_parallel(
        task=task,
        adapter_name=adapter.value,
        repos=repos,
    )

    return {
        "success": result.get("success", False),
        "adapter_used": adapter.value,
        "repo_results": result,
        "fallback_chain": [adapter.value],
    }

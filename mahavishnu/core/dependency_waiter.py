"""Startup dependency waiting and recovery gating helpers."""

from __future__ import annotations

from typing import Any


async def wait_for_dependencies(app: Any) -> bool:
    """Wait for app dependencies and trigger recovery when possible."""
    from .health import DependencyWaiter

    config = app.config.health
    if not config.enabled or not config.dependencies:
        logger = __import__("logging").getLogger(__name__)
        logger.debug("Health check disabled or no dependencies configured")
        return True

    logger = __import__("logging").getLogger(__name__)
    logger.info(
        "Waiting for dependencies",
        extra={"dependencies": list(config.dependencies.keys())},
    )

    waiter = DependencyWaiter(config=config)
    result = await waiter.wait_for_all(config.dependencies)

    if result.success:
        logger.info(
            "All dependencies healthy",
            extra={
                "total_wait_seconds": result.total_wait_seconds,
                "dependencies": {
                    name: dep.status.value for name, dep in result.dependencies.items()
                },
            },
        )
    else:
        logger.error(
            "Required dependencies unhealthy",
            extra={
                "failed_required": result.failed_required,
                "skipped_optional": result.skipped_optional,
            },
        )

    if getattr(app, "_dhara_state", None) is not None:
        available = await app._dhara_state.probe()
        if available:
            await app._recover_workflow_state_from_dhara()
            await app._recover_approvals_from_dhara()

    if getattr(app.config, "unified_validation_enabled", False):
        try:
            from .unified_config import UnifiedConfig

            UnifiedConfig.validate_strict()
            logger.info("Unified config validation passed")
        except Exception as exc:
            logger.error("Config validation failed: %s", exc)
            return False
    else:
        try:
            from .unified_config import UnifiedConfig

            report = UnifiedConfig.validate()
            if not report.valid:
                for err in report.get_errors():
                    logger.warning("Config issue [%s]: %s", err.path, err.message)
        except Exception:
            pass

    return result.success

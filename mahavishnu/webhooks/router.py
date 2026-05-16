"""FastAPI router for OpenClaw webhook endpoints.

This module provides webhook endpoints for external platform integrations
with rate limiting, authentication, and input validation.

Design Reference:
- docs/plans/PRE_IMPLEMENTATION_CHECKLIST.md (P0-4, P0-5)
- Security: Rate limiting, path traversal prevention, auth validation

Usage:
    from mahavishnu.webhooks.router import webhook_router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(webhook_router, prefix="/webhooks")
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from mahavishnu.core.errors import AuthenticationError
from mahavishnu.core.rate_limiting import rate_limit
from mahavishnu.core.routing import TaskRouter
from mahavishnu.factories import get_pool_manager

from .models import (
    OpenClawSweepRequest,
    OpenClawWorkflowRequest,
    WebhookErrorResponse,
    WebhookResponse,
    WebhookStatus,
)

logger = logging.getLogger(__name__)

# Create router with tags for OpenAPI documentation
webhook_router = APIRouter(
    prefix="/openclaw",
    tags=["webhooks", "openclaw"],
    responses={
        429: {"model": WebhookErrorResponse, "description": "Rate limit exceeded"},
        401: {"model": WebhookErrorResponse, "description": "Authentication failed"},
        422: {"model": WebhookErrorResponse, "description": "Validation error"},
    },
)


# =============================================================================
# P0-5: Correct Auth Pattern
# =============================================================================
# IMPORTANT: Use MultiAuthHandler.authenticate_request(), NOT validate_jwt()
# The validate_jwt() function does NOT exist in this codebase.
#
# CORRECT:
#   from mahavishnu.core.subscription_auth import MultiAuthHandler
#   auth = MultiAuthHandler(config)
#   result = auth.authenticate_request(authorization)
#
# INCORRECT:
#   from mahavishnu.core.auth import validate_jwt  # DOES NOT EXIST
#   user = await validate_jwt(authorization)
# =============================================================================


async def get_auth_handler():
    """Get or create MultiAuthHandler instance.

    Lazy initialization to avoid circular imports.
    """
    from mahavishnu.core.config import get_settings
    from mahavishnu.core.subscription_auth import MultiAuthHandler

    settings = get_settings()
    return MultiAuthHandler(settings)


async def validate_auth(
    authorization: Annotated[
        str,
        Header(
            ...,
            alias="Authorization",
            description="Bearer token for authentication",
        ),
    ],
) -> dict[str, Any]:
    """Validate authentication using MultiAuthHandler.

    This is the CORRECT auth pattern for Mahavishnu.
    DO NOT use validate_jwt() - it does not exist.

    Args:
        authorization: Authorization header value (e.g., "Bearer <token>")

    Returns:
        Authentication result with user info and method used

    Raises:
        HTTPException: 401 if authentication fails
    """
    auth_handler = await get_auth_handler()

    try:
        result = auth_handler.authenticate_request(authorization)
        if not result.get("authenticated"):
            raise HTTPException(
                status_code=401,
                detail={
                    "error_code": "AUTHENTICATION_ERROR",
                    "message": "Authentication failed",
                    "recovery": [
                        "Ensure token is valid and not expired",
                        "Use 'Bearer <token>' format in Authorization header",
                    ],
                },
            )
        return result  # type: ignore[no-any-return]
    except AuthenticationError as e:
        logger.warning(f"Authentication failed: {e.message}")
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTHENTICATION_ERROR",
                "message": e.message,
                "recovery": [
                    "Check token format: 'Bearer <token>'",
                    "Verify token has not expired",
                ],
                "details": e.details,
            },
        )


# Type alias for dependency injection
AuthDep = Annotated[dict[str, Any], Depends(validate_auth)]


@webhook_router.post(
    "/sweep",
    response_model=WebhookResponse,
    responses={
        200: {"description": "Sweep workflow initiated"},
        429: {"model": WebhookErrorResponse, "description": "Rate limit exceeded"},
    },
    summary="Trigger sweep workflow for repositories matching a tag",
    description="""
    Initiates a sweep workflow across all repositories matching the specified tag.

    Rate limit: 10 requests per minute per IP.

    Security:
    - Tag must be alphanumeric with underscores/hyphens only
    - Path traversal characters are rejected
    - Requires valid authentication token
    """,
)
@rate_limit("10/minute")
async def sweep_endpoint(
    request: Request,
    sweep_request: OpenClawSweepRequest,
    auth: AuthDep,
) -> WebhookResponse:
    """Handle OpenClaw sweep webhook request.

    Triggers a sweep workflow across repositories matching the tag.

    Args:
        request: FastAPI request (for rate limiting)
        sweep_request: Validated sweep request parameters
        auth: Authentication result from dependency

    Returns:
        WebhookResponse with workflow status
    """
    logger.info(
        f"Sweep request from user {auth.get('user')}: "
        f"tag={sweep_request.tag}, adapter={sweep_request.adapter}"
    )

    # Get pool manager singleton
    get_pool_manager()

    # Get task router singleton
    task_router = TaskRouter()

    # Classify the task intent
    task_type = task_router.classify_intent(
        sweep_request.task_description or f"sweep {sweep_request.tag} repositories"
    )

    # Generate fallback chain
    fallback_chain = task_router.generate_fallback_chain(
        task_type,
        preferred_adapter=sweep_request.adapter,
    )

    # TODO: Trigger actual workflow execution via pool_manager
    # This is a stub for P0-4/P0-5 verification
    workflow_id = f"wf-sweep-{sweep_request.tag}-{auth.get('user', 'unknown')}"

    logger.info(
        f"Sweep workflow initiated: {workflow_id}, "
        f"task_type={task_type.value}, "
        f"fallback_chain={[a.value for a in fallback_chain]}"
    )

    return WebhookResponse(
        status=WebhookStatus.ACCEPTED,
        message=f"Sweep workflow initiated for tag '{sweep_request.tag}'",
        workflow_id=workflow_id,
        details={
            "tag": sweep_request.tag,
            "adapter": sweep_request.adapter.value,
            "task_type": task_type.value,
            "fallback_chain": [a.value for a in fallback_chain],
            "dry_run": sweep_request.dry_run,
            "user": auth.get("user"),
        },
    )


@webhook_router.post(
    "/workflow",
    response_model=WebhookResponse,
    responses={
        200: {"description": "Workflow initiated"},
        429: {"model": WebhookErrorResponse, "description": "Rate limit exceeded"},
    },
    summary="Trigger workflow for specified repositories",
    description="""
    Initiates a workflow across the specified repository list.

    Rate limit: 5 requests per minute per IP (lower due to higher resource usage).

    Security:
    - Repository paths are validated against path traversal
    - Absolute paths are rejected
    - Maximum 100 repositories per request
    - Requires valid authentication token
    """,
)
@rate_limit("5/minute")
async def workflow_endpoint(
    request: Request,
    workflow_request: OpenClawWorkflowRequest,
    auth: AuthDep,
) -> WebhookResponse:
    """Handle OpenClaw workflow webhook request.

    Triggers a workflow across the specified repositories.

    Args:
        request: FastAPI request (for rate limiting)
        workflow_request: Validated workflow request parameters
        auth: Authentication result from dependency

    Returns:
        WebhookResponse with workflow status
    """
    logger.info(
        f"Workflow request from user {auth.get('user')}: "
        f"repos={len(workflow_request.repos)}, adapter={workflow_request.adapter}"
    )

    # Get pool manager singleton
    get_pool_manager()

    # Get task router singleton
    task_router = TaskRouter()

    # Classify the task intent
    task_type = task_router.classify_intent(
        workflow_request.task_description or f"workflow for {len(workflow_request.repos)} repos"
    )

    # Generate fallback chain
    fallback_chain = task_router.generate_fallback_chain(
        task_type,
        preferred_adapter=workflow_request.adapter,
    )

    # TODO: Trigger actual workflow execution via pool_manager
    # This is a stub for P0-4/P0-5 verification
    workflow_id = f"wf-workflow-{auth.get('user', 'unknown')}"

    logger.info(
        f"Workflow initiated: {workflow_id}, "
        f"repos={len(workflow_request.repos)}, "
        f"task_type={task_type.value}, "
        f"fallback_chain={[a.value for a in fallback_chain]}"
    )

    return WebhookResponse(
        status=WebhookStatus.ACCEPTED,
        message=f"Workflow initiated for {len(workflow_request.repos)} repositories",
        workflow_id=workflow_id,
        details={
            "repos": workflow_request.repos,
            "repos_count": len(workflow_request.repos),
            "adapter": workflow_request.adapter.value,
            "task_type": task_type.value,
            "fallback_chain": [a.value for a in fallback_chain],
            "parallel": workflow_request.parallel,
            "timeout_seconds": workflow_request.timeout_seconds,
            "user": auth.get("user"),
        },
    )


@webhook_router.get(
    "/health",
    response_model=dict,
    summary="Health check for webhook endpoints",
    description="Returns health status of the webhook subsystem",
)
async def webhook_health() -> dict[str, str]:
    """Health check endpoint for webhook router.

    Returns:
        Health status dictionary
    """
    return {
        "status": "healthy",
        "service": "mahavishnu-webhooks",
        "endpoints": ["/openclaw/sweep", "/openclaw/workflow"],  # type: ignore[dict-item]
    }


__all__ = [
    "webhook_router",
    "validate_auth",
    "sweep_endpoint",
    "workflow_endpoint",
]

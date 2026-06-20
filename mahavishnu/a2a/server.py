from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING
import uuid

from oneiric.core.logging import get_logger
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from mahavishnu.a2a.card import A2ACapabilities, A2ASkill, AgentCard
from mahavishnu.core.status import WorkerStatus

logger = get_logger(__name__)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from typing import Any

    from starlette.requests import Request
    from starlette.types import ASGIApp, Receive, Scope, Send

    from mahavishnu.core.config import A2ASettings
    from mahavishnu.workers.base import WorkerResult


# ─── auth middleware ──────────────────────────────────────────────────────────


class _A2ABearerMiddleware:
    """Pure ASGI Bearer-token guard for A2A task endpoints.

    /.well-known/agent.json is intentionally public (A2A spec requirement).
    All other routes require ``Authorization: Bearer <token>``.
    Uses pure ASGI (not BaseHTTPMiddleware) so StreamingResponse is unaffected.
    """

    def __init__(self, app: ASGIApp, *, auth_token: str) -> None:
        self.app = app
        self._token = auth_token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("path") != "/.well-known/agent.json":
            headers = dict(scope.get("headers", []))
            auth = headers.get(b"authorization", b"").decode()
            expected = f"Bearer {self._token}"
            if auth != expected:
                response = Response(
                    '{"error":"Unauthorized"}', status_code=401, media_type="application/json"
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


# ─── private helpers ──────────────────────────────────────────────────────────


def _get_version() -> str:
    try:
        from importlib.metadata import version

        return version("mahavishnu")
    except Exception:  # noqa: BLE001
        return "0.0.0"


def _extract_prompt(task_data: dict[str, Any]) -> str:
    """Extract the first text part from a Google A2A task message."""
    parts = task_data.get("message", {}).get("parts", [])
    return next((p.get("text", "") for p in parts if p.get("type") == "text"), "")


def _result_to_a2a(task_id: str, result: WorkerResult) -> dict[str, Any]:
    if result.status == WorkerStatus.COMPLETED:
        return {
            "id": task_id,
            "status": {"state": "completed"},
            "artifacts": [{"parts": [{"type": "text", "text": result.output or ""}]}],
            "final": True,
        }
    return {
        "id": task_id,
        "status": {"state": "failed", "message": result.error or "Worker failed"},
        "final": True,
    }


def _error_to_a2a(task_id: str, error: str) -> dict[str, Any]:
    return {
        "id": task_id,
        "status": {"state": "failed", "message": error},
        "final": True,
    }


def _sse_event(
    task_id: str,
    state: str,
    *,
    final: bool,
    result: WorkerResult | None = None,
    error: str | None = None,
) -> str:
    payload: dict[str, Any] = {
        "id": task_id,
        "status": {"state": state},
        "final": final,
    }
    if result is not None:
        payload["artifacts"] = [{"parts": [{"type": "text", "text": result.output or ""}]}]
    if error:
        payload["status"]["message"] = error
    return f"data: {json.dumps(payload)}\n\n"


# ─── route factories ──────────────────────────────────────────────────────────


def _agent_card_handler(settings: A2ASettings):  # type: ignore[no-untyped-def]
    async def handler(request: Request) -> JSONResponse:
        card = AgentCard(
            name=settings.card.name,
            description=settings.card.description,
            url=str(request.base_url).rstrip("/"),
            version=settings.card.version or _get_version(),
            capabilities=A2ACapabilities(
                streaming=settings.card.capabilities.streaming,
                pushNotifications=settings.card.capabilities.pushNotifications,
            ),
            skills=[A2ASkill(**s) for s in settings.card.skills],
        )
        return JSONResponse(card.model_dump())

    return handler


# Module-level set keeps background tasks alive until they complete (prevents GC).
_background_tasks: set[asyncio.Task[None]] = set()


def _tasks_send_handler(execute_fn: Any):  # type: ignore[no-untyped-def]
    async def handler(request: Request) -> JSONResponse:
        task_data = await request.json()
        task_id: str = task_data.get("id", str(uuid.uuid4()))
        prompt = _extract_prompt(task_data)
        try:
            result = await execute_fn({"prompt": prompt})
            return JSONResponse(_result_to_a2a(task_id, result))
        except Exception:  # noqa: BLE001
            logger.exception("A2A /tasks/send handler error")
            return JSONResponse(_error_to_a2a(task_id, "Task execution failed"))

    return handler


def _tasks_send_subscribe_handler(execute_fn: Any):  # type: ignore[no-untyped-def]
    async def handler(request: Request) -> StreamingResponse:
        task_data = await request.json()
        task_id: str = task_data.get("id", str(uuid.uuid4()))
        prompt = _extract_prompt(task_data)
        queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=64)

        async def run_and_emit() -> None:
            await queue.put(_sse_event(task_id, "working", final=False))
            try:
                result = await execute_fn({"prompt": prompt})
                await queue.put(_sse_event(task_id, "completed", final=True, result=result))
            except Exception:  # noqa: BLE001
                logger.exception("A2A /tasks/sendSubscribe handler error")
                await queue.put(_sse_event(task_id, "failed", final=True, error="Task execution failed"))
            finally:
                await queue.put(None)

        task = asyncio.create_task(run_and_emit())
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

        async def event_generator() -> AsyncGenerator[str]:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    return handler


# ─── public factory ───────────────────────────────────────────────────────────


def build_a2a_router(
    settings: A2ASettings,
    execute_fn: Any,
    auth_token: str | None = None,
) -> Starlette:
    """Build a Starlette sub-application exposing Google A2A routes.

    When ``settings.require_auth`` is True and ``auth_token`` is provided,
    ``/tasks/send`` and ``/tasks/sendSubscribe`` require ``Authorization: Bearer <token>``.
    ``/.well-known/agent.json`` is always public per the A2A spec.
    """
    routes = [
        Route(
            "/.well-known/agent.json",
            endpoint=_agent_card_handler(settings),
            methods=["GET"],
        ),
        Route(
            "/tasks/send",
            endpoint=_tasks_send_handler(execute_fn),
            methods=["POST"],
        ),
        Route(
            "/tasks/sendSubscribe",
            endpoint=_tasks_send_subscribe_handler(execute_fn),
            methods=["POST"],
        ),
    ]
    middleware: list[Middleware] = []
    if settings.require_auth:
        if auth_token:
            middleware = [Middleware(_A2ABearerMiddleware, auth_token=auth_token)]
        else:
            logger.warning(
                "A2A server: require_auth=True but no auth_token available — "
                "task endpoints are UNPROTECTED. Set auth.enabled + auth.secret to fix."
            )
    return Starlette(routes=routes, middleware=middleware)

from __future__ import annotations

import asyncio
import json
import uuid
from typing import TYPE_CHECKING

from oneiric.core.logging import get_logger
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from mahavishnu.a2a.card import A2ACapabilities, A2ASkill, AgentCard
from mahavishnu.core.status import WorkerStatus

logger = get_logger(__name__)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from typing import Any

    from mahavishnu.core.config import A2ASettings
    from mahavishnu.workers.base import WorkerResult


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
        payload["artifacts"] = [
            {"parts": [{"type": "text", "text": result.output or ""}]}
        ]
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
            version=_get_version(),
            capabilities=A2ACapabilities(
                streaming=settings.card.capabilities.streaming,
                pushNotifications=settings.card.capabilities.pushNotifications,
            ),
            skills=[A2ASkill(**s) for s in settings.card.skills],
        )
        return JSONResponse(card.model_dump())

    return handler


def _tasks_send_handler(worker_manager: Any):  # type: ignore[no-untyped-def]
    async def handler(request: Request) -> JSONResponse:
        task_data = await request.json()
        task_id: str = task_data.get("id", str(uuid.uuid4()))
        prompt = _extract_prompt(task_data)
        try:
            result = await worker_manager.execute_task({"prompt": prompt})
            return JSONResponse(_result_to_a2a(task_id, result))
        except Exception as e:  # noqa: BLE001
            logger.exception("A2A /tasks/send handler error")
            return JSONResponse(_error_to_a2a(task_id, str(e)))

    return handler


def _tasks_send_subscribe_handler(worker_manager: Any):  # type: ignore[no-untyped-def]
    async def handler(request: Request) -> StreamingResponse:
        task_data = await request.json()
        task_id: str = task_data.get("id", str(uuid.uuid4()))
        prompt = _extract_prompt(task_data)
        queue: asyncio.Queue[str | None] = asyncio.Queue()

        async def run_and_emit() -> None:
            await queue.put(_sse_event(task_id, "working", final=False))
            try:
                result = await worker_manager.execute_task({"prompt": prompt})
                await queue.put(
                    _sse_event(task_id, "completed", final=True, result=result)
                )
            except Exception as e:  # noqa: BLE001
                logger.exception("A2A /tasks/sendSubscribe handler error")
                await queue.put(_sse_event(task_id, "failed", final=True, error=str(e)))
            finally:
                await queue.put(None)

        _bg = asyncio.create_task(run_and_emit())

        async def event_generator() -> AsyncGenerator[str, None]:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    return handler


# ─── public factory ───────────────────────────────────────────────────────────


def build_a2a_router(settings: A2ASettings, worker_manager: Any) -> Starlette:
    """Build a Starlette sub-application exposing Google A2A routes."""
    return Starlette(
        routes=[
            Route(
                "/.well-known/agent.json",
                endpoint=_agent_card_handler(settings),
                methods=["GET"],
            ),
            Route(
                "/tasks/send",
                endpoint=_tasks_send_handler(worker_manager),
                methods=["POST"],
            ),
            Route(
                "/tasks/sendSubscribe",
                endpoint=_tasks_send_subscribe_handler(worker_manager),
                methods=["POST"],
            ),
        ]
    )

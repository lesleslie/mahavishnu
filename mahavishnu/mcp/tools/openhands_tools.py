"""MCP tools for OpenHands autonomous development integration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from oneiric.core.logging import get_logger
from pydantic import BaseModel, Field

from mahavishnu.core.config import MahavishnuSettings
from mahavishnu.workers.openhands import OpenHandsClient, OpenHandsConfig, OpenHandsWorker

logger = get_logger(__name__)
mcp = FastMCP("openhands")

_settings = MahavishnuSettings()


class OpenHandsRunInput(BaseModel):
    """Validated input for the openhands_run MCP tool."""

    prompt: str = Field(..., min_length=1, max_length=10_000)
    timeout: int = Field(600, ge=30, le=3600)
    run_quality_check: bool = True


def _make_config() -> OpenHandsConfig:
    """Build OpenHandsConfig from MahavishnuSettings."""
    oh_settings = getattr(_settings, "openhands", None)
    base_url = (
        getattr(oh_settings, "base_url", "http://localhost:3000")
        if oh_settings
        else "http://localhost:3000"
    )
    workspace_dir = (
        getattr(oh_settings, "workspace_dir", Path("/tmp/openhands-workspace"))  # noqa: S108
        if oh_settings
        else Path("/tmp/openhands-workspace")  # noqa: S108
    )

    # Validate workspace_dir containment (MUST be under a configured root)
    workspace_dir = Path(workspace_dir).resolve()
    allowed_root = Path("/tmp").resolve()  # noqa: S108 - override via settings in production
    if oh_settings and hasattr(oh_settings, "workspace_root"):
        allowed_root = Path(oh_settings.workspace_root).resolve()
    if not str(workspace_dir).startswith(str(allowed_root)):
        raise ValueError(
            f"workspace_dir {workspace_dir} is outside allowed root {allowed_root}"
        )

    return OpenHandsConfig(base_url=base_url, workspace_dir=workspace_dir)


async def _run_quality_check(output: str) -> int | None:
    """Run Crackerjack quality check on output. Returns score or None."""
    try:
        from mahavishnu.quality_cli import run_quality_check as crackerjack_check  # noqa: PLC0415

        score = await crackerjack_check(output)
        return score
    except Exception as e:
        logger.warning(f"Quality check failed (non-fatal): {e}")
        return None


async def run_openhands_task(inp: OpenHandsRunInput) -> dict[str, Any]:
    """Core implementation — called by both the MCP tool and tests."""
    config = _make_config()
    worker = OpenHandsWorker(config=config)

    result = await worker.execute({"prompt": inp.prompt, "timeout": inp.timeout})

    quality_score: int | None = None
    if inp.run_quality_check and result.output:
        quality_score = await _run_quality_check(result.output)

    return {
        "status": result.status.value,
        "output": result.output,
        "error": result.error if result.status.value != "completed" else None,
        "quality_score": quality_score,
        "worker_type": "openhands",
    }


@mcp.tool()
async def openhands_run(
    prompt: str,
    timeout: int = 600,
    run_quality_check: bool = True,
) -> dict[str, Any]:
    """Submit an autonomous development task to OpenHands.

    Args:
        prompt: Task description (1-10,000 chars).
        timeout: Max seconds to wait (30-3600). Default 600.
        run_quality_check: Run Crackerjack quality check on output. Default True.
    """
    inp = OpenHandsRunInput(
        prompt=prompt, timeout=timeout, run_quality_check=run_quality_check
    )
    return await run_openhands_task(inp)


@mcp.tool()
async def openhands_status(conv_id: str) -> dict[str, Any]:
    """Get the status of a running OpenHands conversation."""
    config = _make_config()
    client = OpenHandsClient(config)
    try:
        data = await client.get_status(conv_id)
        return {"conv_id": conv_id, "data": data}
    finally:
        await client.close()


@mcp.tool()
async def openhands_cancel(conv_id: str) -> dict[str, Any]:
    """Cancel a running OpenHands conversation."""
    config = _make_config()
    client = OpenHandsClient(config)
    try:
        await client.cancel_conversation(conv_id)
        return {"conv_id": conv_id, "cancelled": True}
    finally:
        await client.close()


@mcp.tool()
async def openhands_health() -> dict[str, Any]:
    """Check whether the OpenHands service is reachable."""
    config = _make_config()
    client = OpenHandsClient(config)
    try:
        healthy = await client.health_check()
        return {"healthy": healthy, "base_url": config.base_url}
    finally:
        await client.close()

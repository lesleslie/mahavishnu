"""Async live probes for worker capability evaluation."""

from __future__ import annotations

import asyncio
import os
import shutil
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import httpx2 as httpx

from ._safe import safe_error_for_user
from ._states import WorkerCheck

if TYPE_CHECKING:
    from mahavishnu.core.config import MahavishnuSettings


def _check_endpoint_scheme(endpoint: str, *, has_secret: bool) -> str | None:
    """Return an error reason when the endpoint is http:// and a secret is in use.

    Sending Authorization: Bearer <token> over plain http:// leaks the token in
    cleartext. Operators must use https:// for token-bearing requests. Returns
    None when the scheme is acceptable (https://, no secret, or empty endpoint).
    """
    if not endpoint or not has_secret:
        return None
    try:
        parsed = urlparse(endpoint)
    except ValueError:
        return None
    if parsed.scheme == "http":
        return "insecure_endpoint"
    return None


async def _probe_openclaw_gateway(endpoint: str, token: str | None) -> WorkerCheck:
    scheme_error = _check_endpoint_scheme(endpoint, has_secret=bool(token))
    if scheme_error is not None:
        return WorkerCheck("openclaw_gateway", "fail", scheme_error)
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(
                f"{endpoint.rstrip('/')}/health",
                headers={"Authorization": f"Bearer {token}"} if token else {},
            )
            r.raise_for_status()
            p = r.json()
    except (httpx.HTTPError, ValueError, OSError) as exc:
        return WorkerCheck("openclaw_gateway", "fail", type(exc).__name__)
    return WorkerCheck(
        "openclaw_gateway",
        "pass" if isinstance(p, dict) and p.get("healthy") else "fail",
        "ok" if isinstance(p, dict) and p.get("healthy") else "unhealthy",
    )


async def _probe_openclaw_cli(binary: str) -> WorkerCheck:
    if shutil.which(binary) is None:
        return WorkerCheck("openclaw_cli", "fail", f"missing:{binary}")
    try:
        p = await asyncio.create_subprocess_exec(
            binary, "--version", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        out, _ = await asyncio.wait_for(p.communicate(), 5)
    except (TimeoutError, OSError) as exc:
        return WorkerCheck("openclaw_cli", "fail", type(exc).__name__)
    return WorkerCheck(
        "openclaw_cli",
        "pass" if p.returncode == 0 else "fail",
        safe_error_for_user(out.decode().strip() or "ok") if p.returncode == 0 else "non_zero_exit",
    )


async def _probe_container_daemon(runtime: str) -> WorkerCheck:
    if shutil.which(runtime) is None:
        return WorkerCheck("container_daemon", "fail", f"missing:{runtime}")
    try:
        p = await asyncio.create_subprocess_exec(
            runtime,
            "version",
            "--format",
            "{{.Server.Version}}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await asyncio.wait_for(p.communicate(), 5)
    except (TimeoutError, OSError) as exc:
        return WorkerCheck("container_daemon", "fail", type(exc).__name__)
    return WorkerCheck(
        "container_daemon",
        "pass" if p.returncode == 0 else "fail",
        safe_error_for_user(out.decode().strip() or "ok")
        if p.returncode == 0
        else "daemon_unreachable",
    )


async def _probe_auth_presence(names: list[str]) -> WorkerCheck:
    missing = [n for n in names if not os.environ.get(n)]
    return WorkerCheck(
        "auth", "fail" if missing else "pass", ",".join(missing) if missing else "ok"
    )


async def _probe_provider_request(provider: str, env_var: str, endpoint: str) -> WorkerCheck:
    token = os.environ.get(env_var)
    if not token:
        return WorkerCheck(f"{provider}_auth", "fail", "missing")
    scheme_error = _check_endpoint_scheme(endpoint, has_secret=True)
    if scheme_error is not None:
        return WorkerCheck(f"{provider}_auth", "fail", scheme_error)
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(endpoint, headers={"Authorization": f"Bearer {token}"})
            r.raise_for_status()
    except httpx.HTTPError as exc:
        return WorkerCheck(f"{provider}_auth", "fail", safe_error_for_user(type(exc).__name__))
    return WorkerCheck(f"{provider}_auth", "pass", "ok")


PROBES = {
    "openclaw_gateway": _probe_openclaw_gateway,
    "openclaw_cli": _probe_openclaw_cli,
    "container_daemon": _probe_container_daemon,
    "auth_presence": _probe_auth_presence,
    "provider_request": _probe_provider_request,
}


def resolve_probe_endpoint(
    provider: str,
    settings: MahavishnuSettings | None = None,
) -> str:
    """Resolve the provider probe endpoint, routing through Bifrost when enabled.

    Per the v1.5 Bifrost spec §5.3 + plan §5 Phase B (REQ-003):
    when ``settings.bifrost.enabled and provider == "minimax"``, the
    probe goes to ``<bifrost.base_url>/v1/models`` (the Bifrost
    gateway's OpenAI-compatible /v1/models endpoint). Otherwise
    the literal ``PROVIDER_PROBES[provider][1]`` is returned (so
    the probe dictionary stays stable for tests and operator
    inspection).

    The provider set is the four in ``PROVIDER_PROBES``: ``minimax``,
    ``anthropic``, ``openai``, ``qwen``. For non-minimax providers
    the helper is a passthrough regardless of the bifrost flag
    (per the v1.5 amendment — only the cloud-tier MinMax path is
    routed through Bifrost; the other providers stay direct).
    """
    if settings is not None and getattr(settings, "bifrost", None) is not None:
        bifrost = settings.bifrost
        if bifrost.enabled and provider == "minimax":
            return bifrost.base_url.rstrip("/") + "/v1/models"
    return PROVIDER_PROBES[provider][1]


PROVIDER_PROBES = {
    "minimax": ("MINIMAX_API_KEY", "https://api.minimax.io/v1/models"),
    "anthropic": ("ANTHROPIC_API_KEY", "https://api.anthropic.com/v1/models"),
    "openai": ("OPENAI_API_KEY", "https://api.openai.com/v1/models"),
    "qwen": ("QWEN_API_KEY", "https://dashscope.aliyuncs.com/api/v1/models"),
}

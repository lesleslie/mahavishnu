"""Async live probes for worker capability evaluation."""

from __future__ import annotations

import asyncio
import ipaddress
import os
import shutil
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import httpx2 as httpx

from mahavishnu.bifrost.models import VIRTUAL_KEY_ENV, VIRTUAL_KEY_HEADER
from mahavishnu.bifrost.paths import DEFAULT_BIFROST_PORT

from ._safe import safe_error_for_user
from ._states import WorkerCheck

if TYPE_CHECKING:
    from mahavishnu.core.config import MahavishnuSettings


def _is_loopback(hostname: str | None) -> bool:
    """True for hosts that never leave the machine."""
    if not hostname:
        return False
    if hostname.lower() in {"localhost", "localhost.localdomain"}:
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _check_endpoint_scheme(endpoint: str, *, has_secret: bool) -> str | None:
    """Return an error reason when the endpoint is http:// and a secret is in use.

    Sending a bearer token over plain http:// leaks it in cleartext. Operators
    must use https:// for token-bearing requests.

    Loopback is exempt: traffic to 127.0.0.1 never crosses a network, so there
    is nothing to eavesdrop on. The Bifrost gateway is served over loopback
    http and is the reason this exemption exists -- without it every probe of a
    perfectly healthy local gateway reports ``insecure_endpoint`` and the
    capability is scored unavailable.
    """
    if not endpoint or not has_secret:
        return None
    try:
        parsed = urlparse(endpoint)
    except ValueError:
        return None
    if parsed.scheme != "http":
        return None
    if _is_loopback(parsed.hostname):
        return None
    return "insecure_endpoint"


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


def _is_bifrost_endpoint(endpoint: str) -> bool:
    """True when ``endpoint`` addresses the local Bifrost gateway.

    Bifrost is a gateway, not a provider: it does not accept an upstream
    provider key, and reads virtual keys *exclusively* from its own
    ``x-bf-vk`` header. A header-differential probe confirmed no
    ``Authorization: Bearer`` form is honoured. Probing it the upstream way
    returns 401 forever, which reports a healthy gateway as unreachable.
    """
    parsed = urlparse(endpoint)
    return _is_loopback(parsed.hostname) and parsed.port == DEFAULT_BIFROST_PORT


def _probe_auth_headers(provider: str, env_var: str, endpoint: str) -> tuple[dict[str, str] | None, str]:
    """Build the headers for a provider probe, or explain why we cannot.

    Returns ``(headers, "")`` on success and ``(None, reason)`` when the
    required credential is absent. Bifrost probes use the gateway's virtual
    key; direct-provider probes keep the upstream bearer token.
    """
    if _is_bifrost_endpoint(endpoint):
        virtual_key = os.environ.get(VIRTUAL_KEY_ENV)
        if not virtual_key:
            return None, f"missing {VIRTUAL_KEY_ENV}"
        return {VIRTUAL_KEY_HEADER: virtual_key}, ""

    token = os.environ.get(env_var)
    if not token:
        return None, "missing"
    return {"Authorization": f"Bearer {token}"}, ""


async def _probe_provider_request(provider: str, env_var: str, endpoint: str) -> WorkerCheck:
    headers, reason = _probe_auth_headers(provider, env_var, endpoint)
    if headers is None:
        return WorkerCheck(f"{provider}_auth", "fail", reason)
    scheme_error = _check_endpoint_scheme(endpoint, has_secret=True)
    if scheme_error is not None:
        return WorkerCheck(f"{provider}_auth", "fail", scheme_error)
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(endpoint, headers=headers)
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

    Per REQ-BIFROST-007: when the oneiric ``BifrostLLMRouter``
    returns a URL for the OPENAI provider (router is enabled +
    OPENAI route is configured) **and** ``provider == "minimax"``,
    the probe goes to ``<router.base_url>/v1/models`` (the Bifrost
    gateway's OpenAI-compatible /v1/models endpoint). Otherwise the
    literal ``PROVIDER_PROBES[provider][1]`` is returned (so the
    probe dictionary stays stable for tests and operator
    inspection).

    The ``settings`` parameter is preserved for API stability; the
    oneiric router reads its own config from the environment. The
    ``settings.bifrost`` check is honored as a precedence override —
    if it's explicitly disabled, the probe stays direct.

    The provider set is the four in ``PROVIDER_PROBES``: ``minimax``,
    ``anthropic``, ``openai``, ``qwen``. For non-minimax providers
    the helper is a passthrough regardless of the bifrost flag
    (per the v1.5 amendment — only the cloud-tier MiniMax path is
    routed through Bifrost; the other providers stay direct).
    """
    from oneiric.adapters.llm.bifrost import get_router
    from oneiric.adapters.llm.llm_interface import LLMProvider

    settings_disables_bifrost = (
        settings is not None
        and getattr(settings, "bifrost", None) is not None
        and not settings.bifrost.enabled
    )
    if settings_disables_bifrost or provider != "minimax":
        return PROVIDER_PROBES[provider][1]
    resolved = get_router().resolve(LLMProvider.OPENAI)
    if resolved is not None:
        # The router's base URL already carries the OpenAI-compatible ``/v1``
        # suffix when it points at Bifrost (``OPENAI_BASE_URL`` convention), so
        # unconditionally appending another produced ``/v1/v1/models`` -- a
        # path Bifrost does not serve, which reported a healthy gateway as
        # unreachable. Mirrors the same guard in ``terminal/manager.py``.
        base = resolved.rstrip("/")
        if not base.endswith("/v1"):
            base += "/v1"
        return f"{base}/models"
    return PROVIDER_PROBES[provider][1]


PROVIDER_PROBES = {
    "minimax": ("MINIMAX_API_KEY", "https://api.minimax.io/v1/models"),
    "anthropic": ("ANTHROPIC_API_KEY", "https://api.anthropic.com/v1/models"),
    "openai": ("OPENAI_API_KEY", "https://api.openai.com/v1/models"),
    "qwen": ("QWEN_API_KEY", "https://dashscope.aliyuncs.com/api/v1/models"),
}

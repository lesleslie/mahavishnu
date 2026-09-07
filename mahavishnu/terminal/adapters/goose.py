"""Goose terminal adapter (Block's ``goose serve`` over HTTP).

The adapter wraps a :class:`~mahavishnu.terminal.goose_client.GooseHTTPClient`
and translates the abstract :class:`TerminalAdapter` operations into HTTP
calls. v1 is HTTP-poll based — capture_output issues a fresh ``GET
/sessions/{id}/output`` per call. WebSocket streaming (v2) is a planned
follow-up; ``goose_client.stream()`` returns ``NotImplementedError``.

Session ID format
=================
Default is full UUID4 (``session_id_format="uuid"``). The Mock adapter uses
8-character prefixes — that pattern would collide after ~10K concurrent
sessions per the security review (D3 BLOCKER #10). Goose owns its own UUID
universe so we always emit the 36-char canonical form.

Req: REQ-GOO-001, REQ-GOO-002, REQ-GOO-005, REQ-GOO-007
"""  # req: REQ-GOO-007

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, cast
import uuid

from oneiric.core.logging import get_logger

from ...core.errors import (
    GooseAuthError,
    GooseTimeoutError,
    GooseUnavailable,
)
from .base import SessionNotFoundError, TerminalAdapter, TerminalError

if TYPE_CHECKING:
    from ..goose_client import GooseHTTPClient

logger = get_logger(__name__)


class GooseTerminalAdapter(TerminalAdapter):
    """Terminal adapter backed by ``goose serve`` over HTTP.

    The adapter does not own the ``goose serve`` subprocess — operators run
    that separately (``goose serve --port 8694 --auth-token $GOOSE_SECRET``).
    The adapter owns its :class:`GooseHTTPClient` and a local ``_sessions``
    dict that maps our local session IDs (UUID4 by default) to server-side
    handles.
    """

    def __init__(
        self,
        http_client: GooseHTTPClient,
        *,
        session_id_format: Literal["uuid", "short"] = "uuid",
    ) -> None:
        self.http = http_client
        self._sessions: dict[str, dict[str, Any]] = {}
        # 8-char IDs are reserved for the Mock adapter; we default to UUID4
        # so 10K+ sessions don't collide.
        if session_id_format not in {"uuid", "short"}:
            raise ValueError(
                f"GooseTerminalAdapter: session_id_format must be 'uuid' or 'short', "
                f"got {session_id_format!r}"
            )
        self._session_id_format = session_id_format  # req: REQ-GOO-005

    @property
    def adapter_name(self) -> str:
        """Return adapter name."""
        return "goose"

    def _new_session_id(self) -> str:
        """Generate a session ID matching the configured format.

        REQ-GOO-005 — UUID4 is the default; ``short`` only exists for
        parity with the Mock adapter's 8-char prefixes and is rarely
        needed in production.
        """
        if self._session_id_format == "short":
            return str(uuid.uuid4())[:8]
        return str(uuid.uuid4())

    async def startup_probe(self) -> dict[str, Any]:
        """Fire a no-op authenticated call to verify the bearer is accepted.

        Returns a dict so callers can inspect ``ok`` and ``detail``. The
        default ABC behaviour is ``{"ok": True}``; the Goose implementation
        actively probes by hitting ``GET /health`` (or ``GET /`` if the
        server doesn't expose ``/health``).
        """
        try:
            await self.http.request("GET", "/health")
            return {"ok": True, "adapter": self.adapter_name}
        except GooseAuthError as exc:
            # Auth is the operator's misconfiguration, not a probe failure.
            auth_details: dict[str, Any] = cast("dict[str, Any]", exc.details)  # pyright: ignore[reportUnknownMemberType]
            return {
                "ok": False,
                "adapter": self.adapter_name,
                "reason": "auth_failed",
                "status_code": auth_details.get("status_code"),
            }
        except GooseUnavailable as exc:
            details: dict[str, Any] = cast("dict[str, Any]", exc.details)  # pyright: ignore[reportUnknownMemberType]
            return {
                "ok": False,
                "adapter": self.adapter_name,
                "reason": "unreachable",
                "install_hint": details.get("install_hint", ""),
            }
        except GooseTimeoutError as exc:
            timeout_details: dict[str, Any] = cast("dict[str, Any]", exc.details)  # pyright: ignore[reportUnknownMemberType]
            return {
                "ok": False,
                "adapter": self.adapter_name,
                "reason": "timeout",
                "timeout_seconds": timeout_details.get("timeout_seconds"),
            }

    async def launch_session(
        self,
        command: str,
        columns: int = 80,
        rows: int = 24,
        **kwargs: Any,
    ) -> str:
        """Allocate a server-side session via ``POST /sessions``.

        Args:
            command: Initial command to run in the terminal.
            columns: Terminal width in characters.
            rows: Terminal height in lines.
            **kwargs: Adapter-specific parameters (e.g. ``cwd``).

        Returns:
            Local session ID (UUID4 by default). The server-side handle
            (whatever goose returns) is stored in ``_sessions`` keyed by
            this ID.
        """
        local_id = self._new_session_id()
        try:
            result = await self.http.request(
                "POST",
                "/sessions",
                json={
                    "command": command,
                    "columns": columns,
                    "rows": rows,
                    **({"kwargs": kwargs} if kwargs else {}),
                },
            )
        except (GooseUnavailable, GooseTimeoutError, GooseAuthError) as exc:
            raise TerminalError(
                message=f"goose: failed to launch session: {exc}",
                details={"local_id": local_id, "command": command},
            ) from exc
        server_handle = result.get("session_id") or result.get("id") or local_id
        self._sessions[local_id] = {
            "command": command,
            "columns": columns,
            "rows": rows,
            "server_handle": server_handle,
        }
        logger.debug("goose session launched: local=%s server=%s", local_id, server_handle)
        return local_id

    async def send_command(self, session_id: str, command: str) -> None:
        """Send a command to an active goose session.

        Args:
            session_id: Local session identifier from :meth:`launch_session`.
            command: Command string to send.

        Raises:
            SessionNotFoundError: If ``session_id`` is not tracked locally.
            TerminalError: If the underlying HTTP call fails.
        """
        meta = self._sessions.get(session_id)
        if meta is None:
            raise SessionNotFoundError(
                message=f"goose: session {session_id} not found",
                details={"session_id": session_id},
            )
        server_handle = meta["server_handle"]
        try:
            await self.http.request(
                "POST",
                f"/sessions/{server_handle}/input",
                json={"command": command},
            )
        except (GooseUnavailable, GooseTimeoutError, GooseAuthError) as exc:
            raise TerminalError(
                message=f"goose: failed to send command: {exc}",
                details={"session_id": session_id, "command": command},
            ) from exc

    async def capture_output(
        self,
        session_id: str,
        lines: int | None = None,
    ) -> str:
        """Capture PTY output via ``GET /sessions/{id}/output``.

        Args:
            session_id: Local session identifier.
            lines: Number of trailing lines to capture (None for full buffer).

        Returns:
            Terminal output as a string.

        Raises:
            SessionNotFoundError: If ``session_id`` is not tracked locally.
            TerminalError: If the underlying HTTP call fails.
        """
        meta = self._sessions.get(session_id)
        if meta is None:
            raise SessionNotFoundError(
                message=f"goose: session {session_id} not found",
                details={"session_id": session_id},
            )
        server_handle = meta["server_handle"]
        path = f"/sessions/{server_handle}/output"
        if lines is not None:
            path = f"{path}?limit_lines={int(lines)}"
        try:
            result = await self.http.request("GET", path)
        except (GooseUnavailable, GooseTimeoutError, GooseAuthError) as exc:
            raise TerminalError(
                message=f"goose: failed to capture output: {exc}",
                details={"session_id": session_id},
            ) from exc
        if isinstance(result, str):
            return result
        # Per contract, the server returns either a JSON object (dict) or a
        # string body; guard for both. Pyright narrows dict[str, Any] to
        # dict[Unknown, Unknown] at the attribute level, so isinstance is
        # redundant for type but useful as a runtime invariant.
        if isinstance(result, dict):  # pyright: ignore[reportUnnecessaryIsInstance]
            return result.get("output") or ""
        return str(result)

    async def close_session(self, session_id: str) -> None:
        """Close a goose session via ``DELETE /sessions/{id}``.

        Errors are logged at WARN level rather than re-raised so the caller
        can drop the session even when the server is unreachable.

        Args:
            session_id: Local session identifier.
        """
        meta = self._sessions.pop(session_id, None)
        if meta is None:
            # Already gone — treat as success.
            return
        server_handle = meta["server_handle"]
        try:
            await self.http.request("DELETE", f"/sessions/{server_handle}")
        except (GooseUnavailable, GooseTimeoutError, GooseAuthError) as exc:
            logger.warning("goose: close_session failed (non-fatal): %s", exc)
        logger.debug("goose session closed: %s", session_id)

    async def list_sessions(self) -> list[dict[str, Any]]:
        """Return locally tracked sessions as a list of dicts."""
        return [
            {
                "id": sid,
                "command": meta["command"],
                "columns": meta["columns"],
                "rows": meta["rows"],
                "server_handle": meta["server_handle"],
            }
            for sid, meta in self._sessions.items()
        ]

    async def run_applescript(self, script: str) -> str:
        """AppleScript is not supported on the Goose adapter — Goose is a
        cross-platform Rust binary, not an iTerm2/macOS shell."""
        raise NotImplementedError("GooseTerminalAdapter does not support AppleScript")


__all__ = ["GooseTerminalAdapter"]

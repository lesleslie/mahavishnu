"""Terminal-based AI workers — compatibility shim over GenericShellWorker.

All execution behaviour now lives in GenericShellWorker.  TerminalAIWorker
keeps the legacy ``ai_type`` constructor API so existing callers are not
broken during the transition period.  New code should use GenericShellWorker
directly.
"""

import logging
from typing import Any

from .base import WorkerResult
from .generic_shell import GenericShellWorker

logger = logging.getLogger(__name__)


class TerminalAIWorker(GenericShellWorker):
    """Compatibility shim for GenericShellWorker with the ``ai_type`` API.

    Translates the legacy positional ``ai_type`` parameter into the
    ``worker_type`` key used by GenericShellWorker and the worker registry.
    All execution, completion detection, and Session-Buddy storage delegate
    to GenericShellWorker.

    Use GenericShellWorker directly for new code:

        worker = GenericShellWorker(terminal_manager, worker_type="terminal-claude")

    Args:
        terminal_manager: TerminalManager for session control.
        ai_type: Short AI name without prefix (e.g. ``"claude"``, ``"qwen"``).
        session_id: Optional pre-existing session ID.
        session_buddy_client: Optional Session-Buddy MCP client.
    """

    def __init__(
        self,
        terminal_manager: Any,
        ai_type: str,
        session_id: str | None = None,
        session_buddy_client: Any = None,
    ) -> None:
        super().__init__(
            terminal_manager=terminal_manager,
            worker_type=f"terminal-{ai_type}",
            session_id=session_id,
            session_buddy_client=session_buddy_client,
        )
        # Backward-compatibility attributes accessed by legacy code and tests.
        self.worker_name = ai_type
        self.worker_key = self.worker_type
        self._worker_config = self.config

    async def execute(self, task: dict[str, Any]) -> WorkerResult:
        """Execute task, prepending the repo path to the prompt when provided.

        The ``repo`` key in *task* is a legacy convenience shorthand; callers
        that already embed the repo path in the prompt can omit it.
        """
        if task.get("repo"):
            prompt = task.get("prompt", "")
            task = {**task, "prompt": f"Working in {task['repo']}. {prompt}"}
        return await super().execute(task)


__all__ = ["TerminalAIWorker"]

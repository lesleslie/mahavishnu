"""Conservative path-traversal guard for caller-supplied workflow IDs.

Caller-provided ``workflow_id`` is spliced into
``f"workflow-results/{workflow_id}/"`` for both ``dispatch_to_pool`` and
``workflow_result``, so it MUST match a conservative identifier pattern
before touching Dhara. On mismatch, callers should return
``{"workflow_id": workflow_id, "status": "invalid_workflow_id"}`` so MCP
callers see a consistent error shape and Dhara is never touched with a
tainted key.

Mirrors the legacy ``uuid4()`` shape: 1-128 chars, alphanumeric plus dot,
dash, and underscore. Anything outside this regex must be rejected BEFORE
the value is spliced into a Dhara key path, otherwise a caller can read
or write ``workflow-results/../../etc/...`` on the persist layer.
"""

from __future__ import annotations

import re

WORKFLOW_ID_PATTERN: re.Pattern[str] = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def validate_workflow_id(workflow_id: str) -> bool:
    """Return True iff ``workflow_id`` is a safe Dhara key fragment."""
    return bool(WORKFLOW_ID_PATTERN.match(workflow_id))


# Back-compat aliases preserved so existing call sites keep compiling during
# the extraction window. New code should import ``WORKFLOW_ID_PATTERN`` and
# ``validate_workflow_id`` from this module directly.
_WORKFLOW_ID_PATTERN = WORKFLOW_ID_PATTERN
_validate_workflow_id = validate_workflow_id

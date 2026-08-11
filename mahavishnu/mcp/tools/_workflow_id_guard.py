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


def validate_approval_id(approval_id: str) -> bool:
    """Check ``approval_id`` against the per-id allowlist pattern.

    Mirrors :func:`validate_workflow_id`. Used at the read path in
    :func:`mahavishnu.cli.approval_cli.list_approval_history` before
    splicing into ``f"approval-history/{approval_id}/"``.

    The producer side is server-generated (see
    :mod:`mahavishnu.core.approval_manager`); this guard exists so the
    consumer side rejects caller-supplied traversal attempts before the
    value reaches the Dhara key path.
    """
    return bool(WORKFLOW_ID_PATTERN.match(approval_id))


def validate_webhook_id(webhook_id: str) -> bool:
    """Check ``webhook_id`` against the per-id allowlist pattern.

    Mirrors :func:`validate_workflow_id`. Used at the read path in
    :func:`mahavishnu.webhooks.replay.webhook_replay` before splicing
    into ``f"webhook-ingress/{webhook_id}/"``.

    The producer side is server-generated (see
    :mod:`dhara.schema.webhook_ingress`); this guard exists so the
    consumer side rejects caller-supplied traversal attempts before the
    value reaches the Dhara key path.
    """
    return bool(WORKFLOW_ID_PATTERN.match(webhook_id))


# Back-compat aliases preserved so existing call sites keep compiling during
# the extraction window. New code should import ``WORKFLOW_ID_PATTERN``,
# ``validate_workflow_id``, ``validate_approval_id``, and
# ``validate_webhook_id`` from this module directly.
_WORKFLOW_ID_PATTERN = WORKFLOW_ID_PATTERN
_validate_workflow_id = validate_workflow_id

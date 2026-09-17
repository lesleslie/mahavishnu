"""Mahavishnu-owned persistence types — locally vendored from Dhara.

These are the durable entity shapes produced by Mahavishnu's workflow /
approval / webhook writers and consumed by the corresponding readers.
They were previously imported from ``dhara.schema.{WorkflowOutcome,
ApprovalLog, WebhookIngress}``; after the Phase 8 Dhara MCP retirement
(see ``docs/plans/2026-09-16-dhara-mcp-retirement-plan.md``) they live
in this consumer repo instead.

Per user direction 2026-09-16 ("use oneiric models not equivalents"),
these types are **NOT** shipped as oneiric equivalents. Oneiric is a
substrate library (lifecycle, registry, settings, queues, persistence
primitives), not a Bodai-component-shaped model catalog. Each consumer
repo that needs these shapes owns its own copy. If a future contributor
is tempted to "promote" these into oneiric for tidiness, cite this
header and the plan's Task 2 before doing so.

The ``msgspec.Struct(frozen=True)`` form is preserved verbatim from
the Dhara originals (``dhara/schema/workflow_outcome.py``,
``dhara/schema/approval_log.py``, ``dhara/schema/webhook_ingress.py``).
Wire-format compatibility is pinned by
``tests/unit/test_models_persistence.py``.

Scope notes for downstream Tasks 4 + 7 of the plan:

- ``validate`` / ``from_dict`` / ``to_dict`` helpers from ``dhara.schema``
  are **not** re-exported here — they wrap the Dhara schema registry,
  which is itself staying in Dhara. Call-sites that currently do
  ``dhara.schema.validate(x)`` / ``dhara.schema.from_dict(Struct, x)`` /
  ``dhara.schema.to_dict(x)`` will be migrated in Tasks 4 + 7 to
  either msgspec primitives (``msgspec.convert`` / ``msgspec.to_builtins``)
  or to small wrappers added at that point.
- ``SchemaValidationError`` becomes ``msgspec.ValidationError`` at the
  call sites that need to catch validation failures.
- ``ChannelSessionState`` (session-buddy-only) is **not** defined here;
  it will be added in a session-buddy-local module as part of Task 7.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

import msgspec


class WorkflowOutcome(msgspec.Struct, frozen=True):
    """Structured result of a workflow execution.

    Mirrors ``dhara.schema.WorkflowOutcome`` field-for-field. Persisted
    by Mahavishnu's workflow outcome writer.
    """

    workflow_id: str
    status: Literal["succeeded", "failed", "cancelled"]
    started_at: datetime
    finished_at: datetime
    metadata: dict[str, Any] = msgspec.field(default_factory=dict)


class ApprovalLog(msgspec.Struct, frozen=True):
    """Approval history entry — append-only.

    Mirrors ``dhara.schema.ApprovalLog`` field-for-field. Records are
    written by Mahavishnu's approval decision writer and read via
    ``list_approval_history``.
    """

    approval_id: str
    actor: str
    action: Literal["approved", "denied", "requested"]
    at: datetime
    metadata: dict[str, Any] = msgspec.field(default_factory=dict)


class WebhookIngress(msgspec.Struct, frozen=True):
    """Durable webhook receipt record — idempotent replay support.

    Mirrors ``dhara.schema.WebhookIngress`` field-for-field. ``payload_hash``
    enables idempotent replay without re-processing.
    """

    webhook_id: str
    source: str
    received_at: datetime
    payload_hash: str
    metadata: dict[str, Any] = msgspec.field(default_factory=dict)

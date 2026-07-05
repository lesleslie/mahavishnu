"""CompletionReport Pydantic v2 model (Spec #1: completion-report-schema-v1).

This is the foundational Phase 1 contract for workflow completion outcomes.
Workers publish a ``CompletionReport`` at the end of a workflow; consumers
(Dhara persistence, Akosha analysis, Crackerjack quality gates, Session-Buddy
memory) read from this typed shape instead of parsing ad-hoc dicts.

Scope (per Spec #1 brief, sql_blocked substrate):

- ``CompletionStatus`` StrEnum (success | failure | partial).
- ``ReportArtifact`` (kind, path, optional label).
- ``CompletionReport`` (status, summary, artifacts, started_at,
  completed_at, metadata, auto-generated ``report_id``).
- ``model_json_schema()`` export for downstream validation pipelines.
- Roundtrip serialization via ``model_dump_json`` / ``model_validate_json``.

Notes:

- ``report_id`` auto-generates a UUID4 string when not supplied. Workers
  MAY supply an explicit ID (e.g. for retry idempotency) but should treat
  the field as opaque.
- ``metadata`` is intentionally free-form ``dict[str, Any]`` so workers
  can attach context (workflow_id, worker_id, pool_id, etc.) without a
  schema bump. Downstream consumers should treat unknown keys defensively.
- This module deliberately avoids Dhara or EventBus imports so it stays
  importable in tests and pure worker contexts.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003  (runtime Pydantic field type)
from enum import StrEnum
from pathlib import Path  # noqa: TC003  (runtime Pydantic field type)
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class CompletionStatus(StrEnum):
    """Outcome status for a completed workflow.

    Three values is the architectural contract (Spec #1). Additions
    require a schema bump.
    """

    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"


class ReportArtifact(BaseModel):
    """A single artifact produced or referenced by a workflow run.

    ``kind`` is a free-form label (``"log"``, ``"diff"``, ``"coverage"``,
    ``"screenshot"``, ...) chosen by the producer. ``path`` points to
    the artifact on disk (string or Path; coerced to str on serialize).
    ``label`` is optional human-readable annotation.
    """

    model_config = ConfigDict(extra="forbid")

    kind: str
    path: Path
    label: str | None = None


def _generate_report_id() -> str:
    """Generate a new UUID4 string for a CompletionReport."""
    return str(uuid4())


class CompletionReport(BaseModel):
    """Typed contract for the outcome of a workflow run (Spec #1 v1).

    Required fields (per the architectural contract):

    - ``status``: CompletionStatus (success | failure | partial).
    - ``summary``: human-readable one-paragraph description.
    - ``started_at``: datetime the workflow began.
    - ``completed_at``: datetime the workflow finished.

    Optional fields:

    - ``report_id``: UUID4 string; auto-generated if not supplied.
    - ``artifacts``: list of ReportArtifact (default empty).
    - ``metadata``: free-form dict (default empty).
    """

    model_config = ConfigDict(extra="forbid")

    report_id: str = Field(default_factory=_generate_report_id)
    status: CompletionStatus
    summary: str
    artifacts: list[ReportArtifact] = Field(default_factory=list)
    started_at: datetime
    completed_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "CompletionReport",
    "CompletionStatus",
    "ReportArtifact",
]

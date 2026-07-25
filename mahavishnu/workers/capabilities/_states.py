"""Capability state and report dataclasses."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
class WorkerCapabilityState(str, Enum):
    REGISTERED="REGISTERED"; CONFIGURED="CONFIGURED"; READY="READY"; AVAILABLE="AVAILABLE"
@dataclass
class WorkerCheck:
    kind: str; status: str; safe_reason: str | None=None; duration_ms: float=0.0; cached: bool=False
    checked_at: datetime=field(default_factory=lambda: datetime.now(timezone.utc))
@dataclass
class WorkerCapabilityReport:
    worker_type: str; state: WorkerCapabilityState; checks: list[WorkerCheck]=field(default_factory=list)
    missing_requirements: list[str]=field(default_factory=list); safe_reason: str | None=None
    probe_at: datetime=field(default_factory=lambda: datetime.now(timezone.utc)); cache_ttl_s: int=30

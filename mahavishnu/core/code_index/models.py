"""Pydantic models for code graph indexing and querying."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field, field_validator

if TYPE_CHECKING:
    pass


class CodeGraphNode(BaseModel):
    """A node in the code knowledge graph."""

    symbol_id: str = Field(
        description='Qualified: "{repo_path}|||{file_path}|||{symbol_type}|||{symbol_name}"'
    )
    symbol_name: str = Field(description="Human-readable name for display")
    symbol_type: Literal["function", "class", "module", "file", "variable"]
    file_path: str
    repo_path: str
    start_line: int | None = None
    end_line: int | None = None
    language: str = "python"
    signature: str | None = None
    complexity: int | None = None
    is_deleted: bool = False
    last_indexed_at: datetime
    commit_hash: str


class CodeGraphEdge(BaseModel):
    """An edge in the code knowledge graph."""

    source: str = Field(description="Qualified symbol_id")
    target: str = Field(description="Qualified symbol_id")
    edge_type: Literal["calls", "imports", "inherits", "contains", "implements"]
    source_file: str
    target_file: str
    repo_path: str
    confidence: float = 1.0
    created_at: datetime


class CallChainRequest(BaseModel):
    """Input for call chain resolution."""

    symbol_name: str
    direction: Literal["callers", "callees", "both"] = "both"
    max_depth: int = 5
    repo_path: str | None = None
    edge_filter: list[str] | None = None

    @field_validator("max_depth")
    @classmethod
    def clamp_depth(cls, v: int) -> int:
        if v > 10:
            raise ValueError("max_depth cannot exceed 10")
        return v


class CallChain(BaseModel):
    """A single call chain path."""

    path: list[str] = Field(description="Qualified symbol names in traversal order")
    depth: int
    edge_types: list[str]
    files: list[str]


class CallChainResult(BaseModel):
    """Output of call chain resolution."""

    root_symbol: str
    chains: list[CallChain]
    total_nodes: int
    truncated: bool = False
    stale: bool = False
    last_indexed_at: datetime | None = None


class SymbolImpact(BaseModel):
    """Impact of a single symbol on another."""

    symbol_name: str = Field(description="Qualified symbol ID")
    symbol_type: Literal["function", "class", "module"]
    file_path: str
    depth: int
    dependency_type: Literal["calls", "imports", "inherits", "contains", "implements"]


class ImpactAnalysisRequest(BaseModel):
    """Input for change impact analysis."""

    symbol_name: str
    repo_path: str | None = None
    include_indirect: bool = True
    max_depth: int = 5

    @field_validator("max_depth")
    @classmethod
    def clamp_depth(cls, v: int) -> int:
        if v > 10:
            raise ValueError("max_depth cannot exceed 10")
        return v


class ImpactAnalysisResult(BaseModel):
    """Output of change impact analysis."""

    target: str
    direct_dependents: list[SymbolImpact]
    indirect_dependents: list[SymbolImpact]
    affected_files: list[str]
    risk_level: Literal["low", "medium", "high"]
    blast_radius: int = Field(description="Total transitive reach (all depths)")
    stale: bool = False
    last_indexed_at: datetime | None = None


class IndexWorkItem(BaseModel):
    """Tracks indexing state for a single repo."""

    repo_path: str
    trigger: Literal["git-event", "schedule", "manual"]
    files_changed: list[str]
    status: Literal["queued", "parsing", "upserting", "notifying", "complete", "failed"]
    started_at: datetime | None = None
    completed_at: datetime | None = None
    parse_failures: int = 0


class CodeGraphUnavailable(BaseModel):
    """Structured response when the code graph is unavailable."""

    reason: str
    suggestion: str
    tier: int = 4


class DegradationTier(BaseModel):
    """Current degradation state."""

    tier: Literal[1, 2, 3, 4]
    reason: str
    stale_since: datetime | None = None
    parse_failures: int = 0
    total_files: int = 0

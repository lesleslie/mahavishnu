"""Pattern Models for Mahavishnu.

Defines data models for pattern detection, analysis, and prediction.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class PatternType(str, Enum):
    """Types of detectable patterns."""

    TASK_DURATION = "task_duration"
    BLOCKER_RECURRING = "blocker_recurring"
    COMPLETION_SEQUENCE = "completion_sequence"
    REPOSITORY_WORKFLOW = "repository_workflow"
    ASSIGNMENT_PATTERN = "assignment_pattern"
    TAG_CORRELATION = "tag_correlation"


class PatternSeverity(str, Enum):
    """Pattern severity levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PatternFrequency(str, Enum):
    """How often a pattern occurs."""

    RARE = "rare"  # < 5%
    OCCASIONAL = "occasional"  # 5-20%
    COMMON = "common"  # 20-50%
    FREQUENT = "frequent"  # 50-80%
    VERY_FREQUENT = "very_frequent"  # > 80%


class PatternBase(BaseModel):
    """Base pattern model."""

    pattern_type: PatternType
    description: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    frequency: PatternFrequency = PatternFrequency.OCCASIONAL
    severity: PatternSeverity = PatternSeverity.MEDIUM
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskDurationPattern(PatternBase):
    """Pattern for task duration estimation."""

    pattern_type: PatternType = PatternType.TASK_DURATION

    # Duration statistics (in hours)
    min_duration: float
    max_duration: float
    avg_duration: float
    median_duration: float
    std_deviation: float

    # Factors that influence duration
    repository: str | None = None
    task_type: str | None = None  # bug, feature, enhancement
    priority_range: tuple[str, str] | None = None

    # Sample data
    sample_count: int = 0
    sample_task_ids: list[str] = Field(default_factory=list)


class BlockerPattern(PatternBase):
    """Pattern for recurring blockers."""

    pattern_type: PatternType = PatternType.BLOCKER_RECURRING

    # Blocker identification
    blocker_keyword: str  # Keyword that triggers this blocker
    blocker_category: str  # e.g., "dependency", "resource", "technical"

    # Occurrence data
    occurrence_count: int = 0
    affected_task_ids: list[str] = Field(default_factory=list)
    affected_repositories: list[str] = Field(default_factory=list)

    # Resolution suggestions
    resolution_suggestions: list[str] = Field(default_factory=list)
    avg_resolution_time_hours: float | None = None


class CompletionSequencePattern(PatternBase):
    """Pattern for task completion sequences."""

    pattern_type: PatternType = PatternType.COMPLETION_SEQUENCE

    # Sequence data
    sequence: list[str]  # Ordered list of task type transitions
    sequence_count: int = 0  # How often this sequence occurs

    # Context
    repository: str | None = None

    # Predictive value
    leads_to_completion: bool = True
    completion_probability: float = Field(ge=0.0, le=1.0)


class DetectedPattern(BaseModel):
    """A pattern detected in task data."""

    id: str = Field(default_factory=lambda: str(uuid4())[:8])
    pattern_type: PatternType
    pattern_data: PatternBase

    # Detection metadata
    detected_at: datetime = Field(default_factory=datetime.utcnow)
    source_task_ids: list[str] = Field(default_factory=list)
    confidence_score: float = Field(ge=0.0, le=1.0)

    # Embedding for similarity search
    embedding: list[float] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "id": self.id,
            "pattern_type": self.pattern_type.value,
            "pattern_data": self.pattern_data.model_dump(),
            "detected_at": self.detected_at.isoformat(),
            "source_task_ids": self.source_task_ids,
            "confidence_score": self.confidence_score,
        }


class PatternMatch(BaseModel):
    """A match between a task and a pattern."""

    pattern_id: str
    pattern_type: PatternType
    match_score: float = Field(ge=0.0, le=1.0)
    matched_at: datetime = Field(default_factory=datetime.utcnow)

    # What was matched
    matched_keywords: list[str] = Field(default_factory=list)
    matched_features: dict[str, Any] = Field(default_factory=dict)

    # Predictions based on this match
    predictions: dict[str, Any] = Field(default_factory=dict)


class PatternAnalysisResult(BaseModel):
    """Result of pattern analysis on a set of tasks."""

    analyzed_at: datetime = Field(default_factory=datetime.utcnow)
    task_count: int = 0

    # Detected patterns
    duration_patterns: list[TaskDurationPattern] = Field(default_factory=list)
    blocker_patterns: list[BlockerPattern] = Field(default_factory=list)
    sequence_patterns: list[CompletionSequencePattern] = Field(default_factory=list)

    # Statistics
    avg_task_duration_hours: float = 0.0
    blocker_rate: float = 0.0
    completion_rate: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "analyzed_at": self.analyzed_at.isoformat(),
            "task_count": self.task_count,
            "duration_patterns": [p.model_dump() for p in self.duration_patterns],
            "blocker_patterns": [p.model_dump() for p in self.blocker_patterns],
            "sequence_patterns": [p.model_dump() for p in self.sequence_patterns],
            "statistics": {
                "avg_task_duration_hours": self.avg_task_duration_hours,
                "blocker_rate": self.blocker_rate,
                "completion_rate": self.completion_rate,
            },
        }

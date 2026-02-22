"""Adaptive RAG routing with query complexity detection.

This module implements intelligent query routing to select the optimal RAG
strategy based on query complexity, context, and available resources.

Architecture:
    ┌─────────────────────────────────────────────────────────────┐
    │                  AdaptiveRAGRouter                          │
    ├─────────────────────────────────────────────────────────────┤
    │  Query Complexity Analysis                                  │
    │  - Length, structure, domain terminology                   │
    │  - Multi-hop reasoning requirements                        │
    │  - Temporal/spatial constraints                            │
    ├─────────────────────────────────────────────────────────────┤
    │  Strategy Selection                                         │
    │  - Naive RAG (score < 0.3): Simple lookup                  │
    │  - Hybrid RAG (0.3-0.6): Vector + cache                    │
    │  - Graph RAG (0.6-0.8): Knowledge graph traversal          │
    │  - Agentic RAG (score > 0.8): Multi-agent collaboration    │
    └─────────────────────────────────────────────────────────────┘

Usage:
    from mahavishnu.core.adaptive_rag import AdaptiveRAGRouter

    router = AdaptiveRAGRouter()
    strategy = await router.route_query("Explain the authentication flow")
    results = await strategy.retrieve(query, context)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mahavishnu.core.embedding_cache import EmbeddingCache

logger = logging.getLogger(__name__)


class RAGStrategyType(Enum):
    """Available RAG strategy types."""

    NAIVE = "naive"  # Simple vector lookup
    HYBRID = "hybrid"  # Vector + cache + full-text
    GRAPH = "graph"  # Knowledge graph traversal
    AGENTIC = "agentic"  # Multi-agent collaboration


@dataclass
class ComplexityScore:
    """Query complexity analysis result.

    Attributes:
        score: Overall complexity score (0.0-1.0)
        length_factor: Contribution from query length
        structure_factor: Contribution from query structure (clauses, conjunctions)
        domain_factor: Contribution from domain-specific terminology
        reasoning_factor: Contribution from multi-hop reasoning indicators
        temporal_factor: Contribution from temporal/spatial constraints
    """

    score: float
    length_factor: float = 0.0
    structure_factor: float = 0.0
    domain_factor: float = 0.0
    reasoning_factor: float = 0.0
    temporal_factor: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "score": self.score,
            "length_factor": self.length_factor,
            "structure_factor": self.structure_factor,
            "domain_factor": self.domain_factor,
            "reasoning_factor": self.reasoning_factor,
            "temporal_factor": self.temporal_factor,
        }


@dataclass
class QueryAnalysis:
    """Complete query analysis result.

    Attributes:
        query: Original query text
        complexity: Complexity score breakdown
        detected_entities: Named entities found in query
        detected_intents: Query intents (explain, compare, how-to, etc.)
        suggested_strategy: Recommended RAG strategy
        routing_reason: Explanation for strategy selection
    """

    query: str
    complexity: ComplexityScore
    detected_entities: list[str] = field(default_factory=list)
    detected_intents: list[str] = field(default_factory=list)
    suggested_strategy: RAGStrategyType = RAGStrategyType.NAIVE
    routing_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "query": self.query,
            "complexity": self.complexity.to_dict(),
            "detected_entities": self.detected_entities,
            "detected_intents": self.detected_intents,
            "suggested_strategy": self.suggested_strategy.value,
            "routing_reason": self.routing_reason,
        }


class QueryComplexityAnalyzer:
    """Analyzes query complexity for adaptive routing.

    Uses multiple heuristics to determine query complexity:
    1. Length analysis - Longer queries tend to be more complex
    2. Structure analysis - Clauses, conjunctions, parentheses
    3. Domain terminology - Technical terms indicate complexity
    4. Reasoning indicators - "why", "how", "compare" suggest multi-hop
    5. Temporal/spatial - Time and location references
    """

    # Domain-specific terminology patterns
    DOMAIN_PATTERNS = [
        r"\b(api|rest|graphql|grpc|websocket|http)\b",
        r"\b(database|sql|nosql|postgres|mongodb|redis)\b",
        r"\b(authentication|authorization|jwt|oauth|token)\b",
        r"\b(kubernetes|docker|container|pod|deployment)\b",
        r"\b(machine learning|model|embedding|vector|rag)\b",
        r"\b(microservice|monolith|architecture|pattern)\b",
        r"\b(testing|unit test|integration|e2e|coverage)\b",
        r"\b(ci|cd|pipeline|deployment|release)\b",
    ]

    # Multi-hop reasoning indicators
    REASONING_PATTERNS = [
        r"\b(why|how|explain|describe|analyze)\b",
        r"\b(compare|contrast|difference|versus|vs)\b",
        r"\b(relationship|connection|impact|affect)\b",
        r"\b(cause|effect|consequence|result)\b",
        r"\b(because|therefore|thus|hence|since)\b",
    ]

    # Temporal/spatial patterns
    TEMPORAL_PATTERNS = [
        r"\b(when|while|during|before|after)\b",
        r"\b(today|yesterday|tomorrow|last week|next month)\b",
        r"\b(where|location|region|area|place)\b",
        r"\b(history|historical|timeline|chronological)\b",
    ]

    # Intent patterns
    INTENT_PATTERNS = {
        "explain": [r"\b(explain|describe|what is|tell me about)\b"],
        "how_to": [r"\b(how (to|do|can)|steps|guide|tutorial)\b"],
        "compare": [r"\b(compare|difference|versus|vs|contrast)\b"],
        "troubleshoot": [r"\b(error|bug|issue|problem|fix|debug)\b"],
        "code": [r"\b(code|implement|function|class|method)\b"],
        "architecture": [r"\b(architecture|design|structure|pattern)\b"],
    }

    # Structure complexity patterns
    STRUCTURE_PATTERNS = [
        r"\band\b",
        r"\bor\b",
        r"\bbut\b",
        r"\bhowever\b",
        r"\balthough\b",
        r"\(",
        r"\)",
        r";",
        r":",
    ]

    def __init__(
        self,
        domain_patterns: list[str] | None = None,
        reasoning_patterns: list[str] | None = None,
    ) -> None:
        """Initialize the analyzer.

        Args:
            domain_patterns: Additional domain patterns to recognize
            reasoning_patterns: Additional reasoning patterns to recognize
        """
        self.domain_patterns = list(self.DOMAIN_PATTERNS)
        if domain_patterns:
            self.domain_patterns.extend(domain_patterns)

        self.reasoning_patterns = list(self.REASONING_PATTERNS)
        if reasoning_patterns:
            self.reasoning_patterns.extend(reasoning_patterns)

        # Compile patterns for efficiency
        self._domain_regex = [re.compile(p, re.IGNORECASE) for p in self.domain_patterns]
        self._reasoning_regex = [
            re.compile(p, re.IGNORECASE) for p in self.reasoning_patterns
        ]
        self._temporal_regex = [
            re.compile(p, re.IGNORECASE) for p in self.TEMPORAL_PATTERNS
        ]
        self._structure_regex = [
            re.compile(p, re.IGNORECASE) for p in self.STRUCTURE_PATTERNS
        ]

    def analyze(self, query: str) -> ComplexityScore:
        """Analyze query complexity.

        Args:
            query: Query text to analyze

        Returns:
            ComplexityScore with detailed breakdown
        """
        # Normalize query
        normalized = query.lower().strip()
        words = normalized.split()
        word_count = len(words)

        # 1. Length factor (0.0-1.0)
        # Short (< 5 words) = 0.1, Long (> 30 words) = 1.0
        length_factor = min(1.0, max(0.1, (word_count - 5) / 25 + 0.1))

        # 2. Structure factor (0.0-1.0)
        # Count structural complexity indicators
        structure_count = 0
        for pattern in self._structure_regex:
            structure_count += len(pattern.findall(normalized))
        structure_factor = min(1.0, structure_count / 5)

        # 3. Domain factor (0.0-1.0)
        # Count domain-specific terminology
        domain_count = 0
        for pattern in self._domain_regex:
            domain_count += len(pattern.findall(normalized))
        domain_factor = min(1.0, domain_count / 3)

        # 4. Reasoning factor (0.0-1.0)
        # Count multi-hop reasoning indicators
        reasoning_count = 0
        for pattern in self._reasoning_regex:
            reasoning_count += len(pattern.findall(normalized))
        reasoning_factor = min(1.0, reasoning_count / 2)

        # 5. Temporal factor (0.0-1.0)
        # Count temporal/spatial constraints
        temporal_count = 0
        for pattern in self._temporal_regex:
            temporal_count += len(pattern.findall(normalized))
        temporal_factor = min(1.0, temporal_count / 2)

        # Calculate weighted overall score
        # Weights prioritize reasoning and domain complexity
        score = (
            length_factor * 0.15
            + structure_factor * 0.20
            + domain_factor * 0.25
            + reasoning_factor * 0.30
            + temporal_factor * 0.10
        )

        return ComplexityScore(
            score=round(score, 3),
            length_factor=round(length_factor, 3),
            structure_factor=round(structure_factor, 3),
            domain_factor=round(domain_factor, 3),
            reasoning_factor=round(reasoning_factor, 3),
            temporal_factor=round(temporal_factor, 3),
        )

    def detect_intents(self, query: str) -> list[str]:
        """Detect query intents.

        Args:
            query: Query text to analyze

        Returns:
            List of detected intents
        """
        normalized = query.lower()
        intents = []

        for intent, patterns in self.INTENT_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, normalized):
                    intents.append(intent)
                    break

        return intents

    def detect_entities(self, query: str) -> list[str]:
        """Extract potential named entities.

        Simple heuristic-based entity extraction for common patterns.

        Args:
            query: Query text to analyze

        Returns:
            List of potential entities
        """
        entities = []

        # Capitalized words (potential proper nouns)
        capitalized = re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b", query)
        entities.extend(capitalized)

        # Quoted strings
        quoted = re.findall(r'["\']([^"\']+)["\']', query)
        entities.extend(quoted)

        # Code-like patterns
        code_patterns = re.findall(r"`([^`]+)`", query)
        entities.extend(code_patterns)

        # File paths
        paths = re.findall(r"\b[/\w]+\.\w+\b", query)
        entities.extend(paths)

        return list(set(entities))


class AdaptiveRAGRouter:
    """Routes queries to appropriate RAG strategy based on complexity.

    Implements the adaptive RAG pattern from the architecture plan:
    - Naive RAG (score < 0.3): Simple vector lookup
    - Hybrid RAG (0.3-0.6): Vector + cache + full-text
    - Graph RAG (0.6-0.8): Knowledge graph traversal
    - Agentic RAG (score > 0.8): Multi-agent collaboration

    Example:
        >>> router = AdaptiveRAGRouter()
        >>> analysis = await router.analyze_query("How does auth work?")
        >>> print(analysis.suggested_strategy)
        RAGStrategyType.HYBRID
    """

    # Strategy thresholds
    NAIVE_THRESHOLD = 0.3
    HYBRID_THRESHOLD = 0.6
    GRAPH_THRESHOLD = 0.8

    def __init__(
        self,
        analyzer: QueryComplexityAnalyzer | None = None,
        embedding_cache: EmbeddingCache | None = None,
    ) -> None:
        """Initialize the router.

        Args:
            analyzer: Query complexity analyzer (creates default if None)
            embedding_cache: Embedding cache for hybrid strategies
        """
        self._analyzer = analyzer or QueryComplexityAnalyzer()
        self._embedding_cache = embedding_cache

        # Strategy statistics
        self._strategy_counts: dict[RAGStrategyType, int] = {
            strategy: 0 for strategy in RAGStrategyType
        }

    def select_strategy(self, complexity: ComplexityScore) -> tuple[RAGStrategyType, str]:
        """Select RAG strategy based on complexity score.

        Args:
            complexity: Query complexity analysis

        Returns:
            Tuple of (strategy type, routing reason)
        """
        score = complexity.score

        if score < self.NAIVE_THRESHOLD:
            strategy = RAGStrategyType.NAIVE
            reason = (
                f"Low complexity ({score:.2f} < {self.NAIVE_THRESHOLD}): "
                "Simple vector lookup sufficient"
            )
        elif score < self.HYBRID_THRESHOLD:
            strategy = RAGStrategyType.HYBRID
            reason = (
                f"Medium complexity ({score:.2f}): "
                "Hybrid vector + cache + full-text search"
            )
        elif score < self.GRAPH_THRESHOLD:
            strategy = RAGStrategyType.GRAPH
            reason = (
                f"High complexity ({score:.2f}): "
                "Knowledge graph traversal for multi-hop reasoning"
            )
        else:
            strategy = RAGStrategyType.AGENTIC
            reason = (
                f"Very high complexity ({score:.2f} >= {self.GRAPH_THRESHOLD}): "
                "Multi-agent collaboration required"
            )

        # Update statistics
        self._strategy_counts[strategy] += 1

        return strategy, reason

    async def analyze_query(self, query: str) -> QueryAnalysis:
        """Analyze query and determine routing.

        Args:
            query: Query text to analyze

        Returns:
            QueryAnalysis with complexity, intents, and suggested strategy
        """
        # Analyze complexity
        complexity = self._analyzer.analyze(query)

        # Detect intents
        intents = self._analyzer.detect_intents(query)

        # Detect entities
        entities = self._analyzer.detect_entities(query)

        # Select strategy
        strategy, reason = self.select_strategy(complexity)

        return QueryAnalysis(
            query=query,
            complexity=complexity,
            detected_entities=entities,
            detected_intents=intents,
            suggested_strategy=strategy,
            routing_reason=reason,
        )

    async def route_query(self, query: str) -> RAGStrategyType:
        """Route query to appropriate strategy.

        Args:
            query: Query text to route

        Returns:
            Selected RAG strategy type
        """
        analysis = await self.analyze_query(query)
        logger.info(
            "adaptive_rag_routing",
            extra={
                "query_length": len(query),
                "complexity_score": analysis.complexity.score,
                "strategy": analysis.suggested_strategy.value,
                "intents": analysis.detected_intents,
            },
        )
        return analysis.suggested_strategy

    def get_strategy_stats(self) -> dict[str, Any]:
        """Get routing statistics.

        Returns:
            Dictionary with strategy usage counts and percentages
        """
        total = sum(self._strategy_counts.values())
        stats = {
            "total_queries": total,
            "strategy_counts": {
                s.value: c for s, c in self._strategy_counts.items()
            },
        }

        if total > 0:
            stats["strategy_percentages"] = {
                s.value: round(c / total * 100, 1)
                for s, c in self._strategy_counts.items()
            }

        return stats


def create_adaptive_router(
    embedding_cache: EmbeddingCache | None = None,
    domain_patterns: list[str] | None = None,
) -> AdaptiveRAGRouter:
    """Create an adaptive RAG router with custom configuration.

    Args:
        embedding_cache: Embedding cache for hybrid strategies
        domain_patterns: Additional domain patterns to recognize

    Returns:
        Configured AdaptiveRAGRouter instance
    """
    analyzer = QueryComplexityAnalyzer(domain_patterns=domain_patterns)
    return AdaptiveRAGRouter(analyzer=analyzer, embedding_cache=embedding_cache)


__all__ = [
    "AdaptiveRAGRouter",
    "ComplexityScore",
    "QueryAnalysis",
    "QueryComplexityAnalyzer",
    "RAGStrategyType",
    "create_adaptive_router",
]

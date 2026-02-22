"""Unit tests for adaptive RAG routing."""

from __future__ import annotations

import pytest

from mahavishnu.core.adaptive_rag import (
    AdaptiveRAGRouter,
    ComplexityScore,
    QueryAnalysis,
    QueryComplexityAnalyzer,
    RAGStrategyType,
    create_adaptive_router,
)


class TestComplexityScore:
    """Tests for ComplexityScore."""

    def test_default_values(self) -> None:
        """Test default complexity score values."""
        score = ComplexityScore(score=0.5)
        assert score.score == 0.5
        assert score.length_factor == 0.0
        assert score.structure_factor == 0.0

    def test_to_dict(self) -> None:
        """Test dictionary conversion."""
        score = ComplexityScore(
            score=0.7,
            length_factor=0.3,
            structure_factor=0.4,
        )
        d = score.to_dict()
        assert d["score"] == 0.7
        assert d["length_factor"] == 0.3


class TestQueryComplexityAnalyzer:
    """Tests for QueryComplexityAnalyzer."""

    def test_simple_query_low_complexity(self) -> None:
        """Test that simple queries have low complexity."""
        analyzer = QueryComplexityAnalyzer()
        score = analyzer.analyze("hello world")
        assert score.score < 0.3

    def test_complex_query_high_complexity(self) -> None:
        """Test that complex queries have higher complexity."""
        analyzer = QueryComplexityAnalyzer()
        complex_query = (
            "Explain how the authentication system works in this microservices "
            "architecture and compare it with the previous monolithic design"
        )
        score = analyzer.analyze(complex_query)
        assert score.score > 0.4

    def test_domain_terminology_detected(self) -> None:
        """Test that domain terminology increases complexity."""
        analyzer = QueryComplexityAnalyzer()
        simple = analyzer.analyze("how does it work")
        technical = analyzer.analyze("how does the kubernetes api authentication work")

        assert technical.domain_factor > simple.domain_factor

    def test_reasoning_indicators_detected(self) -> None:
        """Test that reasoning indicators increase complexity."""
        analyzer = QueryComplexityAnalyzer()
        simple = analyzer.analyze("show me the code")
        reasoning = analyzer.analyze("explain why this error happens")

        assert reasoning.reasoning_factor > simple.reasoning_factor

    def test_intent_detection(self) -> None:
        """Test intent detection."""
        analyzer = QueryComplexityAnalyzer()

        intents = analyzer.detect_intents("explain how authentication works")
        assert "explain" in intents

        intents = analyzer.detect_intents("how to fix this bug")
        assert "how_to" in intents

        intents = analyzer.detect_intents("compare postgres vs mysql")
        assert "compare" in intents

    def test_entity_detection(self) -> None:
        """Test entity detection."""
        analyzer = QueryComplexityAnalyzer()

        entities = analyzer.detect_entities('What is the "FastAPI" framework?')
        assert "FastAPI" in entities

        entities = analyzer.detect_entities("Show me the file /src/main.py")
        # Path regex captures without leading slash
        assert "src/main.py" in entities


class TestAdaptiveRAGRouter:
    """Tests for AdaptiveRAGRouter."""

    def test_simple_query_routes_to_naive(self) -> None:
        """Test that simple queries route to NAIVE strategy."""
        router = AdaptiveRAGRouter()
        strategy, reason = router.select_strategy(ComplexityScore(score=0.1))

        assert strategy == RAGStrategyType.NAIVE
        assert "Low complexity" in reason

    def test_medium_query_routes_to_hybrid(self) -> None:
        """Test that medium complexity queries route to HYBRID."""
        router = AdaptiveRAGRouter()
        strategy, reason = router.select_strategy(ComplexityScore(score=0.45))

        assert strategy == RAGStrategyType.HYBRID
        assert "Medium complexity" in reason

    def test_high_query_routes_to_graph(self) -> None:
        """Test that high complexity queries route to GRAPH."""
        router = AdaptiveRAGRouter()
        strategy, reason = router.select_strategy(ComplexityScore(score=0.7))

        assert strategy == RAGStrategyType.GRAPH
        assert "High complexity" in reason

    def test_very_high_query_routes_to_agentic(self) -> None:
        """Test that very high complexity queries route to AGENTIC."""
        router = AdaptiveRAGRouter()
        strategy, reason = router.select_strategy(ComplexityScore(score=0.9))

        assert strategy == RAGStrategyType.AGENTIC
        assert "Very high complexity" in reason

    @pytest.mark.asyncio
    async def test_analyze_query(self) -> None:
        """Test full query analysis."""
        router = AdaptiveRAGRouter()
        analysis = await router.analyze_query("How does authentication work?")

        assert analysis.query == "How does authentication work?"
        assert analysis.complexity.score >= 0
        assert isinstance(analysis.suggested_strategy, RAGStrategyType)

    @pytest.mark.asyncio
    async def test_route_query(self) -> None:
        """Test query routing."""
        router = AdaptiveRAGRouter()
        strategy = await router.route_query("hello")

        assert isinstance(strategy, RAGStrategyType)

    def test_strategy_stats(self) -> None:
        """Test strategy statistics tracking."""
        router = AdaptiveRAGRouter()

        # Route some queries
        router.select_strategy(ComplexityScore(score=0.1))
        router.select_strategy(ComplexityScore(score=0.5))
        router.select_strategy(ComplexityScore(score=0.1))

        stats = router.get_strategy_stats()
        assert stats["total_queries"] == 3
        assert stats["strategy_counts"]["naive"] == 2
        assert stats["strategy_counts"]["hybrid"] == 1


class TestCreateAdaptiveRouter:
    """Tests for factory function."""

    def test_creates_router(self) -> None:
        """Test that factory creates a router."""
        router = create_adaptive_router()
        assert isinstance(router, AdaptiveRAGRouter)

    def test_custom_domain_patterns(self) -> None:
        """Test that custom domain patterns are accepted."""
        router = create_adaptive_router(
            domain_patterns=[r"\b(custom_term)\b"]
        )
        assert isinstance(router, AdaptiveRAGRouter)

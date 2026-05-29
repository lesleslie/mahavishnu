"""Tests for mahavishnu.testing.__init__ module."""

from __future__ import annotations

from mahavishnu.testing import (
    LoadTestConfig,
    LoadTestMetrics,
    LoadTestPhase,
    LoadTestRunner,
    MockTaskClient,
    RequestResult,
)


class TestExports:
    """Test that all expected exports are available."""

    def test_loadtestconfig_exported(self):
        """Test LoadTestConfig is exported."""
        assert LoadTestConfig is not None
        # Check it's the correct class by creating an instance
        config = LoadTestConfig()
        assert config.concurrent_users == 50

    def test_loadtestmetrics_exported(self):
        """Test LoadTestMetrics is exported."""
        assert LoadTestMetrics is not None
        metrics = LoadTestMetrics(operation="test_op")
        assert metrics.operation == "test_op"

    def test_loadtestphase_exported(self):
        """Test LoadTestPhase is exported."""
        assert LoadTestPhase is not None
        assert LoadTestPhase.WARMUP.value == "warmup"
        assert LoadTestPhase.STEADY_STATE.value == "steady_state"

    def test_loadtestrunner_exported(self):
        """Test LoadTestRunner is exported."""
        assert LoadTestRunner is not None

    def test_mocktaskclient_exported(self):
        """Test MockTaskClient is exported."""
        assert MockTaskClient is not None

    def test_requestresult_exported(self):
        """Test RequestResult is exported."""
        assert RequestResult is not None
        result = RequestResult(
            timestamp=1000.0,
            operation="test",
            latency_ms=10.0,
            success=True,
        )
        assert result.operation == "test"


class TestAllIsCorrect:
    """Test __all__ is correctly defined."""

    def test_all_contains_expected_items(self):
        """Test __all__ contains all expected items."""
        from mahavishnu.testing import __all__

        expected = [
            "LoadTestConfig",
            "LoadTestMetrics",
            "LoadTestRunner",
            "LoadTestPhase",
            "MockTaskClient",
            "RequestResult",
        ]
        for item in expected:
            assert item in __all__, f"{item} should be in __all__"

    def test_all_count(self):
        """Test __all__ has exactly 6 items."""
        from mahavishnu.testing import __all__

        assert len(__all__) == 6

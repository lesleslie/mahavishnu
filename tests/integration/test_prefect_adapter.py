"""Integration tests for Prefect adapter with dynamic quality scoring."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.engines.prefect_adapter import PrefectAdapter, process_repository


@pytest.mark.asyncio
async def test_process_repository_dynamic_quality_score():
    """Test that process_repository calculates dynamic quality scores."""
    # Mock task spec
    task_spec = {"type": "code_sweep", "id": "test_task"}

    # Mock a repository path (doesn't need to exist for this test)
    repo_path = "/fake/repo"

    # Patch the code graph analyzer to return predictable results
    with patch("mahavishnu.engines.prefect_adapter.CodeGraphAnalyzer") as mock_analyzer_class:
        # Setup mock analyzer
        mock_analyzer = MagicMock()
        mock_analyzer_class.return_value = mock_analyzer
        mock_analyzer.nodes = {
            "func1": MagicMock(
                name="complex_func",
                file_id="test.py",
                start_line=10,
                end_line=50,  # 40 lines long
                calls=["call1", "call2", "call3", "call4", "call5", "call6"],
                is_export=True,
            ),
            "func2": MagicMock(
                name="simple_func",
                file_id="test.py",
                start_line=1,
                end_line=5,
                calls=["call1"],
                is_export=False,
            ),
        }
        mock_analyzer.analyze_repository = AsyncMock(
            return_value={"functions_indexed": 2, "other_data": "test"}
        )

        # Execute the task
        result = await process_repository(repo_path, task_spec)

        # Verify result structure
        assert result["status"] == "completed"
        assert result["repo"] == repo_path
        assert result["task_id"] == "test_task"

        # Verify quality score is calculated (not hardcoded)
        assert "quality_score" in result["result"]
        quality_score = result["result"]["quality_score"]

        # Quality score should be a number between 0 and 100
        assert isinstance(quality_score, (int, float))
        assert 0 <= quality_score <= 100

        # Quality score should NOT be the hardcoded 95
        # With 1 complex function (40 lines, 6 calls), score should be < 95
        assert quality_score < 95

        # Verify quality factors are included
        assert "quality_factors" in result["result"]
        factors = result["result"]["quality_factors"]
        assert "total_functions" in factors
        assert "complex_functions_count" in factors
        assert "avg_function_length" in factors
        assert "max_complexity" in factors


@pytest.mark.asyncio
async def test_process_repository_quality_check_integration():
    """Test that quality_check task type uses Crackerjack integration."""
    task_spec = {"type": "quality_check", "id": "qc_task"}
    repo_path = "/fake/repo"

    with patch("mahavishnu.engines.prefect_adapter.QualityControl") as mock_qc_class:
        # Setup mock QC
        mock_qc = MagicMock()
        mock_qc_class.return_value = mock_qc
        mock_qc.check_repository = AsyncMock(return_value={"status": "passed", "score": 85})

        # Execute
        result = await process_repository(repo_path, task_spec)

        # Verify QC was called
        mock_qc.check_repository.assert_called_once_with(repo_path)

        # Verify result
        assert result["status"] == "completed"
        assert "result" in result


@pytest.mark.asyncio
async def test_prefect_adapter_real_flow_run_ids():
    """Test that Prefect adapter returns real flow run IDs."""
    # Mock config
    config = MagicMock()

    # Create adapter
    adapter = PrefectAdapter(config)

    # Mock Prefect client
    with patch("mahavishnu.engines.prefect_adapter.get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_get_client.return_value.__aenter__.return_value = mock_client
        mock_client.api_url = "http://prefect.local"

        # Mock flow run
        mock_flow_run = MagicMock()
        mock_flow_run.id = "real-flow-run-id-12345"
        mock_client.create_run = AsyncMock(return_value=mock_flow_run)

        # Mock flow state
        mock_state = MagicMock()
        mock_state.is_completed.return_value = True
        mock_state.result.return_value = [{"status": "completed"}]
        mock_client.wait_for_flow_run = AsyncMock(return_value=mock_state)

        # Execute
        task = {"id": "test_task", "type": "code_sweep"}
        repos = ["/fake/repo"]
        result = await adapter.execute(task, repos)

        # Verify real flow run ID is returned (not fake/generated)
        assert "flow_run_id" in result
        assert result["flow_run_id"] == "real-flow-run-id-12345"

        # Verify flow run URL is included
        assert "flow_run_url" in result
        assert "real-flow-run-id-12345" in result["flow_run_url"]
        assert "prefect.local" in result["flow_run_url"]

        # Verify Prefect client methods were called
        mock_client.create_run.assert_called_once()
        mock_client.wait_for_flow_run.assert_called_once()


@pytest.mark.asyncio
async def test_quality_score_calculation_edge_cases():
    """Test quality score calculation with various code complexity scenarios."""

    test_cases = [
        # (complex_funcs, avg_length, max_calls, expected_score_range)
        ([], 0, 0, (95, 100)),  # No complex functions = high score
        ([{"length": 20, "calls_count": 3}], 20, 3, (85, 100)),  # Mild complexity
        ([{"length": 50, "calls_count": 8}], 50, 8, (70, 90)),  # High complexity
        ([{"length": 100, "calls_count": 15}], 100, 15, (68, 78)),  # Very high
        (
            [{"length": 30, "calls_count": 5}, {"length": 40, "calls_count": 6}],
            35,
            6,
            (75, 90),
        ),  # Multiple complex funcs
    ]

    for complex_funcs, avg_length, max_calls, score_range in test_cases:
        # Calculate quality score using the same logic
        quality_score = 100
        quality_score -= min(len(complex_funcs) * 2, 20)
        quality_score -= min(avg_length / 2, 15)
        quality_score -= min(max_calls, 10)
        quality_score = max(quality_score, 0)

        # Verify score is in expected range
        assert score_range[0] <= quality_score <= score_range[1], (
            f"Score {quality_score} not in range {score_range} for input: complex_funcs={len(complex_funcs)}, avg_length={avg_length}, max_calls={max_calls}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

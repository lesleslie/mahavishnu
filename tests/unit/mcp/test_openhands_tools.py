from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError
import pytest


@pytest.mark.unit
def test_openhands_run_input_rejects_empty_prompt() -> None:
    from mahavishnu.mcp.tools.openhands_tools import OpenHandsRunInput

    with pytest.raises(ValidationError):
        OpenHandsRunInput(prompt="", timeout=60, run_quality_check=False)


@pytest.mark.unit
def test_openhands_run_input_rejects_oversized_prompt() -> None:
    from mahavishnu.mcp.tools.openhands_tools import OpenHandsRunInput

    with pytest.raises(ValidationError):
        OpenHandsRunInput(
            prompt="x" * 10_001,
            timeout=60,
            run_quality_check=False,
        )


@pytest.mark.unit
def test_openhands_run_input_rejects_timeout_out_of_range() -> None:
    from mahavishnu.mcp.tools.openhands_tools import OpenHandsRunInput

    with pytest.raises(ValidationError):
        OpenHandsRunInput(prompt="valid", timeout=10, run_quality_check=False)


@pytest.mark.unit
async def test_openhands_run_returns_quality_score_none_path(tmp_path: Path) -> None:
    """When Crackerjack returns quality_score=None, result must still succeed."""
    from mahavishnu.mcp.tools.openhands_tools import OpenHandsRunInput, run_openhands_task

    inp = OpenHandsRunInput(prompt="Write tests", timeout=60, run_quality_check=True)
    mock_worker_result = MagicMock()
    mock_worker_result.status.value = "completed"
    mock_worker_result.output = "all tests pass"

    with (
        patch(
            "mahavishnu.mcp.tools.openhands_tools.OpenHandsWorker.execute",
            new_callable=AsyncMock,
            return_value=mock_worker_result,
        ),
        patch(
            "mahavishnu.mcp.tools.openhands_tools._run_quality_check",
            new_callable=AsyncMock,
            return_value=None,  # quality_score=None
        ),
    ):
        result = await run_openhands_task(inp)

    assert result["status"] == "completed"
    assert result.get("quality_score") is None


@pytest.mark.unit
def test_openhands_settings_rejects_workspace_dir_outside_root() -> None:
    from pydantic import ValidationError

    from mahavishnu.core.config import OpenHandsSettings

    with pytest.raises(ValidationError):
        OpenHandsSettings(
            workspace_root="/tmp/safe",
            workspace_dir="/etc/passwd",  # outside root
        )

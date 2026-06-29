"""Unit tests for mahavishnu.core.opensearch_constants."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from mahavishnu.core import opensearch_constants


def test_opensearch_available_constant_exists() -> None:
    """OPENSEARCH_AVAILABLE is importable and is a bool."""
    assert hasattr(opensearch_constants, "OPENSEARCH_AVAILABLE")
    assert isinstance(opensearch_constants.OPENSEARCH_AVAILABLE, bool)


def test_opensearch_available_matches_opensearchpy_install_state() -> None:
    """Constant reflects whether opensearchpy is actually importable."""
    opensearchpy_installed = importlib.util.find_spec("opensearchpy") is not None
    assert opensearch_constants.OPENSEARCH_AVAILABLE is opensearchpy_installed


def test_no_duplicate_flag_declarations() -> None:
    """Neither caller module may redeclare OPENSEARCH_AVAILABLE = True/False."""
    repo_root = Path(__file__).resolve().parents[3]
    caller_files = [
        repo_root / "mahavishnu" / "core" / "opensearch_integration.py",
        repo_root / "mahavishnu" / "core" / "dead_letter_queue.py",
    ]
    for source_path in caller_files:
        text = source_path.read_text()
        rel = source_path.relative_to(repo_root)
        assert "OPENSEARCH_AVAILABLE = True" not in text, (
            f"{rel} still declares OPENSEARCH_AVAILABLE = True; "
            "the flag must live in mahavishnu/core/opensearch_constants.py only."
        )
        assert "OPENSEARCH_AVAILABLE = False" not in text, (
            f"{rel} still declares OPENSEARCH_AVAILABLE = False; "
            "the flag must live in mahavishnu/core/opensearch_constants.py only."
        )

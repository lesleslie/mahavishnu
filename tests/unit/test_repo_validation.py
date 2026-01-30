"""Unit tests for repository validation."""

import os
import tempfile

import pytest

from mahavishnu.core.app import _validate_path


def test_validate_path_normal():
    """Test that normal paths are validated correctly."""
    # Create a temporary directory for testing
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_path = os.path.join(tmp_dir, "valid_dir")
        os.makedirs(test_path, exist_ok=True)

        validated_path = _validate_path(test_path)
        assert str(validated_path) == test_path


def test_validate_path_with_relative():
    """Test that relative paths are handled correctly."""
    # Create a temporary directory for testing
    with tempfile.TemporaryDirectory() as tmp_dir:
        original_cwd = os.getcwd()
        os.chdir(tmp_dir)

        try:
            # Create a subdirectory
            subdir = os.path.join(tmp_dir, "subdir")
            os.makedirs(subdir, exist_ok=True)

            # Test relative path
            rel_path = "subdir"
            validated_path = _validate_path(rel_path)
            expected_path = os.path.join(tmp_dir, rel_path)
            assert str(validated_path) == expected_path
        finally:
            os.chdir(original_cwd)


def test_validate_path_with_dotdot():
    """Test that paths with '..' are rejected."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Create a nested directory structure
        parent_dir = tmp_dir
        child_dir = os.path.join(parent_dir, "child")
        os.makedirs(child_dir, exist_ok=True)

        # Try to access parent directory using '..'
        malicious_path = os.path.join(child_dir, "..", "..")

        with pytest.raises(Exception) as exc_info:
            _validate_path(malicious_path)

        assert "directory traversal" in str(exc_info.value)


def test_validate_path_with_encoded_dotdot():
    """Test that paths with encoded '..' are rejected."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Test various ways '..' might be encoded
        malicious_paths = [
            "../",
            "subdir/../..",
            "subdir/../../",
            "subdir/..\\..",  # Windows-style
        ]

        for malicious_path in malicious_paths:
            with pytest.raises(Exception) as exc_info:
                _validate_path(malicious_path)

            assert "directory traversal" in str(
                exc_info.value
            ) or "outside allowed directory" in str(exc_info.value)


def test_validate_path_absolute_outside_cwd():
    """Test that absolute paths outside current working directory are rejected."""
    # Create a temporary directory that's outside our current working directory
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Get a path that's definitely outside our current working directory
        outside_path = "/"

        # This should fail because it's outside the current working directory
        with pytest.raises(Exception) as exc_info:
            _validate_path(outside_path)

        assert "outside allowed directory" in str(exc_info.value)

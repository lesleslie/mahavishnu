"""Tests for adapters/workflow/prefect_adapter.py — deprecated re-export module.

Tests cover:
- Import-time deprecation warning
- Re-export behavior (success or graceful ImportError)
- Module attributes (__all__)
"""

import warnings
from unittest.mock import patch

import pytest


class TestDeprecationWarning:
    def test_import_emits_deprecation_warning(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            import importlib
            import mahavishnu.adapters.workflow.prefect_adapter as mod
            importlib.reload(mod)
            dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(dep_warnings) >= 1
            assert "deprecated" in str(dep_warnings[0].message).lower()
            assert "engines.prefect_adapter" in str(dep_warnings[0].message)


class TestReExports:
    def test_all_defined(self):
        import mahavishnu.adapters.workflow.prefect_adapter as mod
        assert "PrefectAdapter" in mod.__all__
        assert "process_repository" in mod.__all__
        assert "process_repositories_flow" in mod.__all__

    def test_prefect_available_flag(self):
        """The _prefect_available flag should be set based on import success."""
        import mahavishnu.adapters.workflow.prefect_adapter as mod
        assert hasattr(mod, "_prefect_available")
        assert isinstance(mod._prefect_available, bool)

    def test_import_success_path(self):
        """When engines module is importable, re-exports should succeed."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            import mahavishnu.adapters.workflow.prefect_adapter as mod

            if mod._prefect_available:
                assert mod.PrefectAdapter is not None
                assert mod.process_repository is not None
                assert mod.process_repositories_flow is not None
            else:
                assert mod.PrefectAdapter is None
                assert mod.process_repository is None
                assert mod.process_repositories_flow is None

    def test_graceful_import_error(self):
        """When engines module is not importable, attributes should be None."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            with patch.dict("sys.modules", {"mahavishnu.engines.prefect_adapter": None}):
                # Force reimport with the module unavailable
                import importlib
                import mahavishnu.adapters.workflow.prefect_adapter as mod
                importlib.reload(mod)
                assert mod._prefect_available is False
                assert mod.PrefectAdapter is None

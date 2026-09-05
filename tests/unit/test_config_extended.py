"""Extended coverage tests for ``mahavishnu.core.config``.

Targets the small set of validators and helpers that the existing
``tests/unit/test_config*.py`` suite does not exercise, raising the
config.py coverage from 92.78% to >= 97%.

Each test is intentionally narrow: it constructs the smallest possible
input that hits a missing branch and asserts the documented contract.
No production code in ``mahavishnu/`` is touched.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from mahavishnu.core import config as config_mod
from mahavishnu.core.config import (
    A2AAgentEntry,
    A2ACardSettings,
    AgnoMemoryConfig,
    MahavishnuSettings,
    MemoryBackend,
    OTelIngesterConfig,
    OpenHandsSettings,
    WorkerEntry,
    WorkerRegistryConfig,
    get_settings,
    reset_settings,
    set_settings,
)

if TYPE_CHECKING:
    import os
    from collections.abc import Iterator


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_settings_cache() -> Iterator[None]:
    """Isolate the module-level ``_settings_cache`` for each test.

    Every test in this file touches the global settings cache directly
    (via ``get_settings`` / ``set_settings`` / ``reset_settings``), so we
    snapshot and restore it to keep test order independent.
    """
    original_cache = config_mod._settings_cache
    reset_settings()
    try:
        yield
    finally:
        config_mod._settings_cache = original_cache


# ---------------------------------------------------------------------------
# AgnoMemoryConfig.validate_connection_string (lines 137-143)
# ---------------------------------------------------------------------------


class TestAgnoMemoryConnectionString:
    """Cover the postgres-without-connection-string guard."""

    def test_postgres_backend_with_explicit_none_raises(self) -> None:
        """Explicit ``connection_string=None`` should also trip the guard."""
        with pytest.raises(ValidationError, match="connection_string must be set"):
            AgnoMemoryConfig(
                backend=MemoryBackend.POSTGRES,
                connection_string=None,
            )

    def test_postgres_backend_with_connection_string_ok(self) -> None:
        """Supplying a connection_string keeps the postgres backend valid."""
        cfg = AgnoMemoryConfig(
            backend=MemoryBackend.POSTGRES,
            connection_string="postgresql://user:strongpass@localhost:5432/agno",
        )
        assert cfg.backend == MemoryBackend.POSTGRES
        assert cfg.connection_string == "postgresql://user:strongpass@localhost:5432/agno"

    def test_non_postgres_backend_does_not_check_connection_string(self) -> None:
        """sqlite/none backends tolerate a missing connection_string."""
        cfg = AgnoMemoryConfig(backend=MemoryBackend.SQLITE)
        assert cfg.connection_string is None


# ---------------------------------------------------------------------------
# OTelIngesterConfig._validate_turboquant_bits (line 670)
# ---------------------------------------------------------------------------


class TestOTelIngesterTurboQuantBits:
    """The non-3/4 branch of the ``turboquant_bits`` validator."""

    def test_invalid_bits_raises(self) -> None:
        """Any bits value outside {3, 4, None} must raise."""
        with pytest.raises(ValidationError, match="turboquant_bits must be 3 or 4"):
            OTelIngesterConfig(turboquant_bits=5)
        with pytest.raises(ValidationError, match="turboquant_bits must be 3 or 4"):
            OTelIngesterConfig(turboquant_bits=0)
        with pytest.raises(ValidationError, match="turboquant_bits must be 3 or 4"):
            OTelIngesterConfig(turboquant_bits=2)


# ---------------------------------------------------------------------------
# OTelIngesterConfig._validate_storage_type (lines 676-678)
# ---------------------------------------------------------------------------


class TestOTelIngesterStorageType:
    """The invalid-storage-type branch of the storage_type validator."""

    def test_invalid_storage_type_raises(self) -> None:
        """Anything other than duckdb/postgresql must raise."""
        with pytest.raises(ValidationError, match="storage_type must be 'duckdb' or 'postgresql'"):
            OTelIngesterConfig(storage_type="sqlite")
        with pytest.raises(ValidationError, match="storage_type must be 'duckdb' or 'postgresql'"):
            OTelIngesterConfig(storage_type="")

    def test_postgresql_storage_type_accepted(self) -> None:
        """The documented postgresql value passes validation."""
        cfg = OTelIngesterConfig(storage_type="postgresql")
        assert cfg.storage_type == "postgresql"

    def test_duckdb_storage_type_accepted(self) -> None:
        """The default duckdb value passes validation."""
        cfg = OTelIngesterConfig(storage_type="duckdb")
        assert cfg.storage_type == "duckdb"


# ---------------------------------------------------------------------------
# A2ACardSettings._validate_skills (lines 1022-1024)
# ---------------------------------------------------------------------------


class TestA2ACardSkillsValidator:
    """The skills-required-keys branch."""

    def test_missing_required_keys_raises(self) -> None:
        """A skill without id/name/description must fail with a useful message."""
        with pytest.raises(ValidationError, match=r"skill\[0\] missing required keys"):
            A2ACardSettings(
                skills=[
                    {"id": "x", "name": "X"},  # no description
                ]
            )

    def test_missing_multiple_keys_reports_full_set(self) -> None:
        """All missing keys appear in the error message."""
        with pytest.raises(ValidationError) as exc_info:
            A2ACardSettings(skills=[{"name": "only-name"}])
        msg = str(exc_info.value)
        assert "id" in msg
        assert "description" in msg

    def test_well_formed_skill_passes(self) -> None:
        """The happy path: id/name/description all present."""
        cfg = A2ACardSettings(
            skills=[{"id": "search", "name": "Search", "description": "Find things"}]
        )
        assert cfg.skills[0]["id"] == "search"

    def test_empty_skills_list_passes(self) -> None:
        """An empty list is valid (no skill entries to check)."""
        cfg = A2ACardSettings(skills=[])
        assert cfg.skills == []


# ---------------------------------------------------------------------------
# A2AAgentEntry._validate_url_scheme (lines 1041-1046)
# ---------------------------------------------------------------------------


class TestA2AAgentEntryURLValidator:
    """The non-http/https branch of the A2A URL scheme check."""

    def test_ftp_scheme_rejected(self) -> None:
        """ftp:// (and any non-http/https scheme) must raise."""
        with pytest.raises(ValidationError, match="must use http or https"):
            A2AAgentEntry(name="foo", url="ftp://example.com/agent")

    def test_file_scheme_rejected(self) -> None:
        """file:// is not a valid A2A URL scheme."""
        with pytest.raises(ValidationError, match="must use http or https"):
            A2AAgentEntry(name="foo", url="file:///tmp/agent")

    def test_scheme_missing_rejected(self) -> None:
        """A bare URL with no scheme should also fail."""
        with pytest.raises(ValidationError, match="must use http or https"):
            A2AAgentEntry(name="foo", url="example.com/agent")

    def test_http_scheme_accepted(self) -> None:
        """The plain http scheme passes."""
        entry = A2AAgentEntry(name="foo", url="http://localhost:9000/agent")
        assert entry.url == "http://localhost:9000/agent"

    def test_https_scheme_accepted(self) -> None:
        """The https scheme passes."""
        entry = A2AAgentEntry(name="foo", url="https://agent.example.com/")
        assert entry.url == "https://agent.example.com/"


# ---------------------------------------------------------------------------
# OpenHandsSettings._workspace_dir_inside_root (line 1090)
# ---------------------------------------------------------------------------


class TestOpenHandsWorkspaceContainment:
    """The workspace_dir not-inside-workspace_root guard."""

    def test_workspace_dir_outside_root_raises(self, tmp_path: Path) -> None:
        """workspace_dir that escapes workspace_root must fail."""
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        root = tmp_path / "root"
        root.mkdir()

        with pytest.raises(ValidationError, match="must be inside workspace_root"):
            OpenHandsSettings(
                workspace_dir=outside,
                workspace_root=root,
            )

    def test_workspace_dir_inside_root_passes(self, tmp_path: Path) -> None:
        """A workspace_dir that sits under workspace_root is valid."""
        root = tmp_path / "root"
        inside = root / "workspace"
        inside.mkdir(parents=True)

        cfg = OpenHandsSettings(
            workspace_dir=inside,
            workspace_root=root,
        )
        # Field validator resolves the path; verify containment survives.
        assert inside.is_relative_to(root)
        assert cfg.workspace_dir.is_relative_to(cfg.workspace_root)


# ---------------------------------------------------------------------------
# WorkerEntry._validate_provides (line 1174)
# ---------------------------------------------------------------------------


class TestWorkerEntryProvidesValidator:
    """The capability-id pattern check on ``provides``."""

    def test_invalid_capability_id_raises(self) -> None:
        """An entry that violates ``^[a-z]+:[a-z0-9._-]+$`` must raise."""
        with pytest.raises(ValidationError, match="does not match"):
            WorkerEntry(
                worker_type="terminal-claude",
                provides=["BAD PATTERN"],  # spaces + uppercase, no colon
            )

    def test_capability_id_missing_namespace_raises(self) -> None:
        """``worker:bash`` is required, not bare ``bash``."""
        with pytest.raises(ValidationError, match="does not match"):
            WorkerEntry(
                worker_type="terminal-claude",
                provides=["bash"],  # no namespace: separator
            )

    def test_valid_capability_id_passes(self) -> None:
        """The canonical ``ns:name`` form passes."""
        entry = WorkerEntry(
            worker_type="terminal-claude",
            provides=["worker:bash", "worker:edit_file"],
        )
        assert entry.provides == ["worker:bash", "worker:edit_file"]

    def test_empty_provides_passes(self) -> None:
        """An empty list is valid (no entries to check)."""
        entry = WorkerEntry(worker_type="terminal-claude", provides=[])
        assert entry.provides == []


# ---------------------------------------------------------------------------
# WorkerEntry._validate_worker_type (line 1183)
# ---------------------------------------------------------------------------


class TestWorkerEntryWorkerTypeValidator:
    """The empty-worker_type guard."""

    def test_empty_worker_type_raises(self) -> None:
        """``worker_type=""`` must raise — the field is mandatory."""
        with pytest.raises(ValidationError, match="worker_type must be non-empty"):
            WorkerEntry(worker_type="")

    def test_non_empty_worker_type_passes(self) -> None:
        """Any non-empty string is accepted."""
        entry = WorkerEntry(worker_type="terminal-claude")
        assert entry.worker_type == "terminal-claude"


# ---------------------------------------------------------------------------
# WorkerRegistryConfig integration smoke test (combo of the two validators)
# ---------------------------------------------------------------------------


class TestWorkerRegistryConfigIntegration:
    """Smoke test: a registry of WorkerEntry rows round-trips through YAML."""

    def test_registry_with_valid_entries(self) -> None:
        """Two well-formed entries round-trip through model_dump."""
        registry = WorkerRegistryConfig(
            entries=[
                WorkerEntry(
                    worker_type="terminal-claude",
                    name="claude",
                    provides=["worker:bash"],
                ),
                WorkerEntry(
                    worker_type="terminal-qwen",
                    name="qwen",
                    provides=["worker:edit_file"],
                ),
            ]
        )
        dumped = registry.model_dump()
        assert len(dumped["entries"]) == 2
        assert dumped["entries"][0]["worker_type"] == "terminal-claude"

    def test_registry_rejects_invalid_provides(self) -> None:
        """Validation runs on the inner WorkerEntry, not just the wrapper."""
        with pytest.raises(ValidationError, match="does not match"):
            WorkerRegistryConfig(
                entries=[
                    WorkerEntry(
                        worker_type="terminal-claude",
                        provides=["bogus-no-colon"],
                    ),
                ]
            )


# ---------------------------------------------------------------------------
# MahavishnuSettings._settings_build_values — empty sources short circuit
# (line 2481)
# ---------------------------------------------------------------------------


class TestSettingsBuildValuesEmptySources:
    """The early-return path when ``sources`` is empty."""

    def test_empty_sources_returns_empty_dict(self) -> None:
        """An empty ``sources`` list must short-circuit to ``{}``."""
        result = MahavishnuSettings._settings_build_values(sources=[], init_kwargs={})
        assert result == {}


# ---------------------------------------------------------------------------
# get_settings / set_settings / reset_settings (lines 2560-2574)
# ---------------------------------------------------------------------------


class TestSettingsCacheHelpers:
    """Exercise the module-level cache helpers."""

    def test_get_settings_caches_after_first_call(self) -> None:
        """The first ``get_settings()`` populates the cache and reuses it."""
        first = get_settings()
        second = get_settings()
        # Identity equality proves the cache returned the same instance.
        assert first is second
        # And the cache slot is populated (not None).
        assert config_mod._settings_cache is first

    def test_set_settings_overrides_cache(self) -> None:
        """``set_settings`` swaps the cached instance for the provided one."""
        replacement = MahavishnuSettings(repos_path="/tmp/swap.yaml")
        set_settings(replacement)
        assert config_mod._settings_cache is replacement
        assert get_settings() is replacement

    def test_reset_settings_clears_cache(self) -> None:
        """``reset_settings`` returns the cache to ``None``."""
        # Force a cache hit first.
        get_settings()
        assert config_mod._settings_cache is not None
        reset_settings()
        assert config_mod._settings_cache is None

    def test_reset_then_get_rebuilds(self) -> None:
        """After reset, the next ``get_settings`` rebuilds a fresh instance."""
        original = get_settings()
        reset_settings()
        replacement = get_settings()
        # Distinct identity proves the rebuild happened.
        assert replacement is not original
        # And both are still valid settings objects.
        assert isinstance(replacement, MahavishnuSettings)

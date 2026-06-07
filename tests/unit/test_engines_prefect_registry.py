"""Unit tests for the Prefect flow registry.

Covers ``mahavishnu.engines.prefect_registry.FlowRegistry`` and the
``get_flow_registry`` / ``reset_flow_registry`` module-level helpers.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from mahavishnu.engines.prefect_registry import (
    FlowRegistry,
    get_flow_registry,
    reset_flow_registry,
)

pytestmark = pytest.mark.unit


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def flow_func() -> MagicMock:
    """A simple MagicMock that pretends to be a Prefect-decorated flow."""
    func = MagicMock()
    func.__name__ = "sample_flow"
    func.name = "prefect-flow-name"
    return func


@pytest.fixture
def plain_func() -> MagicMock:
    """A MagicMock without a custom Prefect ``name`` attribute."""
    func = MagicMock(spec=["__name__"])  # only __name__ available
    func.__name__ = "plain_flow"
    return func


@pytest.fixture
def registry() -> FlowRegistry:
    """Fresh FlowRegistry instance for each test (no shared state)."""
    return FlowRegistry()


@pytest.fixture(autouse=True)
def _reset_global_registry() -> None:
    """Ensure module-level global registry is reset around every test."""
    reset_flow_registry()
    yield
    reset_flow_registry()


# =============================================================================
# Basic registration
# =============================================================================


class TestRegisterFlow:
    """Behaviour of ``FlowRegistry.register_flow``."""

    def test_register_returns_uuid_string(
        self, registry: FlowRegistry, flow_func: MagicMock
    ) -> None:
        flow_id = registry.register_flow(flow_func, name="my-flow")
        assert isinstance(flow_id, str)
        # UUIDs are 36 chars long (8-4-4-4-12)
        assert len(flow_id) == 36

    def test_register_unique_ids_for_repeated_calls(
        self, registry: FlowRegistry, flow_func: MagicMock
    ) -> None:
        id_a = registry.register_flow(flow_func, name="flow-a")
        id_b = registry.register_flow(flow_func, name="flow-b")
        assert id_a != id_b

    def test_register_persists_function(self, registry: FlowRegistry, flow_func: MagicMock) -> None:
        flow_id = registry.register_flow(flow_func, name="my-flow")
        assert registry.get_flow(flow_id) is flow_func

    def test_register_stores_metadata_fields(
        self, registry: FlowRegistry, flow_func: MagicMock
    ) -> None:
        flow_id = registry.register_flow(flow_func, name="my-flow", tags=["etl", "prod"])
        meta = registry.get_flow_metadata(flow_id)
        assert meta is not None
        assert meta["id"] == flow_id
        assert meta["name"] == "my-flow"
        assert meta["func_name"] == "sample_flow"
        assert meta["prefect_name"] == "prefect-flow-name"
        assert meta["tags"] == ["etl", "prod"]
        assert "registered_at" in meta

    def test_register_defaults_tags_to_empty_list(
        self, registry: FlowRegistry, flow_func: MagicMock
    ) -> None:
        flow_id = registry.register_flow(flow_func, name="my-flow")
        assert registry.get_flow_metadata(flow_id)["tags"] == []

    def test_register_falls_back_to_func_name_when_no_prefect_name(
        self, registry: FlowRegistry, plain_func: MagicMock
    ) -> None:
        flow_id = registry.register_flow(plain_func, name="my-flow")
        meta = registry.get_flow_metadata(flow_id)
        # plain_func has no .name attribute, so prefect_name == func_name
        assert meta["prefect_name"] == "plain_flow"
        assert meta["func_name"] == "plain_flow"

    def test_register_non_callable_raises_value_error(self, registry: FlowRegistry) -> None:
        with pytest.raises(ValueError) as exc_info:
            registry.register_flow("not-callable", name="x")  # type: ignore[arg-type]
        assert "callable" in str(exc_info.value).lower()

    def test_register_logs_at_info_level(
        self,
        registry: FlowRegistry,
        flow_func: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.INFO, logger="mahavishnu.engines.prefect_registry"):
            registry.register_flow(flow_func, name="logged-flow")
        assert any("Registered flow" in r.message for r in caplog.records)


# =============================================================================
# Retrieval
# =============================================================================


class TestGetFlow:
    """Behaviour of ``FlowRegistry.get_flow``."""

    def test_get_unknown_returns_none(self, registry: FlowRegistry) -> None:
        assert registry.get_flow("does-not-exist") is None

    def test_get_known_returns_registered_func(
        self, registry: FlowRegistry, flow_func: MagicMock
    ) -> None:
        flow_id = registry.register_flow(flow_func, name="f")
        assert registry.get_flow(flow_id) is flow_func


class TestGetFlowMetadata:
    """Behaviour of ``FlowRegistry.get_flow_metadata``."""

    def test_unknown_id_returns_none(self, registry: FlowRegistry) -> None:
        assert registry.get_flow_metadata("nope") is None

    def test_known_id_returns_full_metadata(
        self, registry: FlowRegistry, flow_func: MagicMock
    ) -> None:
        flow_id = registry.register_flow(flow_func, name="f", tags=["t1", "t2"])
        meta = registry.get_flow_metadata(flow_id)
        assert meta is not None
        for key in (
            "id",
            "name",
            "func_name",
            "prefect_name",
            "tags",
            "registered_at",
        ):
            assert key in meta


# =============================================================================
# Listing
# =============================================================================


class TestListFlows:
    """Behaviour of ``FlowRegistry.list_flows``."""

    def test_list_empty_returns_empty_list(self, registry: FlowRegistry) -> None:
        assert registry.list_flows() == []

    def test_list_returns_all_when_no_tag_filter(
        self, registry: FlowRegistry, flow_func: MagicMock
    ) -> None:
        registry.register_flow(flow_func, name="a")
        registry.register_flow(flow_func, name="b")
        registry.register_flow(flow_func, name="c")
        flows = registry.list_flows()
        assert len(flows) == 3

    def test_list_filters_by_single_tag(self, registry: FlowRegistry, flow_func: MagicMock) -> None:
        registry.register_flow(flow_func, name="a", tags=["etl"])
        registry.register_flow(flow_func, name="b", tags=["ml"])
        registry.register_flow(flow_func, name="c", tags=["etl"])
        result = registry.list_flows(tags=["etl"])
        names = sorted(f["name"] for f in result)
        assert names == ["a", "c"]

    def test_list_filters_using_and_logic_for_multiple_tags(
        self, registry: FlowRegistry, flow_func: MagicMock
    ) -> None:
        registry.register_flow(flow_func, name="a", tags=["etl", "prod"])
        registry.register_flow(flow_func, name="b", tags=["etl"])
        registry.register_flow(flow_func, name="c", tags=["etl", "prod"])
        result = registry.list_flows(tags=["etl", "prod"])
        names = sorted(f["name"] for f in result)
        # Only "a" and "c" have BOTH etl AND prod
        assert names == ["a", "c"]

    def test_list_with_no_matches_returns_empty(
        self, registry: FlowRegistry, flow_func: MagicMock
    ) -> None:
        registry.register_flow(flow_func, name="a", tags=["etl"])
        assert registry.list_flows(tags=["nonexistent"]) == []

    def test_list_returns_independent_snapshots(
        self, registry: FlowRegistry, flow_func: MagicMock
    ) -> None:
        registry.register_flow(flow_func, name="a")
        snapshot = registry.list_flows()
        registry.register_flow(flow_func, name="b")
        # Original snapshot should be unchanged
        assert len(snapshot) == 1


# =============================================================================
# Unregistration
# =============================================================================


class TestUnregisterFlow:
    """Behaviour of ``FlowRegistry.unregister_flow``."""

    def test_unregister_existing_returns_true(
        self, registry: FlowRegistry, flow_func: MagicMock
    ) -> None:
        flow_id = registry.register_flow(flow_func, name="f")
        assert registry.unregister_flow(flow_id) is True
        assert registry.get_flow(flow_id) is None
        assert registry.count() == 0

    def test_unregister_unknown_returns_false(self, registry: FlowRegistry) -> None:
        assert registry.unregister_flow("missing") is False

    def test_unregister_unknown_logs_warning(
        self,
        registry: FlowRegistry,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="mahavishnu.engines.prefect_registry"):
            registry.unregister_flow("does-not-exist")
        assert any("non-existent" in r.message for r in caplog.records)

    def test_unregister_only_removes_specified(
        self, registry: FlowRegistry, flow_func: MagicMock
    ) -> None:
        id_a = registry.register_flow(flow_func, name="a")
        registry.register_flow(flow_func, name="b")
        assert registry.unregister_flow(id_a) is True
        assert registry.count() == 1


# =============================================================================
# Clear / count
# =============================================================================


class TestClearAndCount:
    """Behaviour of ``FlowRegistry.clear`` and ``count``."""

    def test_count_empty(self, registry: FlowRegistry) -> None:
        assert registry.count() == 0

    def test_count_reflects_registrations(
        self, registry: FlowRegistry, flow_func: MagicMock
    ) -> None:
        registry.register_flow(flow_func, name="a")
        registry.register_flow(flow_func, name="b")
        assert registry.count() == 2

    def test_clear_empties_registry(self, registry: FlowRegistry, flow_func: MagicMock) -> None:
        registry.register_flow(flow_func, name="a")
        registry.register_flow(flow_func, name="b")
        removed = registry.clear()
        assert removed == 2
        assert registry.count() == 0
        assert registry.list_flows() == []

    def test_clear_empty_returns_zero(self, registry: FlowRegistry) -> None:
        assert registry.clear() == 0

    def test_clear_drops_metadata_and_function(
        self, registry: FlowRegistry, flow_func: MagicMock
    ) -> None:
        flow_id = registry.register_flow(flow_func, name="a")
        registry.clear()
        assert registry.get_flow(flow_id) is None
        assert registry.get_flow_metadata(flow_id) is None


# =============================================================================
# Lookup helpers
# =============================================================================


class TestFindByName:
    """Behaviour of ``find_by_name`` and ``find_by_prefect_name``."""

    def test_find_by_name_exact_match(self, registry: FlowRegistry, flow_func: MagicMock) -> None:
        registry.register_flow(flow_func, name="dup")
        registry.register_flow(flow_func, name="dup")
        registry.register_flow(flow_func, name="other")
        matches = registry.find_by_name("dup")
        assert len(matches) == 2
        assert all(m["name"] == "dup" for m in matches)

    def test_find_by_name_no_match(self, registry: FlowRegistry, flow_func: MagicMock) -> None:
        registry.register_flow(flow_func, name="a")
        assert registry.find_by_name("zzz") == []

    def test_find_by_name_partial_does_not_match(
        self, registry: FlowRegistry, flow_func: MagicMock
    ) -> None:
        """The API uses exact matching, not substring."""
        registry.register_flow(flow_func, name="data-pipeline")
        assert registry.find_by_name("data") == []

    def test_find_by_prefect_name(self, registry: FlowRegistry, flow_func: MagicMock) -> None:
        registry.register_flow(flow_func, name="alias-1")
        registry.register_flow(flow_func, name="alias-2")
        # Both share the same prefect_name from the fixture
        matches = registry.find_by_prefect_name("prefect-flow-name")
        assert len(matches) == 2
        names = sorted(m["name"] for m in matches)
        assert names == ["alias-1", "alias-2"]

    def test_find_by_prefect_name_no_match(
        self, registry: FlowRegistry, flow_func: MagicMock
    ) -> None:
        registry.register_flow(flow_func, name="a")
        assert registry.find_by_prefect_name("nope") == []


# =============================================================================
# Global registry helpers
# =============================================================================


class TestGlobalRegistry:
    """Behaviour of ``get_flow_registry`` / ``reset_flow_registry``."""

    def test_get_flow_registry_returns_flow_registry(self) -> None:
        registry = get_flow_registry()
        assert isinstance(registry, FlowRegistry)

    def test_get_flow_registry_is_cached(self) -> None:
        first = get_flow_registry()
        second = get_flow_registry()
        # Lazy singleton — same instance both times
        assert first is second

    def test_reset_flow_registry_clears_singleton(self) -> None:
        first = get_flow_registry()
        first.register_flow(MagicMock(), name="kept")
        assert first.count() == 1

        reset_flow_registry()
        second = get_flow_registry()
        assert second is not first
        assert second.count() == 0

    def test_module_global_cleared_via_helper(self) -> None:
        """After ``reset_flow_registry``, the next ``get_flow_registry`` is fresh."""
        first = get_flow_registry()
        first.register_flow(MagicMock(), name="kept")
        assert first.count() == 1

        reset_flow_registry()
        # Behavioural check: get_flow_registry returns a different instance
        # whose state is independent of the prior global.
        second = get_flow_registry()
        assert second is not first
        assert second.count() == 0

    def test_module_attribute_cleared_after_reset(self) -> None:
        """Access the module attribute after reset to confirm it's None."""
        from mahavishnu.engines import prefect_registry as mod

        get_flow_registry()  # populate lazy global
        assert mod._global_registry is not None
        reset_flow_registry()
        assert mod._global_registry is None


# =============================================================================
# Module exports
# =============================================================================


class TestModuleExports:
    """The module's ``__all__`` includes the public helpers."""

    def test_all_exports_present(self) -> None:
        from mahavishnu.engines import prefect_registry

        for name in ("FlowRegistry", "get_flow_registry", "reset_flow_registry"):
            assert name in prefect_registry.__all__
            assert callable(getattr(prefect_registry, name))

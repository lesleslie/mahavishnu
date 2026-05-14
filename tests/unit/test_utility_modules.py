"""Tests for small utility modules to improve coverage.

Covers: mcp/tool_versions.py, mcp/error_envelope.py, and the
SkillRegistry in core/skill_registry.py.
"""

import pytest

# ---------------------------------------------------------------------------
# mcp/tool_versions.py
# ---------------------------------------------------------------------------


class TestToolVersions:
    def test_get_known_tool_version(self):
        from mahavishnu.mcp.tool_versions import get_tool_version

        assert get_tool_version("list_repos") == "1.0.0"
        assert get_tool_version("trigger_workflow") == "1.1.0"

    def test_get_unknown_tool_returns_none(self):
        from mahavishnu.mcp.tool_versions import get_tool_version

        assert get_tool_version("nonexistent_tool_xyz") is None

    def test_get_all_versions_returns_dict(self):
        from mahavishnu.mcp.tool_versions import TOOL_VERSIONS, get_all_tool_versions

        result = get_all_tool_versions()
        assert isinstance(result, dict)
        assert len(result) > 0
        assert result is not TOOL_VERSIONS  # must be a copy

    def test_tool_versions_dict_values_are_semver(self):
        from mahavishnu.mcp.tool_versions import TOOL_VERSIONS

        for tool, version in TOOL_VERSIONS.items():
            parts = version.split(".")
            assert len(parts) == 3, f"{tool}: expected semver, got {version!r}"

    def test_deprecated_code_intel_tools_have_replacements(self):
        from mahavishnu.mcp.tool_versions import get_tool_deprecation, is_tool_deprecated

        assert is_tool_deprecated("index_code_graph") is True
        assert is_tool_deprecated("find_related_code") is True
        assert is_tool_deprecated("index_documentation") is True
        assert is_tool_deprecated("search_documentation") is True
        assert is_tool_deprecated("get_monitoring_dashboard") is True
        assert get_tool_deprecation("index_code_graph") == "code_index.index_repo"
        assert get_tool_deprecation("find_related_code") == "treesitter_tools"
        assert get_tool_deprecation("index_documentation") == "code_index.index_repo"
        assert get_tool_deprecation("search_documentation") == "search_tools.hybrid_search"
        assert get_tool_deprecation("get_monitoring_dashboard") == "ecosystem_status"


# ---------------------------------------------------------------------------
# mcp/error_envelope.py
# ---------------------------------------------------------------------------


class TestMcpErrorEnvelope:
    def test_wrap_error_minimal(self):
        from mahavishnu.mcp.error_envelope import wrap_error

        env = wrap_error("MHV-001", "Something went wrong")
        assert env.error is True
        assert env.error_code == "MHV-001"
        assert env.message == "Something went wrong"
        assert env.recovery == []
        assert env.retryable is False
        assert env.retry_after_seconds is None
        assert env.details == {}

    def test_wrap_error_full(self):
        from mahavishnu.mcp.error_envelope import wrap_error

        env = wrap_error(
            "MHV-429",
            "Rate limited",
            recovery=["wait 60s", "reduce rate"],
            retryable=True,
            retry_after_seconds=60,
            details={"limit": "10/min"},
        )
        assert env.retryable is True
        assert env.retry_after_seconds == 60
        assert len(env.recovery) == 2
        assert env.details["limit"] == "10/min"

    def test_mcp_error_envelope_model(self):
        from mahavishnu.mcp.error_envelope import McpErrorEnvelope

        env = McpErrorEnvelope(error_code="MHV-003", message="Pre-execution QC failed")
        assert env.error is True
        assert env.error_code == "MHV-003"


# ---------------------------------------------------------------------------
# core/skill_registry.py
# ---------------------------------------------------------------------------


@pytest.fixture
def _skill_fixtures():
    from mahavishnu.core.skill_governance import (
        SkillDraft,
        SkillPromotionPolicy,
        SkillReview,
        SkillReviewDecision,
    )

    policy = SkillPromotionPolicy()
    draft = SkillDraft(
        name="test_skill",
        version="1.0.0",
        description="A test skill",
        body="def test(): pass",
        trigger_conditions=["on error"],
        proposed_by="tester",
    )
    review = SkillReview(
        skill_id=draft.skill_id,
        reviewer="reviewer",
        decision=SkillReviewDecision.APPROVE,
        rationale="Looks good",
    )
    return policy, draft, review


class TestSkillRegistry:
    def test_register_and_get_active(self, _skill_fixtures):
        from mahavishnu.core.skill_registry import SkillRegistry

        policy, draft, review = _skill_fixtures
        registry = SkillRegistry(policy=policy)

        activation = registry.register(draft, review, activated_by="ci")
        assert activation is not None

        record = registry.get_active(draft.skill_id)
        assert record is not None
        assert record.skill_id == draft.skill_id

    def test_policy_property(self, _skill_fixtures):
        from mahavishnu.core.skill_registry import SkillRegistry

        policy, _, _ = _skill_fixtures
        registry = SkillRegistry(policy=policy)
        assert registry.policy is policy

    def test_get_version_missing_returns_none(self, _skill_fixtures):
        from mahavishnu.core.skill_registry import SkillRegistry

        policy, _, _ = _skill_fixtures
        registry = SkillRegistry(policy=policy)
        assert registry.get_version("nonexistent", "0.0.0") is None

    def test_execute_rollback_no_active_raises(self, _skill_fixtures):
        from mahavishnu.core.skill_registry import SkillRegistry

        policy, _, _ = _skill_fixtures
        registry = SkillRegistry(policy=policy)
        with pytest.raises(ValueError, match="No active version"):
            registry.execute_rollback("nonexistent", "0.0.1", "user", "reason")

    def test_execute_rollback_version_not_found_raises(self, _skill_fixtures):
        from mahavishnu.core.skill_registry import SkillRegistry

        policy, draft, review = _skill_fixtures
        registry = SkillRegistry(policy=policy)
        registry.register(draft, review, activated_by="ci")

        with pytest.raises(ValueError, match="not found in history"):
            registry.execute_rollback(draft.skill_id, "9.9.9", "user", "reason")

    def test_deprecate_marks_deprecated(self, _skill_fixtures):
        from mahavishnu.core.skill_registry import SkillRegistry

        policy, draft, review = _skill_fixtures
        registry = SkillRegistry(policy=policy)
        registry.register(draft, review, activated_by="ci")

        registry.deprecate(draft.skill_id, deprecated_by="ci")
        assert registry.get_active(draft.skill_id) is None

    def test_evidence_history_preserved_empty(self, _skill_fixtures):
        from mahavishnu.core.skill_registry import SkillRegistry

        policy, _, _ = _skill_fixtures
        registry = SkillRegistry(policy=policy)
        assert registry.evidence_history_preserved("nonexistent") is True

    def test_evidence_history_preserved_with_records(self, _skill_fixtures):
        from mahavishnu.core.skill_registry import SkillRegistry

        policy, draft, review = _skill_fixtures
        registry = SkillRegistry(policy=policy)
        registry.register(draft, review, activated_by="ci")
        assert registry.evidence_history_preserved(draft.skill_id) is True

    def test_evidence_history_preserved_returns_false_when_rollback_id_in_evidence(
        self, _skill_fixtures
    ):
        """Return False when rollback_id matches a review_id in history (line 140)."""
        from mahavishnu.core.skill_governance import SkillRollback
        from mahavishnu.core.skill_registry import SkillRegistry, VersionRecord
        from mahavishnu.core.skill_governance import SkillPromotionState

        policy, draft, review = _skill_fixtures
        registry = SkillRegistry(policy=policy)

        # Build a VersionRecord with a rollback_id that equals the review's review_id
        rollback = SkillRollback(
            rollback_id=review.review_id,  # intentionally matches review_id
            skill_id=draft.skill_id,
            from_version="2.0.0",
            to_version="1.0.0",
            reason="regression",
            performed_by="ci",
        )

        rec_with_review = VersionRecord(
            skill_id=draft.skill_id,
            version="1.0.0",
            state=SkillPromotionState.ACTIVE,
            body="def x(): pass",
            review=review,
        )
        rec_with_rollback = VersionRecord(
            skill_id=draft.skill_id,
            version="2.0.0",
            state=SkillPromotionState.DEPRECATED,
            body="def x(): pass",
            rollback=rollback,
        )
        registry._history.extend([rec_with_review, rec_with_rollback])

        assert registry.evidence_history_preserved(draft.skill_id) is False


# ---------------------------------------------------------------------------
# mahavishnu.adapters package surface
# ---------------------------------------------------------------------------


class TestAdapterPackageSurface:
    def test_pgvector_is_no_longer_reexported(self):
        from mahavishnu import adapters

        assert "PgvectorAdapter" not in adapters.__all__
        assert "PgvectorSettings" not in adapters.__all__

    def test_pgvector_imports_remain_available_from_canonical_module(self):
        from mahavishnu.adapters.pgvector_adapter import PgvectorAdapter, PgvectorSettings

        assert PgvectorAdapter is not None
        assert PgvectorSettings is not None


class TestIngesterPackageSurface:
    def test_package_has_no_reexports(self):
        from mahavishnu import ingesters

        assert getattr(ingesters, "__all__", []) == []


class TestTaskRouterSurface:
    def test_legacy_aliases_are_gone(self):
        import mahavishnu.core.task_router as task_router

        assert not hasattr(task_router, "get_task_router")
        assert not hasattr(task_router, "reset_task_router")


class TestAdapterDiscoverySurface:
    def test_oneiric_aliases_are_gone(self):
        import mahavishnu.core.adapter_discovery as adapter_discovery

        assert not hasattr(adapter_discovery, "_get_oneiric_client")
        assert not hasattr(adapter_discovery, "discover_from_oneiric_mcp")

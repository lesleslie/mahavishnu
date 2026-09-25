"""Unit tests for mahavishnu.mcp.tools.clone_tools — Task 13 Phase B + Task 6."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_app():
    app = MagicMock()
    app.settings = MagicMock()
    app.settings.crackerjack_url = "http://localhost:8676"
    app.settings.mcp_url = "http://localhost:8683"
    app.settings.verification_enabled = True
    app.mcp_url = "http://localhost:8683"
    return app


@pytest.fixture
def mock_mcp():
    mcp = MagicMock()
    mcp.tool = MagicMock(return_value=lambda fn: fn)
    return mcp


def _diff_one_line() -> str:
    """Trivial extraction diff for tests that don't care about content."""
    return (
        "--- a/foo.py\n+++ b/foo.py\n"
        "@@ -1 +1 @@\n-x = 1\n+x = 2\n"
    )


@pytest.fixture
def mock_mcp_backend(monkeypatch):
    """Monkeypatch the module-level `mcp_backend` to a stub.

    Tests that exercise clone_refactor_group interact with cluster_state_claim
    → mcp_backend._circuit_is_open / .get / .put / .delete. The real
    MCPStateBackend would try to talk to localhost:8683 (which fails in
    CI / unit tests), so we stub it out. Mirrors the pattern used in the
    integration e2e tests.
    """
    from unittest.mock import AsyncMock

    from mahavishnu.core.state_backends.mcp import MCPStateBackend

    mock_backend = AsyncMock(spec=MCPStateBackend)
    mock_backend.dag_key = lambda x: f"workflow/v1/{x}"
    mock_backend.cluster_key = lambda x: f"cluster/v1/{x}"
    mock_backend.in_flight_key = lambda x: f"cluster/v1/{x}/in_flight"
    # _circuit_is_open must be a sync bool — AsyncMock attribute returns a
    # coroutine which is truthy and would raise MCPStateBackendUnavailable.
    mock_backend._circuit_is_open = lambda: False
    mock_backend.try_put_with_log_context = AsyncMock(return_value=True)
    mock_backend.put = AsyncMock()
    mock_backend.delete = AsyncMock()
    mock_backend.get = AsyncMock(return_value=None)
    mock_backend.list_prefix = AsyncMock(return_value=[])
    monkeypatch.setattr("mahavishnu.mcp.tools.clone_tools.mcp_backend", mock_backend)
    return mock_backend


# ---------------------------------------------------------------------------
# CloneTools class tests
# ---------------------------------------------------------------------------


class TestCloneToolsInit:
    def test_clone_tools_accepts_app(self, mock_app):
        from mahavishnu.mcp.tools.clone_tools import CloneTools

        tools = CloneTools(mock_app)
        assert tools.app is mock_app


class TestCloneDetectEcosystem:
    async def test_returns_job_id_immediately(self, mock_app):
        """clone_detect_ecosystem must return a job_id, not block on scan."""
        from mahavishnu.mcp.tools.clone_tools import CloneTools

        tools = CloneTools(mock_app)
        result = await tools.clone_detect_ecosystem(repos=None, min_similarity=0.9)

        assert "detect_job_id" in result
        assert result["status"] == "queued"

    async def test_accepts_repo_list(self, mock_app):
        from mahavishnu.mcp.tools.clone_tools import CloneTools

        tools = CloneTools(mock_app)
        result = await tools.clone_detect_ecosystem(repos=["repo_a", "repo_b"])
        assert "detect_job_id" in result

    async def test_accepts_none_repos_default(self, mock_app):
        from mahavishnu.mcp.tools.clone_tools import CloneTools

        tools = CloneTools(mock_app)
        result = await tools.clone_detect_ecosystem()
        assert result["status"] == "queued"


@pytest.mark.req(["REQ-CLONE-007", "REQ-CLONE-009", "REQ-CLONE-015"])
class TestCloneRefactorGroup:
    async def test_returns_refactor_job_id_immediately(self, mock_app, mock_mcp_backend):
        """clone_refactor_group must return immediately with a job_id (C-NEW-5)."""
        from unittest.mock import AsyncMock, patch

        from mahavishnu.mcp.tools.clone_tools import CloneTools

        tools = CloneTools(mock_app)
        with patch(
            "mahavishnu.mcp.tools.clone_tools.verify_proposal",
            AsyncMock(return_value=None),
        ):
            with patch.object(tools, "_store", MagicMock(persist=AsyncMock())):
                result = await tools.clone_refactor_group(
                    cluster_id="abc-123",
                    target_repo="/tmp/foo",
                    consumer_repos=[],
                    extracted_symbol="X",
                    extraction_diff=_diff_one_line(),
                )
        assert "refactor_job_id" in result
        assert result["status"] == "queued"
        assert result["cluster_id"] == "abc-123"

    async def test_cross_repo_always_propose_approve(self, mock_app, mock_mcp_backend):
        """Cross-repo refactors must flag as PROPOSE_APPROVE (M-NEW-5).

        With ``verification_enabled=False``, the verification gate is
        informational — the decision stays "propose_approve" even when
        consensus happens to be REJECT (the refuter rationales still
        surface in the ``verification`` field).
        """
        from unittest.mock import AsyncMock, patch

        from mahavishnu.mcp.tools.clone_tools import CloneTools

        mock_app.settings.verification_enabled = False
        tools = CloneTools(mock_app)
        with patch(
            "mahavishnu.mcp.tools.clone_tools.verify_proposal",
            AsyncMock(return_value=None),
        ):
            with patch.object(tools, "_store", MagicMock(persist=AsyncMock())):
                result = await tools.clone_refactor_group(
                    cluster_id="cross-repo-cluster",
                    target_repo="/tmp/foo",
                    consumer_repos=["/tmp/consumer1"],
                    extracted_symbol="Foo",
                    extraction_diff=_diff_one_line(),
                )
        assert result.get("decision") == "propose_approve"

    async def test_returns_verification_field(self, mock_app, mock_mcp_backend):
        """clone_refactor_group surfaces refuter rationales under ``verification``."""
        from unittest.mock import AsyncMock, patch

        from mahavishnu.mcp.tools.clone_tools import CloneTools

        tools = CloneTools(mock_app)
        with patch(
            "mahavishnu.mcp.tools.clone_tools.verify_proposal",
            AsyncMock(return_value=None),
        ):
            with patch.object(tools, "_store", MagicMock(persist=AsyncMock())):
                result = await tools.clone_refactor_group(
                    cluster_id="v-1",
                    target_repo="/tmp/foo",
                    consumer_repos=[],
                    extracted_symbol="X",
                    extraction_diff=_diff_one_line(),
                )
        assert "verification" in result

    async def test_blocked_by_verification_when_enabled_and_rejected(
        self, mock_app, mock_mcp_backend
    ):
        """When verification_enabled=True AND consensus=REJECT, decision flips."""
        from unittest.mock import AsyncMock, patch

        from mahavishnu.core.verification import (
            Consensus,
            RefuterVerdict,
            RefuterVerdictValue,
            VerificationResult,
        )
        from mahavishnu.mcp.tools.clone_tools import CloneTools

        mock_app.settings.verification_enabled = True
        tools = CloneTools(mock_app)

        rejected_verdicts = [
            RefuterVerdict(
                strategy_name="checklist",
                verdict=RefuterVerdictValue.REJECT,
                rationale="bad",
                concerns=["too risky"],
                latency_seconds=0.1,
            ),
        ]
        rejected_result = VerificationResult(
            proposal_id="pid-x",
            verdicts=rejected_verdicts,
            consensus=Consensus.REJECT,
            concerns_aggregated=["too risky"],
            persisted=False,
            persist_error="mcp backend not configured",
        )
        with patch(
            "mahavishnu.mcp.tools.clone_tools.verify_proposal",
            AsyncMock(return_value=rejected_result),
        ):
            with patch.object(
                tools, "_store",
                MagicMock(persist=AsyncMock(return_value=rejected_result)),
            ):
                result = await tools.clone_refactor_group(
                    cluster_id="blocked-cluster",
                    target_repo="/tmp/foo",
                    consumer_repos=[],
                    extracted_symbol="X",
                    extraction_diff=_diff_one_line(),
                )

        assert result["decision"] == "blocked_by_verification"
        assert result["verification"]["consensus"] == "reject"

    async def test_propose_approve_when_enabled_and_approved(
        self, mock_app, mock_mcp_backend
    ):
        """When verification_enabled=True but consensus != REJECT, decision stays."""
        from unittest.mock import AsyncMock, patch

        from mahavishnu.core.verification import (
            Consensus,
            RefuterVerdict,
            RefuterVerdictValue,
            VerificationResult,
        )
        from mahavishnu.mcp.tools.clone_tools import CloneTools

        mock_app.settings.verification_enabled = True
        tools = CloneTools(mock_app)
        approved_verdicts = [
            RefuterVerdict(
                strategy_name="checklist",
                verdict=RefuterVerdictValue.APPROVE,
                rationale="ok",
                concerns=[],
                latency_seconds=0.1,
            ),
        ]
        approved_result = VerificationResult(
            proposal_id="pid-y",
            verdicts=approved_verdicts,
            consensus=Consensus.APPROVE,
            concerns_aggregated=[],
            persisted=False,
        )
        with patch(
            "mahavishnu.mcp.tools.clone_tools.verify_proposal",
            AsyncMock(return_value=approved_result),
        ):
            with patch.object(
                tools, "_store",
                MagicMock(persist=AsyncMock(return_value=approved_result)),
            ):
                result = await tools.clone_refactor_group(
                    cluster_id="ok-cluster",
                    target_repo="/tmp/foo",
                    consumer_repos=[],
                    extracted_symbol="X",
                    extraction_diff=_diff_one_line(),
                )
        assert result["decision"] == "propose_approve"

    async def test_invalid_cluster_id_rejected(self, mock_app):
        """REQ-CLONE-015: cluster_id must match ^[a-z0-9-]{3,64}$."""
        from mahavishnu.mcp.tools.clone_tools import CloneTools

        tools = CloneTools(mock_app)
        with pytest.raises(ValueError, match="invalid_cluster_id"):
            await tools.clone_refactor_group(
                cluster_id="Bad_ID!",
                target_repo="/tmp/foo",
                consumer_repos=[],
                extracted_symbol="X",
                extraction_diff=_diff_one_line(),
            )


@pytest.mark.req(["REQ-CLONE-007"])
class TestCloneRefactorStatus:
    async def test_returns_list_of_key_value_pairs(self, mock_app, monkeypatch):
        """clone_refactor_status returns list[tuple[str, dict]]."""
        from unittest.mock import AsyncMock

        from mahavishnu.mcp.tools.clone_tools import CloneTools

        tools = CloneTools(mock_app)
        # Patch the module-level mcp_backend to a stub list_prefix.
        mock_backend = AsyncMock()
        mock_backend.list_prefix = AsyncMock(
            return_value=[
                ("workflow/v1/job-a", {"status": "completed"}),
                ("workflow/v1/job-b", {"status": "running"}),
            ]
        )
        monkeypatch.setattr(
            "mahavishnu.mcp.tools.clone_tools.mcp_backend", mock_backend
        )
        result = await tools.clone_refactor_status(limit=10)

        assert isinstance(result, list)
        assert all(isinstance(item, tuple) and len(item) == 2 for item in result)
        # UUIDv7 lexicographic: job-a < job-b, so reverse order: job-b first.
        assert result[0][0] == "workflow/v1/job-b"
        assert result[1][0] == "workflow/v1/job-a"

    async def test_returns_empty_list_on_substrate_failure(self, mock_app, monkeypatch):
        """Substrate failure returns [] (silent degrade)."""
        from unittest.mock import AsyncMock

        from mahavishnu.mcp.tools.clone_tools import CloneTools

        tools = CloneTools(mock_app)
        mock_backend = AsyncMock()
        mock_backend.list_prefix = AsyncMock(side_effect=RuntimeError("boom"))
        monkeypatch.setattr(
            "mahavishnu.mcp.tools.clone_tools.mcp_backend", mock_backend
        )
        result = await tools.clone_refactor_status()
        assert result == []


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------


@pytest.mark.req(["REQ-CLONE-007"])
class TestRegisterCloneTools:
    def test_register_function_exists(self):
        from mahavishnu.mcp.tools.clone_tools import register_clone_tools

        assert callable(register_clone_tools)

    def test_registers_four_tools(self, mock_mcp, mock_app):
        """Registers 3 clone-DAG tools + 1 verification-result lookup tool (T1.5)."""
        from mahavishnu.mcp.tools.clone_tools import register_clone_tools

        register_clone_tools(mock_mcp, mock_app)
        assert mock_mcp.tool.call_count == 4

    def test_register_function_accepts_optional_store(self, mock_mcp, mock_app):
        """register_clone_tools accepts an injected VerificationStore for tests."""
        from mahavishnu.mcp.tools.clone_tools import register_clone_tools

        register_clone_tools(mock_mcp, mock_app, store=None)  # must not raise


class TestGetVerificationResult:
    async def test_returns_not_found_when_store_missing(self, mock_app):
        from unittest.mock import patch

        from mahavishnu.mcp.tools.clone_tools import CloneTools

        # Force the store to be None by skipping the default build.
        with patch("mahavishnu.core.verification.build_default_store", return_value=None):
            tools = CloneTools(mock_app)
            result = await tools.get_verification_result(proposal_id="missing")
        assert result["status"] == "not_found"
        assert result["proposal_id"] == "missing"

    async def test_returns_verification_when_present(self, mock_app):
        """get_verification_result surfaces the serialized VerificationResult."""
        from unittest.mock import AsyncMock

        from mahavishnu.core.verification import (
            Consensus,
            RefuterVerdict,
            RefuterVerdictValue,
            VerificationResult,
            VerificationStore,
        )
        from mahavishnu.mcp.tools.clone_tools import CloneTools

        stored = VerificationResult(
            proposal_id="pid-z",
            verdicts=[
                RefuterVerdict(
                    strategy_name="checklist",
                    verdict=RefuterVerdictValue.APPROVE,
                    rationale="ok",
                    concerns=[],
                    latency_seconds=0.1,
                ),
            ],
            consensus=Consensus.APPROVE,
            concerns_aggregated=[],
            persisted=True,
            persist_error=None,
        )
        fake_store = MagicMock(spec=VerificationStore)
        fake_store.get = AsyncMock(return_value=stored)
        tools = CloneTools(mock_app, store=fake_store)

        result = await tools.get_verification_result(proposal_id="pid-z")
        assert result["proposal_id"] == "pid-z"
        assert "verification" in result
        assert result["verification"]["consensus"] == "approve"
        assert result["verification"]["persisted"] is True

    async def test_returns_not_found_when_store_returns_none(self, mock_app):
        """get_verification_result surfaces a miss cleanly when store.get returns None."""
        from unittest.mock import AsyncMock

        from mahavishnu.core.verification import VerificationStore
        from mahavishnu.mcp.tools.clone_tools import CloneTools

        fake_store = MagicMock(spec=VerificationStore)
        fake_store.get = AsyncMock(return_value=None)
        tools = CloneTools(mock_app, store=fake_store)

        result = await tools.get_verification_result(proposal_id="absent")
        assert result["status"] == "not_found"

    def test_full_registrations_includes_clone_tools(self):
        from mahavishnu.mcp.tools.profiles import FULL_REGISTRATIONS

        assert "_register_clone_tools" in FULL_REGISTRATIONS

    def test_standard_registrations_excludes_clone_tools(self):
        from mahavishnu.mcp.tools.profiles import STANDARD_REGISTRATIONS

        assert "_register_clone_tools" not in STANDARD_REGISTRATIONS

    def test_minimal_registrations_excludes_clone_tools(self):
        from mahavishnu.mcp.tools.profiles import MINIMAL_REGISTRATIONS

        assert "_register_clone_tools" not in MINIMAL_REGISTRATIONS


@pytest.mark.req(["REQ-CLONE-001"])
class TestCloneRefactorGroupVerification:
    """Phase 1 Task 1.6 exit criteria — verification gate runs on every call."""

    async def test_clone_refactor_group_runs_verification(self, mock_app, mock_mcp_backend):
        """clone_refactor_group must always return a ``verification`` field.

        This is the smoke check for Task 1.3 wiring: regardless of the
        downstream consensus, the response carries the serialized
        ``VerificationResult`` under ``verification`` so reviewers see
        refuter rationales.
        """
        from unittest.mock import AsyncMock, patch

        from mahavishnu.mcp.tools.clone_tools import CloneTools

        tools = CloneTools(mock_app)
        with patch(
            "mahavishnu.mcp.tools.clone_tools.verify_proposal",
            AsyncMock(return_value=None),
        ):
            with patch.object(tools, "_store", MagicMock(persist=AsyncMock())):
                result = await tools.clone_refactor_group(
                    cluster_id="task-1-6-cluster",
                    target_repo="/tmp/foo",
                    consumer_repos=[],
                    extracted_symbol="X",
                    extraction_diff=_diff_one_line(),
                )

        assert "verification" in result

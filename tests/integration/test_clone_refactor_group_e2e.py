"""MCP-tool end-to-end tests for clone_refactor_group.

This suite calls `CloneTools.clone_refactor_group` directly (in-process) and
verifies the wire-up behavior that the MCP server exposes — cluster_id
normalization, UUID7 ID format, cluster_claim dedup, initial DAG state
write, fire-and-forget task spawn, and per-step durability.

For the full MCP transport test (call_tool + TestClient), mirror the
pattern from `tests/integration/test_get_agent_e2e.py`.

Implements: REQ-CLONE-007, REQ-CLONE-009, REQ-CLONE-014, REQ-CLONE-015,
            REQ-CLONE-016
"""

from __future__ import annotations

import asyncio
import re
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from mahavishnu.mcp.tools.clone_claims import (
    ConcurrentDAGError,
    MCPStateBackendUnavailable,
)
from mahavishnu.mcp.tools.clone_tools import CloneTools

# REQ-CLONE-015
CLUSTER_ID_RE = re.compile(r"^[a-z0-9-]{3,64}$")


def _uuid7_version(uuid_str: str) -> int:
    """Return the version nibble of a UUID string. UUIDv7 has version=7."""
    return int(UUID(uuid_str).version)


def _make_clone_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[CloneTools, AsyncMock]:
    """Returns (CloneTools, mocked MCPStateBackend) pair.

    CR-B3 fix: return type is `tuple[CloneTools, AsyncMock]`, not `CloneTools`.
    The fixture returns both; downstream tests unpack.
    """
    from mahavishnu.core.state_backends.mcp import MCPStateBackend

    app = MagicMock()
    app.settings = MagicMock()
    # Enable verification gate so REJECT path is exercisable in tests
    # that need it (TestRejectBlocksDAG). Tests that don't care about
    # verification_enabled ignore this value.
    app.settings.verification_enabled = True
    app.settings.mcp_state = MagicMock(enabled=True, flush_interval_seconds=60,
                                       max_routing_buffer_age_seconds=3600)
    app.mcp_url = "http://localhost:8683"
    tools = CloneTools(app=app)
    # Inject a mocked MCPStateBackend that we control
    mock_backend = AsyncMock(spec=MCPStateBackend)
    mock_backend.dag_key = lambda x: f"workflow/v1/{x}"
    mock_backend.cluster_key = lambda x: f"cluster/v1/{x}"
    mock_backend.in_flight_key = lambda x: f"cluster/v1/{x}/in_flight"
    # _circuit_is_open must be a sync bool — production calls
    # `if mcp_backend._circuit_is_open():`. An AsyncMock attribute returns a
    # coroutine, which would be truthy and raise MCPStateBackendUnavailable.
    mock_backend._circuit_is_open = lambda: False
    mock_backend.try_put_with_log_context = AsyncMock(return_value=True)
    mock_backend.put = AsyncMock()
    mock_backend.delete = AsyncMock()
    mock_backend.get = AsyncMock(return_value=None)
    monkeypatch.setattr("mahavishnu.mcp.tools.clone_tools.mcp_backend", mock_backend)
    return tools, mock_backend


@pytest.fixture
def clone_tools_with_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[CloneTools, AsyncMock]:
    return _make_clone_tools(monkeypatch)


class TestClusterIdNormalization:
    """REQ-CLONE-015: ^[a-z0-9-]{3,64}$"""

    def test_valid_cluster_id_accepted(self):
        assert CLUSTER_ID_RE.match("cluster-abc123")
        assert CLUSTER_ID_RE.match("abc")
        assert CLUSTER_ID_RE.match("a-b-c-123")

    def test_invalid_cluster_id_rejected(self):
        for bad in ["Bad_ID!", "ab", "Cluster-1", "cluster_abc", "a" * 65]:
            assert not CLUSTER_ID_RE.match(bad), f"Should reject {bad!r}"


# CR-B1 fix: shared git_repo fixture. Each test method gets a fresh
# tmp_path-scoped git repo with user.email/name configured. Replaces the
# 5-line subprocess.run() boilerplate that exceeded 100 chars (would fail
# `ruff check` and gate crackerjack run).
@pytest.fixture
def git_repo(tmp_path):
    """Initialize a git repo at tmp_path/<random> with user.email/name."""
    import secrets
    import subprocess
    repo = tmp_path / f"target-{secrets.token_hex(4)}"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "x@x"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "X"],
        check=True, capture_output=True,
    )
    (repo / "foo.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "init"],
        check=True, capture_output=True,
    )
    return repo


def _diff_one_line() -> str:
    """Trivial extraction diff for tests that don't care about content."""
    return (
        "--- a/foo.py\n+++ b/foo.py\n"
        "@@ -1 +1 @@\n-x = 1\n+x = 2\n"
    )


@pytest.mark.req(["REQ-CLONE-007"])
class TestCloneRefactorGroupHappyPath:
    """REQ-CLONE-007: returns refactor_job_id + status: queued."""

    async def test_returns_job_id_and_starts_dag(
        self, clone_tools_with_backend, git_repo,
    ):
        tools, backend = clone_tools_with_backend

        # CR-B4 fix (v4): the verification call is module-level `verify_proposal`
        # (clone_tools.py:208), not a private CloneTools._verify method (which
        # never existed). Patch the module-level name. The store is an instance
        # attribute (set in __init__ at clone_tools.py:53), so patch the instance.
        with patch(
            "mahavishnu.mcp.tools.clone_tools.verify_proposal",
            AsyncMock(return_value=None),
        ):
            with patch.object(tools, "_store", MagicMock(persist=AsyncMock())):
                result = await tools.clone_refactor_group(
                    cluster_id="cluster-test",
                    target_repo=str(git_repo),
                    consumer_repos=[],
                    extracted_symbol="X",
                    extraction_diff=_diff_one_line(),
                )

        assert "refactor_job_id" in result
        assert result["status"] == "queued"
        # workflow/v1/{id} was written
        backend.put.assert_called()


@pytest.mark.req(["REQ-CLONE-007"])
class TestUUID7Format:
    """REQ-CLONE-007: refactor_job_id is UUIDv7."""

    async def test_refactor_job_id_is_uuid7(
        self, clone_tools_with_backend, git_repo,
    ):
        tools, backend = clone_tools_with_backend

        # CR-B4 fix (v4): the verification call is module-level `verify_proposal`
        # (clone_tools.py:208), not a private CloneTools._verify method (which
        # never existed). Patch the module-level name. The store is an instance
        # attribute (set in __init__ at clone_tools.py:53), so patch the instance.
        with patch(
            "mahavishnu.mcp.tools.clone_tools.verify_proposal",
            AsyncMock(return_value=None),
        ):
            with patch.object(tools, "_store", MagicMock(persist=AsyncMock())):
                result = await tools.clone_refactor_group(
                    cluster_id="cluster-uuid7",
                    target_repo=str(git_repo),
                    consumer_repos=[],
                    extracted_symbol="X",
                    extraction_diff=_diff_one_line(),
                )
        # REQ-CLONE-007: parse the returned ID and assert version=7
        version = _uuid7_version(result["refactor_job_id"])
        assert version == 7, f"Expected UUIDv7, got version={version}"


@pytest.mark.req(["REQ-CLONE-001"])
class TestRejectBlocksDAG:
    """REQ-CLONE-001: consensus=REJECT blocks DAG."""

    async def test_clone_refactor_group_reject_blocks_dag(
        self, clone_tools_with_backend, git_repo,
    ):
        tools, backend = clone_tools_with_backend

        # Mock verify_proposal to return REJECT. CE-fix: the store's persist
        # must also return the SAME reject_result (not a fresh MagicMock) so
        # the consensus check downstream still sees Consensus.REJECT.
        from mahavishnu.core.verification import Consensus
        reject_result = MagicMock()
        reject_result.consensus = Consensus.REJECT
        # CR-B4 fix (v4): see note in TestCloneRefactorGroupHappyPath.
        with patch(
            "mahavishnu.mcp.tools.clone_tools.verify_proposal",
            AsyncMock(return_value=reject_result),
        ):
            with patch.object(
                tools, "_store",
                MagicMock(persist=AsyncMock(return_value=reject_result)),
            ):
                result = await tools.clone_refactor_group(
                    cluster_id="cluster-reject",
                    target_repo=str(git_repo),
                    consumer_repos=[],
                    extracted_symbol="X",
                    extraction_diff=_diff_one_line(),
                )
        assert result.get("decision") == "blocked_by_verification"
        # Claim was released (REQ-CLONE-001: REJECT path releases sentinel)
        backend.delete.assert_called_with("cluster/v1/cluster-reject/in_flight")


@pytest.mark.req(["REQ-CLONE-009"])
class TestConcurrentCalls:
    """REQ-CLONE-009: two concurrent calls with same cluster_id → second
    raises ConcurrentDAGError."""

    async def test_concurrent_calls_deduplicate(
        self, clone_tools_with_backend, git_repo,
    ):
        tools, backend = clone_tools_with_backend

        # CR-B4 fix (v4): the verification call is module-level `verify_proposal`
        # (clone_tools.py:208), not a private CloneTools._verify method (which
        # never existed). Patch the module-level name. The store is an instance
        # attribute (set in __init__ at clone_tools.py:53), so patch the instance.
        with patch(
            "mahavishnu.mcp.tools.clone_tools.verify_proposal",
            AsyncMock(return_value=None),
        ):
            with patch.object(tools, "_store", MagicMock(persist=AsyncMock())):
                # Make cluster_state_claim succeed for the first call,
                # then return a fake "existing" record for the second.
                # CE-fix: do NOT reset call_count between calls — the DAG
                # background task also reads mcp_backend.get (for its
                # re-entry guard at clone_refactor_workflow.py:398), and we
                # want a single monotonic counter. After the first
                # clone_refactor_group + DAG re-entry check, all subsequent
                # gets see the existing sentinel.
                call_count = 0

                async def fake_get(key):
                    nonlocal call_count
                    call_count += 1
                    if call_count == 1:
                        return None  # first call: no sentinel
                    return {"refactor_job_id": "first-job-id"}

                backend.get = fake_get

                # First call — succeeds
                first = await tools.clone_refactor_group(
                    cluster_id="cluster-concurrent",
                    target_repo=str(git_repo),
                    consumer_repos=[],
                    extracted_symbol="X",
                    extraction_diff=_diff_one_line(),
                )

                # Second call — must raise ConcurrentDAGError
                with pytest.raises(ConcurrentDAGError) as exc_info:
                    await tools.clone_refactor_group(
                        cluster_id="cluster-concurrent",
                        target_repo=str(git_repo),
                        consumer_repos=[],
                        extracted_symbol="X",
                        extraction_diff=_diff_one_line(),
                    )
                assert exc_info.value.existing_job_id == "first-job-id"


@pytest.mark.req(["REQ-CLONE-014"])
class TestMCPStateBackendUnavailable:
    """SF-B6: substrate circuit-open raises MCPStateBackendUnavailable."""

    async def test_substrate_unavailable_raises_unavailable(
        self, clone_tools_with_backend,
    ):
        tools, backend = clone_tools_with_backend

        # Make cluster_state_claim raise MCPStateBackendUnavailable
        async def fake_claim(*args, **kwargs):
            raise MCPStateBackendUnavailable(key="k", reason="circuit_open")

        with patch(
            "mahavishnu.mcp.tools.clone_tools.cluster_state_claim",
            side_effect=fake_claim,
        ):
            with pytest.raises(MCPStateBackendUnavailable):
                await tools.clone_refactor_group(
                    cluster_id="cluster-down",
                    target_repo="/tmp/x",
                    consumer_repos=[],
                    extracted_symbol="X",
                    extraction_diff="",
                )


@pytest.mark.req(["REQ-CLONE-016"])
class TestCancellationMarksTerminal:
    """REQ-CLONE-016: client cancellation marks terminal "cancelled"."""

    async def test_dag_cancellation_marks_terminal(
        self, clone_tools_with_backend, git_repo,
    ):
        tools, backend = clone_tools_with_backend

        # CR-B4 fix (v4): patch module-level verify_proposal with CancelledError
        # to simulate client cancellation flowing through the call site
        # (clone_tools.py:208). The store is an instance attribute.
        with patch(
            "mahavishnu.mcp.tools.clone_tools.verify_proposal",
            AsyncMock(side_effect=asyncio.CancelledError()),
        ):
            with patch.object(tools, "_store", MagicMock(persist=AsyncMock())):
                with pytest.raises(asyncio.CancelledError):
                    await tools.clone_refactor_group(
                        cluster_id="cluster-cancel",
                        target_repo=str(git_repo),
                        consumer_repos=[],
                        extracted_symbol="X",
                        extraction_diff=_diff_one_line(),
                    )
        # Claim was released on cancellation
        backend.delete.assert_called_with("cluster/v1/cluster-cancel/in_flight")

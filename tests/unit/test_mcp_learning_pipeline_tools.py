"""Unit tests for mahavishnu.mcp.tools.learning_pipeline_tools.

The module exposes ``register_learning_tools`` which attaches five read-only
FastMCP tool functions. The tests capture those functions (via a stub
``mcp.tool()`` decorator) and exercise them with mocked pipeline_service,
evidence_store, skill_registry, and rbac_manager dependencies.

The wiring tests at the bottom of this file cover
``mahavishnu.mcp.bootstrap._register_learning_pipeline_tools`` — the
function that bridges the live ``LearningPipelineService`` (stashed on
``MahavishnuApp._learning_pipeline`` by ``init_learning_pipeline``) to
the read-only MCP tool surface.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.mcp.bootstrap import _register_learning_pipeline_tools
from mahavishnu.mcp.tools.learning_pipeline_tools import register_learning_tools


class _StubMCP:
    """Minimal FastMCP stand-in that returns decorated functions unchanged."""

    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn

            return fn

        return decorator


def _model(**fields) -> MagicMock:
    """Build a MagicMock whose ``model_dump(mode=...)`` returns ``fields``."""
    m = MagicMock()
    m.model_dump = MagicMock(return_value=fields)
    for k, v in fields.items():
        setattr(m, k, v)
    return m


def _fake_rbac_manager() -> MagicMock:
    """Return a fake RBAC manager that allows all checks.

    Mirrors the pattern in ``tests/unit/mcp/test_capability_tools.py``:
    the ``@require_mcp_auth`` decorator awaits
    ``rbac_manager.check_permission(user_id, repo, perm)``; an AsyncMock
    returning ``True`` satisfies the gate so tests can drive the
    tool's behavior (return values, error paths, etc.) without
    standing up a real RBAC.

    A separate test below covers the AUTH_NOT_CONFIGURED / AUTH_REQUIRED
    failure paths explicitly.
    """
    rbac = MagicMock()
    rbac.check_permission = AsyncMock(return_value=True)
    return rbac


_USER = "test-user"  # arbitrary user_id passed to every tool call


@pytest.fixture
def stub_mcp() -> _StubMCP:
    return _StubMCP()


@pytest.fixture
def rbac() -> MagicMock:
    return _fake_rbac_manager()


@pytest.fixture
def pipeline_service() -> MagicMock:
    service = MagicMock()
    service.is_running = True
    service.cycle_count = 7
    service.total_drafts = 3
    service.last_result = _model(cycle=7, drafts_added=2, status="ok")
    service.run_once = AsyncMock(return_value=_model(cycle=8, drafts_added=1, status="ok"))
    return service


@pytest.fixture
def evidence_store() -> MagicMock:
    store = MagicMock()
    store.query_evidence = AsyncMock(
        return_value=[
            _model(id="e1", kind="pattern", text="hello"),
            _model(id="e2", kind="metric", text="world"),
        ]
    )
    return store


@pytest.fixture
def skill_registry() -> MagicMock:
    reg = MagicMock()
    reg.list_active = MagicMock(
        return_value=[
            SimpleNamespace(skill_id="skill-1", version="1.0.0", state="draft", body="body one"),
            SimpleNamespace(skill_id="skill-2", version="0.9.0", state="review", body=None),
        ]
    )
    reg.list_history = MagicMock(
        return_value=[
            SimpleNamespace(version="1.0.0", state="active", body="new body", rollback=None),
            SimpleNamespace(version="0.9.0", state="draft", body="older", rollback="old-snapshot"),
        ]
    )
    return reg


# ---------------------------------------------------------------------------
# Auth-gate tests — exercise the @require_mcp_auth wrapper behavior.
# These verify the gate fails closed per ``mahavishnu/mcp/auth.py`` §11.7.
# ---------------------------------------------------------------------------


def test_register_attaches_all_five_tools(stub_mcp: _StubMCP, rbac: MagicMock) -> None:
    register_learning_tools(stub_mcp, rbac_manager=rbac)
    expected = {
        "get_pipeline_status",
        "list_evidence",
        "trigger_synthesis",
        "list_pending_drafts",
        "get_promotion_history",
    }
    assert set(stub_mcp.tools) == expected


def test_auth_denies_when_rbac_manager_missing(stub_mcp: _StubMCP) -> None:
    """No rbac_manager -> AUTH_NOT_CONFIGURED on every tool call.

    The decorator fails closed (auth.py:88-95) so a misconfigured
    registrar cannot silently open the tools.
    """
    register_learning_tools(stub_mcp, rbac_manager=None)
    import asyncio

    for name in (
        "get_pipeline_status",
        "list_evidence",
        "trigger_synthesis",
        "list_pending_drafts",
        "get_promotion_history",
    ):
        fn = stub_mcp.tools[name]
        result = asyncio.run(fn(user_id=_USER))
        assert result == {
            "status": "error",
            "error": "RBAC manager not configured",
            "error_code": "AUTH_NOT_CONFIGURED",
        }, f"Tool {name!r} did not deny on missing rbac_manager"


def test_auth_denies_when_user_id_missing(stub_mcp: _StubMCP, rbac: MagicMock) -> None:
    """rbac present but user_id absent -> AUTH_REQUIRED."""
    register_learning_tools(stub_mcp, rbac_manager=rbac)
    import asyncio

    result = asyncio.run(stub_mcp.tools["get_pipeline_status"]())
    assert result == {
        "status": "error",
        "error": "Authentication required: user_id parameter missing",
        "error_code": "AUTH_REQUIRED",
    }


def test_auth_denies_when_permission_check_fails(
    stub_mcp: _StubMCP, evidence_store: MagicMock
) -> None:
    """rbac present but check_permission returns False -> PERMISSION_DENIED."""
    rbac = MagicMock()
    rbac.check_permission = AsyncMock(return_value=False)
    register_learning_tools(stub_mcp, evidence_store=evidence_store, rbac_manager=rbac)
    import asyncio

    result = asyncio.run(stub_mcp.tools["list_evidence"](user_id=_USER, query="x"))
    assert result["error_code"] == "PERMISSION_DENIED"
    # The tool body must NOT have run.
    evidence_store.query_evidence.assert_not_awaited()


# ---------------------------------------------------------------------------
# Tool behavior tests — all calls pass rbac + user_id; the gate is satisfied.
# ---------------------------------------------------------------------------


def test_get_pipeline_status_without_service(
    stub_mcp: _StubMCP, rbac: MagicMock
) -> None:
    register_learning_tools(stub_mcp, rbac_manager=rbac)
    fn = stub_mcp.tools["get_pipeline_status"]
    import asyncio

    result = asyncio.run(fn(user_id=_USER))
    assert result == {
        "available": False,
        "error": "Learning pipeline service not initialized",
    }


def test_get_pipeline_status_with_service(
    stub_mcp: _StubMCP, pipeline_service: MagicMock, rbac: MagicMock
) -> None:
    register_learning_tools(
        stub_mcp, pipeline_service=pipeline_service, rbac_manager=rbac
    )
    fn = stub_mcp.tools["get_pipeline_status"]
    import asyncio

    result = asyncio.run(fn(user_id=_USER))
    assert result["available"] is True
    assert result["is_running"] is True
    assert result["cycle_count"] == 7
    assert result["total_drafts"] == 3
    # NOTE: source key is "last_cycle" (not "last_result"); pinned here.
    assert result["last_cycle"] == {
        "cycle": 7,
        "drafts_added": 2,
        "status": "ok",
    }


def test_get_pipeline_status_with_no_last_result(
    stub_mcp: _StubMCP, rbac: MagicMock
) -> None:
    service = MagicMock()
    service.is_running = False
    service.cycle_count = 0
    service.total_drafts = 0
    service.last_result = None
    register_learning_tools(
        stub_mcp, pipeline_service=service, rbac_manager=rbac
    )
    fn = stub_mcp.tools["get_pipeline_status"]
    import asyncio

    result = asyncio.run(fn(user_id=_USER))
    assert result["is_running"] is False
    assert result["last_cycle"] is None


def test_list_evidence_without_store(stub_mcp: _StubMCP, rbac: MagicMock) -> None:
    register_learning_tools(stub_mcp, rbac_manager=rbac)
    fn = stub_mcp.tools["list_evidence"]
    import asyncio

    result = asyncio.run(fn(user_id=_USER, query="x"))
    assert result == {
        "available": False,
        "error": "Evidence store not initialized",
    }


def test_list_evidence_passes_query_and_limit(
    stub_mcp: _StubMCP, evidence_store: MagicMock, rbac: MagicMock
) -> None:
    register_learning_tools(
        stub_mcp, evidence_store=evidence_store, rbac_manager=rbac
    )
    fn = stub_mcp.tools["list_evidence"]
    import asyncio

    result = asyncio.run(fn(user_id=_USER, query="hello", limit=5))
    evidence_store.query_evidence.assert_awaited_once_with("hello", 5)
    assert result["available"] is True
    assert result["count"] == 2
    assert result["evidence"] == [
        {"id": "e1", "kind": "pattern", "text": "hello"},
        {"id": "e2", "kind": "metric", "text": "world"},
    ]


def test_list_evidence_handles_query_error(
    stub_mcp: _StubMCP, evidence_store: MagicMock, rbac: MagicMock
) -> None:
    evidence_store.query_evidence = AsyncMock(side_effect=RuntimeError("index down"))
    register_learning_tools(
        stub_mcp, evidence_store=evidence_store, rbac_manager=rbac
    )
    fn = stub_mcp.tools["list_evidence"]
    import asyncio

    result = asyncio.run(fn(user_id=_USER, query="q"))
    assert result["available"] is True
    assert result["count"] == 0
    assert result["evidence"] == []
    # Sensitive-error-disclosure fix: only the exception class name is
    # returned, not the full message. The full trace stays in logs.
    assert result["error"] == "RuntimeError"


def test_trigger_synthesis_without_service(
    stub_mcp: _StubMCP, rbac: MagicMock
) -> None:
    register_learning_tools(stub_mcp, rbac_manager=rbac)
    fn = stub_mcp.tools["trigger_synthesis"]
    import asyncio

    result = asyncio.run(fn(user_id=_USER))
    assert result == {
        "available": False,
        "error": "Learning pipeline service not initialized",
    }


def test_trigger_synthesis_returns_cycle_result(
    stub_mcp: _StubMCP, pipeline_service: MagicMock, rbac: MagicMock
) -> None:
    register_learning_tools(
        stub_mcp, pipeline_service=pipeline_service, rbac_manager=rbac
    )
    fn = stub_mcp.tools["trigger_synthesis"]
    import asyncio

    result = asyncio.run(fn(user_id=_USER))
    pipeline_service.run_once.assert_awaited_once()
    assert result["available"] is True
    assert result["cycle_result"] == {
        "cycle": 8,
        "drafts_added": 1,
        "status": "ok",
    }


def test_trigger_synthesis_handles_error(
    stub_mcp: _StubMCP, pipeline_service: MagicMock, rbac: MagicMock
) -> None:
    pipeline_service.run_once = AsyncMock(side_effect=RuntimeError("boom"))
    register_learning_tools(
        stub_mcp, pipeline_service=pipeline_service, rbac_manager=rbac
    )
    fn = stub_mcp.tools["trigger_synthesis"]
    import asyncio

    result = asyncio.run(fn(user_id=_USER))
    assert result["available"] is True
    assert result["error"] == "RuntimeError"


def test_list_pending_drafts_without_registry(
    stub_mcp: _StubMCP, rbac: MagicMock
) -> None:
    register_learning_tools(stub_mcp, rbac_manager=rbac)
    fn = stub_mcp.tools["list_pending_drafts"]
    import asyncio

    result = asyncio.run(fn(user_id=_USER))
    assert result == {
        "available": False,
        "error": "Skill registry not initialized",
    }


def test_list_pending_drafts_truncates_long_bodies(
    stub_mcp: _StubMCP, skill_registry: MagicMock, rbac: MagicMock
) -> None:
    long_body = "x" * 1000
    skill_registry.list_active = MagicMock(
        return_value=[
            SimpleNamespace(skill_id="s-long", version="1.0", state="draft", body=long_body),
        ]
    )
    register_learning_tools(
        stub_mcp, skill_registry=skill_registry, rbac_manager=rbac
    )
    fn = stub_mcp.tools["list_pending_drafts"]
    import asyncio

    result = asyncio.run(fn(user_id=_USER))
    assert result["count"] == 1
    assert result["drafts"][0]["skill_id"] == "s-long"
    assert len(result["drafts"][0]["body"]) == 500


def test_list_pending_drafts_handles_none_body(
    stub_mcp: _StubMCP, skill_registry: MagicMock, rbac: MagicMock
) -> None:
    register_learning_tools(
        stub_mcp, skill_registry=skill_registry, rbac_manager=rbac
    )
    fn = stub_mcp.tools["list_pending_drafts"]
    import asyncio

    result = asyncio.run(fn(user_id=_USER))
    assert result["count"] == 2
    assert result["drafts"][1]["body"] is None


def test_list_pending_drafts_handles_error(
    stub_mcp: _StubMCP, skill_registry: MagicMock, rbac: MagicMock
) -> None:
    skill_registry.list_active = MagicMock(side_effect=RuntimeError("registry down"))
    register_learning_tools(
        stub_mcp, skill_registry=skill_registry, rbac_manager=rbac
    )
    fn = stub_mcp.tools["list_pending_drafts"]
    import asyncio

    result = asyncio.run(fn(user_id=_USER))
    assert result["available"] is True
    assert result["error"] == "RuntimeError"
    assert result["drafts"] == []


def test_get_promotion_history_without_registry(
    stub_mcp: _StubMCP, rbac: MagicMock
) -> None:
    register_learning_tools(stub_mcp, rbac_manager=rbac)
    fn = stub_mcp.tools["get_promotion_history"]
    import asyncio

    result = asyncio.run(fn(user_id=_USER, skill_id="x"))
    assert result == {
        "available": False,
        "error": "Skill registry not initialized",
    }


def test_get_promotion_history_returns_versions(
    stub_mcp: _StubMCP, skill_registry: MagicMock, rbac: MagicMock
) -> None:
    register_learning_tools(
        stub_mcp, skill_registry=skill_registry, rbac_manager=rbac
    )
    fn = stub_mcp.tools["get_promotion_history"]
    import asyncio

    result = asyncio.run(fn(user_id=_USER, skill_id="skill-1"))
    skill_registry.list_history.assert_called_once_with("skill-1")
    assert result["available"] is True
    assert result["skill_id"] == "skill-1"
    assert result["count"] == 2
    assert result["history"][0]["version"] == "1.0.0"
    assert result["history"][0]["has_rollback"] is False
    assert result["history"][1]["has_rollback"] is True


def test_get_promotion_history_handles_error(
    stub_mcp: _StubMCP, skill_registry: MagicMock, rbac: MagicMock
) -> None:
    skill_registry.list_history = MagicMock(side_effect=RuntimeError("db error"))
    register_learning_tools(
        stub_mcp, skill_registry=skill_registry, rbac_manager=rbac
    )
    fn = stub_mcp.tools["get_promotion_history"]
    import asyncio

    result = asyncio.run(fn(user_id=_USER, skill_id="x"))
    assert result["available"] is True
    assert result["error"] == "RuntimeError"
    assert result["count"] == 0
    assert result["history"] == []


# ---------------------------------------------------------------------------
# Wiring tests — ``mahavishnu.mcp.bootstrap._register_learning_pipeline_tools``
# ---------------------------------------------------------------------------


class _StubServer:
    """Minimal FastMCPServer stand-in for wiring tests.

    Only the ``server`` (the inner FastMCP) and ``app`` (the
    MahavishnuApp wrapper that holds ``_learning_pipeline`` and
    ``rbac_manager``) attributes are touched by the wiring function.
    """

    def __init__(self, app: object) -> None:
        self.server = _StubMCP()
        self.app = app


def _build_pipeline_service_mock() -> MagicMock:
    """Build a service mock with the two new public accessors wired in.

    Mirrors the real ``LearningPipelineService`` accessors the wiring
    function reaches into: ``evidence_store`` and ``skill_registry``.
    """
    service = MagicMock()
    service.is_running = False
    service.cycle_count = 0
    service.total_drafts = 0
    service.last_result = None
    service.evidence_store = MagicMock()
    service.skill_registry = MagicMock()
    return service


class TestRegisterLearningPipelineToolsWiring:
    def test_passes_live_pipeline_through_to_register(self) -> None:
        service = _build_pipeline_service_mock()
        rbac = _fake_rbac_manager()
        app = SimpleNamespace(_learning_pipeline=service, rbac_manager=rbac)
        server = _StubServer(app)

        _register_learning_pipeline_tools(server)

        # All five tools attached.
        assert set(server.server.tools) == {
            "get_pipeline_status",
            "list_evidence",
            "trigger_synthesis",
            "list_pending_drafts",
            "get_promotion_history",
        }
        # The captured tool closures captured the live service + the
        # accessors the wiring function resolved off of it. The
        # ``_pipeline_status`` helper (called by ``get_pipeline_status``)
        # returns ``available: True`` when the service is non-None.
        import asyncio

        result = asyncio.run(server.server.tools["get_pipeline_status"](user_id=_USER))
        assert result["available"] is True
        assert result["is_running"] is False

    def test_passes_none_dependencies_when_pipeline_disabled(self) -> None:
        """``learning.enabled=false`` ⇒ pipeline is None ⇒ tools report unavailable.

        The wiring function must NOT raise when the app has no pipeline
        — the tools handle ``None`` dependencies and return
        ``{"available": False, ...}``.
        """
        rbac = _fake_rbac_manager()
        app = SimpleNamespace(_learning_pipeline=None, rbac_manager=rbac)
        server = _StubServer(app)

        _register_learning_pipeline_tools(server)

        assert set(server.server.tools) == {
            "get_pipeline_status",
            "list_evidence",
            "trigger_synthesis",
            "list_pending_drafts",
            "get_promotion_history",
        }
        import asyncio

        status = asyncio.run(server.server.tools["get_pipeline_status"](user_id=_USER))
        assert status == {
            "available": False,
            "error": "Learning pipeline service not initialized",
        }
        evidence = asyncio.run(server.server.tools["list_evidence"](user_id=_USER, query="x"))
        assert evidence == {
            "available": False,
            "error": "Evidence store not initialized",
        }
        drafts = asyncio.run(server.server.tools["list_pending_drafts"](user_id=_USER))
        assert drafts == {
            "available": False,
            "error": "Skill registry not initialized",
        }

    def test_passes_evidence_store_and_skill_registry_from_pipeline(self) -> None:
        """The wiring must reach the same instances the pipeline owns.

        The MCP read-only tools must observe the same state the pipeline
        mutates — a copy / shadow registry would silently diverge from
        activation events.
        """
        service = _build_pipeline_service_mock()
        live_store = MagicMock(name="live_evidence_store")
        live_registry = MagicMock(name="live_skill_registry")
        service.evidence_store = live_store
        service.skill_registry = live_registry
        rbac = _fake_rbac_manager()
        app = SimpleNamespace(_learning_pipeline=service, rbac_manager=rbac)
        server = _StubServer(app)

        with patch(
            "mahavishnu.mcp.tools.learning_pipeline_tools.register_learning_tools"
        ) as mock_register:
            _register_learning_pipeline_tools(server)
            mock_register.assert_called_once()
            kwargs = mock_register.call_args.kwargs
            assert kwargs["pipeline_service"] is service
            assert kwargs["evidence_store"] is live_store
            assert kwargs["skill_registry"] is live_registry
            assert kwargs["rbac_manager"] is rbac

    def test_passes_none_dependencies_when_app_missing_pipeline_attr(self) -> None:
        """Defensive: an app that has no ``_learning_pipeline`` attribute yet
        (e.g. mid-init) must not crash the wiring function.
        """
        rbac = _fake_rbac_manager()
        app = SimpleNamespace(rbac_manager=rbac)  # no _learning_pipeline attribute
        server = _StubServer(app)

        _register_learning_pipeline_tools(server)  # must not raise

        import asyncio

        status = asyncio.run(server.server.tools["get_pipeline_status"](user_id=_USER))
        assert status == {
            "available": False,
            "error": "Learning pipeline service not initialized",
        }

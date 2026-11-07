"""End-to-end tests for the eval MCP tool group (REQ-EVAL-005).

Four gates, each one a claim the plan makes about the feature:

- **e1** — all three tools return non-empty results in the happy path.
- **e2** — ``eval_run_suite`` returns ``{"status": "error", "error":
  "evaluation disabled"}`` when evaluation is disabled.
- **e3** — the raw FastMCP ``tools/list`` is empty for the eval tools
  under the ``minimal`` tool profile (and populated under ``standard``).
- **e4** — ``eval_run_suite`` completes without an ``EvalPool`` being
  spawned: the Phase 1 tools call the engine directly.

The tests drive the real registration path against a real FastMCP
server and call the tools through the MCP call surface, so a broken
registration or a broken schema fails here rather than in production.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mcp_common.fastmcp import FastMCP
from mcp_common.tools.dispatch import _apply_tool_profile
import pytest

from mahavishnu.core.eval.settings import EvalSettings
from mahavishnu.mcp.tools.eval_tools import register_eval_tools
from mahavishnu.mcp.tools.profiles import (
    MAHAVISHNU_MANDATORY_GROUPS,
    PROFILE_REGISTRATIONS,
    settings_yaml_loader,
)

if TYPE_CHECKING:
    from mahavishnu.core.eval.engine import EvalRunResult, EvalSuite

# req: REQ-EVAL-005

#: The three tool names the group registers.
EVAL_TOOL_NAMES = frozenset(
    {"eval_register_dataset", "eval_run_suite", "eval_get_run"}
)


def _eval_settings(tmp_path: Path, *, enabled: bool = True) -> EvalSettings:
    """Build eval settings pointing at a temporary run store."""
    return EvalSettings(
        enabled=enabled,
        db_path=str(tmp_path / "runs.sqlite"),
        dataset_root=str(tmp_path),
        default_model_backend="mahavishnu.mock",
        default_scorers=["mahavishnu.exact_match"],
    )


def _dataset(tmp_path: Path, *, cases: int = 2) -> Path:
    """Write a JSONL dataset of ``cases`` echo cases and return its path."""
    path = tmp_path / "cases.jsonl"
    lines = [
        json.dumps({"id": f"c{index}", "input": f"ping-{index}", "expected": f"ping-{index}"})
        for index in range(cases)
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _install_settings(monkeypatch: pytest.MonkeyPatch, settings: EvalSettings) -> None:
    """Point the eval settings accessor at the given settings.

    The tools resolve ``get_eval_settings`` at call time, so patching
    the module attribute is enough.
    """
    monkeypatch.setattr(
        "mahavishnu.core.eval.settings.get_eval_settings",
        lambda: settings,
    )


async def _call(mcp: FastMCP, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Call a tool and return its structured result."""
    result = await mcp.call_tool(name, arguments)
    assert result.structured_content is not None
    return dict(result.structured_content)


@pytest.mark.integration
@pytest.mark.req(["REQ-EVAL-005"])
async def test_e1_all_three_tools_return_non_empty_results(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """All three tools return non-empty results in the happy path."""
    _install_settings(monkeypatch, _eval_settings(tmp_path))

    mcp = FastMCP(name="eval-e2e")
    register_eval_tools(mcp)

    tool_names = {tool.name for tool in await mcp.list_tools()}
    assert tool_names >= EVAL_TOOL_NAMES

    dataset = _dataset(tmp_path)

    registered = await _call(mcp, "eval_register_dataset", {"path": str(dataset)})
    assert registered["status"] == "ok"
    assert registered["cases"] == 2
    assert registered["content_hash"]

    ran = await _call(
        mcp,
        "eval_run_suite",
        {"suite": str(dataset), "model": "mahavishnu.mock"},
    )
    assert ran["status"] == "completed"
    assert ran["run_id"]
    assert ran["summary"]["total_cases"] == 2

    # The run writes its Markdown report, and the tool says where.
    report_path = Path(ran["report_path"])
    assert report_path.exists()
    document = report_path.read_text(encoding="utf-8")
    assert ran["run_id"] in document
    assert "## Summary" in document

    fetched = await _call(mcp, "eval_get_run", {"run_id": ran["run_id"]})
    assert fetched["run_id"] == ran["run_id"]
    assert len(fetched["case_results"]) == 2
    assert len(fetched["scores"]) == 2


@pytest.mark.integration
@pytest.mark.req(["REQ-EVAL-005"])
async def test_e2_disabled_evaluation_returns_the_disabled_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """With evaluation disabled, the tool reports "evaluation disabled".

    The tool is registered while evaluation is enabled and the setting
    is then turned off — that is the state a server reaches when eval
    is switched off mid-flight. The body must refuse the run rather
    than spend budget.
    """
    _install_settings(monkeypatch, _eval_settings(tmp_path, enabled=True))

    mcp = FastMCP(name="eval-disabled")
    register_eval_tools(mcp)

    _install_settings(monkeypatch, _eval_settings(tmp_path, enabled=False))

    dataset = _dataset(tmp_path)
    result = await _call(
        mcp,
        "eval_run_suite",
        {"suite": str(dataset), "model": "mahavishnu.mock"},
    )
    assert result == {"status": "error", "error": "evaluation disabled"}


@pytest.mark.integration
@pytest.mark.req(["REQ-EVAL-005"])
async def test_registration_is_skipped_when_evaluation_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A disabled evaluation registers no tools at all.

    The registration gate and the body guard are different contracts:
    the gate keeps the tools out of ``tools/list``; the body guard
    covers a server whose setting changes after registration.
    """
    _install_settings(monkeypatch, _eval_settings(tmp_path, enabled=False))

    mcp = FastMCP(name="eval-not-registered")
    register_eval_tools(mcp)

    tool_names = {tool.name for tool in await mcp.list_tools()}
    assert not tool_names & EVAL_TOOL_NAMES


@pytest.mark.integration
@pytest.mark.req(["REQ-EVAL-005"])
async def test_e3_minimal_profile_registers_no_eval_tools(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The minimal profile registers no eval tools; standard does."""
    _install_settings(monkeypatch, _eval_settings(tmp_path))

    async def _run_profile(profile: str) -> tuple[set[str], set[str]]:
        """Apply a profile and report the requested groups and tools."""
        monkeypatch.setenv("MAHAVISHNU_TOOL_PROFILE", profile)
        mcp = FastMCP(name=f"eval-profile-{profile}")
        requested: list[str] = []

        def _make(name: str) -> Any:
            def _register(server: FastMCP) -> None:
                requested.append(name)
                if name == "_register_eval_tools":
                    register_eval_tools(server)

            return _register

        group_names = {
            name for group in PROFILE_REGISTRATIONS.values() for name in group
        } | set(MAHAVISHNU_MANDATORY_GROUPS)
        await _apply_tool_profile(
            mcp,
            profile_env_var="MAHAVISHNU_TOOL_PROFILE",
            registrations=PROFILE_REGISTRATIONS,  # ty: ignore[invalid-argument-type]
            registration_map={name: _make(name) for name in group_names},
            register_all_fn=None,
            mandatory_groups=MAHAVISHNU_MANDATORY_GROUPS,
            yaml_loader=settings_yaml_loader,
        )
        tool_names = {tool.name for tool in await mcp.list_tools()}
        return set(requested), tool_names

    minimal_groups, minimal_tools = await _run_profile("minimal")
    assert "_register_eval_tools" not in minimal_groups
    assert not minimal_tools & EVAL_TOOL_NAMES

    standard_groups, standard_tools = await _run_profile("standard")
    assert "_register_eval_tools" in standard_groups
    assert standard_tools >= EVAL_TOOL_NAMES


@pytest.mark.integration
@pytest.mark.req(["REQ-EVAL-005"])
async def test_e4_run_suite_needs_no_eval_pool(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The tool runs a suite without an EvalPool being constructed."""
    from mahavishnu.pools.eval_pool import EvalPool

    _install_settings(monkeypatch, _eval_settings(tmp_path))

    def _explode(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("the eval tools must not construct an EvalPool")

    monkeypatch.setattr(EvalPool, "__init__", _explode)

    mcp = FastMCP(name="eval-no-pool")
    register_eval_tools(mcp)

    dataset = _dataset(tmp_path)
    result = await _call(
        mcp,
        "eval_run_suite",
        {"suite": str(dataset), "model": "mahavishnu.mock"},
    )
    assert result["status"] == "completed"


@pytest.mark.integration
@pytest.mark.req(["REQ-EVAL-005"])
async def test_run_suite_reports_a_missing_dataset_as_an_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A dataset that cannot be loaded produces an error, not a raise."""
    _install_settings(monkeypatch, _eval_settings(tmp_path))

    mcp = FastMCP(name="eval-missing-dataset")
    register_eval_tools(mcp)

    result = await _call(
        mcp,
        "eval_run_suite",
        {"suite": str(tmp_path / "nope.jsonl"), "model": "mahavishnu.mock"},
    )
    assert result["status"] == "error"
    assert result["error_type"] == "EvalDatasetLoadError"


@pytest.mark.integration
@pytest.mark.req(["REQ-EVAL-005"])
async def test_get_run_reports_an_unknown_run_as_an_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An unknown run id produces an error, not a raise."""
    _install_settings(monkeypatch, _eval_settings(tmp_path))

    mcp = FastMCP(name="eval-unknown-run")
    register_eval_tools(mcp)

    result = await _call(mcp, "eval_get_run", {"run_id": "does-not-exist"})
    assert result["status"] == "error"
    assert result["error_type"] == "EvalStorageError"


@pytest.mark.integration
@pytest.mark.req(["REQ-EVAL-002"])
async def test_a_dataset_outside_the_root_is_refused(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A dataset outside the configured root is refused.

    The MCP surface is server-reachable: without confinement a client
    could name any file on disk and have the server read it.
    """
    _install_settings(monkeypatch, _eval_settings(tmp_path))

    outside = tmp_path.parent / "outside-dataset.jsonl"
    outside.write_text('{"id": "c1", "input": "x", "expected": "x"}\n', encoding="utf-8")

    mcp = FastMCP(name="eval-confinement")
    register_eval_tools(mcp)

    result = await _call(
        mcp,
        "eval_register_dataset",
        {"path": str(outside)},
    )
    assert result["status"] == "error"
    assert result["error_type"] == "EvalDatasetLoadError"
    assert "outside the eval dataset root" in result["error"]


@pytest.mark.integration
@pytest.mark.req(["REQ-EVAL-003"])
async def test_a_caller_cannot_raise_the_operators_budget(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A caller-supplied budget is clamped to the operator's cap.

    The operator's budget is a ceiling. A client that names a larger one
    is asking to spend money the operator did not authorise.

    The assertion is on the budget the engine is actually handed, not
    on the clamp helper: the tool builds the suite, and the suite's
    cap is what the run is held to. Asserting the helper would still
    pass if the tool stopped calling it.

    (The suite the tool builds prices the model at zero, so the run
    itself costs nothing and the *spend* cannot show the clamp. The
    budget the engine receives is where the clamp is visible.)
    """
    from mahavishnu.core.eval.engine import EvalEngine

    captured: list[EvalSuite] = []

    class _CapturingEngine(EvalEngine):
        """An engine that remembers the suite it was asked to run."""

        async def run_suite(self, suite: EvalSuite) -> EvalRunResult:
            captured.append(suite)
            return await super().run_suite(suite)

    monkeypatch.setattr("mahavishnu.mcp.tools.eval_tools.EvalEngine", _CapturingEngine)
    _install_settings(monkeypatch, _eval_settings(tmp_path))

    mcp = FastMCP(name="eval-budget-clamp")
    register_eval_tools(mcp)

    dataset = _dataset(tmp_path)
    result = await _call(
        mcp,
        "eval_run_suite",
        {
            "suite": str(dataset),
            "model": "mahavishnu.mock",
            "params": {"budget_usd": 10_000.0},
        },
    )
    assert result["status"] == "completed"
    assert len(captured) == 1
    # The caller asked for 10,000; the operator allows 5.
    assert captured[0].cost_budget.max_usd == 5.0


@pytest.mark.integration
@pytest.mark.req(["REQ-EVAL-003"])
async def test_a_caller_cannot_raise_the_token_ceiling(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A caller-supplied token ceiling is clamped, not honoured.

    The assertion is the *effect*: the run persists the model config
    it ran with, and the persisted ceiling is the operator's, not the
    caller's. Asserting the private clamp helper instead would still
    pass if the tool stopped calling it.
    """
    from mahavishnu.core.eval.settings import EvalSettings
    from mahavishnu.core.eval.storage_backends.sqlite import SqliteEvalStorage

    settings = EvalSettings(
        enabled=True,
        db_path=str(tmp_path / "runs.sqlite"),
        dataset_root=str(tmp_path),
        default_model_backend="mahavishnu.mock",
        default_scorers=["mahavishnu.exact_match"],
        max_tokens_per_call=512,
    )
    _install_settings(monkeypatch, settings)

    mcp = FastMCP(name="eval-token-clamp")
    register_eval_tools(mcp)

    dataset = _dataset(tmp_path)
    result = await _call(
        mcp,
        "eval_run_suite",
        {
            "suite": str(dataset),
            "model": "mahavishnu.mock",
            "params": {"max_tokens": 1_000_000},
        },
    )
    assert result["status"] == "completed"

    storage = SqliteEvalStorage(tmp_path / "runs.sqlite")
    details = await storage.get_run(result["run_id"])
    assert details is not None
    model_config = details.run.model_configs["mahavishnu.mock"]
    assert model_config["max_tokens"] == 512


@pytest.mark.integration
@pytest.mark.req(["REQ-EVAL-005"])
async def test_an_unknown_model_backend_names_the_alternatives(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A model name where a backend name belongs is a client error.

    The likeliest mistake is naming a model (``MiniMax-M3``) where a
    backend (``mahavishnu.mock``) is wanted. That must read as a
    client error with the available names, not as a server fault.
    """
    _install_settings(monkeypatch, _eval_settings(tmp_path))

    mcp = FastMCP(name="eval-unknown-backend")
    register_eval_tools(mcp)

    dataset = _dataset(tmp_path)
    result = await _call(
        mcp,
        "eval_run_suite",
        {"suite": str(dataset), "model": "MiniMax-M3"},
    )
    assert result["status"] == "error"
    assert result["error_type"] == "EvalEngineError"
    assert "unknown model backend 'MiniMax-M3'" in result["error"]
    assert "mahavishnu.mock" in result["error"]


@pytest.mark.integration
@pytest.mark.req(["REQ-EVAL-003"])
async def test_the_clamp_helper_survives_hostile_input() -> None:
    """The clamp helper is total: a hostile value cannot raise or pass through.

    The helper is the last thing between a caller's number and the
    engine's budget, so it has to answer for every input. A NaN, a
    string, and a value below the floor all resolve to a number the
    engine can hold.
    """
    from mahavishnu.mcp.tools.eval_tools import _clamped

    assert _clamped(64, 512) == 64
    assert _clamped(float("nan"), 512) == 512
    assert _clamped("nonsense", 512) == 512
    assert _clamped(-10, 512) == 0.0
    assert _clamped(10_000, 512) == 512

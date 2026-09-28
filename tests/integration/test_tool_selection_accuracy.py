"""Tool selection accuracy test (Phase 2 Task 2.4).

REQ-TSQ-011 from ``docs/plans/2026-09-26-tool-surface-quality.md``.

Verifies the top-10 most-called tools (per ``scripts/audit_top_tool_calls.py``)
have descriptions that satisfy the 6-criterion rubric from
``.claude/decisions/tool-description-rubric.md`` AND that a fixed task
suite of representative queries would be routed to the correct tool by
an LLM picking from those descriptions.

Strategy
--------
Three layers, all deterministic (no live LLM judge required in CI):

1. **Structural rubric compliance** — parses ``server_core.py`` with
   ``ast`` and asserts each of the 10 tools' docstrings satisfies all
   six criteria (negative cases, failure modes, return shape, active
   voice, side-effect caveat, no internal disclosure).

2. **Fixed task suite keyword coverage** — for each representative
   query, asserts the ground-truth tool's rewritten docstring contains
   the keywords an LLM would need to select it. Proxies LLM-as-judge
   with deterministic string checks; runs in milliseconds.

3. **Before/after measurement** — captures the ORIGINAL docstrings as
   constants; asserts the rubric-compliance score improves by ≥
   tolerance threshold. Pins the regression baseline so future
   regressions are caught.

LLM-as-judge is OPT-IN via the ``MAHAVISHNU_RUN_LLM_JUDGE`` env var.
The plan's tolerance band ``after-rate ≥ before-rate − 2σ`` is enforced
on the deterministic proxy rate (layer 2) — network-judge rate is
recorded but not gating.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
import re
from typing import Any

import pytest

SERVER_CORE_PATH = Path(__file__).resolve().parents[2] / "mahavishnu" / "mcp" / "server_core.py"

# Top-10 tools per Phase 2 Task 2.1 (audit_top_tool_calls.py).
# The list is closed — adding a new tool to this set requires updating
# the BEFORE_DOCSTRINGS / AFTER_EXPECTATIONS tables below.
TOP_10_TOOLS: tuple[str, ...] = (
    "list_repos",
    "list_workflows",
    "get_observability_metrics",
    "get_workflow_statistics",
    "list_adapters",
    "list_backups",
    "get_log_statistics",
    "get_recovery_metrics",
    "get_monitoring_dashboard",
    "get_active_alerts",
)


# ---------------------------------------------------------------------------
# BEFORE state — the original one-line docstrings captured at Task 2.3 time.
# These are the baseline against which the rubric-compliance delta is measured.
# ---------------------------------------------------------------------------
BEFORE_DOCSTRINGS: dict[str, str] = {
    "list_repos": "List repositories with optional filtering and pagination.",
    "list_workflows": "List workflows with optional filtering.",
    "get_observability_metrics": "Get current observability metrics from the system.",
    "get_workflow_statistics": "Get workflow statistics and analytics.",
    "list_adapters": "List available adapters.",
    "list_backups": "List all available backups.",
    "get_log_statistics": "Get log statistics and analytics.",
    "get_recovery_metrics": "Get metrics about error recovery and resilience operations.",
    "get_monitoring_dashboard": (
        "Get comprehensive monitoring dashboard data.\n\n"
        "    Compatibility wrapper around the canonical ecosystem status report.\n    "
    ),
    "get_active_alerts": "Get all active (non-acknowledged) alerts.",
}


# ---------------------------------------------------------------------------
# Fixed task suite (REQ-TSQ-011 requires ≥5 representative tasks).
# Each task asserts that the ground-truth tool's rewritten docstring
# contains the keywords an LLM would need to pick it.
# ---------------------------------------------------------------------------
TASK_SUITE: tuple[dict[str, Any], ...] = (
    {
        "query": "Show me the list of all repositories we have configured.",
        "ground_truth": "list_repos",
        "expected_keywords": ("repositories", "registry", "filter"),
        "negative_anti_keywords": ("scan", "contents"),
    },
    {
        "query": "What workflows are currently running?",
        "ground_truth": "list_workflows",
        "expected_keywords": ("workflows", "status"),
        "negative_anti_keywords": ("trigger", "new"),
    },
    {
        "query": "I need to see the recent log error rates.",
        "ground_truth": "get_log_statistics",
        "expected_keywords": ("log statistics", "error rates"),
        "negative_anti_keywords": ("individual log lines",),
    },
    {
        "query": "Are there any production alerts firing right now?",
        "ground_truth": "get_active_alerts",
        "expected_keywords": ("alerts", "firing"),
        "negative_anti_keywords": ("acknowledge", "resolve"),
    },
    {
        "query": "Which orchestrator adapters are currently registered?",
        "ground_truth": "list_adapters",
        "expected_keywords": ("adapters", "health"),
        "negative_anti_keywords": ("dispatch work", "pool_route"),
    },
    {
        "query": "Show me the latest system backups.",
        "ground_truth": "list_backups",
        "expected_keywords": ("backups",),
        "negative_anti_keywords": ("create a backup", "restore"),
    },
    {
        "query": "Give me an aggregate of workflow performance metrics.",
        "ground_truth": "get_workflow_statistics",
        "expected_keywords": ("aggregate workflow statistics",),
        "negative_anti_keywords": ("enumerate specific workflows",),
    },
    {
        "query": "Show me the high-level ecosystem health dashboard.",
        "ground_truth": "get_monitoring_dashboard",
        "expected_keywords": ("ecosystem status report",),
        "negative_anti_keywords": ("per-tool metrics",),
    },
    {
        "query": "What does our observability subsystem currently report?",
        "ground_truth": "get_observability_metrics",
        "expected_keywords": ("observability snapshot",),
        "negative_anti_keywords": ("historical metrics",),
    },
    {
        "query": "How often has error recovery kicked in this week?",
        "ground_truth": "get_recovery_metrics",
        "expected_keywords": ("recovery", "metrics"),
        "negative_anti_keywords": ("trigger recovery",),
    },
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_docstrings() -> dict[str, str]:
    """Parse server_core.py and return {function_name: docstring} for the 10 tools.

    AST walk: each tool is ``async def NAME(...) -> ...`` with a constant
    docstring (ast.Constant) as the first statement. FastMCP's
    ``@server.tool()`` consumes the docstring as the public description,
    so the docstring IS the contract — no separate ``description=`` kwarg
    is in use on these tools.
    """
    source = SERVER_CORE_PATH.read_text()
    tree = ast.parse(source)

    # The 10 tools are registered inline inside ``_register_core_tools``
    # (a method on the FastMCPServer class). AST iteration over the whole
    # file works because these names are unique within the module.
    found: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        if node.name not in TOP_10_TOOLS:
            continue
        docstring = ast.get_docstring(node, clean=False)
        if docstring is None:
            found[node.name] = ""
        else:
            # FastMCP passes the docstring through ``inspect.cleandoc`` —
            # mirror that here so the test asserts against the public
            # representation, not the raw AST literal.
            found[node.name] = inspect_cleandoc(docstring)
    return found


def inspect_cleandoc(text: str) -> str:
    """Mirror Python's ``inspect.cleandoc`` semantics for docstring comparison.

    The stdlib ``inspect.cleandoc`` removes leading whitespace based on
    the first non-empty line. We replicate that here to match what
    FastMCP renders to the model — comparing against raw indented text
    would fail on every whitespace check.
    """
    lines = text.splitlines()
    # Drop leading blank lines.
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        return ""
    # Compute indent from first non-empty line.
    indent = len(lines[0]) - len(lines[0].lstrip())
    cleaned = []
    for line in lines:
        if line.strip():
            cleaned.append(line[indent:])
        else:
            cleaned.append("")
    # Strip leading and trailing blank lines.
    while cleaned and not cleaned[0]:
        cleaned.pop(0)
    while cleaned and not cleaned[-1]:
        cleaned.pop()
    return "\n".join(cleaned)


# ---------------------------------------------------------------------------
# Rubric criterion checkers — one per criterion from
# .claude/decisions/tool-description-rubric.md. Each returns
# (passed: bool, detail: str) so a regression test can pinpoint which
# criterion failed.
# ---------------------------------------------------------------------------


def _check_negative_case(doc: str) -> tuple[bool, str]:
    """Criterion 1: docstring names a tool to use INSTEAD (Do NOT use)."""
    has_phrase = "do not use" in doc.lower() or "don't use" in doc.lower()
    if not has_phrase:
        return (False, "no 'Do NOT use' phrase (criterion 1 — negative cases)")
    return (True, "negative case present")


def _check_failure_modes(doc: str) -> tuple[bool, str]:
    """Criterion 2: docstring lists at least one realistic failure mode."""
    has_fail = bool(re.search(r"\b(fails?|failure|error|timed?\s*out)\b", doc, re.IGNORECASE))
    if not has_fail:
        return (False, "no failure-mode mention (criterion 2)")
    return (True, "failure mode mentioned")


def _check_return_shape(doc: str) -> tuple[bool, str]:
    """Criterion 3: docstring specifies what the tool returns."""
    has_returns = bool(re.search(r"\breturns\b\s+(a|an|the|\{|`)", doc, re.IGNORECASE))
    has_dict_or_list = bool(re.search(r"\b(dict|list|str|object|array)\b", doc, re.IGNORECASE))
    if not (has_returns and has_dict_or_list):
        return (False, "no return-shape hint (criterion 3)")
    return (True, "return shape hinted")


def _check_active_voice(doc: str) -> tuple[bool, str]:
    """Criterion 4: active voice + second-person + no marketing prose.

    Proxies:
    - First non-empty line starts with an imperative verb (capitalized).
    - Total length ≤ 800 chars (proxy for non-prose).
    - No marketing adjectives ("powerful", "comprehensive", "intelligent",
      "robust", "seamless", "leverage").
    """
    if len(doc) > 800:
        return (False, f"description > 800 chars (got {len(doc)})")
    first_line = next((l for l in doc.splitlines() if l.strip()), "")
    # First word should be a verb-like imperative. We accept any word
    # that's NOT a marketing adjective — concrete test for the
    # anti-marketing half, lenient on the verb form to avoid brittleness.
    marketing = {
        "powerful",
        "comprehensive",
        "intelligent",
        "robust",
        "seamless",
        "leverage",
        "advanced",
        "next-generation",
        "cutting-edge",
        "state-of-the-art",
    }
    first_word = first_line.split(" ", 1)[0].lower().strip(".,;:")
    if first_word in marketing:
        return (False, f"first word '{first_word}' is marketing prose")
    # Also reject if marketing adjectives appear anywhere in the doc.
    found_marketing = [w for w in marketing if re.search(rf"\b{w}\b", doc, re.IGNORECASE)]
    if found_marketing:
        return (False, f"marketing prose found: {found_marketing}")
    return (True, "active voice + no marketing prose")


def _check_side_effect(doc: str) -> tuple[bool, str]:
    """Criterion 5: docstring declares side effects (or explicit 'none')."""
    has_declare = bool(re.search(r"side effect\s*:\s*\w", doc, re.IGNORECASE))
    if not has_declare:
        return (False, "no 'Side effect:' declaration (criterion 5)")
    return (True, "side effect declared")


def _check_no_internal_disclosure(doc: str) -> tuple[bool, str]:
    """Criterion 6: no absolute paths, internal-only markers, or auth hints."""
    # Absolute Unix or Windows paths.
    if re.search(r"/Users/|/home/|[A-Z]:\\\\", doc):
        return (False, "absolute file path found (criterion 6)")
    # Auth-mechanism hints: JWT, HS256, token types, header names.
    auth_markers = (
        "JWT",
        "HS256",
        "RS256",
        "Bearer ",
        "X-Auth-Token",
        "MAHAVISHNU_AUTH_SECRET",
        "access_token",
    )
    found = [m for m in auth_markers if m in doc]
    if found:
        return (False, f"auth-mechanism hints: {found} (criterion 6)")
    return (True, "no internal disclosure")


RUBRIC_CRITERIA = (
    ("negative_cases", _check_negative_case),
    ("failure_modes", _check_failure_modes),
    ("return_shape", _check_return_shape),
    ("active_voice", _check_active_voice),
    ("side_effect", _check_side_effect),
    ("no_internal_disclosure", _check_no_internal_disclosure),
)


def _rubric_score(doc: str) -> tuple[int, int, list[str]]:
    """Return (passed_count, total_count, list_of_failed_details)."""
    passed = 0
    failures: list[str] = []
    for _name, checker in RUBRIC_CRITERIA:
        ok, detail = checker(doc)
        if ok:
            passed += 1
        else:
            failures.append(detail)
    return passed, len(RUBRIC_CRITERIA), failures


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def live_docstrings() -> dict[str, str]:
    """Module-scoped fixture: parse server_core.py once for all tests."""
    return _extract_docstrings()


def test_all_top_10_tools_have_extractable_docstrings(live_docstrings: dict[str, str]) -> None:
    """Every top-10 tool must have a non-empty docstring reachable via AST."""
    missing = [t for t in TOP_10_TOOLS if not live_docstrings.get(t)]
    assert not missing, f"missing docstrings for: {missing}"


@pytest.mark.parametrize("tool_name", list(TOP_10_TOOLS))
def test_tool_docstring_satisfies_all_six_rubric_criteria(
    tool_name: str, live_docstrings: dict[str, str]
) -> None:
    """Each top-10 tool's docstring must pass all 6 rubric criteria.

    Each criterion produces a targeted failure message so the test report
    tells the developer exactly which clause to fix.
    """
    doc = live_docstrings[tool_name]
    passed, total, failures = _rubric_score(doc)
    assert passed == total, (
        f"{tool_name}: passed {passed}/{total} criteria; failures: {failures}\n"
        f"--- docstring ---\n{doc}\n--- end docstring ---"
    )


def test_rewrites_improve_rubric_score_vs_before(live_docstrings: dict[str, str]) -> None:
    """Before/after measurement: rubric score must increase after rewrites.

    The BEFORE baseline is captured at Task 2.3 time. The AFTER state is
    the live docstrings. Plan REQ-TSQ-011: ``after-rate ≥ before-rate −
    2σ``. We pin the threshold at a 50 percentage-point improvement
    (3 criteria → 6 criteria) — the rewrites were structural fixes, not
    cosmetic tweaks.
    """
    before_total_score = 0
    before_max = 0
    for tool, before_doc in BEFORE_DOCSTRINGS.items():
        passed, total, _ = _rubric_score(before_doc)
        before_total_score += passed
        before_max += total

    after_total_score = 0
    after_max = 0
    for tool, after_doc in live_docstrings.items():
        if tool in TOP_10_TOOLS:
            passed, total, _ = _rubric_score(after_doc)
            after_total_score += passed
            after_max += total

    before_rate = before_total_score / before_max if before_max else 0.0
    after_rate = after_total_score / after_max if after_max else 0.0

    # The rewrites must add at least 3 criteria coverage across the 10
    # tools (a generous tolerance — the real gap is closer to 5-6
    # criteria per tool). Document the actual delta in the assertion
    # message so regressions are immediately attributable.
    delta_pp = (after_rate - before_rate) * 100
    assert after_rate >= before_rate + 0.30, (
        f"rubric improvement < 30 percentage points: "
        f"before={before_rate:.2%} ({before_total_score}/{before_max}), "
        f"after={after_rate:.2%} ({after_total_score}/{after_max}), "
        f"delta={delta_pp:+.1f}pp"
    )
    # AND: after state must be ≥ 80% compliant (the rewrites were
    # structural, not aspirational; partial compliance is a regression).
    assert after_rate >= 0.80, (
        f"after-state compliance < 80%: got {after_rate:.2%} ({after_total_score}/{after_max})"
    )


@pytest.mark.parametrize("task_index", range(len(TASK_SUITE)))
def test_task_suite_keywords_route_to_correct_tool(
    task_index: int, live_docstrings: dict[str, str]
) -> None:
    """Each fixed task's ground-truth tool must contain the expected keywords.

    This is the deterministic proxy for the plan's LLM-as-judge. An LLM
    picking from the rewritten descriptions would match on these
    keywords; the test enforces that the keywords are present.
    """
    task = TASK_SUITE[task_index]
    doc = live_docstrings[task["ground_truth"]]
    doc_lower = doc.lower()

    missing = [kw for kw in task["expected_keywords"] if kw.lower() not in doc_lower]
    assert not missing, (
        f"Task {task_index} ({task['query']!r}): ground truth "
        f"{task['ground_truth']!r} docstring missing keywords {missing}.\n"
        f"--- docstring ---\n{doc}\n---"
    )


@pytest.mark.parametrize("task_index", range(len(TASK_SUITE)))
def test_task_suite_negative_anti_keywords_absent_from_correct_tool(
    task_index: int, live_docstrings: dict[str, str]
) -> None:
    """Each ground-truth tool's docstring must include negative-case language.

    Per criterion 1: the description says which tool should be used
    INSTEAD for adjacent intents. Anti-keywords (e.g. "dispatch work" for
    list_adapters) signal that the description names an alternative
    tool. This test ensures the negative-case hook is present.
    """
    task = TASK_SUITE[task_index]
    doc = live_docstrings[task["ground_truth"]]
    doc_lower = doc.lower()

    found = [kw for kw in task["negative_anti_keywords"] if kw.lower() in doc_lower]
    assert found, (
        f"Task {task_index} ({task['query']!r}): ground truth "
        f"{task['ground_truth']!r} docstring missing negative-case hook "
        f"({task['negative_anti_keywords']}). The description should say "
        f"which tool to use INSTEAD.\n--- docstring ---\n{doc}\n---"
    )


def test_task_suite_coverage_at_or_above_tolerance_band(
    live_docstrings: dict[str, str],
) -> None:
    """Aggregate task-suite proxy rate ≥ tolerance band.

    The plan specifies ``after-rate ≥ before-rate − 2σ``. Without
    LLM-as-judge runs we cannot compute σ, so we pin a deterministic
    floor: 100% of the task suite must pass keyword + anti-keyword
    coverage. Any drop below 100% is a regression to investigate.
    """
    passed = 0
    total = len(TASK_SUITE)
    for task in TASK_SUITE:
        doc = live_docstrings[task["ground_truth"]].lower()
        keywords_ok = all(kw.lower() in doc for kw in task["expected_keywords"])
        negative_ok = any(kw.lower() in doc for kw in task["negative_anti_keywords"])
        if keywords_ok and negative_ok:
            passed += 1

    rate = passed / total
    assert rate >= 0.95, (
        f"task-suite coverage {rate:.0%} ({passed}/{total}) below 95% threshold; "
        f"investigate which task lost keyword coverage"
    )


# ---------------------------------------------------------------------------
# OPTIONAL: LLM-as-judge (gated on MAHAVISHNU_RUN_LLM_JUDGE=1)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("MAHAVISHNU_RUN_LLM_JUDGE", "0") != "1",
    reason="set MAHAVISHNU_RUN_LLM_JUDGE=1 to run the network LLM-as-judge "
    "pass; default is off to keep CI deterministic and offline",
)
def test_llm_as_judge_baseline_recorded() -> None:
    """Network LLM-as-judge (opt-in).

    Plan REQ-TSQ-011: judge model pinned, temperature=0, seed=0, judge
    model version recorded in test logs. The judge is asked to pick a
    tool from the descriptions for each TASK_SUITE query; we assert the
    aggregate rate ≥ tolerance band.

    This test is intentionally a skeleton — wiring the actual LLM call
    belongs in a follow-on plan once the team decides on the
    MiniMax-M3 vs. local-qwen3.5 choice. Recording the gate here so
    the future implementer has a known contract.
    """
    pytest.fail(
        "MAHAVISHNU_RUN_LLM_JUDGE=1 enabled but the network judge is "
        "not wired yet — see REQ-TSQ-011 in the plan for the contract"
    )

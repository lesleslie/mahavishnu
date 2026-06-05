"""Tests for ``scripts/check_ecosystem_gitignores.py``.

The audit script is what enforces the convention that every Bodai
ecosystem repo has the right ``.claude`` rule in its ``.gitignore``.
Two design choices are pinned here so future edits don't silently
weaken the rule:

1. **Shared-content classification.** A repo that holds project content
   in ``.claude/`` (``agents/``, ``commands/``, ``skills/`` ...) must
   use SELECTIVE ``.gitignore`` rules. A blanket ``.claude/`` would
   hide the catalog and is a FAIL, not a WARN.

2. **Section title detection.** The parser recognises both
   "decorative" (mahavishnu-style) and "plain" (oneiric-style)
   section headers. A multi-line descriptive comment mid-section is
   NOT treated as a header — otherwise the report would say
   ``[settings.local.json, CLAUDE.md); ignore runtime-only ...]``
   instead of the actual section name.
"""

from __future__ import annotations

import json
from pathlib import Path

# ``scripts/`` is on ``sys.path`` at test time (see root ``conftest.py``)
from check_ecosystem_gitignores import (  # noqa: E402
    ClaudeDirState,
    ClaudeIgnoreState,
    _BLANKET_CLAUDE_PATTERNS,
    classify_claude_dir,
    evaluate_repo,
    parse_claude_ignore,
    parse_gitignore_sections,
    render_json_report,
    render_text_report,
    resolve_repos,
)


# ---------------------------------------------------------------------------
# classify_claude_dir
# ---------------------------------------------------------------------------


def test_classify_claude_dir_missing(tmp_path: Path) -> None:
    """A repo with no ``.claude/`` returns present=False and empty lists."""
    state = classify_claude_dir(tmp_path)
    assert state == ClaudeDirState(present=False, shared_subdirs=[], runtime_entries=[])


def test_classify_claude_dir_runtime_only(tmp_path: Path) -> None:
    """``settings.local.json`` alone is runtime-only, no shared hits."""
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.local.json").touch()
    state = classify_claude_dir(tmp_path)
    assert state.present is True
    assert state.shared_subdirs == []
    assert state.runtime_entries == ["settings.local.json"]


def test_classify_claude_dir_shared_catalog(tmp_path: Path) -> None:
    """``agents/`` and ``commands/`` are shared catalog content."""
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "agents").mkdir()
    (tmp_path / ".claude" / "commands").mkdir()
    (tmp_path / ".claude" / "handoff").mkdir()
    (tmp_path / ".claude" / "settings.json").touch()
    state = classify_claude_dir(tmp_path)
    assert state.shared_subdirs == ["agents", "commands"]
    # handoff is a dir but not in SHARED_CLAUDE_SUBDIRS → runtime.
    # settings.json is a file → runtime.
    assert sorted(state.runtime_entries) == ["handoff", "settings.json"]


def test_classify_claude_dir_empty_dir(tmp_path: Path) -> None:
    """An empty ``.claude/`` returns present=True with empty lists."""
    (tmp_path / ".claude").mkdir()
    state = classify_claude_dir(tmp_path)
    assert state.present is True
    assert state.shared_subdirs == []
    assert state.runtime_entries == []


# ---------------------------------------------------------------------------
# parse_gitignore_sections
# ---------------------------------------------------------------------------


def test_parse_sections_no_headers() -> None:
    """A bare-file gitignore returns a single ``(no header)`` section."""
    sections = parse_gitignore_sections("__pycache__/\n*.pyc\n")
    assert len(sections) == 1
    name, patterns = sections[0]
    assert name == "(no header)"
    assert patterns == ["__pycache__/", "*.pyc"]


def test_parse_sections_plain_header_style(tmp_path: Path) -> None:
    """oneiric-style: single comment line, no decorative dividers."""
    text = (
        "# Python-generated files\n"
        "__pycache__/\n"
        "*.pyc\n"
        "\n"
        "# Virtual environments\n"
        ".venv/\n"
    )
    sections = parse_gitignore_sections(text)
    assert [n for n, _ in sections] == [
        "Python-generated files",
        "Virtual environments",
    ]
    assert sections[0][1] == ["__pycache__/", "*.pyc"]
    assert sections[1][1] == [".venv/"]


def test_parse_sections_decorative_header_style() -> None:
    """mahavishnu-style: comment flanked by ``# ====`` dividers."""
    text = (
        "# ============================================================================\n"
        "# Python - Unit Test / Coverage Reports\n"
        "# ============================================================================\n"
        ".coverage\n"
        "htmlcov/\n"
        "\n"
        "# ============================================================================\n"
        "# Claude Code Project-Specific Data\n"
        "# ============================================================================\n"
        ".claude/handoff/\n"
    )
    sections = parse_gitignore_sections(text)
    assert [n for n, _ in sections] == [
        "Python - Unit Test / Coverage Reports",
        "Claude Code Project-Specific Data",
    ]
    assert sections[0][1] == [".coverage", "htmlcov/"]
    assert sections[1][1] == [".claude/handoff/"]


def test_parse_sections_multi_line_descriptive_comment_not_a_title() -> None:
    """A descriptive comment block mid-section is not a section header.

    Regression: previously the parser treated every ``# ...`` line as
    a potential header, which would split the actual section and
    surface a long descriptive comment as the "section name" in
    reports.
    """
    text = (
        "# ============================================================================\n"
        "# Claude Code Project-Specific Data\n"
        "# ============================================================================\n"
        "# Track canonical config (agents, skills, commands, CLAUDE.md, mcp-hooks.json,\n"
        "# settings.local.json, CLAUDE.md); ignore runtime-only and secret-adjacent dirs.\n"
        ".claude/settings.json\n"
        ".claude/handoff/\n"
    )
    sections = parse_gitignore_sections(text)
    # Only ONE section — the descriptive comment is part of the same section.
    assert len(sections) == 1
    name, patterns = sections[0]
    assert name == "Claude Code Project-Specific Data"
    assert patterns == [".claude/settings.json", ".claude/handoff/"]


def test_parse_sections_decorative_dash_dividers() -> None:
    """``# ----`` dividers work too, not just ``# ====``."""
    text = (
        "# ----------------------------------------\n"
        "# Section A\n"
        "# ----------------------------------------\n"
        "pattern_a\n"
    )
    sections = parse_gitignore_sections(text)
    assert [n for n, _ in sections] == ["Section A"]


# ---------------------------------------------------------------------------
# parse_claude_ignore
# ---------------------------------------------------------------------------


def test_parse_claude_ignore_blanket() -> None:
    state = parse_claude_ignore(".claude/\nfoo/\n")
    assert state.has_blanket is True
    assert state.has_exception is False
    assert state.selective_paths == []


def test_parse_claude_ignore_blanket_wildcard() -> None:
    state = parse_claude_ignore(".claude/*\n")
    assert state.has_blanket is True
    assert state.has_exception is False


def test_parse_claude_ignore_blanket_with_exception() -> None:
    """``.claude/*`` + ``!.claude/settings.json`` is blanket+exception."""
    state = parse_claude_ignore(".claude/*\n!.claude/settings.json\n")
    assert state.has_blanket is True
    assert state.has_exception is True
    assert state.selective_paths == []


def test_parse_claude_ignore_selective_single() -> None:
    state = parse_claude_ignore(".claude/handoff/\n.claude/backups/\n")
    assert state.has_blanket is False
    assert state.has_exception is False
    assert state.selective_paths == [".claude/handoff/", ".claude/backups/"]


def test_parse_claude_ignore_selective_nested() -> None:
    """Nested subpaths like ``.claude/hooks/scripts/`` are selective."""
    state = parse_claude_ignore(".claude/hooks/scripts/\n")
    assert state.has_blanket is False
    assert state.selective_paths == [".claude/hooks/scripts/"]


def test_parse_claude_ignore_selective_glob_segment() -> None:
    """``*`` inside the subpath is allowed (e.g. ``.claude/skills/*/.archive/``)."""
    state = parse_claude_ignore(".claude/skills/*/.archive/\n")
    assert state.selective_paths == [".claude/skills/*/.archive/"]


def test_parse_claude_ignore_file_not_subpath() -> None:
    """``.claude/settings.json`` is a file rule, not a subpath ignore."""
    state = parse_claude_ignore(".claude/settings.json\n!.claude/settings.json\n")
    assert state.has_blanket is False
    assert state.has_exception is True
    assert state.selective_paths == []


def test_parse_claude_ignore_no_claude_rules() -> None:
    state = parse_claude_ignore("__pycache__/\n*.pyc\n")
    assert state.has_blanket is False
    assert state.has_exception is False
    assert state.selective_paths == []


# ---------------------------------------------------------------------------
# evaluate_repo — the verdict tree
# ---------------------------------------------------------------------------


def _write_gitignore(repo: Path, body: str) -> None:
    (repo / ".gitignore").write_text(body)


def test_evaluate_repo_skip_no_claude_dir(tmp_path: Path) -> None:
    v = evaluate_repo("x", tmp_path)
    assert v.status == "SKIP"
    assert v.issue == "No .claude/ directory present"


def test_evaluate_repo_fail_missing_gitignore(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()
    v = evaluate_repo("x", tmp_path)
    assert v.status == "FAIL"
    assert "missing" in (v.issue or "").lower()


def test_evaluate_repo_fail_shared_with_blanket(tmp_path: Path) -> None:
    """mahavishnu-style repo with a blanket rule is FAIL."""
    (tmp_path / ".claude" / "agents").mkdir(parents=True)
    (tmp_path / ".claude" / "commands").mkdir(parents=True)
    _write_gitignore(tmp_path, "# XDG - State directories\n.claude/\n")
    v = evaluate_repo("x", tmp_path)
    assert v.status == "FAIL"
    assert "Blanket" in (v.issue or "")
    assert "agents" in (v.issue or "") and "commands" in (v.issue or "")


def test_evaluate_repo_pass_shared_with_selective(tmp_path: Path) -> None:
    """mahavishnu-style repo with selective rule is PASS."""
    (tmp_path / ".claude" / "agents").mkdir(parents=True)
    (tmp_path / ".claude" / "handoff").mkdir(parents=True)
    _write_gitignore(
        tmp_path,
        "# Claude Code Project-Specific Data\n.claude/handoff/\n",
    )
    v = evaluate_repo("x", tmp_path)
    assert v.status == "PASS"
    assert v.matched_rule == ".claude/handoff/"
    assert v.section == "Claude Code Project-Specific Data"


def test_evaluate_repo_pass_runtime_with_blanket(tmp_path: Path) -> None:
    """akosha-style repo with blanket rule is PASS."""
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.local.json").touch()
    _write_gitignore(tmp_path, "# XDG - State directories\n.claude/\n")
    v = evaluate_repo("x", tmp_path)
    assert v.status == "PASS"
    assert v.matched_rule == ".claude/"
    assert v.section == "XDG - State directories"


def test_evaluate_repo_pass_runtime_with_blanket_and_exception(tmp_path: Path) -> None:
    """session-buddy-style blanket+exception is PASS for runtime-only repos."""
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").touch()
    (tmp_path / ".claude" / "handoff").mkdir()
    _write_gitignore(
        tmp_path,
        "# XDG - State directories\n.claude/*\n!.claude/settings.json\n",
    )
    v = evaluate_repo("x", tmp_path)
    assert v.status == "PASS"
    assert v.matched_rule == ".claude/*"


def test_evaluate_repo_fail_runtime_no_rule(tmp_path: Path) -> None:
    """Runtime-only repo with no .claude rule is FAIL."""
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.local.json").touch()
    _write_gitignore(tmp_path, "__pycache__/\n*.pyc\n")
    v = evaluate_repo("x", tmp_path)
    assert v.status == "FAIL"
    assert "settings.local.json" in (v.issue or "")


def test_evaluate_repo_fail_shared_no_rule(tmp_path: Path) -> None:
    """Shared-content repo with no .claude rule at all is FAIL."""
    (tmp_path / ".claude" / "agents").mkdir(parents=True)
    (tmp_path / ".claude" / "commands").mkdir(parents=True)
    _write_gitignore(tmp_path, "__pycache__/\n*.pyc\n")
    v = evaluate_repo("x", tmp_path)
    assert v.status == "FAIL"
    assert "agents" in (v.issue or "")


# ---------------------------------------------------------------------------
# render_text_report / render_json_report
# ---------------------------------------------------------------------------


def _make_verdict(name, status, **overrides):
    """Build a minimal Verdict for render tests."""
    from check_ecosystem_gitignores import Verdict

    return Verdict(
        name=name,
        repo=Path(f"/fake/{name}"),
        claude_state=overrides.get(
            "claude_state",
            ClaudeDirState(present=True, shared_subdirs=[], runtime_entries=[]),
        ),
        ignore_state=overrides.get(
            "ignore_state",
            ClaudeIgnoreState(
                has_blanket=False, has_exception=False, selective_paths=[], sections=[]
            ),
        ),
        status=status,
        matched_rule=overrides.get("matched_rule"),
        section=overrides.get("section"),
        issue=overrides.get("issue"),
    )


def test_render_text_report_counts_per_status() -> None:
    verdicts = [
        _make_verdict("a", "PASS", matched_rule=".claude/handoff/", section="X"),
        _make_verdict("b", "PASS", matched_rule=".claude/"),
        _make_verdict("c", "FAIL", issue="missing rule"),
        _make_verdict("d", "SKIP", issue="No .claude/ directory present"),
    ]
    out = render_text_report(verdicts)
    assert "2 PASS" in out
    assert "1 FAIL" in out
    assert "1 SKIP" in out
    assert "4 repos checked" in out


def test_render_json_report_shape() -> None:
    verdicts = [
        _make_verdict("a", "PASS", matched_rule=".claude/handoff/", section="X"),
        _make_verdict("b", "FAIL", issue="missing"),
    ]
    out = render_json_report(verdicts)
    payload = json.loads(out)
    assert payload["ecosystem"] == "Bodai"
    assert payload["summary"] == {"total": 2, "pass": 1, "warn": 0, "fail": 1, "skip": 0}
    assert payload["repos"][0]["status"] == "PASS"
    assert payload["repos"][0]["matched_rule"] == ".claude/handoff/"
    assert payload["repos"][1]["status"] == "FAIL"
    assert payload["repos"][1]["issue"] == "missing"


# ---------------------------------------------------------------------------
# resolve_repos
# ---------------------------------------------------------------------------


def test_resolve_repos_default_expands_user() -> None:
    """Default repos use ``~`` which must expand, not be a literal."""
    repos = resolve_repos(None)
    assert all(not str(path).startswith("~") for _, path in repos)
    # And every default has a non-empty name.
    assert all(name for name, _ in repos)


def test_resolve_repos_explicit_name_path() -> None:
    repos = resolve_repos(["custom:~/Projects/custom"])
    assert repos[0][0] == "custom"
    assert not str(repos[0][1]).startswith("~")


def test_resolve_repos_explicit_path_only() -> None:
    """A bare path uses the directory's basename as the label."""
    repos = resolve_repos(["/Users/les/Projects/somewhere"])
    assert repos[0][0] == "somewhere"

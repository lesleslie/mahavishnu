"""Tests for ``scripts/validate_document_frontmatter.py``.

``scripts/`` is added to ``sys.path`` by the root ``conftest.py`` so we can
import the validator module directly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from validate_document_frontmatter import (
    FileResult,
    Issue,
    _print_json,
    discover_files,
    validate_file,
)

# ---------------------------------------------------------------------------
# Shared fixtures & helpers
# ---------------------------------------------------------------------------

# Minimum valid full-schema frontmatter. Tests mutate copies of this string to
# derive invalid variants so the scaffolding stays consistent. Dates are
# quoted so YAML keeps them as strings rather than auto-converting to
# ``datetime.date`` (which the validator's ``isinstance(value, str)`` check
# would then reject).
MINIMAL_VALID_FULL = (
    "---\n"
    "status: active\n"
    "role: canonical\n"
    'date: "2026-07-16"\n'
    'last_reviewed: "2026-07-16"\n'
    "topic: mcp-design\n"
    "---\n\n"
    "# Document body\n"
)

# Lite schema is identical for the required keys — the difference is the path
# (.claude/decisions/) which the validator infers from the relative path.
MINIMAL_VALID_LITE = MINIMAL_VALID_FULL


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Create a fake repo layout mirroring the six default Bodai stores."""
    for store in (
        "docs/adr",
        "docs/plans/drafts",
        "docs/superpowers/specs",
        "docs/superpowers/plans",
        ".claude/decisions",
        "docs/followups",
    ):
        (tmp_path / store).mkdir(parents=True, exist_ok=True)
    return tmp_path


def _write(repo_root: Path, rel: str, content: str) -> Path:
    """Write ``content`` at ``repo_root/rel`` and return the absolute path."""
    abs_path = repo_root / rel
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text(content, encoding="utf-8")
    return abs_path


def _validate(
    repo_root: Path,
    abs_path: Path,
    rel: str,
    *,
    strict: bool = False,
    allow_nonstandard: bool = False,
    validate_links: bool = False,
    skip_link_note: bool = False,
    known_files: set[str] | None = None,
    known_topics: set[str] | None = None,
) -> FileResult:
    """Slim wrapper around ``validate_file`` that fills in repo_root."""
    return validate_file(
        abs_path,
        rel,
        repo_root=repo_root,
        known_files=known_files if known_files is not None else set(),
        known_topics=known_topics if known_topics is not None else set(),
        strict=strict,
        allow_nonstandard=allow_nonstandard,
        validate_links=validate_links,
        skip_link_note=skip_link_note,
    )


# ---------------------------------------------------------------------------
# 1-2: Valid frontmatter
# ---------------------------------------------------------------------------


def test_valid_full_frontmatter_passes(repo: Path) -> None:
    """Minimal correct metadata, no errors, no warnings."""
    rel = "docs/adr/sample.md"
    f = _write(repo, rel, MINIMAL_VALID_FULL)
    result = _validate(repo, f, rel)
    assert result.status == "ok"
    assert result.errors == []
    assert result.warnings == []


def test_valid_lite_decision_frontmatter_passes(repo: Path) -> None:
    """Decisions file with no superseded_by/blocks_on — lite schema."""
    rel = ".claude/decisions/sample.md"
    f = _write(repo, rel, MINIMAL_VALID_LITE)
    result = _validate(repo, f, rel)
    assert result.status == "ok"
    assert result.errors == []
    assert result.warnings == []


# ---------------------------------------------------------------------------
# 3-8: Per-rule validation failures
# ---------------------------------------------------------------------------


def test_missing_frontmatter_reported(repo: Path) -> None:
    """File without --- block at top should report MISSING_FRONTMATTER."""
    rel = "docs/adr/no-frontmatter.md"
    f = _write(repo, rel, "# Title\n\nBody with no frontmatter.\n")
    result = _validate(repo, f, rel)
    assert result.status == "missing"
    assert any(i.rule == "MISSING_FRONTMATTER" for i in result.errors)


def test_invalid_lifecycle_rejected(repo: Path) -> None:
    """status: foo is not in the lifecycle vocabulary."""
    rel = "docs/adr/bad-status.md"
    bad = MINIMAL_VALID_FULL.replace("status: active", "status: foo")
    f = _write(repo, rel, bad)
    result = _validate(repo, f, rel)
    assert any(i.rule == "status_invalid" for i in result.errors)


def test_legacy_lifecycle_rejected(repo: Path) -> None:
    """status: Accepted (capitalized, legacy value) is rejected."""
    rel = "docs/adr/legacy-status.md"
    bad = MINIMAL_VALID_FULL.replace("status: active", "status: Accepted")
    f = _write(repo, rel, bad)
    result = _validate(repo, f, rel)
    assert any(i.rule == "status_invalid" for i in result.errors)


def test_legacy_resolved_coerced_to_complete(repo: Path) -> None:
    """BUG 3 fix: legacy 'Resolved' (case-insensitive, optional trailing '.')
    is coerced to canonical 'complete' before validation, so no
    status_invalid error is emitted.
    """
    for legacy in ("Resolved", "resolved", "RESOLVED", "Resolved.", "resolved."):
        rel = f"docs/followups/{legacy.replace('.', '_')}.md"
        body = MINIMAL_VALID_FULL.replace("status: active", f"status: {legacy}")
        f = _write(repo, rel, body)
        result = _validate(repo, f, rel)
        assert not any(
            i.rule == "status_invalid" for i in result.errors
        ), f"{legacy!r} should coerce to 'complete' but produced status_invalid"


def test_invalid_role_rejected(repo: Path) -> None:
    """role: authoritative is not in the role vocabulary."""
    rel = "docs/adr/bad-role.md"
    bad = MINIMAL_VALID_FULL.replace("role: canonical", "role: authoritative")
    f = _write(repo, rel, bad)
    result = _validate(repo, f, rel)
    assert any(i.rule == "role_invalid" for i in result.errors)


def test_invalid_date_format_rejected(repo: Path) -> None:
    """date: 2026/07/16 is not ISO-8601 YYYY-MM-DD."""
    rel = "docs/adr/bad-date.md"
    bad = MINIMAL_VALID_FULL.replace('date: "2026-07-16"', 'date: "2026/07/16"')
    f = _write(repo, rel, bad)
    result = _validate(repo, f, rel)
    assert any(i.rule == "date_invalid" for i in result.errors)


def test_invalid_topic_format_rejected(repo: Path) -> None:
    """topic: 'TUI Design' has uppercase + space — fails slug regex."""
    rel = "docs/adr/bad-topic.md"
    bad = MINIMAL_VALID_FULL.replace("topic: mcp-design", "topic: TUI Design")
    f = _write(repo, rel, bad)
    result = _validate(repo, f, rel)
    assert any(i.rule == "topic_invalid" for i in result.errors)


def test_unknown_topic_warns_only(repo: Path) -> None:
    """topic not in vocab: WARNING without --strict, ERROR with --strict."""
    rel = "docs/adr/unknown-topic.md"
    bad = MINIMAL_VALID_FULL.replace("topic: mcp-design", "topic: rocket-foo")
    f = _write(repo, rel, bad)

    # The validator only emits topic_unknown when known_topics is non-empty
    # AND the topic isn't in it. Seed a vocab that intentionally excludes
    # ``rocket-foo``.
    vocab = {"mcp-design", "some-other-topic"}

    loose = _validate(repo, f, rel, strict=False, known_topics=vocab)
    assert any(
        i.rule == "topic_unknown" and i.severity == "WARNING"
        for i in loose.warnings
    )
    assert not any(i.rule == "topic_unknown" for i in loose.errors)

    strict = _validate(repo, f, rel, strict=True, known_topics=vocab)
    assert any(
        i.rule == "topic_unknown" and i.severity == "ERROR"
        for i in strict.errors
    )


def test_topic_reserved_word_rejected(repo: Path) -> None:
    """topic: 'active' collides with a lifecycle word — always rejected."""
    rel = "docs/adr/reserved-topic.md"
    bad = MINIMAL_VALID_FULL.replace("topic: mcp-design", "topic: active")
    f = _write(repo, rel, bad)
    result = _validate(repo, f, rel)
    assert any(i.rule == "topic_reserved" for i in result.errors)


# ---------------------------------------------------------------------------
# 11-13: superseded_by / blocks_on link validation
# ---------------------------------------------------------------------------


def test_superseded_by_link_validation_skipped_by_default(repo: Path) -> None:
    """Broken superseded_by link: no error unless --validate-links is on."""
    rel = "docs/adr/old-doc.md"
    body = MINIMAL_VALID_FULL.replace(
        "topic: mcp-design\n",
        "topic: mcp-design\nsuperseded_by: docs/adr/does-not-exist.md\n",
    )
    f = _write(repo, rel, body)

    # Default: validate_links=False, skip_link_note=True
    result = _validate(repo, f, rel, validate_links=False, skip_link_note=True)
    assert not any(i.rule == "superseded_by_unresolved" for i in result.errors)


def test_superseded_by_link_validation_resolves(repo: Path) -> None:
    """With --validate-links, a broken superseded_by triggers an error."""
    rel = "docs/adr/old-doc.md"
    body = MINIMAL_VALID_FULL.replace(
        "topic: mcp-design\n",
        "topic: mcp-design\nsuperseded_by: docs/adr/does-not-exist.md\n",
    )
    f = _write(repo, rel, body)

    result = _validate(
        repo,
        f,
        rel,
        validate_links=True,
        known_files={"docs/adr/other.md"},
    )
    assert any(
        i.rule == "superseded_by_unresolved" for i in result.errors
    )


def test_blocks_on_accepts_ext_identifier(repo: Path) -> None:
    """blocks_on entries of the form ext:<id> pass without filesystem checks."""
    rel = "docs/adr/dependent-doc.md"
    body = MINIMAL_VALID_FULL.replace(
        "topic: mcp-design\n",
        "topic: mcp-design\nblocks_on:\n  - ext:dhara-async-migration\n",
    )
    f = _write(repo, rel, body)

    # With validate_links=True, only filesystem paths would be checked.
    # ext: identifiers must always pass.
    result = _validate(
        repo, f, rel, validate_links=True, known_files=set()
    )
    assert not any(i.rule == "blocks_on_unresolved" for i in result.errors)


def test_superseded_by_accepts_list_form(repo: Path) -> None:
    """BUG 2 fix: superseded_by accepts a YAML list of paths/ext:<id>.

    Each list entry must resolve to a known file or ext:<id>; broken entries
    produce superseded_by_unresolved errors.
    """
    rel = "docs/adr/multi-supersede.md"
    body = MINIMAL_VALID_FULL.replace(
        "topic: mcp-design\n",
        "topic: mcp-design\nsuperseded_by:\n"
        "  - ext:dhara-async-migration\n"
        "  - docs/adr/does-not-exist.md\n",
    )
    f = _write(repo, rel, body)

    # ext: entries pass; the broken path entry produces an error.
    result = _validate(
        repo,
        f,
        rel,
        validate_links=True,
        known_files={"docs/adr/other.md"},
    )
    assert not any(
        i.rule == "superseded_by_invalid" for i in result.errors
    )
    # The known ext:<id> does not produce an unresolved error.
    assert not any(
        i.rule == "superseded_by_unresolved"
        and "ext:dhara-async-migration" in i.message
        for i in result.errors
    )
    # The bogus path does produce an unresolved error.
    assert any(
        i.rule == "superseded_by_unresolved"
        and "does-not-exist.md" in i.message
        for i in result.errors
    )


# ---------------------------------------------------------------------------
# 14-16: File discovery exclusions
# ---------------------------------------------------------------------------


def test_plan_index_excluded(repo: Path) -> None:
    """docs/plans/PLAN_INDEX.md never appears in scan results."""
    rel = "docs/plans/PLAN_INDEX.md"
    idx = _write(repo, rel, MINIMAL_VALID_FULL)

    files = discover_files(repo, [repo / "docs/plans/"], [idx])
    rels = [r for _, r in files]
    assert "docs/plans/PLAN_INDEX.md" not in rels


def test_drafts_directory_excluded(repo: Path) -> None:
    """Files under docs/plans/drafts/ never appear in scan results."""
    _write(repo, "docs/plans/drafts/draft1.md", MINIMAL_VALID_FULL)
    _write(repo, "docs/plans/drafts/nested/draft2.md", MINIMAL_VALID_FULL)

    files = discover_files(repo, [repo / "docs/plans/"], [])
    rels = [r for _, r in files]
    assert not any(r.startswith("docs/plans/drafts/") for r in rels)


def test_archive_subdirectory_excluded(repo: Path) -> None:
    """BUG 1 fix: any path with an 'archive' or '.archive' segment is excluded.

    Mirrors the docs/plans/drafts/ exclusion but applies to every store
    (e.g. docs/followups/.archive/*, docs/adr/.archive/*).
    """
    _write(repo, "docs/followups/.archive/old.md", MINIMAL_VALID_FULL)
    _write(repo, "docs/followups/archive/old2.md", MINIMAL_VALID_FULL)
    _write(repo, "docs/followups/nested/.archive/deep.md", MINIMAL_VALID_FULL)
    _write(repo, "docs/followups/keep.md", MINIMAL_VALID_FULL)

    files = discover_files(repo, [repo / "docs/followups/"], [])
    rels = [r for _, r in files]
    assert "docs/followups/keep.md" in rels
    assert not any(".archive" in r.split("/") for r in rels)
    assert not any("archive" in r.split("/") for r in rels)


def test_backup_files_excluded(repo: Path) -> None:
    """*.backup and *.backup.json are excluded from scan results."""
    _write(repo, "docs/adr/keep.md", MINIMAL_VALID_FULL)
    _write(repo, "docs/adr/keep.md.backup", MINIMAL_VALID_FULL)
    _write(repo, "docs/adr/keep.md.backup.json", MINIMAL_VALID_FULL)

    files = discover_files(repo, [repo / "docs/adr/"], [])
    rels = [r for _, r in files]
    assert "docs/adr/keep.md" in rels
    assert "docs/adr/keep.md.backup" not in rels
    assert "docs/adr/keep.md.backup.json" not in rels


# ---------------------------------------------------------------------------
# 17: Nonstandard inline status
# ---------------------------------------------------------------------------


def test_allow_nonstandard_suppresses_inline_warnings(repo: Path) -> None:
    """Inline ## Status block warns by default, silent with --allow-nonstandard."""
    rel = "docs/adr/with-inline-status.md"
    body = (
        MINIMAL_VALID_FULL
        + "\n## Status\n\n**Status:** inline nonstandard block\n"
    )
    f = _write(repo, rel, body)

    strict = _validate(repo, f, rel, allow_nonstandard=False)
    assert any(
        i.rule == "NONSTANDARD_INLINE_STATUS" for i in strict.warnings
    )

    relaxed = _validate(repo, f, rel, allow_nonstandard=True)
    assert not any(
        i.rule == "NONSTANDARD_INLINE_STATUS" for i in relaxed.warnings
    )


# ---------------------------------------------------------------------------
# 18: CLI JSON output
# ---------------------------------------------------------------------------


def test_json_output_structure(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``--json`` produces a parseable JSON document describing each file."""
    rel = "docs/adr/json-roundtrip.md"
    f = _write(repo, rel, MINIMAL_VALID_FULL)
    result = _validate(repo, f, rel)

    _print_json([result])
    captured = capsys.readouterr()

    # Output must be parseable JSON.
    parsed = json.loads(captured.out)
    assert isinstance(parsed, list)
    assert len(parsed) == 1

    entry = parsed[0]
    assert set(entry.keys()) == {"path", "status", "errors", "warnings"}
    assert entry["path"] == "docs/adr/json-roundtrip.md"
    assert entry["status"] == "ok"
    assert entry["errors"] == []
    assert entry["warnings"] == []

    # Round-trip: every Issue carries severity/rule/message.
    assert all(
        {"severity", "rule", "message"} <= set(issue.keys())
        for issue in entry["errors"] + entry["warnings"]
    ) or (entry["errors"] == [] and entry["warnings"] == [])

"""Tests for scripts/audit_doc_frontmatter.py — the frontmatter conformance gate."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.audit_doc_frontmatter import (
    SCHEMA_STORES,
    Problem,
    audit_frontmatter,
    audit_store,
    check_frontmatter,
    format_problems,
    main,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[3]

CLEAN_FRONTMATTER = """\
---
status: active
role: canonical
kind: decision
date: 2026-11-05
last_reviewed: 2026-11-05
superseded_by: null
topic: audit-fixture
---

# Fixture
"""


def _write(root: Path, rel: str, body: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _codes(problems: list) -> list[str]:
    return [problem.code for problem in problems]


def test_clean_frontmatter_reports_no_problems(tmp_path: Path) -> None:
    path = _write(tmp_path, "docs/decisions/clean.md", CLEAN_FRONTMATTER)
    assert check_frontmatter(path, "docs/decisions/clean.md") == []


def test_missing_frontmatter_is_reported(tmp_path: Path) -> None:
    path = _write(tmp_path, "docs/decisions/none.md", "# No frontmatter here\n")
    problems = check_frontmatter(path, "docs/decisions/none.md")
    assert _codes(problems) == ["frontmatter_missing"]


def test_unparseable_frontmatter_is_distinguished_from_missing(tmp_path: Path) -> None:
    """A value starting with a backtick is not a valid YAML plain scalar.

    This is the exact shape that made a live decision vanish from the
    index: the renderer skips unparsable frontmatter silently, so it
    looked identical to having no frontmatter at all.
    """
    body = (
        "---\n"
        "description: ``mahavishnu.pools.RunPodPool`` uses ``req.output()``.\n"
        "---\n"
        "\n"
        "# Fixture\n"
    )
    path = _write(tmp_path, "docs/decisions/malformed.md", body)
    problems = check_frontmatter(path, "docs/decisions/malformed.md")
    assert _codes(problems) == ["frontmatter_malformed"]


@pytest.mark.parametrize(
    "missing_key", ["status", "role", "date", "last_reviewed", "topic"]
)
def test_each_required_key_is_required(tmp_path: Path, missing_key: str) -> None:
    lines = CLEAN_FRONTMATTER.splitlines()
    kept = [line for line in lines if not line.startswith(f"{missing_key}:")]
    body = "\n".join(kept) + "\n"
    path = _write(tmp_path, "docs/decisions/missing-key.md", body)
    problems = check_frontmatter(path, "docs/decisions/missing-key.md")
    assert "key_missing" in _codes(problems)


def test_status_outside_the_lifecycle_vocabulary_is_rejected(tmp_path: Path) -> None:
    body = CLEAN_FRONTMATTER.replace("status: active", "status: accepted")
    path = _write(tmp_path, "docs/decisions/bad-status.md", body)
    problems = check_frontmatter(path, "docs/decisions/bad-status.md")
    assert "status_invalid" in _codes(problems)


def test_role_outside_the_role_vocabulary_is_rejected(tmp_path: Path) -> None:
    body = CLEAN_FRONTMATTER.replace("role: canonical", "role: owner")
    path = _write(tmp_path, "docs/decisions/bad-role.md", body)
    problems = check_frontmatter(path, "docs/decisions/bad-role.md")
    assert "role_invalid" in _codes(problems)


def test_kind_outside_the_kind_vocabulary_is_rejected(tmp_path: Path) -> None:
    body = CLEAN_FRONTMATTER.replace("kind: decision", "kind: migration-design")
    path = _write(tmp_path, "docs/decisions/bad-kind.md", body)
    problems = check_frontmatter(path, "docs/decisions/bad-kind.md")
    assert "kind_invalid" in _codes(problems)


def test_spec_and_followup_kinds_are_in_the_vocabulary(tmp_path: Path) -> None:
    for kind in ("spec", "followup"):
        body = CLEAN_FRONTMATTER.replace("kind: decision", f"kind: {kind}")
        path = _write(tmp_path, f"docs/specs/{kind}.md", body)
        assert check_frontmatter(path, f"docs/specs/{kind}.md") == [], kind


def test_topic_must_be_a_kebab_case_slug(tmp_path: Path) -> None:
    body = CLEAN_FRONTMATTER.replace("topic: audit-fixture", "topic: Not A Slug")
    path = _write(tmp_path, "docs/decisions/bad-topic.md", body)
    problems = check_frontmatter(path, "docs/decisions/bad-topic.md")
    assert "topic_invalid" in _codes(problems)


def test_non_iso_date_is_rejected(tmp_path: Path) -> None:
    body = CLEAN_FRONTMATTER.replace("date: 2026-11-05", "date: November 5th")
    path = _write(tmp_path, "docs/decisions/bad-date.md", body)
    problems = check_frontmatter(path, "docs/decisions/bad-date.md")
    assert "date_invalid" in _codes(problems)


def test_superseded_role_requires_a_successor(tmp_path: Path) -> None:
    body = CLEAN_FRONTMATTER.replace("role: canonical", "role: superseded")
    path = _write(tmp_path, "docs/decisions/orphan-superseded.md", body)
    problems = check_frontmatter(path, "docs/decisions/orphan-superseded.md")
    assert "superseded_mismatch" in _codes(problems)


def test_successor_requires_the_superseded_role(tmp_path: Path) -> None:
    body = CLEAN_FRONTMATTER.replace(
        "superseded_by: null", "superseded_by: docs/plans/next.md"
    )
    path = _write(tmp_path, "docs/decisions/pointer-without-role.md", body)
    problems = check_frontmatter(path, "docs/decisions/pointer-without-role.md")
    assert "superseded_mismatch" in _codes(problems)


def test_superseded_role_with_a_successor_is_accepted(tmp_path: Path) -> None:
    body = CLEAN_FRONTMATTER.replace("role: canonical", "role: superseded").replace(
        "superseded_by: null", "superseded_by: docs/plans/next.md"
    )
    path = _write(tmp_path, "docs/decisions/properly-superseded.md", body)
    assert check_frontmatter(path, "docs/decisions/properly-superseded.md") == []


def test_archived_files_are_not_audited(tmp_path: Path) -> None:
    _write(tmp_path, "docs/plans/.archive/old.md", "# No frontmatter\n")
    _write(tmp_path, "docs/specs/.archive/old.md", "---\nbroken: [\n---\n")
    assert audit_store(tmp_path, "docs/plans/") == []
    assert audit_store(tmp_path, "docs/specs/") == []


def test_absent_store_is_not_an_error(tmp_path: Path) -> None:
    assert audit_store(tmp_path, "docs/decisions/") == []


def test_audit_frontmatter_walks_every_schema_store(tmp_path: Path) -> None:
    _write(tmp_path, "docs/decisions/bad.md", "# No frontmatter\n")
    problems = audit_frontmatter(tmp_path)
    assert len(problems) == 1
    assert problems[0].path == "docs/decisions/bad.md"


def test_format_problems_reports_success_and_failure() -> None:
    assert format_problems([])[0].startswith("OK:")
    failure = Problem("a.md", "key_missing", "x")
    assert format_problems([failure])[0].startswith("FAIL:")


def test_main_returns_zero_for_a_conformant_tree(tmp_path: Path) -> None:
    _write(tmp_path, "docs/decisions/clean.md", CLEAN_FRONTMATTER)
    assert main(["--repo-root", str(tmp_path)]) == 0


def test_main_returns_one_for_a_nonconformant_tree(tmp_path: Path) -> None:
    _write(tmp_path, "docs/decisions/bad.md", "# No frontmatter\n")
    assert main(["--repo-root", str(tmp_path)]) == 1


def test_the_real_corpus_conforms() -> None:
    """The repository's own governed stores must pass the gate they define.

    This is the regression guard for the whole finding: the audit exists
    because `docs/decisions/` was indexed but never validated, so a
    decision could carry unusable frontmatter and vanish from the index
    without any error anywhere.
    """
    problems = audit_frontmatter(REPO_ROOT)
    assert problems == [], "\n".join(str(problem) for problem in problems)


def test_schema_stores_are_the_documented_set() -> None:
    assert SCHEMA_STORES == (
        "docs/adr/",
        "docs/plans/",
        "docs/specs/",
        "docs/decisions/",
        "docs/followups/",
        "docs/initiatives/",
    )

from __future__ import annotations

from pathlib import Path

from scripts.audit_workflow_lifecycle import audit_workflows


def _make_repo(tmp_path: Path) -> Path:
    wf = tmp_path / ".claude" / "workflows"
    wf.mkdir(parents=True)
    (wf / "wave-x.js").write_text("// wave x\n")
    decisions = tmp_path / ".claude" / "decisions" / "workflows"
    decisions.mkdir(parents=True)
    (decisions / "2026-01-01-wave-x.md").write_text(
        "# 2026-01-01-wave-x\n\n## Status\n\nActive\n\n## Context\n\nfoo\n"
    )
    return tmp_path


def test_audit_passes_when_each_workflow_has_a_decision(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    issues = audit_workflows(repo)
    assert issues == []


def test_audit_flags_missing_decision(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    (repo / ".claude" / "workflows" / "wave-y.js").write_text("// wave y\n")
    issues = audit_workflows(repo)
    assert any("wave-y" in i for i in issues)


def test_audit_ignores_archive(tmp_path: Path) -> Path:
    repo = _make_repo(tmp_path)
    archive = repo / ".claude" / "workflows" / ".archive"
    archive.mkdir()
    (archive / "wave-old.js").write_text("// old\n")
    issues = audit_workflows(repo)
    assert issues == []

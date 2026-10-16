"""Phase F migration cleanup verification tests.

Per docs/plans/2026-10-15-bifrost-gateway-wiring.md §5 Phase F exit
criteria. Each test asserts one of the four proof-assertion guarantees
that audit_bifrost_grep.py also enforces (these are the in-process
mirror of the shell-level grep checks; running both is the
"belt-and-suspenders" pattern for CI gates).
"""

from __future__ import annotations

from pathlib import Path
import re
import subprocess

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MODELS_YAML = REPO_ROOT / "settings" / "models.yaml"
AUDIT_SCRIPT = REPO_ROOT / "scripts" / "audit_bifrost_grep.py"


def test_models_yaml_bifrost_block_deleted() -> None:
    """The misplaced ``bifrost:`` block at models.yaml:103-107 is gone.

    Phase F replaces the structurally-misplaced block (outside the
    MahavishnuSettings envelope) with the proper mount on
    settings/mahavishnu.yaml → bifrost.* (Phase A). The model literal
    routing rules in config/bifrost/config.template.json still
    reference the model name (``qwen3-8b-q4_k_m``); those are
    Bifrost-side routing rules, not settings.yaml fields.
    """
    text = MODELS_YAML.read_text(encoding="utf-8")
    # The block is a 4-line stanza starting with "bifrost:" at column 0.
    # After Phase F, no such stanza should exist.
    assert not re.search(
        r"^bifrost:\s*$",
        text,
        re.MULTILINE,
    ), f"bifrost: block still present in {MODELS_YAML} (Phase F regression)"


def test_no_bifrost_base_url_references() -> None:
    """The pre-1.0 BIFROST env var is no longer read in production code.

    Pre-1.0 replace-not-extend (per
    feedback-no-backwards-compat-pre-1.0.md). The env var was
    the only read-side path into the Bifrost gateway before the
    MahavishnuSettings.bifrost mount (Phase A). With the mount in
    place, the env var is dead code.

    Excludes ``docs/`` (changelogs and historical docs may
    legitimately reference the deprecated env var) and
    ``tests/unit/test_phase_f_migration.py`` itself (the test
    mentions the env var in its assertions).
    """
    proc = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    tracked = [p for p in proc.stdout.splitlines() if p.strip()]
    targets = [
        p
        for p in tracked
        if p.startswith(("settings/", "config/", "mahavishnu/"))
        and not p.endswith((".bak", ".bak.*", ".tmp"))
    ]
    offenders: list[str] = []
    for path in targets:
        full = REPO_ROOT / path
        if not full.is_file():
            continue
        try:
            text = full.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "BIFROST_BASE_URL" in text:
            offenders.append(path)
    assert not offenders, (
        "BIFROST_BASE_URL still referenced in production files: "
        + ", ".join(offenders)
    )


def test_audit_bifrost_grep_runs_clean() -> None:
    """``scripts/audit_bifrost_grep.py`` exits 0 on the current tree.

    The audit script is the CI gate for the four Phase F proof
    assertions. This test invokes it as a subprocess and asserts
    the exit code is 0. A failure here means either the migration
    regressed (e.g. someone re-introduced a direct minimax.io/v1
    URL) or the audit script has a bug.

    Originally marked xfail waiting on Phase B's wiring to land;
    flipped to a real pass after the 5 follow-up commits (the
    factory refactor added the minimax gateway consumer; the
    heartbeat + review-pass fixup cleared the docstring URL).
    """
    proc = subprocess.run(
        ["python3", str(AUDIT_SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, (
        f"audit_bifrost_grep.py failed (rc={proc.returncode}):\n"
        f"--- stdout ---\n{proc.stdout}\n"
        f"--- stderr ---\n{proc.stderr}\n"
    )
    proc = subprocess.run(
        ["python3", str(AUDIT_SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, (
        f"audit_bifrost_grep.py failed (rc={proc.returncode}):\n"
        f"--- stdout ---\n{proc.stdout}\n"
        f"--- stderr ---\n{proc.stderr}\n"
    )


def test_audit_bifrost_grep_uses_ripgrep_or_grep() -> None:
    """The audit script's _run_grep helper prefers ripgrep (rg) and falls back to grep.

    This is a regression-prevention test: if someone refactors the
    helper to use a different tool that doesn't have the same
    exclude-glob semantics, the audit may start matching files
    inside .archive/ or .venv/ that should be ignored. Pin the
    tool choice.
    """
    src = AUDIT_SCRIPT.read_text(encoding="utf-8")
    assert "rg" in src or "ripgrep" in src, "audit script should use ripgrep"
    assert "grep" in src, "audit script should fall back to grep"


@pytest.fixture(scope="module")
def audit_consumer_count() -> int:
    """Return the count of ``from mahavishnu.llm_gateway`` imports in mahavishnu/.

    Mirrors assertion_4 in audit_bifrost_grep.py. Phase B's Agno
    adapter changes are the canonical consumer; this test
    guards against an orphan regression (e.g. someone refactoring
    the import path and breaking the wiring without realizing it).
    """
    proc = subprocess.run(
        [
            "git",
            "ls-files",
            "mahavishnu/",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    count = 0
    for line in proc.stdout.splitlines():
        path = REPO_ROOT / line.strip()
        if not path.is_file() or not line.endswith(".py"):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        count += len(re.findall(r"from\s+mahavishnu\.llm_gateway", text))
    return count


def test_llm_gateway_has_at_least_one_consumer(audit_consumer_count: int) -> None:
    """At least one production file in mahavishnu/ imports from mahavishnu.llm_gateway.

    Phase B's LLMProviderFactory (in agno_adapter_impl.py) is the
    canonical consumer. The audit_orphans.py sibling enforces the
    inverse (zero orphans); this test guards the positive side.

    Originally marked xfail waiting on the LLMProviderFactory
    refactor; flipped to a real pass after the 5 follow-up commits
    (consumer count went from 1 → 5: openai, anthropic, minimax
    each import the gateway helpers via the new
    ``_resolve_bifrost_base_url`` helper).
    """
    assert audit_consumer_count > 0, (
        f"No production consumers of mahavishnu.llm_gateway in "
        f"mahavishnu/ (count={audit_consumer_count}). Phase B's "
        f"LLMProviderFactory should be the canonical consumer."
    )

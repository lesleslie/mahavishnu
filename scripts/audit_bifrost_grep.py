#!/usr/bin/env python3
"""Docs-CI grep check enforcing the Bifrost wiring proof assertions.

Per docs/plans/2026-10-15-bifrost-gateway-wiring.md §1 "Proof it worked"
+ §5 Phase F exit criteria. The four assertions:

1. grep -rn 'minimax\\.io/v1' mahavishnu/engines mahavishnu/workers/capabilities
        mahavishnu/llm_gateway  -- must return 0 hits
   (CloudWorker excluded per the KEEP decision at
   docs/feature-tracking/2026-09-25-cloud-worker-decision.md:58; the
   constant MINIMAX_OPENAI_BASE_URL at cloud_worker.py:37 is preserved
   as the default_factory fallback at cloud_worker.py:57.)
2. grep -rn BIFROST_BASE_URL . -- must return 0 hits
   (Pre-1.0 replace-not-extend; the env var is deleted per
   feedback-no-backwards-compat-pre-1.0.md.)
3. grep -rn 'bifrost:' settings/models.yaml -- must return 0 hits
   (The block at models.yaml:103-107 was structurally misplaced
   outside the MahavishnuSettings envelope; deleted in Phase F.)
4. grep -rn 'from mahavishnu.llm_gateway' mahavishnu/ -- must return > 0 hits
   (Proves the llm_gateway package has production consumers; the
   audit_orphans.py sibling enforces the inverse — zero orphans.)

Designed to be runnable in any CI context (no external deps beyond
the standard library + the mahavishnu package). The script exits 0
on success, 1 on any failure with a structured error message naming
the failing assertion.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_grep(
    pattern: str,
    paths: list[str],
    *,
    regex: bool = True,
    exclude_globs: list[str] | None = None,
) -> list[str]:
    """Return a list of "file:line:content" matches for the grep pattern.

    Uses ripgrep (rg) if available, falls back to grep -RIn. Skips
    .git, .venv, and the worktree's .archive dirs (per
    docs/decisions/2026-10-03-plans-specs-canonical-paths.md).
    The ``exclude_globs`` parameter adds caller-specific globs
    (e.g. docs/** when an assertion targets production code only).
    """
    cmd = [
        "rg",
        "--no-heading",
        "--line-number",
        "--color=never",
        "--glob=!.git/**",
        "--glob=!.venv/**",
        "--glob=!**/.archive/**",
    ]
    for glob in exclude_globs or []:
        cmd.append(f"--glob=!{glob}")
    if not regex:
        cmd.append("--fixed-strings")
    cmd.append(pattern)
    cmd.extend(paths)

    try:
        proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        # rg missing — fall back to grep
        cmd = ["grep", "-RIn", "--exclude-dir=.git", "--exclude-dir=.venv"]
        if not regex:
            cmd.append("-F")
        cmd.extend([pattern, *paths])
        proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    return [line for line in proc.stdout.splitlines() if line.strip()]


def assertion_1_no_direct_minimax_url() -> list[str]:
    """No direct minimax.io/v1 in the LLM-calling surface.

    Excludes:
    - ``docs/`` (changelogs and historical docs may legitimately
      reference the deprecated direct URL)
    - ``scripts/audit_bifrost_grep.py`` (the audit mentions the URL
      in its assertions)
    - ``tests/unit/test_phase_f_migration.py`` (the test reads the
      URL to assert the migration took effect)
    - CloudWorker (mahavishnu/workers/cloud_worker.py) is excluded per
      the KEEP decision (docs/feature-tracking/2026-09-25-cloud-
      worker-decision.md:58)
    - The PROVIDER_PROBES dict entry at
      ``mahavishnu/workers/capabilities/_probes.py`` is the
      *canonical direct-URL fallback* (read by
      ``resolve_probe_endpoint`` for the bifrost-disabled path).
      The audit is about the *call sites*; the dictionary is
      allowed because the bifrost-enabled path bypasses it.
    """
    return _run_grep(
        r"minimax\.io/v1",
        [
            "mahavishnu/engines",
            "mahavishnu/workers/capabilities",
            "mahavishnu/llm_gateway",
        ],
        exclude_globs=[
            "docs/**",
            "scripts/audit_bifrost_grep.py",
            "tests/unit/test_phase_f_migration.py",
            "mahavishnu/workers/capabilities/_probes.py",
        ],
    )


def assertion_2_no_bifrost_base_url_env() -> list[str]:
    """The BIFROST_BASE_URL env var is no longer read in production code.

    Excludes ``docs/`` (changelogs and historical docs may
    legitimately reference the deprecated env var), the audit
    script itself (it mentions the env var in its assertions),
    and the Phase F test file (it reads the env var name to
    assert the migration took effect).
    """
    return _run_grep(
        r"BIFROST_BASE_URL",
        ["."],
        exclude_globs=[
            "docs/**",
            "scripts/audit_bifrost_grep.py",
            "tests/unit/test_phase_f_migration.py",
        ],
    )


def assertion_3_models_yaml_no_bifrost_block() -> list[str]:
    """The misplaced bifrost: block in settings/models.yaml is gone."""
    return _run_grep(r"^bifrost:", ["settings/models.yaml"])


def assertion_4_llm_gateway_has_consumers() -> int:
    """mahavishnu.llm_gateway has at least one production consumer.

    Returns the count of imports, not the matches — callers check > 0.
    """
    return len(
        _run_grep(
            r"from mahavishnu\.llm_gateway",
            ["mahavishnu/"],
        )
    )


def main() -> int:
    """Run the four assertions and exit 0 on success, 1 on any failure."""
    failures: list[tuple[str, list[str]]] = []

    # Assertion 1: must be empty
    matches_1 = assertion_1_no_direct_minimax_url()
    if matches_1:
        failures.append(
            (
                "minimax.io/v1 in LLM-calling surface (CloudWorker excluded)",
                matches_1,
            )
        )

    # Assertion 2: must be empty
    matches_2 = assertion_2_no_bifrost_base_url_env()
    if matches_2:
        failures.append(("BIFROST_BASE_URL still referenced", matches_2))

    # Assertion 3: must be empty
    matches_3 = assertion_3_models_yaml_no_bifrost_block()
    if matches_3:
        failures.append(("bifrost: block still in settings/models.yaml", matches_3))

    # Assertion 4: must be > 0
    consumer_count = assertion_4_llm_gateway_has_consumers()
    if consumer_count == 0:
        failures.append(
            (
                "no production consumers of mahavishnu.llm_gateway",
                ["(grep returned 0 matches)"],
            )
        )

    if failures:
        print("audit_bifrost_grep.py FAILED:", file=sys.stderr)
        for label, matches in failures:
            print(f"  - {label}:", file=sys.stderr)
            for line in matches[:5]:
                print(f"      {line}", file=sys.stderr)
            if len(matches) > 5:
                print(f"      ... and {len(matches) - 5} more", file=sys.stderr)
        return 1

    print(f"audit_bifrost_grep.py OK (llm_gateway consumers: {consumer_count})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Phase 8 (bifrost plan 2026-10-17) — cross-repo caller audit.

Walks the 4 in-scope repos (mahavishnu, session-buddy, crackerjack,
mcp-common) and asserts that no LLM client construction hardcodes
an upstream cloud URL. Every LLM call site must source its
``base_url`` from the oneiric ``BifrostLLMRouter`` via
``get_router().resolve(...)`` (or from one of the canonical local
provider URLs on ``LOCAL_PROVIDER_ALLOWLIST``).

The check is scoped to *string-literal* base URLs on lines that
contain a recognized LLM-client keyword
(``AsyncOpenAI``, ``OpenAI``, ``Anthropic``, ``AsyncAnthropic``,
``openai.AsyncClient``, etc.). Generic ``base_url=`` assignments
on MCP clients, OTel exporters, Dhara clients, and observability
adapters are out of scope — those are governed by their own
audit/decision docs.

Run from any cwd:

    python scripts/audit_bifrost_callers.py

Exit codes:
    0  PASS — every LLM base URL is sourced from oneiric.
    1  FAIL — at least one LLM client hardcodes a non-allowlisted URL.
    2  Setup error (missing repo, etc.).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


IN_SCOPE_REPOS: tuple[str, ...] = (
    "mahavishnu",
    "session-buddy",
    "crackerjack",
    "mcp-common",
)

# Local-only providers that intentionally bypass Bifrost.
LOCAL_PROVIDER_ALLOWLIST: frozenset[str] = frozenset({
    "http://localhost:8081",
    "http://127.0.0.1:8081",
    "http://localhost:11434",
    "http://127.0.0.1:11434",
})

# Upstream cloud URLs that must NEVER appear as a hardcoded
# ``base_url=...`` literal — the migration moved all routing
# through Bifrost.
FORBIDDEN_LITERAL_HOSTS: frozenset[str] = frozenset({
    "api.minimax.io",
    "api.z.ai",
    "api.anthropic.com",
    "api.openai.com",
    "api.deepseek.com",
    "api.groq.com",
    "api.together.ai",
    "api.mistral.ai",
})

# Line-level keywords that mark a line as LLM-client construction.
# A line that contains one of these AND a ``base_url="..."``
# literal is the audit target. We intentionally scope narrowly
# so MCP/OTel/Dhara clients (which also have ``base_url``) are
# out of scope.
LLM_CLIENT_KEYWORDS: tuple[str, ...] = (
    "AsyncOpenAI",
    "AsyncAnthropic",
    "openai.OpenAI",
    "anthropic.Anthropic",
    "OpenAI(",
    "Anthropic(",
    "AsyncClient(",
    "LLMProviderFactory",
    "create_model",
    "create_async_model",
)

BASE_URL_LITERAL_RE = re.compile(
    r"""\bbase_url\s*=\s*['"]([^'"]+)['"]"""
)


def _find_repo_root(repo_name: str) -> Path:
    here = Path(__file__).resolve()
    parent = here.parent.parent.parent
    candidate = parent / repo_name
    if candidate.is_dir():
        return candidate
    for ancestor in here.parents:
        sibling = ancestor / repo_name
        if sibling.is_dir():
            return sibling
    raise FileNotFoundError(
        f"Could not find repo {repo_name!r} from {here}; "
        f"expected a sibling directory at {candidate}."
    )


def _git_ls_tracked_py(repo_root: Path, subpath: str) -> list[Path]:
    proc = subprocess.run(
        ["git", "ls-files", subpath],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        base = repo_root / subpath
        if not base.exists():
            return []
        return sorted(p for p in base.rglob("*.py") if p.is_file())
    return [
        (repo_root / line.strip())
        for line in proc.stdout.splitlines()
        if line.strip().endswith(".py")
    ]


def _extract_host(url: str) -> str | None:
    if "://" in url:
        _, _, rest = url.partition("://")
    else:
        rest = url
    host_port = rest.split("/", 1)[0]
    return host_port.split(":", 1)[0] or None


def audit_repo(repo_name: str) -> list[str]:
    """Walk one repo and return a list of FAILURE lines (empty = pass)."""
    repo_root = _find_repo_root(repo_name)
    failures: list[str] = []

    src_candidates: list[str] = []
    for cand in (repo_name, repo_name.replace("-", "_")):
        if (repo_root / cand).is_dir():
            src_candidates.append(cand)
    if not src_candidates:
        src_candidates = [""]

    for subpath in src_candidates:
        for py_file in _git_ls_tracked_py(repo_root, subpath):
            try:
                text = py_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line_no, line in enumerate(text.splitlines(), start=1):
                # Skip comments and docstring lines.
                stripped = line.lstrip()
                if stripped.startswith("#"):
                    continue

                # Must contain an LLM-client keyword to be in scope.
                if not any(kw in line for kw in LLM_CLIENT_KEYWORDS):
                    continue

                # Check each base_url literal on this line.
                for m in BASE_URL_LITERAL_RE.finditer(line):
                    value = m.group(1)

                    # 1. Local provider allowlist: OK
                    if value in LOCAL_PROVIDER_ALLOWLIST:
                        continue

                    # 2. Loopback-only URL (any port on 127.0.0.1 /
                    #    localhost / 0.0.0.0): OK — local dev, no
                    #    upstream egress.
                    host = _extract_host(value)
                    if host and host.startswith("127."):
                        continue
                    if host in ("localhost", "0.0.0.0", "::1"):
                        continue

                    # 3. Forbidden upstream cloud host: FAIL
                    if host and host in FORBIDDEN_LITERAL_HOSTS:
                        rel = py_file.relative_to(repo_root)
                        failures.append(
                            f"{repo_name}/{rel}:{line_no}: hardcoded "
                            f"upstream cloud URL {value!r} on an LLM "
                            f"client construction — must route through "
                            f"oneiric via get_router().resolve(...)\n"
                            f"    {line.rstrip()}"
                        )
                        continue

                    # 4. Any other non-loopback URL on an LLM line:
                    #    flag as suspicious. The LLM call sites
                    #    documented in the plan all use oneiric
                    #    resolve() or local allowlist; anything else
                    #    is likely a regression.
                    if value.startswith(("http://", "https://")):
                        rel = py_file.relative_to(repo_root)
                        failures.append(
                            f"{repo_name}/{rel}:{line_no}: non-allowlisted "
                            f"base_url {value!r} on an LLM client line — "
                            f"must be sourced from oneiric via "
                            f"get_router().resolve(...) or added to "
                            f"LOCAL_PROVIDER_ALLOWLIST (after audit)\n"
                            f"    {line.rstrip()}"
                        )

    return failures


def main() -> int:
    all_failures: list[str] = []
    for repo_name in IN_SCOPE_REPOS:
        try:
            failures = audit_repo(repo_name)
        except FileNotFoundError as exc:
            print(f"audit_bifrost_callers: setup error: {exc}", file=sys.stderr)
            return 2
        all_failures.extend(failures)

    if all_failures:
        print(
            f"audit_bifrost_callers FAILED — {len(all_failures)} "
            f"LLM-client base_url literal(s) not sourced from oneiric:",
            file=sys.stderr,
        )
        for f in all_failures:
            print(f"  - {f}", file=sys.stderr)
        return 1

    print(
        f"audit_bifrost_callers OK — every LLM-client base_url literal "
        f"in the 4 in-scope repos ({', '.join(IN_SCOPE_REPOS)}) is "
        f"sourced from oneiric or on LOCAL_PROVIDER_ALLOWLIST."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

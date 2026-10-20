#!/usr/bin/env python3
"""Extract-and-execute gate for an implementation plan.

Three tiers, cheapest-signal-first:
  Tier 1  syntax-check every fenced ```python block           (pure signal, no false positives)
  Tier 2  check every path a ```bash block touches exists on disk
  Tier 3  pytest --collect-only every block that is a complete test file

Exit 0 = clean. Exit 1 = findings (for CI-style gating).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

FENCE = re.compile(
    r"^(?P<indent>[ ]{0,3})```(?P<lang>[\w+-]*)\s*$\n(?P<body>.*?)^(?P=indent)```",
    re.MULTILINE | re.DOTALL,
)
BASH_CD = re.compile(r"^cd\s+(\S+)", re.MULTILINE)
PY_FILE = re.compile(r"(\S+\.py)\b")
YAML_FILE = re.compile(r"(\S+\.ya?ml)\b")
TOML_FILE = re.compile(r"(\S+\.toml)\b")
TESTPATH = re.compile(r"tests/\S+?\.py")

REPO_ROOTS = [
    Path("/Users/les/Projects/mahavishnu"),
    Path("/Users/les/Projects/akosha"),
    Path("/Users/les/Projects/oneiric"),
    Path("/Users/les/Projects/mcp-common"),
]


def line_of(text: str, idx: int) -> int:
    return text.count("\n", 0, idx) + 1


def extract(plan: Path) -> list[dict]:
    text = plan.read_text()
    out = []
    for m in FENCE.finditer(text):
        out.append(
            {
                "lang": m.group("lang") or "(none)",
                "body": m.group("body"),
                "line": line_of(text, m.start()),
            }
        )
    return out


def _syntax_fail(src: str, tag: str) -> str | None:
    """Return an error string if src does not compile, else None."""
    try:
        compile(src, f"<plan:{tag}>", "exec")
        return None
    except SyntaxError as e:
        return f"{type(e).__name__}: {e.msg} (block line {e.lineno})"
    except Exception as e:  # ValueError, TypeError from odd literals
        return f"{type(e).__name__}: {e}"


def _is_intentional_fragment(raw_err: str, ded_err: str) -> bool:
    """True when a block's compile failure is an artifact of being a
    paste-in fragment rather than a defect.

    Two shapes are legitimate in a plan: a signature-only stub whose body
    is elided (``def f():`` with no body), and a method/lifespan body
    indented for insertion into a class or an ``async def``.
    """
    needles = (
        "expected an indented block after function definition",  # sig-only stub
        "'await' outside function",  # async method body
        "expected an indented block after 'match'",  # match stub
    )
    combined = f"{raw_err} | {ded_err}"
    return any(n in combined for n in needles)


def tier1_syntax(blocks: list[dict]) -> list[dict]:
    """Report only blocks that fail BOTH raw and dedented, and are not
    recognizable as intentional paste-in fragments."""
    import textwrap

    bad = []
    fragments = 0
    for b in blocks:
        if b["lang"] != "python":
            continue
        src = b["body"]
        raw_err = _syntax_fail(src, str(b["line"]))
        if raw_err is None:
            continue
        ded_err = _syntax_fail(textwrap.dedent(src), f"{b['line']}:dedent")
        if ded_err is None:
            fragments += 1
            continue
        if _is_intentional_fragment(raw_err, ded_err):
            fragments += 1
            continue
        bad.append({**b, "err": f"raw: {raw_err} | dedented: {ded_err}"})
    print(f"  (intentional fragments skipped: {fragments})")
    return bad


def tier2_paths(blocks: list[dict], plan_text: str) -> list[dict]:
    """Check only paths the plan claims ALREADY EXIST.

    A "Create: foo.py" target is legitimately absent until implemented,
    so its absence is not a defect. Only "Modify"-class targets — existing
    source, config, and manifest files the plan edits in place — are
    meaningful here. Globs and shell-regex fragments are skipped.
    """
    # Paths the plan declares it will CREATE are out of scope. The plan
    # uses both `- Create: \`p\`` (list form) and `**Create:** \`p\``.
    created = set(re.findall(r"\*\*Create:\*\*\s*`([^`]+)`", plan_text))
    created |= set(re.findall(r"^-\s+Create:\s*`([^`]+)`", plan_text, re.MULTILINE))
    created |= set(re.findall(r"^Create:\s*`([^`]+)`", plan_text, re.MULTILINE))
    created |= set(re.findall(r"^-\s+Test:\s*`([^`]+)`", plan_text, re.MULTILINE))

    bad = []
    for b in blocks:
        if b["lang"] not in ("bash", "sh", ""):
            continue
        body = b["body"]
        cds = BASH_CD.findall(body)
        roots = [Path(c) for c in cds if c.startswith("/Users/les/Projects/")]
        targets = (
            set(PY_FILE.findall(body)) | set(YAML_FILE.findall(body)) | set(TOML_FILE.findall(body))
        )
        for t in sorted(targets):
            t = t.strip("'\"")
            # Skip globs, regex-ish tokens, and shell punctuation.
            if any(ch in t for ch in "*^|()[") or t.startswith(("--", ".")):
                continue
            # Skip plan-declared creates.
            tail = t.split("/")[-1]
            if t in created or any(c.endswith("/" + tail) for c in created):
                continue
            if t.startswith("/Users/les/Projects/"):
                cand = [Path(t)]
            elif t.startswith("/"):
                continue
            else:
                cand = [(r / t) for r in roots] or [(r / t) for r in REPO_ROOTS]
            if not any(c.exists() for c in cand):
                bad.append(
                    {
                        **b,
                        "err": f"declared-existing path missing: {t}",
                        "roots": [str(r) for r in (roots[:2] or REPO_ROOTS[:1])],
                    }
                )
    return bad


def _repo_for_block(body: str) -> Path | None:
    """Infer which repo a block belongs to from its imports."""
    for pkg, root in (
        ("akosha", "/Users/les/Projects/akosha"),
        ("oneiric", "/Users/les/Projects/oneiric"),
        ("mcp_common", "/Users/les/Projects/mcp-common"),
        ("mahavishnu", "/Users/les/Projects/mahavishnu"),
    ):
        if re.search(rf"^\s*(?:from|import)\s+{re.escape(pkg)}\b", body, re.MULTILINE):
            return Path(root)
    return None


def tier3_collect(blocks: list[dict]) -> list[dict]:
    """pytest --collect-only each complete test file, in ITS OWN repo's venv.

    Running in the wrong venv is a false signal: mahavishnu's venv has an
    installed copy of akosha, so a block importing akosha can resolve
    against stale site-packages instead of the checkout.
    """
    complete = [
        b
        for b in blocks
        if b["lang"] == "python"
        and b["body"].lstrip().startswith("from __future__ import annotations")
        and "def test_" in b["body"]
    ]
    results = []
    with tempfile.TemporaryDirectory() as td:
        for i, b in enumerate(complete):
            repo = _repo_for_block(b["body"])
            if repo is None:
                continue
            py = repo / ".venv" / "bin" / "python"
            if not py.exists():
                results.append({**b, "err": f"no venv at {py}"})
                continue
            f = Path(td) / f"test_planblock_{i}.py"
            f.write_text(b["body"])
            try:
                p = subprocess.run(
                    [
                        str(py),
                        "-m",
                        "pytest",
                        str(f),
                        "--collect-only",
                        "-q",
                        "-p",
                        "no:cacheprovider",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=90,
                    cwd=str(repo),
                )
            except subprocess.TimeoutExpired:
                results.append({**b, "err": "collect timeout"})
                continue
            if p.returncode != 0:
                tail = (p.stdout + p.stderr).strip().splitlines()
                results.append({**b, "err": "\n".join(tail[-8:]), "repo": str(repo)})
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("plan", type=Path)
    ap.add_argument("--tier", type=int, default=3)
    args = ap.parse_args()

    blocks = extract(args.plan)
    py = sum(1 for b in blocks if b["lang"] == "python")
    sh = sum(1 for b in blocks if b["lang"] in ("bash", "sh", ""))
    print(f"blocks: {len(blocks)} total, {py} python, {sh} bash\n")

    total = 0
    if args.tier >= 1:
        bad = tier1_syntax(blocks)
        print(f"TIER 1 — python syntax: {len(bad)}/{py} blocks fail")
        for b in bad:
            print(f"  L{b['line']}: {b['err']}")
        total += len(bad)

    if args.tier >= 2:
        bad = tier2_paths(blocks, args.plan.read_text())
        print(f"\nTIER 2 — bash paths: {len(bad)} findings")
        seen = set()
        for b in bad:
            k = (b["err"], tuple(b["roots"]))
            if k in seen:
                continue
            seen.add(k)
            print(f"  L{b['line']}: {b['err']}")
        total += len(bad)

    if args.tier >= 3:
        bad = tier3_collect(blocks)
        print(f"\nTIER 3 — pytest collect: {len(bad)} failures")
        for b in bad:
            print(f"  L{b['line']}: {b['err'][:300]}")
        total += len(bad)

    print(f"\nTOTAL FINDINGS: {total}")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())

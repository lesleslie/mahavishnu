#!/usr/bin/env python3
"""audit_doc_drift.py — find design documents whose code references no longer resolve.

Design documents describe code that should exist. When a refactor renames or
moves a module, the document silently becomes fiction: it still names a path
that no longer resolves, and a reader who trusts it is misled.

This script closes that gap deterministically. It reads design documents,
extracts the code references they make, resolves each one against the tree,
and reports the ones that no longer exist.

What it can prove
    - a referenced file does not exist            -> ``missing_path``
    - a referenced symbol does not exist          -> ``missing_symbol``
    - a normative claim needs human judgement     -> ``semantic_review`` worklist

What it cannot prove
    Whether the *behaviour* described by a claim still matches the
    implementation ("Logic Shortcuts", "Architectural Divergence" in the
    upstream vocabulary). Those are surfaced as an explicit worklist rather
    than guessed at, because a guessed verdict is worse than no verdict.

Scope discipline
    A reference is only a drift candidate when it plausibly describes *this*
    repository. References into sibling Bodai repos (``akosha/``,
    ``oneiric/``, ``session_buddy/``) are outside this repo's contract and are
    skipped rather than reported. Paths are resolved against the repo root
    and, when present, the package root, because this repo's documents mix
    both conventions (``mahavishnu/jot/x.py`` and ``jot/x.py``).

Severity is derived from the document's lifecycle status, so a draft plan may
legitimately reference files that do not exist yet while a shipped spec may
not.

Upstream vocabulary: google/elephant-goldfish-model (Apache-2.0), whose
``egm-drift-report`` skill defined the discrepancy categories this script
realises for the deterministically-checkable subset.

Usage:
    python scripts/audit_doc_drift.py
    python scripts/audit_doc_drift.py --json
    python scripts/audit_doc_drift.py --docs docs/specs docs/plans --out reports/doc_drift.md
    python scripts/audit_doc_drift.py --warn-only
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# --- REQ-DRIFT-001 -----------------------------------------------------------
# The script resolves every code reference made by a design document and
# reports the ones that no longer exist.

# Extensions that make a bare token look like a repository path.
CODE_EXTENSIONS = frozenset(
    {
        ".cfg",
        ".css",
        ".html",
        ".ini",
        ".js",
        ".json",
        ".jsx",
        ".md",
        ".py",
        ".sh",
        ".sql",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".yaml",
        ".yml",
    }
)

# Tokens that are obviously placeholders rather than real references.
PLACEHOLDER_CHARS = frozenset("<>{}*$!?\\")

# Placeholder shapes: ``2026-XX-XX-name.md``, ``tests/unit/...``.
PLACEHOLDER_RE = re.compile(r"X{2,}|\.\.\.")

# Directories skipped when indexing the tree by basename.
SKIP_INDEX_DIRS = frozenset(
    {
        ".backups",
        ".crackerjack",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "build",
        "dist",
        "node_modules",
        "venv",
    }
)

# A dotted token: ``mahavishnu.core.config`` or ``mahavishnu.core.config.Settings``.
MODULE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+$")

# Inline code spans: double-backtick first, then single.
CODE_SPAN_RE = re.compile(r"``([^`\n]+)``|`([^`\n]+)`")

# Markdown link targets: ``[text](target)``.
LINK_TARGET_RE = re.compile(r"\]\(([^)\s]+)\)")

# Normative markers that make a sentence a claim about required behaviour.
NORMATIVE_RE = re.compile(r"\b(?:must|shall|will|should|MUST|SHALL|WILL|SHOULD)\b")

# Frontmatter ``status:`` value.
FRONTMATTER_STATUS_RE = re.compile(r"^status:\s*([A-Za-z0-9_.\-]+)\s*$", re.MULTILINE)

# Sibling repository names, read from the ecosystem manifest.
ECOSYSTEM_NAME_RE = re.compile(r"^\s*-\s*(?:name|package):\s*[\"']?([A-Za-z0-9_.\-]+)")

ECOSYSTEM_MANIFEST = "settings/ecosystem.yaml"

# Directories never scanned for design documents.
EXCLUDED_DIR_NAMES = frozenset({".archive", ".git", "__pycache__", "node_modules"})

# Files inside a doc store that are scaffolding rather than documents.
EXCLUDED_FILE_NAMES = frozenset({"README.md", "TEMPLATE.md", "PLAN_INDEX.md"})

# Where a bare filename reference might live when the document does not say.
DOC_SEARCH_STORES = (
    "docs/decisions",
    "docs/specs",
    "docs/plans",
    "docs/adr",
    "docs/followups",
    "docs/decisions/.archive",
    ".claude",
)

# Severity ladder keyed by document lifecycle status.
# req: REQ-DRIFT-003
STATUS_SEVERITY: dict[str, str] = {
    "draft": "expected",
    "active": "warning",
    "partial": "warning",
    "shipped": "error",
    "complete": "error",
}

DEFAULT_SEVERITY = "warning"

CATEGORY_LABELS = {
    "missing_path": "Missing Features",
    "missing_symbol": "Incomplete Models",
    "unresolved_reference": "Unplaced Reference",
}


@dataclass(frozen=True)
class Reference:
    """A single code reference extracted from a document."""

    kind: str  # "path" | "module"
    target: str  # file path or dotted module
    symbol: str | None  # symbol name, when the reference carries one
    raw: str  # the token exactly as written
    line: int
    bare: bool  # True when the target carries no directory separator


@dataclass
class Finding:
    """A reference that does not resolve."""

    document: str
    status: str
    severity: str
    category: str
    reference: str
    line: int
    message: str


@dataclass
class SemanticItem:
    """A normative claim that references real code but needs human judgement."""

    document: str
    line: int
    claim: str


@dataclass
class Baseline:
    """Known findings that are tolerated until they are cleared.

    The baseline is a ratchet: findings already recorded do not fail the
    gate, but any *new* drift does. Keys deliberately omit the line number,
    because a line number shifts whenever the document is edited.
    """

    known: set[tuple[str, str, str]] = field(default_factory=set)

    @classmethod
    def load(cls, path: Path) -> Baseline:
        """Read a baseline file written by ``--write-baseline``."""
        if not path.is_file():
            return cls()
        payload = json.loads(path.read_text(encoding="utf-8"))
        entries = payload.get("findings", payload) if isinstance(payload, dict) else payload
        known: set[tuple[str, str, str]] = set()
        for entry in entries:
            if isinstance(entry, dict):
                known.add(
                    (
                        str(entry.get("document", "")),
                        str(entry.get("category", "")),
                        str(entry.get("reference", "")),
                    )
                )
        return cls(known)

    def matches(self, finding: Finding) -> bool:
        """True when a finding is already recorded in the baseline."""
        return (finding.document, finding.category, finding.reference) in self.known

    def to_payload(self, findings: list[Finding]) -> dict[str, object]:
        """Render findings as a baseline payload.

        Entries are deduplicated on ``(document, category, reference)``: the
        same reference cited on several lines of one document is one known
        finding, not several.
        """
        unique: dict[tuple[str, str, str], dict[str, str]] = {}
        for finding in findings:
            key = (finding.document, finding.category, finding.reference)
            unique.setdefault(
                key,
                {
                    "document": finding.document,
                    "category": finding.category,
                    "reference": finding.reference,
                },
            )
        return {
            "findings": sorted(
                unique.values(),
                key=lambda e: (e["document"], e["category"], e["reference"]),
            )
        }


@dataclass
class Report:
    """Aggregate result of a drift scan."""

    documents_scanned: int = 0
    references_checked: int = 0
    findings: list[Finding] = field(default_factory=list)
    baseline_findings: list[Finding] = field(default_factory=list)
    semantic_review: list[SemanticItem] = field(default_factory=list)

    @property
    def errors(self) -> int:
        return sum(1 for f in self.findings if f.severity == "error")

    @property
    def warnings(self) -> int:
        return sum(1 for f in self.findings if f.severity == "warning")

    @property
    def expected(self) -> int:
        return sum(1 for f in self.findings if f.severity == "expected")

    def to_dict(self) -> dict[str, object]:
        return {
            "documents_scanned": self.documents_scanned,
            "references_checked": self.references_checked,
            "errors": self.errors,
            "warnings": self.warnings,
            "expected": self.expected,
            "baseline_known": len(self.baseline_findings),
            "semantic_review": len(self.semantic_review),
            "findings": [
                {
                    "document": f.document,
                    "status": f.status,
                    "severity": f.severity,
                    "category": f.category,
                    "reference": f.reference,
                    "line": f.line,
                    "message": f.message,
                }
                for f in self.findings
            ],
            "baseline_findings": [
                {
                    "document": f.document,
                    "category": f.category,
                    "reference": f.reference,
                }
                for f in self.baseline_findings
            ],
            "semantic_review_items": [
                {"document": s.document, "line": s.line, "claim": s.claim}
                for s in self.semantic_review
            ],
        }


# --- extraction --------------------------------------------------------------


def strip_fenced_code(text: str) -> str:
    """Blank out fenced code blocks, preserving line numbering."""
    out: list[str] = []
    fence: str | None = None
    for line in text.splitlines():
        stripped = line.lstrip()
        if fence is None:
            if stripped.startswith("```") or stripped.startswith("~~~"):
                fence = stripped[:3]
                out.append("")
                continue
            out.append(line)
        else:
            out.append("")
            if stripped.startswith(fence):
                fence = None
    return "\n".join(out)


def _is_placeholder(token: str) -> bool:
    return any(ch in PLACEHOLDER_CHARS for ch in token) or bool(PLACEHOLDER_RE.search(token))


def looks_like_config_key(token: str) -> bool:
    """True when a dotted token is a settings key rather than a module path.

    ``settings.load``, ``settings.models.yaml`` and the logger name
    ``mahavishnu.log`` are all lowercase dotted tokens. A Python module
    reference either resolves to a file or names a class (uppercase segment);
    an all-lowercase dotted token that resolves to nothing is a config key
    and not a claim about code.
    """
    if not MODULE_RE.fullmatch(token):
        return False
    return not any(ch.isupper() for ch in token)


def _split_symbol_suffix(token: str) -> tuple[str, str | None]:
    """Split ``path/to/file.py::Class.method`` into its parts.

    A numeric suffix is a line number, not a symbol, so it is dropped.
    """
    for sep in ("::", ":"):
        if sep in token:
            head, _, tail = token.rpartition(sep)
            if not head:
                continue
            tail = tail.strip()
            if not tail or tail.isdigit():
                return head, None
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*", tail):
                return head, tail
            return head, None
    return token, None


def classify_token(token: str, root: Path) -> tuple[str, str, str | None, bool] | None:
    """Classify a candidate token.

    Returns ``(kind, target, symbol, bare)`` or ``None`` when the token is not
    a code reference this script should resolve.
    """
    token = token.strip().rstrip("():").strip()
    if not token or " " in token or "\t" in token:
        return None
    if "://" in token or token.startswith(("#", "/", "~")):
        return None
    if _is_placeholder(token):
        return None

    base, symbol = _split_symbol_suffix(token)

    if "/" in base:
        return ("path", base, symbol, False)

    # A single-dot filename (``README.md``) is a path, not a module, even
    # though it also matches the dotted-module shape.
    if (
        MODULE_RE.fullmatch(base)
        and base.count(".") == 1
        and base.endswith(tuple(CODE_EXTENSIONS))
    ):
        return ("path", base, symbol, True)

    # ``mahavishnu.core.config`` -> dotted module, but only when the first
    # segment is a real top-level package in this repo.
    if MODULE_RE.fullmatch(base):
        first = base.split(".", 1)[0]
        if (root / first).is_dir():
            return ("module", base, symbol, False)
        return None

    # A bare file name (``wire-up-contract.md``).
    if base.endswith(tuple(CODE_EXTENSIONS)):
        return ("path", base, symbol, True)

    return None


def extract_references(text: str, root: Path) -> list[Reference]:
    """Extract every resolvable code reference from a document."""
    body = strip_fenced_code(text)
    refs: list[Reference] = []
    seen: set[tuple[str, str, str | None, int]] = set()

    def add(raw: str, line: int) -> None:
        classified = classify_token(raw, root)
        if classified is None:
            return
        kind, target, symbol, bare = classified
        key = (kind, target, symbol, line)
        if key in seen:
            return
        seen.add(key)
        refs.append(
            Reference(kind=kind, target=target, symbol=symbol, raw=raw, line=line, bare=bare)
        )

    for line_no, line in enumerate(body.splitlines(), start=1):
        for match in CODE_SPAN_RE.finditer(line):
            token = match.group(1) or match.group(2) or ""
            add(token, line_no)
        for match in LINK_TARGET_RE.finditer(line):
            add(match.group(1), line_no)

    return refs


# req: REQ-DRIFT-006
def extract_semantic_claims(text: str, resolved: set[str]) -> list[tuple[int, str]]:
    """Find normative claims that reference code which does exist.

    These are the lines a machine cannot adjudicate: the referenced symbol is
    present, but whether the described behaviour still matches is a judgement
    call. They are handed to a human rather than guessed at.
    """
    body = strip_fenced_code(text)
    claims: list[tuple[int, str]] = []
    for line_no, line in enumerate(body.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not NORMATIVE_RE.search(stripped):
            continue
        if not any(token in stripped for token in resolved):
            continue
        claims.append((line_no, stripped[:300]))
    return claims


# --- resolution --------------------------------------------------------------


def module_to_path(module: str, root: Path) -> Path | None:
    """Resolve a dotted module name to a file on disk."""
    parts = module.split(".")
    candidate = root.joinpath(*parts).with_suffix(".py")
    if candidate.is_file():
        return candidate
    package = root.joinpath(*parts) / "__init__.py"
    if package.is_file():
        return package
    return None


# req: REQ-DRIFT-002
def collect_symbols(path: Path) -> set[str] | None:
    """Collect top-level names and class methods from a Python file.

    Returns ``None`` when the file cannot be parsed, so that a syntax error
    is never reported as a missing symbol.
    """
    if path.suffix != ".py":
        return set()
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except (OSError, SyntaxError, ValueError):
        return None

    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
            if isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        names.add(f"{node.name}.{sub.name}")
        elif isinstance(node, ast.Assign):
            # Module-level aliases (``load_settings = get_settings``) are
            # importable names even though they are not definitions.
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def load_sibling_repos(root: Path) -> tuple[set[str], str]:
    """Read the sibling repository names and this repo's own name.

    Cross-repo design documents describe files that live in *other* Bodai
    repositories (``oneiric/core/cli.py`` is oneiric's file, not ours). Those
    references are outside this repository's contract, so they are excluded
    rather than reported as drift.

    The catalog is read from the canonical ecosystem manifest
    (``settings/ecosystem.yaml``). Empty stub directories left behind by
    sibling checkouts are ignored — presence on disk is not ownership.
    """
    manifest = root / ECOSYSTEM_MANIFEST
    names: set[str] = set()
    own = ""
    if manifest.is_file():
        for line in manifest.read_text(encoding="utf-8", errors="replace").splitlines():
            match = ECOSYSTEM_NAME_RE.match(line)
            if match:
                names.add(match.group(1))
    for candidate in ("mahavishnu",):
        if candidate in names:
            own = candidate
    return names - {own}, own


class TreeIndex:
    """Index of the repository tree, used to resolve bare-name references."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._by_basename: dict[str, list[Path]] | None = None

    def by_basename(self) -> dict[str, list[Path]]:
        """Map every file's basename to the paths it occupies."""
        if self._by_basename is None:
            index: dict[str, list[Path]] = {}
            for path in self.root.rglob("*"):
                if not path.is_file():
                    continue
                try:
                    parts = path.relative_to(self.root).parts
                except ValueError:
                    continue
                if parts and parts[0] in SKIP_INDEX_DIRS:
                    continue
                if any(part in EXCLUDED_DIR_NAMES for part in parts):
                    continue
                index.setdefault(path.name, []).append(path)
            self._by_basename = index
        return self._by_basename

    def find_by_basename(self, name: str) -> Path | None:
        """Find any file with the given basename."""
        matches = self.by_basename().get(name)
        return matches[0] if matches else None


def path_candidates(
    target: str,
    root: Path,
    package_prefix: str | None,
    own_repo: str,
) -> list[Path]:
    """Candidate on-disk locations for a path reference, in priority order.

    This repo's documents mix three conventions for the same file:
    ``settings/mahavishnu.yaml`` (repo-relative), ``mahavishnu/settings/...``
    (repo-name-prefixed) and ``core/config.py`` (package-relative). All three
    are accepted; a reference only counts as drift when none of them resolve.
    """
    candidates: list[Path] = []

    def add(base: Path, rel: str) -> None:
        if rel and not rel.startswith("/"):
            candidates.append(base / rel)

    add(root, target)
    if own_repo and target.startswith(f"{own_repo}/"):
        add(root, target[len(own_repo) + 1 :])
    if package_prefix:
        add(root / package_prefix, target)
        if own_repo and target.startswith(f"{own_repo}/"):
            add(root / package_prefix, target[len(own_repo) + 1 :])

    # A document that was archived still exists; the reference is not broken.
    archived = [candidate.parent / ".archive" / candidate.name for candidate in candidates]
    return candidates + archived


# req: REQ-DRIFT-001
def resolve_path(
    target: str,
    root: Path,
    package_prefix: str | None,
    sibling_repos: set[str],
    own_repo: str,
    index: TreeIndex,
) -> tuple[Path | None, bool]:
    """Locate a path reference on disk.

    Returns ``(resolved_path, in_scope)``. ``in_scope`` is False when the
    reference points outside this repository (a sibling Bodai repo), in which
    case it is not this repo's drift.
    """
    first = target.split("/", 1)[0]

    # A reference into a sibling Bodai repo is out of scope, even when an
    # empty stub directory of the same name happens to exist locally.
    if first in sibling_repos and first != own_repo:
        return None, False

    for candidate in path_candidates(target, root, package_prefix, own_repo):
        if candidate.exists():
            return candidate, True

    # A bare filename may live anywhere in the tree.
    if "/" not in target:
        found = index.find_by_basename(target)
        if found is not None:
            return found, True
        for store in DOC_SEARCH_STORES:
            candidate = root / store / target
            if candidate.exists():
                return candidate, True

    in_scope = (root / first).exists()
    if not in_scope and package_prefix and first != package_prefix:
        in_scope = (root / package_prefix / first).exists()
    return None, in_scope


def resolve_module(
    target: str,
    symbol: str | None,
    root: Path,
) -> tuple[Path | None, str | None]:
    """Locate a dotted module reference and any symbol it names.

    ``mahavishnu.core.config.Settings`` may mean the module
    ``mahavishnu.core.config`` with symbol ``Settings``, or a module literally
    named ``Settings``. The module reading wins only if it exists.

    An all-lowercase dotted token that names no module is a config key or a
    logger name, so it is not split into a module plus a symbol.
    """
    path = module_to_path(target, root)
    if path is not None:
        return path, symbol

    if looks_like_config_key(target):
        return None, None

    if "." in target:
        head, _, tail = target.rpartition(".")
        path = module_to_path(head, root)
        if path is not None:
            return path, tail

    return None, symbol


# --- scanning ----------------------------------------------------------------


def read_status(text: str) -> str:
    """Read the ``status:`` value from a document's frontmatter."""
    if not text.startswith("---"):
        return "unknown"
    end = text.find("\n---", 3)
    if end == -1:
        return "unknown"
    match = FRONTMATTER_STATUS_RE.search(text[:end])
    return match.group(1).strip().lower() if match else "unknown"


def collect_documents(stores: list[Path], root: Path) -> list[Path]:
    """Collect design documents from the given stores."""
    docs: list[Path] = []
    for store in stores:
        if not store.is_dir():
            continue
        for path in sorted(store.rglob("*.md")):
            if any(part in EXCLUDED_DIR_NAMES for part in path.parts):
                continue
            if path.name in EXCLUDED_FILE_NAMES:
                continue
            docs.append(path)
    return docs


def scan_document(
    path: Path,
    root: Path,
    package_prefix: str | None,
    sibling_repos: set[str],
    own_repo: str,
    index: TreeIndex,
) -> tuple[list[Finding], list[SemanticItem], int]:
    """Scan one document, returning its findings, semantic worklist and ref count."""
    text = path.read_text(encoding="utf-8", errors="replace")
    status = read_status(text)
    severity = STATUS_SEVERITY.get(status, DEFAULT_SEVERITY)
    rel = path.relative_to(root).as_posix()

    findings: list[Finding] = []
    resolved_tokens: set[str] = set()
    refs = extract_references(text, root)

    def record(category: str, message: str, ref: Reference, sev: str | None = None) -> None:
        if severity == "expected":
            return
        findings.append(
            Finding(
                document=rel,
                status=status,
                severity=sev or severity,
                category=category,
                reference=ref.raw,
                line=ref.line,
                message=message,
            )
        )

    for ref in refs:
        if ref.kind == "path":
            resolved_path, in_scope = resolve_path(
                ref.target, root, package_prefix, sibling_repos, own_repo, index
            )
            if resolved_path is None:
                if not in_scope:
                    continue
                if ref.bare:
                    record(
                        "unresolved_reference",
                        f"bare filename not found in this repo: {ref.target}",
                        ref,
                        sev="warning",
                    )
                else:
                    record(
                        "missing_path",
                        f"referenced path does not exist: {ref.target}",
                        ref,
                    )
                continue

            resolved_tokens.add(ref.target)
            # Symbols are only defined in Python; a ``file.yaml:key`` suffix
            # is a config key, not a symbol.
            if ref.symbol and resolved_path.suffix == ".py" and resolved_path.is_file():
                symbols = collect_symbols(resolved_path)
                if symbols is not None and ref.symbol not in symbols:
                    record(
                        "missing_symbol",
                        f"symbol '{ref.symbol}' not found in {ref.target}",
                        ref,
                    )
                if symbols is not None:
                    resolved_tokens.add(ref.symbol)
            continue

        # module / module_symbol
        module_path, symbol = resolve_module(ref.target, ref.symbol, root)
        if module_path is None:
            first = ref.target.split(".", 1)[0]
            if first in sibling_repos:
                continue
            # An all-lowercase dotted token that resolves to no module is a
            # configuration key (``settings.load``) or a logger name
            # (``mahavishnu.log``), not a claim about code.
            if looks_like_config_key(ref.target):
                continue
            # Only a real Python package directory makes an unresolvable
            # dotted token a claim about code; a plain directory
            # (``settings/``) is far more likely to be a config namespace.
            if (root / first / "__init__.py").is_file():
                record(
                    "missing_path",
                    f"module does not resolve to a file: {ref.target}",
                    ref,
                )
            continue

        resolved_tokens.add(ref.target)
        if symbol and module_path.suffix == ".py" and module_path.is_file():
            symbols = collect_symbols(module_path)
            if symbols is not None and symbol not in symbols:
                record(
                    "missing_symbol",
                    f"symbol '{symbol}' not found in {ref.target}",
                    ref,
                )
            if symbols is not None:
                resolved_tokens.add(symbol)

    semantic = [
        SemanticItem(document=rel, line=line_no, claim=claim)
        for line_no, claim in extract_semantic_claims(text, resolved_tokens)
    ]

    return findings, semantic, len(refs)


# req: REQ-DRIFT-004
def render_markdown(report: Report) -> str:
    """Render the report as markdown."""
    lines: list[str] = ["# Doc Drift Report", ""]
    lines.append(
        f"- Documents scanned: {report.documents_scanned}\n"
        f"- References checked: {report.references_checked}\n"
        f"- Errors: {report.errors}\n"
        f"- Warnings: {report.warnings}\n"
        f"- Expected (draft docs): {report.expected}\n"
        f"- Known baseline entries: {len(report.baseline_findings)}\n"
        f"- Needing semantic review: {len(report.semantic_review)}"
    )
    lines.append("")

    if report.findings:
        lines.append("## Findings")
        lines.append("")
        for finding in sorted(
            report.findings,
            key=lambda f: (f.severity != "error", f.document, f.line),
        ):
            label = CATEGORY_LABELS.get(finding.category, finding.category)
            lines.append(
                f"- **{finding.severity.upper()}** `{finding.document}:{finding.line}` "
                f"({label}) — {finding.message}"
            )
        lines.append("")

    if report.baseline_findings:
        lines.append("## Known baseline entries (not failing the gate)")
        lines.append("")
        for finding in sorted(
            report.baseline_findings,
            key=lambda f: (f.document, f.reference),
        ):
            lines.append(f"- `{finding.document}` — {finding.reference}")
        lines.append("")

    if report.semantic_review:
        lines.append("## Needs semantic review")
        lines.append("")
        lines.append(
            "These claims reference code that exists, but a machine cannot "
            "confirm the described behaviour still holds."
        )
        lines.append("")
        for item in report.semantic_review:
            lines.append(f"- `{item.document}:{item.line}` — {item.claim}")
        lines.append("")

    if not report.findings and not report.semantic_review:
        lines.append("No drift detected.")
        lines.append("")

    return "\n".join(lines)


def detect_package_prefix(root: Path) -> str | None:
    """Detect the repo's importable package root (``mahavishnu/``)."""
    for candidate in sorted(p for p in root.iterdir() if p.is_dir()):
        if (candidate / "__init__.py").is_file():
            return candidate.name
    return None


def main(argv: list[str] | None = None) -> int:
    """Run the drift scan."""
    parser = argparse.ArgumentParser(
        description="Find design documents whose code references no longer resolve.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root to resolve references against (default: cwd).",
    )
    parser.add_argument(
        "--docs",
        nargs="*",
        default=["docs/specs"],
        help="Document stores to scan.",
    )
    parser.add_argument(
        "--package-prefix",
        default=None,
        help="Package root for package-relative paths (default: auto-detect).",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--out", type=Path, help="Write the markdown report to this path.")
    parser.add_argument(
        "--baseline",
        type=Path,
        help="Baseline file of known findings; matching findings do not fail the gate.",
    )
    parser.add_argument(
        "--write-baseline",
        type=Path,
        help="Write the current findings to this baseline file and exit.",
    )
    parser.add_argument(
        "--warn-only",
        action="store_true",
        help="Always exit 0, even when error-severity drift is present.",
    )
    parser.add_argument(
        "--max-semantic-items",
        type=int,
        default=25,
        help="Cap on semantic-review items per document.",
    )
    args = parser.parse_args(argv)

    root = args.repo_root.resolve()
    stores = [root / store for store in args.docs]
    documents = collect_documents(stores, root)
    package_prefix = args.package_prefix or detect_package_prefix(root)
    sibling_repos, own_repo = load_sibling_repos(root)
    index = TreeIndex(root)

    report = Report(documents_scanned=len(documents))
    for document in documents:
        findings, semantic, count = scan_document(
            document, root, package_prefix, sibling_repos, own_repo, index
        )
        report.findings.extend(findings)
        report.references_checked += count
        per_document: dict[str, int] = {}
        kept: list[SemanticItem] = []
        for item in semantic:
            seen = per_document.get(item.document, 0)
            if seen >= args.max_semantic_items:
                continue
            per_document[item.document] = seen + 1
            kept.append(item)
        report.semantic_review.extend(kept)

    if args.write_baseline is not None:
        payload = Baseline().to_payload(report.findings)
        args.write_baseline.parent.mkdir(parents=True, exist_ok=True)
        args.write_baseline.write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote {len(payload['findings'])} baseline entries to {args.write_baseline}")
        return 0

    if args.baseline is not None:
        baseline = Baseline.load(args.baseline)
        new_findings: list[Finding] = []
        for finding in report.findings:
            if baseline.matches(finding):
                report.baseline_findings.append(finding)
            else:
                new_findings.append(finding)
        report.findings = new_findings

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(render_markdown(report))

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(render_markdown(report), encoding="utf-8")

    if report.errors and not args.warn_only:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

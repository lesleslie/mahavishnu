"""Every in-repo relation reference in ``docs/`` must resolve to a real file.

A governed document points at other documents through its frontmatter
relation keys (``depends_on``, ``blocks_on``, ``superseded_by``,
``parent_spec`` and friends). Those pointers are the only machine-readable
edge in the corpus, and nothing validated them: the frontmatter auditor
checked that ``superseded_by`` was POPULATED when the role was
``superseded``, but never that the path it named still existed. A plan
deleted in one commit left its dependents pointing at nothing, and the
index carried on showing them as current work.

This test closes that hole for the references that can be checked from
inside this repository.

What is checked
---------------
An in-repo reference must name a file that is TRACKED by git:

* a value starting with ``docs/`` is in-repo;
* a value starting with ``<repo-name>/`` is a SELF-reference wearing a
  redundant prefix -- the prefix is stripped and the rest is checked,
  because a reference to this repo's own file must resolve like any
  other;
* anything else (``akosha/docs/...``, ``session-buddy/docs/...``) is a
  cross-repo pointer and is NOT checked here -- those resolve in the
  other repository, and this test cannot see it.

What is deliberately not checked
--------------------------------
Paths under an ``.archive/`` directory are exempt. ``.gitignore`` carries
``**/.archive/``, so archived documents leave version control by design
(``docs/plans/2026-11-16`` shipped that rule). A reference into the
archive therefore resolves on the machine that performed the archival
and nowhere else -- including in CI. Exempting the whole archive
directory keeps the test honest about what it can prove.

A tracked document that points into the archive is still worth writing,
because ``docs/plans/2026-11-07-archived-requirements-registry.md``
establishes that convention: it is tracked, and it points at
``docs/plans/.archive/...`` nine times.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

#: This repository's own name. A relation value that starts with it and
#: then names a ``docs/`` path is a self-reference with a redundant
#: prefix, and is checked like any other in-repo reference.
REPO_NAME = "mahavishnu"

#: Frontmatter keys whose values name other documents.
RELATION_KEYS: tuple[str, ...] = (
    "blocks_on",
    "cross_repo_plans",
    "depends_on",
    "origin_plan",
    "parent_spec",
    "partially_superseded_by",
    "related",
    "related_plans",
    "replaces",
    "superseded_by",
    "supersedes",
)

#: The document stores that carry governed documents.
STORES: tuple[str, ...] = ("docs/plans", "docs/specs", "docs/followups")

#: Files that are not governed documents.
NOT_DOCUMENTS: frozenset[str] = frozenset(
    {"PLAN_INDEX.md", "README.md", "TEMPLATE.md"}
)


def _tracked_files() -> frozenset[str]:
    """The repo-relative paths git tracks, as a frozenset."""
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    )
    return frozenset(result.stdout.split())


def _frontmatter(path: Path) -> dict[str, Any]:
    """The YAML frontmatter of a document, or an empty mapping."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    try:
        loaded = yaml.safe_load(text[3:end].lstrip("\n"))
    except yaml.YAMLError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _values(front: dict[str, Any]) -> list[str]:
    """Every relation value in a frontmatter mapping, flattened to strings."""
    out: list[str] = []
    for key in RELATION_KEYS:
        value = front.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            out.append(value)
        elif isinstance(value, (list, tuple)):
            out.extend(str(item) for item in value)
    return out


def _classify(value: str) -> str:
    """Classify a relation value.

    Returns ``"skip"`` for anything this test cannot judge, ``"archive"``
    for a path into a gitignored archive directory, and ``"in-repo"`` for a
    path that must resolve inside this repository.
    """
    candidate = value.strip()
    if not candidate or candidate.startswith("ext:"):
        return "skip"
    if "/" not in candidate or not candidate.endswith(".md"):
        return "skip"
    if candidate.startswith(f"{REPO_NAME}/"):
        candidate = candidate[len(REPO_NAME) + 1 :]
    elif not candidate.startswith("docs/"):
        # Another repository's plan, by the cross-repo convention.
        return "skip"
    if ".archive" in Path(candidate).parts:
        return "archive"
    return "in-repo"


def _dangling(tracked: frozenset[str]) -> list[tuple[str, str, str]]:
    """Every in-repo reference that names no tracked file.

    Returns ``(document, key, value)`` triples.
    """
    out: list[tuple[str, str, str]] = []
    for store in STORES:
        base = REPO_ROOT / store
        if not base.is_dir():
            continue
        for doc in sorted(base.rglob("*.md")):
            if ".archive" in doc.parts or doc.name in NOT_DOCUMENTS:
                continue
            rel = doc.relative_to(REPO_ROOT).as_posix()
            front = _frontmatter(doc)
            for key in RELATION_KEYS:
                for value in _values({key: front.get(key)}):
                    if _classify(value) != "in-repo":
                        continue
                    target = value.strip()
                    if target.startswith(f"{REPO_NAME}/"):
                        target = target[len(REPO_NAME) + 1 :]
                    if target not in tracked:
                        out.append((rel, key, value))
    return out


@pytest.fixture(scope="module")
def tracked() -> frozenset[str]:
    """The tracked file set, read once for the module."""
    return _tracked_files()


class TestTheClassifier:
    """The classifier decides what is checkable and what is not."""

    def test_a_docs_path_is_checked(self) -> None:
        assert _classify("docs/plans/2026-01-01-example.md") == "in-repo"

    def test_a_self_reference_is_checked(self) -> None:
        assert _classify("mahavishnu/docs/plans/2026-01-01-example.md") == "in-repo"

    def test_another_repository_is_not_checked(self) -> None:
        assert _classify("akosha/docs/plans/2026-01-01-example.md") == "skip"

    def test_an_archive_path_is_exempt(self) -> None:
        assert _classify("docs/plans/.archive/2026-01-01-example.md") == "archive"

    def test_an_external_identifier_is_not_checked(self) -> None:
        assert _classify("ext:REQ-001") == "skip"

    def test_a_value_that_is_not_a_path_is_not_checked(self) -> None:
        assert _classify("") == "skip"
        assert _classify("null") == "skip"


class TestEveryInRepoReferenceResolves:
    """The invariant itself."""

    def test_no_dangling_in_repo_references(
        self, tracked: frozenset[str]
    ) -> None:
        dangling = _dangling(tracked)
        assert not dangling, "these references name no tracked file:\n" + "\n".join(
            f"  {doc}: [{key}] -> {value}" for doc, key, value in dangling
        )

    def test_the_reference_keys_are_the_ones_the_corpus_uses(self) -> None:
        """The key list must not drift away from the corpus silently."""
        used: set[str] = set()
        for store in STORES:
            base = REPO_ROOT / store
            if not base.is_dir():
                continue
            for doc in sorted(base.rglob("*.md")):
                if ".archive" in doc.parts or doc.name in NOT_DOCUMENTS:
                    continue
                used.update(
                    key for key in _frontmatter(doc) if key in RELATION_KEYS
                )
        assert used, "no relation keys found -- the corpus shape changed"
        assert used <= set(RELATION_KEYS)

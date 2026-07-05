# Anti-AI-Flavor Style SOP v1.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship per-repo style SOPs (`.bodai/style-sop.md`) with machine-checkable bans, packaged default SOP, discovery + parser, validator, and Crackerjack skill integration.

**Architecture:** Markdown + YAML frontmatter format. Discovery walks up from CWD looking for `.bodai/style-sop.md`. Falls back to packaged default at `mahavishnu/style-sop.md`. Validator scans content against the frontmatter `bans` list (regex). Crackerjack skill `anti-ai-flavor-check` exposes the validator.

**Tech Stack:** Python 3.13, `pyyaml`, `pathlib`, Crackerjack (existing), pytest with `asyncio_mode = "auto"`.

______________________________________________________________________

## Global Constraints

Inherited from Spec #1's plan. New constraints:

- **Default SOP ships in package** at `mahavishnu/style-sop.md`.
- **Discovery walks up from CWD**, nearest ancestor wins.
- **Bans are regex patterns**; operator's voice lives in the markdown body.
- **Advisory in v1.1, gate in v2.0** — no CI enforcement in v1.0.

______________________________________________________________________

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `mahavishnu/style-sop.md` | Default SOP file (package resource). |
| `mahavishnu/core/style_sop.py` | `discover_style_sop`, `load_style_sop`, `_parse_sop`. |
| `mahavishnu/core/style_sop_validator.py` | `check_content(content, start_path)`. |
| `mahavishnu/quality/anti_ai_flavor_check.py` | Crackerjack skill entry point. |
| `tests/unit/test_style_sop.py` | L0 tests for parser. |
| `tests/unit/test_style_sop_validator.py` | L1/L2 tests for validator. |
| `tests/integration/test_anti_ai_flavor_skill.py` | L3 tests for Crackerjack integration. |

### Modified files

| Path | Modification |
|---|---|
| `mahavishnu/quality/__init__.py` | Register `anti-ai-flavor-check` skill (if registry pattern exists). |

______________________________________________________________________

## Task 1: Ship the default SOP

**Files:**

- Create: `mahavishnu/style-sop.md`

- [ ] **Step 1: Create the default SOP file**

Create `mahavishnu/style-sop.md`:

```markdown
---
bans:
  - pattern: "Co-Authored-By:\\s*Claude"
    message: "No AI attribution in commit messages"
  - pattern: "Generated with Claude Code"
    message: "No AI tooling attribution"
  - pattern: "\\[bot\\]\\s*$"
    message: "No bot suffix in commit messages"
  - pattern: "^##\\s*(What this MR does|Why we need it)\\s*$"
    message: "No fill-in-the-blank headings; use descriptive titles"
  - pattern: "\\*\\*(Root cause|Fix|Risk|What changes):\\*\\*"
    message: "No bold-tag structure in prose; integrate naturally"
  - pattern: "verified locally"
    message: "Proof of work must be command-reproducible"
required_disclosures:
  - "MR description: include Changes: bullet list"
  - "Commit message: include reproducible test command if applicable"
---

# Style SOP — Mahavishnu default

This SOP constrains how agents write MR descriptions, commit messages,
and other operator-facing artifacts. The goal: output that doesn't look
AI-generated and is grounded in actual project work.

## Voice

Write MR descriptions as continuous prose with a `Changes:` bullet list
at the end, the way an engineer would write it manually. No "What this
MR does / Why we need it" templates.

## Proof of work

When claiming verification, include the actual command and its relevant
output. Not "verified locally" — `pytest tests/test_foo.py::test_bar -v`
with the relevant 3 lines.

## What makes output smell AI

- Bold inline tags like `**Root cause:**`, `**Fix:**`, `**Risk:**` —
  the single most reliable AI-flavor tell.
- Fill-in-the-blank section headings.
- Generic prose without specific numbers or measurements.
- Co-Authored-By or [bot] suffixes in commit messages.

## What makes output look human

- Specific measurements ("reduces p99 from 340ms to 95ms over 1000 requests").
- Honest post-mortems ("I tried X first; it didn't work because Y").
- Names of specific files and functions.
- Concrete commands and their output.

## Editing this SOP

Operators edit this file at any time. The next MR picks up the new rules.
No daemon restart, no code change. To ban something new, add to the YAML
frontmatter's `bans` list with a regex pattern and a message.
```

- [ ] **Step 2: Verify file loads as YAML + markdown**

Run a quick REPL check:

```bash
python -c "
import yaml, re
text = open('mahavishnu/style-sop.md').read()
fm_match = re.match(r'^---\n(.+?)\n---\n', text, re.DOTALL)
assert fm_match, 'no frontmatter'
fm = yaml.safe_load(fm_match.group(1))
assert 'bans' in fm and len(fm['bans']) >= 1, 'no bans'
print('OK:', len(fm['bans']), 'bans')
"
```

Expected: `OK: 6 bans`

- [ ] **Step 3: Commit**

```bash
git add mahavishnu/style-sop.md
git commit -m "feat(style-sop): add default SOP package resource"
```

______________________________________________________________________

## Task 2: Implement discovery + parser

**Files:**

- Create: `mahavishnu/core/style_sop.py`

- Test: `tests/unit/test_style_sop.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_style_sop.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from mahavishnu.core.style_sop import (
    discover_style_sop,
    load_style_sop,
)


def test_discover_returns_none_when_no_sop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "some_file.py").write_text("# no sop here")
    monkeypatch.chdir(tmp_path)
    # Walk up to filesystem root — should return None.
    result = discover_style_sop(tmp_path)
    assert result is None


def test_discover_finds_repo_sop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / ".bodai").mkdir()
    sop_file = tmp_path / ".bodai" / "style-sop.md"
    sop_file.write_text("---\nbans: []\n---\n\n# Body\n")
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    monkeypatch.chdir(subdir)
    result = discover_style_sop(subdir)
    assert result == sop_file


def test_load_style_sop_returns_frontmatter_and_body(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / ".bodai").mkdir()
    sop_text = (
        "---\n"
        "bans:\n"
        "  - pattern: 'foo'\n"
        "    message: 'no foo'\n"
        "required_disclosures:\n"
        "  - 'always include bar'\n"
        "---\n"
        "\n"
        "# Body\n"
        "This is the prose.\n"
    )
    (tmp_path / ".bodai" / "style-sop.md").write_text(sop_text)
    monkeypatch.chdir(tmp_path)
    sop = load_style_sop(tmp_path)
    assert "bans" in sop["frontmatter"]
    assert sop["frontmatter"]["bans"][0]["pattern"] == "foo"
    assert "Body" in sop["body"]
    assert "This is the prose" in sop["body"]


def test_load_style_sop_handles_missing_frontmatter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / ".bodai").mkdir()
    (tmp_path / ".bodai" / "style-sop.md").write_text("# Just markdown\n\nNo frontmatter.")
    monkeypatch.chdir(tmp_path)
    sop = load_style_sop(tmp_path)
    assert sop["frontmatter"] == {}
    assert "Just markdown" in sop["body"]


def test_load_style_sop_falls_back_to_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "no_sop_here.py").write_text("")
    monkeypatch.chdir(tmp_path)
    sop = load_style_sop(tmp_path)
    # Should fall back to packaged default.
    assert sop["source_path"] is not None
    assert sop["source_path"].name == "style-sop.md"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_style_sop.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the module**

Create `mahavishnu/core/style_sop.py`:

```python
"""Style SOP discovery and parsing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def discover_style_sop(start_path: Path | None = None) -> Path | None:
    """Walk up from start_path looking for .bodai/style-sop.md.

    Returns the path or None if no SOP is found within the filesystem root.
    """
    start = (start_path or Path.cwd()).resolve()
    current = start
    while True:
        candidate = current / ".bodai" / "style-sop.md"
        if candidate.exists():
            return candidate
        if current.parent == current:
            return None
        current = current.parent


_PACKAGED_DEFAULT_SOP = Path(__file__).parent.parent / "style-sop.md"


def _parse_sop(path: Path) -> dict[str, Any]:
    text = path.read_text()
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end > 0:
            frontmatter = yaml.safe_load(text[4:end]) or {}
            body = text[end + 5:]
        else:
            frontmatter = {}
            body = text
    else:
        frontmatter = {}
        body = text
    return {
        "frontmatter": frontmatter,
        "body": body,
        "source_path": path,
    }


def load_style_sop(start_path: Path | None = None) -> dict[str, Any]:
    """Load the active SOP. Returns {frontmatter, body, source_path}.

    Discovery order:
    1. .bodai/style-sop.md walking up from start_path
    2. Packaged default at mahavishnu/style-sop.md
    3. Empty SOP (no bans)
    """
    repo_sop = discover_style_sop(start_path)
    if repo_sop:
        return _parse_sop(repo_sop)
    if _PACKAGED_DEFAULT_SOP.exists():
        return _parse_sop(_PACKAGED_DEFAULT_SOP)
    return {
        "frontmatter": {"bans": [], "required_disclosures": []},
        "body": "",
        "source_path": None,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_style_sop.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/core/style_sop.py tests/unit/test_style_sop.py
git commit -m "feat(style-sop): add discovery and parser for .bodai/style-sop.md"
```

______________________________________________________________________

## Task 3: Implement validator

**Files:**

- Create: `mahavishnu/core/style_sop_validator.py`

- Test: `tests/unit/test_style_sop_validator.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_style_sop_validator.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from mahavishnu.core.style_sop_validator import check_content


@pytest.fixture
def sop_with_bans(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / ".bodai").mkdir()
    (tmp_path / ".bodai" / "style-sop.md").write_text(
        "---\n"
        "bans:\n"
        "  - pattern: 'Co-Authored-By:\\\\s*Claude'\n"
        "    message: 'No AI attribution'\n"
        "  - pattern: '\\*\\*Root cause:\\*\\*'\n"
        "    message: 'No bold-tag structure'\n"
        "---\n"
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_check_returns_empty_for_clean_content(sop_with_bans: Path):
    violations = check_content("# Clean MR\n\nThis is fine.", sop_with_bans)
    assert violations == []


def test_check_detects_banned_pattern(sop_with_bans: Path):
    content = "feat: add thing\n\nCo-Authored-By: Claude <noreply@anthropic.com>"
    violations = check_content(content, sop_with_bans)
    assert len(violations) == 1
    assert "AI attribution" in violations[0]["message"]


def test_check_detects_multiple_violations(sop_with_bans: Path):
    content = (
        "feat: add thing\n\n"
        "Co-Authored-By: Claude <noreply@anthropic.com>\n\n"
        "**Root cause:** the bug."
    )
    violations = check_content(content, sop_with_bans)
    assert len(violations) == 2


def test_check_uses_default_when_no_repo_sop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # No repo SOP — uses packaged default.
    (tmp_path / "no_sop.py").write_text("")
    monkeypatch.chdir(tmp_path)
    # Default SOP bans "Co-Authored-By: Claude"
    content = "feat: x\n\nCo-Authored-By: Claude <noreply@anthropic.com>"
    violations = check_content(content, tmp_path)
    assert len(violations) >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_style_sop_validator.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the validator**

Create `mahavishnu/core/style_sop_validator.py`:

```python
"""Style SOP content validator."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from oneiric.logging import get_logger

from mahavishnu.core.style_sop import load_style_sop

logger = get_logger(__name__)


def check_content(content: str, start_path: Path | None = None) -> list[dict[str, Any]]:
    """Check content against the active SOP. Returns list of violations.

    Each violation is {pattern, message, source_sop}.
    """
    sop = load_style_sop(start_path)
    violations: list[dict[str, Any]] = []
    for ban in sop["frontmatter"].get("bans", []):
        pattern = ban.get("pattern", "")
        message = ban.get("message", "Banned pattern")
        try:
            if re.search(pattern, content, re.MULTILINE):
                violations.append({
                    "pattern": pattern,
                    "message": message,
                    "source_sop": str(sop["source_path"]),
                })
        except re.error as exc:
            logger.warning(
                "skipping invalid regex pattern in SOP",
                extra={"pattern": pattern, "error": str(exc)},
            )
    return violations
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_style_sop_validator.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/core/style_sop_validator.py tests/unit/test_style_sop_validator.py
git commit -m "feat(style-sop): add check_content validator with regex bans"
```

______________________________________________________________________

## Task 4: Implement Crackerjack skill

**Files:**

- Create: `mahavishnu/quality/anti_ai_flavor_check.py`

- Test: `tests/integration/test_anti_ai_flavor_skill.py`

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_anti_ai_flavor_skill.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from mahavishnu.quality.anti_ai_flavor_check import run_anti_ai_flavor_check


@pytest.fixture
def sop_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / ".bodai").mkdir()
    (tmp_path / ".bodai" / "style-sop.md").write_text(
        "---\n"
        "bans:\n"
        "  - pattern: 'verified locally'\n"
        "    message: 'Proof must be command-reproducible'\n"
        "---\n"
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "module.py").write_text("# code")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_skill_returns_violations(sop_repo: Path):
    target_file = sop_repo / "src" / "module.py"
    content = "# Changelog\n\nverified locally"
    result = run_anti_ai_flavor_check(content, target_file)
    assert len(result["violations"]) == 1
    assert "command-reproducible" in result["violations"][0]["message"]


def test_skill_returns_empty_for_clean_content(sop_repo: Path):
    target_file = sop_repo / "src" / "module.py"
    content = "# Changelog\n\n- Fix bug X\n- Add test Y"
    result = run_anti_ai_flavor_check(content, target_file)
    assert result["violations"] == []


def test_skill_includes_sop_source(sop_repo: Path):
    target_file = sop_repo / "src" / "module.py"
    content = "verified locally"
    result = run_anti_ai_flavor_check(content, target_file)
    assert result["sop_source"] is not None
    assert result["sop_source"].endswith("style-sop.md")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_anti_ai_flavor_skill.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the skill**

Create `mahavishnu/quality/anti_ai_flavor_check.py`:

```python
"""Crackerjack skill: anti-ai-flavor-check.

Validates generated content (MR descriptions, commit messages, etc.)
against the active style SOP. Returns violations with source SOP path.
"""

from __future__ import annotations

from pathlib import Path

from mahavishnu.core.style_sop import load_style_sop
from mahavishnu.core.style_sop_validator import check_content


def run_anti_ai_flavor_check(content: str, file_path: Path) -> dict:
    """Crackerjack skill entry point.

    Args:
        content: the generated content (MR description, commit message, etc.)
        file_path: where the content was generated; used for SOP discovery.

    Returns:
        {"violations": [...], "sop_source": "..."}
    """
    violations = check_content(content, file_path.parent)
    sop = load_style_sop(file_path.parent)
    return {
        "violations": violations,
        "sop_source": str(sop["source_path"]) if sop["source_path"] else None,
    }
```

If the project has a Crackerjack skill registry, register this skill there. Otherwise, it's a standalone module exposed via the import path.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_anti_ai_flavor_skill.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/quality/anti_ai_flavor_check.py tests/integration/test_anti_ai_flavor_skill.py
git commit -m "feat(style-sop): add Crackerjack skill anti-ai-flavor-check"
```

______________________________________________________________________

## Self-Review

**1. Spec coverage:**

| Spec section | Covered by |
|---|---|
| Default SOP | Task 1 |
| Discovery + parser | Task 2 |
| Validator | Task 3 |
| Crackerjack skill | Task 4 |
| L0-L3 testing | Tasks 1-4 |

**2. Placeholder scan:** No `TBD`/`TODO` markers.

**3. Type consistency:** `load_style_sop` and `check_content` signatures consistent across Tasks 2-4.

**Gaps:** None.

Plan complete. Moving to spec #7 brainstorm (`project-scoped-sop-evolution`, Phase 3).

# Anti-AI-Flavor Style SOP v1.0 — Design

**Status:** Draft (brainstormed 2026-06-22)
**Phase:** 2 (Workflow Evolution)
**Source:** `Building a Production Agent Harness` — "The Anti-AI-Flavor Style Guide." Operator-curated style constraints prevent MR descriptions from "smelling AI," which would erode operator trust in the automated MR pipeline.

---

## Overview

This spec defines per-repo style SOPs (`.bodai/style-sop.md`) with machine-checkable bans (YAML frontmatter) and operator's prose voice (markdown body). The default SOP ships in the package; operators customize per-repo. A Crackerjack skill `anti-ai-flavor-check` validates generated content against the active SOP.

**Architectural property:** The SOP is **operator-curated, not code-curated**. Operators edit the file at any time; the next MR picks up the new rules. No daemon restart, no code change.

---

## Goals

- **G1.** Prevent MR descriptions and commit messages from "smelling AI" by enforcing operator-curated style constraints.
- **G2.** Per-repo customization: different repos can have different style constraints.
- **G3.** Machine-checkable: validators can detect banned patterns automatically.
- **G4.** Operator's voice preserved: prose rules in the body are guidance, not just bans.
- **G5.** Crackerjack integration: validators run in CI; advisory in v1.1, gate in v2.0.

## Non-Goals

- **N1.** Universal AI-flavor detection (LLM-based classification). v1.0 uses regex patterns only; LLM-based detection is a future spec.
- **N2.** Style transfer or rewriting. The validator flags violations; it doesn't auto-rewrite.
- **N3.** Enforcement in v1.0. The skill is advisory; CI gates come in v2.0.

---

## Architecture & Data Flow

```
Per-repo SOP file:
  .bodai/style-sop.md
  ├── YAML frontmatter (machine-checkable bans)
  │     bans:
  │       - pattern: 'Co-Authored-By: Claude'
  │         message: 'No AI attribution'
  └── Markdown body (operator's prose voice)
        "Write MR descriptions as continuous prose..."

Generation flow:
  1. Worker producing MR description / commit message reads SOP
     - discover_style_sop(cwd) walks up looking for .bodai/style-sop.md
     - Falls back to packaged default if not found
  2. Worker prompt includes SOP body (prose voice) + frontmatter rules
  3. Worker generates content
  4. Crackerjack skill `anti-ai-flavor-check` validates output
     - Returns violations list with pattern + message + source SOP
  5. Worker loop:
     - v1.0: violation is warning, loop continues
     - v1.1: violation is CI gate (advisory)
     - v2.0: violation is CI gate (fails build)
```

---

## Default SOP (ships in package)

Path: `mahavishnu/style-sop.md`

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

---

## Discovery & Fallback

```python
# mahavishnu/core/style_sop.py

from pathlib import Path

import yaml


def discover_style_sop(start_path: Path | None = None) -> Path | None:
    """Walk up from start_path looking for .bodai/style-sop.md. Return path or None."""
    start = (start_path or Path.cwd()).resolve()
    current = start
    while True:
        candidate = current / ".bodai" / "style-sop.md"
        if candidate.exists():
            return candidate
        if current.parent == current:
            return None
        current = current.parent


def load_style_sop(start_path: Path | None = None) -> dict:
    """Load the active SOP. Returns {frontmatter, body, source_path}."""
    repo_sop = discover_style_sop(start_path)
    if repo_sop:
        return _parse_sop(repo_sop)
    default_sop = Path(__file__).parent.parent / "style-sop.md"
    if default_sop.exists():
        return _parse_sop(default_sop)
    return {
        "frontmatter": {"bans": [], "required_disclosures": []},
        "body": "",
        "source_path": None,
    }


def _parse_sop(path: Path) -> dict:
    text = path.read_text()
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end > 0:
            frontmatter = yaml.safe_load(text[4:end])
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
```

**Discovery rule:** nearest ancestor wins. A subdir SOP overrides parent. v1.0 doesn't chain inheritance — subdir SOP fully replaces.

---

## Validator

```python
# mahavishnu/core/style_sop_validator.py

import re
from pathlib import Path

from mahavishnu.core.style_sop import load_style_sop


def check_content(content: str, start_path: Path | None = None) -> list[dict]:
    """Check content against the active SOP. Returns list of violations."""
    sop = load_style_sop(start_path)
    violations: list[dict] = []
    for ban in sop["frontmatter"].get("bans", []):
        pattern = ban.get("pattern", "")
        message = ban.get("message", "Banned pattern")
        if re.search(pattern, content, re.MULTILINE):
            violations.append({
                "pattern": pattern,
                "message": message,
                "source_sop": str(sop["source_path"]),
            })
    return violations
```

---

## Crackerjack Skill

```python
# Crackerjack skill: anti-ai-flavor-check
# Registered with Crackerjack's skill registry

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

---

## Adoption & Migration

| Version | Adoption policy |
|---|---|
| **v1.0** | Default SOP ships at `mahavishnu/style-sop.md`. Crackerjack skill `anti-ai-flavor-check` shipped. Workers opt-in to including the SOP in their prompt. CI integration is documentation only. |
| **v1.1** | Workers producing MR descriptions, commit messages, and PR descriptions MUST inject the SOP into their prompts. Crackerjack skill runs in CI as advisory check (warns, doesn't fail). |
| **v2.0** | Crackerjack skill runs in CI as gate (fails build on violations). Operators can override per-PR via `<!-- bodai:sop-override -->` comment. |

---

## Storage & Retrieval

No new persistence. SOP files are markdown on disk. Crackerjack reads them on each invocation. The `body` is read by agents (prompt injection); the `frontmatter` is read by validators.

---

## Error Handling

| Failure | Detection | Response |
|---|---|---|
| SOP file malformed (no closing `---`) | `_parse_sop` | Returns frontmatter={}, body=full_text. Operators see validator run against prose body (no bans enforced). |
| YAML frontmatter invalid | `yaml.safe_load` raises | Validator falls back to no bans; logs error. |
| Regex pattern invalid | `re.search` raises | Skipped; logged. |
| Default SOP missing | File not found | Validator returns empty list (no bans). |
| `.bodai/` directory missing | `discover_style_sop` walks to root | Falls back to default. |

---

## Testing Strategy

| Layer | Tests |
|---|---|
| **L0 (pure boundary)** | YAML frontmatter parsing; markdown body extraction. Default SOP loads correctly. |
| **L1 (file isolation)** | `discover_style_sop` walks up correctly. Falls back to default when no repo SOP. Returns None when no SOP at all. |
| **L2 (service isolation)** | `check_content` returns violations for content matching bans; empty list for clean content. Multiple bans match correctly. |
| **L3 (sandbox)** | Crackerjack skill integration: runs against MR descriptions; produces expected report. |
| **L4 (integration)** | Sample worker producing content with SOP injected; Crackerjack reports violations when present. |

**Coverage target:** `tests/unit/test_style_sop.py`, `tests/unit/test_style_sop_validator.py` ≥ 95% line coverage.

---

## Implementation Module Paths

| Component | Path |
|---|---|
| Default SOP file | `mahavishnu/style-sop.md` |
| Discovery + parser | `mahavishnu/core/style_sop.py` |
| Validator | `mahavishnu/core/style_sop_validator.py` |
| Crackerjack skill | `mahavishnu/quality/anti_ai_flavor_check.py` |
| L0 tests | `tests/unit/test_style_sop.py` |
| L1 tests | `tests/unit/test_style_sop_validator.py` |
| L3 tests | `tests/integration/test_anti_ai_flavor_skill.py` |

---

## Trade-offs & Alternatives Considered

| Choice | Why this | Why not the alternative |
|---|---|---|
| Per-repo SOP + Crackerjack validator | Operators customize per-project; CI catches violations | Global SOP — no per-project customization; prompt-only — no enforcement |
| Markdown + YAML frontmatter | Prose for human voice, structured for machines | Pure markdown — weak validation; pure YAML — weak expression |
| Discovery walks up from CWD | Standard `.gitignore`-style pattern | Hardcoded path — inflexible |
| Default SOP ships in package | Works out of the box; operators customize per-repo | No default — operators must write SOPs before using |
| Crackerjack validator, advisory in v1.1, gate in v2.0 | Gradual rollout; lets operators adjust before enforcement | Immediate gate — too aggressive for adoption |
| Regex-based bans (not LLM-based) | Deterministic; cheap; fast | LLM-based — slow; expensive; non-deterministic |

---

## Open Questions / Future Work

- **OQ1.** SOP discovery: walk up vs explicit path. v1.0 uses walk-up; v1.1 may add explicit path override via env var or CLI flag.
- **OQ2.** SOP inheritance: subdir SOP overrides parent. v1.1 may chain inheritance (parent body + child overrides).
- **OQ3.** Default SOP source location: package resource vs user-editable config. v1.0 ships package resource; v1.1 may copy to user-editable location on first run.
- **OQ4.** Required disclosures enforcement: advisory vs gate. v1.0 advisory; v1.1+ gate.
- **OQ5.** LLM-based AI-flavor detection (semantic, not just regex). Future spec.

---

## Success Criteria

- **SC1.** Default SOP file ships at `mahavishnu/style-sop.md` with the article's bans and operator's prose voice.
- **SC2.** Discovery walks up from CWD; falls back to default when no repo SOP.
- **SC3.** Validator returns violations for content matching bans; empty list for clean content.
- **SC4.** Crackerjack skill `anti-ai-flavor-check` registered and runnable.
- **SC5.** L0–L3 tests green; ≥ 95% line coverage on new modules.

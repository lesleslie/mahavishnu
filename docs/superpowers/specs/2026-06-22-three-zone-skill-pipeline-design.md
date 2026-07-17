---
status: draft
role: implementation
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
blocks_on: []
topic: convergence-control-plane
---

# Three-Zone Skill Pipeline v1.0 — Design

**Status:** Draft (brainstormed 2026-06-22)  <!-- legacy status: Draft (brainstormed 2026-06-22) — see YAML frontmatter -->
**Phase:** 2 (Workflow Evolution)
**Source:** `Rebuilt Hermes / MAOS` — Part 4 ("Self-Learning — Fixed, Not Removed"). The MAOS three-zone pipeline (staging → systems → promoted) plus audit log is the structural fix for autonomous self-learning silently overwriting manually-tuned skills.

______________________________________________________________________

## Overview

This spec introduces a three-zone filesystem layout for skills, an append-only Dhara audit log for transitions, a CLI for human-promoted transitions, and an auto-learning helper that enforces "staging only" at the code level.

**Zones:**

- `commands/{tools,workflows}/staging/` — proposal zone. Agent writes here only. Never active.
- `commands/{tools,workflows}/systems/` — active zone. Human-promoted skills. Used by agents.
- `commands/{tools,workflows}/promoted/` — archive zone. Retired versions, never deleted. Filename suffixed with retirement date.

**Architectural property:** The agent proposes; the human disposes; history is preserved. Mirrors the article's "the agent cannot promote its own work" principle.

______________________________________________________________________

## Goals

- **G1.** Prevent autonomous skill learning from silently overwriting manually-tuned skills.
- **G2.** Operators see proposals via `git diff` on `staging/`; promotion is reviewable code change.
- **G3.** All transitions recorded in append-only audit log; full history of any skill is queryable.
- **G4.** Code-level enforcement: workers cannot bypass the staging-only rule.
- **G5.** Reuse existing `request_approval` MCP tool for the human promotion gate.

## Non-Goals

- **N1.** Auto-discovery of staged skills by Crackerjack (deferred to v1.1; Crackerjack currently discovers from `commands/` root only).
- **N2.** Skill content validation (linting, schema enforcement). Staging accepts any well-formed markdown.
- **N3.** Skill dependency resolution. Skills remain independent files; no `requires:` metadata in v1.0.

______________________________________________________________________

## Architecture & Data Flow

```
Skill lifecycle:

  1. Worker identifies a repeatable pattern
     └─> stage_skill(name, content, kind, actor, reason)
         └─> Writes commands/{kind}/staging/<name>.md
         └─> Records audit log entry: (skill_name, from="none", to="staging")

  2. Operator reviews staging/<name>.md (git diff, filesystem read)
     └─> Operator runs: mahavishnu skill promote <name> --kind tools --reason "..."
         └─> CLI calls request_approval(approval_type="skill_promote", options=[promote|edit|reject|hold])
             ├─> "promote": file moves staging/ → systems/; audit (staging → systems)
             ├─> "edit": file stays in staging/; operator edits and re-runs
             ├─> "reject": file stays in staging/; audit records rejection
             └─> "hold": file stays in staging/; audit records hold

  3. Active skill in systems/ is used by agents

  4. Operator deprecates active skill
     └─> Operator runs: mahavishnu skill archive <name> --kind tools --reason "..."
         └─> CLI moves systems/<name>.md → promoted/<name>-<YYYY-MM-DD>.md; audit
```

______________________________________________________________________

## Filesystem Layout

```
commands/
├── tools/
│   ├── staging/    # agents write here; never auto-promoted
│   ├── systems/    # active; human-promoted
│   └── promoted/   # archive; never deleted
└── workflows/
    ├── staging/
    ├── systems/
    └── promoted/
```

Each skill is a single markdown file (existing convention). Filename (without `.md`) is the skill's identity.

**Migration:** v1.0 ships with all existing `commands/tools/*.md` and `commands/workflows/*.md` content moved into `commands/{kind}/systems/`. No semantic change to skill content.

______________________________________________________________________

## Audit Log Schema (Dhara)

Table `skill_transitions`:

| Column | Type | Description |
|---|---|---|
| `transition_id` | UUID | primary key |
| `skill_name` | string | filename without `.md` |
| `skill_kind` | enum (`tool`, `workflow`) | from path |
| `from_zone` | enum (`none`, `staging`, `systems`, `promoted`) | — |
| `to_zone` | enum (`none`, `staging`, `systems`, `promoted`) | — |
| `actor` | string | user_id, `system:cli`, or `system:agent:<id>` |
| `reason` | string | operator-supplied note |
| `confidence` | int | null | agent confidence if staging; null on human transitions |
| `content_hash` | string | SHA-256 of file content at transition time |
| `transition_at` | timestamp | UTC |

Indexes: `(skill_name, transition_at DESC)`, `(actor, transition_at DESC)`.

______________________________________________________________________

## CLI Commands

```python
# mahavishnu/cli/skill_cli.py

import hashlib
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

import typer

from mahavishnu.core.dhara_client import execute, query
from mahavishnu.mcp.tools.approval_tools import request_approval


skill_app = typer.Typer(help="Three-zone skill pipeline management")

ZONES = ("staging", "systems", "promoted")
SKILL_KINDS = ("tools", "workflows")
SKILLS_ROOT = Path("commands")


def _resolve_path(kind: str, zone: str, name: str) -> Path:
    return SKILLS_ROOT / kind / zone / f"{name}.md"


def _audit(
    *,
    skill_name: str,
    skill_kind: str,
    from_zone: str,
    to_zone: str,
    actor: str,
    reason: str,
    content_hash: str,
    confidence: int | None = None,
) -> None:
    execute(
        "INSERT INTO skill_transitions "
        "(transition_id, skill_name, skill_kind, from_zone, to_zone, "
        " actor, reason, confidence, content_hash, transition_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
        (
            str(uuid.uuid4()),
            skill_name,
            skill_kind,
            from_zone,
            to_zone,
            actor,
            reason,
            confidence,
            content_hash,
        ),
    )


@skill_app.command("promote")
def promote(
    skill: str = typer.Argument(help="Skill filename without .md"),
    kind: str = typer.Option("tools", "--kind", help="tools or workflows"),
    reason: str = typer.Option("", "--reason", help="Reason for promotion"),
) -> None:
    """Promote a skill from staging to systems (human approval required)."""
    staging_path = _resolve_path(kind, "staging", skill)
    if not staging_path.exists():
        typer.echo(f"Skill not found in staging: {staging_path}")
        raise typer.Exit(code=1)

    content_hash = hashlib.sha256(staging_path.read_bytes()).hexdigest()
    decision = request_approval(
        approval_type="skill_promote",
        context={
            "skill_name": skill,
            "skill_kind": kind,
            "from_zone": "staging",
            "to_zone": "systems",
            "content_hash": content_hash,
            "reason": reason,
            "options": ["promote", "edit", "reject", "hold"],
        },
    )

    if decision == "promote":
        systems_path = _resolve_path(kind, "systems", skill)
        systems_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staging_path), str(systems_path))
        _audit(
            skill_name=skill,
            skill_kind=kind,
            from_zone="staging",
            to_zone="systems",
            actor="system:cli",
            reason=reason,
            content_hash=content_hash,
        )
        typer.echo(f"Promoted {skill} to systems/")
    elif decision == "reject":
        _audit(
            skill_name=skill,
            skill_kind=kind,
            from_zone="staging",
            to_zone="staging",
            actor="system:cli",
            reason=f"rejected: {reason}",
            content_hash=content_hash,
        )
        typer.echo(f"Promotion rejected: {skill} stays in staging/")
    else:
        typer.echo(f"Promotion on hold: {skill} stays in staging/")


@skill_app.command("archive")
def archive(
    skill: str = typer.Argument(help="Skill filename without .md"),
    kind: str = typer.Option("tools", "--kind", help="tools or workflows"),
    reason: str = typer.Option("", "--reason", help="Reason for archiving"),
) -> None:
    """Archive a skill from systems to promoted (with retirement date)."""
    systems_path = _resolve_path(kind, "systems", skill)
    if not systems_path.exists():
        typer.echo(f"Skill not found in systems: {systems_path}")
        raise typer.Exit(code=1)

    retirement_date = datetime.now(UTC).strftime("%Y-%m-%d")
    promoted_path = _resolve_path(kind, "promoted", f"{skill}-{retirement_date}")

    content_hash = hashlib.sha256(systems_path.read_bytes()).hexdigest()
    promoted_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(systems_path), str(promoted_path))
    _audit(
        skill_name=skill,
        skill_kind=kind,
        from_zone="systems",
        to_zone="promoted",
        actor="system:cli",
        reason=reason,
        content_hash=content_hash,
    )
    typer.echo(f"Archived {skill} → {promoted_path.name}")


@skill_app.command("list")
def list_skills(
    zone: str = typer.Option("all", "--zone", help="staging|systems|promoted|all"),
) -> None:
    """List skills by zone."""
    for kind in SKILL_KINDS:
        zones_to_show = ZONES if zone == "all" else (zone,)
        for z in zones_to_show:
            zone_path = SKILLS_ROOT / kind / z
            if not zone_path.exists():
                continue
            skills = sorted(p.stem for p in zone_path.glob("*.md"))
            if skills:
                typer.echo(f"{kind}/{z}/: {', '.join(skills)}")
```

______________________________________________________________________

## Auto-Learning Helper

```python
# mahavishnu/core/skill_staging.py

import hashlib
from pathlib import Path

from mahavishnu.cli.skill_cli import _audit, _resolve_path, SKILLS_ROOT


async def stage_skill(
    skill_name: str,
    content: str,
    kind: str,
    actor: str,
    reason: str,
    confidence: int | None = None,
) -> Path:
    """Write a skill to staging/ and audit the staging action.

    Workers call this when they identify a repeatable pattern.
    Code-level enforcement: the helper writes ONLY to staging/.
    Direct writes to systems/ are detected by `mahavishnu skill --audit-coverage`.
    """
    if kind not in ("tools", "workflows"):
        raise ValueError(f"unknown skill kind: {kind}")
    staging_path = _resolve_path(kind, "staging", skill_name)
    staging_path.parent.mkdir(parents=True, exist_ok=True)
    staging_path.write_text(content)
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    _audit(
        skill_name=skill_name,
        skill_kind=kind,
        from_zone="none",
        to_zone="staging",
        actor=actor,
        reason=reason,
        content_hash=content_hash,
        confidence=confidence,
    )
    return staging_path
```

______________________________________________________________________

## Adoption & Migration

| Version | Adoption policy |
|---|---|
| **v1.0** | Three-zone dirs created; existing `commands/{tools,workflows}/*.md` content moved into `systems/` subdirs. CLI shipped. Auto-learning helper shipped. Workers opt-in via `stage_skill()`. |
| **v1.1** | Workers that auto-learn (per Spec #1-3 pipeline) MUST use `stage_skill()`. Direct file writes outside the helper log deprecation warnings. Crackerjack discovers staged skills with `enabled_by_default: false` frontmatter marker. |
| **v2.0** | Direct file writes to `commands/{tools,workflows}/systems/` are blocked at the filesystem level; only the CLI + approval can populate the active zone. |

**Migration script** (one-time, runs at v1.0 deploy):

```bash
mkdir -p commands/tools/{staging,systems,promoted}
mkdir -p commands/workflows/{staging,systems,promoted}
git mv commands/tools/*.md commands/tools/systems/   # if not already in systems/
git mv commands/workflows/*.md commands/workflows/systems/
```

______________________________________________________________________

## Storage & Retrieval

**Dhara `skill_transitions` table** — append-only. Retention 365 days (longer than iteration reports; skill history is more durable).

**Query helper** (out of scope for v1.0; documented for v1.1):

```python
async def get_skill_history(skill_name: str) -> list[dict]:
    rows = query(
        "SELECT * FROM skill_transitions WHERE skill_name = ? ORDER BY transition_at DESC",
        (skill_name,),
    )
    return rows


async def get_active_skills(kind: str | None = None) -> list[str]:
    """List currently-active skill names (those in systems/)."""
    if kind:
        zone_path = SKILLS_ROOT / kind / "systems"
        return sorted(p.stem for p in zone_path.glob("*.md")) if zone_path.exists() else []
    result = []
    for k in ("tools", "workflows"):
        result.extend(await get_active_skills(k))
    return result
```

______________________________________________________________________

## Error Handling

| Failure | Detection | Response |
|---|---|---|
| Skill not in staging on promote | `staging_path.exists()` returns False | CLI exits with code 1; no audit entry recorded. |
| `request_approval` fails | Exception in CLI | Bubbles up; no file move; no audit entry. |
| Dhara audit write fails | Exception in `_audit` | File move still happens; audit log is best-effort with warning. (v1.0 trade-off: file move is the durable state; audit is observational.) |
| Direct write to systems/ detected | `mahavishnu skill --audit-coverage` scans for files outside staging or promoted | Reports violations; non-zero exit code; CI gate (v2.0). |
| Staging skill written but never promoted | Periodic operator review (out of scope for spec) | Operator decides: promote, edit, reject, hold. |
| Two operators promote same skill concurrently | Race on file move | Last write wins; audit log records both attempts. v1.1: add file locking. |

______________________________________________________________________

## Testing Strategy

| Layer | Tests |
|---|---|
| **L0 (pure boundary)** | `_resolve_path` produces correct paths. `_audit` SQL parameters correct. `stage_skill` writes file + records audit entry. Hashing is deterministic. |
| **L1 (file isolation)** | Real filesystem: `promote` moves staging → systems; `archive` moves systems → promoted/<name>-<date>.md. Audit log records correct from_zone/to_zone. |
| **L2 (service isolation)** | `request_approval` mocked: returns "promote" → file moved. Returns "reject" → file stays. Returns "hold" → file stays. Returns "edit" → file stays. Dhara write mocked; verifies correct SQL params. |
| **L3 (sandbox)** | Real filesystem + real Dhara + mocked approval: full promotion flow. |
| **L4 (integration)** | Worker auto-learning flow: `stage_skill` → `promote` → audit chain complete. CI integration: `--audit-coverage` flags direct writes. |

**Coverage target:** `tests/unit/test_skill_cli.py`, `tests/unit/test_skill_staging.py`, `tests/integration/test_skill_pipeline.py` ≥ 95% line coverage.

______________________________________________________________________

## Implementation Module Paths

| Component | Path |
|---|---|
| CLI commands | `mahavishnu/cli/skill_cli.py` |
| Auto-learning helper | `mahavishnu/core/skill_staging.py` |
| Dhara migration (table creation) | `mahavishnu/core/dhara_migrations/skill_transitions.sql` |
| L0/L1 tests | `tests/unit/test_skill_cli.py` |
| L2 tests | `tests/integration/test_skill_cli_approval.py` |
| L3 tests | `tests/integration/test_skill_pipeline.py` |
| Coverage scan | `mahavishnu/cli/skill_cli.py` (`audit-coverage` command) |

______________________________________________________________________

## Trade-offs & Alternatives Considered

| Choice | Why this | Why not the alternative |
|---|---|---|
| Filesystem zones + Dhara audit | Operators see proposals via `git diff`; structured queryability via Dhara | Filesystem only — no structured query; Dhara only — no git visibility |
| CLI + approval gate via `request_approval` | Mirrors article's "human in the loop"; reuses existing surface | Direct CLI without approval — bypasses human gate |
| Append-only audit log (no edits/deletes) | History preservation is the whole point of the audit log | Mutable audit log — defeats the purpose |
| `stage_skill()` helper enforces staging-only at code level | Workers cannot bypass | Prompt-only enforcement — known failure mode |
| Retirement date in filename (`promoted/<name>-<YYYY-MM-DD>.md`) | Same skill name can be archived multiple times without collision | Single promoted/<name>.md — overwrites on re-archive |
| Confidence column in audit row | Useful for filtering "high-confidence proposals"; supports v1.1 query helpers | Skip confidence — simpler schema; loses observability |

______________________________________________________________________

## Open Questions / Future Work

- **OQ1.** Skill content hash: SHA-256 of file content. Useful for "is this the same skill we promoted?". Adopt in v1.0.
- **OQ2.** Skill name collision: skill `<name>.md` in both `staging/` and `systems/`. Disallowed in v1.0; CLI checks before promotion.
- **OQ3.** Crackerjack auto-discovery of staged skills. v1.1 work; uses frontmatter `enabled_by_default: false` marker to gate activation.
- **OQ4.** Skill dependency resolution. v1.1+ work; `requires:` metadata in skill frontmatter.
- **OQ5.** Bulk promotion (multiple skills in one approval). Out of scope for v1.0; documented for v1.1.

______________________________________________________________________

## Success Criteria

- **SC1.** Three-zone dirs created; existing content migrated.
- **SC2.** CLI commands shipped: `promote`, `archive`, `list`, `audit-coverage`.
- **SC3.** `stage_skill()` helper enforces staging-only at code level.
- **SC4.** Dhara `skill_transitions` table created and populated by all CLI operations and the helper.
- **SC5.** Promotion routes through `request_approval` MCP tool; non-promote outcomes (reject/hold/edit) recorded in audit log.
- **SC6.** L0–L3 tests green; ≥ 95% line coverage on new modules.

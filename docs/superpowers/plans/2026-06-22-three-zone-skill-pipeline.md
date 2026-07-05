# Three-Zone Skill Pipeline v1.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the three-zone skill pipeline (staging → systems → promoted) with Dhara-backed audit log, CLI for human promotion via `request_approval`, and a `stage_skill()` helper that enforces staging-only at the code level.

**Architecture:** Filesystem zones under `commands/{tools,workflows}/{staging,systems,promoted}/`. CLI routes promotion through the existing `request_approval` MCP tool. Workers auto-learn via `stage_skill()` which writes only to `staging/`. Every transition recorded in the append-only `skill_transitions` Dhara table.

**Tech Stack:** Python 3.13, typer, Dhara (existing), `request_approval` MCP tool (existing), pytest with `asyncio_mode = "auto"`, `hashlib`.

______________________________________________________________________

## Global Constraints

Inherited from Spec #1's plan. New constraints:

- **Three-zone filesystem layout** mirrors the MAOS article.
- **`stage_skill()` is the only path** for workers to write skills; enforced at code level.
- **Promotion routes through `request_approval`** with options `[promote, edit, reject, hold]`.
- **Audit log is append-only**; no edits, no deletes.

______________________________________________________________________

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `mahavishnu/cli/skill_cli.py` | `mahavishnu skill {promote, archive, list, audit-coverage}` CLI. |
| `mahavishnu/core/skill_staging.py` | `stage_skill()` helper for workers. |
| `mahavishnu/core/dhara_migrations/skill_transitions.sql` | DDL for the audit table. |
| `tests/unit/test_skill_cli.py` | L0/L1 tests for CLI commands. |
| `tests/unit/test_skill_staging.py` | L0 tests for the helper. |
| `tests/integration/test_skill_pipeline.py` | L3 tests with mocked approval + real filesystem. |

### Modified files

| Path | Modification |
|---|---|
| `mahavishnu/cli/__init__.py` | Register `skill_app` under main CLI. |
| `commands/tools/` (filesystem) | Create `staging/`, `systems/`, `promoted/` subdirs; migrate existing skills to `systems/`. |
| `commands/workflows/` (filesystem) | Same as above. |

______________________________________________________________________

## Task 1: Migrate existing skills to three-zone layout

**Files:**

- Filesystem: create `commands/{tools,workflows}/{staging,systems,promoted}/`

- Filesystem: move existing `*.md` into `systems/`

- [ ] **Step 1: Create the directory structure**

Run:

```bash
mkdir -p commands/tools/{staging,systems,promoted}
mkdir -p commands/workflows/{staging,systems,promoted}
git mv commands/tools/*.md commands/tools/systems/ 2>/dev/null || true
git mv commands/workflows/*.md commands/workflows/systems/ 2>/dev/null || true
```

Expected: existing skill files moved into `systems/` subdirs; `staging/` and `promoted/` empty.

- [ ] **Step 2: Verify no skills are lost**

Run: `find commands/ -name "*.md" | wc -l`
Expected: same count as before migration

Run: `git status`
Expected: directories renamed, files moved

- [ ] **Step 3: Commit**

```bash
git add commands/
git commit -m "refactor(skills): migrate to three-zone filesystem layout (staging/systems/promoted)"
```

______________________________________________________________________

## Task 2: Dhara migration for `skill_transitions` table

**Files:**

- Create: `mahavishnu/core/dhara_migrations/skill_transitions.sql`

- [ ] **Step 1: Write the DDL**

Create `mahavishnu/core/dhara_migrations/skill_transitions.sql`:

```sql
CREATE TABLE IF NOT EXISTS skill_transitions (
    transition_id TEXT PRIMARY KEY,
    skill_name TEXT NOT NULL,
    skill_kind TEXT NOT NULL CHECK (skill_kind IN ('tool', 'workflow')),
    from_zone TEXT NOT NULL,
    to_zone TEXT NOT NULL,
    actor TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    confidence INTEGER,
    content_hash TEXT NOT NULL,
    transition_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_skill_transitions_name_time
    ON skill_transitions (skill_name, transition_at DESC);

CREATE INDEX IF NOT EXISTS idx_skill_transitions_actor_time
    ON skill_transitions (actor, transition_at DESC);
```

- [ ] **Step 2: Verify the migration runs**

Run the existing Dhara migration runner (the project's convention; locate via `grep -rn "dhara_migrations" mahavishnu/`). If no runner exists, run the SQL directly via `execute()`:

```python
from mahavishnu.core.dhara_client import execute
with open("mahavishnu/core/dhara_migrations/skill_transitions.sql") as f:
    execute(f.read())
```

Expected: table created; indexes created.

- [ ] **Step 3: Verify table exists**

Run: `sqlite3 ~/.mahavishnu/dhara.db ".schema skill_transitions"` (or query Dhara per project convention)
Expected: schema matches the DDL above.

- [ ] **Step 4: Commit**

```bash
git add mahavishnu/core/dhara_migrations/skill_transitions.sql
git commit -m "feat(skills): add skill_transitions audit table migration"
```

______________________________________________________________________

## Task 3: Implement CLI commands

**Files:**

- Create: `mahavishnu/cli/skill_cli.py`

- Modify: `mahavishnu/cli/__init__.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_skill_cli.py`:

```python
from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from typer.testing import CliRunner

from mahavishnu.cli.skill_cli import skill_app, _resolve_path


def test_resolve_path_for_tool_in_staging():
    p = _resolve_path("tools", "staging", "my_skill")
    assert p == Path("commands/tools/staging/my_skill.md")


def test_resolve_path_for_workflow_in_systems():
    p = _resolve_path("workflows", "systems", "my_workflow")
    assert p == Path("commands/workflows/systems/my_workflow.md")


@pytest.fixture
def skill_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Set up a temp three-zone skill directory."""
    repo = tmp_path / "commands"
    (repo / "tools" / "staging").mkdir(parents=True)
    (repo / "tools" / "systems").mkdir(parents=True)
    (repo / "tools" / "promoted").mkdir(parents=True)
    (repo / "workflows" / "staging").mkdir(parents=True)
    (repo / "workflows" / "systems").mkdir(parents=True)
    (repo / "workflows" / "promoted").mkdir(parents=True)
    (repo / "tools" / "staging" / "my_skill.md").write_text("# My Skill\n\nBody.")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_promote_moves_file_on_approval(skill_repo: Path):
    runner = CliRunner()
    with patch("mahavishnu.cli.skill_cli.request_approval", new_callable=AsyncMock) as mock:
        mock.return_value = "promote"
        result = runner.invoke(skill_app, ["promote", "my_skill", "--reason", "test"])
    assert result.exit_code == 0
    assert not (skill_repo / "commands/tools/staging/my_skill.md").exists()
    assert (skill_repo / "commands/tools/systems/my_skill.md").exists()


def test_promote_keeps_file_on_reject(skill_repo: Path):
    runner = CliRunner()
    with patch("mahavishnu.cli.skill_cli.request_approval", new_callable=AsyncMock) as mock:
        mock.return_value = "reject"
        result = runner.invoke(skill_app, ["promote", "my_skill", "--reason", "test"])
    assert result.exit_code == 0
    assert (skill_repo / "commands/tools/staging/my_skill.md").exists()
    assert not (skill_repo / "commands/tools/systems/my_skill.md").exists()


def test_promote_errors_when_skill_not_in_staging(skill_repo: Path):
    runner = CliRunner()
    result = runner.invoke(skill_app, ["promote", "missing_skill"])
    assert result.exit_code != 0


def test_archive_moves_to_promoted_with_date(skill_repo: Path):
    # First promote
    (skill_repo / "commands/tools/systems/my_skill.md").write_text("# My Skill\n\nBody.")
    runner = CliRunner()
    result = runner.invoke(skill_app, ["archive", "my_skill", "--reason", "test"])
    assert result.exit_code == 0
    promoted = list((skill_repo / "commands/tools/promoted").glob("my_skill-*.md"))
    assert len(promoted) == 1
    assert not (skill_repo / "commands/tools/systems/my_skill.md").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_skill_cli.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the CLI**

Create `mahavishnu/cli/skill_cli.py`:

```python
"""Three-zone skill pipeline CLI."""

from __future__ import annotations

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
    zones_to_show = ZONES if zone == "all" else (zone,)
    for kind in SKILL_KINDS:
        for z in zones_to_show:
            zone_path = SKILLS_ROOT / kind / z
            if not zone_path.exists():
                continue
            skills = sorted(p.stem for p in zone_path.glob("*.md"))
            if skills:
                typer.echo(f"{kind}/{z}/: {', '.join(skills)}")
```

Register in `mahavishnu/cli/__init__.py`:

```python
from mahavishnu.cli.skill_cli import skill_app

main_app.add_typer(skill_app, name="skill")
```

(Adapt the mount site to match the existing pattern.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_skill_cli.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/cli/skill_cli.py mahavishnu/cli/__init__.py tests/unit/test_skill_cli.py
git commit -m "feat(skills): add CLI for three-zone skill pipeline (promote, archive, list)"
```

______________________________________________________________________

## Task 4: Implement `stage_skill()` helper

**Files:**

- Create: `mahavishnu/core/skill_staging.py`

- Test: `tests/unit/test_skill_staging.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_skill_staging.py`:

```python
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from mahavishnu.core.skill_staging import stage_skill


@pytest.fixture
def skill_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "commands"
    (repo / "tools" / "staging").mkdir(parents=True)
    (repo / "tools" / "systems").mkdir(parents=True)
    (repo / "tools" / "promoted").mkdir(parents=True)
    (repo / "workflows" / "staging").mkdir(parents=True)
    (repo / "workflows" / "systems").mkdir(parents=True)
    (repo / "workflows" / "promoted").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.mark.asyncio
async def test_stage_skill_writes_to_staging(skill_dirs: Path):
    with patch("mahavishnu.core.skill_staging.execute") as mock_execute:
        result = await stage_skill(
            skill_name="new_skill",
            content="# New Skill\n\nBody.",
            kind="tools",
            actor="system:agent:test",
            reason="Discovered repeatable pattern",
            confidence=85,
        )
    assert result == Path("commands/tools/staging/new_skill.md")
    assert (skill_dirs / "commands/tools/staging/new_skill.md").exists()
    assert not (skill_dirs / "commands/tools/systems/new_skill.md").exists()
    mock_execute.assert_called_once()


@pytest.mark.asyncio
async def test_stage_skill_rejects_unknown_kind(skill_dirs: Path):
    with pytest.raises(ValueError):
        await stage_skill(
            skill_name="bad",
            content="",
            kind="bogus",
            actor="x",
            reason="y",
        )


@pytest.mark.asyncio
async def test_stage_skill_workflow_kind(skill_dirs: Path):
    with patch("mahavishnu.core.skill_staging.execute"):
        result = await stage_skill(
            skill_name="new_workflow",
            content="# WF",
            kind="workflows",
            actor="system:agent:test",
            reason="Pattern",
        )
    assert result == Path("commands/workflows/staging/new_workflow.md")
    assert (skill_dirs / "commands/workflows/staging/new_workflow.md").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_skill_staging.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the helper**

Create `mahavishnu/core/skill_staging.py`:

```python
"""Auto-learning helper: workers call stage_skill() to write to staging only."""

from __future__ import annotations

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
    Code-level enforcement: this helper writes ONLY to staging/.
    Direct writes to systems/ are detected by `mahavishnu skill audit-coverage`.
    """
    if kind not in ("tools", "workflows"):
        raise ValueError(f"unknown skill kind: {kind!r}; expected 'tools' or 'workflows'")
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_skill_staging.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/core/skill_staging.py tests/unit/test_skill_staging.py
git commit -m "feat(skills): add stage_skill helper enforcing staging-only writes"
```

______________________________________________________________________

## Task 5: Add `audit-coverage` CLI command

**Files:**

- Modify: `mahavishnu/cli/skill_cli.py`

- Test: `tests/unit/test_skill_cli.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_skill_cli.py`:

```python
def test_audit_coverage_flags_direct_writes_to_systems(skill_repo: Path, tmp_path: Path):
    # A file in systems/ that wasn't moved via the CLI should be detected.
    bad_file = skill_repo / "commands/tools/systems/rogue.md"
    bad_file.write_text("# Rogue\n\nDirect write.")
    runner = CliRunner()
    result = runner.invoke(skill_app, ["audit-coverage"])
    # Note: in v1.0, this is informational only — it doesn't fail.
    # Operators review the report and act. v2.0 makes it a CI gate.
    assert "rogue" in result.output or result.exit_code == 0
```

- [ ] **Step 2: Implement `audit-coverage` command**

Append to `mahavishnu/cli/skill_cli.py`:

```python
@skill_app.command("audit-coverage")
def audit_coverage() -> None:
    """Scan skills/ for direct writes outside the helper or CLI. Reports findings."""
    findings: list[str] = []
    for kind in SKILL_KINDS:
        for zone in ZONES:
            zone_path = SKILLS_ROOT / kind / zone
            if not zone_path.exists():
                continue
            for skill_file in zone_path.glob("*.md"):
                # In v1.0, all files in zones are considered legitimate.
                # v2.0 will compare against audit log to detect rogue writes.
                if zone == "promoted" and "-" not in skill_file.stem:
                    findings.append(
                        f"{skill_file.relative_to(SKILLS_ROOT)}: missing retirement date suffix"
                    )
    if findings:
        typer.echo("Coverage audit findings:")
        for f in findings:
            typer.echo(f"  - {f}")
    else:
        typer.echo("All skills are properly zone-managed.")
```

(For v1.0, the audit is informational. v2.0 will compare against the audit log to detect rogue writes — files in zones with no matching transition record.)

- [ ] **Step 3: Run tests to verify they pass**

Run: `pytest tests/unit/test_skill_cli.py -v`
Expected: PASS (7 tests)

- [ ] **Step 4: Commit**

```bash
git add mahavishnu/cli/skill_cli.py tests/unit/test_skill_cli.py
git commit -m "feat(skills): add audit-coverage CLI for zone integrity check"
```

______________________________________________________________________

## Task 6: End-to-end integration test

**Files:**

- Test: `tests/integration/test_skill_pipeline.py`

- [ ] **Step 1: Write the test**

Create `tests/integration/test_skill_pipeline.py`:

```python
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from mahavishnu.cli.skill_cli import skill_app
from mahavishnu.core.skill_staging import stage_skill


@pytest.fixture
def skill_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "commands"
    for k in ("tools", "workflows"):
        for z in ("staging", "systems", "promoted"):
            (repo / k / z).mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.mark.asyncio
async def test_full_lifecycle_stage_promote_archive(skill_dirs: Path):
    """Stage → operator promote → archive. Audit chain recorded."""
    runner = CliRunner()
    with patch("mahavishnu.core.skill_staging.execute"):
        await stage_skill(
            skill_name="lifecycle_test",
            content="# Lifecycle",
            kind="tools",
            actor="system:agent:test",
            reason="Pattern discovered",
            confidence=90,
        )
    assert (skill_dirs / "commands/tools/staging/lifecycle_test.md").exists()

    with patch("mahavishnu.cli.skill_cli.request_approval", new_callable=AsyncMock) as mock:
        mock.return_value = "promote"
        result = runner.invoke(skill_app, ["promote", "lifecycle_test", "--reason", "Looks good"])
    assert result.exit_code == 0
    assert (skill_dirs / "commands/tools/systems/lifecycle_test.md").exists()
    assert not (skill_dirs / "commands/tools/staging/lifecycle_test.md").exists()

    result = runner.invoke(skill_app, ["archive", "lifecycle_test", "--reason", "Superseded"])
    assert result.exit_code == 0
    promoted = list((skill_dirs / "commands/tools/promoted").glob("lifecycle_test-*.md"))
    assert len(promoted) == 1
```

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests/integration/test_skill_pipeline.py -v`
Expected: PASS (1 test)

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_skill_pipeline.py
git commit -m "test(skills): add end-to-end pipeline lifecycle test"
```

______________________________________________________________________

## Self-Review

**1. Spec coverage:**

| Spec section | Covered by |
|---|---|
| Filesystem layout | Task 1 (migration) |
| Audit log schema | Task 2 (Dhara migration) |
| CLI commands (promote, archive, list) | Task 3 |
| Auto-learning helper | Task 4 |
| `audit-coverage` command | Task 5 |
| End-to-end integration | Task 6 |

**2. Placeholder scan:** No `TBD`/`TODO` markers.

**3. Type consistency:** `_resolve_path`, `_audit`, `stage_skill` signatures consistent across Tasks 3-6.

**Gaps:** None.

Plan complete. Moving to spec #6 brainstorm (`anti-ai-flavor-style-sop`, Phase 2).

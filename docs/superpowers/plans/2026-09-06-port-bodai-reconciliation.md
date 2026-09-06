---
status: active
role: implementation
date: 2026-09-06
last_reviewed: 2026-09-06
superseded_by: null
blocks_on:
  - docs/superpowers/specs/2026-09-06-mcp-stub-activation-design.md
topic: mcp-stub-activation
---

# Port and Bodai Config Reconciliation (Plan 0b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `bodai/config/portmap.yaml` describe the ports repos actually bind, repair
two stale entries in `bodai/config/ecosystem.yaml`, allocate 3054-3056 for the three new
MCP servers, and add a guard test so port drift fails `crackerjack run`.

**Architecture:** `portmap.yaml` is currently fiction in at least six places — it assigns
`css-mcp` to 3049 while css-mcp binds 3050, assigns `spline-mcp` to 3050 while spline
binds 3052, and omits `penpot-api-mcp` (3051), `mdinject` (8679), and `akosha`'s
`mcp_port` (3002) entirely. This plan audits ports from the repos themselves, treats the
repos as the source of truth, rewrites `portmap.yaml` to match, and pins the result with a
three-source uniqueness guard.

**Tech Stack:** Python 3.14, PyYAML, pytest, crackerjack.

**Spec:** `docs/superpowers/specs/2026-09-06-mcp-stub-activation-design.md` (§4.9, §7.2,
§7.3)

## Global Constraints

- **This plan edits two repositories.** `/Users/les/Projects/bodai` (configs and the new
  guard test) and read-only inspection of every other repo under `~/Projects`. All
  bodai-relative paths below are from `/Users/les/Projects/bodai`.
- Python `>=3.14`. `from __future__ import annotations` first non-comment line.
- Line length 100. No `assert` in production code; tests assert freely.
- Project pytest markers only. `asyncio_mode = "auto"`.
- **The repo's own `settings/*.yaml` is the source of truth for what port it binds.**
  `portmap.yaml` is a registry that must match reality, not a mandate that overrides it.
  Where they disagree, change `portmap.yaml`.
- **Do not delete `n8n-mcp`** — comment it out pending a consumer audit (Task 5).
- Commit after every task. Never `git push`.
- Bodai merges directly to `main` pre-1.0; no PR.

## File Structure

| File | Responsibility |
|---|---|
| `config/portmap.yaml` | **Modify.** Rewrite `allocations:` to match reality; add 3054-3056; narrow `reserved:` to 3057-3059. |
| `config/ecosystem.yaml` | **Modify.** `druva` → `dhara`; comment out `n8n-mcp`; add the three new components. |
| `tests/test_portmap_sync.py` | **Create.** Three-source port uniqueness and coverage guard. |
| `docs/2026-09-06-port-audit.md` | **Create.** The widened audit's raw output, so the next reconciliation starts from evidence rather than re-deriving it. |
| `docs/2026-09-06-unregistered-repos.md` | **Create.** Register-or-exclude decision for the four never-registered repos. |

______________________________________________________________________

## Phase 1: Establish ground truth

### Task 1: Widen the port audit beyond `settings/*.yaml`

The spec's §4.9 audit covered `settings/*.yaml` only and said so. Repos that declare
ports in code defaults, `.env`, or `pyproject.toml` were not scanned, so "3054-3056 are
free" is confirmed against three sources, not exhaustively. Close that gap before
allocating.

**Files:**

- Create: `docs/2026-09-06-port-audit.md`

**Interfaces:**

- Consumes: nothing.
- Produces: the authoritative port → repo mapping that Tasks 2 and 3 write into
  `portmap.yaml`. Task 6's guard test asserts against the same mapping.

- [ ] **Step 1: Scan `settings/*.yaml` (reproduces the spec's audit)**

```bash
cd /Users/les/Projects
for d in */; do
  d="${d%/}"
  case "$d" in ARCHIVED|BACKUP|SCRATCH|sites) continue;; esac
  [ -d "$d/settings" ] || continue
  grep -rhoE "^[a-z_]*port: *[0-9]{4}" "$d/settings/" 2>/dev/null \
    | while read -r line; do printf "%-24s settings  %s\n" "$d" "$line"; done
done | sort -u
```

- [ ] **Step 2: Scan Python code defaults**

```bash
cd /Users/les/Projects
for d in */; do
  d="${d%/}"
  case "$d" in ARCHIVED|BACKUP|SCRATCH|sites) continue;; esac
  grep -rhoE "(port|PORT)[^0-9]{0,20}(30[0-9]{2}|8[0-9]{3})" "$d" \
    --include="*.py" --exclude-dir=.venv --exclude-dir=tests \
    --exclude-dir=.claude --exclude-dir=node_modules 2>/dev/null \
    | sort -u | while read -r line; do printf "%-24s code      %s\n" "$d" "$line"; done
done | sort -u
```

- [ ] **Step 3: Scan `pyproject.toml` and `.env*` files**

```bash
cd /Users/les/Projects
for d in */; do
  d="${d%/}"
  case "$d" in ARCHIVED|BACKUP|SCRATCH|sites) continue;; esac
  for f in "$d/pyproject.toml" "$d"/.env "$d"/.env.*; do
    [ -f "$f" ] || continue
    grep -hoE "(port|PORT)[^0-9]{0,12}(30[0-9]{2}|8[0-9]{3})" "$f" 2>/dev/null \
      | while read -r line; do printf "%-24s %-9s %s\n" "$d" "$(basename "$f")" "$line"; done
  done
done | sort -u
```

- [ ] **Step 4: Scan launchd plists, which bind ports outside the repos**

```bash
ls ~/Library/LaunchAgents/ 2>/dev/null | grep -iE "bodai|mahavishnu|akosha|dhara|crackerjack|mcp" || echo "(no matching plists)"
grep -rhoE "(30[0-9]{2}|8[0-9]{3})" ~/Library/LaunchAgents/*.plist 2>/dev/null | sort -u | head -30
```

- [ ] **Step 5: Write the audit document**

Create `docs/2026-09-06-port-audit.md`. Do not summarize — paste the raw output of
Steps 1-4 under a heading each, then add a reconciled table:

```markdown
# Port Audit — 2026-09-06

Opened by Plan 0b to close the verification gap in
`mahavishnu/docs/superpowers/specs/2026-09-06-mcp-stub-activation-design.md` §4.9,
which audited `settings/*.yaml` only.

## Raw scans

### settings/*.yaml
<Step 1 output>

### Python code defaults
<Step 2 output>

### pyproject.toml and .env
<Step 3 output>

### launchd plists
<Step 4 output>

## Reconciled allocation

| Port | Repo | Declared in | portmap.yaml said | Action |
|---|---|---|---|---|
<one row per port found; Action is "match", "correct", or "add">

## Confirmed free

<list every port in 3030-3059 and 8676-8699 with no claimant, and state
whether 3054/3055/3056 survived the widened audit>
```

- [ ] **Step 6: Confirm the allocation target is still free**

If the widened audit shows **any** claimant on 3054, 3055, or 3056, stop and record
it prominently in the audit document. Pick the next three free ports from the
"Confirmed free" list instead, and use those consistently in Tasks 3 and 6 and in the
three server plans' settings. Do not proceed with a known collision — that is the
exact defect this plan exists to fix.

- [ ] **Step 7: Commit**

```bash
cd /Users/les/Projects/bodai
git add docs/2026-09-06-port-audit.md
git commit -m "docs(ports): widen port audit to code, pyproject, .env, and launchd

Closes the verification gap in the stub-activation spec §4.9, which covered
settings/*.yaml only. Raw scan output retained so the next reconciliation
starts from evidence."
```

#### Integration Contract — Phase 1

- **Triggered from:** manual invocation during Plan 0b. Not a runtime code path.
- **Returns to / updates:** `bodai/docs/2026-09-06-port-audit.md`. Its reconciled table
  is the input to Tasks 2, 3, and 6.
- **Demonstrable by:** the document exists, contains raw output from all four scans, and
  its "Confirmed free" section explicitly states whether 3054-3056 are unclaimed.
- **Rollback signal:** none — the task only writes a document. If the audit contradicts
  the spec's §4.9 table, that is a finding, not a failure.
- **Observability added:** none (documentation task). The guard test in Task 6 is what
  makes future drift observable.

______________________________________________________________________

## Phase 2: Reconcile the configs

### Task 2: Correct the six wrong `portmap.yaml` allocations

**Files:**

- Modify: `config/portmap.yaml`
- Test: `tests/test_portmap_sync.py` (create)

**Interfaces:**

- Consumes: the reconciled table from Task 1.
- Produces: a `portmap.yaml` whose `allocations:` matches repo reality. Task 3 appends to
  it; Task 6 asserts over it.

- [ ] **Step 1: Write the failing test**

Create `tests/test_portmap_sync.py`:

```python
"""Guard against drift between portmap.yaml and the ports repos actually bind.

portmap.yaml is a registry, not a mandate: a repo's own settings/*.yaml
decides what it binds. Before Plan 0b, portmap.yaml was wrong about six
allocations — it assigned css-mcp to 3049 while css-mcp bound 3050, assigned
spline-mcp to 3050 while spline bound 3052, and omitted penpot-api-mcp,
mdinject, and akosha's mcp_port entirely. A collision would have surfaced
only as a bind failure at runtime.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

BODAI_ROOT = Path(__file__).resolve().parents[1]
PROJECTS_ROOT = BODAI_ROOT.parent
PORTMAP_PATH = BODAI_ROOT / "config" / "portmap.yaml"
ECOSYSTEM_PATH = BODAI_ROOT / "config" / "ecosystem.yaml"

SKIP_DIRS = {"ARCHIVED", "BACKUP", "SCRATCH", "sites"}
PORT_LINE = re.compile(r"^[a-z_]*port:\s*(\d{4})\s*$", re.MULTILINE)


def _load(path: Path) -> dict[str, Any]:
    with path.open() as handle:
        return yaml.safe_load(handle)


def _portmap_allocations() -> dict[int, str]:
    """Port -> component name, excluding the 'available' placeholder rows."""
    raw = _load(PORTMAP_PATH).get("allocations", {})
    return {
        int(port): name
        for port, name in raw.items()
        if isinstance(name, str) and name != "available"
    }


def _repo_declared_ports() -> dict[int, set[str]]:
    """Port -> set of repo names declaring it in their own settings/*.yaml."""
    found: dict[int, set[str]] = {}
    for repo_dir in sorted(PROJECTS_ROOT.iterdir()):
        if not repo_dir.is_dir() or repo_dir.name in SKIP_DIRS:
            continue
        if repo_dir.name.startswith("."):
            continue
        settings_dir = repo_dir / "settings"
        if not settings_dir.is_dir():
            continue
        for settings_file in settings_dir.glob("*.yaml"):
            for match in PORT_LINE.finditer(settings_file.read_text()):
                found.setdefault(int(match.group(1)), set()).add(repo_dir.name)
    return found


@pytest.mark.unit
class TestPortmapMatchesReality:
    """portmap.yaml must agree with what repos declare."""

    def test_no_portmap_entry_contradicts_a_repo(self) -> None:
        """If portmap says port P belongs to A but repo B declares P, that is a
        contradiction the registry must resolve in the repo's favour."""
        allocations = _portmap_allocations()
        declared = _repo_declared_ports()
        contradictions = {
            port: {"portmap": allocations[port], "declared_by": sorted(repos)}
            for port, repos in declared.items()
            if port in allocations and allocations[port] not in repos
        }
        assert contradictions == {}, f"portmap contradicts repos: {contradictions}"

    def test_every_declared_port_is_in_portmap(self) -> None:
        """A repo binding an unregistered port can collide with a future
        allocation without anything noticing."""
        allocations = _portmap_allocations()
        declared = _repo_declared_ports()
        unregistered = {
            port: sorted(repos)
            for port, repos in declared.items()
            if port not in allocations
        }
        assert unregistered == {}, f"declared but not in portmap: {unregistered}"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/les/Projects/bodai
.venv/bin/pytest tests/test_portmap_sync.py -v
```

Expected: `test_no_portmap_entry_contradicts_a_repo` FAILS, naming 3049/3050 (portmap
says `css-mcp` at 3049, css-mcp declares 3050), 3050 (portmap says `spline-mcp`,
css-mcp declares it), 8684 and 8685 (portmap says `fastblocks`/`mdinject`, crackerjack
declares both). `test_every_declared_port_is_in_portmap` FAILS naming 3002 (akosha
`mcp_port`), 3051 (penpot-api-mcp), 3052 (spline-mcp), 8679 (mdinject), and possibly
3000 (session-buddy `server_port`).

Record the exact failure output — it is the checklist for Step 3.

- [ ] **Step 3: Rewrite `allocations:` to match the audit**

Edit `config/portmap.yaml`. Correct the contradictions and add the omissions, keeping
the file's existing `PORT: name  # comment` style. The corrections, per Task 1's audit:

```yaml
  3002: akosha            # Akosha MCP port (distinct from api_port 8682)
  3049: available         # Reserved (css-mcp actually binds 3050)
  3050: css-mcp           # CSS analysis and documentation
  3051: penpot-api-mcp    # Penpot design platform API
  3052: spline-mcp        # Spline.design 3D scene orchestration
```

and in the core range:

```yaml
  8679: mdinject          # Markdown injection and content healing
  8684: crackerjack       # Crackerjack dashboard_port
  8685: crackerjack       # Crackerjack zuban_port
```

If Task 1's audit found `session-buddy` declaring `server_port: 3000`, add
`3000: session-buddy` with a comment distinguishing it from the MCP port 8678 — a repo
legitimately binding two ports needs both registered.

**Do not** remove `fastblocks` from the file without a home for it: if 8684 now belongs
to crackerjack, either find fastblocks' real port in Task 1's audit and register that,
or add a comment noting fastblocks has no declared port. Silently dropping a component
is how this drift started.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/les/Projects/bodai
.venv/bin/pytest tests/test_portmap_sync.py -v
```

Expected: both tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/bodai
git add config/portmap.yaml tests/test_portmap_sync.py
git commit -m "fix(ports): reconcile portmap.yaml with the ports repos actually bind

portmap.yaml was wrong about six allocations: css-mcp 3049 -> 3050,
spline-mcp 3050 -> 3052, and it omitted penpot-api-mcp 3051, mdinject 8679,
akosha 3002, while assigning 8684/8685 to fastblocks/mdinject when
crackerjack binds both.

Guard test treats each repo's settings/*.yaml as the source of truth and
fails on contradiction or omission."
```

### Task 3: Allocate 3054-3056 and narrow the reserved range

**Files:**

- Modify: `config/portmap.yaml`
- Modify: `tests/test_portmap_sync.py`

**Interfaces:**

- Consumes: the corrected `allocations:` from Task 2; the free-port confirmation from
  Task 1 Step 6.
- Produces: `3054: archive-org-mcp`, `3055: medium-mcp`, `3056: scapy-mcp`. **The three
  server plans hard-code these in their `settings/<name>.yaml`** — if Task 1 forced
  different ports, update all three server plans in the same commit.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_portmap_sync.py`:

```python
NEW_SERVER_PORTS = {
    3054: "archive-org-mcp",
    3055: "medium-mcp",
    3056: "scapy-mcp",
}


@pytest.mark.unit
class TestNewServerPorts:
    """The three new MCP servers must have registered, non-colliding ports."""

    @pytest.mark.parametrize(("port", "name"), sorted(NEW_SERVER_PORTS.items()))
    def test_new_server_port_allocated(self, port: int, name: str) -> None:
        assert _portmap_allocations().get(port) == name

    def test_new_server_ports_are_unique(self) -> None:
        allocations = _portmap_allocations()
        for port, name in NEW_SERVER_PORTS.items():
            others = {p: n for p, n in allocations.items() if p != port and n == name}
            assert others == {}, f"{name} also allocated at {others}"

    def test_reserved_range_excludes_allocated_ports(self) -> None:
        """A port cannot be both allocated and reserved for future expansion."""
        reserved = _load(PORTMAP_PATH).get("reserved", {})
        allocated = set(_portmap_allocations())
        overlaps: dict[str, list[int]] = {}
        for key in reserved:
            match = re.fullmatch(r"(\d{4})-(\d{4})", str(key))
            if not match:
                continue
            low, high = int(match.group(1)), int(match.group(2))
            hits = sorted(p for p in allocated if low <= p <= high)
            if hits:
                overlaps[str(key)] = hits
        assert overlaps == {}, f"reserved ranges overlap allocations: {overlaps}"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/les/Projects/bodai
.venv/bin/pytest tests/test_portmap_sync.py::TestNewServerPorts -v
```

Expected: the three `test_new_server_port_allocated` cases FAIL (not yet allocated).
`test_reserved_range_excludes_allocated_ports` FAILS on `3050-3059`, which now
contains `css-mcp` (3050), `penpot-api-mcp` (3051), and `spline-mcp` (3052) from
Task 2.

- [ ] **Step 3: Allocate the three ports and narrow the reserved range**

In `config/portmap.yaml`, add to `allocations:`:

```yaml
  3054: archive-org-mcp   # Internet Archive Wayback and catalog
  3055: medium-mcp        # Medium content via the unofficial medium2 API
  3056: scapy-mcp         # Scapy packet crafting, dissection, capture
```

And change the `reserved:` block from:

```yaml
reserved:
  8684-8699: future expansion (core)
  3050-3059: future expansion (integrations)
```

to:

```yaml
reserved:
  8686-8699: future expansion (core)
  3057-3059: future expansion (integrations)
```

The core range also narrows: 8684 and 8685 are now allocated to crackerjack (Task 2),
so a reserved range starting at 8684 overlaps them.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/les/Projects/bodai
.venv/bin/pytest tests/test_portmap_sync.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/bodai
git add config/portmap.yaml tests/test_portmap_sync.py
git commit -m "feat(ports): allocate 3054-3056 for the three new MCP servers

Narrows the reserved integration range to 3057-3059 and the core range to
8686-8699, since Task 2's corrections put real allocations inside both
previously-reserved bands.

Guard asserts a port is never both allocated and reserved."
```

### Task 4: Rename `druva` to `dhara` in `config/ecosystem.yaml`

**Files:**

- Modify: `config/ecosystem.yaml`
- Modify: `tests/test_portmap_sync.py`

**Interfaces:**

- Consumes: nothing.
- Produces: a `dhara` component key. Nothing downstream in this plan depends on it.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_portmap_sync.py`:

```python
@pytest.mark.unit
class TestEcosystemComponentPaths:
    """Every declared component must point at a directory that exists."""

    def test_no_dangling_component_repo(self) -> None:
        components = _load(ECOSYSTEM_PATH).get("components", {})
        dangling = {
            name: spec["repo"]
            for name, spec in components.items()
            if "repo" in spec
            and not Path(str(spec["repo"]).replace("~", str(Path.home()))).is_dir()
        }
        assert dangling == {}, f"components with missing repos: {dangling}"

    def test_dhara_replaces_druva(self) -> None:
        components = _load(ECOSYSTEM_PATH).get("components", {})
        assert "druva" not in components, "druva was renamed to dhara"
        assert "dhara" in components
        assert components["dhara"]["port"] == 8683
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/les/Projects/bodai
.venv/bin/pytest tests/test_portmap_sync.py::TestEcosystemComponentPaths -v
```

Expected: `test_no_dangling_component_repo` FAILS naming both `druva`
(`~/Projects/druva`) and `n8n-mcp` (`~/Projects/n8n-mcp`).
`test_dhara_replaces_druva` FAILS — `druva` is present, `dhara` is not.

- [ ] **Step 3: Rename the component**

In `config/ecosystem.yaml`, replace the `druva` block:

```yaml
  druva:
    name: druva
    role: curator
    port: 8683
    repo: ~/Projects/druva
    start_command: ["python", "-m", "druva.mcp.server"]
    status: production
    description: Persistent object storage with ACID properties
```

with:

```yaml
  dhara:
    name: dhara
    role: curator
    port: 8683
    repo: ~/Projects/dhara
    start_command: ["python", "-m", "dhara.mcp.server"]
    status: production
    description: Persistent object storage with ACID properties
```

All four occurrences of the old name change: the key, `name`, `repo`, and the module
path inside `start_command`. Leaving any one behind produces a component that
half-works.

- [ ] **Step 4: Check for other `druva` references in this repo**

```bash
cd /Users/les/Projects/bodai
grep -rn "druva" --include="*.py" --include="*.yaml" --include="*.md" \
  . --exclude-dir=.venv --exclude-dir=.git | grep -v CHANGELOG
```

Expected: only `config/portmap.yaml`'s comment (`8683: druva  # Curator`) remains.
Update it to `8683: dhara  # Curator`. Any Python reference is a separate bug — record
it in the commit message rather than silently fixing unrelated code.

- [ ] **Step 5: Run test to verify `test_dhara_replaces_druva` passes**

```bash
cd /Users/les/Projects/bodai
.venv/bin/pytest tests/test_portmap_sync.py::TestEcosystemComponentPaths -v
```

Expected: `test_dhara_replaces_druva` PASSES.
`test_no_dangling_component_repo` still FAILS on `n8n-mcp` — Task 5 handles it.

- [ ] **Step 6: Commit**

```bash
cd /Users/les/Projects/bodai
git add config/ecosystem.yaml config/portmap.yaml tests/test_portmap_sync.py
git commit -m "fix(ecosystem): rename druva to dhara

The curator component was renamed but bodai/config/ecosystem.yaml still
declared druva at 8683 with repo ~/Projects/druva, which does not exist.
Updates the key, name, repo, start_command module path, and the portmap
comment."
```

### Task 5: Audit and disable `n8n-mcp`

`~/Projects/n8n-mcp` does not exist, but no consumer check was ever performed. A
launchd plist, start script, or health probe may reference it. **Comment out, do not
delete** — spec §7.2 item 5.

**Files:**

- Modify: `config/ecosystem.yaml`
- Modify: `tests/test_portmap_sync.py`

**Interfaces:**

- Consumes: nothing.
- Produces: nothing.

- [ ] **Step 1: Audit for consumers**

```bash
grep -rn "n8n" /Users/les/Projects/bodai --include="*.py" --include="*.yaml" \
  --include="*.sh" --include="*.json" --exclude-dir=.venv --exclude-dir=.git
grep -rln "n8n" /Users/les/Projects/mahavishnu --include="*.py" --include="*.yaml" \
  --include="*.json" --exclude-dir=.venv --exclude-dir=.claude 2>/dev/null
ls ~/Library/LaunchAgents/ 2>/dev/null | grep -i n8n || echo "(no n8n plist)"
grep -rn "n8n" ~/.claude/settings.json ~/Projects/mahavishnu/.mcp.json 2>/dev/null \
  || echo "(no n8n MCP config)"
```

Record every hit. If a live consumer exists, note it in the comment you write in
Step 3 — a commented-out entry that something still expects is a latent failure, and
the next person needs to know.

- [ ] **Step 2: Write the failing test**

Add to `tests/test_portmap_sync.py`:

```python
    def test_n8n_mcp_is_not_an_active_component(self) -> None:
        """~/Projects/n8n-mcp does not exist. The entry is commented out
        pending a consumer audit rather than deleted."""
        components = _load(ECOSYSTEM_PATH).get("components", {})
        assert "n8n-mcp" not in components
```

- [ ] **Step 3: Comment out the entry**

In `config/ecosystem.yaml`, replace the active `n8n-mcp` block with a commented one
carrying the audit result:

```yaml
  # DISABLED 2026-09-06 (Plan 0b Task 5): ~/Projects/n8n-mcp does not exist.
  # Commented rather than deleted pending the consumer audit recorded below.
  # Consumers found: <paste Step 1 result, or "none">
  # Delete this block once the audit above stays empty across one release.
  # n8n-mcp:
  #   name: n8n-mcp
  #   role: tool
  #   port: 3044
  #   repo: ~/Projects/n8n-mcp
  #   start_command: ["python", "-m", "n8n_mcp.mcp.server"]
  #   status: development
  #   description: n8n workflow automation via MCP
```

Port 3044 is now unclaimed. In `config/portmap.yaml`, add
`3044: available  # (n8n-mcp disabled 2026-09-06)` so the gap is documented rather
than merely absent — Task 2's guard requires every declared port to be registered, and
an undocumented gap invites silent reuse.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/les/Projects/bodai
.venv/bin/pytest tests/test_portmap_sync.py -v
```

Expected: all PASS, including `test_no_dangling_component_repo` — both dangling
entries are now resolved.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/bodai
git add config/ecosystem.yaml config/portmap.yaml tests/test_portmap_sync.py
git commit -m "fix(ecosystem): disable n8n-mcp, repo does not exist

Commented out rather than deleted pending a consumer audit (recorded in
the comment). Port 3044 marked available so the gap is documented.

Both dangling component entries are now resolved and the path guard passes."
```

### Task 6: Add the three new components to `config/ecosystem.yaml`

**Files:**

- Modify: `config/ecosystem.yaml`
- Modify: `tests/test_portmap_sync.py`

**Interfaces:**

- Consumes: the port allocations from Task 3.
- Produces: three `components:` entries. Their `port` values must match `portmap.yaml`
  exactly — Task 7's guard asserts it.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_portmap_sync.py`:

```python
    @pytest.mark.parametrize(("port", "name"), sorted(NEW_SERVER_PORTS.items()))
    def test_new_server_component_declared(self, port: int, name: str) -> None:
        components = _load(ECOSYSTEM_PATH).get("components", {})
        assert name in components
        assert components[name]["port"] == port
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/les/Projects/bodai
.venv/bin/pytest tests/test_portmap_sync.py -k new_server_component -v
```

Expected: three FAILURES — the components are absent.

- [ ] **Step 3: Add the three components**

In `config/ecosystem.yaml`, append to the `# Additional MCP Integration Servers`
section, matching the existing entries' shape:

```yaml
  archive-org-mcp:
    name: archive-org-mcp
    role: tool
    port: 3054
    repo: ~/Projects/archive-org-mcp
    start_command: ["python", "-m", "archive_org_mcp.server"]
    status: development
    description: Internet Archive Wayback and catalog access via MCP

  medium-mcp:
    name: medium-mcp
    role: tool
    port: 3055
    repo: ~/Projects/medium-mcp
    start_command: ["python", "-m", "medium_mcp.server"]
    status: development
    description: Medium content access via the unofficial medium2 API

  scapy-mcp:
    name: scapy-mcp
    role: tool
    port: 3056
    repo: ~/Projects/scapy-mcp
    start_command: ["python", "-m", "scapy_mcp.server"]
    status: development
    description: Scapy packet crafting, dissection, capture, and PCAP I/O via MCP
```

Note `status: development`, not `production` — none is implemented yet, and the three
server plans flip this when they ship. Note also the `start_command` module path is
`<package>.server`, not `<package>.mcp.server`: these repos use a flat
`<package>/server.py`, unlike the core components' `<package>/mcp/server.py`. Verify
against each repo's actual layout before committing — `python -m` on a wrong path fails
only at launch.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/les/Projects/bodai
.venv/bin/pytest tests/test_portmap_sync.py -v
```

Expected: all PASS. `test_no_dangling_component_repo` still passes — all three
directories exist even though they are not yet git repos.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/bodai
git add config/ecosystem.yaml tests/test_portmap_sync.py
git commit -m "feat(ecosystem): register archive-org-mcp, medium-mcp, scapy-mcp

status: development until the server plans ship. start_command uses
<package>.server, matching these repos' flat layout rather than the core
components' <package>.mcp.server."
```

______________________________________________________________________

## Phase 3: Cross-source guard and the unregistered four

### Task 7: Assert ports agree across all three sources

Spec §7.3 assertion 3. Tasks 2 and 3 compared `portmap.yaml` against repo settings;
this closes the third source, `bodai/config/ecosystem.yaml`.

**Files:**

- Modify: `tests/test_portmap_sync.py`

**Interfaces:**

- Consumes: all prior tasks' config state.
- Produces: the completed three-source guard.

- [ ] **Step 1: Write the test**

Add to `tests/test_portmap_sync.py`:

```python
def _ecosystem_ports() -> dict[int, str]:
    components = _load(ECOSYSTEM_PATH).get("components", {})
    return {
        int(spec["port"]): name
        for name, spec in components.items()
        if "port" in spec
    }


@pytest.mark.unit
class TestThreeSourceAgreement:
    """portmap.yaml, bodai ecosystem.yaml, and repo settings must agree."""

    def test_ecosystem_ports_match_portmap(self) -> None:
        allocations = _portmap_allocations()
        mismatches = {
            port: {"ecosystem": name, "portmap": allocations.get(port, "<unallocated>")}
            for port, name in _ecosystem_ports().items()
            if allocations.get(port) != name
        }
        assert mismatches == {}, f"ecosystem.yaml disagrees with portmap: {mismatches}"

    def test_no_port_claimed_by_two_components(self) -> None:
        components = _load(ECOSYSTEM_PATH).get("components", {})
        seen: dict[int, list[str]] = {}
        for name, spec in components.items():
            if "port" in spec:
                seen.setdefault(int(spec["port"]), []).append(name)
        collisions = {p: sorted(n) for p, n in seen.items() if len(n) > 1}
        assert collisions == {}, f"two components share a port: {collisions}"

    def test_repo_settings_match_ecosystem_where_both_declare(self) -> None:
        """The third source. A repo binding a port its component entry
        disagrees with will fail at launch, not at config load."""
        ecosystem = _ecosystem_ports()
        declared = _repo_declared_ports()
        conflicts = {
            port: {"ecosystem": name, "declared_by": sorted(repos)}
            for port, repos in declared.items()
            if port in ecosystem and ecosystem[port] not in repos
        }
        assert conflicts == {}, f"repo settings conflict with ecosystem: {conflicts}"
```

- [ ] **Step 2: Run the whole suite**

```bash
cd /Users/les/Projects/bodai
.venv/bin/pytest tests/test_portmap_sync.py -v
```

Expected: all PASS. If `test_ecosystem_ports_match_portmap` fails, `ecosystem.yaml`
carries a port `portmap.yaml` disagrees with — resolve in favour of the repo's own
settings, then update both registries.

- [ ] **Step 3: Prove the guard catches drift**

```bash
cd /Users/les/Projects/bodai
cp config/portmap.yaml /tmp/portmap.yaml.bak
python3 - <<'PY'
import re
from pathlib import Path
p = Path("config/portmap.yaml")
p.write_text(re.sub(r"^  3054: archive-org-mcp", "  3054: bogus-mcp",
                    p.read_text(), flags=re.MULTILINE))
PY
.venv/bin/pytest tests/test_portmap_sync.py -v || echo "GUARD FIRED (expected)"
cp /tmp/portmap.yaml.bak config/portmap.yaml
rm /tmp/portmap.yaml.bak
.venv/bin/pytest tests/test_portmap_sync.py -v
```

Expected: the middle run FAILS on `test_new_server_port_allocated` and
`test_ecosystem_ports_match_portmap`; the final run PASSES.

- [ ] **Step 4: Commit**

```bash
cd /Users/les/Projects/bodai
git add tests/test_portmap_sync.py
git commit -m "test(ports): assert agreement across portmap, ecosystem, and repo settings

Completes the three-source guard. The third source — each repo's own
settings/*.yaml — is what the spec's original audit missed, and is how the
3051/3052 collision escaped review.

Verified by injecting a bogus allocation and observing the failure."
```

### Task 8: Decide the four never-registered repos

`flowscape`, `bodai-plugins`, `peanutbutterpub`, `mdinject-pypi-placeholder` appear in no
manifest. Each gets a register-or-exclude decision with a recorded reason.

**Files:**

- Create: `docs/2026-09-06-unregistered-repos.md`
- Modify: `config/ecosystem.yaml` (only for any decided "register")

**Interfaces:**

- Consumes: nothing.
- Produces: a decision document. Registration edits, if any, must satisfy Task 7's guard.

- [ ] **Step 1: Gather facts on each**

```bash
cd /Users/les/Projects
for d in flowscape bodai-plugins peanutbutterpub mdinject-pypi-placeholder; do
  echo "=== $d ==="
  ls -a "$d" 2>/dev/null | head -12
  [ -f "$d/pyproject.toml" ] && grep -m1 -E '^name|^description' "$d/pyproject.toml"
  [ -d "$d/.git" ] && echo "git: yes" || echo "git: no"
  [ -f "$d/README.md" ] && head -3 "$d/README.md"
done
```

- [ ] **Step 2: Write the decision document**

Create `docs/2026-09-06-unregistered-repos.md`:

```markdown
# Unregistered Repositories — Register or Exclude

Opened by Plan 0b Task 8. Four directories under `~/Projects` appear in no
manifest: neither `mahavishnu/settings/ecosystem.yaml`,
`bodai/config/ecosystem.yaml`, nor `bodai/config/portmap.yaml`.

| Repo | Facts | Decision | Reason |
|---|---|---|---|
| `flowscape` | <Step 1 output> | <register / exclude> | <reason> |
| `bodai-plugins` | <Step 1 output> | <register / exclude> | <reason> |
| `peanutbutterpub` | <Step 1 output> | <register / exclude> | <reason> |
| `mdinject-pypi-placeholder` | <Step 1 output> | <register / exclude> | <reason> |

## Guidance applied

- **Register** if the repo is an active component the ecosystem should route to
  or sweep.
- **Exclude** if it is a name-reservation placeholder, a plugin bundle consumed
  by path rather than routed to, or an unrelated project. Placeholders in
  particular should stay unregistered — registering one implies a component
  that does not exist, which is the `n8n-mcp` failure mode in reverse.

Note: `flowscape` has a design spec and implementation plan in Mahavishnu
(`docs/superpowers/specs/2026-08-31-flowscape-design.md`) but is pre-implementation.
Registering a component with no server yet would make it appear routable.
```

- [ ] **Step 3: Apply any "register" decisions**

For each repo decided "register", add a `components:` entry to
`config/ecosystem.yaml` following Task 6's shape. Omit `port` entirely for anything
that is not an MCP server — Task 7's guard only checks entries that declare one, and
inventing a port for a non-server creates a phantom allocation.

- [ ] **Step 4: Run the suite**

```bash
cd /Users/les/Projects/bodai
.venv/bin/pytest tests/test_portmap_sync.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/bodai
git add docs/2026-09-06-unregistered-repos.md config/ecosystem.yaml
git commit -m "docs(ecosystem): register-or-exclude decision for four unregistered repos

flowscape, bodai-plugins, peanutbutterpub, mdinject-pypi-placeholder each
get a recorded decision. Placeholders stay unregistered — registering one
implies a component that does not exist."
```

### Task 9: Run the full gate

- [ ] **Step 1: Run bodai's quality gate**

```bash
cd /Users/les/Projects/bodai
.venv/bin/python -m crackerjack run
```

Expected: PASS. Note: the CLI requires the `run` subcommand — bare
`crackerjack -p minor` fails.

If `mdformat` flags either new doc, **do not run `mdformat` on it** —
`mdformat-frontmatter` is not installed in these venvs and it rewrites `---`
frontmatter delimiters into horizontal rules, corrupting the schema every tool reads.
The two docs created here use no YAML frontmatter, so they are safe to format; the
warning applies if you add frontmatter later.

- [ ] **Step 2: Verify bodai's own config loader still works**

```bash
cd /Users/les/Projects/bodai
.venv/bin/python -c "
from bodai.core.config import load_ecosystem, load_portmap
eco = load_ecosystem()
pm = load_portmap()
print('components:', len(eco.components))
print('portmap range:', pm.mcp_range)
"
```

Expected: prints a component count including the three new servers, and a portmap
range. This exercises `bodai/core/config.py:15` and `:23` — the two loaders that read
the files this plan rewrote. A schema mistake surfaces here rather than at a later
`bodai status` invocation.

- [ ] **Step 3: Verify the CLI status path**

```bash
cd /Users/les/Projects/bodai
.venv/bin/bodai status 2>&1 | head -20 || .venv/bin/python -m bodai status 2>&1 | head -20
```

Expected: the `ecosystem.yaml: N components` and `portmap.yaml: range ...` lines from
`bodai/cli.py:291-300` render without error.

- [ ] **Step 4: Commit any gate fixes**

```bash
cd /Users/les/Projects/bodai
git add -u
git commit -m "chore(ports): quality gate fixes from Plan 0b"
```

Skip if the gate was clean and there is nothing to commit.

#### Integration Contract — Phases 2 and 3

- **Triggered from:** `bodai/core/config.py:load_ecosystem()` (`:15`) and
  `load_portmap()` (`:23`), reached by `bodai status` (`bodai/cli.py:291-300`) and by
  any component-startup path reading `start_command`. The guard is triggered by
  `pytest tests/test_portmap_sync.py` under `crackerjack run`.
- **Returns to / updates:** `bodai/config/portmap.yaml` (corrected allocations, 3054-3056
  added, reserved ranges narrowed), `bodai/config/ecosystem.yaml` (`dhara` replaces
  `druva`, `n8n-mcp` disabled, three components added), plus two decision documents under
  `bodai/docs/`.
- **Demonstrable by:** `pytest tests/test_portmap_sync.py -v` passes;
  `bodai status` prints a component count including the three new servers; Task 7 Step 3
  shows the guard firing on an injected bogus allocation.
- **Rollback signal:** `bodai status` errors on config load, or `load_ecosystem()` raises
  a validation error. Revert `config/portmap.yaml` and `config/ecosystem.yaml` together —
  Task 7's guard couples them.
- **Observability added:** `bodai status` already surfaces both file states
  (`cli.py:291`, `:298`). The guard test's failure messages name the specific
  contradicting port and the repos on each side, rather than reporting a count mismatch.

______________________________________________________________________

## Validation Matrix

| Command | Expected outcome | Evidence |
|---|---|---|
| `pytest tests/test_portmap_sync.py -v` | all pass | Tasks 2-8 |
| `bodai status` | prints component count incl. 3 new servers | Task 9 Step 3 |
| `python -c "from bodai.core.config import load_ecosystem, load_portmap; ..."` | both load | Task 9 Step 2 |
| Guard fires on bogus allocation | fails, then passes after restore | Task 7 Step 3 |
| `python -m crackerjack run` (in bodai) | pass | Task 9 Step 1 |
| `docs/2026-09-06-port-audit.md` exists with 4 raw scans | present | Task 1 |
| `docs/2026-09-06-unregistered-repos.md` has 4 decisions | present | Task 8 |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Widened audit finds a claimant on 3054-3056 | low | Task 1 Step 6 halts and re-picks; the three server plans must be updated in the same commit |
| Removing `fastblocks` from 8684 leaves it unregistered | medium | Task 2 Step 3 forbids silently dropping a component; find its real port or comment the absence |
| Commented-out `n8n-mcp` still has a live consumer | medium | Task 5 Step 1 audits before disabling and records hits in the comment |
| `start_command` module path wrong for the new servers | medium | Task 6 Step 3 requires verifying `<package>.server` against each repo's actual layout |
| `bodai` config loader rejects the new schema | medium | Task 9 Step 2 exercises both loaders directly before the CLI |
| `mdformat` corrupts a doc's frontmatter | low (these docs have none) | Task 9 Step 1 warns; applies only if frontmatter is added later |

## Decision Rule

Plan 0b is done when the guard suite passes, `bodai status` renders, and both loaders
import cleanly.

Under scope pressure, Task 8 (unregistered four) is cuttable — it produces decisions, not
behaviour. **Task 1 must never be cut**: allocating ports without the widened audit is how
the 3051/3052 collision happened. Task 7 must never be cut — it is the assertion whose
absence let `portmap.yaml` drift six entries out of true.

Plan 0b's guard test will fail loudly if a server plan registers before 0b confirms
the port is free, but the server plans' Phase 0b gates (live upstream proof, RapidAPI
key, committed pcap fixtures) are independent of 0b's ports. The execution order —
0a → 0b → server plans — is the natural sequence, but a server plan's Phase 0b can
run without 0b landing first.

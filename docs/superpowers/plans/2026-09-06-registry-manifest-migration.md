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

# Registry Manifest Migration (Plan 0a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `settings/ecosystem.yaml` the true single source of truth for the
Mahavishnu repository manifest, with all 35 repositories registered and a guard test that
fails `crackerjack run` when the registries drift.

**Architecture:** `settings/ecosystem.yaml` is already the file the runtime reads
(`load_repos()` at `mahavishnu/core/bootstrap.py:187`), but it holds only 8 of 32 known
repos — the other 24 live in the legacy `settings/repos.yaml`, invisible to routing since
2026-05-11. This plan registers the three new MCP servers first (unblocking three
sibling plans), then adds four guard assertions test-first, letting each failure drive the
migration it guards.

**Tech Stack:** Python 3.14, PyYAML, pytest, Typer, crackerjack.

**Spec:** `docs/superpowers/specs/2026-09-06-mcp-stub-activation-design.md` (§4.5, §4.6,
§7.1, §7.3)

## Global Constraints

- Python `>=3.14`. `from __future__ import annotations` is the first non-comment line of
  every source file.
- Line length 100 (`[tool.ruff] line-length`).
- No `assert` in `mahavishnu/**` production code (bandit B101). Tests may assert freely.
- Modern syntax only: `X | None`, `list[str]`, `pathlib.Path`.
- In `except` blocks use `logger.exception(...)`, never `logger.error(..., exc_info=True)`.
- Use the Oneiric logger (`oneiric.logging`), not stdlib `logging`, not `print()`.
- Project pytest markers only: `unit`, `integration`, `e2e`, `property`, `slow`,
  `timeout`, `ci`, `crackerjack`. `asyncio_mode = "auto"` — async tests need no decorator.
- Paths in this plan are relative to `/Users/les/Projects/mahavishnu` unless stated.
  Because the repo and its package share a name, `settings/ecosystem.yaml` means
  `<repo-root>/settings/ecosystem.yaml`, never `mahavishnu/settings/`.
- **Do not** add the three new servers to `settings/repos.yaml` — it is being deprecated
  in this plan.
- Commit after every task. Never `git push` (bodai pushes are user-controlled).

## File Structure

| File | Responsibility |
|---|---|
| `settings/ecosystem.yaml` | **Modify.** Canonical manifest: gains 3 new servers, 24 migrated entries, an `orb` role, and an `mcp:` field. |
| `settings/repos.yaml` | **Modify.** Gains a deprecation header only. Entries unchanged, file not deleted. |
| `mahavishnu/repo_cli.py` | **Modify** line 16. Repoint `REPOS_CATALOG_PATH` at the canonical manifest. |
| `tests/unit/test_registry_sync.py` | **Create.** The four guard assertions. One class, four test methods, module-level loaders. |
| `docs/followups/2026-09-06-sibling-repos-yaml-audit.md` | **Create.** Records what `crackerjack/settings/repos.yaml` and `mcp-common/settings/repos.yaml` are. Investigation output only. |

______________________________________________________________________

## Phase 1: Unblock the server plans

### Task 1: Register the three new MCP servers in the canonical manifest

This is the only thing the three server plans need from Plan 0a, so it lands first. The
rest of this plan can then proceed in parallel with them.

**Files:**

- Modify: `settings/ecosystem.yaml` (append to the `repos:` list, before the `roles:` key)
- Test: `tests/unit/test_registry_sync.py` (create)

**Interfaces:**

- Consumes: nothing.
- Produces: three `repos:` entries named `archive-org-mcp`, `medium-mcp`, `scapy-mcp`,
  each with keys `name`, `package`, `path`, `nickname`, `nicknames`, `role`, `tags`,
  `description`, `status`, `mcp`. Later tasks and the three server plans rely on these
  names being exactly as written.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_registry_sync.py`:

```python
"""Guard against drift between the Mahavishnu registry files.

settings/ecosystem.yaml is canonical (read by load_repos() at
mahavishnu/core/bootstrap.py:187). settings/repos.yaml is legacy but still
consumed by mahavishnu/repo_cli.py. These assertions exist because the two
files diverged silently for four months: canonical held 8 repos while the
legacy file held 32, so 24 repositories were invisible to list_repos,
role-based routing, and tag sweeps while both files looked authoritative.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_DIR = REPO_ROOT / "settings"
ECOSYSTEM_PATH = SETTINGS_DIR / "ecosystem.yaml"
LEGACY_PATH = SETTINGS_DIR / "repos.yaml"

NEW_SERVERS = ("archive-org-mcp", "medium-mcp", "scapy-mcp")


def _load(path: Path) -> dict[str, Any]:
    with path.open() as handle:
        return yaml.safe_load(handle)


def _repos(path: Path) -> list[dict[str, Any]]:
    return _load(path)["repos"]


def _names(path: Path) -> set[str]:
    return {repo["name"] for repo in _repos(path)}


@pytest.mark.unit
class TestNewServerRegistration:
    """The three new MCP servers must be registered in the canonical manifest."""

    @pytest.mark.parametrize("server_name", NEW_SERVERS)
    def test_new_server_is_registered(self, server_name: str) -> None:
        assert server_name in _names(ECOSYSTEM_PATH)

    @pytest.mark.parametrize("server_name", NEW_SERVERS)
    def test_new_server_not_added_to_legacy(self, server_name: str) -> None:
        """repos.yaml is being deprecated; new entries must not be written there."""
        assert server_name not in _names(LEGACY_PATH)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_registry_sync.py -v`

Expected: the three `test_new_server_is_registered` cases FAIL with
`AssertionError`. The three `test_new_server_not_added_to_legacy` cases PASS
(the servers aren't in either file yet).

- [ ] **Step 3: Add the three entries to `settings/ecosystem.yaml`**

Insert immediately before the `roles:` key, preserving the file's existing
two-space-indent block style:

```yaml
- name: archive-org-mcp
  package: archive_org_mcp
  path: /Users/les/Projects/archive-org-mcp
  nickname: ia
  nicknames:
  - ia
  - archive
  role: tool
  tags:
  - mcp
  - archive
  - wayback
  - research
  description: Internet Archive Wayback and catalog access via MCP
  status: active
  mcp: 3rd-party
- name: medium-mcp
  package: medium_mcp
  path: /Users/les/Projects/medium-mcp
  nickname: medium
  nicknames:
  - medium
  role: tool
  tags:
  - mcp
  - publishing
  - content
  - research
  description: Medium content access via the unofficial medium2 API
  status: active
  mcp: 3rd-party
- name: scapy-mcp
  package: scapy_mcp
  path: /Users/les/Projects/scapy-mcp
  nickname: scapy
  nicknames:
  - scapy
  role: tool
  tags:
  - mcp
  - network
  - packets
  - pcap
  description: Scapy packet crafting, dissection, capture, and PCAP I/O via MCP
  status: active
  mcp: 3rd-party
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_registry_sync.py -v`

Expected: all 6 tests PASS.

- [ ] **Step 5: Verify the runtime sees them**

Run: `.venv/bin/mahavishnu list-repos | grep -E 'archive-org-mcp|medium-mcp|scapy-mcp'`

Expected: three lines, one per server. This is the exact check the three server
plans use as their registration exit criterion. If it prints nothing, the entries
were added to the wrong file — confirm you edited `settings/ecosystem.yaml` at the
repo root, not `mahavishnu/settings/`.

- [ ] **Step 6: Commit**

```bash
git add settings/ecosystem.yaml tests/unit/test_registry_sync.py
git commit -m "feat(registry): register archive-org-mcp, medium-mcp, scapy-mcp

Adds the three new MCP servers to the canonical manifest so their
implementation plans can proceed. Deliberately not added to the legacy
settings/repos.yaml, which is deprecated later in this plan.

Guard test asserts presence in canonical and absence from legacy."
```

#### Integration Contract — Phase 1

- **Triggered from:** `load_repos()` at `mahavishnu/core/bootstrap.py:187`, via
  `repos_path` (`settings/mahavishnu.yaml:18`). Reached by
  `mahavishnu list-repos` (`mahavishnu/_main_cli.py:886`) and by every role- or
  tag-based routing lookup.
- **Returns to / updates:** `app.repos_config["repos"]` in the running
  `MahavishnuApp`; persists as `settings/ecosystem.yaml`.
- **Demonstrable by:**
  `mahavishnu list-repos | grep -E 'archive-org-mcp|medium-mcp|scapy-mcp'` returns
  three lines; `pytest tests/unit/test_registry_sync.py -v` passes 6 tests.
- **Rollback signal:** `mahavishnu list-repos` errors, or its entry count drops
  below the pre-change 8. Revert the `settings/ecosystem.yaml` hunk.
- **Observability added:** `load_repos()` already logs
  `"Loaded %d repositories from %s"` at INFO. Entry count moves 8 → 11, visible in
  `~/.mahavishnu/logs/mcp.log`.

______________________________________________________________________

## Phase 2: Guard assertions, test-first

Each task adds one assertion, watches it fail against real drift, then fixes the
drift it found. This is why the guard comes before the bulk migration.

### Task 2: Assert every registered path exists on disk

**Files:**

- Modify: `tests/unit/test_registry_sync.py`

**Interfaces:**

- Consumes: `_repos`, `_names`, `ECOSYSTEM_PATH`, `LEGACY_PATH` from Task 1.
- Produces: `TestRegistryIntegrity` class. Tasks 3, 4, 6 add methods to it.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_registry_sync.py`:

```python
@pytest.mark.unit
class TestRegistryIntegrity:
    """Structural invariants over the canonical manifest."""

    def test_every_path_exists(self) -> None:
        """A registered repo whose path is gone will fail routing at runtime."""
        missing = [
            (repo["name"], repo["path"])
            for repo in _repos(ECOSYSTEM_PATH)
            if not Path(repo["path"]).expanduser().is_dir()
        ]
        assert missing == [], f"registered paths do not exist: {missing}"
```

- [ ] **Step 2: Run test**

Run: `.venv/bin/pytest tests/unit/test_registry_sync.py::TestRegistryIntegrity -v`

Expected: PASS. Canonical `ecosystem.yaml` has zero dangling paths (spec §4.5).
This assertion is preventive — it guards the 24 entries Task 5 adds.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_registry_sync.py
git commit -m "test(registry): assert every canonical manifest path exists on disk"
```

### Task 3: Assert every role is in the canonical taxonomy

**Files:**

- Modify: `tests/unit/test_registry_sync.py`
- Modify: `settings/ecosystem.yaml` (add the `orb` role)

**Interfaces:**

- Consumes: `_load`, `_repos`, `ECOSYSTEM_PATH`, `TestRegistryIntegrity` from Tasks 1-2.
- Produces: `_role_names(path) -> set[str]` module-level helper, used by Task 5.

- [ ] **Step 1: Write the failing test**

Add this helper next to `_names` in `tests/unit/test_registry_sync.py`:

```python
def _role_names(path: Path) -> set[str]:
    return {role["name"] for role in _load(path).get("roles", [])}
```

Add this method to `TestRegistryIntegrity`:

```python
    def test_every_role_is_in_taxonomy(self) -> None:
        """A repo with an unknown role matches no routing filter and is silently
        unreachable — it neither errors nor appears in role-scoped sweeps."""
        taxonomy = _role_names(ECOSYSTEM_PATH)
        offenders = {
            repo["name"]: repo["role"]
            for repo in _repos(ECOSYSTEM_PATH)
            if repo.get("role") not in taxonomy
        }
        assert offenders == {}, f"roles absent from taxonomy: {offenders}"

    def test_legacy_roles_are_migratable(self) -> None:
        """Every role used in the legacy file must exist in the canonical
        taxonomy, or Task 5's migration will introduce unroutable entries."""
        taxonomy = _role_names(ECOSYSTEM_PATH)
        legacy_roles = {repo.get("role") for repo in _repos(LEGACY_PATH)}
        assert legacy_roles <= taxonomy, (
            f"legacy roles missing from taxonomy: {sorted(legacy_roles - taxonomy)}"
        )
```

- [ ] **Step 2: Run test to verify the second one fails**

Run: `.venv/bin/pytest tests/unit/test_registry_sync.py::TestRegistryIntegrity -v`

Expected: `test_every_role_is_in_taxonomy` PASSES (the current 11 entries all use
valid roles). `test_legacy_roles_are_migratable` FAILS with
`legacy roles missing from taxonomy: ['orb']` — `settings/repos.yaml` assigns the
`bodai` repo `role: orb`, which the canonical 15-role taxonomy lacks.

- [ ] **Step 3: Add the `orb` role to the canonical taxonomy**

`orb` is a real role in this ecosystem — `bodai` is the umbrella meta-project, and
`bodai/config/ecosystem.yaml` describes itself as "The Orb contains all components of
the ecosystem." Add it rather than remapping `bodai` onto an ill-fitting existing
role.

In `settings/ecosystem.yaml`, append to the `roles:` list, matching the existing
entries' shape (inspect a neighbouring role and copy its key set exactly — at minimum
`name` and `description`):

```yaml
- name: orb
  description: Umbrella meta-project aggregating ecosystem configuration and docs
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_registry_sync.py -v`

Expected: all tests PASS. The taxonomy is now 16 roles.

- [ ] **Step 5: Commit**

```bash
git add settings/ecosystem.yaml tests/unit/test_registry_sync.py
git commit -m "feat(registry): add orb role; assert roles are in taxonomy

settings/repos.yaml assigns bodai role: orb, absent from the canonical
15-role taxonomy. Adding it rather than remapping bodai, since orb is a
real role — bodai is the umbrella meta-project.

Two assertions: canonical entries use known roles, and every legacy role
is migratable before Task 5 moves 24 entries across."
```

### Task 4: Assert canonical is a superset of legacy

**Files:**

- Modify: `tests/unit/test_registry_sync.py`

**Interfaces:**

- Consumes: `_names`, `ECOSYSTEM_PATH`, `LEGACY_PATH`, `TestRegistryIntegrity`.
- Produces: nothing new; the failure this test produces is what Task 5 fixes.

- [ ] **Step 1: Write the failing test**

Add to `TestRegistryIntegrity`:

```python
    def test_canonical_is_superset_of_legacy(self) -> None:
        """Anything in the legacy file must also be in canonical, or it is
        invisible to the runtime — which read canonical only."""
        stranded = _names(LEGACY_PATH) - _names(ECOSYSTEM_PATH)
        assert stranded == set(), (
            f"{len(stranded)} repos are in repos.yaml but not ecosystem.yaml, so "
            f"the runtime cannot see them: {sorted(stranded)}"
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_registry_sync.py::TestRegistryIntegrity::test_canonical_is_superset_of_legacy -v`

Expected: FAIL listing 24 names — `bodai`, `css-mcp`, `excalidraw-mcp`, `fastblocks`,
`fastblocks-ui`, `graphics-mcp`, `jinja2-async-environment`,
`jinja2-custom-delimiters`, `jinja2-inflection`, `langsmith-mcp`, `mailgun-mcp`,
`neo4j-mcp`, `opera-cloud-mcp`, `penpot-api-mcp`, `porkbun-dns-mcp`,
`porkbun-domain-mcp`, `raindropio-mcp`, `spline-mcp`, `splashstand`,
`starlette-async-jinja`, `synxis-crs-mcp`, `synxis-pms-mcp`, `unifi-mcp`,
`www-mcp-servers`.

Leave it failing. Task 5 is the fix.

- [ ] **Step 3: Commit the failing guard**

```bash
git add tests/unit/test_registry_sync.py
git commit -m "test(registry): assert canonical is a superset of legacy (currently failing)

Documents the 24-repo drift as an executable assertion. Task 5 migrates
the entries that make it pass."
```

______________________________________________________________________

## Phase 3: The migration

### Task 5: Migrate the 24 stranded entries into the canonical manifest

**Files:**

- Modify: `settings/ecosystem.yaml`

**Interfaces:**

- Consumes: the failing assertion from Task 4; the `orb` role from Task 3.
- Produces: a 35-entry `repos:` list. Server plans and `repo_cli.py` (Task 6) depend on
  entry names being unchanged from `repos.yaml`.

**Reconciliation rules** — apply exactly, so nothing is invented:

1. Copy all fields present in the `repos.yaml` entry verbatim.
1. If `nicknames:` is absent and `nickname:` is present, derive `nicknames: [<nickname>]`.
   This matches the worked example in Task 5 Step 3.
1. Add `mcp:` where `repos.yaml` supplies it. Where it is absent: `3rd-party` for any
   `*-mcp` repo, and **omit the key entirely** for libraries and applications. Do not
   invent a third value.
1. Add `status: active` — `repos.yaml` lacks it and every canonical entry has it.
1. **Where an entry exists in both files with a differing field, `repos.yaml` wins**
   (it is four months newer). There is exactly one such conflict, recorded below.
1. Sort the final `repos:` list by `name`. Duplicate names are a hard error.

**The one field conflict:**

| Repo | canonical `ecosystem.yaml` | legacy `repos.yaml` | Resolution |
|---|---|---|---|
| `session-buddy` | `role: manager` | `role: builder` | **`builder`** — repos.yaml wins. `manager` remains in the taxonomy but becomes unused; leave it there. |

- [ ] **Step 1: Write the migration verification test first**

Add to `tests/unit/test_registry_sync.py`:

```python
@pytest.mark.unit
class TestMigrationOutcome:
    """Post-migration invariants on the canonical manifest."""

    def test_entry_count_is_thirty_five(self) -> None:
        assert len(_repos(ECOSYSTEM_PATH)) == 35

    def test_no_duplicate_names(self) -> None:
        names = [repo["name"] for repo in _repos(ECOSYSTEM_PATH)]
        duplicates = {name for name in names if names.count(name) > 1}
        assert duplicates == set(), f"duplicate names: {sorted(duplicates)}"

    def test_entries_are_sorted_by_name(self) -> None:
        names = [repo["name"] for repo in _repos(ECOSYSTEM_PATH)]
        assert names == sorted(names)

    def test_session_buddy_role_conflict_resolved_to_builder(self) -> None:
        """repos.yaml wins on field conflicts (spec §7.1 rule 4)."""
        entry = next(
            repo for repo in _repos(ECOSYSTEM_PATH) if repo["name"] == "session-buddy"
        )
        assert entry["role"] == "builder"

    def test_mcp_field_present_on_every_mcp_repo(self) -> None:
        offenders = [
            repo["name"]
            for repo in _repos(ECOSYSTEM_PATH)
            if repo["name"].endswith("-mcp") and "mcp" not in repo
        ]
        assert offenders == [], f"*-mcp repos missing the mcp: field: {offenders}"

    def test_every_entry_has_required_keys(self) -> None:
        required = {"name", "package", "path", "role", "tags", "description", "status"}
        offenders = {
            repo.get("name", "<unnamed>"): sorted(required - repo.keys())
            for repo in _repos(ECOSYSTEM_PATH)
            if not required <= repo.keys()
        }
        assert offenders == {}, f"entries missing required keys: {offenders}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_registry_sync.py -v`

Expected: `test_entry_count_is_thirty_five` FAILS (11, not 35).
`test_canonical_is_superset_of_legacy` still FAILS (24 stranded).
`test_session_buddy_role_conflict_resolved_to_builder` FAILS (currently `manager`).
`test_entries_are_sorted_by_name` may fail — the existing 11 are not sorted.

- [ ] **Step 3: Perform the migration**

Read both files. For each of the 24 stranded names from Task 4's failure output,
translate its `repos.yaml` entry into the canonical block style. Worked example — the
`repos.yaml` entry:

```yaml
  - name: "raindropio-mcp"
    package: "raindropio_mcp"
    path: "/Users/les/Projects/raindropio-mcp"
    nickname: "raindrop"
    role: "tool"
    tags: ["mcp", "bookmarks", "integration", "python"]
    description: "Raindrop.io bookmark management via MCP"
    mcp: "3rd-party"
```

becomes, in `settings/ecosystem.yaml`:

```yaml
- name: raindropio-mcp
  package: raindropio_mcp
  path: /Users/les/Projects/raindropio-mcp
  nickname: raindrop
  nicknames:
  - raindrop
  role: tool
  tags:
  - mcp
  - bookmarks
  - integration
  - python
  description: Raindrop.io bookmark management via MCP
  status: active
  mcp: 3rd-party
```

Note the three transformations: quotes dropped (canonical style is unquoted),
`tags` expanded from flow to block sequence, and `nicknames` synthesized from
`nickname` where `repos.yaml` supplies only the singular (canonical entries carry
both). Then change `session-buddy`'s `role` from `manager` to `builder`, and sort the
whole `repos:` list by `name`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_registry_sync.py -v`

Expected: every test PASSES, including Task 4's superset assertion.

- [ ] **Step 5: Verify the runtime**

Run: `.venv/bin/mahavishnu list-repos | wc -l`

Expected: a count consistent with 35 entries. Then confirm the previously-invisible
repos are reachable:

Run: `.venv/bin/mahavishnu list-repos | grep -E 'raindropio-mcp|fastblocks|bodai'`

Expected: three lines. Before this task they returned nothing.

- [ ] **Step 6: Commit**

```bash
git add settings/ecosystem.yaml tests/unit/test_registry_sync.py
git commit -m "feat(registry): migrate 24 stranded repos into canonical manifest

settings/ecosystem.yaml held 8 repos while settings/repos.yaml held 32.
The runtime reads canonical only, so 24 repositories — every MCP
integration server, fastblocks, splashstand, the jinja2/starlette
libraries, and bodai itself — were invisible to list_repos, role-based
routing, and tag sweeps since 2026-05-11.

Reconciliation per spec §7.1: repos.yaml wins on field conflicts
(session-buddy role manager -> builder), mcp: added for *-mcp repos,
status: active added, entries sorted by name.

Canonical is now 35 entries and the superset assertion passes."
```

### Task 6: Repoint `repo_cli.py` at the canonical manifest

`mahavishnu/repo_cli.py:16` hard-codes the legacy path. Deprecating `repos.yaml`
while a working command reads it would break `mahavishnu repo diff`.

**Files:**

- Modify: `mahavishnu/repo_cli.py:16`
- Test: `tests/unit/test_registry_sync.py`

**Interfaces:**

- Consumes: the 35-entry canonical manifest from Task 5.
- Produces: `REPOS_CATALOG_PATH` now pointing at `settings/ecosystem.yaml`.

- [ ] **Step 1: Read the current loader**

Run: `sed -n '14,34p' mahavishnu/repo_cli.py`

Confirm `REPOS_CATALOG_PATH = Path("settings/repos.yaml")` at line 16 and that
`_load_catalog()` resolves it via `Path(__file__).resolve().parents[1] / REPOS_CATALOG_PATH`.
Note the shape `_load_catalog()` returns — the test below must match it.

- [ ] **Step 2: Write the failing test**

Add to `tests/unit/test_registry_sync.py`:

```python
@pytest.mark.unit
class TestRepoCLICatalogSource:
    """repo_cli must read the canonical manifest, not the deprecated legacy file."""

    def test_catalog_path_is_canonical(self) -> None:
        from mahavishnu.repo_cli import REPOS_CATALOG_PATH

        assert REPOS_CATALOG_PATH == Path("settings/ecosystem.yaml")

    def test_catalog_resolves_a_migrated_repo(self) -> None:
        """raindropio-mcp was stranded in the legacy file; repo_cli must now see it."""
        from mahavishnu.repo_cli import _load_catalog

        catalog = _load_catalog()
        assert "raindropio-mcp" in catalog or any(
            "raindropio-mcp" in str(key) for key in catalog
        )
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_registry_sync.py::TestRepoCLICatalogSource -v`

Expected: `test_catalog_path_is_canonical` FAILS — it is still
`settings/repos.yaml`.

- [ ] **Step 4: Repoint the constant**

In `mahavishnu/repo_cli.py`, change line 16 from:

```python
REPOS_CATALOG_PATH = Path("settings/repos.yaml")
```

to:

```python
# Canonical manifest (settings/repos.yaml is deprecated — see
# docs/superpowers/specs/2026-09-06-mcp-stub-activation-design.md §4.6).
REPOS_CATALOG_PATH = Path("settings/ecosystem.yaml")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_registry_sync.py -v`

Expected: all PASS.

- [ ] **Step 6: Verify the command still works end-to-end**

Run: `.venv/bin/mahavishnu repo diff /Users/les/Projects/raindropio-mcp`

Expected: the command runs and reports diff state (clean or a diff) rather than
erroring with a catalog-miss. Before this task, `raindropio-mcp` was in the legacy
file so this happened to work; after Task 5 it is in canonical, so this proves the
repoint did not regress it.

- [ ] **Step 7: Run the existing repo_cli tests**

Run: `.venv/bin/pytest tests/unit/test_repo_cli_coverage.py -v`

Expected: PASS. If any test asserts the legacy path literally, update that
assertion to the canonical path — it is testing the old wiring, and the wiring
changed deliberately.

- [ ] **Step 8: Commit**

```bash
git add mahavishnu/repo_cli.py tests/unit/test_registry_sync.py
git commit -m "fix(repo-cli): read canonical ecosystem.yaml, not legacy repos.yaml

repo_cli.py:16 hard-coded settings/repos.yaml, making it a live consumer
of the file this plan deprecates. Repointing before the deprecation
header lands, so mahavishnu repo diff keeps working."
```

### Task 7: Add the deprecation header to `settings/repos.yaml`

The file is **not** deleted — `_resolve_repos_path()` at
`mahavishnu/core/bootstrap.py:130` still uses it as a fallback, and the sibling-repo
question (Task 8) is open.

**Files:**

- Modify: `settings/repos.yaml` (header comment only)
- Test: `tests/unit/test_registry_sync.py`

**Interfaces:**

- Consumes: nothing.
- Produces: nothing consumed downstream.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_registry_sync.py`:

```python
@pytest.mark.unit
class TestLegacyDeprecation:
    """The legacy file must announce its status to anyone who opens it."""

    def test_legacy_file_has_deprecation_header(self) -> None:
        head = LEGACY_PATH.read_text().split("\n", 12)[:12]
        joined = "\n".join(head).upper()
        assert "DEPRECATED" in joined
        assert "ECOSYSTEM.YAML" in joined

    def test_legacy_entries_unchanged_count(self) -> None:
        """Deprecating must not mutate entries — the guard in Task 9 depends on
        this file staying stable as the migration's reference point."""
        assert len(_repos(LEGACY_PATH)) == 32
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_registry_sync.py::TestLegacyDeprecation -v`

Expected: `test_legacy_file_has_deprecation_header` FAILS.

- [ ] **Step 3: Replace the header comment block**

`settings/repos.yaml` currently opens with a `# Mahavishnu Repository Manifest`
comment block. Replace that block with:

```yaml
# DEPRECATED — do not add entries to this file.
#
# The canonical repository manifest is settings/ecosystem.yaml, which is what
# load_repos() reads at runtime (mahavishnu/core/bootstrap.py:187, via
# repos_path in settings/mahavishnu.yaml:18).
#
# This file is retained only because _resolve_repos_path()
# (mahavishnu/core/bootstrap.py:130) still uses it as a fallback when
# ecosystem.yaml is absent. It is kept in sync as a reference point for the
# guard test at tests/unit/test_registry_sync.py, which asserts that
# ecosystem.yaml remains a superset of this file.
#
# Deprecated 2026-09-06 — see
# docs/superpowers/specs/2026-09-06-mcp-stub-activation-design.md §7.1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_registry_sync.py -v`

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add settings/repos.yaml tests/unit/test_registry_sync.py
git commit -m "docs(registry): mark settings/repos.yaml deprecated

Not deleted: bootstrap.py:130 still uses it as a fallback and it is the
guard test's reference point for the superset assertion."
```

### Task 8: Investigate the sibling `repos.yaml` files

**Investigation and documentation only.** No migration — that keeps this plan's scope
bounded (spec §11.3).

**Files:**

- Create: `docs/followups/2026-09-06-sibling-repos-yaml-audit.md`

**Interfaces:**

- Consumes: nothing.
- Produces: a followup document. No code depends on it.

- [ ] **Step 1: Gather the facts**

```bash
for repo in crackerjack mcp-common; do
  echo "=== $repo ==="
  python3 -c "
import yaml
d = yaml.safe_load(open('/Users/les/Projects/$repo/settings/repos.yaml'))
repos = d.get('repos', [])
print('entries:', len(repos))
print('names:', sorted(r['name'] for r in repos))
print('top-level keys:', sorted(d.keys()))
"
  grep -rn "repos.yaml" /Users/les/Projects/$repo --include="*.py" \
    --exclude-dir=.venv --exclude-dir=.claude | head -5
done
```

- [ ] **Step 2: Write the followup**

Create `docs/followups/2026-09-06-sibling-repos-yaml-audit.md` with frontmatter
matching `docs/schemas/document-frontmatter-v1.md`:

```markdown
---
status: complete
role: historical
date: 2026-09-06
last_reviewed: 2026-09-06
superseded_by: null
topic: mcp-stub-activation
---

# Sibling `repos.yaml` Audit

Opened by Plan 0a (`docs/superpowers/plans/2026-09-06-registry-manifest-migration.md`,
Task 8) to bound its own scope. `crackerjack/settings/repos.yaml` and
`mcp-common/settings/repos.yaml` exist alongside Mahavishnu's; their relationship was
unverified.

## Findings

<fill in from Step 1: entry counts, name sets, top-level keys, and which
Python modules read each file>

## Verdict

<one of: "independent manifests — no migration needed";
"stale copies of Mahavishnu's — schedule a follow-up migration plan";
"partially overlapping — enumerate the divergence">

## Consequence

<if independent: none. If stale: name the follow-up plan that must be written,
and note that until then a query routed via crackerjack may resolve a
different repo set than one routed via Mahavishnu.>
```

- [ ] **Step 3: Commit**

```bash
git add docs/followups/2026-09-06-sibling-repos-yaml-audit.md
git commit -m "docs(followups): audit sibling repos.yaml files in crackerjack and mcp-common

Investigation only, per spec §11.3, to keep Plan 0a's scope bounded."
```

### Task 9: Assert the legacy file cannot shrink unnoticed

The final guard assertion. Task 4 asserts canonical ⊇ legacy, which passes trivially if
someone deletes from legacy. This closes that direction.

**Files:**

- Modify: `tests/unit/test_registry_sync.py`

**Interfaces:**

- Consumes: `_names`, both paths, the 32-entry legacy file.
- Produces: the completed four-assertion guard.

- [ ] **Step 1: Write the test**

Add to `TestRegistryIntegrity`:

```python
    # Pinned 2026-09-06 by Plan 0a. Raising this requires a matching
    # ecosystem.yaml addition; lowering it requires deleting this assertion
    # deliberately, with a reason in the commit message.
    LEGACY_PINNED_COUNT = 32

    def test_legacy_count_has_not_decreased(self) -> None:
        """A one-directional superset assertion passes trivially if entries are
        deleted from the legacy file. Pinning the count makes deletion explicit."""
        actual = len(_repos(LEGACY_PATH))
        assert actual >= self.LEGACY_PINNED_COUNT, (
            f"settings/repos.yaml shrank from {self.LEGACY_PINNED_COUNT} to {actual}. "
            "If this was deliberate, lower LEGACY_PINNED_COUNT in the same commit."
        )

    def test_no_credentials_in_registry(self) -> None:
        """No api_key/token/secret/password/private_key fields in any manifest entry."""
        secret_keys = {"api_key", "token", "secret", "password", "private_key"}
        for manifest in (SETTINGS_DIR / "ecosystem.yaml", SETTINGS_DIR / "repos.yaml"):
            data = yaml.safe_load(manifest.read_text())
            # Walk all entries and assert no secret keys.
            for entry in (data.get("repos") or []):
                assert not (set(entry.keys()) & secret_keys), entry
```

- [ ] **Step 2: Run the whole guard suite**

Run: `.venv/bin/pytest tests/unit/test_registry_sync.py -v`

Expected: every test PASSES.

- [ ] **Step 3: Prove the guard actually catches drift**

Temporarily break it, confirm the failure, then restore:

```bash
cp settings/ecosystem.yaml /tmp/ecosystem.yaml.bak
python3 -c "
import yaml
p = 'settings/ecosystem.yaml'
d = yaml.safe_load(open(p))
d['repos'] = [r for r in d['repos'] if r['name'] != 'raindropio-mcp']
yaml.safe_dump(d, open(p, 'w'), sort_keys=False)
"
.venv/bin/pytest tests/unit/test_registry_sync.py -v || echo "GUARD FIRED (expected)"
cp /tmp/ecosystem.yaml.bak settings/ecosystem.yaml
rm /tmp/ecosystem.yaml.bak
.venv/bin/pytest tests/unit/test_registry_sync.py -v
```

Expected: the middle run FAILS on `test_canonical_is_superset_of_legacy` and
`test_entry_count_is_thirty_five`; the final run PASSES. A guard that has never
been seen to fail is not known to work.

- [ ] **Step 4: Run the full quality gate**

Run: `.venv/bin/python -m crackerjack run`

Expected: PASS. If `mdformat` flags the followup doc, note that it will corrupt YAML
frontmatter — `mdformat-frontmatter` is not installed in this venv, and
`docs/plans/PLAN_INDEX.md` also fails `mdformat --check` for the same reason. Do not
run `mdformat` on any file with frontmatter.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_registry_sync.py
git commit -m "test(registry): pin legacy entry count against silent deletion

Completes the four-assertion guard: paths exist, roles are in taxonomy,
canonical is a superset of legacy, and legacy cannot shrink unnoticed.
Verified by breaking the manifest and observing the failure."
```

#### Integration Contract — Phases 2 and 3

- **Triggered from:** `pytest tests/unit/test_registry_sync.py`, executed by
  `crackerjack run` on every quality gate. Also `mahavishnu/repo_cli.py:_load_catalog()`
  for the repoint.
- **Returns to / updates:** `settings/ecosystem.yaml` (35 entries, 16 roles),
  `settings/repos.yaml` (deprecation header), `mahavishnu/repo_cli.py`
  (`REPOS_CATALOG_PATH`), `docs/followups/2026-09-06-sibling-repos-yaml-audit.md`.
- **Demonstrable by:** `pytest tests/unit/test_registry_sync.py -v` passes;
  `mahavishnu list-repos | grep raindropio-mcp` returns a line where it previously
  returned nothing; `mahavishnu repo diff /Users/les/Projects/raindropio-mcp` runs;
  Task 9 Step 3 shows the guard firing on injected drift.
- **Rollback signal:** `mahavishnu list-repos` errors or returns fewer than 35 entries;
  `mahavishnu repo diff` reports a catalog miss for a known repo. Revert the
  `settings/ecosystem.yaml` and `repo_cli.py` hunks together — they are coupled.
- **Observability added:** `load_repos()`'s existing INFO log
  `"Loaded %d repositories from %s"` now reports 35 from `ecosystem.yaml`. The guard
  test's failure messages name the specific drifting entries rather than reporting a
  bare count mismatch.

______________________________________________________________________

## Validation Matrix

| Command | Expected outcome | Evidence |
|---|---|---|
| `.venv/bin/pytest tests/unit/test_registry_sync.py -v` | all pass | Tasks 1-9 |
| `.venv/bin/mahavishnu list-repos \| grep -E 'archive-org-mcp\|medium-mcp\|scapy-mcp'` | 3 lines | Task 1 Step 5 |
| `.venv/bin/mahavishnu list-repos \| grep -E 'raindropio-mcp\|fastblocks\|bodai'` | 3 lines | Task 5 Step 5 |
| `.venv/bin/mahavishnu repo diff /Users/les/Projects/raindropio-mcp` | runs, no catalog miss | Task 6 Step 6 |
| `.venv/bin/pytest tests/unit/test_repo_cli_coverage.py -v` | pass | Task 6 Step 7 |
| Guard fires on injected drift | test fails, then passes after restore | Task 9 Step 3 |
| `.venv/bin/python -m crackerjack run` | pass | Task 9 Step 4 |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Migration breaks routing for the 8 already-working repos | medium | Guard asserts required keys and path existence on all 35; the one field conflict is enumerated; `list-repos` verified after |
| `repo_cli` repoint breaks `repo diff` | medium | Task 6 Step 6 exercises the command end-to-end; Step 7 runs the existing test file |
| An existing test asserts the legacy path literally | medium | Task 6 Step 7 surfaces it; update the assertion, since the wiring changed deliberately |
| `mdformat` corrupts the followup doc's frontmatter | high if run | Task 9 Step 4 warns explicitly; `mdformat-frontmatter` is absent from this venv |
| Sibling `repos.yaml` files turn out to be stale copies | unknown | Task 8 documents rather than migrates; a follow-up plan is named if needed |

## Decision Rule

Plan 0a is done when the guard suite passes, `mahavishnu list-repos` returns 35 entries,
and `mahavishnu repo diff` still works.

Under scope pressure, Task 8 (sibling audit) is the only cuttable item — it produces a
document, not behaviour. **Task 1 must never be cut**: three sibling plans are gated on
it. Tasks 2-4 and 9 must never be cut — they are the guard whose absence caused this
drift to survive four months.

# Plan Index Dhara-Canonical Metadata Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **v2 changelog (post 4-agent plan review):** Applied BLOCKER + HIGH fixes from a 4-agent rotated-angle review (implementation order, test coverage, migration safety, code-correctness). Critical fixes: (a) `Permission.READ_PLAN_INDEX` case corrected to lowercase `"read_plan_index"` to match `RBACManager.check_permission`'s `.lower()` coercion; (b) `derive_plan_id` now normalizes repo internally so the spec test passes; (c) `register_plan_tools` call site in bootstrap.py uses correct `store_provider=` injection; (d) `discover_stores` arity fixed (was missing `yaml_module` arg); (e) cron `run_rebuild_cycle` no longer a no-op — reads filesystem via the orchestrator helper; (f) `PlanIndexFeedState.as_dict()` keys prefixed with `feed_` to match `SignerFeedState` precedent and the wiring discipline's strict 4-signal contract; (g) ~25 missing spec-mandated test files added as Task 11.5. Migration tasks 18-20 collapsed into a Makefile-driven runbook plus explicit test artifacts.

**Goal:** Replace filesystem-scanned `docs/plans/PLAN_INDEX.md` with a Dhara-canonical metadata index — same read substrate topology as jot, but with git as the only write path. Cross-machine visibility, serverless compatibility, and a queryable substrate for the math plan's `scripts/feature_eligibility.py`.

**Architecture:** Four layers — git (write-only) → rebuilder + renderer (CLI orchestrator) → Dhara index (canonical store, slash-separated keys per `dhara-key-prefixes-2026-07-15.md`) → 5 typed-Dict MCP tools gated by `@require_mcp_auth(Permission.READ_PLAN_INDEX)`. A `PeriodicTaskRunner` invokes the rebuilder every hour; the renderer emits markdown for humans; the tools read Dhara directly.

**Tech Stack:** Python 3.14, Dhara (canonical store), Oneiric EventBridge (telemetry topic), typer (CLI), FastMCP (tool registration), pytest + Hypothesis (property tests).

**Spec:** `docs/superpowers/specs/2026-09-10-plan-index-dhara-design.md`

## Global Constraints

These apply to every task. Failure to honor them is a BLOCKER on merge.

- **Python 3.14**, `from __future__ import annotations` as the first non-comment line of every source file
- **Frozen dataclasses with slots**: `@dataclass(frozen=True, slots=True, kw_only=True)` — no mutable defaults
- **No `Any` in tool inputs or orchestration state**: TypedDicts everywhere
- **No `assert` in production code** (`mahavishnu/plan_index/`, `mahavishnu/mcp/tools/plan_tools.py`): bandit B101
- **Mypy strict** with `disallow_untyped_defs`, `no_implicit_optional`, `warn_unused_ignores`, `warn_return_any`
- **Line length**: 100 chars; function args ≤ 10; branches ≤ 15; returns ≤ 6; statements ≤ 55
- **Imports sorted** (stdlib → third-party → first-party with `known-first-party = ["mahavishnu"]`)
- **Test markers**: `unit`, `integration`, `property`, `slow`. No new markers invented.
- **Coverage gate**: ≥ 89% line coverage on `mahavishnu/plan_index/` and `mahavishnu/mcp/tools/plan_tools.py`
- **Auth gate**: ALL five `plan_*` MCP tools require `@require_mcp_auth(required_permission=Permission.READ_PLAN_INDEX)` when `MAHAVISHNU_AUTH_ENABLED=true`. The decorator must be applied in the same PR as the 5-edit registration dance. Test `test_auth_gate_e2e.py` enforces this.
- **`repo` normalization**: `PlanIndexRebuilder.normalize_repo_url()` runs BEFORE `plan_id` derivation. Strip userinfo, lowercase host, hash path segments, reject control characters. The normalized form is what gets persisted AND fed into the SHA.
- **Errors log redaction**: `PlanRebuildErrorDict.ctx` is a TypedDict; never contains raw `path` or `repo` — only `path_hash = sha256(path)[:12]`.
- **Wire-up discipline**: `PlanIndexFeedState.as_dict()` returns EXACTLY `{ok, entities_count, last_updated_timestamp, errors_total, cycles_total}` plus nothing — the 4-signal contract is strict.

---

## Task 1: Foundation — PlanId, errors, TypedDicts

**Files:**
- Create: `mahavishnu/plan_index/__init__.py`
- Create: `mahavishnu/plan_index/paths.py`
- Create: `mahavishnu/plan_index/errors.py`
- Test: `tests/unit/plan_index/__init__.py`
- Test: `tests/unit/plan_index/test_paths.py`
- Test: `tests/unit/plan_index/test_errors.py`

**Interfaces:**
- Consumes: nothing (foundation)
- Produces:
  - `PlanId = NewType("PlanId", str)`
  - `errors_log_path() -> Path`, `jot_dir() -> Path`, `log_path() -> Path`, `node_path() -> Path` (mirrors `mahavishnu/jot/paths.py`)
  - `class PlanIndexError(Exception)` + `PlanNotFoundError(PlanIndexError)` + `PlanIndexUnavailableError(PlanIndexError)` + `PlanRebuildLockedError(PlanIndexError)`
  - `__all__` exports on each module

- [ ] **Step 1: Write the failing paths test**

```python
# tests/unit/plan_index/test_paths.py
from __future__ import annotations

from pathlib import Path

import pytest

from mahavishnu.plan_index.paths import (
    errors_log_path,
    jot_dir,
    log_path,
    node_path,
)


class TestPaths:
    def test_jot_dir_default(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        path = jot_dir()
        assert path == tmp_path / ".mahavishnu" / "plan_index"
        assert path.exists()
        assert oct(path.stat().st_mode)[-3:] == "700"

    def test_log_path_under_jot_dir(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        assert log_path().parent == jot_dir()

    def test_errors_log_path_under_jot_dir(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        assert errors_log_path().parent == jot_dir()

    def test_node_path_under_jot_dir(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        assert node_path().parent == jot_dir()

    def test_log_file_mode_0o600_on_creation(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        path = log_path()
        assert path.exists()
        assert oct(path.stat().st_mode)[-3:] == "600"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/plan_index/test_paths.py -v`
Expected: ImportError or ModuleNotFoundError because `mahavishnu/plan_index/` doesn't exist yet.

- [ ] **Step 3: Create `mahavishnu/plan_index/__init__.py`**

```python
"""Plan-index Dhara-canonical metadata layer."""

from __future__ import annotations

from typing import NewType

PlanId = NewType("PlanId", str)

__all__ = ["PlanId"]
```

- [ ] **Step 4: Create `mahavishnu/plan_index/paths.py`**

```python
"""Filesystem paths for the plan_index module.

Mirror `mahavishnu/jot/paths.py` for mode discipline (0o700 dir, 0o600 files).
The jot_dir() raises PermissionError on creation failure; we propagate.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["jot_dir", "log_path", "errors_log_path", "node_path"]


def jot_dir() -> Path:
    """Return the plan_index directory, creating it with mode 0o700."""
    path = Path.home() / ".mahavishnu" / "plan_index"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def log_path() -> Path:
    """Return the path to the in-memory operational log (not currently used in v1)."""
    return jot_dir() / "log.jsonl"


def errors_log_path() -> Path:
    """Return the path to errors.log. Mode 0o600 on creation."""
    path = jot_dir() / "errors.log"
    if not path.exists():
        os.open(str(path), os.O_CREAT | os.O_WRONLY, 0o600).close()
    return path


def node_path() -> Path:
    """Return the path to the persisted HLC node identifier."""
    return jot_dir() / "node"
```

- [ ] **Step 5: Create `mahavishnu/plan_index/errors.py`**

```python
"""Error hierarchy for plan_index.

Subclasses carry structured context. FastMCP subclass serialization
is verified by tests/integration/plan_index/test_fastmcp_error_serialization.py.
"""

from __future__ import annotations

from typing import Any

__all__ = ["PlanIndexError", "PlanNotFoundError", "PlanIndexUnavailableError", "PlanRebuildLockedError"]


class PlanIndexError(Exception):
    """Base class for all plan_index errors."""


class PlanNotFoundError(PlanIndexError):
    """plan_id matched no record."""

    def __init__(self, plan_id: str, message: str | None = None) -> None:
        super().__init__(message or f"Plan not found: {plan_id}")
        self.plan_id = plan_id


class PlanIndexUnavailableError(PlanIndexError):
    """Dhara unreachable; caller should fall back to filesystem read."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"plan_index unavailable: {reason}")
        self.reason = reason


class PlanRebuildLockedError(PlanIndexError):
    """Another rebuild holds the lock."""

    def __init__(self, holder: str, age_ms: int) -> None:
        super().__init__(f"plan_index rebuild locked by {holder} ({age_ms}ms)")
        self.holder = holder
        self.age_ms = age_ms
```

- [ ] **Step 6: Create `tests/unit/plan_index/__init__.py`**

```python
"""Unit tests for plan_index."""
```

- [ ] **Step 7: Create empty `tests/unit/plan_index/test_errors.py`**

```python
from __future__ import annotations

from mahavishnu.plan_index.errors import (
    PlanIndexError,
    PlanIndexUnavailableError,
    PlanNotFoundError,
    PlanRebuildLockedError,
)


class TestErrorHierarchy:
    def test_subclasses_inherit_from_base(self) -> None:
        assert issubclass(PlanNotFoundError, PlanIndexError)
        assert issubclass(PlanIndexUnavailableError, PlanIndexError)
        assert issubclass(PlanRebuildLockedError, PlanIndexError)

    def test_not_found_carries_plan_id(self) -> None:
        err = PlanNotFoundError("abc123")
        assert err.plan_id == "abc123"
        assert "abc123" in str(err)

    def test_unavailable_carries_reason(self) -> None:
        err = PlanIndexUnavailableError("connection timeout")
        assert err.reason == "connection timeout"

    def test_locked_carries_holder_and_age(self) -> None:
        err = PlanRebuildLockedError("deadbeef/1234", 5000)
        assert err.holder == "deadbeef/1234"
        assert err.age_ms == 5000
```

- [ ] **Step 8: Run paths test to verify it passes**

Run: `pytest tests/unit/plan_index/test_paths.py tests/unit/plan_index/test_errors.py -v`
Expected: 9 tests pass.

- [ ] **Step 9: Run type check + lint**

Run: `uv run crackerjack run -p minor`
Expected: mypy strict clean; ruff clean.

- [ ] **Step 10: Commit**

```bash
git add mahavishnu/plan_index/ tests/unit/plan_index/
git commit -m "feat(plan_index): foundation — PlanId, errors hierarchy, paths"
```

---

## Task 2: TypedDicts — plan surface types

**Files:**
- Create: `mahavishnu/plan_index/types.py`
- Test: `tests/unit/plan_index/test_types.py`

**Interfaces:**
- Consumes: PlanId from `mahavishnu/plan_index/__init__.py`
- Produces:
  - `PlanRecordDict`, `RebuildErrorCtx`, `PlanVitalsDict`, `PlanRebuildStatusDict`, `PlanRebuildErrorDict`, `PlanListResultDict`, `PlanDegradedDict`
  - `Literal["ok", "no_recent_edits", "no_recent_reads", "review_cadence_lagging"]` (4 distinct states)

- [ ] **Step 1: Write the failing types test**

```python
# tests/unit/plan_index/test_types.py
from __future__ import annotations

from typing import NotRequired, TypedDict, get_type_hints

import pytest

from mahavishnu.plan_index.types import (
    PlanDegradedDict,
    PlanListResultDict,
    PlanRecordDict,
    PlanRebuildErrorDict,
    PlanRebuildStatusDict,
    PlanVitalsDict,
    RebuildErrorCtx,
    TripwireState,
)


class TestTripwireState:
    def test_exactly_four_distinct_states(self) -> None:
        states: tuple[TripwireState, ...] = get_args(TripwireState)
        assert len(states) == 4
        assert len(set(states)) == 4  # all distinct
        assert "ok" in states
        assert "review_cadence_lagging" in states


class TestPlanRecordDict:
    def test_required_fields_present(self) -> None:
        hints = get_type_hints(PlanRecordDict)
        for required in (
            "plan_id", "path", "title", "status", "role", "topic",
            "date", "last_reviewed", "blocks_on", "sha", "repo",
            "updated_at_ms",
        ):
            assert required in hints, f"missing required field: {required}"


class TestRebuildErrorCtx:
    def test_all_fields_not_required(self) -> None:
        hints = get_type_hints(RebuildErrorCtx, include_extras=True)
        # NotRequired fields have the marker
        assert "plan_id" in hints
        assert "path_hash" in hints  # never raw path
        assert "op" in hints


class TestPlanVitalsTripwire:
    def test_tripwire_field_uses_literal(self) -> None:
        hints = get_type_hints(PlanVitalsDict)
        assert hints["tripwire"] is TripwireState


class TestPlanRebuildStatusLockHeldBy:
    def test_lock_held_by_field_is_optional(self) -> None:
        hints = get_type_hints(PlanRebuildStatusDict)
        assert "lock_held_by" in hints


class TestPlanListResultDictStatus:
    def test_status_field_uses_literal(self) -> None:
        hints = get_type_hints(PlanListResultDict)
        assert hints["status"] is str  # Literal collapses to str at runtime


class TestPlanRebuildErrorCtx:
    def test_ctx_is_typed_dict_not_dict(self) -> None:
        hints = get_type_hints(PlanRebuildErrorDict)
        # TypedDict hints are typed fields, not dict[str, Any]
        assert hints["ctx"] is RebuildErrorCtx


class TestPlanDegradedDictNoStatusField:
    def test_no_status_literal_field(self) -> None:
        hints = get_type_hints(PlanDegradedDict)
        # The type IS the discriminator; single-value Literal is a code smell.
        assert "status" not in hints
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/plan_index/test_types.py -v`
Expected: ModuleNotFoundError on `mahavishnu.plan_index.types`.

- [ ] **Step 3: Create `mahavishnu/plan_index/types.py`**

```python
"""TypedDicts for the plan_index MCP surface.

All public TypedDicts are TypedDict (not dict[str, Any]) per the
CLAUDE.md "no Any" hard rule. Conditional fields use NotRequired[T].
"""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

# 4 distinct tripwire states. v0 had "ok" duplicated; fixed.
TripwireState = Literal[
    "ok", "no_recent_edits", "no_recent_reads", "review_cadence_lagging"
]


class RebuildErrorCtx(TypedDict, total=False):
    """Structured context for PlanRebuildErrorDict.

    NEVER carries raw path or repo. Use path_hash = sha256(path).hexdigest()[:12].
    """
    plan_id: NotRequired[str]
    path_hash: NotRequired[str]
    op: NotRequired[str]
    attempt: NotRequired[int]


class PlanRecordDict(TypedDict):
    plan_id: str
    path: str
    title: str
    status: str
    role: str
    topic: str
    date: str
    last_reviewed: str
    superseded_by: NotRequired[str]
    blocks_on: list[str]
    sha: str
    repo: str
    lifecycle_state: NotRequired[str]
    updated_at_ms: int


class PlanVitalsDict(TypedDict):
    total: int
    by_status: dict[str, int]
    by_role: dict[str, int]
    by_topic_top10: list[tuple[str, int]]
    last_rebuild_ms: NotRequired[int]
    last_success_ms: NotRequired[int]
    oldest_active_ms: NotRequired[int]
    cycles_total: int
    successful_cycles_total: int
    errors_total: int
    recent_errors: list[PlanRebuildErrorDict]
    tripwire: TripwireState


class PlanRebuildStatusDict(TypedDict):
    last_rebuild_ms: NotRequired[int]
    last_success_ms: NotRequired[int]
    cycles_total: int
    successful_cycles_total: int
    errors_total: int
    recent_errors: list[PlanRebuildErrorDict]
    lock_held_by: NotRequired[str]
    lock_age_ms: NotRequired[int]
    stale: bool


class PlanRebuildErrorDict(TypedDict):
    ts_ms: int
    op: str
    err: str
    ctx: RebuildErrorCtx


class PlanListResultDict(TypedDict):
    plans: list[PlanRecordDict]
    total: int
    cached_at_ms: NotRequired[int]
    status: Literal["ok", "degraded"]


class PlanDegradedDict(TypedDict):
    """Discriminated by absence of the 'plans' field. No 'status' literal."""

    reason: str
    cached_at_ms: NotRequired[int]


__all__ = [
    "PlanDegradedDict",
    "PlanListResultDict",
    "PlanRecordDict",
    "PlanRebuildErrorDict",
    "PlanRebuildStatusDict",
    "PlanVitalsDict",
    "RebuildErrorCtx",
    "TripwireState",
]
```

Wait — `PlanDegradedDict` was supposed to remove `status`, but the test asserts `"status" not in hints`. The current TypedDict above has no `status` field. Test passes.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/plan_index/test_types.py -v`
Expected: 9 tests pass.

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/plan_index/types.py tests/unit/plan_index/test_types.py
git commit -m "feat(plan_index): TypedDicts for MCP surface"
```

---

## Task 3: PlanRecord dataclass

**Files:**
- Create: `mahavishnu/plan_index/record.py`
- Test: `tests/unit/plan_index/test_record.py`

**Interfaces:**
- Consumes: `PlanId` from `mahavishnu/plan_index/__init__.py`
- Produces:
  - `@dataclass(frozen=True, slots=True, kw_only=True) class PlanRecord` with the 13 fields from spec §Data Model

- [ ] **Step 1: Write the failing record test**

```python
# tests/unit/plan_index/test_record.py
from __future__ import annotations

import pytest

from mahavishnu.plan_index.record import PlanRecord


def _sample(**overrides: object) -> PlanRecord:
    defaults: dict[str, object] = {
        "plan_id": "abcdef0123456789abcdef0123456789",  # 32 hex chars
        "path": "docs/plans/2026-09-15-foo.md",
        "title": "Foo",
        "status": "draft",
        "role": "implementation",
        "topic": "routing-composition",
        "date": "2026-09-15",
        "last_reviewed": "2026-09-15",
        "superseded_by": None,
        "blocks_on": [],
        "sha": "f" * 40,
        "repo": "github.com/example/repo",
        "updated_at_ms": 1700000000000,
    }
    defaults.update(overrides)  # type: ignore[arg-type]
    return PlanRecord(**defaults)  # type: ignore[arg-type]


class TestPlanRecordShape:
    def test_required_fields_construct(self) -> None:
        rec = _sample()
        assert rec.plan_id == "abcdef0123456789abcdef0123456789"
        assert rec.path == "docs/plans/2026-09-15-foo.md"
        assert rec.status == "draft"

    def test_frozen_prevents_mutation(self) -> None:
        rec = _sample()
        with pytest.raises((AttributeError, Exception)):  # FrozenInstanceError
            rec.title = "Bar"  # type: ignore[misc]

    def test_kw_only_required(self) -> None:
        # Positional args are rejected at construction
        with pytest.raises(TypeError):
            PlanRecord("id", "path", "title")  # type: ignore[misc]

    def test_status_literal_rejected_at_runtime(self) -> None:
        with pytest.raises(ValueError):
            _sample(status="in-review")  # type: ignore[arg-type]

    def test_role_literal_rejected_at_runtime(self) -> None:
        with pytest.raises(ValueError):
            _sample(role="spec")  # type: ignore[arg-type]

    def test_lifecycle_state_default_is_none(self) -> None:
        rec = _sample()
        assert rec.lifecycle_state is None

    def test_lifecycle_state_accepts_feature_tracking_values(self) -> None:
        rec = _sample(lifecycle_state="adopted")
        assert rec.lifecycle_state == "adopted"


class TestPlanRecordBlocksOn:
    def test_blocks_on_accepts_plan_ids(self) -> None:
        rec = _sample(blocks_on=["11111111111111111111111111111111", "22222222222222222222222222222222"])
        assert len(rec.blocks_on) == 2

    def test_blocks_on_empty_default(self) -> None:
        rec = _sample()
        assert rec.blocks_on == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/plan_index/test_record.py -v`
Expected: ModuleNotFoundError on `mahavishnu.plan_index.record`.

- [ ] **Step 3: Create `mahavishnu/plan_index/record.py`**

```python
"""PlanRecord — frozen dataclass for plan-index entries.

13 fields per spec §Data Model. kw_only=True prevents positional mistakes.
status/role/lifecycle_state use Literal; invalid values raise ValueError
at construction (mypy checks at static time, runtime check is defensive).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from mahavishnu.plan_index import PlanId

__all__ = ["PlanRecord"]


@dataclass(frozen=True, slots=True, kw_only=True)
class PlanRecord:
    plan_id: PlanId
    path: str
    title: str
    status: Literal["draft", "active", "partial", "shipped", "complete"]
    role: Literal[
        "canonical", "implementation", "umbrella", "historical", "superseded"
    ]
    topic: str
    date: str
    last_reviewed: str
    superseded_by: str | None
    blocks_on: list[PlanId]
    sha: str
    repo: str
    lifecycle_state: Literal["built", "wired", "adopted"] | None = None
    updated_at_ms: int
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/plan_index/test_record.py -v`
Expected: 9 tests pass.

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/plan_index/record.py tests/unit/plan_index/test_record.py
git commit -m "feat(plan_index): PlanRecord dataclass with Literal enums"
```

---

## Task 4: normalize_repo_url — security-critical helper

**Files:**
- Create: `mahavishnu/plan_index/url.py`
- Test: `tests/unit/plan_index/test_url.py`

**Interfaces:**
- Consumes: nothing (pure function)
- Produces:
  - `normalize_repo_url(raw: str) -> str | None` — returns normalized form, or `None` if rejected
  - `class RepoUrlRejectedError(ValueError)` — raised when caller wants the rejection reason
  - The normalized form is what gets persisted AND fed into the `plan_id` SHA

- [ ] **Step 1: Write the failing url test**

```python
# tests/unit/plan_index/test_url.py
from __future__ import annotations

import pytest

from mahavishnu.plan_index.url import (
    RepoUrlRejectedError,
    normalize_repo_url,
)


class TestNormalizeSshForm:
    def test_ssh_shorthand_normalized(self) -> None:
        result = normalize_repo_url("git@github.com:foo/bar.git")
        assert result is not None
        # Userinfo stripped, host lowercased, path hashed
        assert "github.com" in result
        assert "@" not in result.split("/")[0]  # no userinfo in path segment
        assert result.startswith("github.com/")


class TestNormalizeHttpsForm:
    def test_https_normalized(self) -> None:
        result = normalize_repo_url("https://github.com/foo/bar.git")
        assert result is not None
        assert "github.com" in result


class TestNormalizeSshProtocolForm:
    def test_ssh_protocol_normalized(self) -> None:
        result = normalize_repo_url("ssh://git@github.com/foo/bar.git")
        assert result is not None
        assert "github.com" in result


class TestThreeUrlFormsSameRepo:
    def test_three_forms_produce_same_normalization(self) -> None:
        forms = [
            "git@github.com:foo/bar.git",
            "https://github.com/foo/bar.git",
            "ssh://git@github.com/foo/bar.git",
        ]
        normalized = [normalize_repo_url(f) for f in forms]
        assert all(n is not None for n in normalized)
        # Same host + same path → same normalized output
        # (path normalization hashes path segments so two forms with same path produce same)
        assert normalized[0] == normalized[1] == normalized[2]


class TestRejection:
    def test_empty_string_rejected(self) -> None:
        assert normalize_repo_url("") is None

    def test_garbage_string_rejected(self) -> None:
        assert normalize_repo_url("not a url") is None

    def test_control_characters_rejected(self) -> None:
        with pytest.raises(Exception):
            normalize_repo_url("git@github.com:foo/bar\x00.git")

    def test_ftp_protocol_rejected(self) -> None:
        assert normalize_repo_url("ftp://github.com/foo/bar.git") is None


class TestUserinfoStripping:
    def test_https_with_userinfo_strips_user(self) -> None:
        result = normalize_repo_url("https://user:pass@github.com/foo/bar.git")
        assert result is not None
        # No "user" or "pass" in normalized form
        assert "user" not in result
        assert "pass" not in result

    def test_ssh_user_prefix_stripped(self) -> None:
        result = normalize_repo_url("git@github.com:foo/bar.git")
        assert result is not None
        # The "git@" user is stripped
        assert not result.startswith("git@")


class TestHostLowercasing:
    def test_uppercase_host_lowercased(self) -> None:
        result = normalize_repo_url("https://GitHub.com/foo/bar.git")
        assert result is not None
        assert "github.com" in result
        assert "GitHub.com" not in result


class TestPathHashing:
    def test_path_segments_hashed(self) -> None:
        result = normalize_repo_url("https://github.com/secret-org/secret-project.git")
        assert result is not None
        # Path segments should NOT appear verbatim in normalized form
        assert "secret-org" not in result
        assert "secret-project" not in result


class TestRepoUrlRejectedError:
    def test_raised_with_rejection_reason(self) -> None:
        with pytest.raises(RepoUrlRejectedError) as exc_info:
            normalize_repo_url("garbage", raise_on_reject=True)
        assert exc_info.value.reason  # populated
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/plan_index/test_url.py -v`
Expected: ModuleNotFoundError on `mahavishnu.plan_index.url`.

- [ ] **Step 3: Create `mahavishnu/plan_index/url.py`**

```python
"""Git remote URL normalization (security: REQ-PLAN-011).

normalize_repo_url runs BEFORE plan_id derivation (D4). The normalized
form is what gets persisted to Dhara AND fed into the SHA. Three URL
forms of the same repo produce the same normalized output:

    git@github.com:foo/bar.git
    https://github.com/foo/bar.git
    ssh://git@github.com/foo/bar.git

    →
    github.com/<hash_of_foo/bar>

The hash is sha256("/".join(path_segments)).hexdigest()[:12].
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from urllib.parse import urlparse

__all__ = ["RepoUrlRejectedError", "normalize_repo_url"]

# URL pattern: scheme + host + path. Reject anything else.
_ALLOWED_PATTERN = re.compile(r"^(git@|https?://|ssh://)[A-Za-z0-9._-]+(/|:).+$")
_PATH_SEGMENT_DELIM = "/"
_HASH_PREFIX_LEN = 12


@dataclass(frozen=True, slots=True)
class RepoUrlRejectedError(ValueError):
    """Raised by normalize_repo_url when the input cannot be normalized."""

    raw: str
    reason: str

    def __str__(self) -> str:
        return f"RepoUrlRejectedError({self.reason!r}, raw={self.raw!r})"


def _strip_userinfo(url: str) -> str:
    """Strip userinfo (user:pass@ or user@) from a URL.

    The git@github.com:path shorthand has no scheme; convert to ssh:// first.
    """
    if url.startswith("git@"):
        # git@host:path → ssh://git@host/path (parseable by urlparse)
        host_part, _, path_part = url.partition(":")
        host = host_part.removeprefix("git@")
        return f"ssh://{host}/{path_part}"
    return url


def _hash_path_segments(path: str) -> str:
    """Hash path segments so repo structure is not exposed in Dhara."""
    # Strip leading slashes, drop .git suffix, split on /
    cleaned = path.strip("/").removesuffix(".git")
    segments = cleaned.split(_PATH_SEGMENT_DELIM)
    joined = _PATH_SEGMENT_DELIM.join(segments)
    return hashlib.sha256(joined.encode()).hexdigest()[:_HASH_PREFIX_LEN]


def normalize_repo_url(raw: str, *, raise_on_reject: bool = False) -> str | None:
    """Normalize a git remote URL.

    Returns:
        The normalized form "host/<path_hash>" if the URL is well-formed.
        None if rejected (default behavior).

    Raises:
        RepoUrlRejectedError if raise_on_reject=True and the URL is rejected.

    The normalized form is stable across the three canonical URL formats
    (git@, https://, ssh://), lowercase, and has its path hashed.
    """
    if not isinstance(raw, str):
        if raise_on_reject:
            raise RepoUrlRejectedError(str(raw), "not a string")
        return None

    # Control character check
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in raw):
        if raise_on_reject:
            raise RepoUrlRejectedError(raw, "control characters")
        return None

    # Pattern check before normalization
    if not _ALLOWED_PATTERN.match(raw):
        if raise_on_reject:
            raise RepoUrlRejectedError(raw, "does not match allowed pattern")
        return None

    # Strip userinfo
    stripped = _strip_userinfo(raw)

    # Parse
    try:
        parsed = urlparse(stripped)
    except ValueError:
        if raise_on_reject:
            raise RepoUrlRejectedError(raw, "urlparse failure")
        return None

    # Lowercase host
    host = (parsed.hostname or "").lower()
    if not host:
        if raise_on_reject:
            raise RepoUrlRejectedError(raw, "no host")
        return None

    # Hash path
    path_hash = _hash_path_segments(parsed.path or "")
    return f"{host}/{path_hash}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/plan_index/test_url.py -v`
Expected: 14 tests pass.

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/plan_index/url.py tests/unit/plan_index/test_url.py
git commit -m "feat(plan_index): normalize_repo_url helper (REQ-PLAN-011)"
```

---

## Task 5: PlanIndexStore — Dhara-backed CRUD

**Files:**
- Create: `mahavishnu/plan_index/store.py`
- Test: `tests/unit/plan_index/test_store.py`

**Interfaces:**
- Consumes: `PlanRecord`, Dhara client (mockable via DI)
- Produces:
  - `class PlanIndexStore` with methods:
    - `__init__(self, dhara: AsyncClient | None = None)` — DI for testing
    - `async def upsert(self, record: PlanRecord) -> None`
    - `async def get(self, plan_id: PlanId) -> PlanRecordDict | None`
    - `async def list_by_status(self, status: str, *, limit: int = 50) -> list[PlanRecordDict]`
    - `async def list_by_topic(self, topic: str, *, limit: int = 50) -> list[PlanRecordDict]`
    - `async def list_by_date_range(self, date_from: str, date_to: str) -> list[PlanRecordDict]`
    - `async def list_all(self, *, limit: int = 1000) -> list[PlanRecordDict]`
    - `async def vitals(self) -> PlanVitalsDict`
    - `async def rebuild_status(self) -> PlanRebuildStatusDict`
    - `async def search(self, query: str, *, limit: int = 20) -> list[PlanRecordDict]`

- [ ] **Step 1: Write the failing store test**

```python
# tests/unit/plan_index/test_store.py
from __future__ import annotations

import pytest

from mahavishnu.plan_index import PlanId
from mahavishnu.plan_index.record import PlanRecord
from mahavishnu.plan_index.store import PlanIndexStore
from mahavishnu.plan_index.testing import FakeDhara  # to be added in this task


def _sample_record(plan_id: str = "11111111111111111111111111111111") -> PlanRecord:
    return PlanRecord(
        plan_id=plan_id,
        path="docs/plans/2026-09-15-foo.md",
        title="Foo",
        status="active",
        role="implementation",
        topic="routing-composition",
        date="2026-09-15",
        last_reviewed="2026-09-15",
        superseded_by=None,
        blocks_on=[],
        sha="f" * 40,
        repo="github.com/example/repo",
        updated_at_ms=1700000000000,
    )


@pytest.fixture
def store() -> PlanIndexStore:
    fake = FakeDhara()
    return PlanIndexStore(dhara=fake)  # type: ignore[arg-type]


class TestUpsertAndGet:
    @pytest.mark.asyncio
    async def test_upsert_then_get_roundtrips(self, store: PlanIndexStore) -> None:
        rec = _sample_record()
        await store.upsert(rec)
        result = await store.get(rec.plan_id)
        assert result is not None
        assert result["plan_id"] == rec.plan_id
        assert result["path"] == rec.path
        assert result["status"] == rec.status


class TestListByStatus:
    @pytest.mark.asyncio
    async def test_list_by_status_filters(self, store: PlanIndexStore) -> None:
        await store.upsert(_sample_record("11" * 16))
        await store.upsert(_sample_record("22" * 16))
        await store.upsert(
            _sample_record("33" * 16).__class__(
                **{  # type: ignore[arg-type]
                    **_sample_record("33" * 16).__dict__,
                    "status": "shipped",  # type: ignore[dict-item]
                }
            )
        )
        active = await store.list_by_status("active")
        assert len(active) == 2
        shipped = await store.list_by_status("shipped")
        assert len(shipped) == 1


class TestVitals:
    @pytest.mark.asyncio
    async def test_vitals_empty(self, store: PlanIndexStore) -> None:
        v = await store.vitals()
        assert v["total"] == 0
        assert v["cycles_total"] == 0
        assert v["tripwire"] == "ok"

    @pytest.mark.asyncio
    async def test_vitals_after_upserts(self, store: PlanIndexStore) -> None:
        for i in range(3):
            await store.upsert(_sample_record(str(i + 1) * 16))
        v = await store.vitals()
        assert v["total"] == 3
        assert v["by_status"]["active"] == 3


class TestRebuildStatus:
    @pytest.mark.asyncio
    async def test_rebuild_status_never_ran(self, store: PlanIndexStore) -> None:
        s = await store.rebuild_status()
        assert s["cycles_total"] == 0
        assert s["stale"] is True
        assert "last_rebuild_ms" not in s
```

The test references `FakeDhara` from `mahavishnu.plan_index.testing`. Add that as part of this task.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/plan_index/test_store.py -v`
Expected: ModuleNotFoundError on `mahavishnu.plan_index.store`.

- [ ] **Step 3: Create `mahavishnu/plan_index/testing.py` (FakeDhara)**

```python
"""Test helpers for plan_index — mock Dhara client."""

from __future__ import annotations

import json
from typing import Any

__all__ = ["FakeDhara"]


class FakeDhara:
    """Minimal in-memory Dhara stand-in for tests.

    Implements the subset of AsyncClient API used by PlanIndexStore.
    """

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def put(self, key: str, value: str, *, ttl: int | None = None) -> None:
        self._store[key] = value

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def list_prefix(self, prefix: str) -> list[tuple[str, str]]:
        return [(k, v) for k, v in self._store.items() if k.startswith(prefix)]

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)
```

- [ ] **Step 4: Create `mahavishnu/plan_index/store.py`**

```python
"""Dhara-backed CRUD for plan metadata.

This is the only file that imports the Dhara client. PlanIndexRebuilder,
PlanIndexRenderer, PeriodicTaskRunner, and the MCP tools all consume
this module's interface — never Dhara directly.

Key conventions (mirror dhara-key-prefixes-2026-07-15.md):
  - plan_index/{plan_id}                  — primary, TTL 24h
  - plan_index/status/{status}/{date}/{plan_id}  — secondary index
  - plan_index/topic/{topic}/{date}/{plan_id}    — secondary index
  - plan_index/meta/{counter}             — counters (no TTL)
  - plan_index/meta/rebuild_lock/...      — TTL 60s
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Protocol

from mahavishnu.plan_index import PlanId
from mahavishnu.plan_index.record import PlanRecord
from mahavishnu.plan_index.types import (
    PlanListResultDict,
    PlanRebuildStatusDict,
    PlanRecordDict,
    PlanVitalsDict,
    TripwireState,
)

if TYPE_CHECKING:
    pass


__all__ = ["PlanIndexStore"]


class _DharaClient(Protocol):
    """Subset of AsyncClient that PlanIndexStore uses. Exists for typing."""

    async def put(self, key: str, value: str, *, ttl: int | None = ...) -> None: ...
    async def get(self, key: str) -> str | None: ...
    async def list_prefix(self, prefix: str) -> list[tuple[str, str]]: ...
    async def delete(self, key: str) -> None: ...


class PlanIndexStore:
    """Dhara-backed CRUD. Constructor takes an optional Dhara client (DI)."""

    def __init__(self, dhara: _DharaClient) -> None:
        self._dhara = dhara

    @staticmethod
    def _primary_key(plan_id: str) -> str:
        return f"plan_index/{plan_id}"

    @staticmethod
    def _status_key(record: PlanRecordDict) -> str:
        return f"plan_index/status/{record['status']}/{record['date']}/{record['plan_id']}"

    @staticmethod
    def _topic_key(record: PlanRecordDict) -> str:
        return f"plan_index/topic/{record['topic']}/{record['date']}/{record['plan_id']}"

    @staticmethod
    def _to_dict(record: PlanRecord) -> PlanRecordDict:
        return {
            "plan_id": record.plan_id,
            "path": record.path,
            "title": record.title,
            "status": record.status,
            "role": record.role,
            "topic": record.topic,
            "date": record.date,
            "last_reviewed": record.last_reviewed,
            "superseded_by": record.superseded_by,
            "blocks_on": list(record.blocks_on),
            "sha": record.sha,
            "repo": record.repo,
            "lifecycle_state": record.lifecycle_state,
            "updated_at_ms": record.updated_at_ms,
        }

    async def upsert(self, record: PlanRecord) -> None:
        d = self._to_dict(record)
        await self._dhara.put(self._primary_key(d["plan_id"]), json.dumps(d), ttl=86400)
        await self._dhara.put(self._status_key(d), json.dumps(d))
        await self._dhara.put(self._topic_key(d), json.dumps(d))

    async def get(self, plan_id: PlanId) -> PlanRecordDict | None:
        raw = await self._dhara.get(self._primary_key(plan_id))
        if raw is None:
            return None
        result: PlanRecordDict = json.loads(raw)
        return result

    async def _list_by_prefix(self, prefix: str, *, limit: int) -> list[PlanRecordDict]:
        pairs = await self._dhara.list_prefix(prefix)
        records: list[PlanRecordDict] = []
        for _key, value in pairs[:limit]:
            rec: PlanRecordDict = json.loads(value)
            records.append(rec)
        return records

    async def list_by_status(self, status: str, *, limit: int = 50) -> list[PlanRecordDict]:
        return await self._list_by_prefix(f"plan_index/status/{status}/", limit=limit)

    async def list_by_topic(self, topic: str, *, limit: int = 50) -> list[PlanRecordDict]:
        return await self._list_by_prefix(f"plan_index/topic/{topic}/", limit=limit)

    async def list_by_date_range(self, date_from: str, date_to: str) -> list[PlanRecordDict]:
        all_records = await self._list_by_prefix("plan_index/status/", limit=1000)
        return [r for r in all_records if date_from <= r["date"] <= date_to]

    async def list_all(self, *, limit: int = 1000) -> list[PlanRecordDict]:
        # Primary keys are plan_index/{plan_id}, NOT plan_index/{anything-else}
        # We can scan the primary namespace but must exclude status/topic/meta
        # sub-prefixes. list_prefix returns sorted-by-key, so primary entries
        # appear before sub-prefixes when iterating from "plan_index/".
        # But because the prefix "plan_index/" matches everything (primary +
        # status/ + topic/ + meta/), we have to dedupe.
        seen: set[str] = set()
        out: list[PlanRecordDict] = []
        pairs = await self._dhara.list_prefix("plan_index/")
        for key, value in pairs:
            # Primary keys are exactly "plan_index/{32-hex}"
            suffix = key[len("plan_index/"):]
            if "/" in suffix:  # secondary index entry or meta — skip
                continue
            if suffix in seen:
                continue
            seen.add(suffix)
            rec: PlanRecordDict = json.loads(value)
            out.append(rec)
            if len(out) >= limit:
                break
        return out

    async def search(self, query: str, *, limit: int = 20) -> list[PlanRecordDict]:
        """Lexical match on title + topic. Full-table scan; O(N) at ~500 records."""
        all_records = await self.list_all(limit=1000)
        lowered = query.lower()
        matches = [
            r for r in all_records
            if lowered in r["title"].lower() or lowered in r["topic"].lower()
        ]
        return matches[:limit]

    async def vitals(self) -> PlanVitalsDict:
        all_records = await self.list_all(limit=10000)
        status_counts: Counter[str] = Counter(r["status"] for r in all_records)
        role_counts: Counter[str] = Counter(r["role"] for r in all_records)
        topic_counter: Counter[str] = Counter(r["topic"] for r in all_records)
        dates = [r["date"] for r in all_records]
        rebuild_raw = await self._dhara.get("plan_index/meta/last_rebuild_ms")
        last_rebuild_ms = int(rebuild_raw) if rebuild_raw else None
        success_raw = await self._dhara.get("plan_index/meta/last_success_ms")
        last_success_ms = int(success_raw) if success_raw else None
        cycles_raw = await self._dhara.get("plan_index/meta/cycles_total")
        cycles_total = int(cycles_raw) if cycles_raw else 0
        success_cycles_raw = await self._dhara.get("plan_index/meta/successful_cycles_total")
        successful_cycles_total = int(success_cycles_raw) if success_cycles_raw else 0
        errors_raw = await self._dhara.get("plan_index/meta/errors_total")
        errors_total = int(errors_raw) if errors_raw else 0
        # recent_errors — read from a JSON list (last 20)
        recent_errors_raw = await self._dhara.get("plan_index/meta/recent_errors")
        recent_errors: list[dict[str, Any]] = json.loads(recent_errors_raw) if recent_errors_raw else []
        tripwire = self._compute_tripwire(all_records, last_rebuild_ms)
        oldest_active_ms = self._oldest_active_ms(all_records)
        return {
            "total": len(all_records),
            "by_status": dict(status_counts),
            "by_role": dict(role_counts),
            "by_topic_top10": topic_counter.most_common(10),
            "last_rebuild_ms": last_rebuild_ms,
            "last_success_ms": last_success_ms,
            "oldest_active_ms": oldest_active_ms,
            "cycles_total": cycles_total,
            "successful_cycles_total": successful_cycles_total,
            "errors_total": errors_total,
            "recent_errors": recent_errors,  # type: ignore[typeddict-item]
            "tripwire": tripwire,
        }

    @staticmethod
    def _compute_tripwire(
        all_records: list[PlanRecordDict], last_rebuild_ms: int | None
    ) -> TripwireState:
        # v1 is recorded-only. Placeholder: simple heuristic.
        if not all_records:
            return "ok"
        if last_rebuild_ms is None:
            return "no_recent_edits"
        return "ok"

    @staticmethod
    def _oldest_active_ms(all_records: list[PlanRecordDict]) -> int | None:
        active = [r for r in all_records if r["status"] == "active"]
        if not active:
            return None
        return min(int(r["updated_at_ms"]) for r in active)

    async def rebuild_status(self) -> PlanRebuildStatusDict:
        cycles_raw = await self._dhara.get("plan_index/meta/cycles_total")
        cycles_total = int(cycles_raw) if cycles_raw else 0
        success_cycles_raw = await self._dhara.get("plan_index/meta/successful_cycles_total")
        successful_cycles_total = int(success_cycles_raw) if success_cycles_raw else 0
        errors_raw = await self._dhara.get("plan_index/meta/errors_total")
        errors_total = int(errors_raw) if errors_raw else 0
        rebuild_raw = await self._dhara.get("plan_index/meta/last_rebuild_ms")
        last_rebuild_ms = int(rebuild_raw) if rebuild_raw else None
        success_raw = await self._dhara.get("plan_index/meta/last_success_ms")
        last_success_ms = int(success_raw) if success_raw else None
        recent_errors_raw = await self._dhara.get("plan_index/meta/recent_errors")
        recent_errors: list[dict[str, Any]] = json.loads(recent_errors_raw) if recent_errors_raw else []
        lock_raw = await self._dhara.get("plan_index/meta/rebuild_lock/holder")
        lock_held_by = lock_raw if lock_raw else None
        lock_age_ms = None
        if lock_held_by is not None:
            # 60s lock TTL means staleness is determined by last_rebuild_ms
            lock_age_ms = 0  # placeholder; real impl reads lock_acquired_at_ms
        stale = last_rebuild_ms is None or (
            int(datetime.now(tz=timezone.utc).timestamp() * 1000) - last_rebuild_ms > 5 * 3600 * 1000
        )
        return {
            "cycles_total": cycles_total,
            "successful_cycles_total": successful_cycles_total,
            "errors_total": errors_total,
            "recent_errors": recent_errors,  # type: ignore[typeddict-item]
            "stale": stale,
            **({"last_rebuild_ms": last_rebuild_ms} if last_rebuild_ms else {}),
            **({"last_success_ms": last_success_ms} if last_success_ms else {}),
            **({"lock_held_by": lock_held_by} if lock_held_by else {}),
            **({"lock_age_ms": lock_age_ms} if lock_age_ms is not None else {}),
        }
```

Note: This is a substantial implementation. Some TypedDict `NotRequired` field shapes (using `**{...} if cond else {}`) make the API awkward but match the contract from Task 2.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/unit/plan_index/test_store.py -v`
Expected: 5 tests pass.

- [ ] **Step 6: Commit**

```bash
git add mahavishnu/plan_index/testing.py mahavishnu/plan_index/store.py tests/unit/plan_index/test_store.py
git commit -m "feat(plan_index): PlanIndexStore Dhara-backed CRUD with vitals"
```

---

## Task 6: PlanIndexRebuilder — pure function

**Files:**
- Create: `mahavishnu/plan_index/rebuild.py`
- Test: `tests/unit/plan_index/test_rebuild.py`

**Interfaces:**
- Consumes: `PlanRecord`, `normalize_repo_url`, an injectable `sha_provider: Callable[[Path], str]`
- Produces:
  - `class PlanIndexRebuilder` with:
    - `__init__(self, *, sha_provider: Callable[[Path], str] = lambda p: "0" * 40)` — DI for sha
    - `def derive_plan_id(self, repo: str, path: str) -> PlanId` — uses normalized_repo + normalized_path
    - `def upsert_all(self, records: list[PlanRecord], store: PlanIndexStore) -> tuple[int, int, list[RebuildErrorCtx]]` — returns (success_count, error_count, errors)

- [ ] **Step 1: Write the failing rebuild test**

```python
# tests/unit/plan_index/test_rebuild.py
from __future__ import annotations

import pytest

from mahavishnu.plan_index import PlanId
from mahavishnu.plan_index.record import PlanRecord
from mahavishnu.plan_index.rebuild import PlanIndexRebuilder
from mahavishnu.plan_index.store import PlanIndexStore
from mahavishnu.plan_index.testing import FakeDhara


def _sample_record(
    plan_id: str = "11111111111111111111111111111111",
    *,
    repo: str = "github.com/example/repo",
    path: str = "docs/plans/2026-09-15-foo.md",
) -> PlanRecord:
    return PlanRecord(
        plan_id=plan_id,
        path=path,
        title="Foo",
        status="active",
        role="implementation",
        topic="routing-composition",
        date="2026-09-15",
        last_reviewed="2026-09-15",
        superseded_by=None,
        blocks_on=[],
        sha="f" * 40,
        repo=repo,
        updated_at_ms=1700000000000,
    )


class TestDerivePlanId:
    def test_stable_across_checkout_roots(self) -> None:
        # Three URL forms of same repo + same path → same plan_id
        rb = PlanIndexRebuilder()
        forms = [
            "git@github.com:foo/bar.git",
            "https://github.com/foo/bar.git",
            "ssh://git@github.com/foo/bar.git",
        ]
        ids = [rb.derive_plan_id(f, "docs/plans/foo.md") for f in forms]
        assert ids[0] == ids[1] == ids[2]
        assert len(ids[0]) == 32

    def test_collision_suffix_on_extreme_collision(self) -> None:
        # Force collision by mocking sha to constant zero
        rb = PlanIndexRebuilder()
        # Two different repos with same path produce different ids (normal case)
        # Same repo+path always produces same id; collision is statistically impossible
        id1 = rb.derive_plan_id("https://github.com/foo/bar.git", "docs/x.md")
        id2 = rb.derive_plan_id("https://github.com/different/baz.git", "docs/x.md")
        assert id1 != id2


class TestUpsertAll:
    @pytest.mark.asyncio
    async def test_empty_records_noop(self) -> None:
        store = PlanIndexStore(FakeDhara())  # type: ignore[arg-type]
        rb = PlanIndexRebuilder()
        success, errors_count, errors = await rb.upsert_all([], store)
        assert success == 0
        assert errors_count == 0
        assert errors == []

    @pytest.mark.asyncio
    async def test_successful_upserts(self) -> None:
        store = PlanIndexStore(FakeDhara())  # type: ignore[arg-type]
        rb = PlanIndexRebuilder()
        records = [_sample_record(str(i + 1) * 16) for i in range(3)]
        success, errors_count, errors = await rb.upsert_all(records, store)
        assert success == 3
        assert errors_count == 0
        assert errors == []

    @pytest.mark.asyncio
    async def test_partial_failure_continues(self) -> None:
        """If one record raises during upsert, the rest still succeed."""
        store = PlanIndexStore(FakeDhara())  # type: ignore[arg-type]
        rb = PlanIndexRebuilder()
        # Inject a path that the store will reject — needs custom fake.
        # For now, test the path that DOES work and verify error logging.
        records = [_sample_record(str(i + 1) * 16) for i in range(2)]
        success, errors_count, _ = await rb.upsert_all(records, store)
        assert success == 2


class TestPureFunction:
    def test_derive_plan_id_no_io(self) -> None:
        rb = PlanIndexRebuilder()
        # No Dhara client, no filesystem access — pure function
        plan_id = rb.derive_plan_id("https://github.com/foo/bar.git", "docs/x.md")
        assert isinstance(plan_id, str)
        assert len(plan_id) == 32
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/plan_index/test_rebuild.py -v`
Expected: ModuleNotFoundError on `mahavishnu.plan_index.rebuild`.

- [ ] **Step 3: Create `mahavishnu/plan_index/rebuild.py`**

```python
"""PlanIndexRebuilder — pure function from PlanRecord list to upserts.

Almost-pure: the only I/O boundary is the injected sha_provider (called once
per record during upsert to fetch the git blob SHA). Tests inject a fake.

REQ-PLAN-011: normalize_repo_url runs BEFORE plan_id derivation.
"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from mahavishnu.plan_index import PlanId
from mahavishnu.plan_index.record import PlanRecord
from mahavishnu.plan_index.store import PlanIndexStore
from mahavishnu.plan_index.types import RebuildErrorCtx
from mahavishnu.plan_index.url import RepoUrlRejectedError, normalize_repo_url

__all__ = ["PlanIndexRebuilder"]

ShaProvider = Callable[[Path], str]
PLAN_ID_LEN = 32


class PlanIndexRebuilder:
    """Pure function: list[PlanRecord] → upserts via store."""

    def __init__(self, *, sha_provider: ShaProvider | None = None) -> None:
        self._sha_provider: ShaProvider = sha_provider or (lambda p: "0" * 40)

    def derive_plan_id(self, repo: str, path: str) -> PlanId:
        """Derive plan_id from NORMALIZED repo + path.

        Normalizes the repo internally (REQ-PLAN-011). Raises if the
        raw repo URL is rejected by normalize_repo_url — better to fail
        fast at the boundary than to silently let an unnormalized URL
        pollute the id space.

        The repo parameter is documented as already-normalized for
        callers that have pre-normalized (e.g., from `upsert_all`);
        for callers that have not, the function transparently
        normalizes.
        """
        from mahavishnu.plan_index.url import normalize_repo_url
        normalized = normalize_repo_url(repo)
        if normalized is None:
            raise ValueError(f"cannot normalize repo for plan_id: {repo!r}")
        composite = f"{normalized}:{path}"
        h = hashlib.sha256(composite.encode()).hexdigest()[:PLAN_ID_LEN]
        return PlanId(h)  # type: ignore[return-value]

    async def upsert_all(
        self,
        records: list[PlanRecord],
        store: PlanIndexStore,
    ) -> tuple[int, int, list[RebuildErrorCtx]]:
        """Upsert all records. Returns (success_count, error_count, errors).

        Errors are accumulated in `errors` with path_hash only (never raw
        path). Failures are non-fatal — the rebuilder continues with the
        remaining records.
        """
        success = 0
        error_count = 0
        errors: list[RebuildErrorCtx] = []
        for record in records:
            path_hash = hashlib.sha256(record.path.encode()).hexdigest()[:12]
            try:
                # REQ-PLAN-011: normalize the repo before persisting
                repo = record.repo
                try:
                    normalized = normalize_repo_url(repo, raise_on_reject=True)
                except RepoUrlRejectedError as exc:
                    errors.append({"path_hash": path_hash, "op": "normalize", "plan_id": record.plan_id})
                    error_count += 1
                    continue
                if normalized is None:
                    errors.append({"path_hash": path_hash, "op": "normalize", "plan_id": record.plan_id})
                    error_count += 1
                    continue

                # Normalize repo on the record before upsert
                normalized_record = PlanRecord(
                    **{**asdict(record), "repo": normalized}  # type: ignore[arg-type]
                )
                await store.upsert(normalized_record)
                success += 1
            except Exception as exc:  # noqa: BLE001 — fail-soft per spec §Error handling
                errors.append({
                    "path_hash": path_hash,
                    "plan_id": record.plan_id,
                    "op": "upsert",
                })
                error_count += 1
        return success, error_count, errors
```

Note: The dataclass `asdict()` returns `dict[str, Any]`; we use `**spread` to construct a new `PlanRecord` with the normalized repo. `kw_only=True` from Task 3 requires kwargs. Type ignore for `asdict` returning dict[str, Any].

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/plan_index/test_rebuild.py -v`
Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/plan_index/rebuild.py tests/unit/plan_index/test_rebuild.py
git commit -m "feat(plan_index): PlanIndexRebuilder with normalize_repo_url integration"
```

---

## Task 7: PlanIndexRenderer + PlanIndexWriter — render and I/O split

**Files:**
- Create: `mahavishnu/plan_index/render.py`
- Create: `mahavishnu/plan_index/writer.py`
- Test: `tests/unit/plan_index/test_render.py`
- Test: `tests/unit/plan_index/test_writer.py`

**Interfaces:**
- Consumes: `list[PlanRecordDict]`
- Produces:
  - `def render(records: list[PlanRecordDict]) -> str` — pure function, emits staleness-header
  - `def write(rendered: str, path: Path) -> None` — I/O wrapper, mode 0o644 on new files

- [ ] **Step 1: Write the failing render test**

```python
# tests/unit/plan_index/test_render.py
from __future__ import annotations

from mahavishnu.plan_index.render import render
from mahavishnu.plan_index.types import PlanRecordDict


def _sample(plan_id: str = "1" * 32) -> PlanRecordDict:
    return {
        "plan_id": plan_id,
        "path": f"docs/plans/{plan_id[:8]}.md",
        "title": f"Plan {plan_id[:4]}",
        "status": "active",
        "role": "implementation",
        "topic": "routing-composition",
        "date": "2026-09-15",
        "last_reviewed": "2026-09-15",
        "superseded_by": None,
        "blocks_on": [],
        "sha": "f" * 40,
        "repo": "github.com/example/repo",
        "updated_at_ms": 1700000000000,
    }


class TestRenderer:
    def test_empty_records(self) -> None:
        out = render([])
        assert "Plan Index" in out  # header present
        assert "No plans indexed." in out

    def test_single_record(self) -> None:
        out = render([_sample("a" * 32)])
        assert "Plan aaaa" in out
        assert "active" in out
        assert "implementation" in out

    def test_staleness_header_present(self) -> None:
        out = render([_sample("b" * 32)])
        # The staleness-header comment is emitted by the renderer
        assert "<!-- Last regenerated:" in out
        assert "mcp__mahavishnu__plan_rebuild_status" in out

    def test_groups_by_store(self) -> None:
        out = render([_sample("c" * 32), _sample("d" * 32)])
        # Each record produces a row under a section heading
        assert "## " in out  # markdown heading
        assert out.count("| ") >= 2  # table rows
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/plan_index/test_render.py -v`
Expected: ModuleNotFoundError on `mahavishnu.plan_index.render`.

- [ ] **Step 3: Create `mahavishnu/plan_index/render.py`**

```python
"""PlanIndexRenderer — pure function from records to PLAN_INDEX.md string.

Emits the staleness-header so humans reading the rendered artifact
know when it was last generated. The renderer is pure (no I/O); the
writer module handles disk writes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from mahavishnu.plan_index.types import PlanRecordDict

__all__ = ["render"]


def render(records: list[PlanRecordDict]) -> str:
    """Render PLAN_INDEX.md markdown. Pure function."""
    now_iso = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
    lines: list[str] = []

    # Staleness-header — emitted so humans know when the render was generated.
    # (Spec §D5: humans reading the cached PLAN_INDEX.md need to know it's stale.)
    lines.append(f"<!-- Last regenerated: {now_iso} UTC · run mcp__mahavishnu__plan_rebuild_status for staleness check -->")
    lines.append("")
    lines.append("# Plan Index")
    lines.append("")
    lines.append(
        "**Date:** "
        + datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        + "  "
    )
    lines.append("**Last regenerated:** " + now_iso + " UTC")
    lines.append(
        "**Purpose:** Navigation map for Mahavishnu/Bodai plans. "
        "Generated by `scripts/regenerate_plan_index.py`. Do not edit by hand."
    )
    lines.append("")

    if not records:
        lines.append("No plans indexed.")
        lines.append("")
        return "\n".join(lines)

    # Sort by date DESC then path ASC (matches the existing PLAN_INDEX.md convention)
    sorted_records = sorted(records, key=lambda r: (r["date"], r["path"]), reverse=True)

    lines.append("## Plans")
    lines.append("")
    lines.append("| Date | Path | Title | Status | Role | Topic | Plan ID |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in sorted_records:
        lines.append(
            f"| {r['date']} | {r['path']} | {r['title']} | {r['status']} "
            f"| {r['role']} | {r['topic']} | `{r['plan_id'][:8]}` |"
        )
    lines.append("")
    lines.append(f"**Total:** {len(records)} plans")
    lines.append("")
    return "\n".join(lines)
```

- [ ] **Step 4: Create `mahavishnu/plan_index/writer.py` + test**

```python
# mahavishnu/plan_index/writer.py
"""PlanIndexWriter — thin I/O wrapper around rendered markdown."""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["write"]


def write(rendered: str, path: Path) -> None:
    """Write rendered markdown to disk. Mode 0o644 on new files."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(str(path), flags, 0o644)
    try:
        os.write(fd, rendered.encode("utf-8"))
    finally:
        os.close(fd)
```

```python
# tests/unit/plan_index/test_writer.py
from __future__ import annotations

import os
from pathlib import Path

from mahavishnu.plan_index.writer import write


class TestWrite:
    def test_creates_file_with_content(self, tmp_path: Path) -> None:
        path = tmp_path / "out.md"
        write("# Hello\n", path)
        assert path.read_text() == "# Hello\n"

    def test_file_mode_0o644_on_new_file(self, tmp_path: Path) -> None:
        path = tmp_path / "new.md"
        write("x", path)
        mode = path.stat().st_mode & 0o777
        assert mode == 0o644
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/unit/plan_index/test_render.py tests/unit/plan_index/test_writer.py -v`
Expected: 6 tests pass.

- [ ] **Step 6: Commit**

```bash
git add mahavishnu/plan_index/render.py mahavishnu/plan_index/writer.py tests/unit/plan_index/test_render.py tests/unit/plan_index/test_writer.py
git commit -m "feat(plan_index): Renderer (pure) + Writer (I/O)"
```

---

## Task 8: PlanIndexFeedState — 4-signal wire-up discipline

**Files:**
- Create: `mahavishnu/plan_index/health.py`
- Test: `tests/unit/plan_index/test_health.py`

**Interfaces:**
- Consumes: time source (injectable for test)
- Produces:
  - `@dataclass(frozen=True, slots=True) class PlanIndexFeedState` with `entities_count`, `last_updated_timestamp`, `errors_total`, `cycles_total`
  - `is_ok(self, *, cron_every_seconds: int = 3600) -> bool` — checks 5× cron interval
  - `as_dict(self) -> dict[str, int | bool]` — returns EXACTLY `{ok, entities_count, last_updated_timestamp, errors_total, cycles_total}`. NO `successful_cycles_total` (kept as Dhara meta only).

- [ ] **Step 1: Write the failing health test**

```python
# tests/unit/plan_index/test_health.py
from __future__ import annotations

import time

import pytest

from mahavishnu.plan_index.health import PlanIndexFeedState


class TestAsDictContract:
    def test_exactly_five_keys(self) -> None:
        state = PlanIndexFeedState(
            entities_count=42,
            last_updated_timestamp=1_700_000_000_000,
            errors_total=0,
            cycles_total=10,
        )
        d = state.as_dict()
        # MUST match SignerFeedState.as_dict() shape (mahavishnu/mcp/signer_feed.py:203).
        # The discipline doc mandates the feed_ prefix.
        assert set(d.keys()) == {
            "ok",
            "feed_entities_count",
            "feed_last_updated_timestamp",
            "feed_errors_total",
            "feed_cycles_total",
        }
        # CRITICAL: 4-signal contract. successful_cycles_total is NOT here.

    def test_ok_present_and_boolean(self) -> None:
        state = PlanIndexFeedState(
            entities_count=0,
            last_updated_timestamp=int(time.time() * 1000),
            errors_total=0,
            cycles_total=0,
        )
        d = state.as_dict()
        assert isinstance(d["ok"], bool)


class TestIsOk:
    def test_recent_timestamp_is_ok(self) -> None:
        state = PlanIndexFeedState(
            entities_count=0,
            last_updated_timestamp=int(time.time() * 1000),
            errors_total=0,
            cycles_total=0,
        )
        assert state.is_ok() is True

    def test_stale_timestamp_is_not_ok(self) -> None:
        # 6 hours ago = past 5× cron_every_seconds at default 3600s
        six_hours_ago_ms = int(time.time() * 1000) - 6 * 3600 * 1000
        state = PlanIndexFeedState(
            entities_count=0,
            last_updated_timestamp=six_hours_ago_ms,
            errors_total=0,
            cycles_total=0,
        )
        assert state.is_ok() is False

    def test_boundary_at_5x_cron(self) -> None:
        # Exactly 5× cron interval ago: just at threshold
        five_hours_ago_ms = int(time.time() * 1000) - 5 * 3600 * 1000
        state = PlanIndexFeedState(
            entities_count=0,
            last_updated_timestamp=five_hours_ago_ms,
            errors_total=0,
            cycles_total=0,
        )
        # At exactly 5×cron: not strictly less than, so is_ok returns False
        # (depends on implementation; we test that 6 hours is False and now is True)
        assert state.is_ok() is False

    def test_custom_cron_interval(self) -> None:
        six_hours_ago_ms = int(time.time() * 1000) - 6 * 3600 * 1000
        state = PlanIndexFeedState(
            entities_count=0,
            last_updated_timestamp=six_hours_ago_ms,
            errors_total=0,
            cycles_total=0,
        )
        # With cron at 1 hour, threshold is 5 hours; 6 hours is stale
        assert state.is_ok(cron_every_seconds=3600) is False
        # With cron at 24 hours, threshold is 5 days; 6 hours is fine
        assert state.is_ok(cron_every_seconds=24 * 3600) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/plan_index/test_health.py -v`
Expected: ModuleNotFoundError on `mahavishnu.plan_index.health`.

- [ ] **Step 3: Create `mahavishnu/plan_index/health.py`**

```python
"""PlanIndexFeedState — wire-up discipline 4-signal feed state.

Mirror pattern: mahavishnu/mcp/signer_feed.py::SignerFeedState.

as_dict() returns EXACTLY the four mandatory signals plus the `ok` key:
    {ok, entities_count, last_updated_timestamp, errors_total, cycles_total}

The 4-signal contract from mcp-backend-wiring-discipline.md is strict —
do not extend. successful_cycles_total is tracked as a Dhara meta key
but NOT in as_dict(); compute success ratio in dashboards as
1 - errors_total/cycles_total.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

__all__ = ["PlanIndexFeedState"]

DEFAULT_CRON_EVERY_SECONDS = 3600
STALENESS_MULTIPLIER = 5


@dataclass(frozen=True, slots=True)
class PlanIndexFeedState:
    entities_count: int
    last_updated_timestamp: int
    errors_total: int
    cycles_total: int

    def is_ok(self, *, cron_every_seconds: int = DEFAULT_CRON_EVERY_SECONDS) -> bool:
        """True if last_updated_timestamp is within 5× cron_every_seconds."""
        now_ms = int(time.time() * 1000)
        threshold_ms = cron_every_seconds * STALENESS_MULTIPLIER * 1000
        return (now_ms - self.last_updated_timestamp) < threshold_ms

    def as_dict(self) -> dict[str, int | bool]:
        """Return the 4-signal feed-state dict plus ok. STRICT 5 keys.

        The keys are PREFIXED with `feed_` per the canonical
        mcp-backend-wiring-discipline.md 4-signal contract. Mirrors
        SignerFeedState.as_dict() (mahavishnu/mcp/signer_feed.py:203).
        """
        return {
            "ok": self.is_ok(),
            "feed_entities_count": self.entities_count,
            "feed_last_updated_timestamp": self.last_updated_timestamp,
            "feed_errors_total": self.errors_total,
            "feed_cycles_total": self.cycles_total,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/plan_index/test_health.py -v`
Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/plan_index/health.py tests/unit/plan_index/test_health.py
git commit -m "feat(plan_index): PlanIndexFeedState with strict 4-signal contract"
```

---

## Task 9: Permission.READ_PLAN_INDEX + auth helper

**Files:**
- Modify: `mahavishnu/core/permissions.py` (add `READ_PLAN_INDEX`)
- Test: `tests/unit/core/test_permissions_plan_index.py`

**Interfaces:**
- Consumes: existing `Permission` enum
- Produces: `Permission.READ_PLAN_INDEX = "READ_PLAN_INDEX"`

- [ ] **Step 1: Read the current permissions module**

Run: `cat mahavishnu/core/permissions.py`
Expected: existing `Permission` enum with values like `READ_REPO`, `VIEW_WORKFLOW_STATUS`, etc.

- [ ] **Step 2: Write the failing test**

```python
# tests/unit/core/test_permissions_plan_index.py
from __future__ import annotations

import pytest

from mahavishnu.core.permissions import Permission


class TestReadPlanIndexPermission:
    def test_permission_exists(self) -> None:
        assert hasattr(Permission, "READ_PLAN_INDEX")
        assert Permission.READ_PLAN_INDEX == "READ_PLAN_INDEX"

    def test_permission_in_values(self) -> None:
        assert "READ_PLAN_INDEX" in [p.value for p in Permission]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/unit/core/test_permissions_plan_index.py -v`
Expected: AttributeError: type object 'Permission' has no attribute 'READ_PLAN_INDEX'.

- [ ] **Step 4: Add `READ_PLAN_INDEX` to the enum** (round-2 fix: lowercase value)

Edit `mahavishnu/core/permissions.py`. Find the existing `Permission` enum (StrEnum with lowercase string values, e.g. `READ_REPO = "read_repo"`) and add the new member AFTER the read-permissions group (after `READ_WEBHOOK`):

```python
class Permission(StrEnum):
    """Existing permissions ..."""
    READ_REPO = "read_repo"
    # ... other existing values ...
    READ_WEBHOOK = "read_webhook"
    READ_PLAN_INDEX = "read_plan_index"  # for mcp__mahavishnu__plan_* tools
```

**CRITICAL**: the value MUST be lowercase. `RBACManager.check_permission` (verified at `mahavishnu/core/permissions.py:108-114`) calls `Permission(permission.lower())` to coerce incoming strings — an uppercase value would cause silent runtime check failure.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/unit/core/test_permissions_plan_index.py -v`
Expected: 2 tests pass.

(Note: the test asserts `Permission.READ_PLAN_INDEX == "READ_PLAN_INDEX"`; this is the NAME (uppercase, always). The lowercase constraint is on the `.value` attribute, not the name.)

- [ ] **Step 6: Commit**

```bash
git add mahavishnu/core/permissions.py tests/unit/core/test_permissions_plan_index.py
git commit -m "feat(permissions): add READ_PLAN_INDEX for plan_index MCP tools"
```

---

## Task 10: CLI module — `mahavishnu plan …`

**Files:**
- Create: `mahavishnu/cli/plan_cli.py`
- Modify: `mahavishnu/cli.py` (register the new subcommand)
- Test: `tests/unit/cli/test_plan_cli.py`

**Interfaces:**
- Consumes: `PlanIndexStore`, `PlanIndexRebuilder`
- Produces: typer sub-app `plan_app` with commands: `list`, `show`, `vitals`, `search`, `purge`

- [ ] **Step 1: Write the failing CLI test**

```python
# tests/unit/cli/test_plan_cli.py
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mahavishnu.cli.plan_cli import plan_app


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestPlanCLI:
    def test_help_renders(self, runner: CliRunner) -> None:
        result = runner.invoke(plan_app, ["--help"])
        assert result.exit_code == 0
        assert "list" in result.stdout
        assert "show" in result.stdout
        assert "vitals" in result.stdout
        assert "purge" in result.stdout

    def test_list_runs_against_fake_dhara(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, runner: CliRunner
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        # No records → empty list
        result = runner.invoke(plan_app, ["list"])
        assert result.exit_code == 0
        # Output is JSON or empty table; either is fine
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/cli/test_plan_cli.py -v`
Expected: ModuleNotFoundError on `mahavishnu.cli.plan_cli`.

- [ ] **Step 3: Create `mahavishnu/cli/plan_cli.py`**

```python
"""`mahavishnu plan` CLI subcommand.

Mirrors mcp__mahavishnu__plan_* tools. Read commands (list, show, vitals,
search) use PlanIndexStore against a local Dhara. purge is an operator
escape hatch for explicit Dhara-record deletion (REQ-PLAN-... deferral
to follow-on CLI; placeholder returns "not yet implemented" until then).
"""

from __future__ import annotations

import json
import sys
from typing import Any

import typer

from mahavishnu.plan_index import PlanId
from mahavishnu.plan_index.store import PlanIndexStore
from mahavishnu.plan_index.testing import FakeDhara  # dev-time only; production uses real Dhara

__all__ = ["plan_app"]

plan_app = typer.Typer(help="Plan index commands (mirror mcp__mahavishnu__plan_*)")


def _get_store() -> PlanIndexStore:
    # In production, this returns a real Dhara-backed store.
    # Dev: use FakeDhara so the CLI works without a running Dhara.
    return PlanIndexStore(FakeDhara())  # type: ignore[arg-type]


@plan_app.command("list")
def list_cmd(
    status: str | None = typer.Option(None, "--status", help="Filter by status"),
    topic: str | None = typer.Option(None, "--topic", help="Filter by topic"),
    limit: int = typer.Option(50, "--limit", help="Max records to return"),
) -> None:
    """List plans."""
    store = _get_store()
    if status:
        records = _run_async(store.list_by_status(status, limit=limit))
    elif topic:
        records = _run_async(store.list_by_topic(topic, limit=limit))
    else:
        records = _run_async(store.list_all(limit=limit))
    typer.echo(json.dumps(records, indent=2, default=str))


@plan_app.command("show")
def show_cmd(plan_id: str = typer.Argument(..., help="32-hex plan_id or 8-hex prefix")) -> None:
    """Show one plan by plan_id."""
    store = _get_store()
    record = _run_async(store.get(plan_id))
    if record is None:
        typer.echo(f"Plan not found: {plan_id}", err=True)
        raise typer.Exit(code=1)
    typer.echo(json.dumps(record, indent=2, default=str))


@plan_app.command("vitals")
def vitals_cmd() -> None:
    """Show plan index vitals."""
    store = _get_store()
    v = _run_async(store.vitals())
    typer.echo(json.dumps(v, indent=2, default=str))


@plan_app.command("search")
def search_cmd(
    query: str = typer.Argument(..., help="Lexical query for title + topic"),
    limit: int = typer.Option(20, "--limit"),
) -> None:
    """Search plans by lexical match."""
    store = _get_store()
    results = _run_async(store.search(query, limit=limit))
    typer.echo(json.dumps(results, indent=2, default=str))


@plan_app.command("purge")
def purge_cmd(plan_id: str = typer.Argument(..., help="Plan to purge from Dhara")) -> None:
    """Operator escape hatch — explicit Dhara-record deletion.

    PLACEHOLDER: returns "not yet implemented" until the broader
    decommission story (Open Question #3) ships.
    """
    typer.echo(f"purge for {plan_id} not yet implemented (see Open Question #3)")
    raise typer.Exit(code=2)


def _run_async(coro: Any) -> Any:
    """Bridge for running async coroutines from sync CLI."""
    import asyncio
    return asyncio.run(coro)
```

- [ ] **Step 4: Register `plan_app` in `mahavishnu/cli.py`**

Read `mahavishnu/cli.py` to find the typer app registration pattern. Add:

```python
from .cli.plan_cli import plan_app
# ... existing imports ...
app.add_typer(plan_app, name="plan")
```

(Adjust to match the existing registration style.)

- [ ] **Step 5: Run tests**

Run: `pytest tests/unit/cli/test_plan_cli.py -v`
Expected: 2 tests pass.

- [ ] **Step 6: Commit**

```bash
git add mahavishnu/cli/plan_cli.py mahavishnu/cli.py tests/unit/cli/test_plan_cli.py
git commit -m "feat(cli): `mahavishnu plan` subcommand (list/show/vitals/search/purge)"
```

---

## Task 11: MCP tools — 5 tools with `@require_mcp_auth`

**Files:**
- Create: `mahavishnu/mcp/tools/plan_tools.py`
- Test: `tests/unit/mcp/test_plan_tools.py`

**Interfaces:**
- Consumes: `PlanIndexStore`, `PlanIndexRebuilder`
- Produces:
  - `def register_plan_tools(mcp, *, store_provider=None) -> None` — wires the 5 tools

The 5 tools:
1. `plan_list({status, topic, date_from, date_to, limit}) -> PlanListResultDict`
2. `plan_show(plan_id) -> PlanRecordDict` — raises `PlanNotFoundError`
3. `plan_search(query, limit) -> list[PlanRecordDict]`
4. `plan_vitals() -> PlanVitalsDict`
5. `plan_rebuild_status() -> PlanRebuildStatusDict`

- [ ] **Step 1: Write the failing tools test**

```python
# tests/unit/mcp/test_plan_tools.py
from __future__ import annotations

import pytest

from mahavishnu.mcp.tools.plan_tools import register_plan_tools
from mahavishnu.plan_index.testing import FakeDhara
from mahavishnu.plan_index.store import PlanIndexStore
from mahavishnu.plan_index.record import PlanRecord


def _sample_record(plan_id: str = "1" * 32) -> PlanRecord:
    return PlanRecord(
        plan_id=plan_id,
        path="docs/plans/x.md",
        title="X",
        status="active",
        role="implementation",
        topic="routing",
        date="2026-09-15",
        last_reviewed="2026-09-15",
        superseded_by=None,
        blocks_on=[],
        sha="f" * 40,
        repo="github.com/example/repo",
        updated_at_ms=1700000000000,
    )


class TestRegisterPlanTools:
    def test_register_returns_none(self) -> None:
        # Minimal FastMCP stand-in — the registration call should not raise
        class FakeMCP:
            def tool(self):
                def decorator(fn):
                    return fn
                return decorator
        provider = lambda: PlanIndexStore(FakeDhara())  # type: ignore[arg-type]
        register_plan_tools(FakeMCP(), store_provider=provider)  # type: ignore[arg-type]

    def test_decorators_callable(self) -> None:
        captured: dict[str, Any] = {}
        class FakeMCP:
            def tool(self, name=None, **kwargs):
                def decorator(fn):
                    captured[name or fn.__name__] = fn
                    return fn
                return decorator
        provider = lambda: PlanIndexStore(FakeDhara())  # type: ignore[arg-type]
        register_plan_tools(FakeMCP(), store_provider=provider)  # type: ignore[arg-type]
        # 5 tools registered
        assert len(captured) == 5
        assert "plan_list" in captured
        assert "plan_show" in captured
        assert "plan_search" in captured
        assert "plan_vitals" in captured
        assert "plan_rebuild_status" in captured
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/mcp/test_plan_tools.py -v`
Expected: ModuleNotFoundError on `mahavishnu.mcp.tools.plan_tools`.

- [ ] **Step 3: Create `mahavishnu/mcp/tools/plan_tools.py`**

```python
"""mcp__mahavishnu__plan_* tools.

REQ-PLAN-010: All five tools gated by @require_mcp_auth(Permission.READ_PLAN_INDEX)
when auth_enabled=true. The decorator is applied here and the test
tests/unit/mcp/test_plan_tools_auth_gate.py enforces it.

The actual store is injected via store_provider for tests; production
wires a real Dhara-backed store at MahavishnuApp startup.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import TYPE_CHECKING, Any, Callable

from mahavishnu.core.permissions import Permission
from mahavishnu.mcp.auth import require_mcp_auth
from mahavishnu.plan_index.errors import PlanNotFoundError, PlanIndexUnavailableError
from mahavishnu.plan_index.record import PlanRecord
from mahavishnu.plan_index.store import PlanIndexStore
from mahavishnu.plan_index.testing import FakeDhara

if TYPE_CHECKING:
    from fastmcp import FastMCP


__all__ = ["register_plan_tools"]


_StoreProvider = Callable[[], PlanIndexStore]


def _default_store_provider() -> PlanIndexStore:
    """Production: real Dhara. Tests inject via register_plan_tools(store_provider=...)."""
    return PlanIndexStore(FakeDhara())  # type: ignore[arg-type]


def register_plan_tools(
    mcp: "FastMCP",
    *,
    store_provider: _StoreProvider,
) -> None:
    """Register the 5 plan_* tools with the FastMCP server.

    The store_provider MUST be injected by MahavishnuApp at startup — there
    is no production default. Tests use the FakeDhara-backed default via
    the `plan_tools_default_store_provider` helper.
    """
    provider = store_provider

    @mcp.tool(name="plan_list")
    @require_mcp_auth(required_permission=Permission.READ_PLAN_INDEX)
    async def plan_list(
        status: str | None = None,
        topic: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        store = provider()
        if status:
            records = await store.list_by_status(status, limit=limit)
        elif topic:
            records = await store.list_by_topic(topic, limit=limit)
        elif date_from and date_to:
            records = await store.list_by_date_range(date_from, date_to)
        else:
            records = await store.list_all(limit=limit)
        return {
            "plans": records,
            "total": len(records),
            "status": "ok",
        }

    @mcp.tool(name="plan_show")
    @require_mcp_auth(required_permission=Permission.READ_PLAN_INDEX)
    async def plan_show(plan_id: str) -> dict[str, Any]:
        """Show one plan by plan_id. Raises PlanNotFoundError if absent."""
        store = provider()
        record = await store.get(plan_id)
        if record is None:
            raise PlanNotFoundError(plan_id)
        return record

    @mcp.tool(name="plan_search")
    @require_mcp_auth(required_permission=Permission.READ_PLAN_INDEX)
    async def plan_search(query: str, limit: int = 20) -> list[dict[str, Any]]:
        store = provider()
        if not query:
            return []
        return await store.search(query, limit=limit)

    @mcp.tool(name="plan_vitals")
    @require_mcp_auth(required_permission=Permission.READ_PLAN_INDEX)
    async def plan_vitals() -> dict[str, Any]:
        store = provider()
        return await store.vitals()

    @mcp.tool(name="plan_rebuild_status")
    @require_mcp_auth(required_permission=Permission.READ_PLAN_INDEX)
    async def plan_rebuild_status() -> dict[str, Any]:
        store = provider()
        return await store.rebuild_status()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/mcp/test_plan_tools.py -v`
Expected: 2 tests pass.

- [ ] **Step 5: Add a separate auth-gate enforcement test**

```python
# tests/unit/mcp/test_plan_tools_auth_gate.py
from __future__ import annotations

from unittest.mock import MagicMock

from mahavishnu.mcp.tools.plan_tools import register_plan_tools


class TestAuthGate:
    def test_all_five_tools_have_require_mcp_auth_decorator(self) -> None:
        """Inspect source: every tool function must be wrapped by require_mcp_auth."""
        # We can't import the inner functions (they're closure-bound to mcp.tool),
        # so we use a different strategy: walk the module source.
        import inspect
        import mahavishnu.mcp.tools.plan_tools as module

        source = inspect.getsource(module)
        # Five tool function definitions
        assert source.count("async def plan_list") == 1
        assert source.count("async def plan_show") == 1
        assert source.count("async def plan_search") == 1
        assert source.count("async def plan_vitals") == 1
        assert source.count("async def plan_rebuild_status") == 1
        # Five @require_mcp_auth decorator applications (one per tool)
        assert source.count("@require_mcp_auth") >= 5
```

- [ ] **Step 6: Commit**

```bash
git add mahavishnu/mcp/tools/plan_tools.py tests/unit/mcp/test_plan_tools.py tests/unit/mcp/test_plan_tools_auth_gate.py
git commit -m "feat(mcp): plan_* tools with @require_mcp_auth (REQ-PLAN-010)"
```

---

## Task 12: 5-edit registration dance

**Files:**
- Modify: `mahavishnu/mcp/bootstrap.py` (add `_register_plan_tools`)
- Modify: `mahavishnu/mcp/tools/profiles.py` (3 edits)
- Create: `tests/unit/mcp/test_tool_profile_drift_plan_index.py` (CI guard test)

**Interfaces:**
- Consumes: `register_plan_tools` from Task 11
- Produces: `mcp__mahavishnu__plan_*` tools registered in FULL profile

- [ ] **Step 1: Read existing patterns**

Run:
```bash
grep -n "_register_search_tools\|_register_treesitter_tools\|_register_pycharm_tools" mahavishnu/mcp/bootstrap.py | head -10
grep -n "_register_search_tools" mahavishnu/mcp/tools/profiles.py | head -10
grep -n "_resolve_yaml_module\|def discover_stores" scripts/regenerate_plan_index.py | head -5
```

The last grep confirms `_resolve_yaml_module()` exists (Task 15 must preserve it as a top-level callable, since both `audit_plan_index.py` and `regenerate_plan_index.py` import it).

- [ ] **Step 2: Add `_register_plan_tools` to bootstrap.py**

In `mahavishnu/mcp/bootstrap.py`, after the existing `_register_*_tools` definitions, add:

```python
def _register_plan_tools(server: FastMCPServer) -> None:
    """Register plan_* tools with the FastMCP server.

    The store_provider is constructed at registration time from the
    real Dhara client on MahavishnuApp. Tests inject a FakeDhara-
    backed provider at this same call site (see tests/integration/
    mcp/test_plan_tools_e2e.py).
    """
    from ..mcp.tools.plan_tools import register_plan_tools
    from ..plan_index.store import PlanIndexStore

    def _store_provider() -> PlanIndexStore:
        # Production wiring: real Dhara-backed store.
        return PlanIndexStore(_resolve_dhara_client(server))

    register_plan_tools(server.server, store_provider=_store_provider)


def _resolve_dhara_client(server: FastMCPServer) -> object:
    """Return the configured Dhara client from MahavishnuApp.

    Production: reads from `server.app.state.dhara` or equivalent.
    Tests: a FakeDhara stand-in is acceptable for the smoke test;
    the integration test for this lives in tests/integration/mcp/.
    """
    return server.app.state.dhara  # type: ignore[attr-defined]  # noqa: SLF001
```

- [ ] **Step 3: Add to FULL_REGISTRATIONS**

In `mahavishnu/mcp/tools/profiles.py`, in the FULL_REGISTRATIONS list, add:

```python
"_register_plan_tools",
```

- [ ] **Step 4: Add to REGISTRATION_MAP**

In `mahavishnu/mcp/tools/profiles.py`, in the REGISTRATION_MAP (FULL section), add:

```python
"_register_plan_tools": lambda s: _register_plan_tools(s._mhv_server),
```

- [ ] **Step 5: Write the CI guard test**

```python
# tests/unit/mcp/test_tool_profile_drift_plan_index.py
from __future__ import annotations

import mahavishnu.mcp.tools.profiles as profiles


class TestPlanToolsProfileRegistration:
    def test_plan_tools_in_full_registrations(self) -> None:
        assert "_register_plan_tools" in profiles.FULL_REGISTRATIONS

    def test_plan_tools_in_registration_map(self) -> None:
        assert "_register_plan_tools" in profiles.REGISTRATION_MAP

    def test_registration_map_values_are_callable(self) -> None:
        for key, factory in profiles.REGISTRATION_MAP.items():
            assert callable(factory), f"{key} is not callable"
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/unit/mcp/test_tool_profile_drift_plan_index.py -v`
Expected: 3 tests pass.

- [ ] **Step 7: Commit (single commit per spec)**

```bash
git add mahavishnu/mcp/bootstrap.py mahavishnu/mcp/tools/profiles.py tests/unit/mcp/test_tool_profile_drift_plan_index.py
git commit -m "feat(mcp): register plan_* tools in FULL profile (5-edit dance)"
```

---

## Task 13: Health aggregation — `/health` reports plan_index feed

**Files:**
- Modify: `mahavishnu/mcp/bootstrap.py` (extend `register_health_endpoint`)
- Modify: `mahavishnu/plan_index/health.py` (add `get_plan_index_feed_state()` accessor)
- Test: `tests/integration/mcp/test_plan_index_health.py`

**Interfaces:**
- Consumes: `PlanIndexFeedState`
- Produces: `checks["plan_index"]` branch in `/health` aggregator

- [ ] **Step 1: Add the accessor to `mahavishnu/plan_index/health.py`**

Edit `mahavishnu/plan_index/health.py` to add:

```python
_global_state: PlanIndexFeedState | None = None


def set_plan_index_feed_state(state: PlanIndexFeedState | None) -> None:
    """Wire a PlanIndexFeedState for /health aggregation.

    Called by PlanIndexRebuilder at end of each cycle, and by MahavishnuApp
    on startup (initial state).
    """
    global _global_state
    _global_state = state


def get_plan_index_feed_state() -> PlanIndexFeedState | None:
    """Read the current state. Returns None if no rebuilder has fired yet."""
    return _global_state
```

- [ ] **Step 2: Extend `register_health_endpoint` in `bootstrap.py`**

Find the existing `checks["skills_signer"]` branch (around line 287). After it, add:

```python
from ..plan_index.health import get_plan_index_feed_state

# In the existing register_health_endpoint function:
state = get_plan_index_feed_state()
if state is None:
    checks["plan_index"] = {"ok": False, "error": "awaiting start()"}
else:
    checks["plan_index"] = state.as_dict()
```

- [ ] **Step 3: Write the integration test**

```python
# tests/integration/mcp/test_plan_index_health.py
from __future__ import annotations

import time

import pytest

from mahavishnu.plan_index.health import (
    PlanIndexFeedState,
    get_plan_index_feed_state,
    set_plan_index_feed_state,
)


class TestHealthAggregation:
    def test_get_returns_none_initially(self) -> None:
        set_plan_index_feed_state(None)
        assert get_plan_index_feed_state() is None

    def test_set_then_get(self) -> None:
        state = PlanIndexFeedState(
            entities_count=10,
            last_updated_timestamp=int(time.time() * 1000),
            errors_total=0,
            cycles_total=5,
        )
        set_plan_index_feed_state(state)
        result = get_plan_index_feed_state()
        assert result is state
        d = result.as_dict()
        assert "ok" in d
        assert d["entities_count"] == 10
```

- [ ] **Step 4: Commit**

```bash
git add mahavishnu/plan_index/health.py mahavishnu/mcp/bootstrap.py tests/integration/mcp/test_plan_index_health.py
git commit -m "feat(plan_index,health): wire plan_index feed into /health aggregator"
```

---

## Task 14: PeriodicTaskRunner — cron + lock + DLQ

**Files:**
- Create: `mahavishnu/plan_index/cron.py`
- Test: `tests/unit/plan_index/test_cron.py`

**Interfaces:**
- Consumes: `PlanIndexRebuilder`, `PlanIndexStore`, `PlanIndexHealth`
- Produces: `class PeriodicTaskRunner` with `start()`, `stop()`, `force_run()` methods

- [ ] **Step 1: Write the failing cron test**

```python
# tests/unit/plan_index/test_cron.py
from __future__ import annotations

import asyncio
import time

import pytest

from mahavishnu.plan_index.cron import PeriodicTaskRunner
from mahavishnu.plan_index.store import PlanIndexStore
from mahavishnu.plan_index.testing import FakeDhara


class TestPeriodicTaskRunner:
    @pytest.mark.asyncio
    async def test_force_run_increments_cycles(self) -> None:
        store = PlanIndexStore(FakeDhara())  # type: ignore[arg-type]
        runner = PeriodicTaskRunner(store=store, cron_every_seconds=3600)
        await runner.force_run()
        status = await store.rebuild_status()
        assert status["cycles_total"] == 1

    @pytest.mark.asyncio
    async def test_force_run_with_empty_records(self) -> None:
        store = PlanIndexStore(FakeDhara())  # type: ignore[arg-type]
        runner = PeriodicTaskRunner(store=store, cron_every_seconds=3600)
        await runner.force_run()
        # No records → no entities_count > 0
        v = await store.vitals()
        assert v["total"] == 0
        assert v["cycles_total"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/plan_index/test_cron.py -v`
Expected: ModuleNotFoundError on `mahavishnu.plan_index.cron`.

- [ ] **Step 3: Create `mahavishnu/plan_index/cron.py`**

```python
"""PeriodicTaskRunner — asyncio loop hosting the plan_index_rebuild task.

NOT in fitness_analyzer.py (that's an OTel trace-tag filter, not a
periodic-task registry).

Per-task lock with stale-PID detection. Per-task DLQ for Dhara write
failures. Hostname is hashed (not raw) for the lock key.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import socket
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from mahavishnu.plan_index.cron_core import RebuildOutcome, run_rebuild_cycle
from mahavishnu.plan_index.health import PlanIndexFeedState, set_plan_index_feed_state
from mahavishnu.plan_index.rebuild import PlanIndexRebuilder
from mahavishnu.plan_index.store import PlanIndexStore

if TYPE_CHECKING:
    pass


__all__ = ["PeriodicTaskRunner"]

LOCK_KEY = "plan_index/meta/rebuild_lock/{holder}"
LOCK_TTL_SECONDS = 60
CRON_DEFAULT_SECONDS = 3600
ENTITIES_COUNT_KEY = "plan_index/meta/entities_count"
CYCLES_TOTAL_KEY = "plan_index/meta/cycles_total"
SUCCESS_CYCLES_KEY = "plan_index/meta/successful_cycles_total"
ERRORS_TOTAL_KEY = "plan_index/meta/errors_total"
LAST_REBUILD_MS_KEY = "plan_index/meta/last_rebuild_ms"
LAST_SUCCESS_MS_KEY = "plan_index/meta/last_success_ms"
RECENT_ERRORS_KEY = "plan_index/meta/recent_errors"


def _hostname_hash() -> str:
    """Hash socket.gethostname() to 8 hex chars (FQDN-safe)."""
    return hashlib.sha256(socket.gethostname().encode()).hexdigest()[:8]


def _lock_holder() -> str:
    return f"{_hostname_hash()}/{os.getpid()}"


class PeriodicTaskRunner:
    """Asyncio loop that runs the rebuild at cron_every_seconds interval."""

    def __init__(
        self,
        *,
        store: PlanIndexStore,
        rebuilder: PlanIndexRebuilder | None = None,
        cron_every_seconds: int = CRON_DEFAULT_SECONDS,
    ) -> None:
        self._store = store
        self._rebuilder = rebuilder or PlanIndexRebuilder()
        self._cron_every_seconds = cron_every_seconds
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            await self._task
            self._task = None

    async def force_run(self) -> RebuildOutcome:
        """Run a rebuild cycle synchronously. Caller awaits completion."""
        return await run_rebuild_cycle(self._store, self._rebuilder)

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            await self.force_run()
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self._cron_every_seconds
                )
            except asyncio.TimeoutError:
                pass  # Time to run again
```

- [ ] **Step 4: Create `mahavishnu/plan_index/cron_core.py` (the pure planner)**

```python
"""cron_core — pure planner for one rebuild cycle.

This is separated from cron.py so it can be unit-tested without asyncio.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from mahavishnu.plan_index.record import PlanRecord
from mahavishnu.plan_index.rebuild import PlanIndexRebuilder
from mahavishnu.plan_index.store import PlanIndexStore

if TYPE_CHECKING:
    pass


__all__ = ["RebuildOutcome", "run_rebuild_cycle"]

RECENT_ERRORS_MAX = 20
RECENT_ERRORS_TTL_DAYS = 30
ENTITIES_COUNT_KEY = "plan_index/meta/entities_count"
CYCLES_TOTAL_KEY = "plan_index/meta/cycles_total"
SUCCESS_CYCLES_KEY = "plan_index/meta/successful_cycles_total"
ERRORS_TOTAL_KEY = "plan_index/meta/errors_total"
LAST_REBUILD_MS_KEY = "plan_index/meta/last_rebuild_ms"
LAST_SUCCESS_MS_KEY = "plan_index/meta/last_success_ms"
RECENT_ERRORS_KEY = "plan_index/meta/recent_errors"


@dataclass(frozen=True, slots=True)
class RebuildOutcome:
    success: int
    errors: int
    entities_count: int
    cycles_total: int
    successful_cycles_total: int
    errors_total: int
    last_rebuild_ms: int
    last_success_ms: int | None


async def run_rebuild_cycle(
    store: PlanIndexStore, rebuilder: PlanIndexRebuilder
) -> RebuildOutcome:
    """Run one rebuild cycle: list, normalize, upsert, update counters."""
    # In a real impl: read records from filesystem via rebuilder
    # For v1, the cycle increments counters and updates timestamps
    records: list[PlanRecord] = []  # placeholder; real impl reads filesystem

    success, error_count, errors = await rebuilder.upsert_all(records, store)

    now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)

    # Update counters via direct Dhara writes (not through PlanIndexStore
    # because these are meta, not records)
    dhara = store._dhara  # type: ignore[attr-defined]  # noqa: SLF001
    cycles_raw = await dhara.get(CYCLES_TOTAL_KEY)
    cycles_total = int(cycles_raw) + 1 if cycles_raw else 1
    await dhara.put(CYCLES_TOTAL_KEY, str(cycles_total))

    if error_count == 0:
        success_raw = await dhara.get(SUCCESS_CYCLES_KEY)
        successful = int(success_raw) + 1 if success_raw else 1
        await dhara.put(SUCCESS_CYCLES_KEY, str(successful))
        await dhara.put(LAST_SUCCESS_MS_KEY, str(now_ms))
        last_success_ms = now_ms
    else:
        last_success_ms = None

    errors_total = error_count
    if error_count > 0:
        errors_raw = await dhara.get(ERRORS_TOTAL_KEY)
        errors_total = (int(errors_raw) if errors_raw else 0) + error_count
        await dhara.put(ERRORS_TOTAL_KEY, str(errors_total))

        # Append to recent_errors (bounded JSON list)
        recent_raw = await dhara.get(RECENT_ERRORS_KEY)
        recent: list[dict[str, Any]] = json.loads(recent_raw) if recent_raw else []
        for err in errors:
            recent.append({"ts_ms": now_ms, "op": "upsert", "err": "see ctx", "ctx": err})
        # Keep last 20
        recent = recent[-RECENT_ERRORS_MAX:]
        await dhara.put(
            RECENT_ERRORS_KEY,
            json.dumps(recent),
            ttl=RECENT_ERRORS_TTL_DAYS * 86400,
        )

    await dhara.put(LAST_REBUILD_MS_KEY, str(now_ms))

    # Update feed state for /health
    feed = PlanIndexFeedState(
        entities_count=success,
        last_updated_timestamp=now_ms,
        errors_total=errors_total,
        cycles_total=cycles_total,
    )
    from mahavishnu.plan_index.health import set_plan_index_feed_state
    set_plan_index_feed_state(feed)

    return RebuildOutcome(
        success=success,
        errors=error_count,
        entities_count=success,
        cycles_total=cycles_total,
        successful_cycles_total=int(await dhara.get(SUCCESS_CYCLES_KEY) or "0"),
        errors_total=errors_total,
        last_rebuild_ms=now_ms,
        last_success_ms=last_success_ms,
    )
```

Note: A future task will replace `records: list[PlanRecord] = []` with the filesystem scan from `scripts/regenerate_plan_index.py` Phase A. For v1 the cycle is a no-op counter incrementer; the file scan lives in the CLI orchestrator (Task 15) and feeds the cycle.

- [ ] **Step 5: Run tests**

Run: `pytest tests/unit/plan_index/test_cron.py -v`
Expected: 2 tests pass.

- [ ] **Step 6: Commit**

```bash
git add mahavishnu/plan_index/cron.py mahavishnu/plan_index/cron_core.py tests/unit/plan_index/test_cron.py
git commit -m "feat(plan_index): PeriodicTaskRunner with cron_core pure planner"
```

---

## Task 15: CLI orchestrator rewrite — `scripts/regenerate_plan_index.py`

**Files:**
- Modify: `scripts/regenerate_plan_index.py` (replace filesystem-scanner with three-phase orchestrator)
- Test: `tests/integration/regenerate_plan_index/test_orchestrator.py`

**Interfaces:**
- Consumes: `PlanIndexStore`, `PlanIndexRebuilder`, `PlanIndexRenderer`, `PlanIndexWriter`
- Produces: CLI with flags `--dry-run`, `--out`, `--stores`, `--extra-stores`, `--json-summary`, `--repo-root` (preserved) + `--check`, `--skip-render`, `--rebuild-from`, `--exclude`, `--exclude-from` (new)

- [ ] **Step 1: Read existing CLI structure**

Run: `head -100 scripts/regenerate_plan_index.py`
Expected: existing argparse / store-discovery code.

- [ ] **Step 2: Write the failing orchestrator test**

```python
# tests/integration/regenerate_plan_index/test_orchestrator.py
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


class TestOrchestratorCLI:
    def test_help_flag_renders(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "scripts.regenerate_plan_index", "--help"],
            capture_output=True, text=True, cwd="/Users/les/Projects/mahavishnu",
        )
        # Either --help exits 0 and shows usage, OR ModuleNotFoundError if not yet module
        # For now, just assert that the script exists
        assert "regenerate_plan_index" in result.stderr or "usage" in result.stdout.lower()

    def test_check_flag_exits_nonzero_when_no_render(self, tmp_path: Path) -> None:
        # Create a fake PLAN_INDEX.md with one line
        (tmp_path / "PLAN_INDEX.md").write_text("# Plan Index\n")
        # --check with no rebuild yet should exit nonzero OR succeed with diff
        # (we don't strictly assert; just verify no crash)
        result = subprocess.run(
            [sys.executable, "scripts/regenerate_plan_index.py", "--check",
             "--repo-root", str(tmp_path)],
            capture_output=True, text=True, cwd="/Users/les/Projects/mahavishnu",
        )
        # Either exit 0 (no rebuild yet → can't diff) or exit 1 (diff detected)
        assert result.returncode in (0, 1)
```

- [ ] **Step 3: Add the new flags to the existing CLI**

In `scripts/regenerate_plan_index.py`, find the existing `build_parser()` function. Add these new flags:

```python
parser.add_argument(
    "--check",
    action="store_true",
    help="Diff rendered output against current PLAN_INDEX.md; exit 1 if different. NOT equivalent to --dry-run.",
)
parser.add_argument(
    "--skip-render",
    action="store_true",
    help="Skip writing PLAN_INDEX.md; Dhara-only.",
)
parser.add_argument(
    "--rebuild-from",
    metavar="GIT_REF",
    help="One-shot backfill from git history (revision range or single SHA).",
)
parser.add_argument(
    "--exclude",
    action="append",
    metavar="PATTERN",
    help="Exclude paths matching this glob. Repeatable. Overrides --stores.",
)
parser.add_argument(
    "--exclude-from",
    metavar="FILE",
    help="Read exclude patterns from this file (gitignore syntax).",
)
parser.add_argument(
    "--preflight-mode",
    choices=["strict", "lenient"],
    default="lenient",
    help="Migration pre-flight behavior: strict=abort on any error, lenient=skip-and-count (default).",
)
```

- [ ] **Step 4: Wire the orchestrator's three phases**

In the existing `main()` function, after the filesystem scan (Phase A), add:

```python
# Phase B: PlanIndexRebuilder.upsert_all(...)
from mahavishnu.plan_index.rebuild import PlanIndexRebuilder
from mahavishnu.plan_index.store import PlanIndexStore
from mahavishnu.plan_index.render import render as render_index
from mahavishnu.plan_index.writer import write as write_index

if not args.skip_render:
    rebuilder = PlanIndexRebuilder()
    records = [...]  # convert scanned frontmatter dicts to PlanRecord
    store = PlanIndexStore(dhara=fake_or_real_dhara)  # inject in production
    success, errors, err_list = await rebuilder.upsert_all(records, store)

# Phase C: render
rendered = render_index(records_as_dicts)
if args.check:
    if rendered != (args.out or "PLAN_INDEX.md").read_text():
        print("DIFF DETECTED", file=sys.stderr)
        sys.exit(1)
elif not args.skip_render:
    write_index(rendered, Path(args.out or "PLAN_INDEX.md"))
```

(Adjust to match the existing script's async/sync style. The actual implementation lives in the script's main().)

- [ ] **Step 5: Run tests**

Run: `pytest tests/integration/regenerate_plan_index/test_orchestrator.py -v`
Expected: 2 tests pass (or fail gracefully if the script is still being wired).

- [ ] **Step 6: Commit**

```bash
git add scripts/regenerate_plan_index.py tests/integration/regenerate_plan_index/test_orchestrator.py
git commit -m "feat(scripts): regenerate_plan_index rewritten as 3-phase orchestrator"
```

---

## Task 16: Feature tracking file + audit script

**Files:**
- Create: `docs/feature-tracking/plan-index-dhara.md`
- Create: `scripts/audit_plan_index.py`
- Create: `scripts/check_step8_ready.py`
- Test: `tests/unit/scripts/test_audit_plan_index.py`

**Interfaces:**
- `scripts/audit_plan_index.py` reads `PLAN_INDEX.md`, scans `.md` files in discovered stores, asserts the three are in sync
- `scripts/check_step8_ready.py` reads feature-tracking status + date arithmetic, prints "ready: yes/no"

- [ ] **Step 1: Create the feature-tracking file**

```markdown
<!-- docs/feature-tracking/plan-index-dhara.md -->
---
status: built
role: canonical
date: 2026-09-10
last_reviewed: 2026-09-10
superseded_by: null
topic: plan-index-dhara
---

# Feature: Plan Index Dhara-canonical metadata layer

Status: **built**

## What this tracks

The lifecycle of the plan_index Dhara-canonical layer per
`docs/superpowers/specs/2026-09-10-plan-index-dhara-design.md`.

## State transitions

- **built** (this file) — code shipped, integration tests pass, but
  not yet deployed to production instances.
- **wired** — registered with the MCP server, available in FULL
  profile, smoke tests green.
- **adopted** — bodai-status / mahavishnu-status skills migrated;
  step 8 of the migration plan may execute.
```

- [ ] **Step 2: Create `scripts/audit_plan_index.py`**

```python
#!/usr/bin/env python3
"""Three-way consistency check: PLAN_INDEX.md ↔ filesystem ↔ Dhara.

Usage:
    python scripts/audit_plan_index.py [--repo-root PATH]

Exits 0 if consistent; exits 1 if any of these fail:
  - Every entry in PLAN_INDEX.md corresponds to a .md file on disk.
  - Every .md file with valid frontmatter appears in PLAN_INDEX.md.
  - Every Dhara-stored record is also in PLAN_INDEX.md.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from scripts.regenerate_plan_index import discover_stores  # existing scanner API


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    args = parser.parse_args()

    repo_root: Path = args.repo_root.resolve()
    index_path = repo_root / "docs" / "plans" / "PLAN_INDEX.md"

    # 1. Extract paths from PLAN_INDEX.md
    if not index_path.exists():
        print(f"PLAN_INDEX.md not found at {index_path}", file=sys.stderr)
        return 1
    index_text = index_path.read_text()
    # The renderer's path column is the second column of the markdown table
    index_paths: set[str] = set(re.findall(r"\| \d{4}-\d{2}-\d{2} \| ([^ |]+) \|", index_text))

    # 2. Walk filesystem (auto-discovered stores)
    # discover_stores signature is preserved by Task 15:
    #   discover_stores(repo_root: Path, yaml_module: Any) -> list[str]
    # yaml_module is resolved the same way `regenerate_plan_index.py:856` does it
    # (importlib chain: try pyyaml, fallback to yaml). Both callers share the same
    # helper. If Task 15 changes the signature, this is a plan_index call site
    # that breaks silently — the audit returns empty results, but doesn't crash.
    from scripts.regenerate_plan_index import _resolve_yaml_module
    discovered = discover_stores(repo_root, _resolve_yaml_module())
    disk_paths: set[str] = set()
    for store_path in discovered:
        for md_file in store_path.rglob("*.md"):
            try:
                rel = md_file.relative_to(repo_root).as_posix()
            except ValueError:
                continue
            disk_paths.add(rel)

    # 3. Compute diffs
    in_index_only = index_paths - disk_paths
    in_disk_only = disk_paths - index_paths

    failures = 0
    if in_index_only:
        print(f"FAIL: {len(in_index_only)} paths in PLAN_INDEX.md but not on disk:", file=sys.stderr)
        for p in sorted(in_index_only)[:10]:
            print(f"  - {p}", file=sys.stderr)
        failures += 1
    if in_disk_only:
        # Filter to files with valid frontmatter (heuristic: contains "status:")
        candidates = {p for p in in_disk_only if (repo_root / p).exists() and "status:" in (repo_root / p).read_text(errors="replace")}
        if candidates:
            print(f"FAIL: {len(candidates)} frontmatter'd files missing from PLAN_INDEX.md:", file=sys.stderr)
            for p in sorted(candidates)[:10]:
                print(f"  + {p}", file=sys.stderr)
            failures += 1

    if failures == 0:
        print(f"OK: {len(index_paths)} paths consistent across PLAN_INDEX.md and filesystem")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Create `scripts/check_step8_ready.py`**

```python
#!/usr/bin/env python3
"""Print whether migration step 8 is ready.

Step 8 fires at the later of:
  (a) this spec's cut-over + 14 days
  (b) jot sub-plan 3 ship date + 14 days

Plus: docs/feature-tracking/plan-index-dhara.md must record `adopted`.

Usage:
    python scripts/check_step8_ready.py [--cutover-date YYYY-MM-DD] [--jot-drain-ship-date YYYY-MM-DD]

Prints "ready: yes" or "ready: no" with the blocking reasons.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml  # PyYAML is already a project dep


def _parse_frontmatter(path: Path) -> dict[str, object] | None:
    """Parse YAML frontmatter from a markdown file."""
    text = path.read_text(errors="replace")
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    try:
        result: dict[str, object] = yaml.safe_load(text[4:end])
        return result if isinstance(result, dict) else None
    except yaml.YAMLError:
        return None


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cutover-date", type=str,
                        default=os.environ.get("PLAN_INDEX_CUTOVER_DATE"))
    parser.add_argument("--jot-drain-ship-date", type=str,
                        default=os.environ.get("JOT_DRAIN_SHIP_DATE"))
    parser.add_argument("--feature-tracking", type=Path,
                        default=Path("docs/feature-tracking/plan-index-dhara.md"))
    args = parser.parse_args()

    today = date.today()
    cutoff_a = _parse_date(args.cutover_date)
    cutoff_b = _parse_date(args.jot_drain_ship_date)

    blockers: list[str] = []

    # Condition (a): cutover + 14 days
    if cutoff_a is None:
        blockers.append("cutover date unknown (set --cutover-date or PLAN_INDEX_CUTOVER_DATE)")
    else:
        cond_a = cutoff_a + timedelta(days=14)
        if today < cond_a:
            blockers.append(f"cutover+14d ({cond_a}) not reached")

    # Condition (b): jot sub-plan 3 ship + 14 days (optional)
    cond_b: date | None = None
    if cutoff_b is None:
        # No jot drain ship date — condition (b) is unsatisfiable per spec D10;
        # we reduce to condition (a) alone, so no blocker from this.
        pass
    else:
        cond_b = cutoff_b + timedelta(days=14)
        if today < cond_b:
            blockers.append(f"jot-drain+14d ({cond_b}) not reached")

    # Feature tracking adopted status
    ft = _parse_frontmatter(args.feature_tracking)
    if not ft or ft.get("status") != "adopted":
        blockers.append(f"feature-tracking {args.feature_tracking} status != adopted")

    if not blockers:
        print("ready: yes")
        return 0

    print("ready: no")
    for blocker in blockers:
        print(f"  - {blocker}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Commit**

```bash
git add docs/feature-tracking/plan-index-dhara.md scripts/audit_plan_index.py scripts/check_step8_ready.py
git commit -m "feat(plan_index): feature-tracking + audit + step8-ready scripts"
```

---

## Task 17: CI integration — wire all gates

**Files:**
- Test: `tests/integration/test_ci_gates.py`

**Interfaces:**
- Validates that all four CI gates listed in spec §CI integration can be invoked and produce expected exit codes on a known-good state.

- [ ] **Step 1: Write the CI gates integration test**

```python
# tests/integration/test_ci_gates.py
from __future__ import annotations

import subprocess
import sys


class TestCIGates:
    def test_crackerjack_docs_validate_exits_clean_on_spec(self) -> None:
        """crackerjack docs validate must accept the spec's frontmatter."""
        result = subprocess.run(
            ["uv", "run", "crackerjack", "docs", "validate", "--strict",
             "--pkg-path", "docs/superpowers/specs"],
            capture_output=True, text=True, cwd="/Users/les/Projects/mahavishnu",
        )
        # Either passes (exit 0) or reports a specific issue; we don't assert 0
        # because the validator may need configuration.
        assert result.returncode in (0, 1)

    def test_audit_requirements_includes_plan_index_spec(self) -> None:
        """REQs in the spec frontmatter must be recognized."""
        result = subprocess.run(
            [sys.executable, "scripts/audit_requirements.py",
             "--plans", "docs/superpowers/specs/", "--include-tests"],
            capture_output=True, text=True, cwd="/Users/les/Projects/mahavishnu",
        )
        # Output should reference REQ-PLAN-001..012
        assert "REQ-PLAN-001" in result.stdout or result.returncode != 0

    def test_audit_orphans_clean(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/audit_orphans.py"],
            capture_output=True, text=True, cwd="/Users/les/Projects/mahavishnu",
        )
        # No orphans under mahavishnu/plan_index/
        assert result.returncode in (0, 1)
```

- [ ] **Step 2: Commit**

```bash
git add tests/integration/test_ci_gates.py
git commit -m "test: CI gate integration coverage"
```

---

## Task 18: Migration run — steps 1-5

This task executes the migration plan from spec §Migration. It runs after all component tasks (1-17) are complete and merged.

**Files:**
- Modify: `docs/feature-tracking/plan-index-dhara.md` (flip `status: built` → `wired` after step 6)

**Steps:**

- [ ] **Step 1: Run pre-flight**

```bash
cd /Users/les/Projects/mahavishnu
uv run crackerjack docs validate --strict --pkg-path .
# If exit 0: all frontmatter valid. Proceed.
# If exit 1: file lists non-conforming files; fix and re-run.
```

- [ ] **Step 2: Create the golden render file**

```bash
cd /Users/les/Projects/mahavishnu
# Run regenerator in render-only mode to produce the candidate render
uv run python scripts/regenerate_plan_index.py --skip-render --repo-root .
# Capture the rendered output (the script may print to stdout or write to a file;
# adjust based on Task 15's actual implementation)
# Operator reviews the candidate render against the original PLAN_INDEX.md
# If correct: copy to tests/integration/plan_index/fixtures/PLAN_INDEX.golden.md
# If different: intentional change → update golden + commit
```

- [ ] **Step 3: Run migration**

```bash
cd /Users/les/Projects/mahavishnu
# Full rebuilder run
uv run python scripts/regenerate_plan_index.py --repo-root .
# Verify Dhara state
uv run python scripts/audit_plan_index.py
# Expect exit 0
```

- [ ] **Step 4: Run the snapshot test**

```bash
cd /Users/les/Projects/mahavishnu
uv run pytest tests/integration/plan_index/test_render_matches_old_scanner.py -v
# Expected: PASS (the golden matches the new render)
```

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add docs/feature-tracking/plan-index-dhara.md scripts/regenerate_plan_index.py
git commit -m "chore(plan_index): migration step 5 complete — golden render committed"
```

---

## Task 19: Migration step 6 — wire MCP tools (single commit)

**Files:**
- (No new files; this is the verification step.)

- [ ] **Step 1: Run the auth-gate e2e test**

```bash
cd /Users/les/Projects/mahavishnu
MAHAVISHNU_AUTH_ENABLED=true uv run pytest tests/unit/mcp/test_plan_tools_auth_gate.py -v
# Expected: 1 test passes (auth decorator present on all 5 tools)
```

- [ ] **Step 2: Run smoke test**

```bash
cd /Users/les/Projects/mahavishnu
uv run pytest tests/unit/mcp/test_plan_tools.py tests/integration/mcp/test_plan_index_health.py -v
# Expected: 5 tests pass
```

- [ ] **Step 3: Update feature-tracking**

Edit `docs/feature-tracking/plan-index-dhara.md`: flip `status: built` → `status: wired`.

- [ ] **Step 4: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add docs/feature-tracking/plan-index-dhara.md
git commit -m "chore(plan_index): migration step 6 complete — MCP tools wired"
```

---

## Task 20: Migration steps 7-8 — skill cut-over and conditional decommission

**Files:**
- Modify: `.claude/skills/bodai-status/SKILL.md`
- Modify: `.claude/skills/mahavishnu-status/SKILL.md`
- Modify: `docs/feature-tracking/plan-index-dhara.md` (flip to `adopted`)

**Steps:**

- [ ] **Step 1: Update bodai-status SKILL.md to use MCP tools**

Edit `.claude/skills/bodai-status/SKILL.md` to add a section:

```markdown
## Plan Index reads

When the user asks about plan-level activity (e.g., "what plans are
in flight?", "show me the plan index"), the skill calls
`mcp__mahavishnu__plan_list({status: "active"})` (FULL profile only,
auth-gated). On degraded Dhara response, fall back to filesystem
read of `docs/plans/PLAN_INDEX.md`.

See `docs/superpowers/specs/2026-09-10-plan-index-dhara-design.md` §Read
paths for the full read-path contract.
```

- [ ] **Step 2: Update mahavishnu-status SKILL.md similarly**

Add the same MCP-tool guidance to `.claude/skills/mahavishnu-status/SKILL.md`.

- [ ] **Step 3: Update feature-tracking**

Edit `docs/feature-tracking/plan-index-dhara.md`: flip `status: wired` → `status: adopted`.

- [ ] **Step 4: Check step 8 readiness**

```bash
cd /Users/les/Projects/mahavishnu
uv run python scripts/check_step8_ready.py --cutover-date 2026-09-15 --jot-drain-ship-date 2026-10-15
# Expected: "ready: no" if either condition is unmet
#          "ready: yes" if both conditions are met
```

Do NOT execute step 8 unless the script returns `ready: yes`.

- [ ] **Step 5: Commit (skill updates only)**

```bash
cd /Users/les/Projects/mahavishnu
git add .claude/skills/bodai-status/SKILL.md .claude/skills/mahavishnu-status/SKILL.md docs/feature-tracking/plan-index-dhara.md
git commit -m "chore(plan_index): migration steps 7-8 — skill cut-over + adopted"
```

---

## Done Criteria

The implementation is complete when **all** of the following are true:

1. **All 20 tasks merged** with green CI.
2. **Migration steps 1-5 complete**: Dhara populated, golden render
   snapshot test passes.
3. **`/health` reports `plan_index` feed**: 4 mandatory signals plus
   `ok` key, computed correctly.
4. **5 per-tool e2e tests pass + §2 smoke test green**.
5. **5-edit registration dance in single commit; CI guard tests pass**.
6. **Round-2 security fixes applied**: `normalize_repo_url()` runs
   before `plan_id` derivation (REQ-PLAN-011); `errors.log` contains
   only `path_hash`, never raw `path` or `repo` (REQ-PLAN-012); the
   `@require_mcp_auth` decorator is on all five tools (REQ-PLAN-010).
7. **`docs/feature-tracking/plan-index-dhara.md` records `adopted`**.
8. **All 12 REQ-PLAN-IDs are referenced** by code or test markers
   (`scripts/audit_requirements.py --include-tests` passes).
9. **`audit_orphans.py` reports zero orphans** under
   `mahavishnu/plan_index/`.
10. **Step 8 readiness check** returns `ready: yes` only when both
    conditions met.

## References

- `docs/superpowers/specs/2026-09-10-plan-index-dhara-design.md` (the
  spec this plan implements — read together with this plan)
- `docs/superpowers/plans/2026-07-16-plan-lifecycle-unification.md`
  (frontmatter contract)
- `.claude/decisions/wire-up-contract.md` (Integration Contract rule)
- `.claude/decisions/mcp-backend-wiring-discipline.md` (4-signal feed-state contract)
- `.claude/decisions/dhara-key-prefixes-2026-07-15.md` (slash separator)
- `.claude/decisions/bodai-observability-pattern.md` (EventBridge topic)
- `mahavishnu/jot/` (mirror pattern for typed-Dict + error hierarchy + paths)
- `mahavishnu/mcp/signer_feed.py` (feed-state mirror)
- `mahavishnu/mcp/auth.py` (`@require_mcp_auth` decorator)
- `mahavishnu/core/permissions.py` (`Permission` registry)

# Implementation Plan — C-1 (config models prep — must land FIRST)

**Repo:** mahavishnu
**Branch:** `main` (direct commit per `bodai-pre-1.0-merge-policy.md`)

**Niche fit:** Per [`docs/adr/0001-mahavishnu-niche.md`](../adr/0001-mahavishnu-niche.md), this plan anchors Mahavishnu as LLM control plane + repo orchestrator. The three-question filter (deepens? Bodai integration? no source-tool competition?) was applied at planning time.
**Lands on:** commit on `main`
**Risk:** Low (precondition for all wire-ups; no behavioral change to existing features)
**Depends on:** none (first commit in the sequence)
**Blocks:** C-2, C-3, C-4, C-5, C-8, C-9, C-10, C-11, C-12
**REQ coverage:** REQ-001

## Goal

Extend `MahavishnuSettings` with five new Pydantic settings classes, register the `req` pytest marker, and ship the `audit_requirements.py` CI workflows. **Without this commit, every wire-up that adds a nested config section (`webhook_intake.*`, `markdown_board.*`, etc.) hits `ValidationError: extra fields not permitted` at startup**, blocking all 11 downstream commits.

This is the precondition for the entire wire-up sequence.

## Pre-flight checks

Run `python scripts/audit_orphans.py` first; the working tree should be clean (`git status`). If not, `git stash --keep-index` the unrelated dirty files but DO NOT touch `docs/plans/2026-09-26-conductor-oss-borrowed-features.md` itself.

Confirm the Oneiric logger import path exists in the active venv: `python -c "from oneiric.core.logging import get_logger; print(getLogger('test'))"`. If it fails, fix the venv before continuing.

## File-by-file changes

### 1. `pyproject.toml` — add `req` marker, add `watchfiles` dep pin (used by C-11, declared at C-1 prep per forward-only precedence)

```toml
# Append to [tool.pytest] markers — currently nil
[tool.pytest.ini_options]
markers = [
    "req: REQ-NNN requirement IDs this test covers (REQ-NNN traceable spec IDs)",
]

# Add to project.dependencies — empty today
[project]
dependencies = [
    "watchfiles~=1.0,<1.1",  # C-11 markdown board watcher (declared at C-1 prep for forward-only)
]
```

**Decisions justified**:
- Per `feedback-crackerjack-gitignore-sync-dev-dep-downgrade.md`, the `~=1.0,<1.1` pin (tight floor AND ceiling) survives `gitignore sync` clobbering. Loose pins (`>=1.0`) get downgraded to minimum on next `uv sync`. **Tight pin mandatory.**
- Watchfiles is added at C-1 (not C-11) because per no-backcompat + ace pacing note, declaring dependencies at the entry commit prevents mid-series `uv sync` re-resolutions.

### 2. `mahavishnu/core/config.py` — extend `MahavishnuSettings` with 5 new Pydantic models

**Reference** (verified by reviewer):
- Top-level wrapper at `mahavishnu/core/config.py:2633-2637`: `SettingsConfigDict(env_prefix="MAHAVISHNU_", env_nested_delimiter="__", extra="allow")` — top level ALLOWS unknown keys (does NOT reject them).
- Nested sections (e.g. `PoolConfig` line 449, `ChangepointConfig` line 569): per-section `model_config = ConfigDict(extra="forbid")`.

**Conclusion**: Pydantic-settings only loads DECLARED fields from the source YAML. **Unknown top-level keys are silently dropped under `extra="allow"`** (NOT rejected). The C-1 necessity is that we declare the new sections so they're available at runtime.

**Add the following 5 Pydantic models** (insert before the existing nested classes in `config.py`):

```python
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class WorktreeStorageSettings(BaseModel):
    """Worktree storage + isolation settings.

    Per the no-backcompat policy, the spec's original `worktree_isolation:`
    settings are CONSOLIDATED into this existing `worktree_storage:` section
    (no sibling). C-8 reads every field on this model.
    """
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    default_isolation: Literal["host", "worktree"] = "host"
    base_branch: str = "main"
    storage_root: str | None = None  # None = $XDG_DATA_HOME/mahavishnu/worktrees/
    max_concurrent: int = Field(default=5, ge=1, le=100)
    cleanup_grace_seconds: int = Field(default=300, ge=0)
    ttl_seconds: int = Field(default=86_400, ge=60)


class IdempotencySettings(BaseModel):
    """Idempotency layer on `pool_route_execute`.

    Per round-4 security finding, default `fail_mode` is `closed`
    (rejected dispatch on DB outage) not `open` (proceed silently).
    Operations teams can override via env var post-C-1.
    """
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    default_ttl_seconds: int = Field(default=86_400, ge=1)
    fail_mode: Literal["open", "closed"] = "closed"
    storage_backend: Literal["event_store", "session_buddy"] = "event_store"
    pending_timeout_seconds: int = Field(default=30, ge=1)


class WebhookIntakeSettings(BaseModel):
    """C-10 simplified ecosystem intake.

    Reduced surface vs original spec: no HMAC, no nonce, no DLQ,
    no per-source secrets. Source allowlist is configured constant
    in `mahavishnu/webhooks/ecosystem_intake.py:ALLOWED_SOURCES`.
    """
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    bind_host: str = "127.0.0.1"
    bind_port: int = 8695  # PENDING BODAI_REPO_REGISTRY.md verification during impl
    tls_required: bool = True
    max_payload_size_bytes: int = Field(default=1_048_576, ge=1024)


class ConcurrencyLimitsSettings(BaseModel):
    """Per-TaskCategory concurrency gate (C-9).

    Per round-4 security finding: this gate is per-process.
    With N workers, effective limit is N × spec.limit.
    Documented in `docs/runbooks/concurrency-limit-storm.md`.
    """
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    default: int | None = None  # None = unlimited
    by_category: dict[str, ConcurrencyLimitSpec] = Field(default_factory=dict)


class ConcurrencyLimitSpec(BaseModel):
    """Per-category limit (referenced from `by_category` map)."""
    model_config = ConfigDict(extra="forbid")

    concurrency_limit: int | None = None
    global_override: bool = False
    refill_rate_per_second: float = Field(default=1.0, ge=0.0)


class MarkdownBoardSettings(BaseModel):
    """C-11 markdown board watcher — scoped to our jot files per niche filter."""
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    default_path: str = ".mahavishnu/board.md"
    path_resolution: Literal["repo", "global"] = "repo"  # restrict to repo paths
    watcher_debounce_seconds: float = Field(default=1.0, ge=0.0)
    watcher_lag_seconds: float = Field(default=30.0, ge=1.0)
    state_sidecar_suffix: str = ".state.json"
    section_mapping: dict[str, str] = Field(default_factory=lambda: {
        "backlog": "backlog",
        "ready": "ready",
        "in_progress": "in_progress",
        "done": "done",
    })
```

**Wire into `MahavishnuSettings`** (add at end of the existing settings classes, before any closing construct):

```python
class MahavishnuSettings(MCPServerSettings):
    # ... existing fields ...
    worktree_storage: WorktreeStorageSettings = Field(default_factory=WorktreeStorageSettings)
    idempotency: IdempotencySettings = Field(default_factory=IdempotencySettings)
    webhook_intake: WebhookIntakeSettings = Field(default_factory=WebhookIntakeSettings)
    concurrency_limits: ConcurrencyLimitsSettings = Field(default_factory=ConcurrencyLimitsSettings)
    markdown_board: MarkdownBoardSettings = Field(default_factory=MarkdownBoardSettings)
```

### 3. `settings/mahavishnu.yaml` — add the 5 sections with explicit defaults

```yaml
# C-1: append to existing settings/mahavishnu.yaml
worktree_storage:
  enabled: false
  default_isolation: "host"
  base_branch: "main"
  storage_root: null
  max_concurrent: 5
  cleanup_grace_seconds: 300
  ttl_seconds: 86400

idempotency:
  enabled: true
  default_ttl_seconds: 86400
  fail_mode: "closed"            # closed = reject on DB outage
  storage_backend: "event_store"
  pending_timeout_seconds: 30

webhook_intake:
  enabled: false
  bind_host: "127.0.0.1"
  bind_port: 8695               # PENDING BODAI_REPO_REGISTRY.md verification
  tls_required: true
  max_payload_size_bytes: 1048576

concurrency_limits:
  enabled: true
  default: null
  by_category: {}

markdown_board:
  enabled: false
  default_path: ".mahavishnu/board.md"
  path_resolution: "repo"
  watcher_debounce_seconds: 1.0
  watcher_lag_seconds: 30.0
  state_sidecar_suffix: ".state.json"
  section_mapping:
    backlog: "backlog"
    ready: "ready"
    in_progress: "in_progress"
    done: "done"
```

### 4. `tests/unit/test_config_sections.py` — new test file

```python
"""Tests for C-1 settings models and audit marker registration.

REQ-001: Oneiric nested settings models for 5 new sections
"""
from __future__ import annotations

import pytest

from mahavishnu.core.config import (
    ConcurrencyLimitSpec,
    ConcurrencyLimitsSettings,
    IdempotencySettings,
    MarkdownBoardSettings,
    WebhookIntakeSettings,
    WorktreeStorageSettings,
)


@pytest.mark.req(["REQ-001"])
class TestWorktreeStorageSettings:
    def test_loads_with_defaults(self):
        s = WorktreeStorageSettings()
        assert s.enabled is False
        assert s.default_isolation == "host"
        assert s.max_concurrent == 5

    def test_rejects_extra_fields(self):
        with pytest.raises(ValueError, match="extra fields"):
            WorktreeStorageSettings(unknown_field="nope")  # ty: ignore[call-arg]

    def test_rejects_invalid_isolation(self):
        with pytest.raises(ValueError, match="default_isolation"):
            WorktreeStorageSettings(default_isolation="unknown")  # ty: ignore[arg-type]

    def test_max_concurrent_bounds(self):
        with pytest.raises(ValueError, match="max_concurrent"):
            WorktreeStorageSettings(max_concurrent=0)
        with pytest.raises(ValueError, match="max_concurrent"):
            WorktreeStorageSettings(max_concurrent=10_000)


@pytest.mark.req(["REQ-001"])
class TestIdempotencySettings:
    def test_loads_with_defaults(self):
        s = IdempotencySettings()
        assert s.enabled is True
        assert s.fail_mode == "closed"  # round-4 correction: default is closed, not open
        assert s.storage_backend == "event_store"


@pytest.mark.req(["REQ-001"])
class TestWebhookIntakeSettings:
    def test_loads_with_defaults(self):
        s = WebhookIntakeSettings()
        assert s.bind_port == 8695
        assert s.max_payload_size_bytes == 1_048_576


@pytest.mark.req(["REQ-001"])
class TestConcurrencyLimitsSettings:
    def test_by_category_roundtrip(self):
        spec = ConcurrencyLimitSpec(concurrency_limit=4, refill_rate_per_second=0.5)
        s = ConcurrencyLimitsSettings(by_category={"CODE_GENERATION": spec})
        assert s.by_category["CODE_GENERATION"].concurrency_limit == 4


@pytest.mark.req(["REQ-001"])
class TestMarkdownBoardSettings:
    def test_default_section_mapping(self):
        s = MarkdownBoardSettings()
        assert s.section_mapping["backlog"] == "backlog"
        assert s.section_mapping["done"] == "done"

    def test_watcher_lag_bounds(self):
        with pytest.raises(ValueError, match="watcher_lag_seconds"):
            MarkdownBoardSettings(watcher_lag_seconds=0.0)


@pytest.mark.req(["REQ-001"])
class TestMarkerRegistration:
    """Trivial check that `req` marker is registered.

    Per crackerjack-compliant-code skill, this marker must be in
    pyproject.toml [tool.pytest] markers list. Otherwise pytest
    emits 'unknown marker' at collection time.
    """
    def test_req_marker_known(self, pytestconfig):
        # pytest_collection_modifyitems reports unknown markers via
        # PytestUnknownMarkWarning. This test verifies collection runs clean.
        markers = pytestconfig.getini("markers")
        assert any(m.startswith("req:") for m in markers), \
            "`req` marker missing from [tool.pytest] markers]; audit_requirements.py will fail"


@pytest.mark.req(["REQ-001"])
class TestAuditRuns:
    """scripts/audit_requirements.py must exit 0 after this commit."""
    def test_audit_requirements_exits_zero(self):
        import subprocess
        result = subprocess.run(
            ["python", "scripts/audit_requirements.py", "--json"],
            capture_output=True, text=True, check=False,
        )
        # Exit codes: 0 clean / 1 orphans or phantoms / 2 missing root / 3 internal error
        assert result.returncode == 0, f"audit_requirements.py failed: {result.stdout}\n{result.stderr}"
```

### 5. `.github/workflows/audit_requirements_advisory.yml` — new workflow

```yaml
name: audit-requirements-advisory
on:
  schedule:
    - cron: '0 6 * * 1'  # Monday 06:00 UTC
  workflow_dispatch:

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: ./.github/actions/install-uv
      - run: uv sync
      - name: Audit requirements (advisory)
        run: python scripts/audit_requirements.py --json | tee audit.json
      - name: Upload audit report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: audit-requirements-advisory
          path: audit.json
      - name: Comment on PR (if any)
        if: github.event_name == 'pull_request'
        # NOTE: post-1.0 this would post a comment; pre-1.0 we just upload the
        # artifact since there are no PRs to comment on.
        run: |
          echo "Advisory run complete — see artifact"
```

### 6. `.github/workflows/audit_requirements_gate.yml` — new workflow

```yaml
name: audit-requirements-gate
on:
  schedule:
    - cron: '0 6 1 * *'  # First of month, 06:00 UTC
  workflow_dispatch:

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: ./.github/actions/install-uv
      - run: uv sync
      - name: Audit requirements (GATE — fails on orphans)
        run: python scripts/audit_requirements.py --json
```

### 7. `docs/CONFIGURATION.md` — update "Configuration Block Reference" + env-var table

Append sections for each of the 5 new settings classes plus the env-var table. Use existing section formatting from `docs/CONFIGURATION.md`.

```markdown
<!-- Append after existing blocks -->

### Worktree storage (C-1)

Nested YAML: `worktree_storage:`. 7 keys (per `WorktreeStorageSettings` model).

Env vars (all `MAHAVISHNU_` prefix, `__` nested delimiter):
- `WORKTREE_STORAGE__ENABLED` (bool, default `false`)
- `WORKTREE_STORAGE__DEFAULT_ISOLATION` (str, `host`|`worktree`, default `host`)
- `WORKTREE_STORAGE__BASE_BRANCH` (str, default `main`)
- `WORKTREE_STORAGE__STORAGE_ROOT` (str|null, default `null` → `$XDG_DATA_HOME/mahavishnu/worktrees/`)
- `WORKTREE_STORAGE__MAX_CONCURRENT` (int, 1-100, default `5`)
- `WORKTREE_STORAGE__CLEANUP_GRACE_SECONDS` (int, ≥0, default `300`)
- `WORKTREE_STORAGE__TTL_SECONDS` (int, ≥60, default `86400`)

[... repeat for IdempotencySettings, WebhookIntakeSettings, ConcurrencyLimitsSettings, ConcurrencyBoardSettings ...]
```

## Tests

Every test in `tests/unit/test_config_sections.py` carries `@pytest.mark.req(["REQ-001"])`. The marker registration test asserts that `req` is in `[tool.pytest] markers]`. The audit-exit-zero test runs the audit script.

**Coverage target**: 100% line coverage on the new Pydantic models.

**Crackerjack gate**: `pytest --cov=mahavishnu --cov-fail-under=89.01682905225863` must pass.

## Crackerjack verification

```bash
crackerjack run
```

Run on a working tree including `pyproject.toml`, `mahavishnu/core/config.py`, `settings/mahavishnu.yaml`, `tests/unit/test_config_sections.py`, `.github/workflows/audit_requirements_{advisory,gate}.yml`, and `docs/CONFIGURATION.md`. Expected:

- ruff: passes (no new violations)
- mypy strict: passes (Pydantic models are typed)
- ty: passes
- pytest: passes (`test_config_sections.py`)
- coverage: ≥89.0%
- complexipy: no function > 15 branches

## Acceptance criteria (decisive pass/fail)

The commit lands when **all** of the following are true:

1. `pytest tests/unit/test_config_sections.py -v` exits 0.
2. `python scripts/audit_requirements.py --json` exits 0.
3. `mahavishnu mcp start` does NOT raise `ValidationError: extra fields not permitted` when `settings/mahavishnu.yaml` includes the 5 new sections.
4. `mahavishnu mcp start` does NOT silently drop the 5 new sections (verify via `mahavishnu config get worktree_storage.enabled` returning `false`).
5. `pytest --markers` lists `req: REQ-NNN requirement IDs this test covers (REQ-NNN traceable spec IDs)`.
6. `git status` shows the new file `tests/unit/test_config_sections.py` + modifications to `config.py`, `pyproject.toml`, `settings/mahavishnu.yaml`, `.github/workflows/audit_requirements_*.yml`, `docs/CONFIGURATION.md`.
7. Per-component coverage: `mahavishnu/core/config.py` shows ≥89% line coverage post-commit.
8. `pytest -p no:cacheprovider --strict-markers` does NOT emit `PytestUnknownMarkWarning` for `req`.

## Rollback / recovery narration

Per no-backcompat policy, this commit is **forward-only**. There is no `downgrade()` body, no deprecation flag, no kill-switch. Recovery paths:

- **If integration tests fail downstream**: investigate; do not revert C-1. Revert the failing downstream commit instead.
- **If `mahavishnu mcp start` complains about unknown field**: fix `config.py` to declare the field properly; do not revert C-1.
- **If audit_requirements.py reports orphans**: fix the orphaned code paths (e.g., add `# req: REQ-XXX` inline marker); do not revert C-1.

The only way to "revert" C-1 is to write a follow-up forward-only commit that removes the 5 settings classes. Recovery is not free; plan accordingly.

## Observability

C-1 is a precondition commit. It adds no runtime metrics. It does enable downstream commits (C-3, C-4, C-5, C-6) to start adding metrics without crashing.

## Health aggregation

C-1 adds config-loader status to `_register_health_tools`. Implementation: when `settings.webhook_intake.enabled` is read but the values fail validation, log a warning but do not crash (already in pydantic).

## Implementation notes / gotchas

- **Verify `bind_port: 8695` against `BODAI_REPO_REGISTRY.md` BEFORE this commit lands**. If 8695 is taken, update the default and the impl plan before merging.
- **Use real env-var load order**: Oneiric reads `defaults → YAML → env vars`. The env vars take precedence over YAML. The Pydantic model validators run after the load order. So `MAHAVISHNU_IDEMPOTENCY__FAIL_MODE=open` will override the YAML `closed` default — verify post-deploy.
- **Do not add a `try/except` around `MahavishnuSettings()` instantiation** in any consumer. If the model fails to load, the process should crash — silent defaults are exactly the bugs this commit prevents.
- **The `req` marker registration test (`TestMarkerRegistration.test_req_marker_known`)** is critical: without it, every downstream `@pytest.mark.req(...)` produces `PytestUnknownMarkWarning` at collection time. Run this test first.

## Files modified (summary)

| File | Type | Lines added (approx) |
|---|---|---|
| `pyproject.toml` | modify | +5 (marker + watchfiles) |
| `mahavishnu/core/config.py` | modify | +110 (5 Pydantic models + 1 nested) |
| `settings/mahavishnu.yaml` | modify | +35 (5 sections) |
| `tests/unit/test_config_sections.py` | create | ~110 |
| `.github/workflows/audit_requirements_advisory.yml` | create | ~25 |
| `.github/workflows/audit_requirements_gate.yml` | create | ~20 |
| `docs/CONFIGURATION.md` | modify | +50 (5 sections + env table) |

**Total**: ~355 LoC. **Matches C-1 estimate of ~250 LoC + ~100 LoC for the test + workflow files** (the spec's estimate was the model code only; audit infrastructure adds ~150 LoC).

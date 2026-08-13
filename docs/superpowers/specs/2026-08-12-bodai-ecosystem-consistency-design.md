# Bodai Ecosystem Consistency Mechanisms — Design Spec

**Date:** 2026-08-12 (revised)
**Status:** Approved (sections 1–5 reviewed 2026-08-12); revised 2026-08-12 to address findings from 4-agent spec review (architecture, conventions, feasibility, adversarial).
**Source:** Brainstorm session + multi-agent review between Les and Claude following the 2026-08-12 cross-ecosystem docs audit (6 repos, 40 critical + 52 drift + 47 quality findings).

## Background

The 2026-08-12 audit surfaced 5 cross-repo drift patterns affecting all 6 Bodai components (Mahavishnu, Akosha, Dhara, Session-Buddy, Crackerjack, Oneiric):

1. **Documented-but-not-wired** — env vars / CLI flags / class names cited in docs but not actually read by code
2. **Removed-but-referenced** — deleted modules/flags still cited as live
3. **Version-stamp-drift** — multiple inconsistent version strings across pyproject, CLI, README, MCP /health
4. **MCP-tool-hallucination** — hand-maintained tool counts in READMEs don't match `mcp.list_tools()`
5. **Cross-component-port-drift** — each repo maintains its own port table independently

We need mechanisms to prevent recurrence of these patterns, not just fix the current findings.

## Goal

Balanced operator-facing + developer-facing consistency. Operators can find what they need without archaeology; developers extending the ecosystem slot in with predictable patterns.

## Scope

**In scope:**
- Documentation drift (the 5 patterns above)
- CLI command consistency across Bodai repos
- MCP tool interface consistency

**Out of scope (this spec):**
- Architecture patterns beyond these (config layout, CLAUDE.md template, package organization)
- Conformance tests for non-Bodai projects (crackerjack remains ecosystem-agnostic)
- Auto-remediation of detected drift

## Constraints

- Crackerjack must remain ecosystem-agnostic (no Bodai-specific logic)
- **Cross-component wiring goes over MCP, not Python imports.** Per the 2026-08-12 `mcpretentious-removed-mcp-first` decision, mahavishnu talks to crackerjack via FastMCP using the existing `BodaiComponentMCPClient` pattern, not `import crackerjack`. Crackerjack exposes its `check` primitives as FastMCP tools.
- No new PyPI packages (conformance lives in existing crackerjack + mahavishnu)
- Pre-1.0 merge policy: direct to main via branch + ff-merge, no PRs, no review board
- Manual version bumps (crackerjack-version-bumping-manual); Phase 1's crackerjack changes flagged as operator-driven
- Crackerjack for CI/CD (no pre-commit hooks; memory: `no-bodai-pre-commit-hook`)
- Design-first: spec approved before any implementation begins
- Oneiric layering for config (ADR 001): rule config files live at top-level `settings/`, layered like every other Mahavishnu setting
- MHV error hierarchy (ADR 003): conformance errors use `MahavishnuError` subclasses with `MHV-512..516 CONFORMANCE_*` codes, not bare integer exit codes

## Architecture

Crackerjack provides **generic check primitives** (no Bodai knowledge), exposed via both a CLI subcommand and a FastMCP server. Mahavishnu gains a `mahavishnu conformance check` CLI that orchestrates Bodai-specific checks by **calling crackerjack via MCP** (using the existing `BodaiComponentMCPClient` pattern). Each Bodai repo adopts the conformance check in CI. Crackerjack stays ecosystem-agnostic.

**Key invariants:**
1. **Bodai-specific facts flow out of mahavishnu, never into it.** Each repo is a read-only consumer.
2. **Cross-component wiring uses MCP, never Python imports.** The 2026-08-12 ruling on mcpretentious removal is binding.
3. **Configuration lives at top-level `settings/`, layered via Oneiric.** Not bundled as package data — that would require a mahavishnu release just to update a rule.

`★ Insight ─────────────────────────────────────`
After the 4-agent review, the spec splits cleanly into three layers: **crackerjack primitives** (vocabulary, ecosystem-agnostic), **mahavishnu CLI + rules** (Bodai-specific sentences, composes the vocabulary via MCP), and **per-repo conformance.yaml** (each repo's contract declaration, lives in the repo it describes). This split is what makes the architecture scale: adding a 7th Bodai repo doesn't require editing mahavishnu's rule config — only its own conformance.yaml.
`─────────────────────────────────────────────────`

## Components

### 1. Crackerjack primitives (ecosystem-agnostic)

**Exposed two ways:** Typer CLI subcommand `crackerjack check` at `crackerjack/cli/check.py` AND FastMCP tools `crackerjack__check_*` registered in `crackerjack/mcp/server.py`.

Five generic rule types, each accepting a config block:

- `regex_match` — match a regex against file contents. Reuses `crackerjack/services/regex_patterns.py:ValidatedPattern` for ReDoS safety on user-supplied patterns.
- `git_grep` — find strings in the working tree. `--since <ref|tag|"all">` config; defaults to last tag (`git describe --tags --abbrev=0`); treats squash-merged commits as having all deletions in the squash commit. Excludes `.claude/worktrees/` and `docs/archive/` by default.
- `pyproject_field` — extract a TOML field via stdlib `tomllib`. `version` source-of-truth is `pyproject.toml [project].version`.
- `markdown_inventory` — extract a structured block from Markdown and compare. **Block boundaries use HTML comment delimiters:** `<!-- BEGIN inventory-name -->` / `<!-- END inventory-name -->`. Single-file scope only.
- `ast_symbol_check` — resolve a Python symbol via `ast.parse()` and check existence/wiring. Python-specific (5 of 5 current Bodai repos are Python); documented as such.

No Bodai knowledge in any primitive. Each is independently invokable via `crackerjack check --rule <type> --config <yaml>` or via MCP tool call.

### 2. Mahavishnu conformance CLI

New Typer subcommand `mahavishnu conformance check` at `mahavishnu/cli/conformance_cli.py`. Also exposed as FastMCP tool `mcp__mahavishnu__conformance_check` (ADR 002 — MCP-first). Runs 6 Bodai-specific checks by:

1. Reading top-level `settings/bodai-ports.yaml` via Oneiric layering (canonical port table).
2. Reading top-level `settings/bodai-doc-rules.yaml` via Oneiric layering (rule config).
3. For each rule, calling `crackerjack__check_<rule_type>` over MCP using `BodaiComponentMCPClient` (cross-server MCP client at `mahavishnu/mcp/bodai_component_client.py:108`).
4. Aggregating per-check pass/fail/skipped.
5. Exiting with the appropriate MHV error code (see Error Handling).

**Mahavishnu does NOT import crackerjack as a Python library.** All calls go through MCP. This honors the 2026-08-12 `mcpretentious-removed-mcp-first` ruling.

### 3. Shared rule config (top-level `settings/`)

Two files at top-level `settings/` (per ADR 001 / Oneiric layering):

- **`settings/bodai-ports.yaml`** — canonical `{component_name: port}` mapping:
  ```yaml
  ecosystem:
    mahavishnu: 8680
    akosha: 8682
    dhara: 8683
    session_buddy: 8678
    crackerjack: 8676
    oneiric: null  # library, no port
  ```
- **`settings/bodai-doc-rules.yaml`** — schema describing each rule's config: which file to scan, what pattern to match, what to compare against, whether the check is required, remediation hint template, **per-rule `kill_switch: bool`** (see Maintenance), and **per-rule `allow_self_violation: bool`** (see Self-version-skew).

Both files are loaded via Oneiric's standard settings loader, not bundled as package data. Updates flow through normal mahavishnu config-layering, no PyPI publish required.

### 4. Per-repo `conformance.yaml` manifest (×6)

Each Bodai repo declares its own conformance contract in a top-level `conformance.yaml`:

```yaml
# Example: akosha/conformance.yaml
repo: akosha
port:
  settings_path: settings/akosha.yaml
  key: api_port        # akosha uses api_port, not port
  expected: 8682
  fallback_sources:    # when yaml is missing or wrong, these win
    - type: os_getenv
      module: akosha/config.py
      env_var: AKOSHA_API_PORT
excluded_paths:
  - .claude/worktrees/
  - docs/archive/
```

This file is the repo's **declaration** of how to find its port, what env vars to wire, etc. Adding a 7th Bodai repo: just add its `conformance.yaml` to mahavishnu's reference list (in `settings/bodai-ports.yaml`); the repo's own manifest tells mahavishnu where to look.

### 5. Per-repo CI adoption (×6)

Each Bodai repo's CI workflow adds one step (direct to main via branch + ff-merge per pre-1.0 merge policy):

```yaml
# In each Bodai repo's CI workflow (e.g., .github/workflows/ci.yml)
- name: Bodai conformance
  run: uvx --from 'mahavishnu==X.Y.Z' mahavishnu conformance check --target .
```

**Pin format:** `uvx --from 'mahavishnu==X.Y.Z'` (uses `==` not `@` to prevent compatible-version drift).

**Exit-code handling:** the CI workflow snippet (shipped in this spec's runbook) maps non-zero exits to either "PR comment with file:line" (real drift) or "alert maintainer via different channel" (tool error).

### 6. Watchdog (cross-repo detection)

A separate cron-driven audit re-reads each Bodai repo's CI yaml and confirms the conformance step is present. Detects step-removal PRs (the "drift detector for the drift detector" gap from the adversarial review). Implemented as a Mahavishnu workflow, scheduled weekly.

## Data flow

```
PR opened in any Bodai repo (say akosha)
  ↓
CI workflow runs (additive — existing steps unchanged):
  - existing: crackerjack run, ruff, mypy, pytest
  - NEW: uvx --from 'mahavishnu==<pinned>' mahavishnu conformance check --target .
  ↓
mahavishnu conformance CLI / MCP tool:
  - opens MCP connection to local crackerjack server via BodaiComponentMCPClient
  - reads settings/bodai-ports.yaml via Oneiric
  - reads settings/bodai-doc-rules.yaml via Oneiric
  - for each rule in bodai-doc-rules.yaml:
    - calls crackerjack__check_<rule_type>(config=rule_config) over MCP
    - collects pass/fail + file:line + remediation hint
  - aggregates per-check results
  - emits per-check status with structured MHV error code
  ↓
CI reports:
  - exit 0 → all pass → continue to merge
  - non-zero → MHV-coded error → route by category (PR comment vs maintainer alert)
```

**Boundary crossings:**
1. `mahavishnu → crackerjack` via MCP (NOT Python import). Honors mcpretentious-removed-mcp-first.
2. `crackerjack primitive → mahavishnu rule` via MCP tool call (structured response).
3. `rule config → check result` in MCP response. Structured pass/fail + diagnostics.
4. `Oneiric settings layer → conformance runner` via standard `settings/bodai-doc-rules.yaml` lookup.

**Why `uvx --from 'mahavishnu==X.Y.Z'` not `uvx mahavishnu@X.Y.Z`:** the `@` form resolves to "this version or compatible"; a `mahavishnu>=0.13.0,<0.14.0` pin might resolve to a newer 0.13.x patch than the rule config expects. `==` pins exactly. (Adversarial review finding.)

## Error handling

### MHV error codes (ADR 003)

Per ADR 003, conformance errors use `MahavishnuError` subclasses, not bare integer exit codes. Allocated in `mahavishnu/core/errors.py`:

| MHV code | Class | Meaning | CI routing |
|---|---|---|---|
| `MHV-512` | `ConformanceDriftDetected` | Real drift found in docs/config/CLI | PR comment with file:line |
| `MHV-513` | `ConformanceRulesConfigInvalid` | `bodai-doc-rules.yaml` has invalid pattern/missing field | Maintainer alert |
| `MHV-514` | `ConformanceRulesFileMissing` | `settings/bodai-ports.yaml` or `bodai-doc-rules.yaml` not found | Maintainer alert |
| `MHV-515` | `ConformancePrimitiveCrash` | Crackerjack primitive returned an error | Maintainer alert (likely crackerjack bug) |
| `MHV-516` | `ConformanceUnavailable` | Cannot reach crackerjack MCP server, PyPI unreachable, etc. | Maintainer alert |

Each `MahavishnuError` subclass carries:
- `error_code: str` (e.g., `"MHV-512"`)
- `recovery: list[str]` (e.g., `["Update README.md:11 to read 0.12.0", "Or run `mahavishnu version sync`"]`)
- `details: dict[str, Any]` (per-check file:line + rule name)

CI workflow snippet maps the 5 MHV codes to either PR comment or maintainer alert.

### Per-check failure isolation

Each check runs in its own try/except. One crash doesn't block others. CLI/MCP output:

```
[MHV-512] documented_but_not_wired: FAIL
  → akosha/processing/embeddings.py:1-8 references 'ONNX runtime' but pyproject.toml:173 has empty embeddings group
  → Recovery: rewrite module docstring to reflect actual runtime

[MHV-512] removed_but_referenced: PASS
[MHV-512] version_guard: SKIPPED (kill_switch: true)
[MHV-515] mcp_tool_inventory: CRASH
  → BodaiComponentMCPClient: cannot reach crackerjack at http://localhost:8676/mcp
```

### Graceful degradation

- **Rule missing from bodai-doc-rules.yaml**: skipped (not failed). New Bodai repos that haven't adopted all 6 checks still work.
- **Rule has `kill_switch: true`**: skipped explicitly. Maintainer can disable a single rule without a new mahavishnu release (adversarial review finding).
- **Unknown rule**: SKIPPED with stderr note rather than crashing.

### Remediation hints

Every drift error includes a remediation hint. Hints are templated in `bodai-doc-rules.yaml` (each rule declares its hint template). Crackerjack primitives don't know about hints — the rule layer generates them.

## Maintenance: per-rule kill switch

Each rule in `bodai-doc-rules.yaml` has a `kill_switch: bool` field. When `true`, the rule is SKIPPED at runtime (not failed) and a note is logged.

**Why:** if a buggy primitive false-positives on all 6 repos simultaneously, maintainers can disable one rule with a one-line YAML edit (no new mahavishnu release, no PyPI publish, no per-repo pin bump). Adversarial review finding.

## Self-version-skew handling

Crackerjack's own `__init__.py` may declare a different version than its `pyproject.toml` (currently true: `pyproject.toml:0.12.0` vs `__init__.py:0.1.0`). When the `version_guard` rule is adopted in the crackerjack repo itself, it will fire on its own skew forever.

**Solution:** every rule in `bodai-doc-rules.yaml` has an `allow_self_violation: bool` field. When `true`, the rule is SKIPPED when the target repo's name matches the repo that owns the rule (e.g., `version_guard` has `allow_self_violation: true` in mahavishnu's settings, so the crackerjack repo can adopt it without firing on its own skew until that's fixed).

**Source-of-truth:** `pyproject.toml [project].version` is canonical for all Bodai repos. `__init__.py` `__version__` should read via `importlib.metadata.version()`.

## Pydantic env var scoping (MVP)

`documented_but_not_wired` is the most complex rule. Most Bodai env vars use `SettingsConfigDict(env_prefix="MAHAVISHNU_")` + `env_nested_delimiter="__"`, not `Field(validation_alias=...)`. AST-detectable explicit-alias wiring covers ~20% of env vars.

**MVP scope:** the rule only checks for **explicit `Field(validation_alias=...)`, `Field(alias=...)`, `AliasChoices(...)`, and `AliasPath(...)`** patterns. ~80% of env vars (those using `env_prefix` + delimiter) are out of scope for the MVP.

**MVP behavior:** if an env var is documented but has no explicit alias binding, the rule reports a **hint** (not failure) with the recommendation to either add an explicit alias or document the `env_prefix`-derived name. After 2 quarterly audits confirm the MVP is useful, extend to full Pydantic AST traversal in a follow-up spec.

This is a documented scope reduction, not a bug. The audit's "documented-but-not-wired" pattern includes many cases the MVP cannot catch — that's fine for the MVP; the goal is to catch *some* of them and build the pipeline.

## Security

- **SHA256 hash pinning for `uvx`:** each Bodai repo's CI pins the mahavishnu wheel by SHA256: `uvx --from 'mahavishnu==X.Y.Z --hash=sha256:abc123...' mahavishnu`. Defends against PyPI compromise.
- **YAML loading:** mandatorily `yaml.safe_load` (or `CSafeLoader`). Never `yaml.load` (RCE risk if anyone modifies the rule config).
- **Watchdog (see Components §6):** detects CI step removal.
- **TLS verification:** `uvx` verifies PyPI TLS by default; spec explicitly states no overrides (`UV_INDEX_URL` to private mirror must still be TLS-verified).

## 6-check vs 5-primitive mapping

The 6 Bodai-specific checks map to the 5 crackerjack primitives as follows:

| Check | Primary primitive | Notes |
|---|---|---|
| `version_guard` | `pyproject_field` + `regex_match` (for README banner) + MCP `/health` call | Multi-source comparison |
| `mcp_tool_inventory` | `markdown_inventory` (compare committed vs regenerated) | Default mode is fixture-only (committed inventory); live MCP comparison is opt-in |
| `removed_but_referenced` | `git_grep` (deleted symbols since tag) + `regex_match` (scan docs/) | Excludes worktrees + archive paths |
| `documented_but_not_wired` | `ast_symbol_check` (explicit aliases only — MVP) | See Pydantic env var scoping section |
| `port_consistency` | `pyproject_field` + per-repo `conformance.yaml` port key path | |
| `cli_conventions` | Deferred to Phase 4 — conventions TBD | Listed for completeness; no implementation yet |

## Testing

Three layers.

### Layer 1: Crackerjack primitive unit tests

Each of the 5 generic primitives gets unit tests with deliberately-broken fixtures at `/Users/les/Projects/crackerjack/tests/fixtures/`:

- `regex_match`: README with banner (pass), without (fail), malformed regex (config error, MHV-513).
- `git_grep`: repo with deleted symbols cited in docs (fail), clean repo (pass), no deleted symbols (pass trivially), worktree-only matches (skip).
- `pyproject_field`: pyproject with version (pass), without (MHV-514).
- `markdown_inventory`: committed inventory matching API (pass), missing tool (fail), malformed delimiters (MHV-513).
- `ast_symbol_check`: symbol resolves (pass), doesn't (fail).

### Layer 2: Mahavishnu rule integration tests

Each of the 6 Bodai-specific rules gets an integration test at `mahavishnu/tests/integration/conformance/`:

1. Create fixture Bodai-shaped repo (with pyproject, README, CLAUDE.md, settings/<repo>.yaml, conformance.yaml).
2. Run `mahavishnu conformance check --target <fixture>` over MCP.
3. Assert expected pass/fail outcome with expected MHV code.

Fixture repos:
- `fixture_clean_bodai_repo/` — all 6 checks pass.
- `fixture_version_drift/` — version_guard fails (MHV-512).
- `fixture_removed_but_referenced/` — git_grep finds deleted symbol in docs.
- `fixture_documented_but_not_wired/` — env var in docs has no explicit alias.
- `fixture_port_mismatch/` — repo settings disagree with bodai-ports.yaml.
- `fixture_akosha_3_port_sources/` — real akosha 3-source conflict (regression test for adversarial finding).

### Layer 3: Cross-layer drift detection (permanent regression)

`tests/integration/conformance/test_cross_layer_drift_detection.py` runs conformance check against each Bodai repo **as it stands today** and asserts at least the documented audit findings are caught:

```python
result = run_conformance_check("/Users/les/Projects/akosha")
assert result.failures >= audit_findings_count_for("akosha")
```

This is a **permanent CI gate for the conformance subsystem itself**, not a one-off. Each quarterly audit runs against this test's baseline; failures during audits update the baseline under review.

## Out of scope (YAGNI)

- No new Python packages
- No new MCP servers (crackerjack adds tools to its existing server; mahavishnu exposes via existing)
- No new repos
- No auto-fix of detected drift (humans in the loop; future spec after 2 quarterly audits show rules are stable)
- No web dashboard for drift status
- No retry logic in checks (deterministic local reads; no network except MCP server call which is local)
- No silent failure suppression
- CLI conventions rule content (Phase 4 TBD)
- Full Pydantic AST traversal (MVP scope reduction; Phase 2 follow-up)

## Open question deferred

Port registry mechanism: **Option 3** (per-repo `conformance.yaml` manifest, mahavishnu cross-checks) for now. **Option 2** (fetch at startup from mahavishnu MCP server) deferred until "something more complex is needed."

## Implementation rollout

### Integration Contract (per Phase)

Each phase deliverable specifies:
- **Triggered from:** which CI workflow entry / CLI command / MCP tool
- **Returns to / updates:** which artifact / config / lock file
- **Demonstrable by:** one CLI/MCP invocation or test name that proves wiring end-to-end
- **Rollback signal:** log line, metric, or alert
- **Observability added:** OTel span, Dhara event, or `mahavishnu-activity-stream` line

---

### Phase 1: Crackerjack primitives + version_guard rule + adopt in mahavishnu

**Deliverable:** 5 crackerjack primitives (CLI + MCP) + `version_guard` rule + adopt in mahavishnu.

- **Triggered from:** PR opened in `/Users/les/Projects/crackerjack`; PR opened in `/Users/les/Projects/mahavishnu`.
- **Returns to / updates:**
  - `crackerjack/cli/check.py` (new), `crackerjack/mcp/server.py` (new tools registered), `crackerjack/services/regex_patterns.py` (reused), `tests/fixtures/` (new)
  - `mahavishnu/settings/bodai-ports.yaml` (new), `mahavishnu/settings/bodai-doc-rules.yaml` (new with `version_guard` rule + `allow_self_violation: true`)
  - `mahavishnu/cli/conformance_cli.py` (new), `mahavishnu/mcp/tools/conformance_tools.py` (new MCP tool)
  - `mahavishnu/.github/workflows/ci.yml` (add step)
- **Demonstrable by:**
  - `mahavishnu conformance check --target .` exits 0 against clean mahavishnu HEAD
  - `mahavishnu conformance check --target .` against `akosha` (or other repo with intentional drift) exits with `MHV-512`
- **Rollback signal:** CI logs `MHV-516` (conformance unavailable) or sustained MHV-515 (primitive crash) for >1 hour
- **Observability added:** OTel span `bodai.conformance_check`; Dhara event `convention_check_completed` per invocation

**Manual version bump (crackerjack repo):** flagged as `Skipped — user handles manually` per `crackerjack-version-bumping-manual`. The implementer brief does NOT bump crackerjack's `pyproject.toml`. The user handles the version bump + PyPI publish post-merge.

**Phase 1 success criterion:** `mahavishnu conformance check --target .` catches the existing `mahavishnu/__init__.py` vs `pyproject.toml` skew (modulo `allow_self_violation: true`).

---

### Phase 2: Remaining 5 Bodai rules + adopt in 5 sibling repos

**Deliverable:** `mcp_tool_inventory`, `removed_but_referenced`, `documented_but_not_wired`, `port_consistency`, plus adopt in akosha/dhara/session-buddy/crackerjack/oneiric.

- **Triggered from:** PRs in the 5 sibling repos; PR in mahavishnu.
- **Returns to / updates:**
  - `mahavishnu/settings/bodai-doc-rules.yaml` (5 new rule blocks)
  - `mahavishnu/tests/integration/conformance/` (5 new fixture repos)
  - `<each-sibling>/conformance.yaml` (per-repo port manifest)
  - `<each-sibling>/.github/workflows/ci.yml` (add step)
- **Demonstrable by:** Layer 3 cross-layer drift detection test passes for all 5 sibling repos
- **Rollback signal:** any sibling's CI fails 3 consecutive runs after rule update
- **Observability added:** `mahavishnu-activity-stream` hook fires per check pass/fail

**Manual version bumps (Phase 2):** for non-crackerjack Bodai repos, `crackerjack-p-minor-full-lifecycle` memory applies — `python -m crackerjack run -v -p minor` handles bump+commit+tag+push+publish automatically. Implementer runs that command. Verify with PyPI JSON API per the memory's hook-failure catalog.

---

### Phase 3: Watchdog + cross-layer regression test

**Deliverable:** watchdog (cron-driven) + permanent cross-layer drift detection test.

- **Triggered from:** weekly cron + every mahavishnu CI run.
- **Returns to / updates:**
  - `mahavishnu/workflows/bodai-conformance-watchdog/` (new Mahavishnu workflow)
  - `mahavishnu/tests/integration/conformance/test_cross_layer_drift_detection.py` (permanent)
- **Demonstrable by:** watchdog alerts when a repo's CI yaml is missing the conformance step
- **Rollback signal:** watchdog generates >10 false alerts in 7 days (tune)
- **Observability added:** OTel spans `bodai.conformance_watchdog.run`

---

### Phase 4 (future): CLI conventions rule + auto-remediation

Not in this spec. TBD after 2 quarterly audits show Phase 1-3 are stable.

## Success criteria

- All 5 cross-repo drift patterns from the 2026-08-12 audit are caught (MVP-scope for `documented_but_not_wired`)
- Zero false-positive failures on clean code (validated by Layer 3 cross-layer drift detection test)
- Crackerjack remains usable by non-Bodai projects (validated by existing crackerjack test suite)
- Per-repo adoption takes <30 minutes (validated by manual adoption in mahavishnu first)
- Watchdog catches any PR that removes the CI conformance step within 7 days
- `uvx` invocation is hash-pinned to defend against PyPI compromise

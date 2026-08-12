# Bodai Ecosystem Consistency Mechanisms — Design Spec

**Date:** 2026-08-12
**Status:** Approved (sections 1–5 reviewed 2026-08-12)
**Source:** Brainstorm session between Les and Claude following the 2026-08-12 cross-ecosystem docs audit (6 repos, 40 critical + 52 drift + 47 quality findings).

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
- No new PyPI packages (conformance lives in existing crackerjack + mahavishnu)
- Pre-1.0 merge policy: direct to main, no PRs, no review board
- Manual version bumps (crackerjack-version-bumping-manual)
- Crackerjack for CI/CD (no pre-commit hooks; memory: `no-bodai-pre-commit-hook`)
- Design-first: spec approved before any implementation begins

## Architecture

Crackerjack provides **generic primitives only** (no Bodai knowledge). Mahavishnu gains a `mahavishnu conformance check` CLI that orchestrates Bodai-specific checks by calling crackerjack primitives. Each Bodai repo adopts the conformance check in CI. Crackerjack stays ecosystem-agnostic.

**Key invariant:** Bodai-specific facts flow out of mahavishnu, never into it. Each repo is a read-only consumer.

## Components

### 1. Crackerjack primitives (ecosystem-agnostic)

New Typer subcommand `crackerjack check` at `crackerjack/cli/check.py`. Five generic rule types, each accepting a config block:

- `regex_match` — match a regex against file contents
- `git_grep` — find strings in the working tree, optionally compared against deleted symbols since the last tag
- `pyproject_field` — extract a TOML field and compare against a value
- `markdown_inventory` — extract a structured block from Markdown and compare
- `ast_symbol_check` — resolve a Python symbol and check existence/wiring

No Bodai knowledge. Each primitive is independently invokable via `crackerjack check --rule <type> --config <yaml>`.

### 2. Mahavishnu conformance CLI

New Typer subcommand `mahavishnu conformance check` at `mahavishnu/cli/conformance_cli.py`. Runs 6 Bodai-specific checks by:

1. Reading bundled `mahavishnu/settings/ports.yaml` (canonical port table) from package data
2. Reading bundled `mahavishnu/settings/bodai-doc-rules.yaml` (rule config) from package data
3. For each rule, calling `crackerjack.check.<rule_type>(config=rule_config)` in-process
4. Aggregating per-check pass/fail/skipped
5. Exiting 0 if all pass, non-zero otherwise

Mahavishnu imports crackerjack as a Python library (crackerjack is already a runtime dep of mahavishnu's CI machinery — no new coupling).

### 3. Shared rule config

Two files in `mahavishnu/settings/`:

- **`ports.yaml`** — canonical `{component_name: port}` mapping for all 6 Bodai repos:
  ```yaml
  ecosystem:
    mahavishnu: 8680
    akosha: 8682
    dhara: 8683
    session_buddy: 8678
    crackerjack: 8676
    oneiric: null  # library, no port
  ```
- **`bodai-doc-rules.yaml`** — schema describing each rule's config: which file to scan, what pattern to match, what to compare against, whether the check is required, remediation hint template.

Both files are bundled with the mahavishnu package (via `package_data`). Repos get the current version when they run `uvx mahavishnu@<version>`.

### 4. Per-repo adoption (×6)

One small PR per Bodai repo adds a CI step:

```yaml
# In each Bodai repo's CI workflow (e.g., .github/workflows/ci.yml)
- name: Bodai conformance
  run: uvx mahavishnu@<pinned-version> conformance check --target .
```

No structural changes to any repo. Total adoption: ~30 minutes per repo × 6 = ~3 hours.

### 5. Fallback path (no mahavishnu dev-dep)

Repos that can't depend on `uvx mahavishnu` (e.g., air-gapped CI) can vendor `bodai-doc-rules.yaml` locally and run crackerjack primitives directly. Same checks, different invocation.

## Data flow

```
PR opened in any Bodai repo (say akosha)
  ↓
CI workflow runs (additive — existing steps unchanged):
  - existing: crackerjack run, ruff, mypy, pytest
  - NEW: uvx mahavishnu@<pinned-version> conformance check --target .
  ↓
mahavishnu conformance CLI (Python):
  - imports crackerjack as Python lib
  - loads bundled settings/ports.yaml from package data
  - loads bundled settings/bodai-doc-rules.yaml from package data
  - for each rule in bodai-doc-rules.yaml:
    - build crackerjack check config from rule
    - call crackerjack.check.<rule_type>(config=rule_config)
    - collect pass/fail + file:line + remediation hint
  - aggregate per-check results
  - emit per-check status; exit 0/1/2/3/4/5 per error category
  ↓
CI reports:
  - exit 1 → real drift → block PR
  - exit 2-5 → tool error → alert maintainer (different channel)
```

**Boundary crossings:**
1. `mahavishnu package → Bodai repo CI` via `uvx` invocation. One-way read.
2. `crackerjack primitive → mahavishnu rule` via Python function call. No IPC.
3. `rule config → check result` in-process. Structured data flows up.

**Failure modes addressed:**
- `uvx` cannot fetch mahavishnu → CI fails with clear error (exit 5)
- Repo settings disagree with mahavishnu → port_consistency check catches (exit 1)
- Rule config malformed → exit 2, doesn't false-positive fail

## Error handling

### Exit code strategy

| Category | Exit | Example | Operator action |
|---|---|---|---|
| Real drift | 1 | `version_guard FAIL: pyproject says 0.12.0 but README says 0.3.3` | Fix the drift |
| Tool broken (config) | 2 | `version_guard: regex pattern in bodai-doc-rules.yaml doesn't match README.md` | Fix the rules config |
| Tool broken (missing file) | 3 | `port_consistency: akosha has no settings/akosha.yaml` | Fix rules config or add file |
| Tool broken (crash) | 4 | `mcp_tool_inventory: connection refused` | Start server, or skip check |
| Tool unavailable | 5 | `uvx: cannot fetch mahavishnu==0.13.0 from PyPI` | Retry, or check network |

CI workflows: exit 1 → fail PR (drift). Exit 2-5 → fail pipeline (tool error, different alerting).

### Per-check failure isolation

Each check runs in its own try/except. One check crashing doesn't prevent others. CI report shows:

```
version_guard: PASS
mcp_tool_inventory: PASS
removed_but_referenced: PASS
documented_but_not_wired: FAIL (exit 1)
  → akosha/processing/embeddings.py:1-8 references 'ONNX runtime' but pyproject.toml:173 has empty embeddings group
port_consistency: TOOL ERROR (exit 3)
  → akosha has no settings/akosha.yaml — fix rules.yaml:port_settings_path
cli_conventions: SKIPPED (no rule config)
```

### Graceful degradation

- **Rule missing from bodai-doc-rules.yaml**: check is **skipped**, not failed. A new Bodai repo that hasn't adopted all 6 checks yet still works.
- **Optional checks**: each check has `required: true|false` flag. Optional checks warn, don't fail.
- **Unknown rule**: `crackerjack check --rule <unknown>` exits 0 with stderr "rule not registered — skipping" rather than crashing.

### Remediation hints

Every real-drift error includes a remediation hint with file:line and suggested fix. Hints are generated from the rule config (each rule declares its hint template) — crackerjack primitives don't know about hints.

## Testing

Three layers.

### Layer 1: Crackerjack primitive unit tests

Each of the 5 generic primitives gets unit tests with **deliberately-broken fixtures**:

- `regex_match`: README with banner (pass), without (fail), malformed regex (config error exit 2).
- `git_grep`: repo with deleted symbols cited in docs (fail), clean repo (pass), no deleted symbols (pass trivially).
- `pyproject_field`: pyproject with version (pass), without (config error exit 2).
- `markdown_inventory`: committed inventory matching API (pass), missing tool (fail), extra tool (fail).
- `ast_symbol_check`: symbol resolves (pass), doesn't (fail).

Fixtures in `crackerjack/tests/fixtures/`. No network, no external state.

### Layer 2: Mahavishnu rule integration tests

Each of the 6 Bodai-specific rules gets an integration test in `mahavishnu/tests/integration/conformance/`:

1. Create fixture Bodai-shaped repo (with pyproject, README, CLAUDE.md, settings/<repo>.yaml).
2. Run `mahavishnu conformance check --target <fixture>` with rule config matching that fixture's shape.
3. Assert expected pass/fail outcome.

Fixture repos:
- `fixture_clean_bodai_repo/` — all 6 checks pass.
- `fixture_version_drift/` — version_guard fails (exit 1).
- `fixture_removed_but_referenced/` — git_grep finds deleted symbol in docs.
- `fixture_documented_but_not_wired/` — env var in docs has no Field binding.
- `fixture_port_mismatch/` — repo settings disagree with ports.yaml.

### Layer 3: Cross-layer drift detection verification

Most important test. Runs conformance check against each Bodai repo **pre-remediation** and asserts **at least the documented audit findings are caught**:

```python
# One-off test, run before/after remediation wave
result = run_conformance_check("/Users/les/Projects/akosha")
assert result.failures >= audit_findings_count_for("akosha")
```

After remediation lands, same test asserts zero failures. Proves the system is both **sensitive** (catches real drift) and **specific** (doesn't false-positive on clean code).

### Out of testing scope

- Live MCP server testing (covered by per-repo smoke tests)
- Auto-remediation testing (out of scope entirely)
- Cross-repo interaction testing (each repo's check is independent)

## Out of scope (YAGNI)

- No new Python packages
- No new MCP servers
- No new repos
- No auto-fix of detected drift (humans in the loop; future spec after 2 quarterly audits show rules are stable)
- No web dashboard for drift status (crackerjack's existing CI status is the dashboard)
- No retry logic in checks
- No silent failure suppression
- Architecture conformance (config layout, CLAUDE.md template) — future spec if needed

## Open question deferred

Port registry mechanism: **Option 3** (pin-in-each-repo, crackerjack cross-checks) for now. **Option 2** (fetch at startup from mahavishnu MCP server) deferred until "something more complex is needed."

## Implementation rollout (preview)

| Phase | Scope | Time |
|---|---|---|
| 1 | Crackerjack primitives + first Bodai rule (version guard). Adopt in 1 repo (mahavishnu). Verify CI catches real drift. | Week 1 |
| 2 | Add remaining 5 Bodai rules. Adopt in all 6 Bodai repos. | Weeks 2-3 |
| 3 | Per-repo smoke tests + cross-layer drift detection verification. Quarterly audit cadence begins. | Week 4 |
| 4 (future) | Auto-remediation tools. Mahavishnu ports sync. CLI conventions enforcement. | TBD |

## Success criteria

- All 5 cross-repo drift patterns from the 2026-08-12 audit are caught by the conformance check
- Zero false-positive failures on clean code (validated by cross-layer drift detection test after remediation)
- Crackerjack remains usable by non-Bodai projects (validated by existing crackerjack test suite)
- Per-repo adoption takes <30 minutes (validated by manual adoption in mahavishnu first)

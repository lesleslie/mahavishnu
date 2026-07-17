---
status: shipped
role: historical
date: 2026-04-25
last_reviewed: 2026-07-16
superseded_by: null
topic: adapter-architecture
---

# Type Adapter Migration Plan

**Date**: 2026-04-25
**Status**: active, Phase 3 (canary/promotion)  <!-- legacy status: active, Phase 3 — see YAML frontmatter -->
**Scope**: Crackerjack `ty`, `pyrefly`, and `zuban` adapters plus AI-fix routing

## Summary

Crackerjack currently treats `zuban` as the default comprehensive type checker and keeps `ty` and `pyrefly` behind experimental flags. That is still the right default posture, but the adapter layer has drifted from current upstream docs:

- `ty` now documents `ty check`, `--output-format`, `--fix`, and `--add-ignore`.
- `pyrefly` now documents `pyrefly check`, `--output-format=json`, `pyrefly suppress`, and baseline support.
- `zuban` still exposes both `zuban check` and `zuban mypy`, with the current adapter intentionally using the mypy-compatible path.

This plan refreshes all three adapters to current upstream contracts, then updates the AI-fix pipeline so native checker fixes are used only when they are actually supported.

## Goals

1. Keep `zuban` as the baseline comprehensive type checker until the newer tools are validated on real repos.
1. Bring `ty` and `pyrefly` adapters up to date with current CLI and output contracts.
1. Make native tool capabilities explicit in the adapter layer rather than inferred from tool names.
1. Make AI-fix use native type-checker fixes as a pre-pass when supported, then hand remaining issues to the AI loop.
1. Reduce parser fragility by covering current real outputs in tests.

## Non-Goals

1. Do not replace `zuban` as the default comprehensive checker in the first pass.
1. Do not make suppression workflows the default AI-fix path.
1. Do not depend on undocumented output formats from the upstream tools.

## Current Findings

### `ty`

- Upstream docs describe `ty` as beta/0.0.x and explicitly note that breaking changes can occur between releases.
- The current CLI contract is `ty check`.
- The documented output format is controlled by `--output-format`.
- `--fix` is supported and should be treated as a native pre-pass fixer.
- The LSP offers code actions and quick fixes, but those should not be assumed to exist for every diagnostic.

### `pyrefly`

- Upstream docs describe `pyrefly` as active but still under development.
- The current CLI contract is `pyrefly check`.
- The documented machine-readable output format is `--output-format=json`.
- `pyrefly suppress` and `--baseline` are first-class rollout mechanisms.
- The adapter should prefer real JSON output over text parsing when available.

### `zuban`

- Upstream docs describe both `zuban check` and `zuban mypy`.
- The current adapter uses the mypy-compatible path, which is a defensible baseline for compatibility.
- `zuban` should remain the comparator while `ty` and `pyrefly` are being refreshed.

## Implementation Phases

### Phase 0: Contract Verification

Tasks:

- Add current-output fixtures for each type checker.
- Verify the exact exit-code and severity semantics used by the upstream CLIs.
- Confirm which commands should be used in batch mode versus AI-fix mode.

Exit criteria:

- Each adapter has a current fixture that matches the upstream tool's present CLI contract.
- The plan has a documented parser contract for each tool.

### Phase 1: Adapter Refresh

#### `ty`

Update the adapter to:

- Invoke `ty check` rather than the legacy root command.
- Use a parser-friendly output format consistent with current `ty` docs.
- Expose an explicit `supports_fix` capability.
- Treat `--fix` as a native pre-pass capability.
- Stop assuming old flag names that are no longer documented.

#### `pyrefly`

Update the adapter to:

- Invoke `pyrefly check`.
- Use `--output-format=json`.
- Add explicit support for suppression and baseline workflows.
- Keep `pyrefly suppress` and `--baseline` opt-in.
- Remove assumptions that predate the current config model.

#### `zuban`

Update the adapter to:

- Re-verify whether `zuban mypy` should remain the default adapter command or whether `zuban check` is a better parser target.
- Keep mypy-compatible parsing as the compatibility baseline if it still matches current output best.
- Update fixtures to current text output.

Exit criteria:

- Each adapter builds a command that matches current upstream docs.
- Each adapter parses current output from a real sample or a documented equivalent.

### Phase 2: Capability-Based AI-Fix Routing

Add adapter capability metadata:

- `supports_fix`
- `supports_suppress`
- `supports_baseline`
- `supports_json_output`

Then update AI-fix routing to:

1. Run the checker.
1. Apply the tool's own fix path if `supports_fix` is true.
1. Re-run the checker.
1. Pass remaining issues to the AI fixer.
1. Re-run the checker after AI edits.

Rules:

- `ty --fix` is a pre-pass, not a replacement for AI-fix.
- `pyrefly suppress` is a rollout/suppression tool, not the default AI repair path.
- `zuban` stays the default source of truth until the canary lanes prove stable.

Exit criteria:

- AI-fix can tell the difference between native-fix tools and pure diagnostic tools.
- The pipeline reruns the same checker after each edit stage.

### Phase 3: Canary and Promotion

Roll out in this order:

1. Refresh adapters and tests.
1. Enable `ty` as an opt-in canary.
1. Enable `pyrefly` as an opt-in experimental lane.
1. Compare output fidelity, fix success rate, and false-positive rate against `zuban`.
1. Promote only if the newer checker is stable on representative repos.

Exit criteria:

- `ty` and `pyrefly` both have documented rollout status.
- `zuban` remains available as the fallback baseline.

## Required Code Changes

- [x] crackerjack/adapters/type/ty.py — `ty check`, `--output-format`, `--fix`, `--add-ignore`, capability methods
- [x] crackerjack/adapters/type/pyrefly.py — `pyrefly check --output-format=json`, baseline, suppress, JSON parser
- [x] crackerjack/adapters/type/zuban.py — `zuban mypy --config-file mypy.ini`, mypy-format text parser
- [x] crackerjack/adapters/type/README.md — settings docs, AI-fix workflow notes
- [x] crackerjack/config/hooks.py — `_build_opt_in_type_hooks()` for ty/pyrefly, zuban in COMPREHENSIVE_HOOKS
- [x] crackerjack/config/tool_commands.py — all three tools wired via `_preferred_binary_command`
- [x] crackerjack/core/autofix_coordinator.py — `_run_native_tool_fix` gated by `supports_fix()`, `_refresh_type_tool_issues` re-checks after fix
- [x] tests/adapters/test_type_adapters.py — 22 tests: Ty (7), Pyrefly (7), Zuban (8)

## Validation Matrix

- `ty`
  - `ty check`
  - `ty check --fix`
  - `ty check --output-format=<current parser-friendly format>`
- `pyrefly`
  - `pyrefly check --output-format=json`
  - `pyrefly suppress`
  - `pyrefly check --baseline=<file>`
- `zuban`
  - `zuban mypy`
  - `zuban check` if the adapter switch is justified by parser fidelity

## Risks

- `ty` and `pyrefly` are still moving targets and may change diagnostics or output details between releases.
- `ty --fix` may only resolve a subset of issues, so the AI loop still needs to handle the remainder.
- `pyrefly` suppression/baseline workflows can hide real regressions if they are used too early.
- `zuban` licensing and packaging choices should stay visible in the plan so the default lane does not drift silently.

## Decision Rule

Promote a new type checker only if:

- the adapter can parse its current output reliably,
- the AI-fix loop still works end-to-end,
- and a canary run across representative repos does not regress fix success or developer trust.

---
status: complete
role: historical
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
blocks_on: []
topic: crow-mcp-client
---

# Crow Adapter `mcp_client=None` Wiring — Bootstrap Followup

**Status:** Resolved (2026-06-29) <!-- legacy status: Resolved — see YAML frontmatter -->. The long-term proper fix is in place: all three CLI call sites in `mahavishnu/_main_cli.py` (~1073, 1156, 1381) now construct the `mcp_client` from settings via the `_resolve_crow_mcp_client` helper, which delegates to `mahavishnu.mcp.crow_server.create_crow_mcp_client`. When `terminal.crow_enabled=true`, the call sites pass a configured `BodaiComponentMCPClient` to `TerminalManager.create()`; when the toggle is left at its `false` default, the call sites pass `None` and the factory falls through to the mock adapter. No separate call-site PR is needed; operators opt in by setting `crow_enabled: true` in `settings/local.yaml`. Regression coverage lives at `tests/unit/cli/test_crow_call_site_wiring.py`.
**Refs:** bodai-crow-server runbook (`docs/runbooks/bodai-crow-server.md`) §6; MHV-307 error code; `docs/runbooks/crow-adapter-mcp-client.md`.

## Background

The stock `mahavishnu mcp start` command crashes immediately on default configuration. The trigger is a wiring gap in the crow adapter, not a missing config field:

- `settings/mahavishnu.yaml:188` ships with `terminal.adapter_preference: "crow"` as the default.

- Three callers in `mahavishnu/_main_cli.py` (lines **1073**, **1156**, and **1381**) construct the terminal manager with `mcp_client=None`.

- The factory at `mahavishnu/terminal/manager.py:451-456` checks for `mcp_client is None` when `adapter_preference == "crow"` and raises:

  ```
  ConfigurationError: crow adapter requires mcp_client pointing at the Bodai crow HTTP server
  ```

The error message's wording ("pointing at the Bodai crow HTTP server") misdirects operators toward a URL-typo hunt. The real failure is that *no caller passes an `mcp_client` at all* — there is nothing to "point" because nothing is constructed. A user with a perfectly correct `MAHAVISHNU_CROW_HTTP_HOST`/`PORT` setup still crashes, because those env vars are not consulted by the CLI entry points.

The error code at `mahavishnu/core/errors.py:84` is `MHV-307 CROW_MCP_UNAVAILABLE` — this is the documented signal for "crow can't be reached". The current `mcp_client=None` failure surfaces a different (more confusing) `ConfigurationError` upstream of MHV-307.

## Why out of scope

This is a code change spanning three CLI call sites + the factory check, not a config change. The remediation must keep the *documented* happy path working (`adapter_preference: "crow"` + running crow server on `127.0.0.1:8675`) without breaking environments that don't have crow running. That's a behavior decision that warrants its own PR with explicit test coverage.

Folding the fix into the runbook + `local.yaml.example` PR would:

- Change bootstrap behavior for every user who runs `mahavishnu mcp start` with the default config.
- Couple a behavioral change to a documentation PR, making the diff hard to review.
- Risk silent regressions for users who *do* have crow wired correctly and rely on the current fail-fast behavior to detect drift.

## Proposed remediation

Two options, in order of preference. **The recommended option is to introduce a `crow.enabled` toggle**; the alternative is a smaller but more user-facing change.

### Recommended — Add `crow.enabled` toggle

1. **Default off in `settings/mahavishnu.yaml`:**

   ```yaml
   crow:
     enabled: false  # When false, terminal.adapter_preference: "crow" is ignored
     http_host: "127.0.0.1"
     http_port: 8675
   ```

1. **Update `mahavishnu/terminal/manager.py:451-456`** to skip the `mcp_client is None` check when `settings.crow.enabled` is `false`. When disabled, fall through to the next preference (`mock` → `iterm2` → `mcpretentious`) per the existing cascade. No `ConfigurationError` raised.

1. **Update `mahavishnu/_main_cli.py:1073,1156,1381`** to pass `mcp_client=None` only when `settings.crow.enabled` is false; otherwise, construct a client from `MAHAVISHNU_CROW_HTTP_HOST` / `MAHAVISHNU_CROW_HTTP_PORT` (or the corresponding `settings.crow.*` values).

1. **Backward compatible.** Operators who want today's behavior (fail-fast when crow is unreachable) set `crow.enabled: true` explicitly. The default change is opt-in: users who add `enabled: true` to their `local.yaml` get exactly the existing crash, just with a clearer message.

1. **Regression test** at `tests/unit/terminal/test_manager_crow_toggle.py`:

   - `test_crow_disabled_skips_mcp_client_check` — `crow.enabled: false`, `adapter_preference: "crow"` → falls through to mock, no `ConfigurationError`.
   - `test_crow_enabled_constructs_client_from_env` — sets `MAHAVISHNU_CROW_HTTP_HOST`/`PORT`, asserts the constructed client targets them.
   - `test_crow_enabled_missing_env_raises_clear_error` — `crow.enabled: true`, no env → `MHV-307 CROW_MCP_UNAVAILABLE` with the message "set MAHAVISHNU_CROW_HTTP_HOST/MAHAVISHNU_CROW_HTTP_PORT or disable crow in settings".

### Alternative — Flip the default to `mock`

- One-line change at `settings/mahavishnu.yaml:188`: `terminal.adapter_preference: "mock"`.
- Smallest possible diff. No code changes.
- **Trade-off:** disables crow for every user by default. Operators who want crow must remember to set the preference, breaking the "crow is the recommended path" posture in the runbook.
- Reasonable as a stopgap, but not the long-term answer.

### Long-term proper fix

Once the `crow.enabled` toggle is in place, follow up with proper wiring:

1. `mahavishnu/_main_cli.py:1073,1156,1381` constructs the `mcp_client` from settings, not from `None`.
1. `mahavishnu/terminal/manager.py:451-456` assumes the client is always valid when `adapter_preference == "crow"`; the MHV-307 error path moves to the client construction site (where it actually checks reachability).
1. The "Bodai crow HTTP server" wording in the original error message is replaced with a one-line checklist pointing at the runbook.

This is the cleanest end state but requires more invasive changes. Sequence: `crow.enabled` toggle first (this PR), proper wiring later (separate PR).

## References

- `settings/mahavishnu.yaml:188` — `terminal.adapter_preference: "crow"` default
- `mahavishnu/_main_cli.py:1073` — first `mcp_client=None` caller
- `mahavishnu/_main_cli.py:1156` — second `mcp_client=None` caller
- `mahavishnu/_main_cli.py:1381` — third `mcp_client=None` caller
- `mahavishnu/terminal/manager.py:451-456` — factory check that raises `ConfigurationError`
- `mahavishnu/core/errors.py:84` — `MHV-307 CROW_MCP_UNAVAILABLE` (intended error path; currently bypassed)
- `docs/runbooks/bodai-crow-server.md` §6 — operational runbook the bootstrap is supposed to honor

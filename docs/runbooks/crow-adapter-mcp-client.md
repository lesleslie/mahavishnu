# Crow Adapter — Missing MCP Client Runbook

**Status:** Resolved as of 2026-06-29 (long-term proper fix landed). The CLI call
sites now construct an `mcp_client` from settings when `terminal.crow_enabled=true`,
and fall through to the mock adapter when the toggle is left at its `false` default.
Operators opt in to crow by setting `crow_enabled: true` in `settings/local.yaml`
— no separate call-site fix is needed. Ticket ID `MHV-001` does not appear in recent
commits; the related error code in `mahavishnu/core/errors.py:84` is `MHV-307 CROW_MCP_UNAVAILABLE`.

**Refs:**

- `settings/mahavishnu.yaml:188` — `terminal.adapter_preference: "crow"` is the **default**.
- `mahavishnu/terminal/config.py:63-71` — `crow_enabled` toggle (defaults to `false`).
- `mahavishnu/_main_cli.py:78-103` — `_resolve_crow_mcp_client` helper.
- `mahavishnu/_main_cli.py:~1073, 1156, 1381` — three call sites wired to the helper.
- `mahavishnu/mcp/crow_server.py` — bundled `bodai-crow` HTTP server (default endpoint `http://localhost:8675/mcp`) and `create_crow_mcp_client` helper.
- `mahavishnu/terminal/manager.py:451-486` — factory now falls through to mock when `crow_enabled=false`; raises clear error only when enabled and client is missing.
- `mahavishnu/core/errors.py:84` — `CROW_MCP_UNAVAILABLE` definition.
- `docs/followups/2026-06-29-crow-mcp-client-wiring.md` — original followup (now Resolved).

## Severity

**Resolved.** A stock install (with `crow_enabled=false`) no longer crashes —
the terminal factory falls through to the mock adapter. Operators who flip
`crow_enabled: true` get the proper crow client wired automatically at all
three CLI call sites, and a missing client now produces a clear
`ConfigurationError` instead of a misleading URL hint.

## Detection

### Primary signal — CLI crash (only when crow_enabled=true)

A stock install no longer crashes because `crow_enabled` defaults to `false`
and the factory falls through to the mock adapter. If an operator has set
`crow_enabled: true` (and the bundled crow server is not reachable) the
factory raises a clear `ConfigurationError`:

```
ConfigurationError: crow adapter is enabled (crow_enabled=true) but no
mcp_client was provided to TerminalManager.create(). Either provide an
mcp_client pointing at the Bodai crow HTTP server, or set
terminal.crow_enabled=false to use the mock adapter.
```

The error is raised from the adapter factory at `mahavishnu/terminal/manager.py:451-486`. Exit code is non-zero; no HTTP listen port is bound; the local `http://localhost:8680/mcp` endpoint never becomes reachable.

### Secondary signal — `get_health` after a partial start

If a partial start reaches the health endpoint before the crash, the terminal subsystem reports an exception in its detail block:

```json
{
  "overall": "degraded",
  "subsystems": {
    "terminal": {
      "status": "unhealthy",
      "error": "ConfigurationError: crow adapter requires mcp_client pointing at the Bodai crow HTTP server",
      "adapter_preference": "crow"
    },
    "mcp": { "status": "unknown" }
  }
}
```

(Exact JSON shape varies. The diagnostic that matters is the `ConfigurationError` text inside `subsystems.terminal.error` and the `adapter_preference` echoed as `"crow"`.)

## Diagnosis

The initial user-facing framing was *"mcp_client URL is misconfigured"* — meaning someone read the error message literally as *"the URL is wrong."* Discovery proved that framing wrong on three independent lines of evidence. The actual root cause is a wiring bug, not a config-string bug.

### Evidence 1 — The default preference is `"crow"`

`settings/mahavishnu.yaml:188`:

```yaml
terminal:
  adapter_preference: "crow"
```

This means the adapter factory at `manager.py:451` is unconditionally consulted on every CLI invocation that touches the terminal subsystem. The factory then consults `terminal.adapter_preference` and routes into the `crow` branch. There is no fallback and no `crow.enabled` gate.

### Evidence 2 — The three CLI callers hardcode `None`

In `mahavishnu/_main_cli.py`, three sites construct the terminal manager with the same defect:

- Line **1073** — sub-command path that needs terminal sessions
- Line **1156** — alternate dispatch path
- Line **1381** — pool/worker startup path

Each reads (approximately):

```python
TerminalManager(
    adapter_preference=settings.terminal.adapter_preference,
    mcp_client=None,  # ← factory rejects this for the crow branch
)
```

The plumbing from settings → `TerminalManager(...)` to bridge the existing bundled `bodai-crow` HTTP client into `mcp_client=` was never wired. The error message says *"pointing at the Bodai crow HTTP server"* because that is what the factory expects, but no caller is passing any client at all.

### Evidence 3 — The factory rejects `None` unconditionally

`mahavishnu/terminal/manager.py:451-456` raises immediately when `mcp_client is None` and `adapter_preference == "crow"`:

```python
if adapter_preference == "crow" and mcp_client is None:
    raise ConfigurationError(
        "crow adapter requires mcp_client pointing at the Bodai crow HTTP server"
    )
```

There is no `crow.enabled` check and no env-var-based short-circuit. The error message is technically correct (a crow client IS required for the crow adapter), but in practice no caller provides one, so a stock install is non-functional on day one.

### Why the error message is misleading

The text reads like a *misconfiguration* — *"the URL is wrong"* — but the URL string is never reached because no `mcp_client` is constructed at all. Operators can spend time editing `crow.http_host` / `crow.http_port` (or `MAHAVISHNU_CROW_HTTP_HOST` / `MAHAVISHNU_CROW_HTTP_PORT` env vars) without effect, because those settings only matter **after** an `mcp_client` is constructed against them. The path from settings to client to factory is broken at step one (client construction), not step two (URL).

### Diagnostic decision tree

```
mahavishnu mcp start
  → ConfigurationError?
    YES → read `adapter_preference` from settings:
      == "crow"?  →  THIS RUNBOOK applies (default-config crash).
                    Verify with `grep -n "adapter_preference" settings/mahavishnu.yaml`.
      == "mock"?  →  Different issue. Crow is not the selected adapter.
                    Check terminal manager construction at the call site.
      == "iterm2" / "mcpretentious"?  →  Different issue. Verify the relevant
                    adapter's prerequisites (e.g. iTerm2 AppleScript bridge).
```

## Remediation

### Current state (2026-06-29)

The long-term proper fix is in place:

1. The `crow_enabled` toggle (`mahavishnu/terminal/config.py:63-71`) defaults to
   `false`. The terminal factory (`mahavishnu/terminal/manager.py:451-486`)
   falls through to the mock adapter when the toggle is `false`, so a stock
   install no longer crashes.
1. All three CLI call sites in `mahavishnu/_main_cli.py` (~1073, 1156, 1381)
   now construct the `mcp_client` from settings via the
   `_resolve_crow_mcp_client` helper. Operators opt in by setting
   `crow_enabled: true` in `settings/local.yaml` — no separate call-site fix
   is needed.
1. The bundled `bodai-crow` HTTP client is built via
   `mahavishnu.mcp.crow_server.create_crow_mcp_client`, which wraps the
   existing `BodaiComponentMCPClient` and reads
   `MAHAVISHNU_CROW_HTTP_HOST` / `MAHAVISHNU_CROW_HTTP_PORT` env overrides
   when set.

The historical options below are kept as a record of the decisions made
along the way. Pick **Option A** only as a stopgap if the toggle is not
appropriate for your environment.

______________________________________________________________________

Three legitimate paths were considered. Pick **one**. Do **not** combine them.

### Option A — Change the default to `mock` (quickest patch)

Safest for greenfield installs that do not yet need the crow HTTP server. One YAML edit, zero code changes.

1. Edit `settings/mahavishnu.yaml:188` and replace the default:

   ```yaml
   # before
   terminal:
     adapter_preference: "crow"

   # after
   terminal:
     adapter_preference: "mock"
   ```

   Or override per-environment in `settings/local.yaml` (gitignored) — preferred if you want to keep the bundled default pointing at `"crow"` for installations that *do* run the bundled crow server.

1. Restart: `mahavishnu mcp restart`.

**Trade-offs.** Smallest change. Eliminates the crash immediately. Disables the bundled crow HTTP server's terminal dispatch; pool workers fall back to the in-process `mock` adapter (no real terminal I/O). The crow HTTP server itself still runs on `127.0.0.1:8675` for its other consumers (file, web). Acceptable when you plan to enable crow properly later.

**Recommended when:** the install is greenfield, crow is not deployed, and a one-line YAML edit is the only change you can ship today.

### Option B — Wire the three callers (proper long-term fix)

Modify `mahavishnu/_main_cli.py:1073, 1156, 1381` so each constructs a `mcp_client` from settings before passing it to `TerminalManager(...)`. This is the fix that actually uses the bundled `bodai-crow` server.

1. In each of the three call sites, construct the client from settings. Roughly:

   ```python
   from mahavishnu.mcp.crow_client import CrowMCPClient  # canonical helper, see below

   mcp_client = CrowMCPClient(
       host=settings.crow.http_host,   # default 127.0.0.1
       port=settings.crow.http_port,   # default 8675
   )
   terminal_mgr = TerminalManager(
       adapter_preference=settings.terminal.adapter_preference,
       mcp_client=mcp_client,
   )
   ```

   (The exact helper name and import path live in `mahavishnu/mcp/crow_server.py:59-100`. Use whatever client helper is defined there — do **not** roll a fresh HTTP client inline at the three call sites.)

1. Ensure the bundled `bodai-crow` server is running before the CLI starts:

   ```bash
   mahavishnu mcp start crow
   mahavishnu mcp start     # then the main MCP server
   ```

1. Verify the env-var overrides are respected: `MAHAVISHNU_CROW_HTTP_HOST`, `MAHAVISHNU_CROW_HTTP_PORT`, `MAHAVISHNU_CROW_CROW_MCP_COMMAND`.

**Trade-offs.** The proper fix. Touches three call sites and adds a client-helper dependency at each. Risk is medium because the three sites have slightly different surrounding construction logic and may need different argument lists. Pair with a regression test that exercises the terminal-manager construction path against each call site.

**Recommended when:** crow is a first-class consumer, the team has bandwidth for a small refactor, and a follow-up PR is acceptable.

### Option C — Add a `crow.enabled` toggle (recommended middle ground)

Smallest code change that keeps the bundled default intent intact. Adds one config key and a one-line guard at `manager.py:451-456`.

1. Add `crow.enabled: true` (default) to `settings/mahavishnu.yaml`:

   ```yaml
   crow:
     enabled: false   # default off until callers are wired (Option B)
     http_host: "127.0.0.1"
     http_port: 8675
   ```

1. Modify the guard at `mahavishnu/terminal/manager.py:451-456`:

   ```python
   if (
       adapter_preference == "crow"
       and settings.crow.enabled   # ← new guard
       and mcp_client is None
   ):
       raise ConfigurationError(
           "crow adapter requires mcp_client pointing at the Bodai crow HTTP server"
       )
   ```

   When `crow.enabled` is `False`, the factory falls through to the default mock/iTerm2 branch without raising, and a stock `mahavishnu mcp start` succeeds even though `adapter_preference == "crow"` and `mcp_client is None`.

1. Operators opt in to the strict check by setting `crow.enabled: true` in `settings/local.yaml` once Option B is in place.

**Trade-offs.** Backward-compatible. Honors the bundled default intent (the system *wants* crow enabled) while not crashing stock installs. Smallest code surface — one YAML key, one ternary clause. Pairs naturally with Option B: ship C today, complete B later.

**Recommended when:** you cannot do Option B in this sprint but want to leave a clean path to it. **This runbook's headline recommendation.**

### Migration order

If you need crow eventually:

1. Land **Option C** to stop the crash today.
1. Track **Option B** as follow-up tech debt.
1. Once **Option B** is in place, flip `crow.enabled: true` in `settings/local.yaml` to enable the strict check.

If you do **not** need crow:

1. Land **Option A** (change the default).
1. Re-evaluate later if crow becomes a dependency.

## Verification

After applying **any** of A/B/C:

1. **Re-run the failing command.** It must not raise:

   ```bash
   uv run mahavishnu mcp start
   # expected: server binds, no ConfigurationError, log line "started on 127.0.0.1:8680"
   ```

1. **Health check.** Expect `overall: healthy` (or `degraded` without terminal in the failing state):

   ```bash
   curl -fsS http://localhost:8680/mcp -H 'content-type: application/json' \
        -d '{"jsonrpc":"2.0","id":1,"method":"health","params":{}}' | jq
   ```

   Healthy response looks like:

   ```json
   {
     "jsonrpc": "2.0",
     "id": 1,
     "result": {
       "status": "healthy",
       "subsystems": {
         "terminal": { "status": "healthy", "adapter_preference": "crow" },
         "mcp": { "status": "healthy" }
       }
     }
   }
   ```

   If `terminal.status` is still `unhealthy` and the `error` field contains the `ConfigurationError` text, the remediation did not take — re-check that the YAML edit landed or the code guard is wired correctly.

1. **Pool dispatch smoke test** (only after Option B lands — Options A and C with `crow.enabled: false` skip the crow path):

   ```bash
   uv run mahavishnu pool route --prompt "echo hello" --selector least_loaded
   ```

   Expect a 2xx response with the routed pool ID.

## References

| Concern | Location |
|---------|----------|
| Default adapter preference (the trigger) | `settings/mahavishnu.yaml:188` |
| Hardcoded `mcp_client=None` callers | `mahavishnu/_main_cli.py:1073`, `:1156`, `:1381` |
| Factory guard that raises | `mahavishnu/terminal/manager.py:451-456` |
| Bundled `bodai-crow` HTTP server | `mahavishnu/mcp/crow_server.py:59-100` |
| Error code `MHV-307` | `mahavishnu/core/errors.py:84` |
| Env-var overrides | `MAHAVISHNU_CROW_HTTP_HOST`, `MAHAVISHNU_CROW_HTTP_PORT`, `MAHAVISHNU_CROW_CROW_MCP_COMMAND` |

### Note on ticket ID

The originally reported ticket `MHV-001` does not appear in recent commits and is likely an external or pre-rename identifier. The authoritative code-defined error is `MHV-307 CROW_MCP_UNAVAILABLE` at `mahavishnu/core/errors.py:84`. When filing or triaging, prefer the error-code-based identification over the ticket ID.

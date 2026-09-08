---
status: active
role: implementation
date: 2026-09-07
last_reviewed: 2026-09-07
superseded_by: null
topic: terminal-adapter-goose
requirements:
  - id: REQ-GOO-001
    title: "Goose adapter speaks v1 HTTP (POST /sessions, GET /sessions/{id}/output, DELETE /sessions/{id})"
  - id: REQ-GOO-002
    title: "Goose bearer token is a pydantic SecretStr; never appears in repr/str/log dumps"
  - id: REQ-GOO-003
    title: "httpx event_hooks strip Authorization from any retry request"
  - id: REQ-GOO-004
    title: "GooseHTTPClient factory resolves args > env vars > 127.0.0.1:8694"
  - id: REQ-GOO-005
    title: "Goose session IDs default to full UUID4 (avoids 8-char prefix collisions)"
  - id: REQ-GOO-006
    title: "Goose error classes redact any details field whose name matches secret|token|key|bearer|authorization"
  - id: REQ-GOO-007
    title: "GooseTerminalAdapter integrates with the D0 terminal adapter registry"
---

# Goose Terminal Adapter (D3)

**Date:** 2026-09-07
**Status:** `active`, `implementation`
**Owner:** Core Eng
**Scope:** Mahavishnu (`/Users/les/Projects/mahavishnu`)
**Companion plan:** `/Users/les/.claude/plans/adaptive-hugging-mist.md` — D0 (registry) + D1 + D2 + D3. This plan implements D3 in isolation.

## 1. Outcome

When this plan ships, Mahavishnu gains a fourth terminal adapter (`goose`)
that bridges Python orchestrators with Block's `goose serve` HTTP backend —
Rust-fast, vendor-neutral, 70+ prebuilt MCP extensions. The adapter is
opt-in (default `goose_enabled=false`); operators opt in by setting
`goose_enabled=true` and providing the bearer via
`MAHAVISHNU_TERMINAL__GOOSE_SECRET_KEY` (or `goose_secret_key` in
`settings/local.yaml`).

Security primitives are non-negotiable:

1. The bearer token is a `pydantic.SecretStr` (never `str`). It cannot be
   serialised, repr'd, or dumped via structured logs. (REQ-GOO-002)
2. `httpx.AsyncClient(..., event_hooks={"response": [_default_redactor]})`
   strips `Authorization` from any retry request — a misrouted DNS or
   502+retry cannot exfiltrate the token to a different host.
   (REQ-GOO-003)
3. The error classes (`GooseUnavailable`, `GooseAuthError`,
   `GooseTimeoutError`) carry redaction in both `details` (field-name
   based) and message strings (regex-based). (REQ-GOO-006)
4. Default session IDs are full UUID4 (36 chars), avoiding the 8-char
   prefix collision risk that Mock is locked into. (REQ-GOO-005)

How we know it succeeded:

- `pytest tests/unit/terminal/test_goose_adapter.py -v --no-cov` passes
- `pytest tests/unit/terminal/test_goose_secret_redaction.py -v --no-cov` confirms the bearer never appears in `repr(error)`/`str(error)`
- `pytest tests/unit/terminal/test_goose_session_id_uniqueness.py -v --no-cov` confirms 10K launches produce no duplicate IDs
- `python -c "from mahavishnu.terminal.adapters import list_adapter_names; print(list_adapter_names())"` includes `goose`
- `mahavishnu mcp start` with `adapter_preference: "goose"` + `goose_enabled: true` returns `Adapter: goose`

## 2. Goals

1. Add a registry-driven fourth terminal adapter (`goose`) that speaks Block's `goose serve` HTTP surface.
2. Guarantee that the bearer token never leaks via `repr()`, `str()`, structured logs, or httpx retry to a non-canonical host.
3. Default to UUID4 session IDs to prevent 10K+ prefix collisions.
4. Expose typed errors (`GooseUnavailable`, `GooseAuthError`, `GooseTimeoutError`) with install hints and redacted payloads.
5. Reuse the D0 terminal adapter registry — adding `goose` is one `register_adapter("goose", ...)` call.

## 3. Non-Goals

1. Goose WebSocket streaming (v2 surface) — deferred to a follow-up plan; v1 is HTTP-poll only.
2. AppleScript execution — Goose is a cross-platform Rust binary, not an iTerm2/macOS shell. `run_applescript` raises `NotImplementedError`.
3. WebSocket broadcast channels for the adapter (per observability reviewer #4 in the parent plan) — out of scope until those channels exist.
4. CLI flag additions — Goose reuses the existing `adapter_preference: "goose"` setting.
5. Operator-side changes to `goose serve` (install instructions) — covered in `settings/local.yaml.example` comment block.

## 4. Current Findings

- The terminal adapter dispatch was refactored to a registry in D0 (`mahavishnu/terminal/adapters/__init__.py:31-57`). Adding `goose` is therefore a single `register_adapter("goose", ...)` call plus the lazy `try/except ImportError` wrapper that mirrors Crow.
- `pydantic.SecretStr` is already used at `mahavishnu/mcp/auth.py:11`, `mahavishnu/core/secure_logging.py:284`, and `mahavishnu/adapters/pgvector_adapter.py:99`. No new dependency.
- `httpx2` is the project's HTTP client (legacy `httpx` shadows via `import httpx2 as httpx`). MockTransport-based tests are the canonical pattern (`tests/unit/_httpx_test_helpers.py`).
- Mock adapter (`mahavishnu/terminal/adapters/mock.py:68`) uses 8-char prefixes; the security review flagged 8-char collisions at ~10K sessions. Goose is the first adapter that owns its own UUID space — default to UUID4.
- The existing `_REDACT_PATTERN` in `mahavishnu/core/errors.py` covers `sk-…`, `ghp_…`, `xox[ab]-…`, `ya29.…`, and `bearer …` patterns. D3 extends it to cover `secret=value`, `key=value`, `token=value`, and the space-separated variant (`token <value>`) — scope-limited, additive.

## 4.5 Requirements

Declared in YAML frontmatter above. `audit_requirements.py` validates that
every `# req: REQ-GOO-NNN` / `# Implements: REQ-GOO-NNN` /
`@pytest.mark.req(["REQ-GOO-NNN"])` reference points back to a declared
ID. The five core requirements (REQ-GOO-001 through REQ-GOO-007) cover
the full D3 surface.

## 5. Implementation Phases

### Phase 1: Errors and HTTP client

**Goal:** Establish the typed errors and the bearer-bearing HTTP transport
with auth-redaction.

**Tasks:**
- Add `GooseUnavailable`, `GooseAuthError`, `GooseTimeoutError` to `mahavishnu/core/errors.py`. Each redaction-safe (`__repr__` and `__str__` never include the token). (REQ-GOO-006)
- Extend `_REDACT_PATTERN` in `mahavishnu/core/errors.py` to cover `secret=value`, `token=value`, etc. (REQ-GOO-006)
- Create `mahavishnu/terminal/goose_client.py`:
  - `GooseHTTPClient` wraps `httpx2.AsyncClient(..., event_hooks={"response": [_default_redactor]})`. (REQ-GOO-003)
  - `_default_redactor` strips `Authorization`, `Proxy-Authorization`, `X-API-Key` from any retry request. (REQ-GOO-003)
  - `create_goose_http_client(host, port, secret_key, timeout)` resolves args > env vars > defaults. (REQ-GOO-004)
- Map `httpx.TimeoutException` → `GooseTimeoutError`, `httpx.ConnectError` → `GooseUnavailable`, `401/403` → `GooseAuthError`, `>=500` → `GooseUnavailable`.

#### Integration Contract — Phase 1
- **Triggered from**: import of `mahavishnu.terminal.goose_client` or call to `create_goose_http_client()`.
- **Returns to / updates**: typed error classes accessible from `mahavishnu.core.errors`; HTTP client with retry-safe auth header stripping.
- **Demonstrable by**: `pytest tests/unit/terminal/test_goose_secret_redaction.py -v --no-cov` passes; `repr(GooseAuthError("bearer abc123"))` does NOT contain `abc123`.
- **Rollback signal**: any test in `test_goose_secret_redaction.py` fails (would indicate a token-leak regression).
- **Observability added**: structured log emitted at `WARNING` from `close_session` on HTTP failure (no token payload in the log).
- **Knowledge transfer**: `_default_redactor` is async because httpx2 awaits every event hook. The redactor mutates `response.next_request.headers` (httpx >= 0.27 attribute) — `next_request` is `None` for the final response, which is a no-op. **If reverted**: retries to a misrouted DNS will carry the bearer token to an unintended host.

### Phase 2: Adapter and registry integration

**Goal:** Register the Goose terminal adapter with the existing D0
registry.

**Tasks:**
- Create `mahavishnu/terminal/adapters/goose.py` with `GooseTerminalAdapter(TerminalAdapter)`. (REQ-GOO-001)
  - Default `session_id_format="uuid"`; `"short"` available for parity. (REQ-GOO-005)
  - `startup_probe()` fires a no-op authenticated `GET /health` and returns `{"ok": bool, "adapter": "goose", "reason": ...}`.
  - `launch_session` calls `POST /sessions` and tracks the local session ID + server handle.
  - `send_command` calls `POST /sessions/{server_handle}/input`.
  - `capture_output` calls `GET /sessions/{server_handle}/output?limit_lines=N` (v1 HTTP poll).
  - `close_session` calls `DELETE /sessions/{server_handle}` and pops from `_sessions`.
  - `list_sessions` returns the locally tracked sessions.
  - `run_applescript` raises `NotImplementedError`.
- Edit `mahavishnu/terminal/adapters/__init__.py`:
  - Lazy import of `GooseTerminalAdapter` (mirrors Crow pattern at line 122).
  - `_build_goose_adapter(config, mcp_client)` factory: when `goose_enabled=false`, returns `MockTerminalAdapter`; when `True`, constructs `GooseHTTPClient` from `config.goose_http_host`/`port`/`secret_key`. (REQ-GOO-007)
  - `register_adapter("goose", _build_goose_adapter)`.

#### Integration Contract — Phase 2
- **Triggered from**: `import mahavishnu.terminal.adapters` (registry self-registration); `mahavishnu.terminal.manager.create(adapter_preference="goose")`.
- **Returns to / updates**: `list_adapter_names()` includes `goose`; `terminal_current_adapter` MCP returns `"goose"` when selected.
- **Demonstrable by**: `python -c "from mahavishnu.terminal.adapters import list_adapter_names; assert 'goose' in list_adapter_names()"` returns exit code 0.
- **Rollback signal**: `list_adapter_names()` does not include `goose` after deploy; `mahavishnu mcp start` with `adapter_preference: "goose"` fails to construct.
- **Observability added**: `INFO` log `terminal.adapter.goose.selected` on construction; `WARN` log on `close_session` HTTP failure (non-fatal).
- **Knowledge transfer**: The factory's lazy import keeps `import time` for the common path unaffected when the optional `pydantic.SecretStr`/httpx2 chain is not exercised. **If reverted**: terminal adapter dispatch is back to a 3-place edit (CLI whitelist + manager dispatch + lazy importer); the D0 refactor was wasted.

### Phase 3: Settings, YAML, and tests

**Goal:** Wire configuration and prove the contract end-to-end.

**Tasks:**
- Edit `mahavishnu/terminal/config.py`:
  - Add `goose_enabled`, `goose_http_host`, `goose_http_port=8694`, `goose_secret_key: SecretStr | None`, `goose_poll_interval=0.5`.
  - `@model_validator(mode="after") _goose_auth_required_when_enabled` rejects `goose_enabled=True` without a configured secret.
- Edit `settings/mahavishnu.yaml` (extend `terminal:` block) — `goose_enabled: false`, `goose_http_host`, `goose_http_port`, `goose_poll_interval`.
- Edit `settings/local.yaml.example` — comment block explaining operator setup (`goose serve --port 8694 --auth-token $GOOSE_SECRET` + `MAHAVISHNU_TERMINAL__GOOSE_SECRET_KEY`).
- Create `tests/unit/terminal/test_goose_adapter.py` — adapter contract tests (MockMcpResult-style mocks via `httpx2.MockTransport`).
- Create `tests/unit/terminal/test_goose_secret_redaction.py` — bearer redaction tests across all three error classes.
- Create `tests/unit/terminal/test_goose_session_id_uniqueness.py` — UUID4 vs short-format collision test (10K launches).

#### Integration Contract — Phase 3
- **Triggered from**: Oneiric config load (settings/mahavishnu.yaml + env vars); `mahavishnu mcp start`.
- **Returns to / updates**: `TerminalSettings.goose_*` fields populated; Oneiric auto-derived env vars `MAHAVISHNU_TERMINAL__GOOSE_*`.
- **Demonstrable by**: `python -c "from mahavishnu.terminal.config import TerminalSettings; t(goose_enabled=True)"` raises `ValidationError` (validator rejects missing secret); `mahavishnu mcp start --verbose` shows `Adapter: goose`.
- **Rollback signal**: `TerminalSettings(goose_enabled=True)` succeeds without a secret (validator regressed); `mahavishnu pool spawn` / `terminal switch-adapter goose` produces ImportError.
- **Observability added**: validator error includes the env-var name `MAHAVISHNU_TERMINAL__GOOSE_SECRET_KEY` so operators see the resolution path.
- **Knowledge transfer**: `SecretStr` is the contract; do not relax to `str` because the type-strip on `repr()` is the only thing keeping `dir()`/`vars()`/structured-log dumps from leaking the token. **If reverted**: the type-level guarantee is gone and any consumer that forgets to use `.get_secret_value()` will print the token by accident.

## 6. Required Code Changes

| Path | Change |
|------|--------|
| `mahavishnu/core/errors.py` | Extend with three error classes; extend `_REDACT_PATTERN`. |
| `mahavishnu/terminal/goose_client.py` | **new** — HTTP client + factory. |
| `mahavishnu/terminal/adapters/goose.py` | **new** — terminal adapter. |
| `mahavishnu/terminal/adapters/__init__.py` | Lazy import + factory registration. |
| `mahavishnu/terminal/config.py` | Extend `TerminalSettings` with Goose fields. |
| `settings/mahavishnu.yaml` | Extend `terminal:` block with Goose defaults. |
| `settings/local.yaml.example` | Comment block for operator opt-in. |
| `tests/unit/terminal/test_goose_adapter.py` | **new** — contract tests. |
| `tests/unit/terminal/test_goose_secret_redaction.py` | **new** — bearer redaction. |
| `tests/unit/terminal/test_goose_session_id_uniqueness.py` | **new** — UUID4 collision test. |

## 7. Validation Matrix

| Tool / command | Expected outcome | Evidence location |
|---|---|---|
| `pytest tests/unit/terminal/test_goose_adapter.py -v --no-cov` | 15 passed | local stdout |
| `pytest tests/unit/terminal/test_goose_secret_redaction.py -v --no-cov` | 7 passed | local stdout |
| `pytest tests/unit/terminal/test_goose_session_id_uniqueness.py -v --no-cov` | 5 passed | local stdout |
| `pytest tests/integration/test_audit_requirements.py -v -m integration` | reports `phantom_count=0` after this plan declares the requirements | local stdout |
| `python scripts/audit_requirements.py --json` | JSON has `declared_count=7` (REQ-GOO-001..007), `orphans=[]` | stdout |
| `mypy --strict mahavishnu/terminal/goose_client.py mahavishnu/terminal/adapters/goose.py` | no issues | local stdout |
| `pyright mahavishnu/terminal/goose_client.py mahavishnu/terminal/adapters/goose.py` | no errors (only `reportMissingTypeStubs` for `oneiric.core.logging`, expected) | local stdout |
| `python -c "from mahavishnu.terminal.adapters import list_adapter_names; assert 'goose' in list_adapter_names()"` | exit 0 | local stdout |

## 8. Risks

| Risk | Likelihood | Mitigation |
|------|-----------|-----------|
| Goose protocol drift (server returns different JSON shape than assumed) | Low | Adapter wraps `response.json()` and returns `result.get("output") or ""` for unknown shapes; `startup_probe()` returns a typed dict so callers see failures clearly. |
| Token leaks via dict-copy (e.g. `details.copy()`) | Low | `pydantic.SecretStr` plus `_redact_sensitive_details` redaction on `details` covers both `.details` access and free-form message strings. |
| Bearer exfiltration through httpx retry to misrouted DNS | Low | `event_hooks["response"]` redactor strips `Authorization` from `response.next_request` on every intermediate response. (REQ-GOO-003) |
| Goose binary not installed on operator host | High | `GooseUnavailable` carries `install_hint="Install Block's goose CLI: …"` in `details`; `startup_probe()` returns `{"ok": False, "reason": "unreachable", "install_hint": "..."}`. |
| 10K+ concurrent sessions → 8-char prefix collision | n/a (Goose is UUID4 by default) | REQ-GOO-005 — default `session_id_format="uuid"` (36-char UUID4); `"short"` is opt-in only. |
| Regression on existing terminal tests | Low | D3 inherits the D0 registry refactor; no edits to `manager.py`/`bootstrap.py`/`terminal_tools.py` are required. |

## 9. Decision Rule

This plan is "done enough" when:
1. All three new test files pass on `pytest --no-cov`.
2. `audit_requirements.py --json` reports `orphans: []` and `phantoms: []` for the new IDs.
3. `mypy --strict` and `pyright` report no issues on the new files.
4. `list_adapter_names()` includes `goose` and the factory constructs a valid adapter when `goose_enabled=true` + `goose_secret_key` are set.

Scope cuts if pressure forces:
- WebSocket streaming (v2 surface) is dropped — captured in §3 (Non-Goals). Reschedule when Goose ships WS.
- Per-session metrics/OTel counters are dropped — D3 inherits existing terminal-manager telemetry; explicit `mahavishnu.goose.adapter.*` counters are a follow-up.

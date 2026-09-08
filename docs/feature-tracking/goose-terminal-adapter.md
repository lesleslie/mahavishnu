---
name: goose-terminal-adapter
status: wired
date: 2026-09-07
last_reviewed: 2026-09-07
owner: Core Eng
role: canonical
---

# Feature: goose-terminal-adapter

**Owner:** Core Eng
**Created:** 2026-09-07
**Last updated:** 2026-09-07
**Repo(s):** /Users/les/Projects/mahavishnu

## State — pick one

- [ ] **built** (code merged, no callers wired)
- [x] **wired** (entry-point exists; integration contract executed end-to-end)
- [ ] **adopted** (in active use by ≥1 user/workflow/agent)

## Wiring checklist

- [x] Entry point registered (CLI command / MCP tool / FastAPI route / handler)
- [x] Trigger path identified (who calls this, and from where)
- [x] Returns / state updates land in expected destination
- [x] End-to-end smoke check documented (one command that proves it works)
- [x] Observability hook in place (log/metric/trace)
- [x] Rollback signal defined

## Built (yes/no)

\<yes — `mahavishnu/terminal/goose_client.py`, `mahavishnu/terminal/adapters/goose.py`, three new error classes in `mahavishnu/core/errors.py`, the `goose_*` settings fields in `mahavishnu/terminal/config.py`, and the YAML extensions in `settings/mahavishnu.yaml` / `settings/local.yaml.example` are merged on the main branch.>

## Wired (yes/no)

\<yes — `register_adapter("goose", _build_goose_adapter)` is called at module
import; `_build_goose_adapter` reads `config.goose_enabled`, `config.goose_http_host`,
`config.goose_http_port`, and `config.goose_secret_key`; falls back to
`MockTerminalAdapter` when `goose_enabled=False` (matching the Crow factory).
`list_adapter_names()` returns `('crow', 'goose', 'mock', 'tmux')`.>

## Trigger path

- `mahavishnu.terminal.adapters._build_goose_adapter(config, mcp_client)` is
  the canonical factory. Registered via `register_adapter("goose", ...)`
  on `import mahavishnu.terminal.adapters`.
- `mahavishnu.terminal.manager.TerminalManager.create(adapter_preference="goose")`
  looks up the factory via the D0 registry (`get_adapter_factory("goose")`)
  and constructs the adapter.
- Operator CLI: no new CLI subcommand — `mahavishnu mcp start` with
  `adapter_preference: "goose"` and `goose_enabled: true` in
  `settings/local.yaml` selects Goose end-to-end.
- Operator must run `goose serve --port 8694 --auth-token "$GOOSE_SECRET"`
  separately before starting `mahavishnu mcp start`.

## Integration point

- `mahavishnu.terminal.adapters._ADAPTER_REGISTRY["goose"]` — registry entry
  consumed by `TerminalManager.create` and `mcp/bootstrap._resolve_terminal_adapter`.
- `mahavishnu.terminal.config.TerminalSettings.goose_*` — config singleton
  loaded by Oneiric from `settings/mahavishnu.yaml` and
  `MAHAVISHNU_TERMINAL__GOOSE_*` env vars.
- `mahavishnu.core.errors.{GooseUnavailable, GooseAuthError, GooseTimeoutError}`
  — typed error surface consumed by the adapter.

## End-to-end check

```bash
# Unit tests prove the wiring contract:
uv run pytest tests/unit/terminal/test_goose_adapter.py \
                tests/unit/terminal/test_goose_secret_redaction.py \
                tests/unit/terminal/test_goose_session_id_uniqueness.py \
                -v --no-cov

# Registry self-registration:
uv run python -c \
  "from mahavishnu.terminal.adapters import list_adapter_names; \
   names = list_adapter_names(); \
   assert 'goose' in names, names; \
   print('OK', names)"

# Requirements traceability:
uv run python scripts/audit_requirements.py --json | jq '.summary'
# Expect: {declared_count: >=7, orphan_count: 0, phantom_count: 0}

# Manual smoke (operator run, not CI):
MAHAVISHNU_TERMINAL__GOOSE_SECRET_KEY="$(cat ~/.config/goose/auth-token)" \
  mahavishnu mcp start
# With adapter_preference: "goose" and goose_enabled: true in local.yaml,
# mahavishnu mcp status reports Adapter: goose.
```

If any of the above fails, the wiring does not exist.

## Blocker

None — feature is wired. Promotion to "adopted" requires at least one
real `goose serve` HTTP round-trip (launch a session, send a command,
capture output, close it) executed against a live `goose serve` subprocess.
That smoke lives outside the unit-test harness (requires `goose serve`
installed and reachable on the operator host) and is captured in the
plan's Phase 3 integration test as opt-in.

## Next action

- Run the manual smoke (above) on a host with `goose serve` running; confirm
  `mahavishnu.terminal.adapter=goose` is reported by `mahavishnu mcp status`.
- Promote to `adopted` once one real session launch + capture round-trip
  succeeds end-to-end and at least one production user/workflow/agent has
  dispatched through it.
- Capture a follow-up plan for the v2 Goose WebSocket streaming surface
  (`stream()` extension point at `mahavishnu/terminal/goose_client.py:215`).

## Related

- Plan: docs/plans/2026-09-07-goose-terminal-adapter.md
- Parent plan: /Users/les/.claude/plans/adaptive-hugging-mist.md
- Integration contract: docs/plans/2026-09-07-goose-terminal-adapter.md §5
  Phases 1-3 (one Integration Contract per phase)
- Audit evidence:
  - `python scripts/audit_requirements.py --json` → 0 orphans, 0 phantoms
  - `python scripts/audit_orphans.py` → unchanged from prior to D3

## How to save to Session-Buddy

After completing this file, persist a one-line summary to Session-Buddy
for cross-session retrieval by calling the Session-Buddy MCP tool
`store_reflection` with the following shape:

```python
mcp__session-buddy__store_reflection(
    content=(
        "Feature goose-terminal-adapter: state=wired, "
        "built=yes, wired=yes, "
        "blocker=none, "
        "next=manual smoke via `goose serve --port 8694 --auth-token …` + "
        "`mahavishnu mcp start` with adapter_preference=goose"
    ),
    tags=["feature-tracking", "goose-terminal-adapter", "wire-up-state"],
)
```

That call returns a reflection ID; paste that ID into the section below
so the long-form record and the searchable reflection stay linked.

## Session-Buddy

- Reflection ID: \<to be filled in after `store_reflection` call>
- Saved at: \<ISO timestamp from the call's response>

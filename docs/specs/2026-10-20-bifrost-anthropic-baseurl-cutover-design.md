---
status: draft
role: operational
kind: spec
date: 2026-10-20
last_reviewed: 2026-10-20
topic: bifrost-anthropic-baseurl-cutover
revision: v0.1
owner: platform-team
scope: the operational path from "Bifrost paused, Claude Code on direct MiniMax" to "Claude Code routed through Bifrost" and back, given the current macOS Gatekeeper blocker on `@maximhq/bifrost`'s native binary.
related:
  - docs/specs/2026-10-15-bifrost-gateway-wiring-design.md
  - docs/plans/2026-10-17-bifrost-oneiric-gateway-adapter.md
  - docs/plans/2026-10-19-bifrost-mcp-skills-aggregation.md
  - config/bifrost/README.md
  - scripts/bifrost-ctl
  - scripts/bifrost-toggle-claude-url
  - scripts/bifrost-gateway.py
  - scripts/audit_bifrost_callers.py
  - scripts/verify_qwen_bifrost_gate.sh
title: "Bifrost ↔ Claude Code ANTHROPIC_BASE_URL cutover — Spec v0.1"
---

# Bifrost ↔ Claude Code ANTHROPIC_BASE_URL cutover — Spec v0.1

> **TL;DR** — Today (2026-10-20) the Bifrost gateway on this Mac is **paused** because `@maximhq/bifrost`'s native binary is rejected by macOS Gatekeeper (`LC_VERSION_MIN_MACOSX sdk 10.4`, no `LC_BUILD_VERSION`). The cutover plumbing — `scripts/bifrost-ctl`, `scripts/bifrost-toggle-claude-url`, the LaunchAgent plist at `~/Library/LaunchAgents/ai.bifrost.gateway.plist`, and the config template at `config/bifrost/config.template.json` — is in place. Until the upstream `@maximhq/bifrost` ships a build that modern macOS accepts, the *plumbing exists* but the *gateway cannot bind* `127.0.0.1:8471`. Flipping `ANTHROPIC_BASE_URL` is therefore safe in one direction only: **toward Bifrost is a no-op** (the gateway is down, so Claude Code's first API call returns "connection refused" — Claude Code surfaces that to the user rather than silently falling back); the recovery direction back to direct is what we want to keep clean.

## 1. Outcome

After this spec lands:

1. The question *"is it safe to point Claude Code's `ANTHROPIC_BASE_URL` at Bifrost today?"* has a documented, runnable answer.
2. `scripts/bifrost_anthropic_url_cutover_smoke.py` exists as a runnable pre-flight that verifies the cutover *plumbing* without requiring the gateway to be live. Empty-PASS + zero FAILs = go; any FAIL = blocked, see logs.
3. The forward path is phased. Even after the gateway comes back, three stop-points separate "ready" from "Claude Code routed through it."

## 2. Current-state audit (2026-10-20)

| Component | State today | Source |
|---|---|---|
| Bifrost gateway runtime | **paused** (no listener on `:8471`) | `config/bifrost/README.md:7-13` |
| LaunchAgent plist | present in `~/Library/LaunchAgents/ai.bifrost.gateway.plist`, booted out 2026-06-26 | `config/bifrost/README.md:17` |
| Config store | `~/.config/bifrost/config.{json,db}` | `scripts/bifrost-gateway.py:42-44` |
| Mahavishnu LLM callers | direct to `https://api.minimax.io/{v1,anthropic}` | `CLAUDE.md` § "LLM Provider Configuration" |
| Claude Code (host) | direct to `https://api.minimax.io/anthropic` via `minimax-coding-plan-mcp` MCP server | `CLAUDE.md` § "Tool Preferences" |
| `bifrost-ctl start` | will fail at macOS Gatekeeper on `bifrost-http-0` | `config/bifrost/README.md:11-13`, `scripts/bifrost-ctl:110-128` |
| `bifrost-toggle-claude-url` | ready; would mutate `~/.claude/settings.json` if invoked | `scripts/bifrost-toggle-claude-url:78-100` |
| Routing rules in config | 5 rules (think, long-context, web-search, background, classify) | `config/bifrost/config.template.json:16-128` |
| Provider model set | `MiniMax-M3` primary, `MiniMax-M2.7` fallback, `qwen3-8b-q4_k_m` local | `config/bifrost/config.template.json:144-225`, `settings/models.yaml:28-48` |
| `audit_bifrost_callers.py` | ready; exits 0 today (every LLM caller is oneiric-routed or local-allowlisted per the v1.5 spec) | `scripts/audit_bifrost_callers.py` |
| `verify_qwen_bifrost_gate.sh` | ready; gates the Phase D Qwen cutover | `scripts/verify_qwen_bifrost_gate.sh` |
| `TestYAMLRoutingSync` guard | green; `DEFAULT_MINIMAX_ROUTING` and `settings/models.yaml` are pinned in sync | `tests/unit/test_task_router.py::TestYAMLRoutingSync` per `CLAUDE.md` |

## 3. Today's safety answer

**Yes — pointing Claude Code's `ANTHROPIC_BASE_URL` at Bifrost today cannot disable Claude Code's LLM access.** Reasoning:

- The gateway is paused. `127.0.0.1:8471` doesn't accept connections.
- `ANTHROPIC_BASE_URL` is read by Claude Code **once at session start**. With the URL pointed at a non-listening port, Claude Code's first API call will return `Connection refused` from the OS — Claude Code surfaces that to the user; it does **not** silently fall back to `https://api.anthropic.com`.
- `scripts/bifrost-toggle-claude-url bifrost` saves the prior `ANTHROPIC_BASE_URL` (if any) to `~/.config/bifrost/claude-url-backup.txt` *before* overwriting `~/.claude/settings.json` (per `scripts/bifrost-toggle-claude-url:67-76`). Recovery is one command: `python scripts/bifrost-toggle-claude-url direct`.
- Restarting Claude Code *without* the env var restores the default Anthropic endpoint. There is no global, persistent loss of model access from this env var.

The one tool we'd run to convince ourselves: `python scripts/bifrost_anthropic_url_cutover_smoke.py`. It does not mutate `~/.claude/settings.json` — it dry-runs the toggle in both directions and reports the gateway port's bind state.

## 4. Reactivation gate (when `@maximhq/bifrost` becomes usable again)

To flip the gateway from paused to live on this Mac, ALL of these must hold:

1. **Upstream fix landed** — `@maximhq/bifrost` ships a native binary whose `LC_BUILD_VERSION` (or `LC_VERSION_MIN_MACOSX >= 11.0`) is acceptable to modern macOS Gatekeeper. Until this is true, every other gate below is moot.
2. **Optional ad-hoc codesign workaround** — if the upstream fix is delayed and the operator accepts the friction: `codesign --force --sign - ~/Library/Caches/bifrost/<version>/bin/bifrost-http-0` (per `config/bifrost/README.md:236`). Unblocks manual launches but does not survive `bifrost-ctl rebootstrap` (which re-extracts the cache).
3. **Ready file written** — `~/.local/state/mcp/ready/bifrost.ready` exists. The `bifrost-gateway.py` launcher writes this only after `lsof` confirms the listener (per `scripts/bifrost-gateway.py:178-193`).
4. **Port bound** — `lsof -tiTCP:8471 -sTCP:LISTEN` returns a PID.
5. **Health endpoint live** — `curl -fsS http://127.0.0.1:8471/health` returns `{"status":"ok",...}` JSON. The v1.5 spec records `{"components":{"db_pings":"ok"},"status":"ok"}` from 2026-10-15.
6. **`bifrost.log` structurally sane** — emits JSON lines. The launcher wraps with `stdbuf -oL -eL` (per `scripts/bifrost-gateway.py:87-117`); macOS without `coreutils` falls back to block-buffered output. The e2e tests already absorb the 15s window per `docs/specs/2026-10-15-bifrost-gateway-wiring-design.md:518`.

When all six hold, `scripts/bifrost-ctl start` brings the gateway up and (after the ready file is written, within a 60s window) calls `bifrost-toggle-claude-url bifrost` to flip CC's base URL. Restart Claude Code for the new URL to take effect (per `scripts/bifrost-toggle-claude-url:18-22`).

## 5. Forward cutover phases (after Bifrost is live)

Three independent stop-points. Each failure rolls back without disturbing the next.

### Phase A — pre-flight (no env change)

- Run `python scripts/bifrost_anthropic_url_cutover_smoke.py` → exit 0, zero FAILs.
- Run `python scripts/audit_bifrost_callers.py` → exit 0.
- Confirm `MINIMAX_API_KEY` is exported per `feedback-credentials-source-secrets-env`.

### Phase B — sandboxed Claude Code pilot

- `python scripts/bifrost-toggle-claude-url bifrost` to flip CC's URL.
- Launch a fresh Claude Code instance inside `/tmp/claude-bifrost-smoke/` (a scratch cwd, no real work).
- Run three task types:
  1. Single file `Read` against a real file in the scratch dir.
  2. A small `Edit` followed by a `Bash` invocation.
  3. A single-tool subagent dispatch via `mcp__mahavishnu__dispatch_to_pool` with `caller_kind=claude_code`.
- Watch for: tool-dispatch latency spikes (>3× direct), tool-result truncation, hang-on-first-tool. Any of these = roll back (see §6).
- Confirm `caller_id` lines appear in `~/.local/state/mcp/logs/bifrost.log` via `grep '"caller_id":"claude-code"'`.

### Phase C — production CC over Bifrost (only if Phase B passes)

- `bifrost-ctl rebootstrap` to refresh `~/.config/bifrost/config.db` against the latest `config/bifrost/config.template.json`.
- Re-run the Phase A smoke (`rebootstrap` resets routing rules; per `config/bifrost/README.md:154-160`, after `config_store` is enabled, edits to `config.json` no longer take effect).
- Promote CC out of `/tmp` and back to real work.

Each Phase is independent. Do not collapse them.

## 6. Rollback (kill switch)

Three independent revert paths. Pick whichever is fastest:

**a) Via the toggle helper** (preserves backup):

```bash
python scripts/bifrost-toggle-claude-url direct
# Restores the saved ANTHROPIC_BASE_URL from ~/.config/bifrost/claude-url-backup.txt
# Then restart Claude Code
```

**b) Via `bifrost-ctl stop`** (also tears down the gateway):

```bash
scripts/bifrost-ctl stop
# Same direct action, then bootouts the launchd job and kill the listener
```

**c) By hand** (always works):

```bash
unset ANTHROPIC_BASE_URL          # if exported in the parent shell
# OR
$EDITOR ~/.claude/settings.json    # remove env.ANTHROPIC_BASE_URL
# Then restart Claude Code
```

**Kill-switch property**: every path ends with "restart Claude Code." Claude Code never silently falls back; the operator sees the URL state at session start and can intervene.

## 7. Integration Contract

**Triggered from**: operator command — `scripts/bifrost-ctl {start,stop,restart,rebootstrap}` or `python scripts/bifrost-toggle-claude-url {bifrost,direct,status}`.

**Returns to**: the gateway lifecycle (running or stopped) and the `~/.claude/settings.json:env.ANTHROPIC_BASE_URL` value.

**Demonstrable by**:

- `python scripts/bifrost_anthropic_url_cutover_smoke.py` → exit 0 + zero FAILs.
- `python scripts/audit_bifrost_callers.py` → exit 0.
- `curl -fsS http://127.0.0.1:8471/health` (gateway up) → `{"status":"ok",...}`.
- `grep '"caller_id":"claude-code"' ~/.local/state/mcp/logs/bifrost.log | tail -1` returns a recent line within a Phase B pilot's run.

**Rollback signal**: any Phase B failure → invoke §6 path (a). Per `mcp-backend-wiring-discipline.md`, gateway `/health` returning non-200 in steady state is a degraded feed and propagates to `mahavishnu_health_feed_status{feed="bifrost",status="degraded"}`.

**Observability added**: the smoke script's per-check report lines are the dashboardable signal in this session. Long-term, the v1.5 spec's Phase E deliverable (`mahavishnu metrics bifrost`) becomes the live surface.

## 8. Related work not affected by this spec

- **In-repo LLM callers** (`mahavishnu/engines/agno_adapter_impl.py`, `mahavishnu/workers/cloud_worker.py`, `mahavishnu/workers/capabilities/_probes.py`) route through oneiric per the v1.5 spec / 2026-10-17 plan. They flow through Bifrost when `bifrost.enabled: true` (currently `false`). **None of this moves when Claude Code's own `ANTHROPIC_BASE_URL` flips** — host CC vs. spawned workers are independent surfaces per `docs/specs/2026-10-15-bifrost-gateway-wiring-design.md:39`.
- **`MAHAVISHNU_BIFROST__*` env-var back-compat shim** (planned) and the deleted **`BIFROST_BASE_URL` env var** (per the v1.5 spec, Phase F cleanup) are separate from CC's session-level `ANTHROPIC_BASE_URL`.
- **PiPool** env-allowlist strips `MAHAVISHNU_*` / `BIFROST_*` keys per `mahavishnu/pools/pi_pool.py` so Pi subprocesses cannot leak Bifrost creds — unaffected by CC's base URL.

## 9. References

- `docs/specs/2026-10-15-bifrost-gateway-wiring-design.md` — the upstream design spec (v1.5, Phase G)
- `docs/plans/2026-10-17-bifrost-oneiric-gateway-adapter.md` — the oneiric-router consolidation
- `config/bifrost/README.md` — canonical "current state: paused" record (`LC_VERSION_MIN_MACOSX sdk 10.4` Gatekeeper rejection)
- `scripts/bifrost-ctl` — orchestrator (install/start/stop/restart/rebootstrap/status/tail/foreground)
- `scripts/bifrost-toggle-claude-url` — CC URL rewriter (bifrost/direct/status + idempotent backup)
- `scripts/bifrost-gateway.py` — Python launcher resolving Oneiric secrets before spawning `@maximhq/bifrost`
- `scripts/audit_bifrost_callers.py` — cross-repo caller audit (REQ-BIFROST-013)
- `scripts/verify_qwen_bifrost_gate.sh` — Phase D Qwen routing gate
- `mahavishnu/CLAUDE.md` § "Tool Preferences" — the Claude-Code-default direct-to-MiniMax contract
- `~/.claude/settings.json`, `~/.config/bifrost/config.{json,db}`, `~/.config/bifrost/claude-url-backup.txt` — runtime state files
- `feedback-bodai-push-is-user-controlled.md` — push is user-controlled; the operator runs `git push` from their shell
- `feedback-credentials-source-secrets-env.md` — credentials live in `~/.config/secrets.env`, sourced at use-time

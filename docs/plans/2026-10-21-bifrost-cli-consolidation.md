---
status: draft
role: implementation
kind: plan
date: 2026-10-21
last_reviewed: 2026-10-21
superseded_by: null
topic: bifrost-cli-consolidation
title: "Bifrost CLI Consolidation — one Typer app replacing seven scripts"
---

## 1. Outcome

`mahavishnu bifrost <command>` replaces the seven standalone Bifrost scripts
with a single wired CLI surface. Success is: `mahavishnu bifrost --help` lists
every capability, `scripts/` contains no `bifrost*` files, and no reference to
a retired script path remains in code, tests, plist, or docs.

## 2. Goals

1. One Typer sub-app, `mahavishnu bifrost`, carrying the full lifecycle,
   toggle, policy, smoke, and verify surface.
2. Deduplicate the two near-identical toggle scripts into one
   harness-parameterised implementation (they are ~95% the same).
3. Teach both toggles to write the virtual-key credential
   (`ANTHROPIC_CUSTOM_HEADERS` / `customHeaders`), so neither harness
   reproduces the `401 virtual key is required` failure.
4. Close the gate hole: `BIFROST_CTL_NO_CC_URL_REWRITE` is enforced in the
   one code path, not duplicated across a shell wrapper and a Python helper.
5. Wire the result into `_main_cli.py`, `docs/CLI_REFERENCE.md`, and the
   LaunchAgent plist so nothing becomes an orphan.

## 3. Non-Goals

1. **Not** maintaining a localhost-only restriction on either harness. The
   protocol driver for it turned out to be false — see §4.1. Both harnesses can
   present a virtual key, so both may target a remote gateway.
2. **Not** disabling virtual-key enforcement. Enforcement stays ON.
3. **Not** changing Bifrost provider configuration, model routing, or keys.
4. **Not** changing what Bodai/Oneiric workers do — they already speak custom
   HTTP and are untouched by this plan.
5. **Not** rewriting the gateway wrapper's process supervision semantics; it is
   relocated, not redesigned.

## 4. Current Findings

### 4.1 Claude Code CAN send a virtual key (corrects an earlier finding)

`ANTHROPIC_CUSTOM_HEADERS` is a documented Claude Code setting — `Name: Value`,
newline-separated. Requires ≥ 2.1.227; this host runs **2.1.307**.
Confirmed against the running gateway: `x-bf-vk: <value>` is the header Bifrost
reads, and a deliberately invalid value produces
`access not found. The provided credential does not exist or has been revoked`
rather than `virtual key is required`.

A prior draft of this plan concluded the opposite, on the basis that Claude
Code sends only `Authorization: Bearer` or `x-api-key`. That inference checked
Bifrost's reader but not Claude Code's writer. **Correction accepted.**

Related settings in the same family: `CLAUDE_CODE_GATEWAY_HINT_HEADERS`,
`CLAUDE_CODE_EXTRA_BODY`, `CLAUDE_CODE_PROPAGATE_TRACEPARENT`.

### 4.2 Qwen Code can also send a virtual key

`QwenLM/qwen-code` `docs/users/configuration/settings.md` documents
`customHeaders` ("useful for request tracing, monitoring, **API gateway
routing**, or when different models require different headers"), with
`${session_id}` dynamic expansion and an `anthropic` transport.

### 4.3 The toggle scripts are near-duplicates

`bifrost-toggle-qwen-url`'s own docstring: *"Mirrors
`scripts/bifrost-toggle-claude-url` so the two tools have a matching shape for
ops convenience."* Both implement the same
`bifrost` / `direct` / `status` state machine over a settings file, differing
only in path, env-var name, and URL shape. One parameterised implementation
replaces both.

### 4.4 Neither toggle writes a credential

Both write only a base URL. Neither references `x-bf-vk`, `customHeaders`, or
any credential. So each harness, once pointed at a Bifrost with enforcement on,
reproduces the 401. This is the actual defect observed on 2026-10-21.

### 4.5 The gate is enforced in the wrong layer

```
BIFROST_CTL_NO_CC_URL_REWRITE occurrences:
  scripts/bifrost-ctl               → 3   (guarded)
  scripts/bifrost-toggle-claude-url → 0   (unguarded side door)
```

Observed consequence: after a successful toggle, `ANTHROPIC_BASE_URL` reverted
to MiniMax **and** the backup file was deleted — exactly the helper's `direct`
action — while the gate was set. Only a direct helper call produces that pair.

### 4.6 The operator has no first-class CC-URL verb

`bifrost-ctl` exposes `{install|sync-config|start|stop|restart|rebootstrap|status|tail|foreground}`.
The CC URL is a derivative of gateway lifecycle — `start` rewrites it only
after `wait_for_ready_file 60` succeeds, which is sound readiness gating — but
there is no way to set it without also restarting the gateway. That gap is
what forces operators onto the unguarded helper.

### 4.7 Seven Bifrost scripts

`bifrost-ctl` (zsh), `bifrost-gateway.py`, `bifrost-toggle-claude-url`,
`bifrost-toggle-qwen-url`, `bifrost-auth-policy`,
`bifrost_anthropic_url_cutover_smoke.py`, `bifrost_qwen_url_cutover_smoke.py`,
plus `verify_qwen_bifrost_gate.sh`. The two smoke scripts are themselves
duplicates (same `is_bifrost_url` / `read_settings_url` / `port_bound` /
`dry_run_toggle` helpers, different harness constants).

### 4.8 Referenced from

`pyproject.toml`, `settings/mahavishnu.yaml`,
`config/launchd/ai.bifrost.gateway.plist`, `config/bifrost/README.md`,
`tests/unit/test_bifrost_gateway_stdbuf.py`,
`tests/unit/test_terminal_worker_settings.py`,
`tests/integration/test_bifrost_routing_e2e.py`, and four docs.

## 4.5 Requirements

```yaml
requirements:
  - id: REQ-BIFROST-024
    title: "Single Typer sub-app exposes all Bifrost capabilities"
  - id: REQ-BIFROST-025
    title: "Toggle implementation is harness-parameterised, not duplicated"
  - id: REQ-BIFROST-026
    title: "Claude toggle writes ANTHROPIC_CUSTOM_HEADERS with x-bf-vk"
  - id: REQ-BIFROST-027
    title: "Qwen toggle writes modelProviders customHeaders with x-bf-vk"
  - id: REQ-BIFROST-028
    title: "Virtual key resolved from env/flag, never hardcoded in settings"
  - id: REQ-BIFROST-029
    title: "BIFROST_CTL_NO_CC_URL_REWRITE enforced in the single toggle path"
  - id: REQ-BIFROST-030
    title: "LaunchAgent plist invokes the migrated gateway module"
  - id: REQ-BIFROST-031
    title: "Smoke checks are harness-parameterised"
  - id: REQ-BIFROST-032
    title: "No references to retired script paths remain"
```

## 5. Implementation Phases

### Phase 1: `mahavishnu/bifrost/` package skeleton + toggle core

**Goal:** one harness-parameterised toggle replacing both scripts.

**Tasks:** new package `mahavishnu/bifrost/` with `models.py` (harness
descriptor: settings path, url env-var, URL shape, credential sink) and
`toggles.py` (the `bifrost`/`direct`/`status` state machine). Gate check lives
here and nowhere else.

**Exit criteria:** `mahavishnu bifrost cc-url status` and
`mahavishnu bifrost qwen-url status` both report current state without a
gateway restart.

#### Integration Contract

- **Triggered from**: `mahavishnu bifrost {cc,qwen}-url {bifrost,direct,status}`.
- **Returns to / updates**: `~/.claude/settings.json` `env.ANTHROPIC_BASE_URL`
  and `env.ANTHROPIC_CUSTOM_HEADERS`; `~/.qwen/settings.json`
  `env.OPENAI_BASE_URL` and `modelProviders[].generationConfig.customHeaders`;
  backups at `~/.config/bifrost/{claude,qwen}-url-backup.txt`.
- **Demonstrable by**: `mahavishnu bifrost cc-url bifrost --dry-run` prints the
  two keys it would write and exits without mutating.
- **Rollback signal**: `mahavishnu bifrost {cc,qwen}-url status` reporting
  `Bifrost` while the operator intended `direct` — the backup file is the undo.
- **Observability added**: structured line
  `bifrost-toggle harness=<cc|qwen> action=<…> result=written|refused|skipped-gate|noop`.

### Phase 2: lifecycle commands ported from `bifrost-ctl`

**Goal:** start/stop/restart/status/foreground/tail/install/sync-config/rebootstrap
in Python, preserving readiness-gated URL rewriting.

**Tasks:** `mahavishnu/bifrost/lifecycle.py` mirroring the zsh semantics
exactly — including that `start` rewrites the harness URL only after the ready
file appears, and that `stop`/`foreground`'s EXIT trap restores `direct`.
Retire `bifrost-ctl` and `bifrost-gateway.py`.

**Exit criteria:** `mahavishnu bifrost restart` brings the gateway up and
leaves the harness URL matching `bifrost-auth-policy`'s verdict path.

#### Integration Contract

- **Triggered from**: `mahavishnu bifrost {start,stop,restart,rebootstrap,status,tail,foreground,install,sync-config}`.
- **Returns to / updates**: `~/Library/LaunchAgents/ai.bifrost.gateway.plist`,
  launchd `gui/$UID` service state, `~/.local/state/mcp/ready/bifrost.ready`,
  log tails, and (via Phase 1) harness settings.
- **Demonstrable by**: `mahavishnu bifrost status` →
  `state = running` plus a `pid =` line and the harness URL verdict.
- **Rollback signal**: ready file absent after the 60 s budget → harness URL
  left untouched and a warning emitted, matching current behaviour.
- **Observability added**: existing `bifrost.log` / `bifrost.err` streams plus
  `bifrost-lifecycle action=<…> result=<…>`.

### Phase 3: credential wiring (the actual 401 fix)

**Goal:** both toggles emit the virtual key so neither harness 401s.

**Tasks:** read the VK from `BIFROST_VIRTUAL_KEY` (or `--virtual-key-file`);
never inline a literal. `cc-url` writes
`env.ANTHROPIC_CUSTOM_HEADERS="x-bf-vk: <vk>"`; `qwen-url` writes
`modelProviders[<entry>].generationConfig.customHeaders["x-bf-vk"]`.

**Exit criteria:** with enforcement ON, a request from each harness returns a
provider response, not `virtual key is required`.

#### Integration Contract

- **Triggered from**: `mahavishnu bifrost {cc,qwen}-url bifrost`.
- **Returns to / updates**: the credential key named above; the value is read
  from env at write time and never persisted in plaintext settings beyond what
  the harness requires.
- **Demonstrable by**: `mahavishnu bifrost smoke --harness both` exits `0` with
  enforcement on, having received no 401.
- **Rollback signal**: a `401` in `bifrost.log` with `virtual key is required`
  means the credential key was written to the wrong sink — re-run the toggle
  with `--harness` explicitly.
- **Observability added**: `bifrost-toggle harness=<…> credential=written` with
  the value redacted.

### Phase 4: policy, smoke, verify + deprecation

**Goal:** retire every remaining script and clear dangling references.

**Tasks:** port `bifrost-auth-policy` → `mahavishnu bifrost policy
{check,enforce}`; merge the two smoke scripts → `mahavishnu bifrost smoke
[--harness claude|qwen|both]`; port `verify_qwen_bifrost_gate.sh` → `mahavishnu
bifrost verify-gate`. Delete all seven scripts. Update plist, `pyproject.toml`,
`settings/mahavishnu.yaml`, `config/bifrost/README.md`, the three test
modules, and `docs/CLI_REFERENCE.md`.

**Exit criteria:** `ls scripts/bifrost*` returns nothing;
`grep -rn "bifrost-ctl\|bifrost-toggle-\|bifrost-gateway.py" .` returns no hits
outside this plan and the deprecation note.

#### Integration Contract

- **Triggered from**: `mahavishnu bifrost {policy,smoke,verify-gate}`.
- **Returns to / updates**: `docs/CLI_REFERENCE.md`;
  `config/launchd/ai.bifrost.gateway.plist` `ProgramArguments`.
- **Demonstrable by**: `.venv/bin/pytest tests/unit/test_bifrost_*.py -q` passes
  after migration with test module paths updated.
- **Rollback signal**: plist `ProgramArguments` pointing at a deleted path —
  the LaunchAgent fails to load and `mahavishnu bifrost status` reports
  `service not loaded`.
- **Observability added**: none beyond Phase 2 (consolidation phase).

## 6. Required Code Changes

**New**

- [ ] `mahavishnu/bifrost/__init__.py`
- [ ] `mahavishnu/bifrost/models.py` — `HarnessDescriptor`
- [ ] `mahavishnu/bifrost/toggles.py` — shared state machine + gate
- [ ] `mahavishnu/bifrost/lifecycle.py` — port of `bifrost-ctl`
- [ ] `mahavishnu/bifrost/gateway.py` — port of `bifrost-gateway.py`
- [ ] `mahavishnu/bifrost/policy.py` — port of `bifrost-auth-policy`
- [ ] `mahavishnu/bifrost/smoke.py` — merge of both smoke scripts
- [ ] `mahavishnu/bifrost/cli.py` — Typer `bifrost_app`
- [ ] `mahavishnu/bifrost/verify.py` — port of `verify_qwen_bifrost_gate.sh`

**Modified**

- [ ] `mahavishnu/_main_cli.py` — `app.add_typer(bifrost_app, name="bifrost")`
- [ ] `config/launchd/ai.bifrost.gateway.plist` — `ProgramArguments`
- [ ] `settings/mahavishnu.yaml` — script path references
- [ ] `pyproject.toml` — script references
- [ ] `config/bifrost/README.md` — usage rewritten against the CLI
- [ ] `docs/CLI_REFERENCE.md` — add `bifrost` section
- [ ] `tests/unit/test_bifrost_gateway_stdbuf.py` — new import path
- [ ] `tests/unit/test_terminal_worker_settings.py` — new import path
- [ ] `tests/integration/test_bifrost_routing_e2e.py` — new import path

**Deleted**

- [ ] `scripts/bifrost-ctl`
- [ ] `scripts/bifrost-gateway.py`
- [ ] `scripts/bifrost-toggle-claude-url`
- [ ] `scripts/bifrost-toggle-qwen-url`
- [ ] `scripts/bifrost-auth-policy`
- [ ] `scripts/bifrost_anthropic_url_cutover_smoke.py`
- [ ] `scripts/bifrost_qwen_url_cutover_smoke.py`
- [ ] `scripts/verify_qwen_bifrost_gate.sh`

## 7. Validation Matrix

| Tool / command | Expected outcome | Evidence location |
|---|---|---|
| `mahavishnu bifrost --help` | lists lifecycle + url + policy + smoke + verify | terminal |
| `mahavishnu bifrost cc-url status` | URL + backup state | terminal |
| `BIFROST_CTL_NO_CC_URL_REWRITE=1 mahavishnu bifrost cc-url bifrost` | no-op (gate) | terminal |
| `mahavishnu bifrost restart` | gateway running; harness URL = Bifrost | terminal + `bifrost.log` |
| `mahavishnu bifrost smoke --harness both` | exit `0`, no 401 | `bifrost.log` |
| `mahavishnu bifrost policy enforce` | verdict line + exit code | terminal |
| `ls scripts/bifrost*` | empty | terminal |
| `.venv/bin/pytest tests/unit/test_bifrost_*.py -q` | pass | terminal |
| `crackerjack run -v` | pass (merge gate) | terminal |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Lifecycle port regresses readiness gating — harness URL repointed at a gateway that never came up | Medium | Port the `wait_for_ready_file` semantics verbatim; smoke test asserts URL only flips after readiness |
| Plist `ProgramArguments` left pointing at a deleted script, breaking the LaunchAgent on next login | Medium | Phase 4 exit criterion greps for retired paths; `bifrost status` reports `service not loaded` |
| A real virtual key is committed into `settings.json` or a settings file under version control | Low | `BIFROST_VIRTUAL_KEY` env indirection (REQ-BIFROST-028); `.gitignore` audit for `~/.qwen/settings.json` check-in patterns |
| Deduplicating the toggles silently changes Qwen's env-var override (`--env-var` / `BIFROST_QWEN_ENV_VAR`) | Low | `HarnessDescriptor` keeps the override as a field; regression test per harness |
| Gate enforcement moves and some other caller relied on bypassing it | Low | Single grep sweep in Phase 4; the one known caller was the bug itself (§4.5) |

## 9. Decision Rule

Done when `mahavishnu bifrost --help` covers every capability of all seven
scripts, `ls scripts/bifrost*` is empty, no retired path is referenced, and
both harnesses complete a request through Bifrost **with virtual-key
enforcement still on**. Documentation polish may slip; the credential path
(Phase 3) and the reference sweep (Phase 4) may not.

## References

- `docs/specs/2026-10-20-bifrost-anthropic-baseurl-cutover-design.md`
- `docs/specs/2026-10-15-bifrost-gateway-wiring-design.md`
- `docs/decisions/wire-up-contract.md`
- `config/bifrost/README.md`
- Claude Code env-vars docs — `ANTHROPIC_CUSTOM_HEADERS` (≥ 2.1.227)
- `QwenLM/qwen-code` — `docs/users/configuration/settings.md` (`customHeaders`)

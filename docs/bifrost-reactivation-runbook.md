# Bifrost Reactivation Runbook

Date: 2026-04-09 (last updated 2026-06-26)

> ## Status: Paused indefinitely (2026-06-26)
>
> As of 2026-06-26, Bifrost is paused indefinitely. The upstream
> `@maximhq/bifrost` npm package's native binary has Mach-O metadata
> (`LC_VERSION_MIN_MACOSX sdk 10.4`, no `LC_BUILD_VERSION`) that modern
> macOS strict-validators and Gatekeeper reject. Ad-hoc signing the
> binary fails with `main executable failed strict validation` (v1.6.0)
> or is accepted by codesign but still rejected by `spctl` (v1.5.16).
> `npx -y @maximhq/bifrost@<ver>` does not help — `bin.js` hardcodes the
> same `~/Library/Caches/bifrost/v1.6.0/bin/bifrost-http-0` path
> regardless of package version.
>
> This runbook remains for the day the upstream build pipeline ships a
> properly-signed, modern-Mach-O binary. Until then, do not attempt to
> reactivate Bifrost; clients should be left on direct provider
> endpoints.

## Purpose

This runbook brings the local Bifrost gateway back from dormant state into a usable localhost-only deployment.

Use it when:

- the upstream `@maximhq/bifrost` npm package ships a properly-signed,
  modern-Mach-O native binary (the blocker as of 2026-06-26)
- you switch from subscription-backed coding tools to API-billed usage
- you want routing, exact-match cache, and optional semantic cache
- you want a reproducible way to reinstall the macOS LaunchAgents

Do not use it while your main traffic still depends on subscription-only endpoints.

## Current Dormant State

As of 2026-06-26:

- source launchd plists still exist in the repo:
  - `config/launchd/ai.bifrost.gateway.plist`
  - `config/launchd/ai.bifrost.redis-stack.plist`
- installed copies in `~/Library/LaunchAgents/` were booted out on
  2026-06-26; the `.plist` files were kept for future reactivation
- live user configs for Codex, Claude Code, Qwen, and OpenClaw were
  reverted to direct provider endpoints; Nanobot is retired
- Claude Code `ANTHROPIC_BASE_URL` is `https://api.minimax.io/anthropic`
  (direct)
- Mahavishnu worker code has zero Bifrost opt-in references — workers
  are fully native already
- Bifrost and the dedicated Redis Stack cache are not expected to
  auto-start on reboot

## Claude Code URL Toggle

`bifrost-ctl start` and `bifrost-ctl stop` now flip Claude Code's
`ANTHROPIC_BASE_URL` in `~/.claude/settings.json` so Claude Code points at
Bifrost while the gateway is up and at its prior endpoint while it is down.

Behavior:

- `start` (and `restart`, `rebootstrap`) waits up to 60 s for the
  `~/.local/state/mcp/ready/bifrost.ready` file before flipping Claude onto
  the gateway. If the ready file never appears, Claude's URL is left alone.
- `stop` flips Claude onto its prior URL *first*, then tears down the gateway.
  That avoids a window where Claude is still pointed at Bifrost while the
  listener is gone.
- `status` prints which URL Claude is currently configured with and whether
  the prior-value backup exists.
- The toggle is idempotent. Re-running any action with the file already in
  the matching state is a no-op.
- The toggle never overwrites a URL it did not set itself. If Claude's
  `ANTHROPIC_BASE_URL` is something hand-written (not the Bifrost URL), `stop`
  leaves it alone rather than guessing the user's true default.

**Important caveat:** Claude Code reads `settings.json` once per session.
Editing the file does not reconfigure a running Claude Code session — restart
Claude Code after toggling for the change to take effect.

The prior URL is saved to `~/.config/bifrost/claude-url-backup.txt` while
Bifrost is active and removed on stop. The helper itself is
`scripts/bifrost-toggle-claude-url`; you can also call it directly:

```zsh
./scripts/bifrost-toggle-claude-url bifrost    # point Claude at Bifrost
./scripts/bifrost-toggle-claude-url direct     # restore prior URL
./scripts/bifrost-toggle-claude-url status     # show current state
./scripts/bifrost-toggle-claude-url --dry-run bifrost   # preview, no changes
```

## Operational Gotchas

### Run with foreground when launchd-managed start fails on Gatekeeper

If `bifrost-ctl start` (LaunchAgent path) fails because macOS Gatekeeper rejects
the unsigned `@maximhq/bifrost` native binary, run the gateway wrapper directly
in a Terminal session:

```zsh
./scripts/bifrost-ctl foreground
```

This bypasses launchd entirely. The script:

1. Kills any orphan listener on 8471.
1. Runs `scripts/bifrost-gateway.py` (using the project's venv python) in this
   shell as a background process.
1. Waits up to 60 s for the ready file. If it appears, flips Claude Code's
   `ANTHROPIC_BASE_URL` onto Bifrost (saving the prior URL).
1. Waits for the wrapper to exit (press Ctrl-C to stop Bifrost).
1. On any exit (Ctrl-C, error, normal completion), an `EXIT` trap restores
   Claude Code's prior URL and removes the ready file.

The downside: the gateway only runs as long as your Terminal session does.
Closing the terminal kills Bifrost. Acceptable when you only need it for one
working session.

> Note: foreground execution does **not** by itself bypass Gatekeeper. macOS
> Sonoma+ will reject the unsigned `bifrost-http-0` Go binary even from a
> foreground shell. If foreground also fails with `Unknown system error -88`,
> try the v1.5.16 symlink workaround below.

### EACCES on the Bifrost native binary

The npm package `@maximhq/bifrost` downloads its native Go binary into
`~/Library/Caches/bifrost/<version>/bin/bifrost-http-0`. Some extractions land
without the execute bit; the launch wrapper will then fail with:

```
Failed to start Bifrost. Error: spawnSync .../bifrost-http-0 EACCES
```

Fix:

```zsh
chmod +x ~/Library/Caches/bifrost/v1.6.0/bin/bifrost-http-0
./scripts/bifrost-ctl start
```

Audit all cached versions at once:

```zsh
for v in v1.5.0-prerelease1 v1.5.0-prerelease2 v1.5.16 v1.6.0; do
  for f in ~/Library/Caches/bifrost/$v/bin/*; do
    [[ -e "$f" ]] || continue
    [[ "$(stat -f '%Sp' "$f")" == *"x"* ]] || echo "MISSING +x: $f"
  done
done
```

### Gatekeeper rejection of an unsigned native binary

If the chmod is in place but `bifrost-ctl start` still fails after 60 s, the
next layer is macOS Gatekeeper. The npm package extracts the Go binary
**unsigned**; when a LaunchAgent-spawned process tries to `spawnSync` it,
Gatekeeper refuses with `ENOTSUP` (Go's `-88`):

```text
Failed to start Bifrost. Error: spawnSync .../bifrost-http-0 Unknown system error -88
codesign -dv .../bifrost-http-0
  → code object is not signed at all
spctl --assess --verbose .../bifrost-http-0
  → rejected (source=no usable signature)
```

The same binary typically runs fine from a foreground shell (Gatekeeper is
more permissive in interactive contexts); the failure only surfaces under
launchd. This is why older cached versions that "used to work" may also fail
now — the policy on LaunchAgent-spawned unsigned binaries tightened.

Fix (manual, not automated): ad-hoc sign the binary so Gatekeeper sees a
valid self-attested signature. This is the standard remedy for unsigned CLI
binaries distributed without a developer signature.

```zsh
codesign --force --sign - ~/Library/Caches/bifrost/v1.6.0/bin/bifrost-http-0
codesign -v ~/Library/Caches/bifrost/v1.6.0/bin/bifrost-http-0     # prints nothing on success
spctl --assess --verbose ~/Library/Caches/bifrost/v1.6.0/bin/bifrost-http-0   # should say "accepted"
./scripts/bifrost-ctl start
```

If a future npm extraction replaces the binary, the signature is lost and
the fix must be reapplied. `bifrost-gateway.py` does not auto-sign; that's a
deliberate policy choice (the wrapper should not silently bypass Gatekeeper).

### v1.6.0 binary can't be ad-hoc signed (structural Mach-O issue)

If `codesign --force --sign -` returns `main executable failed strict validation`, the binary has Mach-O metadata that Apple's strict validator
rejects. Inspect the load commands:

```zsh
otool -l ~/Library/Caches/bifrost/v1.6.0/bin/bifrost-http-0 | grep -E "LC_BUILD_VERSION|LC_VERSION_MIN|sdk "
# Expected on a properly-built binary:
#       cmd LC_BUILD_VERSION
#       sdk 14.x
# If you see only `LC_VERSION_MIN_MACOSX` with `sdk 10.4`, the binary was
# cross-compiled from Linux without the modern macOS version tag.
```

The cached `v1.5.16/bin/bifrost-http-0` has the same metadata and signs
successfully with `codesign --force --sign -`, but Gatekeeper (`spctl`)
still rejects it under macOS Sonoma+. All current npm releases
(`1.6.0`–`1.6.3`) hardcode the binary path
`~/Library/Caches/bifrost/v1.6.0/bin/bifrost-http-0` regardless of the
package version, so re-downloading via `npx -y @maximhq/bifrost@<ver>`
does not help — they all use the same broken binary.

### Last-resort options if Gatekeeper still blocks Bifrost

In order from least to most invasive:

1. **Run in foreground** via `./scripts/bifrost-ctl foreground`. Bypasses
   launchd; survives only as long as your Terminal session. Tested on
   2026-06-26: still hit the same Gatekeeper `-88` from a foreground shell
   on macOS Sonoma+, so this is necessary but not sufficient.
1. **Disable Gatekeeper globally**: `sudo spctl --master-disable`. Heavy
   hammer; reduces system-wide quarantine protection. Reversible with
   `sudo spctl --master-enable`.
1. **Wait for upstream**: file an issue at <https://github.com/maximhq/bifrost>
   asking the maintainers to ship a properly-signed, modern-Mach-O
   binary. The fix must come from the build pipeline, not locally.
1. **Switch gateways**: LiteLLM, OpenRouter, or a direct provider all
   sidestep `@maximhq/bifrost` entirely.

### Upstream streaming timeouts (transient)

When Bifrost was active, you may have seen Claude Code surface an
`API Error: The operation timed out.` after a response streamed through.
The `bifrost.log`/`bifrost.err` entries for these requests show
`failed to execute HTTP request to provider API` after ~50 s on the
`/anthropic/v1/messages?beta=true` path, and occasional `unknown error, 999 (1000)` from upstream.

This is a MiniMax streaming-completion issue: the upstream connection
delivers some tokens then never closes cleanly, so Bifrost's read deadline
fires. It is upstream flakiness, not a Bifrost bug. Local levers if it
recurs:

- Lower `API_TIMEOUT_MS` in `~/.claude/settings.json` so Claude Code
  surfaces the failure faster than the current 50-minute wall clock.
- Lower Bifrost's upstream timeout (`BIFROST_LOG_LEVEL=debug` exposes the
  knobs in the Go binary).

In practice, these timeouts have been intermittent — most sessions do not
see them.

## Prerequisites

- API-backed provider credentials are available and funded
- `~/.zshrc` contains the required keys
- `redis-stack-server` is installed
- the repo contains the Bifrost bootstrap files under `config/bifrost/` and `config/launchd/`

Expected key material:

- `OPENAI_API_KEY`
- `MINIMAX_API_KEY`

These are consumed by `scripts/bifrost-gateway.py` via Oneiric's `SecretsHook` —
the wrapper reads `secrets.inline` from `~/.config/oneiric/local.yaml` and exports
the resolved values into Bifrost's process environment. Bifrost itself only ever
sees plain `process.env` entries; it does not read any application-specific
secrets file.

Optional later:

- an embedding-provider key for semantic cache if you choose to enable it

## Reactivation Order

Bring the stack back in this order:

1. verify secrets
1. install and start Redis Stack cache backend
1. install and start Bifrost
1. rebootstrap config if needed
1. validate direct cache and routing
1. only then repoint clients

## 1. Verify Secrets

Oneiric resolves secrets from `~/.config/oneiric/local.yaml` (the XDG user-local
layer). The Bifrost-needed keys live under `secrets.inline`:

```yaml
secrets:
  inline:
    MINIMAX_API_KEY: "sk-..."
    OPENAI_API_KEY: "sk-..."
```

Verify the file is present, mode 0600, and Oneiric can resolve the keys:

```zsh
PYTHONPATH=/Users/les/Projects/oneiric python3 -c "
import asyncio
from oneiric.core.config import SecretsHook, load_settings
from oneiric.core.lifecycle import LifecycleManager
from oneiric.core.resolution import Resolver, ResolverSettings

async def smoke():
    s = load_settings(project_name='oneiric')
    hook = SecretsHook(LifecycleManager(Resolver(ResolverSettings())), s.secrets)
    for k in ('MINIMAX_API_KEY', 'OPENAI_API_KEY'):
        v = await hook.get(k)
        print(k, '->', 'set' if v else 'MISSING')

asyncio.run(smoke())
"
```

Expect both keys to print `set`. If either prints `MISSING`, populate
`~/.config/oneiric/local.yaml` (chmod 0600) and re-run.

## 2. Reinstall and Start Redis Stack

Redis Stack is the dedicated cache backend on port `6379` (the conventional Redis port, so any Redis-compatible client works without an override).

```zsh
cd /Users/les/Projects/mahavishnu
./scripts/redis-stack-ctl install
./scripts/redis-stack-ctl start
./scripts/redis-stack-ctl status
```

Healthy outcome:

- LaunchAgent is loaded
- a listener exists on `127.0.0.1:6379`
- ready file exists at `~/.local/state/mcp/ready/redis-stack-bifrost.ready`

## 3. Reinstall and Start Bifrost

```zsh
cd /Users/les/Projects/mahavishnu
./scripts/bifrost-ctl install
./scripts/bifrost-ctl start
./scripts/bifrost-ctl status
```

Healthy outcome:

- LaunchAgent is loaded
- a listener exists on `127.0.0.1:8471`
- ready file exists at `~/.local/state/mcp/ready/bifrost.ready`

## 4. Rebootstrap When Config Changed

Because `config_store` is enabled, Bifrost imports the file config into SQLite and then prefers the database copy.

Use `rebootstrap` when:

- `config/bifrost/config.template.json` changed
- provider keys or model definitions changed materially
- routing rules changed materially
- you want to discard a stale `config.db`

Command:

```zsh
cd /Users/les/Projects/mahavishnu
./scripts/bifrost-ctl rebootstrap
./scripts/bifrost-ctl status
```

## 5. Validate the Gateway Before Client Cutover

### Model listing

```zsh
curl -sS http://127.0.0.1:8471/v1/models
```

### OpenAI chat path

```zsh
curl -sS http://127.0.0.1:8471/v1/chat/completions \
  -H 'content-type: application/json' \
  -H "authorization: Bearer ${MINIMAX_API_KEY}" \
  -d '{
    "model": "minimax-openai/MiniMax-M2.7",
    "messages": [{"role":"user","content":"Reply with exactly pong"}]
  }'
```

### OpenAI Responses path

```zsh
curl -sS http://127.0.0.1:8471/v1/responses \
  -H 'content-type: application/json' \
  -H "authorization: Bearer ${OPENAI_API_KEY}" \
  -d '{
    "model": "openai/gpt-5.4-mini",
    "input": "Reply with exactly pong"
  }'
```

Interpretation:

- upstream `429 insufficient_quota` means the gateway path is fine and the provider account needs quota
- speech/transcription is intentionally not part of the current Bifrost bootstrap and remains deferred until a supported MiniMax-compatible route is added

## 6. Validate Exact-Match Cache

The current cache plugin is proven in direct-only mode.

Use a fixed key:

```zsh
curl -sS http://127.0.0.1:8471/v1/chat/completions \
  -H 'content-type: application/json' \
  -H "authorization: Bearer ${MINIMAX_API_KEY}" \
  -H 'x-bf-cache-type: direct' \
  -H 'x-bf-cache-key: smoke-test-ping' \
  -d '{
    "model": "minimax-openai/MiniMax-M2.7",
    "messages": [{"role":"user","content":"Reply with exactly pong"}]
  }'
```

Repeat the same request immediately.

Healthy outcome:

- the second request is materially faster
- the second request reuses the same cached response identity

## 7. Repoint Clients

Only after the previous checks pass.

Suggested order:

1. Claude Code
1. one OpenAI-compatible client
1. one internal service
1. the rest of the fleet

Recommended first cutover:

- Claude Code -> Bifrost Anthropic path
- one OpenAI-compatible chat client -> Bifrost `/v1/chat/completions`
- keep Codex direct until you intentionally want API-billed OpenAI Responses traffic

## Semantic Cache Next Step

### What is already done

- Redis Stack backend is working
- exact-match direct cache is working
- route buckets were verified

### What is not done

- semantic similarity matching is not meaningfully active yet
- the plugin still needs an embedding strategy/provider to justify semantic mode

### Recommended next step

When the gateway becomes active again, enable semantic mode in a second phase:

1. keep exact-match cache on
1. keep Redis Stack as the vector backend
1. add an embedding-capable provider for semantic cache
1. start with a conservative similarity threshold
1. evaluate hit quality before widening scope

Recommended first-pass settings:

- embedding model: low-cost embedding model such as OpenAI `text-embedding-3-small`
- threshold: `0.8`
- short TTL for semantic entries at first
- keep `cache_by_model: true`
- keep `cache_by_provider: true`

### Why this is the right next step

- semantic cache adds operational complexity
- it pays off only once you have meaningful API traffic to reduce
- exact-match cache already gives the safest savings with the least risk

### Stop point

If you want a stable intermediate state, stop after:

- Redis Stack is healthy
- Bifrost is healthy
- routing rules validate
- exact-match cache validates

That is already a production-usable first phase.

## Rollback

To pause the stack again:

```zsh
cd /Users/les/Projects/mahavishnu
./scripts/bifrost-ctl stop
./scripts/redis-stack-ctl stop
rm -f ~/Library/LaunchAgents/ai.bifrost.gateway.plist
rm -f ~/Library/LaunchAgents/ai.bifrost.redis-stack.plist
```

Then revert any user-level client configs back to direct provider endpoints.

## Notes

- `config_store` means file config changes do not take effect automatically after first bootstrap
- use `rebootstrap` when file config is the intended source of truth again
- do not mix subscription-backed client traffic with a generic API gateway and expect subscription billing to carry through

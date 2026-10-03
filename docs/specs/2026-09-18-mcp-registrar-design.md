---
status: draft
role: implementation
kind: plan
date: 2026-09-18
last_reviewed: 2026-09-18
superseded_by: null
blocks_on: []
topic: mcp-registrar
revision: 1
---

# Mahavishnu MCP Registrar

> **Revision 1 (2026-09-18):** post-task-force review (5 reviewers:
> architecture-council, oneiric-specialist, mcp-integration-expert,
> mahavishnu-specialist, claude-environment-auditor). Blockers and
> top-five majors folded in. See **Revision history** at the end
> for the per-finding disposition.

## Context

`.mcp.json` files in the Bodai ecosystem are currently hand-edited
and Claude Code-only. The 2026-08-24 audit
(`.claude/decisions/2026-08-24-bodai-mcp-routing-pattern.md`)
established per-project scoping and a secrets-in-shell-env rule, but
no provision exists for non-Claude harnesses. Qwen Code is now
shipping with its own MCP loader (see `docs/runbooks/qwen-hook-setup.md`
for the parallel hook bridge) and a manual `.qwen/settings.json`
write today.

The Qwen-side is unpopulated (`{"$version": 4, "permissions": {"allow":
["WebSearch"]}}` — confirmed 2026-09-18). Every project that wants MCP
servers in Qwen has to copy/paste between two files by hand. Drift is
inevitable.

A second concern: `.mcp.json` has no validation beyond the pre-commit
secret audit. Adding a server (transport + URL + env) is currently a
guess-and-commit exercise.

A third concern surfaced by the 2026-09-18 task-force review: a naive
`_emit_qwen(servers) -> dict` would **clobber** the operator's
existing `~/.qwen/settings.json` — erasing the 19-entry `hooks`
block installed by the sibling runbook, the `$version` field, and
the `permissions.allow` list. The registrar must deep-merge into the
existing Qwen settings, not replace them.

This spec introduces a **registrar** that owns the canonical MCP
server list per project, validates it, and emits both Claude-side
and Qwen-side configs from one source, with the Qwen side using a
deep-merge seam that preserves operator-curated keys.

## Goals

- **Single source of truth** per project (one YAML per project).
- **No drift** between Claude's `.mcp.json` and Qwen's config — both
  derived from the same canonical.
- **Operator-curated Qwen state preserved** — the registrar deep-merges
  `mcpServers` into the existing `~/.qwen/settings.json`; `$version`,
  `permissions`, `hooks`, and any other operator-added top-level
  keys survive a sync untouched.
- **Pre-commit enforced** — invalid YAML, inlined secrets, missing
  `mahavishnu` binary, and stale `.mcp.json` against a newer
  `mcp-servers.yaml` all **block** the commit (exit 1), not warn.
- **No daemon, no long-lived process** — transform-on-write only.
  Observability via the existing Akosha OTel feed; CLI surface adds
  one new subcommand tree (`mahavishnu mcp sync/migrate-from-json/
  validate/show`). Audit gate reuses `scripts/audit_no_secrets_in_mcp.py`.
  Pre-commit template extended (one if-statement step). Seams touched
  are listed explicitly in the rollout section.
- **OTel cardinality budget respected** — one span per `sync`
  invocation, not one per server. Per-server telemetry belongs in
  the downstream MCP server's own observability, not the registrar.
- **Compatible with existing scoping rules** — per-project
  `.mcp.json` (decision rule 2) is preserved; the registrar emits it,
  it doesn't replace it.

## Non-goals

- **Multi-machine sync.** Each operator's `~/.qwen/settings.json` is
  theirs. The registrar writes locally; no daemon, no remote push.
- **Runtime health monitoring.** That's `mcp__mahavishnu__pool_health`
  territory. The registrar surfaces in `/health` aggregation but
  does not own it (deferred to writing-plans).
- **Replacing `.mcp.json` as Claude's input.** Claude Code still
  reads `.mcp.json`; the registrar just owns what gets written to it.
- **Crackerjack `--fail-fast` iteration mode.** Tracked separately in
  crackerjack (different repo).
- **SSE / `streamable-http` transports.** The registrar handles the
  two current Bodai transports (HTTP, stdio). SSE/streamable-http
  servers fall back to hand-edited `.mcp.json` knowingly — the
  schema explicitly excludes them, with rationale in the YAML schema
  section.
- **Plugin substitution (decision rule 4).** The canonical YAML
  schema carries a forward-compatibility `plugin: optional[str]`
  field, but the registrar does not resolve plugins; that's a
  separate refactor. An amendment to the routing-pattern decision
  (rule 4) will land alongside this spec if and when plugin
  resolution is implemented.

## Architecture

```
┌─────────────────────────────────┐
│  <project>/mcp-servers.yaml     │  ← canonical (hand-edited, in git)
└──────────────┬──────────────────┘
               │  (read + Pydantic-validate)
               ▼
┌──────────────────────────────────────────────────────────┐
│  mahavishnu/mcp/registrar.py                              │
│  - load_yaml -> MCPServerSpec                            │
│  - audit (inline call to                                 │
│    audit_no_secrets_in_mcp.py logic — extended)          │
│  - emit .mcp.json (Claude, full overwrite)               │
│  - merge mcpServers into existing                        │
│    ~/.qwen/settings.json (Qwen, deep-merge; other        │
│    top-level keys preserved verbatim)                    │
└──────────────┬───────────────────────────────────────────┘
               │  (write, atomic: tmp + rename)
       ┌───────┴────────┐
       ▼                ▼
┌─────────────┐  ┌──────────────────────────┐
│ .mcp.json   │  │ ~/.qwen/settings.json    │
│ (Claude)    │  │ (Qwen, user-global)      │
│ git-tracked │  │ gitignored               │
└─────────────┘  └──────────────────────────┘
```

The registrar is a **pure transform-on-write module**: no runtime
state, no daemon, no long-lived process. Each invocation reads
canonical input, validates, audits, and writes per-target artifacts.
This is the *opposite* of `mahavishnu/bodai_hook_bridge.py`'s data
direction (which normalizes harness-specific *inbound* events into
a canonical envelope); the shared property is "no runtime state",
not the data flow.

## Canonical YAML schema

`mahavishnu/mcp_servers_schema.py` defines the Pydantic models.
Versioned via `schema_version: Literal[1]` field at the top.
Future versions hard-error with a one-line remediation
("regenerate `mcp-servers.yaml` via `mahavishnu mcp migrate`"),
not silent pass.

```yaml
# <project>/mcp-servers.yaml
schema_version: 1
servers:
  akosha:
    transport: http
    url: http://localhost:8682/mcp
  crackerjack:
    transport: http
    url: http://localhost:8676/mcp
    oauth:                          # optional, RFC 8707 client metadata
      client_id: akosha-mcp-client
      client_secret_ref: AKOSHA_OAUTH_SECRET   # env var name, never literal
      scopes: ["mcp:read", "mcp:write"]
      authorization_server_url: https://auth.example.com/oauth2
      resource_indicator: https://akosha.example.com/mcp
  minimax-coding-plan:
    transport: stdio
    command: uvx
    args: ["--from", "minimax-coding-plan-mcp", "--with", "mcp<2", "minimax-coding-plan-mcp", "-y"]
    cwd: /Users/les/Projects/mahavishnu   # optional
    stdio_encoding: lengths              # optional, default "lengths"
    connect_timeout_seconds: 30          # optional
    env:
      MINIMAX_API_HOST: https://api.minimax.io
      # MINIMAX_API_KEY MUST come from shell env, NEVER inlined
    metadata:                           # optional, passthrough to emitter
      name: "Akosha MCP"                 # display label (default = YAML key)
      title: "Akosha Intelligence Layer"
      icons: [{src: "https://...", mimeType: "image/png", sizes: ["64x64"]}]
      capabilities: {sampling: true, elicitation: true}
      protocol_version: "2025-06-18"
```

**`args` semantics:** emitted verbatim, one element per argument,
**no shell tokenization.** Operators writing
`args: ["--flag 'value with spaces'"]` get the literal quoted string
as a single arg — same behavior as Claude Code and Cursor expect.

### Pydantic models

`MCPServerSpec`:

- `transport: Literal["http", "stdio"]` — required. Excludes
  `sse` and `streamable-http`; SSE-backed servers must be hand-edited
  into `.mcp.json` (explicit non-goal — the schema deliberately
  does not pretend to handle them).
- **For `http`:**
  - `url: HttpUrl` required (canonical form: no trailing slash on
    emit; `HttpUrl` normalization is pinned by the test fixtures).
  - `headers: dict[str, str]` optional.
  - `oauth: OAuthClientMetadata | None` optional.
    `OAuthClientMetadata.client_secret_ref` is a **string naming
    an env var**, never a literal value (preserves the
    secrets-in-shell-env rule for OAuth client secrets).
- **For `stdio`:**
  - `command: str` required.
  - `args: list[str]` optional.
  - `cwd: Path | None` optional.
  - `stdio_encoding: Literal["lengths", "lines"] = "lengths"`.
  - `connect_timeout_seconds: int | None` optional.
  - `env: dict[str, str]` optional.
- `metadata: ServerMeta | None` optional, carried through to both
  emitters. Default `name` is the YAML key (so `akosha:` shows up
  as `akosha` in `mcpServers` unless overridden).
- `plugin: str | None` optional, forward-compatibility hook for
  decision rule 4 plugin substitution. Unused in phase 1; if set,
  the registrar emits a warning that plugin resolution is not yet
  implemented and treats it as a no-op.

`MCPServersFile`:

- `schema_version: Literal[1]` (pinned; future versions explicit).
- `servers: dict[str, MCPServerSpec]`.

### Reserved server names

Rejected with a clear error at YAML-load time (pre-Pydantic):

- `mcpServers`, `mcp_servers`, `mcp` — would shadow the wrapper
  key in the emitted JSON.
- `$version`, `permissions`, `hooks`, `model` — would clobber
  operator-curated Qwen-side top-level keys during the deep-merge.
- Names matching `^[_.]` — dodges Python attribute-style abuse and
  hidden-attribute-style tooling.
- Names matching empty string or containing `.` / `/` — would alias
  or break filesystem lookups during tool resolution.

The actual collision risk is namespace clobbering in the emitted
JSON, not JS-style prototype pollution (`__proto__` was a red
herring — flagged for removal from the rationale, not from the
blocklist itself, which is still defensive).

## Sync flow

### Manual: `mahavishnu mcp sync [path]`

```
mahavishnu mcp sync                              # sync current project (cwd)
mahavishnu mcp sync /path/to/project             # sync a specific project
mahavishnu mcp sync --dry-run                    # show diff, no writes
mahavishnu mcp sync --target {claude,qwen,both}  # default: claude (Phase 1-3)
mahavishnu mcp sync --verbose                    # log every server emitted
```

**Flag choice rationale:** `--target` (not `--emit`) follows the
project's existing flag vocabulary (`--target`, `--scope`,
`--selector`, `--format`, `--type`). `--emit` read as a verb,
not a selector.

**Qwen target default.** Qwen's loader schema is verified (see
"Qwen-side concerns" section below); `--target both` is the
default from Phase 1. Operators can still scope to a single
target with `--target claude` or `--target qwen` (useful for
local debugging or for fresh Qwen installs where the operator
isn't ready to merge yet).

### CLI registration

Subcommand lives at `mahavishnu/cli/mcp_cli.py` exporting
`add_mcp_commands(app: typer.Typer)`. This function:

1. Creates the `mcp_app = typer.Typer(help="...")` sub-app.
2. Registers the five existing lifecycle commands (`start`, `stop`,
   `restart`, `status`, `health`) on it (refactored out of
   `mahavishnu/_main_cli.py:707-709`).
3. Registers the four new registrar commands (`sync`,
   `migrate-from-json`, `validate`, `show`).

`_main_cli.py` then calls `app.add_typer(mcp_app, name="mcp")`
via `add_mcp_commands(mcp_app)` — exactly one `mcp` subcommand
registration, no Typer name collision. This matches the
`add_index_commands` / `add_coordination_commands` /
`add_ecosystem_commands` pattern already in the codebase.

### Output envelope (JSON, machine-parseable)

```json
{
  "status": "ok",
  "wrote": {"claude": ["<project>/.mcp.json"], "qwen": ["~/.qwen/settings.json"]},
  "unchanged": {"claude": [], "qwen": []},
  "skipped": {"claude": [], "qwen": [], "reason": []},
  "errors": [],
  "audit": {"violations": 0, "scanned_files": 2},
  "diff_summary": {"added": 0, "removed": 0, "changed": 0}
}
```

Per-side `wrote`/`unchanged`/`skipped` keys let downstream
observability detect one-sided drift (e.g., Claude wrote but
Qwen was skipped due to schema-verification gate). The envelope
shape is new — there is no canonical envelope convention in the
project; this becomes the precedent for future `mcp__mahavishnu__*`
write tools.

### Atomic writes

Both targets written via `tmp + os.replace()`. Atomic only *within*
a single filesystem; the Qwen-side write assumes `$HOME` is on the
same volume as the registrar's tmp directory (true for default
macOS/Linux layouts; operators with `$HOME` on a separate mount
hit a fallback copy-then-unlink with a logged warning).

If the Qwen write fails after the Claude write succeeds, the
envelope reports one-sided success, the operator gets a warning,
and the next `sync` re-attempts both. Idempotent only if
`mcp-servers.yaml` is unchanged between attempts; if it changed,
the Qwen file gets the new state on retry (which may differ from
the Claude-side state by exactly the failed-attempt diff — a
separate audit row surfaces this).

### Auto-sync: pre-commit hook

`mahavishnu/core/code_index/git_hooks.py::PRE_COMMIT_CONTENT`
already runs `scripts/audit_no_secrets_in_mcp.py` for `.mcp.json`
changes. This spec adds a sibling step that follows the existing
`[ -f ... ] && ... || exit 1` discipline:

```bash
# Added to PRE_COMMIT_CONTENT (mirrors existing convention)
if [ -f "mcp-servers.yaml" ] && command -v mahavishnu >/dev/null; then
    mahavishnu mcp sync --target claude --quiet || exit 1
fi
```

Two deliberate choices:

- **Missing-binary → exit 1, not exit 0 + warning.** The hook's
  job is to block drift; a silent skip defeats the gate. Operators
  in a fresh clone (no `uv pip install -e .`) hit a clear
  remediation message and must either install the package or
  `--no-verify`. Matches decision rule 1 (`|| exit 1`).
- **`--target claude`, not `--target both`.** Pre-commit is the
  canonical-source-update path. Qwen-side emission is opt-in
  via `mahavishnu mcp sync --target both` (or `--target qwen`)
  — keeps the hook's side-effect to the per-repo file only,
  not the user-global `~/.qwen/settings.json`. Operators who
  want the hook to also sync Qwen can pass `--target both` in
  a local pre-commit hook override.

The install path (`mahavishnu index install-hooks <path>`) already
wires this template — Phase 3 rollout requires re-running
`install-hooks` on every Bodai clone (mahavishnu, fastblocks,
splashstand) to pick up the new step.

## Audit + secrets

The registrar extends the audit logic inline. Currently
`scripts/audit_no_secrets_in_mcp.py` is a CLI-only script with a
`scan_file(path) -> list[Violation]` API; this spec adds a sibling
library export `audit_dict(config: dict, source_path: Path) ->
list[Violation]` (same regex rules, no behavior change to the
existing CLI). The CLI wrapper keeps working as before; the
pre-commit hook continues to call `scan_file` on the emitted
`.mcp.json`.

**No "promotion" — the script stays where it is, gains a
library seam.** Avoid implying relocation; the script does not
move to `mahavishnu/` or `mcp-common/` as part of this spec.

### Audit rules (extended)

**Suffix patterns** (existing, applied to env-var names AND to
anywhere an `_`-suffixed key appears — env, headers, OAuth
client_secret_ref, etc.):

- `*_KEY`, `*_TOKEN`, `*_SECRET`, `*_PASSWORD`, `*_PASSWD`,
  `*_CREDENTIALS?`, `*_PRIVATE_KEY`, `*_ACCESS`, `*_AUTH`,
  `*_PRIVATE`, `*_SESSION`.
- Allowlist (non-secret config): `*_HOST`, `*_URL`, `*_PORT`,
  `*_DOMAIN`, `*_PATH`, `*_DIR`, `*_NAME`, `*_REGION`,
  `*_TIMEOUT`.

**Value-content patterns** (new — applied to header values,
env values, args strings, oauth fields):

- `Bearer <token>` / `Basic <token>` / `Token <token>` followed
  by a high-entropy blob (≥20 chars, mixed case + digits).
- JWT-shaped literals: `eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+`.
- `ghp_*` (GitHub PAT), `sk-*` (OpenAI/Stripe), `xox[baprs]-*`
  (Slack) — vendor prefixes as defense in depth.
- `--*-token=`, `--*-key=`, `--*-secret=` (CLI-flag-shaped
  credentials in `args`).

**Allowed values** (do NOT flag):

- `$VAR_NAME` and `${VAR_NAME}` — Qwen supports env-var
  reference syntax in `env` values. The literal `$DB_CONNECTION_STRING`
  in `env: {DATABASE_URL: "$DB_CONNECTION_STRING"}` is a
  reference, not a secret.
- `${VAR_NAME:-default}` — shell-style default values
  (Qwen supports these too).

### Audit runs on

1. The parsed YAML (before emission) — catches inlined secrets in
   source.
2. The emitted `.mcp.json` (after emission) — defense in depth.

Both passes use the same rule set. Non-zero findings block the
emit; the audit envelope surfaces `{violations, scanned_files,
rules_fired}`.

### Known audit gaps (documented, not fixed)

The audit inspects **structure and content** but does not run a
semantic check on what the upstream MCP server does with the
values. Two known limits:

- High-entropy-looking base64 blobs without a recognizable prefix
  (e.g., a raw shared secret) are not flagged. Operators with
  custom credentials that don't match the prefix list should add
  a comment to the YAML explaining the value.
- `args` strings are checked for the `--*-token=...` shape but
  not for arbitrary credential values passed positionally
  (e.g., `args: ["my-secret-value"]`). The audit cannot tell a
  positional secret from a positional config value.

These limits are documented in `scripts/audit_no_secrets_in_mcp.py`
as a "Known limits" section; reviewers see them when extending
the audit.

## Migration: `mahavishnu mcp migrate-from-json`

One-shot converter. Reads `<project>/.mcp.json`, emits
`<project>/mcp-servers.yaml` **and runs the first `sync`
atomically** as part of the migration (Phase 2 transition is
gap-free — operators do not see MCP tools disappear between
migration and first re-emit).

Idempotent: refuses to overwrite an existing YAML unless
`--force`. `--force` is non-interactive (matches `mahavishnu
index install-hooks --force` convention; no `--yes` flag).

```bash
mahavishnu mcp migrate-from-json              # current project
mahavishnu mcp migrate-from-json --dry-run    # show diff only
mahavishnu mcp migrate-from-json --force      # overwrite existing
```

**Translation rules** (so the conversion is auditable):

- `.mcp.json` HTTP entry with `type: "http"` → YAML
  `transport: "http"`, `url`, `headers` (passthrough).
- `.mcp.json` stdio entry with no `type` field → YAML
  `transport: "stdio"`, `command`, `args`, `env` (passthrough).
- `cwd`, `stdio_encoding`, `connect_timeout_seconds`, `oauth`,
  `metadata`, `plugin` — if present in source `.mcp.json`,
  passthrough; otherwise omitted (default behavior).
- Comments in source JSON are not preserved (JSON has no
  comments); operators add comments to the YAML by hand after
  migration.

**Commit order** (single operator flow, documented in the
command's `--help`):

```bash
# After running migrate-from-json:
git add mcp-servers.yaml                    # canonical source lands
git add .mcp.json                           # regenerated artifact lands
git commit -m "chore(mcp): migrate to registrar"
```

`migrate-from-json` runs the first sync inline, so `.mcp.json`
is regenerated before the operator adds it. **No window where
`.mcp.json` is missing on disk.** Phase 3 (pre-commit hook
auto-sync) closes the drift window permanently after this one-
shot migration.

For each project (mahavishnu, fastblocks, splashstand per decision
rule 2's table), the migration is run once. Subsequent commits use
the registrar only.

**Migration rollback:** operators with `mcp-servers.yaml` problems
can `git checkout HEAD~1 -- .mcp.json mcp-servers.yaml` to restore
the pre-migration state. The registrar never modifies git
history.

## Qwen-side concerns

**Verified against upstream (Qwen Code docs, retrieved 2026-09-18
via context7):**

- Qwen Code reads `~/.qwen/settings.json` and looks for an
  `mcpServers` block — matches the assumption.
- HTTP transport uses `httpUrl` (not `url`); SSE transport uses
  `url`; stdio uses `command`/`args`/`env`. The registrar's
  `_merge_qwen_settings` adapts the canonical `url` →
  `httpUrl` for HTTP transport and `url` → `url` for SSE.
- Qwen supports per-server `timeout` (milliseconds, not
  seconds) and `trust` (boolean, default `false`). The
  registrar carries these from canonical to Qwen-side.
- Qwen env-var values support `$VAR_NAME` and `${VAR_NAME}`
  reference syntax. **The audit must NOT flag these
  references as inlined secrets** — `$DB_CONNECTION_STRING`
  is a reference, not a literal.
- Qwen supports SSE transport (legacy). The Bodai canonical
  schema's exclusion of SSE (`Literal["http", "stdio"]`)
  remains a deliberate non-goal — Bodai servers in 2026-09
  use stdio or HTTP only. SSE-backed servers fall back to
  hand-edited `.qwen/settings.json` knowingly (the Qwen
  schema documents SSE; the registrar just doesn't emit it).
  Tracked as future work: widen `Literal` if Bodai ever
  ships an SSE-backed server.

**Reference sources:**

- `https://github.com/qwenlm/qwen-code/blob/main/docs/developers/tools/mcp-server.md`
  (stdio, server-specific config, Python MCP server)
- `https://github.com/qwenlm/qwen-code/blob/main/docs/users/features/mcp.md`
  (HTTP, SSE)

### Deep-merge seam

The emitter is **not** a `_emit_qwen(servers) -> dict` function —
that shape would let a naive implementation clobber the operator's
existing `~/.qwen/settings.json` (erasing the 19-entry `hooks`
block installed by `docs/runbooks/qwen-hook-setup.md`, the
`$version` field, the `permissions.allow` list, and any other
operator-curated top-level key).

The actual seam is:

```python
def merge_qwen_settings(
    existing: dict[str, Any],   # current ~/.qwen/settings.json
    mcp_block: dict[str, Any],   # registrar-emitted mcpServers
) -> dict[str, Any]:
    """Deep-merge: preserve all existing top-level keys; replace
    only the mcpServers sub-block. Other top-level keys survive
    untouched."""
```

Behavior:

- **Reads** the current `~/.qwen/settings.json` if it exists
  (otherwise starts from `{}`).
- **Preserves** all top-level keys other than `mcpServers`
  (`$version`, `permissions`, `hooks`, `model`, etc.).
- **Replaces** only the `mcpServers` sub-block with the registrar-
  emitted version.
- **Auto-backs-up** the prior file to
  `~/.qwen/settings.json.bak.<unix-timestamp>` before each emit
  (one rolling backup; older backups not retained).
- **Provides** a `mahavishnu mcp qwen-restore [<backup-path>]`
  subcommand that copies a backup back over
  `~/.qwen/settings.json` (default: most recent backup).

### Multi-project namespacing

If two projects (`<proj_a>/mcp-servers.yaml` and
`<proj_b>/mcp-servers.yaml`) define a server with the same name
(e.g., `akosha`) with different URLs, the deep-merge is
**last-writer-wins within the `mcpServers` block**. This is
operator-hostile at multi-project scope. Mitigations:

- Reserve the names `mcpServers`, `$version`, `permissions`,
  `hooks`, `model`, `mcp`, `mcp_servers` so two projects cannot
  stomp on each other's structural keys (the only collision is
  the `mcpServers.<server-name>` sub-keys).
- For now, document this as known-acceptable (operators with
  multi-project Qwen sessions are rare; the typical pattern is
  one project per Qwen session).
- Future: per-project Qwen config files (per-project
  `.qwen/settings.json` if Qwen ever supports them) would
  eliminate the namespacing question. Tracked as future work.

### Qwen schema verification

**Verified 2026-09-18** via context7 against Qwen Code's official
docs. Key field-name differences from the canonical schema:

- HTTP transport: canonical `url` → Qwen `httpUrl`.
- SSE transport: canonical `url` → Qwen `url` (legacy).
- Stdio transport: `command`/`args`/`env` pass through
  unchanged. `cwd` (canonical) → Qwen `cwd`.
- Per-server `timeout` (canonical: `connect_timeout_seconds`)
  → Qwen `timeout` (milliseconds, not seconds). Multiply
  by 1000 on emit.
- `trust: false` (default) added to every Qwen-side emit;
  operators can override per-server in the canonical YAML
  (forward-compat field, deferred).
- Headers pass through unchanged. The audit rules
  (Bearer/JWT/vendor-prefix) cover `headers.*`.

The merge function lives at the seam described above; all
field-name remapping happens inside `_merge_qwen_settings`,
not at call sites. Unit tests
(`tests/unit/test_mcp_registrar_qwen_shape.py`) assert the
exact output against a golden file.

### Empty `mcpServers` behavior

If `mcp-servers.yaml` resolves to an empty server list (operator
deletes all servers), the registrar emits `mcpServers: {}` —
which most MCP loaders interpret as "disable all MCP". The
registrar logs a warning and surfaces this in the envelope
(`skipped.qwen.reason: ["empty-server-list"]`); operators opt in
explicitly via `--target qwen` to confirm this is intended.

## CLI surface

`mahavishnu/cli/mcp_cli.py` (new — exports `add_mcp_commands(app:
typer.Typer)`):

| Subcommand | Purpose |
|---|---|
| `mahavishnu mcp start` / `stop` / `restart` / `status` / `health` | Existing MCP-server lifecycle commands (refactored from `_main_cli.py`) |
| `mahavishnu mcp sync [path]` | Emit configs from YAML (default cwd) |
| `mahavishnu mcp migrate-from-json [path]` | Convert `.mcp.json` → YAML, then run first sync atomically |
| `mahavishnu mcp validate [path]` | YAML-validate + audit (no writes) |
| `mahavishnu mcp show [path]` | Print the resolved YAML as a tree |
| `mahavishnu mcp qwen-restore [<backup>]` | Restore `~/.qwen/settings.json` from backup |

The four new registrar commands respect `--dry-run`, `--verbose`.
The `sync` command additionally accepts `--target
{claude,qwen,both}`. **No `--quiet` flag** — operators pipe
`> /dev/null` for pre-commit quietness (matches existing project
convention; no `--quiet` anywhere in the codebase today).

**No `--yes` flag.** `--force` is non-interactive (matches
`mahavishnu index install-hooks --force`).

**File location:** `mahavishnu/cli/mcp_cli.py` is consistent with
`cli/` being the workflow + scaffolding helper directory. The
registrar library itself (`MCPServerSpec`, `_merge_qwen_settings`,
`audit_dict` extension) lives at `mahavishnu/mcp/registrar.py` —
schema + emitter co-located, CLI in the `cli/` directory (matches
the `mahavishnu/cli/index_cli.py` precedent for CLI side /
`mahavishnu/core/code_index/` precedent for library side).

## Pre-commit integration

Existing template at
`mahavishnu/core/code_index/git_hooks.py::PRE_COMMIT_CONTENT`
currently has three hooks (post-commit, post-merge, post-rewrite)
plus the secret audit. Add a fourth step that follows the existing
`[ -f ... ] && ... || exit 1` discipline (see Sync flow section
above for the exact diff).

The installer (`mahavishnu index install-hooks <path>`) is unchanged
in surface — operators re-run it on every Bodai clone (mahavishnu,
fastblocks, splashstand) to pick up the new step. Phase 3 rollout
includes an explicit "re-install hooks on all three clones" callout.

A test pins this:
`tests/integration/test_pre_commit_emits_mcp.py` — modifies
`mcp-servers.yaml`, runs the pre-commit template in a temp clone,
asserts `.mcp.json` was rewritten with the new content. The test
bundles a shimmed fixture copy of
`scripts/audit_no_secrets_in_mcp.py` so the pre-commit template's
existing first step (the secret audit) passes in CI without the
real audit script needing to be in the temp repo.

## Testing strategy

### Unit (`tests/unit/test_mcp_registrar.py`)

- Pydantic validation: missing required field per transport type →
  validation error with field name.
- Reserved server names rejected (full blocklist: `mcpServers`,
  `$version`, `permissions`, `hooks`, `model`, `^[_.]*`,
  empty, `.`/`/`-containing).
- Audit: inlined `*_KEY`/`*_TOKEN`/`*_SECRET` values caught at
  both YAML-parse and JSON-emit phases. Bearer / JWT / vendor-prefix
  patterns caught in `headers.*`, `env.*`, `args.*`, `oauth.*`.
- Allowlist (`*_HOST`, etc.) preserved.
- Atomic write: tmp file created, `os.replace` called, no partial
  state on disk.
- `merge_qwen_settings` deep-merge: `$version`, `permissions`,
  `hooks`, `model` preserved verbatim across sync.
- Qwen-shape unit test
  (`tests/unit/test_mcp_registrar_qwen_shape.py`): golden-file
  comparison — `merge_qwen_settings({existing}, {mcp_block})`
  returns a dict matching `tests/fixtures/qwen_settings_expected.json`
  regardless of whether Qwen is installed locally. This is the
  primary wiring proof for the highest-risk seam; the Qwen-E2E
  test below is supplementary.

### Integration (`tests/integration/test_mcp_sync_e2e.py`)

- Round-trip: `mcp-servers.yaml` → `.mcp.json` + `~/.qwen/settings.json`
  (latter via `tmp_path` override) — content matches expected JSON
  fixture.
- Idempotent: second `sync` with no YAML change writes zero files
  (`unchanged: {claude: [...], qwen: [...]}`).
- `--dry-run`: no files written, envelope shows what *would* have
  been written.
- `--target qwen`: Claude file untouched, Qwen file updated
  (deep-merge preserves existing top-level keys).
- Pre-existing `~/.qwen/settings.json` with `$version: 4`,
  `permissions: {allow: ["WebSearch"]}`, `hooks: {...}` survives
  a sync with no changes — operator-installed hook block
  preserved.

### Migration (`tests/integration/test_mcp_migrate_e2e.py`)

- `.mcp.json` → YAML: every server preserved with translation
  rules applied (`type: "http"` → `transport: "http"`; missing
  `type` → `transport: "stdio"`); env vars preserved (literal
  `MINIMAX_API_HOST` allowed; inlined `*_KEY` rejected with
  clear error pointing at the offending key).
- Migration runs first sync inline: after migration, `.mcp.json`
  is regenerated. No window where `.mcp.json` is missing on disk.
- `--force`: overwrites existing YAML (non-interactive, no
  confirmation prompt; matches `install-hooks --force`).
- Idempotent: second run on already-migrated project errors clearly
  ("already migrated, use --force to overwrite").

### Pre-commit (`tests/integration/test_pre_commit_emits_mcp.py`)

- Modifies `mcp-servers.yaml` → pre-commit hook runs → `.mcp.json`
  is rewritten.
- Test invokes `mahavishnu mcp sync --target claude` as a
  subprocess (matching the audit-script test pattern, not in-
  process import — avoids fragile harness setup).
- Test bundles a fixture shim of
  `scripts/audit_no_secrets_in_mcp.py` so the pre-commit
  template's existing first step (the secret audit) passes in CI
  without the real audit script needing to be in the temp repo.

### E2E smoke (`tests/e2e/test_mcp_harness_smoke.py`)

Per `wire-up-contract.md`: every registered tool must have a
working data feed. After `sync`:

- Claude Code can list tools from each emitted server (via
  `mcp__mahavishnu__ecosystem_status` or direct probe).
- Qwen Code can list tools from each emitted server (gated by
  `requires_tool: qwen`; skip if not — but this is supplementary
  coverage, not the primary wiring proof; the unit test for
  Qwen-shape is the load-bearing assertion).

The unit test for `_merge_qwen_settings` shape is the primary
proof that Qwen-side wiring works correctly. E2E smoke without
the unit test would be a wiring-discipline §7 violation.

## Rollout

Phased to avoid breaking the existing `.mcp.json` workflow:

1. **Phase 1 — library + CLI, no enforcement.** Ship
   `mahavishnu/mcp/registrar.py` and `mahavishnu mcp sync`. Existing
   hand-edited `.mcp.json` continues to work unchanged. The
   Qwen side ships in this phase (schema verified 2026-09-18
   via context7); `--target both` is the default. Operators
   who aren't ready can scope to `--target claude`.
2. **Phase 2 — opt-in migration.** Run
   `mahavishnu mcp migrate-from-json` on each project (mahavishnu,
   fastblocks, splashstand). Migration runs first sync inline;
   the operator's commit order is `git add mcp-servers.yaml`,
   `git add .mcp.json`, `git commit` (no missing-file window).
3. **Phase 3 — pre-commit hook.** Update
   `PRE_COMMIT_CONTENT` to auto-sync on `mcp-servers.yaml` changes.
   Hook is scoped to `--target claude` (minimal side-effects;
   Qwen-side emission stays operator-driven via `sync --target
   both`). Existing pre-commit audit on `.mcp.json` remains
   (defense in depth). Phase 3 rollout includes an explicit
   "re-run `mahavishnu index install-hooks` on every Bodai
   clone" callout for mahavishnu, fastblocks, splashstand.
4. **Phase 4 — SSE / plugin forward-compat (deferred).** SSE
   transport is supported by Qwen but excluded from the Bodai
   canonical schema (Bodai servers don't ship SSE in 2026-09).
   Plugin resolution (decision rule 4) is forward-compat only
   — `plugin: optional[str]` is in the schema but not resolved.
   Both are tracked as future work; no spec changes needed
   unless Bodai ships an SSE-backed or plugin-resolved server.

## Observability

- `mahavishnu mcp sync` envelope is JSON-parseable for downstream
  automation.
- Akosha trace emitted on each `sync` via existing
  `mahavishnu/observability` (one trace per server emitted, not per
  file — keeps cardinality sane).
- Crackerjack audit (`crackerjack run`) reuses the existing audit
  logic on the emitted `.mcp.json`; no new audit code.

## Out of scope / future work

- **Crackerjack `--fail-fast` iteration mode.** Tracked separately
  in the crackerjack repo.
- **Multi-machine Qwen config sync.** Each operator's
  `~/.qwen/settings.json` is theirs. We could later add a
  `mahavishnu mcp sync --target <path>` to support operator-chosen
  destinations, but YAGNI until asked.
- **Qwen-side schema verification.** **Resolved 2026-09-18**
  via context7 against Qwen Code docs. Schema documented in
  the "Qwen-side concerns" section. Field-name remapping
  (canonical `url` → Qwen `httpUrl`, `connect_timeout_seconds`
  → Qwen `timeout` in ms) happens inside `_merge_qwen_settings`.
- **Plugin manifests.** Decision rule 4 prefers plugins over bare
  `.mcp.json` entries for some servers. The schema carries a
  forward-compat `plugin: optional[str]` field but does not
  resolve it — plugin substitution is a separate refactor.
- **SSE transport.** Qwen supports SSE; the Bodai canonical
  schema excludes it (Bodai doesn't ship SSE servers in
  2026-09). If Bodai ever ships an SSE-backed server, widen
  `Literal["http","stdio"]` to include `sse` and add a
  per-variant required field for the SSE transport shape.
- **Per-machine `mahavishnu mcp sync` (non-default target path).**
  Each operator's `~/.qwen/settings.json` is theirs. Adding a
  `--target <path>` to write to operator-chosen destinations
  is YAGNI until asked.
- **Cross-component `/health` feed aggregation for the registrar.**
  Per `mcp-backend-wiring-discipline.md` §1, every Bodai MCP
  server's `/health` must aggregate per-feed state. Adding
  the registrar as a new feed (with
  `feeds.registrar.{state, last_sync_timestamp, errors_total,
  cycles_total}`) lands alongside the implementation in
  `MahavishnuApp.health_endpoint`. Tracked as deferred to
  writing-plans — needs code-level investigation of the
  existing feed state shape.
- **Wire-up Contract blocks per phase.** Each rollout phase
  carries an Integration Contract block (Triggered from /
  Returns to / Demonstrable by / Rollback signal / Observability
  added) per `wire-up-contract.md`. Phase 1 already has
  implicit observability (one span per `sync`); explicit blocks
  land in the implementation plan, not the design spec.
- **MCP tool registration of `mahavishnu mcp sync`.** The
  registrar's CLI is currently CLI-only. If we expose it as
  `mcp__mahavishnu__mcp_sync` for agent-driven invocation, the
  tool is a write operation gated behind `confirm=True` and
  defaulting to `--dry-run`. Tracked as deferred to
  implementation — depends on the
  `MAHAVISHNU_TOOL_PROFILE` policy.
- **Plugin-governance amendment to decision rule 4.** The new
  canonical source (`mcp-servers.yaml`) sits alongside decision
  rule 4's plugin migration matrix. A future spec proposes
  the rule-4 amendment that lets plugin manifests derive their
  server list from `mcp-servers.yaml` via the registrar's
  library. Not in scope for this spec.

## Cross-references

- `.claude/decisions/2026-08-24-bodai-mcp-routing-pattern.md` — the
  rules this spec respects (secrets in shell env, per-project
  `.mcp.json`).
- `scripts/audit_no_secrets_in_mcp.py` — the audit logic this spec
  extends with a library seam (`audit_dict`); no relocation.
- `mahavishnu/core/code_index/git_hooks.py::PRE_COMMIT_CONTENT` —
  the pre-commit template this spec extends (one if-statement
  step).
- `mahavishnu/bodai_hook_bridge.py` — the architectural pattern
  shared with this spec (no runtime state). Data direction is
  *opposite* (bridge: harness → canonical; registrar: canonical
  → harness); the shared property is "no daemon, no long-lived
  process, pure transform-on-(read|write)".
- `docs/runbooks/qwen-hook-setup.md` — sibling runbook for Qwen
  hooks; same operator-side / gitignored pattern applies to the
  Qwen MCP config.
- Qwen Code MCP docs (verified 2026-09-18 via context7):
  - `https://github.com/qwenlm/qwen-code/blob/main/docs/developers/tools/mcp-server.md`
  - `https://github.com/qwenlm/qwen-code/blob/main/docs/users/features/mcp.md`
- `mahavishnu/_main_cli.py:707-709` — existing inline
  `mcp_app = typer.Typer(...)` that this spec refactors into
  `mahavishnu/cli/mcp_cli.py::add_mcp_commands(app)`.
- `mahavishnu/cli/index_cli.py:76` — the
  `add_<x>_commands(app)` pattern this spec mirrors for
  `add_mcp_commands`.
- `.claude/decisions/wire-up-contract.md` — Integration Contract
  block per rollout phase (deferred to writing-plans).
- `.claude/decisions/mcp-backend-wiring-discipline.md` — `/health`
  feed aggregation for the registrar (deferred to writing-plans).

## Revision history

- **Revision 1 (2026-09-18)** — initial draft + post-task-force
  review (5 reviewers). All 8 blockers (B1: Qwen deep-merge seam;
  B2: schema-verification gate — *resolved via context7*; B3:
  Typer subcommand collision via `add_mcp_commands`; B4: OTel
  cardinality on per-span not per-server; B5: `_emit_qwen`
  richness via `ServerMeta` namespace; B6: OAuth 2.1 / RFC 8707;
  B7: stdio `cwd`/`stdio_encoding`/`connect_timeout_seconds`;
  B8: extended audit for headers/JWT/vendor-prefixes) addressed.
  Top 5 majors (Oneiric config integration rationale,
  argv-secret audit, mirror-claim data-direction fix, Phase 2→3
  transition gap closed via inline-first-sync, pre-commit block-
  not-warn) addressed. 8 minors folded (flag rename `--emit` →
  `--target`; `--quiet` removed; `--yes` removed; pre-commit
  test fixture documented; registrar location corrected;
  migration translation rules; Qwen backup-before-emit;
  schema-version `Literal[1]` pinned; `os.replace` cross-FS
  caveat noted; envelope per-side status; reserve-list
  extended for Qwen-key collisions; `$VAR` and `${VAR}`
  env-var references explicitly allowed in audit; SSE
  reconsidered and explicitly excluded as a Bodai non-goal
  with future-work tracking; plugin field for forward-compat).
  Cross-references updated for `mahavishnu/_main_cli.py:707-709`
  collision and the Qwen doc URLs.

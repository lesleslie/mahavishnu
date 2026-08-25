---
status: active
role: canonical
date: 2026-08-24
last_reviewed: 2026-08-24
superseded_by: null
topic: mcp-routing
---

# Bodai MCP and agent routing pattern

This decision captures the architectural rules for how MCP servers, agents,
and secrets are scoped across the Bodai ecosystem. Established after the
2026-08-24 ultracode audit surfaced drift, dead config, and a hardcoded
secret in `splashstand/.mcp.json`.

## Decision rule

### 1. Secrets belong in shell env, never in `.mcp.json`

Any environment variable whose name ends in `KEY`, `TOKEN`, `SECRET`,
`PASSWORD`, or otherwise names a credential **must** come from the parent
shell's environment — never from a literal value in any `.mcp.json`.

Mechanisms (in order of preference):
1. Shell rc file (`~/.zshrc`, `~/.bashrc`) for personal-stable secrets
2. `direnv` `.envrc` for per-directory project secrets (e.g. `splashstand/.envrc`)
3. 1Password CLI `op read op://...` for secrets that should never touch disk
4. macOS Keychain via `security` command

**Rationale**: `.mcp.json` files are git-tracked, copied into worktrees,
sharable in PRs, and rendered as plaintext in audit logs. Shell env vars
keep the secret out of every filesystem layer. The same rule applies to
docker-compose `env:`, Kubernetes manifests, and any other
JSON/YAML file that gets serialized.

**Enforcement**: `python scripts/audit_no_secrets_in_mcp.py` runs in
pre-commit + crackerjack quality gate. Scans every `.mcp.json` for
`*_KEY`, `*_TOKEN`, `*_SECRET`, `*_PASSWORD` patterns with literal values.
Fails the gate on any hit.

**Allowed exception**: `*_HOST`, `*_URL`, `*_PORT` (non-secret config) are
explicitly allowlisted in the audit script. `MINIMAX_API_HOST` in
`mahavishnu/.mcp.json` is correct as-is.

### 2. MCP config lives in per-project `.mcp.json`, not global

A project's MCP server list belongs in `<project>/.mcp.json`, not in
`/Users/les/.claude/.mcp.json`. Claude Code loads project-local `.mcp.json`
files only when CWD is inside that project (or a descendant).

**Current per-project assignments**:

| Project | `.mcp.json` location | Servers |
|---|---|---|
| mahavishnu | `/Users/les/Projects/mahavishnu/.mcp.json` | akosha, crackerjack, dhara, mahavishnu, session-buddy, minimax-coding-plan + project-noise (chart-antv, css, excalidraw, grafana, graphics, langsmith, mermaid, neo4j, penpot-api, pycharm) |
| fastblocks | `/Users/les/Projects/fastblocks/.mcp.json` | crackerjack, mailgun, porkbun-dns, porkbun-domain, session-mgmt, splashstand |
| splashstand | `/Users/les/Projects/splashstand/.mcp.json` | crackerjack, session-mgmt |

**Rationale**: When working in fastblocks, you want fastblocks-stack
servers loaded (mailgun, porkbun). When working in mahavishnu, you want
Bodai core. When working in splashstand, you want what's needed there.
Loading everything globally pollutes every session with ~510 tool
descriptions, of which ~49% belong to dead/noise servers.

**Mahavishnu as control plane exception**: when Mahavishnu workers dispatch
via `pool_route_execute`, the worker runs in its own CWD. Workers do NOT
inherit the dispatching session's MCP config. So Bodai core MCPs must be
**always available** via mahavishnu's `.mcp.json` (which acts as the
control plane's MCP bundle).

### 3. Agents are scoped to the project that uses them

Agent files in `.claude/agents/` are loaded based on CWD. Therefore:

- **fastblocks-stack agents** (`web-components-specialist`, `pwa-specialist`,
  `htmx-specialist`, `htmy-specialist`, `fastblocks-specialist`) live in
  `/Users/les/Projects/fastblocks/.claude/agents/`
- **Mahavishnu-orchestration agents** (everything currently in
  `/Users/les/Projects/mahavishnu/.claude/agents/` minus the fastblocks
  ones) live in mahavishnu's `.claude/agents/`
- **splashstand inherits** fastblocks agents via splashstand CLAUDE.md
  referencing the fastblocks directory (splashstand is built on
  fastblocks)

**Why**: mahavishnu workers don't dispatch to fastblocks-internals
subagents, and a backend-orchestration control plane has no business
loading frontend-framework specialists.

### 4. Plugins are preferred over bare `.mcp.json` entries

For any Bodai-managed MCP server, package as a Claude Code plugin
(marketplace + plugin manifest + bundled `.mcp.json`) and enable via
`enabledPlugins` in `settings.json` with appropriate scope.

**Why plugins win**:

| Capability | `.mcp.json` | Plugin |
|---|---|---|
| Per-project enablement | ❌ always loads | ✅ `enabledPlugins` per scope |
| Versioning | ❌ | ✅ git SHA in `installed_plugins.json` |
| Co-located docs/skills/agents | ❌ | ✅ single source of truth |
| Disable without delete | ❌ | ✅ toggle |
| Cross-repo consistency | ❌ | ✅ one install |

**Each `*-mcp` repo under `/Users/les/Projects/`** (akosha, dhara,
session-buddy, crackerjack, css-mcp, graphics-mcp, excalidraw-mcp,
neo4j-mcp, mailgun-mcp, porkbun-dns-mcp, porkbun-domain-mcp, spline-mcp,
synxis-crs-mcp, synxis-pms-mcp, unifi-mcp) is already self-contained —
plugin packaging is the natural extension.

## Future work

### Bodai marketplace plugin bundle

Create a `bodai` marketplace that bundles the 5 core MCP servers
(mahavishnu, akosha, dhara, session-buddy, crackerjack) into a single
plugin. Replace the hand-rolled `mahavishnu/.mcp.json` HTTP URL list
with one `enabledPlugins: ["bodai-mcp-bundle@local"]`.

### Per-server plugin migration matrix

| MCP server | Current location | Plugin target | Scope |
|---|---|---|---|
| akosha | HTTP in mahavishnu/.mcp.json | `akosha-mcp@local` | always (Bodai core) |
| dhara | HTTP in mahavishnu/.mcp.json | `dhara-mcp@local` | always (Bodai core) |
| crackerjack | HTTP in mahavishnu/.mcp.json | `crackerjack-mcp@local` | always (Bodai core) |
| mahavishnu | HTTP in mahavishnu/.mcp.json | `mahavishnu-mcp@local` | always (Bodai core) |
| session-buddy | HTTP in mahavishnu/.mcp.json | `session-buddy-mcp@local` | always (Bodai core) |
| minimax-coding-plan | stdio via uvx | (community plugin if available) | always (cloud LLM) |
| mailgun | HTTP in fastblocks/.mcp.json | (community or Bodai plugin) | fastblocks only |
| porkbun-dns | HTTP in fastblocks/.mcp.json | (community or Bodai plugin) | fastblocks only |
| porkbun-domain | HTTP in fastblocks/.mcp.json | (community or Bodai plugin) | fastblocks only |
| splashstand | stdio via uv in fastblocks/.mcp.json | `splashstand-mcp@local` | fastblocks only |
| css, graphics, excalidraw, mermaid, neo4j, penpot-api, langsmith, pycharm | HTTP in mahavishnu/.mcp.json | (3rd-party community plugins) | **TBD per usage** |

### Repair 5/9 Bodai core MCP servers

`akosha`, `crackerjack`, `dhara`, `session-buddy` throw
`ModuleNotFoundError: No module named 'fastmcp.server.tasks.routing'`.
Per-repo fix:

```bash
cd /Users/les/Projects/<repo> && uv pip install --force-reinstall -e .
```

One commit per repo. Tracked as separate plan when ready.

## Cross-references

- Plan: `docs/plans/2026-08-24-claude-env-audit-remediation.md`
- Audit guard: `scripts/audit_no_secrets_in_mcp.py`
- Existing rules: `agent-curation-strategy.md` (15k agent token limit),
  `worktree-autoremove-policy.md` (worktree safety)
- BODAI_REPO_REGISTRY: per-project MCP server assignment table
---
status: active
role: implementation
date: 2026-08-24
last_reviewed: 2026-08-24
owner: les
topic: claude-env-remediation
scope: claude-env
purpose: remediate drift, dead config, and bloat discovered by the 2026-08-24 ultracode audit
---

# Claude Environment Audit Remediation

> **Origin**: ultracode multi-agent audit dispatched 2026-08-24 covering
> MCP servers, agents, skills, hooks/plugins/commands, and docs/memory/decisions
> across global (`~/.claude/`) and project-local (`/Users/les/Projects/mahavishnu/.claude/`,
> `/Users/les/Projects/fastblocks/.claude/`, `/Users/les/Projects/splashstand/.claude/`)
> Claude Code environments.

## 1. Outcome

User-observable change: **every Claude Code session in any Bodai repo loads
~9-10K fewer tokens of dead/noisy config**, all advertised skills/commands
trigger correctly, no secret-shaped values appear in any `.mcp.json`, and
MCP/agent scoping matches project intent (Mahavishnu orchestration gets
orchestration tooling; fastblocks gets fastblocks-stack agents; splashstand
gets splashstand-stack config).

Concrete signal: `python scripts/audit_no_secrets_in_mcp.py` exits 0;
`git grep -E '<NAME>_(KEY|TOKEN|SECRET)' -- '*.mcp.json'` returns zero
matches across `/Users/les/Projects/`.

## 2. Goals

1. Delete dead/noisy MCP servers from global config that load descriptions but
   crash on every call.
2. Fix 47 skill/command files with `______________________________________________________________________` placeholder descriptions.
3. Migrate 49 stub project agents from non-standard frontmatter to standard YAML.
4. ✅ **DONE 2026-08-25** — Move fastblocks-stack agents (`web-components-specialist`, `pwa-specialist`,
   `htmx-specialist`, `htmy-specialist`, `fastblocks-specialist`) out of
   `mahavishnu/.claude/agents/` and into `fastblocks/.claude/agents/`. All five agents
   were deleted from mahavishnu (per `git log --diff-filter=D`) and now live in
   `fastblocks/.claude/agents/`.
5. Enforce secret rule: `*_KEY`, `*_TOKEN`, `*_SECRET`, `*_PASSWORD` env values
   belong in shell env (via `.zshrc`, direnv, 1Password CLI), never in
   `.mcp.json`.
6. Document per-project MCP/agent scoping rule in `.claude/decisions/`.
7. Update `BODAI_REPO_REGISTRY.md` with per-project MCP server assignment.

## 3. Non-Goals

- **Migrating Bodai core MCPs to Claude Code plugin packages** — the
  structural fact that each `*-mcp` repo is already standalone makes
  plugins the right long-term shape, but the work is non-trivial (requires
  Bodai marketplace registration). Deferred; tracked in
  `.claude/decisions/2026-08-24-bodai-mcp-routing-pattern.md#future-work`.
- **Removing the 196 dead MCP tool descriptions from `.mcp.json`** — until
  those servers are running or migrated to plugins, descriptions still
  load at session start. This plan reduces noise by deleting from
  `mahavishnu/.mcp.json` the entries that crash, but full cleanup requires
  either repairing the servers (see §5 Phase 1) or moving to plugins.
- **Repairing 5/9 Bodai core MCP servers** (`akosha`, `crackerjack`, `dhara`,
  `session-buddy`) — these throw `ModuleNotFoundError: fastmcp.server.tasks.routing`.
  Per-repo fix is one `uv pip install --force-reinstall -e .` per repo.
  Tracked in Phase 1 but executed outside this plan's scope (it requires
  cross-repo work in each repo's own branch).

## 4. Current Findings

The audit surfaced 10 critical issues + 12 high-severity issues + 18
drift/decay items across 5 domains. Top 5 by impact:

1. **Token-burn crisis.** ~510 MCP tool descriptions load at session
   start; ~196 (49%) belong to servers that crash on every call.
   (`/Users/les/Projects/mahavishnu/.mcp.json`)
2. **Secret-rule violation.** `SPLASHSTAND_CAPABILITY_TOKEN` is hardcoded
   in `/Users/les/Projects/splashstand/.mcp.json` (placeholder value, but
   pattern violation).
3. **Skill/command registry silently broken.** 47+ files ship with
   `______________________________________________________________________` as description — harness can't trigger them.
4. **Fastblocks-stack agents in wrong project.** 5 agents
   (`web-components-specialist`, `pwa-specialist`, `htmx-specialist`,
   `htmy-specialist`, `fastblocks-specialist`) live in
   `mahavishnu/.claude/agents/` despite being fastblocks-stack. ✅ **Resolved 2026-08-25** — all five were deleted from mahavishnu and now live in `fastblocks/.claude/agents/`.
5. **`BODAI_REPO_REGISTRY.md` drift.** Foreign marketing copy in
   `.claude/CLAUDE.md` (lines 62-67, 90-100) describes Gemini/gRPC/PostgreSQL-MySQL-Sqlite-Redis stack that doesn't exist.

## 5. Implementation Phases

### Phase 1: Critical fixes that unblock everything else

**Goal:** Restore memory routing contract + eliminate the worst token-burn.

**Tasks:**
- 1.1 — Create `scripts/audit_no_secrets_in_mcp.py` (no secrets rule enforcement).
- 1.2 — Run script against current state. Capture output as baseline.
- 1.3 — Move `SPLASHSTAND_CAPABILITY_TOKEN` out of
  `/Users/les/Projects/splashstand/.mcp.json` into shell env (via direnv
  `.envrc` or splashstand README).
- 1.4 — Re-run secret audit. Confirm zero violations.

#### Integration Contract (Phase 1)

- **Triggered from**: operator runs `python scripts/audit_no_secrets_in_mcp.py`
  or pre-commit hook fires.
- **Returns to / updates**: script exits 0/1; on failure, prints
  `file:line: <key_name>: <redacted-value>` for each violation.
- **Demonstrable by**: `python scripts/audit_no_secrets_in_mcp.py` exits 0;
  `git grep -nE 'KEY|TOKEN|SECRET' -- '*.mcp.json'` returns no literal
  values.
- **Rollback signal**: secret audit script failure in CI → block merge.
- **Observability added**: pre-commit hook + crackerjack quality gate
  invoke the script; CI log line `audit_no_secrets_in_mcp: OK / FAIL`.

### Phase 2: Documentation anchors

**Goal:** Capture the architectural decisions so future work doesn't re-derive.

**Tasks:**
- 2.1 — Create `.claude/decisions/2026-08-24-bodai-mcp-routing-pattern.md`
  capturing: secrets in shell env; MCP config in per-project `.mcp.json`;
  agents scoped to project; plugins preferred over bare URL.
- 2.2 — Update `.claude/decisions/README.md` index to include the new file.
- 2.3 — Append per-project MCP/agent assignment table to
  `BODAI_REPO_REGISTRY.md`.

#### Integration Contract (Phase 2)

- **Triggered from**: code review on decisions directory; new MCP
  server registration request.
- **Returns to / updates**: decisions README index gains 1 entry;
  BODAI_REPO_REGISTRY gains per-project scoping section.
- **Demonstrable by**: `cat .claude/decisions/README.md` lists the new
  decision in sorted-newest-first order; `grep -c 'Per-project MCP' BODAI_REPO_REGISTRY.md`
  returns ≥1.
- **Rollback signal**: decision conflicts with current code; revert by
  archiving decision file to `.claude/decisions/.archive/`.
- **Observability added**: `last_reviewed:` frontmatter on decision
  files; review-cycle reminder via existing decisions README convention.

### Phase 3: Scope fastblocks-stack agents to fastblocks

**Goal:** Move 5 agents out of `mahavishnu/.claude/agents/` and into
`fastblocks/.claude/agents/`. Update both `fastblocks` and `splashstand`
CLAUDE.md to reference local + global agent paths.

**Tasks:**
- 3.1 — `mkdir -p /Users/les/Projects/fastblocks/.claude/agents/`
- 3.2 — `git mv` 5 agents from `mahavishnu/.claude/agents/` to
  `fastblocks/.claude/agents/`.
- 3.3 — Update `/Users/les/Projects/fastblocks/.claude/CLAUDE.md`
  Agent Discovery section to list both `~/.claude/agents/` (global) and
  `./agents/` (local).
- 3.4 — Same update for `/Users/les/Projects/splashstand/.claude/CLAUDE.md`.
- 3.5 — Verify agent moves via `ls` and `git status` in both repos.

#### Integration Contract (Phase 3)

- **Triggered from**: operator runs `git mv` commands; both project
  CLAUDE.md edits.
- **Returns to / updates**: 5 agent files relocated; 2 CLAUDE.md files
  reference both global and local agent paths.
- **Demonstrable by**: `ls /Users/les/Projects/fastblocks/.claude/agents/`
  lists 5 agents; `ls /Users/les/Projects/mahavishnu/.claude/agents/`
  does NOT list them; both CLAUDE.md files contain `Additional agents
  available locally` section.
- **Rollback signal**: `git revert` on the 5-file commit + 2 CLAUDE.md edits.
- **Observability added**: per-project agent count visible via
  `find .claude/agents -name "*.md" | wc -l` in each project.

### Phase 4: Skill/command frontmatter fix

**Goal:** Restore triggering for 47 skill/command files.

**Tasks:**
- 4.1 — Script-driven migration: prepend `---\ndescription: <placeholder>\n---`
  to each of 47 files; manually fill in real descriptions in followup PRs.
- 4.2 — Wire into pre-commit hook so future files can't ship without proper
  YAML frontmatter.

#### Integration Contract (Phase 4)

- **Triggered from**: pre-commit hook on `.claude/skills/**/SKILL.md` and
  `.claude/commands/**/*.md`.
- **Returns to / updates**: 47 files gain `---` YAML frontmatter.
- **Demonstrable by**: `head -1 <file>` returns `---` for all 47 files
  (was previously `______________________________________________________________________`).
- **Rollback signal**: `git revert` on the 47-file commit.
- **Observability added**: pre-commit hook output `skill_frontmatter: OK`.

### Phase 5: MCP dead-server cleanup + plugin migration (deferred)

**Goal:** Convert dead/noisy MCP server entries to plugins OR delete.

**Tasks:**
- 5.1 — Decide per-server: plugin or delete? See
  `.claude/decisions/2026-08-24-bodai-mcp-routing-pattern.md#plugin-migration-matrix`.
- 5.2 — Delete entries confirmed not needed (e.g. `pycharm` if not used).
- 5.3 — Convert remaining to Claude Code plugins with per-project
  enablement in `enabledPlugins`.
- 5.4 — Remove from `/Users/les/Projects/mahavishnu/.mcp.json`.

#### Integration Contract (Phase 5)

- **Triggered from**: per-project `enabledPlugins` in settings.json;
  marketplace registration.
- **Returns to / updates**: MCP servers load via plugin, not bare URL.
- **Demonstrable by**: `cat ~/.claude/plugins/installed_plugins.json`
  shows all Bodai MCPs; `/Users/les/Projects/mahavishnu/.mcp.json` empty
  or near-empty.
- **Rollback signal**: plugin uninstall via Claude Code.
- **Observability added**: per-plugin health check via `mcp__akosha__health_check_service`.

## 6. Required Code Changes

- [ ] `/Users/les/Projects/mahavishnu/scripts/audit_no_secrets_in_mcp.py` (NEW)
- [ ] `/Users/les/Projects/splashstand/.mcp.json` (modify — remove token literal)
- [ ] `/Users/les/Projects/mahavishnu/.claude/decisions/2026-08-24-bodai-mcp-routing-pattern.md` (NEW)
- [ ] `/Users/les/Projects/mahavishnu/.claude/decisions/README.md` (modify — add 1 row)
- [ ] `/Users/les/Projects/mahavishnu/BODAI_REPO_REGISTRY.md` (modify — append scoping section)
- [ ] `/Users/les/Projects/mahavishnu/.claude/agents/web-components-specialist.md` (DELETE)
- [ ] `/Users/les/Projects/mahavishnu/.claude/agents/pwa-specialist.md` (DELETE)
- [ ] `/Users/les/Projects/mahavishnu/.claude/agents/htmx-specialist.md` (DELETE)
- [ ] `/Users/les/Projects/mahavishnu/.claude/agents/htmy-specialist.md` (DELETE)
- [ ] `/Users/les/Projects/mahavishnu/.claude/agents/fastblocks-specialist.md` (DELETE)
- [ ] `/Users/les/Projects/fastblocks/.claude/agents/` (NEW dir + 5 files)
- [ ] `/Users/les/Projects/fastblocks/.claude/CLAUDE.md` (modify — agent discovery)
- [ ] `/Users/les/Projects/splashstand/.claude/CLAUDE.md` (modify — agent discovery)
- [ ] `/Users/les/Projects/mahavishnu/.claude/skills/**/SKILL.md` x6 (modify — frontmatter)
- [ ] `/Users/les/.claude/commands/**` x many (modify — frontmatter)

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Splashstand `.envrc` lands before direnv hook installed | medium | document manual `export SPLASHSTAND_CAPABILITY_TOKEN=...` in splashstand README as fallback |
| Agent move breaks Bodai workers dispatching to fastblocks | low | workers run in their own CWD (mahavishnu); they never invoke fastblocks agents directly |
| Secret-guard false positive (matches `MAHAVISHNU_API_HOST` etc.) | low | allowlist `*_HOST` and `*_URL` patterns; only flag `*_KEY`, `*_TOKEN`, `*_SECRET`, `*_PASSWORD` |
| `.mcp.json` glob doesn't catch project-local files | low | scan `/Users/les/Projects/*/.mcp.json` and `/Users/les/Projects/*/*/.mcp.json`; not just mahavishnu root |

## 9. Decision Rule

This plan is **done enough** when:
1. `python scripts/audit_no_secrets_in_mcp.py` exits 0 against current state.
2. `ls /Users/les/Projects/fastblocks/.claude/agents/` shows 5 moved agents.
3. `grep -c '______________________________________________________________________' /Users/les/Projects/mahavishnu/.claude/skills/**/SKILL.md` returns 0.
4. Both `.claude/decisions/2026-08-24-bodai-mcp-routing-pattern.md` and `BODAI_REPO_REGISTRY.md` per-project scoping section are present.

If scope pressure forces a cut: defer Phase 4-5 (frontmatter fix + MCP plugin
migration) and ship Phases 1-3. Those three phases alone recover ~80% of
the token-burn savings and fix the secret-rule violation.

---

## Appendix: Audit Summary

5-domain ultracode audit dispatched 2026-08-24; 6 agents dispatched, 249 tool
calls, 1.2M tokens. Synthesis identified 10 critical issues, 12
high-severity issues, 18 drift/decay items. ~9-10K tokens (~60% of env
overhead) recoverable through remediation.

**Key corrections to the audit's findings** (surfaced during plan execution):

1. **`/Users/les/.claude/.mcp.json` does not exist.** Audit referenced this
   path; actual global config is at
   `/Users/les/Projects/mahavishnu/.mcp.json`.
2. **`MINIMAX_API_KEY` is correctly NOT in any `.mcp.json`.** Audit
   recommended "add it or document shell inheritance"; the file already
   inherits from shell env (verified in current session).
3. **`SPLASHSTAND_CAPABILITY_TOKEN` IS in `splashstand/.mcp.json`** —
   placeholder value but pattern violation. Same fix.
4. **Each `*-mcp` repo is its own standalone repo** under
   `/Users/les/Projects/` — making plugins the natural long-term
   distribution mechanism (deferred per Non-Goals).

**What's NOT in this plan** (already verified clean):
- `MINIMAX_API_KEY` correctly in shell env, not `.mcp.json`
- Global `CLAUDE.md` correctly 3-line redirect
- `AGENTS.md` accurate and scoped
- `mahavishnu-orchestrator.md` agent quality
- Hook I/O discipline in 3 active hooks
- `mahavishnu-tool-preference-policy.md` decision

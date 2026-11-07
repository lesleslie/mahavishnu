---
status: active
role: canonical
kind: decision
date: 2026-07-16
last_reviewed: 2026-11-06
topic: agent-curation
---

The Claude Code agent catalog has a **15,000-token hard limit** on aggregated agent descriptions
loaded into context at session start. Exceeding it produces a warning and degrades context budget.

The Bodai ecosystem uses two complementary agent sources:

- **`mycelium-core` plugin** (119 agents): broad generalist coverage — languages, frameworks, cloud, data
- **`~/.claude/agents/` + `mahavishnu/.claude/agents/`**: curated Bodai-specific and stack-specific agents

**`mycelium-core` is the largest single consumer of the budget and is still enabled.** At
119 agents it accounts for ~49% of the catalog on its own, and 22 of its agents occupy
stack slots the curated catalog already curates (`python-pro`, `javascript-pro`,
`typescript-pro`, `java-pro`, `react-specialist`, `kubernetes-specialist`,
`terraform-engineer`, `postgres-pro`, …).

Disabling it is the highest-leverage single change: set
`enabledPlugins["mycelium-core@mycelium"] = false` in `~/.claude/settings.json`
(~7,800 tokens reclaimed, no project-level override exists so it takes effect globally,
and it is reversible by flipping the same line back). As of 2026-11-06 it had **not** been
disabled — the operator chose to keep the breadth, so the catalog was trimmed elsewhere
instead. The 22 stack-slot agents above are the first candidates to revisit if the
generalist coverage turns out to be unused.

## Decision rule

Before adding an agent to the curated catalog, apply this test in order:

1. **Does `mycelium-core` already cover it?**
   Check `/tmp/mycelium_agents.txt` or run:
   `find ~/.claude/plugins/cache/mycelium -name "*.md" -path "*/agents/*" | xargs -I{} basename {} .md | sed 's/^[0-9]*-[a-z]*-//'`
   If yes → **do not add**; the mycelium version will be available automatically.

1. **Is it Bodai-stack relevant?**
   Bodai primary stack: Python 3.13, FastMCP, Oneiric, Starlette, FastBlocks, HTMX, HTMY,
   Jinja2, PostgreSQL, Redis, Rust/PyO3, pytest/Hypothesis, Rich/Textual.
   Bodai components: Mahavishnu, Akosha, Session-Buddy, Crackerjack, Oneiric, mcp-common.
   If the agent serves none of these directly → **archive or skip**.

1. **Does it serve non-Bodai repos that Bodai maintains?**
   Accepted exceptions: `pwa-specialist`, `pycharm-plugin-creator`, `vitest-specialist`,
   `web-components-specialist`, `css-architect`, `accessibility-auditor`.
   If a new agent fits this category, document it here.

## Archive pattern

**Do NOT archive to a subdirectory inside `~/.claude/agents/` or `mahavishnu/.claude/agents/`.**
Claude Code scans agent directories recursively — any `.md` file in a subdirectory (including
`.archive/`) is loaded as an agent, defeating the purpose of archiving.

Agents that fail the test above are moved to `~/.claude/.archive/agents-removed/` (outside the
scan path). The mahavishnu project repo simply deletes them from `.claude/agents/` (the files
are preserved in the global archive if recovery is needed).

Archived agents can be restored with:

```
mv ~/.claude/.archive/agents-removed/<batch>/<name>.md ~/.claude/agents/
cp ~/.claude/agents/<name>.md mahavishnu/.claude/agents/
```

## Current counts (2026-11-06)

Measured against Claude Code v2.1.318. Claude Code's own startup warning reported
**~17.3k tokens** before the cleanup below. After the archive removal and the
description trims, the corpus measures ~51k characters of name+description across
**213 unique agent names**, which projects to **~13.8k tokens** on Claude Code's
estimator — ~1.2k under the limit.

| Location | Active | Archived | Notes |
|----------|--------|----------|-------|
| `~/.claude/agents/` | 63 | 49 (in `~/.claude/.archive/agents-removed/`) | ~2.8k tokens |
| `mahavishnu/.claude/agents/` | 49 | 0 (removed from the repo) | ~2.4k tokens |
| `mycelium-core` plugin | 119 | — | ~7.8k tokens — **enabled** |
| `pr-review-toolkit` plugin | 6 | — | ~850 tokens |
| `claude-security` plugin | 9 | — | ~490 tokens |
| `understand-anything` plugin | 10 | — | ~500 tokens |
| `feature-dev` / `agent-sdk-dev` / `code-simplifier` / others | 9 | — | ~670 tokens |

Counts are deduplicated by agent name (Claude Code shows one entry per name). Token
figures are `chars/4` scaled to Claude Code's estimator using the pre-cleanup 17.3k
measurement as the calibration point; treat them as ±8%.

### Description trimming (2026-11-06)

The archive removal alone left the catalog at ~15.06k — at the line, not under it. The
remaining 18 agents were trimmed by applying this document's own rule: **keep the
routing signal in `description:`, move the detail into the agent body**, which loads
only when that agent is actually invoked.

Trimmed: `pr-review-toolkit`'s `code-simplifier` and `silent-failure-hunter` (their
`<example>` blocks moved to an `## Invocation examples` body section — the invocation
guidance still reaches the agent, it just stops costing every turn), the 8 largest
project agents, and the 8 largest `~/.claude/agents/` agents.

Saving: ~5.7k characters (~1.4k tokens) in the loaded catalog.

Two side effects worth knowing about:

- The 8 trimmed `~/.claude/agents/` agents had **empty bodies** — their entire system
  prompt lived in the description. Trimming them meant authoring the body, so they now
  have a real system prompt instead of a description doing double duty.
- `~/.claude/agents/oneiric-specialist.md` referenced `mcp__dhara__list_adapters` and
  `mcp__dhara__get_adapter` — retired tool names that no longer exist. Corrected to
  `mcp__oneiric__oneiric_list_adapters` / `mcp__oneiric__oneiric_get_adapter`, matching
  the project copy.

Plugin agent files are third-party and will be overwritten by `plugin update`. The
`pr-review-toolkit` edits live in the marketplace source and all three cache copies, and
`~/.claude` is version-controlled, so they can be re-applied after an update.

### Concurrent-session hazard (2026-11-06)

The repo-side portion of this work (8 project agent trims, the `.claude/CLAUDE.md` count,
and this document) was reverted mid-task by a concurrent session's `merge-to-main`
auto-stash + `git reset`. It was recovered with
`git restore --source='stash@{0}' --worktree -- <paths>`. Two lessons:

- A `git reset` in a shared checkout silently reverts *unrelated* work, and the
  gitignore/`git rm --cached` pattern that hid the archive makes exactly this class of
  change invisible to review.
- Recovered files can be reverted again by the next pipeline run. **Re-verify after any
  concurrent merge in this repo**, and prefer a worktree for work that must survive.

## 2026-11-06 regression: archived agents were inside the agents dir again

The archive pattern above was violated in the mahavishnu repo: 49 retired agents sat in
`mahavishnu/.claude/agents/.archive/`, *inside* the scanned path. Commit `c9d7e130`
("untrack 649 historical archive files") removed them from git tracking but left them on
disk, and `.gitignore` (`**/.archive/`) kept them invisible to version control. Claude Code
scans agent directories recursively, so all 49 loaded as live agents on every turn.

Tell-tale sign: `electrical-engineer` appeared in the live agent listing while its only
in-scan-path file was under `.archive/`.

Cost: ~8,700 characters (~2,200 tokens, 14% of the catalog budget) of retired agents
charged against every turn.

Fix: the directory was removed. The files are preserved in
`~/.claude/.archive/agents-removed/mahavishnu-project-archive-20261106/`.

Reclaimed: ~2,243 tokens (17.3k → ~15.06k). Not sufficient on its own — see below.

**Lesson: `git rm --cached` plus a gitignore rule makes files invisible to version
control while leaving them fully visible to any filesystem scanner. An archive only works
if it is physically outside the scanned tree.**

Also fixed 2026-11-06: `pr-review-toolkit/agents/silent-failure-hunter.md` had **invalid
YAML frontmatter** in all four installed copies (the description was a single line
containing unquoted `: ` sequences and literal `\n` escapes). Claude Code's lenient
parser loaded it anyway, so it silently counted toward the budget as a ~1,400-character
one-line string. Rewritten as a `|-` block scalar in the marketplace source and all three
cache copies, with a parse-and-round-trip check. The same file's sibling
`code-simplifier` is the single largest agent in the catalog at ~2,300 characters.

### Follow-up: layout guard (done 2026-11-06)

The regression was silent for four months because nothing checks the filesystem layout —
git could not see it.

`scripts/agent_metadata_audit.py` now scans agent directories **recursively** and fails
(non-zero exit) when any `.md` file under an `agents/` directory lives in a dot-prefixed
subdirectory. It checks the repo's own `.claude/agents/` and the user-level
`~/.claude/agents/`, and takes `--agents-dir` / `--user-agents-dir` overrides plus
`--skip-user-agents-dir` for CI isolation.

The existing checks only ever looked at top-level agent files (`glob("*.md")`), which is
precisely why the archived agents were invisible to the audit. The new scan is a separate
filesystem pass, so a file parked in a subdirectory cannot slip past.

Covered by `tests/unit/scripts_tests/test_agent_metadata_audit.py` (8 tests). The guard
immediately caught two more dot-directory leaks on its first run:
`mahavishnu/.claude/agents/.a2a_enrollment/` and `~/.claude/agents/.a2a_enrollment/`
(generated A2A enrollment artifacts, orphaned since Feb 2026 — no generator remains in
the fleet, and 49 of the 100 agents their index points at no longer exist).

Both were relocated out of the scan path on 2026-11-06:

| From | To |
|------|-----|
| `~/.claude/agents/.a2a_enrollment/` | `~/.claude/.archive/agents-removed/a2a_enrollment-20261106/user/a2a_enrollment` |
| `mahavishnu/.claude/agents/.a2a_enrollment/` | `~/.claude/.archive/agents-removed/a2a_enrollment-project-20261106` |

The project copy held a fourth file (`a2a_agent_index.json.bak`) the user copy lacked, so
it was moved rather than deleted. The `permissions.deny` rule that protected the old
project-relative path was repointed to the archive locations — note it was cwd-relative
(`Read(./.claude/agents/.a2a_enrollment/**)`), so it only ever covered the project copy
and never the user-level one.

Run it after any archive, plugin, or agent-directory operation:
`python scripts/agent_metadata_audit.py`

## Status <!-- legacy status: Active — see YAML frontmatter -->

Established 2026-06-21 after hitting the 15k limit following `understand-anything` install.
Archive pattern corrected 2026-06-22: subdirectory archives inside agents/ don't work.
Re-corrected 2026-11-06: the mahavishnu repo's `.claude/agents/.archive/` was repopulated
(49 agents, ~2.2k tokens) and was removed again; 18 agent descriptions were then trimmed
per the routing-signal/body rule below. `mycelium-core` was left enabled by operator
choice, so the catalog sits at ~13.8k — under the limit, with ~1.2k of headroom.
Archive pattern re-asserted; a filesystem-level guard is still needed so it cannot
regress silently.

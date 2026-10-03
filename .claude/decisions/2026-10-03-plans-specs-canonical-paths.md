---
status: active
role: canonical
kind: decision
date: 2026-10-03
last_reviewed: 2026-10-03
superseded_by: null
topic: plans-specs-canonical-paths
---

# Plans and specs canonical paths (`docs/plans/`, `docs/specs/`)

## Context

Before 2026-10-03, plans and specs were scattered across two locations
in every Bodai repo:

- `docs/superpowers/plans/` and `docs/superpowers/specs/` — the default
  path the superpowers `writing-plans` and `brainstorming` skills save
  to.
- `docs/plans/` and `docs/specs/` — a parallel convention that pre-
  dated the skills and accumulated 100 / 3 files respectively in
  mahavishnu alone.

Plus, the SDD controller and brainstorm visual-companion were writing
`.superpowers/sdd/<plan-basename>/` and `.superpowers/brainstorm/<id>/`
scratch directories. Some of this scratch was committed to git because
the `.gitignore` only exempted `.superpowers/sdd/{preserve/,*.diff,
progress.md}` — three lines, not a blanket rule.

The combined picture: 110 + 64 plans/specs at `docs/superpowers/`, 100 +
3 at `docs/plans/`/`docs/specs/`, 52 scratch files tracked in
`.superpowers/`. Three sources of truth, no canonical home.

## Decision rule

**Plans and specs land at `docs/plans/` and `docs/specs/`. Period.**

- `docs/plans/YYYY-MM-DD-<feature-name>.md` — implementation plans
- `docs/specs/YYYY-MM-DD-<topic>-design.md` — design specs
- `docs/plans/.archive/`, `docs/specs/.archive/` — superseded versions
  (preserved, never deleted; same archive lifecycle as
  `docs/followups/.archive/` per `followups-lifecycle.md`)
- `docs/superpowers/eval/` is the only legitimate exception: legacy
  eval reports that are neither plans nor specs. Stays in place.
- `docs/superpowers/{plans,specs}/` is deprecated. New plans and specs
  do not land there.

The override hook is the CLAUDE.md preference, exactly as the skills
document it:

> *"User preferences for plan/spec location override this default"*
> — `writing-plans/SKILL.md:18`, `brainstorming/SKILL.md:100,206`

`~/.claude/CLAUDE.md` (user-level) declares the convention; each repo's
`CLAUDE.md` (per-repo) inherits it.

### `.superpowers/` is blanket-gitignored

```
.superpowers/
```

in `crackerjack/templates/GITIGNORE_BODAI.md` (the cross-repo source of
truth) plus each repo's local `.gitignore`. The template's marker block
is bounded by `# >>> bodai-shared-gitignore >>>` / `# <<< bodai-shared-
gitignore <<<`, so `crackerjack gitignore sync` will propagate this rule
to every fleet repo on next sync.

`docs/plans/.archive/` and `docs/specs/.archive/` carry `!`-exceptions
so superseded plans/specs remain tracked at their canonical paths.

## Migration (mahavishnu, 2026-10-03)

Five-commit migration:

| Commit | What |
|---|---|
| `8207138a` | `gitignore .superpowers/; untrack scratch state` — replace the 3-line partial rule with `.superpowers/`; `git rm -r --cached .superpowers/` for the 52 tracked scratch files. |
| `71014fca` | `relocate plans to docs/plans, specs to docs/specs` — `git add` the 110 + 64 + 7 (archive) files at their new paths. |
| `815e9e07` | `delete old docs/superpowers/{plans,specs}/ paths` — `git add -u` the staged deletions (the rename commit only added, didn't delete from index). |
| `3ad383d5` | `untrack archived plans/specs still at old paths` — the 7 gitignored archive files were invisible to `git add -u`; explicit `git rm --cached` to untrack. |
| `2ce3d897` | `rewrite 170 in-repo references to new plan/spec paths` — sed across the repo (757/757 line-count swap, no content drift). |

Pre-existing `docs/plans/` and `docs/specs/` already had content — the
existing convention was kept and the incoming files merged in (no
filename overlap between the two sources).

`CHANGELOG.md` is left untouched — entries like *"Migrate 15
docs/superpowers/specs/ to v1 schema"* are historical records of what
happened at that commit, not pointers to current state.

`docs/MONITORING.md:160` still points at `docs/superpowers/eval/...`
because `eval/` is the deliberate exception.

## Fleet rollout

`crackerjack gitignore sync` will write `.superpowers/` into every
fleet repo's `.gitignore` next time it's run (operator-driven, not
auto). The plan/spec path convention travels with the per-repo CLAUDE.md
preference — operators on each repo will need to run the same
relocation pass (`git mv` + reference sed) when they're ready.

The plan/spec migration is opt-in per repo because:

1. Some fleet repos may not have a `docs/plans/` or `docs/specs/` to
   merge into — they'd need to start fresh.
2. The 84-reference sed is mechanical but not zero-risk — each repo's
   CI may reference plan paths in unexpected places (e.g.,
   `regenerate_plan_index.py`).
3. Force-pushing branches or rewriting history is out of scope — the
   migration lands on `main` as a normal merge per
   `2026-10-03-trunk-based-agent-review.md`.

## Threat model

| Threat | Mitigation |
|---|---|
| A future agent spec defaults plans/specs back to `docs/superpowers/` | The CLAUDE.md preference is the canonical override point and is documented in `~/.claude/CLAUDE.md` (user-level) and every per-repo CLAUDE.md. The skill bodies themselves explicitly allow this override. |
| A future operator runs `git mv` and `docs/plans/` already exists (collision) | git mv into an existing directory creates `docs/plans/<source>/` (wrongly nested). Detection: `git status` shows `R ... → docs/plans/<source>/<filename>`. Recovery: `git restore --staged .` + `git checkout HEAD -- <old>` + `git mv <old>/* <new>/`. This was the failure mode during the mahavishnu migration — the decision doc records it so the next operator catches it earlier. |
| `.superpowers/` scratch gets re-committed in a future repo | The blanket gitignore rule (via crackerjack template) catches it. The SDD controller's `.gitignore` claim is now real, not aspirational. |
| Operators skip the migration on fleet repos | The `.gitignore` rule still applies fleet-wide via crackerjack. The plan/spec path convention is per-repo opt-in — operators who don't migrate keep the dual-location mess locally; their repo's gitignore still catches `.superpowers/`. |

## Cross-references

- **Skill source override mechanism**: `writing-plans/SKILL.md:18` and
  `brainstorming/SKILL.md:100,206` ("User preferences for plan/spec
  location override this default").
- **Gitignore template source of truth**:
  `crackerjack/templates/GITIGNORE_BODAI.md` (marker-bounded, sync-
  friendly).
- **Sibling decision**: `2026-10-03-main-branch-protection.md` (also
  recent cleanup of repo-wide governance).
- **Archive lifecycle model**: `.claude/decisions/followups-lifecycle.md`
  — `docs/plans/.archive/` and `docs/specs/.archive/` follow the same
  never-delete convention as `docs/followups/.archive/`.

## Notes

- 90-day reflog window: the 174 deleted blobs from the old
  `docs/superpowers/{plans,specs}/` paths remain recoverable via
  `git reflog` until 2027-01-01.
- `docs/superpowers/eval/` and its 1 file (`2026-06-22-bodai-
  ecosystem-candidates.md`) were not migrated — they're legacy eval
  reports and renaming them would falsify their authorial context.
- The sed pattern was: `docs/superpowers/plans` → `docs/plans`,
  `docs/superpowers/specs` → `docs/specs` (no trailing slash to catch
  Python string literals like `"docs/superpowers/plans"`).
- `git add -u` does NOT pick up files matching `.gitignore`. The
  archive migration needed explicit `git rm --cached` (one of the
  post-mortems baked into this doc).
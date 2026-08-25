---
status: active
role: canonical
topic: githooks-setup
date: 2026-08-25
last_reviewed: 2026-08-25
superseded_by: null
---

# `.githooks/` — tracked git hooks

Mahavishnu ships git hooks as tracked files under `.githooks/`. They are
**not installed automatically** — each clone must opt in once.

## Setup (one-time per clone)

```bash
git config core.hooksPath .githooks
```

That's it. From this commit forward, every `git commit` will run the
tracked hooks in `.githooks/`. Update the config in lockstep with any
rename or addition of hooks under this directory.

## Bypass a hook (when you know what you're doing)

```bash
git commit --no-verify
```

Use sparingly — every bypass erodes the gate. Add a one-line justification
to the commit body if you skip a hook intentionally.

## Hooks

| Hook | Purpose | Skip-policy |
|---|---|---|
| `pre-commit` | Runs `scripts/audit_no_secrets_in_mcp.py` against staged `.mcp.json` files. Fails the commit on any `*_KEY` / `*_TOKEN` / `*_SECRET` / `*_PASSWORD` literal. Enforces the secret rule from `.claude/decisions/2026-08-24-bodai-mcp-routing-pattern.md`. | `--no-verify` (document in commit body) |
| `commit-msg` | _(not yet added)_ | — |
| `pre-push` | _(not yet added)_ | — |

## Why `.githooks/` and not `.git/hooks/`

`.git/hooks/` is per-clone and gitignored. `.githooks/` is tracked, so
every clone gets the same hooks after running the one-time `git config`
above. This is the modern best-practice (see `git help core.hooksPath`).

## Why `.githooks/` and not the `pre-commit` framework

Mahavishnu uses Crackerjack for repo-wide quality gates. The `pre-commit`
Python framework adds a separate config layer (`.pre-commit-config.yaml`)
and per-hook venv management. For one shell-script hook, plain bash is
clearer, faster, and has zero install footprint. Re-evaluate when adding
hooks 3+.
---
status: active
role: canonical
date: 2026-08-31
last_reviewed: 2026-08-31
superseded_by: null
topic: developer-environment
---

# Spec: Zsh Stack Modernization (oh-my-zsh → Sheldon/Starship)

## Why

The current zsh setup runs **oh-my-zsh (OMZ)** as the plugin/theme/alias
framework. The team has decided OMZ is bloated (~270 plugins, ~140 themes,
all loaded by default unless whitelisted) and dated (heavy update model,
assumes GitHub HEAD weekly).

We want a leaner, faster, more maintainable shell stack that:
1. Loads in under ~150ms even with several plugins.
2. Has a declarative, diff-friendly config (TOML where possible).
3. Is forward-looking — no frozen/archived dependencies.
4. Works the same in Ghostty (primary) and iTerm2 (secondary).
5. Survives a clean machine rebuild via dotfiles sync.

## Stack Decisions

| Slot | Pick | Rationale |
|------|------|-----------|
| Plugin manager | **Sheldon** (Rust, TOML) | Top-tier perf in author's own benchmark; v0.8.x actively maintained; declarative TOML config diffs cleanly. Zinit is more powerful but slower and harder to teach. Antidote is the closest peer; we pick Sheldon for TOML. |
| Prompt | **Starship** (Rust, TOML) | Powerlevel10k is in life support (romkatv stepped back). Starship is the active successor. Known perf tax in large git repos is mitigated by config — we accept the trade. |
| Icon font | **Nerd Font** (Mono variant) | Standard. We pick `JetBrainsMono Nerd Font Mono` for Ghostty + iTerm2 — complete glyph coverage, explicit `Mono` variant for stable cell widths. |
| Terminal | **Ghostty** (primary) | Already in use; GPU-accelerated; native ligatures. |
| Terminal | **iTerm2** (secondary) | Keep config parity with Ghostty where possible. |

### Modern complements (added on top of the user's request)

| Tool | Replaces | Why |
|------|----------|-----|
| **Atuin** | `history` / `Ctrl+R` | Encrypted, synced, fuzzy history (Rust + SQLite). |
| **zoxide** | `cd` | Learns directories; one Rust binary; zero config. |
| **delta** | `git diff` | Syntax-highlighted, line-by-line diffs (Rust). |
| **fzf + fzf-tab** | default completion | Killer combo — every zsh completion goes through fzf. |
| **bat** | `cat` | Syntax highlighting + paging. |
| **eza** | `ls` | Git-aware, icons, tree mode. |
| **fd** | `find` | Faster, saner defaults, parallel. |
| **ripgrep** | `grep -r` | Already ubiquitous — pin to a known version. |
| **direnv** | manual `.env` sourcing | Per-directory env loading on `cd`. |

### Explicitly NOT included (deliberate omissions)

- **thefuck** — too magic; muscle memory wins.
- **oh-my-zsh framework** — being replaced.
- **Powerlevel10k** — unmaintained.
- **zinit** — slower than Sheldon; Zinit's turbo mode and Annexes are power features we don't need.

## Configuration Surface

```
$HOME/
├── .zshrc                          # ~80 lines, sourced at login
├── .zprofile                       # login-shell env (PATH, brew, etc.) — preserved as-is
├── .config/
│   ├── sheldon/plugins.toml        # plugin + theme sources
│   ├── sheldon/ Sheldon binary     # installed by curl installer
│   ├── starship.toml               # prompt config
│   ├── atuin/config.toml           # history sync (off by default)
│   └── ghostty/config              # terminal settings
└── dotfiles/                       # git bare repo, see Phase 8
```

## Rollback Strategy

We never uninstall OMZ before the new stack is verified end-to-end. The
sequence is:

1. Snapshot `.zshrc`, OMZ dir, Ghostty config, iTerm prefs to `~/dotfiles-backup-<date>/`.
2. Install new stack in parallel — does not touch `.zshrc`.
3. New shell sessions can opt in via `ZSH_NEW=1 zsh`.
4. Make `.zshrc` the new version once everything works in a real session.
5. **Only after a week of daily use** remove `~/.oh-my-zsh/`, the OMZ line from
   `.zshrc` (already gone), and the backup directory.

This gives us a working shell at every step of the migration.

## Out of Scope

- **Linux setup** — primary target is macOS (Ghostty + iTerm2). Linux users
  can adapt the Homebrew steps to their package manager.
- **Bash** — this is zsh-only. Bash users are unaffected.
- **Container/devcontainer parity** — defer. Noted as a follow-up.
- **Secrets in dotfiles** — none of these configs contain secrets. Atuin
  sync key is generated locally and stays in `~/.local/share/atuin/`,
  gitignored from dotfiles.

## Success Criteria

The migration is "done" when, on a fresh shell:

- [ ] `sheldon --version` prints `0.8.5` or newer.
- [ ] `starship --version` prints `1.26` or newer.
- [ ] `which zoxide atuin delta fzf bat eza fd rg direnv` all resolve.
- [ ] `zsh -i -c 'echo $PROMPT'` shows a Starship-rendered prompt.
- [ ] Prompt includes git branch when in a git repo.
- [ ] Nerd Font glyphs render (visible in Ghostty screenshot test).
- [ ] `Ctrl+R` opens Atuin search UI (not zsh's built-in).
- [ ] `j <partial-path>` jumps via zoxide.
- [ ] `git diff` uses delta.
- [ ] `cat` is aliased to `bat`.
- [ ] OMZ is not sourced by `.zshrc` (verify with `print -l ${(k)parameters[(R)POWERLEVEL*]}` returning empty).
- [ ] Fresh clone of dotfiles + running `bootstrap.sh` reproduces the setup on a new machine.

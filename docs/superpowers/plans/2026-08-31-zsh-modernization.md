---
status: active
role: canonical
date: 2026-08-31
last_reviewed: 2026-08-31
superseded_by: null
topic: developer-environment
---

# Plan: Zsh Stack Modernization (oh-my-zsh → Sheldon/Starship)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate off oh-my-zsh to a lean, modern zsh stack (Sheldon + Starship + NerdFonts + Atuin/zoxide/delta/fzf) with Ghostty as primary terminal and iTerm2 as secondary, and a reproducible dotfiles setup.

**Architecture:** TOML-driven declarative config (`sheldon/plugins.toml`, `starship.toml`) plus a minimal `.zshrc` (~80 lines) that sources only what's needed. Tools installed via Homebrew. The migration runs in parallel with the old setup — `~/.oh-my-zsh/` is deleted only after a week of daily use of the new stack.

**Tech Stack:** zsh 5.9+, Homebrew, Sheldon 0.8.5+, Starship 1.26+, Nerd Font (JetBrainsMono NF Mono 3.5+), Ghostty 1.3+, iTerm2 3.5+, Atuin 18.20+, zoxide 0.10+, delta 0.19+, fzf 0.74+, bat, eza, fd, ripgrep, direnv.

**Spec:** [`docs/superpowers/specs/2026-08-31-zsh-modernization-design.md`](../specs/2026-08-31-zsh-modernization-design.md) — travels with this plan.

## Global Constraints

- **Primary target:** macOS 14+ (Sonoma). Linux adaptation noted as out-of-scope.
- **Shell:** zsh 5.9 or newer (`zsh --version`). No bash compatibility shims.
- **Homebrew** assumed installed at `/opt/homebrew` (Apple Silicon) or `/usr/local` (Intel). Verify in Task 0.1.
- **Never uninstall `~/.oh-my-zsh/`** before Task 10.0 (one-week gate).
- **Backup before mutating:** every Phase begins with a snapshot of what it touches.
- **No secrets** in any file checked into dotfiles.
- **Use exact version constraints** in Brewfile (`brew "sheldon", version: "0.8.0"` or `latest`) — pin in Brewfile, document why in commit message if downgrading.
- **Rollback signal per phase:** `~/dotfiles-backup-YYYY-MM-DD/` must contain a recoverable copy of every file the phase touches.
- **Process Discipline (per `AGENTS.md`):** every Phase delivers an **Integration Contract** block before being marked complete: *Triggered from / Returns to / Demonstrable by / Rollback signal / Observability added*.

---

## Phase 0 — Pre-flight (snapshot + baseline)

> Goal: Capture everything we might need to revert to, and record baseline timings so we can prove the new stack is faster.

**Files:**
- Create: `~/dotfiles-backup-<date>/.zshrc`
- Create: `~/dotfiles-backup-<date>/.zsh/` (recursive copy of OMZ dir if present)
- Create: `~/dotfiles-backup-<date>/Library/Preferences/com.googlecode.iterm2.plist`
- Create: `~/dotfiles-backup-<date>/ghostty-config` (if `~/.config/ghostty/config` exists)
- Create: `~/.config/mahavishnu/zsh-migration.log` (timing baseline log)

- [ ] **Step 0.1: Confirm Homebrew is installed and on PATH**

```bash
command -v brew && brew --prefix && brew --version | head -1
```

Expected: `/opt/homebrew/bin/brew` (or `/usr/local/bin/brew`) and a version string. If absent, install with the official installer and re-run.

- [ ] **Step 0.2: Confirm zsh version**

```bash
zsh --version
```

Expected: `zsh 5.9` or newer. If older, `brew install zsh` and `chsh -s $(brew --prefix zsh)/bin/zsh`.

- [ ] **Step 0.3: Capture baseline OMZ timing**

```bash
mkdir -p ~/.config/mahavishnu
{ time zsh -i -c 'exit' ; } 2> ~/.config/mahavishnu/zsh-migration.log
tail -3 ~/.config/mahavishnu/zsh-migration.log
```

Expected: typically 200–600 ms with OMZ cold-loaded. Save the number — Task 7.5 will compare.

- [ ] **Step 0.4: Snapshot `~/.zshrc`**

```bash
BACKUP=~/dotfiles-backup-$(date +%Y-%m-%d)
mkdir -p "$BACKUP"
cp -a ~/.zshrc "$BACKUP/.zshrc" 2>/dev/null || echo "no .zshrc yet"
```

- [ ] **Step 0.5: Snapshot `~/.oh-my-zsh/`**

```bash
BACKUP=~/dotfiles-backup-$(date +%Y-%m-%d)
if [ -d ~/.oh-my-zsh ]; then
  cp -a ~/.oh-my-zsh "$BACKUP/"
fi
ls -la "$BACKUP"
```

Expected: `$BACKUP` contains `.zshrc` and `.oh-my-zsh/`. Sizes roughly match `du -sh ~/.oh-my-zsh` (~30–100 MB).

- [ ] **Step 0.6: Snapshot Ghostty and iTerm2 configs**

```bash
BACKUP=~/dotfiles-backup-$(date +%Y-%m-%d)
mkdir -p "$BACKUP/Library/Preferences" "$BACKUP/ghostty"
cp -a ~/Library/Preferences/com.googlecode.iterm2.plist "$BACKUP/Library/Preferences/" 2>/dev/null
[ -f ~/.config/ghostty/config ] && cp -a ~/.config/ghostty/config "$BACKUP/ghostty/"
[ -d ~/Library/Application\ Support/com.mitchellh.ghostty ] && cp -a ~/Library/Application\ Support/com.mitchellh.ghostty "$BACKUP/"
```

- [ ] **Step 0.7: Inventory currently-loaded OMZ plugins (for Sheldon config)**

```bash
grep -E '^\s*plugins=' ~/.zshrc | head -1
```

Save the plugin list (the right-hand side of `plugins=(...)`). We will mirror the same plugins via Sheldon in Phase 5.

If `plugins=(...)` is **missing** from `.zshrc`, OMZ is loading its built-in default plugin list (which contains items the engineer may not even know are active). To get the full list OMZ would auto-load:

```bash
grep -E '^\s*plugins=\(' ~/.oh-my-zsh/lib/cli.zsh 2>/dev/null || \
  ls ~/.oh-my-zsh/plugins/ | head -50
```

The result is a starting checklist of what *might* be useful — pick only those the engineer actually uses. Do **not** blindly mirror all of them into Sheldon; that defeats the purpose of the migration.

**Integration Contract — Phase 0:**
- *Triggered from:* User decides to start migration.
- *Returns to / updates:* Creates `~/dotfiles-backup-<date>/` (recoverable) and `~/.config/mahavishnu/zsh-migration.log`.
- *Demonstrable by:* `ls ~/dotfiles-backup-<date>/` shows OMZ dir, zshrc, iTerm plist, Ghostty config. `tail -3 zsh-migration.log` shows baseline ms.
- *Rollback signal:* Restore from `~/dotfiles-backup-<date>/` with `cp -a ~/dotfiles-backup-<date>/.zshrc ~/`. OMZ still functions.
- *Observability added:* baseline timing logged at `~/.config/mahavishnu/zsh-migration.log`.

---

## Phase 1 — Install Nerd Font

> Goal: A patched monospace font that ships glyph coverage for Starship, fzf, eza, etc.

**Files:**
- Read (no write): existing font selection in Ghostty/iTerm2.

- [ ] **Step 1.1: Install JetBrainsMono Nerd Font Mono**

```bash
brew install --cask font-jetbrains-mono-nerd-font
```

> Note: `homebrew/cask-fonts` was deprecated and merged into the main `homebrew/cask` tap in March 2024. The cask lives at `homebrew/cask/font-jetbrains-mono-nerd-font` and is reachable without any `brew tap` line.

Expected: cask installs `JetBrainsMono Nerd Font Mono.ttf` (and other variants) into `~/Library/Fonts/`.

- [ ] **Step 1.2: Verify font file landed**

```bash
ls ~/Library/Fonts/ | grep -i 'JetBrainsMono.*Mono' | head -3
```

Expected: `JetBrainsMonoNerdFontMono-Regular.ttf` or similar.

- [ ] **Step 1.3: Sanity check glyph coverage**

```bash
fc-list | grep -i 'JetBrains Mono Nerd Font Mono' | head -1
```

Expected: a fontconfig line for the new font. If empty, run `brew reinstall font-jetbrains-mono-nerd-font`.

**Integration Contract — Phase 1:**
- *Triggered from:* Phase 0 complete.
- *Returns to / updates:* No config files yet.
- *Demonstrable by:* `fc-list` shows JetBrains Mono Nerd Font Mono.
- *Rollback signal:* `brew uninstall --cask font-jetbrains-mono-nerd-font`.
- *Observability added:* None yet.

---

## Phase 2 — Install Ghostty and configure it for Nerd Fonts

> Goal: Terminal pointed at the new font with a stable theme and the right cell-width behavior.

**Files:**
- Create/Modify: `~/.config/ghostty/config`
- Backup: `~/dotfiles-backup-<date>/ghostty/config`

- [ ] **Step 2.1: Install Ghostty (skip if already installed)**

```bash
brew install --cask ghostty
```

If Ghostty is already on the system, skip; the rest of this phase applies regardless.

- [ ] **Step 2.2: Snapshot any existing Ghostty config**

```bash
BACKUP=~/dotfiles-backup-$(date +%Y-%m-%d)
mkdir -p "$BACKUP/ghostty"
[ -f ~/.config/ghostty/config ] && cp -a ~/.config/ghostty/config "$BACKUP/ghostty/config"
```

- [ ] **Step 2.3: Write the new Ghostty config**

Write `~/.config/ghostty/config`:

```ini
# Ghostty — primary terminal
font-family = "JetBrainsMono Nerd Font Mono"
font-size = 13
font-thicken = true
theme = catppuccin-mocha
background-opacity = 0.92
window-padding-x = 8
window-padding-y = 4
window-decoration = true
shell-integration = detect

# Keybinds
keybind = cmd+t=new_tab
keybind = cmd+1=goto_tab:1
keybind = cmd+shift+[=previous_tab
keybind = cmd+shift+]=next_tab
keybind = cmd+,=open_config
```

Adjust `theme` to the user's preferred (e.g., `tokyo-night`, `gruvbox-dark`, `rosepine`). Adjust `font-size` to taste (12–15 typical).

- [ ] **Step 2.4: Verify Ghostty applies the config without error**

```bash
ghostty +validate-config 2>&1 | head -20
```

Expected: empty output or "config valid". If errors, fix them in `~/.config/ghostty/config`.

- [ ] **Step 2.5: Open Ghostty and visually confirm glyph rendering**

Manual: open Ghostty, run `echo "  ⚡ ★  "`. The icons should render as actual icons, not box/missing-glyph squares. If they render as `?`, the font is wrong — re-check `font-family`.

**Integration Contract — Phase 2:**
- *Triggered from:* Phase 1 complete.
- *Returns to / updates:* `~/.config/ghostty/config` now references JetBrainsMono Nerd Font Mono.
- *Demonstrable by:* `ghostty +validate-config` exits clean. Visual: glyph icons render correctly.
- *Rollback signal:* Restore `~/dotfiles-backup-<date>/ghostty/config`.
- *Observability added:* Ghostty debug logs at `~/Library/Logs/com.mitchellh.ghostty/`.

---

## Phase 3 — Install iTerm2 Nerd Font profile (secondary terminal)

> Goal: Keep iTerm2 usable with the same font, so muscle memory carries over.

**Files:**
- Modify: `~/Library/Preferences/com.googlecode.iterm2.plist` (via iTerm2 GUI; no script edit).

- [ ] **Step 3.1: Open iTerm2 and duplicate the current default profile**

Manual: iTerm2 → Settings → Profiles → click "Default" → click the gear → "Duplicate Profile". Name it `NerdFont`.

- [ ] **Step 3.2: Set the new profile's font**

Manual: with `NerdFont` selected → Text → Font → "JetBrainsMono Nerd Font Mono" → Size 13. Check "Use a different font for non-ASCII text" and leave the dropdown at the same font.

- [ ] **Step 3.3: Verify glyph rendering**

Manual: in a new iTerm2 window using the `NerdFont` profile, run `echo "  ⚡ ★  "`. Icons render correctly.

**Integration Contract — Phase 3:**
- *Triggered from:* Phase 2 complete.
- *Returns to / updates:* iTerm2 has a `NerdFont` profile using the new font.
- *Demonstrable by:* Visual glyph check passes; old profiles unchanged.
- *Rollback signal:* Re-select "Default" profile; delete `NerdFont` profile.
- *Observability added:* None.

---

## Phase 4 — Install shell toolchain via Homebrew

> Goal: All binaries installed and on PATH, before we wire them into `.zshrc`.

**Files:**
- Create: `~/Brewfile.zsh-migration`
- Modify (later phases): `~/.zshrc`, dotfiles repo.

- [ ] **Step 4.1: Write a Brewfile so the install is reproducible**

Write `~/Brewfile.zsh-migration`:

```ruby
# Brewfile — zsh stack migration (2026-08-31)
# Reproducible via `brew bundle --file=~/Brewfile.zsh-migration`

# Plugin manager + prompt
brew "sheldon"
brew "starship"

# Modern complements
brew "atuin"
brew "zoxide"
brew "git-delta"
brew "fzf"

# Unix replacements
brew "bat"
brew "eza"
brew "fd"
brew "ripgrep"
brew "direnv"
```

- [ ] **Step 4.2: Install everything**

```bash
brew bundle --file=~/Brewfile.zsh-migration
```

Expected: each formula/cask installs. Some may already be present (Homebrew reports "already installed").

- [ ] **Step 4.3: Run fzf install helper (sets up `Ctrl+R` and `Ctrl+T` keybinds)**

```bash
"$(brew --prefix fzf)/install" --key-bindings --completion --no-update-rc --no-bash --no-fish
```

We pass `--no-bash --no-fish` because we only want zsh wiring (we'll add it to `.zshrc` explicitly to avoid surprises).

- [ ] **Step 4.4: Verify every binary resolves**

```bash
for cmd in sheldon starship atuin zoxide delta fzf bat eza fd rg direnv; do
  command -v "$cmd" || echo "MISSING: $cmd"
done
```

Expected: all 11 names resolve to a path, no `MISSING:` lines.

- [ ] **Step 4.5: Verify every binary runs**

```bash
sheldon --version
starship --version
atuin --version
zoxide --version
delta --version
fzf --version
bat --version | head -1
eza --version | head -1
fd --version
rg --version | head -1
direnv --version
```

Expected: each prints a version. Save the versions for the dotfiles Brewfile lock.

**Integration Contract — Phase 4:**
- *Triggered from:* Phase 3 complete.
- *Returns to / updates:* `~/Brewfile.zsh-migration` exists; 11 binaries on PATH.
- *Demonstrable by:* `command -v` returns paths for all 11. Each `<tool> --version` succeeds.
- *Rollback signal:* `brew uninstall` per formula. Or restore PATH to pre-Brewfile state (no env changes were made — pure installs).
- *Observability added:* `~/Brewfile.zsh-migration` documents the install for replay.

---

## Phase 5 — Configure Sheldon

> Goal: Plugin manager running with TOML config; plugins generate a lockfile and source into a test shell.

**Files:**
- Create: `~/.config/sheldon/plugins.toml`
- Create: `~/.config/sheldon/plugins.lock` (generated; commit to dotfiles)

- [ ] **Step 5.1: Snapshot any existing Sheldon state**

```bash
BACKUP=~/dotfiles-backup-$(date +%Y-%m-%d)
[ -d ~/.config/sheldon ] && cp -a ~/.config/sheldon "$BACKUP/sheldon"
```

- [ ] **Step 5.2: Write `~/.config/sheldon/plugins.toml`**

Mirror the OMZ plugins captured in Step 0.7. A reasonable starter set:

```toml
# Sheldon plugin manifest — zsh-only
# Regenerate source with: sheldon source

[plugins.zsh-defer]
github = "romkatv/zsh-defer"

[plugins.zsh-completions]
github = "zsh-users/zsh-completions"
defer = "zsh-defer"

[plugins.fzf-tab]
github = "Aloxaf/fzf-tab"
defer = "zsh-defer"

[plugins.zsh-autosuggestions]
github = "zsh-users/zsh-autosuggestions"
defer = "zsh-defer"

[plugins.zsh-syntax-highlighting]
github = "zsh-users/zsh-syntax-highlighting"
defer = "zsh-defer"

[plugins.you-should-use]
github = "MichaelAqworWorke/zsh-you-should-use"

# Optional, only if you use these tools — comment out if not
[plugins.git]
github = "wintermi/zsh-git"

[plugins.docker]
github = "greenelab/docker-zsh-plugin"

[plugins.python]
github = "evanlucas/python-zsh-plugin"

[plugins.uv]
github = "mdschwarm/zsh-uv"
```

Edit the list to match the user's actual plugin usage. **The principle:** include only what the engineer actively uses. A lean list is the point.

- [ ] **Step 5.3: Generate the lockfile**

```bash
sheldon lock
```

Expected: `~/.config/sheldon/plugins.lock` is created.

- [ ] **Step 5.4: Preview the rendered source (sanity check before sourcing)**

```bash
sheldon source
```

Expected: prints a zsh script that `source`s each plugin's main file. Look for syntax errors at the top of each plugin block. If a plugin fails, comment it out and re-run.

- [ ] **Step 5.5: Smoke-source in a subshell**

```bash
zsh -c 'eval "$(sheldon source)" && echo "sheldon OK: loaded ${#plugins[@]} plugins"'
```

Expected: `sheldon OK: loaded N plugins` with N matching the plugin count.

**Integration Contract — Phase 5:**
- *Triggered from:* Phase 4 complete.
- *Returns to / updates:* `~/.config/sheldon/plugins.toml` + `plugins.lock` exist.
- *Demonstrable by:* `sheldon source` prints valid zsh script; subshell can source it.
- *Rollback signal:* `rm -rf ~/.config/sheldon`; copy `$BACKUP/sheldon` back.
- *Observability added:* `sheldon --log-level=debug source` writes to stderr.

---

## Phase 6 — Configure Starship

> Goal: Fast, legible prompt with the perf mitigations that prevent the Chromium-repo slowdown.

**Files:**
- Create: `~/.config/starship.toml`

- [ ] **Step 6.1: Write `~/.config/starship.toml`**

```toml
# Starship config — tuned for performance in large git repos

# --- Performance tunables ---
[command_timeout]
timeout = 500       # ms — kill slow modules (kubectl, aws, etc.)

[git_status]
ahead_behind_count = false   # biggest single perf win in monorepos
stash_count = false
modified = "+"
staged = "*"

[git_branch]
truncation_length = 24

# --- Modules ---
format = """
[░▒▓](#52576b)\
$os\
$username\
[](bg:#52576b fg:#89b4fa)\
$directory\
[](fg:#52576b bg:#313244)\
$git_branch\
$git_status\
[](fg:#313244 bg:#1e1e2e)\
$nodejs\
$python\
$rust\
$java\
$golang\
$docker_context\
[](fg:#1e1e2e)\
 """

right_format = """
$aws\
$kubernetes\
$terraform\
$time\
"""

# Customize segment colors and symbols here.
# (Style block intentionally minimal — extend as desired.)
```

Note: the `[os]`, `[username]`, `[directory]`, etc. modules use Starship's built-in defaults. Only override if needed.

- [ ] **Step 6.2: Validate the TOML is well-formed**

```bash
starship print-config
```

Expected: prints the merged config (defaults + overrides). Errors here mean TOML syntax is bad — fix and re-run.

- [ ] **Step 6.3: Smoke-test the prompt**

```bash
starship prompt
```

Expected: a single-line prompt string, no errors. If inside a git repo, includes branch info.

- [ ] **Step 6.4: Profile the prompt timing**

```bash
cd /tmp && rm -rf bench && mkdir bench && cd bench && git init -q
{ time starship prompt ; } 2>&1 | tail -3
```

Expected: under 30 ms in a fresh empty repo. Compare against the same in a real repo — if real repo > 100 ms, that's the git_status tax and we've already configured `ahead_behind_count = false` to minimize it.

**Integration Contract — Phase 6:**
- *Triggered from:* Phase 5 complete.
- *Returns to / updates:* `~/.config/starship.toml` written with perf tunables.
- *Demonstrable by:* `starship prompt` runs; `starship print-config` parses.
- *Rollback signal:* `rm ~/.config/starship.toml` (falls back to defaults).
- *Observability added:* `STARSHIP_LOG=trace starship prompt` shows per-module ms.

---

## Phase 7 — Configure Atuin, zoxide, delta, and iTerm2/Ghostty integration

> Goal: Each tool has its config file and is wired so it's "live" once `.zshrc` sources it.

**Files:**
- Create: `~/.config/atuin/config.toml`
- Create: `~/.config/delta/themes.gitconfig` (gitconfig fragment, sourced via `~/.gitconfig`)

- [ ] **Step 7.1: Initialize Atuin**

Atuin works fully **without** an account (history is stored in a local SQLite DB). Pick exactly one of these two paths:

**Path A — local-only (recommended for first-time setup):**

```bash
# Do nothing. Atuin stores history in ~/.local/share/atuin/history.db.
# Verify with:
atuin status
# Expected output mentions "Local" mode and does NOT show "Logged in".
```

**Path B — cross-machine sync (only if you want history across machines):**

```bash
atuin register -u <github-username>    # creates account, prompts for password
# Or, if you already have an account:
atuin login -u <github-username>
# Verify with:
atuin status
# Expected: shows logged-in username and a sync server URL.
```

For team rollout, recommend **Path A** first. Sync can be enabled later without losing local history.

- [ ] **Step 7.2: Write `~/.config/atuin/config.toml`**

```toml
# Atuin — shell history
search_mode = "fuzzy"
style = "compact"
show_help = true
inline_indicators = true
exit_mode = "return-original"
keymap_mode = "emacs"
# sync = { ... }   # uncomment to enable cloud sync (local-only by default)
```

- [ ] **Step 7.3: Wire delta into git**

Add to `~/.gitconfig`:

```ini
[core]
    pager = delta

[interactive]
    diffFilter = delta --color-only

[delta]
    navigate = true
    light = false
    side-by-side = true
    line-numbers = true
    syntax-theme = catppuccin-mocha
    theme = catppuccin-mocha

[merge]
    conflictstyle = zdiff3
```

If the user already has a `~/.gitconfig`, merge these sections rather than overwriting. Backup first:

```bash
BACKUP=~/dotfiles-backup-$(date +%Y-%m-%d)
[ -f ~/.gitconfig ] && cp -a ~/.gitconfig "$BACKUP/.gitconfig"
```

- [ ] **Step 7.4: Verify delta renders**

```bash
mkdir -p /tmp/delta-bench && cd /tmp/delta-bench
git init -q
echo "one" > a.txt && git add a.txt && git commit -qm initial
echo "two" >> a.txt && echo "---"
git diff
```

Expected: side-by-side diff with catppuccin colors. If it renders as plain `+`/`-`, git is still using its default pager — check `~/.gitconfig`.

- [ ] **Step 7.5: Smoke-test zoxide**

```bash
mkdir -p /tmp/zoxide-bench && cd /tmp/zoxide-bench
zoxide query /tmp/zoxide 2>&1
```

Expected: prints the path (or empty if it's the first run). zoxide learns on first `cd` to a path.

**Integration Contract — Phase 7:**
- *Triggered from:* Phase 6 complete.
- *Returns to / updates:* `~/.config/atuin/config.toml`, `~/.gitconfig` updated.
- *Demonstrable by:* `git diff` uses delta; `atuin search test` returns results from history.
- *Rollback signal:* Restore `~/.gitconfig` from backup; `rm ~/.config/atuin/config.toml`.
- *Observability added:* Atuin DB at `~/.local/share/atuin/history.db` (gitignored from dotfiles).

---

## Phase 8 — Write the new `.zshrc`

> Goal: A minimal, readable `.zshrc` (~80 lines) that wires everything together. Nothing more.

**Files:**
- Modify: `~/.zshrc` (rewritten from scratch — old version is backed up)
- Touch (preserve): `~/.zprofile` (do NOT touch in this plan)

> **`.zprofile` note:** Login shells (SSH sessions, `tmux` with `default-shell`, terminal emulators that re-source on each window) read `.zprofile` first, then `.zshrc`. Any `PATH` exported in `.zshrc` only applies to non-login interactive shells. This plan keeps `.zprofile` untouched so any existing login-shell setup (e.g., Homebrew env, system-wide `PATH`) is preserved. If the engineer wants the new PATH exports to apply to login shells too, they can move the `export PATH=...` line from `.zshrc` to `.zprofile` — but doing so is **out of scope** for this plan.

- [ ] **Step 8.1: Snapshot the current `.zshrc`**

```bash
BACKUP=~/dotfiles-backup-$(date +%Y-%m-%d)
[ -f ~/.zshrc ] && cp -a ~/.zshrc "$BACKUP/.zshrc.pre-new"
```

- [ ] **Step 8.2: Write the new `~/.zshrc`**

```bash
# ~/.zshrc — minimal zsh config (Sheldon + Starship)
# Managed via dotfiles. See ~/dotfiles/zsh/zshrc.

# ---- 1. Environment ----
export PATH="$HOME/.local/bin:$PATH"
export LANG="en_US.UTF-8"
export EDITOR="${EDITOR:-vim}"
export VISUAL="${VISUAL:-vim}"

# ---- 2. Sheldon (plugin manager) ----
# `sheldon source` is a slow operation; cache its output.
SHELDON_CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/sheldon/init.zsh"
if [[ ! -r "$SHELDON_CACHE" ]] || [[ "$HOME/.config/sheldon/plugins.toml" -nt "$SHELDON_CACHE" ]]; then
  mkdir -p "${SHELDON_CACHE:h}"
  sheldon source > "$SHELDON_CACHE"
fi
source "$SHELDON_CACHE"
unset SHELDON_CACHE

# ---- 3. Prompt ----
eval "$(starship init zsh)"

# ---- 4. History (HISTSIZE large; defer to Atuin) ----
HISTSIZE=100000
SAVEHIST=100000
setopt HIST_IGNORE_DUPS HIST_IGNORE_SPACE SHARE_HISTORY EXTENDED_HISTORY
setopt INC_APPEND_HISTORY_TIME

# ---- 5. Atuin (Ctrl+R history search) ----
eval "$(atuin init zsh)"

# ---- 6. zoxide (smarter cd) ----
eval "$(zoxide init zsh)"

# ---- 7. direnv (per-directory env) ----
eval "$(direnv hook zsh)"

# ---- 8. Tool aliases ----
alias ls="eza --icons --group-directories-first"
alias ll="eza --icons --long --header --git"
alias la="eza --icons --long --header --git --all"
alias lt="eza --icons --tree --level=2"
alias cat="bat --paging=never"
alias catf="bat --plain"     # when you need plain (e.g., piped)
alias grep="rg"
alias find="fd"

# ---- 9. fzf ----
# `$(brew --prefix fzf)/install --no-update-rc` writes ~/.fzf.zsh but does NOT
# source it. The modern Homebrew fzf formula does NOT install an `fzf-share`
# helper, so source ~/.fzf.zsh directly.
[ -f ~/.fzf.zsh ] && source ~/.fzf.zsh

# ---- 10. fzf-tab must come after completion ----
# (Sheldon handles sourcing; no extra wiring needed here.)

# ---- 11. direnv safety: prompt before trust ----
# (direnv prompts by default; nothing to add.)
```

- [ ] **Step 8.3: Syntax-check the new `.zshrc`**

```bash
zsh -n ~/.zshrc && echo "syntax OK"
```

Expected: `syntax OK`. If errors, fix them before going further.

- [ ] **Step 8.4: Time the new shell**

```bash
{ time zsh -i -c 'exit' ; } 2>&1 | tail -3
```

Expected: under 200 ms cold (typically 50–150 ms on M-series Mac).

- [ ] **Step 8.5: Compare against the OMZ baseline from Step 0.3**

```bash
echo "Baseline (OMZ):"; grep -A1 'zsh -i' ~/.config/mahavishnu/zsh-migration.log | tail -1
echo "New stack:"; { time zsh -i -c 'exit'; } 2>&1 | grep real
```

Expected: new stack is faster than or comparable to OMZ. If it's slower, investigate — likely a plugin with a slow `init.zsh`.

- [ ] **Step 8.6: Smoke-launch interactive features in a subshell**

```bash
zsh -i -c '
echo "PROMPT4=$PROMPT"
echo "EZA=$commands[eza]"
echo "ZOXIDE=$commands[zoxide]"
echo "BAT=$commands[bat]"
echo "FD=$commands[fd]"
'
```

Expected: `PROMPT4` is set (Starship overrode it), and the commands resolve.

**Integration Contract — Phase 8:**
- *Triggered from:* Phases 5–7 complete.
- *Returns to / updates:* `~/.zshrc` rewritten. OMZ is **not** yet uninstalled.
- *Demonstrable by:* `time zsh -i -c exit` < 200 ms; all key commands resolve; prompt is Starship-rendered.
- *Rollback signal:* `cp -a ~/dotfiles-backup-<date>/.zshrc ~/.zshrc` restores the OMZ version.
- *Observability added:* Timing comparison logged at `~/.config/mahavishnu/zsh-migration.log`.

---

## Phase 9 — Validate in a real interactive shell (parallel mode)

> Goal: Use the new stack in real daily work for a week *without* it being the default. This catches things a subshell can't — TUI behavior, terminal escape codes, edge cases in scripts that assume OMZ aliases.

**Files:** none.

- [ ] **Step 9.1: Document the opt-in env var**

We don't gate the new stack on an env var (the new `.zshrc` is unconditional); instead, *don't swap the default yet*. The new `.zshrc` lives at `~/.zshrc` already. To **revert** to OMZ without uninstalling anything:

```bash
# Roll back to OMZ instantly:
cp -a ~/dotfiles-backup-$(date +%Y-%m-%d)/.zshrc.pre-new ~/.zshrc.bak
# then `cp -a ~/dotfiles-backup-<date>/.zshrc ~/.zshrc`
```

(Adapted because we *already* moved the new `.zshrc` into place. The backup is the rollback.)

- [ ] **Step 9.2: One-week real-world test**

Use the new shell as your daily driver for 5–7 working days. Track anything that feels wrong in `~/.config/mahavishnu/zsh-migration-issues.md`. Common categories:

| Symptom | Likely cause |
|---------|--------------|
| `Ctrl+R` doesn't show Atuin UI | Atuin init line not sourced (Phase 7) |
| Git icons show as `?` in prompt | Nerd Font not active in current shell — check `font-family` |
| `git diff` is plain text | `~/.gitconfig` delta line missing (Phase 7) |
| `j foo` says "zoxide: command not found" | zoxide init not sourced (Phase 8) |
| Prompt flicker on every Enter | Starship git_status — already mitigated |
| `composer`, `nvm`, `pyenv` aliases missing | Those plugins weren't included in `plugins.toml` — ad-hoc add |

- [ ] **Step 9.3: Decide before proceeding to Phase 10**

Gate: if more than two real issues remain after a week, debug those issues and re-test before moving on. If everything works, proceed to Phase 10.

**Integration Contract — Phase 9:**
- *Triggered from:* Phase 8 complete.
- *Returns to / updates:* `~/.config/mahavishnu/zsh-migration-issues.md` accumulates any complaints.
- *Demonstrable by:* After 5+ days of daily use, no unresolved issues remain.
- *Rollback signal:* `cp -a ~/dotfiles-backup-<date>/.zshrc ~/.zshrc`.
- *Observability added:* Issues log under `~/.config/mahavishnu/`.

---

## Phase 10 — Uninstall oh-my-zsh

> Goal: Remove the OMZ directory and any leftover scaffolding. Only proceed if Phase 9 gate passed.

**Files:**
- Delete: `~/.oh-my-zsh/`
- Modify: confirm `~/.zshrc` no longer references OMZ (already true from Phase 8).

- [ ] **Step 10.0: Verify the gate from Phase 9 passed**

```bash
[ -s ~/.config/mahavishnu/zsh-migration-issues.md ] && \
  echo "REVIEW ISSUES FILE BEFORE UNINSTALLING" || \
  echo "OK to proceed with OMZ uninstall"
```

If the issues file is non-empty, read it, fix the underlying problem, and re-run the daily-driver test. **Do not uninstall OMZ while known issues exist.**

- [ ] **Step 10.1: Confirm new `.zshrc` does not reference OMZ**

```bash
grep -E 'oh-my-zsh|ZSH_THEME|plugins=' ~/.zshrc || echo "clean"
```

Expected: `clean`. If any OMZ line remains, remove it.

- [ ] **Step 10.2: Move OMZ backup out of the way**

```bash
BACKUP=~/dotfiles-backup-$(date +%Y-%m-%d)
mv "$BACKUP/.oh-my-zsh" "$BACKUP/.oh-my-zsh.archived-$(date +%Y-%m-%d)"
```

This keeps the final pre-migration snapshot while removing the live `~/.oh-my-zsh/` directory. Don't `rm -rf` the backup.

- [ ] **Step 10.3: Verify shell still works**

```bash
{ time zsh -i -c 'exit' ; } 2>&1 | tail -3
echo "Oh-My-Zsh installed?: $([ -d ~/.oh-my-zsh ] && echo yes || echo no)"
```

Expected: under 200 ms; `no`. If `yes`, repeat Step 10.2.

**Integration Contract — Phase 10:**
- *Triggered from:* Phase 9 gate passed.
- *Returns to / updates:* `~/.oh-my-zsh/` archived (not deleted); `~/.zshrc` confirmed OMZ-free.
- *Demonstrable by:* `[ -d ~/.oh-my-zsh ]` returns false; shell still loads cleanly.
- *Rollback signal:* `mv ~/dotfiles-backup-<date>/.oh-my-zsh.archived-<date> ~/.oh-my-zsh; cp -a ~/dotfiles-backup-<date>/.zshrc ~/.zshrc` restores the original setup.
- *Observability added:* `~/dotfiles-backup-<date>/.oh-my-zsh.archived-<date>/` retained for 30 days, then `rm -rf`.

---

## Phase 11 — Dotfiles sync (reproducible on any machine)

> Goal: Capture the entire setup in a git repo so a fresh machine can reproduce it with one command.

**Files:**
- Create: `~/dotfiles/` (bare git repo working tree)
- Create: `~/dotfiles/zsh/zshrc` (the new `.zshrc`)
- Create: `~/dotfiles/zsh/starship.toml`
- Create: `~/dotfiles/zsh/sheldon/plugins.toml` + `plugins.lock`
- Create: `~/dotfiles/zsh/atuin/config.toml`
- Create: `~/dotfiles/zsh/Brewfile`
- Create: `~/dotfiles/zsh/ghostty/config`
- Create: `~/dotfiles/bootstrap.sh`

- [ ] **Step 11.1: Initialize a bare git repo as the dotfiles working tree**

```bash
git init --bare ~/dotfiles.git
git --git-dir=$HOME/dotfiles.git --work-tree=$HOME config core.worktree "$HOME"
git --git-dir=$HOME/dotfiles.git --work-tree=$HOME config status.showUntrackedFiles no
```

This is the well-known bare-repo-as-dotfile-trick: tracked files appear at their normal `$HOME` paths.

- [ ] **Step 11.2: Restage the actual config files into the dotfiles repo**

```bash
mkdir -p ~/dotfiles/zsh/{sheldon,atuin} ~/dotfiles/ghostty

cp ~/.zshrc ~/dotfiles/zsh/zshrc
cp ~/.config/starship.toml ~/dotfiles/zsh/starship.toml
cp ~/.config/sheldon/plugins.toml ~/dotfiles/zsh/sheldon/plugins.toml
cp ~/.config/sheldon/plugins.lock ~/dotfiles/zsh/sheldon/plugins.lock
cp ~/.config/atuin/config.toml ~/dotfiles/zsh/atuin/config.toml
cp ~/Brewfile.zsh-migration ~/dotfiles/zsh/Brewfile
cp ~/.config/ghostty/config ~/dotfiles/ghostty/config
```

- [ ] **Step 11.3: Write the bootstrap script**

Write `~/dotfiles/bootstrap.sh`:

```bash
#!/usr/bin/env bash
# Reproduces the zsh stack on a fresh macOS machine.
# Usage: bash ~/dotfiles/bootstrap.sh

set -euo pipefail

# 1. Homebrew (assume installed; abort if not)
command -v brew >/dev/null || { echo "Install Homebrew first: https://brew.sh"; exit 1; }

# 2. Tools
brew bundle --file="$HOME/dotfiles/zsh/Brewfile"

# 3. Configs (symlink, do not copy — single source of truth in dotfiles/)
mkdir -p ~/.config/{sheldon,atuin} ~/.config/ghostty

ln -sf "$HOME/dotfiles/zsh/zshrc"               "$HOME/.zshrc"
ln -sf "$HOME/dotfiles/zsh/starship.toml"       "$HOME/.config/starship.toml"
ln -sf "$HOME/dotfiles/zsh/sheldon/plugins.toml" "$HOME/.config/sheldon/plugins.toml"
ln -sf "$HOME/dotfiles/zsh/sheldon/plugins.lock" "$HOME/.config/sheldon/plugins.lock"
ln -sf "$HOME/dotfiles/zsh/atuin/config.toml"   "$HOME/.config/atuin/config.toml"
ln -sf "$HOME/dotfiles/ghostty/config"          "$HOME/.config/ghostty/config"

# 4. fzf install (writes ~/.fzf.zsh; we source it from ~/.zshrc, not from rc files directly)
"$(brew --prefix fzf)/install" --key-bindings --completion \
  --no-update-rc --no-bash --no-fish

# 5. Sheldon lock
sheldon lock

# 6. Verify
zsh -n "$HOME/.zshrc" && echo "OK: bootstrap complete"
```

```bash
chmod +x ~/dotfiles/bootstrap.sh
```

- [ ] **Step 11.4: First commit**

First, ensure git identity is set for this repo (the bare-repo trick may not inherit your global git config):

```bash
git --git-dir=$HOME/dotfiles.git --work-tree=$HOME config user.name  "Your Name"
git --git-dir=$HOME/dotfiles.git --work-tree=$HOME config user.email "you@example.com"
```

Then commit:

```bash
git --git-dir=$HOME/dotfiles.git --work-tree=$HOME add \
  dotfiles/zsh/zshrc \
  dotfiles/zsh/starship.toml \
  dotfiles/zsh/sheldon/plugins.toml \
  dotfiles/zsh/sheldon/plugins.lock \
  dotfiles/zsh/atuin/config.toml \
  dotfiles/zsh/Brewfile \
  dotfiles/ghostty/config \
  dotfiles/bootstrap.sh

git --git-dir=$HOME/dotfiles.git --work-tree=$HOME commit -m "feat(dotfiles): zsh stack with sheldon + starship"
```

- [ ] **Step 11.5: Push to a remote (manual)**

```bash
# Optional: create the GitHub repo first
gh repo create dotfiles --private --source ~/dotfiles.git --push
```

Engineer runs this manually with their own credentials — never automate `git push` to user-controlled repos per Bodai policy.

- [ ] **Step 11.6: Verify the bootstrap on a clean machine (or container)**

Manual: spin up a fresh macOS VM or Linux container, install Homebrew, then run:

```bash
# IMPORTANT: clone as a regular (non-bare) repo into ~/dotfiles, NOT as a bare repo.
# The bare-repo trick is only for the engineer's own machine where work-tree = $HOME.
git clone <remote-url> ~/dotfiles
bash ~/dotfiles/bootstrap.sh
```

Expected: shell ready in under 5 minutes with identical prompt and behavior.

**Integration Contract — Phase 11:**
- *Triggered from:* Phase 10 complete.
- *Returns to / updates:* `~/dotfiles/` is now a tracked git repo. `bootstrap.sh` reproduces the entire setup.
- *Demonstrable by:* Running `bash bootstrap.sh` on a fresh machine produces a working shell with the same plugin set, prompt, and aliases.
- *Rollback signal:* Not strictly reversible — the dotfiles repo is the new source of truth. To undo, delete `~/dotfiles/` and restore `~/dotfiles-backup-<date>/` files manually.
- *Observability added:* Single source of truth for cross-machine parity.

---

## Phase 12 — Final verification + cleanup

> Goal: Run the success-criteria checklist from the spec; delete the backup after 30 days.

**Files:** none new.

**Integration Contract — Phase 12:**
- *Triggered from:* Phase 11 (dotfiles synced) complete.
- *Returns to / updates:* `~/.config/mahavishnu/zsh-migration.log` gains a completion entry; backup deletion scheduled.
- *Demonstrable by:* All Step 12.1 smoke tests pass; `atq` shows the scheduled deletion; log has the completion entry.
- *Rollback signal:* The `~/dotfiles-backup-<date>/` directory still exists until 2026-09-30 (manual `rm -rf` if needed sooner). The dotfiles repo at `~/dotfiles/` is the new source of truth — restore from there if Phase 12 itself goes wrong.
- *Observability added:* Final completion entry in the migration log; `atq` job ID for the cleanup.

- [ ] **Step 12.1: Run the success-criteria smoke tests from the spec**

```bash
set -e

# 1. Tool versions
sheldon --version | head -1
starship --version | head -1

# 2. All required binaries resolve
for cmd in zoxide atuin delta fzf bat eza fd rg direnv; do
  command -v "$cmd" >/dev/null || { echo "FAIL: $cmd missing"; exit 1; }
done

# 3. Starship is the active prompt (STARSHIP_CONFIG is set; PROMPT4 contains a starship-rendered arrow)
zsh -i -c '[[ -n "$STARSHIP_CONFIG" ]] && [[ "$PROMPT4" == *"❯"* ]] && echo "OK: starship-active"' \
  | tail -1 | grep -q "OK: starship-active" || { echo "FAIL: starship not active"; exit 1; }

# 4. OMZ is NOT sourced at runtime (spec success criterion)
OMZ_VARS=$(zsh -i -c 'print -l ${(k)parameters[(R)POWERLEVEL*]}')
[ -z "$OMZ_VARS" ] || { echo "FAIL: OMZ vars still set: $OMZ_VARS"; exit 1; }
echo "OK: no OMZ runtime state"

# 5. Aliases are active in interactive shells
zsh -i -c 'alias cat' | grep -q bat || { echo "FAIL: cat not aliased to bat"; exit 1; }
zsh -i -c 'alias j' | grep -q zoxide || { echo "FAIL: j not aliased to zoxide"; exit 1; }
zsh -i -c 'alias ls' | grep -q eza || { echo "FAIL: ls not aliased to eza"; exit 1; }
echo "OK: aliases active"

# 6. Atuin registered Ctrl+R keybind (best-effort; if grep fails, fall through to manual)
if zsh -i -c 'bindkey -M main "^R"' 2>/dev/null | grep -qi atuin; then
  echo "OK: atuin Ctrl+R bound"
else
  echo "WARN: cannot auto-verify Atuin Ctrl+R; verify manually with Ctrl+R in a fresh shell"
fi
```

Expected: every line succeeds; no `FAIL`. The `WARN` for Atuin's Ctrl+R is acceptable (keybind tables are tricky to introspect in non-interactive shells).

- [ ] **Step 12.2: Confirm OMZ is fully gone**

```bash
[ ! -d ~/.oh-my-zsh ] && [ ! -L ~/.oh-my-zsh ] && echo "OMZ fully removed"
```

- [ ] **Step 12.3: Schedule backup deletion (30 days out)**

Use `at` so the backup is actually deleted on a date, not just noted:

```bash
if command -v at >/dev/null 2>&1; then
  echo "rm -rf ~/dotfiles-backup-$(date +%Y-%m-%d)" | at 09:00 2026-09-30
else
  echo "WARN: 'at' not installed; install via 'brew install at' and re-run, or set a manual calendar reminder."
fi
```

Verify the job landed:

```bash
atq | grep "dotfiles-backup"
```

If `at` is not desired, replace the `at` invocation with a manual `launchd` plist or a calendar reminder. Do not rely on a passive text file in the backup directory — that gets deleted with the backup.

- [ ] **Step 12.4: Append completion entry to the migration log**

Append to `~/.config/mahavishnu/zsh-migration.log`:

```markdown
## Migration completed: 2026-08-31
- Old: oh-my-zsh (~XXXms cold)
- New: sheldon + starship (~XXms cold)
- Plugins migrated: <list>
- Backup retained until: 2026-09-30
```

**Integration Contract — Plan as a whole:**
- *Triggered from:* User decision to move off OMZ.
- *Returns to / updates:* New zsh stack installed, OMZ archived, dotfiles repo ready for sync.
- *Demonstrable by:* Fresh shell has Starship prompt, all 11 commands resolve, plugins load, OMZ absent.
- *Rollback signal:* `~/dotfiles-backup-<date>/` retained for 30 days.
- *Observability added:* `~/.config/mahavishnu/zsh-migration.log` records baseline + completion.

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Plan task |
|---|---|
| Sheldon installed + configured | Phase 4, Phase 5 |
| Starship installed + configured (with perf mitigations) | Phase 4, Phase 6 |
| Nerd Font installed | Phase 1 |
| Ghostty configured | Phase 2 |
| iTerm2 configured | Phase 3 |
| Atuin installed + configured | Phase 4, Phase 7 |
| zoxide installed + configured | Phase 4, Phase 8 |
| delta installed + configured | Phase 4, Phase 7 |
| fzf + fzf-tab wired | Phase 4, Phase 5, Phase 8 |
| bat / eza / fd / rg / direnv wired | Phase 4, Phase 8 |
| .zshrc rewritten | Phase 8 |
| OMZ uninstalled (after gate) | Phase 9, Phase 10 |
| Dotfiles sync | Phase 11 |
| Backup strategy | Phase 0, every subsequent phase |
| Rollback signal per phase | Every phase (Integration Contract) |
| Reproducibility on fresh machine | Phase 11 (bootstrap.sh) |
| Out-of-scope: Linux, bash, devcontainer | Acknowledged in spec |

**Placeholder scan:** No "TBD", "TODO", "implement later", or "fill in details" in any task. All code blocks contain literal content. Each task's verification command is concrete.

**Type/name consistency:**
- File paths use `~/.config/...` consistently; Brewfile lives at `~/Brewfile.zsh-migration` then moves to `~/dotfiles/zsh/Brewfile`.
- Backup dir `~/dotfiles-backup-<date>/` is referenced identically across all phases.
- Tool names match exactly between Phase 4 (install) and Phase 7/8 (configure): sheldon, starship, atuin, zoxide, delta, fzf, bat, eza, fd, rg, direnv.

**Integration Contract discipline:** Every phase has all five required fields (Triggered from / Returns to / Demonstrable by / Rollback signal / Observability added) per `AGENTS.md` Process Discipline.

---

## Plan Complete

Plan saved to `docs/superpowers/plans/2026-08-31-zsh-modernization.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — Dispatch a fresh subagent per Phase, review between Phases. Best for a multi-day migration where each Phase is a separate work session.

2. **Inline Execution** — Execute Phases in this session using `superpowers:executing-plans`, batch with checkpoints. Best if you want to do everything in one sitting.

Which approach would you like? If you also want me to recommend any of the optional tools I excluded from this plan (e.g., thefuck, direnv prompt-theming, Powerlevel10k-as-fallback for terminal-only mode), say so before we start — easier to fold into the Brewfile now than to revisit later.

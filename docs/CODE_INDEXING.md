# Code Graph Indexing System

Mahavishnu maintains code graphs for all Bodai ecosystem repositories, enabling semantic search, call chain analysis, and impact assessment across the ecosystem.

## Overview

**Component responsible**: Mahavishnu (`mahavishnu/core/code_index/`)

**Storage backend**: Session-Buddy via MCP at `localhost:8678`

**Fallback**: Local queue at `~/.claude/data/mahavishnu-index-queue/` when Session-Buddy is unavailable

## Architecture

```
git commit
    │
    ▼
.git/hooks/post-commit (installed per-repo)
    │
    ▼
mahavishnu index repo --trigger git-event --repo /path/to/repo &
    │
    ├──► filter_changed_files() → git diff (incremental) or git ls-files (full)
    │
    ├──► parse_file() → CodeGraphAnalyzer._analyze_python_file() (async)
    │
    ├──► _upsert_to_session_buddy() → POST to localhost:8678/mcp
    │
    └───► [on failure] _queue_locally() → ~/.claude/data/mahavishnu-index-queue/
```

## Key Files

| File | Purpose |
|------|---------|
| `mahavishnu/core/code_index/indexer.py` | Main orchestration: detects changes, parses, upserts |
| `mahavishnu/core/code_index/parser.py` | Parses Python files into graph nodes/edges |
| `mahavishnu/core/code_index/models.py` | Pydantic models: `CodeGraphNode`, `CodeGraphEdge`, `IndexWorkItem` |
| `mahavishnu/core/code_index/git_hooks.py` | Installs/removes git hooks for auto-indexing |
| `mahavishnu/core/code_index/path_validation.py` | Validates repo paths against `settings/ecosystem.yaml` |

## CLI Commands

```bash
# Index a repo (manual trigger)
mahavishnu index repo /path/to/repo --full    # Full re-index (all tracked .py files)
mahavishnu index repo /path/to/repo           # Incremental (only changed files)

# Check status
mahavishnu index status

# Install auto-index hooks (post-commit, post-merge, post-rewrite)
mahavishnu index install-hooks /path/to/repo --force

# Remove hooks
mahavishnu index uninstall-hooks /path/to/repo
```

## Gitignore Compliance

The indexer respects `.gitignore` through two mechanisms:

- **Incremental indexing**: Uses `git diff --name-only` — only tracked, non-ignored files appear
- **Full re-index**: Uses `git ls-files --cached` — returns all tracked files, gitignore is inherently respected

SKIP_DIRS in `parser.py` provides an additional guard:

```python
SKIP_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "node_modules",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "htmlcov",
    "dist", "build", ".eggs", ".tox",
}
```

Note: Tests are NOT excluded by SKIP_DIRS. The `CodeGraphAnalyzer` from `mcp-common` has internal test-file filtering that applies when using `analyze_repository()`, but direct calls to `_analyze_python_file()` (which Mahavishnu uses) bypass that filter.

## Hook Installation

Hooks must be installed **per-repo** since `.git/hooks/` is repo-local:

```bash
# Install on all Bodai repos
for repo in mahavishnu crackerjack session-buddy akosha dhara oneiric mcp-common mdinject; do
  mahavishnu index install-hooks /Users/les/Projects/$repo --force
done
```

Hook content (installed in `.git/hooks/post-commit`, `.git/hooks/post-merge`, `.git/hooks/post-rewrite`):

```sh
#!/bin/sh
# Managed by mahavishnu index --install-hooks
# Remove with: mahavishnu index --uninstall-hooks --repo <path>
mahavishnu index repo --trigger git-event --repo "$(pwd)" &
```

The `&` runs indexing in the background so git operations aren't blocked.

## Queue and Recovery

When Session-Buddy is unavailable, indexed data is queued locally:

```bash
ls ~/.claude/data/mahavishnu-index-queue/
```

To flush the queue, ensure Session-Buddy is running then re-index:

```bash
python -m session_buddy start --force  # if not running
mahavishnu index repo /path/to/repo --full
```

## Indexing Status (Current)

| Repo | Status | Files Indexed |
|------|--------|---------------|
| mahavishnu | ✅ Indexed | 833 |
| akosha | ✅ Indexed | 145 |
| dhara | ✅ Indexed | 311 |
| mcp-common | ✅ Indexed | 175 |
| mdinject | ✅ Indexed | 84 |
| oneiric | ✅ Indexed | 418 |
| crackerjack | ✅ Indexed | 992 |
| session-buddy | ✅ Indexed | 541 |

All repos have hooks installed for auto-indexing on git events.

## Bugs Fixed

1. **Pydantic forward reference** (`models.py`): `datetime` was in `TYPE_CHECKING` block, causing `IndexWorkItem` initialization to fail. Fixed by importing `datetime` normally.

1. **Async method handling** (`parser.py`): `_analyze_python_file()` is `async` and returns `None` (populates `analyzer.nodes` instead). The code was treating the return value as having `.nodes`. Fixed with `asyncio.run()` + direct node access.

1. **Path resolution** (`path_validation.py`): `get_registered_repos()` resolved `settings/repos_path` relative to `cwd` instead of the project directory. Fixed to use `Path(__file__)`-based resolution.

1. **Git hook command** (`git_hooks.py`): Hook used `mahavishnu index --trigger` but the CLI expects `mahavishnu index repo --trigger`. Fixed the hook template.

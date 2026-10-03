---
status: shipped
role: implementation
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
topic: splashstand-oneiric
---

# Splashstand ACB → Oneiric Migration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Status:** COMPLETE — all tasks checked [x]. Splashstand uses `from oneiric...` imports throughout; pyproject.toml restored. Verified via `MIGRATION-3.1.0.md`. Reference only. <!-- legacy status: COMPLETE — see YAML frontmatter -->
> **Goal:** Replace all ACB imports with Oneiric equivalents across 17 Splashstand source files, restoring pyproject.toml and adding a `resolve_dep()` helper.
> **Architecture:** Mechanical import rename from `acb.*` to `oneiric.*` plus a `splashstand/deps.py` helper module. The `depends.inject` decorator is replaced with direct `resolve_dep()` calls. `dump`/`load` from `acb.actions.encode` are replaced with `yaml`/`json` standard library calls.
> **Tech Stack:** Python 3.13, Oneiric (replacement for ACB), Fastblocks, PyYAML, Starlette
> **Spec:** `docs/superpowers/specs/2026-04-26-splashstand-oneiric-migration-design.md`
> **Working directory:** `/Users/les/Projects/splashstand`

______________________________________________________________________

## Import Mapping Reference

| ACB Import | Oneiric Equivalent | Files Affected |
|------------|-------------------|----------------|
| `from acb import register_pkg` | `from oneiric import register_pkg` | main.py |
| `from acb.depends import depends` | `from splashstand.deps import resolve_dep` | 13 files |
| `from acb.config import AdapterBase` | `from oneiric.config import AdapterBase` | 6 files |
| `from acb.config import Config` | `from oneiric.config import Config` | 7 files |
| `from acb.config import Settings` | `from oneiric.config import Settings` | 4 files |
| `from acb.config import AppSettings` | `from oneiric.config import AppSettings` | 1 file |
| `from acb.adapters import import_adapter` | `from oneiric.adapters import import_adapter` | 6 files |
| `from acb.adapters import get_adapter` | `from oneiric.adapters import get_adapter` | 1 file |
| `from acb.adapters import root_path` | `from oneiric.adapters import root_path` | 1 file |
| `from acb.adapters import tmp_path` | `from oneiric.adapters import tmp_path` | 1 file |
| `from acb.adapters.dns._base import DnsRecord` | `from oneiric.adapters.dns._base import DnsRecord` | 1 file |
| `from acb.console import console` | `from oneiric.console import console` | 1 file |
| `from acb.debug import debug` | `from oneiric.debug import debug` | 5 files |
| `from acb.logger import Logger` | `from oneiric.logger import Logger` | 2 files |
| `from acb.actions.encode import dump, load` | `import yaml` (direct calls) | 2 files |
| `from fastblocks.applications import FastBlocks` | No change | 2 files |

______________________________________________________________________

### Task 1: Create migration branch and restore pyproject.toml

**Files:**

- Create: branch `migration/acb-to-oneiric`

- Modify: `pyproject.toml`

- [x] **Step 1: Create migration branch**

```bash
cd /Users/les/Projects/splashstand
git checkout -b migration/acb-to-oneiric
```

- [x] **Step 2: Restore pyproject.toml with [project] table**

The current `pyproject.toml` is broken — it contains only `[tool.ruff]` and `[tool.pytest.ini_options]`. Write the complete file with the `[project]` table, replacing `acb` with `oneiric` in dependencies:

```toml
[project]
name = "splashstand"
version = "3.1.0"
description = "Full-stack async web application built on Fastblocks"
requires-python = ">=3.12"
dependencies = [
    "oneiric>=0.19.0",
    "fastblocks>=0.19.0",
    "uvicorn[standard]>=0.30.0",
]

[dependency-groups]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "ruff>=0.5.0",
    "pyright>=1.1.0",
]

[tool.ruff]
target-version = "py313"
line-length = 88
exclude = [
    "tests/",
    "test_*.py",
    "*_test.py",
]

[tool.ruff.lint]
extend-select = [
    "C901",
    "F",
    "I",
    "UP",
]
ignore = [
    "E402",
    "F821",
]
fixable = [
    "ALL",
]

[tool.ruff.lint.mccabe]
max-complexity = 15

[tool.pytest.ini_options]
asyncio_mode = "auto"
timeout = 600
```

- [x] **Step 3: Verify pyproject.toml parses correctly**

```bash
cd /Users/les/Projects/splashstand
python -c "import tomllib; tomllib.load(open('pyproject.toml', 'rb'))"
```

Expected: No output (successful parse)

- [x] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "fix: restore pyproject.toml [project] table with oneiric dependency"
```

______________________________________________________________________

### Task 2: Create resolve_dep() helper module

**Files:**

- Create: `splashstand/deps.py`

- [x] **Step 1: Write splashstand/deps.py**

```python
from oneiric.core.resolution import Resolver

_resolver = Resolver()


def resolve_dep(key: str):
    candidate = _resolver.resolve("splashstand", key)
    if candidate is None:
        raise RuntimeError(f"Missing dependency: {key}")
    factory = getattr(candidate, "factory", None)
    return factory() if callable(factory) else candidate
```

This module has **no side effects on import** — it creates a `Resolver` instance but doesn't call `register_pkg()` or trigger any entry-point initialization. This is why it lives in its own file rather than `main.py`.

- [x] **Step 2: Verify import works (will fail until oneiric installed, that's OK)**

```bash
cd /Users/les/Projects/splashstand
python -c "from splashstand.deps import resolve_dep; print('import OK')" 2>&1 || true
```

- [x] **Step 3: Commit**

```bash
git add splashstand/deps.py
git commit -m "feat: add resolve_dep() helper for Oneiric dependency resolution"
```

______________________________________________________________________

### Task 3: Migrate main.py

**Files:**

- Modify: `splashstand/main.py`

- [x] **Step 1: Replace imports and update depends calls**

Replace the entire content of `splashstand/main.py`:

```python
from oneiric import register_pkg
from splashstand.deps import resolve_dep
from fastblocks.applications import FastBlocks  # noqa  # type: ignore

register_pkg()

app = resolve_dep("app")
logger = resolve_dep("logger")

logger.info(f"Starting application at: {app.__module__}")
```

Key changes:

- `from acb import register_pkg` → `from oneiric import register_pkg`

- `from acb.depends import depends` → `from splashstand.deps import resolve_dep`

- `depends.get()` → `resolve_dep(...)`

- [x] **Step 2: Verify no ACB imports remain**

```bash
grep -n "acb" splashstand/main.py
```

Expected: No output

- [x] **Step 3: Commit**

```bash
git add splashstand/main.py
git commit -m "refactor: migrate main.py from ACB to Oneiric"
```

______________________________________________________________________

### Task 4: Migrate adapter base classes (6 files)

These files all follow the same pattern: replace `acb.config` imports with `oneiric.config`.

**Files:**

- Modify: `splashstand/adapters/app/_base.py`

- Modify: `splashstand/adapters/auth/_base.py`

- Modify: `splashstand/adapters/admin/_base.py`

- Modify: `splashstand/adapters/schemas/_base.py`

- Modify: `splashstand/adapters/captcha/_base.py`

- Modify: `splashstand/adapters/pwa/_base.py`

- [x] **Step 1: Migrate app/\_base.py**

In `splashstand/adapters/app/_base.py`, replace:

```python
from acb.config import AdapterBase
from acb.config import AppSettings as AppConfigSettings
```

with:

```python
from oneiric.config import AdapterBase
from oneiric.config import AppSettings as AppConfigSettings
```

- [x] **Step 2: Migrate auth/\_base.py**

In `splashstand/adapters/auth/_base.py`, replace:

```python
from acb.config import AdapterBase, Config, Settings
from acb.depends import depends
```

with:

```python
from oneiric.config import AdapterBase, Config, Settings
from splashstand.deps import resolve_dep
```

Then update the `@depends.inject` decorator on `AuthBaseSettings.__init__`. Replace:

```python
    @depends.inject
    def __init__(self, config: Config = depends(), **data: t.Any) -> None:
```

with:

```python
    def __init__(self, config: Config | None = None, **data: t.Any) -> None:
        if config is None:
            config = resolve_dep("config")
```

- [x] **Step 3: Migrate admin/\_base.py**

In `splashstand/adapters/admin/_base.py`, replace:

```python
from acb.config import AdapterBase, Settings
```

with:

```python
from oneiric.config import AdapterBase, Settings
```

- [x] **Step 4: Migrate schemas/\_base.py**

In `splashstand/adapters/schemas/_base.py`, replace:

```python
from acb.config import AdapterBase, Settings
```

with:

```python
from oneiric.config import AdapterBase, Settings
```

- [x] **Step 5: Migrate captcha/\_base.py**

In `splashstand/adapters/captcha/_base.py`, replace:

```python
from acb.config import AdapterBase, Settings
```

with:

```python
from oneiric.config import AdapterBase, Settings
```

- [x] **Step 6: Migrate pwa/\_base.py**

In `splashstand/adapters/pwa/_base.py`, replace:

```python
from acb.config import AdapterBase, Settings
```

with:

```python
from oneiric.config import AdapterBase, Settings
```

- [x] **Step 7: Verify no ACB imports remain in \_base files**

```bash
grep -rn "from acb" splashstand/adapters/*/_base.py
```

Expected: No output

- [x] **Step 8: Commit**

```bash
git add splashstand/adapters/
git commit -m "refactor: migrate all adapter base classes from ACB to Oneiric"
```

______________________________________________________________________

### Task 5: Migrate adapter implementation files (10 files)

These files contain the bulk of ACB imports including `depends`, `debug`, `Logger`, `import_adapter`, `Config`, and `load`.

**Files:**

- Modify: `splashstand/adapters/admin/sqladmin.py`

- Modify: `splashstand/adapters/analytics/google.py`

- Modify: `splashstand/adapters/app/default.py`

- Modify: `splashstand/adapters/app/demo.py`

- Modify: `splashstand/adapters/auth/firebase.py`

- Modify: `splashstand/adapters/captcha/google.py`

- Modify: `splashstand/adapters/pwa/_routes.py`

- Modify: `splashstand/adapters/pwa/app.py`

- Modify: `splashstand/adapters/schemas/_models/__init__.py`

- Modify: `splashstand/adapters/schemas/schemaorg.py`

- [x] **Step 1: Migrate admin/sqladmin.py**

Replace these imports:

```python
from acb.actions.encode import load          → import json
from acb.adapters import import_adapter      → from oneiric.adapters import import_adapter
from acb.config import Config                → from oneiric.config import Config
from acb.debug import debug                  → from oneiric.debug import debug
from acb.depends import depends              → from splashstand.deps import resolve_dep
```

Find all `load.json(...)` calls and replace with `json.loads(Path(...).read_text())`. Find all `@depends.inject` decorators and `depends()` default arguments, replacing with `resolve_dep()` calls (same pattern as auth/\_base.py in Task 4 Step 2).

- [x] **Step 2: Migrate analytics/google.py**

Replace:

```python
from acb.depends import depends → from splashstand.deps import resolve_dep
```

Update `@depends.inject` decorators and `depends()` defaults as needed.

- [x] **Step 3: Migrate app/default.py**

Replace:

```python
from acb.adapters import get_adapter, import_adapter → from oneiric.adapters import get_adapter, import_adapter
from acb.config import Config                       → from oneiric.config import Config
from acb.depends import depends                     → from splashstand.deps import resolve_dep
```

- [x] **Step 4: Migrate app/demo.py**

Replace:

```python
from acb.adapters import import_adapter → from oneiric.adapters import import_adapter
from acb.config import Config          → from oneiric.config import Config
from acb.debug import debug            → from oneiric.debug import debug
from acb.depends import depends        → from splashstand.deps import resolve_dep
from acb.logger import Logger          → from oneiric.logger import Logger
```

- [x] **Step 5: Migrate auth/firebase.py**

Replace:

```python
from acb.config import Config     → from oneiric.config import Config
from acb.debug import debug       → from oneiric.debug import debug
from acb.depends import depends   → from splashstand.deps import resolve_dep
```

- [x] **Step 6: Migrate captcha/google.py**

Replace:

```python
from acb.adapters import import_adapter → from oneiric.adapters import import_adapter
from acb.config import Config          → from oneiric.config import Config
from acb.depends import depends        → from splashstand.deps import resolve_dep
from acb.logger import Logger          → from oneiric.logger import Logger
```

- [x] **Step 7: Migrate pwa/\_routes.py**

Replace:

```python
from acb.adapters import import_adapter → from oneiric.adapters import import_adapter
from acb.debug import debug            → from oneiric.debug import debug
from acb.depends import depends        → from splashstand.deps import resolve_dep
```

- [x] **Step 8: Migrate pwa/app.py**

Replace:

```python
from acb.config import Config     → from oneiric.config import Config
from acb.depends import depends   → from splashstand.deps import resolve_dep
```

- [x] **Step 9: Migrate schemas/\_models/__init__.py**

Replace:

```python
from acb.depends import depends → from splashstand.deps import resolve_dep
```

- [x] **Step 10: Migrate schemas/schemaorg.py**

Replace:

```python
from acb.adapters import import_adapter → from oneiric.adapters import import_adapter
from acb.config import Config          → from oneiric.config import Config
from acb.debug import debug            → from oneiric.debug import debug
from acb.depends import depends        → from splashstand.deps import resolve_dep
from acb.logger import Logger          → from oneiric.logger import Logger
```

- [x] **Step 11: Verify no ACB imports remain in adapters**

```bash
grep -rn "from acb\|import acb" splashstand/adapters/
```

Expected: No output

- [x] **Step 12: Commit**

```bash
git add splashstand/adapters/
git commit -m "refactor: migrate all adapter implementations from ACB to Oneiric"
```

______________________________________________________________________

### Task 6: Migrate cli.py (the most complex file)

**Files:**

- Modify: `splashstand/cli.py`

`cli.py` is the most import-heavy file (6 ACB imports) and includes the `dump`/`load` convenience methods from `acb.actions.encode`.

- [x] **Step 1: Read cli.py to understand all ACB usage**

```bash
grep -n "acb\|dump\.\|load\." splashstand/cli.py
```

- [x] **Step 2: Replace imports**

Replace:

```python
from acb.actions.encode import dump, load          → import yaml, json (add to existing imports)
from acb.adapters import import_adapter, root_path, tmp_path → from oneiric.adapters import import_adapter, root_path, tmp_path
from acb.adapters.dns._base import DnsRecord      → from oneiric.adapters.dns._base import DnsRecord
from acb.console import console                     → from oneiric.console import console
from acb.depends import depends                     → from splashstand.deps import resolve_dep
```

- [x] **Step 3: Replace dump/load calls**

Find each usage and replace:

- `dump.yaml(data, path)` → `Path(path).write_text(yaml.dump(data))`
- `dump.json(data, path)` → `Path(path).write_text(json.dumps(data, indent=2))`
- `load.yaml(path)` → `yaml.safe_load(Path(path).read_text())`
- `load.json(path)` → `json.loads(Path(path).read_text())`

If `Path` is not already imported, add `from pathlib import Path` (it may already be imported — check first).

- [x] **Step 4: Replace depends() calls**

Find `depends.get()` and `depends.inject` patterns and replace with `resolve_dep()`.

- [x] **Step 5: Verify no ACB imports remain**

```bash
grep -n "acb" splashstand/cli.py
```

Expected: No output

- [x] **Step 6: Commit**

```bash
git add splashstand/cli.py
git commit -m "refactor: migrate cli.py from ACB to Oneiric, replace dump/load with yaml/json"
```

______________________________________________________________________

### Task 7: Final verification and cleanup

- [x] **Step 1: Full ACB import scan**

```bash
grep -rn "from acb\|import acb" splashstand/
```

Expected: No output

- [x] **Step 2: Verify oneiric is in dependencies**

```bash
grep "oneiric" pyproject.toml
```

Expected: `oneiric>=0.19.0` in dependencies

- [x] **Step 3: Verify acb is NOT in dependencies**

```bash
grep "acb" pyproject.toml
```

Expected: No output

- [x] **Step 4: Verify deps.py exists**

```bash
test -f splashstand/deps.py && echo "OK" || echo "MISSING"
```

Expected: OK

- [x] **Step 5: Run tests**

```bash
cd /Users/les/Projects/splashstand
python -m pytest tests/ -v 2>&1 | tail -20
```

- [x] **Step 6: Update MIGRATION-3.1.0.md**

Add a section documenting the completed ACB → Oneiric migration:

- Date completed

- Files changed (17)

- Import replacements (47)

- Key pattern changes (depends → resolve_dep, dump/load → yaml/json)

- [x] **Step 7: Final commit**

```bash
git add -A
git commit -m "docs: update MIGRATION-3.1.0.md with ACB → Oneiric migration status"
```

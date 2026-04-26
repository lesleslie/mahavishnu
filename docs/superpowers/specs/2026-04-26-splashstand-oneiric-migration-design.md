# Splashstand ACB → Oneiric Migration Design

**Date**: 2026-04-26
**Status**: Draft
**Schema version**: 1.0

## 1. Problem Statement

Splashstand depends on ACB (action-class-blocks), an archived project that is no longer developed. Three other Bodai ecosystem projects (Crackerjack, Session-Buddy, Fastblocks) have already migrated from ACB to Oneiric, ACB's successor. Splashstand has ~25 ACB import sites across ~12 files that need replacement with Oneiric equivalents. Additionally, Splashstand's `pyproject.toml` is broken in the working tree (the `[project]` table is missing), though a staged fix exists.

## 2. Goals

- Replace all ACB imports with Oneiric equivalents across every Splashstand source file.
- Adopt the Fastblocks/Oneiric helper pattern (`resolve_dep()`) used by the three successfully migrated projects.
- Ensure Splashstand runs on Fastblocks 0.19+ with zero ACB imports.
- Preserve all existing functionality — this is a drop-in replacement, not a feature change.

## 3. Non-Goals

- No template migration — Splashstand already uses `[[ ]]` Jinja2 delimiters, matching Fastblocks conventions.
- No feature additions or refactoring beyond what the import changes require.
- No changes to Splashstand's business logic, routing, or adapter behavior.

## 4. Current State

### 4.1 Import Inventory

Splashstand has ~25 ACB import statements across ~12 files. Zero `from oneiric` or `import oneiric` imports exist.

| File | ACB Imports |
|------|------------|
| `main.py` | `register_pkg`, `depends` |
| `cli.py` | `depends`, `dump`, `load`, `import_adapter`, `root_path`, `tmp_path`, `DnsRecord`, `console` |
| `adapters/app/_base.py` | `AdapterBase`, `AppSettings` |
| `adapters/app/demo.py` | `import_adapter`, `Config`, `debug`, `depends`, `Logger` |
| `adapters/app/default.py` | `get_adapter`, `import_adapter`, `Config`, `depends` |
| `adapters/auth/_base.py` | `AdapterBase`, `Config`, `Settings`, `depends` |
| `adapters/auth/firebase.py` | `Config`, `debug`, `depends` |
| `adapters/admin/sqladmin.py` | `load`, `import_adapter`, `debug`, `depends`, `FastBlocks` |
| `adapters/schemas/_base.py` | `AdapterBase`, `Settings`, `depends` |
| `adapters/schemas/_models/__init__.py` | `depends` |

### 4.2 Existing Migration Doc

`MIGRATION-3.1.0.md` exists in the Splashstand root but covers only PEP 735 dependency group packaging changes. All 6 checklist items are unchecked. No ACB → Oneiric code migration is documented.

### 4.3 pyproject.toml State

The working tree has a broken `pyproject.toml` containing only `[tool.ruff]` and `[tool.pytest.ini_options]`. A staged fix exists with the complete `[project]` table including dependency groups, but it has not been committed.

## 5. Import Mapping

Derived from patterns in the three successfully migrated projects (Crackerjack, Session-Buddy, Fastblocks).

### 5.1 Core Imports

| ACB Import | Oneiric Equivalent | Notes |
|------------|-------------------|-------|
| `from acb import register_pkg` | `from oneiric import register_pkg` | Direct rename |
| `from acb.depends import depends` | `from oneiric.depends import depends` | Direct rename |
| `from acb.config import AdapterBase` | `from oneiric.config import AdapterBase` | Direct rename |
| `from acb.config import Config` | `from oneiric.config import Config` | Direct rename |
| `from acb.config import Settings` | `from oneiric.config import Settings` | Direct rename |
| `from acb.config import AppSettings` | `from oneiric.config import AppSettings` | Direct rename |

### 5.2 Adapter Imports

| ACB Import | Oneiric Equivalent | Notes |
|------------|-------------------|-------|
| `from acb.adapters import import_adapter` | `from oneiric.adapters import import_adapter` | Direct rename |
| `from acb.adapters import get_adapter` | `from oneiric.adapters import get_adapter` | Direct rename |
| `from acb.adapters import root_path` | `from oneiric.adapters import root_path` | Direct rename |
| `from acb.adapters import tmp_path` | `from oneiric.adapters import tmp_path` | Direct rename |
| `from acb.adapters.dns._base import DnsRecord` | `from oneiric.adapters.dns._base import DnsRecord` | Direct rename |

### 5.3 Utility Imports

| ACB Import | Oneiric Equivalent | Notes |
|------------|-------------------|-------|
| `from acb.console import console` | `from oneiric.console import console` | Direct rename |
| `from acb.debug import debug` | `from oneiric.debug import debug` | Direct rename |
| `from acb.logger import Logger` | `from oneiric.logger import Logger` | Direct rename |
| `from acb.actions.encode import dump` | `import yaml; yaml.dump()` | ACB provided `dump.yaml()` convenience; replace with direct `yaml` calls |
| `from acb.actions.encode import load` | `import yaml; yaml.safe_load()` | ACB provided `load.yaml()` and `load.json()` convenience; replace with direct `yaml`/`json` calls |

### 5.4 The `resolve_dep()` Helper Pattern

The migrated projects wrap Oneiric's `Candidate` unwrapping in a helper function. This pattern goes in `main.py` alongside the app setup:

```python
from oneiric import register_pkg
from oneiric.core.resolution import Resolver

depends = Resolver()

def resolve_dep(key):
    candidate = depends.resolve("splashstand", key)
    if candidate is None:
        raise RuntimeError(f"Missing dependency: {key}")
    factory = getattr(candidate, "factory", None)
    return factory() if callable(factory) else candidate
```

Sites that call `depends.resolve(...)` and unwrap the result manually should switch to `resolve_dep(key)`.

## 6. Migration Phases

### Phase 0: Restore pyproject.toml

1. Commit the staged `pyproject.toml` fix (restores the `[project]` table).
2. Add `oneiric` to dependencies (replace or supplement `acb`).
3. Verify `pip install -e ".[dev]"` succeeds.

### Phase 1: Core Infrastructure

1. Add `resolve_dep()` helper to `main.py`.
2. Replace `from acb import register_pkg` → `from oneiric import register_pkg`.
3. Replace `from acb.depends import depends` → `from oneiric.core.resolution import Resolver`.
4. Update any direct `depends.resolve(...)` calls to use `resolve_dep(key)`.

### Phase 2: Adapter Migration

Migrate all 8 adapter files in dependency order:

1. `adapters/schemas/_models/__init__.py` (1 import — leaf dependency)
2. `adapters/schemas/_base.py` (3 imports)
3. `adapters/auth/_base.py` (4 imports)
4. `adapters/auth/firebase.py` (3 imports)
5. `adapters/app/_base.py` (2 imports)
6. `adapters/app/demo.py` (5 imports)
7. `adapters/app/default.py` (4 imports)
8. `adapters/admin/sqladmin.py` (5 imports — includes `load` which needs JSON migration)

Each file gets a mechanical `acb` → `oneiric` import rename. Files using `dump`/`load` from `acb.actions.encode` need the additional JSON migration.

### Phase 3: CLI Migration

1. `cli.py` — Replace all 8 ACB imports with Oneiric equivalents.
2. Replace `from acb.actions.encode import dump, load` → `import yaml`.
3. Replace `load.yaml(debug_file)` → `yaml.safe_load(open(debug_file))`.
4. Replace `dump.yaml(debug_settings, debug_file)` → `yaml.dump(debug_settings, open(debug_file, "w"))`.
5. Verify CLI commands still work (`dev`, `run`, etc.).

**Note:** `adapters/admin/sqladmin.py` also uses `from acb.actions.encode import load` with `load.json(...)`. This file is migrated in Phase 2. Replace `load.json(path)` → `json.loads(open(path).read())` and add `import json`.

### Phase 4: Cleanup and Validation

1. Remove `acb` from `pyproject.toml` dependencies (if still present).
2. Run `grep -r "from acb" splashstand/` — expect zero results.
3. Run `grep -r "import acb" splashstand/` — expect zero results.
4. Run full test suite.
5. Run Crackerjack quality checks.
6. Update `MIGRATION-3.1.0.md` to reflect completed migration.

## 7. Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| `acb.actions.encode` provided `dump.yaml()`/`load.yaml()`/`load.json()` convenience methods not available in Oneiric | Replace with direct `yaml`/`json` standard library calls. Three migrated projects all used this pattern successfully. |
| `get_adapter` removed or renamed in Oneiric | Verify against Oneiric 0.19+ API. Fallback: use `import_adapter` + manual instantiation. |
| Template delimiter collision | Not applicable — Splashstand already uses `[[ ]]`. |
| Adapter initialization order changes | Oneiric preserves ACB's lazy resolution semantics. No order changes expected. |

## 8. Acceptance Criteria

1. `grep -r "from acb" splashstand/` returns zero results.
2. `grep -r "import acb" splashstand/` returns zero results.
3. `acb` is not listed in `pyproject.toml` dependencies.
4. `oneiric` is listed in `pyproject.toml` dependencies.
5. `resolve_dep()` helper exists in `main.py`.
6. `main.py` uses `from oneiric import register_pkg`.
7. `main.py` uses `from oneiric.core.resolution import Resolver`.
8. All adapter files use `from oneiric.*` imports exclusively.
9. `cli.py` uses `import yaml` instead of `from acb.actions.encode import dump, load`.
10. All `dump.yaml()`/`load.yaml()` call sites use direct `yaml.dump()`/`yaml.safe_load()`.
11. `sqladmin.py` uses `import json` and `json.loads()` instead of `load.json()`.
12. `pytest` passes with zero failures.
13. Crackerjack quality score meets minimum threshold.
14. `MIGRATION-3.1.0.md` updated to reflect completed migration.
15. No functionality regressions — all CLI commands, routes, and adapters work as before.
16. `pyproject.toml` has a valid `[project]` table committed to git.

## 9. ADR Reference

- **ADR 005**: Unified memory architecture (Oneiric as foundation)
- This migration brings Splashstand into alignment with the Oneiric foundation pattern established by the other three migrated projects.

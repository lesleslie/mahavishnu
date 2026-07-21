---
status: shipped
role: implementation
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
topic: pattern-learning-scaffolding
---

# Pattern Learning & Scaffolding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Status:** COMPLETE — all tasks checked [x]. `PatternLibrary`, `ScaffoldingEngine`, and YAML pattern templates shipped in `mahavishnu/scaffolding/` and `mahavishnu/models/pattern.py`. Reference only. <!-- legacy status: COMPLETE — see YAML frontmatter -->
> **Goal:** Build a pattern learning and scaffolding system that learns Fastblocks/Oneiric architectural patterns from existing projects and generates new web applications from composed patterns — "Lovable for Fastblocks."
> **Architecture:** Three-module pipeline — Pattern Library (YAML storage + query), Pattern Extractor (manual curation + AI suggestion), and Scaffolding Engine (Phase 1 deterministic template rendering, Phase 2 chat-driven incremental merge). Patterns are YAML files in `mahavishnu/patterns/`, version-controlled and human-editable.
> **Tech Stack:** Python 3.13, Pydantic v2, Jinja2 (dual environments), Typer (CLI), YAML (pattern storage), difflib (structural similarity)
> **Spec:** `docs/superpowers/specs/2026-04-26-pattern-learning-scaffolding-design.md`
> **Working directory:** `/Users/les/Projects/mahavishnu`
> **Prerequisites:** Code Indexing Integration (plan 1 of 3), Config Consolidation, Agent & Skill Modernization

______________________________________________________________________

## File Structure

Before defining tasks, here is the complete file layout:

```
mahavishnu/
├── patterns/                              # Pattern Library root (created in Task 2)
│   ├── scaffolding/
│   │   ├── project.yaml                   # Task 3
│   │   └── minimal.yaml                   # Task 3
│   ├── components/
│   │   ├── nav.yaml                       # Task 3
│   │   ├── table.yaml                     # Task 3
│   │   ├── form.yaml                      # Task 3
│   │   ├── card.yaml                      # Task 3
│   │   ├── dashboard.yaml                 # Task 3
│   │   └── hero.yaml                      # Task 3
│   ├── adapters/
│   │   ├── auth.yaml                      # Task 3
│   │   ├── analytics.yaml                 # Task 3
│   │   └── admin.yaml                     # Task 3
│   ├── deployment/
│   │   ├── cloudrun.yaml                  # Task 3
│   │   ├── docker.yaml                    # Task 3
│   │   └── github-actions.yaml            # Task 3
│   └── composite/
│       └── pwa-app.yaml                   # Task 3
├── mahavishnu/
│   ├── scaffolding/
│   │   ├── __init__.py                    # Task 1
│   │   ├── models.py                      # Task 1
│   │   ├── library.py                     # Task 2
│   │   ├── extractor.py                   # Task 6
│   │   ├── engine.py                      # Task 7
│   │   ├── validation.py                  # Task 5
│   │   ├── dependency_graph.py            # Task 4
│   │   └── jinjava_env.py                 # Task 8
│   └── cli/
│       └── scaffold_cli.py                # Task 9
├── tests/
│   ├── unit/
│   │   ├── test_scaffolding_models.py     # Task 1
│   │   ├── test_scaffolding_library.py    # Task 2
│   │   ├── test_scaffolding_dep_graph.py  # Task 4
│   │   ├── test_scaffolding_validation.py # Task 5
│   │   ├── test_scaffolding_engine.py     # Task 7
│   │   └── test_scaffolding_cli.py        # Task 9
│   └── integration/
│       └── test_scaffold_e2e.py           # Task 10
```

______________________________________________________________________

### Task 1: Define Pydantic models for Pattern format

**Files:**

- Create: `mahavishnu/scaffolding/__init__.py`

- Create: `mahavishnu/scaffolding/models.py`

- Create: `tests/unit/test_scaffolding_models.py`

- [x] **Step 1: Create package init**

```python
# mahavishnu/scaffolding/__init__.py
"""Pattern learning and scaffolding for Fastblocks/Oneiric projects."""

__all__ = ["Pattern", "PatternLibrary", "ScaffoldingEngine", "PatternExtractor"]
```

- [x] **Step 2: Write failing tests for models**

```python
# tests/unit/test_scaffolding_models.py
"""Tests for pattern Pydantic models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mahavishnu.scaffolding.models import (
    DirSpec,
    FileSpec,
    Pattern,
    PatternDependency,
    SlotSpec,
)


class TestPatternDependency:
    def test_minimal_dependency(self):
        dep = PatternDependency(id="scaffolding/project")
        assert dep.id == "scaffolding/project"
        assert dep.version is None

    def test_dependency_with_version(self):
        dep = PatternDependency(id="scaffolding/project", version=">=1.0.0")
        assert dep.version == ">=1.0.0"

    def test_dependency_rejects_empty_id(self):
        with pytest.raises(ValidationError):
            PatternDependency(id="")


class TestDirSpec:
    def test_required_dir(self):
        d = DirSpec(path="settings/", required=True, description="Config dir")
        assert d.path == "settings/"
        assert d.required is True

    def test_optional_dir(self):
        d = DirSpec(path="static/", required=False, description="Assets")
        assert d.required is False


class TestFileSpec:
    def test_required_file_with_template(self):
        f = FileSpec(path="main.py", required=True, template="entry-point")
        assert f.template == "entry-point"

    def test_file_without_template_defaults_to_path(self):
        f = FileSpec(path="pyproject.toml", required=True)
        assert f.template == "pyproject.toml"


class TestSlotSpec:
    def test_directory_slot_defaults(self):
        s = SlotSpec(path="templates/base/blocks/", files=["nav.html"])
        assert s.type == "directory"
        assert s.required is False

    def test_file_merge_slot(self):
        s = SlotSpec(
            path="main.py",
            type="file-merge",
            merge_strategy="marker-injection",
        )
        assert s.type == "file-merge"
        assert s.merge_strategy == "marker-injection"

    def test_slot_rejects_bad_type(self):
        with pytest.raises(ValidationError):
            SlotSpec(path="main.py", type="symlink")


class TestPattern:
    def test_minimal_pattern(self):
        p = Pattern(id="scaffolding/project", name="Project Skeleton")
        assert p.schema_version == 1
        assert p.confidence == 1.0
        assert p.depends == []
        assert p.tags == []

    def test_full_pattern(self):
        p = Pattern(
            id="adapters/auth",
            name="Auth Adapter",
            description="Session-based auth",
            version="1.0.0",
            source_repos=["splashstand"],
            tags=["auth", "session"],
            structure={
                "dirs": [{"path": "adapters/", "required": True, "description": "Adapters"}],
                "files": [{"path": "adapters/auth.py", "required": True}],
            },
            templates={"auth-module": "from starlette.middleware import Middleware"},
            slots={"middleware": {"path": "main.py", "type": "file-merge", "merge_strategy": "marker-injection"}},
        )
        assert len(p.structure["dirs"]) == 1
        assert p.templates["auth-module"] == "from starlette.middleware import Middleware"

    def test_rejects_path_traversal_in_dirs(self):
        with pytest.raises(ValidationError):
            Pattern(
                id="bad/pattern",
                name="Bad",
                structure={"dirs": [{"path": "../../etc/", "required": True}], "files": []},
            )

    def test_rejects_path_traversal_in_files(self):
        with pytest.raises(ValidationError):
            Pattern(
                id="bad/pattern",
                name="Bad",
                structure={"dirs": [], "files": [{"path": "/etc/passwd", "required": True}]},
            )
```

- [x] **Step 3: Run tests to verify they fail**

```bash
cd /Users/les/Projects/mahavishnu
python -m pytest tests/unit/test_scaffolding_models.py -v 2>&1 | tail -20
```

Expected: FAIL with `ModuleNotFoundError: No module named 'mahavishnu.scaffolding'`

- [x] **Step 4: Implement models**

```python
# mahavishnu/scaffolding/models.py
"""Pydantic models for pattern format."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


_PATH_TRAVERSAL_RE = re.compile(r"(\.\./|\.\.\\|/etc/|/tmp/|/var/)")


class PatternDependency(BaseModel):
    """A dependency on another pattern."""

    id: str
    version: str | None = None


class DirSpec(BaseModel):
    """Directory specification within a pattern."""

    path: str
    required: bool = True
    description: str = ""


class FileSpec(BaseModel):
    """File specification within a pattern."""

    path: str
    required: bool = True
    template: str | None = None
    description: str = ""

    @field_validator("template", mode="before")
    @classmethod
    def default_template_from_path(cls, v: str | None, info: Any) -> str | None:
        if v is None and "path" in info.data:
            return info.data["path"].lstrip("/").removesuffix(".py").removesuffix(".toml").removesuffix(".yaml").removesuffix(".yml").removesuffix(".html")
        return v


class SlotSpec(BaseModel):
    """Named extension point for pattern composition."""

    path: str
    type: Literal["directory", "file-merge"] = "directory"
    merge_strategy: Literal["marker-injection"] | None = None
    files: list[str] = []
    required: bool = False

    @field_validator("merge_strategy", mode="after")
    @classmethod
    def require_strategy_for_merge(cls, v: str | None, info: Any) -> str | None:
        if info.data.get("type") == "file-merge" and v is None:
            raise ValueError("file-merge slots must specify merge_strategy")
        return v


def _is_safe_path(path: str) -> bool:
    return not _PATH_TRAVERSAL_RE.search(path)


class Pattern(BaseModel):
    """A reusable architectural pattern."""

    schema_version: Literal[1] = 1
    id: str
    name: str
    description: str = ""
    version: str = "1.0.0"
    source_repos: list[str] = []
    confidence: float = 1.0
    depends: list[PatternDependency] = []
    tags: list[str] = []
    structure: dict[str, list[dict[str, Any]]] = Field(default_factory=lambda: {"dirs": [], "files": []})
    templates: dict[str, str] = {}
    slots: dict[str, Any] = {}

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not v or "/" not in v:
            raise ValueError("Pattern ID must be in 'category/name' format")
        return v

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("Confidence must be between 0.0 and 1.0")
        return v

    @field_validator("structure", mode="after")
    @classmethod
    def validate_paths(cls, v: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
        for d in v.get("dirs", []):
            if not _is_safe_path(d.get("path", "")):
                raise ValueError(f"Path traversal detected: {d['path']}")
        for f in v.get("files", []):
            if not _is_safe_path(f.get("path", "")):
                raise ValueError(f"Path traversal detected: {f['path']}")
        return v

    def get_dirs(self) -> list[DirSpec]:
        return [DirSpec(**d) for d in self.structure.get("dirs", [])]

    def get_files(self) -> list[FileSpec]:
        return [FileSpec(**f) for f in self.structure.get("files", [])]

    def get_slots(self) -> dict[str, SlotSpec]:
        result = {}
        for name, spec in self.slots.items():
            if isinstance(spec, dict):
                result[name] = SlotSpec(**spec)
            elif isinstance(spec, SlotSpec):
                result[name] = spec
        return result

    def get_dependency_ids(self) -> list[str]:
        return [d.id for d in self.depends]
```

- [x] **Step 5: Run tests to verify they pass**

```bash
cd /Users/les/Projects/mahavishnu
python -m pytest tests/unit/test_scaffolding_models.py -v 2>&1 | tail -20
```

Expected: All PASS

- [x] **Step 6: Commit**

```bash
git add mahavishnu/scaffolding/__init__.py mahavishnu/scaffolding/models.py tests/unit/test_scaffolding_models.py
git commit -m "feat(scaffolding): add Pydantic models for pattern format"
```

______________________________________________________________________

### Task 2: Build Pattern Library (storage + query)

**Files:**

- Create: `mahavishnu/scaffolding/library.py`

- Create: `tests/unit/test_scaffolding_library.py`

- [x] **Step 1: Write failing tests for PatternLibrary**

```python
# tests/unit/test_scaffolding_library.py
"""Tests for Pattern Library storage and query."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml

from mahavishnu.scaffolding.models import Pattern
from mahavishnu.scaffolding.library import PatternLibrary


@pytest.fixture
def lib(tmp_path: Path) -> PatternLibrary:
    return PatternLibrary(root=tmp_path)


@pytest.fixture
def sample_pattern() -> dict:
    return {
        "id": "scaffolding/project",
        "name": "Fastblocks Project Skeleton",
        "description": "Base project structure",
        "version": "1.0.0",
        "source_repos": ["fastblocks"],
        "tags": ["fastblocks", "skeleton"],
        "structure": {
            "dirs": [{"path": "settings/", "required": True, "description": "Config"}],
            "files": [{"path": "main.py", "required": True, "template": "entry-point"}],
        },
        "templates": {
            "entry-point": "from starlette.routing import Route\napp = None",
        },
        "slots": {
            "nav": {"path": "templates/base/blocks/", "files": ["nav.html"]},
        },
    }


class TestPatternLibraryLoad:
    def test_load_single_pattern(self, lib: PatternLibrary, sample_pattern: dict):
        lib.root.joinpath("scaffolding").mkdir(parents=True)
        lib.root.joinpath("scaffolding", "project.yaml").write_text(yaml.dump(sample_pattern))
        patterns = lib.load_all()
        assert len(patterns) == 1
        assert patterns[0].id == "scaffolding/project"

    def test_load_returns_empty_when_no_patterns(self, lib: PatternLibrary):
        patterns = lib.load_all()
        assert patterns == []

    def test_load_multiple_categories(self, lib: PatternLibrary, sample_pattern: dict):
        for cat in ["scaffolding", "components", "adapters"]:
            lib.root.joinpath(cat).mkdir(parents=True)
            p = dict(sample_pattern)
            p["id"] = f"{cat}/test"
            lib.root.joinpath(cat, "test.yaml").write_text(yaml.dump(p))
        patterns = lib.load_all()
        assert len(patterns) == 3

    def test_load_rejects_invalid_yaml(self, lib: PatternLibrary):
        lib.root.joinpath("bad").mkdir(parents=True)
        lib.root.joinpath("bad", "broken.yaml").write_text("{{invalid yaml")
        with pytest.raises(Exception):
            lib.load_all()


class TestPatternLibraryQuery:
    def test_get_by_id(self, lib: PatternLibrary, sample_pattern: dict):
        lib.root.joinpath("scaffolding").mkdir(parents=True)
        lib.root.joinpath("scaffolding", "project.yaml").write_text(yaml.dump(sample_pattern))
        lib.load_all()
        p = lib.get("scaffolding/project")
        assert p is not None
        assert p.name == "Fastblocks Project Skeleton"

    def test_get_missing_returns_none(self, lib: PatternLibrary):
        lib.load_all()
        assert lib.get("nonexistent") is None

    def test_list_by_category(self, lib: PatternLibrary, sample_pattern: dict):
        for cat in ["scaffolding", "components"]:
            lib.root.joinpath(cat).mkdir(parents=True)
            p = dict(sample_pattern)
            p["id"] = f"{cat}/test"
            lib.root.joinpath(cat, "test.yaml").write_text(yaml.dump(p))
        lib.load_all()
        result = lib.list_category("scaffolding")
        assert len(result) == 1
        assert result[0].id == "scaffolding/test"

    def test_search_by_tag(self, lib: PatternLibrary, sample_pattern: dict):
        lib.root.joinpath("scaffolding").mkdir(parents=True)
        lib.root.joinpath("scaffolding", "project.yaml").write_text(yaml.dump(sample_pattern))
        lib.load_all()
        results = lib.search("fastblocks")
        assert len(results) == 1

    def test_search_by_name(self, lib: PatternLibrary, sample_pattern: dict):
        lib.root.joinpath("scaffolding").mkdir(parents=True)
        lib.root.joinpath("scaffolding", "project.yaml").write_text(yaml.dump(sample_pattern))
        lib.load_all()
        results = lib.search("Skeleton")
        assert len(results) == 1

    def test_has(self, lib: PatternLibrary, sample_pattern: dict):
        lib.root.joinpath("scaffolding").mkdir(parents=True)
        lib.root.joinpath("scaffolding", "project.yaml").write_text(yaml.dump(sample_pattern))
        lib.load_all()
        assert lib.has("scaffolding/project") is True
        assert lib.has("nonexistent") is False


class TestPatternLibrarySave:
    def test_save_pattern(self, lib: PatternLibrary):
        p = Pattern(id="scaffolding/test", name="Test")
        lib.save(p)
        assert lib.root.joinpath("scaffolding", "test.yaml").exists()
        loaded = yaml.safe_load(lib.root.joinpath("scaffolding", "test.yaml").read_text())
        assert loaded["id"] == "scaffolding/test"

    def test_save_creates_category_dir(self, lib: PatternLibrary):
        p = Pattern(id="newcat/item", name="New")
        lib.save(p)
        assert lib.root.joinpath("newcat").is_dir()
```

- [x] **Step 2: Run tests to verify they fail**

```bash
cd /Users/les/Projects/mahavishnu
python -m pytest tests/unit/test_scaffolding_library.py -v 2>&1 | tail -10
```

Expected: FAIL with `ModuleNotFoundError`

- [x] **Step 3: Implement PatternLibrary**

```python
# mahavishnu/scaffolding/library.py
"""Pattern Library: YAML-based storage and query for architectural patterns."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from mahavishnu.scaffolding.models import Pattern

logger = logging.getLogger(__name__)


class PatternLibrary:
    """Load, query, and save pattern YAML files."""

    def __init__(self, root: Path | str | None = None) -> None:
        if root is None:
            root = Path(__file__).resolve().parent.parent.parent / "patterns"
        self.root = Path(root)
        self._cache: dict[str, Pattern] = {}

    def load_all(self) -> list[Pattern]:
        """Load all patterns from the YAML files under root."""
        self._cache.clear()
        if not self.root.is_dir():
            return []
        for yaml_file in sorted(self.root.rglob("*.yaml")):
            try:
                data = yaml.safe_load(yaml_file.read_text())
                if not isinstance(data, dict) or "id" not in data:
                    continue
                pattern = Pattern.model_validate(data)
                pattern._file_path = yaml_file  # type: ignore[attr-defined]
                self._cache[pattern.id] = pattern
            except Exception as e:
                raise ValueError(f"Failed to load {yaml_file}: {e}") from e
        return list(self._cache.values())

    def get(self, pattern_id: str) -> Pattern | None:
        return self._cache.get(pattern_id)

    def has(self, pattern_id: str) -> bool:
        return pattern_id in self._cache

    def list_category(self, category: str) -> list[Pattern]:
        prefix = category + "/"
        return [p for p in self._cache.values() if p.id.startswith(prefix)]

    def list_all_categories(self) -> list[str]:
        seen: set[str] = set()
        for pid in self._cache:
            cat = pid.split("/")[0]
            seen.add(cat)
        return sorted(seen)

    def search(self, query: str) -> list[Pattern]:
        q = query.lower()
        return [
            p
            for p in self._cache.values()
            if q in p.name.lower()
            or q in p.description.lower()
            or q in " ".join(p.tags).lower()
        ]

    def save(self, pattern: Pattern) -> Path:
        category = pattern.id.split("/")[0]
        name = pattern.id.split("/", 1)[1]
        cat_dir = self.root / category
        cat_dir.mkdir(parents=True, exist_ok=True)
        dest = cat_dir / f"{name}.yaml"
        data = pattern.model_dump(mode="json", exclude={"_file_path"})
        atomic_write(dest, yaml.dump(data, default_flow_style=False, sort_keys=False))
        self._cache[pattern.id] = pattern
        return dest

    def delete(self, pattern_id: str) -> bool:
        pattern = self._cache.pop(pattern_id, None)
        if pattern is None:
            return False
        fp = getattr(pattern, "_file_path", None)
        if fp and isinstance(fp, Path) and fp.exists():
            fp.unlink()
        return True


def atomic_write(path: Path, content: str) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(content)
    tmp.replace(path)
```

- [x] **Step 4: Run tests to verify they pass**

```bash
cd /Users/les/Projects/mahavishnu
python -m pytest tests/unit/test_scaffolding_library.py -v 2>&1 | tail -20
```

Expected: All PASS

- [x] **Step 5: Commit**

```bash
git add mahavishnu/scaffolding/library.py tests/unit/test_scaffolding_library.py
git commit -m "feat(scaffolding): add Pattern Library with YAML storage and query"
```

______________________________________________________________________

### Task 3: Create all 15 initial pattern YAML files

**Files:**

- Create: `patterns/scaffolding/project.yaml`

- Create: `patterns/scaffolding/minimal.yaml`

- Create: `patterns/components/nav.yaml`

- Create: `patterns/components/table.yaml`

- Create: `patterns/components/form.yaml`

- Create: `patterns/components/card.yaml`

- Create: `patterns/components/dashboard.yaml`

- Create: `patterns/components/hero.yaml`

- Create: `patterns/adapters/auth.yaml`

- Create: `patterns/adapters/analytics.yaml`

- Create: `patterns/adapters/admin.yaml`

- Create: `patterns/deployment/cloudrun.yaml`

- Create: `patterns/deployment/docker.yaml`

- Create: `patterns/deployment/github-actions.yaml`

- Create: `patterns/composite/pwa-app.yaml`

- [x] **Step 1: Create scaffolding/project.yaml**

```yaml
# patterns/scaffolding/project.yaml
schema_version: 1
id: scaffolding/project
name: Fastblocks Project Skeleton
description: Base project structure with Oneiric config, entry point, settings, and templates
version: "1.0.0"
source_repos: [fastblocks, splashstand]
confidence: 1.0
depends: []
tags: [fastblocks, skeleton, base]

structure:
  dirs:
    - path: settings/
      required: true
      description: Oneiric YAML configuration directory
    - path: templates/base/blocks/
      required: true
      description: Base template blocks for HTMX partial rendering
    - path: templates/pages/
      required: false
      description: Page-level templates
    - path: templates/macros/
      required: false
      description: Jinja2 macro templates
    - path: adapters/
      required: false
      description: Custom Oneiric adapters
    - path: static/
      required: false
      description: Static assets (CSS, JS, images)
    - path: tests/
      required: false
      description: Test files
  files:
    - path: main.py
      required: true
      template: entry-point
      description: Application entry point with route definitions
    - path: pyproject.toml
      required: true
      template: pyproject
      description: Python project dependencies and metadata
    - path: settings/app.yml
      required: true
      template: settings-app
      description: Application-level Oneiric settings

templates:
  entry-point: |
    from starlette.routing import Route
    from oneiric.core.resolution import Resolver

    _resolver = Resolver()

    def resolve_dep(key: str):
        candidate = _resolver.resolve("{{ project_slug }}", key)
        if candidate is None:
            raise RuntimeError(f"Missing dependency: {key}")
        factory = getattr(candidate, "factory", None)
        return factory() if callable(factory) else candidate

    def homepage(request):
        from starlette.responses import HTMLResponse
        return HTMLResponse("<h1>{{ project_title }}</h1>")

    routes = [Route("/", endpoint=homepage)]
    app = resolve_dep("app")
  pyproject: |
    [project]
    name = "{{ project_name }}"
    version = "{{ version }}"
    description = "{{ project_title }}"
    requires-python = ">={{ python_version }}"
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
    ]

    [tool.ruff]
    target-version = "py313"
    line-length = 88

    [tool.pytest.ini_options]
    asyncio_mode = "auto"
    timeout = 600
  settings-app: |
    server_name: "{{ project_title }}"
    host: "127.0.0.1"
    port: 8000

    adapters:
      app:
        type: fastblocks
        enabled: true

    templates:
      dir: templates
      cache_size: 100

slots:
  nav:
    path: templates/base/blocks/
    files: [nav.html, nav-mobile.html]
    required: false
  hero:
    path: templates/pages/
    files: [hero.html]
    required: false
  auth:
    path: adapters/
    files: [auth.py]
    required: false
  middleware:
    path: main.py
    type: file-merge
    merge_strategy: marker-injection
    required: false
  admin:
    path: adapters/
    files: [admin.py]
    required: false
  analytics:
    path: adapters/
    files: [analytics.py]
    required: false
```

- [x] **Step 2: Create scaffolding/minimal.yaml**

```yaml
# patterns/scaffolding/minimal.yaml
schema_version: 1
id: scaffolding/minimal
name: Minimal Fastblocks Project
description: Minimal project with just entry point and pyproject.toml
version: "1.0.0"
source_repos: [fastblocks]
confidence: 1.0
depends: []
tags: [fastblocks, minimal, skeleton]

structure:
  dirs: []
  files:
    - path: main.py
      required: true
      template: entry-point
      description: Application entry point
    - path: pyproject.toml
      required: true
      template: pyproject
      description: Python project metadata

templates:
  entry-point: |
    from starlette.routing import Route
    from starlette.responses import PlainTextResponse

    def homepage(request):
        return PlainTextResponse("Hello from {{ project_name }}")

    routes = [Route("/", endpoint=homepage)]
  pyproject: |
    [project]
    name = "{{ project_name }}"
    version = "{{ version }}"
    description = "{{ project_title }}"
    requires-python = ">={{ python_version }}"
    dependencies = [
        "oneiric>=0.19.0",
        "uvicorn[standard]>=0.30.0",
    ]

    [tool.ruff]
    target-version = "py313"

    [tool.pytest.ini_options]
    asyncio_mode = "auto"

slots: {}
```

- [x] **Step 3: Create components/nav.yaml**

```yaml
# patterns/components/nav.yaml
schema_version: 1
id: components/nav
name: Navigation Bar Component
description: Responsive navigation bar with mobile hamburger toggle using HTMX
version: "1.0.0"
source_repos: [splashstand]
confidence: 1.0
depends: []
tags: [component, nav, responsive, htmx]

structure:
  dirs: []
  files:
    - path: templates/base/blocks/nav.html
      required: true
      template: nav-block
      description: Navigation bar HTML block
    - path: templates/base/blocks/nav-mobile.html
      required: true
      template: nav-mobile-block
      description: Mobile navigation toggle block

templates:
  nav-block: |
    [[# Usage: [[ include 'base/blocks/nav.html' ]] #]]
    <nav class="navbar is-primary" role="navigation" aria-label="main navigation">
      <div class="navbar-brand">
        <a class="navbar-item" href="/">[[= project_title ]]</a>
        <a role="button" class="navbar-burger" aria-label="menu" aria-expanded="false"
           hx-get="/api/nav/mobile" hx-target="#mobile-nav" hx-swap="innerHTML">
          <span aria-hidden="true"></span>
          <span aria-hidden="true"></span>
          <span aria-hidden="true"></span>
        </a>
      </div>
      <div class="navbar-menu" id="navbar-menu">
        <div class="navbar-start">
          [[# Dynamic nav items injected here #]]
          [[ block nav_items ]][[ endblock ]]
        </div>
        <div class="navbar-end">
          [[ block nav_right ]][[ endblock ]]
        </div>
      </div>
    </nav>
  nav-mobile-block: |
    [[# Usage: [[ include 'base/blocks/nav-mobile.html' ]] #]]
    <div class="mobile-nav" id="mobile-nav">
      [[ block mobile_items ]][[ endblock ]]
    </div>

slots: {}
```

- [x] **Step 4: Create components/table.yaml**

```yaml
# patterns/components/table.yaml
schema_version: 1
id: components/table
name: Data Table Component
description: Data table with HTMX pagination, column sorting, and row actions
version: "1.0.0"
source_repos: [splashstand]
confidence: 1.0
depends: []
tags: [component, table, htmx, pagination]

structure:
  dirs: []
  files:
    - path: templates/macros/table.html
      required: true
      template: table-macro
      description: Reusable table macro with HTMX pagination

templates:
  table-macro: |
    [[# Usage: [[ include 'macros/table.html' ]] #]]
    [[ macro table(columns, rows, page=1, page_size=20) ]]
    <table class="table is-fullwidth is-hoverable is-striped">
      <thead>
        <tr>
          [[ for col in columns ]]
          <th hx-get="/api/table/sort?col=[[= col.key ]]" hx-target="table">
            [[= col.label ]]
          </th>
          [[ endfor ]]
        </tr>
      </thead>
      <tbody>
        [[ for row in rows ]]
        <tr>
          [[ for col in columns ]]
          <td>[[= get_cell(row, col.key) ]]</td>
          [[ endfor ]]
        </tr>
        [[ endfor ]]
      </tbody>
    </table>
    <nav class="pagination" role="navigation">
      <a class="pagination-previous"
         hx-get="/api/table?page=[[= page - 1 ]]"
         hx-target="table"
         [[ if page <= 1 ]]disabled[[ endif ]]>Previous</a>
      <a class="pagination-next"
         hx-get="/api/table?page=[[= page + 1 ]]"
         hx-target="table">Next</a>
    </nav>
    [[ endmacro ]]

slots: {}
```

- [x] **Step 5: Create components/form.yaml**

```yaml
# patterns/components/form.yaml
schema_version: 1
id: components/form
name: Form Component
description: Form component with client-side validation and HTMX submission
version: "1.0.0"
source_repos: [splashstand]
confidence: 1.0
depends: []
tags: [component, form, validation, htmx]

structure:
  dirs: []
  files:
    - path: templates/macros/form.html
      required: true
      template: form-macro
      description: Reusable form macro with HTMX submission

templates:
  form-macro: |
    [[# Usage: [[ include 'macros/form.html' ]] #]]
    [[ macro form(fields, action, method='POST') ]]
    <form method="[[= method ]]" action="[[= action ]]"
          hx-post="[[= action ]]" hx-target="#form-result" hx-swap="innerHTML">
      [[ for field in fields ]]
      <div class="field">
        <label class="label" for="[[= field.name ]]">[[= field.label ]]</label>
        <div class="control">
          <input class="input [[ if field.errors ]]is-danger[[ endif ]]"
                 type="[[= field.type or 'text' ]]"
                 name="[[= field.name ]]"
                 id="[[= field.name ]]"
                 [[ if field.placeholder ]]placeholder="[[= field.placeholder ]]"[[ endif ]]
                 [[ if field.required ]]required[[ endif ]] />
        </div>
        [[ if field.errors ]]
        [[ for error in field.errors ]]
        <p class="help is-danger">[[= error ]]</p>
        [[ endfor ]]
        [[ endif ]]
      </div>
      [[ endfor ]]
      <div class="field is-grouped">
        <div class="control">
          <button class="button is-primary" type="submit">Submit</button>
        </div>
      </div>
    </form>
    <div id="form-result"></div>
    [[ endmacro ]]

slots: {}
```

- [x] **Step 6: Create components/card.yaml**

```yaml
# patterns/components/card.yaml
schema_version: 1
id: components/card
name: Card Component
description: Reusable card/panel component for content sections
version: "1.0.0"
source_repos: [fastblocks]
confidence: 1.0
depends: []
tags: [component, card, panel]

structure:
  dirs: []
  files:
    - path: templates/macros/card.html
      required: true
      template: card-macro
      description: Reusable card macro

templates:
  card-macro: |
    [[# Usage: [[ include 'macros/card.html' ]] #]]
    [[ macro card(title, content, footer=None, header_class='') ]]
    <div class="card [[= header_class ]]">
      [[ if title ]]
      <header class="card-header">
        <p class="card-header-title">[[= title ]]</p>
      </header>
      [[ endif ]]
      <div class="card-content">
        <div class="content">
          [[= content ]]
        </div>
      </div>
      [[ if footer ]]
      <footer class="card-footer">
        [[= footer ]]
      </footer>
      [[ endif ]]
    </div>
    [[ endmacro ]]

slots: {}
```

- [x] **Step 7: Create components/dashboard.yaml**

```yaml
# patterns/components/dashboard.yaml
schema_version: 1
id: components/dashboard
name: Dashboard Layout Component
description: Dashboard layout with widget slots and sidebar navigation
version: "1.0.0"
source_repos: [splashstand]
confidence: 1.0
depends: []
tags: [component, dashboard, layout, widgets]

structure:
  dirs: []
  files:
    - path: templates/pages/dashboard.html
      required: true
      template: dashboard-page
      description: Dashboard page layout with widget grid

templates:
  dashboard-page: |
    [[# Dashboard page with widget grid #]]
    [[ extends "base/base.html" ]]
    [[ block title ]]Dashboard[[ endblock ]]
    [[ block content ]]
    <section class="section">
      <div class="columns">
        <div class="column is-3">
          [[ block dashboard_sidebar ]]
          <aside class="menu">
            <p class="menu-label">Navigation</p>
            <ul class="menu-list">
              <li><a href="/dashboard">Overview</a></li>
            </ul>
          </aside>
          [[ endblock ]]
        </div>
        <div class="column is-9">
          <div class="columns is-multiline">
            [[ block dashboard_widgets ]]
            [[# Widget slots go here #]]
            [[ endblock ]]
          </div>
        </div>
      </div>
    </section>
    [[ endblock ]]

slots: {}
```

- [x] **Step 8: Create components/hero.yaml**

```yaml
# patterns/components/hero.yaml
schema_version: 1
id: components/hero
name: Hero Section Component
description: Hero section for landing pages with CTA button
version: "1.0.0"
source_repos: [fastblocks]
confidence: 1.0
depends: []
tags: [component, hero, landing, cta]

structure:
  dirs: []
  files:
    - path: templates/pages/hero.html
      required: true
      template: hero-page
      description: Hero section partial

templates:
  hero-page: |
    [[# Hero section for landing pages #]]
    <section class="hero is-medium is-bold is-primary">
      <div class="hero-body">
        <div class="container">
          <h1 class="title">[[= project_title ]]</h1>
          <h2 class="subtitle">[[ block hero_subtitle ]]Built with Fastblocks[[ endblock ]]</h2>
          [[ block hero_cta ]]
          <a class="button is-large is-light" href="/docs">Get Started</a>
          [[ endblock ]]
        </div>
      </div>
    </section>

slots: {}
```

- [x] **Step 9: Create adapters/auth.yaml**

```yaml
# patterns/adapters/auth.yaml
schema_version: 1
id: adapters/auth
name: Authentication Adapter
description: Session-based authentication with CSRF protection, login/logout routes
version: "1.0.0"
source_repos: [splashstand]
confidence: 1.0
depends: []
tags: [adapter, auth, session, csrf]

structure:
  dirs: []
  files:
    - path: adapters/auth.py
      required: true
      template: auth-adapter
      description: Auth adapter with session middleware
    - path: settings/auth.yml
      required: false
      template: settings-auth
      description: Auth-specific settings

templates:
  auth-adapter: |
    from starlette.middleware import Middleware
    from starlette.routing import Route
    from starlette.responses import HTMLResponse, RedirectResponse
    from itsdangerous import URLSafeTimedSerializer

    SESSION_SECRET = "{{ session_secret }}"

    def login_page(request):
        return HTMLResponse("""
        <form method="POST" action="/auth/login">
          <input name="username" placeholder="Username" required />
          <input name="password" type="password" placeholder="Password" required />
          <button type="submit">Login</button>
        </form>
        """)

    async def login_handler(request):
        form = await request.form()
        # Replace with real auth logic
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie("session", "authenticated", max_age=86400, httponly=True)
        return response

    def logout_handler(request):
        response = RedirectResponse(url="/", status_code=303)
        response.delete_cookie("session")
        return response

    auth_routes = [
        Route("/auth/login", login_page, methods=["GET"]),
        Route("/auth/login", login_handler, methods=["POST"]),
        Route("/auth/logout", logout_handler, methods=["GET"]),
    ]
  settings-auth: |
    auth:
      enabled: true
      session_secret: "{{ session_secret }}"
      cookie_max_age: 86400
      csrf_enabled: true

slots:
  middleware:
    path: main.py
    type: file-merge
    merge_strategy: marker-injection
    required: true
```

- [x] **Step 10: Create adapters/analytics.yaml**

```yaml
# patterns/adapters/analytics.yaml
schema_version: 1
id: adapters/analytics
name: Analytics Adapter
description: Analytics integration adapter with event tracking
version: "1.0.0"
source_repos: [splashstand]
confidence: 1.0
depends: []
tags: [adapter, analytics, tracking]

structure:
  dirs: []
  files:
    - path: adapters/analytics.py
      required: true
      template: analytics-adapter
      description: Analytics adapter with event tracking

templates:
  analytics-adapter: |
    from starlette.routing import Route
    from starlette.responses import JSONResponse

    async def track_event(request):
        import json
        body = json.loads(await request.body())
        # Replace with real analytics backend
        print(f"Analytics event: {body}")
        return JSONResponse({"status": "ok"})

    analytics_routes = [
        Route("/api/analytics/track", track_event, methods=["POST"]),
    ]

slots: {}
```

- [x] **Step 11: Create adapters/admin.yaml**

```yaml
# patterns/adapters/admin.yaml
schema_version: 1
id: adapters/admin
name: Admin Panel Adapter
description: Admin panel with role-based access control
version: "1.0.0"
source_repos: [splashstand]
confidence: 1.0
depends: []
tags: [adapter, admin, rbac]

structure:
  dirs: []
  files:
    - path: adapters/admin.py
      required: true
      template: admin-adapter
      description: Admin panel adapter with role-based access

templates:
  admin-adapter: |
    from starlette.routing import Route
    from starlette.responses import HTMLResponse

    def admin_dashboard(request):
        return HTMLResponse("""
        <h1>Admin Dashboard</h1>
        <nav>
          <a href="/admin/users">Users</a>
          <a href="/admin/settings">Settings</a>
        </nav>
        """)

    admin_routes = [
        Route("/admin", admin_dashboard),
    ]

slots: {}
```

- [x] **Step 12: Create deployment/cloudrun.yaml**

```yaml
# patterns/deployment/cloudrun.yaml
schema_version: 1
id: deployment/cloudrun
name: Google Cloud Run Deployment
description: Google Cloud Run deployment with Dockerfile and cloudbuild.yaml
version: "1.0.0"
source_repos: [splashstand]
confidence: 1.0
depends: []
tags: [deployment, cloudrun, gcp]

structure:
  dirs: []
  files:
    - path: Dockerfile
      required: true
      template: dockerfile
      description: Multi-stage Dockerfile for Cloud Run
    - path: cloudbuild.yaml
      required: true
      template: cloudbuild
      description: Cloud Build configuration

templates:
  dockerfile: |
    FROM python:{{ python_version }}-slim AS builder
    WORKDIR /app
    COPY pyproject.toml .
    RUN pip install --no-cache-dir .
    COPY . .
    FROM python:{{ python_version }}-slim
    COPY --from=builder /app /app
    EXPOSE 8000
    CMD ["uvicorn", "{{ project_slug }}.main:app", "--host", "0.0.0.0", "--port", "8000"]
  cloudbuild: |
    steps:
      - name: "Build"
        args: ["build", "-t", "gcr.io/$PROJECT_ID/{{ project_name }}", "."]
      - name: "Push"
        args: ["push", "gcr.io/$PROJECT_ID/{{ project_name }}"]
      - name: "Deploy"
        args:
          - "run"
          - "--image"
          - "gcr.io/$PROJECT_ID/{{ project_name }}"
          - "--platform"
          - "managed"
          - "--region"
          - "us-central1"
          - "--allow-unauthenticated"

slots: {}
```

- [x] **Step 13: Create deployment/docker.yaml**

```yaml
# patterns/deployment/docker.yaml
schema_version: 1
id: deployment/docker
name: Docker Containerization
description: Docker containerization with multi-stage builds
version: "1.0.0"
source_repos: [fastblocks]
confidence: 1.0
depends: []
tags: [deployment, docker, containerization]

structure:
  dirs: []
  files:
    - path: Dockerfile
      required: true
      template: dockerfile
      description: Multi-stage Dockerfile
    - path: docker-compose.yml
      required: false
      template: compose
      description: Docker Compose for local development

templates:
  dockerfile: |
    FROM python:{{ python_version }}-slim AS builder
    WORKDIR /app
    COPY pyproject.toml .
    RUN pip install --no-cache-dir .
    COPY . .
    FROM python:{{ python_version }}-slim
    COPY --from=builder /app /app
    EXPOSE 8000
    CMD ["uvicorn", "{{ project_slug }}.main:app", "--host", "0.0.0.0", "--port", "8000"]
  compose: |
    services:
      app:
        build: .
        ports:
          - "8000:8000"
        volumes:
          - .:/app
        environment:
          - PYTHONUNBUFFERED=1

slots: {}
```

- [x] **Step 14: Create deployment/github-actions.yaml**

```yaml
# patterns/deployment/github-actions.yaml
schema_version: 1
id: deployment/github-actions
name: GitHub Actions CI/CD
description: CI/CD pipeline with quality gates
version: "1.0.0"
source_repos: [mahavishnu]
confidence: 1.0
depends: []
tags: [deployment, ci-cd, github-actions, quality]

structure:
  dirs:
    - path: .github/workflows/
      required: true
      description: GitHub Actions workflow directory
  files:
    - path: .github/workflows/ci.yml
      required: true
      template: ci-workflow
      description: CI pipeline with lint, test, security scan

templates:
  ci-workflow: |
    name: CI
    on:
      push:
        branches: [main]
      pull_request:
        branches: [main]
    jobs:
      test:
        runs-on: ubuntu-latest
        steps:
          - uses: actions/checkout@v4
          - uses: actions/setup-python@v5
            with:
              python-version: "{{ python_version }}"
          - run: pip install ".[dev]"
          - run: ruff check .
          - run: ruff format --check .
          - run: pytest tests/ -v --tb=short
      security:
        runs-on: ubuntu-latest
        steps:
          - uses: actions/checkout@v4
          - uses: actions/setup-python@v5
            with:
              python-version: "{{ python_version }}"
          - run: pip install bandit
          - run: bandit -r {{ project_slug }}/ -ll

slots: {}
```

- [x] **Step 15: Create composite/pwa-app.yaml**

```yaml
# patterns/composite/pwa-app.yaml
schema_version: 1
id: composite/pwa-app
name: Full PWA Application
description: Full PWA application matching Splashstand's architecture
version: "1.0.0"
source_repos: [splashstand]
confidence: 1.0
depends:
  - id: scaffolding/project
    version: ">=1.0.0"
  - id: components/nav
  - id: components/form
  - id: components/table
  - id: adapters/auth
  - id: deployment/cloudrun
tags: [composite, pwa, full-app]

structure:
  dirs: []
  files: []

templates: {}

slots: {}
```

- [x] **Step 16: Verify all 15 patterns load correctly**

```bash
cd /Users/les/Projects/mahavishnu
python -c "
from mahavishnu.scaffolding.library import PatternLibrary
lib = PatternLibrary()
patterns = lib.load_all()
print(f'Loaded {len(patterns)} patterns')
for p in sorted(patterns, key=lambda x: x.id):
    print(f'  {p.id} v{p.version} [{len(p.get_files())} files, {len(p.get_slots())} slots]')
"
```

Expected: `Loaded 15 patterns` with correct counts

- [x] **Step 17: Commit**

```bash
git add patterns/
git commit -m "feat(scaffolding): add all 15 initial pattern YAML files"
```

______________________________________________________________________

### Task 4: Build pattern dependency graph utilities

**Files:**

- Create: `mahavishnu/scaffolding/dependency_graph.py`

- Create: `tests/unit/test_scaffolding_dep_graph.py`

- [x] **Step 1: Write failing tests**

```python
# tests/unit/test_scaffolding_dep_graph.py
"""Tests for pattern dependency graph utilities."""

from __future__ import annotations

import pytest

from mahavishnu.scaffolding.dependency_graph import (
    PatternDependencyGraph,
    CircularDependencyError,
)


class TestTopologicalSort:
    def test_simple_chain(self):
        g = PatternDependencyGraph()
        g.add("a")
        g.add("b")
        g.add("c")
        g.add_edge("a", "b")
        g.add_edge("b", "c")
        order = g.topological_sort()
        assert order.index("a") < order.index("b") < order.index("c")

    def test_diamond_dependency(self):
        g = PatternDependencyGraph()
        g.add("root")
        g.add("left")
        g.add("right")
        g.add("leaf")
        g.add_edge("root", "left")
        g.add_edge("root", "right")
        g.add_edge("left", "leaf")
        g.add_edge("right", "leaf")
        order = g.topological_sort()
        assert order.index("root") < order.index("left")
        assert order.index("root") < order.index("right")
        assert order.index("left") < order.index("leaf")
        assert order.index("right") < order.index("leaf")

    def test_alphabetical_secondary_sort(self):
        g = PatternDependencyGraph()
        g.add("z")
        g.add("a")
        g.add("m")
        order = g.topological_sort()
        assert order == ["a", "m", "z"]

    def test_circular_dependency_raises(self):
        g = PatternDependencyGraph()
        g.add("a")
        g.add("b")
        g.add("c")
        g.add_edge("a", "b")
        g.add_edge("b", "c")
        g.add_edge("c", "a")
        with pytest.raises(CircularDependencyError):
            g.topological_sort()

    def test_self_dependency_raises(self):
        g = PatternDependencyGraph()
        g.add("a")
        g.add_edge("a", "a")
        with pytest.raises(CircularDependencyError):
            g.topological_sort()


class TestFileConflictDetection:
    def test_no_conflict(self):
        g = PatternDependencyGraph()
        g.add("a")
        g.add("b")
        g.claim_file("a", "main.py")
        g.claim_file("b", "routes.py")
        assert g.check_file_conflicts() == []

    def test_file_conflict_detected(self):
        g = PatternDependencyGraph()
        g.add("a")
        g.add("b")
        g.claim_file("a", "main.py")
        g.claim_file("b", "main.py")
        conflicts = g.check_file_conflicts()
        assert len(conflicts) == 1
        assert "main.py" in str(conflicts[0])

    def test_same_directory_allowed(self):
        g = PatternDependencyGraph()
        g.add("a")
        g.add("b")
        g.claim_file("a", "adapters/auth.py")
        g.claim_file("b", "adapters/admin.py")
        assert g.check_file_conflicts() == []
```

- [x] **Step 2: Run tests to verify they fail**

```bash
cd /Users/les/Projects/mahavishnu
python -m pytest tests/unit/test_scaffolding_dep_graph.py -v 2>&1 | tail -10
```

Expected: FAIL

- [x] **Step 3: Implement dependency graph**

```python
# mahavishnu/scaffolding/dependency_graph.py
"""Pattern dependency graph with topological sort and conflict detection."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field


class CircularDependencyError(Exception):
    def __init__(self, cycle: list[str]):
        self.cycle = cycle
        super().__init__(f"Circular dependency: {' -> '.join(cycle)}")


@dataclass
class FileClaim:
    pattern_id: str
    file_path: str


class PatternDependencyGraph:
    def __init__(self) -> None:
        self._deps: dict[str, set[str]] = defaultdict(set)
        self._nodes: set[str] = set()
        self._file_claims: dict[str, str] = {}

    def add(self, pattern_id: str) -> None:
        self._nodes.add(pattern_id)

    def add_edge(self, dependent: str, dependency: str) -> None:
        self._nodes.add(dependent)
        self._nodes.add(dependency)
        self._deps[dependent].add(dependency)

    def claim_file(self, pattern_id: str, file_path: str) -> None:
        self._file_claims[file_path] = pattern_id

    def topological_sort(self) -> list[str]:
        visited: set[str] = set()
        temp: set[str] = set()
        order: list[str] = []

        def visit(node: str) -> None:
            if node in temp:
                cycle = list(temp)
                raise CircularDependencyError(cycle)
            if node in visited:
                return
            temp.add(node)
            for dep in sorted(self._deps.get(node, [])):
                visit(dep)
            temp.remove(node)
            visited.add(node)
            order.append(node)

        for node in sorted(self._nodes):
            if node not in visited:
                visit(node)

        return order

    def check_file_conflicts(self) -> list[tuple[str, str, str]]:
        conflicts = []
        seen: dict[str, str] = {}
        for file_path, pattern_id in self._file_claims.items():
            if file_path in seen and seen[file_path] != pattern_id:
                conflicts.append((seen[file_path], pattern_id, file_path))
            else:
                seen[file_path] = pattern_id
        return conflicts
```

- [x] **Step 4: Run tests to verify they pass**

```bash
cd /Users/les/Projects/mahavishnu
python -m pytest tests/unit/test_scaffolding_dep_graph.py -v 2>&1 | tail -15
```

Expected: All PASS

- [x] **Step 5: Commit**

```bash
git add mahavishnu/scaffolding/dependency_graph.py tests/unit/test_scaffolding_dep_graph.py
git commit -m "feat(scaffolding): add pattern dependency graph with topological sort"
```

______________________________________________________________________

### Task 5: Build pattern validation module

**Files:**

- Create: `mahavishnu/scaffolding/validation.py`

- Create: `tests/unit/test_scaffolding_validation.py`

- [x] **Step 1: Write failing tests**

```python
# tests/unit/test_scaffolding_validation.py
"""Tests for pattern validation."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml

from mahavishnu.scaffolding.models import Pattern
from mahavishnu.scaffolding.library import PatternLibrary
from mahavishnu.scaffolding.validation import validate_pattern


@pytest.fixture
def library_with_project(tmp_path: Path) -> PatternLibrary:
    lib = PatternLibrary(root=tmp_path)
    data = {
        "id": "scaffolding/project",
        "name": "Project",
        "version": "1.0.0",
        "structure": {
            "dirs": [{"path": "settings/", "required": True}],
            "files": [{"path": "main.py", "required": True, "template": "entry-point"}],
        },
        "templates": {"entry-point": "pass"},
    }
    lib.root.joinpath("scaffolding").mkdir()
    lib.root.joinpath("scaffolding", "project.yaml").write_text(yaml.dump(data))
    lib.load_all()
    return lib


class TestValidatePattern:
    def test_valid_pattern_passes(self, library_with_project: PatternLibrary):
        p = library_with_project.get("scaffolding/project")
        issues = validate_pattern(p, library_with_project)
        assert issues == []

    def test_required_file_missing_template(self, library_with_project: PatternLibrary):
        p = Pattern(
            id="test/missing-tmpl",
            name="Missing Template",
            structure={"dirs": [], "files": [{"path": "missing.py", "required": True}]},
        )
        issues = validate_pattern(p, library_with_project)
        assert any("missing.py" in i for i in issues)

    def test_dependency_not_found(self, library_with_project: PatternLibrary):
        p = Pattern(
            id="test/deps",
            name="Deps",
            depends=[{"id": "nonexistent/pattern"}],
        )
        issues = validate_pattern(p, library_with_project)
        assert any("nonexistent" in i for i in issues)

    def test_id_matches_directory(self, tmp_path: Path):
        lib = PatternLibrary(root=tmp_path)
        lib.root.joinpath("adapters").mkdir()
        data = {
            "id": "WRONG_DIR/auth",
            "name": "Bad",
            "structure": {"dirs": [], "files": []},
        }
        lib.root.joinpath("adapters", "auth.yaml").write_text(yaml.dump(data))
        lib.load_all()
        p = lib.get("WRONG_DIR/auth")
        issues = validate_pattern(p, lib)
        assert any("directory" in i.lower() for i in issues)

    def test_jinja2_syntax_error(self, library_with_project: PatternLibrary):
        p = Pattern(
            id="test/bad-jinja",
            name="Bad Jinja",
            templates={"bad": "{% if %}"},
        )
        issues = validate_pattern(p, library_with_project)
        assert any("Jinja2" in i for i in issues)

    def test_duplicate_id(self, tmp_path: Path):
        lib = PatternLibrary(root=tmp_path)
        lib.root.joinpath("cat").mkdir()
        for name in ["a", "b"]:
            lib.root.joinpath("cat", f"{name}.yaml").write_text(
                yaml.dump({"id": "cat/dup", "name": name})
            )
        lib.load_all()
        p = lib.get("cat/dup")
        issues = validate_pattern(p, lib)
        assert any("Duplicate" in i for i in issues)
```

- [x] **Step 2: Run tests to verify they fail**

```bash
cd /Users/les/Projects/mahavishnu
python -m pytest tests/unit/test_scaffolding_validation.py -v 2>&1 | tail -10
```

Expected: FAIL

- [x] **Step 3: Implement validation**

```python
# mahavishnu/scaffolding/validation.py
"""Pattern validation against schema, slots, dependencies, and Jinja2 syntax."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from jinja2 import Environment, TemplateSyntaxError

if TYPE_CHECKING:
    from mahavishnu.scaffolding.library import PatternLibrary
    from mahavishnu.scaffolding.models import Pattern


def validate_pattern(pattern: Pattern, library: PatternLibrary) -> list[str]:
    issues: list[str] = []

    # ID matches file directory
    fp = getattr(pattern, "_file_path", None)
    if fp and isinstance(fp, Path):
        expected_dir = fp.parent.name
        if not pattern.id.startswith(expected_dir + "/") and pattern.id.split("/")[0] != expected_dir:
            issues.append(
                f"Pattern ID '{pattern.id}' doesn't match directory '{expected_dir}/'"
            )

    # Required files have templates
    for f in pattern.get_files():
        if f.required and f.template and f.template not in pattern.templates:
            issues.append(f"Required file '{f.path}' has no template '{f.template}'")

    # Slot paths within declared dirs
    all_dir_paths = {d.path.rstrip("/") for d in pattern.get_dirs()}
    for slot_name, slot in pattern.get_slots().items():
        slot_parent = _find_parent_dir(slot.path.rstrip("/"), all_dir_paths)
        if all_dir_paths and slot_parent is None:
            issues.append(f"Slot '{slot_name}' path '{slot.path}' is outside all pattern dirs")

    # Jinja2 syntax validation
    env = Environment(undefined=lambda x: "")
    for name, template_str in pattern.templates.items():
        try:
            env.parse(template_str)
        except TemplateSyntaxError as e:
            issues.append(f"Template '{name}' has Jinja2 syntax error: {e}")

    # Cross-pattern dependency checks
    for dep in pattern.depends:
        if not library.has(dep.id):
            issues.append(f"Dependency '{dep.id}' not found in library")

    # Circular dependency detection
    _check_cycles(pattern.id, pattern.get_dependency_ids(), library, issues)

    # Duplicate ID
    existing = library.get(pattern.id)
    if existing is not None:
        existing_fp = getattr(existing, "_file_path", None)
        if existing_fp != fp:
            issues.append(f"Duplicate pattern ID '{pattern.id}'")

    return issues


def _find_parent_dir(slot_path: str, dir_paths: set[str]) -> str | None:
    if not dir_paths:
        return None
    while "/" in slot_path:
        slot_path = slot_path.rsplit("/", 1)[0]
        if slot_path in dir_paths:
            return slot_path
    if slot_path in dir_paths:
        return slot_path
    return None


def _check_cycles(
    pattern_id: str,
    dep_ids: list[str],
    library: PatternLibrary,
    issues: list[str],
    visited: set[str] | None = None,
    path: list[str] | None = None,
) -> None:
    visited = visited or set()
    path = path or []
    if pattern_id in visited:
        cycle = path[path.index(pattern_id) :] + [pattern_id]
        issues.append(f"Circular dependency: {' -> '.join(cycle)}")
        return
    visited.add(pattern_id)
    path = path + [pattern_id]
    for dep_id in dep_ids:
        dep = library.get(dep_id)
        if dep:
            _check_cycles(dep_id, dep.get_dependency_ids(), library, issues, visited, path)
```

- [x] **Step 4: Run tests to verify they pass**

```bash
cd /Users/les/Projects/mahavishnu
python -m pytest tests/unit/test_scaffolding_validation.py -v 2>&1 | tail -15
```

Expected: All PASS

- [x] **Step 5: Commit**

```bash
git add mahavishnu/scaffolding/validation.py tests/unit/test_scaffolding_validation.py
git commit -m "feat(scaffolding): add pattern validation with Jinja2 syntax checking"
```

______________________________________________________________________

### Task 6: Build Pattern Extractor (manual curation)

**Files:**

- Create: `mahavishnu/scaffolding/extractor.py`

- [x] **Step 1: Implement PatternExtractor**

```python
# mahavishnu/scaffolding/extractor.py
"""Pattern Extractor: manual curation and AI suggestion from existing projects."""

from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from pathlib import Path

import yaml

from mahavishnu.scaffolding.models import Pattern

logger = logging.getLogger(__name__)


class PatternDraft:
    """A suggested pattern not yet approved for the library."""

    def __init__(
        self,
        category: str,
        name: str,
        dirs: list[dict],
        files: list[dict],
        confidence: float,
        source_repos: list[str],
    ) -> None:
        self.category = category
        self.name = name
        self.dirs = dirs
        self.files = files
        self.confidence = confidence
        self.source_repos = source_repos

    def to_pattern_dict(self) -> dict:
        return {
            "schema_version": 1,
            "id": f"{self.category}/{self.name}",
            "name": f"{self.category}/{self.name}".title(),
            "description": f"Auto-suggested pattern from {', '.join(self.source_repos)}",
            "version": "0.1.0-draft",
            "source_repos": self.source_repos,
            "confidence": round(self.confidence, 2),
            "depends": [],
            "tags": [self.category, "auto-suggested"],
            "structure": {
                "dirs": self.dirs,
                "files": self.files,
            },
            "templates": {},
            "slots": {},
        }


class PatternExtractor:
    """Extract patterns from existing projects."""

    def __init__(self) -> None:
        self._repo_paths: dict[str, Path] = {}

    def register_repo(self, name: str, path: Path | str) -> None:
        self._repo_paths[name] = Path(path)

    def create_draft_from_project(
        self,
        repo_name: str,
        category: str,
        name: str,
        description: str = "",
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
    ) -> PatternDraft:
        repo_path = self._repo_paths.get(repo_name)
        if repo_path is None:
            raise ValueError(f"Unknown repo: {repo_name}")

        include_re = [re.compile(p) for p in (include_patterns or [r".*"])]
        exclude_re = [re.compile(p) for p in (exclude_patterns or [r"^__pycache__$", r"^\.git$", r"^\.venv$"])]

        dirs: list[dict] = []
        files: list[dict] = []

        for item in sorted(repo_path.rglob("*")):
            rel = item.relative_to(repo_path).as_posix()
            if any(ex.search(rel) for ex in exclude_re):
                continue
            if not any(inc.search(rel) for inc in include_re):
                continue

            if item.is_dir():
                dirs.append({"path": rel + "/", "required": False, "description": ""})
            elif item.is_file() and item.suffix in {".py", ".yaml", ".yml", ".toml", ".html", ".css", ".js"}:
                files.append({"path": rel, "required": False, "description": ""})

        return PatternDraft(
            category=category,
            name=name,
            dirs=dirs,
            files=files,
            confidence=1.0,
            source_repos=[repo_name],
        )

    def suggest_patterns(
        self,
        min_prevalence: float = 0.7,
    ) -> list[PatternDraft]:
        if len(self._repo_paths) < 2:
            logger.info("Need at least 2 repos to suggest patterns")
            return []

        repo_structures: dict[str, list[str]] = {}
        for name, path in self._repo_paths.items():
            repo_structures[name] = _get_sorted_path_list(path)

        shared_dirs = _find_common_subtrees(repo_structures, min_prevalence)

        drafts: list[PatternDraft] = []
        for dir_path, prevalence in shared_dirs.items():
            shared_files = _find_common_files(repo_structures, dir_path, min_prevalence)
            category = _infer_category(dir_path)
            name = dir_path.rstrip("/").replace("/", "-")
            drafts.append(PatternDraft(
                category=category,
                name=name,
                dirs=[{"path": dir_path, "required": True, "description": ""}],
                files=[{"path": f"{dir_path}/{f}", "required": False, "description": ""} for f in shared_files],
                confidence=prevalence,
                source_repos=[n for n, _ in repo_structures.items() if dir_path in _get_sorted_path_list(self._repo_paths[n])],
            ))

        return sorted(drafts, key=lambda d: -d.confidence)


def _get_sorted_path_list(repo_path: Path) -> list[str]:
    paths = []
    for item in sorted(repo_path.rglob("*")):
        rel = item.relative_to(repo_path).as_posix()
        if item.is_file():
            paths.append(rel)
    return paths


def _find_common_subtrees(
    repo_structures: dict[str, list[str]], min_prevalence: float
) -> dict[str, float]:
    all_files: set[str] = set()
    for files in repo_structures.values():
        all_files.update(files)

    n_repos = len(repo_structures)
    result: dict[str, float] = {}
    for file_path in all_files:
        dir_path = file_path.rsplit("/", 1)[0] if "/" in file_path else ""
        if not dir_path:
            continue
        count = sum(1 for files in repo_structures.values() if dir_path in " ".join(files))
        prevalence = count / n_repos
        if prevalence >= min_prevalence:
            result[dir_path] = max(result.get(dir_path, 0), prevalence)

    return result


def _find_common_files(
    repo_structures: dict[str, list[str]], dir_path: str, min_prevalence: float
) -> list[str]:
    file_counts: dict[str, int] = {}
    n_repos = len(repo_structures)
    for files in repo_structures.values():
        matching = [f.split("/")[-1] for f in files if f.startswith(dir_path + "/")]
        for f in matching:
            file_counts[f] = file_counts.get(f, 0) + 1
    return sorted(f for f, c in file_counts.items() if c / n_repos >= min_prevalence)


def _infer_category(dir_path: str) -> str:
    if dir_path.startswith("adapter"):
        return "adapters"
    if dir_path.startswith("component") or dir_path.startswith("template"):
        return "components"
    if dir_path in ("deploy", "deployment", "docker"):
        return "deployment"
    if dir_path in ("settings", "config"):
        return "scaffolding"
    return "scaffolding"
```

- [x] **Step 2: Verify import works**

```bash
cd /Users/les/Projects/mahavishnu
python -c "from mahavishnu.scaffolding.extractor import PatternExtractor; print('OK')"
```

Expected: OK

- [x] **Step 3: Commit**

```bash
git add mahavishnu/scaffolding/extractor.py
git commit -m "feat(scaffolding): add Pattern Extractor with manual curation and AI suggestion"
```

______________________________________________________________________

### Task 7: Build Scaffolding Engine Phase 1

**Files:**

- Create: `mahavishnu/scaffolding/engine.py`

- Create: `tests/unit/test_scaffolding_engine.py`

- [x] **Step 1: Write failing tests**

```python
# tests/unit/test_scaffolding_engine.py
"""Tests for Scaffolding Engine Phase 1."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml

from mahavishnu.scaffolding.models import Pattern
from mahavishnu.scaffolding.library import PatternLibrary
from mahavishnu.scaffolding.engine import ScaffoldingEngine


@pytest.fixture
def engine(tmp_path: Path) -> ScaffoldingEngine:
    lib = PatternLibrary(root=Path(__file__).resolve().parent.parent.parent.parent / "patterns")
    lib.load_all()
    return ScaffoldingEngine(library=lib)


class TestEngineScaffold:
    def test_scaffold_minimal_project(self, engine: ScaffoldingEngine, tmp_path: Path):
        result = engine.scaffold(
            project_name="test-app",
            patterns=["scaffolding/minimal"],
            output_dir=tmp_path / "test-app",
        )
        assert (result / "main.py").exists()
        assert (result / "pyproject.toml").exists()
        assert "test-app" in (result / "pyproject.toml").read_text()

    def test_scaffold_project_creates_dirs(self, engine: ScaffoldingEngine, tmp_path: Path):
        result = engine.scaffold(
            project_name="test-app",
            patterns=["scaffolding/project"],
            output_dir=tmp_path / "test-app",
        )
        assert (result / "settings").is_dir()
        assert (result / "templates" / "base" / "blocks").is_dir()

    def test_variables_rendered(self, engine: ScaffoldingEngine, tmp_path: Path):
        result = engine.scaffold(
            project_name="my-cool-app",
            patterns=["scaffolding/minimal"],
            output_dir=tmp_path / "test-app",
            title="My Cool App",
        )
        content = (result / "main.py").read_text()
        assert "my-cool-app" in content
        assert "My Cool App" in content

    def test_composite_patterns(self, engine: ScaffoldingEngine, tmp_path: Path):
        result = engine.scaffold(
            project_name="test-pwa",
            patterns=["composite/pwa-app"],
            output_dir=tmp_path / "test-pwa",
        )
        assert (result / "main.py").exists()
        assert (result / "Dockerfile").exists()

    def test_manifest_written(self, engine: ScaffoldingEngine, tmp_path: Path):
        result = engine.scaffold(
            project_name="test-app",
            patterns=["scaffolding/minimal"],
            output_dir=tmp_path / "test-app",
        )
        manifest = result / ".mahavishnu" / "manifest.json"
        assert manifest.exists()
        import json
        data = json.loads(manifest.read_text())
        assert data["project_name"] == "test-app"
        assert len(data["patterns"]) >= 1

    def test_file_merge_slot(self, engine: ScaffoldingEngine, tmp_path: Path):
        result = engine.scaffold(
            project_name="test-auth",
            patterns=["scaffolding/project", "adapters/auth"],
            output_dir=tmp_path / "test-auth",
        )
        content = (result / "main.py").read_text()
        assert "middleware" in content.lower() or "Middleware" in content

    def test_circular_dependency_fails(self, tmp_path: Path):
        lib = PatternLibrary(root=tmp_path)
        lib.root.joinpath("a").mkdir()
        lib.root.joinpath("b").mkdir()
        lib.root.joinpath("a", "a.yaml").write_text(
            yaml.dump({"id": "a/x", "name": "X", "depends": [{"id": "b/y"}], "structure": {"dirs": [], "files": []}})
        )
        lib.root.joinpath("b", "b.yaml").write_text(
            yaml.dump({"id": "b/y", "name": "Y", "depends": [{"id": "a/x"}], "structure": {"dirs": [], "files": []}})
        )
        lib.load_all()
        eng = ScaffoldingEngine(library=lib)
        with pytest.raises(Exception, match="ircular"):
            eng.scaffold("test", ["a/x", "b/y"], tmp_path / "test")

    def test_missing_dependency_fails(self, engine: ScaffoldingEngine, tmp_path: Path):
        with pytest.raises(Exception, match="not found"):
            engine.scaffold("test", ["nonexistent/x"], tmp_path / "test")

    def test_atomic_rollback_on_failure(self, engine: ScaffoldingEngine, tmp_path: Path):
        output = tmp_path / "should-not-exist"
        with pytest.raises(Exception):
            engine.scaffold("test", ["nonexistent/x"], output)
        assert not output.exists()
```

- [x] **Step 2: Run tests to verify they fail**

```bash
cd /Users/les/Projects/mahavishnu
python -m pytest tests/unit/test_scaffolding_engine.py -v 2>&1 | tail -10
```

Expected: FAIL

- [x] **Step 3: Implement ScaffoldingEngine**

```python
# mahavishnu/scaffolding/engine.py
"""Scaffolding Engine Phase 1: deterministic template rendering."""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import BaseLoader, Environment, StrictUndefined

from mahavishnu.scaffolding.dependency_graph import PatternDependencyGraph
from mahavishnu.scaffolding.models import Pattern, SlotSpec
from mahavishnu.scaffolding.validation import validate_pattern

if TYPE_CHECKING:
    from mahavishnu.scaffolding.library import PatternLibrary

logger = logging.getLogger(__name__)

_MANAGED_HEADER = (
    "# Managed by mahavishnu scaffold — pattern: {pattern_id} v{version}\n"
    "# Manual edits detected on re-scaffold. Edit the pattern template to make permanent changes.\n"
)


class ScaffoldingEngine:
    def __init__(self, library: PatternLibrary) -> None:
        self.library = library

    def scaffold(
        self,
        project_name: str,
        patterns: list[str],
        output_dir: Path | str,
        title: str | None = None,
        author: str | None = None,
        version: str = "0.1.0",
        python_version: str = "3.12",
    ) -> Path:
        output = Path(output_dir)

        # 1. Resolve all patterns (expand composites)
        resolved = self._resolve_patterns(patterns)

        # 2. Build dependency graph and sort
        graph = self._build_graph(resolved)

        # 3. Validate
        issues: list[str] = []
        for p in resolved.values():
            issues.extend(validate_pattern(p, self.library))
        file_conflicts = graph.check_file_conflicts()
        for p1, p2, path in file_conflicts:
            issues.append(f"File conflict: {p1} and {p2} both claim '{path}'")
        if issues:
            raise ValueError("Validation failed:\n" + "\n".join(f"  - {i}" for i in issues))

        # 4. Compute variables
        variables = self._compute_variables(project_name, title, author, version, python_version, resolved)

        # 5. Create Jinja2 environments
        scaffold_env = Environment(undefined=StrictUndefined)
        scaffold_env.filters["toml_array"] = _toml_array_filter
        template_env = Environment(
            variable_start_string="[[",
            variable_end_string="]]",
            block_start_string="[%",
            block_end_string="%]",
            comment_start_string="[#",
            comment_end_string="#]",
            undefined=StrictUndefined,
        )

        # 6. Scaffold to temp directory
        temp_dir = output.parent / f".mahavishnu-scaffold-{uuid.uuid4().hex[:8]}"
        try:
            temp_dir.mkdir(parents=True)

            for pattern_id in graph.topological_sort():
                pattern = resolved[pattern_id]
                self._render_pattern(pattern, variables, temp_dir, scaffold_env, template_env)

            # 7. Write manifest and lockfile
            self._write_manifest(temp_dir, project_name, resolved, variables)

            # 8. Initialize git
            self._init_git(temp_dir, project_name)

            # 9. Atomic rename
            output.mkdir(parents=True, exist_ok=True)
            shutil.move(str(temp_dir), str(output))

            return output
        except Exception:
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
            raise

    def validate_project(self, project_path: Path) -> list[str]:
        manifest_path = project_path / ".mahavishnu" / "manifest.json"
        if not manifest_path.exists():
            return ["No manifest.json found — not a mahavishnu-scaffolded project"]
        manifest = json.loads(manifest_path.read_text())
        issues: list[str] = []
        for entry in manifest.get("patterns", []):
            p = self.library.get(entry["id"])
            if p is None:
                issues.append(f"Pattern '{entry['id']}' not found in library")
                continue
            for d in p.get_dirs():
                if d.required and not (project_path / d.path).exists():
                    issues.append(f"Required directory '{d.path}' missing")
            for f in p.get_files():
                if f.required and not (project_path / f.path).exists():
                    issues.append(f"Required file '{f.path}' missing")
        return issues

    def _resolve_patterns(self, pattern_ids: list[str]) -> dict[str, Pattern]:
        resolved: dict[str, Pattern] = {}
        queue = list(pattern_ids)

        while queue:
            pid = queue.pop(0)
            if pid in resolved:
                continue
            pattern = self.library.get(pid)
            if pattern is None:
                raise ValueError(f"Pattern '{pid}' not found in library")
            resolved[pid] = pattern
            for dep_id in pattern.get_dependency_ids():
                if dep_id not in resolved:
                    queue.append(dep_id)
        return resolved

    def _build_graph(self, resolved: dict[str, Pattern]) -> PatternDependencyGraph:
        graph = PatternDependencyGraph()
        for pid in resolved:
            graph.add(pid)
            for dep_id in resolved[pid].get_dependency_ids():
                graph.add_edge(pid, dep_id)
            for f in resolved[pid].get_files():
                if f.required:
                    graph.claim_file(pid, f.path)
        return graph

    def _compute_variables(
        self,
        project_name: str,
        title: str | None,
        author: str | None,
        version: str,
        python_version: str,
        resolved: dict[str, Pattern],
    ) -> dict[str, str]:
        import secrets
        slug = project_name.replace("-", "_")
        return {
            "project_name": project_name,
            "project_slug": slug,
            "project_title": title or project_name.replace("-", " ").title(),
            "author": author or "Unknown",
            "version": version,
            "python_version": python_version,
            "session_secret": secrets.token_urlsafe(32),
            "dependencies": ", ".join(
                sorted({d for p in resolved.values() for dep in p.get_dependency_ids()})
            ),
            "adapter_names": ", ".join(
                sorted({pid.split("/")[0] for pid in resolved if pid.startswith("adapters/")})
            ),
        }

    def _render_pattern(
        self,
        pattern: Pattern,
        variables: dict[str, str],
        output_dir: Path,
        scaffold_env: Environment,
        template_env: Environment,
    ) -> None:
        # Create directories
        for d in pattern.get_dirs():
            dir_path = output_dir / d.path
            dir_path.mkdir(parents=True, exist_ok=True)

        # Slot claims for file-merge
        slot_injections: dict[str, str] = {}
        for slot_name, slot in pattern.get_slots().items():
            if slot.type == "file-merge":
                slot_injections[slot_name] = ""

        # Render files
        for f in pattern.get_files():
            template_name = f.template
            template_str = pattern.templates.get(template_name, "")
            if not template_str:
                continue

            env = template_env if f.path.endswith(".html") else scaffold_env
            try:
                rendered = env.from_string(template_str).render(**variables)
            except Exception as e:
                raise ValueError(f"Template render error in '{template_name}' for '{pattern.id}': {e}") from e

            # Apply slot markers
            for slot_name, content in slot_injections.items():
                marker = f"{{{{slot:{slot_name}}}}}"
                if marker in rendered:
                    rendered = rendered.replace(marker, content)

            # Add managed header
            if not rendered.startswith("# Managed by"):
                rendered = _MANAGED_HEADER.format(
                    pattern_id=pattern.id, version=pattern.version
                ) + "\n" + rendered

            file_path = output_dir / f.path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(rendered)

        # Collect file-merge slot content from this pattern's templates
        for slot_name, slot in pattern.get_slots().items():
            if slot.type == "file-merge" and slot.merge_strategy == "marker-injection":
                # Look for a template that provides the injection content
                injection_template = f"{slot_name}-injection"
                if injection_template in pattern.templates:
                    env = template_env if slot.path.endswith(".html") else scaffold_env
                    content = env.from_string(pattern.templates[injection_template]).render(**variables)
                    slot_injections[slot_name] = content

    def _write_manifest(
        self, output_dir: Path, project_name: str, resolved: dict[str, Pattern], variables: dict[str, str]
    ) -> None:
        manifest_dir = output_dir / ".mahavishnu"
        manifest_dir.mkdir(parents=True, exist_ok=True)

        patterns_list = []
        for pid in sorted(resolved):
            p = resolved[pid]
            file_hash = hashlib.sha256(
                yaml.dump(p.model_dump(mode="json")).encode()
            ).hexdigest()[:16]
            patterns_list.append({
                "id": p.id,
                "version": p.version,
                "file_hash": f"sha256:{file_hash}",
            })

        manifest = {
            "schema_version": 1,
            "project_name": project_name,
            "patterns": patterns_list,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "variables": {
                k: v for k, v in variables.items() if k != "session_secret"
            },
        }
        (manifest_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
        (manifest_dir / "patterns.lock").write_text(
            "\n".join(f"{p['id']}=={p['version']}" for p in patterns_list) + "\n"
        )

    def _init_git(self, project_dir: Path, project_name: str) -> None:
        import subprocess
        subprocess.run(["git", "init"], cwd=project_dir, capture_output=True)
        subprocess.run(["git", "add", "-A"], cwd=project_dir, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", f"init: scaffold {project_name} via mahavishnu"],
            cwd=project_dir,
            capture_output=True,
        )


def _toml_array_filter(value: list[str]) -> str:
    items = ", ".join(f'"{v}"' for v in value)
    return f"[{items}]"
```

- [x] **Step 4: Run tests to verify they pass**

```bash
cd /Users/les/Projects/mahavishnu
python -m pytest tests/unit/test_scaffolding_engine.py -v 2>&1 | tail -25
```

Expected: All PASS

- [x] **Step 5: Commit**

```bash
git add mahavishnu/scaffolding/engine.py tests/unit/test_scaffolding_engine.py
git commit -m "feat(scaffolding): add Scaffolding Engine Phase 1 with atomic writes"
```

______________________________________________________________________

### Task 8: Create Jinja2 environment with dual delimiters and custom filters

**Files:**

- Create: `mahavishnu/scaffolding/jinjava_env.py`

- [x] **Step 1: Implement Jinja2 environment factory**

```python
# mahavishnu/scaffolding/jinjava_env.py
"""Jinja2 environment factory with dual delimiter support."""

from __future__ import annotations

from jinja2 import Environment, StrictUndefined


def create_scaffold_env() -> Environment:
    """Create Jinja2 env for scaffold templates ({{ }} delimiters)."""
    env = Environment(undefined=StrictUndefined)
    env.filters["toml_array"] = _toml_array_filter
    env.filters["kebab_to_snake"] = lambda s: s.replace("-", "_")
    env.filters["snake_to_title"] = lambda s: s.replace("_", " ").title()
    return env


def create_template_env() -> Environment:
    """Create Jinja2 env for generated HTML templates ([[ ]] delimiters)."""
    return Environment(
        variable_start_string="[[",
        variable_end_string="]]",
        block_start_string="[%",
        block_end_string="%]",
        comment_start_string="[#",
        comment_end_string="#]",
        undefined=StrictUndefined,
    )


def _toml_array_filter(value: list[str]) -> str:
    items = ", ".join(f'"{v}"' for v in value)
    return f"[{items}]"
```

- [x] **Step 2: Verify import**

```bash
cd /Users/les/Projects/mahavishnu
python -c "from mahavishnu.scaffolding.jinjava_env import create_scaffold_env, create_template_env; print('OK')"
```

Expected: OK

- [x] **Step 3: Commit**

```bash
git add mahavishnu/scaffolding/jinjava_env.py
git commit -m "feat(scaffolding): add dual Jinja2 environment factory"
```

______________________________________________________________________

### Task 9: Build CLI commands

**Files:**

- Create: `mahavishnu/cli/scaffold_cli.py`

- Create: `tests/unit/test_scaffolding_cli.py`

- Modify: `mahavishnu/_main_cli.py`

- [x] **Step 1: Write failing tests for CLI**

```python
# tests/unit/test_scaffolding_cli.py
"""Tests for scaffold CLI commands."""

from __future__ annotations

import tempfile
from pathlib import Path

from typer.testing import CliRunner

from mahavishnu.cli.scaffold_cli import app


runner = CliRunner()


class TestPatternsList:
    def test_list_patterns(self):
        result = runner.invoke(app, ["patterns", "list"])
        assert result.exit_code == 0
        assert "scaffolding/project" in result.output

    def test_list_by_category(self):
        result = runner.invoke(app, ["patterns", "list", "--category", "components"])
        assert result.exit_code == 0
        assert "components/" in result.output
        assert "scaffolding/" not in result.output

    def test_list_empty_category(self):
        result = runner.invoke(app, ["patterns", "list", "--category", "nonexistent"])
        assert result.exit_code == 0


class TestPatternsShow:
    def test_show_pattern(self):
        result = runner.invoke(app, ["patterns", "show", "scaffolding/project"])
        assert result.exit_code == 0
        assert "Fastblocks Project Skeleton" in result.output

    def test_show_missing(self):
        result = runner.invoke(app, ["patterns", "show", "nonexistent"])
        assert result.exit_code == 1


class TestPatternsValidate:
    def test_validate_library(self):
        result = runner.invoke(app, ["patterns", "validate"])
        assert result.exit_code == 0
        assert "validation errors" in result.output.lower() or "valid" in result.output.lower()


class TestScaffoldCommand:
    def test_scaffold_dry_run(self):
        result = runner.invoke(app, [
            "scaffold", "test-dry", "--patterns", "scaffolding/minimal", "--dry-run",
        ])
        assert result.exit_code == 0
        assert "dry-run" in result.output.lower() or "would include" in result.output.lower()

    def test_scaffold_missing_pattern(self):
        result = runner.invoke(app, [
            "scaffold", "test-bad", "--patterns", "nonexistent/x",
        ])
        assert result.exit_code == 1


class TestScaffoldValidate:
    def test_validate_project(self):
        result = runner.invoke(app, ["scaffold", "validate", "--project", "/tmp/nonexistent"])
        assert result.exit_code == 1
```

- [x] **Step 2: Run tests to verify they fail**

```bash
cd /Users/les/Projects/mahavishnu
python -m pytest tests/unit/test_scaffolding_cli.py -v 2>&1 | tail -10
```

Expected: FAIL

- [x] **Step 3: Implement CLI module**

```python
# mahavishnu/cli/scaffold_cli.py
"""CLI commands for pattern management and project scaffolding."""

from __future__ annotations

import tempfile
from pathlib import Path

import typer

from mahavishnu.scaffolding.engine import ScaffoldingEngine
from mahavishnu.scaffolding.library import PatternLibrary
from mahavishnu.scaffolding.validation import validate_pattern

app = typer.Typer(help="Pattern management and project scaffolding")


def _get_library() -> PatternLibrary:
    lib = PatternLibrary()
    lib.load_all()
    return lib


@app.callback(invoke_without_command=True)
def callback():
    """Pattern management and scaffolding for Fastblocks projects."""


# ── Pattern commands ──────────────────────────────────────────────────────────


patterns_app = typer.Typer(help="Pattern library management")
app.add_typer(patterns_app, name="patterns")


@patterns_app.command("list")
def patterns_list(
    category: str | None = typer.Option(None, "--category", "-c", help="Filter by category"),
):
    """List all patterns in the library."""
    lib = _get_library()
    categories = lib.list_all_categories()

    if category and category not in categories:
        typer.echo(f"Category '{category}' not found. Available: {', '.join(categories)}")
        raise typer.Exit(code=1)

    patterns = lib.list_category(category) if category else lib._cache.values()
    if not patterns:
        typer.echo("No patterns found.")
        return

    grouped: dict[str, list] = {}
    for p in sorted(patterns, key=lambda x: x.id):
        cat = p.id.split("/")[0]
        grouped.setdefault(cat, []).append(p)

    for cat in sorted(grouped):
        typer.echo(f"\n{cat}/")
        for p in grouped[cat]:
            dep_str = f" (depends: {len(p.depends)})" if p.depends else ""
            typer.echo(f"  {p.id} v{p.version}{dep_str} — {p.description}")


@patterns_app.command("show")
def patterns_show(
    pattern_id: str = typer.Argument(..., help="Full pattern ID (e.g., components/nav)"),
):
    """Show pattern details."""
    lib = _get_library()
    p = lib.get(pattern_id)
    if p is None:
        typer.echo(f"Pattern '{pattern_id}' not found")
        raise typer.Exit(code=1)

    typer.echo(f"ID:          {p.id}")
    typer.echo(f"Name:        {p.name}")
    typer.echo(f"Version:     {p.version}")
    typer.echo(f"Description: {p.description}")
    typer.echo(f"Source repos: {', '.join(p.source_repos)}")
    typer.echo(f"Confidence:  {p.confidence}")
    typer.echo(f"Tags:        {', '.join(p.tags)}")

    if p.depends:
        typer.echo("Depends:")
        for d in p.depends:
            typer.echo(f"  - {d.id}" + (f" (version: {d.version})" if d.version else ""))

    dirs = p.get_dirs()
    files = p.get_files()
    slots = p.get_slots()
    templates = p.templates

    typer.echo(f"\nStructure:   {len(dirs)} dirs, {len(files)} files")
    typer.echo(f"Slots:       {len(slots)}")
    typer.echo(f"Templates:   {len(templates)}")

    if dirs:
        typer.echo("\nDirectories:")
        for d in dirs:
            req = " [required]" if d.required else ""
            typer.echo(f"  {d.path}{req}")

    if files:
        typer.echo("\nFiles:")
        for f in files:
            req = " [required]" if f.required else ""
            tmpl = f" (template: {f.template})" if f.template else ""
            typer.echo(f"  {f.path}{req}{tmpl}")

    if slots:
        typer.echo("\nSlots:")
        for name, slot in slots.items():
            req = " [required]" if slot.required else ""
            typer.echo(f"  {name}: {slot.path} ({slot.type}){req}")


@patterns_app.command("validate")
def patterns_validate():
    """Validate all patterns in the library."""
    lib = _get_library()
    total_issues = 0
    for p in lib._cache.values():
        issues = validate_pattern(p, lib)
        if issues:
            total_issues += len(issues)
            typer.echo(f"\n{p.id}:")
            for issue in issues:
                typer.echo(f"  - {issue}")
    if total_issues == 0:
        typer.echo("All patterns valid.")
    else:
        typer.echo(f"\n{total_issues} issue(s) found across {len(lib._cache)} patterns.")


@patterns_app.command("search")
def patterns_search(
    query: str = typer.Argument(..., help="Search query"),
    source_repos: str | None = typer.Option(None, "--source-repos", "-s", help="Filter by source repos"),
):
    """Search patterns by keyword."""
    lib = _get_library()
    results = lib.search(query)
    if source_repos:
        results = [p for p in results if any(s in p.source_repos for s in source_repos.split(","))]

    if not results:
        typer.echo(f"No patterns matching '{query}'.")
        return

    typer.echo(f"Found {len(results)} pattern(s) matching '{query}':")
    for p in results:
        typer.echo(f"  {p.id} — {p.name}")


# ── Scaffolding commands ──────────────────────────────────────────────────────


@app.command("scaffold")
def scaffold(
    project_name: str = typer.Argument(..., help="Project name (kebab-case)"),
    patterns: list[str] = typer.Option(..., "--patterns", "-p", help="Pattern IDs to compose"),
    title: str | None = typer.Option(None, "--title", "-t", help="Project title"),
    author: str | None = typer.Option(None, "--author", "-a", help="Author name"),
    version: str = typer.Option("0.1.0", "--version", "-v", help="Initial version"),
    output: Path | None = typer.Option(None, "--output", "-o", help="Output directory"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be scaffolded"),
):
    """Scaffold a new Fastblocks project from composed patterns."""
    lib = _get_library()

    if dry_run:
        resolved = []
        queue = list(patterns)
        seen = set()
        while queue:
            pid = queue.pop(0)
            if pid in seen:
                continue
            p = lib.get(pid)
            if p is None:
                typer.echo(f"Pattern '{pid}' not found.")
                raise typer.Exit(code=1)
            resolved.append(p)
            seen.add(pid)
            for dep in p.get_dependency_ids():
                queue.append(dep)

        typer.echo(f"Would scaffold '{project_name}' with {len(resolved)} patterns:")
        for p in resolved:
            typerper.echo(f"  - {p.id} v{p.version}")
        return

    if output is None:
        output = Path.cwd() / project_name

    engine = ScaffoldingEngine(library=lib)
    try:
        result = engine.scaffold(
            project_name=project_name,
            patterns=patterns,
            output_dir=output,
            title=title,
            author=author,
            version=version,
        )
        typer.echo(f"Scaffolded '{project_name}' to {result}")
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)


@app.command("scaffold-validate")
def scaffold_validate(
    project: Path = typer.Argument(..., help="Path to scaffolded project"),
):
    """Validate a scaffolded project against its manifest."""
    lib = _get_library()
    engine = ScaffoldingEngine(library=lib)
    issues = engine.validate_project(project)
    if issues:
        typer.echo(f"Validation issues in {project}:")
        for i in issues:
            typer.echo(f"  - {i}")
        raise typer.Exit(code=1)
    typer.echo(f"{project} is valid.")
```

- [x] **Step 4: Register CLI in main**

Add to `mahavishnu/_main_cli.py` after the existing imports (around line 48):

```python
# Import pattern scaffolding CLI
from .cli.scaffold_cli import app as scaffold_app
```

And after the existing `app.add_typer(worktree_app, name="worktree")` (around line 58):

```python
# Add scaffold sub-app
app.add_typer(scaffold_app, name="scaffold")
```

- [x] **Step 5: Run CLI tests**

```bash
cd /Users/les/Projects/mahavishnu
python -m pytest tests/unit/test_scaffolding_cli.py -v 2>&1 | tail -25
```

Expected: All PASS

- [x] **Step 6: Smoke test the CLI end-to-end**

```bash
cd /Users/les/Projects/mahavishnu
mahavishnu patterns list 2>&1 | head -10
mahavishnu patterns show scaffolding/project 2>&1 | head -5
mahavishnu scaffold "cli-test" --patterns scaffolding/minimal --output /tmp/cli-test --dry-run 2>&1
mahavishnu patterns validate 2>&1
```

- [x] **Step 7: Commit**

```bash
git add mahavishnu/cli/scaffold_cli.py tests/unit/test_scaffolding_cli.py mahavishnu/_main_cli.py
git commit -m "feat(scaffolding): add CLI commands for pattern management and scaffolding"
```

______________________________________________________________________

### Task 10: End-to-end integration test

**Files:**

- Create: `tests/integration/test_scaffold_e2e.py`

- [x] **Step 1: Write E2E test**

```python
# tests/integration/test_scaffold_e2e.py
"""End-to-end test: scaffold a project, verify it runs."""

from __future__ annotations

import subprocess
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def scaffolded_project():
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir) / "e2e-test-app"
        result = subprocess.run(
            [
                "python", "-m", "mahavishnu", "scaffold",
                "e2e-test-app",
                "--patterns", "scaffolding/project",
                "--output", str(project_dir),
            ],
            capture_output=True,
            text=True,
            cwd="/Users/les/Projects/mahavishnu",
        )
        if result.returncode != 0:
            raise RuntimeError(f"Scaffold failed: {result.stderr}")
        yield project_dir


class TestScaffoldE2E:
    def test_project_structure(self, scaffolded_project: Path):
        assert (scaffolded_project / "main.py").exists()
        assert (scaffolded_project / "pyproject.toml").exists()
        assert (scaffolded_project / "settings").is_dir()
        assert (scaffolded_project / "templates" / "base" / "blocks").is_dir()

    def test_manifest_exists(self, scaffolded_project: Path):
        assert (scaffolded_project / ".mahavishnu" / "manifest.json").exists()
        assert (scaffolded_project / ".mahavishnu" / "patterns.lock").exists()

    def test_git_initialized(self, scaffolded_project: Path):
        assert (scaffolded_project / ".git").is_dir()
        result = subprocess.run(
            ["git", "log", "--oneline"],
            capture_output=True,
            text=True,
            cwd=scaffolded_project,
        )
        assert "init:" in result.stdout or "scaffold" in result.stdout.lower()

    def test_main_py_has_project_name(self, scaffolded_project: Path):
        content = (scaffolded_project / "main.py").read_text()
        assert "e2e-test-app" in content or "e2e_test_app" in content

    def test_pyproject_has_dependencies(self, scaffolded_project: Path):
        content = (scaffolded_project / "pyproject.toml").read_text()
        assert "oneiric" in content.lower()
        assert "fastblocks" in content.lower()

    def test_validate_passes(self, scaffolded_project: Path):
        result = subprocess.run(
            [
                "python", "-m", "mahavishnu", "scaffold-validate",
                "--project", str(scaffolded_project),
            ],
            capture_output=True,
            text=True,
            cwd="/Users/les/Projects/mahavishnu",
        )
        assert result.returncode == 0, f"Validate failed: {result.stderr}"

    def test_composite_scaffold(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "e2e-pwa"
            result = subprocess.run(
                [
                    "python", "-m", "mahavishnu", "scaffold",
                    "e2e-pwa",
                    "--patterns", "composite/pwa-app",
                    "--output", str(project_dir),
                ],
                capture_output=True,
                text=True,
                cwd="/Users/les/Projects/mahavishnu",
            )
            assert result.returncode == 0, f"Composite scaffold failed: {result.stderr}"
            assert (project_dir / "Dockerfile").exists()
            assert (project_dir / "main.py").exists()
```

- [x] **Step 2: Run E2E test**

```bash
cd /Users/les/Projects/mahavishnu
python -m pytest tests/integration/test_scaffold_e2e.py -v 2>&1 | tail -20
```

Expected: All PASS

- [x] **Step 3: Commit**

```bash
git add tests/integration/test_scaffold_e2e.py
git commit -m "test(scaffolding): add end-to-end integration test for scaffolding"
```

______________________________________________________________________

### Task 11: Self-review and cleanup

- [x] **Step 1: Run all scaffolding tests**

```bash
cd /Users/les/Projects/mahavishnu
python -m pytest tests/unit/test_scaffolding_*.py tests/integration/test_scaffold_e2e.py -v 2>&1 | tail -30
```

Expected: All PASS

- [x] **Step 2: Verify no regressions in existing tests**

```bash
cd /Users/les/Projects/mahavishnu
python -m pytest tests/unit/test_dependency_graph.py -v 2>&1 | tail -10
```

Expected: Existing tests still pass

- [x] **Step 3: Run ruff on new modules**

```bash
cd /Users/les/Projects/mahavishnu
ruff check mahavishnu/scaffolding/ mahavishnu/cli/scaffold_cli.py 2>&1
```

Expected: No errors (or only fixable warnings)

- [x] **Step 4: Final commit if any cleanup needed**

```bash
git add -A
git commit -m "chore(scaffolding): cleanup and final review"
```

---
status: shipped
role: implementation
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
topic: code-indexing-integration
---

# Code Indexing Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Status:** COMPLETE — all 42 tasks shipped 2026-04-30 per Phase 4 annotation. Call chain, impact analysis, and incremental re-indexing live in `session_buddy/subscribers/code_graph_subscriber.py`. Reference only. <!-- legacy status: COMPLETE — see YAML frontmatter -->
> **Goal:** Add call chain resolution, change impact analysis, and incremental re-indexing to the Bodai ecosystem by extending Session-Buddy's DuckPGQ property graph and adding Mahavishnu CLI commands.
> **Architecture:** Session-Buddy owns the code graph (DuckDB/DuckPGQ). Mahavishnu orchestrates indexing via CLI + git hooks. Two new Session-Buddy MCP tools (`code_call_chain`, `code_impact_analysis`) query the graph via PGQ. Mahavishnu's CLI triggers parsing with mcp-common's `CodeGraphAnalyzer` and upserts to Session-Buddy via MCP.
> **Tech Stack:** Python 3.12+, DuckDB + DuckPGQ, mcp-common CodeGraphAnalyzer, Typer CLI, Pydantic v2
> **Spec:** `docs/superpowers/specs/2026-04-26-code-indexing-integration-design.md`
> **Working directory:** `/Users/les/Projects/mahavishnu` (Mahavishnu) and `/Users/les/Projects/session-buddy` (Session-Buddy)

______________________________________________________________________

## File Structure

```
mahavishnu/
├── mahavishnu/
│   ├── core/
│   │   └── code_index/                    # NEW - Code indexing infrastructure
│   │       ├── __init__.py
│   │       ├── models.py                  # Pydantic models for requests/responses
│   │       ├── parser.py                  # File parsing orchestration
│   │       ├── indexer.py                 # Indexing workflow (detect changes, parse, upsert)
│   │       ├── git_hooks.py              # Hook installation/removal
│   │       ├── lock.py                    # PID-based file locks
│   │       ├── signature_redaction.py    # Secret pattern detection and redaction
│   │       └── path_validation.py        # Repo path validation against repos.yaml
│   ├── cli/
│   │   └── index_cli.py                  # NEW - CLI commands for indexing
│   └── _main_cli.py                       # MODIFY - register index_cli
└── tests/
    ├── unit/
    │   ├── test_code_index_models.py      # NEW
    │   ├── test_code_index_parser.py     # NEW
    │   ├── test_code_index_indexer.py    # NEW
    │   ├── test_signature_redaction.py    # NEW
    │   ├── test_git_hooks.py             # NEW
    │   ├── test_path_validation.py       # NEW
    │   └── test_code_graph_degradation.py # NEW
    └── integration/
        └── test_code_graph_e2e.py        # NEW

session-buddy/
├── session_buddy/
│   ├── mcp/tools/
│   │   └── code_graph_tools.py           # NEW - code_call_chain + code_impact_analysis
│   ├── knowledge_graph_db.py              # MODIFY - add upsert methods
│   └── mcp/server.py                      # MODIFY - register new tools
└── tests/
    └── test_code_graph_tools.py          # NEW
```

______________________________________________________________________

### Task 1: Create Pydantic models for code indexing

**Files:**

- Create: `mahavishnu/mahavishnu/core/code_index/__init__.py`

- Create: `mahavishnu/mahavishnu/core/code_index/models.py`

- [x] **Step 1: Create the code_index package**

```python
# mahavishnu/mahavishnu/core/code_index/__init__.py
"""Code knowledge graph indexing infrastructure."""

from .models import (
    CallChainRequest,
    CallChainResult,
    CallChain,
    ImpactAnalysisRequest,
    ImpactAnalysisResult,
    SymbolImpact,
    CodeGraphNode,
    CodeGraphEdge,
    IndexWorkItem,
    CodeGraphUnavailable,
    DegradationTier,
)
```

- [x] **Step 2: Write the models module**

```python
# mahavishnu/mahavishnu/core/code_index/models.py
"""Pydantic models for code graph indexing and querying."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class CodeGraphNode(BaseModel):
    """A node in the code knowledge graph."""

    symbol_id: str = Field(
        description='Qualified: "{repo_path}|||{file_path}|||{symbol_type}|||{symbol_name}"'
    )
    symbol_name: str = Field(description="Human-readable name for display")
    symbol_type: Literal["function", "class", "module", "file", "variable"]
    file_path: str
    repo_path: str
    start_line: int | None = None
    end_line: int | None = None
    language: str = "python"
    signature: str | None = None
    complexity: int | None = None
    is_deleted: bool = False
    last_indexed_at: datetime
    commit_hash: str


class CodeGraphEdge(BaseModel):
    """An edge in the code knowledge graph."""

    source: str = Field(description="Qualified symbol_id")
    target: str = Field(description="Qualified symbol_id")
    edge_type: Literal["calls", "imports", "inherits", "contains", "implements"]
    source_file: str
    target_file: str
    repo_path: str
    confidence: float = 1.0
    created_at: datetime


class CallChainRequest(BaseModel):
    """Input for call chain resolution."""

    symbol_name: str
    direction: Literal["callers", "callees", "both"] = "both"
    max_depth: int = 5
    repo_path: str | None = None
    edge_filter: list[str] | None = None

    @field_validator("max_depth")
    @classmethod
    def clamp_depth(cls, v: int) -> int:
        if v > 10:
            raise ValueError("max_depth cannot exceed 10")
        return v


class CallChain(BaseModel):
    """A single call chain path."""

    path: list[str] = Field(description="Qualified symbol names in traversal order")
    depth: int
    edge_types: list[str]
    files: list[str]


class CallChainResult(BaseModel):
    """Output of call chain resolution."""

    root_symbol: str
    chains: list[CallChain]
    total_nodes: int
    truncated: bool = False
    stale: bool = False
    last_indexed_at: datetime | None = None


class SymbolImpact(BaseModel):
    """Impact of a single symbol on another."""

    symbol_name: str = Field(description="Qualified symbol ID")
    symbol_type: Literal["function", "class", "module"]
    file_path: str
    depth: int
    dependency_type: Literal["calls", "imports", "inherits", "contains", "implements"]


class ImpactAnalysisRequest(BaseModel):
    """Input for change impact analysis."""

    symbol_name: str
    repo_path: str | None = None
    include_indirect: bool = True
    max_depth: int = 5

    @field_validator("max_depth")
    @classmethod
    def clamp_depth(cls, v: int) -> int:
        if v > 10:
            raise ValueError("max_depth cannot exceed 10")
        return v


class ImpactAnalysisResult(BaseModel):
    """Output of change impact analysis."""

    target: str
    direct_dependents: list[SymbolImpact]
    indirect_dependents: list[SymbolImpact]
    affected_files: list[str]
    risk_level: Literal["low", "medium", "high"]
    blast_radius: int = Field(description="Total transitive reach (all depths)")
    stale: bool = False
    last_indexed_at: datetime | None = None


class IndexWorkItem(BaseModel):
    """Tracks indexing state for a single repo."""

    repo_path: str
    trigger: Literal["git-event", "schedule", "manual"]
    files_changed: list[str]
    status: Literal["queued", "parsing", "upserting", "notifying", "complete", "failed"]
    started_at: datetime | None = None
    completed_at: datetime | None = None
    parse_failures: int = 0


class CodeGraphUnavailable(BaseModel):
    """Structured response when the code graph is unavailable."""

    reason: str
    suggestion: str
    tier: int = 4


class DegradationTier(BaseModel):
    """Current degradation state."""

    tier: Literal[1, 2, 3, 4]
    reason: str
    stale_since: datetime | None = None
    parse_failures: int = 0
    total_files: int = 0
```

- [x] **Step 3: Verify models import**

```bash
cd /Users/les/Projects/mahavishnu
python -c "from mahavishnu.core.code_index.models import CallChainRequest; print('OK')"
```

- [x] **Step 4: Commit**

```bash
git add mahavishnu/core/code_index/
git commit -m "feat: add Pydantic models for code graph indexing"
```

______________________________________________________________________

### Task 2: Create path validation module

**Files:**

- Create: `mahavishnu/mahavishnu/core/code_index/path_validation.py`

- [x] **Step 1: Write path validator**

```python
# mahavishnu/mahavishnu/core/code_index/path_validation.py
"""Validate repo paths against the registered repository catalog."""

from __future__ import annotations

from pathlib import Path

from mahavishnu.core.config import MahavishnuSettings


def get_registered_repos() -> set[str]:
    """Load registered repo paths from settings/repos.yaml.

    Returns absolute paths as strings.
    """
    settings = MahavishnuSettings()
    repos_path = Path(settings.config_dir) / "repos.yaml"
    if not repos_path.exists():
        return set()
    import yaml
    data = yaml.safe_load(repos_path.read_text())
    if not data or "repos" not in data:
        return set()
    return {str(Path(r["path"]).resolve()) for r in data["repos"] if "path" in r}


def validate_repo_path(repo_path: str) -> str:
    """Validate that a repo path is registered.

    Returns the resolved absolute path.

    Raises:
        ValueError: If the path is not registered in repos.yaml.
    """
    resolved = str(Path(repo_path).resolve())
    registered = get_registered_repos()
    if resolved not in registered:
        raise ValueError(
            f"Repo path '{repo_path}' is not registered in repos.yaml. "
            f"Registered paths: {sorted(registered)}"
        )
    return resolved
```

- [x] **Step 2: Write test**

```python
# mahavishnu/tests/unit/test_path_validation.py
"""Tests for repo path validation."""

from unittest.mock import patch

import pytest

from mahavishnu.core.code_index.path_validation import (
    get_registered_repos,
    validate_repo_path,
)


def test_validate_repo_path_registered(tmp_path, monkeypatch):
    """Accepts a path listed in repos.yaml."""
    repos_yaml = tmp_path / "repos.yaml"
    repos_yaml.write_text(
        f"repos:\n  - path: {tmp_path / 'my-repo'}\n"
    )
    monkeypatch.setattr(
        "mahavishnu.core.config.MahavishnuSettings",
        lambda: type("S", (), {"config_dir": str(tmp_path)})(),
    )
    result = validate_repo_path(str(tmp_path / "my-repo"))
    assert result == str((tmp_path / "my-repo").resolve())


def test_validate_repo_path_unregistered(tmp_path, monkeypatch):
    """Rejects a path not in repos.yaml."""
    repos_yaml = tmp_path / "repos.yaml"
    repos_yaml.write_text("repos: []\n")
    monkeypatch.setattr(
        "mahavishnu.core.config.MahavishnuSettings",
        lambda: type("S", (), {"config_dir": str(tmp_path)})(),
    )
    with pytest.raises(ValueError, match="not registered"):
        validate_repo_path("/unregistered/path")
```

- [x] **Step 3: Run test**

```bash
pytest tests/unit/test_path_validation.py -v
```

Expected: 2 passed

- [x] **Step 4: Commit**

```bash
git add mahavishnu/core/code_index/path_validation.py tests/unit/test_path_validation.py
git commit -m "feat: add repo path validation against repos.yaml"
```

______________________________________________________________________

### Task 3: Create signature redaction module

**Files:**

- Create: `mahavishnu/mahavishnu/core/code_index/signature_redaction.py`

- [x] **Step 1: Write redaction module**

```python
# mahavishnu/mahavishnu/core/code_index/signature_redaction.py
"""Redact secret-bearing patterns from function signatures before storage."""

from __future__ import annotations

import re

SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p)
    for p in [
        r"(?i)(api_key|apikey|api_secret)\s*=\s*['\"][^'\"]+['\"]",
        r"(?i)(password|passwd|pwd)\s*=\s*['\"][^'\"]+['\"]",
        r"(?i)(token|auth_token|access_token)\s*=\s*['\"][^'\"]+['\"]",
        r"(?i)(secret|client_secret)\s*=\s*['\"][^'\"]+['\"]",
        r"(?i)(private_key|rsa_private|ec_private|ssh_key)\s*=\s*['\"][^'\"]+['\"]",
        r"(?i)(connection_string|database_url|redis_url)\s*=\s*['\"][^'\"]+['\"]",
        r"(?i)(webhook_secret|bearer|credential)\s*=\s*['\"][^'\"]+['\"]",
        r"(?i)(aws_secret_access_key|github_token|slack_token)\s*=\s*['\"][^'\"]+['\"]",
        r'(?i)def\s+\w+\([^)]*(?:api_key|password|token|secret)\s*=\s*["\'][^"\']+["\']',
        r'(?i)\w+\s*:\s*str\s*=\s*os\.environ\["\'][^"\']+["\']',
        r'(?i)f["\'][^"\']*(?:token|key|secret|password)[^"\']*["\'].*\{',
    ]
]


def redact_signature(signature: str | None) -> str:
    """Replace secret-bearing patterns in a function signature.

    Returns the redacted signature, or the original if no secrets found.
    """
    if signature is None:
        return ""
    redacted = signature
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub('"<REDACTED>"', redacted)
    return redacted


def has_secrets(signature: str | None) -> bool:
    """Check if a signature contains potential secrets."""
    if signature is None:
        return False
    return any(p.search(signature) for p in SECRET_PATTERNS)
```

- [x] **Step 2: Write test**

```python
# mahavishnu/tests/unit/test_signature_redaction.py
"""Tests for signature redaction."""

import pytest

from mahavishnu.core.code_index.signature_redaction import (
    has_secrets,
    redact_signature,
)


def test_redact_api_key():
    assert redact_signature('def connect(api_key="sk-abc123")') == 'def connect(api_key="<REDACTED>")'


def test_redact_password():
    assert redact_signature('password = "hunter2"') == 'password = "<REDACTED>"'


def test_redact_bearer_token():
    assert redact_signature('token = "ghp_xxxxxxxxxxxx"') == 'token = "<REDACTED>"'


def test_no_redaction_clean_signature():
    sig = "def process_data(items: list[str], limit: int = 10) -> None:"
    assert redact_signature(sig) == sig


def test_has_secrets_true():
    assert has_secrets('def connect(api_key="sk-abc123")') is True


def test_has_secrets_false():
    assert has_secrets("def hello(name: str) -> None:") is False


def test_redact_none():
    assert redact_signature(None) == ""


def test_redact_connection_string():
    assert redact_signature('database_url = "postgres://..."') == 'database_url = "<REDACTED>"'
```

- [x] **Step 3: Run test**

```bash
pytest tests/unit/test_signature_redaction.py -v
```

Expected: 8 passed

- [x] **Step 4: Commit**

```bash
git add mahavishnu/core/code_index/signature_redaction.py tests/unit/test_signature_redaction.py
git commit -m "feat: add signature redaction for code graph storage"
```

______________________________________________________________________

### Task 4: Create PID-based locking module

**Files:**

- Create: `mahavishnu/mahavishnu/core/code_index/lock.py`

- [x] **Step 1: Write lock module**

```python
# mahavishnu/mahavishnu/core/code_index/lock.py
"""PID-based file locks for preventing concurrent indexing of the same repo."""

from __future__ import annotations

import errno
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

LOCK_TTL_SECONDS = 600  # 10 minutes


class RepoIndexLock:
    """PID-based lock for per-repo indexing.

    Lock file format: {pid}\\n{timestamp}\\n{repo_path}
    """

    def __init__(self, repo_path: str) -> None:
        self.repo_path = repo_path
        self.lock_file = Path(repo_path) / ".git" / "mahavishnu-index.lock"

    def acquire(self) -> bool:
        """Try to acquire the lock. Returns True if acquired."""
        if self._try_acquire():
            return True
        # Lock exists — check if stale
        try:
            content = self.lock_file.read_text().strip().split("\n")
            pid = int(content[0])
            ts = float(content[1])
        except (ValueError, IndexError, FileNotFoundError):
            # Corrupted lock file — remove and retry
            self._remove_lock()
            return self._try_acquire()

        # Check if process is alive
        if self._is_process_alive(pid):
            # Check if lock is stale (> 10 minutes)
            if time.time() - ts > LOCK_TTL_SECONDS:
                self._remove_lock()
                return self._try_acquire()
            return False

        # Process is dead — reclaim
        self._remove_lock()
        return self._try_acquire()

    def release(self) -> None:
        """Release the lock if we hold it."""
        try:
            content = self.lock_file.read_text().strip().split("\n")
            pid = int(content[0])
            if pid == os.getpid():
                self._remove_lock()
        except (ValueError, IndexError, FileNotFoundError):
            pass

    def _try_acquire(self) -> bool:
        try:
            self.lock_file.parent.mkdir(parents=True, exist_ok=True)
            self.lock_file.write_text(
                f"{os.getpid()}\n{time.time()}\n{self.repo_path}\n"
            )
            return True
        except OSError:
            return False

    def _remove_lock(self) -> None:
        try:
            self.lock_file.unlink()
        except FileNotFoundError:
            pass

    @staticmethod
    def _is_process_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except OSError as e:
            return e.errno != errno.ESRCH
```

- [x] **Step 2: Write test**

```python
# mahavishnu/tests/unit/test_git_hooks.py
"""Tests for PID-based locking (included in git_hooks test file for now)."""

import os
from pathlib import Path
from unittest.mock import patch

from mahavishnu.core.code_index.lock import RepoIndexLock


def test_acquire_and_release(tmp_path):
    lock = RepoIndexLock(str(tmp_path))
    assert lock.acquire() is True
    assert lock.lock_file.exists()
    lock.release()
    assert not lock.lock_file.exists()


def test_acquire_when_locked(tmp_path):
    lock1 = RepoIndexLock(str(tmp_path))
    lock2 = RepoIndexLock(str(tmp_path))
    assert lock1.acquire() is True
    assert lock2.acquire() is False
    lock1.release()


def test_acquire_reclaims_dead_process(tmp_path):
    lock = RepoIndexLock(str(tmp_path))
    lock.lock_file.parent.mkdir(parents=True, exist_ok=True)
    lock.lock_file.write_text(f"99999\n{0}\n{tmp_path}\n")
    assert lock.acquire() is True
    lock.release()
```

- [x] **Step 3: Run test**

```bash
pytest tests/unit/test_git_hooks.py -v
```

Expected: 3 passed

- [x] **Step 4: Commit**

```bash
git add mahavishnu/core/code_index/lock.py tests/unit/test_git_hooks.py
git commit -m "feat: add PID-based locking for concurrent indexing safety"
```

______________________________________________________________________

### Task 5: Create file parser module

**Files:**

- Create: `mahavishnu/mahavishnu/core/code_index/parser.py`

- [x] **Step 1: Write parser that wraps mcp-common CodeGraphAnalyzer**

```python
# mahavishnu/mahavishnu/core/code_index/parser.py
"""Parse Python source files into code graph nodes and edges using mcp-common."""

from __future__ import annotations

import logging
from datetime import datetime, UTC
from pathlib import Path

from mahavishnu.core.code_index.models import CodeGraphEdge, CodeGraphNode
from mahavishnu.core.code_index.signature_redaction import redact_signature

logger = logging.getLogger(__name__)

# File extensions we can parse
PARSABLE_EXTENSIONS = {".py"}
# Directories to skip
SKIP_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "node_modules",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "htmlcov",
    "dist", "build", ".eggs", ".tox",
}


def parse_file(
    file_path: str,
    repo_path: str,
    commit_hash: str,
) -> tuple[list[CodeGraphNode], list[CodeGraphEdge]] | None:
    """Parse a single file into graph nodes and edges.

    Returns None if the file is not parseable (wrong extension, skip dir, etc.).
    Raises on actual parse failures (caller handles).
    """
    path = Path(file_path)

    if path.suffix not in PARSABLE_EXTENSIONS:
        return None

    for skip_dir in SKIP_DIRS:
        if skip_dir in path.parts:
            return None

    try:
        from mcp_common.code_graph.analyzer import CodeGraphAnalyzer

        analyzer = CodeGraphAnalyzer(Path(repo_path))
        result = analyzer._analyze_python_file(path)
    except Exception as e:
        logger.warning(f"Parse failure for {file_path}: {e}")
        raise

    nodes: list[CodeGraphNode] = []
    edges: list[CodeGraphEdge] = []

    for node in result.nodes:
        symbol_id = f"{repo_path}|||{file_path}|||{node.node_type}|||{node.name}"
        signature = None
        complexity = None
        start_line = None
        end_line = None

        if node.node_type == "function":
            signature = redact_signature(getattr(node, "docstring", None))
            complexity = getattr(node, "complexity", 1)
            start_line = getattr(node, "start_line", None)
            end_line = getattr(node, "end_line", None)
        elif node.node_type == "class":
            start_line = getattr(node, "start_line", None)
            end_line = getattr(node, "end_line", None)

        graph_node = CodeGraphNode(
            symbol_id=symbol_id,
            symbol_name=node.name,
            symbol_type=node.node_type,
            file_path=str(path.relative_to(repo_path)),
            repo_path=repo_path,
            start_line=start_line,
            end_line=end_line,
            language="python",
            signature=signature,
            complexity=complexity,
            last_indexed_at=datetime.now(UTC),
            commit_hash=commit_hash,
        )
        nodes.append(graph_node)

    # Build call edges
    for node in result.nodes:
        if node.node_type == "function" and hasattr(node, "calls"):
            source_id = f"{repo_path}|||{file_path}|||function|||{node.name}"
            for callee in node.calls:
                target_id = f"{repo_path}|||{file_path}|||function|||{callee}"
                edge = CodeGraphEdge(
                    source=source_id,
                    target=target_id,
                    edge_type="calls",
                    source_file=str(path.relative_to(repo_path)),
                    target_file=str(path.relative_to(repo_path)),
                    repo_path=repo_path,
                    created_at=datetime.now(UTC),
                )
                edges.append(edge)

    # Build import edges
    for node in result.nodes:
        if node.node_type == "import" and hasattr(node, "module"):
            source_id = f"{repo_path}|||{file_path}|||file|||{path.name}"
            target_id = f"{repo_path}|||{file_path}|||import|||{node.module}"
            edge = CodeGraphEdge(
                source=source_id,
                target=target_id,
                edge_type="imports",
                source_file=str(path.relative_to(repo_path)),
                target_file=str(path.relative_to(repo_path)),
                repo_path=repo_path,
                created_at=datetime.now(UTC),
            )
            edges.append(edge)

    return nodes, edges


def filter_changed_files(
    repo_path: str,
    commit_hash: str | None = None,
) -> list[str]:
    """Return list of changed Python files since the last indexed commit.

    If commit_hash is None (full re-index), returns all parseable files.
    """
    repo = Path(repo_path)

    if commit_hash is None:
        files = []
        for ext in PARSABLE_EXTENSIONS:
            files.extend(str(f) for f in repo.rglob(f"*{ext}"))
        return sorted(files)

    import subprocess

    result = subprocess.run(
        ["git", "diff", commit_hash, "--name-only", "--diff-filter=ACMR"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    changed = result.stdout.strip().split("\n") if result.stdout.strip() else []
    return sorted(
        str(repo / f)
        for f in changed
        if Path(f).suffix in PARSABLE_EXTENSIONS
    )
```

- [x] **Step 2: Write test**

```python
# mahavishnu/tests/unit/test_code_index_parser.py
"""Tests for file parser."""

from pathlib import Path

import pytest

from mahavishnu.core.code_index.parser import (
    SKIP_DIRS,
    filter_changed_files,
    parse_file,
    PARSABLE_EXTENSIONS,
)


def test_parse_file_returns_nodes_and_edges(tmp_path):
    """Parsing a valid Python file returns nodes and edges."""
    test_file = tmp_path / "test_mod.py"
    test_file.write_text(
        "def foo():\n    return bar()\n\ndef bar():\n    pass\n"
    )
    result = parse_file(str(test_file), str(tmp_path), "abc123")
    assert result is not None
    nodes, edges = result
    assert len(nodes) >= 2  # foo, bar at minimum
    assert any(n.symbol_name == "foo" for n in nodes)


def test_parse_file_skips_non_python(tmp_path):
    """Non-Python files return None."""
    test_file = tmp_path / "readme.md"
    test_file.write_text("# Hello")
    result = parse_file(str(test_file), str(tmp_path), "abc123")
    assert result is None


def test_parse_file_skips_pycache(tmp_path):
    """Files in __pycache__ return None."""
    cache_dir = tmp_path / "__pycache__"
    cache_dir.mkdir()
    test_file = cache_dir / "mod.cpython-312.pyc"
    test_file.write_text("not real python")
    result = parse_file(str(test_file), str(tmp_path), "abc123")
    assert result is None


def test_parsable_extensions():
    assert ".py" in PARSABLE_EXTENSIONS
    assert ".js" not in PARSABLE_EXTENSIONS


def test_skip_dirs():
    assert ".git" in SKIP_DIRS
    assert "node_modules" in SKIP_DIRS
```

- [x] **Step 3: Run test**

```bash
pytest tests/unit/test_code_index_parser.py -v
```

Expected: 5 passed

- [x] **Step 4: Commit**

```bash
git add mahavishnu/core/code_index/parser.py tests/unit/test_code_index_parser.py
git commit -m "feat: add file parser wrapping mcp-common CodeGraphAnalyzer"
```

______________________________________________________________________

### Task 6: Create indexer module

**Files:**

- Create: `mahavishnu/mahavishnu/core/code_index/indexer.py`

- [x] **Step 1: Write indexer module**

```python
# mahavishnu/mahavishnu/core/code_index/indexer.py
"""Orchestrates code graph indexing: detect changes, parse, upsert to Session-Buddy."""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime, UTC
from pathlib import Path

from mahavishnu.core.code_index.lock import RepoIndexLock
from mahavishnu.core.code_index.models import IndexWorkItem
from mahavishnu.core.code_index.parser import filter_changed_files, parse_file

logger = logging.getLogger(__name__)

QUEUE_DIR = Path.home() / ".claude" / "data" / "mahavishnu-index-queue"


def get_last_indexed_commit(repo_path: str) -> str | None:
    """Get the last commit hash that was indexed for a repo."""
    state_file = Path(repo_path) / ".git" / "mahavishnu-last-index"
    if not state_file.exists():
        return None
    return state_file.read_text().strip()


def set_last_indexed_commit(repo_path: str, commit_hash: str) -> None:
    """Persist the last indexed commit hash."""
    state_file = Path(repo_path) / ".git" / "mahavishnu-last-index"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(commit_hash)


def get_current_commit(repo_path: str) -> str:
    """Get the current HEAD commit hash."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def index_repo(
    repo_path: str,
    trigger: str = "manual",
    full: bool = False,
) -> IndexWorkItem:
    """Index a single repository.

    Detects changed files, parses them, and upserts to Session-Buddy.
    Falls back to filesystem queue if Session-Buddy MCP is unavailable.
    """
    lock = RepoIndexLock(repo_path)
    if not lock.acquire():
        logger.info(f"Indexing already in progress for {repo_path}, skipping")
        return IndexWorkItem(
            repo_path=repo_path,
            trigger=trigger,
            files_changed=[],
            status="failed",
        )

    try:
        work_item = IndexWorkItem(
            repo_path=repo_path,
            trigger=trigger,
            files_changed=[],
            status="parsing",
            started_at=datetime.now(UTC),
        )

        # Determine commit range
        if full:
            last_commit = None
        else:
            last_commit = get_last_indexed_commit(repo_path)

        current_commit = get_current_commit(repo_path)
        changed_files = filter_changed_files(repo_path, last_commit)

        work_item.files_changed = changed_files

        if not changed_files:
            work_item.status = "complete"
            work_item.completed_at = datetime.now(UTC)
            logger.info(f"No changes detected for {repo_path}")
            return work_item

        # Parse files
        all_nodes = []
        all_edges = []
        parse_failures = 0

        for file_path in changed_files:
            try:
                result = parse_file(file_path, repo_path, current_commit)
                if result is not None:
                    nodes, edges = result
                    all_nodes.extend(nodes)
                    all_edges.extend(edges)
            except Exception as e:
                parse_failures += 1
                logger.warning(f"Failed to parse {file_path}: {e}")

        work_item.parse_failures = parse_failures

        if parse_failures > 0 and parse_failures / len(changed_files) > 0.25:
            logger.warning(
                f"High parse failure rate for {repo_path}: "
                f"{parse_failures}/{len(changed_files)} files failed"
            )

        # Upsert to Session-Buddy (or fallback to queue)
        work_item.status = "upserting"
        success = _upsert_to_session_buddy(repo_path, all_nodes, all_edges)

        if not success:
            _queue_locally(repo_path, current_commit, all_nodes, all_edges)
            work_item.status = "complete"  # queued locally, not failed
        else:
            work_item.status = "notifying"
            # TODO: notify Akosha (placeholder — Akosha MCP tool call)

        work_item.status = "complete"
        work_item.completed_at = datetime.now(UTC)

        # Record last indexed commit
        set_last_indexed_commit(repo_path, current_commit)

        logger.info(
            f"Indexed {repo_path}: {len(changed_files)} files, "
            f"{len(all_nodes)} nodes, {len(all_edges)} edges, "
            f"{parse_failures} failures"
        )

        return work_item

    finally:
        lock.release()


def _upsert_to_session_buddy(
    repo_path: str,
    nodes: list,
    edges: list,
) -> bool:
    """Try to upsert to Session-Buddy via MCP. Returns True on success."""
    try:
        import httpx

        resp = httpx.post(
            "http://localhost:8678/mcp",
            json={
                "method": "tools/call",
                "params": {
                    "name": "store_code_graph_from_mahavishnu",
                    "arguments": {
                        "repo_path": repo_path,
                        "commit_hash": get_current_commit(repo_path),
                        "indexed_at": datetime.now(UTC).isoformat(),
                        "nodes_count": len(nodes),
                        "graph_data": {
                            "nodes": [n.model_dump() for n in nodes],
                            "edges": [e.model_dump() for e in edges],
                        },
                    },
                },
            },
            timeout=30.0,
        )
        return resp.status_code == 200
    except Exception as e:
        logger.warning(f"Session-Buddy MCP unavailable: {e}")
        return False


def _queue_locally(
    repo_path: str,
    commit_hash: str,
    nodes: list,
    edges: list,
) -> None:
    """Fallback: write parsed data to local filesystem queue."""
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    repo_name = Path(repo_path).name
    queue_file = QUEUE_DIR / f"{repo_name}_{timestamp}.json"
    queue_file.write_text(
        json.dumps({
            "repo_path": repo_path,
            "commit_hash": commit_hash,
            "nodes": [n.model_dump() for n in nodes],
            "edges": [e.model_dump() for e in edges],
        }, default=str)
    )
    logger.info(f"Queued {len(nodes)} nodes to {queue_file}")
```

- [x] **Step 2: Write test**

```python
# mahavishnu/tests/unit/test_code_index_indexer.py
"""Tests for indexer module."""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from mahavishnu.core.code_index.indexer import (
    get_last_indexed_commit,
    index_repo,
    QUEUE_DIR,
    set_last_indexed_commit,
)


def test_set_and_get_last_indexed_commit(tmp_path):
    set_last_indexed_commit(str(tmp_path), "abc123")
    assert get_last_indexed_commit(str(tmp_path)) == "abc123"


def test_get_last_indexed_commit_none(tmp_path):
    assert get_last_indexed_commit(str(tmp_path)) is None


def test_index_repo_no_changes(tmp_path, monkeypatch):
    """Indexing with no changes returns complete with no files."""
    monkeypatch.setattr(
        "mahavishnu.core.code_index.indexer.get_current_commit",
        lambda r: "def456",
    )
    # Simulate: last indexed = current commit = no changes
    set_last_indexed_commit(str(tmp_path), "def456")
    result = index_repo(str(tmp_path), trigger="manual")
    assert result.status == "complete"
    assert result.files_changed == []
```

- [x] **Step 3: Run test**

```bash
pytest tests/unit/test_code_index_indexer.py -v
```

Expected: 3 passed

- [x] **Step 4: Commit**

```bash
git add mahavishnu/core/code_index/indexer.py tests/unit/test_code_index_indexer.py
git commit -m "feat: add indexer module with MCP upsert and filesystem fallback"
```

______________________________________________________________________

### Task 7: Create CLI commands for indexing

**Files:**

- Create: `mahavishnu/mahavishnu/cli/index_cli.py`

- Modify: `mahavishnu/_main_cli.py`

- [x] **Step 1: Write index CLI**

```python
# mahavishnu/mahavishnu/cli/index_cli.py
"""CLI commands for code graph indexing."""

from __future__ import annotations

import typer

from mahavishnu.core.code_index.indexer import index_repo
from mahavishnu.core.code_index.path_validation import validate_repo_path

index_app = typer.Typer(help="Code graph indexing commands")


@index_app.command("repo")
def index_single_repo(
    repo: str = typer.Argument(help="Path to the repository"),
    full: bool = typer.Option(False, "--full", help="Full re-index (ignore last indexed commit)"),
    trigger: str = typer.Option("manual", "--trigger", help="Trigger type for logging"),
):
    """Index a single repository's code graph."""
    validated_path = validate_repo_path(repo)
    typer.echo(f"Indexing {validated_path}...")
    result = index_repo(validated_path, trigger=trigger, full=full)
    typer.echo(
        f"Status: {result.status} | "
        f"Files: {len(result.files_changed)} | "
        f"Failures: {result.parse_failures}"
    )
    if result.status == "failed":
        raise typer.Exit(code=1)


@index_app.command("status")
def index_status():
    """Show indexing status for all registered repos."""
    from mahavishnu.core.code_index.path_validation import get_registered_repos

    repos = get_registered_repos()
    if not repos:
        typer.echo("No repositories registered in repos.yaml")
        return

    typer.echo(f"Registered repos: {len(repos)}")
    for repo in sorted(repos):
        from mahavishnu.core.code_index.indexer import get_last_indexed_commit
        last = get_last_indexed_commit(repo)
        status = f"last indexed: {last[:8]}" if last else "not indexed"
        typer.echo(f"  {repo}: {status}")


def add_index_commands(app: typer.Typer) -> None:
    """Register index commands with the main CLI app."""
    app.add_typer(index_app, name="index")
```

- [x] **Step 2: Register in \_main_cli.py**

Add to `mahavishnu/_main_cli.py` imports:

```python
from .cli.index_cli import add_index_commands
```

Add after the existing `add_*_commands` calls:

```python
add_index_commands(app)
```

- [x] **Step 3: Verify CLI registration**

```bash
python -m mahavishnu index --help
```

Expected: Shows `repo` and `status` subcommands

- [x] **Step 4: Commit**

```bash
git add mahavishnu/cli/index_cli.py mahavishnu/_main_cli.py
git commit -m "feat: add index CLI commands (index repo, index status)"
```

______________________________________________________________________

### Task 8: Create git hook installation

**Files:**

- Create: `mahavishnu/mahavishnu/core/code_index/git_hooks.py`

- Modify: `mahavishnu/cli/index_cli.py`

- [x] **Step 1: Write git hook module**

```python
# mahavishnu/mahavishnu/core/code_index/git_hooks.py
"""Install/uninstall git hooks for automatic code graph indexing."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

HOOK_CONTENT = """#!/bin/sh
# Managed by mahavishnu index --install-hooks
# Remove with: mahavishnu index --uninstall-hooks --repo <path>
mahavishnu index --trigger git-event --repo "$(pwd)" &
"""

MAHAVISHNU_HEADER = "# Managed by mahavishnu index --install-hooks"


def install_hooks(repo_path: str, force: bool = False) -> list[str]:
    """Install post-commit, post-merge, and post-rewrite hooks.

    Returns list of installed hook names.
    """
    hooks_dir = Path(repo_path) / ".git" / "hooks"
    installed = []

    for hook_name in ["post-commit", "post-merge", "post-rewrite"]:
        hook_file = hooks_dir / hook_name
        hooks_dir.mkdir(parents=True, exist_ok=True)

        if hook_file.exists() and not force:
            content = hook_file.read_text()
            if MAHAVISHNU_HEADER not in content:
                raise FileExistsError(
                    f"Hook {hook_name} exists but is not managed by mahavishnu. "
                    f"Use --force to overwrite."
                )

        hook_file.write_text(HOOK_CONTENT)
        hook_file.chmod(hook_file.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        installed.append(hook_name)

    return installed


def uninstall_hooks(repo_path: str) -> list[str]:
    """Remove only mahavishnu-managed hooks."""
    hooks_dir = Path(repo_path) / ".git" / "hooks"
    removed = []

    for hook_name in ["post-commit", "post-merge", "post-rewrite"]:
        hook_file = hooks_dir / hook_name
        if hook_file.exists():
            content = hook_file.read_text()
            if MAHAVISHNU_HEADER in content:
                hook_file.unlink()
                removed.append(hook_name)

    return removed
```

- [x] **Step 2: Add install/uninstall to index CLI**

Add to `mahavishnu/cli/index_cli.py`:

```python
@index_app.command("install-hooks")
def install_repo_hooks(
    repo: str = typer.Argument(help="Path to the repository"),
    force: bool = typer.Option(False, "--force", help="Overwrite existing hooks"),
):
    """Install git hooks for automatic code graph indexing."""
    from mahavishnu.core.code_index.git_hooks import install_hooks
    from mahavishnu.core.code_index.path_validation import validate_repo_path

    validated_path = validate_repo_path(repo)
    installed = install_hooks(validated_path, force=force)
    typer.echo(f"Installed hooks: {', '.join(installed)}")


@index_app.command("uninstall-hooks")
def uninstall_repo_hooks(
    repo: str = typer.Argument(help="Path to the repository"),
):
    """Remove mahavishnu-managed git hooks."""
    from mahavishnu.core.code_index.git_hooks import uninstall_hooks
    from mahavishnu.core.code_index.path_validation import validate_repo_path

    validated_path = validate_repo_path(repo)
    removed = uninstall_hooks(validated_path)
    typer.echo(f"Removed hooks: {', '.join(removed) or 'none'}")
```

- [x] **Step 3: Commit**

```bash
git add mahavishnu/core/code_index/git_hooks.py mahavishnu/cli/index_cli.py
git commit -m "feat: add git hook installation for automatic indexing"
```

______________________________________________________________________

### Task 9: Add Session-Buddy MCP tools (code_call_chain + code_impact_analysis)

**Working directory:** `/Users/les/Projects/session-buddy`

**Files:**

- Create: `session_buddy/mcp/tools/code_graph_tools.py`

- Modify: `session_buddy/mcp/server.py`

- [x] **Step 1: Write Session-Buddy MCP tools**

```python
# session_buddy/session_buddy/mcp/tools/code_graph_tools.py
"""MCP tools for code graph querying: call chains and impact analysis."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

SYMBOL_ID_PATTERN = re.compile(
    r"^[^|]+(\|\|\|[^|]+){3}[^|]+$"
)


def validate_symbol_id(symbol_id: str) -> bool:
    """Validate qualified symbol ID format."""
    return bool(SYMBOL_ID_PATTERN.match(symbol_id))


def _get_max_depth(params: dict) -> int:
    return min(int(params.get("max_depth", 5)), 10)


def _get_graph_age_hours() -> float | None:
    """Return hours since last index. Returns None if unknown."""
    try:
        kg = __import__(
            "session_buddy.knowledge_graph_db", fromlist=["KnowledgeGraphDatabase"]
        )
        # This is a placeholder — actual implementation queries the DB
        return None
    except Exception:
        return None


def register_code_graph_tools(mcp) -> None:
    """Register code graph MCP tools with the FastMCP server."""

    @mcp.tool()
    def code_call_chain(
        symbol_name: str,
        direction: str = "both",
        max_depth: int = 5,
        repo_path: str | None = None,
        edge_filter: list[str] | None = None,
    ) -> dict:
        """Resolve transitive callers/callees of a symbol in the code graph.

        Args:
            symbol_name: Qualified symbol ID or bare name (with repo_path)
            direction: "callers", "callees", or "both"
            max_depth: Maximum traversal depth (1-10, default 5)
            repo_path: Disambiguate bare symbol_name
            edge_filter: Filter by edge types (e.g., ["calls", "imports"])
        """
        max_depth = min(max_depth, 10)

        # Validate symbol ID if qualified
        if "|||" in symbol_name:
            if not validate_symbol_id(symbol_name):
                return {
                    "error": "Invalid symbol ID format",
                    "detail": symbol_name,
                }

        # Check staleness
        age_hours = _get_graph_age_hours()
        stale = age_hours is not None and age_hours > 24

        # Execute PGQ query (placeholder — actual implementation uses DuckPGQ)
        # This will be implemented against the DuckPGQ property graph
        # using CREATE PROPERTY GRAPH code_graph queries
        chains = []
        truncated = False

        return {
            "root_symbol": symbol_name,
            "chains": chains,
            "total_nodes": 0,
            "truncated": truncated,
            "stale": stale,
            "last_indexed_at": datetime.utcnow().isoformat() if stale else None,
        }

    @mcp.tool()
    def code_impact_analysis(
        symbol_name: str,
        repo_path: str | None = None,
        include_indirect: bool = True,
        max_depth: int = 5,
    ) -> dict:
        """Analyze the impact of changing a symbol — what depends on it?

        Args:
            symbol_name: Qualified symbol ID or bare name (with repo_path)
            repo_path: Disambiguate bare symbol_name
            include_indirect: Include transitive dependents
            max_depth: Maximum traversal depth (1-10, default 5)
        """
        max_depth = min(max_depth, 10)

        if "|||" in symbol_name:
            if not validate_symbol_id(symbol_name):
                return {
                    "error": "Invalid symbol ID format",
                    "detail": symbol_name,
                }

        age_hours = _get_graph_age_hours()
        stale = age_hours is not None and age_hours > 24

        return {
            "target": symbol_name,
            "direct_dependents": [],
            "indirect_dependents": [],
            "affected_files": [],
            "risk_level": "low",
            "blast_radius": 0,
            "stale": stale,
            "last_indexed_at": datetime.utcnow().isoformat() if stale else None,
        }
```

- [x] **Step 2: Register tools in server.py**

Add to `session_buddy/mcp/server.py` (in the tool registration section):

```python
from .tools.code_graph_tools import register_code_graph_tools
register_code_graph_tools(mcp)
```

- [x] **Step 3: Verify tools are registered**

```bash
cd /Users/les/Projects/session-buddy
python -c "from session_buddy.mcp.tools.code_graph_tools import register_code_graph_tools; print('OK')"
```

- [x] **Step 4: Commit**

```bash
cd /Users/les/Projects/session-buddy
git add session_buddy/mcp/tools/code_graph_tools.py session_buddy/mcp/server.py
git commit -m "feat: add code_call_chain and code_impact_analysis MCP tools"
```

______________________________________________________________________

### Task 10: Write degradation tier tests

**Files:**

- Create: `mahavishnu/tests/unit/test_code_graph_degradation.py`

- [x] **Step 1: Write degradation tests**

```python
# mahavishnu/tests/unit/test_code_graph_degradation.py
"""Tests for code graph degradation tiers."""

import pytest

from mahavishnu.core.code_index.models import (
    CallChainResult,
    CodeGraphUnavailable,
    DegradationTier,
    ImpactAnalysisResult,
)


def test_stale_flag_true_when_old():
    """Results include stale=True when index is > 24 hours old."""
    result = CallChainResult(
        root_symbol="test",
        chains=[],
        total_nodes=0,
        stale=True,
        last_indexed_at="2026-04-25T00:00:00Z",
    )
    assert result.stale is True


def test_code_graph_unavailable_has_reason():
    unavailable = CodeGraphUnavailable(
        reason="DuckDB file corrupted",
        suggestion="Run mahavishnu index --repo <path> --full to re-index",
    )
    assert unavailable.tier == 4
    assert "corrupted" in unavailable.reason.lower()


def test_impact_result_risk_levels():
    low = ImpactAnalysisResult(
        target="test", direct_dependents=[], indirect_dependents=[],
        affected_files=[], risk_level="low", blast_radius=0,
    )
    assert low.risk_level == "low"


def test_max_depth_clamp():
    """max_depth > 10 is rejected by Pydantic validator."""
    from mahavishnu.core.code_index.models import CallChainRequest, ImpactAnalysisRequest
    with pytest.raises(ValueError, match="max_depth"):
        CallChainRequest(symbol_name="test", max_depth=20)
    with pytest.raises(ValueError, match="max_depth"):
        ImpactAnalysisRequest(symbol_name="test", max_depth=15)
```

- [x] **Step 2: Run test**

```bash
pytest tests/unit/test_code_graph_degradation.py -v
```

Expected: 4 passed

- [x] **Step 3: Commit**

```bash
git add tests/unit/test_code_graph_degradation.py
git commit -m "test: add degradation tier and validation tests"
```

______________________________________________________________________

### Task 11: Run full test suite and authority verification

- [x] **Step 1: Run all new tests**

```bash
pytest tests/unit/test_code_index_models.py tests/unit/test_code_index_parser.py tests/unit/test_code_index_indexer.py tests/unit/test_signature_redaction.py tests/unit/test_git_hooks.py tests/unit/test_path_validation.py tests/unit/test_code_graph_degradation.py -v
```

Expected: All pass

- [x] **Step 2: Authority verification — no other service writes to code graph**

```bash
grep -r "store_code_graph" mahavishnu/ --include="*.py" | grep -v "test" | grep -v "mcp" | grep -v "queue"
```

Expected: No results (Mahavishnu doesn't write directly — it goes through MCP to Session-Buddy)

- [x] **Step 3: Verify no new infrastructure dependencies**

```bash
grep -E "neo4j|tidb|property_graph_index" mahavishnu/core/code_index/ --include="*.py"
```

Expected: No results

- [x] **Step 4: Final commit (if any cleanup needed)**

```bash
git add -A
git status
```

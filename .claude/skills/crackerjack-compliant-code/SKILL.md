______________________________________________________________________

## name: crackerjack-compliant-code description: >- Use when writing or modifying Python code to ensure it passes crackerjack quality gates on the first run. Encodes ruff, mypy strict, bandit, complexipy, and refurb rules preventively so fix-after-the-fact cycles are eliminated. Invoke before writing any new Python function, class, or module.

# Crackerjack-Compliant Code

## Available MCP Servers

| Server | Port | Context Mode | Relevant Tools | Default Timeout |
|--------|------|-------------|---------------|----------------|
| crackerjack | 8676 | summary | mcp\_\_crackerjack\_\_crackerjack_run, mcp\_\_crackerjack\_\_smart_error_analysis, mcp\_\_crackerjack\_\_get_comprehensive_status | 120s |

## Overview

Crackerjack runs 11 concurrent adapters. This skill encodes their exact thresholds
so code passes on the first run rather than requiring a fix loop.

**Core principle:** Internalize the rules before writing. Verify with `crackerjack run`
after writing. Never commit until the run reports zero failures.

______________________________________________________________________

## Before Writing — Rules to Internalize

### File Header (every Python file)

Every file must start with:

```python
from __future__ import annotations
```

This must be the first non-comment line. It enables PEP 563 postponed annotation
evaluation, required for forward references and circular type hints.

### Formatting (ruff format)

- Line length: **100 chars max**
- String quotes: **double quotes**
- Indent: **4 spaces** (never tabs)
- Trailing comma on multi-line structures: required

### Imports (ruff I — isort)

Order: stdlib → third-party → first-party (`mahavishnu`)

```python
from __future__ import annotations

import json
from pathlib import Path

import typer
import yaml

from mahavishnu.core.config import MahavishnuSettings
```

No wildcard imports. No unused imports (creosote/vulture will flag them).

### Naming (ruff N — PEP 8)

| Kind | Convention | Example |
|------|-----------|---------|
| Functions, variables, modules | `snake_case` | `load_config`, `max_workers` |
| Classes | `PascalCase` | `WorkerPool`, `DriftReport` |
| Module-level constants | `SCREAMING_SNAKE_CASE` | `DEFAULT_PORT = 8680` |
| Type aliases | `PascalCase` | `RepoMap = dict[str, Path]` |

### Type Annotations (mypy strict)

Every function must have full annotations — no bare untyped parameters.

```python
# fails mypy (disallow_untyped_defs)
def process(items, count):
    ...

# correct
def process(items: list[str], count: int) -> dict[str, int]:
    ...
```

**Annotation rules:**

- Use `X | None` not `Optional[X]` (ruff UP007)
- Use `list[int]` not `List[int]` (ruff UP006)
- Use `dict[str, Any]` not `Dict[str, Any]`
- Put forward refs or circular imports under `TYPE_CHECKING`
- Async: annotate the inner return type, not the coroutine

```python
async def fetch_status(url: str) -> dict[str, str]:
    ...
```

- `ClassVar` for class-level attributes not set in `__init__`

```python
from typing import ClassVar

class Adapter:
    registry: ClassVar[dict[str, type]] = {}
```

### Security (bandit)

| Pattern | Rule | Fix |
|---------|------|-----|
| `assert x > 0` | B101 | `if x <= 0: raise ValueError(...)` |
| `subprocess.run(cmd, shell=True)` | B603/B604 | Use list args: `["cmd", "arg"]` |
| `random.random()` for secrets | B311 | Use `secrets.token_hex()` |
| Hardcoded password/token in source | B105/B106 | Load from env var |

**Never use `assert` in production code.** It is disabled by Python's `-O` flag
and bandit flags every instance as B101. Use explicit `if` + `raise` instead.

### Complexity (complexipy ≤15, ruff pylint)

| Metric | Limit |
|--------|-------|
| Cyclomatic complexity per function | **15** |
| Parameters per function | **10** |
| Branches per function | **15** |
| Return statements per function | **6** |
| Statements per function | **55** |
| Line length | **100** |

When a function approaches the limit, extract a helper rather than pushing further:

```python
# complex — deeply nested conditions hitting complexity 18
def validate(config: dict[str, Any]) -> bool:
    if config.get("host"):
        if config["host"].startswith("http"):
            if len(config["host"]) < 200:
                ...  # more nesting

# correct — extract focused helpers
def _validate_host(host: str) -> bool:
    return host.startswith(("http://", "https://")) and len(host) < 200

def validate(config: dict[str, Any]) -> bool:
    if not _validate_host(config.get("host", "")):
        return False
    ...
```

### Modern Python (ruff UP, refurb)

```python
# old patterns (ruff will flag these)
from typing import Optional, Union, List, Dict
x: Optional[str] = None
y: Union[int, str] = 0
items: List[str] = []
result = "Hello %s" % name
result = "Hello {}".format(name)

# correct modern equivalents
x: str | None = None
y: int | str = 0
items: list[str] = []
result = f"Hello {name}"
```

Use comprehensions over `map()`/`filter()` (ruff C4):

```python
# ruff C4 prefers comprehension
names = list(map(lambda x: x.name, users))

# correct
names = [u.name for u in users]
```

Use `pathlib.Path` over `os.path`.

### No Dead Code (creosote, vulture)

- Remove all unused imports immediately after writing
- No commented-out code blocks in committed code
- No unreachable branches or stub functions with only `pass`

______________________________________________________________________

## Complexity Budget Cheatsheet

When writing a function, stay within all of these at once:

```
≤100 chars / line    ≤10 parameters    ≤15 branches
complexity ≤15       ≤6 return points  ≤55 statements
```

If any limit is hit, **stop and refactor first**.

______________________________________________________________________

## Type Annotation Quick-Reference

```python
# primitives
x: int
y: float
z: str
flag: bool
data: bytes

# collections (lowercase, no typing module needed)
names: list[str]
config: dict[str, Any]
coords: tuple[float, float]
unique_ids: set[int]

# nullable
value: str | None = None

# callable
handler: Callable[[int, str], bool]

# structured data — prefer dataclass over plain dict
from dataclasses import dataclass, field

@dataclass
class Config:
    host: str
    port: int = 8680
    tags: list[str] = field(default_factory=list)
```

______________________________________________________________________

## After Writing — Verification

### Step 1: Run crackerjack

Via MCP (preferred when server is available):

```
mcp__crackerjack__crackerjack_run
```

Via CLI:

```bash
crackerjack run
```

### Step 2: If failures, diagnose

```
mcp__crackerjack__smart_error_analysis
mcp__crackerjack__get_comprehensive_status
```

### Step 3: Fix and re-run

Fix **all** reported issues before moving to the next task. Quality fixes are not
optional — crackerjack enforces a ratchet. Skipping compounds debt.

### Step 4: Gate on clean

A passing `crackerjack run` is the definition of done for any Python code change.

______________________________________________________________________

## Common First-Run Failures

| Failure | Cause | Fix |
|---------|-------|-----|
| `mypy: missing return type annotation` | Missing `-> ReturnType` | Add return annotation |
| `ruff: E501 line too long` | Line > 100 chars | Break with `\` or parens |
| `bandit: B101 assert detected` | `assert` in production | Replace with `if` + `raise` |
| `complexipy: complexity 18 > 15` | Too many branches | Extract helpers |
| `ruff: UP006 use list not List` | Old typing style | Remove `from typing import List` |
| `ruff: I001 imports unsorted` | Wrong order | Run `ruff check --fix` |
| `mypy: incompatible return type` | Return type mismatch | Fix annotation or logic |
| `creosote: unused import` | Import not used | Delete the import |

## Related Skills

- `run-quality-checks` — Full crackerjack execution guide and CI/CD integration
- `superpowers:test-driven-development` — Write tests before code
- `superpowers:verification-before-completion` — Validate before claiming done

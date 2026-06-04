______________________________________________________________________

## name: python-pro description: >- Expert Python developer for modern Python 3.13+ with type safety and async. Ecosystem: mcp\_\_crackerjack\_\_crackerjack_run (pytest quality gates), mcp\_\_akosha\_\_search_code_patterns (cross-repo Python patterns), mcp\_\_mahavishnu\_\_pool_route_execute (distributed test execution). model: sonnet

## Code Standards

All Python code must pass crackerjack quality gates on the first run. Internalize
these rules before writing; verify with `mcp__crackerjack__crackerjack_run` after.

### Every file starts with

```python
from __future__ import annotations
```

### Formatting (ruff format, line-length = 100)

- Max line length: **100 chars**
- String quotes: **double quotes**
- Indent: **4 spaces**
- Trailing comma required on multi-line structures

### Imports (ruff I — isort order)

```
stdlib → third-party → first-party (mahavishnu)
```

No wildcard imports. No unused imports (creosote/vulture flag them).

### Naming (ruff N — PEP 8)

| Kind | Convention |
|------|-----------|
| Functions, variables | `snake_case` |
| Classes | `PascalCase` |
| Module-level constants | `SCREAMING_SNAKE_CASE` |
| Type aliases | `PascalCase` |

### Type Annotations (mypy strict — disallow_untyped_defs)

Every function requires full annotations — no bare untyped parameters.

```python
# wrong
def process(items, count):
    ...

# correct
def process(items: list[str], count: int) -> dict[str, int]:
    ...
```

Use modern union syntax:

```python
x: str | None = None          # not Optional[str]
y: int | str = 0              # not Union[int, str]
items: list[str] = []         # not List[str]
config: dict[str, Any] = {}   # not Dict[str, Any]
result = f"Hello {name}"      # not "Hello %s" % name
```

Async — annotate the inner return type:

```python
async def fetch(url: str) -> dict[str, str]: ...
```

Use `ClassVar` for class-level attributes not set in `__init__`.

### Security (bandit)

- **Never use `assert` in production code** (B101 — disabled by `-O` flag)
  - Replace: `if x <= 0: raise ValueError("...")`
- Shell commands: use list args, never `shell=True` (B603/B604)
- Secrets: load from env vars, never hardcode (B105/B106)
- Randomness: use `secrets` module, not `random` (B311)

### Complexity (complexipy ≤ 15, ruff pylint)

| Metric | Limit |
|--------|-------|
| Cyclomatic complexity | **15** |
| Parameters | **10** |
| Branches | **15** |
| Return statements | **6** |
| Statements | **55** |

When a function approaches a limit, extract a focused helper rather than pushing further.

### Dead Code (creosote, vulture)

Remove all unused imports immediately. No commented-out code blocks. No stub
functions with only `pass` in non-abstract code.

### Verification Gate

After writing or modifying Python code, call:

```
mcp__crackerjack__crackerjack_run
```

A passing run is the definition of done. Never commit until it reports zero failures.

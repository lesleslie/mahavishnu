---
status: draft
role: implementation
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
topic: track4-turbovec
---

# Track 4 — TurboVec Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add TurboVec as an explicit in-memory vector store fallback in the LlamaIndex adapter, replacing the implicit `SimpleVectorStore` path when OpenSearch is unavailable. Only the `except` block in `llamaindex_adapter_impl.py` and `pyproject.toml` are touched.

**Architecture:** Three-value `_vector_backend` string: `"opensearch"` (OpenSearch available), `"turbovec"` (turbovec installed), `"memory-implicit"` (neither). The `except` block tries `from turbovec.integrations.llamaindex import TurboVec` and falls into `"memory-implicit"` on `ImportError`. No new files created.

**Tech Stack:** `turbovec[llama-index]~=0.1` (new `[vector]` dep group), lazy/guarded import inside `except`, Python 3.13.

## Global Constraints

- `from __future__ import annotations` as first non-comment line (existing file: check it has this)
- Oneiric logger pattern — the existing file uses stdlib `logger = __import__("logging").getLogger(__name__)` inside the except block; do NOT fix this (out of scope, separate PR)
- No `assert` in production code
- Lazy import pattern: `from turbovec.integrations.llamaindex import TurboVec` inside the except block only, with `# noqa: PLC0415` comment
- `~=` compatible release pin for turbovec
- Add `turbovec` to `[tool.creosote] exclude_deps` in `pyproject.toml`
- Scope: ONLY the `except` block (lines ~368-376) and `pyproject.toml`

______________________________________________________________________

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `pyproject.toml` | Modify | Add `[vector]` dep group + creosote exclusion |
| `mahavishnu/engines/llamaindex_adapter_impl.py` | Modify | Expand `except` block for TurboVec fallback |
| `tests/unit/engines/test_turbovec_fallback.py` | Create | 3 unit tests for the 3 `_vector_backend` values |

______________________________________________________________________

## Task 1: pyproject.toml Changes

**Files:**

- Modify: `pyproject.toml`

**Interfaces:**

- Produces: `[dependency-groups] vector = ["turbovec[llama-index]~=0.1"]`

- Produces: `"turbovec"` in `[tool.creosote] exclude_deps`

- [ ] **Step 1: Add `[vector]` dependency group**

In `pyproject.toml`, after the `automation-vision` dep group (around line 164), add:

```toml
# Optional: Explicit in-memory vector store (TurboVec)
vector = [
    "turbovec[llama-index]~=0.1",
]
```

- [ ] **Step 2: Add turbovec to creosote exclude_deps**

In `[tool.creosote]`, in the `exclude_deps` list, add:

```toml
    "turbovec",
```

- [ ] **Step 3: Verify pyproject.toml parses cleanly**

```bash
cd /Users/les/Projects/mahavishnu && python -c "import tomllib; tomllib.loads(open('pyproject.toml').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "feat(deps): add [vector] dep group with turbovec[llama-index]~=0.1"
```

______________________________________________________________________

## Task 2: LlamaIndex Adapter Fallback + Tests

**Files:**

- Modify: `mahavishnu/engines/llamaindex_adapter_impl.py` (lines ~368-376 only)
- Create: `tests/unit/engines/test_turbovec_fallback.py`

**Interfaces:**

- Consumes: `self.vector_store` and `self._vector_backend` set earlier in `_setup_vector_store` method
- Produces: `self._vector_backend in ("opensearch", "turbovec", "memory-implicit")` (exhaustive)

The current code at lines 368-376 (`except Exception as e:` block) is:

```python
        except Exception as e:
            logger = __import__("logging").getLogger(__name__)
            logger.debug(f"OpenSearch vector store unavailable: {e}")
            logger.info(
                "Using in-memory vector store (install opensearch-knn plugin for persistence)"
            )
            self.vector_store = None  # type: ignore[assignment]
            self._vector_backend = "memory"
```

Replace with:

```python
        except Exception as e:
            logger = __import__("logging").getLogger(__name__)
            logger.debug(f"OpenSearch vector store unavailable: {e}")
            try:
                from turbovec.integrations.llamaindex import TurboVec  # noqa: PLC0415

                self.vector_store = TurboVec()
                self._vector_backend = "turbovec"
                logger.info(
                    "Using TurboVec in-memory vector store "
                    "(install turbovec[llama-index] for explicit in-memory store)"
                )
            except ImportError:
                self.vector_store = None  # type: ignore[assignment]
                self._vector_backend = "memory-implicit"
                logger.info(
                    "Using LlamaIndex implicit SimpleVectorStore "
                    "(install turbovec[llama-index] for explicit in-memory store)"
                )
```

- [ ] **Step 1: Create test directory and write failing tests**

```bash
mkdir -p /Users/les/Projects/mahavishnu/tests/unit/engines
touch /Users/les/Projects/mahavishnu/tests/unit/engines/__init__.py
```

Create `tests/unit/engines/test_turbovec_fallback.py`:

```python
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _make_adapter() -> "LlamaIndexAdapter":  # noqa: UP037
    """Return a LlamaIndexAdapter with a minimal mock config."""
    from mahavishnu.engines.llamaindex_adapter_impl import LlamaIndexAdapter

    mock_config = MagicMock()
    mock_config.llamaindex = MagicMock()
    mock_config.llamaindex.opensearch_url = "http://localhost:9200"
    mock_config.llamaindex.opensearch_index = "test-index"
    adapter = LlamaIndexAdapter.__new__(LlamaIndexAdapter)
    adapter._config = mock_config
    adapter.vector_store = None
    adapter._vector_backend = "unset"
    return adapter


@pytest.mark.unit
async def test_vector_backend_is_opensearch_when_opensearch_available() -> None:
    """When OpenSearch connects successfully, _vector_backend = 'opensearch'."""
    adapter = _make_adapter()

    mock_store = MagicMock()

    with patch(
        "mahavishnu.engines.llamaindex_adapter_impl.OpensearchVectorStore",
        return_value=mock_store,
    ):
        await adapter._setup_vector_store()

    assert adapter._vector_backend == "opensearch"
    assert adapter.vector_store is mock_store


@pytest.mark.unit
async def test_vector_backend_is_turbovec_when_opensearch_unavailable_and_turbovec_installed() -> None:
    """When OpenSearch fails and turbovec is installed, _vector_backend = 'turbovec'."""
    adapter = _make_adapter()
    mock_turbo = MagicMock()

    with patch(
        "mahavishnu.engines.llamaindex_adapter_impl.OpensearchVectorStore",
        side_effect=ConnectionError("OpenSearch down"),
    ), patch.dict(
        "sys.modules",
        {
            "turbovec": MagicMock(),
            "turbovec.integrations": MagicMock(),
            "turbovec.integrations.llamaindex": MagicMock(TurboVec=lambda: mock_turbo),
        },
    ):
        await adapter._setup_vector_store()

    assert adapter._vector_backend == "turbovec"
    assert adapter.vector_store is not None


@pytest.mark.unit
async def test_vector_backend_is_memory_implicit_when_neither_available() -> None:
    """When OpenSearch fails and turbovec is absent, _vector_backend = 'memory-implicit'."""
    adapter = _make_adapter()

    with patch(
        "mahavishnu.engines.llamaindex_adapter_impl.OpensearchVectorStore",
        side_effect=ConnectionError("OpenSearch down"),
    ), patch.dict("sys.modules", {"turbovec": None}):
        await adapter._setup_vector_store()

    assert adapter._vector_backend == "memory-implicit"
    assert adapter.vector_store is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/les/Projects/mahavishnu && python -m pytest tests/unit/engines/test_turbovec_fallback.py -v 2>&1 | head -25
```

Expected: Tests collect but fail because `_vector_backend` doesn't have `"turbovec"` or `"memory-implicit"` as a possible value yet.

- [ ] **Step 3: Read the exact lines to modify**

```bash
cd /Users/les/Projects/mahavishnu && grep -n "memory" mahavishnu/engines/llamaindex_adapter_impl.py | head -20
```

Use this to confirm the exact line numbers of the `except` block before editing.

- [ ] **Step 4: Apply the change to `llamaindex_adapter_impl.py`**

Open `mahavishnu/engines/llamaindex_adapter_impl.py`. In the `except Exception as e:` block (the one following the OpenSearch vector store setup, currently setting `self._vector_backend = "memory"`), replace the existing body with:

```python
        except Exception as e:
            logger = __import__("logging").getLogger(__name__)
            logger.debug(f"OpenSearch vector store unavailable: {e}")
            try:
                from turbovec.integrations.llamaindex import TurboVec  # noqa: PLC0415

                self.vector_store = TurboVec()
                self._vector_backend = "turbovec"
                logger.info(
                    "Using TurboVec in-memory vector store "
                    "(install turbovec[llama-index] for explicit in-memory store)"
                )
            except ImportError:
                self.vector_store = None  # type: ignore[assignment]
                self._vector_backend = "memory-implicit"
                logger.info(
                    "Using LlamaIndex implicit SimpleVectorStore "
                    "(install turbovec[llama-index] for explicit in-memory store)"
                )
```

- [ ] **Step 5: Update the downstream `if self.vector_store:` check**

In the `_build_index` method (around lines 670-682), the else branch currently reads `"memory"`. Update its log message to match:

Find:

```python
        else:
            index = VectorStoreIndex(nodes)
```

The context comment or log before this may say `"in-memory"`. Verify it still works with the renamed `"memory-implicit"` backend — the code branch itself doesn't need to change (it checks `if self.vector_store:`), only any log messages that reference `"memory"` need to reflect the new name. Check with:

```bash
grep -n '"memory"' mahavishnu/engines/llamaindex_adapter_impl.py
```

If any log message says `backend = "memory"`, update it to `"memory-implicit"`.

- [ ] **Step 6: Run tests**

```bash
cd /Users/les/Projects/mahavishnu && python -m pytest tests/unit/engines/test_turbovec_fallback.py -v
```

Expected: 3 tests PASS

- [ ] **Step 7: Check for any test that asserts `_vector_backend == "memory"` (old value)**

```bash
grep -rn '"memory"' tests/ | grep -v "memory-implicit" | grep "vector_backend"
```

If any match: update them to `"memory-implicit"`.

- [ ] **Step 8: Verify no regressions**

```bash
cd /Users/les/Projects/mahavishnu && python -m pytest tests/unit/engines/ -v
```

Expected: all PASS

- [ ] **Step 9: Commit**

```bash
git add mahavishnu/engines/llamaindex_adapter_impl.py \
        tests/unit/engines/__init__.py \
        tests/unit/engines/test_turbovec_fallback.py
git commit -m "feat(llamaindex): add TurboVec fallback when OpenSearch unavailable; rename memory backend to memory-implicit"
```

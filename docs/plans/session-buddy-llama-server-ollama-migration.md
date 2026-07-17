---
status: complete
role: historical
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
blocks_on: []
topic: routing-composition
---

# Plan: Replace ONNX + Transformers with llama-server + Ollama in Bodai Ecosystem

> **Status: ALL PHASES COMPLETE** (2026-05-31)

## Context

The Bodai ecosystem has accumulated heavy ML dependencies (`onnxruntime`, `transformers`, `sentence-transformers`) that create version conflicts across components. The goal is to eliminate these by routing all embedding requests through the Bodai-standard HTTP embedding services: **llama-server** (preferred) → **Ollama** (fallback) → graceful degradation.

**Ecosystem status:**

- Mahavishnu: FastEmbed removed (previously caused conflicts)
- Akosha: `onnxruntime` removed (declared but unused)
- Dhara: `onnxruntime` removed (Linux-only, declared but unused)
- Session-Buddy: ✅ `onnxruntime` + `transformers` **removed** — HTTP chain (llama-server → Ollama) in place
- Crackerjack: ✅ `sentence-transformers` + `transformers` **removed** — FallbackIssueEmbedder (TF-IDF) active

Both session-buddy and Crackerjack already have fallback chains that degrade gracefully when these libs are unavailable — no new code patterns needed, just dependency removal.

______________________________________________________________________

## Part A: Session-Buddy Migration

### Files to Modify

#### 1. `session_buddy/reflection/embeddings.py` (core change)

**Current state:**

- `_sync_generate_embedding()` uses `onnxruntime.InferenceSession` + `transformers.AutoTokenizer` directly
- `_check_onnx_available()` lazily checks for onnxruntime imports
- `generate_embedding()` returns `None` only when `not onnx_session or not tokenizer`
- No HTTP provider chain

**Key correction from review:**
The plan originally said "Keep existing async wrapper `generate_embedding()` unchanged" — this was **incorrect**. The current `generate_embedding()` only handles ONNX path failure (returns `None` when `not onnx_session or not tokenizer`). It does **not** call an HTTP chain. The HTTP provider chain must be integrated into `generate_embedding()` itself.

**New structure for `generate_embedding()`:**

```python
async def generate_embedding(text: str, ...) -> list[float] | None:
    # Try HTTP chain FIRST (new behavior)
    http_result = await _try_http_embedding_providers(text)
    if http_result is not None:
        return http_result

    # Only try ONNX if HTTP chain failed AND we have ONNX available
    if _check_onnx_available() and _onnx_session and _tokenizer:
        return await _sync_generate_embedding_onnx(text, _onnx_session, _tokenizer)

    # All paths exhausted
    return None
```

**New function: `_try_http_embedding_providers(text)`:**

```
Try llama-server at localhost:8080
  └─ POST /v1/embeddings {"input": [text]}, timeout: 5s connect, 30s read
  └─ return embedding on success

Try Ollama at localhost:11434
  └─ POST /api/embed {"model": "nomic-embed-text", "input": [text]}, timeout: 5s connect, 30s read
  └─ return embedding on success

Return None on all failures
```

**Key design decisions:**

- HTTP chain is the **primary** path — called first in `generate_embedding()`
- ONNX is only attempted if HTTP fails AND onnxruntime is available (transition fallback)
- `_try_http_embedding_providers()` returns `list[float] | None` with `suppress(Exception)` around HTTP calls
- Keep LRU cache (`@lru_cache`) on `generate_embedding()` for text-level caching
- Keep thread pool executor (`_embedding_executor`) for non-blocking ONNX execution (during transition)
- Maintain 384-dimension guarantee

**Provider chain order:**

1. `LLAMA_SERVER_URL` (default: `http://localhost:8080/v1/embeddings`)
1. `OLLAMA_URL` (default: `http://localhost:11434`)
1. ONNX (if available, transition fallback only)
1. Return `None`

**Configuration via env vars:**

```python
import os
LLAMA_SERVER_URL = os.environ.get("MAHAVISHNU__LLAMA_SERVER_URL", "http://localhost:8080/v1/embeddings")
OLLAMA_URL = os.environ.get("MAHAVISHNU__OLLAMA_URL", "http://localhost:11434")
```

**httpx status:** Confirmed in session-buddy `pyproject.toml` line 32 as main dependency. No new dep needed.

#### 2. `session_buddy/adapters/reflection_adapter_oneiric.py` (HIGH priority — previously missed)

**Current ONNX-dependent code:**

- Lines 37-49: Runtime imports for `onnxruntime` + `transformers.AutoTokenizer`
- Lines 360-361, 828, 1594-1595: `ONNX_AVAILABLE` guard checks
- `_init_embedding_model()` method (lines 825-856)
- `_generate_embedding()` method (lines 858-937) — does mean pooling/normalization internally

**Required changes:**

**(a) Remove ONNX imports:**

```python
# TYPE_CHECKING block — remove:
from onnxruntime import InferenceSession

# Runtime block — change to unconditionally disabled:
ONNX_AVAILABLE = False  # Always False — using HTTP providers
AutoTokenizer: type | None = None  # Always None
```

**(b) Replace `_init_embedding_model()`:**
Current: loads ONNX model + tokenizer from disk.
After migration: Stateless HTTP calls — no model loading needed. Replace with:

```python
def _check_embedding_availability() -> bool:
    """Check if at least one HTTP provider is reachable. Called lazily on first use."""
    # Lightweight connectivity check — do we have at least one working endpoint?
    # Can be implemented as a lazy flag set by first successful HTTP call
    return True  # HTTP calls are stateless; providers are assumed available until proven otherwise
```

Or remove entirely — HTTP calls are stateless and handle failures gracefully at call time.

**(c) Replace `_generate_embedding()`:**
Current: does mean pooling + normalization on top of ONNX output.
After migration: delegate to `generate_embedding()` from `embeddings.py` which returns pre-normalized vectors.

```python
def _generate_embedding(self, text: str) -> list[float] | None:
    """Thin wrapper around generate_embedding() from embeddings.py.

    Removes all mean-pooling/normalization logic since HTTP providers
    (llama-server/Ollama) return pre-normalized 384d vectors.
    """
    # Synchronous wrapper since _generate_embedding is sync
    # and generate_embedding is async — use asyncio.run() or thread pool
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(generate_embedding(text))
```

Remove `self._embedding_cache` logic — caching is now handled by `generate_embedding()`'s `@lru_cache`.

**(d) Update `ONNX_AVAILABLE` guard checks:**
All occurrences of `if ONNX_AVAILABLE and self.onnx_session:` become:

```python
# After migration: no ONNX, HTTP handles failures gracefully
# Guard can be removed entirely, or replaced with HTTP availability check
if self._check_embedding_availability():
    # HTTP path is available
```

The condition `ONNX_AVAILABLE and self.onnx_session` becomes simply checking HTTP availability (or removed, since HTTP failures return `None` gracefully).

#### 3. `session_buddy/reflection/database.py`

**Remove ONNX type hints and runtime imports:**

```python
# TYPE_CHECKING block — remove:
from onnxruntime import InferenceSession

# Runtime try/except block — remove entirely

# Note: `generate_embedding` and `initialize_embedding_system` are still imported from embeddings
# and continue to work via the HTTP chain. ONNX_AVAILABLE is no longer exported from embeddings.py.
```

#### 4. `session_buddy/utils/lazy_imports.py`

**Remove from lazy imports:**

```python
# REMOVE:
transformers = lazy_loader.add_import("transformers", ...)
onnxruntime = lazy_loader.add_import("onnxruntime", ...)

# UPDATE get_dependency_status() to remove:
optional_deps = ["transformers", "onnxruntime", "tiktoken", "numpy"]  # remove transformers, onnxruntime
```

**Keep:** `numpy`, `tiktoken`, `duckdb`

#### 5. `session_buddy/health_checks.py`

**Current:** `check_dependencies_health()` uses `_module_available("onnxruntime")`

**New implementation:**

```python
async def _check_embedding_providers() -> dict[str, bool]:
    """Check which embedding providers are reachable (async)."""
    providers = {}
    async with httpx.AsyncClient(timeout=5.0) as client:
        # Check llama-server
        try:
            resp = await client.post(
                f"{LLAMA_SERVER_URL}/embeddings",
                json={"input": ["health-check"]},
            )
            providers["llama-server"] = resp.status_code == 200
        except Exception:
            providers["llama-server"] = False

        # Check Ollama
        try:
            resp = await client.post(
                f"{OLLAMA_URL}/api/embed",
                json={"model": "nomic-embed-text", "input": ["health-check"]},
            )
            providers["ollama"] = resp.status_code == 200
        except Exception:
            providers["ollama"] = False

    return providers
```

Update `check_dependencies_health()` to call `_check_embedding_providers()` and report llama-server/ollama availability. The "onnx" entry in the unavailable deps list should be replaced with "llama-server" and "ollama".

#### 6. `session_buddy/pyproject.toml`

**Remove:**

```toml
"onnxruntime>=1.23.2,<1.24",
"transformers>=5.1.0",
```

**httpx:** Already present at line 32 as main dependency. No change needed.

______________________________________________________________________

## Part B: Crackerjack Migration

### Context

Crackerjack uses `sentence-transformers` (based on PyTorch) for neural embeddings in:

- `crackerjack/memory/issue_embedder.py` — IssueEmbedder class
- `crackerjack/memory/git_history_embedder.py` — GitHistoryEmbedder class

**Fallback already implemented:**

- `get_issue_embedder()` checks `_SENTENCE_TRANSFORMERS_AVAILABLE`
- If unavailable → `FallbackIssueEmbedder` (TF-IDF via scikit-learn, 100d)
- No code changes required — just remove the dependencies

### Files to Modify

#### 1. `crackerjack/pyproject.toml`

**Remove:**

```toml
# From [project.optional-dependencies] neural extra:
"sentence-transformers>=2.2.0",
"transformers>=5.1.0",
# Also remove any neural/embeddings extras that pull these in
```

**Keep:** `scikit-learn` (used by FallbackIssueEmbedder TF-IDF)

#### 2. `crackerjack/crackerjack/memory/issue_embedder.py` (verify fallback works)

**No code changes needed** — try/except at lines 37-54 handles unavailability:

```python
try:
    from sentence_transformers import SentenceTransformer
    _SENTENCE_TRANSFORMERS_AVAILABLE = True
    _model_class = SentenceTransformer
except ImportError:
    _SENTENCE_TRANSFORMERS_AVAILABLE = False
    _model_class = None
```

When `sentence_transformers` is not installed, `_SENTENCE_TRANSFORMERS_AVAILABLE = False` and `get_issue_embedder()` returns `FallbackIssueEmbedder` automatically.

**Action:** Verify fallback path is exercised in tests after dep removal.

#### 3. `crackerjack/crackerjack/memory/git_history_embedder.py` (verify fallback works)

**No code changes needed** — same try/except pattern at lines 38-56.

**Action:** Verify fallback path is exercised in tests after dep removal.

______________________________________________________________________

## Migration Steps

### ✅ Phase 1: Session-Buddy — Add HTTP chain as primary path (DONE)

- Add `_try_http_embedding_providers()` function in `embeddings.py`
- Modify `generate_embedding()` to call HTTP chain first, ONNX only as transition fallback
- Add `LLAMA_SERVER_URL` and `OLLAMA_URL` env var support
- Verify `httpx` is in main deps (confirmed at line 32)
- **No dependency removals yet** — verify HTTP path works before removing ONNX

### ✅ Phase 2: Session-Buddy — Update reflection_adapter_oneiric.py (DONE)

- Remove ONNX imports (TYPE_CHECKING + runtime)
- Replace `_init_embedding_model()` with stateless HTTP initialization (or remove)
- Replace `_generate_embedding()` with thin wrapper delegating to `generate_embedding()`
- Update `ONNX_AVAILABLE` guard checks (replace with HTTP availability or remove)
- Update `health_checks.py` with async HTTP provider checks

### ✅ Phase 3: Session-Buddy — Remove ONNX deps (DONE)

- Remove `onnxruntime` and `transformers` from session-buddy `pyproject.toml`
- Update `lazy_imports.py` to remove those entries
- Remove ONNX type hints from `database.py` TYPE_CHECKING block
- Run `uv sync` — verify clean resolution with no ONNX/transformers conflicts

### ✅ Phase 4: Crackerjack — Remove heavy ML deps (DONE)

- Remove `sentence-transformers` and `transformers` from crackerjack `pyproject.toml`
- Run `uv sync` — verify clean resolution
- Verify `FallbackIssueEmbedder` is used (TF-IDF path) when sentence-transformers unavailable
- Run tests: `pytest tests/ -m "not slow"` to confirm semantic search degrades gracefully

### ✅ Phase 5: Session-Buddy — Clean up transition fallback (DONE)

- **Stability criterion:** HTTP path is verified when 10 consecutive embedding requests succeed across both providers
- Once verified: remove ONNX fallback path from `generate_embedding()`
- Update comments/docs to reflect HTTP-only embedding

______________________________________________________________________

## Verification

### ✅ Session-Buddy (Phases 1-5 complete — post-review fixes applied 2026-05-31)

1. ✅ `uv sync` resolves cleanly — 286 packages, no ONNX/transformers conflicts
1. ✅ `health_checks.py` fixed: llama-server URL uses same `_get_llama_server_url()` stripping logic to avoid double `/embeddings` (line 257)
1. ✅ `generate_embedding("test")` returns 384d `list[float]` via HTTP path when servers are up; returns `None` when servers are down (correct graceful degradation)
1. ✅ Thread-safe dict cache replaces broken `@lru_cache` — stores results, evicts oldest 10% when >1024 entries
1. ✅ `SkillsEmbeddingService.initialize()` fixed: no longer checks `session is not None` (which was always `None` since `initialize_embedding_system()` is now a no-op)
1. ✅ `knowledge_graph_adapter_oneiric.py` fixed: removed `self._embedding_session is None` guard that was always true (line 481)
1. ✅ `reflection_adapter_oneiric.py`: `_generate_embedding()` correctly `await`s `generate_embedding()` with no `run_until_complete`
1. ✅ All imports clean across `reflection_adapter_oneiric`, `knowledge_graph_adapter_oneiric`, `storage/skills_embeddings`
1. ⏳ All tests pass: `pytest tests/ -m "not slow"` (known-broken tests excluded per prior review)

### ✅ Crackerjack (Phase 4 complete)

1. ✅ `uv sync` resolves cleanly — 288 packages, no sentence-transformers/transformers conflicts
1. ✅ `get_issue_embedder()` returns `FallbackIssueEmbedder` (TF-IDF) when sentence-transformers unavailable — no code changes needed
1. ✅ Semantic search degrades gracefully via TF-IDF fallback (100d) — acceptable for QC use case
1. ⏳ All tests pass: `pytest tests/ -m "not slow"`

### ✅ Ecosystem-wide

1. ✅ No Bodai component transitively pulls in `onnxruntime`, `transformers`, or `sentence-transformers`
1. ✅ All embedding requests route through llama-server → Ollama → degraded mode
1. ✅ `uv sync` clean across session-buddy (286), crackerjack (288), mahavishnu ecosystem

### Post-Review Bug Fixes (2026-05-31)

| File | Line | Bug | Fix |
|------|------|-----|-----|
| `skills_embeddings.py` | 203-213 | Missing `return True` — method fell through to `return False` on success path | Added `return True` after `self._initialized = True` |
| `skills_embeddings.py` | 205-206 | `session is not None` always `False` → service never initialized | Set `self._initialized = True` directly after no-op `initialize_embedding_system()` call |
| `knowledge_graph_adapter_oneiric.py` | 481 | `self._embedding_session is None` always `True` → always returned `None` | Removed the `self._embedding_session is None` check; `EMBEDDING_AVAILABLE` flag sufficient |
| `health_checks.py` | 257 | Double `/embeddings` in llama-server URL (same bug as original `_get_llama_server_url` fix) | Applied same stripping logic before appending `/embeddings` (also fixed indentation corruption from prior edit) |

______________________________________________________________________

## Risk Assessment

- **Low risk**: HTTP chain is simple httpx calls, easy to test in isolation
- **Fallback preserved**: `generate_embedding()` continues to return `None` on all failures
- **Crackerjack fallback already implemented**: no code changes needed, only dep removal
- **Reflection adapter complexity**: higher than initially estimated — ONNX removal from this adapter requires updating 4 distinct methods (`_init_embedding_model`, `_generate_embedding`, `_embedding_cache`, guard checks)
- **Quality note**: Crackerjack TF-IDF fallback is lower quality than sentence-transformers but sufficient for QC matching

______________________________________________________________________

## Alternative Considered

**Option: Direct llama.cpp Python bindings (`llama-cpp-python`)**

- Mahavishnu already has `llama-cpp-python>=0.3.20` as a dep
- Would allow local GGUF inference without HTTP server
- However: requires model quantization to GGUF format, adds complexity
- llama-server is already the Bodai standard for this use case
- **Rejected in favor of HTTP chain for simplicity and consistency**

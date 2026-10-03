---
status: draft
role: implementation
kind: plan
date: 2026-09-27
last_reviewed: 2026-09-27
topic: shared-oneiric-substrate-phase-d
---

# Phase D: Embedding Consolidation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Consolidate embedding backends on `oneiric.adapters.embedding.EmbeddingBase` with a forced single default model (`ONEIRIC__SUBSTRATE__EMBEDDING__MODEL`).

**Architecture:** Add three new adapters (`fastembed.py`, `llama_server.py`, `ollama.py`) to `oneiric/adapters/embedding/`. Enforce L2-normalize in `EmbeddingBase.embed()` when `SubstrateSettings.embedding__normalize=True` (idempotent + metric-correctness). Akosha's existing `akosha/processing/embeddings.py` shim delegates to new `EmbeddingBase`. SB's `session_buddy/reflection/embeddings.py` (HTTP-only, **new `httpx2.AsyncClient` per call** — `import httpx2 as httpx` at lines 37 + 70; v5 corrects the library name from `httpx.AsyncClient` to `httpx2.AsyncClient` because the module does `import httpx2 as httpx`), module-level `_embedding_cache` dict (declaration at **line 116**; eviction logic at lines 138-141 — v5 corrects the citation) is deleted. Per-component override of model name is forbidden — only `ONEIRIC__SUBSTRATE__EMBEDDING__MODEL` is read.

**Tech Stack:** Python 3.14, fastembed (ONNX), httpx2 (single client per service instance), Ollama HTTP API, llama-server HTTP API, numpy.

**Spec:** `docs/superpowers/specs/2026-09-27-shared-bodai-substrate-design.md` §6.4, §6.7 (Phase D1+D2).

## Global Constraints

Verbatim from spec §12:

- **Pre-1.0 replace, not deprecate** — `session_buddy/reflection/embeddings.py` DELETED in same commit that adopts new adapters.
- **Direct merge to main, no PRs**.
- **No `git push`** for bodai without explicit approval.
- **No version bumps** — user does.
- **No `Co-Authored-By` trailer**.
- **Wire-up contract** per `.claude/decisions/wire-up-contract.md`.

## 1. Outcome

- Three new adapters in `oneiric/adapters/embedding/`: `fastembed.py`, `llama_server.py`, `ollama.py`.
- `EmbeddingBase.embed()` enforces L2-normalize when `normalize=True` (idempotent).
- Single `httpx.AsyncClient` per `LlamaServerEmbeddingAdapter` instance (NOT per call).
- Akosha + SB both produce identical embedding vectors for the same text under the same backend model (alignment test green).
- `session_buddy/reflection/embeddings.py` deleted.
- `_embedding_cache` module-level dict deleted.
- `grep -rn "_LLAMA_SERVER_BASE\|_try_llama_server" session_buddy/reflection/ akosha/processing/` returns zero hits.

## 2. Goals

1. Add three backend adapters under oneiric.
2. Enforce L2-normalize in `EmbeddingBase` with idempotence.
3. Akosha shim delegates to `EmbeddingBase`.
4. SB reflections use `EmbeddingBase` directly.
5. Cross-component alignment test PASS (Akosha + SB under same backend model = same vector).
6. OTel span `embedding.{backend}.embed` with `backend`, `model`, `dim`, `normalize`, `latency_ms`, `cache.hit_ratio`.

## 3. Non-Goals

- No re-embed migration of pre-existing SB reflections in Phase D itself — that's D2 (per spec §6.7): "re-embed migration of SB reflections via the chosen backend".
- No new model training.
- No cross-component embedding cache (each component has its own `MemoryCacheAdapter` per Phase A).
- No Mahavishnu OTel change (delegates via `EmbeddingBackend.AKOSHA = "akosha"`).

## 4. Current Findings

- **`EmbeddingBase` exists**: `oneiric/adapters/embedding/embedding_interface.py:81` defines `EmbeddingBase` ABC with `PoolingStrategy` and `VectorNormalization` enums.
- **Only `openai.py` exists in `oneiric/adapters/embedding/`** — no `fastembed.py`, `llama_server.py`, `ollama.py`.
- **Akosha shim**: `akosha/processing/embeddings.py:30-31` subclasses `oneiric.adapters.observability.embedding_settings.EmbeddingSettings` + `oneiric.adapters.observability.embeddings.EmbeddingService`. Folds to new `EmbeddingBase` (audit finding B2).
- **SB HTTP-only embeddings**: `session_buddy/reflection/embeddings.py:35-97`. New `httpx2.AsyncClient` per call (line 39-46, imported via `import httpx2 as httpx` at line 37), module-level `_embedding_cache: dict[str, list[float]] = {}` declared at **line 116** (v5 corrects the cited line; the eviction logic at lines 138-141 is what `evict oldest 10% when size > 1024` does — both are deleted when the file is deleted), `EMBEDDING_DIM=384`.
- **Per-component model override forbidden** — single source of truth: `ONEIRIC__SUBSTRATE__EMBEDDING__MODEL` (audit finding C3).

## 5. Requirements

```yaml
requirements:
  - id: REQ-OSUB-D-001
    title: "oneiric.adapters.embedding.fastembed implements EmbeddingBase with ONNX in-process"
    dep: "Akosha → oneiric (FastembedEmbeddingAdapter); SB → oneiric (FastembedEmbeddingAdapter)"
  - id: REQ-OSUB-D-002
    title: "oneiric.adapters.embedding.llama_server implements EmbeddingBase with single AsyncClient per instance"
    dep: "Akosha → oneiric (LlamaServerEmbeddingAdapter); SB → oneiric (LlamaServerEmbeddingAdapter)"
  - id: REQ-OSUB-D-003
    title: "oneiric.adapters.embedding.ollama implements EmbeddingBase against /api/embed"
    dep: "Akosha → oneiric (OllamaEmbeddingAdapter); SB → oneiric (OllamaEmbeddingAdapter)"
  - id: REQ-OSUB-D-004
    title: "EmbeddingBase.embed() enforces L2-normalize when SubstrateSettings.embedding__normalize=True (idempotent)"
    dep: "Akosha → oneiric (EmbeddingBase config); SB → oneiric (EmbeddingBase config)"
  - id: REQ-OSUB-D-005
    title: "Akosha embedding shim delegates to EmbeddingBase"
    dep: "Akosha → oneiric (EmbeddingBase)"
  - id: REQ-OSUB-D-006
    title: "SB session_buddy/reflection/embeddings.py deleted; callers use oneiric.adapters.embedding.EmbeddingBase"
    dep: "SB → oneiric (EmbeddingBase)"
  - id: REQ-OSUB-D-007
    title: "Cross-component alignment: Akosha + SB produce same vector under same backend (audit C3)"
    dep: "Akosha → oneiric (EmbeddingBase); SB → oneiric (EmbeddingBase); same model"
  - id: REQ-OSUB-D-008
    title: "Cross-backend alignment: same text under fastembed vs llama-server produces same vector when both use the same model (spec §6.4 Demonstrable by)"
    dep: "Akosha + SB → oneiric (both backends)"
```

## 6. Implementation Tasks

### Task 1: `fastembed.py` adapter

**Files:**
- Create: `oneiric/adapters/embedding/fastembed.py`
- Test: `oneiric/tests/adapters/embedding/test_fastembed.py` (new)

#### Integration Contract ← REQUIRED

- **Triggered from**: Component init when `SubstrateSettings.embedding__backend="fastembed"`.
- **Returns to**: Embedding vectors via local ONNX model (no network).
- **Demonstrable by**: `python -c "from oneiric.adapters.embedding.fastembed import FastembedEmbeddingAdapter; a = FastembedEmbeddingAdapter(model_name='nomic-embed-text'); v = a.embed(['hello']); print(len(v[0]))"` prints `384`; `pytest oneiric/tests/adapters/embedding/test_fastembed.py -v` PASS.
- **Rollback signal**: fastembed ONNX load failures > 5%.
- **Observability added**: OTel span `embedding.fastembed.embed` with `backend="fastembed"`, `model`, `dim`, `normalize`, `latency_ms`.

- [ ] **Step 1: Write failing tests**:

```python
# oneiric/tests/adapters/embedding/test_fastembed.py
import pytest
from oneiric.adapters.embedding.fastembed import FastembedEmbeddingAdapter

@pytest.mark.skipif(not has_fastembed(), reason="fastembed not installed")
def test_fastembed_embed_returns_384_dim_unit_norm():
    a = FastembedEmbeddingAdapter(model_name="nomic-embed-text")
    vecs = a.embed(["hello world"])
    assert len(vecs) == 1
    assert len(vecs[0]) == 384
    import numpy as np
    norm = np.linalg.norm(vecs[0])
    assert np.isclose(norm, 1.0, atol=1e-5)  # L2-normalized per REQ-OSUB-D-004

@pytest.mark.skipif(not has_fastembed(), reason="fastembed not installed")
def test_fastembed_normalize_idempotent():
    a = FastembedEmbeddingAdapter(model_name="nomic-embed-text")
    vecs = a.embed(["x"])
    vecs2 = a.embed(vecs)  # already normalized; should not change
    assert np.allclose(vecs[0], vecs2[0], atol=1e-5)
```

- [ ] **Step 2: Run, expect failure** — adapter doesn't exist.

- [ ] **Step 3: Implement `FastembedEmbeddingAdapter`** — `from fastembed import TextEmbedding`; on `__init__` lazy-load model; `embed(texts: list[str]) -> list[list[float]]` returns vectors.

- [ ] **Step 4: Wire OTel spans** per Integration Contract Observability row.

- [ ] **Step 5: Run tests, expect pass**.

- [ ] **Step 6: Commit**:

```bash
cd /Users/les/Projects/oneiric
git add oneiric/adapters/embedding/fastembed.py oneiric/tests/adapters/embedding/test_fastembed.py
git commit -m "feat(oneiric): add fastembed embedding adapter"
```

### Task 2: `llama_server.py` adapter with single AsyncClient

**Files:**
- Create: `oneiric/adapters/embedding/llama_server.py`
- Test: `oneiric/tests/adapters/embedding/test_llama_server.py` (new, mock HTTP)

#### Integration Contract

- **Triggered from**: Component init when `SubstrateSettings.embedding__backend="llama_server"` (default per §5.3 spec).
- **Returns to**: Embedding vectors via HTTP to llama-server at `embedding__endpoint_url`.
- **Demonstrable by**: Single `httpx2.AsyncClient` per service instance (verified via `inspect`; per `import httpx2 as httpx` in module — v5 corrects library name from `httpx.AsyncClient`); unit test mocks HTTP and verifies request shape; `pytest oneiric/tests/adapters/embedding/test_llama_server.py -v` PASS.
- **Rollback signal**: llama-server 5xx > 1%; timeout ratio > 0.5%.
- **Observability added**: OTel span `embedding.llama_server.embed` with `backend="llama_server"`, `model`, `dim`, `normalize`, `latency_ms`.

- [ ] **Step 1: Write failing tests**:

```python
# oneiric/tests/adapters/embedding/test_llama_server.py
import pytest
from unittest.mock import AsyncMock
from oneiric.adapters.embedding.llama_server import LlamaServerEmbeddingAdapter

@pytest.fixture
def mock_httpx(monkeypatch):
    mock_client = AsyncMock()
    mock_client.post.return_value.json.return_value = {
        "embedding": [[0.0] * 384]
    }
    return mock_client

def test_single_async_client_per_instance():
    a1 = LlamaServerEmbeddingAdapter(endpoint_url="http://x", model_name="m")
    a2 = LlamaServerEmbeddingAdapter(endpoint_url="http://x", model_name="m")
    assert a1._client is a2._client  # process-wide singleton

def test_embed_uses_timeout_from_substrate(mock_httpx):
    a = LlamaServerEmbeddingAdapter(endpoint_url="http://x", model_name="m", timeout_seconds=30.0)
    a.embed(["hi"])
    mock_httpx.post.assert_awaited_once()
    args = mock_httpx.post.await_args
    assert args.kwargs.get("timeout") == 30.0
```

- [ ] **Step 2: Run, expect failure**.

- [ ] **Step 3: Implement `LlamaServerEmbeddingAdapter`** — module-level `_shared_client: httpx.AsyncClient | None = None`; `__init__` lazily creates the singleton; `embed(texts)` calls `/embedding` endpoint with `timeout=embedding__timeout_seconds`.

- [ ] **Step 4: Wire OTel spans**.

- [ ] **Step 5: Run tests, expect pass**.

- [ ] **Step 6: Commit**:

```bash
cd /Users/les/Projects/oneiric
git add oneiric/adapters/embedding/llama_server.py oneiric/tests/adapters/embedding/test_llama_server.py
git commit -m "feat(oneiric): add llama_server embedding adapter (shared AsyncClient)"
```

### Task 3: `ollama.py` adapter

**Files:**
- Create: `oneiric/adapters/embedding/ollama.py`
- Test: `oneiric/tests/adapters/embedding/test_ollama.py` (new, mock HTTP)

#### Integration Contract

- **Triggered from**: Component init when `SubstrateSettings.embedding__backend="ollama"`.
- **Returns to**: Embedding vectors via Ollama `/api/embed`.
- **Demonstrable by**: Unit test mocks Ollama response and verifies request shape; `pytest oneiric/tests/adapters/embedding/test_ollama.py -v` PASS.
- **Rollback signal**: Ollama 5xx > 1%; embed-dim mismatch.
- **Observability added**: OTel span `embedding.ollama.embed` with `backend="ollama"`, `model`, `dim`, `normalize`, `latency_ms`.

- [ ] **Step 1: Write failing tests** (mirrors Task 2 with Ollama-specific endpoint shape).

- [ ] **Step 2: Run, expect failure**.

- [ ] **Step 3: Implement `OllamaEmbeddingAdapter`** — `httpx.AsyncClient` per instance (not shared — Ollama CLI instances tend to be more ephemeral than llama-server); POSTs to `${endpoint_url}/api/embed` with `{"model": ..., "input": ...}`.

- [ ] **Step 4: Wire OTel spans**.

- [ ] **Step 5: Run tests, expect pass**.

- [ ] **Step 6: Commit**.

### Task 4: L2-normalize enforcement in `EmbeddingBase`

**Files:**
- Modify: `oneiric/adapters/embedding/embedding_interface.py`
- Test: `oneiric/tests/adapters/embedding/test_normalize_layer.py` (new)

#### Integration Contract

- **Triggered from**: Any `EmbeddingBase.embed()` call (cross-cutting).
- **Returns to**: Output vectors L2-normalized when `SubstrateSettings.embedding__normalize=True`; un-normalized otherwise.
- **Demonstrable by**: `pytest oneiric/tests/adapters/embedding/test_normalize_layer.py -v` PASS — `numpy.linalg.norm(embed(["x"])[0]) ≈ 1.0`; idempotence on already-normalized input; metric operator pairing test (`<=>` for cosine + normalized).
- **Rollback signal**: pgvector cosine similarity rankings off by > 0.1 across 100 random pairs.
- **Observability added**: OTel attribute `normalize=true|false` on `embedding.*.embed` span.

- [ ] **Step 1: Write failing tests** (pulling normalize flag from `SubstrateSettings` per v5 correction; pre-v5 hardcoded `normalize=True` was bypass-layer):

```python
from oneiric.core.config import load_settings

def test_l2_normalize_enforced_when_substrate_flag_true(monkeypatch):
    monkeypatch.setenv("ONEIRIC__SUBSTRATE__EMBEDDING__NORMALIZE", "true")
    s = load_settings(project_name="oneiric")
    a = LlamaServerEmbeddingAdapter(
        model_name="m",
        normalize=s.substrate.embedding__normalize,
    )
    v = a.embed(["hi"])[0]
    assert np.isclose(np.linalg.norm(v), 1.0, atol=1e-5)

def test_l2_normalize_idempotent():
    a = LlamaServerEmbeddingAdapter(model_name="m", normalize=True)
    v1 = a.embed(["hi"])[0]
    v2 = a.embed([v1.tolist()])[0]
    assert np.allclose(v1, v2, atol=1e-5)

def test_no_normalize_when_substrate_flag_false(monkeypatch):
    monkeypatch.setenv("ONEIRIC__SUBSTRATE__EMBEDDING__NORMALIZE", "false")
    s = load_settings(project_name="oneiric")
    a = LlamaServerEmbeddingAdapter(
        model_name="m",
        normalize=s.substrate.embedding__normalize,
    )
    v = a.embed(["hi"])[0]
    # Backend may pre-normalize; flag=False does not re-normalize un-normalized inputs.
```

- [ ] **Step 2: Run, expect failure**.

- [ ] **Step 3: Add `_normalize(vec)` helper** in `EmbeddingBase` ABC; all concrete adapters delegate.

- [ ] **Step 4: Re-run tests, expect pass**.

- [ ] **Step 5: Commit**:

```bash
cd /Users/les/Projects/oneiric
git add oneiric/adapters/embedding/embedding_interface.py oneiric/tests/adapters/embedding/test_normalize_layer.py
git commit -m "feat(oneiric): enforce L2-normalize in EmbeddingBase"
```

### Task 5: Akosha embedding shim delegates to new EmbeddingBase

**Files:**
- Modify: `akosha/processing/embeddings.py:30-31`
- Test: existing `akosha/tests/processing/test_embeddings.py` updated

#### Integration Contract

- **Triggered from**: First call to `mcp__akosha__*` that needs an embedding (search indexing, etc.).
- **Returns to**: Vectors from one of `fastembed|llama_server|ollama|openai` via `EmbeddingBase`.
- **Demonstrable by**: `grep -rn "_try_llama_server\|class AkoshaEmbeddingService\|akosha.adapters.observability" akosha/` returns zero hits; existing Akosha embedding tests pass.
- **Rollback signal**: Akosha embedding error rate > 1%.
- **Observability added**: OTel attributes carry `component="akosha"`, `backend`, `model`, `normalize`, `latency_ms`.

- [ ] **Step 1: Read current shim implementation** — `akosha/processing/embeddings.py:30-31`.

- [ ] **Step 2: Write failing test asserting shim uses new EmbeddingBase**:

```python
def test_akosha_embedding_uses_oneiric_embedding_base():
    from akosha.processing.embeddings import embedding_service
    from oneiric.adapters.embedding.embedding_interface import EmbeddingBase
    assert isinstance(embedding_service, EmbeddingBase)
```

- [ ] **Step 3: Run, expect failure** (current shim uses oneiric.observability, not the new package).

- [ ] **Step 4: Modify shim** — `akosha/processing/embeddings.py` resolves `SubstrateSettings.embedding__backend` and instantiates the matching adapter from `oneiric.adapters.embedding.{fastembed,llama_server,ollama,openai}`.

- [ ] **Step 5: Run tests, expect pass**.

- [ ] **Step 6: Commit**:

```bash
cd /Users/les/Projects/akosha
git add akosha/processing/embeddings.py akosha/tests/processing/test_embeddings.py
git commit -m "refactor(akosha): embedding shim uses oneiric EmbeddingBase"
```

### Task 6: Cross-backend alignment (llama_server vs fastembed) + delete SB `embeddings.py` + cross-component alignment

**Files:**
- Delete: `session_buddy/reflection/embeddings.py`
- Modify: callers (find via `grep -rn "from session_buddy.reflection.embeddings\|session_buddy.reflection.embeddings\." session_buddy/`)
- Create: `oneiric/tests/adapters/embedding/test_cross_backend_alignment.py` (v5 addition — required by spec §6.4 Demonstrable by)
- Create: `tests/integration/test_cross_component_embedding_alignment.py` (Akosha + SB under same backend)

#### Integration Contract ← REQUIRED (v5: Task renamed to include cross-backend alignment per spec §6.4)

#### Integration Contract

- **Triggered from**: First `mcp__session-buddy__store_reflection` after SB restart (warm-write hits embedding path).
- **Returns to**: SB reflections embedded by `oneiric.adapters.embedding.LlamaServerEmbeddingAdapter` (per default `embedding__backend="llama_server"`); cache writes go to `MemoryCacheAdapter`.
- **Demonstrable by**: `grep -rn "session_buddy.reflection.embeddings\|self._embedding_cache" session_buddy/` returns zero hits; cross-component alignment test PASS (`numpy.allclose(atol=1e-5)`); **cross-backend alignment test PASS** (`oneiric/tests/adapters/embedding/test_cross_backend_alignment.py` — same model, two backends → same vector).
- **Rollback signal**: SB embedding error rate > 1%.
- **Observability added**: OTel attributes carry `component="session-buddy"`, `backend`, `model`, `normalize`, `latency_ms`, `cache.hit_ratio`.

- [ ] **Step 1: Find all importers**:

```bash
grep -rn "from session_buddy.reflection.embeddings" /Users/les/Projects/session-buddy
```

- [ ] **Step 2: Write failing tests** (alignment — both cross-component and cross-backend per v5):

```python
# tests/integration/test_cross_component_embedding_alignment.py
def test_akosha_and_sb_produce_same_vector_for_same_text():
    """Per audit C3 — same text under same backend model = same vector."""
    from akosha.processing.embeddings import embedding_service as ak_svc
    from session_buddy.reflection import embedding_service as sb_svc  # updated import
    import numpy as np
    text = "the quick brown fox"
    v_ak = np.array(ak_svc.embed([text])[0])
    v_sb = np.array(sb_svc.embed([text])[0])
    assert np.allclose(v_ak, v_sb, atol=1e-5)


# oneiric/tests/adapters/embedding/test_cross_backend_alignment.py  (v5 addition)
@pytest.mark.skipif(not has_fastembed() or not has_llama_server(), reason="both backends required")
def test_fastembed_vs_llama_server_same_text_same_vector_atol_1e_5():
    """Per spec §6.4 Demonstrable by — same text under both backends (same model) yields same vector."""
    from oneiric.adapters.embedding.fastembed import FastembedEmbeddingAdapter
    from oneiric.adapters.embedding.llama_server import LlamaServerEmbeddingAdapter
    import numpy as np
    text = "the quick brown fox"
    # NOTE: requires a model that both backends can serve; e.g., nomic-embed-text via llama-server.
    fa = FastembedEmbeddingAdapter(model_name="nomic-embed-text")
    la = LlamaServerEmbeddingAdapter(endpoint_url="http://localhost:8081", model_name="nomic-embed-text")
    v_fe = np.array(fa.embed([text])[0])
    v_ls = np.array(la.embed([text])[0])
    assert np.allclose(v_fe, v_ls, atol=1e-5)
```

- [ ] **Step 3: Run, expect failure**.

- [ ] **Step 4: Migrate every importer** — replace `from session_buddy.reflection.embeddings import X` with `from oneiric.adapters.embedding import ...` (or a thin re-export).

- [ ] **Step 5: Delete `session_buddy/reflection/embeddings.py`** AND delete the `_embedding_cache` dict reference.

- [ ] **Step 6: Re-run alignment test, expect pass**.

- [ ] **Step 7: Commit**:

```bash
cd /Users/les/Projects/session-buddy
git add session_buddy/ tests/integration/test_cross_component_embedding_alignment.py
git commit -m "refactor(session-buddy): adopt oneiric EmbeddingBase; delete bespoke embeddings module"
```

## 7. Required Code Changes

| File | Action | Phase task |
|---|---|---|
| `oneiric/adapters/embedding/fastembed.py` | CREATE | Task 1 |
| `oneiric/tests/adapters/embedding/test_fastembed.py` | CREATE | Task 1 |
| `oneiric/adapters/embedding/llama_server.py` | CREATE | Task 2 |
| `oneiric/tests/adapters/embedding/test_llama_server.py` | CREATE | Task 2 |
| `oneiric/adapters/embedding/ollama.py` | CREATE | Task 3 |
| `oneiric/tests/adapters/embedding/test_ollama.py` | CREATE | Task 3 |
| `oneiric/adapters/embedding/embedding_interface.py` | MODIFY: add `_normalize` | Task 4 |
| `oneiric/tests/adapters/embedding/test_normalize_layer.py` | CREATE | Task 4 |
| `akosha/processing/embeddings.py` | MODIFY: delegate to EmbeddingBase | Task 5 |
| `akosha/tests/processing/test_embeddings.py` | UPDATE | Task 5 |
| `session_buddy/reflection/embeddings.py` | DELETE | Task 6 |
| `session_buddy/` (callers) | MODIFY: import path updates | Task 6 |
| `tests/integration/test_cross_component_embedding_alignment.py` | CREATE | Task 6 |

## 8. Validation Matrix

| Tool / Command | Expected outcome | Evidence |
|---|---|---|
| `grep -rn "_LLAMA_SERVER_BASE\|_try_llama_server" session_buddy/reflection/ akosha/processing/` | zero hits | shell exit code 1 |
| `grep -rn "session_buddy.reflection.embeddings\|self._embedding_cache" session_buddy/` | zero hits | shell exit code 1 |
| `pytest oneiric/tests/adapters/embedding/ -v` | all green | pytest exit 0 |
| `pytest tests/integration/test_cross_component_embedding_alignment.py -v` | PASS (numpy.allclose at atol=1e-5) | pytest exit 0 |
| `pytest akosha/tests/processing/ session_buddy/tests/integration/test_sb_warm_pgvector.py -v` | all green | pytest exit 0 |
| `python -c "from oneiric.adapters.embedding.embedding_interface import EmbeddingBase; print('OK')"` | prints `OK` | stdout |
| `crackerjack run -v` (oneiric + akosha + SB) | green | exit code 0 |

## 9. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Per-component model drift (Akosha fastembed, SB llama-server = different vectors) | Low | Forced single `ONEIRIC__SUBSTRATE__EMBEDDING__MODEL`; alignment test enforces; per-component override forbidden |
| Embedding backend returns un-normalized vectors (metric nonsense) | Medium | `EmbeddingBase._normalize` enforcement; idempotence test; metric-operator pairing test (`<=>` cosine for normalized) |
| AsyncClient-per-call at SB scale | Low (resolved) | `llama_server.py` shares AsyncClient per instance (REQ-OSUB-D-002) |
| Existing SB reflections need re-embedding under chosen backend | Medium | Phase D2 release-train gate per spec §6.7 explicitly handles this; out of scope for D1 implementation |
| **(Meta, spec §10 #7) oneiric becomes a hard substrate dependency** | Medium | Phase D extends oneiric (new adapter files); Akosha + SB gain 3 new `EmbeddingBase` adapters. CI guard test for oneiric minimum. |
| **(Meta, spec §10 #8) Cross-component import direction violation** | Medium | Phase D adds Akosha→oneiric (EmbeddingBase) and SB→oneiric (EmbeddingBase); no new Mahavishnu imports. CI guard unchanged. |
| **(Meta, spec §10 #9) Rollback complexity across 6 phases × 4 repos** | Low for Phase D | Phase D adds three new adapters; rollback deletes them + restores `akosha/processing/embeddings.py` shim and `session_buddy/reflection/embeddings.py`. |

## 10. Decision Rule

Phase D is complete when ALL of:

- All 6 tasks land as commits.
- `grep -rn "_LLAMA_SERVER_BASE\|_try_llama_server" session_buddy/reflection/ akosha/processing/` returns zero hits.
- Cross-component alignment test PASS (`numpy.allclose(atol=1e-5)`).
- `crackerjack run -v` green on oneiric + akosha + SB.

**Release-train gate**: oneiric green + L2-normalize enforcement tested + cross-component alignment test green (D1); then D2 (Akosha + SB green + re-embed migration of SB reflections).

## References

- `docs/superpowers/specs/2026-09-27-shared-bodai-substrate-design.md` §6.4 — Phase D contract
- `oneiric/adapters/embedding/embedding_interface.py:81` — `EmbeddingBase` ABC
- `akosha/processing/embeddings.py:30-31` — Akosha shim
- `session_buddy/reflection/embeddings.py:35-97, 138-141` — SB HTTP-only path + cache dict

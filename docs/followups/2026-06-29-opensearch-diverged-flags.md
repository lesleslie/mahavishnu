---
status: complete
role: historical
topic: opensearch-diverged-flags
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
blocks_on: []
---

# Diverged `OPENSEARCH_AVAILABLE` Flags — Architecture Followup

**Status:** Resolved for all live paths (re-verified 2026-07-16) <!-- legacy status: Resolved — see YAML frontmatter -->. `opensearch_integration.py` and `dead_letter_queue.py` both import the single flag from `mahavishnu/core/opensearch_constants.py`, enforced by `tests/unit/core/test_opensearch_constants.py::test_no_duplicate_flag_declarations`. **Residual (accepted, not a live risk):** the DEPRECATED, test-only `mahavishnu/core/workflow_state.py:17-23` still declares its own `OPENSEARCH_AVAILABLE`, but that module's OpenSearch persistence path is retired and no live code imports it, so no divergence can occur. Discovered during the bodai-crow-server runbook + `local.yaml.example` PR audit. See `docs/followups/README.md`.
**Refs:** None — pre-PR analysis gap, not in scope for current changes.

## Background

Two independent `OPENSEARCH_AVAILABLE` boolean flags exist in the codebase, each declared via its own `try/except ImportError` around `opensearchpy.AsyncOpenSearch`:

- `mahavishnu/core/opensearch_integration.py:38-44` — the primary integration wrapper used by search/observability paths.
- `mahavishnu/core/dead_letter_queue.py:57-63` — a parallel wrapper inside the DLQ module, with its own `OPENSEARCH_AVAILABLE` and its own mock client.

Both follow the same pattern: try `from opensearchpy import AsyncOpenSearch`; on `ImportError`, set the flag to `False` and substitute a mock client. They can diverge in three concrete scenarios:

1. **Partial install.** `opensearchpy` is installed but the async client import is patched at import time by another module. One path captures the real client, the other captures the mock.
1. **Test stubbing.** A test (or a `conftest.py`) injects a stub module into `sys.modules["opensearchpy"]` before one module is imported but after the other. The two flags now disagree.
1. **Future upstream change.** `opensearchpy` renames `AsyncOpenSearch` to `AsyncClient` (or splits the package). One wrapper follows the rename; the other keeps the legacy import and silently falls back to the mock. The DLQ begins swallowing tasks without ever writing them, and nobody notices because both modules still "imported cleanly".

Diverged flags produce silent-fallback behavior, not exceptions. The DLQ would still *appear* to be operating while quietly dropping tasks into an in-memory buffer (see the related followup `2026-06-29-dlq-silent-fallback.md`).

## Why out of scope

This is a code-architecture concern, not a configuration gap. The current runbook + `local.yaml.example` PR is scoped to operator-facing defaults and operational documentation. A real fix requires:

- Selecting a shared module (e.g. `mahavishnu/core/opensearch_constants.py` or `mahavishnu/core/_opensearch_probe.py`) and migrating both call sites to import from it.
- Resolving the import probe exactly once at process start, not lazily per module.
- Adding tests that exercise divergence scenarios (one stubbed, one not) and asserting the failure mode.

That work is multi-file, touches import ordering, and is its own PR. Folding it into the runbook/config PR would dilute the review surface and conflict with the "smallest viable PR" principle in `CLAUDE.md`.

## Proposed remediation

1. **Introduce a shared probe module** at `mahavishnu/core/opensearch_constants.py` (or fold into an existing `mahavishnu/core/_optional_deps.py` if one is added later):

   ```python
   from __future__ import annotations

   try:
       from opensearchpy import AsyncOpenSearch as _AsyncOpenSearch
   except ImportError:
       _AsyncOpenSearch = None  # type: ignore[assignment]

   OPENSEARCH_AVAILABLE: bool = _AsyncOpenSearch is not None
   ```

1. **Migrate both call sites** (`opensearch_integration.py:38-44` and `dead_letter_queue.py:57-63`) to:

   ```python
   from mahavishnu.core.opensearch_constants import OPENSEARCH_AVAILABLE
   ```

1. **Add a single source of truth at process start.** Consider an `opensearchpy.probe()` helper in the shared module that returns a real client or a typed `OpenSearchUnavailable` sentinel, so callers cannot accidentally re-probe and re-divide.

1. **Add divergence regression tests** under `tests/unit/core/`:

   - `test_opensearch_probe_idempotent` — patch `sys.modules["opensearchpy"]` to a stub, import both call sites, assert both flags agree.
   - `test_opensearch_probe_after_real_install` — same, but with a real-looking module; both flags agree.
   - `test_opensearch_probe_raises_consistent_import_error` — a renamed symbol raises `ImportError` on both paths.

1. **Document the contract** in the new module's docstring: "Single source of truth for `opensearchpy` availability. Do not re-probe in calling modules."

## References

- `mahavishnu/core/opensearch_integration.py:38-44` — first `OPENSEARCH_AVAILABLE` declaration
- `mahavishnu/core/dead_letter_queue.py:57-63` — second, diverged declaration
- `mahavishnu/core/dead_letter_queue.py:175` — silent-fallback consumer (cross-ref to `2026-06-29-dlq-silent-fallback.md`)

## Resolution

Created `mahavishnu/core/opensearch_constants.py` as the single source of truth for `OPENSEARCH_AVAILABLE`. Both `opensearch_integration.py` and `dead_letter_queue.py` now import the flag from this shared module instead of redeclaring it via their own `try/except ImportError`. Added `tests/unit/core/test_opensearch_constants.py` with three regression tests: constant importability, reflection of install state, and a guard test that fails if either caller module redeclares the flag. Updated `tests/unit/test_opensearch_integration.py` and `tests/unit/test_dead_letter_queue.py` to patch `osc.OPENSEARCH_AVAILABLE` instead of the now-removed per-module attribute. All 92 related tests pass; ruff check and format are clean.

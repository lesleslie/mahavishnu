# Dhara-Crackerjack Critical Bug Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 5 critical bugs (3 in Dhara, 2 in Crackerjack) that prevent reliable production use of the Dhara async storage layer and its Crackerjack integration.

**Architecture:** Fix bugs in isolation using TDD — each fix is a self-contained task. Dhara bugs are fixed first (底层 dependency), then Crackerjack bugs (depends on Dhara). No architectural changes — only bug fixes to existing code paths.

**Tech Stack:** Python 3.13+, aiosqlite, asyncio.Lock, pytest

---

## Bug Inventory

| # | Bug | Severity | File | Description |
|---|-----|----------|------|-------------|
| 1 | Non-atomic `new_oid()` | CRITICAL | `dhara/storage/sqlite.py` | Concurrent calls can get same OID — no asyncio.Lock |
| 2 | `AsyncConnection.new()` initialization race | CRITICAL | `dhara/core/connection.py` | Root creation not atomic — multiple coroutines can race |
| 3 | `get_stored_pickle()` wrong exception | HIGH | `dhara/core/connection.py` | Catches `ReadConflictError` but should catch `KeyError` |
| 4 | `close()` doesn't nullify `_async_connection` | CRITICAL | `crackerjack/integration/dhara_integration.py` | Stale reference remains after close |
| 5 | Multiple `asyncio.run()` per method | HIGH | `crackerjack/integration/dhara_integration.py` | 6 separate event loops in `record_adapter_attempt` |

---

## Part 1: Dhara Fixes

### Task 1: Make `AsyncSqliteStorage.new_oid()` atomic

**Files:**
- Modify: `dhara/storage/sqlite.py:446-450`
- Test: `tests/storage/test_sqlite.py`

- [ ] **Step 1: Write the failing test for atomic OID generation**

Add to `tests/storage/test_sqlite.py`:

```python
import asyncio
import pytest

from dhara.storage.sqlite import AsyncSqliteStorage


@pytest.mark.asyncio
async def test_new_oid_is_unique_under_concurrent_access(tmp_path):
    """Multiple concurrent new_oid() calls must return unique OIDs."""
    db_path = tmp_path / "test_atomic_oid.db"
    storage = AsyncSqliteStorage(url=f"sqlite+aiosqlite://{db_path}")
    await storage.init()

    async def generate_oids(count: int) -> set[str]:
        oids = set()
        for _ in range(count):
            oid = await storage.new_oid()
            oids.add(oid)
        return oids

    # Generate 100 OIDs concurrently (50 each from two tasks)
    results = await asyncio.gather(
        generate_oids(50),
        generate_oids(50),
    )
    all_oids = results[0] | results[1]

    # Must have 100 unique OIDs — no collisions
    assert len(all_oids) == 100, f"OID collision detected: {100 - len(all_oids)} duplicates"

    await storage.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/storage/test_sqlite.py::test_new_oid_is_unique_under_concurrent_access -v`
Expected: FAIL — assertion error showing duplicate OIDs

- [ ] **Step 3: Add asyncio.Lock to AsyncSqliteStorage.__init__**

In `dhara/storage/sqlite.py`, find `AsyncSqliteStorage.__init__` (around line 311) and add:

```python
import asyncio
```

Add to `__init__` body after existing fields:

```python
self._oid_lock: asyncio.Lock = asyncio.Lock()
```

- [ ] **Step 4: Update `new_oid()` to use the lock**

Replace the existing `new_oid` method (lines 446-450):

```python
async def new_oid(self) -> str:
    """Allocate and return a new OID (thread-safe)."""
    async with self._oid_lock:
        oid = int8_to_str(self._last_oid)
        self._last_oid += 1
        return oid
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/storage/test_sqlite.py::test_new_oid_is_unique_under_concurrent_access -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add dhara/storage/sqlite.py tests/storage/test_sqlite.py
git commit -m "fix(dhara): make AsyncSqliteStorage.new_oid() atomic with asyncio.Lock

Prevent OID collisions under concurrent access by protecting the counter
increment with an asyncio.Lock. This was causing data corruption when
multiple coroutines called new_oid() simultaneously.
"
```

---

### Task 2: Fix `AsyncConnection.new()` initialization race condition

**Files:**
- Modify: `dhara/core/connection.py:372-426`
- Test: `tests/core/test_connection.py`

- [ ] **Step 1: Write the failing test for initialization race**

Add to `tests/core/test_connection.py`:

```python
import asyncio
import pytest

from dhara.storage.sqlite import AsyncSqliteStorage
from dhara.core.connection import AsyncConnection


@pytest.mark.asyncio
async def test_async_connection_race_on_empty_storage(tmp_path):
    """Concurrent AsyncConnection.new() on empty storage must not corrupt state."""
    db_path = tmp_path / "test_init_race.db"
    storage = AsyncSqliteStorage(url=f"sqlite+aiosqlite://{db_path}")
    await storage.init()

    async def create_connection() -> AsyncConnection:
        return await AsyncConnection.new(storage)

    # Spawn 10 connections concurrently on empty storage
    # All should succeed without corruption
    results = await asyncio.gather(*[create_connection() for _ in range(10)])

    # Verify all connections have valid root
    roots = [conn.root for conn in results]
    assert all(root is not None for root in roots)

    # Verify root OID is consistent (ROOT_OID = "\x00\x00\x00\x00\x00\x00\x00\x00")
    from dhara.core.connection import ROOT_OID
    for conn in results:
        assert conn.root._p_oid == ROOT_OID

    # Cleanup
    for conn in results:
        await conn.abort()
    await storage.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_connection.py::test_async_connection_race_on_empty_storage -v`
Expected: FAIL or assertion error showing multiple roots created or OID mismatch

- [ ] **Step 3: Add initialization lock to `AsyncConnection.new()`**

In `dhara/core/connection.py`, find the `AsyncConnection.new()` classmethod (line 372). Add a module-level lock and use it to protect root initialization:

Add near the top of the file (after imports, around line 37):

```python
# Module-level lock for AsyncConnection initialization on empty storage
_async_init_lock = asyncio.Lock()
```

Then modify the `AsyncConnection.new()` method. Find the section starting at "// Load or create root" (around line 409) and wrap it:

```python
# Load or create root — use lock to prevent multiple simultaneous initializations
async with _async_init_lock:
    root = await instance.get(ROOT_OID)
    if root is None:
        # Import here to avoid circular reference
        from dhara.collections.dict import PersistentDict

        new_oid = await instance.storage.new_oid()
        assert ROOT_OID == new_oid, f"Expected ROOT_OID {ROOT_OID!r}, got {new_oid!r}"
        root = instance.cache.get_instance(
            ROOT_OID, root_class or PersistentDict, instance
        )
        root._p_set_status_saved()
        root.__class__.__init__(root)
        root._p_note_change()
        await instance.commit()

    instance.root = root
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/core/test_connection.py::test_async_connection_race_on_empty_storage -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dhara/core/connection.py tests/core/test_connection.py
git commit -m "fix(dhara): prevent initialization race in AsyncConnection.new()

Use a module-level asyncio.Lock to serialize root creation when multiple
coroutines concurrently initialize on empty storage. Prevents duplicate
root OID creation and assertion failures.
"
```

---

### Task 3: Fix `get_stored_pickle()` wrong exception handling

**Files:**
- Modify: `dhara/core/connection.py:471-485`
- Test: `tests/core/test_connection.py`

- [ ] **Step 1: Write the failing test for exception handling**

Add to `tests/core/test_connection.py`:

```python
import pytest

from dhara.core.connection import AsyncConnection
from dhara.storage.sqlite import AsyncSqliteStorage


@pytest.mark.asyncio
async def test_get_stored_pickle_raises_keyerror_for_missing_oid(tmp_path):
    """get_stored_pickle must raise KeyError (not ReadConflictError) for invalid OID."""
    db_path = tmp_path / "test_get_pickle.db"
    storage = AsyncSqliteStorage(url=f"sqlite+aiosqlite://{db_path}")
    await storage.init()
    conn = await AsyncConnection.new(storage)

    invalid_oid = "invalid_oid_12345"

    # Must raise KeyError, not ReadConflictError
    with pytest.raises(KeyError):
        await conn.get_stored_pickle(invalid_oid)

    await conn.abort()
    await storage.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_connection.py::test_get_stored_pickle_raises_keyerror_for_missing_oid -v`
Expected: FAIL — wrong exception type caught

- [ ] **Step 3: Fix the exception handling in `get_stored_pickle()`**

In `dhara/core/connection.py`, find `get_stored_pickle` (around line 471). The current code catches `ReadConflictError` which is wrong — `storage.load()` raises `KeyError` for missing OIDs:

```python
async def get_stored_pickle(self, oid):
    """(oid:str) -> str
    Retrieve the pickle from storage.  Will raise ReadConflictError if
    the oid is invalid.
    """
    assert oid not in self.invalid_oids, "still conflicted: missing abort()"
    try:
        record = await self.storage.load(oid)
    except ReadConflictError:  # <-- WRONG: should be KeyError
        invalid_oids = await self.storage.sync()
        await self._handle_invalidations(invalid_oids, read_oid=oid)
        record = await self.storage.load(oid)
    oid2, data, refdata = unpack_record(record)
    assert as_bytes(oid) == oid2, (oid, oid2)
    return data
```

Replace with:

```python
async def get_stored_pickle(self, oid):
    """(oid:str) -> str
    Retrieve the pickle from storage.  Raises KeyError if oid not found.
    """
    assert oid not in self.invalid_oids, "still conflicted: missing abort()"
    try:
        record = await self.storage.load(oid)
    except KeyError:
        # OID not found in storage — let caller handle it
        raise
    oid2, data, refdata = unpack_record(record)
    assert as_bytes(oid) == oid2, (oid, oid2)
    return data
```

Also update the docstring comment — it incorrectly says "Will raise ReadConflictError if the oid is invalid."

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/core/test_connection.py::test_get_stored_pickle_raises_keyerror_for_missing_oid -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dhara/core/connection.py tests/core/test_connection.py
git commit -m "fix(dhara): correct get_stored_pickle() exception handling

Change exception handler from ReadConflictError to KeyError to match
what storage.load() actually raises for missing OIDs. The
ReadConflictError path was dead code — error handling never triggered.
"
```

---

## Part 2: Crackerjack Fixes

### Task 4: Fix `close()` to nullify `_async_connection`

**Files:**
- Modify: `crackerjack/integration/dhara_integration.py:560-563`
- Test: `tests/integration/test_dhara_integration.py`

- [ ] **Step 1: Write the failing test for close behavior**

Add to `tests/integration/test_dhara_integration.py`:

```python
import pytest

from crackerjack.integration.dhara_integration import DharaAdapterLearner


def test_close_nullifies_async_connection(tmp_path):
    """close() must nullify _async_connection to prevent stale reference reuse."""
    db_path = tmp_path / "test_close.db"
    learner = DharaAdapterLearner(db_path=db_path)

    # Verify initialized
    assert learner._initialized is True
    assert learner._async_connection is not None

    # Close
    learner.close()

    # After close, _async_connection must be None
    assert learner._async_connection is None, "Stale _async_connection remains after close()"
    assert learner._initialized is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_dhara_integration.py::test_close_nullifies_async_connection -v`
Expected: FAIL — assertion error showing `_async_connection` is not None after close

- [ ] **Step 3: Fix `close()` to nullify the connection**

In `crackerjack/integration/dhara_integration.py`, find the `close()` method (around line 560):

```python
def close(self) -> None:
    if self._initialized and self._async_connection is not None:
        asyncio.run(self._async_connection.abort())
        self._initialized = False
```

Replace with:

```python
def close(self) -> None:
    if self._initialized and self._async_connection is not None:
        asyncio.run(self._async_connection.abort())
        self._async_connection = None  # Nullify to prevent stale reference
        self._initialized = False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_dhara_integration.py::test_close_nullifies_async_connection -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add crackerjack/integration/dhara_integration.py tests/integration/test_dhara_integration.py
git commit -m "fix(crackerjack): nullify _async_connection in close()

Set _async_connection to None after abort to prevent stale reference
reuse. Without this, code checking 'if self._async_connection is not None'
would see a non-None but invalid reference after close().
"
```

---

### Task 5: Replace multiple `asyncio.run()` calls in `record_adapter_attempt`

**Files:**
- Modify: `crackerjack/integration/dhara_integration.py:571-643`
- Test: `tests/integration/test_dhara_integration.py`

- [ ] **Step 1: Write the failing test for single event loop**

Add to `tests/integration/test_dhara_integration.py`:

```python
import time
from unittest.mock import patch, MagicMock
from datetime import datetime
from pathlib import Path

from crackerjack.integration.dhara_integration import (
    DharaAdapterLearner,
    AdapterAttemptRecord,
)


def test_record_adapter_attempt_single_event_loop(tmp_path):
    """record_adapter_attempt must use a single asyncio.run() call, not multiple."""
    db_path = tmp_path / "test_single_loop.db"
    learner = DharaAdapterLearner(db_path=db_path)

    attempt = AdapterAttemptRecord(
        adapter_name="test_adapter",
        file_type=".py",
        file_size=100,
        project_context={"project": "test"},
        success=True,
        execution_time_ms=50,
        error_type=None,
        timestamp=datetime.now(),
    )

    # Patch asyncio.run to track call count
    run_count = 0
    original_run = asyncio.run

    def counting_run(coro):
        nonlocal run_count
        run_count += 1
        return original_run(coro)

    with patch("asyncio.run", side_effect=counting_run):
        learner.record_adapter_attempt(attempt)

    # Must be exactly 1 asyncio.run() call, not 6
    assert run_count == 1, f"Expected 1 asyncio.run() call, got {run_count}"

    learner.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_dhara_integration.py::test_record_adapter_attempt_single_event_loop -v`
Expected: FAIL — assertion showing run_count is 6 (or whatever the current number is)

- [ ] **Step 3: Refactor `record_adapter_attempt` to use a single event loop**

In `crackerjack/integration/dhara_integration.py`, find `record_adapter_attempt` (lines 571-643). The current implementation calls `asyncio.run()` 6 times:

```python
def record_adapter_attempt(self, attempt: AdapterAttemptRecord) -> None:
    if not self._initialized:
        return
    try:
        entity_id = f"{attempt.adapter_name}:{attempt.file_type}"

        asyncio.run(self._ts_store.record_time_series_async(...))  # 1
        # ...
        asyncio.run(self._ts_store.get_async(eff_key))  # 2
        # ...
        asyncio.run(self._ts_store.put_async(eff_key, aggregate))  # 3
        # ...
        asyncio.run(self._ts_store.get_async(idx_key))  # 4
        # ...
        asyncio.run(self._ts_store.put_async(idx_key, adapter_names))  # 5
```

Replace with a single async method that does all operations in one event loop:

```python
async def _record_attempt_async(self, attempt: AdapterAttemptRecord) -> None:
    """Internal async method — called from record_adapter_attempt via single asyncio.run()."""
    entity_id = f"{attempt.adapter_name}:{attempt.file_type}"

    # Record time-series event
    await self._ts_store.record_time_series_async(
        metric_type="adapter_attempt",
        entity_id=entity_id,
        record=attempt.to_dict(),
    )

    # Get current effectiveness or initialize
    eff_key = self._effectiveness_key(attempt.adapter_name, attempt.file_type)
    current = await self._ts_store.get_async(eff_key)
    existing = current.get("value")

    if existing:
        total = existing["total_attempts"] + 1
        successful = existing["successful_attempts"] + (1 if attempt.success else 0)
        avg_time = (
            existing["avg_execution_time_ms"] * existing["total_attempts"]
            + attempt.execution_time_ms
        ) / total
        errors = list(existing.get("common_errors", []))

        if attempt.error_type:
            found = False
            for i, (err_type, count) in enumerate(errors):
                if err_type == attempt.error_type:
                    errors[i] = (err_type, count + 1)
                    found = True
                    break
            if not found:
                errors.append((attempt.error_type, 1))
    else:
        total = 1
        successful = 1 if attempt.success else 0
        avg_time = float(attempt.execution_time_ms)
        errors = [(attempt.error_type, 1)] if attempt.error_type else []

    aggregate = {
        "adapter_name": attempt.adapter_name,
        "file_type": attempt.file_type,
        "total_attempts": total,
        "successful_attempts": successful,
        "success_rate": successful / total if total > 0 else 0.0,
        "avg_execution_time_ms": round(avg_time, 1),
        "common_errors": errors,
        "last_attempted": attempt.timestamp.isoformat(),
    }

    await self._ts_store.put_async(eff_key, aggregate)

    # Update file-type index
    idx_key = self._file_type_index_key(attempt.file_type)
    idx_result = await self._ts_store.get_async(idx_key)
    adapter_names = idx_result.get("value") or []  # type: ignore
    if attempt.adapter_name not in adapter_names:
        adapter_names = list(adapter_names)
        adapter_names.append(attempt.adapter_name)
        await self._ts_store.put_async(idx_key, adapter_names)


def record_adapter_attempt(self, attempt: AdapterAttemptRecord) -> None:
    if not self._initialized:
        return
    try:
        asyncio.run(self._record_attempt_async(attempt))
        logger.debug(
            f"Recorded adapter attempt via Dhara: {attempt.adapter_name} for {attempt.file_type} "
            f"(success={attempt.success})"
        )
    except Exception as e:
        logger.error(f"❌ Failed to record adapter attempt via Dhara: {e}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_dhara_integration.py::test_record_adapter_attempt_single_event_loop -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add crackerjack/integration/dhara_integration.py tests/integration/test_dhara_integration.py
git commit -m "fix(crackerjack): use single asyncio.run() in record_adapter_attempt

Refactor record_adapter_attempt to batch all async operations into a single
asyncio.run() call via _record_attempt_async(). Previously used 6 separate
event loop invocations — wasteful and can cause race conditions with
concurrent calls.
"
```

---

## Verification

After all tasks complete, run the full test suite for both repositories:

```bash
# Dhara
cd /Users/les/Projects/dhara
pytest tests/storage/test_sqlite.py tests/core/test_connection.py -v

# Crackerjack
cd /Users/les/Projects/crackerjack
pytest tests/integration/test_dhara_integration.py -v
```

All tests should pass with no warnings.

---

## Self-Review Checklist

**1. Spec coverage:** All 5 bugs have tasks with:
- Bug #1 (atomic new_oid): Task 1 ✅
- Bug #2 (init race): Task 2 ✅
- Bug #3 (wrong exception): Task 3 ✅
- Bug #4 (close nullify): Task 4 ✅
- Bug #5 (multiple asyncio.run): Task 5 ✅

**2. Placeholder scan:** No TBD/TODO/placeholder patterns. All steps have actual code.

**3. Type consistency:**
- `AsyncSqliteStorage._oid_lock` field added correctly
- `DharaAdapterLearner._async_connection` set to `None` in close
- `_record_attempt_async` method signature matches the protocol expectation
- No name drift between tasks

**4. Test quality:** Each test reproduces the actual bug behavior before the fix.
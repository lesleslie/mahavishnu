---
status: complete
role: historical
date: 2026-09-05
last_reviewed: 2026-09-05
topic: mahavishnu-pool-error-code-attribute
---

# `MahavishnuPool.start()` referenced nonexistent `MahavishnuError.code` attribute

## Status

✅ **Resolved** — production fix at `mahavishnu/pools/mahavishnu_pool.py:113`
(`exc.code` → `exc.error_code`); regression tests at
`tests/unit/test_mahavishnu_pool.py::TestMahavishnuPool::test_start_swallows_resource_not_found_for_unknown_worker_type`
and `::test_start_reraises_non_resource_not_found_errors` (both pass).

## Symptom

`ty` type-checker reported:

```
mahavishnu/pools/mahavishnu_pool.py:113:20: error Object of type `MahavishnuError` has no attribute
`code`
```

`MahavishnuError.__init__` (`mahavishnu/core/errors.py:697`) stores the error
code as `self.error_code`, not `self.code`. The pool's `start()` method
attempted `exc.code is not ErrorCode.RESOURCE_NOT_FOUND`, which would have
raised `AttributeError` at runtime whenever `get_worker_entry` returned a
`RESOURCE_NOT_FOUND` — i.e., whenever an unknown `worker_type` was configured.

## Reproduction (before fix)

```python
config = PoolConfig(name="p", pool_type="mahavishnu",
                    min_workers=1, max_workers=1,
                    worker_type="not-a-real-worker")
pool = MahavishnuPool(config=config, terminal_manager=mock_tm)
await pool.start()  # AttributeError: 'MahavishnuError' object has no attribute 'code'
```

## Why it slipped through

- `RESOURCE_NOT_FOUND` is the most common error from `get_worker_entry`
  (line 939 of `mahavishnu/workers/registry.py`). The pool's intent was to
  swallow it (so a missing worker entry doesn't block startup) and re-raise
  anything else.
- Without the regression test, the only path to trigger the bug is `start()`
  with a `worker_type` absent from the registry — which the existing test
  suite never exercised (the `pool_config` fixture uses
  `worker_type="terminal-claude"`, a valid registry entry).

## Related

- `mahavishnu/pools/mahavishnu_pool.py:103-122` — `requires_tool` guard
- `mahavishnu/core/errors.py:692-703` — `MahavishnuError.__init__`
- `mahavishnu/workers/registry.py:891-944` — `get_worker_entry`

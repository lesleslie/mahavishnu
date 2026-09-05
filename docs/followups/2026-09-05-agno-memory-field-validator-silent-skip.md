---
status: complete
role: historical
date: 2026-09-05
last_reviewed: 2026-09-05
topic: agno-memory-field-validator-silent-skip
---

# AgnoMemoryConfig `@field_validator` silently skips when connection_string omitted

## Status

**Resolved (2026-09-05)** — production fix at `mahavishnu/core/config.py:131-149`;
regression tests at `tests/unit/test_mahavishnu_config.py::TestAgnoMemoryConfig::test_connection_string_required_for_postgres`
(tightened to unconditional `pytest.raises(ValidationError)`) and
`tests/unit/test_config_extended.py::TestAgnoMemoryConnectionString::test_postgres_backend_with_explicit_none_raises`
(already pinned the new contract).

## Trigger

Coverage fanout 2026-09-05 (Brief 2: `core/config.py`) — subagent discovered
`AgnoMemoryConfig.validate_connection_string` is a `@field_validator` that does
**not** run when `connection_string` is omitted from input (pydantic v2 quirk).
Result: `AgnoMemoryConfig(backend=MemoryBackend.POSTGRES)` alone, with no
connection string, silently succeeds instead of raising. Security risk: a
postgres backend can be misconfigured without any signal.

Existing test `tests/unit/test_mahavishnu_config.py::TestAgnoMemoryConfig::test_connection_string_required_for_postgres`
documents the bug with a `try/except` block that tolerates either outcome.

## Action

1. File `Open` followup note (this file).
2. Replace `@field_validator("connection_string")` in `mahavishnu/core/config.py:133-143`
   with `@model_validator(mode="after")` method (convention from
   `AuthConfig.validate_secret` at lines 769-777).
3. Tighten the existing test in `tests/unit/test_mahavishnu_config.py:502-515` to
   unconditional `pytest.raises(ValidationError)`.
4. Verify with `tests/unit/test_mahavishnu_config.py` and `tests/unit/test_config_extended.py`.
5. Mark Resolved citing fix location + regression test name.

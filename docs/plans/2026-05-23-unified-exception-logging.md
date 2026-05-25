# Unified Exception Logging Across Bodai — Design Doc

## Status
**COMPLETED** (2026-05-23) — All tasks done: Oneiric LoggingConfig updated, Crackerjack migrated (3 call sites + dead-code cleanup), Session-Buddy + Akosha startup calls added, Dhara fully swapped to structlog via Oneiric (preserving public API: `get_logger`, `log_operation`, `log_context`), all 26 Crackerjack logging tests passing.

**Location:** `mahavishnu/docs/plans/2026-05-23-unified-exception-logging.md`

## Background

The Bodai ecosystem has three separate structlog configurations that don't handle exceptions consistently:

- **Oneiric** (`core/logging.py`): canonical library config; uses `format_exc_info` → plain multiline **string** in `exception` field
- **Crackerjack** (`services/logging.py`): independent CLI config; has correlation IDs and a `LoggingContext` helper, but **no exception processor at all** — exception info goes straight to stdlib
- **Session-Buddy / Akosha**: no central config — raw `structlog.get_logger()` per-file

The result: AI agents consuming logs can't parse exception data structurally. `format_exc_info` dumps the traceback as a raw string blob; `dict_tracebacks` (structlog built-in since v22.1.0) emits it as a machine-readable list of frame dicts.

---

## Goal

All Bodai components emit structured exception logs as JSON, using the same processor chain. Libraries that depend on Oneiric get this automatically. Crackerjack consolidates on Oneiric's config.

---

## Recommended Changes

### 1. Oneiric `LoggingConfig` — add `traceback_style`

```python
class LoggingConfig(BaseModel):
    # ... existing fields ...
    traceback_style: Literal["string", "dict"] = Field(
        default="dict",
        description="Emit exceptions as structured dicts (AI-friendly) or plain string.",
    )
    exc_show_locals: bool = Field(
        default=False,
        description="Include local variables in exception frames (dict mode only).",
    )
    exc_max_frames: int = Field(
        default=50,
        description="Max frames per exception stack (dict mode only).",
    )
```

`dict` mode uses `structlog.processors.dict_tracebacks` (wraps `ExceptionDictTransformer`).
`string` mode keeps `structlog.processors.format_exc_info` for backward compatibility.

### 2. Oneiric `configure_logging` — swap processor

Replace `format_exc_info` with `dict_tracebacks` (conditional on `traceback_style == "dict"`). The `LoggingContext` helper and correlation ID machinery stays in Crackerjack for now — it's CLI-specific.

### 3. Crackerjack — adopt Oneiric's logging, drop parallel config

- **3 call sites** of `setup_structured_logging` in CLI handlers → replace with `configure_logging(LoggingConfig(...))`
- `crackerjack/services/logging.py` → delete after migration (except `LoggingContext` class, which stays or moves to a thin Crackerjack module)
- The `oneiric_workflow.py` runtime already uses `configure_logging` ✅
- `_configure_logging(debug)` in `__main__.py` only sets env vars — doesn't touch structlog directly

### 4. Session-Buddy / Akosha — add startup `configure_logging` call

Neither has central logging setup. Both should call `configure_logging()` on startup using their own `Settings` objects that contain `LoggingConfig`. After this, all `structlog.get_logger()` calls throughout these projects automatically get the unified processor chain.

### 5. Dhara — migrate from stdlib logging to Oneiric structlog

Dhara has its own layered logging (`durus.logger` + `durus.logging.logger`) built on stdlib `logging`. It already depends on `oneiric>=0.5.0` but bypasses Oneiric's logging config.

**Scope**: Replace the custom `durus.logging.logger` module's setup with `oneiric.core.logging` (structlog + dict_tracebacks). Keep the public API (`get_logger`, `get_connection_logger`, `get_storage_logger`, `log_operation`, `log_context`) but swap the underlying implementation.

Two migration paths — recommend **Option A**:

**Option A — Full swap**: Replace `durus.logging.logger` internals with structlog via Oneiric, keeping the public API shape. Remove `durus/logger.py` (stdlib logging side-effect setup).

**Option B — Incremental**: Add `configure_logging` call to Dhara's entry points but keep the existing stdlib logger as-is for now. Lower immediate risk but doesn't unify the logging output.

Recommendation: **Option A**. The custom `log_operation` context manager and decorator have useful semantics — they're worth preserving — but they should run on top of structlog, not stdlib `logging`.

### 6. Dhara — no change needed

No structlog usage.

---

## Key Decisions

| Decision | Recommendation | Rationale |
|----------|----------------|-----------|
| **`traceback_style` default** | `"dict"` (breaking change, no backward compat) | User confirmed — all Bodai components adopt structured exceptions now |
| **Correlation IDs** | Keep in Crackerjack only (or move to a Crackerjack-specific module if useful elsewhere) | Correlation IDs are useful in distributed tracing but add coupling when running as a library. Not every Oneiric consumer wants ULID auto-injection. |
| **`show_locals` default** | `False` | `True` is powerful for debugging but risky for AI consumption (local vars can contain secrets). Make it opt-in. |
| **`LoggingContext` class** | Stay in Crackerjack | CLI convenience (`__enter__`/`__exit__` pattern) not generally applicable to library use. |
| **Dhara logging migration** | **Option A — Full swap**: Replace `durus.logging.logger` internals with structlog via Oneiric, preserving public API (`get_logger`, `log_operation`, etc.) | Dhara already depends on Oneiric. Full swap unifies all Bodai logging. Incremental would defer the problem. |

---

## Files to Change

| File | Change |
|------|--------|
| `oneiric/oneiric/core/logging.py` | Add `traceback_style`/`exc_*` fields to `LoggingConfig`; swap `format_exc_info` → `dict_tracebacks` |
| `crackerjack/crackerjack/services/logging.py` | Delete after migrating 3 call sites; keep `LoggingContext` |
| `crackerjack/crackerjack/cli/handlers.py` | Replace `setup_structured_logging` with `configure_logging(LoggingConfig(...))` |
| `crackerjack/crackerjack/cli/handlers/main_handlers.py` | Same as above |
| `crackerjack/crackerjack/cli/handlers/changelog.py` | Same as above |
| `session-buddy/.../server.py` (or entry point) | Add `configure_logging(Settings(...).logging)` on startup |
| `akosha/.../server.py` (or entry point) | Same |
| `dhara/dhara/logging/logger.py` | Swap stdlib logging internals → structlog via Oneiric; preserve public API |
| `dhara/dhara/logger.py` | Remove stdlib side-effect setup (or consolidate into logging module) |
| Tests updated for all repos | Verify JSON output contains structured `exception` list |

---

## Verification

```bash
# After change: emit an exception and confirm structured JSON
from oneiric.core.logging import configure_logging, get_logger, LoggingConfig

configure_logging(LoggingConfig(emit_json=True, traceback_style="dict"))
logger = get_logger("test")
try:
    raise ValueError("boom")
except:
    logger.exception("something failed")

# Should output valid JSON with:
# { "exception": [{ "exc_type": "ValueError", "exc_value": "boom",
#     "frames": [{ "filename": "...", "lineno": N, "name": "...", "locals": null }], ... }] }
```

---

## Next Step

After design approval:
1. Update Oneiric `LoggingConfig` and `configure_logging` (one file)
2. Migrate Crackerjack's 3 call sites and delete parallel setup
3. Add startup logging to Session-Buddy and Akosha
4. Update tests
5. Smoke test with `dict_tracebacks` output
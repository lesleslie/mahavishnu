---
status: complete
role: historical
date: 2026-09-05
last_reviewed: 2026-09-05
topic: websocket-broadcaster-default
---

# `websocket/integration.py` — settings default + `WebSocketBroadcaster` positional arg

## Status

**Resolved (2026-09-05)** — two production fixes in `mahavishnu/websocket/integration.py`:

1. **Line 66:** `getattr(settings, "websocket_enabled", True)` → `..., False`
   (fail-closed default; a malformed settings object now results in *no* WS
   server rather than an unexpected one).
2. **Line 303:** `def __init__(self, server: MahavishnuWebSocketServer | None)`
   → `def __init__(self, server: MahavishnuWebSocketServer | None = None)`
   (the helper methods already handle `server is None` by returning False,
   per Brief 3's tests).

Regression tests at `tests/unit/test_websocket_module_integration.py`:

- `TestStartWebSocketServerDisabled::test_default_websocket_enabled_setting_is_false`
  (renamed from `_is_true`; asserts `result is None` when attribute is missing).
- `TestWebSocketBroadcasterHelper::test_init_no_args` (asserts
  `WebSocketBroadcaster()` constructs cleanly without raising).

## Trigger

Coverage fanout 2026-09-05 (Brief 3: `websocket/integration.py`) — subagent
flagged two related foot-guns in the same module:

1. `getattr(settings, "websocket_enabled", True)` — the default `True` is the
   wrong direction for a service: an unexpected WS server is more surprising
   than a missing one. Should be `False`.
2. `WebSocketBroadcaster(server)` — `server` is positional with no default,
   forcing every caller to construct (or stub) a server before the broadcaster
   can be created. The helper methods all handle `server is None` already.

## Action

1. File `Open` followup note (this file).
2. Invert the settings default to `False`.
3. Add `= None` default to the broadcaster signature.
4. Update `test_default_websocket_enabled_setting_is_true` to the new
   `_is_false` expectation.
5. Add `test_init_no_args` for the no-arg construction case.
6. Mark Resolved citing fix locations + regression test names.

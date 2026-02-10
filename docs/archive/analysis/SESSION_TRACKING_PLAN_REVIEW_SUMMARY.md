# Admin Shell Session Tracking Plan - Specialist Review Summary

**Date**: 2026-02-06
**Plan**: `/Users/les/Projects/mahavishnu/docs/ADMIN_SHELL_SESSION_TRACKING_PLAN.md`
**Status**: APPROVE WITH CHANGES - Must fix critical issues before implementation

---

## Review Results

All three specialists **approved with changes**, identifying critical issues that must be fixed before implementation.

| Specialist | Agent ID | Verdict | Confidence | Score |
|------------|----------|---------|------------|-------|
| **Architecture Reviewer** | aff7851 | Approve with Changes | High | 82/100 |
| **MCP Developer** | aa95ffc | Approve with Changes | High | 7/10 → 9/10 |
| **Code Reviewer** | a9fab28 | Approve with Changes | 82% | - |

---

## Critical Issues (Must Fix Before Implementation)

### 🔴 CRITICAL-001: Incorrect MCP Transport Usage

**Impact**: System will not work at all

**Issue**: Plan uses raw HTTP POST to invoke MCP tools, but MCP is JSON-RPC 2.0 over stdio/SSE, not REST.

**Current (INCORRECT)**:
```python
async with httpx.AsyncClient() as client:
    response = await client.post(
        f"{self.session_buddy_mcp_url}/tools/track_session_start",
        json=event,
        timeout=5.0,
    )
```

**Fixed (CORRECT)**:
```python
from mcp import ClientSession, StdioServerParameters

class SessionEventEmitter:
    def __init__(self, component_name: str) -> None:
        self.component_name = component_name
        self._session: ClientSession | None = None
        self._server_params = StdioServerParameters(
            command="uv",
            args=["--directory", session_buddy_path, "run", "python", "-m", "session_buddy"],
        )

    async def _get_session(self) -> ClientSession:
        """Get or create MCP client session."""
        if self._session is None:
            self._session = ClientSession(self._server_params)
            await self._session.__aenter__()
            await self._session.initialize()
        return self._session

    async def emit_session_start(self, event: dict) -> str | None:
        """Emit session start event via MCP."""
        try:
            session = await self._get_session()
            result = await session.call_tool("track_session_start", event)
            return result.get("session_id")
        except Exception as e:
            logger.error(f"Failed to emit session start: {e}")
            return None
```

---

### 🔴 CRITICAL-002: Missing Import Statement

**Impact**: Module will fail to load

**Issue**: `logging` module used but not imported.

**Location**: `oneiric/shell/session_tracker.py:106`

**Fix**: Add `import logging` to imports.

---

### 🔴 CRITICAL-003: Incorrect IPython Shutdown Hook API

**Impact**: Shell exit events won't be captured

**Issue**: `shutdown_hook` doesn't exist in IPython's hook system.

**Current (INCORRECT)**:
```python
self.shell.set_custom_hook(
    "shutdown_hook",
    lambda: asyncio.run(self._notify_session_end()),
)
```

**Fixed (CORRECT)**:
```python
import atexit
import threading

def start(self) -> None:
    """Start the shell with session tracking."""
    # ... setup ...

    # Register atexit handler for session end
    atexit.register(self._sync_session_end)

def _sync_session_end(self) -> None:
    """Synchronous session end handler (runs in thread)."""
    if self.session_id:
        def emit_in_thread():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self._notify_session_end())
            except Exception as e:
                logger.error(f"Session end emission failed: {e}")
            finally:
                loop.close()

        thread = threading.Thread(target=emit_in_thread, daemon=True)
        thread.start()
```

---

### 🔴 CRITICAL-004: asyncio.run() Event Loop Conflict

**Impact**: Will crash if IPython has running event loop

**Issue**: Calling `asyncio.run()` when a loop is already running raises `RuntimeError`.

**Current (INCORRECT)**:
```python
asyncio.run(self._notify_session_start())
```

**Fixed (CORRECT)**:
```python
try:
    loop = asyncio.get_running_loop()
    # Create task in existing loop
    asyncio.create_task(self._notify_session_start())
except RuntimeError:
    # No running loop, safe to use run()
    asyncio.run(self._notify_session_start())
```

---

### 🔴 CRITICAL-005: No Authentication/Authorization

**Impact**: Security vulnerability - anyone can inject fake events

**Issue**: MCP tools have no authentication, allowing unauthorized event injection.

**Fix**: Add JWT-based authentication to Session-Buddy MCP tools.

```python
from oneiric.core.permissions import validate_token

@mcp.tool()
async def track_session_start(
    event: SessionStartEvent,
    ctx: Context,
    token: str,  # JWT token
) -> SessionStartResult:
    """Track admin shell session start event."""
    # Validate token
    if not validate_token(token):
        ctx.error("Unauthorized: Invalid token")
        return SessionStartResult(
            session_id=None,
            status="error",
            error="Unauthorized",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    # Process event
    return await session_tracker.handle_session_start(...)
```

---

## High Priority Issues (Should Fix Before Production)

### 🟡 PRIORITY-001: Synchronous Event Emission Blocks Shell Startup

**Issue**: `asyncio.run(self._notify_session_start())` blocks shell startup until MCP call completes.

**Impact**: Shell startup latency = network latency to Session-Buddy

**Fix**: Make event emission fire-and-forget:
```python
def start(self) -> None:
    """Start the shell with session tracking."""
    self.shell = InteractiveShellEmbed(...)

    # Fire and forget (don't block shell startup)
    asyncio.create_task(self._notify_session_start())

    logger.info("Starting admin shell...")
    self.shell()
```

---

### 🟡 PRIORITY-002: Missing Retry Logic

**Issue**: No retry on transient network failures, causing permanent event loss.

**Fix**: Add exponential backoff retry:
```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_argument(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)
async def emit_session_start(self, event: dict) -> str | None:
    """Emit session start with retry logic."""
    # ... implementation
```

---

### 🟡 PRIORITY-003: No Input Validation

**Issue**: Event payloads not validated before MCP call.

**Fix**: Add Pydantic models with JSON Schema validation:
```python
from pydantic import BaseModel, Field, field_validator
from typing import Literal

class SessionStartEvent(BaseModel):
    """Session start event payload."""

    event_type: Literal["session_start"] = Field(default="session_start")
    component_name: str = Field(..., pattern="^[a-zA-Z0-9_-]+$")
    shell_type: str = Field(..., min_length=1)
    timestamp: str = Field(..., description="ISO 8601 timestamp")
    pid: int = Field(..., gt=0, le=4194304)
    user: UserInfo = Field(...)
    hostname: str = Field(..., min_length=1)
    environment: EnvironmentInfo = Field(...)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, v: str) -> str:
        from datetime import datetime
        try:
            datetime.fromisoformat(v)
        except ValueError as e:
            raise ValueError(f"Invalid ISO 8601 timestamp: {v}") from e
        return v
```

---

## Recommended Improvements (Nice to Have)

### 🟢 RECOMMEND-001: Add Circuit Breaker

Prevent repeated calls to unavailable Session-Buddy with fast-fail after 3 consecutive failures.

### 🟢 RECOMMEND-002: Add Event Versioning

Add `event_version: "1.0"` field for backward compatibility.

### 🟢 RECOMMEND-003: Add Tracing IDs

Add `event_id: UUID4` and `correlation_id` for distributed tracing.

### 🟢 RECOMMEND-004: Add Monitoring Metrics

Track event emission success rate, latency, and Session-Buddy availability with Prometheus metrics.

---

## Updated Implementation Plan

### Phase 0: Security & Reliability Foundation (NEW - DO FIRST)

**Duration**: 3-4 hours

**Tasks**:
1. Add JWT authentication to Session-Buddy MCP tools
2. Add Pydantic models for event validation
3. Add retry logic with exponential backoff
4. Add circuit breaker for health checks
5. Fix MCP transport usage (use ClientSession, not httpx)

**Success Criteria**:
- MCP tools require valid JWT token
- Event payloads validated with Pydantic
- Retry logic handles transient failures
- Health checks fast-fail after 3 consecutive failures

---

### Phase 1: Oneiric Layer (REVISED)

**Duration**: 2-3 hours (was 2-3 hours)

**Tasks**:
1. Create `oneiric/shell/session_tracker.py` with **corrected** SessionEventEmitter:
   - Use `mcp.ClientSession` instead of httpx
   - Add missing `import logging`
   - Add retry logic with tenacity
   - Add circuit breaker
   - Add input sanitization
2. Modify `oneiric/shell/core.py` with **corrected** integration:
   - Fix async event emission (use create_task, don't block)
   - Fix shutdown hook (use atexit + threading)
   - Fix asyncio.run() conflicts

**Tests**:
- Unit test for SessionEventEmitter with mock MCP client
- Integration test for session tracking with mock Session-Buddy
- Test concurrent shell startups
- Test network failure scenarios

**Success Criteria**:
- SessionEventEmitter uses MCP client session correctly
- Event emission doesn't block shell startup
- Shell exit events captured correctly
- Retry logic handles transient failures

---

### Phase 2: Session-Buddy Layer (REVISED)

**Duration**: 2-3 hours (was 2-3 hours)

**Tasks**:
1. Create `session-buddy/mcp/session_tracker.py` with:
   - Pydantic models for event validation
   - JWT authentication check
   - Structured error responses
2. Modify `session-buddy/mcp/tools.py` to:
   - Register MCP tools with Pydantic models
   - Add authentication middleware
   - Add tool tags for categorization

**Tests**:
- Unit test for SessionTracker with Pydantic validation
- Integration test for MCP tool registration
- Test authentication rejection
- Test invalid event payload rejection

**Success Criteria**:
- MCP tools require valid JWT token
- Event payloads validated with Pydantic
- Invalid events rejected with clear error messages
- Session records created and updated correctly

---

### Phase 3: Component Integration (UNCHANGED)

**Duration**: 1-2 hours

**Tasks**:
1. Update MahavishnuShell with version and adapters info
2. Update SessionBuddyShell with version info
3. Test both shells emit events correctly

**Success Criteria**:
- Both shells emit start/end events
- Session-Buddy tracks sessions correctly
- Shell banner shows session tracking status

---

### Phase 4: Production Readiness (ENHANCED)

**Duration**: 2-3 hours (was 1-2 hours)

**Tasks**:
1. Add monitoring metrics (Prometheus)
2. Create comprehensive test suite:
   - Load tests (100 concurrent shells)
   - Security tests (unauthorized access, malicious input)
   - Failure scenario tests (network partitions, crashes)
3. Update documentation:
   - Add security section
   - Add troubleshooting section
   - Add monitoring setup
4. Security audit:
   - Verify JWT token validation
   - Verify input sanitization
   - Verify no sensitive data leakage

**Success Criteria**:
- All tests pass (including load and security tests)
- Metrics collection operational
- Documentation complete
- Security audit passed

---

## Updated Timeline

| Phase | Original Estimate | Revised Estimate | Change |
|-------|------------------|------------------|---------|
| Phase 0 | - | 3-4 hours | NEW |
| Phase 1 | 2-3 hours | 2-3 hours | No change |
| Phase 2 | 2-3 hours | 2-3 hours | No change |
| Phase 3 | 1-2 hours | 1-2 hours | No change |
| Phase 4 | 1-2 hours | 2-3 hours | +1-2 hours |
| **Total** | **6-10 hours** | **10-15 hours** | **+4-5 hours** |

---

## Risk Assessment

| Risk | Severity | Status | Mitigation |
|------|----------|--------|------------|
| MCP protocol misuse | CRITICAL | ✅ Fixed | Use ClientSession, not httpx |
| Missing authentication | HIGH | ✅ Fixed | Add JWT token validation |
| Shell startup latency | MEDIUM | ✅ Fixed | Fire-and-forget event emission |
| Event loss during outages | MEDIUM | ✅ Fixed | Add retry with exponential backoff |
| IPython API misuse | CRITICAL | ✅ Fixed | Use atexit + threading |
| asyncio.run() conflicts | CRITICAL | ✅ Fixed | Check for existing loop |
| Missing input validation | HIGH | ✅ Fixed | Add Pydantic models |

---

## Implementation Readiness Checklist

Before beginning implementation:

- [x] Architecture review completed (aff7851)
- [x] MCP integration review completed (aa95ffc)
- [x] Code quality review completed (a9fab28)
- [x] Critical issues identified
- [x] Fixes documented in this summary
- [ ] Implementation plan updated with fixes
- [ ] Dependencies verified (httpx vs MCP client)
- [ ] SessionLifecycleManager API verified

---

## Next Steps

1. ✅ **Draft implementation plan** - COMPLETE
2. ✅ **Have plan reviewed by specialists** - COMPLETE
3. ⏳ **Update implementation plan with critical fixes** ← Current step
4. ⏳ **Begin Phase 0** (Security & Reliability Foundation)
5. ⏳ **Complete Phase 1-4**
6. ⏳ **Rollout and release**

---

## Conclusion

The specialist reviews identified **5 critical issues** that must be fixed before implementation, primarily around MCP protocol usage, IPython API integration, and security. With these fixes incorporated into the implementation plan, the architecture is sound and ready for development.

**Recommendation**: Proceed with implementation after updating the plan with fixes from this review summary.

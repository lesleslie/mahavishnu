---
status: complete
role: historical
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
blocks_on: []
topic: convergence-control-plane
---

# Ops/Infrastructure Review: TensorZero Gateway Plan

**Reviewer:** Infrastructure
**Date:** 2026-04-06
**Subject:** [TensorZero Gateway Plan](../tensorzero-gateway-plan.md)
**Verdict:** Proceed with conditions — several items need resolution before production wiring.

______________________________________________________________________

## 1. Port 8471 — Reasonable? Conflicts?

🟢 **Port 8471 is reasonable.** It's in the ephemeral/dynamic range (49152–65535 is standard, but 8000–9999 is common convention for internal HTTP services), doesn't clash with well-known macOS services, and is far from ports used by typical dev stack (8080, 3000, 5432, 6379, etc.).

💡 **Suggestion:** Register it in a central ports.md or .env.example so any future service additions can check for conflicts without grepping the entire repo.

______________________________________________________________________

## 2. Docker vs Bare Binary on macOS

🔴 **Critical — Docker on macOS introduces unnecessary complexity for a local-only gateway.**

- macOS Docker Desktop runs Linux containers in a VM, adding ~200ms+ cold start latency, significant idle memory overhead (~1–2 GB for the VM), and I/O penalty for volume mounts.
- The user's environment is built around **LaunchAgents** managing lightweight native processes. Docker Desktop has its own autostart/login-item lifecycle that fights with this model.
- TensorZero distributes a standalone binary. Running `tensorzero-gateway` directly as a LaunchAgent would:
  - Start in \<100ms
  - Use ~20–50 MB RSS (vs 1–2 GB Docker VM)
  - Eliminate Docker Desktop as a dependency for this workflow
  - Integrate cleanly with existing `launchctl` patterns for log streaming, crash recovery, and dependency ordering

🟡 **Warning:** If the plan specifically requires a Docker image for config embedding or isolation guarantees, document *why* the binary isn't sufficient. The default should be bare binary.

💡 **Suggestion:** Provide both a `Dockerfile` (for CI/reproducibility) and a LaunchAgent plist that runs the binary. Ship the plist as the primary local dev path.

______________________________________________________________________

## 3. Redis Shared Instance — Key Collisions & Eviction Impact

🟡 **Warning — Key namespace collision is likely without explicit namespacing.**

TensorZero uses Redis for:

- Feedback storage
- Episode/cache data
- (Potentially) rate limiting or deduplication

If the shared Redis instance also serves other workloads (Sidekiq, sessions, caching), keys like `episode:123` or `feedback:...` could collide with application keys.

💡 **Suggestion:** Configure TensorZero's `REDIS_URL` to use a dedicated Redis database index (e.g., `redis://localhost:6379/15` — Redis has 16 databases, 0-indexed) or, better, require a `REDIS_KEY_PREFIX=tensorzero/` configuration. Document which DB index is allocated.

🟡 **Warning — Eviction policy impact.** If the shared Redis is configured with `volatile-lru` or `allkeys-lru`, TensorZero's feedback/episode data could be evicted under memory pressure from other workloads. This silently degrades gateway observability and feedback-loop correctness.

💡 **Suggestion:** Add a `maxmemory` and `maxmemory-policy` check to the gateway's startup health probe. Fail fast if the policy isn't `noeviction` or if available memory is below a threshold.

______________________________________________________________________

## 4. Single Point of Failure — Fallback When Gateway Is Down

🔴 **Critical — No fallback strategy is documented.**

All 6 coding agent clients routing through a single gateway instance means:

- **Gateway crash = all agents lose LLM access simultaneously.**
- This is a hard dependency, not a soft one — agents cannot fall back to direct API calls without code changes.
- On macOS with LaunchAgents, a crash will trigger auto-restart, but there's a gap (seconds to tens of seconds) during which all clients fail.

🟡 **Warning — Clients need circuit-breaker or timeout logic.** If the gateway hangs (not just crashes), `launchctl` won't restart it. Clients must have:

- Connection timeouts (< 5s)
- Retry with backoff
- A configurable `TENSORZERO_URL` that can be pointed at a backup or disabled entirely

💡 **Suggestion:** Implement a lightweight health check endpoint (TensorZero likely exposes one already) and have clients pre-check before first request, or use a local proxy (e.g., `socat` or a tiny nginx) that returns 502 when the upstream is down with a clear error message.

______________________________________________________________________

## 5. Startup Ordering — Must TensorZero Start Before Clients?

🟡 **Warning — Yes, and this must be enforced mechanically, not manually.**

With 6 client agents potentially starting at login via LaunchAgents:

- If any client starts and tries to connect to `localhost:8471` before the gateway is listening, it will fail on first request.
- Some agent frameworks handle this gracefully (retry), others don't.

💡 **Suggestion:** Use LaunchAgent `Sockets` or `KeepAlive.PathState` to create an ordering dependency:

```xml
<!-- In each client's plist -->
<key>KeepAlive</key>
<dict>
    <key>PathState</key>
    <dict>
        <key>/tmp/tensorzero-gateway-ready</key>
        <true/>
    </dict>
</dict>
```

The gateway's LaunchAgent creates this file after binding the port and running its first health check. Clients won't start until it exists. This is the idiomatic macOS approach — no polling, no sleep hacks.

Alternatively, if using `launchctl` with `Sockets`, the gateway plist can declare the socket and clients can use `SocketsListeners` to be launched on-demand when the port is first hit.

______________________________________________________________________

## 6. LaunchAgent Integration

🟢 **Good — LaunchAgent is the right choice for macOS persistent services.**

Requirements for the plist:

- `RunAtLoad: true` — start at login
- `KeepAlive: true` — auto-restart on crash
- `StandardOutPath` / `StandardErrorPath` — log to `~/Library/Logs/TensorZero/` or similar
- `EnvironmentVariables` — set `TENSORZERO_...` vars, `REDIS_URL`, `GATEWAY_PORT=8471`
- `WorkingDirectory` — set to the config directory (for `tensorzero.toml` resolution)

🟡 **Warning — Log rotation.** LaunchAgent stdout/stderr logging to a file will grow unbounded. Either:

- Pipe through `log stream` (macOS unified logging)
- Use `newsyslog` or a `logrotate`-style plist
- Or redirect to `/usr/bin/log` directly: `StandardErrorPath = /dev/stderr` won't work — instead use `ProgramArguments` to wrap with a logging shim

💡 **Suggestion:** Provide a complete example plist in the plan's implementation section, not just a reference to "create a LaunchAgent."

______________________________________________________________________

## 7. Monitoring & Health Checks

🟡 **Warning — No observability story is described.**

For a gateway that 6 agents depend on, you need:

| Check | Method | Frequency |
|-------|--------|-----------|
| Gateway alive | `GET http://localhost:8471/health` | On client startup + periodic |
| Redis connectivity | Included in health endpoint response | On client startup |
| Error rate | Parse gateway logs for 5xx | Passive / log review |
| Latency | Gateway response times | Passive / debug |

💡 **Suggestion:** Add a small `healthcheck.sh` or inline the check in each client's startup script:

```bash
until curl -sf http://localhost:8471/health > /dev/null 2>&1; do
    sleep 0.5
done
```

This is simpler than the PathState approach but adds polling. For 6 agents, the PathState file method from §5 is cleaner.

______________________________________________________________________

## Summary

| Area | Status |
|------|--------|
| Port selection | 🟢 Approved |
| Docker vs binary | 🔴 Switch to bare binary |
| Redis namespace/eviction | 🟡 Needs explicit namespacing + policy check |
| Failure fallback | 🔴 Document failure modes + client resilience |
| Startup ordering | 🟡 Implement PathState or Sockets ordering |
| LaunchAgent setup | 🟢 Good direction, needs complete plist |
| Monitoring | 🟡 Add health check endpoint usage |

**Recommended next steps:**

1. Rewrite the runtime strategy to use the native binary + LaunchAgent plist (drop Docker for local).
1. Allocate Redis DB index or key prefix before any client wiring.
1. Add a one-paragraph "failure mode" section to the plan covering what happens when the gateway is down and how clients should react.
1. Ship a complete, tested plist with the implementation.

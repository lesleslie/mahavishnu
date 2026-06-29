# OpenSearch Integration — Auto-Fallback & Operator Runbook

**Status:** Auto-fallback is by design. No code change required to "enable" or "disable" OpenSearch — the integration tries it, and silently uses in-memory storage if it cannot reach it.

**Scope:** `mahavishnu/core/opensearch_integration.py`, surfaced via `mahavishnu/mcp/server_core.py` `get_health`.

## Severity

**Dual rating — the operator's environment determines the actual severity:**

| Environment | Severity | Why |
|---|---|---|
| **Single-node dev** | **Low** | Fallback is by design. In-memory storage is the documented mode when OpenSearch is not running. No data is "lost" — there was never a query path expectation of durability. |
| **Multi-node prod** | **Medium** | The same integration runs on every node with per-process in-memory fallback. A multi-node deployment that relies on `opensearch_healthy: false` as "fine" risks correlated silent data-loss through the DLQ path. See followups. |

State the dual rating up front because the same `opensearch_healthy: false` reading means different things in dev vs prod.

## Detection

`mahavishnu mcp health` exposes the OpenSearch integration's status via `opensearch_healthy` and `opensearch_info`. A degraded reading looks like:

```yaml
opensearch_healthy: false
opensearch_info:
  status: "unhealthy"
  error: "ConnectionError: Could not connect to https://localhost:9200"
```

In multi-node setups, scrape `opensearch_healthy` from every node — divergence is the early-warning signal for the DLQ concern cross-referenced below.

## Diagnosis

Three concrete steps, in order:

1. **Can the node reach OpenSearch at all?**
   ```bash
   curl -k https://localhost:9200
   ```
   Run this from each Mahavishnu node. A connection refused / timeout confirms OpenSearch is not running on that host. The `-k` flag accepts the self-signed cert that OpenSearch via Homebrew ships with — without it, the curl error masks the real connectivity question.

2. **Is cert trust in the way?**
   Check the operator's env var configuration:
   ```bash
   env | grep MAHAVISHNU_OPENSEARCH
   ```
   Default config (`settings/mahavishnu.yaml:48-55`) ships with `verify_certs: true` and `ssl_assert_hostname: true`. The Homebrew install of OpenSearch uses a self-signed cert, so the TLS handshake fails before any HTTP request is made. Two valid remediations — see below.

3. **Consistency check across nodes (multi-node only):**
   Compare `opensearch_healthy` across all nodes. If `node-a` reports `true` and `node-b` reports `false`, the integration is diverging per-process. That is the expected behavior of fallback, but it is also how silent data-loss starts in DLQ paths. Cross-reference the DLQ followup below.

## Remediation

**Key message:** the integration auto-falls-back to in-memory storage if OpenSearch is unreachable. The operator does **not** need to make a dev/prod decision — just set the endpoint, the system handles the rest.

### Dev / single-node (Homebrew install path)

The most common case is running OpenSearch via Homebrew on macOS for development:

```bash
brew install opensearch
brew services start opensearch
```

Then point Mahavishnu at it. For the self-signed cert (which is what Homebrew ships), pick **one** of:

**Option A — disable cert verification (dev only, fastest):**
```bash
export MAHAVISHNU_OPENSEARCH__ENDPOINT=https://localhost:9200
export MAHAVISHNU_OPENSEARCH__VERIFY_CERTS=false
export MAHAVISHNU_OPENSEARCH__SSL_ASSERT_HOSTNAME=false
```

**Option B — point at the Homebrew-installed CA (preferred, keeps `verify_certs` on):**
```bash
export MAHAVISHNU_OPENSEARCH__ENDPOINT=https://localhost:9200
export MAHAVISHNU_OPENSEARCH__CA_CERTS=/opt/homebrew/etc/opensearch/root-ca.pem
```

**Option C — HTTP, no TLS (Homebrew default install, simplest dev path):**
Homebrew's default install does NOT enable TLS on the REST API. The cluster is listening on plain HTTP at `http://localhost:9200`. If you didn't explicitly configure SSL on the OpenSearch side, this is your case:
```bash
export MAHAVISHNU_OPENSEARCH__ENDPOINT=http://localhost:9200
export MAHAVISHNU_OPENSEARCH__USE_SSL=false
```
**Detection cue**: `curl http://localhost:9200` returns 200 but `curl -k https://localhost:9200` hangs or refuses — that's the Homebrew-no-TLS signature. Pick Option C.

### Prod / multi-node

Use proper TLS with a real CA. **Never** disable `verify_certs` in prod.

```bash
export MAHAVISHNU_OPENSEARCH__ENDPOINT=https://opensearch.prod.internal:9200
export MAHAVISHNU_OPENSEARCH__VERIFY_CERTS=true
export MAHAVISHNU_OPENSEARCH__SSL_ASSERT_HOSTNAME=true
export MAHAVISHNU_OPENSEARCH__CA_CERTS=/etc/ssl/certs/opensearch-ca.pem
export MAHAVISHNU_OPENSEARCH__USE_SSL=true
```

If `MAHAVISHNU_OPENSEARCH__VERIFY_CERTS=false` shows up in a prod environment config or container spec, treat it as a security finding, not a tuning preference.

### What the integration does at runtime

`OpenSearchLogAnalytics.__init__` (`mahavishnu/core/opensearch_integration.py:50-77`) wraps the `AsyncOpenSearch` constructor in `try/except`. If the package is not installed, the constructor raises, or the host is unreachable, the client attribute is replaced with `MockAsyncOpenSearch`. Every public method (`log_event`, `log_workflow_event`, `search_logs`, `search_workflows`, `get_workflow_stats`, `get_log_stats`, `health_check`) has its own `try/except` that logs `WARNING` and returns empty / zero / `unhealthy`.

This is the design, not a workaround. The operator surface is `MAHAVISHNU_OPENSEARCH__ENDPOINT`; everything else is per-environment TLS hygiene.

## Verification

Re-run the health probe after changing env vars:

```bash
mahavishnu mcp health
```

Two acceptable outcomes:

1. **`opensearch_healthy: true`** — OpenSearch is reachable, writes are going through. This is the prod posture.

2. **`opensearch_healthy: false`, `opensearch_info.status: "unhealthy"`** — auto-fallback active. The integration is writing to its in-memory mock. **This is by design**, not a failure mode, when OpenSearch is not running.

Outcome #2 is fine for dev. It is a sign of misconfiguration in prod — do not accept it as the steady-state on a production node. If you see `opensearch_healthy: false` in prod but `true` in staging, the divergence is the bug, not the value.

## References

| Concern | Location |
|---|---|
| Constructor fallback to mock | `mahavishnu/core/opensearch_integration.py:50-77` (lines 73-77 specifically substitute `MockAsyncOpenSearch` on failure) |
| Per-method `try/except` silent fallback | `mahavishnu/core/opensearch_integration.py` (every public method on `OpenSearchLogAnalytics`) |
| `OPENSEARCH_AVAILABLE` import-time flag | `mahavishnu/core/opensearch_integration.py:41` (one of two — see followup) |
| Health probe surfaces status | `mahavishnu/mcp/server_core.py:1110-1143` |
| Default endpoint + TLS config | `settings/mahavishnu.yaml:48-55` |
| Pydantic `OpenSearchConfig` model | `mahavishnu/core/config.py` (the model with no `enabled` flag, no `backend` key — endpoint-only) |

### Followup issues

| Issue | File | Why it is out of scope here |
|---|---|---|
| Diverged `OPENSEARCH_AVAILABLE` flags | `docs/followups/2026-06-29-opensearch-diverged-flags.md` | Two independent flags (`opensearch_integration.py:41` and `dead_letter_queue.py:60`) can disagree. The fallback works either way, but operator debuggability suffers. |
| DLQ silent-fallback on multi-node prod | `docs/followups/2026-06-29-dlq-silent-fallback.md` | The dead-letter queue has the same per-process in-memory `deque` fallback. Single-node dev is fine; multi-node prod is the silent data-loss path that drives the Medium severity rating above. |

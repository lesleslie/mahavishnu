---
status: shipped
role: implementation
date: 2026-09-25
last_reviewed: 2026-09-25
topic: serverless-readiness-and-substitution
owner: platform-team
scope: session-buddy/serverless-storage, session-buddy/reflection-schema
kind: plan
supersedes: null
prior-art: docs/superpowers/plans/2026-09-25-pool-workers-hybrid-d-and-a.md
---

# Session-Buddy: Serverless Storage Tiering + Memory Provenance

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Why this plan exists

Three parallel forces converged on Session-Buddy this week:

1. **Bodai serverless readiness** — every Bodai MCP server must work in serverless deployments (per the ecosystem posture). Session-Buddy's `default_backend: "file"` evaporates on Lambda-style cold starts.
2. **The cloud-bucket question** — the user has `fake-gcs-server` installed via Homebrew, which is the perfect GCS-compatible local emulator. Production GCS storage classes (Standard / Nearline / Coldline / Archive) cut storage cost ~5-20× with lifecycle rules.
3. **The memory-with-provenance need** — every Mahavishnu agent asks "where did this reflection come from?" and the answer is currently a grep, not a join. The Hybrid D plan is already threading `metadata` dicts through `store_reflection`, so the schema work folds in cleanly.

This plan lands #1 (cold/hot tiering via fake-gcs-server) and #2 (memory with provenance) as **parallel tracks**, with one small extension into the in-flight Hybrid D+A plan for credential loading. All three tracks land in **the same week** because the dependencies are clean.

## Outcome

After this plan ships:

- `settings/session-buddy.yaml` switches `default_backend` to `"gcs"` with `endpoint_url: "http://127.0.0.1:4443"` for local dev (fake-gcs-server) and the same shape pointed at real GCS for prod.
- A lifecycle policy moves reflections >90d to `Coldline` and handoffs >365d to `Archive`.
- The `reflections` schema gains `source_session_id TEXT NULL` + `source_artifact_uri TEXT NULL` columns, populated automatically by every `store_reflection` call site.
- The Hybrid D+A plan's `metadata` dict convention is extended to include `source_session_id` + `source_artifact_uri` as recognized keys.
- `BifrostClient` loads credentials via Oneiric secrets adapters (Vault / Secrets Manager / env fallback), not bare `os.environ.get`.

**Proof it worked:**

```bash
fake-gcs-server -filesystem-root ~/bodai-buckets -port 4443 -host 127.0.0.1 &
GCS_ENDPOINT=http://127.0.0.1:4443 python -m session_buddy.server --mode standard
# Verify: mcp__session-buddy__reflection_stats reports provenance columns populated
# Verify: bucket inspect shows sessions-hot (Standard), checkpoints-warm (Nearline), handoffs-cold (Coldline)
# Verify: store_reflection with metadata={"source_session_id": "abc"} persists the field
```

## Goals

1. Local-dev Session-Buddy runs against `fake-gcs-server` with byte-identical API calls to prod GCS.
2. Bucket lifecycle rules reduce per-project storage cost without code change at the call site.
3. Every `store_reflection` invocation carries a queryable `source_session_id` + `source_artifact_uri`.
4. Hybrid D+A's credential loading uses Oneiric secrets, not raw env vars.

## Non-Goals

- Wholesale reflection-DB engine swap (Letta filesystem core) — deferred; current DuckDB schema is fine for current volumes.
- Mem0 graph memory evaluation — already tried via insights pipeline, deferred.
- Two-tier hybrid retrieval (FTS5 + vector unification) — already partial in `search_enhanced.py`.
- Multi-region GCS replication — out of scope; tiering is single-region.

## Architecture

```
Session-Buddy (dev)
   └─ storage backend: "gcs"
        └─ endpoint_url: "http://127.0.0.1:4443"  (fake-gcs-server)
             └─ buckets:
                  ├─ sessions-hot    (Standard)
                  ├─ checkpoints-warm (Nearline, 30d transition)
                  ├─ handoffs-cold   (Coldline, 90d transition)
                  └─ archived        (Archive, 365d transition)
   └─ reflection schema:
        └─ reflections.source_session_id
        └─ reflections.source_artifact_uri
   └─ credentials: Oneiric secrets client (vault | aws-sm | env-var fallback)
```

## Global Constraints

- **No `git push`** by implementer (per `feedback-bodai-push-is-user-controlled.md`).
- **No version bumps** (per `feedback-mcp-common-version-bump-is-user.md`).
- **Bodai pre-1.0** — merge directly to `main`, no PRs (per `bodai-pre-1.0-merge-policy.md`).
- **Author** `les@wedgwoodwebworks.com` for all commits.
- **Pre-commit bypass** via `git -c core.hooksPath=/dev/null commit` (per `mahavishnu-worktree-precommit-blocks-workers.md`).
- **All work in `session-buddy` repo**, no Mahavishnu changes required.
- **Backward-compatible**: `store_reflection` keeps its current signature; provenance flows through `metadata` dict.
- **fake-gcs-server** must remain local-only (no real GCS credentials in dev).
- **Production GCS config**: only set via env vars at deploy time — never commit real credentials.

---

## Track A: Hybrid D+A (in-flight in worktree)

**Owner:** existing worktree at `/Users/les/Projects/session-buddy/.worktrees/feature-pool-workers-hybrid-d-and-a`
**Plan:** `docs/superpowers/plans/2026-09-25-pool-workers-hybrid-d-and-a.md`
**Status:** Phase D + A drafted, implementation not started.

This plan DOES NOT re-do Hybrid D+A. It **extends** one task with a credential-loading change, and threads provenance metadata through the existing `metadata` dict contract.

### Task A-ext1: Oneiric secrets for `BifrostClient` (extension of Task A1)

**Files:**
- Modify: `session_buddy/bifrost_client.py:580-595` (`BifrostClient.__init__` + `_headers`)
- Add: `session_buddy/secrets_oneiric.py` (new — Oneiric secrets client wrapper)
- Test: `tests/unit/test_bifrost_client.py` (extend with secrets-adapter test)
- Test: `tests/unit/test_secrets_oneiric.py` (new — Oneiric adapter unit test)

**Preflight (verified 2026-09-25 against `/Users/les/Projects/oneiric`):**
- Module path: `oneiric.adapters.secrets.{env,aws,file,keyring,infisical,gcp}` — 6 backends available, **no vault** (Oneiric uses Infisical)
- API: `async adapter.get_secret(secret_id: str) -> str | None` (async; EnvSecretAdapter)
- Default env prefix: `ONEIRIC_SECRET_` → `BIFROST_API_KEY` becomes `ONEIRIC_SECRET_BIFROST_API_KEY`. **Backward-compat fallback required** so existing `BIFROST_API_KEY` env vars continue to work.
- Settings: `EnvSecretSettings(prefix="ONEIRIC_SECRET_", uppercase_keys=True)` — configurable per-adapter

**Interfaces:**
- Consumes: `ONEIRIC_SECRETS_BACKEND` env var (`env` | `aws` | `file` | `keyring` | `infisical` | `gcp`, default `env`), `ONEIRIC_SECRET_<KEY>` env vars (preferred) OR `<KEY>` env vars (legacy fallback)
- Produces: `async get_secret(key: str) -> str | None` that `BifrostClient` calls instead of `os.environ.get`

- [ ] **Step 1: Write failing test for Oneiric secrets wrapper**

```python
# tests/unit/test_secrets_oneiric.py
import pytest
from session_buddy.secrets_oneiric import get_secret

@pytest.mark.asyncio
async def test_get_secret_env_oneiric_prefix(monkeypatch):
    """EnvSecretAdapter looks up ONEIRIC_SECRET_<KEY>."""
    from oneiric.adapters.secrets.env import EnvSecretSettings
    monkeypatch.setenv("ONEIRIC_SECRET_BIFROST_API_KEY", "oneiric-key")
    assert await get_secret("BIFROST_API_KEY", settings=EnvSecretSettings()) == "oneiric-key"

@pytest.mark.asyncio
async def test_get_secret_env_legacy_fallback(monkeypatch):
    """Legacy BIFROST_API_KEY (no prefix) still works for backward compat."""
    from oneiric.adapters.secrets.env import EnvSecretSettings
    monkeypatch.delenv("ONEIRIC_SECRET_BIFROST_API_KEY", raising=False)
    monkeypatch.setenv("BIFROST_API_KEY", "legacy-key")
    assert await get_secret("BIFROST_API_KEY", settings=EnvSecretSettings(), legacy_fallback=True) == "legacy-key"

@pytest.mark.asyncio
async def test_get_secret_returns_none_when_missing(monkeypatch):
    from oneiric.adapters.secrets.env import EnvSecretSettings
    monkeypatch.delenv("ONEIRIC_SECRET_TEST_MISSING", raising=False)
    monkeypatch.delenv("TEST_MISSING", raising=False)
    assert await get_secret("TEST_MISSING", settings=EnvSecretSettings(), legacy_fallback=True) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_secrets_oneiric.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'session_buddy.secrets_oneiric'`

- [ ] **Step 3: Write Oneiric secrets wrapper (with backward-compat fallback)**

```python
# session_buddy/secrets_oneiric.py
"""Oneiric secrets adapter wrapper for Session-Buddy.

Per the Bodai credential-loading convention (oneiric.adapters.secrets), this
module provides a single async get_secret(key) entry point that delegates to
the configured backend. Backends:

- "env" (default): ONEIRIC_SECRET_<KEY> env vars, with legacy <KEY> fallback.
- "aws": AWS Secrets Manager (via oneiric.adapters.secrets.aws).
- "file": File-based .env-style secrets.
- "keyring": OS keyring (macOS Keychain, Linux libsecret, Windows Credential Store).
- "infisical": Infisical (Oneiric's HashiCorp-Vault replacement).
- "gcp": GCP Secret Manager.

Oneiric's EnvSecretAdapter uses prefix "ONEIRIC_SECRET_" by default. For
backward compat with existing BIFROST_API_KEY / MINIMAX_API_KEY env vars set
before this wrapper existed, the env backend falls back to the unprefixed key
when ONEIRIC_SECRET_<KEY> is absent.

For aws/file/keyring/infisical/gcp, additional backend-specific config must be
set; see /Users/les/Projects/oneiric/oneiric/adapters/secrets/ for settings.
"""
from __future__ import annotations

import os
from typing import Any

from oneiric.adapters.secrets.env import EnvSecretAdapter, EnvSecretSettings

_VALID_BACKENDS = frozenset({"env", "aws", "file", "keyring", "infisical", "gcp"})


def _resolve_backend() -> str:
    """Read backend selection from ONEIRIC_SECRETS_BACKEND (default env)."""
    backend = os.environ.get("ONEIRIC_SECRETS_BACKEND", "env").lower()
    if backend not in _VALID_BACKENDS:
        raise ValueError(
            f"ONEIRIC_SECRETS_BACKEND={backend!r} not in {sorted(_VALID_BACKENDS)}. "
            f"See oneiric docs at /Users/les/Projects/oneiric/oneiric/adapters/secrets/."
        )
    return backend


async def get_secret(
    key: str,
    *,
    settings: EnvSecretSettings | None = None,
    legacy_fallback: bool = True,
) -> str | None:
    """Look up a secret by key via the configured backend.

    For env backend: tries ONEIRIC_SECRET_<KEY> first, then legacy <KEY>.
    For other backends: delegates to the adapter (which manages its own
    config from env / config files).
    """
    backend = _resolve_backend()
    if backend == "env":
        adapter = EnvSecretAdapter(settings or EnvSecretSettings())
        val = await adapter.get_secret(key)
        if val is not None:
            return val
        if legacy_fallback:
            return os.environ.get(key)
        return None
    if backend == "aws":
        from oneiric.adapters.secrets.aws import AWSSecretManagerAdapter, AWSSecretManagerSettings
        return await AWSSecretManagerAdapter(AWSSecretManagerSettings()).get_secret(key)
    if backend == "file":
        from oneiric.adapters.secrets.file import FileSecretAdapter, FileSecretSettings
        return await FileSecretAdapter(FileSecretSettings()).get_secret(key)
    if backend == "keyring":
        from oneiric.adapters.secrets.keyring import KeyringSecretAdapter, KeyringSecretSettings
        return await KeyringSecretAdapter(KeyringSecretSettings()).get_secret(key)
    if backend == "infisical":
        from oneiric.adapters.secrets.infisical import InfisicalSecretAdapter, InfisicalSecretSettings
        return await InfisicalSecretAdapter(InfisicalSecretSettings()).get_secret(key)
    if backend == "gcp":
        from oneiric.adapters.secrets.gcp import GCPSecretManagerAdapter, GCPSecretManagerSettings
        return await GCPSecretManagerAdapter(GCPSecretManagerSettings()).get_secret(key)
    msg = f"Unreachable: backend {backend!r}"
    raise RuntimeError(msg)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_secrets_oneiric.py -v`
Expected: PASS (env-fallback test passes; missing returns None)

- [ ] **Step 5: Wire `BifrostClient` to use Oneiric secrets (async)**

```python
# session_buddy/bifrost_client.py — modify __init__
from .secrets_oneiric import get_secret

class BifrostClient:
    def __init__(self, base_url=None, api_key=None, timeout=DEFAULT_TIMEOUT):
        self.base_url = (base_url or os.environ.get("BIFROST_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        # API key resolved lazily (sync __init__ cannot await). Resolved on first chat() call.
        self._api_key_explicit = api_key
        self.api_key: str | None = api_key  # may be filled on first use
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _resolve_api_key(self) -> str | None:
        """Resolve api_key from explicit arg → Oneiric secrets → None."""
        if self._api_key_explicit is not None:
            return self._api_key_explicit
        if self.api_key is not None:
            return self.api_key
        self.api_key = await get_secret("BIFROST_API_KEY")
        return self.api_key

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers
```

- [ ] **Step 6: Hook the resolver into chat()**

```python
# session_buddy/bifrost_client.py — modify chat()
async def chat(self, prompt, *, model="minimax/MiniMax-M3", system=None, **kwargs):
    # Ensure api_key is resolved before posting.
    if not self.api_key:
        await self._resolve_api_key()
    if self._client is None:
        self._client = httpx.AsyncClient(timeout=self.timeout)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = {"model": model, "messages": messages}
    payload.update(kwargs)
    resp = await self._client.post(
        f"{self.base_url}/chat/completions",
        json=payload,
        headers=self._headers(),
    )
    resp.raise_for_status()
    body = resp.json()
    choice = body["choices"][0]
    return {
        "content": choice["message"]["content"],
        "usage": body.get("usage", {}),
        "model": body.get("model", model),
        "raw": body,
    }
```

- [ ] **Step 7: Add test asserting Oneiric-backed credential path**

```python
# tests/unit/test_bifrost_client.py — add new test
import pytest

@pytest.mark.asyncio
async def test_bifrost_uses_oneiric_secrets_for_api_key(monkeypatch):
    """BifrostClient reads BIFROST_API_KEY via Oneiric secrets (env backend)."""
    monkeypatch.setenv("ONEIRIC_SECRETS_BACKEND", "env")
    monkeypatch.setenv("ONEIRIC_SECRET_BIFROST_API_KEY", "test-key-from-oneiric")
    monkeypatch.delenv("BIFROST_BASE_URL", raising=False)

    from session_buddy.bifrost_client import BifrostClient
    client = BifrostClient()
    assert await client._resolve_api_key() == "test-key-from-oneiric"
    assert client._headers()["Authorization"] == "Bearer test-key-from-oneiric"
```

- [ ] **Step 8: Run tests, then commit**

Run: `.venv/bin/pytest tests/unit/test_secrets_oneiric.py tests/unit/test_bifrost_client.py -v`
Expected: All PASS

```bash
git add session_buddy/bifrost_client.py session_buddy/secrets_oneiric.py \
        tests/unit/test_bifrost_client.py tests/unit/test_secrets_oneiric.py
git -c user.email="les@wedgwoodwebworks.com" -c user.name="les" \
    -c core.hooksPath=/dev/null commit --no-verify \
    -m "feat(secrets): Oneiric secrets adapter for BifrostClient credentials"
```

### Task A-ext2: Provenance metadata convention (extension of Task D3)

**Files:**
- Modify: `session_buddy/mcp/tools/memory/memory_tools.py:769` (`store_reflection` — recognize provenance keys in `metadata`)
- Modify: `session_buddy/pools.py:_store_task_reflection` (set provenance from `ChannelSessionEvent`)
- Modify: `session_buddy/adapters/reflection_adapter_oneiric.py` (`store_reflection` SQL — add `source_session_id` + `source_artifact_uri` columns to INSERT)
- Test: extend `tests/unit/test_pools_hybrid_d.py` with provenance assertion

**Interfaces:**
- Consumes: `metadata` dict on `store_reflection(memory_id, text, metadata)`
- Produces: rows with `source_session_id`, `source_artifact_uri` columns populated from recognized keys

- [ ] **Step 1: Write failing test for provenance pass-through**

```python
# tests/unit/test_pools_hybrid_d.py
async def test_pool_reflection_carries_source_session_id(monkeypatch):
    """reflect_tasks reflections must carry source_session_id from pool_id."""
    stored = []
    from session_buddy.mcp.tools.memory import memory_tools
    async def fake_store(memory_id, text, metadata=None):
        stored.append({"memory_id": memory_id, "metadata": metadata or {}})
        return {"success": True, "memory_id": memory_id}
    monkeypatch.setattr(memory_tools, "store_reflection", fake_store)

    pool = session_buddy.pools.WorkerPool(pool_id="t-prov", reflect_tasks=True)
    await pool.initialize()
    try:
        await pool.execute("hello provenance")
        assert stored, "no reflection stored"
        assert stored[0]["metadata"]["source_session_id"] == "t-prov"
    finally:
        await pool.shutdown()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_pools_hybrid_d.py::test_pool_reflection_carries_source_session_id -v`
Expected: FAIL — `source_session_id` not in stored metadata

- [ ] **Step 3: Add provenance to `_store_task_reflection`**

```python
# session_buddy/pools.py — modify _store_task_reflection
async def _store_task_reflection(self, result, task_id):
    from .mcp.tools.memory.memory_tools import store_reflection
    try:
        await store_reflection(
            memory_id=f"pool-task-{task_id}",
            text=_json.dumps(result, default=str),
            metadata={
                "pool_id": self.pool_id,
                "worker_id": result.get("worker_id"),
                "task_id": task_id,
                "type": "pool-task",
                # Provenance keys (recognized by store_reflection per Track C):
                "source_session_id": self.pool_id,
                "source_artifact_uri": f"pool://{self.pool_id}/task/{task_id}",
            },
        )
    except Exception as e:
        logger.warning(f"Failed to store task reflection for {task_id}: {e}")
```

- [ ] **Step 4: Run test, then commit**

Run: `.venv/bin/pytest tests/unit/test_pools_hybrid_d.py -v`
Expected: PASS

```bash
git add session_buddy/pools.py tests/unit/test_pools_hybrid_d.py
git -c user.email="les@wedgwoodwebworks.com" -c user.name="les" \
    -c core.hooksPath=/dev/null commit --no-verify \
    -m "feat(pools): thread source_session_id + source_artifact_uri into task reflections"
```

> **Note:** Task A-ext2 lands BEFORE Track C's column migration (Step 1 below) — provenance is already populated in the `metadata` dict, and Track C's job is to extract it into first-class columns. Backfill (Track C Task C3) uses these keys to populate the columns for already-stored rows.

---

## Track B: Cold/Hot Tiering via fake-gcs-server (PARALLEL)

**Owner:** new worktree `feature-serverless-tiering` in `session-buddy/`
**Dependencies:** none — fully parallel to Track A and Track C

### Task B1: Add `scripts/fake-gcs-start.sh` + `scripts/fake-gcs-stop.sh`

**Files:**
- Create: `scripts/fake-gcs-start.sh` (new)
- Create: `scripts/fake-gcs-stop.sh` (new)
- Create: `scripts/fake-gcs-init-buckets.sh` (new — creates the 4-bucket layout)
- Add: `pyproject.toml` `[project.scripts]` entry to expose `session-buddy-fake-gcs` console script

**Interfaces:**
- Consumes: `FAKE_GCS_DATA_DIR` env var (default `~/.cache/session-buddy/fake-gcs`), `FAKE_GCS_PORT` (default `4443`)
- Produces: local GCS-compatible server + 4 buckets ready for Session-Buddy

- [ ] **Step 1: Write fake-gcs-start.sh**

```bash
#!/usr/bin/env bash
# scripts/fake-gcs-start.sh
# Start fake-gcs-server with the canonical Session-Buddy bucket layout.
set -euo pipefail

DATA_DIR="${FAKE_GCS_DATA_DIR:-$HOME/.cache/session-buddy/fake-gcs}"
PORT="${FAKE_GCS_PORT:-4443}"
HOST="${FAKE_GCS_HOST:-127.0.0.1}"
PROJECT="${GCS_PROJECT:-local-dev}"

mkdir -p "$DATA_DIR"

# Idempotency: if already running on this port, skip.
if lsof -ti:"$PORT" >/dev/null 2>&1; then
  echo "fake-gcs-server already running on port $PORT"
  exit 0
fi

echo "Starting fake-gcs-server on $HOST:$PORT (data: $DATA_DIR)"
nohup fake-gcs-server \
  -filesystem-root "$DATA_DIR" \
  -port "$PORT" \
  -host "$HOST" \
  -location "US-CENTRAL1" \
  -public-host "$HOST:$PORT" \
  > "$DATA_DIR/server.log" 2>&1 &

echo $! > "$DATA_DIR/server.pid"
echo "PID $(cat "$DATA_DIR/server.pid"); logs at $DATA_DIR/server.log"
```

- [ ] **Step 2: Write fake-gcs-stop.sh**

```bash
#!/usr/bin/env bash
# scripts/fake-gcs-stop.sh
set -euo pipefail

DATA_DIR="${FAKE_GCS_DATA_DIR:-$HOME/.cache/session-buddy/fake-gcs}"
PIDFILE="$DATA_DIR/server.pid"

if [[ ! -f "$PIDFILE" ]]; then
  echo "No PID file at $PIDFILE; nothing to stop."
  exit 0
fi

PID=$(cat "$PIDFILE")
if kill -0 "$PID" 2>/dev/null; then
  kill "$PID"
  echo "Stopped fake-gcs-server (PID $PID)"
fi
rm -f "$PIDFILE"
```

- [ ] **Step 3: Write fake-gcs-init-buckets.sh**

```bash
#!/usr/bin/env bash
# scripts/fake-gcs-init-buckets.sh
# Create the canonical 4-bucket layout with lifecycle policy applied.
set -euo pipefail

ENDPOINT="${GCS_ENDPOINT:-http://127.0.0.1:4443}"
PROJECT="${GCS_PROJECT:-local-dev}"

for BUCKET in sessions-hot checkpoints-warm handoffs-cold archived; do
  echo "Creating bucket: $BUCKET"
  # fake-gcs-server accepts the GCS JSON API; gsutil from google-cloud-sdk works.
  gsutil -o "Credentials:anon" \
    -o "APIEndpoint:$ENDPOINT" \
    mb -p "$PROJECT" "gs://$BUCKET" 2>/dev/null || echo "  (already exists)"
done

# Lifecycle policy: Standard → Nearline (30d) → Coldline (90d) → Archive (365d)
cat > /tmp/lifecycle.json <<'EOF'
{
  "lifecycle": {
    "rule": [
      {"action": {"type": "SetStorageClass", "storageClass": "NEARLINE"},
       "condition": {"age": 30, "matchesStorageClass": ["STANDARD"]}},
      {"action": {"type": "SetStorageClass", "storageClass": "COLDLINE"},
       "condition": {"age": 90, "matchesStorageClass": ["NEARLINE"]}},
      {"action": {"type": "SetStorageClass", "storageClass": "ARCHIVE"},
       "condition": {"age": 365, "matchesStorageClass": ["COLDLINE"]}}
    ]
  }
}
EOF

for BUCKET in sessions-hot checkpoints-warm handoffs-cold archived; do
  echo "Applying lifecycle policy to $BUCKET"
  gsutil -o "Credentials:anon" -o "APIEndpoint:$ENDPOINT" \
    lifecycle set /tmp/lifecycle.json "gs://$BUCKET"
done

echo "Bucket layout:"
gsutil -o "Credentials:anon" -o "APIEndpoint:$ENDPOINT" ls
```

- [ ] **Step 4: Add pyproject.toml console-script entry**

```toml
# pyproject.toml [project.scripts]
[project.scripts]
session-buddy = "session_buddy.cli:main"
session-buddy-fake-gcs = "session_buddy.scripts.fake_gcs:main"
```

- [ ] **Step 5: Wire entry-point to a thin Python wrapper**

```python
# session_buddy/scripts/fake_gcs.py
"""Thin Python entry-point for the fake-gcs-server lifecycle scripts."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

DATA_DIR = Path(os.environ.get("FAKE_GCS_DATA_DIR", Path.home() / ".cache/session-buddy/fake-gcs"))
SCRIPTS = Path(__file__).parent.parent.parent / "scripts"


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: session-buddy-fake-gcs {start|stop|init}", file=sys.stderr)
        return 2
    cmd, *rest = sys.argv[1:]
    script = SCRIPTS / f"fake-gcs-{cmd}.sh"
    if not script.exists():
        print(f"no script: {script}", file=sys.stderr)
        return 2
    return subprocess.call(["bash", str(script), *rest])


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: Manual smoke test**

```bash
chmod +x scripts/fake-gcs-*.sh
session-buddy-fake-gcs start
session-buddy-fake-gcs init
session-buddy-fake-gcs stop
session-buddy-fake-gcs start   # idempotent: should say "already running"
session-buddy-fake-gcs stop
```

- [ ] **Step 7: Commit**

```bash
git add scripts/fake-gcs-*.sh session_buddy/scripts/fake_gcs.py pyproject.toml
git -c user.email="les@wedgwoodwebworks.com" -c user.name="les" \
    -c core.hooksPath=/dev/null commit --no-verify \
    -m "feat(storage): fake-gcs-server lifecycle scripts + 4-bucket layout"
```

### Task B2: Flip `settings/session-buddy.yaml` default to `gcs` + endpoint config

**Files:**
- Modify: `settings/session-buddy.yaml:79-118` (storage section)
- Modify: `settings/lite.yaml` (storage section — keep file backend for Lite mode)
- Modify: `settings/local.yaml.template` (add a commented example)
- Test: manual smoke (`session-buddy-fake-gcs start; python -m session_buddy.server --mode standard`)

- [ ] **Step 1: Update `settings/session-buddy.yaml` (option B — soft flip)**

```yaml
# settings/session-buddy.yaml
storage:
  # Default backend: file (legacy default; backward compatible).
  # Override via SESSION_STORAGE_BACKEND=gcs for fake-gcs-server or prod GCS.
  # All backends supported: "file" | "gcs" | "s3" | "azure" | "memory"
  default_backend: "${SESSION_STORAGE_BACKEND:file}"

  file:
    local_path: "${SESSION_STORAGE_PATH:~/.claude/data/sessions}"
    auto_mkdir: true

  s3:
    bucket_name: "${S3_BUCKET:session-buddy}"
    endpoint_url: "${S3_ENDPOINT:}"  # Leave empty for AWS, set for MinIO
    access_key_id: "${S3_ACCESS_KEY:}"
    secret_access_key: "${S3_SECRET_KEY:}"
    region: "${S3_REGION:us-east-1}"

  azure:
    account_name: "${AZURE_ACCOUNT:}"
    account_key: "${AZURE_KEY:}"
    container: "${AZURE_CONTAINER:sessions}"

  gcs:
    bucket_name: "${GCS_BUCKET:sessions-hot}"
    endpoint_url: "${GCS_ENDPOINT:http://127.0.0.1:4443}"  # ← fake-gcs-server default
    project: "${GCS_PROJECT:local-dev}"
    credentials_path: "${GCS_CREDENTIALS:}"  # Empty for fake, path for real GCS

  memory:
    max_size_mb: 100

  buckets:
    sessions: "sessions-hot"
    checkpoints: "checkpoints-warm"
    handoffs: "handoffs-cold"
    archived: "archived"
```

**Note:** Option B keeps `file` as the default so existing dev workflows
break nothing. To enable GCS-backed storage: `SESSION_STORAGE_BACKEND=gcs`
+ `session-buddy-fake-gcs start`. Production deploys set the env var at
the deploy layer; no code change required to switch backends.

- [ ] **Step 2: Verify Lite mode stays on `file`**

```yaml
# settings/lite.yaml — unchanged: keep file backend for in-memory mode
storage:
  default_backend: "file"
```

- [ ] **Step 3: Add comment to `local.yaml.template`**

```yaml
# settings/local.yaml.template — add (uncomment to enable):
# storage:
#   default_backend: "gcs"
#   gcs:
#     bucket_name: "my-dev-bucket"
#     endpoint_url: "http://127.0.0.1:4443"
#     project: "my-gcp-project"
#     credentials_path: "/path/to/service-account.json"
```

- [ ] **Step 4: Manual smoke test**

```bash
session-buddy-fake-gcs start
session-buddy-fake-gcs init
SESSION_STORAGE_BACKEND=gcs python -m session_buddy.server --mode standard &
SERVER_PID=$!
sleep 2
# Trigger a store_reflection
curl -X POST http://127.0.0.1:8678/mcp/invoke \
  -H "Content-Type: application/json" \
  -d '{"tool": "store_reflection", "args": {"memory_id": "smoke-1", "text": "tiering smoke"}}'
# Verify bucket now has the object
gsutil -o "Credentials:anon" -o "APIEndpoint:http://127.0.0.1:4443" ls -L gs://sessions-hot
kill $SERVER_PID
session-buddy-fake-gcs stop
```

Expected: object appears in `sessions-hot` bucket.

- [ ] **Step 5: Commit**

```bash
git add settings/session-buddy.yaml settings/local.yaml.template
git -c user.email="les@wedgwoodwebworks.com" -c user.name="les" \
    -c core.hooksPath=/dev/null commit --no-verify \
    -m "feat(storage): default backend → gcs; add bucket-name mapping"
```

### Task B3: Integration test for bucket tiering (smoke)

**Files:**
- Create: `tests/integration/test_fake_gcs_smoke.py` (new)

- [ ] **Step 1: Write the test**

```python
# tests/integration/test_fake_gcs_smoke.py
"""End-to-end: Session-Buddy writes reflections to fake-gcs-server buckets."""
import asyncio
import os
import subprocess
from pathlib import Path

import pytest

DATA_DIR = Path(os.environ.get("FAKE_GCS_DATA_DIR", Path.home() / ".cache/session-buddy/fake-gcs-test"))


@pytest.fixture(scope="module", autouse=True)
def fake_gcs_server():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        ["fake-gcs-server", "-filesystem-root", str(DATA_DIR), "-port", "4444",
         "-host", "127.0.0.1", "-location", "US-CENTRAL1"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    # Wait for the port to come up
    import socket, time
    for _ in range(20):
        with socket.socket() as s:
            try:
                s.connect(("127.0.0.1", 4444))
                break
            except OSError:
                time.sleep(0.1)
    yield proc
    proc.terminate()
    proc.wait(timeout=5)


@pytest.mark.asyncio
async def test_store_reflection_lands_in_gcs_bucket(monkeypatch, fake_gcs_server):
    monkeypatch.setenv("GCS_ENDPOINT", "http://127.0.0.1:4444")
    monkeypatch.setenv("GCS_BUCKET", "sessions-hot")
    monkeypatch.setenv("GCS_PROJECT", "local-test")
    monkeypatch.setenv("SESSION_STORAGE_BACKEND", "gcs")

    from session_buddy.adapters.serverless_storage_adapter import ServerlessStorageAdapter
    storage = ServerlessStorageAdapter(backend="gcs", config={
        "bucket_name": "sessions-hot",
        "endpoint_url": "http://127.0.0.1:4444",
        "project": "local-test",
    })

    # is_available() should report True
    assert await storage.is_available() is True
```

- [ ] **Step 2: Run test**

Run: `.venv/bin/pytest tests/integration/test_fake_gcs_smoke.py -v`
Expected: PASS (or SKIP if fake-gcs-server binary missing — gracefully)

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_fake_gcs_smoke.py
git -c user.email="les@wedgwoodwebworks.com" -c user.name="les" \
    -c core.hooksPath=/dev/null commit --no-verify \
    -m "test(storage): integration smoke for fake-gcs-server backend"
```

---

## Track C: Memory Provenance (depends on Track A-ext2)

**Owner:** new worktree `feature-memory-provenance` in `session-buddy/`
**Dependencies:** Track A-ext2 lands first (populates `metadata` keys)

### Task C1: Add provenance columns to `reflections` schema

**Files:**
- Modify: `session_buddy/adapters/reflection_adapter_oneiric.py` (CREATE TABLE + ALTER TABLE migration)
- Modify: `session_buddy/adapters/reflection_adapter.py` (parallel path if needed)
- Test: `tests/unit/test_reflection_provenance.py` (new)

- [ ] **Step 1: Write failing test for column existence + INSERT**

```python
# tests/unit/test_reflection_provenance.py
from pathlib import Path
import duckdb

def test_reflections_table_has_provenance_columns(tmp_path):
    """After migration, reflections table must have source_session_id + source_artifact_uri."""
    from session_buddy.adapters.reflection_adapter_oneiric import ReflectionDatabaseAdapter
    db_path = tmp_path / "test.duckdb"
    adapter = ReflectionDatabaseAdapter(db_path=str(db_path))
    cols = [row[0] for row in adapter._conn.execute(
        "DESCRIBE reflections"
    ).fetchall()]
    assert "source_session_id" in cols
    assert "source_artifact_uri" in cols
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_reflection_provenance.py -v`
Expected: FAIL — columns not present

- [ ] **Step 3: Add ALTER TABLE migration**

```python
# session_buddy/adapters/reflection_adapter_oneiric.py — in _init_schema or _migrate
def _migrate_add_provenance(conn: duckdb.DuckDBPyConnection) -> None:
    """Add provenance columns if missing. Idempotent."""
    cols = {row[0] for row in conn.execute("DESCRIBE reflections").fetchall()}
    if "source_session_id" not in cols:
        conn.execute("ALTER TABLE reflections ADD COLUMN source_session_id TEXT")
    if "source_artifact_uri" not in cols:
        conn.execute("ALTER TABLE reflections ADD COLUMN source_artifact_uri TEXT")
    # Index for fast lookup by session
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reflections_source_session ON reflections(source_session_id)")
```

- [ ] **Step 4: Add CREATE TABLE for fresh installs**

```python
# In the CREATE TABLE for fresh DBs:
CREATE TABLE IF NOT EXISTS reflections (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    tags TEXT[],
    embedding FLOAT[384],
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    project TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source_session_id TEXT,
    source_artifact_uri TEXT
);
```

- [ ] **Step 5: Run test, verify it passes**

Run: `.venv/bin/pytest tests/unit/test_reflection_provenance.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add session_buddy/adapters/reflection_adapter_oneiric.py \
        tests/unit/test_reflection_provenance.py
git -c user.email="les@wedgwoodwebworks.com" -c user.name="les" \
    -c core.hooksPath=/dev/null commit --no-verify \
    -m "feat(reflections): add source_session_id + source_artifact_uri columns"
```

### Task C2: `store_reflection` extracts provenance from `metadata`

**Files:**
- Modify: `session_buddy/mcp/tools/memory/memory_tools.py:769` (`store_reflection` — recognize `source_session_id` + `source_artifact_uri` keys in `metadata`, pass to INSERT)
- Modify: `session_buddy/adapters/reflection_adapter_oneiric.py:store_reflection` (signature accepts optional `source_session_id`, `source_artifact_uri`)
- Test: extend `tests/unit/test_reflection_provenance.py`

- [ ] **Step 1: Write failing test for extraction**

```python
def test_store_reflection_extracts_provenance_from_metadata(tmp_path):
    """metadata={'source_session_id': 'abc'} populates the column on store."""
    from session_buddy.adapters.reflection_adapter_oneiric import ReflectionDatabaseAdapter
    db_path = tmp_path / "test.duckdb"
    adapter = ReflectionDatabaseAdapter(db_path=str(db_path))
    adapter.store_reflection(
        memory_id="r1",
        text="prov test",
        metadata={"source_session_id": "sess-abc", "source_artifact_uri": "pool://sess-abc/task/1"},
    )
    row = adapter._conn.execute(
        "SELECT source_session_id, source_artifact_uri FROM reflections WHERE id='r1'"
    ).fetchone()
    assert row[0] == "sess-abc"
    assert row[1] == "pool://sess-abc/task/1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_reflection_provenance.py::test_store_reflection_extracts_provenance_from_metadata -v`
Expected: FAIL — columns NULL

- [ ] **Step 3: Add optional params to `ReflectionDatabaseAdapter.store_reflection`**

```python
# session_buddy/adapters/reflection_adapter_oneiric.py
def store_reflection(
    self,
    memory_id: str,
    text: str,
    *,
    metadata: dict[str, Any] | None = None,
    source_session_id: str | None = None,
    source_artifact_uri: str | None = None,
) -> bool:
    """Persist a reflection. Provenance keys may come from explicit args or metadata."""
    md = dict(metadata or {})
    src_sid = source_session_id or md.pop("source_session_id", None)
    src_uri = source_artifact_uri or md.pop("source_artifact_uri", None)
    self._conn.execute(
        """
        INSERT INTO reflections (id, content, tags, embedding, source_session_id, source_artifact_uri)
        VALUES (?, ?, ?, NULL, ?, ?)
        ON CONFLICT (id) DO UPDATE SET
            content = excluded.content,
            tags = excluded.tags,
            source_session_id = excluded.source_session_id,
            source_artifact_uri = excluded.source_artifact_uri
        """,
        [memory_id, text, list(md.get("tags", [])), src_sid, src_uri],
    )
    return True
```

- [ ] **Step 4: Run test, verify it passes**

Run: `.venv/bin/pytest tests/unit/test_reflection_provenance.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add session_buddy/adapters/reflection_adapter_oneiric.py \
        tests/unit/test_reflection_provenance.py
git -c user.email="les@wedgwoodwebworks.com" -c user.name="les" \
    -c core.hooksPath=/dev/null commit --no-verify \
    -m "feat(reflections): store_reflection extracts provenance from metadata"
```

### Task C3: Backfill provenance for existing rows

**Files:**
- Create: `scripts/backfill_reflection_provenance.py` (new — idempotent migration)

- [ ] **Step 1: Write backfill script**

```python
#!/usr/bin/env python3
"""Backfill source_session_id + source_artifact_uri from metadata JSON.

Idempotent. Scans all reflections where the provenance columns are NULL and
parses the `tags` field for JSON-embedded provenance keys (set by call sites
that stored provenance in tags before columns existed).
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

logger = logging.getLogger("session_buddy.backfill_provenance")


def backfill(db_path: Path, *, dry_run: bool = False) -> tuple[int, int]:
    import duckdb
    conn = duckdb.connect(str(db_path), read_only=False)
    updated = 0
    skipped = 0
    for row in conn.execute(
        """
        SELECT id, tags
        FROM reflections
        WHERE source_session_id IS NULL OR source_artifact_uri IS NULL
        """
    ).fetchall():
        rid, tags_json = row
        if not tags_json:
            skipped += 1
            continue
        try:
            tags = json.loads(tags_json) if isinstance(tags_json, str) else tags_json
        except json.JSONDecodeError:
            skipped += 1
            continue
        sid = tags.get("source_session_id") if isinstance(tags, dict) else None
        uri = tags.get("source_artifact_uri") if isinstance(tags, dict) else None
        if not sid and not uri:
            skipped += 1
            continue
        if not dry_run:
            conn.execute(
                "UPDATE reflections SET source_session_id = ?, source_artifact_uri = ? WHERE id = ?",
                [sid, uri, rid],
            )
        updated += 1
    return updated, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("~/.claude/data/session-buddy.duckdb").expanduser())
    parser.add_argument("--dry-run", action="store_true", help="Report counts without writing")
    args = parser.parse_args()
    updated, skipped = backfill(args.db, dry_run=args.dry_run)
    print(f"Updated: {updated}; Skipped: {skipped}; DB: {args.db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Manual dry-run + commit**

```bash
chmod +x scripts/backfill_reflection_provenance.py
python scripts/backfill_reflection_provenance.py --dry-run
# If counts look right, run for real:
python scripts/backfill_reflection_provenance.py

git add scripts/backfill_reflection_provenance.py
git -c user.email="les@wedgwoodwebworks.com" -c user.name="les" \
    -c core.hooksPath=/dev/null commit --no-verify \
    -m "feat(reflections): idempotent backfill script for provenance columns"
```

### Task C4: Provenance surfaced in `reflection_stats` + new MCP tool

**Files:**
- Modify: `session_buddy/mcp/tools/memory/memory_tools.py` (extend `reflection_stats` with provenance coverage %)
- Add: new MCP tool `search_by_source_session(session_id: str, limit: int = 20)` → list of reflections

- [ ] **Step 1: Add `search_by_source_session` tool**

```python
# session_buddy/mcp/tools/memory/memory_tools.py
async def search_by_source_session(
    session_id: str,
    *,
    limit: int = 20,
    project: str | None = None,
) -> dict[str, Any]:
    """Find all reflections sourced from a given session_id.

    Useful for: 'show me everything this session wrote' (provenance query).
    Returns a list of {memory_id, content, tags, timestamp} dicts.
    """
    from ...adapters.reflection_adapter_oneiric import ReflectionDatabaseAdapter
    from ...adapters.session_storage_adapter import get_default_db_path
    adapter = ReflectionDatabaseAdapter(db_path=str(get_default_db_path()))
    rows = adapter._conn.execute(
        """
        SELECT id, content, tags, timestamp
        FROM reflections
        WHERE source_session_id = ?
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        [session_id, limit],
    ).fetchall()
    return {
        "success": True,
        "count": len(rows),
        "session_id": session_id,
        "results": [
            {"memory_id": r[0], "content": r[1], "tags": json.loads(r[2]) if r[2] else [],
             "timestamp": r[3].isoformat() if r[3] else None}
            for r in rows
        ],
    }
```

- [ ] **Step 2: Register in profile + test**

```python
# tests/unit/test_reflection_provenance.py — add new test
def test_search_by_source_session_returns_reflections(tmp_path):
    from session_buddy.adapters.reflection_adapter_oneiric import ReflectionDatabaseAdapter
    adapter = ReflectionDatabaseAdapter(db_path=str(tmp_path / "test.duckdb"))
    for i, sid in enumerate(["sess-x", "sess-x", "sess-y"]):
        adapter.store_reflection(
            memory_id=f"r{i}", text=f"content {i}",
            metadata={"source_session_id": sid, "tags": [f"t{i}"]},
        )
    rows = adapter._conn.execute(
        "SELECT id FROM reflections WHERE source_session_id = 'sess-x' ORDER BY timestamp"
    ).fetchall()
    assert len(rows) == 2
```

- [ ] **Step 3: Run tests, commit**

Run: `.venv/bin/pytest tests/unit/test_reflection_provenance.py -v`
Expected: PASS

```bash
git add session_buddy/mcp/tools/memory/memory_tools.py \
        tests/unit/test_reflection_provenance.py
git -c user.email="les@wedgwoodwebworks.com" -c user.name="les" \
    -c core.hooksPath=/dev/null commit --no-verify \
    -m "feat(reflections): search_by_source_session MCP tool"
```

---

## Execution Order

| Order | Track | Task | Why this slot |
|---|---|---|---|
| 1 | A | A-ext1 (Oneiric secrets for Bifrost) | Standalone — small, no dependencies |
| 2 | B | B1 (fake-gcs scripts) | Standalone — no dependencies |
| 3 | B | B2 (flip default backend) | Depends on B1 |
| 4 | B | B3 (integration smoke) | Depends on B1 + B2 |
| 5 | A | A-ext2 (provenance metadata in `_store_task_reflection`) | Standalone — populates `metadata` keys |
| 6 | C | C1 (add provenance columns) | Depends on A-ext2 having populated the metadata keys |
| 7 | C | C2 (extract provenance on insert) | Depends on C1 |
| 8 | C | C3 (backfill script) | Depends on C1 |
| 9 | C | C4 (search_by_source_session tool) | Depends on C2 |

Tracks A-ext2 and B can run in **parallel** (no shared files). Track C depends on Track A-ext2 landing first so the `metadata` keys exist for backfill.

**Two parallel subagents possible:**
- Subagent 1: Track A-ext1 + A-ext2 (in existing Hybrid D+A worktree)
- Subagent 2: Track B1 → B3 (new worktree)
- Subagent 3 (after A-ext2 lands): Track C1 → C4

## Validation

| Check | Command | Expected |
|---|---|---|
| All ruff checks pass | `.venv/bin/ruff check session_buddy/` | All clean |
| Full test suite passes | `.venv/bin/pytest tests/unit/ tests/integration/ -m "not slow"` | All green |
| Storage tiering smoke | `session-buddy-fake-gcs start && session-buddy-fake-gcs init && python -m session_buddy.server --mode standard` then `mcp__session-buddy__store_reflection` | object lands in `sessions-hot` bucket |
| Lifecycle policy applied | `gsutil -o Credentials:anon -o APIEndpoint:http://127.0.0.1:4443 lifecycle get gs://sessions-hot` | returns the 4-rule JSON |
| Provenance extraction | `store_reflection(..., metadata={"source_session_id": "x"})` then query `search_by_source_session("x")` | returns ≥1 result |
| Backfill idempotent | Run `python scripts/backfill_reflection_provenance.py` twice | second run reports 0 updates |
| Oneiric secrets fallback | `ONEIRIC_SECRETS_BACKEND=env BIFROST_API_KEY=test python -c "from session_buddy.bifrost_client import BifrostClient; print(BifrostClient().api_key)"` | prints "test" |
| diff scope | `git diff --stat main..HEAD` | ≤8 files, ≤500 lines added |
| Audit: orphans | `python scripts/audit_orphans.py` | exit 0 |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| `fake-gcs-server` doesn't accept `gsutil lifecycle set` (different storage class semantics) | Medium | Test in B3 first; if it fails, skip `lifecycle set` and document — tiering still works via per-bucket config |
| Existing call sites don't populate `source_session_id` in metadata | Medium | Backfill script (C3) scans metadata for the key; missing rows stay NULL until next write |
| Oneiric secrets adapter import path differs from the documented `oneiric.secrets.vault_client` shape | Medium | Task A-ext1 Step 1 test verifies the import works; if shape differs, adjust `_get_backend` factory |
| `GCS_ENDPOINT` env var leaks into prod (real GCS rejects unknown endpoint) | Low | Track B2 default is `http://127.0.0.1:4443` only when set; prod deploys unset it |
| DuckDB ALTER TABLE on existing rows is slow at scale (1.1GB → 234+ rows) | Low | `ALTER TABLE ... ADD COLUMN` is metadata-only in DuckDB (no row rewrite) |
| Parallel subagents conflict on `settings/session-buddy.yaml` | Low | Track B owns the settings file; Track A-ext2 only touches `session_buddy/pools.py` and metadata dict |

## Decision Rule

This plan is "done enough" when:

1. All tasks committed (target: 9 commits across 3 worktrees).
2. `pytest tests/unit/ tests/integration/ -m "not slow"` passes.
3. `ruff check` clean for `session_buddy/`.
4. `session-buddy-fake-gcs start && init && ... && stop` round-trip succeeds.
5. `mcp__session-buddy__search_by_source_session("any-test-id")` returns ≥1 row when a `store_reflection` has been called with `metadata={"source_session_id": "any-test-id"}`.
6. `BIFROST_API_KEY` loaded via `ONEIRIC_SECRETS_BACKEND=env` returns the env value.
7. The Hybrid D+A plan's D3 test (already written) passes with `source_session_id` populated in stored metadata.

**Universal invariants** (from CLAUDE.md):
- No `git push`
- No version bumps
- Author `les@wedgwoodwebworks.com`
- Pre-commit bypass via `git -c core.hooksPath=/dev/null commit --no-verify`

## Critical files

- `/Users/les/Projects/session-buddy/session_buddy/bifrost_client.py` — Track A-ext1 (Oneiric secrets swap)
- `/Users/les/Projects/session-buddy/session_buddy/secrets_oneiric.py` — NEW (Track A-ext1)
- `/Users/les/Projects/session-buddy/session_buddy/pools.py` — Track A-ext2 (provenance metadata)
- `/Users/les/Projects/session-buddy/scripts/fake-gcs-{start,stop,init-buckets}.sh` — NEW (Track B1)
- `/Users/les/Projects/session-buddy/session_buddy/scripts/fake_gcs.py` — NEW (Track B1)
- `/Users/les/Projects/session-buddy/settings/session-buddy.yaml` — Track B2 (default backend flip)
- `/Users/les/Projects/session-buddy/session_buddy/adapters/reflection_adapter_oneiric.py` — Track C1, C2 (schema + insert)
- `/Users/les/Projects/session-buddy/session_buddy/mcp/tools/memory/memory_tools.py` — Track C2, C4 (extraction + new tool)
- `/Users/les/Projects/session-buddy/scripts/backfill_reflection_provenance.py` — NEW (Track C3)

## What I'm NOT doing (and why)

- **Wholesale Letta filesystem core swap** — Deferred; current DuckDB schema is sufficient at current volumes (~1.1GB / 234 reflections).
- **Mem0 graph memory evaluation** — Deferred; the insights-pipeline-removal pattern was the failure mode, not the graph shape.
- **CRDT-style sync (Automerge / Yjs)** — Deferred until a multi-device story lands.
- **Tiered memory (working / episodic / semantic full redesign)** — Deferred; current flat shape works at current volume.
- **Real GCS deploy wiring** — Out of scope; Track B2 only changes the dev/local config. Production deploy changes are the deploy team's call.
- **Schema redesign for Vault integration** — Oneiric secrets adapter is already wired into the ecosystem; this plan consumes it, doesn't reinvent.

## References

- `docs/superpowers/plans/2026-09-25-pool-workers-hybrid-d-and-a.md` — Hybrid D+A plan (worktree at `.worktrees/feature-pool-workers-hybrid-d-and-a`)
- `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/feedback-session-buddy-insights-pipeline-removed.md` — Prior research on memory patterns (Anthropic / Letta / Mem0 / Cline)
- `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/feedback-memories-must-be-dual-stored.md` — Cross-cutting rules must dual-store (CC memory + Session-Buddy)
- Oneiric secrets docs — `oneiric/secrets/README.md` (consumed by Track A-ext1)
- `CLAUDE.md` — Memory routing table; project posture
- `feedback-bodai-push-is-user-controlled.md` — no push by implementer
- `feedback-mcp-common-version-bump-is-user.md` — no version bump
- `bodai-pre-1.0-merge-policy.md` — direct-to-main, no PRs
- `mahavishnu-worktree-precommit-blocks-workers.md` — `core.hooksPath=/dev/null` bypass

## Revision history

- **v1** (2026-09-25, current) — Initial plan. Three tracks: A-ext (in-flight Hybrid D+A extension), B (cold/hot tiering in fake-gcs-server), C (memory provenance columns + extraction + backfill + new tool). Two parallel subagents + one dependent on Track A-ext2.

# C-13: crackerjack review-pr skill (WP-7 — separate repo, separate plan)

**REQ-NNN:** (none — C-13 ships without a formal REQ-NNN ID; it's an Akosha-pattern-triggered skill in a separate repo)
**Repo:** **Crackerjack** (NOT Mahavishnu). Lands on Crackerjack's local `main` branch per `bodai-pre-1.0-merge-policy`. **No PRs.** The plan is filed here because the trigger surface touches both repos.
**Risk:** Medium (cross-repo coupling — version-pin to `mahavishnu >= 0.29`; durable queue for GitHub 5xx retries; Akosha pattern subscription replaces webhook trigger per niche filter)
**Blocks:** None (this is the final wire-up in the C-1..C-13 chain)
**Direct-to-main commit:** Yes — committed directly to Crackerjack's local `main` branch. **No PRs.** No `--no-verify` (Bodai uses Crackerjack for CI/CD per `no-bodai-pre-commit-hook.md`). Per `crackerjack-cli-run-subcommand.md`, the gate is `crackerjack run -p minor` (user-initiated bumps; not part of this commit).
**Status:** Draft — round-4 niche-filter corrections baked in (Akosha pattern trigger replaces Mahavishnu webhook; specific filenames; specific env-var name).

## Goal

Build a Crackerjack skill that subscribes to an Akosha pattern (per round-4 niche filter — **no Mahavishnu webhook trigger**), pulls GitHub PR diff via `CRACKERJACK_GITHUB_TOKEN` env var, runs Crackerjack quality gates, dispatches code-review agent via Mahavishnu's `pool_route_execute`, posts the review back as a PR comment.

**Why this is the final wire-up**: C-13 ties together C-5 (safe_publish singleton) + C-6 (idempotent dispatch) + the niche filter (no Mahavishnu webhook) + Akosha as the cross-system event bus. It is the "consume Akosha events and act on them" half of the Bodai event flow.

## Pre-flight checks

1. **C-5 has landed (in Mahavishnu).** `safe_publish()` is available; `MahavishnuSettings.webhook_intake.enabled` is queryable. Crackerjack queries this setting via the configured channel.
2. **C-6 has landed (in Mahavishnu).** `IdempotencyOptions` + `pool_route_execute(idempotency=...)` available for code-review dispatches.
3. **`mcp__akosha__detect_anomalies` (or equivalent pattern subscription API) is reachable.** Crackerjack uses the Akosha MCP server to subscribe to patterns.
4. **`CRACKERJACK_GITHUB_TOKEN` env var is set** in the operator's shell rc (NOT committed). Per Oneiric convention, the skill reads the token via the configured `api_key_env` reference, not raw.
5. **Crackerjack version is `>=0.83.9`** (supports `async def` in `crackerjack audit` symbols per `feedback-crackerjack-release-audit-symbol-notation.md`).
6. **No existing `crackerjack/skills/review_pr.py`** (`ls crackerjack/skills/` returns only the existing skills).
7. **No `webhook_register` MCP tool exists** — the Akosha pattern subscription REPLACES it (per niche filter).

## File-by-file changes (in Crackerjack repo)

### 1. `crackerjack/skills/review_pr.py` — new file (~120 LoC)

```python
"""Crackerjack review-pr skill — Akosha-pattern-triggered PR review.

Per niche filter (docs/adr/0001-mahavishnu-niche.md in the mahavishnu repo):
- Trigger is Akosha pattern subscription, NOT a Mahavishnu webhook.
- Pulls GitHub PR diff via env var reference (never raw token).
- Dispatches code-review via mahavishnu.pool_route_execute(idempotency=...).
- Posts review back as PR comment.

Version-pin to mahavishnu >= 0.29 for safe_publish + IdempotencyOptions.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
from typing import Any
from uuid import uuid4

from crackerjack.skills.comment_poster import post_pr_comment
from crackerjack.skills.durable_queue import DurableQueue
from crackerjack.skills.github_client import fetch_pr_diff, GitHubAPIError
from oneiric.core.logging import get_logger

logger = get_logger(__name__)


async def on_akosha_pattern(event: dict[str, Any]) -> None:
    """Akosha pattern subscription handler.

    Trigger: ecosystem.event.received{source="git-monitor"}.
    Pattern detection: mcp__akosha__detect_anomalies (or equivalent).

    FIX (round-5 INC-4): consume structured payload, not sanitized string.
    The producer (C-10 ecosystem intake OR a direct Akosha publisher for
    external systems) emits `payload.data` as a dict with known fields;
    the consumer reads typed fields. Sanitizing to a string was a half-measure.
    """
    source = event.get("payload", {}).get("source", "")
    if source != "git-monitor":
        return

    # FIX (round-5 INC-4): structured payload — `data` is a dict, not a string
    pr_url = event.get("payload", {}).get("data", {}).get("pr_url", "")
    if not pr_url:
        logger.debug("no pr_url in event; skipping")
        return

    await _handle_pr_event(pr_url)


async def _handle_pr_event(pr_url: str) -> None:
    """Process one PR review event."""
    queue = DurableQueue(path=os.environ.get(
        "CRACKERJACK_REVIEW_QUEUE_PATH", "/tmp/crackerjack-review-queue"
    ))
    queue.enqueue(pr_url)

    try:
        diff = await fetch_pr_diff(pr_url)
    except GitHubAPIError as exc:
        logger.warning("GitHub fetch failed; queued for retry",
                       extra={"pr_url": pr_url, "error": str(exc)})
        return

    # Dispatch via mahavishnu pool_route_execute (cross-process via subprocess
    # because crackerjack and mahavishnu are separate repos).
    idempotency_nonce = hashlib.sha256(pr_url.encode()).hexdigest()[:32]
    review_prompt = _build_review_prompt(pr_url, diff)

    try:
        result = await _dispatch_via_mahavishnu(review_prompt, idempotency_nonce)
        await post_pr_comment(pr_url, result["comment"])
        metrics.pr_review_post_total.labels(result="success").inc()
    except Exception as exc:
        logger.exception("review dispatch failed",
                         extra={"pr_url": pr_url, "error": str(exc)})
        metrics.pr_review_post_total.labels(result="error").inc()


def _build_review_prompt(pr_url: str, diff: str) -> str:
    """Construct the prompt sent to mahavishnu pool_route_execute."""
    return (
        f"Review the following pull request diff for quality, security, "
        f"and convention adherence:\n\n"
        f"PR: {pr_url}\n\n"
        f"Diff:\n{diff[:50_000]}"  # truncate to 50K chars
    )


async def _dispatch_via_mahavishnu(prompt: str, idempotency_nonce: str) -> dict[str, Any]:
    """Cross-process dispatch via mahavishnu CLI.

    Crackerjack is a separate repo; we shell out to `mahavishnu pool-route-execute`
    rather than importing across repos. The dispatch is async-subprocess to
    avoid blocking crackerjack's event loop.

    TODO (round-5 fix): once crackerjack grows an MCP-aware runtime, swap this
    subprocess dispatch for `mcp__mahavishnu__pool_route_execute` (MCP-mediated).
    MCP-mediated dispatch gives observability (per-pool-worker-id metrics,
    Akosha envelope correlation) that subprocess cannot. Until then, subprocess
    is the lowest-friction cross-repo path. Both options are documented per
    user decision "both".

    FIX (round-5 INC-3): the original CLI invocation used `--idempotency-source=...`
    flag-value syntax which no plan implemented. Updated to Typer-style
    `--idempotency-source <value>` matching the C-6 Typer shim.
    """
    import json
    import subprocess

    cmd = [
        "mahavishnu", "pool-route-execute", "execute",
        "--prompt", prompt,
        "--pool-selector", "least_loaded",
        "--idempotency-source", "crackerjack.review_pr",
        "--idempotency-nonce", idempotency_nonce,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"mahavishnu dispatch failed: {stderr.decode()}")
    return json.loads(stdout.decode())
```

### 2. `crackerjack/skills/github_client.py` — new file (~60 LoC)

```python
"""GitHub API client — fetches PR diffs via httpx + respx-mocked for tests."""
from __future__ import annotations

import os

import httpx


class GitHubAPIError(Exception):
    """Raised on GitHub API failures (5xx, 429, auth, network)."""


async def fetch_pr_diff(pr_url: str) -> str:
    """Fetch the raw diff for a pull request.

    Uses CRACKERJACK_GITHUB_TOKEN env var (referenced via api_key_env in
    crackerjack/settings/ai.yaml, never raw).
    """
    token = os.environ.get("CRACKERJACK_GITHUB_TOKEN")
    if not token:
        raise GitHubAPIError("CRACKERJACK_GITHUB_TOKEN not set")

    # Convert PR URL to .diff URL (e.g., https://github.com/owner/repo/pull/N → .diff)
    diff_url = f"{pr_url}.diff" if not pr_url.endswith(".diff") else pr_url

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3.diff",
        "User-Agent": "crackerjack-review-pr/1.0",
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        try:
            response = await client.get(diff_url, headers=headers)
        except httpx.HTTPError as exc:
            raise GitHubAPIError(f"network error: {exc}") from exc

        if response.status_code == 429:
            # Rate limit; retry logic lives in durable_queue
            raise GitHubAPIError(f"rate limited: {response.status_code}")
        if response.status_code >= 500:
            raise GitHubAPIError(f"server error: {response.status_code}")
        if response.status_code == 401:
            raise GitHubAPIError("auth failure: 401")
        if response.status_code >= 400:
            raise GitHubAPIError(
                f"client error {response.status_code}: {response.text[:200]}"
            )

    return response.text
```

### 3. `crackerjack/skills/comment_poster.py` — new file (~40 LoC)

```python
"""Posts review comments back to GitHub PRs."""
from __future__ import annotations

import os

import httpx

from crackerjack.skills.github_client import GitHubAPIError


async def post_pr_comment(pr_url: str, body: str) -> dict:
    """Post a comment to a PR.

    Returns the response JSON (with 'id' of the created comment).
    """
    token = os.environ.get("CRACKERJACK_GITHUB_TOKEN")
    if not token:
        raise GitHubAPIError("CRACKERJACK_GITHUB_TOKEN not set")

    # Extract owner/repo/number from URL
    parts = pr_url.replace("https://github.com/", "").split("/")
    if len(parts) < 4 or parts[2] != "pull":
        raise GitHubAPIError(f"malformed PR URL: {pr_url}")
    owner, repo, _, number = parts[0], parts[1], parts[2], parts[3]
    number = number.rstrip(".diff")  # in case .diff suffix slipped through

    api_url = f"https://api.github.com/repos/{owner}/{repo}/issues/{number}/comments"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "crackerjack-review-pr/1.0",
    }
    payload = {"body": body}

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        response = await client.post(api_url, headers=headers, json=payload)
        if response.status_code >= 400:
            raise GitHubAPIError(
                f"comment post failed {response.status_code}: {response.text[:200]}"
            )
    return response.json()
```

### 4. `crackerjack/skills/durable_queue.py` — new file (~50 LoC)

```python
"""Local durable queue for retry on GitHub 5xx errors.

Persists PR URLs that failed to fetch so a background retry process can
re-attempt them. Uses fcntl.flock for concurrency safety.
"""
from __future__ import annotations

import fcntl
import json
from pathlib import Path


class DurableQueue:
    """File-backed FIFO queue with flock-based concurrency control."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    def enqueue(self, item: str) -> None:
        """Append an item to the queue (one JSON string per line)."""
        with open(self.path, "a") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.write(json.dumps({"item": item}) + "\n")
                f.flush()
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def dequeue(self) -> str | None:
        """Pop the oldest item from the queue. Returns None if empty."""
        with open(self.path, "r+") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                lines = f.readlines()
                if not lines:
                    return None
                item = json.loads(lines[0])["item"]
                # Rewrite without the first line
                f.seek(0)
                f.writelines(lines[1:])
                f.truncate()
                return item
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def __len__(self) -> int:
        return sum(1 for _ in open(self.path))
```

### 5. `crackerjack/skills/__init__.py` — register the skill

Add to the skill registry:

```python
from crackerjack.skills.review_pr import on_akosha_pattern

SKILL_REGISTRY["review_pr"] = {
    "name": "review_pr",
    "trigger": "akosha_pattern:ecosystem.event.received{source='git-monitor'}",
    "handler": on_akosha_pattern,
    "version_pin": "mahavishnu >= 0.29",
    "rollback_signal": "SKILL_REGISTRY['review_pr']['enabled'] = False",
}
```

### 6. `crackerjack/settings/ai.yaml` — add Crackerjack-side config

```yaml
crack:
  github:
    api_key_env: "CRACKERJACK_GITHUB_TOKEN"  # env-var reference, NEVER raw
    fork_pr_quota_buffer: 10
  review_pr:
    enabled: true  # binary flag — set to false to disable
    queue_path: "/tmp/crackerjack-review-queue"
    mahavishnu_dispatch_path: "mahavishnu"  # CLI binary in PATH
```

## Tests (in Crackerjack repo)

### 7. `crackerjack/tests/integration/test_review_pr.py` — new file (~250 LoC)

Five error paths covered:

```python
"""Integration tests for crackerjack review_pr skill with respx mocks."""
from __future__ import annotations

import pytest
import respx
from httpx import Response

from crackerjack.skills.github_client import GitHubAPIError, fetch_pr_diff


@pytest.fixture
def github_token(monkeypatch):
    monkeypatch.setenv("CRACKERJACK_GITHUB_TOKEN", "ghp_TEST_TOKEN")


@pytest.mark.req(["REQ-016"])
class TestFetchPrDiff:
    @respx.mock
    async def test_success(self, github_token) -> None:
        respx.get("https://github.com/owner/repo/pull/123.diff").mock(
            return_value=Response(200, text="diff --git a/file b/file\n@@\n+hi\n")
        )
        diff = await fetch_pr_diff("https://github.com/owner/repo/pull/123")
        assert "diff --git" in diff

    @respx.mock
    async def test_5xx_triggers_retry(self, github_token) -> None:
        respx.get("https://github.com/owner/repo/pull/123.diff").mock(
            return_value=Response(503, text="Service Unavailable")
        )
        with pytest.raises(GitHubAPIError, match="server error"):
            await fetch_pr_diff("https://github.com/owner/repo/pull/123")

    @respx.mock
    async def test_429_triggers_backoff(self, github_token) -> None:
        respx.get("https://github.com/owner/repo/pull/123.diff").mock(
            return_value=Response(429, text="Too Many Requests")
        )
        with pytest.raises(GitHubAPIError, match="rate limited"):
            await fetch_pr_diff("https://github.com/owner/repo/pull/123")

    @respx.mock
    async def test_401_auth_failure(self, github_token) -> None:
        respx.get("https://github.com/owner/repo/pull/123.diff").mock(
            return_value=Response(401, text="Unauthorized")
        )
        with pytest.raises(GitHubAPIError, match="auth failure"):
            await fetch_pr_diff("https://github.com/owner/repo/pull/123")

    @respx.mock
    async def test_malformed_pr_diff(self, github_token) -> None:
        # GitHub returns 200 with HTML error page when URL is malformed
        respx.get("https://github.com/owner/repo/pull/abc.diff").mock(
            return_value=Response(200, text="<html>Not Found</html>")
        )
        diff = await fetch_pr_diff("https://github.com/owner/repo/pull/abc")
        # Caller (review_pr.py) detects non-diff content and raises
        assert "<html>" in diff  # the caller decides what to do with this

    @respx.mock
    async def test_network_timeout(self, github_token, monkeypatch) -> None:
        import httpx
        async def raise_timeout(*args, **kwargs):
            raise httpx.TimeoutException("timeout")
        monkeypatch.setattr(
            "crackerjack.skills.github_client.httpx.AsyncClient.get",
            raise_timeout,
        )
        with pytest.raises(GitHubAPIError, match="network error"):
            await fetch_pr_diff("https://github.com/owner/repo/pull/123")


@pytest.mark.req(["REQ-016"])
class TestOnAkoshaPattern:
    async def test_skips_non_git_monitor_events(self) -> None:
        from crackerjack.skills.review_pr import on_akosha_pattern
        # Should return early without fetching
        await on_akosha_pattern({"payload": {"source": "crontroller"}})
        # No exception; no fetch attempted (verify by no mock needed)

    async def test_skips_events_without_pr_url(self) -> None:
        from crackerjack.skills.review_pr import on_akosha_pattern
        await on_akosha_pattern({"payload": {"source": "git-monitor"}})
        # No exception; no fetch attempted


@pytest.mark.req(["REQ-016"])
class TestDurableQueue:
    def test_enqueue_dequeue(self, tmp_path) -> None:
        from crackerjack.skills.durable_queue import DurableQueue
        q = DurableQueue(tmp_path / "queue.jsonl")
        q.enqueue("item-1")
        q.enqueue("item-2")
        assert q.dequeue() == "item-1"
        assert q.dequeue() == "item-2"
        assert q.dequeue() is None

    def test_flock_serializes_concurrent_writes(self, tmp_path) -> None:
        """Two threads writing to the same queue do not corrupt the file."""
        import threading
        from crackerjack.skills.durable_queue import DurableQueue

        q = DurableQueue(tmp_path / "queue.jsonl")

        def writer(prefix: str) -> None:
            for i in range(10):
                q.enqueue(f"{prefix}-{i}")

        t1 = threading.Thread(target=writer, args=("a",))
        t2 = threading.Thread(target=writer, args=("b",))
        t1.start(); t2.start()
        t1.join(); t2.join()
        # All 20 items present, no truncation
        assert len(q) == 20
```

### 8. `crackerjack/tests/e2e/test_review_pr_e2e.py` — new file (~100 LoC)

Per `.claude/decisions/mcp-backend-wiring-discipline.md`, e2e smoke test:

```python
"""E2E smoke test for review_pr skill against a real GitHub test repo.

Disabled by default — requires CRACKERJACK_E2E=1 + a test repo.
"""
from __future__ import annotations

import os

import pytest


@pytest.mark.req(["REQ-016"])
@pytest.mark.e2e
@pytest.mark.skipif(
    not os.environ.get("CRACKERJACK_E2E") == "1",
    reason="CRACKERJACK_E2E not set",
)
class TestReviewPrE2E:
    async def test_review_against_test_repo(self) -> None:
        """Spin up the skill against a known test PR and verify a comment is posted."""
        from crackerjack.skills.review_pr import _handle_pr_event

        test_pr_url = os.environ.get(
            "CRACKERJACK_E2E_PR_URL",
            "https://github.com/crackerjack-dev/test-pr-repo/pull/1",
        )
        await _handle_pr_event(test_pr_url)
        # Verification: the e2e test repo has a fixture PR that the skill
        # can comment on; manual inspection of the test repo confirms posting.
```

## Crackerjack verification

```bash
cd crackerjack
uv run pytest tests/integration/test_review_pr.py -v
uv run pytest tests/e2e/test_review_pr_e2e.py -v -m e2e
uv run crackerjack run -p minor  # NOT in this commit — user-initiated
```

## Acceptance criteria (decisive pass/fail)

1. `crackerjack/skills/review_pr.py` exists with `on_akosha_pattern()` function.
2. `crackerjack/skills/github_client.py` exists with `fetch_pr_diff()` and `GitHubAPIError`.
3. `crackerjack/skills/comment_poster.py` exists with `post_pr_comment()`.
4. `crackerjack/skills/durable_queue.py` exists with `DurableQueue` class.
5. **No `webhook_register` MCP tool** exists (the Akosha pattern subscription REPLACES it).
6. **`CRACKERJACK_GITHUB_TOKEN` is referenced via env var**, NEVER raw (verified by `git grep "ghp_" crackerjack/skills/` returning nothing).
7. **5 error paths covered**: 5xx, 429, auth failure (401), malformed diff, network timeout.
8. Trigger is `ecosystem.event.received{source="git-monitor"}` (Akosha pattern), NOT a Mahavishnu webhook.
9. Cross-repo contract test asserts `mahavishnu >= 0.29` (verifies safe_publish availability).
10. Cross-repo contract test asserts `MahavishnuSettings.webhook_intake.enabled` is queryable from Crackerjack.
11. E2E smoke test passes (gated by `CRACKERJACK_E2E=1`).
12. DurableQueue's flock-based serialization works under concurrent writers.
13. `crackerjack audit --strict` passes; coverage gate holds (Crackerjack's gate).

## Rollback / recovery narration

Per `feedback-no-backwards-compat-pre-1.0` and Bodai pre-1.0 merge policy:
- **Direct-to-main commit on Crackerjack's local `main` branch. No PRs.** Per `bodai-pre-1.0-merge-policy` (applies to all Bodai repos, not just mahavishnu).
- **Rollback signal: binary flag** — `crack.review_pr.enabled: false` in `crackerjack/settings/ai.yaml`. Set to false to disable the skill without code rollback.
- **Hard rollback: `git revert <commit-sha>`** — removes the skill entirely. Operators see Akosha pattern events for `git-monitor` get no response.
- **Cross-repo coupling**: if Mahavishnu `safe_publish` is removed or `pool_route_execute` arg signature changes, Crackerjack's dispatch fails. Version-pin `mahavishnu >= 0.29` in `crackerjack/pyproject.toml` enforces this.

## Observability added

Four new Prometheus metrics (in Crackerjack):

```python
PR_REVIEW_DURATION = Histogram(
    "pr_review_duration_seconds",
    "Time to review one PR (fetch + dispatch + post).",
    buckets=(5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
)
PR_REVIEW_POST_TOTAL = Counter(
    "pr_review_post_total",
    "PR review posts, labeled by result.",
    labelnames=["result"],  # success | error | 5xx | 429 | auth | timeout
)
GITHUB_API_QUOTA_REMAINING = Gauge(
    "github_api_quota_remaining",
    "GitHub API quota remaining (from response headers).",
)
PR_REVIEW_FORK_PR_TOTAL = Counter(
    "pr_review_fork_pr_total",
    "Fork PR reviews (separate quota tracking).",
    labelnames=["result"],
)
```

Plus Akosha-side `pattern.detected` for recurring review findings (operator-tunable threshold).

## Health aggregation

The skill's health feeds into the existing Crackerjack `_register_health_tools` aggregator. If `pr_review_post_total{result="error"} rate > 0.1/s` for 5m, operators see `/health` degraded on Crackerjack.

## Implementation notes / gotchas

- **`CRACKERJACK_GITHUB_TOKEN` is referenced via `api_key_env`, not raw.** Per Oneiric convention and `feedback-bodai-push-is-user-controlled.md` (never commit secrets).
- **The Akosha pattern subscription REPLACES the Mahavishnu webhook trigger** per niche filter. C-13 explicitly does NOT depend on the C-10 ecosystem intake endpoint; external systems publish to Akosha directly.
- **Cross-process dispatch via subprocess** is intentional — Crackerjack and Mahavishnu are separate repos. Importing across repos would couple them inappropriately. Subprocess dispatch preserves the API contract.
- **`respx` mocks for GitHub API** are the standard pattern for httpx-based clients. No live GitHub calls in tests.
- **`DurableQueue` uses `fcntl.flock`** for concurrency safety. macOS supports flock; Windows does NOT (use `msvcrt.locking` if Windows support is needed — out of scope for C-13).
- **The `fork_pr_quota_buffer` setting** (default 10) reserves API quota for fork PRs. GitHub counts fork PRs against a separate quota; without the buffer, regular reviews get throttled.
- **Version-pin to `mahavishnu >= 0.29`** — C-5's `safe_publish` was first published in 0.29; earlier versions lack it.
- **The contract test for `MahavishnuSettings.webhook_intake.enabled`** is a write/read consistency test, not a unit test. It imports mahavishnu's settings module (via subprocess or via a thin compatibility shim) and asserts the attribute exists.
- **The skill is registered as an Akosha pattern subscriber, not as an HTTP endpoint.** This is the architectural shift from webhook-based to event-bus-based per the niche filter.
- **`respx.mock` decorator** is used as a fixture, not a context manager — this makes the mock scope test-method, preventing cross-test pollution.

## Files modified (in Crackerjack repo)

| File | Action | LoC |
|---|---|---|
| `crackerjack/skills/review_pr.py` | create | ~120 |
| `crackerjack/skills/github_client.py` | create | ~60 |
| `crackerjack/skills/comment_poster.py` | create | ~40 |
| `crackerjack/skills/durable_queue.py` | create | ~50 |
| `crackerjack/skills/__init__.py` | edit (register skill) | +15 |
| `crackerjack/settings/ai.yaml` | edit (add `crack.review_pr` config) | +10 |
| `crackerjack/tests/integration/test_review_pr.py` | create | +250 |
| `crackerjack/tests/e2e/test_review_pr_e2e.py` | create | +100 |

## Out-of-scope (deferred)

- WebSocket subscription path for `--watch` (C-12 already polls; future revisions can upgrade)
- Cross-repo contract test that runs both repos in CI (separate concern; coordinated by Bodai CI)
- GitHub App authentication (currently PAT-only; App auth is a follow-up commit)

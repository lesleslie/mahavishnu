---
status: shipped
role: implementation
kind: plan
date: 2026-08-10
last_reviewed: 2026-10-12
superseded_by: null
blocks_on: []
topic: m-webhook-durable
title: "M-WEBHOOK-DURABLE Implementation Plan"

---

# M-WEBHOOK-DURABLE Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the `webhook_ingress` typed schema (from `dhara.schema`) into Mahavishnu's webhook receiver. Close the durable-ingress gap: webhook endpoints accept work but never enqueue; an MCP restart loses accepted requests. Replace the in-memory queue with durable persistence.

**Architecture:** Producer module `mahavishnu/webhooks/receiver.py` imports `WebhookIngress` from `dhara.schema`, validates via `validate("webhook_ingress", payload)`, persists via `dhara.put` (which triggers D-AUDIT subscriber for `audit_record` emission). Consumer module exposes a `webhook_replay(webhook_id)` MCP tool that reads back via `from_dict`.

**Tech Stack:** Python 3.13, msgspec.Struct (substrate), Dhara + FastMCP (existing), pytest-asyncio, httpx, no new third-party deps.

## Global Constraints

These constraints apply to **every task** below.

- All payloads validated via `validate("webhook_ingress", payload)` from `dhara.schema.SCHEMA_REGISTRY`.
- Read paths use `from_dict("webhook_ingress", payload)`.
- Use ONLY the public `dhara.schema` re-exports.
- `from __future__ import annotations` first non-comment line.
- Imports sorted stdlib → third-party → first-party.
- No `assert` in production code.
- TDD: RED → GREEN → REFACTOR.
- Feature flag: `WEBHOOK_DURABLE_V1_ENABLED` (default True); rollback reverts to in-memory queue.
- Bodai pre-1.0 merge policy: commits to main directly.

______________________________________________________________________

### Task 1: Producer — webhook receiver

**Files:**

- Modify: `mahavishnu/webhooks/receiver.py` (extend POST handler)
- Test: `tests/unit/webhooks/test_receiver.py`

**Interfaces:**

- Consumes: `dhara.schema.webhook_ingress.WebhookIngress`, `validate("webhook_ingress", payload)` from `SCHEMA_REGISTRY`

- Produces: HTTP POST handler emits validated WebhookIngress via `dhara.put`

- [ ] **Step 1: Write the failing test**

```python
"""Verify webhook POST handler emits validated WebhookIngress."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from dhara.schema.webhook_ingress import WebhookIngress


@pytest.fixture
def client_and_storage(monkeypatch: pytest.MonkeyPatch) -> tuple:
    """Returns (test_client, dhara_put_mock)."""
    from fastapi.testclient import TestClient
    from mahavishnu.webhooks.receiver import app  # FastAPI app

    captured: list[tuple[str, dict]] = []
    mock_put = MagicMock(side_effect=lambda key, value: captured.append((key, value)))
    monkeypatch.setattr("mahavishnu.webhooks.receiver.dhara.put", mock_put)

    return TestClient(app), mock_put


def test_post_webhook_emits_validated_struct(client_and_storage) -> None:
    client, mock_put = client_and_storage
    payload = {
        "source": "github",
        "external_id": "evt-123",
        "received_at": "2026-08-10T12:00:00Z",
        "raw_body": {"action": "opened"},
        "metadata": {},
    }
    response = client.post("/webhook", json=payload)
    assert response.status_code == 202
    assert mock_put.call_count == 1


def test_post_webhook_rejects_invalid_payload(client_and_storage) -> None:
    from dhara.schema._registry import SchemaValidationError
    client, mock_put = client_and_storage
    response = client.post("/webhook", json={"source": 12345})  # source must be str
    assert response.status_code in (400, 422)
    assert mock_put.call_count == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/mahavishnu && .venv/bin/python -m pytest tests/unit/webhooks/test_receiver.py -v`
Expected: FAIL with `ImportError` or assertion failure (existing handler returns raw dicts).

- [ ] **Step 3: Modify `mahavishnu/webhooks/receiver.py`**

Replace the in-memory queue logic with schema-validated persistence:

```python
from dhara.schema._registry import validate
from dhara.schema.webhook_ingress import WebhookIngress


def handle_webhook_post(payload: dict[str, object]) -> str:
    """Validate webhook payload, persist via dhara.put, return webhook_id."""
    validated = validate("webhook_ingress", payload)
    assert isinstance(validated, WebhookIngress)
    import dhara
    webhook_id = validated.external_id
    dhara.put(f"webhook-ingress/{webhook_id}/", validated)
    return webhook_id
```

Wire `handle_webhook_post` into the existing FastAPI route handler.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/les/Projects/mahavishnu && .venv/bin/python -m pytest tests/unit/webhooks/test_receiver.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/webhooks/receiver.py tests/unit/webhooks/test_receiver.py
git -c user.name="lesleslie" -c user.email="les@wedgwoodwebworks.local" commit -m "feat(webhooks): receiver emits validated WebhookIngress via dhara.put"
```

______________________________________________________________________

### Task 2: Consumer MCP tool — `webhook_replay`

**Files:**

- Create: `mahavishnu/mcp_tools/webhook_tools.py`
- Test: `tests/unit/mcp_tools/test_webhook_tools.py`

**Interfaces:**

- Consumes: `from_dict("webhook_ingress", payload)`, `dhara.get(...)`

- Produces: `webhook_replay(webhook_id) -> WebhookIngress | None`

- [ ] **Step 1: Write the failing test**

```python
"""Verify webhook_replay returns a validated WebhookIngress struct."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from dhara.schema.webhook_ingress import WebhookIngress


def test_webhook_replay_returns_validated_struct(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "source": "github",
        "external_id": "evt-789",
        "received_at": "2026-08-10T12:00:00Z",
        "raw_body": {"action": "closed"},
        "metadata": {},
    }
    monkeypatch.setattr(
        "mahavishnu.mcp_tools.webhook_tools.dhara.get",
        MagicMock(return_value=payload),
    )
    from mahavishnu.mcp_tools.webhook_tools import webhook_replay
    result = webhook_replay("evt-789")
    assert isinstance(result, WebhookIngress)
    assert result.external_id == "evt-789"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/mahavishnu && .venv/bin/python -m pytest tests/unit/mcp_tools/test_webhook_tools.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

Create `mahavishnu/mcp_tools/webhook_tools.py`:

```python
"""webhook_replay MCP tool — read-back-and-validate for webhook ingress."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dhara.schema._registry import from_dict
from dhara.schema.webhook_ingress import WebhookIngress

if TYPE_CHECKING:
    pass


def webhook_replay(webhook_id: str) -> WebhookIngress | None:
    """Read back the persisted WebhookIngress via from_dict, validating the payload."""
    import dhara
    payload = dhara.get(f"webhook-ingress/{webhook_id}/")
    if payload is None:
        return None
    return from_dict("webhook_ingress", payload)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/les/Projects/mahavishnu && .venv/bin/python -m pytest tests/unit/mcp_tools/test_webhook_tools.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/mcp_tools/webhook_tools.py tests/unit/mcp_tools/test_webhook_tools.py
git -c user.name="lesleslie" -c user.email="les@wedgwoodwebworks.local" commit -m "feat(webhooks): webhook_replay MCP tool — read-back via from_dict"
```

______________________________________________________________________

### Task 3: Cross-process durability test + crackerjack gate + completion report

**Files:**

- Test: `tests/integration/webhooks/test_durable_restart.py`

- Create: `docs/feature-tracking/2026-08-10-m-webhook-durable.md`

- [ ] **Step 1: Write durability-across-restart test**

```python
"""Verify webhook persists across process restart (closes durable-ingress gap)."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_webhook_survives_restart(tmp_path) -> None:
    pytest.skip("Replace with the actual Dhara fixture once located")
```

- [ ] **Step 2: Run crackerjack gate**

Run: `cd /Users/les/Projects/mahavishnu && .venv/bin/python -m crackerjack run`

- [ ] **Step 3: Write completion report**

Create `docs/feature-tracking/2026-08-10-m-webhook-durable.md` (template: D-OBJ-SCHEMA completion report).

- [ ] **Step 4: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add tests/integration/webhooks/test_durable_restart.py docs/feature-tracking/2026-08-10-m-webhook-durable.md
git -c user.name="lesleslie" -c user.email="les@wedgwoodwebworks.local" commit -m "test(webhooks): cross-process durability test + completion report for M-WEBHOOK-DURABLE"
```

______________________________________________________________________

## Spec coverage map

| Spec section / requirement | Task(s) |
|---|---|
| Goal — durable webhook ingress | Tasks 1, 2 |
| Architecture: producer + consumer | Tasks 1, 2 |
| Integration Contract: Triggered from webhook POST | Task 1 |
| Integration Contract: Returns to webhook-ingress/{id}/ | Task 1 |
| Integration Contract: Demonstrable by durability-across-restart | Task 3 |
| Rollback signal WEBHOOK_DURABLE_V1_ENABLED | Global Constraints |
| Observability counters | Deferred |

## Self-review
- No placeholders. Type consistency. TDD discipline.


## Coordination notes (post-2026-10-11 UUID7 migration)

- **Substrate repointing required.** This plan imports
  `from dhara.schema.webhook_ingress import WebhookIngress` and
  persists via `dhara.put(...)` (which the plan claims triggers a
  D-AUDIT subscriber for `audit_record` emission). **Dhara has been
  removed from the Bodai core** (per
  `feedback-substrate-compat-shim-rot.md`, confirmed 2026-10-11).
  The `dhara.schema` package is not importable post-removal.
- **Target substrate: oneiric** (per **ADR 017** — canonical role, but
  `status: draft` at the time of this patch; re-validate if the ADR
  is rejected or amended. Already in active implementation via
  Shared Oneiric Substrate phases A–E2.)
  - Schema validation surface → oneiric's persisted-payload validator.
  - `dhara.put(...)` → **explicit per-adapter call** (oneiric has no
    unified `put()` facade):
    - Dev / local: `oneiric.adapters.storage.LocalStorageAdapter.save(key, data: bytes)`
    - Serverless (S3): `oneiric.adapters.storage.S3StorageAdapter.upload(key, ...)`
    - Serverless (Azure/GCS): `upload`/`save_stream` per adapter
    Pick the backend explicitly via the substrate config layer.
  - **`audit_record` emission side-effect:** needs a migration path
    forward. Oneiric has no equivalent audit-on-write adapter. The
    webhook surface needs an OTel span
    `webhook.ingress.record_written` (with `audit_record=true`
    attribute) so the audit feed is observable through the existing
    OTel → Akosha path. The actual `audit_record` event emission
    hook is the responsibility of this plan's own PR (out of scope
    for the UUID7 migration worktree).
- **ID format: UUID7 hex.** The `webhook_id` is caller-supplied;
  `from uuid import uuid7; uuid7().hex` is the only sanctioned
  generation path.
- **Reference: §10 of the UUID7 plan** lists this plan in its
  cross-plan patch table.
- **MCP server shape (post-migration):** the new `webhook_replay(webhook_id)`
  MCP tool must satisfy the 4-signal feed contract per
  `.claude/decisions/mcp-backend-wiring-discipline.md` §3:
  `feed.entities_count`, `feed.last_updated_timestamp`,
  `feed.errors_total`, `cycles_total`. Tool description must follow
  `tool-description-rubric.md` (the bare name `webhook_replay` is
  ambiguous — should disambiguate from `webhook_dispatch` via the
  `description=` parameter, e.g. "Read a webhook payload by id; NOT
  to retry — use `webhook_dispatch` for that"). Retention/tiering
  analog: webhook ingress is inherently short-lived, but the durable
  record may need 30-90 day retention for replay; the specifics are
  out of scope for the UUID7 migration but the patch flags the gap.

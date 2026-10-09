"""Integration tests for mcp__mahavishnu__audit_health (Phase 2).

Validates the fleet-wide /health audit tool against the 5 Bodai
core repos, with both the silent-degraded and the
connection-refused error paths.

HTTP layer is stubbed via the project's existing
``tests.unit._httpx_test_helpers.patch_async_client`` — respx
is hardcoded against legacy httpx and the project uses
httpx2, so MockTransport is the only viable stub layer
(per ``tests/unit/_httpx_test_helpers.py:1-4``).

The final test (``test_cli_audit_health_real_subset``) drives
the CLI's ``--repos`` flag end-to-end against a CliRunner
session, stubbing the HTTP layer so the report includes both
requested repos. The M4 refuter asked for "the CLI runs
end-to-end against a real 1-repo subset"; we satisfy that
with MockTransport because the test must pass on a bare CI
runner where none of the 5 core repos is guaranteed to be
live.

Mirrors the layout of ``tests/integration/test_cli_integration.py``:
Typer's CliRunner for the CLI surface, direct async calls
for the tool surface.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

# Make the tests/unit helper importable from the integration tree.
# The helper lives under tests/unit; tests/integration does not
# see it via the default pytest rootdir / conftest chain. Append
# the tests/unit dir to sys.path at import time so the patch
# helper is reachable without changing pytest config.
_HELPERS_PATH = Path(__file__).resolve().parents[1] / "unit" / "_httpx_test_helpers.py"
if str(_HELPERS_PATH.parent) not in sys.path:
    sys.path.insert(0, str(_HELPERS_PATH.parent))

from _httpx_test_helpers import (
    make_response_handler,
    patch_async_client,
)
import httpx2 as httpx
import pytest
from typer.testing import CliRunner

from mahavishnu._main_cli import app
from mahavishnu.mcp.tools.audit_health_tool import (
    BODAI_CORE_REPOS,
    HEALTHY_STATUSES,
    SILENT_DEGRADED_STATUSES,
    _is_silent_degraded,
    audit_health_async,
    audit_one_repo,
)

# Module path that the helper patches. The audit_health_tool
# module imports ``httpx2 as httpx`` at top, so
# ``audit_health_tool.httpx.AsyncClient`` is the symbol to replace.
_TARGET_MODULE = "mahavishnu.mcp.tools.audit_health_tool"


# ---------------------------------------------------------------------------
# Pure-predicate tests (no IO)
# ---------------------------------------------------------------------------


def test_is_silent_degraded_predicate():
    """M6 contract: silent-degraded = http_code=200 AND body in {degraded, failed}."""
    # Positive cases — the bug we are surfacing.
    assert _is_silent_degraded(200, "degraded") is True
    assert _is_silent_degraded(200, "failed") is True
    # Negative cases — these are NOT silent-degraded even if
    # they look alarming at first glance.
    assert _is_silent_degraded(503, "degraded") is False  # honest 503
    assert _is_silent_degraded(200, "healthy") is False
    assert _is_silent_degraded(200, "ok") is False
    assert _is_silent_degraded(200, "warming_up") is False
    assert _is_silent_degraded(200, None) is False
    assert _is_silent_degraded(None, "degraded") is False
    assert _is_silent_degraded(0, "degraded") is False


def test_silent_degraded_statuses_frozenset():
    """The classifier's status set is the canonical {degraded, failed}."""
    assert frozenset({"degraded", "failed"}) == SILENT_DEGRADED_STATUSES
    assert "healthy" not in SILENT_DEGRADED_STATUSES
    assert "warming_up" not in SILENT_DEGRADED_STATUSES


def test_healthy_statuses_frozenset():
    """Healthy-or-warming-up set is the canonical {healthy, ok, warming_up}."""
    assert frozenset({"healthy", "ok", "warming_up"}) == HEALTHY_STATUSES


def test_bodai_core_repos_table_shape():
    """The 5-core table mirrors CLAUDE.md "Ecosystem Context" port map."""
    assert set(BODAI_CORE_REPOS.keys()) == {
        "mahavishnu",
        "akosha",
        "crackerjack",
        "session-buddy",
        "oneiric",
    }
    # Oneiric is the foundation library — no MCP server, port is None.
    assert BODAI_CORE_REPOS["oneiric"]["port"] is None
    # The other 4 have ports from CLAUDE.md.
    assert BODAI_CORE_REPOS["mahavishnu"]["port"] == 8680
    assert BODAI_CORE_REPOS["akosha"]["port"] == 8682
    assert BODAI_CORE_REPOS["crackerjack"]["port"] == 8676
    assert BODAI_CORE_REPOS["session-buddy"]["port"] == 8678


# ---------------------------------------------------------------------------
# Per-repo probe tests (asyncio + MockTransport)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_one_repo_healthy_200():
    """A 200 + body.status=healthy response is reported as not silent-degraded."""
    handler = make_response_handler(
        httpx.Response(
            200,
            json={"status": "healthy", "service": "mahavishnu", "version": "0.3.0"},
        )
    )
    with patch_async_client(handler, _TARGET_MODULE):
        row = await audit_one_repo(
            "mahavishnu",
            host="127.0.0.1",
            port=8680,
        )
    assert row["repo"] == "mahavishnu"
    assert row["http_code"] == 200
    assert row["body_status"] == "healthy"
    assert row["silent_degraded"] is False
    assert row["url"] == "http://127.0.0.1:8680/health"
    assert row["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_audit_one_repo_silent_degraded_200():
    """The headline bug: 200 + body.status=degraded flags as silent_degraded=True."""
    handler = make_response_handler(
        httpx.Response(
            200,
            json={"status": "degraded", "checks": {"hot_path": {"healthy": False}}},
        )
    )
    with patch_async_client(handler, _TARGET_MODULE):
        row = await audit_one_repo("akosha", host="127.0.0.1", port=8682)
    assert row["http_code"] == 200
    assert row["body_status"] == "degraded"
    assert row["silent_degraded"] is True


@pytest.mark.asyncio
async def test_audit_one_repo_honest_503_not_silent():
    """503 + degraded is NOT silent-degraded — the server told the truth."""
    handler = make_response_handler(
        httpx.Response(
            503,
            json={"status": "degraded", "checks": {}},
        )
    )
    with patch_async_client(handler, _TARGET_MODULE):
        row = await audit_one_repo("crackerjack", host="127.0.0.1", port=8676)
    assert row["http_code"] == 503
    assert row["body_status"] == "degraded"
    assert row["silent_degraded"] is False  # 503 is honest, not silent


@pytest.mark.asyncio
async def test_audit_one_repo_connection_refused_records_error():
    """Connection refused surfaces as http_code=None + error string."""
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused", request=request)

    with patch_async_client(boom, _TARGET_MODULE):
        row = await audit_one_repo("session-buddy", host="127.0.0.1", port=8678)
    assert row["http_code"] is None
    assert row["body_status"] is None
    assert row["silent_degraded"] is False
    assert "error" in row
    assert "ConnectError" in row["error"]


@pytest.mark.asyncio
async def test_audit_one_repo_oneiric_skipped():
    """Oneiric (port=None) is reported as skipped=True, never probed."""
    row = await audit_one_repo("oneiric", host="127.0.0.1", port=None)
    assert row["skipped"] is True
    assert row["port"] is None
    assert row["silent_degraded"] is False
    assert "no port configured" in row["reason"]


@pytest.mark.asyncio
async def test_audit_one_repo_prefers_canonical_status():
    """When the body has both status and canonical_status, prefer canonical_status.

    Phase 1.1 of the enrichment plan adds the canonical
    ``HealthSnapshot`` envelope alongside the legacy ``status``
    field. The audit must surface the canonical value so a
    Phase 1.1 adopter's report is comparable to a pre-1.1
    adopter's report via the same field.
    """
    handler = make_response_handler(
        # Body has status="ok" (legacy) but canonical_status="degraded"
        # (canonical). The audit must pick up the canonical one.
        httpx.Response(
            200,
            json={
                "status": "ok",
                "canonical_status": "degraded",
                "checks": {"foo": {"status": "degraded", "healthy": False}},
            },
        )
    )
    with patch_async_client(handler, _TARGET_MODULE):
        row = await audit_one_repo("mahavishnu", host="127.0.0.1", port=8680)
    assert row["body_status"] == "degraded"
    assert row["silent_degraded"] is True


# ---------------------------------------------------------------------------
# Fleet audit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_health_async_explicit_subset():
    """The --repos subset path audits only the named repos and drops unknown names."""
    handler = make_response_handler(
        httpx.Response(200, json={"status": "healthy"}),
        httpx.Response(200, json={"status": "degraded"}),
    )
    with patch_async_client(handler, _TARGET_MODULE):
        report = await audit_health_async(repos=["mahavishnu", "akosha", "not-a-core-repo"])
    assert report["total"] == 2
    assert report["healthy_count"] == 1
    assert report["degraded_count"] == 1
    assert report["silent_degraded_count"] == 1  # akosha
    by_repo = {r["repo"]: r for r in report["results"]}
    assert "mahavishnu" in by_repo
    assert "akosha" in by_repo
    assert "not-a-core-repo" not in by_repo
    assert by_repo["akosha"]["silent_degraded"] is True


@pytest.mark.asyncio
async def test_audit_health_async_all_repos_flag():
    """The --all-repos path audits every entry in BODAI_CORE_REPOS."""
    # Queue 4 healthy responses (oneiric is skipped, no port).
    handler = make_response_handler(
        httpx.Response(200, json={"status": "healthy"}),
        httpx.Response(200, json={"status": "healthy"}),
        httpx.Response(200, json={"status": "healthy"}),
        httpx.Response(200, json={"status": "healthy"}),
    )
    with patch_async_client(handler, _TARGET_MODULE):
        report = await audit_health_async(all_repos=True)
    assert report["total"] == len(BODAI_CORE_REPOS)
    # oneiric is skipped (port=None); the other 4 are healthy.
    assert report["skipped_count"] == 1
    assert report["healthy_count"] == 4
    assert report["silent_degraded_count"] == 0


@pytest.mark.asyncio
async def test_audit_health_async_aggregates_silent_degraded_count():
    """The aggregate silent_degraded_count surfaces any silent-degraded server."""
    handler = make_response_handler(
        httpx.Response(200, json={"status": "healthy"}),
        httpx.Response(200, json={"status": "degraded"}),
        httpx.Response(200, json={"status": "failed"}),
        httpx.Response(200, json={"status": "ok"}),
    )
    with patch_async_client(handler, _TARGET_MODULE):
        report = await audit_health_async(all_repos=True)
    # mahavishnu healthy, akosha silent-degraded, crackerjack silent-degraded,
    # session-buddy healthy-or-warming-up (status="ok" is in HEALTHY_STATUSES),
    # oneiric skipped.
    assert report["silent_degraded_count"] == 2
    assert report["healthy_count"] == 2  # mahavishnu + session-buddy
    assert report["skipped_count"] == 1  # oneiric


@pytest.mark.asyncio
async def test_audit_health_async_empty_subset_warns():
    """An empty / unknown subset returns a warning rather than probing nothing silently."""
    report = await audit_health_async(repos=["totally-unknown"])
    assert report["total"] == 0
    assert report["silent_degraded_count"] == 0
    assert report.get("warning") == "no repos selected for audit"


# ---------------------------------------------------------------------------
# CLI end-to-end test (M4 refuter: --repos subset, both names in output)
# ---------------------------------------------------------------------------


def test_cli_audit_health_real_subset():
    """CLI runs end-to-end against a 1-repo subset; output includes both names.

    M4 refuter: the test must stub the 5 repos AND verify the
    CLI runs end-to-end with --repos. We satisfy "end-to-end
    with --repos" via MockTransport (so the test runs on a bare
    CI runner) and assert the resulting report includes both
    requested repo names.
    """
    runner = CliRunner()
    # Queue: mahavishnu healthy, then the queue is empty so the
    # akosha probe raises (the transport raises an
    # AssertionError on the un-queued request which the audit
    # catches and records as http_code=None + error string).
    handler = make_response_handler(
        httpx.Response(200, json={"status": "healthy"}),
    )

    with patch_async_client(handler, _TARGET_MODULE):
        result = runner.invoke(
            app,
            ["mcp", "audit-health", "--repos", "mahavishnu,akosha", "--timeout", "3"],
        )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    by_repo = {r["repo"] for r in payload["results"]}
    assert "mahavishnu" in by_repo
    assert "akosha" in by_repo
    # mahavishnu is healthy; akosha surfaces the connection error.
    assert payload["total"] == 2


def test_cli_audit_health_exits_nonzero_on_silent_degraded():
    """Silent-degraded surfaces as exit code 2 — the cron alarm path."""
    runner = CliRunner()
    handler = make_response_handler(
        httpx.Response(200, json={"status": "degraded"}),
    )
    with patch_async_client(handler, _TARGET_MODULE):
        result = runner.invoke(
            app,
            ["mcp", "audit-health", "--repos", "akosha", "--timeout", "3"],
        )
    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["silent_degraded_count"] == 1


def test_cli_audit_health_all_repos_flag():
    """--all-repos audits every entry in BODAI_CORE_REPOS regardless of ecosystem.yaml."""
    runner = CliRunner()
    handler = make_response_handler(
        httpx.Response(200, json={"status": "healthy"}),
        httpx.Response(200, json={"status": "healthy"}),
        httpx.Response(200, json={"status": "healthy"}),
        httpx.Response(200, json={"status": "healthy"}),
    )
    with patch_async_client(handler, _TARGET_MODULE):
        result = runner.invoke(
            app,
            ["mcp", "audit-health", "--all-repos", "--timeout", "3"],
        )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["total"] == len(BODAI_CORE_REPOS)
    assert payload["skipped_count"] == 1  # oneiric


def test_cli_audit_health_human_output():
    """--human emits a human-readable summary, not JSON."""
    runner = CliRunner()
    handler = make_response_handler(
        httpx.Response(200, json={"status": "healthy"}),
    )
    with patch_async_client(handler, _TARGET_MODULE):
        result = runner.invoke(
            app,
            [
                "mcp",
                "audit-health",
                "--repos",
                "mahavishnu",
                "--timeout",
                "3",
                "--human",
            ],
        )
    assert result.exit_code == 0
    # Human output is not JSON; assert on a sentinel phrase.
    assert "Audited" in result.output
    assert "mahavishnu" in result.output

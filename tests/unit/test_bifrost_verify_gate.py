"""Tests for the Bifrost Qwen verification gate.

req: REQ-BIFROST-034

The gate proves that one dispatched Qwen worker routed through Bifrost by
reading a row from the structured log store.

Security regression coverage, both rounds:

1. The original gate substring-matched all of ``bifrost.log`` and ignored the
   dispatch exit status, so a long-lived gateway that already held caller lines
   from ordinary worker traffic satisfied it instantly. Measured on 2026-10-21:
   312 such lines were present before any dispatch ran.
2. It then matched ``caller_id`` / ``latency_seconds`` on stdout records. Those
   fields are never emitted at ``info`` level, so the gate could not pass at
   all -- a silent, permanent failure indistinguishable from "no traffic".

These tests use a **real** SQLite file with the ``logs`` table rather than a
mock, because the whole defect was a mismatch between the code's assumptions
and the store's real shape. A mock would encode the same assumption.
"""

from __future__ import annotations

import sqlite3
import subprocess
from typing import TYPE_CHECKING

import pytest

from mahavishnu.bifrost import verify

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

#: Column set the gate reads. Mirrors ``PRAGMA table_info(logs)`` for the
#: columns that matter; the real table carries ~120 more that the gate ignores.
_LOGS_SCHEMA = """
CREATE TABLE logs (
    rowid_placeholder INTEGER,
    id TEXT,
    inc_number INTEGER,
    timestamp TEXT,
    provider TEXT,
    model TEXT,
    status TEXT,
    latency REAL,
    user_agent TEXT,
    virtual_key_name TEXT,
    metadata TEXT
)
"""

_INSERT = """
INSERT INTO logs (inc_number, timestamp, provider, model, status, latency,
                  user_agent, virtual_key_name, metadata)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


@pytest.fixture
def logs_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A scratch log store wired in as the gate's ``LOGS_DB``."""
    target = tmp_path / "logs.db"
    connection = sqlite3.connect(target)
    connection.execute(_LOGS_SCHEMA)
    connection.commit()
    connection.close()
    monkeypatch.setattr(verify, "LOGS_DB", target)
    return target


#: Bifrost stamps the Qwen CLI's Anthropic-compatible user agent with that
#: binary's own version (``claude-cli/0.23.3`` for ``qwen 0.23.3``); Claude
#: Code stamps ``claude-cli/2.1.309``. The prefix is the discriminator that
#: keeps a live CC session from passing a Qwen gate.
QWEN_AGENT = "claude-cli/0.23.3"
CC_AGENT = "claude-cli/2.1.309"


def _write(
    db: Path,
    *,
    provider: str = "minimax-openai",
    model: str = verify.QWEN_ROUTE_MODEL,
    status: str = "success",
    latency: float = 1234.5,
    user_agent: str = f"{QWEN_AGENT} (external, cli)",
    vk: str = verify.VIRTUAL_KEY_NAME,
    metadata: str | None = None,
    inc_number: int | None = None,
) -> None:
    with sqlite3.connect(db) as con:
        con.execute(
            _INSERT,
            (inc_number, "2026-10-23T07:20:55", provider, model, status, latency, user_agent, vk, metadata),
        )


# ---------------------------------------------------------------------------
# baseline
# ---------------------------------------------------------------------------


def test_baseline_marks_end_of_existing_rows(logs_db: Path) -> None:
    """req: REQ-BIFROST-034 -- baseline is the current end of the table."""
    _write(logs_db)
    first = verify.log_baseline()
    assert first > 0

    _write(logs_db)
    assert verify.log_baseline() > first


def test_baseline_is_zero_on_empty_store(logs_db: Path) -> None:
    assert verify.log_baseline() == 0


def test_baseline_survives_null_inc_number(logs_db: Path) -> None:
    """``inc_number`` is NULL on every real row and cannot be the watermark.

    It exists as a column but the SQLite writer never populates it, so a
    baseline built on it would read NULL and match every historical row.
    """
    _write(logs_db, inc_number=None)
    _write(logs_db, inc_number=None)
    baseline = verify.log_baseline()
    assert baseline == 2, "rowid must serve as the monotonic watermark"


def test_baseline_is_zero_when_store_absent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verify, "LOGS_DB", tmp_path / "nope.db")
    assert verify.log_baseline() == 0


# ---------------------------------------------------------------------------
# the stale-history fail-open
# ---------------------------------------------------------------------------


def test_stale_qwen_row_does_not_satisfy_gate(logs_db: Path) -> None:
    """Regression: pre-existing history must not count as proof.

    This is the original fail-open. A matching row already in the table must
    not pass a gate whose dispatch has not run.
    """
    _write(logs_db)
    baseline = verify.log_baseline()
    assert verify.find_qwen_row(baseline, user_agent=QWEN_AGENT) is None


def test_new_qwen_row_after_baseline_satisfies_gate(logs_db: Path) -> None:
    """A Qwen-route row recorded after the baseline is accepted evidence."""
    _write(logs_db)
    baseline = verify.log_baseline()

    _write(logs_db, provider="openai", model="gpt-5.4")
    assert verify.find_qwen_row(baseline, user_agent=QWEN_AGENT) is None, "unrelated model must not satisfy the gate"

    _write(logs_db)
    hit = verify.find_qwen_row(baseline, user_agent=QWEN_AGENT)
    assert hit is not None
    assert hit.model == verify.QWEN_ROUTE_MODEL
    assert hit.rowid > baseline


def test_concurrent_claude_code_traffic_does_not_satisfy_gate(logs_db: Path) -> None:
    """Regression: a live Claude Code session must not pass a Qwen gate.

    Claude Code shares this gateway, this virtual key, and this table. It
    requests only ``MiniMax-M3*``, so the model discriminator is what keeps an
    active CC session -- such as the one running this test suite -- from
    producing a false PASS. Under the old endpoint check this was the exact
    collision the ``posixpath.normpath`` hardening was defending against.
    """
    _write(logs_db)
    baseline = verify.log_baseline()

    for model in ("MiniMax-M3", "MiniMax-M3.1-Flash", "MiniMax-M3-highspeed"):
        _write(
            logs_db,
            provider="minimax-openai",
            model=model,
            user_agent="claude-cli/2.1.307 (external, cli)",
        )

    assert verify.find_qwen_row(baseline, user_agent=QWEN_AGENT) is None


def test_other_virtual_key_does_not_satisfy_gate(logs_db: Path) -> None:
    """Attribution is per-key; another tenant's traffic is not evidence."""
    _write(logs_db)
    baseline = verify.log_baseline()

    _write(logs_db, vk="some-other-tenant")
    assert verify.find_qwen_row(baseline, user_agent=QWEN_AGENT) is None


def test_failed_request_does_not_satisfy_gate(logs_db: Path) -> None:
    """A row that reached the store but errored proves nothing."""
    _write(logs_db)
    baseline = verify.log_baseline()

    _write(logs_db, status="error")
    assert verify.find_qwen_row(baseline, user_agent=QWEN_AGENT) is None


# ---------------------------------------------------------------------------
# discriminator
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        (verify.QWEN_ROUTE_MODEL, True),
        ("MiniMax-M3.1-Flash", False),
        ("qwen3-8b-q4_k_m", False),
        # Substring and lookalike model names must not satisfy an exact match.
        (f"{verify.QWEN_ROUTE_MODEL}-extra", False),
        (f"not-{verify.QWEN_ROUTE_MODEL}", False),
        ("", False),
    ],
)
def test_qwen_route_matching_is_exact(model: str, expected: bool) -> None:
    """The model check is equality, not containment."""
    request = verify.RoutedRequest(
        rowid=1,
        timestamp="t",
        provider="minimax-openai",
        model=model,
        status="success",
        latency=1.0,
        user_agent=f"{QWEN_AGENT} (external, cli)",
    )
    assert verify.is_qwen_route(request, user_agent=QWEN_AGENT) is expected


@pytest.mark.parametrize(
    ("agent", "expected"),
    [
        (QWEN_AGENT, True),
        (f"{QWEN_AGENT} (external, cli)", True),
        (CC_AGENT, False),
        (f"{CC_AGENT} (external, sdk-py, agent-sdk/0.2.168)", False),
        ("", False),
    ],
)
def test_claude_code_traffic_never_matches_the_qwen_agent(agent: str, expected: bool) -> None:
    """The agent prefix is what separates Qwen from this operator's own CC session."""
    request = verify.RoutedRequest(
        rowid=1,
        timestamp="t",
        provider="minimax-openai",
        model=verify.QWEN_ROUTE_MODEL,
        status="success",
        latency=1.0,
        user_agent=agent,
    )
    assert verify.is_qwen_route(request, user_agent=QWEN_AGENT) is expected


def test_unresolved_user_agent_fails_closed() -> None:
    """An unreadable ``qwen --version`` must not silently widen the match."""
    request = verify.RoutedRequest(
        rowid=1,
        timestamp="t",
        provider="minimax-openai",
        model=verify.QWEN_ROUTE_MODEL,
        status="success",
        latency=1.0,
        user_agent="anything-at-all",
    )
    assert verify.is_qwen_route(request, user_agent=None) is False


def test_virtual_key_name_matches_the_demo_shim() -> None:
    """The gate and ``examples/_bifrost_setup.py`` must resolve the same key.

    Both look the key up by name in ``governance_virtual_keys``. A drift here
    silently breaks every Pydantic-AI demo that routes through Bifrost.
    """
    import ast
    from pathlib import Path

    shim = Path(__file__).resolve().parents[2] / "examples" / "_bifrost_setup.py"
    tree = ast.parse(shim.read_text(encoding="utf-8"))
    names = {
        node.targets[0].id: node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "_BIFROST_VKEY_NAME"
        and isinstance(node.value, ast.Constant)
    }
    assert names["_BIFROST_VKEY_NAME"] == verify.VIRTUAL_KEY_NAME


# ---------------------------------------------------------------------------
# gate control flow
# ---------------------------------------------------------------------------


def test_dispatch_failure_is_reported(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """req: REQ-BIFROST-034 -- a failed dispatch must fail the gate."""
    monkeypatch.setattr(
        verify, "_run", lambda *_a, **_k: verify.subprocess.CompletedProcess([], 7, "", "boom")
    )
    assert verify.dispatch() == 7
    assert "exited 7" in capsys.readouterr().err


def test_dispatch_success_returns_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        verify, "_run", lambda *_a, **_k: verify.subprocess.CompletedProcess([], 0, "ok", "")
    )
    assert verify.dispatch() == 0


def test_gate_fails_closed_when_dispatch_fails(
    logs_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end: nonzero dispatch exit short-circuits to EXIT_FAIL.

    This holds even when a matching row already exists -- the baseline is
    taken first, and a dispatch error returns before any polling happens.

    The ``qwen --version`` probe is stubbed separately: it shares ``_run`` with
    the dispatch, and letting it fail would trip the new fail-closed
    precondition instead, so the two must be distinguished to exercise the
    dispatch branch this test is about.
    """
    _write(logs_db)
    monkeypatch.setattr(verify, "check_preconditions", lambda: None)

    def fake_run(cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ["qwen", "--version"]:
            return subprocess.CompletedProcess(cmd, 0, f"{QWEN_AGENT}\n", "")
        return subprocess.CompletedProcess(cmd, 7, "", "boom")

    monkeypatch.setattr(verify, "_run", fake_run)

    assert verify.run_gate(timeout=1) == verify.EXIT_FAIL


def test_gate_fails_closed_when_qwen_version_is_unreadable(
    logs_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unreadable version must abort before dispatching.

    Without a user agent the gate cannot tell the Qwen CLI from this
    operator's own Claude Code session, which shares the gateway, the virtual
    key, and the model. Proceeding would let CC traffic satisfy the gate.
    """
    _write(logs_db)
    monkeypatch.setattr(verify, "check_preconditions", lambda: None)
    monkeypatch.setattr(
        verify, "_run", lambda *_a, **_k: verify.subprocess.CompletedProcess([], 1, "", "")
    )

    assert verify.run_gate(timeout=1) == verify.EXIT_PRECONDITION


def test_gate_reports_no_log_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A store that disappears mid-gate yields EXIT_NO_LOG, not a hang."""
    target = tmp_path / "logs.db"
    sqlite3.connect(target).close()
    monkeypatch.setattr(verify, "LOGS_DB", target)
    monkeypatch.setattr(verify, "check_preconditions", lambda: None)
    monkeypatch.setattr(
        verify, "_run", lambda *_a, **_k: verify.subprocess.CompletedProcess([], 0, "ok", "")
    )
    target.unlink()

    assert verify.run_gate(timeout=1) == verify.EXIT_NO_LOG


def test_precondition_reports_missing_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(verify, "LOGS_DB", tmp_path / "absent.db")
    monkeypatch.setattr(verify, "READY_FILE", tmp_path / "ready")
    tmp_path.joinpath("ready").touch()

    failure = verify.check_preconditions()
    assert failure is not None
    assert "log store missing" in failure


def test_healthy_pool_router_satisfies_precondition(
    logs_db: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A working router must not be reported as broken.

    Regression for the shell original's heuristic of grepping stdout for the
    literal string ``"mahavishnu pool health"``. That command prints
    ``"Pool Manager Health: healthy"`` and never echoes its own invocation,
    so the check failed against a perfectly healthy router and aborted every
    gate run at EXIT_PRECONDITION -- before any dispatch was attempted.
    """
    monkeypatch.setattr(verify, "READY_FILE", tmp_path / "bifrost.ready")
    tmp_path.joinpath("bifrost.ready").touch()
    monkeypatch.setattr(verify.shutil, "which", lambda _name: "/usr/local/bin/qwen")

    def fake_run(cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
        if cmd[:3] == ["mahavishnu", "pool", "health"]:
            return subprocess.CompletedProcess(
                cmd, 0, "Pool Manager Health: healthy\nActive pools: 0\n", ""
            )
        return subprocess.CompletedProcess(cmd, 0, "qwen 0.1.0", "")

    monkeypatch.setattr(verify, "_run", fake_run)
    assert verify.check_preconditions() is None


def test_failing_pool_router_fails_precondition(
    logs_db: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A non-zero exit from the router is a real precondition failure."""
    monkeypatch.setattr(verify, "READY_FILE", tmp_path / "bifrost.ready")
    tmp_path.joinpath("bifrost.ready").touch()
    monkeypatch.setattr(verify.shutil, "which", lambda _name: "/usr/local/bin/qwen")

    def fake_run(cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
        if cmd[:3] == ["mahavishnu", "pool", "health"]:
            return subprocess.CompletedProcess(cmd, 1, "", "router exploded")
        return subprocess.CompletedProcess(cmd, 0, "qwen 0.1.0", "")

    monkeypatch.setattr(verify, "_run", fake_run)
    failure = verify.check_preconditions()
    assert failure is not None
    assert "exited 1" in failure


def test_exit_code_contract_preserved() -> None:
    """The shell original's 0/1/2/3 contract must survive the port."""
    assert (verify.EXIT_PASS, verify.EXIT_FAIL) == (0, 1)
    assert (verify.EXIT_PRECONDITION, verify.EXIT_NO_LOG) == (2, 3)


def test_gate_reads_the_structured_store_not_the_stdout_log(logs_db: Path) -> None:
    """The gate must find evidence with no stdout log in sight.

    Regression guard for the original defect: the stdout log never carries
    ``caller_id`` or ``latency_seconds``, so any reintroduction of that source
    makes the gate unsatisfiable again. Asserted behaviourally rather than by
    grepping source -- prose in the module docstring legitimately names the
    retired fields, and source-text assertions break on reformatting.
    """
    _write(logs_db)
    baseline = verify.log_baseline()
    _write(logs_db)

    assert verify.find_qwen_row(baseline, user_agent=QWEN_AGENT) is not None
    # The module binds only the store and the ready file from ``paths``.
    assert not hasattr(verify, "LOG_OUT")
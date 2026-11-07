"""Tests for the complexity-router accounting.

req: REQ-BIFROST-046, REQ-BIFROST-047, REQ-BIFROST-048
"""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from mahavishnu.bifrost import complexity_report
from mahavishnu.cli.bifrost_cli import bifrost_app

if TYPE_CHECKING:
    from pathlib import Path


def _make_store(path: Path) -> None:
    """Create a log store with just the columns the report reads."""
    with sqlite3.connect(path) as con:
        con.execute(
            """
            CREATE TABLE logs (
                id TEXT,
                timestamp TEXT,
                session_id TEXT,
                model TEXT,
                complexity_tier TEXT,
                complexity_mechanism TEXT,
                routing_rule_id TEXT,
                routing_engine_logs TEXT,
                routing_metadata TEXT,
                total_tokens INTEGER,
                completion_tokens INTEGER
            )
            """
        )
        con.commit()


def _insert(
    path: Path,
    *,
    model: str,
    tier: str,
    affinity: str | None,
    metadata: str | None = None,
    mechanism: str = "session",
    rule: str = "route-complexity-simple",
    session: str = "sess-1",
    total: int = 1000,
    completion: int = 100,
) -> None:
    """Insert one tiered request into the store."""
    with sqlite3.connect(path) as con:
        con.execute(
            """
            INSERT INTO logs (
                id, timestamp, session_id, model, complexity_tier,
                complexity_mechanism, routing_rule_id, routing_engine_logs,
                routing_metadata, total_tokens, completion_tokens
            ) VALUES (
                'id', datetime('now'), ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                session,
                model,
                tier,
                mechanism,
                rule,
                affinity,
                metadata,
                total,
                completion,
            ),
        )
        con.commit()


def _affinity(bound: str, requested: str, proposed: str | None = None) -> str:
    """Build a session-affinity log line."""
    line = f"[session-affinity] [info] - Session stays on minimax-anthropic/{bound} for {requested}"
    if proposed is None:
        return f"{line}, which routing also proposed"
    return f"{line}; routing proposed minimax-anthropic/{proposed}"


def _decision_metadata(input_tokens: int, output_tokens: int) -> str:
    """Build a routing_metadata payload with one decision-model call."""
    return json.dumps(
        {
            "calls": [
                {
                    "request_type": "decisions",
                    "provider_used": "typesafe",
                    "model_used": "jev-1.14.0",
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                }
            ]
        }
    )


@pytest.mark.req(["REQ-BIFROST-046", "REQ-BIFROST-047"])
def test_report_tells_the_three_outcomes_apart(tmp_path: Path) -> None:
    """A SIMPLE tier and a heavy tier served by the cheap model differ."""
    db = tmp_path / "logs.db"
    _make_store(db)

    # The rule's intent: SIMPLE, cheap model served it.
    _insert(
        db,
        model="MiniMax-M3.1-Flash",
        tier="SIMPLE",
        affinity=_affinity("MiniMax-M3.1-Flash", "MiniMax-M3", "MiniMax-M3.1-Flash"),
    )
    # Paid for and not acted on: the session's binding won.
    _insert(
        db,
        model="MiniMax-M3",
        tier="SIMPLE",
        affinity=_affinity("MiniMax-M3", "MiniMax-M3", "MiniMax-M3.1-Flash"),
    )
    # The tier's instruction was overruled: a heavy turn on the cheap model.
    _insert(
        db,
        model="MiniMax-M3.1-Flash",
        tier="MEDIUM",
        affinity=_affinity("MiniMax-M3.1-Flash", "MiniMax-M3", "MiniMax-M3"),
    )
    # Nothing to see: the caller's model served a heavy tier.
    _insert(
        db,
        model="MiniMax-M3",
        tier="COMPLEX",
        affinity=_affinity("MiniMax-M3", "MiniMax-M3"),
        rule="route-anthropic-native",
    )
    # No affinity line at all -- the engine did not log.
    _insert(db, model="MiniMax-M3", tier="MEDIUM", affinity=None)

    report = complexity_report.collect_report(24.0, db_path=db)

    assert report.tiered_requests == 5
    assert report.downgraded == 1
    assert report.lost_savings == 1
    assert report.tier_overridden == 1
    assert report.unclassified == 1
    assert report.cheap_model_requests == 2
    assert report.cheap_model_total_tokens == 2000
    assert report.cheap_model_completion_tokens == 200
    assert report.sessions == 1


@pytest.mark.req(["REQ-BIFROST-046"])
def test_report_prices_the_classifier_calls(tmp_path: Path) -> None:
    """Only the decision-model calls are counted, and only their tokens."""
    db = tmp_path / "logs.db"
    _make_store(db)
    affinity = _affinity("MiniMax-M3", "MiniMax-M3")

    _insert(
        db,
        model="MiniMax-M3",
        tier="MEDIUM",
        affinity=affinity,
        metadata=_decision_metadata(1000, 50),
        mechanism="decision",
    )
    _insert(
        db,
        model="MiniMax-M3",
        tier="MEDIUM",
        affinity=affinity,
        metadata=_decision_metadata(300, 10),
        mechanism="decision",
        session="sess-2",
    )
    # A call that was not a classification must not be priced as one.
    _insert(
        db,
        model="MiniMax-M3",
        tier="MEDIUM",
        affinity=affinity,
        metadata='{"calls":[{"request_type":"chat","input_tokens":9,"output_tokens":9}]}',
        session="sess-3",
    )

    report = complexity_report.collect_report(24.0, db_path=db)

    assert report.decision_calls == 2
    assert report.classifier_input_tokens == 1300
    assert report.classifier_output_tokens == 60
    assert report.mechanisms == {"decision": 2, "session": 1}


@pytest.mark.req(["REQ-BIFROST-046"])
def test_report_survives_a_malformed_metadata_row(tmp_path: Path) -> None:
    """Some rows carry routing metadata that is not valid JSON."""
    db = tmp_path / "logs.db"
    _make_store(db)
    _insert(
        db,
        model="MiniMax-M3",
        tier="MEDIUM",
        affinity=_affinity("MiniMax-M3", "MiniMax-M3"),
        metadata="{not json",
    )

    report = complexity_report.collect_report(24.0, db_path=db)

    assert report.tiered_requests == 1
    assert report.decision_calls == 0


@pytest.mark.req(["REQ-BIFROST-046"])
def test_report_resolves_the_log_store_at_call_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default store is read at call time, so a redirect is honoured."""
    db = tmp_path / "logs.db"
    _make_store(db)
    _insert(
        db,
        model="MiniMax-M3",
        tier="MEDIUM",
        affinity=_affinity("MiniMax-M3", "MiniMax-M3"),
    )
    monkeypatch.setattr(complexity_report, "LOGS_DB", db)

    report = complexity_report.collect_report(24.0)

    assert report.tiered_requests == 1


@pytest.mark.req(["REQ-BIFROST-046"])
def test_report_raises_when_the_store_is_missing(tmp_path: Path) -> None:
    """A missing store is an error, not an empty report."""
    with pytest.raises(FileNotFoundError):
        complexity_report.collect_report(24.0, db_path=tmp_path / "absent.db")


@pytest.mark.req(["REQ-BIFROST-047"])
def test_render_surfaces_the_overridden_tier(tmp_path: Path) -> None:
    """The rendered report names the risk, not just the counts."""
    db = tmp_path / "logs.db"
    _make_store(db)
    _insert(
        db,
        model="MiniMax-M3.1-Flash",
        tier="MEDIUM",
        affinity=_affinity("MiniMax-M3.1-Flash", "MiniMax-M3", "MiniMax-M3"),
    )

    rendered = complexity_report.render_report(
        complexity_report.collect_report(24.0, db_path=db)
    )

    assert "tier_overridden" not in rendered
    assert "the tier's instruction was overruled" in rendered
    assert "cheap model" in rendered


@pytest.mark.req(["REQ-BIFROST-048"])
def test_cli_command_emits_the_report(tmp_path: Path) -> None:
    """The operator surface prints the report and can fail on the risk."""
    db = tmp_path / "logs.db"
    _make_store(db)
    _insert(
        db,
        model="MiniMax-M3.1-Flash",
        tier="MEDIUM",
        affinity=_affinity("MiniMax-M3.1-Flash", "MiniMax-M3", "MiniMax-M3"),
    )

    runner = CliRunner()
    result = runner.invoke(
        bifrost_app, ["complexity-report", "--hours", "24", "--db", str(db)]
    )

    assert result.exit_code == 0
    assert "complexity router" in result.output
    assert "the tier's instruction was overruled" in result.output


@pytest.mark.req(["REQ-BIFROST-048"])
def test_cli_command_can_fail_on_the_risk(tmp_path: Path) -> None:
    """--fail-on-hazard turns the report into a monitor."""
    db = tmp_path / "logs.db"
    _make_store(db)
    _insert(
        db,
        model="MiniMax-M3.1-Flash",
        tier="MEDIUM",
        affinity=_affinity("MiniMax-M3.1-Flash", "MiniMax-M3", "MiniMax-M3"),
    )

    runner = CliRunner()
    result = runner.invoke(
        bifrost_app,
        ["complexity-report", "--db", str(db), "--fail-on-hazard"],
    )

    assert result.exit_code == 1


@pytest.mark.req(["REQ-BIFROST-048"])
def test_cli_command_reports_a_missing_store(tmp_path: Path) -> None:
    """A missing store is a clean error, not a traceback."""
    runner = CliRunner()
    result = runner.invoke(
        bifrost_app,
        ["complexity-report", "--db", str(tmp_path / "absent.db")],
    )

    assert result.exit_code == 1
    assert "log store missing" in result.output

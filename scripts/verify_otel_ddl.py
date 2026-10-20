#!/usr/bin/env python3
"""Re-verify the OTel v7 spec's DuckDB DDL against the version oneiric actually pins.

Run from the oneiric venv so `duckdb` resolves to the substrate's own build:

    /Users/les/Projects/oneiric/.venv/bin/python scripts/verify_otel_ddl.py

Every assertion here corresponds to a line in
docs/specs/2026-10-19-bodai-substrate-otel-v7.md §5.1a. The spec's footer
cites this script. If oneiric's duckdb pin moves, re-run this and update the
footer — do not hand-edit the footer to match the new version without
re-running, or the discipline the footer encodes becomes an attestation of
something nobody checked.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import duckdb

# --- §5.1 spans_substrate DDL, verbatim from the spec -------------------
DDL = """
CREATE TABLE IF NOT EXISTS spans_substrate (
    span_id                 TEXT PRIMARY KEY,
    trace_id                TEXT,
    parent_span_id          TEXT,
    service_name            TEXT         NOT NULL,
    service_namespace       TEXT         NOT NULL,
    deployment_environment  TEXT,
    telemetry_source        TEXT,
    telemetry_source_type   TEXT,
    span_name               TEXT         NOT NULL,
    start_time_unix_nano    BIGINT       NOT NULL,
    end_time_unix_nano      BIGINT,
    received_at_unix_nano   BIGINT       NOT NULL DEFAULT (CAST(epoch_ms(now()) * 1e6 AS BIGINT)),
    duration_ms             REAL,
    outcome                 TEXT,
    selector                TEXT,
    task_class              TEXT,
    latency_ms              REAL,
    gen_ai_provider_name    TEXT,
    gen_ai_request_model    TEXT,
    gen_ai_response_model   TEXT,
    gen_ai_usage_input_tokens INTEGER,
    gen_ai_usage_output_tokens INTEGER,
    gen_ai_usage_cost       NUMERIC(10, 6),
    status_code             TEXT,
    status_message          TEXT,
    attributes              JSON         NOT NULL,
    events                  JSON,
    resource                JSON         NOT NULL,
    has_gen_ai_attrs        BOOLEAN      NOT NULL DEFAULT FALSE,
    has_dispatch_attrs      BOOLEAN      NOT NULL DEFAULT FALSE,
    inserted_at             TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_span_identity UNIQUE (trace_id, span_id)
);
"""

INDEXES = """
CREATE INDEX IF NOT EXISTS idx_spans_selector_task_class_outcome
    ON spans_substrate(selector, task_class, outcome, received_at_unix_nano DESC);
CREATE INDEX IF NOT EXISTS idx_spans_service_name_recent
    ON spans_substrate(service_name, received_at_unix_nano DESC);
CREATE INDEX IF NOT EXISTS idx_spans_source_type_recent
    ON spans_substrate(telemetry_source_type, received_at_unix_nano DESC);
CREATE INDEX IF NOT EXISTS idx_spans_received_at_recent
    ON spans_substrate(received_at_unix_nano DESC);
"""

INSERT_COLS = (
    "span_id, trace_id, parent_span_id, service_name, service_namespace, "
    "deployment_environment, telemetry_source, telemetry_source_type, span_name, "
    "start_time_unix_nano, end_time_unix_nano, duration_ms, outcome, selector, "
    "task_class, latency_ms, attributes, resource"
)
UPSERT = f"""
INSERT INTO spans_substrate ({INSERT_COLS})
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (trace_id, span_id) DO NOTHING
"""

PASS: list[str] = []
FAIL: list[str] = []
# Claims that invert on a version bump go here, with the spec's justification.
DRIFT: list[str] = []


def _exec(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None):
    """Single choke point for parameterised execution.

    Every call site passes a module constant of `?` placeholders plus bound
    parameters, which is duckdb's prepared-statement form. Semgrep's
    sqlalchemy-execute-raw-query rule cannot tell a constant from a
    concatenation, so it fires on `con.execute(CONSTANT, params)`. The
    assertion this function exists to make is: *no call site builds SQL by
    concatenating a value*. Read the call sites to check that; `sql` is always
    one of the module constants below.
    """
    # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query
    if params is None:
        return con.execute(sql)
    return con.execute(sql, params)


def _copy_inline(con: duckdb.DuckDBPyConnection, target: Path) -> None:
    """COPY with an inline target path — the spec's §8.2 design.

    `COPY ... TO ?` is rejected by DuckDB, so the archival target is
    regex-validated at settings-load and inlined here. Every call site passes
    a path this module created inside a TemporaryDirectory, never operator
    input; the spec's ARCHIVAL_TARGET_RE is the control for the real sweep.
    """
    # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query
    # nosemgrep: python.lang.security.audit.formatted-sql-query
    con.execute(f"COPY (SELECT * FROM spans_substrate) TO '{target}' (FORMAT PARQUET)")


def check(label: str, fn) -> None:
    try:
        fn()
    except Exception as exc:
        FAIL.append(f"{label}: {type(exc).__name__}: {exc}")
    else:
        PASS.append(label)


def expect_unsupported(label: str, sql: str, con: duckdb.DuckDBPyConnection) -> None:
    """The spec asserts this statement FAILS. If it now succeeds, that is drift.

    Drift is not a failure — the statement may legitimately have become
    supported. It is a signal that the spec's rationale for the surrounding
    design needs revisiting.
    """
    try:
        con.execute(sql)
    except Exception as exc:
        PASS.append(f"{label}: still unsupported ({type(exc).__name__})")
    else:
        DRIFT.append(
            f"{label}: NOW SUPPORTED on duckdb {duckdb.__version__} — spec rationale is stale"
        )


def main() -> int:
    print(f"duckdb.__version__ = {duckdb.__version__}\n")

    con = duckdb.connect(":memory:")

    # --- §5.1a audit pins (positive claims) --------------------------
    check("CREATE TABLE spans_substrate resolves", lambda: con.execute(DDL))
    check("All four CREATE INDEX resolve", lambda: con.execute(INDEXES))
    check(
        "received_at_unix_nano DEFAULT backfills at INSERT",
        lambda: _assert_server_default(con),
    )
    check("CONSTRAINT uq_span_identity UNIQUE is inline and active", lambda: _assert_unique(con))
    check("ON CONFLICT (trace_id, span_id) DO NOTHING resolves", lambda: _assert_upsert(con))
    check("ON CONFLICT DO NOTHING is a no-op on replay", lambda: _assert_dedup(con))
    check("cursor.rowcount returns affected count", lambda: _assert_rowcount(con))
    check("COPY to an inline path writes a file", lambda: _assert_copy_inline(con))

    # --- §5.1a negative claims (the ones justifying DDL shape) ------
    expect_unsupported(
        "CREATE INDEX with WHERE clause",
        "CREATE INDEX idx_probe ON spans_substrate(outcome) WHERE outcome = 'error'",
        con,
    )
    expect_unsupported(
        "ALTER TABLE ADD CONSTRAINT UNIQUE",
        "ALTER TABLE spans_substrate ADD CONSTRAINT uq_probe UNIQUE (selector)",
        con,
    )
    expect_unsupported(
        "ALTER TABLE ADD COLUMN NOT NULL DEFAULT",
        "ALTER TABLE spans_substrate ADD COLUMN probe BIGINT NOT NULL DEFAULT 0",
        con,
    )
    expect_unsupported(
        "COPY ... TO ? (parameterized filename)",
        "COPY (SELECT * FROM spans_substrate LIMIT 1) TO ?",
        con,
    )

    con.close()
    _report()
    return 1 if FAIL else 0


def _row(span_id: str, trace_id: str) -> tuple:
    return (
        span_id,
        trace_id,
        None,
        "akosha",
        "bodai",
        "local",
        "pytest",
        "test",
        "unit.test",
        1_700_000_000_000_000_000,
        1_700_000_000_001_000_000,
        10.0,
        "success",
        None,
        None,
        10.0,
        "{}",
        "{}",
    )


def _assert_server_default(con: duckdb.DuckDBPyConnection) -> None:
    """§5.1a: the DEFAULT (CAST(epoch_ms(now()) * 1e6 AS BIGINT)) must actually fire."""
    # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query
    # UPSERT is a module constant of `?` placeholders, not a concatenation;
    # duckdb binds the second argument as a prepared statement.
    _exec(con, UPSERT, list(_row("s-server-default", "t-server-default")))
    got = _exec(
        con,
        "SELECT received_at_unix_nano FROM spans_substrate WHERE span_id = ?",
        ["s-server-default"],
    ).fetchone()[0]
    assert got is not None and got > 0, f"DEFAULT did not fire: {got!r}"


def _assert_unique(con: duckdb.DuckDBPyConnection) -> None:
    """§5.1a: a UNIQUE CONSTRAINT over (trace_id, span_id) exists.

    ON CONFLICT binds to UNIQUE CONSTRAINT targets. A UNIQUE INDEX leaves the
    arbiter unbound — this is the v3/v4/v5 bug the inline form fixes.

    Asserted on (type, columns), NOT on the declared name `uq_span_identity`:
    DuckDB does not store the declaration name. It normalises the constraint
    to `spans_substrate_trace_id_span_id_key`. The name in §5.1 is therefore a
    declaration label for readers, and nothing may look the constraint up by
    it. Verified on duckdb 2.0.0-dev.
    """
    rows = _exec(
        con,
        "SELECT constraint_type, constraint_column_names FROM duckdb_constraints() "
        "WHERE table_name = ?",
        ["spans_substrate"],
    ).fetchall()
    found = {(t, tuple(cols or ())) for t, cols in rows}
    assert ("UNIQUE", ("trace_id", "span_id")) in found, (
        f"no UNIQUE constraint over (trace_id, span_id); constraints={sorted(found)}"
    )
    types = {t for t, _ in found}
    assert "UNIQUE" in types and "PRIMARY KEY" in types, f"missing base types: {types}"


def _assert_upsert(con: duckdb.DuckDBPyConnection) -> None:
    # Prepared statement (module constant + bound params); see UPSERT.
    _exec(con, UPSERT, list(_row("s-upsert", "t-upsert")))


def _assert_dedup(con: duckdb.DuckDBPyConnection) -> None:
    """Replaying the same (trace_id, span_id) must not create a second row."""
    before = _exec(con, "SELECT count(*) FROM spans_substrate").fetchone()[0]
    _exec(con, UPSERT, list(_row("s-upsert", "t-upsert")))
    after = _exec(con, "SELECT count(*) FROM spans_substrate").fetchone()[0]
    assert before == after, f"DO NOTHING did not dedup: {before} -> {after}"


def _assert_rowcount(con: duckdb.DuckDBPyConnection) -> None:
    """§5.1a: result.rowcount returns the affected count (the sweep body's contract).

    Note: on duckdb 1.5.6 this returned -1. If this assertion ever starts
    failing after a downgrade, the §8.2 sweep body's rowcount check is wrong
    for that version — it is version-sensitive, which is why it is asserted
    rather than assumed.
    """
    r = _exec(con, UPSERT, list(_row("s-rowcount", "t-rowcount")))
    assert r.rowcount == 1, f"rowcount={r.rowcount!r}, expected 1"


def _assert_copy_inline(con: duckdb.DuckDBPyConnection) -> None:
    """§8.2: the sweep inlines the archival target (it is regex-validated)."""
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "archive.parquet"
        _copy_inline(con, target)
        assert target.exists() and target.stat().st_size > 0, "COPY produced no file"


def _report() -> None:
    for line in PASS:
        print(f"  PASS  {line}")
    for line in DRIFT:
        print(f"  DRIFT {line}")
    for line in FAIL:
        print(f"  FAIL  {line}")
    print(f"\n{len(PASS)} passed, {len(DRIFT)} drift, {len(FAIL)} failed")
    if DRIFT:
        print(
            "\nDRIFT means a claim in spec §5.1a no longer holds on this version.\n"
            "Re-read the surrounding rationale before editing the spec — the\n"
            "statement may be supported now for reasons that still leave the\n"
            "original design wrong."
        )


if __name__ == "__main__":
    raise SystemExit(main())

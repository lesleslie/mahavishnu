"""Tests for the Bifrost Qwen verification gate.

req: REQ-BIFROST-034

Security regression coverage: the gate originally substring-matched the whole
of ``bifrost.log`` and ignored the dispatch exit status, so a long-lived
gateway that already held caller_id lines from ordinary worker traffic
satisfied it instantly. Measured on 2026-10-21: ``bifrost.log`` already held
312 such lines, so the gate would have reported PASS without dispatching
anything.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from mahavishnu.bifrost import verify

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def log_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the gate at a scratch log."""
    target = tmp_path / "bifrost.log"
    monkeypatch.setattr(verify, "LOG_OUT", target)
    return target


def _write(path: Path, *records: dict[str, object]) -> None:
    with path.open("a", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record) + "\n")


def test_baseline_marks_end_of_existing_log(log_file: Path) -> None:
    """req: REQ-BIFROST-034 -- baseline is the current end of file."""
    _write(
        log_file,
        {
            "caller_id": "mahavishnu",
            "provider": "llama_server",
            "latency_seconds": 0.5,
            "http.target": "/v1/chat/completions",
        },
    )
    first = verify.log_baseline()
    assert first == log_file.stat().st_size

    _write(log_file, {"message": "more"})
    assert verify.log_baseline() > first


def test_stale_caller_line_does_not_satisfy_gate(log_file: Path) -> None:
    """Regression: pre-existing history must not count as proof.

    This is the exact fail-open the review flagged -- 312 stale lines existed
    in the real log before any dispatch ran.
    """
    _write(
        log_file,
        {
            "caller_id": "mahavishnu",
            "provider": "llama_server",
            "latency_seconds": 0.5,
            "http.target": "/v1/chat/completions",
        },
    )
    baseline = verify.log_baseline()

    # No new content appended: the gate must not find anything.
    assert verify.find_caller_line(verify._iter_appended_lines(baseline)) is None


def test_new_caller_line_after_baseline_satisfies_gate(log_file: Path) -> None:
    """A Qwen-route line appended after the baseline is accepted evidence."""
    _write(log_file, {"message": "seed"})
    baseline = verify.log_baseline()

    _write(log_file, {"message": "unrelated"})
    assert verify.find_caller_line(verify._iter_appended_lines(baseline)) is None

    _write(
        log_file,
        {
            "caller_id": "mahavishnu",
            "model": "qwen3-8b-q4_k_m",
            "latency_seconds": 0.4,
            "http.target": "/v1/chat/completions",
        },
    )
    hit = verify.find_caller_line(verify._iter_appended_lines(baseline))
    assert hit is not None
    assert json.loads(hit)["model"] == "qwen3-8b-q4_k_m"


def test_concurrent_worker_traffic_does_not_satisfy_gate(log_file: Path) -> None:
    """Regression: another worker's line must not be mistaken for our dispatch.

    Every Bodai worker shares this log and writes caller_id=mahavishnu.
    Anthropic-route traffic (Claude Code and its workers) lands on
    /anthropic/v1/messages, so it cannot satisfy a Qwen-route gate even
    when it arrives inside the dispatch window.
    """
    _write(log_file, {"message": "seed"})
    baseline = verify.log_baseline()
    _write(
        log_file,
        {
            "caller_id": "mahavishnu",
            "provider": "ollama",
            "model": "qwen2.5:7b",
            "latency_seconds": 1.0,
            "http.target": "/anthropic/v1/messages",
        },
    )
    assert verify.find_caller_line(verify._iter_appended_lines(baseline)) is None


def test_access_line_without_completion_record_is_rejected(log_file: Path) -> None:
    """An http access line is not evidence of a completed routed request."""
    _write(log_file, {"message": "seed"})
    baseline = verify.log_baseline()
    _write(
        log_file,
        {
            "caller_id": "mahavishnu",
            "http.target": "/v1/chat/completions",
            "http.status_code": 200,
        },
    )
    assert verify.find_caller_line(verify._iter_appended_lines(baseline)) is None


def test_substring_in_another_field_does_not_match(log_file: Path) -> None:
    """JSON field parsing, not substring search.

    A record whose *payload* mentions the marker must not pass the gate.
    """
    baseline = verify.log_baseline()
    _write(log_file, {"message": 'prefix "caller_id":"mahavishnu" suffix'})

    assert verify.find_caller_line(verify._iter_appended_lines(baseline)) is None


def test_malformed_lines_are_skipped(log_file: Path) -> None:
    """Non-JSON and truncated lines must not crash or match."""
    baseline = verify.log_baseline()
    with log_file.open("a", encoding="utf-8") as fh:
        fh.write("not json at all\n")
        fh.write('{"caller_id": "mahavropt\n')

    assert verify.find_caller_line(verify._iter_appended_lines(baseline)) is None


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
    log_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end: nonzero dispatch exit short-circuits to EXIT_FAIL.

    Critically, this holds even when the log already contains matching
    history -- the baseline is taken first, and a dispatch error returns
    before any polling happens.
    """
    _write(
        log_file,
        {
            "caller_id": "mahavishnu",
            "provider": "llama_server",
            "latency_seconds": 0.5,
            "http.target": "/v1/chat/completions",
        },
    )
    monkeypatch.setattr(verify, "check_preconditions", lambda: None)
    monkeypatch.setattr(verify, "READY_FILE", log_file.parent / "bifrost.ready")
    log_file.parent.joinpath("bifrost.ready").touch()
    monkeypatch.setattr(
        verify, "_run", lambda *_a, **_k: verify.subprocess.CompletedProcess([], 7, "", "boom")
    )

    assert verify.run_gate(timeout=1) == verify.EXIT_FAIL


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("/v1/chat/completions", True),
        ("/v1/completions", True),
        ("/v1/chat/completions?model=x", True),
        ("http://127.0.0.1:8471/v1/chat/completions", True),
        ("/v1/chat/completions/", True),
        ("/v1/./chat/completions", True),
        ("//v1//chat//completions", True),
        # Traversal and lookalike paths must not satisfy an exact match.
        ("/v1/chat/completions/../../admin", False),
        ("/not-really/chat/completions", False),
        ("/v1/chat/completions/extra", False),
        ("/anthropic/v1/messages", False),
        ("/", False),
        ("", False),
    ],
)
def test_endpoint_matching_is_exact_not_substring(target: str, expected: bool) -> None:
    """Security: unanchored substring matching let traversal paths through.

    ``"/chat/completions" in target`` also matched
    ``/v1/chat/completions/../../admin`` and ``/not-really/chat/completions``.
    Matching is now exact against the normalized path.
    """
    assert verify.is_qwen_endpoint(target) is expected


def test_exit_code_contract_preserved() -> None:
    """The shell original's 0/1/2/3 contract must survive the port."""
    assert (verify.EXIT_PASS, verify.EXIT_FAIL) == (0, 1)
    assert (verify.EXIT_PRECONDITION, verify.EXIT_NO_LOG) == (2, 3)

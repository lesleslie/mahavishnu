"""Tests for ``scripts/check_merge_driver.py`` and the merge_driver health probe.

Covers the Phase 4 operator-facing pre-flight + the ``/health``
``merge_driver`` payload (REQ-SM-008 + REQ-SM-009).
"""

from __future__ import annotations

from datetime import UTC, datetime
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

# Load the script module via importlib — it lives outside the package
# hierarchy and uses a ``__main__`` guard, so the canonical import path
# isn't available. Registering in ``sys.modules`` is required so the
# ``@dataclass`` decorator can resolve ``cls.__module__`` (it reads
# ``sys.modules[cls.__module__].__dict__`` for field defaults).
SCRIPT_PATH = Path(__file__).resolve().parent.parent.parent / "scripts" / "check_merge_driver.py"
_spec = importlib.util.spec_from_file_location("check_merge_driver", SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
check_merge_driver = importlib.util.module_from_spec(_spec)
sys.modules["check_merge_driver"] = check_merge_driver
_spec.loader.exec_module(check_merge_driver)


# ---------------------------------------------------------------------------
# check_merge_driver unit tests
# ---------------------------------------------------------------------------


def test_check_binary_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """check_binary returns ok with the resolved path when mergiraf is on PATH."""
    monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/mergiraf")
    result = check_merge_driver.check_binary()
    assert result.state == "ok"
    assert result.detail == "/usr/local/bin/mergiraf"


def test_check_binary_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """check_binary returns missing with a remediation hint."""
    monkeypatch.setattr("shutil.which", lambda _: None)
    result = check_merge_driver.check_binary()
    assert result.state == "missing"
    assert "brew install mergiraf" in result.detail


def test_check_version_parses_semver(monkeypatch: pytest.MonkeyPatch) -> None:
    """check_version parses ``mergiraf 0.19.1`` → ok with version."""
    monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/mergiraf")
    completed = MagicMock(spec=subprocess.CompletedProcess)
    completed.returncode = 0
    completed.stdout = "mergiraf 0.19.1\n"
    completed.stderr = ""

    def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
        return completed

    monkeypatch.setattr("subprocess.run", fake_run)
    result = check_merge_driver.check_version()
    assert result.state == "ok"
    assert result.detail == "0.19.1"


def test_check_version_malformed(monkeypatch: pytest.MonkeyPatch) -> None:
    """check_version returns error on unparseable output."""
    monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/mergiraf")
    completed = MagicMock(spec=subprocess.CompletedProcess)
    completed.returncode = 0
    completed.stdout = "???\n"
    completed.stderr = ""

    monkeypatch.setattr(
        "subprocess.run",
        lambda cmd, **kwargs: completed,
    )
    result = check_merge_driver.check_version()
    assert result.state == "error"


def test_check_python_grammar_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """check_python_grammar returns ok when 'Python' appears in languages output."""
    monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/mergiraf")
    completed = MagicMock(spec=subprocess.CompletedProcess)
    completed.returncode = 0
    completed.stdout = "Python (*.py)\nRust (*.rs)\nGo (*.go)\n"
    completed.stderr = ""

    monkeypatch.setattr(
        "subprocess.run",
        lambda cmd, **kwargs: completed,
    )
    result = check_merge_driver.check_python_grammar()
    assert result.state == "ok"


def test_check_python_grammar_absent_is_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    """check_python_grammar returns warning (not missing) when absent.

    Soft failure — operators can still run with heuristics, but should
    install the grammar via ``mergiraf install-grammar python``.
    """
    monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/mergiraf")
    completed = MagicMock(spec=subprocess.CompletedProcess)
    completed.returncode = 0
    completed.stdout = "Rust (*.rs)\nGo (*.go)\n"  # no Python
    completed.stderr = ""

    monkeypatch.setattr(
        "subprocess.run",
        lambda cmd, **kwargs: completed,
    )
    result = check_merge_driver.check_python_grammar()
    assert result.state == "warning"
    assert "mergiraf install-grammar python" in result.detail


def test_check_git_version_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """check_git_version returns ok for git >= 2.38."""
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/git" if cmd == "git" else None)
    completed = MagicMock(spec=subprocess.CompletedProcess)
    completed.returncode = 0
    completed.stdout = "git version 2.55.0\n"
    completed.stderr = ""

    monkeypatch.setattr(
        "subprocess.run",
        lambda cmd, **kwargs: completed,
    )
    result = check_merge_driver.check_git_version()
    assert result.state == "ok"
    assert "2.55" in result.detail


def test_check_git_version_too_old(monkeypatch: pytest.MonkeyPatch) -> None:
    """check_git_version returns missing with migration hint for git < 2.38."""
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/git" if cmd == "git" else None)
    completed = MagicMock(spec=subprocess.CompletedProcess)
    completed.returncode = 0
    completed.stdout = "git version 2.30.0\n"
    completed.stderr = ""

    monkeypatch.setattr(
        "subprocess.run",
        lambda cmd, **kwargs: completed,
    )
    result = check_merge_driver.check_git_version()
    assert result.state == "missing"
    assert "brew install git" in result.detail


def test_run_checks_aggregates_states() -> None:
    """run_checks returns one CheckResult per check."""
    with (
        patch.object(
            check_merge_driver,
            "check_binary",
            return_value=check_merge_driver.CheckResult(
                name="binary",
                state="ok",
                detail="/x",
            ),
        ),
        patch.object(
            check_merge_driver,
            "check_version",
            return_value=check_merge_driver.CheckResult(
                name="version",
                state="ok",
                detail="1.0.0",
            ),
        ),
        patch.object(
            check_merge_driver,
            "check_python_grammar",
            return_value=check_merge_driver.CheckResult(
                name="python_grammar",
                state="warning",
                detail="missing",
            ),
        ),
        patch.object(
            check_merge_driver,
            "check_git_version",
            return_value=check_merge_driver.CheckResult(
                name="git_version",
                state="ok",
                detail="2.55",
            ),
        ),
    ):
        results = check_merge_driver.run_checks(strict=False)
    assert len(results) == 4
    assert [r.state for r in results] == ["ok", "ok", "warning", "ok"]


def test_run_checks_strict_promotes_warning_to_missing() -> None:
    """--strict converts grammar warnings to missing (exit non-zero)."""
    with (
        patch.object(
            check_merge_driver,
            "check_binary",
            return_value=check_merge_driver.CheckResult(
                name="binary",
                state="ok",
                detail="/x",
            ),
        ),
        patch.object(
            check_merge_driver,
            "check_version",
            return_value=check_merge_driver.CheckResult(
                name="version",
                state="ok",
                detail="1.0.0",
            ),
        ),
        patch.object(
            check_merge_driver,
            "check_python_grammar",
            return_value=check_merge_driver.CheckResult(
                name="python_grammar",
                state="warning",
                detail="missing",
            ),
        ),
        patch.object(
            check_merge_driver,
            "check_git_version",
            return_value=check_merge_driver.CheckResult(
                name="git_version",
                state="ok",
                detail="2.55",
            ),
        ),
    ):
        strict_results = check_merge_driver.run_checks(strict=True)
    python_result = next(r for r in strict_results if r.name == "python_grammar")
    assert python_result.state == "missing"


def test_main_json_format(capsys: pytest.CaptureFixture[str]) -> None:
    """``--json`` emits JSON to stdout."""
    with patch.object(
        check_merge_driver,
        "run_checks",
        return_value=[
            check_merge_driver.CheckResult(name="binary", state="ok", detail="/x"),
        ],
    ):
        rc = check_merge_driver.main(["--json"])
    assert rc == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["passed"] == 1
    assert payload["total"] == 1


def test_main_returns_1_on_hard_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hard failures (missing/error states) return exit code 1."""
    monkeypatch.setattr("sys.argv", ["check_merge_driver.py"])
    with patch.object(
        check_merge_driver,
        "run_checks",
        return_value=[
            check_merge_driver.CheckResult(name="binary", state="missing", detail="no mergiraf"),
            check_merge_driver.CheckResult(name="version", state="ok", detail="1.0"),
            check_merge_driver.CheckResult(name="python_grammar", state="ok", detail="ok"),
            check_merge_driver.CheckResult(name="git_version", state="ok", detail="2.55"),
        ],
    ):
        rc = check_merge_driver.main([])
    assert rc == 1


# ---------------------------------------------------------------------------
# Phase 4 deferred review Group A: M6 (--repo-path), M8 (probe_ok field)
# ---------------------------------------------------------------------------


def test_check_python_grammar_with_repo_path_missing_languages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M6: --repo-path walks the repo and surfaces missing grammars.

    When ``--repo-path`` points to a repo that needs Rust and Go but
    only Python is installed, the check returns a warning listing
    exactly which grammars are missing. Operators see the gap and the
    remediation (``mergiraf install-grammar rust go``) in one line.
    """
    # Create files matching Rust and Go extensions.
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text("fn main() {}\n")
    (tmp_path / "src" / "main.go").write_text("package main\n")

    monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/mergiraf")
    completed = MagicMock(spec=subprocess.CompletedProcess)
    completed.returncode = 0
    completed.stdout = "Python (*.py)\n"  # Rust/Go absent
    completed.stderr = ""

    def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
        return completed

    monkeypatch.setattr("subprocess.run", fake_run)
    result = check_merge_driver.check_python_grammar(repo_path=tmp_path)
    assert result.state == "warning"
    detail = result.detail
    assert "Rust" in detail
    assert "Go" in detail
    assert "mergiraf install-grammar" in detail


def test_check_python_grammar_with_repo_path_all_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M6: --repo-path ok when every needed grammar is loadable."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text("fn main() {}\n")
    (tmp_path / "src" / "main.py").write_text("print('x')\n")

    monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/mergiraf")
    completed = MagicMock(spec=subprocess.CompletedProcess)
    completed.returncode = 0
    completed.stdout = "Python (*.py)\nRust (*.rs)\n"
    completed.stderr = ""

    monkeypatch.setattr("subprocess.run", lambda cmd, **kwargs: completed)
    result = check_merge_driver.check_python_grammar(repo_path=tmp_path)
    assert result.state == "ok"
    assert "Python" in result.detail
    assert "Rust" in result.detail


def test_check_python_grammar_with_repo_path_no_matching_files(
    tmp_path: Path,
) -> None:
    """M6: --repo-path on a repo with no tracked-extension files returns ok.

    Defensive: nothing to verify, so the check passes (operators
    shouldn't be nagged when their repo happens to be all Markdown or
    all YAML).
    """
    (tmp_path / "README.md").write_text("# project\n")
    result = check_merge_driver.check_python_grammar(repo_path=tmp_path)
    assert result.state == "ok"
    assert "no files matched" in result.detail


def test_required_grammars_for_repo_dedupes(tmp_path: Path) -> None:
    """M6: required-grammar detection dedupes by grammar name.

    Many ``.py`` files all map to the ``Python`` grammar — the dedupe
    ensures ``["Python"]`` not ``["Python", "Python", ...]``. Also
    covers the cross-extension case: ``.ts`` + ``.tsx`` both map to
    ``TypeScript``, single entry in the result.
    """
    (tmp_path / "a.py").write_text("x")
    (tmp_path / "b.py").write_text("x")
    (tmp_path / "c.ts").write_text("x")
    (tmp_path / "d.tsx").write_text("x")
    grammars = check_merge_driver._required_grammars_for_repo(tmp_path)
    assert sorted(grammars) == ["Python", "TypeScript"]


def test_required_grammars_for_repo_skips_large_files(tmp_path: Path) -> None:
    """M6: the detector skips files > 1MB to avoid vendored-deps noise.

    A vendored ``node_modules/foo.js`` (often 10MB+) doesn't change
    the grammars we need; including it just slows the walk and could
    trip on lockfiles / generated blobs.
    """
    (tmp_path / "small.py").write_text("x")
    big = tmp_path / "big.py"
    big.write_text("x" * 1_500_000)  # 1.5MB
    grammars = check_merge_driver._required_grammars_for_repo(tmp_path)
    # Both files map to Python but only "small" should be visible.
    assert grammars == ["Python"]


def test_resolve_repo_path_none_returns_none() -> None:
    """M6: ``_resolve_repo_path(None)`` returns ``None`` (legacy default)."""
    assert check_merge_driver._resolve_repo_path(None) is None


def test_resolve_repo_path_validates_existence(tmp_path: Path) -> None:
    """M6: ``_resolve_repo_path`` raises on nonexistent path."""
    with pytest.raises(ValueError, match="does not exist"):
        check_merge_driver._resolve_repo_path("/nonexistent/path/xyz")


def test_resolve_repo_path_validates_directory(tmp_path: Path) -> None:
    """M6: ``_resolve_repo_path`` raises when path is a file, not a dir."""
    f = tmp_path / "not_a_dir.txt"
    f.write_text("x")
    with pytest.raises(ValueError, match="not a directory"):
        check_merge_driver._resolve_repo_path(str(f))


def test_main_repo_path_flag_threads_to_run_checks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M6: ``--repo-path`` is threaded into ``run_checks``."""
    captured: dict[str, object] = {}

    def fake_run_checks(
        *,
        strict: bool = False,
        repo_path: Path | None = None,
    ) -> list[check_merge_driver.CheckResult]:
        captured["strict"] = strict
        captured["repo_path"] = repo_path
        return [check_merge_driver.CheckResult(name="binary", state="ok", detail="/x")]

    monkeypatch.setattr(check_merge_driver, "run_checks", fake_run_checks)
    rc = check_merge_driver.main(["--repo-path", str(tmp_path)])
    assert rc == 0
    assert captured["repo_path"] == tmp_path
    assert captured["strict"] is False


def test_main_repo_path_invalid_returns_2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M6: invalid ``--repo-path`` returns exit code 2 (internal error).

    Distinct from "mergiraf missing" (exit 1). Path validation
    failures are operator-input errors, not environment problems.
    """
    monkeypatch.setattr("sys.argv", ["check_merge_driver.py"])
    rc = check_merge_driver.main(["--repo-path", "/definitely/not/here/xyz"])
    assert rc == 2


# ---------------------------------------------------------------------------
# merge_driver health probe tests
# ---------------------------------------------------------------------------


def test_merge_driver_health_when_binary_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """``merge_driver_health`` returns ok payload when mergiraf is available.

    Phase 4 deferred review (M8): healthy probe sets ``probe_ok=True``.
    """
    import mahavishnu.core.health as health_module

    health_module._DEGRADED_SINCE = None  # type: ignore[attr-defined]
    monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/mergiraf")

    completed = MagicMock(spec=subprocess.CompletedProcess)
    completed.returncode = 0
    completed.stdout = "mergiraf 0.19.1\nPython (*.py)\nRust (*.rs)\nGo (*.go)\n"
    completed.stderr = ""

    monkeypatch.setattr(
        "subprocess.run",
        lambda cmd, **kwargs: completed,
    )

    payload = health_module.merge_driver_health()
    assert payload["available"] is True
    assert payload["binary"] == "/usr/local/bin/mergiraf"
    assert payload["version"] == "0.19.1"
    assert "Python" in payload["grammars"]
    assert payload["probe_ok"] is True
    assert payload["degraded_since"] is None


def test_merge_driver_health_when_binary_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """``merge_driver_health`` returns empty payload when mergiraf is missing.

    Phase 4 deferred review (M8): the binary-missing branch surfaces
    ``probe_ok=False`` so operators see a structured signal that the
    probe never ran. Pre-M8 there was no field; M8 distinguishes "no
    grammars" from "probe never ran".
    """
    import mahavishnu.core.health as health_module

    monkeypatch.setattr("shutil.which", lambda _: None)
    payload = health_module.merge_driver_health()
    assert payload["available"] is False
    assert payload["binary"] is None
    assert payload["version"] is None
    assert payload["grammars"] == []
    assert payload["probe_ok"] is False
    assert payload["degraded_since"] is None


def test_merge_driver_health_when_grammar_probe_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M8: grammar-probe timeout surfaces ``probe_ok=False``.

    Phase 4 deferred review (M8). When ``mergiraf languages`` hangs
    past the 10s probe timeout, the probe is broken — operators see
    ``probe_ok=False`` plus a stamped ``degraded_since`` (a brand-new
    degraded signal; the broken probe is its own kind of degradation
    distinct from a missing binary).
    """
    import mahavishnu.core.health as health_module

    health_module._assign_degraded_since(None, None)  # reset stamp

    monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/mergiraf")

    # Version probe succeeds; grammar probe times out.
    def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
        if "--version" in cmd:
            completed = MagicMock(spec=subprocess.CompletedProcess)
            completed.returncode = 0
            completed.stdout = "mergiraf 0.19.1\n"
            completed.stderr = ""
            return completed
        if "languages" in cmd:
            raise subprocess.TimeoutExpired(cmd="languages", timeout=10)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr("subprocess.run", fake_run)
    payload = health_module.merge_driver_health()
    assert payload["available"] is True
    assert payload["version"] == "0.19.1"
    assert payload["grammars"] == []
    assert payload["probe_ok"] is False
    assert payload["degraded_since"] is not None  # M8 stamps on broken probe


def test_merge_driver_health_when_grammar_probe_nonzero_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M8: non-zero ``mergiraf languages`` exit is ``probe_ok=False``.

    Subprocess completed but exited non-zero (e.g. ``mergiraf`` is a
    stub binary that prints the languages header then crashes). M8
    distinguishes this from the empty-grammars case.
    """
    import mahavishnu.core.health as health_module

    health_module._assign_degraded_since(None, None)

    monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/mergiraf")

    def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
        if "--version" in cmd:
            completed = MagicMock(spec=subprocess.CompletedProcess)
            completed.returncode = 0
            completed.stdout = "mergiraf 0.19.1\n"
            completed.stderr = ""
            return completed
        if "languages" in cmd:
            completed = MagicMock(spec=subprocess.CompletedProcess)
            completed.returncode = 2
            completed.stdout = "fatal: tree-sitter crash\n"
            completed.stderr = ""
            return completed
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr("subprocess.run", fake_run)
    payload = health_module.merge_driver_health()
    assert payload["probe_ok"] is False
    assert payload["degraded_since"] is not None


def test_merge_driver_health_empty_grammars_with_probe_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M8: empty grammars + ``probe_ok=True`` is a healthy config, not degraded.

    Operator installed mergiraf without ANY grammars — the probe ran
    cleanly, returned empty, ``probe_ok=True``. No ``degraded_since``
    stamp (operators made a configuration choice; no degradation).
    Distinct from the probe-broke case in M8 where ``probe_ok=False``
    stamps the stamp.
    """
    import mahavishnu.core.health as health_module

    health_module._assign_degraded_since(None, None)

    monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/mergiraf")
    completed = MagicMock(spec=subprocess.CompletedProcess)
    completed.returncode = 0
    completed.stdout = "mergiraf 0.19.1\n"  # version succeeds
    completed.stderr = ""

    def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
        if "languages" in cmd:
            completed2 = MagicMock(spec=subprocess.CompletedProcess)
            completed2.returncode = 0
            completed2.stdout = ""  # empty — no grammars installed
            completed2.stderr = ""
            return completed2
        return completed

    monkeypatch.setattr("subprocess.run", fake_run)
    payload = health_module.merge_driver_health()
    assert payload["probe_ok"] is True
    assert payload["grammars"] == []
    assert payload["degraded_since"] is None  # NOT stamped — clean empty


def test_merge_driver_health_clears_degraded_after_healthy_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A healthy probe clears a previously-stale degraded_since stamp."""
    import mahavishnu.core.health as health_module

    # Seed a stale degraded stamp.
    health_module._DEGRADED_SINCE = datetime.now(UTC)  # type: ignore[attr-defined]

    monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/mergiraf")
    completed = MagicMock(spec=subprocess.CompletedProcess)
    completed.returncode = 0
    completed.stdout = "mergiraf 0.19.1\nPython (*.py)\n"
    completed.stderr = ""

    monkeypatch.setattr(
        "subprocess.run",
        lambda cmd, **kwargs: completed,
    )
    payload = health_module.merge_driver_health()
    assert payload["degraded_since"] is None


# ---------------------------------------------------------------------------
# Round-5 review deferred fixes: M9 (always stamp), M10 (probe span), m3 (per-app)
# ---------------------------------------------------------------------------


def test_mark_merge_driver_fallback_updates_on_subsequent_calls() -> None:
    """M9 fix: ``_DEGRADED_SINCE`` updates on every fallback, not just the first.

    Prior logic only stamped when the slot was ``None``, leaving stale
    "days ago" timestamps visible while the current degradation was
    hidden. The new behavior is: ``mark_merge_driver_fallback()`` always
    stamps the slot so operators see the most recent fallback.
    """
    import mahavishnu.core.health as health_module

    # Start clean — module-global slot.
    health_module._DEGRADED_SINCE = None  # type: ignore[attr-defined]

    first = datetime.now(UTC)
    health_module.mark_merge_driver_fallback()
    after_first = health_module._DEGRADED_SINCE  # type: ignore[attr-defined]
    assert after_first is not None
    assert after_first >= first

    # Second call should overwrite the first stamp. The prior logic
    # would have left ``after_first`` intact — exactly the bug this
    # test pins against regression.
    import time as _time

    _time.sleep(0.005)  # ensure datetime.now(UTC) advances
    health_module.mark_merge_driver_fallback()
    after_second = health_module._DEGRADED_SINCE  # type: ignore[attr-defined]
    assert after_second is not None
    assert after_second > after_first, (
        "Expected the second mark_merge_driver_fallback() call to advance "
        "the stamp; the M9 fix ensures operators always see the most-recent "
        "fallback timestamp."
    )


def test_mark_merge_driver_fallback_with_app_uses_per_instance_slot() -> None:
    """m3 fix: per-app ``_degraded_since`` isolates two ``MahavishnuApp`` instances.

    Two apps in the same process must not stomp each other's fallback
    history. The per-instance stamp should advance independently of
    the module-global fallback.
    """
    import mahavishnu.core.health as health_module

    # Reset module-global so the assertion below is unambiguous.
    health_module._DEGRADED_SINCE = None  # type: ignore[attr-defined]

    # Build two duck-typed stand-ins (no need to import the full
    # ``MahavishnuApp`` — instantiating it pulls in Oneiric config,
    # observability, etc.; ``hasattr`` is the gate the resolver uses).
    class _AppStub:
        def __init__(self) -> None:
            self._degraded_since: datetime | None = None

    app_a = _AppStub()
    app_b = _AppStub()

    health_module.mark_merge_driver_fallback(app_a)
    assert app_a._degraded_since is not None
    assert app_b._degraded_since is None
    assert health_module._DEGRADED_SINCE is None  # type: ignore[attr-defined]

    # Stamping app_b leaves app_a's stamp intact.
    import time as _time

    _time.sleep(0.005)
    health_module.mark_merge_driver_fallback(app_b)
    assert app_b._degraded_since > app_a._degraded_since
    # Module-global still untouched — neither call fell through.
    assert health_module._DEGRADED_SINCE is None  # type: ignore[attr-defined]


def test_merge_driver_health_emits_probe_span(monkeypatch: pytest.MonkeyPatch) -> None:
    """M10 fix: ``merge.driver.probe`` OTel span is emitted around the PATH probe.

    Uses ``InMemorySpanExporter`` (opentelemetry.sdk.trace) as the
    primary assertion source — MagicMock on the tracer would also work
    but the SDK exporter is the canonical verification.
    """
    import mahavishnu.core.health as health_module

    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    # Override the tracer returned by ``trace.get_tracer`` so the
    # health module emits to our in-memory exporter. ``get_tracer`` is
    # called inside ``health_module`` at import time, so patch the
    # already-resolved tracer.
    health_module._probe_tracer = provider.get_tracer(__name__)

    health_module._DEGRADED_SINCE = None  # type: ignore[attr-defined]
    monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/mergiraf")
    completed = MagicMock(spec=subprocess.CompletedProcess)
    completed.returncode = 0
    completed.stdout = "mergiraf 0.19.1\nPython (*.py)\n"
    completed.stderr = ""

    monkeypatch.setattr(
        "subprocess.run",
        lambda cmd, **kwargs: completed,
    )

    payload = health_module.merge_driver_health()
    assert payload["available"] is True

    spans = exporter.get_finished_spans()
    span_names = {s.name for s in spans}
    assert "merge.driver.probe" in span_names, (
        f"Expected ``merge.driver.probe`` span; got {span_names!r}"
    )
    probe_span = next(s for s in spans if s.name == "merge.driver.probe")
    # Span attributes should mirror the spec'd keys.
    attrs = dict(probe_span.attributes or {})
    assert attrs.get("merge.driver") == "mergiraf"
    assert attrs.get("merge.binary_path") == "/usr/local/bin/mergiraf"
    # ``probe.cached`` is False on a fresh probe (no module-cache
    # consulted by ``merge_driver_health`` — every call re-probes).
    assert attrs.get("probe.cached") is False


def test_merge_driver_health_probe_span_records_missing_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M10 fix: ``merge.driver.probe`` records ``merge.binary_path=None`` on miss."""
    import mahavishnu.core.health as health_module

    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    health_module._probe_tracer = provider.get_tracer(__name__)

    health_module._DEGRADED_SINCE = None  # type: ignore[attr-defined]
    monkeypatch.setattr("shutil.which", lambda _: None)
    health_module.merge_driver_health()

    spans = exporter.get_finished_spans()
    probe_span = next(s for s in spans if s.name == "merge.driver.probe")
    attrs = dict(probe_span.attributes or {})
    assert attrs.get("merge.binary_path") is None


def test_merge_driver_health_clears_per_app_stamp_after_healthy_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """m3 fix: a healthy probe clears the per-app ``_degraded_since`` stamp.

    The per-instance stamp must obey the same M2 semantics as the
    module-global: a successful probe clears stale degradation, but
    binary-missing preserves it (the operator wants to see fallback
    history even when the binary briefly disappeared).
    """
    import mahavishnu.core.health as health_module

    class _AppStub:
        def __init__(self) -> None:
            self._degraded_since: datetime | None = None

    app = _AppStub()
    health_module._DEGRADED_SINCE = None  # type: ignore[attr-defined]

    # Seed a per-app degraded stamp.
    health_module.mark_merge_driver_fallback(app)
    assert app._degraded_since is not None

    # Successful probe with binary present clears the per-app stamp.
    monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/mergiraf")
    completed = MagicMock(spec=subprocess.CompletedProcess)
    completed.returncode = 0
    completed.stdout = "mergiraf 0.19.1\n"
    completed.stderr = ""

    monkeypatch.setattr(
        "subprocess.run",
        lambda cmd, **kwargs: completed,
    )

    payload = health_module.merge_driver_health(app)
    assert payload["available"] is True
    assert payload["degraded_since"] is None
    # Module-global untouched (per-app was the target).
    assert health_module._DEGRADED_SINCE is None  # type: ignore[attr-defined]

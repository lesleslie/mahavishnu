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
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

if TYPE_CHECKING:
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
# merge_driver health probe tests
# ---------------------------------------------------------------------------


def test_merge_driver_health_when_binary_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """``merge_driver_health`` returns ok payload when mergiraf is available."""
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
    assert payload["degraded_since"] is None


def test_merge_driver_health_when_binary_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """``merge_driver_health`` returns empty payload when mergiraf is missing."""
    import mahavishnu.core.health as health_module

    monkeypatch.setattr("shutil.which", lambda _: None)
    payload = health_module.merge_driver_health()
    assert payload["available"] is False
    assert payload["binary"] is None
    assert payload["version"] is None
    assert payload["grammars"] == []
    assert payload["degraded_since"] is None


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

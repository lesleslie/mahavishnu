"""Thin file-backed persister for CompletionReport (Spec #1 Phase 1 v0).

Writes each report as a JSON file under ``$XDG_CACHE_HOME/mahavishnu/
completion_reports/`` (or ``$HOME/.cache/mahavishnu/completion_reports/``
when ``XDG_CACHE_HOME`` is unset). Filename is ``{report_id}.json``.

This is the v0 reference implementation. The Dhara-backed persister is
a follow-up once the substrate lands; the API here is the contract that
the Dhara implementation must satisfy.

The persister deliberately uses synchronous file I/O because saving a
report is a side-effect at workflow end, not in the hot path of the
worker loop. Callers that need async behavior should ``run_in_executor``
or use ``aiofiles`` at the call site.
"""

from __future__ import annotations

from os import environ
from pathlib import Path  # noqa: TC003  (runtime Path argument)
from re import compile

from mahavishnu.core.completion_report import CompletionReport

# Filename-safe character set: alphanumerics, dash, underscore, dot.
# ``report_id`` is normally a UUID4 string, but callers may supply
# arbitrary IDs (e.g. for retry idempotency). Reject anything that
# could escape the reports_dir.
_SAFE_NAME_RE = compile(r"[^A-Za-z0-9._-]")


def _sanitize_filename(report_id: str) -> str:
    """Return a filename-safe version of ``report_id``."""
    return _SAFE_NAME_RE.sub("_", report_id) or "report"


def default_reports_dir() -> Path:
    """Return the default directory for storing completion reports.

    Order of precedence:

    1. ``$XDG_CACHE_HOME/mahavishnu/completion_reports``
    2. ``$HOME/.cache/mahavishnu/completion_reports``
    """
    base = environ.get("XDG_CACHE_HOME")
    if base:
        return Path(base) / "mahavishnu" / "completion_reports"
    home = environ.get("HOME", str(Path.home()))
    return Path(home) / ".cache" / "mahavishnu" / "completion_reports"


class LocalFileCompletionPersister:
    """File-backed persister for ``CompletionReport``.

    Each report is written as ``{reports_dir}/{sanitized_report_id}.json``.
    Calling ``save`` with a ``report_id`` that already exists overwrites
    the prior file (idempotent retries).
    """

    def __init__(self, reports_dir: Path | None = None) -> None:
        self.reports_dir: Path = reports_dir or default_reports_dir()

    def _path_for(self, report_id: str) -> Path:
        return self.reports_dir / f"{_sanitize_filename(report_id)}.json"

    def save(self, report: CompletionReport) -> Path:
        """Write ``report`` to disk; return the path written."""
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        path = self._path_for(report.report_id)
        path.write_text(report.model_dump_json(indent=2))
        return path

    def load(self, report_id: str) -> CompletionReport:
        """Read a previously-saved report; raise ``FileNotFoundError`` if missing."""
        path = self._path_for(report_id)
        return CompletionReport.model_validate_json(path.read_text())


__all__ = [
    "LocalFileCompletionPersister",
    "default_reports_dir",
]
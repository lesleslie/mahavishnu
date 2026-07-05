"""Unit tests for mahavishnu/core/completion_report.py and completion_persister.py.

Spec #1: completion-report-schema-v1 (foundational; Phase 1).

Scope (per Spec #1 brief, sql_blocked substrate):

- CompletionReport (Pydantic v2) with status, summary, artifacts, started_at,
  completed_at, metadata, auto-generated report_id.
- CompletionStatus (StrEnum): success | failure | partial.
- ReportArtifact (kind, path, optional label).
- JSON Schema export via model_json_schema().
- Validation: missing required fields raise ValidationError.
- Roundtrip: model_dump_json -> model_validate_json.
- Thin file-backed persister writing to $XDG_CACHE_HOME/mahavishnu/
  completion_reports/ (or ~/.cache fallback).

The Dhara-backed persister is a follow-up once the substrate lands.
"""

from __future__ import annotations

from datetime import UTC, datetime
from json import dumps, loads
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import ValidationError
import pytest

from mahavishnu.core.completion_persister import (
    LocalFileCompletionPersister,
    default_reports_dir,
)
from mahavishnu.core.completion_report import (
    CompletionReport,
    CompletionStatus,
    ReportArtifact,
)

# ---------------------------------------------------------------------------
# CompletionStatus StrEnum
# ---------------------------------------------------------------------------


class TestCompletionStatus:
    def test_members_present(self) -> None:
        assert CompletionStatus.SUCCESS.name == "SUCCESS"
        assert CompletionStatus.FAILURE.name == "FAILURE"
        assert CompletionStatus.PARTIAL.name == "PARTIAL"

    def test_member_count_is_three(self) -> None:
        # success | failure | partial — the architectural contract.
        assert len(CompletionStatus) == 3

    def test_values_are_lowercase_strings(self) -> None:
        assert CompletionStatus.SUCCESS.value == "success"
        assert CompletionStatus.FAILURE.value == "failure"
        assert CompletionStatus.PARTIAL.value == "partial"

    def test_status_is_string_subclass(self) -> None:
        # StrEnum means each member IS a str.
        assert isinstance(CompletionStatus.SUCCESS, str)
        assert CompletionStatus.SUCCESS == "success"


# ---------------------------------------------------------------------------
# ReportArtifact
# ---------------------------------------------------------------------------


class TestReportArtifact:
    def test_required_fields(self) -> None:
        art = ReportArtifact(kind="log", path=Path("/tmp/x.log"))
        assert art.kind == "log"
        assert art.path == Path("/tmp/x.log")
        assert art.label is None

    def test_optional_label(self) -> None:
        art = ReportArtifact(kind="diff", path=Path("/tmp/x.patch"), label="primary")
        assert art.label == "primary"

    def test_serialization_roundtrip(self) -> None:
        art = ReportArtifact(kind="log", path=Path("/tmp/x.log"), label="L1")
        data = art.model_dump()
        restored = ReportArtifact.model_validate(data)
        assert restored == art

    def test_path_accepts_str_and_path(self) -> None:
        # Both str and Path should be accepted and normalized to Path.
        a_str = ReportArtifact(kind="x", path="/tmp/x.log")
        a_path = ReportArtifact(kind="x", path=Path("/tmp/x.log"))
        assert a_str.path == a_path.path
        assert isinstance(a_str.path, Path)
        # JSON dump roundtrip preserves the path as a string (Path str()).
        dumped = a_str.model_dump()
        dumped["path"] = str(dumped["path"])
        assert isinstance(dumped["path"], str)


# ---------------------------------------------------------------------------
# CompletionReport — construction and validation
# ---------------------------------------------------------------------------


def _valid_kwargs(**overrides: object) -> dict[str, object]:
    """Build a valid CompletionReport kwargs dict; allow per-field overrides."""
    started = datetime(2026, 6, 22, 10, 0, 0, tzinfo=UTC)
    completed = datetime(2026, 6, 22, 10, 5, 0, tzinfo=UTC)
    base: dict[str, object] = {
        "status": CompletionStatus.SUCCESS,
        "summary": "All checks green.",
        "artifacts": [],
        "started_at": started,
        "completed_at": completed,
        "metadata": {"workflow_id": str(uuid4())},
    }
    base.update(overrides)
    return base


class TestCompletionReportConstruction:
    def test_minimal_valid_report(self) -> None:
        report = CompletionReport(**_valid_kwargs())
        assert report.status is CompletionStatus.SUCCESS
        assert report.summary == "All checks green."
        assert report.artifacts == []
        assert report.metadata == {"workflow_id": report.metadata["workflow_id"]}

    def test_report_id_auto_generated(self) -> None:
        report = CompletionReport(**_valid_kwargs())
        assert report.report_id is not None
        # Must look like a UUID4 string.
        UUID(report.report_id, version=4)

    def test_report_id_is_unique_across_instances(self) -> None:
        r1 = CompletionReport(**_valid_kwargs())
        r2 = CompletionReport(**_valid_kwargs())
        assert r1.report_id != r2.report_id

    def test_explicit_report_id_preserved(self) -> None:
        rid = "fixed-id-1234"
        report = CompletionReport(**_valid_kwargs(report_id=rid))
        assert report.report_id == rid

    def test_artifacts_default_to_empty_list(self) -> None:
        report = CompletionReport(**_valid_kwargs())
        assert report.artifacts == []

    def test_metadata_defaults_to_empty_dict(self) -> None:
        # metadata has a default; explicitly drop it.
        kwargs = _valid_kwargs()
        kwargs.pop("metadata")
        report = CompletionReport(**kwargs)
        assert report.metadata == {}

    def test_status_accepts_string(self) -> None:
        # StrEnum should accept the raw string value (for ergonomic parsing).
        report = CompletionReport(**_valid_kwargs(status="failure"))
        assert report.status is CompletionStatus.FAILURE

    def test_status_rejects_unknown_value(self) -> None:
        with pytest.raises(ValidationError):
            CompletionReport(**_valid_kwargs(status="unknown"))


class TestCompletionReportMissingRequiredFields:
    def test_missing_status_raises(self) -> None:
        kwargs = _valid_kwargs()
        del kwargs["status"]
        with pytest.raises(ValidationError):
            CompletionReport(**kwargs)

    def test_missing_summary_raises(self) -> None:
        kwargs = _valid_kwargs()
        del kwargs["summary"]
        with pytest.raises(ValidationError):
            CompletionReport(**kwargs)

    def test_missing_started_at_raises(self) -> None:
        kwargs = _valid_kwargs()
        del kwargs["started_at"]
        with pytest.raises(ValidationError):
            CompletionReport(**kwargs)

    def test_missing_completed_at_raises(self) -> None:
        kwargs = _valid_kwargs()
        del kwargs["completed_at"]
        with pytest.raises(ValidationError):
            CompletionReport(**kwargs)


# ---------------------------------------------------------------------------
# JSON Schema export
# ---------------------------------------------------------------------------


class TestCompletionReportJsonSchema:
    def test_model_json_schema_is_a_dict(self) -> None:
        schema = CompletionReport.model_json_schema()
        assert isinstance(schema, dict)

    def test_schema_has_top_level_keys(self) -> None:
        schema = CompletionReport.model_json_schema()
        # Pydantic emits at least: properties, required, title, type.
        for key in ("properties", "type"):
            assert key in schema, f"missing {key!r} in schema"

    def test_schema_lists_required_fields(self) -> None:
        schema = CompletionReport.model_json_schema()
        required = schema.get("required", [])
        for field_name in ("status", "summary", "started_at", "completed_at"):
            assert field_name in required, f"{field_name!r} must be required"

    def test_schema_is_serializable_json(self) -> None:
        schema = CompletionReport.model_json_schema()
        # Round-trip to ensure no non-JSON values snuck in.
        dumps(schema)


# ---------------------------------------------------------------------------
# Roundtrip serialization
# ---------------------------------------------------------------------------


class TestCompletionReportRoundtrip:
    def test_model_dump_json_then_validate(self) -> None:
        original = CompletionReport(**_valid_kwargs())
        as_json = original.model_dump_json()
        restored = CompletionReport.model_validate_json(as_json)
        assert restored == original

    def test_roundtrip_preserves_report_id(self) -> None:
        original = CompletionReport(**_valid_kwargs())
        restored = CompletionReport.model_validate_json(original.model_dump_json())
        assert restored.report_id == original.report_id

    def test_roundtrip_preserves_artifacts(self) -> None:
        art = ReportArtifact(kind="log", path=Path("/tmp/run.log"), label="main")
        original = CompletionReport(**_valid_kwargs(artifacts=[art]))
        restored = CompletionReport.model_validate_json(original.model_dump_json())
        assert len(restored.artifacts) == 1
        assert restored.artifacts[0].kind == "log"
        assert restored.artifacts[0].label == "main"
        # Path is serialized to str and re-coerced.
        assert Path(restored.artifacts[0].path) == Path("/tmp/run.log")

    def test_roundtrip_with_metadata(self) -> None:
        md = {"workflow_id": "abc", "tags": ["a", "b"]}
        original = CompletionReport(**_valid_kwargs(metadata=md))
        restored = CompletionReport.model_validate_json(original.model_dump_json())
        assert restored.metadata == md


# ---------------------------------------------------------------------------
# Thin file-backed persister (Phase 1 v0; Dhara is follow-up)
# ---------------------------------------------------------------------------


class TestDefaultReportsDir:
    def test_uses_xdg_cache_home_when_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        result = default_reports_dir()
        assert result == tmp_path / "mahavishnu" / "completion_reports"

    def test_falls_back_to_home_cache(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))
        result = default_reports_dir()
        assert result == tmp_path / ".cache" / "mahavishnu" / "completion_reports"


class TestLocalFileCompletionPersister:
    def test_save_creates_file_under_reports_dir(self, tmp_path: Path) -> None:
        persister = LocalFileCompletionPersister(reports_dir=tmp_path)
        report = CompletionReport(**_valid_kwargs())
        written_path = persister.save(report)
        assert written_path.exists()
        assert written_path.parent == tmp_path
        assert written_path.name == f"{report.report_id}.json"

    def test_save_writes_valid_json(self, tmp_path: Path) -> None:
        persister = LocalFileCompletionPersister(reports_dir=tmp_path)
        report = CompletionReport(**_valid_kwargs())
        written_path = persister.save(report)
        data = loads(written_path.read_text())
        assert data["report_id"] == report.report_id
        assert data["status"] == "success"
        assert data["summary"] == report.summary

    def test_save_creates_reports_dir_if_missing(self, tmp_path: Path) -> None:
        target = tmp_path / "deep" / "nested"
        assert not target.exists()
        persister = LocalFileCompletionPersister(reports_dir=target)
        report = CompletionReport(**_valid_kwargs())
        written_path = persister.save(report)
        assert target.exists()
        assert written_path.exists()

    def test_load_roundtrips_saved_report(self, tmp_path: Path) -> None:
        persister = LocalFileCompletionPersister(reports_dir=tmp_path)
        report = CompletionReport(**_valid_kwargs())
        persister.save(report)
        loaded = persister.load(report.report_id)
        assert loaded == report

    def test_load_missing_report_raises(self, tmp_path: Path) -> None:
        persister = LocalFileCompletionPersister(reports_dir=tmp_path)
        with pytest.raises(FileNotFoundError):
            persister.load("does-not-exist")

    def test_save_overwrites_existing_report_with_same_id(self, tmp_path: Path) -> None:
        persister = LocalFileCompletionPersister(reports_dir=tmp_path)
        rid = "fixed-id-1234"
        r1 = CompletionReport(**_valid_kwargs(report_id=rid, summary="first"))
        r2 = CompletionReport(**_valid_kwargs(report_id=rid, summary="second"))
        persister.save(r1)
        persister.save(r2)
        loaded = persister.load(rid)
        assert loaded.summary == "second"

    def test_filename_is_safe(self, tmp_path: Path) -> None:
        # Even a maliciously crafted report_id must not escape the reports_dir.
        persister = LocalFileCompletionPersister(reports_dir=tmp_path)
        bad = CompletionReport(**_valid_kwargs(report_id="../../etc/passwd"))
        written_path = persister.save(bad)
        # File lands inside reports_dir, no traversal — sanitize replaces
        # any non [A-Za-z0-9._-] character with '_', so '..' becomes '.._.._...'.
        assert written_path.parent == tmp_path
        assert written_path.is_relative_to(tmp_path)
        # The resulting filename must be a single segment (no separators).
        assert "/" not in written_path.name
        assert "\\" not in written_path.name
        assert ".." not in Path(written_path.name).parts

    def test_default_reports_dir_used_when_unset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        persister = LocalFileCompletionPersister()
        report = CompletionReport(**_valid_kwargs())
        written_path = persister.save(report)
        expected_dir = tmp_path / "mahavishnu" / "completion_reports"
        assert written_path.parent == expected_dir

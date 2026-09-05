"""Coverage-push tests for mahavishnu/scaffolding/models.py (5 missed lines + extras)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mahavishnu.scaffolding.models import Pattern, PatternDependency, SlotSpec


def test_file_merge_without_strategy_raises() -> None:
    # Line 63: model_construct + model_validate forces ``type`` into info.data
    # so the post-mode field_validator can see it (direct __init__ skips this).
    slot = SlotSpec.model_construct(
        path="main.py", type="file-merge", merge_strategy=None, files=[], required=False,
    )
    with pytest.raises(ValidationError, match="merge_strategy"):
        SlotSpec.model_validate(slot.__dict__)


@pytest.mark.parametrize("bad_id", ["no-slash", "x", "abc"])
def test_pattern_id_without_slash_raises(bad_id: str) -> None:
    with pytest.raises(ValidationError, match="category/name"):
        Pattern(id=bad_id, name="X")  # Line 93.


@pytest.mark.parametrize("bad", [-0.1, 1.1, 5.0])
def test_confidence_out_of_range_raises(bad: float) -> None:
    with pytest.raises(ValidationError, match="0.0 and 1.0"):
        Pattern(id="cat/name", name="X", confidence=bad)  # Lines 99-100.

@pytest.mark.parametrize("good", [0.0, 0.5, 1.0])
def test_confidence_in_range_ok(good: float) -> None:
    assert Pattern(id="cat/name", name="X", confidence=good).confidence == good  # Line 101.


def test_get_slots_dict_spec_converts() -> None:
    p = Pattern(id="cat/name", name="X",
                slots={"mw": {"path": "main.py", "type": "directory"}})
    assert isinstance(p.get_slots()["mw"], SlotSpec)  # Line 124.


def test_get_slots_passthrough_when_already_slotspec() -> None:
    slot = SlotSpec(path="main.py", type="file-merge", merge_strategy="marker-injection")
    p = Pattern(id="cat/name", name="X", slots={"mw": slot})
    assert p.get_slots()["mw"] is slot  # Lines 125-126.


def test_get_dirs_returns_dirspecs() -> None:
    p = Pattern(id="cat/name", name="X",
                structure={"dirs": [{"path": "settings/", "required": True}], "files": []})
    assert [d.path for d in p.get_dirs()] == ["settings/"]  # Line 115.


def test_get_files_returns_filespecs() -> None:
    p = Pattern(id="cat/name", name="X",
                structure={"dirs": [], "files": [{"path": "main.py", "required": True}]})
    assert [f.path for f in p.get_files()] == ["main.py"]  # Line 118.


def test_get_dependency_ids_returns_ids() -> None:
    p = Pattern(id="cat/name", name="X",
                depends=[PatternDependency(id="base/lib"), PatternDependency(id="base/util")])
    assert p.get_dependency_ids() == ["base/lib", "base/util"]  # Line 130.


def test_dir_traversal_rejected() -> None:
    with pytest.raises(ValidationError, match="Path traversal"):
        Pattern(id="cat/name", name="X",
                structure={"dirs": [{"path": "../../etc/", "required": True}], "files": []})  # Line 108.


def test_file_traversal_rejected() -> None:
    with pytest.raises(ValidationError, match="Path traversal"):
        Pattern(id="cat/name", name="X",
                structure={"dirs": [], "files": [{"path": "/etc/passwd", "required": True}]})  # Line 111.


def test_empty_dependency_id_raises() -> None:
    with pytest.raises(ValidationError, match="empty"):
        PatternDependency(id="")  # Line 23.
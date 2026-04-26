"""Pydantic models for pattern format."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


_PATH_TRAVERSAL_RE = re.compile(r"(\.\./|\.\.\\|/etc/|/tmp/|/var/)")


class PatternDependency(BaseModel):
    """A dependency on another pattern."""

    id: str
    version: str | None = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not v:
            raise ValueError("Dependency id must not be empty")
        return v


class DirSpec(BaseModel):
    """Directory specification within a pattern."""

    path: str
    required: bool = True
    description: str = ""


class FileSpec(BaseModel):
    """File specification within a pattern."""

    path: str
    required: bool = True
    template: str | None = None
    description: str = ""

    @model_validator(mode="after")
    def default_template_from_path(self) -> FileSpec:
        if self.template is None:
            self.template = self.path.lstrip("/")
        return self


class SlotSpec(BaseModel):
    """Named extension point for pattern composition."""

    path: str
    type: Literal["directory", "file-merge"] = "directory"
    merge_strategy: Literal["marker-injection"] | None = None
    files: list[str] = []
    required: bool = False

    @field_validator("merge_strategy", mode="after")
    @classmethod
    def require_strategy_for_merge(cls, v: str | None, info: Any) -> str | None:
        if info.data.get("type") == "file-merge" and v is None:
            raise ValueError("file-merge slots must specify merge_strategy")
        return v


def _is_safe_path(path: str) -> bool:
    return not _PATH_TRAVERSAL_RE.search(path)


class Pattern(BaseModel):
    """A reusable architectural pattern."""

    schema_version: Literal[1] = 1
    id: str
    name: str
    description: str = ""
    version: str = "1.0.0"
    source_repos: list[str] = []
    confidence: float = 1.0
    depends: list[PatternDependency] = []
    tags: list[str] = []
    structure: dict[str, list[dict[str, Any]]] = Field(
        default_factory=lambda: {"dirs": [], "files": []}
    )
    templates: dict[str, str] = {}
    slots: dict[str, Any] = {}

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not v or "/" not in v:
            raise ValueError("Pattern ID must be in 'category/name' format")
        return v

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("Confidence must be between 0.0 and 1.0")
        return v

    @field_validator("structure", mode="after")
    @classmethod
    def validate_paths(
        cls, v: dict[str, list[dict[str, Any]]]
    ) -> dict[str, list[dict[str, Any]]]:
        for d in v.get("dirs", []):
            if not _is_safe_path(d.get("path", "")):
                raise ValueError(f"Path traversal detected: {d['path']}")
        for f in v.get("files", []):
            if not _is_safe_path(f.get("path", "")):
                raise ValueError(f"Path traversal detected: {f['path']}")
        return v

    def get_dirs(self) -> list[DirSpec]:
        return [DirSpec(**d) for d in self.structure.get("dirs", [])]

    def get_files(self) -> list[FileSpec]:
        return [FileSpec(**f) for f in self.structure.get("files", [])]

    def get_slots(self) -> dict[str, SlotSpec]:
        result: dict[str, SlotSpec] = {}
        for name, spec in self.slots.items():
            if isinstance(spec, dict):
                result[name] = SlotSpec(**spec)
            elif isinstance(spec, SlotSpec):
                result[name] = spec
        return result

    def get_dependency_ids(self) -> list[str]:
        return [d.id for d in self.depends]

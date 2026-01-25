"""Repository validation models."""
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class RepositoryMetadata(BaseModel):
    """Metadata for a repository."""

    version: str = Field(default="0.0.0", description="Repository version")
    language: str = Field(default="python", description="Primary language")
    min_python: str | None = Field(None, description="Minimum Python version")
    dependencies: int = Field(default=0, ge=0, description="Number of dependencies")
    last_validated: datetime = Field(
        default_factory=datetime.utcnow, description="Last validation timestamp"
    )


class Repository(BaseModel):
    """Repository configuration model."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9]([\-a-z0-9]*[a-z0-9])?$",
    )
    package: str = Field(..., pattern=r"^[a-z][a-z0-9_]*$")
    path: Path = Field(..., description="Absolute path to repository")
    tags: list[str] = Field(..., min_length=1, max_length=10)
    description: str = Field(..., min_length=1, max_length=500)
    mcp: Literal["native", "3rd-party"] | None = Field(
        None, description="MCP server type"
    )
    metadata: RepositoryMetadata | None = Field(
        default=None, description="Additional metadata"
    )

    @field_validator("path")
    @classmethod
    def path_must_be_absolute(cls, v: Path) -> Path:
        """Ensure path is absolute."""
        if not v.is_absolute():
            raise ValueError("Repository path must be absolute")
        return v.resolve()

    @field_validator("tags")
    @classmethod
    def tags_must_be_valid(cls, v: list[str]) -> list[str]:
        """Validate tag format."""
        import re

        tag_pattern = re.compile(r"^[a-z0-9]([\-_][a-z0-9]+)*$")

        for tag in v:
            if not tag_pattern.match(tag):
                raise ValueError(
                    f"Invalid tag '{tag}': must be lowercase alphanumeric with hyphens/underscores"
                )
        return v

    @field_validator("name")
    @classmethod
    def name_must_match_package_convention(cls, v: str) -> str:
        """Ensure name follows convention."""
        if " " in v:
            raise ValueError("Repository name must not contain spaces")
        return v.lower()

    @model_validator(mode="after")
    def validate_mcp_consistency(self) -> "Repository":
        """Ensure MCP type matches description."""
        if self.mcp and "mcp" not in self.tags:
            # Auto-add mcp tag if not present
            self.tags.append("mcp")

        if self.mcp == "native" and "3rd-party" in self.tags:
            raise ValueError("Native MCP servers cannot have '3rd-party' tag")

        if self.mcp == "3rd-party" and "native" in self.tags:
            raise ValueError("Third-party MCP servers cannot have 'native' tag")

        return self


class RepositoryManifest(BaseModel):
    """Complete repository manifest."""

    version: str = "1.0"
    schema_version: str = "1.0"
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    repos: list[Repository] = Field(min_length=1)

    @field_validator("repos")
    @classmethod
    def repos_must_be_unique(cls, v: list[Repository]) -> list[Repository]:
        """Ensure no duplicate repos."""
        paths = set()
        names = set()
        packages = set()

        for repo in v:
            if str(repo.path) in paths:
                raise ValueError(f"Duplicate repository path: {repo.path}")
            if repo.name in names:
                raise ValueError(f"Duplicate repository name: {repo.name}")
            if repo.package in packages:
                raise ValueError(f"Duplicate package name: {repo.package}")

            paths.add(str(repo.path))
            names.add(repo.name)
            packages.add(repo.package)

        return v

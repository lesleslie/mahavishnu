"""Team configuration models for Agno multi-agent orchestration.

This module provides Pydantic models for defining agent teams with
configurable members, roles, and collaboration modes.

Example YAML configuration:
    ```yaml
    team:
      name: "code_review_team"
      mode: "coordinate"
      leader:
        name: "review_coordinator"
        role: "Coordinates code review"
        model: "claude-sonnet-4-6"
        instructions: "Distribute tasks to specialists"
      members:
        - name: "security_analyst"
          role: "Security analysis"
          model: "claude-sonnet-4-6"
          instructions: "Analyze for security vulnerabilities"
          tools: ["search_code", "read_file"]
    ```
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class TeamMode(StrEnum):
    """Team collaboration modes for multi-agent orchestration.

    Modes:
        coordinate: Leader agent distributes tasks to members, aggregates results.
                   Best for: code review, research, complex analysis.

        route: Single agent selected based on task type or expertise.
               Best for: customer support, Q&A, specialized tasks.

        broadcast: All agents work on the same task simultaneously.
                   Best for: brainstorming, parallel analysis, consensus building.

        collaborate: Agents work together sequentially on shared context.
                    Best for: complex workflows, iterative refinement.
    """

    COORDINATE = "coordinate"
    ROUTE = "route"
    BROADCAST = "broadcast"
    COLLABORATE = "collaborate"


class MemberConfig(BaseModel):
    """Configuration for a team member agent.

    Each member is an independent agent with its own role, instructions,
    and optional tools. Members are orchestrated by the team manager.

    Attributes:
        name: Unique identifier for the member within the team.
        role: Human-readable role description (e.g., "Security Analyst").
        model: LLM model identifier (e.g., "claude-sonnet-4-6", "gpt-4o").
        instructions: Detailed instructions for the agent's behavior.
        tools: List of tool names this agent can use.
        max_tokens: Maximum tokens for responses.
        temperature: Sampling temperature (0.0-2.0).

    Example:
        ```python
        member = MemberConfig(
            name="security_analyst",
            role="Security vulnerability detection",
            model="claude-sonnet-4-6",
            instructions="Analyze code for security vulnerabilities...",
            tools=["search_code", "read_file", "check_dependencies"],
        )
        ```
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Unique name for this team member",
    )
    role: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Role description for the agent",
    )
    model: str = Field(
        default="qwen2.5:7b",
        description="LLM model identifier",
    )
    instructions: str = Field(
        ...,
        min_length=10,
        description="Detailed instructions for the agent",
    )
    tools: list[str] = Field(
        default_factory=list,
        description="List of tool names this agent can use",
    )
    max_tokens: int = Field(
        default=4096,
        ge=1,
        le=128000,
        description="Maximum tokens for responses",
    )
    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="Sampling temperature",
    )

    model_config = {"extra": "forbid"}


class TeamConfig(BaseModel):
    """Configuration for an agent team.

    A team consists of a leader (optional for some modes) and multiple
    member agents that collaborate on tasks using the specified mode.

    Attributes:
        name: Unique team identifier.
        description: Human-readable team description.
        mode: Collaboration mode (coordinate, route, broadcast, collaborate).
        leader: Optional leader agent configuration (required for coordinate mode).
        members: List of member agent configurations.
        memory_enabled: Whether team shares conversation memory.
        max_concurrent_runs: Maximum concurrent agent executions.
        timeout_seconds: Default timeout for team operations.

    Example:
        ```python
        config = TeamConfig(
            name="code_review_team",
            mode=TeamMode.COORDINATE,
            leader=MemberConfig(
                name="coordinator",
                role="Coordinates review",
                model="claude-sonnet-4-6",
                instructions="Distribute tasks to specialists",
            ),
            members=[
                MemberConfig(
                    name="security_analyst",
                    role="Security analysis",
                    model="claude-sonnet-4-6",
                    instructions="Find security vulnerabilities",
                ),
            ],
        )
        ```
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Unique team name",
    )
    description: str = Field(
        default="",
        max_length=500,
        description="Human-readable team description",
    )
    mode: TeamMode = Field(
        default=TeamMode.COORDINATE,
        description="Team collaboration mode",
    )
    leader: MemberConfig | None = Field(
        default=None,
        description="Leader agent configuration (required for coordinate mode)",
    )
    members: list[MemberConfig] = Field(
        ...,
        min_length=1,
        description="List of team member configurations",
    )
    memory_enabled: bool = Field(
        default=True,
        description="Enable shared memory across team members",
    )
    max_concurrent_runs: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum concurrent agent executions",
    )
    timeout_seconds: int = Field(
        default=300,
        ge=30,
        le=3600,
        description="Default timeout for team operations",
    )

    model_config = {"extra": "forbid"}

    @field_validator("leader")
    @classmethod
    def validate_leader_for_coordinate(
        cls, v: MemberConfig | None, info
    ) -> MemberConfig | None:
        """Validate that coordinate mode has a leader."""
        mode = info.data.get("mode")
        if mode == TeamMode.COORDINATE and v is None:
            raise ValueError(
                "leader is required when mode is 'coordinate'. "
                "Set leader configuration or use a different mode."
            )
        return v

    @field_validator("members")
    @classmethod
    def validate_unique_names(cls, v: list[MemberConfig]) -> list[MemberConfig]:
        """Validate that all member names are unique."""
        names = [m.name for m in v]
        if len(names) != len(set(names)):
            duplicates = [n for n in names if names.count(n) > 1]
            raise ValueError(
                f"Member names must be unique. Duplicates found: {duplicates}"
            )
        return v

    def get_all_members(self) -> list[MemberConfig]:
        """Get all team members including leader if present.

        Returns:
            List of all MemberConfig instances in the team.
        """
        all_members = list(self.members)
        if self.leader:
            all_members.insert(0, self.leader)
        return all_members

    def get_member_by_name(self, name: str) -> MemberConfig | None:
        """Get a member by name.

        Args:
            name: Member name to search for.

        Returns:
            MemberConfig if found, None otherwise.
        """
        for member in self.get_all_members():
            if member.name == name:
                return member
        return None


class TeamConfigFile(BaseModel):
    """Root model for team configuration YAML files.

    Team configs are stored in YAML format with a 'team' root key.

    Example YAML:
        ```yaml
        team:
          name: "code_review_team"
          mode: "coordinate"
          leader:
            name: "coordinator"
            role: "Coordinates review"
            model: "claude-sonnet-4-6"
            instructions: "..."
          members:
            - name: "analyst"
              role: "Analysis"
              model: "claude-sonnet-4-6"
              instructions: "..."
        ```
    """

    team: TeamConfig

    model_config = {"extra": "forbid"}


# ============================================================================
# Team Templates
# ============================================================================


def get_builtin_team_templates() -> dict[str, dict[str, Any]]:
    """Get built-in team templates for common use cases.

    Returns:
        Dictionary of template name to TeamConfig-compatible dict.
    """
    return {
        "code_review": {
            "name": "code_review_team",
            "description": "Multi-agent team for comprehensive code review",
            "mode": TeamMode.COORDINATE,
            "leader": {
                "name": "review_coordinator",
                "role": "Coordinates code review across specialists",
                "model": "claude-sonnet-4-6",
                "instructions": """You are a code review coordinator. Your job is to:
1. Analyze incoming code review requests
2. Distribute review tasks to specialist agents
3. Aggregate findings into a comprehensive report
4. Prioritize issues by severity and impact""",
            },
            "members": [
                {
                    "name": "security_analyst",
                    "role": "Security vulnerability detection",
                    "model": "claude-sonnet-4-6",
                    "instructions": """Analyze code for security vulnerabilities including:
- SQL injection risks
- XSS vulnerabilities
- Authentication/authorization flaws
- Sensitive data exposure
- Insecure configurations""",
                    "tools": ["search_code", "read_file", "check_dependencies"],
                },
                {
                    "name": "quality_engineer",
                    "role": "Code quality and best practices",
                    "model": "claude-sonnet-4-6",
                    "instructions": """Evaluate code quality including:
- Adherence to style guides
- Complexity metrics
- Test coverage gaps
- Documentation completeness
- Maintainability concerns""",
                    "tools": ["search_code", "read_file", "run_linter"],
                },
            ],
        },
        "research": {
            "name": "research_team",
            "description": "Team for research and information gathering",
            "mode": TeamMode.COORDINATE,
            "leader": {
                "name": "research_coordinator",
                "role": "Coordinates research across sources",
                "model": "claude-sonnet-4-6",
                "instructions": """You are a research coordinator. Your job is to:
1. Break down research questions into sub-topics
2. Assign research tasks to specialist agents
3. Synthesize findings into coherent reports
4. Identify gaps and request additional research""",
            },
            "members": [
                {
                    "name": "web_researcher",
                    "role": "Web search and content extraction",
                    "model": "gpt-4o",
                    "instructions": "Search the web for relevant information and extract key insights.",
                    "tools": ["web_search", "read_url"],
                },
                {
                    "name": "code_researcher",
                    "role": "Code analysis and documentation",
                    "model": "claude-sonnet-4-6",
                    "instructions": "Analyze codebases to understand implementation patterns and best practices.",
                    "tools": ["search_code", "read_file"],
                },
                {
                    "name": "doc_synthesizer",
                    "role": "Synthesizes findings into reports",
                    "model": "claude-sonnet-4-6",
                    "instructions": "Create clear, well-structured documentation from research findings.",
                    "tools": ["write_file"],
                },
            ],
        },
    }


__all__ = [
    "TeamMode",
    "MemberConfig",
    "TeamConfig",
    "TeamConfigFile",
    "get_builtin_team_templates",
]

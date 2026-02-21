"""Agent team manager for multi-agent orchestration.

This module provides the AgentTeamManager class that handles creation,
execution, and lifecycle management of Agno agent teams.

Key Features:
- Team creation from configuration
- Multiple team modes (coordinate, route, broadcast, collaborate)
- Result aggregation from multiple agents
- Concurrent execution with semaphore control
- Health monitoring and statistics
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
import logging
from pathlib import Path
import time
from typing import TYPE_CHECKING, Any
import uuid

import yaml

from mahavishnu.core.errors import AgnoError, ErrorCode

from .config import MemberConfig, TeamConfig, TeamMode

if TYPE_CHECKING:
    from agno.agent import Agent
    from agno.run.team import TeamRunOutput
    from agno.team import Team

logger = logging.getLogger(__name__)


@dataclass
class AgentRunResult:
    """Result from a single agent run within a team."""

    agent_name: str
    content: str
    run_id: str
    success: bool = True
    error: str | None = None
    tokens_used: int = 0
    latency_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TeamRunResult:
    """Result from a team run with multiple agents."""

    team_name: str
    mode: str
    responses: list[AgentRunResult]
    run_id: str
    success: bool = True
    error: str | None = None
    total_tokens: int = 0
    latency_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class AgentTeamManager:
    """Manager for creating and running multi-agent teams.

    The AgentTeamManager handles:
    - Loading team configurations from YAML files
    - Creating Agno Team instances with configured agents
    - Running teams with different collaboration modes
    - Aggregating results from team executions
    - Team lifecycle management (create, list, get, cleanup)

    Example:
        ```python
        from mahavishnu.engines.agno_teams import AgentTeamManager, TeamConfig

        # Create manager
        manager = AgentTeamManager(llm_factory=llm_factory)

        # Create team from config
        config = TeamConfig(
            name="review_team",
            mode=TeamMode.COORDINATE,
            leader=MemberConfig(...),
            members=[MemberConfig(...)],
        )
        team_id = await manager.create_team(config)

        # Run team task
        result = await manager.run_team(team_id, "Review this code")
        print(result.responses)
        ```
    """

    def __init__(
        self,
        llm_factory: Any,
        mcp_tools: list[Any] | None = None,
        max_concurrent_agents: int = 5,
    ) -> None:
        """Initialize the team manager.

        Args:
            llm_factory: LLMProviderFactory instance for creating model instances.
            mcp_tools: Optional list of MCP tools to provide to agents.
            max_concurrent_agents: Maximum concurrent agent executions.
        """
        self.llm_factory = llm_factory
        self.mcp_tools = mcp_tools or []
        self.max_concurrent_agents = max_concurrent_agents

        # Internal state
        self._teams: dict[str, Team] = {}
        self._team_configs: dict[str, TeamConfig] = {}
        self._agents: dict[str, Agent] = {}
        self._semaphore = asyncio.Semaphore(max_concurrent_agents)
        self._run_history: dict[str, list[TeamRunResult]] = {}

    async def create_team(self, config: TeamConfig) -> str:
        """Create an agent team from configuration.

        This method creates the Agno Team instance and all member agents
        based on the provided configuration.

        Args:
            config: TeamConfig instance defining the team structure.

        Returns:
            Unique team ID string.

        Raises:
            AgnoError: If team creation fails.
        """
        from agno.team import Team

        team_id = f"team_{config.name}_{uuid.uuid4().hex[:8]}"

        try:
            # Create agents for all members
            agents: list[Agent] = []

            for member_config in config.members:
                agent = await self._create_member_agent(member_config)
                agents.append(agent)
                self._agents[member_config.name] = agent

            # Create leader agent if specified
            leader_agent: Agent | None = None
            if config.leader:
                leader_agent = await self._create_member_agent(config.leader)
                self._agents[config.leader.name] = leader_agent

            # Map our mode to Agno's TeamMode
            agno_mode = self._map_team_mode(config.mode)

            # Create the team
            team_kwargs: dict[str, Any] = {
                "name": config.name,
                "mode": agno_mode,
                "members": agents,
            }

            if leader_agent:
                team_kwargs["leader"] = leader_agent

            team = Team(**team_kwargs)

            # Store team and config
            self._teams[team_id] = team
            self._team_configs[team_id] = config
            self._run_history[team_id] = []

            logger.info(
                f"Created team: id={team_id}, name={config.name}, "
                f"mode={config.mode.value}, members={len(agents)}"
            )

            return team_id

        except Exception as e:
            logger.error(f"Failed to create team '{config.name}': {e}")
            raise AgnoError(
                f"Failed to create team: {e}",
                error_code=ErrorCode.AGNO_AGENT_NOT_FOUND,
                details={"team_name": config.name, "error": str(e)},
            ) from e

    async def create_team_from_yaml(self, yaml_path: str) -> str:
        """Create a team from a YAML configuration file.

        Args:
            yaml_path: Path to the YAML configuration file.

        Returns:
            Unique team ID string.

        Raises:
            AgnoError: If file loading or team creation fails.
        """
        try:
            path = Path(yaml_path)
            if not path.exists():
                raise AgnoError(
                    f"Team config file not found: {yaml_path}",
                    error_code=ErrorCode.CONFIGURATION_ERROR,
                    details={"path": yaml_path},
                )

            with open(path) as f:
                data = yaml.safe_load(f)

            if "team" not in data:
                raise AgnoError(
                    "Invalid team config: missing 'team' key",
                    error_code=ErrorCode.CONFIGURATION_ERROR,
                    details={"path": yaml_path},
                )

            config = TeamConfig(**data["team"])
            return await self.create_team(config)

        except AgnoError:
            raise
        except Exception as e:
            logger.error(f"Failed to load team config from {yaml_path}: {e}")
            raise AgnoError(
                f"Failed to load team config: {e}",
                error_code=ErrorCode.CONFIGURATION_ERROR,
                details={"path": yaml_path, "error": str(e)},
            ) from e

    async def run_team(
        self,
        team_id: str,
        task: str,
        mode: str | None = None,
        session_id: str | None = None,
    ) -> TeamRunResult:
        """Run a team task and return aggregated results.

        Args:
            team_id: Team ID returned from create_team().
            task: Task/prompt for the team to process.
            mode: Optional mode override (coordinate, route, broadcast).
            session_id: Optional session ID for memory continuity.

        Returns:
            TeamRunResult with responses from all participating agents.

        Raises:
            AgnoError: If team execution fails.
        """
        if team_id not in self._teams:
            raise AgnoError(
                f"Team not found: {team_id}",
                error_code=ErrorCode.AGNO_AGENT_NOT_FOUND,
                details={"team_id": team_id},
            )

        team = self._teams[team_id]
        config = self._team_configs[team_id]
        run_id = f"run_{uuid.uuid4().hex[:8]}"

        start_time = time.monotonic()

        try:
            # Run the team
            async with asyncio.timeout(config.timeout_seconds):
                response: TeamRunOutput = await team.arun(task)

            latency_ms = (time.monotonic() - start_time) * 1000

            # Extract responses from team members
            responses = self._extract_team_responses(response, config)

            # Calculate totals
            total_tokens = sum(r.tokens_used for r in responses)

            result = TeamRunResult(
                team_name=config.name,
                mode=mode or config.mode.value,
                responses=responses,
                run_id=run_id,
                success=True,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                metadata={
                    "session_id": session_id,
                    "team_id": team_id,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )

            # Store in history
            self._run_history[team_id].append(result)

            logger.info(
                f"Team run completed: team={config.name}, run_id={run_id}, "
                f"latency={latency_ms:.0f}ms, responses={len(responses)}"
            )

            return result

        except TimeoutError:
            latency_ms = (time.monotonic() - start_time) * 1000
            result = TeamRunResult(
                team_name=config.name,
                mode=mode or config.mode.value,
                responses=[],
                run_id=run_id,
                success=False,
                error=f"Team execution timed out after {config.timeout_seconds}s",
                latency_ms=latency_ms,
            )
            self._run_history[team_id].append(result)
            return result

        except Exception as e:
            latency_ms = (time.monotonic() - start_time) * 1000
            logger.error(f"Team run failed: team={config.name}, error={e}")

            result = TeamRunResult(
                team_name=config.name,
                mode=mode or config.mode.value,
                responses=[],
                run_id=run_id,
                success=False,
                error=str(e),
                latency_ms=latency_ms,
            )
            self._run_history[team_id].append(result)
            return result

    async def get_team(self, team_id: str) -> Team | None:
        """Get a team instance by ID.

        Args:
            team_id: Team ID to look up.

        Returns:
            Team instance if found, None otherwise.
        """
        return self._teams.get(team_id)

    async def get_team_config(self, team_id: str) -> TeamConfig | None:
        """Get a team configuration by ID.

        Args:
            team_id: Team ID to look up.

        Returns:
            TeamConfig if found, None otherwise.
        """
        return self._team_configs.get(team_id)

    def list_teams(self) -> list[str]:
        """List all team IDs.

        Returns:
            List of team ID strings.
        """
        return list(self._teams.keys())

    def get_team_stats(self, team_id: str) -> dict[str, Any]:
        """Get statistics for a team.

        Args:
            team_id: Team ID to get stats for.

        Returns:
            Dictionary with team statistics.
        """
        config = self._team_configs.get(team_id)
        history = self._run_history.get(team_id, [])

        if not config:
            return {"error": "Team not found"}

        successful_runs = sum(1 for r in history if r.success)
        total_runs = len(history)

        return {
            "team_id": team_id,
            "team_name": config.name,
            "mode": config.mode.value,
            "member_count": len(config.members),
            "total_runs": total_runs,
            "successful_runs": successful_runs,
            "success_rate": successful_runs / total_runs if total_runs > 0 else 0,
            "avg_latency_ms": (
                sum(r.latency_ms for r in history) / total_runs if total_runs > 0 else 0
            ),
        }

    async def delete_team(self, team_id: str) -> bool:
        """Delete a team and cleanup resources.

        Args:
            team_id: Team ID to delete.

        Returns:
            True if team was deleted, False if not found.
        """
        if team_id not in self._teams:
            return False

        config = self._team_configs[team_id]

        # Remove agents
        for member in config.get_all_members():
            self._agents.pop(member.name, None)

        # Remove team
        del self._teams[team_id]
        del self._team_configs[team_id]

        # Keep history for auditing

        logger.info(f"Deleted team: {team_id}")
        return True

    async def shutdown(self) -> None:
        """Shutdown all teams and cleanup resources."""
        team_ids = list(self._teams.keys())
        for team_id in team_ids:
            await self.delete_team(team_id)

        self._agents.clear()
        self._teams.clear()
        self._team_configs.clear()

        logger.info("AgentTeamManager shutdown complete")

    # ========================================================================
    # Private Methods
    # ========================================================================

    async def _create_member_agent(self, config: MemberConfig) -> Agent:
        """Create an agent from member configuration.

        Args:
            config: MemberConfig for the agent.

        Returns:
            Configured Agent instance.
        """
        from agno.agent import Agent

        # Create model for this agent
        model = self._create_model_for_member(config)

        # Get tools for this agent
        tools = self._get_tools_for_member(config)

        agent = Agent(
            name=config.name,
            role=config.role,
            instructions=config.instructions,
            model=model,
            tools=tools,
        )

        logger.debug(f"Created member agent: {config.name}")
        return agent

    def _create_model_for_member(self, config: MemberConfig) -> Any:
        """Create an LLM model for a team member.

        Args:
            config: MemberConfig with model settings.

        Returns:
            LLM model instance.
        """
        # Update factory config for this member's model
        original_model_id = self.llm_factory.config.model_id
        original_temp = self.llm_factory.config.temperature
        original_max_tokens = self.llm_factory.config.max_tokens

        try:
            self.llm_factory.config.model_id = config.model
            self.llm_factory.config.temperature = config.temperature
            self.llm_factory.config.max_tokens = config.max_tokens

            # Clear cached model to create new one
            self.llm_factory._model_instance = None

            return self.llm_factory.create_model()

        finally:
            # Restore original settings
            self.llm_factory.config.model_id = original_model_id
            self.llm_factory.config.temperature = original_temp
            self.llm_factory.config.max_tokens = original_max_tokens

    def _get_tools_for_member(self, config: MemberConfig) -> list[Any]:
        """Get tools for a team member.

        If member specifies tools, filter MCP tools to match.
        Otherwise, return all MCP tools.

        Args:
            config: MemberConfig with tool specifications.

        Returns:
            List of tool instances.
        """
        if not config.tools:
            return self.mcp_tools

        # Filter tools by name (if MCP tools support naming)
        # For now, return all MCP tools as Agno handles filtering
        return self.mcp_tools

    def _map_team_mode(self, mode: TeamMode) -> str:
        """Map our TeamMode enum to Agno's TeamMode string.

        Args:
            mode: Our TeamMode enum value.

        Returns:
            Agno TeamMode string value.
        """
        # Agno uses lowercase string values for TeamMode
        mode_map = {
            TeamMode.COORDINATE: "coordinate",
            TeamMode.ROUTE: "route",
            TeamMode.BROADCAST: "broadcast",
            TeamMode.COLLABORATE: "coordinate",  # collaborate maps to coordinate
        }
        return mode_map.get(mode, "coordinate")

    def _extract_team_responses(
        self,
        response: TeamRunOutput,
        config: TeamConfig,
    ) -> list[AgentRunResult]:
        """Extract individual agent responses from team output.

        Args:
            response: TeamRunOutput from team execution.
            config: TeamConfig for reference.

        Returns:
            List of AgentRunResult instances.
        """
        results: list[AgentRunResult] = []

        # Try different response structures
        if hasattr(response, "responses") and response.responses:
            # Multiple agent responses
            for agent_response in response.responses:
                results.append(
                    AgentRunResult(
                        agent_name=getattr(agent_response, "agent_name", "unknown"),
                        content=self._extract_content(agent_response),
                        run_id=getattr(agent_response, "run_id", "unknown"),
                        success=True,
                        tokens_used=getattr(agent_response, "tokens_used", 0),
                    )
                )

        elif hasattr(response, "messages") and response.messages:
            # Extract from messages
            for i, msg in enumerate(response.messages):
                results.append(
                    AgentRunResult(
                        agent_name=f"agent_{i}",
                        content=self._extract_content(msg),
                        run_id=getattr(response, "run_id", "unknown"),
                        success=True,
                    )
                )

        else:
            # Fallback: single response
            results.append(
                AgentRunResult(
                    agent_name=config.name,
                    content=self._extract_content(response),
                    run_id=getattr(response, "run_id", "unknown"),
                    success=True,
                )
            )

        return results

    def _extract_content(self, response: Any) -> str:
        """Extract string content from a response object.

        Args:
            response: Response object from agent/team execution.

        Returns:
            String content.
        """
        # Try different content attributes
        if hasattr(response, "content") and response.content:
            if isinstance(response.content, str):
                return response.content
            return str(response.content)

        if hasattr(response, "text") and response.text:
            return str(response.text)

        if hasattr(response, "messages") and response.messages:
            last_msg = response.messages[-1]
            if hasattr(last_msg, "content"):
                return str(last_msg.content)

        # Fallback to string representation
        return str(response)


__all__ = [
    "AgentTeamManager",
    "AgentRunResult",
    "TeamRunResult",
]

"""Goal-driven team MCP tools for natural language team creation.

This module provides MCP tools for creating and managing agent teams
from natural language goals using the GoalDrivenTeamFactory.

Created: 2026-02-21
Version: 1.0
Related: Goal-Driven Teams Phase 1 - MCP tool integration
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from fastmcp import FastMCP  # noqa: TC002

from mahavishnu.core.context import get_agno_adapter, get_llm_factory, is_context_initialized
from mahavishnu.core.errors import (
    ErrorCode,
    GoalParsingError,
    GoalTeamError,
)

logger = logging.getLogger(__name__)


def register_goal_team_tools(mcp: FastMCP) -> None:
    """Register goal-driven team management tools.

    Args:
        mcp: FastMCP instance

    This registers 3 goal-driven team tools:
    - team_from_goal: Create and optionally run a team from a natural language goal
    - parse_goal: Parse a goal to see what team would be created
    - list_team_skills: List all available skills for team creation
    """

    @mcp.tool()
    async def team_from_goal(
        goal: str,
        name: str | None = None,
        mode: str | None = None,
        auto_run: bool = False,
        task: str | None = None,
    ) -> dict[str, Any]:
        """Create an agent team from a natural language goal.

        This tool parses a natural language goal and automatically creates
        an appropriate team configuration with the right agents, skills,
        and collaboration mode.

        Args:
            goal: Natural language description of what the team should do.
                  Examples:
                  - "Review this code for security issues"
                  - "Write tests for the authentication module"
                  - "Analyze performance bottlenecks in the API"
            name: Optional team name (auto-generated if not provided).
                  Example: "security_review_team"
            mode: Optional collaboration mode. One of:
                  - "coordinate": Leader distributes tasks to specialists
                  - "route": Single agent selected based on expertise
                  - "broadcast": All agents work simultaneously
                  Default is selected based on goal intent.
            auto_run: If True, immediately run the team with the provided task.
                      Default is False (just create the team).
            task: Task to run if auto_run is True. Required when auto_run=True.

        Returns:
            Dictionary with:
            - success: Whether team creation succeeded
            - team_id: Unique team identifier (if created successfully)
            - config: Team configuration details
            - parsed_goal: How the goal was interpreted
            - run_result: Execution results (only if auto_run=True)
            - error: Error details (if failed)

        Example:
            ```python
            # Create a team from a goal
            result = await team_from_goal(
                goal="Review this code for security issues",
                name="security_review"
            )
            print(f"Team ID: {result['team_id']}")

            # Create and immediately run a team
            result = await team_from_goal(
                goal="Write comprehensive tests for the API module",
                auto_run=True,
                task="Generate unit tests for all public endpoints"
            )
            print(f"Result: {result['run_result']}")
            ```
        """
        try:
            # Validate inputs
            if len(goal.strip()) < 10:
                raise GoalParsingError(
                    goal=goal,
                    reason="Goal is too short. Provide at least 10 characters describing the task.",
                    error_code=ErrorCode.GOAL_TOO_SHORT,
                )

            if len(goal) > 1000:
                raise GoalParsingError(
                    goal=goal,
                    reason="Goal is too long. Maximum 1000 characters allowed.",
                    error_code=ErrorCode.GOAL_TOO_LONG,
                )

            if auto_run and not task:
                return {
                    "success": False,
                    "error": {
                        "code": ErrorCode.VALIDATION_ERROR.value,
                        "message": "task parameter is required when auto_run=True",
                    },
                }

            # Check context initialization
            llm_factory = None
            if not is_context_initialized():
                # Try to get LLM factory (may fail, which is OK for pattern-only parsing)
                with contextlib.suppress(Exception):
                    llm_factory = get_llm_factory()
            else:
                llm_factory = get_llm_factory()

            # Import and create factory
            from mahavishnu.engines.agno_teams.config import TeamMode
            from mahavishnu.engines.goal_team_factory import GoalDrivenTeamFactory

            # Parse mode if provided
            team_mode = None
            if mode:
                mode_map = {
                    "coordinate": TeamMode.COORDINATE,
                    "route": TeamMode.ROUTE,
                    "broadcast": TeamMode.BROADCAST,
                    "collaborate": TeamMode.COLLABORATE,
                }
                if mode.lower() not in mode_map:
                    return {
                        "success": False,
                        "error": {
                            "code": ErrorCode.VALIDATION_ERROR.value,
                            "message": f"Invalid mode '{mode}'. Must be one of: {list(mode_map.keys())}",
                        },
                    }
                team_mode = mode_map[mode.lower()]

            # Create factory and parse goal
            factory = GoalDrivenTeamFactory(llm_factory=llm_factory)
            parsed = await factory.parse_goal(goal)

            # Create team configuration
            team_config = await factory.create_team_from_goal(
                goal=goal,
                name=name,
                mode=team_mode,
            )

            # Get Agno adapter and create the team
            agno_adapter = get_agno_adapter()
            team_id = await agno_adapter.create_team(team_config)

            result: dict[str, Any] = {
                "success": True,
                "team_id": team_id,
                "config": {
                    "name": team_config.name,
                    "description": team_config.description,
                    "mode": team_config.mode.value,
                    "members": [
                        {
                            "name": m.name,
                            "role": m.role,
                            "model": m.model,
                        }
                        for m in team_config.members
                    ],
                    "leader": {
                        "name": team_config.leader.name,
                        "role": team_config.leader.role,
                    } if team_config.leader else None,
                },
                "parsed_goal": {
                    "intent": parsed.intent,
                    "domain": parsed.domain,
                    "skills": parsed.skills,
                    "confidence": parsed.confidence,
                    "raw_goal": parsed.raw_goal,
                },
            }

            # Auto-run if requested
            if auto_run and task:
                logger.info(f"Auto-running team {team_id} with task: {task[:50]}...")
                run_result = await agno_adapter.run_team(team_id, task)
                result["run_result"] = {
                    "success": run_result.success,
                    "responses": [
                        {
                            "agent_name": r.agent_name,
                            "content": r.content[:500] if r.content else None,
                        }
                        for r in run_result.responses
                    ],
                    "total_tokens": run_result.total_tokens,
                    "latency_ms": run_result.latency_ms,
                }

            logger.info(
                f"Created team from goal: team_id={team_id}, "
                f"mode={team_config.mode.value}, members={len(team_config.members)}, "
                f"confidence={parsed.confidence:.2f}"
            )

            return result

        except GoalParsingError as e:
            logger.warning(f"Goal parsing failed: {e.message}")
            return {
                "success": False,
                "error": {
                    "code": e.error_code.value,
                    "message": e.message,
                    "details": e.details,
                },
            }
        except GoalTeamError as e:
            logger.error(f"Goal team error: {e.message}")
            return {
                "success": False,
                "error": {
                    "code": e.error_code.value,
                    "message": e.message,
                    "details": e.details,
                },
            }
        except Exception as e:
            logger.exception(f"Failed to create team from goal: {e}")
            return {
                "success": False,
                "error": {
                    "code": ErrorCode.INTERNAL_ERROR.value,
                    "message": str(e),
                },
            }

    @mcp.tool()
    async def parse_goal(goal: str) -> dict[str, Any]:
        """Parse a goal to see what team would be created.

        This is a preview tool that shows how a goal would be interpreted
        without actually creating a team. Useful for debugging and
        understanding the goal parsing logic.

        Args:
            goal: Natural language goal to parse.
                  Example: "Review this code for security vulnerabilities"

        Returns:
            Dictionary with:
            - success: Whether parsing succeeded
            - parsed: Parsed goal details including:
                - intent: Primary intent (review, build, test, fix, etc.)
                - domain: Domain area (security, performance, quality, etc.)
                - skills: Required skills extracted from the goal
                - confidence: Parsing confidence score (0.0-1.0)
                - method: How parsing was done ("pattern" or "llm")
            - suggested_team: What team configuration would be created
            - error: Error details (if failed)

        Example:
            ```python
            result = await parse_goal("Review this code for security issues")
            print(f"Intent: {result['parsed']['intent']}")
            print(f"Skills: {result['parsed']['skills']}")
            print(f"Confidence: {result['parsed']['confidence']}")
            ```
        """
        try:
            # Validate inputs
            if len(goal.strip()) < 10:
                raise GoalParsingError(
                    goal=goal,
                    reason="Goal is too short. Provide at least 10 characters.",
                    error_code=ErrorCode.GOAL_TOO_SHORT,
                )

            # Try to get LLM factory for fallback (may not be available)
            llm_factory = None
            if is_context_initialized():
                with contextlib.suppress(Exception):
                    llm_factory = get_llm_factory()

            # Import factory
            from mahavishnu.engines.goal_team_factory import GoalDrivenTeamFactory

            # Create factory and parse
            factory = GoalDrivenTeamFactory(llm_factory=llm_factory)
            parsed = await factory.parse_goal(goal)

            # Generate suggested team config
            team_config = await factory.create_team_from_goal(goal)

            return {
                "success": True,
                "parsed": {
                    "intent": parsed.intent,
                    "domain": parsed.domain,
                    "skills": parsed.skills,
                    "confidence": parsed.confidence,
                    "method": parsed.metadata.get("method", "unknown"),
                    "raw_goal": parsed.raw_goal,
                },
                "suggested_team": {
                    "name": team_config.name,
                    "mode": team_config.mode.value,
                    "member_count": len(team_config.members),
                    "members": [
                        {
                            "name": m.name,
                            "role": m.role,
                            "model": m.model,
                        }
                        for m in team_config.members
                    ],
                    "has_leader": team_config.leader is not None,
                },
            }

        except GoalParsingError as e:
            return {
                "success": False,
                "error": {
                    "code": e.error_code.value,
                    "message": e.message,
                    "details": e.details,
                },
            }
        except Exception as e:
            logger.exception(f"Failed to parse goal: {e}")
            return {
                "success": False,
                "error": {
                    "code": ErrorCode.INTERNAL_ERROR.value,
                    "message": str(e),
                },
            }

    @mcp.tool()
    async def list_team_skills() -> dict[str, Any]:
        """List all available skills for goal-driven team creation.

        Skills are pre-configured agent templates that get matched to
        goals based on keywords and domain patterns. Each skill defines
        a specialist agent with specific expertise.

        Returns:
            Dictionary with:
            - success: Whether the operation succeeded
            - skills: Dictionary of skill names to configurations:
                - role: The agent's role description
                - tools: Tools the agent can use
                - model: Default LLM model
                - temperature: Sampling temperature
            - count: Total number of available skills

        Example:
            ```python
            result = await list_team_skills()
            for skill_name, config in result['skills'].items():
                print(f"{skill_name}: {config['role']}")
            ```
        """
        try:
            from mahavishnu.engines.goal_team_factory import SKILL_MAPPING

            skills_data = {}
            for skill_name, config in SKILL_MAPPING.items():
                skills_data[skill_name] = {
                    "role": config.role,
                    "tools": config.tools,
                    "model": config.model,
                    "temperature": config.temperature,
                }

            return {
                "success": True,
                "skills": skills_data,
                "count": len(skills_data),
            }

        except Exception as e:
            logger.exception(f"Failed to list team skills: {e}")
            return {
                "success": False,
                "error": {
                    "code": ErrorCode.INTERNAL_ERROR.value,
                    "message": str(e),
                },
                "skills": {},
                "count": 0,
            }

    logger.info("Registered 3 goal-driven team tools")

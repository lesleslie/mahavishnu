"""Goal-driven team MCP tools for natural language team creation.

This module provides MCP tools for creating and managing agent teams
from natural language goals using the GoalDrivenTeamFactory.

Created: 2026-02-21
Version: 1.4
Related: Goal-Driven Teams Phase 1 + Phase 3 - MCP tool integration with feature flags, Prometheus metrics, WebSocket broadcasting, and learning
"""

from __future__ import annotations

import contextlib
import logging
import time
from datetime import UTC, datetime
from typing import Any

from fastmcp import FastMCP  # noqa: TC002

from mahavishnu.core.context import (
    get_agno_adapter,
    get_llm_factory,
    get_websocket_server,
    is_context_initialized,
)
from mahavishnu.core.errors import (
    ErrorCode,
    FeatureDisabledError,
    GoalParsingError,
    GoalTeamError,
)
from mahavishnu.core.feature_flags import is_feature_enabled
from mahavishnu.core.goal_team_metrics import get_goal_team_metrics
from mahavishnu.core import team_learning

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
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Create an agent team from a natural language goal."""
        # Get metrics instance for recording
        metrics = get_goal_team_metrics()
        # Get WebSocket server for broadcasting (optional)
        ws_server = get_websocket_server()
        start_time = time.monotonic()
        team_id = None

        try:
            # Check feature flags first
            if not is_feature_enabled("enabled"):
                return {
                    "success": False,
                    "error": {
                        "code": ErrorCode.FEATURE_DISABLED.value,
                        "message": "Goal-Driven Teams feature is disabled. Enable it in settings/mahavishnu.yaml under goal_teams.enabled",
                    },
                }

            if not is_feature_enabled("mcp_tools_enabled"):
                return {
                    "success": False,
                    "error": {
                        "code": ErrorCode.FEATURE_DISABLED.value,
                        "message": "Goal-Driven Teams MCP tools are disabled. Enable mcp_tools_enabled in feature_flags",
                    },
                }

            # Validate inputs
            if len(goal.strip()) < 10:
                metrics.record_error(error_code=ErrorCode.GOAL_TOO_SHORT.value)
                error = GoalParsingError(
                    goal=goal,
                    reason="Goal is too short. Provide at least 10 characters describing the task.",
                    error_code=ErrorCode.GOAL_TOO_SHORT,
                )
                # Broadcast error
                if ws_server:
                    await ws_server.broadcast_team_error(
                        team_id="",
                        error_code=ErrorCode.GOAL_TOO_SHORT.value,
                        message=error.message,
                        user_id=user_id,
                    )
                raise error

            if len(goal) > 1000:
                metrics.record_error(error_code=ErrorCode.GOAL_TOO_LONG.value)
                error = GoalParsingError(
                    goal=goal,
                    reason="Goal is too long. Maximum 1000 characters allowed.",
                    error_code=ErrorCode.GOAL_TOO_LONG,
                )
                # Broadcast error
                if ws_server:
                    await ws_server.broadcast_team_error(
                        team_id="",
                        error_code=ErrorCode.GOAL_TOO_LONG.value,
                        message=error.message,
                        user_id=user_id,
                    )
                raise error

            if auto_run and not task:
                metrics.record_error(error_code=ErrorCode.VALIDATION_ERROR.value)
                error_msg = "task parameter is required when auto_run=True"
                # Broadcast error
                if ws_server:
                    await ws_server.broadcast_team_error(
                        team_id="",
                        error_code=ErrorCode.VALIDATION_ERROR.value,
                        message=error_msg,
                        user_id=user_id,
                    )
                return {
                    "success": False,
                    "error": {
                        "code": ErrorCode.VALIDATION_ERROR.value,
                        "message": error_msg,
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
                    metrics.record_error(error_code=ErrorCode.VALIDATION_ERROR.value)
                    error_msg = f"Invalid mode '{mode}'. Must be one of: {list(mode_map.keys())}"
                    # Broadcast error
                    if ws_server:
                        await ws_server.broadcast_team_error(
                            team_id="",
                            error_code=ErrorCode.VALIDATION_ERROR.value,
                            message=error_msg,
                            user_id=user_id,
                        )
                    return {
                        "success": False,
                        "error": {
                            "code": ErrorCode.VALIDATION_ERROR.value,
                            "message": error_msg,
                        },
                    }
                team_mode = mode_map[mode.lower()]

            # Create factory and parse goal with metrics
            # Check if LLM fallback is enabled for goal parsing
            use_llm_fallback = is_feature_enabled("llm_fallback_enabled")
            factory = GoalDrivenTeamFactory(llm_factory=llm_factory if use_llm_fallback else None)
            parsed = await factory.parse_goal(goal)

            # Record goal parsing metrics
            metrics.record_goal_parsed(
                intent=parsed.intent,
                domain=parsed.domain,
                method=parsed.metadata.get("method", "pattern"),
                confidence=parsed.confidence,
            )

            # Record skill usage for parsed skills
            metrics.record_skills_usage(parsed.skills)

            # Broadcast goal parsed event (if WebSocket broadcasts enabled)
            if ws_server and is_feature_enabled("websocket_broadcasts_enabled"):
                await ws_server.broadcast_team_parsed(
                    goal=goal,
                    intent=parsed.intent,
                    skills=parsed.skills,
                    confidence=parsed.confidence,
                    user_id=user_id,
                )

            # Determine final mode for metrics
            final_mode = team_mode if team_mode else parsed.intent

            # Create team configuration with timing
            with metrics.team_creation_duration(
                mode=final_mode.value if hasattr(final_mode, "value") else str(final_mode)
            ):
                team_config = await factory.create_team_from_goal(
                    goal=goal,
                    name=name,
                    mode=team_mode,
                )

            # Get Agno adapter and create the team
            agno_adapter = get_agno_adapter()
            team_id = await agno_adapter.create_team(team_config)

            # Record successful team creation (if Prometheus metrics enabled)
            if is_feature_enabled("prometheus_metrics_enabled"):
                metrics.record_team_created(
                    mode=team_config.mode.value,
                    skill_count=len(team_config.members),
                )

                # Increment active teams gauge
                metrics.increment_active_teams()

                # Set team info metric
                metrics.set_team_info(
                    team_id=team_id,
                    mode=team_config.mode.value,
                    intent=parsed.intent,
                    domain=parsed.domain,
                    skill_count=len(team_config.members),
                    confidence=parsed.confidence,
                )

            # Broadcast team created event (if WebSocket broadcasts enabled)
            if ws_server and is_feature_enabled("websocket_broadcasts_enabled"):
                await ws_server.broadcast_team_created(
                    team_id=team_id,
                    team_name=team_config.name,
                    goal=goal,
                    mode=team_config.mode.value,
                    user_id=user_id,
                )

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
                    }
                    if team_config.leader
                    else None,
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

                # Broadcast execution started (if WebSocket broadcasts enabled)
                if ws_server and is_feature_enabled("websocket_broadcasts_enabled"):
                    await ws_server.broadcast_team_execution_started(
                        team_id=team_id,
                        task=task,
                        user_id=user_id,
                    )

                run_result = await agno_adapter.run_team(team_id, task)
                latency_ms = (time.monotonic() - start_time) * 1000

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

                # Broadcast execution completed (if WebSocket broadcasts enabled)
                if ws_server and is_feature_enabled("websocket_broadcasts_enabled"):
                    await ws_server.broadcast_team_execution_completed(
                        team_id=team_id,
                        success=run_result.success,
                        duration_ms=latency_ms,
                        user_id=user_id,
                    )

                # Record learning outcome (if learning system enabled)
                if is_feature_enabled("learning_system_enabled"):
                    try:
                        learning_engine = team_learning.get_learning_engine()
                        learning_engine.record_outcome(
                            team_learning.TeamExecutionOutcome(
                                team_id=team_id,
                                goal=goal,
                                parsed_intent=parsed.intent,
                                parsed_domain=parsed.domain,
                                parsed_skills=parsed.skills,
                                team_mode=team_config.mode.value,
                                task=task or goal,
                                success=run_result.success,
                                latency_ms=latency_ms,
                                tokens_used=run_result.total_tokens,
                            )
                        )
                        metrics.record_learning_outcome(
                            success=run_result.success,
                            mode=team_config.mode.value,
                            latency_ms=latency_ms,
                        )
                    except Exception:
                        logger.debug(
                            "Learning outcome recording failed; continuing without blocking",
                            exc_info=True,
                        )

            logger.info(
                f"Created team from goal: team_id={team_id}, "
                f"mode={team_config.mode.value}, members={len(team_config.members)}, "
                f"confidence={parsed.confidence:.2f}"
            )

            return result

        except FeatureDisabledError as e:
            logger.warning(f"Feature disabled: {e.message}")
            return {
                "success": False,
                "error": {
                    "code": e.error_code.value,
                    "message": e.message,
                    "details": e.details,
                },
            }
        except GoalParsingError as e:
            logger.warning(f"Goal parsing failed: {e.message}")
            metrics.record_error(error_code=e.error_code.value)
            # Broadcast error
            if ws_server and not team_id:
                await ws_server.broadcast_team_error(
                    team_id=team_id or "",
                    error_code=e.error_code.value,
                    message=e.message,
                    user_id=user_id,
                )
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
            metrics.record_error(error_code=e.error_code.value)
            # Broadcast error
            if ws_server:
                await ws_server.broadcast_team_error(
                    team_id=team_id or "",
                    error_code=e.error_code.value,
                    message=e.message,
                    user_id=user_id,
                )
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
            metrics.record_error(error_code=ErrorCode.INTERNAL_ERROR.value)
            # Broadcast error
            if ws_server:
                await ws_server.broadcast_team_error(
                    team_id=team_id or "",
                    error_code=ErrorCode.INTERNAL_ERROR.value,
                    message=str(e),
                    user_id=user_id,
                )
            return {
                "success": False,
                "error": {
                    "code": ErrorCode.INTERNAL_ERROR.value,
                    "message": str(e),
                },
            }

    @mcp.tool()
    async def parse_goal(goal: str, user_id: str | None = None) -> dict[str, Any]:
        """Parse a goal to see what team would be created."""
        # Get metrics instance for recording
        metrics = get_goal_team_metrics()
        # Get WebSocket server for broadcasting (optional)
        ws_server = get_websocket_server()

        try:
            # Check feature flags first
            if not is_feature_enabled("enabled"):
                return {
                    "success": False,
                    "error": {
                        "code": ErrorCode.FEATURE_DISABLED.value,
                        "message": "Goal-Driven Teams feature is disabled. Enable it in settings/mahavishnu.yaml under goal_teams.enabled",
                    },
                }

            if not is_feature_enabled("mcp_tools_enabled"):
                return {
                    "success": False,
                    "error": {
                        "code": ErrorCode.FEATURE_DISABLED.value,
                        "message": "Goal-Driven Teams MCP tools are disabled. Enable mcp_tools_enabled in feature_flags",
                    },
                }

            # Validate inputs
            if len(goal.strip()) < 10:
                metrics.record_error(error_code=ErrorCode.GOAL_TOO_SHORT.value)
                error = GoalParsingError(
                    goal=goal,
                    reason="Goal is too short. Provide at least 10 characters.",
                    error_code=ErrorCode.GOAL_TOO_SHORT,
                )
                # Broadcast error
                if ws_server:
                    await ws_server.broadcast_team_error(
                        team_id="",
                        error_code=ErrorCode.GOAL_TOO_SHORT.value,
                        message=error.message,
                        user_id=user_id,
                    )
                raise error

            # Try to get LLM factory for fallback (may not be available)
            llm_factory = None
            if is_context_initialized():
                with contextlib.suppress(Exception):
                    llm_factory = get_llm_factory()

            # Import factory
            from mahavishnu.engines.goal_team_factory import GoalDrivenTeamFactory

            # Create factory and parse
            # Check if LLM fallback is enabled for goal parsing
            use_llm_fallback = is_feature_enabled("llm_fallback_enabled")
            factory = GoalDrivenTeamFactory(llm_factory=llm_factory if use_llm_fallback else None)
            parsed = await factory.parse_goal(goal)

            # Record goal parsing metrics (if Prometheus metrics enabled)
            if is_feature_enabled("prometheus_metrics_enabled"):
                metrics.record_goal_parsed(
                    intent=parsed.intent,
                    domain=parsed.domain,
                    method=parsed.metadata.get("method", "unknown"),
                    confidence=parsed.confidence,
                )

            # Broadcast goal parsed event (if WebSocket broadcasts enabled)
            if ws_server and is_feature_enabled("websocket_broadcasts_enabled"):
                await ws_server.broadcast_team_parsed(
                    goal=goal,
                    intent=parsed.intent,
                    skills=parsed.skills,
                    confidence=parsed.confidence,
                    user_id=user_id,
                )

            # Generate suggested team config
            team_config = await factory.create_team_from_goal(goal)

            # Check learning system for mode recommendation (Phase 3)
            recommended_mode = None
            if is_feature_enabled("learning_system_enabled"):
                try:
                    learning_engine = team_learning.get_learning_engine()
                    recommendation = learning_engine.get_mode_recommendation(parsed.intent)
                    if recommendation is not None:
                        recommended_mode = (
                            recommendation.model_dump()
                            if hasattr(recommendation, "model_dump")
                            else {
                                "mode": recommendation.mode,
                                "confidence": recommendation.confidence,
                                "success_rate": recommendation.success_rate,
                                "sample_count": recommendation.sample_count,
                                "reason": recommendation.reason,
                            }
                        )
                        metrics.record_mode_recommendation(
                            intent=parsed.intent,
                            mode=recommendation.mode,
                            confidence=recommendation.confidence,
                        )
                except Exception:
                    logger.debug(
                        "Mode recommendation failed; continuing without recommendation",
                        exc_info=True,
                    )

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
                "recommended_mode": recommended_mode,
            }

        except FeatureDisabledError as e:
            return {
                "success": False,
                "error": {
                    "code": e.error_code.value,
                    "message": e.message,
                    "details": e.details,
                },
            }
        except GoalParsingError as e:
            metrics.record_error(error_code=e.error_code.value)
            # Broadcast error
            if ws_server:
                await ws_server.broadcast_team_error(
                    team_id="",
                    error_code=e.error_code.value,
                    message=e.message,
                    user_id=user_id,
                )
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
            metrics.record_error(error_code=ErrorCode.INTERNAL_ERROR.value)
            # Broadcast error
            if ws_server:
                await ws_server.broadcast_team_error(
                    team_id="",
                    error_code=ErrorCode.INTERNAL_ERROR.value,
                    message=str(e),
                    user_id=user_id,
                )
            return {
                "success": False,
                "error": {
                    "code": ErrorCode.INTERNAL_ERROR.value,
                    "message": str(e),
                },
            }

    @mcp.tool()
    async def list_team_skills() -> dict[str, Any]:
        """List all available skills for goal-driven team creation."""
        try:
            # Check feature flags first
            if not is_feature_enabled("enabled"):
                return {
                    "success": False,
                    "error": {
                        "code": ErrorCode.FEATURE_DISABLED.value,
                        "message": "Goal-Driven Teams feature is disabled. Enable it in settings/mahavishnu.yaml under goal_teams.enabled",
                    },
                    "skills": {},
                    "count": 0,
                }

            if not is_feature_enabled("mcp_tools_enabled"):
                return {
                    "success": False,
                    "error": {
                        "code": ErrorCode.FEATURE_DISABLED.value,
                        "message": "Goal-Driven Teams MCP tools are disabled. Enable mcp_tools_enabled in feature_flags",
                    },
                    "skills": {},
                    "count": 0,
                }

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

        except FeatureDisabledError as e:
            return {
                "success": False,
                "error": {
                    "code": e.error_code.value,
                    "message": e.message,
                    "details": e.details,
                },
                "skills": {},
                "count": 0,
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

    logger.info(
        "Registered 3 goal-driven team tools with feature flags, Prometheus metrics, WebSocket broadcasting, and learning integration"
    )

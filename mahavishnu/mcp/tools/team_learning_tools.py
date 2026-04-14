"""Team Learning MCP tools for Goal-Driven Teams.

This module provides MCP tools for recording and querying team
execution outcomes for the learning system.

Tools:
    - record_team_outcome: Record an execution result
    - get_learning_summary: View learning data summary
    - get_recommended_mode: Get mode recommendation for an intent
    - get_learning_stats: Get detailed statistics
    - record_user_feedback: Record user feedback on an outcome

Created: 2026-02-21
Version: 1.0
Related: Goal-Driven Teams Phase 3 - Learning System MCP tools
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastmcp import FastMCP

from mahavishnu.core.feature_flags import is_feature_enabled
from mahavishnu.core.team_learning import (
    ModeRecommendation,
    TeamExecutionOutcome,
    get_learning_engine,
)

logger = logging.getLogger(__name__)


def register_team_learning_tools(mcp: FastMCP) -> None:
    """Register team learning tools with FastMCP.

    Args:
        mcp: FastMCP instance to register tools with
    """

    @mcp.tool()
    async def record_team_outcome(
        team_id: str,
        goal: str,
        parsed_intent: str,
        parsed_domain: str,
        parsed_skills: list[str],
        team_mode: str,
        task: str,
        success: bool,
        latency_ms: float,
        tokens_used: int = 0,
        quality_score: float | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        user_feedback: str | None = None,
    ) -> dict[str, Any]:
        """Record a team execution outcome for learning."""
        try:
            # Check feature flags
            if not is_feature_enabled("enabled"):
                return {
                    "success": False,
                    "error": {
                        "code": "FEATURE_DISABLED",
                        "message": "Goal-Driven Teams feature is disabled",
                    },
                }

            if not is_feature_enabled("learning_system_enabled"):
                return {
                    "success": False,
                    "error": {
                        "code": "FEATURE_DISABLED",
                        "message": "Learning system is disabled. Enable learning_system_enabled in feature_flags",
                    },
                }

            # Validate user_feedback
            if user_feedback is not None and user_feedback not in ("positive", "negative"):
                return {
                    "success": False,
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "user_feedback must be 'positive', 'negative', or None",
                    },
                }

            # Validate quality_score
            if quality_score is not None and not (0 <= quality_score <= 100):
                return {
                    "success": False,
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "quality_score must be between 0 and 100",
                    },
                }

            # Create outcome object
            outcome = TeamExecutionOutcome(
                team_id=team_id,
                goal=goal,
                parsed_intent=parsed_intent,
                parsed_domain=parsed_domain,
                parsed_skills=parsed_skills,
                team_mode=team_mode,
                task=task,
                success=success,
                latency_ms=latency_ms,
                tokens_used=tokens_used,
                quality_score=quality_score,
                timestamp=datetime.now(UTC),
                error_code=error_code,
                error_message=error_message,
                user_feedback=user_feedback,
            )

            # Record the outcome
            engine = get_learning_engine()
            engine.record_outcome(outcome)

            # Generate outcome ID
            outcome_id = f"outcome_{team_id}_{int(outcome.timestamp.timestamp())}"

            logger.info(
                f"Recorded team outcome: team_id={team_id}, success={success}, "
                f"mode={team_mode}, latency={latency_ms:.0f}ms"
            )

            return {
                "success": True,
                "outcome_id": outcome_id,
                "message": f"Recorded outcome for team {team_id}: {'success' if success else 'failed'}",
                "timestamp": outcome.timestamp.isoformat(),
            }

        except Exception as e:
            logger.exception(f"Failed to record team outcome: {e}")
            return {
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": str(e),
                },
            }

    @mcp.tool()
    async def get_learning_summary() -> dict[str, Any]:
        """Get a summary of the team learning system."""
        try:
            # Check feature flags
            if not is_feature_enabled("enabled"):
                return {
                    "success": False,
                    "error": {
                        "code": "FEATURE_DISABLED",
                        "message": "Goal-Driven Teams feature is disabled",
                    },
                }

            engine = get_learning_engine()
            summary = engine.get_learning_summary()

            return {
                "success": True,
                "summary": summary,
            }

        except Exception as e:
            logger.exception(f"Failed to get learning summary: {e}")
            return {
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": str(e),
                },
            }

    @mcp.tool()
    async def get_recommended_mode(
        intent: str,
        min_samples: int = 3,
    ) -> dict[str, Any]:
        """Get recommended team mode for an intent."""
        try:
            # Check feature flags
            if not is_feature_enabled("enabled"):
                return {
                    "success": False,
                    "error": {
                        "code": "FEATURE_DISABLED",
                        "message": "Goal-Driven Teams feature is disabled",
                    },
                }

            engine = get_learning_engine()
            recommendation = engine.get_mode_recommendation(intent, min_samples=min_samples)

            # Fallback mode based on intent
            fallback_map = {
                "review": "coordinate",
                "build": "coordinate",
                "test": "coordinate",
                "fix": "route",
                "refactor": "coordinate",
                "document": "route",
                "analyze": "broadcast",
            }
            fallback_mode = fallback_map.get(intent, "coordinate")

            if recommendation is None:
                return {
                    "success": True,
                    "recommendation": None,
                    "fallback_mode": fallback_mode,
                    "message": f"Insufficient data for intent '{intent}'. Using fallback mode '{fallback_mode}'.",
                }

            return {
                "success": True,
                "recommendation": recommendation.model_dump(),
                "fallback_mode": fallback_mode,
            }

        except Exception as e:
            logger.exception(f"Failed to get recommended mode: {e}")
            return {
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": str(e),
                },
            }

    @mcp.tool()
    async def get_learning_stats(
        stats_type: str,
        key: str | None = None,
    ) -> dict[str, Any]:
        """Get detailed learning statistics."""
        try:
            # Check feature flags
            if not is_feature_enabled("enabled"):
                return {
                    "success": False,
                    "error": {
                        "code": "FEATURE_DISABLED",
                        "message": "Goal-Driven Teams feature is disabled",
                    },
                }

            engine = get_learning_engine()

            if stats_type == "mode":
                if not key:
                    return {
                        "success": False,
                        "error": {
                            "code": "VALIDATION_ERROR",
                            "message": "key parameter required for stats_type='mode'",
                        },
                    }
                stats = engine.get_mode_stats(key)
                if stats is None:
                    return {
                        "success": True,
                        "stats_type": stats_type,
                        "key": key,
                        "stats": None,
                        "message": f"No data for mode '{key}'",
                    }
                return {
                    "success": True,
                    "stats_type": stats_type,
                    "key": key,
                    "stats": stats.to_dict(),
                }

            elif stats_type == "intent":
                if not key:
                    return {
                        "success": False,
                        "error": {
                            "code": "VALIDATION_ERROR",
                            "message": "key parameter required for stats_type='intent'",
                        },
                    }
                stats = engine.get_intent_stats(key)
                if stats is None:
                    return {
                        "success": True,
                        "stats_type": stats_type,
                        "key": key,
                        "stats": None,
                        "message": f"No data for intent '{key}'",
                    }
                return {
                    "success": True,
                    "stats_type": stats_type,
                    "key": key,
                    "stats": stats.to_dict(),
                }

            elif stats_type == "skill":
                if not key:
                    return {
                        "success": False,
                        "error": {
                            "code": "VALIDATION_ERROR",
                            "message": "key parameter required for stats_type='skill' (comma-separated skills)",
                        },
                    }
                skills = [s.strip() for s in key.split(",")]
                success_rate = engine.get_skill_success_rate(skills)
                skill_key = ",".join(sorted(skills))
                # Get full stats if available
                stats_dict = engine._skill_stats.get(skill_key)
                return {
                    "success": True,
                    "stats_type": stats_type,
                    "key": key,
                    "stats": stats_dict.to_dict() if stats_dict else {"success_rate": success_rate},
                }

            elif stats_type == "recent":
                limit = 10  # Default limit for recent outcomes
                stats = engine.get_recent_outcomes(limit=limit)
                return {
                    "success": True,
                    "stats_type": stats_type,
                    "stats": stats,
                    "count": len(stats),
                }

            else:
                return {
                    "success": False,
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": f"Invalid stats_type '{stats_type}'. Must be one of: mode, intent, skill, recent",
                    },
                }

        except Exception as e:
            logger.exception(f"Failed to get learning stats: {e}")
            return {
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": str(e),
                },
            }

    @mcp.tool()
    async def record_user_feedback(
        team_id: str,
        feedback: str,
        quality_score: float | None = None,
    ) -> dict[str, Any]:
        """Record user feedback for a recent team execution."""
        try:
            # Check feature flags
            if not is_feature_enabled("enabled"):
                return {
                    "success": False,
                    "error": {
                        "code": "FEATURE_DISABLED",
                        "message": "Goal-Driven Teams feature is disabled",
                    },
                }

            if not is_feature_enabled("learning_system_enabled"):
                return {
                    "success": False,
                    "error": {
                        "code": "FEATURE_DISABLED",
                        "message": "Learning system is disabled",
                    },
                }

            # Validate feedback
            if feedback not in ("positive", "negative"):
                return {
                    "success": False,
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "feedback must be 'positive' or 'negative'",
                    },
                }

            # Validate quality_score
            if quality_score is not None and not (0 <= quality_score <= 100):
                return {
                    "success": False,
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "quality_score must be between 0 and 100",
                    },
                }

            engine = get_learning_engine()

            # Find most recent outcome for this team
            team_outcomes = [o for o in engine._recent_outcomes if o.team_id == team_id]
            if not team_outcomes:
                return {
                    "success": False,
                    "error": {
                        "code": "NOT_FOUND",
                        "message": f"No recent outcomes found for team '{team_id}'",
                    },
                }

            # Update the most recent outcome
            outcome = team_outcomes[-1]
            outcome.user_feedback = feedback
            if quality_score is not None:
                outcome.quality_score = quality_score

            # Update stats
            skill_key = ",".join(sorted(outcome.parsed_skills)) if outcome.parsed_skills else "none"
            if skill_key in engine._skill_stats:
                if feedback == "positive":
                    engine._skill_stats[skill_key].positive_feedback_count += 1
                else:
                    engine._skill_stats[skill_key].negative_feedback_count += 1

            if outcome.parsed_intent in engine._intent_stats:
                if feedback == "positive":
                    engine._intent_stats[outcome.parsed_intent].positive_feedback_count += 1
                else:
                    engine._intent_stats[outcome.parsed_intent].negative_feedback_count += 1

            if outcome.team_mode in engine._mode_stats:
                if feedback == "positive":
                    engine._mode_stats[outcome.team_mode].positive_feedback_count += 1
                else:
                    engine._mode_stats[outcome.team_mode].negative_feedback_count += 1

            logger.info(f"Recorded user feedback for team {team_id}: {feedback}")

            return {
                "success": True,
                "message": f"Recorded {feedback} feedback for team {team_id}",
                "team_id": team_id,
                "feedback": feedback,
                "quality_score": quality_score,
            }

        except Exception as e:
            logger.exception(f"Failed to record user feedback: {e}")
            return {
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": str(e),
                },
            }

    logger.info(
        "Registered 5 team learning tools: record_team_outcome, get_learning_summary, get_recommended_mode, get_learning_stats, record_user_feedback"
    )

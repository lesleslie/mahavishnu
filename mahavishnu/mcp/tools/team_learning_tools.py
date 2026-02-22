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
        """Record a team execution outcome for learning.

        This tool records the result of a team execution so the learning
        system can improve future team configurations.

        Args:
            team_id: Unique team identifier
            goal: Original natural language goal
            parsed_intent: Intent extracted from goal (review, build, test, etc.)
            parsed_domain: Domain extracted from goal (security, performance, etc.)
            parsed_skills: Skills extracted from goal
            team_mode: Team collaboration mode used (coordinate, route, broadcast, collaborate)
            task: The actual task that was executed
            success: Whether the execution succeeded
            latency_ms: Execution latency in milliseconds
            tokens_used: Total tokens consumed (default: 0)
            quality_score: Optional quality score 0-100 (default: None)
            error_code: Error code if execution failed (default: None)
            error_message: Error message if execution failed (default: None)
            user_feedback: User feedback "positive" or "negative" (default: None)

        Returns:
            Dictionary with:
            - success: Whether recording succeeded
            - outcome_id: Unique identifier for the recorded outcome
            - message: Human-readable confirmation
            - error: Error details if failed

        Example:
            ```python
            result = await record_team_outcome(
                team_id="team_abc123",
                goal="Review code for security vulnerabilities",
                parsed_intent="review",
                parsed_domain="security",
                parsed_skills=["security", "quality"],
                team_mode="coordinate",
                task="Review the authentication module",
                success=True,
                latency_ms=1500.0,
                quality_score=92.5,
            )
            print(result["message"])
            ```
        """
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
        """Get a summary of the team learning system.

        Returns aggregate statistics about team executions, including
        success rates, top performing skills, and mode performance.

        Returns:
            Dictionary with:
            - success: Whether the operation succeeded
            - summary: Learning summary including:
                - total_outcomes: Total recorded outcomes
                - skill_combinations: Number of unique skill combinations
                - intents_tracked: Number of intents with data
                - modes_tracked: Number of modes with data
                - top_skills: Top 5 performing skill combinations
                - mode_performance: Performance stats by mode
                - intent_performance: Performance stats by intent
                - recent_success_rate: Success rate for recent outcomes
            - error: Error details if failed

        Example:
            ```python
            result = await get_learning_summary()
            print(f"Total outcomes: {result['summary']['total_outcomes']}")
            print(f"Recent success rate: {result['summary']['recent_success_rate']:.0%}")
            ```
        """
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
        """Get recommended team mode for an intent.

        Analyzes historical execution data to recommend the best
        collaboration mode for a given intent.

        Args:
            intent: The intent to get a recommendation for
                   (review, build, test, fix, refactor, document, analyze)
            min_samples: Minimum samples required for recommendation (default: 3)

        Returns:
            Dictionary with:
            - success: Whether the operation succeeded
            - recommendation: Mode recommendation (if available):
                - mode: Recommended team mode
                - confidence: Confidence in recommendation (0.0-1.0)
                - success_rate: Historical success rate for this mode
                - sample_count: Number of samples used
                - reason: Human-readable explanation
            - fallback_mode: Default mode if no recommendation available
            - error: Error details if failed

        Example:
            ```python
            result = await get_recommended_mode(intent="review")
            if result.get("recommendation"):
                print(f"Recommended: {result['recommendation']['mode']}")
                print(f"Confidence: {result['recommendation']['confidence']:.0%}")
            else:
                print(f"Using fallback: {result['fallback_mode']}")
            ```
        """
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
        """Get detailed learning statistics.

        Query specific statistics from the learning system.

        Args:
            stats_type: Type of stats to retrieve:
                - "mode": Stats for a specific mode (requires key)
                - "intent": Stats for a specific intent (requires key)
                - "skill": Stats for a skill combination (requires key as comma-separated)
                - "recent": Recent execution outcomes
            key: The specific key to query (required for mode/intent/skill types)

        Returns:
            Dictionary with:
            - success: Whether the operation succeeded
            - stats_type: The type of stats retrieved
            - stats: The requested statistics
            - error: Error details if failed

        Example:
            ```python
            # Get mode stats
            result = await get_learning_stats(stats_type="mode", key="coordinate")
            print(f"Success rate: {result['stats']['success_rate']:.0%}")

            # Get skill stats
            result = await get_learning_stats(stats_type="skill", key="security,quality")
            print(f"Executions: {result['stats']['total_executions']}")

            # Get recent outcomes
            result = await get_learning_stats(stats_type="recent")
            for outcome in result['stats']:
                print(f"Team: {outcome['team_id']}, Success: {outcome['success']}")
            ```
        """
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
        """Record user feedback for a recent team execution.

        Updates the most recent outcome for a team with user feedback.
        This feedback is used to improve future recommendations.

        Args:
            team_id: The team ID to provide feedback for
            feedback: User feedback, either "positive" or "negative"
            quality_score: Optional quality score 0-100 (default: None)

        Returns:
            Dictionary with:
            - success: Whether recording succeeded
            - message: Confirmation message
            - error: Error details if failed

        Example:
            ```python
            result = await record_user_feedback(
                team_id="team_abc123",
                feedback="positive",
                quality_score=95.0,
            )
            print(result["message"])
            ```
        """
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

    logger.info("Registered 5 team learning tools: record_team_outcome, get_learning_summary, get_recommended_mode, get_learning_stats, record_user_feedback")

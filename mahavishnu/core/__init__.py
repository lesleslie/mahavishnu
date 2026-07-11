"""Mahavishnu core module.

All public symbols are lazily imported via __getattr__ to avoid pulling in
heavy submodules (config loading, adapter init, etc.) when only individual
submodules are needed.  Access anything from ``mahavishnu.core`` and it will
be imported on first use.
"""

from __future__ import annotations

import asyncio

__all__ = [
    "MahavishnuApp",
    "MahavishnuSettings",
    "MahavishnuError",
    "ConfigurationError",
    "WorkflowError",
    # New error classes for Phase 0
    "AdapterError",
    "AuthenticationError",
    "AuthorizationError",
    "ValidationError",
    "TaskNotFoundError",
    "RepositoryNotFoundError",
    "WebhookAuthError",
    "RateLimitError",
    "TimeoutError",
    "DatabaseError",
    "ExternalServiceError",
    "ErrorCode",
    "RepositoryManager",
    "Repository",
    "RepositoryManifest",
    "RepositoryMetadata",
    "ExecutionTracker",
    "get_execution_tracker",
    "AdapterType",
    "TaskType",
    "ExecutionStatus",
    "StatisticalRouter",
    "CostOptimizer",
    "TaskRouter",
    "RoutingMetrics",
    "get_routing_metrics",
    "Alert",
    "AlertSeverity",
    "AlertType",
    "AlertHandler",
    "LoggingAlertHandler",
    "RoutingAlertManager",
    "get_alert_manager",
    # Approval Manager
    "ApprovalManager",
    "ApprovalOption",
    "ApprovalRequest",
    "ApprovalResult",
    # Fix Orchestrator
    "FixOrchestrator",
    "FixTask",
    "FixResult",
    "QualityGateResult",
    # Skill governance
    "LearningArtifactType",
    "LearningEvidence",
    "SkillActivation",
    "SkillDraft",
    "SkillPromotionPolicy",
    "SkillPromotionState",
    "SkillRollback",
    "SkillReview",
    "SkillReviewDecision",
    # Completion report (Spec #1 Phase 1: completion-report-schema-v1)
    "CompletionReport",
    "CompletionStatus",
    "ReportArtifact",
    "LocalFileCompletionPersister",
    # Loop helpers (Phase 2: detect_until_dry for ultracode integration wiring)
    "detect_until_dry",
]

# Mapping of export name -> (relative_module, attribute_name)
_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    # App
    "MahavishnuApp": (".app", "MahavishnuApp"),
    # Config
    "MahavishnuSettings": (".config", "MahavishnuSettings"),
    # Errors
    "ErrorCode": (".errors", "ErrorCode"),
    "MahavishnuError": (".errors", "MahavishnuError"),
    "ConfigurationError": (".errors", "ConfigurationError"),
    "WorkflowError": (".errors", "WorkflowError"),
    "AdapterError": (".errors", "AdapterError"),
    "AuthenticationError": (".errors", "AuthenticationError"),
    "AuthorizationError": (".errors", "AuthorizationError"),
    "ValidationError": (".errors", "ValidationError"),
    "TaskNotFoundError": (".errors", "TaskNotFoundError"),
    "RepositoryNotFoundError": (".errors", "RepositoryNotFoundError"),
    "WebhookAuthError": (".errors", "WebhookAuthError"),
    "RateLimitError": (".errors", "RateLimitError"),
    "TimeoutError": (".errors", "TimeoutError"),
    "DatabaseError": (".errors", "DatabaseError"),
    "ExternalServiceError": (".errors", "ExternalServiceError"),
    # Cost optimizer
    "CostOptimizer": (".cost_optimizer", "CostOptimizer"),
    # Fix orchestrator
    "FixOrchestrator": (".fix_orchestrator", "FixOrchestrator"),
    "FixResult": (".fix_orchestrator", "FixResult"),
    "FixTask": (".fix_orchestrator", "FixTask"),
    "QualityGateResult": (".fix_orchestrator", "QualityGateResult"),
    # Skill governance
    "LearningArtifactType": (".skill_governance", "LearningArtifactType"),
    "LearningEvidence": (".skill_governance", "LearningEvidence"),
    "SkillActivation": (".skill_governance", "SkillActivation"),
    "SkillDraft": (".skill_governance", "SkillDraft"),
    "SkillPromotionPolicy": (".skill_governance", "SkillPromotionPolicy"),
    "SkillPromotionState": (".skill_governance", "SkillPromotionState"),
    "SkillRollback": (".skill_governance", "SkillRollback"),
    "SkillReview": (".skill_governance", "SkillReview"),
    "SkillReviewDecision": (".skill_governance", "SkillReviewDecision"),
    # Completion report (Spec #1 Phase 1: completion-report-schema-v1)
    "CompletionReport": (".completion_report", "CompletionReport"),
    "CompletionStatus": (".completion_report", "CompletionStatus"),
    "ReportArtifact": (".completion_report", "ReportArtifact"),
    "LocalFileCompletionPersister": (
        ".completion_persister",
        "LocalFileCompletionPersister",
    ),
    # Metrics collector
    "ExecutionTracker": (".metrics_collector", "ExecutionTracker"),
    "get_execution_tracker": (".metrics_collector", "get_execution_tracker"),
    # Metrics schema
    "AdapterType": (".metrics_schema", "AdapterType"),
    "ExecutionStatus": (".metrics_schema", "ExecutionStatus"),
    "TaskType": (".metrics_schema", "TaskType"),
    # Repo manager
    "RepositoryManager": (".repo_manager", "RepositoryManager"),
    # Repo models
    "Repository": (".repo_models", "Repository"),
    "RepositoryManifest": (".repo_models", "RepositoryManifest"),
    "RepositoryMetadata": (".repo_models", "RepositoryMetadata"),
    # Routing alerts
    "Alert": (".routing_alerts", "Alert"),
    "AlertHandler": (".routing_alerts", "AlertHandler"),
    "AlertSeverity": (".routing_alerts", "AlertSeverity"),
    "AlertType": (".routing_alerts", "AlertType"),
    "LoggingAlertHandler": (".routing_alerts", "LoggingAlertHandler"),
    "RoutingAlertManager": (".routing_alerts", "RoutingAlertManager"),
    "get_alert_manager": (".routing_alerts", "get_alert_manager"),
    # Routing metrics
    "RoutingMetrics": (".routing_metrics", "RoutingMetrics"),
    "get_routing_metrics": (".routing_metrics", "get_routing_metrics"),
    # Statistical router
    "StatisticalRouter": (".statistical_router", "StatisticalRouter"),
    # Task router
    "TaskRouter": (".task_router", "TaskRouter"),
    # Loop helpers (Phase 2: detect_until_dry for ultracode integration wiring)
    "detect_until_dry": (".loop_helpers", "detect_until_dry"),
    # Approval manager
    "ApprovalManager": (".approval_manager", "ApprovalManager"),
    "ApprovalOption": (".approval_manager", "ApprovalOption"),
    "ApprovalRequest": (".approval_manager", "ApprovalRequest"),
    "ApprovalResult": (".approval_manager", "ApprovalResult"),
}


def __getattr__(name: str):
    """Lazy import to avoid heavy initialization on package import."""
    if entry := _LAZY_IMPORTS.get(name):
        from importlib import import_module

        module = import_module(entry[0], __name__)
        return getattr(module, entry[1])
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _ensure_default_event_loop() -> None:
    """Create a default event loop for legacy sync tests on Python 3.13+."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


_ensure_default_event_loop()

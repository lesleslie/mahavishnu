"""Mahavishnu core module."""

from .app import MahavishnuApp
from .approval_manager import (
    ApprovalManager,
    ApprovalOption,
    ApprovalRequest,
    ApprovalResult,
)
from .config import MahavishnuSettings
from .cost_optimizer import CostOptimizer
from .errors import (
    # New error classes for Phase 0
    AdapterError,
    AuthenticationError,
    AuthorizationError,
    ConfigurationError,
    DatabaseError,
    ErrorCode,
    ExternalServiceError,
    MahavishnuError,
    RateLimitError,
    RepositoryNotFoundError,
    TaskNotFoundError,
    TimeoutError,
    ValidationError,
    WebhookAuthError,
    WorkflowError,
)
from .fix_orchestrator import (
    FixOrchestrator,
    FixResult,
    FixTask,
    QualityGateResult,
)
from .metrics_collector import ExecutionTracker, get_execution_tracker
from .metrics_schema import (
    AdapterType,
    ExecutionStatus,
    TaskType,
)
from .repo_manager import RepositoryManager
from .repo_models import Repository, RepositoryManifest, RepositoryMetadata
from .routing_alerts import (
    Alert,
    AlertHandler,
    AlertSeverity,
    AlertType,
    LoggingAlertHandler,
    RoutingAlertManager,
    get_alert_manager,
)
from .routing_metrics import RoutingMetrics, get_routing_metrics
from .statistical_router import StatisticalRouter
from .task_router import TaskRouter

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
]

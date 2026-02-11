"""Real-time monitoring demonstrations for Mahavishnu.

This package provides interactive terminal demos showcasing Mahavishnu's
WebSocket infrastructure for real-time orchestration monitoring.

Available demos:
- pool_monitor: Monitor pool status, workers, and tasks
- workflow_monitor: Monitor workflow execution progress
- multi_service_dashboard: Unified dashboard for all services

Example usage:
    >>> python -m realtime_monitoring.pool_monitor --pool-id pool_local
    >>> python -m realtime_monitoring.workflow_monitor --workflow-id wf_123
    >>> python -m realtime_monitoring.multi_service_dashboard
"""

__version__ = "0.1.0"

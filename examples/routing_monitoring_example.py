"""Example demonstrating adaptive routing with monitoring and alerting.

Shows how to:
- Track routing metrics with Prometheus
- Monitor adapter health with alerting
- Set up Grafana dashboard visualization
- Handle cost spikes and adapter degradation

Usage:
    python examples/routing_monitoring_example.py
"""

import asyncio
import logging

from mahavishnu.core import (
    AdapterManager,
    CostOptimizer,
    StateManager,
    StatisticalRouter,
    TaskRouter,
)
from mahavishnu.core.metrics_schema import AdapterType, TaskType
from mahavishnu.core.routing_alerts import (
    LoggingAlertHandler,
    RoutingAlertManager,
)
from mahavishnu.core.routing_metrics import get_routing_metrics

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def setup_routing_with_monitoring():
    """Set up complete routing system with monitoring and alerting.

    Architecture:
        User Request
            ↓
        TaskRouter (coordinates adapters)
            ↓
        StatisticalRouter (selects adapter)
            ↓
        AdapterManager (executes with fallback)
            ↓
        CostOptimizer (optimizes for cost)
            ↓
        RoutingMetrics (Prometheus export)
            ↓
        RoutingAlertManager (monitors health)
    """
    logger.info("Setting up adaptive routing with monitoring...")

    # 1. Initialize metrics collection
    metrics = get_routing_metrics()
    logger.info(f"Metrics initialized: {metrics.get_metrics_summary()}")

    # 2. Set up alert handlers
    # Using logging handler (add WebhookAlertHandler for production)
    alert_handlers = [
        LoggingAlertHandler(),
        # WebhookAlertHandler(webhook_url="https://hooks.slack.com/YOUR/WEBHOOK"),
    ]

    # 3. Initialize alert manager with thresholds
    alert_manager = RoutingAlertManager(
        success_rate_threshold=0.95,  # Alert if success rate < 95%
        fallback_rate_threshold=0.1,  # Alert if fallbacks > 10%
        latency_p95_threshold_ms=5000,  # Alert if p95 latency > 5s
        cost_spike_multiplier=2.0,  # Alert if cost 2x normal
        evaluation_interval_seconds=60,  # Check every minute
        handlers=alert_handlers,
    )
    await alert_manager.start()
    logger.info(f"Alert manager started: {alert_manager.get_status()}")

    # 4. Initialize core routing components
    adapter_manager = AdapterManager()
    state_manager = StateManager()

    # 5. Create statistical router with metrics integration
    router = StatisticalRouter(
        adapter_manager=adapter_manager,
        state_manager=state_manager,
    )

    # 6. Create cost optimizer
    cost_optimizer = CostOptimizer()

    # 7. Create task router with all components
    task_router = TaskRouter(
        adapter_manager=adapter_manager,
        state_manager=state_manager,
        statistical_router=router,
        cost_optimizer=cost_optimizer,
    )

    logger.info("Routing components initialized")

    return task_router, metrics, alert_manager


async def simulate_routing_operations(
    task_router: TaskRouter,
    metrics,
    alert_manager,
):
    """Simulate routing operations to demonstrate monitoring.

    Generates:
    - Normal routing decisions
    - Adapter failures with fallback
    - Cost tracking
    - Alert conditions
    """
    logger.info("=" * 60)
    logger.info("SIMULATING ROUTING OPERATIONS")
    logger.info("=" * 60)

    # Simulate 1: Normal routing to LlamaIndex
    logger.info("\n1. Normal routing decision (WORKFLOW → LlamaIndex)")
    task_spec = {
        "task_type": TaskType.WORKFLOW,
        "prompt": "Analyze sales data",
        "repos": ["/path/to/repo"],
    }

    # Record routing decision in metrics
    metrics.record_routing_decision(
        adapter=AdapterType.LLAMAINDEX,
        task_type=TaskType.WORKFLOW,
        preference_order=1,
    )

    # Simulate execution
    metrics.record_adapter_execution(
        adapter=AdapterType.LLAMAINDEX,
        success=True,
        latency_ms=234,
    )

    # Record cost
    metrics.record_cost(
        adapter=AdapterType.LLAMAINDEX,
        task_type=TaskType.WORKFLOW,
        cost_usd=0.015,
    )

    logger.info("   ✓ Routed to LlamaIndex (success, 234ms, $0.015)")
    await asyncio.sleep(0.5)

    # Simulate 2: Adapter degradation (Prefect failures)
    logger.info("\n2. Simulating adapter degradation (Prefect failures)")
    for i in range(3):
        # Record failed attempts
        metrics.record_routing_decision(
            adapter=AdapterType.PREFECT,
            task_type=TaskType.AI_TASK,
            preference_order=1,
        )
        metrics.record_adapter_execution(
            adapter=AdapterType.PREFECT,
            success=False,
            latency_ms=1000 + (i * 500),
        )
        metrics.record_fallback(
            original_adapter=AdapterType.PREFECT,
            fallback_adapter=AdapterType.AGNO,
        )
        logger.info(f"   ✗ Attempt {i + 1}: Prefect failed (fallback to Agno)")
        await asyncio.sleep(0.3)

    # Record successful fallback to Agno
    metrics.record_routing_decision(
        adapter=AdapterType.AGNO,
        task_type=TaskType.AI_TASK,
        preference_order=2,
    )
    metrics.record_adapter_execution(
        adapter=AdapterType.AGNO,
        success=True,
        latency_ms=850,
    )
    metrics.record_fallback_chain_length(chain_length=4)

    logger.info("   ✓ Agno succeeded after 3 Prefect failures")
    logger.warning("   ⚠ This would trigger ADAPTER_DEGRADATION alert!")

    await asyncio.sleep(0.5)

    # Simulate 3: Cost spike
    logger.info("\n3. Simulating cost spike detection")
    metrics.set_current_cost("daily", 10.0)
    logger.info("   Current daily cost: $10.00")

    await asyncio.sleep(0.5)

    metrics.set_current_cost("daily", 25.0)
    logger.info("   Current daily cost: $25.00")
    logger.warning("   ⚠ 150% increase - would trigger COST_SPIKE alert!")

    await asyncio.sleep(0.5)

    # Simulate 4: Budget exceeded
    logger.info("\n4. Simulating budget exceeded")
    metrics.trigger_budget_alert("daily", "critical")
    logger.critical("   ⛔ Daily budget $50 exceeded - would trigger BUDGET_EXCEEDED alert!")

    await asyncio.sleep(0.5)

    # Simulate 5: Excessive fallbacks
    logger.info("\n5. Simulating excessive fallbacks")
    for i in range(15):
        metrics.record_routing_decision(
            adapter=AdapterType.PREFECT,
            task_type=TaskType.RAG_QUERY,
            preference_order=1,
        )
        metrics.record_adapter_execution(
            adapter=AdapterType.PREFECT,
            success=False,
            latency_ms=500,
        )
        metrics.record_fallback(
            original_adapter=AdapterType.PREFECT,
            fallback_adapter=AdapterType.LLAMAINDEX,
        )
    logger.info(f"   Fallback {i + 1}/15: Prefect → LlamaIndex")
    await asyncio.sleep(0.1)

    logger.warning("   ⚠ 100% fallback rate - would trigger EXCESSIVE_FALLBACKS alert!")

    logger.info("\n" + "=" * 60)
    logger.info("SIMULATION COMPLETE")
    logger.info("=" * 60)

    # Display metrics summary
    logger.info("\n📊 ROUTING METRICS SUMMARY")
    logger.info("-" * 40)
    summary = metrics.get_metrics_summary()
    for key, value in summary.items():
        logger.info(f"   {key}: {value}")

    # Display alert manager status
    logger.info("\n🚨 ALERT MANAGER STATUS")
    logger.info("-" * 40)
    alert_status = alert_manager.get_status()
    for key, value in alert_status.items():
        logger.info(f"   {key}: {value}")


async def main():
    """Main example entry point."""
    logger.info("Starting Adaptive Routing Monitoring Example")
    logger.info("This demonstrates:")
    logger.info("  - Routing metrics collection (Prometheus)")
    logger.info("  - Adapter health monitoring")
    logger.info("  - Cost anomaly detection")
    logger.info("  - Alert generation and delivery")

    # Setup routing with monitoring
    task_router, metrics, alert_manager = await setup_routing_with_monitoring()

    # Option 1: Start Prometheus metrics server
    logger.info("\n📡 To start Prometheus metrics server:")
    logger.info("   python -m mahavishnu.core.routing_metrics")
    logger.info("   Metrics available at: http://localhost:9091")

    # Option 2: Import dashboard to Grafana
    logger.info("\n📊 To import Grafana dashboard:")
    logger.info("   1. Open Grafana: http://localhost:3000")
    logger.info("   2. Go to Dashboards → Import")
    logger.info("   3. Upload: docs/grafana/Routing_Monitoring.json")
    logger.info("   4. Select Prometheus datasource: http://localhost:9091")

    # Simulate routing operations
    await simulate_routing_operations(task_router, metrics, alert_manager)

    # Cleanup
    logger.info("\nStopping alert manager...")
    await alert_manager.stop()

    logger.info("\n✅ Example complete!")
    logger.info("\nNext steps:")
    logger.info("  1. Start metrics server: python -m mahavishnu.core.routing_metrics")
    logger.info("  2. Configure Prometheus in grafana.ini:")
    logger.info("     [scrape_configs]")
    logger.info("     job_name = 'mahavishnu_routing'")
    logger.info("     static_configs = [")
    logger.info("       { targets = ['localhost:9091'] }")
    logger.info("  3. Restart Grafana: sudo systemctl restart grafana-server")


if __name__ == "__main__":
    asyncio.run(main())

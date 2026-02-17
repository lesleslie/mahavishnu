#!/usr/bin/env python3
"""
Agent Performance Metrics Tracking System

Tracks agent invocations, success rates, token usage, and user satisfaction
to enable data-driven optimization of the agent ecosystem.

Usage:
    uv run agent_metrics_system.py log <agent_name> <task> <result>
    uv run agent_metrics_system.py report [--agent <name>] [--days <n>]
    uv run agent_metrics_system.py optimize
"""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, Optional
from dataclasses import dataclass, asdict
from collections import defaultdict
import click


@dataclass
class AgentMetric:
    """Single agent invocation metric"""
    agent_name: str
    task_type: str
    timestamp: datetime
    tokens_used: int
    success: bool
    execution_time_ms: float
    user_feedback: Optional[Literal["positive", "neutral", "negative"]] = None
    error_type: Optional[str] = None
    context_size: Optional[int] = None


class AgentMetricsDB:
    """SQLite-based agent metrics storage"""

    def __init__(self, db_path: Path = Path.home() / ".claude" / "agent_metrics.db"):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_name TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    tokens_used INTEGER NOT NULL,
                    success BOOLEAN NOT NULL,
                    execution_time_ms REAL NOT NULL,
                    user_feedback TEXT,
                    error_type TEXT,
                    context_size INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_agent_name
                ON agent_metrics(agent_name)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp
                ON agent_metrics(timestamp)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_success
                ON agent_metrics(success)
            """)

    def log_metric(self, metric: AgentMetric) -> None:
        """Log a single agent metric"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO agent_metrics (
                    agent_name, task_type, timestamp, tokens_used,
                    success, execution_time_ms, user_feedback,
                    error_type, context_size
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                metric.agent_name,
                metric.task_type,
                metric.timestamp.isoformat(),
                metric.tokens_used,
                metric.success,
                metric.execution_time_ms,
                metric.user_feedback,
                metric.error_type,
                metric.context_size
            ))

    def get_metrics(
        self,
        agent_name: Optional[str] = None,
        days: int = 30
    ) -> list[dict]:
        """Retrieve metrics with optional filtering"""
        cutoff = datetime.now() - timedelta(days=days)

        query = """
            SELECT * FROM agent_metrics
            WHERE timestamp >= ?
        """
        params = [cutoff.isoformat()]

        if agent_name:
            query += " AND agent_name = ?"
            params.append(agent_name)

        query += " ORDER BY timestamp DESC"

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]


class AgentAnalyzer:
    """Analyze agent performance and generate insights"""

    def __init__(self, db: AgentMetricsDB):
        self.db = db

    def generate_report(
        self,
        agent_name: Optional[str] = None,
        days: int = 30
    ) -> dict:
        """Generate comprehensive performance report"""
        metrics = self.db.get_metrics(agent_name, days)

        if not metrics:
            return {"error": "No metrics found for the specified period"}

        # Aggregate by agent
        by_agent = defaultdict(lambda: {
            "invocations": 0,
            "successes": 0,
            "failures": 0,
            "total_tokens": 0,
            "total_time_ms": 0,
            "positive_feedback": 0,
            "negative_feedback": 0,
            "errors": defaultdict(int),
            "task_types": defaultdict(int)
        })

        for metric in metrics:
            agent = metric["agent_name"]
            stats = by_agent[agent]

            stats["invocations"] += 1
            stats["total_tokens"] += metric["tokens_used"]
            stats["total_time_ms"] += metric["execution_time_ms"]

            if metric["success"]:
                stats["successes"] += 1
            else:
                stats["failures"] += 1
                if metric["error_type"]:
                    stats["errors"][metric["error_type"]] += 1

            if metric["user_feedback"] == "positive":
                stats["positive_feedback"] += 1
            elif metric["user_feedback"] == "negative":
                stats["negative_feedback"] += 1

            stats["task_types"][metric["task_type"]] += 1

        # Calculate derived metrics
        report = {}
        for agent, stats in by_agent.items():
            invocations = stats["invocations"]

            report[agent] = {
                "invocations": invocations,
                "success_rate": stats["successes"] / invocations if invocations > 0 else 0,
                "avg_tokens": stats["total_tokens"] / invocations if invocations > 0 else 0,
                "avg_time_ms": stats["total_time_ms"] / invocations if invocations > 0 else 0,
                "satisfaction_rate": (
                    stats["positive_feedback"] /
                    (stats["positive_feedback"] + stats["negative_feedback"])
                    if (stats["positive_feedback"] + stats["negative_feedback"]) > 0
                    else None
                ),
                "top_errors": dict(sorted(
                    stats["errors"].items(),
                    key=lambda x: x[1],
                    reverse=True
                )[:5]),
                "top_tasks": dict(sorted(
                    stats["task_types"].items(),
                    key=lambda x: x[1],
                    reverse=True
                )[:5])
            }

        return {
            "period_days": days,
            "total_invocations": len(metrics),
            "agents": report,
            "generated_at": datetime.now().isoformat()
        }

    def identify_optimization_opportunities(self, days: int = 30) -> dict:
        """Identify agents that need optimization"""
        report = self.generate_report(days=days)

        if "error" in report:
            return report

        opportunities = {
            "underutilized": [],
            "low_success_rate": [],
            "high_token_usage": [],
            "low_satisfaction": [],
            "recommendations": []
        }

        agents = report["agents"]
        total_invocations = report["total_invocations"]
        avg_invocations = total_invocations / len(agents) if agents else 0

        for agent_name, stats in agents.items():
            # Underutilized agents
            if stats["invocations"] < avg_invocations * 0.25:
                opportunities["underutilized"].append({
                    "agent": agent_name,
                    "invocations": stats["invocations"],
                    "issue": "Low usage - may need better triggers or documentation"
                })

            # Low success rate
            if stats["success_rate"] < 0.8 and stats["invocations"] > 5:
                opportunities["low_success_rate"].append({
                    "agent": agent_name,
                    "success_rate": stats["success_rate"],
                    "invocations": stats["invocations"],
                    "top_errors": stats["top_errors"],
                    "issue": "High failure rate - needs investigation"
                })

            # High token usage
            if stats["avg_tokens"] > 50000:
                opportunities["high_token_usage"].append({
                    "agent": agent_name,
                    "avg_tokens": stats["avg_tokens"],
                    "issue": "Consider optimizing prompts or context"
                })

            # Low satisfaction
            if stats["satisfaction_rate"] and stats["satisfaction_rate"] < 0.6:
                opportunities["low_satisfaction"].append({
                    "agent": agent_name,
                    "satisfaction_rate": stats["satisfaction_rate"],
                    "issue": "User dissatisfaction - review agent instructions"
                })

        # Generate recommendations
        if opportunities["low_success_rate"]:
            opportunities["recommendations"].append(
                "Review agents with low success rates for instruction clarity"
            )

        if opportunities["underutilized"]:
            opportunities["recommendations"].append(
                "Add proactive triggers to underutilized agents"
            )

        if opportunities["high_token_usage"]:
            opportunities["recommendations"].append(
                "Optimize prompts for agents with high token usage"
            )

        return opportunities


@click.group()
def cli():
    """Agent Performance Metrics CLI"""
    pass


@cli.command()
@click.argument("agent_name")
@click.argument("task")
@click.option("--tokens", type=int, required=True)
@click.option("--success/--failure", default=True)
@click.option("--time-ms", type=float, required=True)
@click.option("--feedback", type=click.Choice(["positive", "neutral", "negative"]))
@click.option("--error-type", type=str)
def log(agent_name: str, task: str, tokens: int, success: bool,
        time_ms: float, feedback: Optional[str], error_type: Optional[str]):
    """Log an agent metric"""
    db = AgentMetricsDB()

    metric = AgentMetric(
        agent_name=agent_name,
        task_type=task,
        timestamp=datetime.now(),
        tokens_used=tokens,
        success=success,
        execution_time_ms=time_ms,
        user_feedback=feedback,
        error_type=error_type
    )

    db.log_metric(metric)
    click.echo(f"✓ Logged metric for {agent_name}")


@cli.command()
@click.option("--agent", type=str, help="Filter by agent name")
@click.option("--days", type=int, default=30, help="Days to analyze")
@click.option("--format", type=click.Choice(["json", "text"]), default="text")
def report(agent: Optional[str], days: int, format: str):
    """Generate performance report"""
    db = AgentMetricsDB()
    analyzer = AgentAnalyzer(db)

    result = analyzer.generate_report(agent, days)

    if format == "json":
        click.echo(json.dumps(result, indent=2))
    else:
        _print_text_report(result)


@cli.command()
@click.option("--days", type=int, default=30, help="Days to analyze")
def optimize(days: int):
    """Identify optimization opportunities"""
    db = AgentMetricsDB()
    analyzer = AgentAnalyzer(db)

    opportunities = analyzer.identify_optimization_opportunities(days)

    click.echo("\n=== Agent Optimization Opportunities ===\n")

    if opportunities.get("underutilized"):
        click.echo("⚠️  Underutilized Agents:")
        for item in opportunities["underutilized"]:
            click.echo(f"  - {item['agent']}: {item['invocations']} invocations")
            click.echo(f"    {item['issue']}\n")

    if opportunities.get("low_success_rate"):
        click.echo("❌ Low Success Rate:")
        for item in opportunities["low_success_rate"]:
            click.echo(f"  - {item['agent']}: {item['success_rate']:.1%} success")
            if item['top_errors']:
                click.echo(f"    Top errors: {list(item['top_errors'].keys())}\n")

    if opportunities.get("high_token_usage"):
        click.echo("💰 High Token Usage:")
        for item in opportunities["high_token_usage"]:
            click.echo(f"  - {item['agent']}: {item['avg_tokens']:.0f} avg tokens")
            click.echo(f"    {item['issue']}\n")

    if opportunities.get("low_satisfaction"):
        click.echo("😞 Low User Satisfaction:")
        for item in opportunities["low_satisfaction"]:
            click.echo(f"  - {item['agent']}: {item['satisfaction_rate']:.1%} satisfaction\n")

    if opportunities.get("recommendations"):
        click.echo("\n📋 Recommendations:")
        for rec in opportunities["recommendations"]:
            click.echo(f"  • {rec}")


def _print_text_report(report: dict):
    """Print report in human-readable format"""
    click.echo(f"\n=== Agent Performance Report ({report['period_days']} days) ===\n")
    click.echo(f"Total Invocations: {report['total_invocations']}\n")

    agents = sorted(
        report["agents"].items(),
        key=lambda x: x[1]["invocations"],
        reverse=True
    )

    for agent_name, stats in agents:
        click.echo(f"Agent: {agent_name}")
        click.echo(f"  Invocations: {stats['invocations']}")
        click.echo(f"  Success Rate: {stats['success_rate']:.1%}")
        click.echo(f"  Avg Tokens: {stats['avg_tokens']:.0f}")
        click.echo(f"  Avg Time: {stats['avg_time_ms']:.0f}ms")

        if stats['satisfaction_rate'] is not None:
            click.echo(f"  Satisfaction: {stats['satisfaction_rate']:.1%}")

        if stats['top_tasks']:
            click.echo(f"  Top Tasks: {', '.join(stats['top_tasks'].keys())}")

        if stats['top_errors']:
            click.echo(f"  Top Errors: {', '.join(stats['top_errors'].keys())}")

        click.echo()


if __name__ == "__main__":
    cli()

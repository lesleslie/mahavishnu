#!/usr/bin/env python3
"""
Automatic Agent Usage Metrics Tracker

Parses Claude Code session transcripts to automatically track:
- Agent invocation counts
- Token usage per agent
- Success/failure patterns
- Task types and patterns
- Cost analysis per agent

Usage:
    python3 auto_agent_metrics.py parse <transcript_path>
    python3 auto_agent_metrics.py report [--agent <name>] [--days <n>]
    python3 auto_agent_metrics.py top [--limit <n>]
    python3 auto_agent_metrics.py cost-analysis

Architecture:
- No external dependencies (stdlib only)
- JSON-based storage for portability
- Automatic extraction from transcript files
- Cost calculations based on model pricing

Author: python-pro specialist
Date: 2025-10-26
Version: 1.0
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from collections import defaultdict
from dataclasses import dataclass, asdict


# Model pricing per 1M tokens (input/output average)
MODEL_COSTS = {
    'opus': 15.0,
    'sonnet': 3.0,
    'haiku-4.5': 0.25,
    'haiku': 0.50,
}


@dataclass
class AgentInvocation:
    """Single agent invocation record"""
    agent_name: str
    timestamp: datetime
    task_description: str
    tokens_input: int
    tokens_output: int
    model: str
    success: bool = True
    error_message: Optional[str] = None

    @property
    def total_tokens(self) -> int:
        return self.tokens_input + self.tokens_output

    @property
    def estimated_cost(self) -> float:
        """Estimated cost in dollars"""
        cost_per_m = MODEL_COSTS.get(self.model, 3.0)
        return (self.total_tokens / 1_000_000) * cost_per_m


class AgentMetricsStore:
    """JSON-based metrics storage"""

    def __init__(self, store_path: Path = Path.home() / ".claude" / "agent_metrics.json"):
        self.store_path = store_path
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.metrics = self._load()

    def _load(self) -> List[dict]:
        """Load existing metrics"""
        if self.store_path.exists():
            try:
                with open(self.store_path, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                return []
        return []

    def save(self) -> None:
        """Save metrics to disk"""
        with open(self.store_path, 'w') as f:
            json.dump(self.metrics, f, indent=2, default=str)

    def add_invocation(self, invocation: AgentInvocation) -> None:
        """Add a new invocation record"""
        record = asdict(invocation)
        record['timestamp'] = invocation.timestamp.isoformat()
        self.metrics.append(record)

    def get_metrics(
        self,
        agent_name: Optional[str] = None,
        days: Optional[int] = None
    ) -> List[dict]:
        """Get filtered metrics"""
        filtered = self.metrics

        if days is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            filtered = [
                m for m in filtered
                if datetime.fromisoformat(m['timestamp']) >= cutoff
            ]

        if agent_name:
            filtered = [m for m in filtered if m['agent_name'] == agent_name]

        return filtered


class TranscriptParser:
    """Parse agent invocations from transcript files"""

    def __init__(self, agents_dir: Path = Path.home() / ".claude" / "agents"):
        self.agents_dir = agents_dir
        self.agent_models = self._load_agent_models()

    def _load_agent_models(self) -> Dict[str, str]:
        """Load agent->model mapping from agent files"""
        mapping = {}
        for agent_file in self.agents_dir.glob("*.md"):
            try:
                with open(agent_file, 'r') as f:
                    content = f.read()
                    # Extract name and model from frontmatter
                    name_match = None
                    model_match = None
                    for line in content.split('\n'):
                        if line.startswith('name:'):
                            name_match = line.split('name:')[1].strip()
                        if line.startswith('model:'):
                            model_match = line.split('model:')[1].strip()

                    if name_match and model_match:
                        mapping[name_match] = model_match
            except Exception:
                continue

        return mapping

    def parse_transcript(self, transcript_path: Path) -> List[AgentInvocation]:
        """Extract agent invocations from a transcript file"""
        invocations = []

        try:
            with open(transcript_path, 'r') as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        invocations.extend(self._extract_agent_calls(entry))
                    except json.JSONDecodeError:
                        continue
        except FileNotFoundError:
            print(f"Error: Transcript not found: {transcript_path}", file=sys.stderr)
            return []

        return invocations

    def _extract_agent_calls(self, entry: dict) -> List[AgentInvocation]:
        """Extract agent Task tool calls from a transcript entry"""
        invocations = []

        message = entry.get('message', {})
        timestamp_str = entry.get('timestamp')
        if not timestamp_str:
            return []

        timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))

        # Check for Task tool usage in content
        content = message.get('content', [])
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get('type') == 'tool_use':
                    if block.get('name') == 'Task':
                        input_data = block.get('input', {})
                        agent_name = input_data.get('subagent_type', 'unknown')
                        task_desc = input_data.get('description', 'No description')

                        # Get token usage
                        usage = message.get('usage', {})
                        tokens_in = usage.get('input_tokens', 0) or 0
                        tokens_out = usage.get('output_tokens', 0) or 0

                        # Get model from agent mapping
                        model = self.agent_models.get(agent_name, 'sonnet')

                        invocations.append(AgentInvocation(
                            agent_name=agent_name,
                            timestamp=timestamp,
                            task_description=task_desc,
                            tokens_input=tokens_in,
                            tokens_output=tokens_out,
                            model=model
                        ))

        return invocations


class MetricsAnalyzer:
    """Analyze agent usage patterns and generate reports"""

    def __init__(self, store: AgentMetricsStore):
        self.store = store

    def generate_summary(self, days: int = 30) -> dict:
        """Generate comprehensive usage summary"""
        metrics = self.store.get_metrics(days=days)

        if not metrics:
            return {
                'error': f'No metrics found for the last {days} days',
                'suggestion': 'Run: python3 auto_agent_metrics.py parse <transcript_path>'
            }

        # Aggregate by agent
        by_agent = defaultdict(lambda: {
            'invocations': 0,
            'total_tokens': 0,
            'total_cost': 0.0,
            'tasks': [],
            'first_used': None,
            'last_used': None,
        })

        total_tokens = 0
        total_cost = 0.0

        for m in metrics:
            agent = m['agent_name']
            stats = by_agent[agent]

            stats['invocations'] += 1
            stats['total_tokens'] += m['tokens_input'] + m['tokens_output']

            # Calculate cost
            model = m.get('model', 'sonnet')
            cost_per_m = MODEL_COSTS.get(model, 3.0)
            cost = ((m['tokens_input'] + m['tokens_output']) / 1_000_000) * cost_per_m
            stats['total_cost'] += cost
            total_cost += cost

            total_tokens += m['tokens_input'] + m['tokens_output']

            # Track task descriptions
            if m['task_description'] not in stats['tasks']:
                stats['tasks'].append(m['task_description'])

            # Track usage dates
            ts = datetime.fromisoformat(m['timestamp'])
            if stats['first_used'] is None or ts < stats['first_used']:
                stats['first_used'] = ts
            if stats['last_used'] is None or ts > stats['last_used']:
                stats['last_used'] = ts

        # Convert to serializable format
        agent_stats = {}
        for agent, stats in by_agent.items():
            agent_stats[agent] = {
                'invocations': stats['invocations'],
                'total_tokens': stats['total_tokens'],
                'avg_tokens_per_invocation': stats['total_tokens'] / stats['invocations'],
                'total_cost_usd': round(stats['total_cost'], 4),
                'avg_cost_per_invocation': round(stats['total_cost'] / stats['invocations'], 4),
                'unique_tasks': len(stats['tasks']),
                'first_used': stats['first_used'].isoformat() if stats['first_used'] else None,
                'last_used': stats['last_used'].isoformat() if stats['last_used'] else None,
            }

        return {
            'period_days': days,
            'total_invocations': len(metrics),
            'total_tokens': total_tokens,
            'total_cost_usd': round(total_cost, 2),
            'unique_agents': len(by_agent),
            'agents': agent_stats,
            'generated_at': datetime.now(timezone.utc).isoformat()
        }

    def get_top_agents(self, limit: int = 10, metric: str = 'invocations') -> List[tuple]:
        """Get top N agents by specified metric"""
        summary = self.generate_summary(days=30)

        if 'error' in summary:
            return []

        agents = summary['agents']
        sorted_agents = sorted(
            agents.items(),
            key=lambda x: x[1].get(metric, 0),
            reverse=True
        )

        return sorted_agents[:limit]

    def cost_breakdown(self) -> dict:
        """Analyze costs by agent and model"""
        metrics = self.store.get_metrics(days=30)

        by_agent = defaultdict(float)
        by_model = defaultdict(float)

        for m in metrics:
            model = m.get('model', 'sonnet')
            cost_per_m = MODEL_COSTS.get(model, 3.0)
            cost = ((m['tokens_input'] + m['tokens_output']) / 1_000_000) * cost_per_m

            by_agent[m['agent_name']] += cost
            by_model[model] += cost

        return {
            'by_agent': dict(sorted(by_agent.items(), key=lambda x: x[1], reverse=True)),
            'by_model': dict(sorted(by_model.items(), key=lambda x: x[1], reverse=True)),
            'total_cost_usd': round(sum(by_agent.values()), 2)
        }


def print_report(summary: dict) -> None:
    """Print human-readable report"""
    if 'error' in summary:
        print(f"\n❌ {summary['error']}")
        if 'suggestion' in summary:
            print(f"💡 {summary['suggestion']}\n")
        return

    print(f"\n{'='*70}")
    print(f"Agent Usage Report - Last {summary['period_days']} Days")
    print(f"{'='*70}\n")

    print(f"📊 Summary:")
    print(f"  Total Invocations: {summary['total_invocations']}")
    print(f"  Unique Agents Used: {summary['unique_agents']}")
    print(f"  Total Tokens: {summary['total_tokens']:,}")
    print(f"  Estimated Cost: ${summary['total_cost_usd']:.2f}\n")

    print(f"{'─'*70}")
    print(f"Top Agents by Usage:\n")

    # Sort by invocations
    sorted_agents = sorted(
        summary['agents'].items(),
        key=lambda x: x[1]['invocations'],
        reverse=True
    )

    for i, (agent, stats) in enumerate(sorted_agents[:15], 1):
        print(f"{i:2}. {agent}")
        print(f"    Invocations: {stats['invocations']}")
        print(f"    Avg Tokens: {stats['avg_tokens_per_invocation']:,.0f}")
        print(f"    Total Cost: ${stats['total_cost_usd']:.4f}")
        print(f"    Unique Tasks: {stats['unique_tasks']}")
        print()


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  auto_agent_metrics.py parse <transcript_path>")
        print("  auto_agent_metrics.py report [--agent <name>] [--days <n>]")
        print("  auto_agent_metrics.py top [--limit <n>]")
        print("  auto_agent_metrics.py cost-analysis")
        sys.exit(1)

    command = sys.argv[1]
    store = AgentMetricsStore()

    if command == 'parse':
        if len(sys.argv) < 3:
            print("Error: parse requires transcript path")
            sys.exit(1)

        transcript_path = Path(sys.argv[2])
        parser = TranscriptParser()

        print(f"Parsing transcript: {transcript_path}")
        invocations = parser.parse_transcript(transcript_path)

        print(f"Found {len(invocations)} agent invocations")

        for inv in invocations:
            store.add_invocation(inv)
            print(f"  - {inv.agent_name}: {inv.task_description[:50]}...")

        store.save()
        print(f"\n✓ Saved to {store.store_path}")

    elif command == 'report':
        days = 30
        agent_name = None

        # Parse optional arguments
        i = 2
        while i < len(sys.argv):
            if sys.argv[i] == '--days' and i + 1 < len(sys.argv):
                days = int(sys.argv[i + 1])
                i += 2
            elif sys.argv[i] == '--agent' and i + 1 < len(sys.argv):
                agent_name = sys.argv[i + 1]
                i += 2
            else:
                i += 1

        analyzer = MetricsAnalyzer(store)

        if agent_name:
            metrics = store.get_metrics(agent_name=agent_name, days=days)
            print(f"\n{agent_name} - {len(metrics)} invocations in last {days} days")
            for m in metrics[:10]:
                ts = datetime.fromisoformat(m['timestamp'])
                print(f"  {ts.strftime('%Y-%m-%d %H:%M')}: {m['task_description'][:60]}")
        else:
            summary = analyzer.generate_summary(days=days)
            print_report(summary)

    elif command == 'top':
        limit = 10
        if '--limit' in sys.argv:
            idx = sys.argv.index('--limit')
            if idx + 1 < len(sys.argv):
                limit = int(sys.argv[idx + 1])

        analyzer = MetricsAnalyzer(store)
        top_agents = analyzer.get_top_agents(limit=limit)

        print(f"\n🏆 Top {limit} Agents by Invocations:\n")
        for i, (agent, stats) in enumerate(top_agents, 1):
            print(f"{i:2}. {agent}: {stats['invocations']} invocations, ${stats['total_cost_usd']:.4f}")

    elif command == 'cost-analysis':
        analyzer = MetricsAnalyzer(store)
        breakdown = analyzer.cost_breakdown()

        print(f"\n💰 Cost Analysis:\n")
        print(f"Total Cost: ${breakdown['total_cost_usd']:.2f}\n")

        print("By Model:")
        for model, cost in breakdown['by_model'].items():
            print(f"  {model}: ${cost:.2f}")

        print("\nTop 10 by Cost:")
        for i, (agent, cost) in enumerate(list(breakdown['by_agent'].items())[:10], 1):
            print(f"  {i:2}. {agent}: ${cost:.4f}")

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()

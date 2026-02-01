# Cross-Repository Metrics Tracking Proposal

**Date:** 2026-02-01
**Status:** Proposed

## Current State

### What Exists (Fragmented)

Each repository has its own:
- ✅ Unit tests (pytest)
- ✅ Coverage files (.coverage, coverage.xml)
- ✅ Coverage reports (pytest-cov)
- ✅ Quality checks (ruff, mypy, bandit)

**But NO central aggregation across all 24 repos!**

### What's Missing

1. **Unified coverage dashboard** - See all repos at once
2. **Quality score tracking** - Track trends over time
3. **Cross-repo quality gates** - Enforce standards
4. **Metrics history** - Track improvements/degradations
5. **Automated alerts** - Notify when quality drops

## Proposed Solution

### Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                  Cross-Repository Quality Tracking                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌──────────────────────┐    ┌──────────────────────────────────┐  │
│  │ Metrics Collector     │───→│  Coordination System             │  │
│  │ (Python script)       │    │  (Issues, Plans, Todos)         │  │
│  └──────────────────────┘    │                                  │  │
│           ↓                     └──────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                    Central Metrics Database                       │ │
│  │  • Coverage per repo (history)                              │ │
│  │  • Test pass/fail rates                                       │ │
│  │  • Quality scores (ruff, mypy, bandit)                         │ │
│  │  • Trends over time                                            │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                    Dashboard (Future)                          │ │
│  │  • Unified coverage view                                       │ │
│  │  • Quality trends charts                                       │
│  │  • Repo comparison                                            │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘
```

### Implementation Plan

#### Option 1: Use Coordination System (Recommended)

**Why:** We just built this! It's perfect for tracking cross-repo issues.

**Approach:**
1. Create quality issues in coordination system
2. Track metrics as todos/dependencies
3. Use memory integration for trends
4. Execute sweeps via pools

**Example Usage:**
```bash
# Create quality issue for low coverage
mahavishnu coord create-issue \
  --title "Fastblocks coverage below 80%" \
  --description "Current coverage: 65%. Need to add tests." \
  --repos "fastblocks" \
  --priority high \
  --severity quality

# Create todos to fix
mahavishnu coord create-todo \
  --task "Add tests for fastbulma components" \
  --repo fastblocks \
  --estimate 16 \
  --blocked-by ISSUE-Q-001

# Track quality via plans
mahavishnu coord create-plan \
  --title "Q1 2026 Quality Improvement" \
  --repos "mahavishnu,crackerjack,session-buddy" \
  --milestones "all_repos_80_coverage:2026-02-28"
```

#### Option 2: Metrics Collector Script

**File:** `mahavishnu/scripts/collect_metrics.py`

**What it does:**
- Scans all repos in repos.yaml
- Collects .coverage, coverage.xml files
- Runs `pytest --cov` if needed
- Aggregates results
- Creates coordination issues for low-quality repos

**Usage:**
```bash
# Collect all metrics
python scripts/collect_metrics.py

# Generate report
python scripts/collect_metrics.py --report

# Create issues for repos below threshold
python scripts/collect_metrics.py --create-issues --min-coverage 80
```

#### Option 3: Crackerjack Enhancement

**File:** `crackerjack/aggregate.py`

**Enhance Crackerjack to:**
- Scan all repos in ecosystem.yaml
- Aggregate coverage reports
- Generate unified quality dashboard
- Store in Session-Buddy for trends

## Detailed Design

### Metrics Collector Script

```python
"""Collect metrics across all repositories."""

import json
from pathlib import Path
from typing import Dict, List, Any

import yaml
import coverage


class MetricsCollector:
    """Collect and aggregate metrics across repositories."""

    def __init__(self, ecosystem_path: str = "settings/repos.yaml"):
        """Initialize with repository catalog."""
        self.repos_path = Path(ecosystem_path)
        with open(self.repos_path) as f:
            repos_data = yaml.safe_load(f)
        self.repos = repos_data.get("repos", [])

    def collect_coverage(self) -> Dict[str, Dict[str, Any]]:
        """Collect coverage from all repositories."""
        results = {}

        for repo in self.repos:
            repo_path = Path(repo["path"])

            # Try .coverage file
            coverage_file = repo_path / ".coverage"
            if coverage_file.exists():
                cov = coverage.CoverageData()
                cov.read_file(str(coverage_file))
                results[repo["name"]] = {
                    "coverage": cov.report(include_unmatched=True),
                    "files": cov.measured_files(),
                }

            # Try coverage.xml
            else:
                xml_file = repo_path / "coverage.xml"
                if xml_file.exists():
                    # Parse XML and extract coverage
                    results[repo["name"]] = self._parse_coverage_xml(xml_file)

        return results

    def collect_quality_scores(self) -> Dict[str, Dict[str, Any]]:
        """Collect quality scores from crackerjack runs."""
        # Run crackerjack on each repo
        results = {}

        for repo in self.repos:
            repo_path = repo["path"]

            # Try to run crackerjack
            try:
                result = subprocess.run(
                    ["crackerjack", "run", "--quick", repo_path],
                    capture_output=True,
                    text=True,
                )
                results[repo["name"]] = json.loads(result.stdout)
            except Exception as e:
                results[repo["name"]] = {"error": str(e)}

        return results

    def generate_report(self) -> Dict[str, Any]:
        """Generate comprehensive metrics report."""
        coverage = self.collect_coverage()
        quality = self.collect_quality_scores()

        return {
            "timestamp": datetime.now().isoformat(),
            "coverage": coverage,
            "quality": quality,
            "summary": self._generate_summary(coverage, quality),
        }

    def create_coordination_issues(self, min_coverage: float = 80.0) -> List[str]:
        """Create coordination issues for repos below threshold."""
        issues_created = []
        coverage = self.collect_coverage()

        for repo_name, data in coverage.items():
            if isinstance(data, dict) and "coverage" in data:
                cov_percent = data["coverage"] * 100
                if cov_percent < min_coverage:
                    # Create coordination issue
                    issue_id = self._create_quality_issue(
                        repo_name,
                        cov_percent,
                        min_coverage
                    )
                    issues_created.append(issue_id)

        return issues_created
```

### Dashboard (Future)

**FastBlock-based dashboard:**

```python
# apps/dashboard/app.py
from fastblocks import FastBlocksApp

@app.get("/")
async def metrics_dashboard():
    """Show unified metrics dashboard."""
    collector = MetricsCollector()
    report = collector.generate_report()

    return render_template("metrics.html", **report)
```

**Features:**
- Coverage comparison table (all 24 repos)
- Quality trends over time
- Historical charts (last 30 days, 90 days)
- Filter by role, tag, or quality gate
- Drill-down into specific repo details

## Integration with Existing Systems

### 1. Crackerjack

**Current:** Per-repo quality checks
**Enhancement:** Cross-repo aggregation

```bash
# New command
crackerjack aggregate --repos all --min-coverage 80
```

### 2. Session-Buddy

**Store metrics events:**
```python
await session_buddy.store_memory(
    collection="mahavishnu_metrics",
    content="Fastblocks coverage dropped from 85% to 65%",
    metadata={
        "repo": "fastbulma",
        "type": "coverage_alert",
        "old_coverage": 85.0,
        "new_coverage": 65.0,
        "timestamp": "2026-02-01T12:00:00"
    }
)
```

### 3. Mahavishnu Coordination

**Track quality issues as coordination issues:**
```yaml
# ecosystem.yaml coordination section
coordination:
  issues:
    - id: "QUALITY-001"
      title: "Low coverage across multiple repos"
      description: "FastBlocks (65%), Mailgun-MCP (45%) need tests"
      severity: "quality"
      repos: ["fastbulma", "mailgun-mcp"]
      priority: "high"
      created: "2026-02-01"
      updated: "2026-02-01"
      status: "open"
      labels: ["quality", "coverage"]
```

## Quick Start Implementation

### Phase 1: Simple Collector Script (Day 1)

```python
# scripts/collect_metrics.py
import subprocess
from pathlib import Path

def get_coverage(repo_path: Path) -> float:
    """Get coverage percentage from a repo."""
    # Try pytest-cov
    result = subprocess.run(
        ["python", "-m", "pytest", "--cov", "--cov-report=term-missing"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )

    # Parse output
    for line in result.stdout.split('\n'):
        if "TOTAL" in line:
            # Extract percentage
            pct = line.split()[-1].replace('%', '')
            return float(pct)

    return 0.0

# Scan all repos
repos = yaml.safe_load(open("settings/repos.yaml"))
for repo in repos["repos"]:
    cov = get_coverage(Path(repo["path"]))
    print(f"{repo['name']}: {cov:.1f}%")
```

### Phase 2: Coordination Integration (Day 2)

```bash
# Create quality issues for low coverage
python scripts/collect_metrics.py --create-issues --min-coverage 80

# View all quality issues
mahavishnu coord list-issues --severity quality

# Track via plans
mahavishnu coord create-plan \
  --title "Q1 Quality Improvement" \
  --milestones "all_80_coverage:2026-02-28"
```

### Phase 3: Dashboard (Day 3-4)

- FastBlocks web app
- Real-time metrics
- Historical charts
- Trend analysis

## Benefits

### 1. Single Source of Truth

All metrics aggregated in one place, stored in ecosystem.yaml coordination section.

### 2. Trend Analysis

Session-Buddy memory integration provides historical tracking and semantic search.

### 3. Action-Oriented

Coordination system turns metrics into actionable issues and todos.

### 4. Role-Based Routing

Filter metrics by repo role (orchestrator, tool, app, etc.) for targeted improvements.

## Example Workflow

```bash
# 1. Collect metrics
python scripts/collect_metrics.py --report

# 2. Identify low-quality repos
mahavishnu coord list-issues --severity quality --status open

# 3. Create improvement plan
mahavishnu coord create-plan \
  --title "Fix coverage in tool repos" \
  --repos "mailgun-mcp,raindropio-mcp" \
  --target "2026-02-28"

# 4. Add todos
mahavishnu coord create-todo \
  --task "Add tests to mailgun-mcp" \
  --repo mailgun-mcp \
  --estimate 8

# 5. Execute via pools
await executor.sweep_plan("PLAN-QUALITY-001")
```

## What This Enables

### 1. Unified Quality View

```bash
# See all repos at once
python scripts/collect_metrics.py --dashboard

# Filter by role
python scripts/collect_metrics.py --by-role tool

# Find outliers
python scripts/collect_metrics.py --outliers
```

### 2. Automated Quality Gates

```yaml
# .github/workflows/quality.yml
- name: Check quality metrics
  run: python scripts/collect_metrics.py --fail-below 80

- name: Create coordination issues if failed
  run: python scripts/collect_metrics.py --create-issues
```

### 3. Historical Tracking

```python
# Search quality trends
await session_buddy.search(
    query="coverage decreased",
    collection="mahavishnu_metrics",
    filters={"type": "coverage_alert"}
)
```

### 4. Cross-Repo Standards Enforcement

```bash
# Enforce 80% coverage minimum
mahavishnu coord create-issue \
  --title "Enforce 80% coverage across all repos" \
  --repos "*" \
  --labels "gated"
```

## Recommendation

**Start with Option 1** (Coordination System) because:

1. ✅ **Already built** - use what we just created!
2. ✅ **Action-oriented** - turns metrics into work items
3. ✅ **Memory-aware** - Session-Buddy integration for trends
4. ✅ **Pool-executable** - can trigger automated fixes
5. ✅ **Role-aware** - leverage existing repo taxonomy

**Then add Option 2** (Collector Script) for automation:

1. Scan all repos automatically
2. Parse coverage files
3. Create coordination issues programmatically
4. Generate reports

**Consider Option 3** (Dashboard) later when needed:

1. Visual interface for stakeholders
2. Real-time monitoring
3. Historical charts and trends

## Next Steps

Would you like me to:

1. **Create the metrics collector script** (`scripts/collect_metrics.py`)?
2. **Set up automated coordination issues** for quality tracking?
3. **Create a sample quality plan** for your repos?
4. **Integrate with crackerjack** for unified quality reporting?
5. **Build a FastBlocks dashboard** for metrics visualization?

This would be a perfect way to demonstrate the coordination system in action!

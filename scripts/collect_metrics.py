#!/usr/bin/env python3
"""
Quick metrics collector for Mahavishnu ecosystem.

Scans all repositories and aggregates coverage data.
Can optionally create coordination issues for low-coverage repos.
"""

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any

import yaml


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Collect metrics across Mahavishnu ecosystem")
    parser.add_argument(
        "--create-issues",
        action="store_true",
        help="Create coordination issues for repos below coverage threshold",
    )
    parser.add_argument(
        "--min-coverage",
        type=float,
        default=80.0,
        help="Minimum coverage threshold (default: 80.0)",
    )
    parser.add_argument(
        "--store-metrics",
        action="store_true",
        help="Store metrics in Session-Buddy for historical tracking",
    )
    parser.add_argument(
        "--output",
        type=str,
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    return parser.parse_args()


def get_coverage_from_file(repo_path: Path) -> dict[str, Any]:
    """Extract coverage from .coverage file."""
    try:
        from io import StringIO

        import coverage

        # Create a Coverage object
        cov = coverage.Coverage(str(repo_path / ".coverage"), config_file=False)
        cov.load()

        # Capture report output
        output = StringIO()
        cov.report(file=output)
        output.seek(0)

        # Parse the last line which contains TOTAL
        lines = output.readlines()
        for line in lines:
            if "TOTAL" in line:
                # Format: "TOTAL                             500     400   80%"
                parts = line.split()
                if len(parts) >= 4:
                    # Get coverage percentage (last column)
                    coverage_str = parts[-1]
                    coverage_pct = float(coverage_str.rstrip("%"))

                    # Get number of files measured
                    data = cov.get_data()
                    measured_files = len(data.measured_files())

                    return {"coverage": coverage_pct, "files": measured_files}

    except Exception as e:
        return {"error": str(e)}

    return {}


def create_coordination_issues(
    results: list[dict[str, Any]],
    min_coverage: float,
    ecosystem_path: Path,
) -> list[str]:
    """Create coordination issues for repos below coverage threshold.

    Args:
        results: List of coverage results
        min_coverage: Minimum coverage threshold
        ecosystem_path: Path to ecosystem.yaml

    Returns:
        List of created issue IDs
    """
    try:
        from mahavishnu.core.coordination.manager import CoordinationManager
        from mahavishnu.core.coordination.models import (
            CrossRepoIssue,
            IssueStatus,
            Priority,
        )

        mgr = CoordinationManager(str(ecosystem_path))
        issues_created = []

        # Find repos below threshold
        low_coverage = [r for r in results if r["coverage"] < min_coverage]

        for repo_data in low_coverage:
            repo_name = repo_data["repo"]
            coverage = repo_data["coverage"]
            role = repo_data["role"]

            # Check if issue already exists
            existing_issues = mgr.list_issues()
            issue_id = None

            for issue in existing_issues:
                if f"Low coverage: {repo_name}" in issue.title:
                    issue_id = issue.id
                    break

            if issue_id:
                print(f"  ℹ️  Issue {issue_id} already exists for {repo_name}")
                issues_created.append(issue_id)
                continue

            # Create new issue
            new_issue = CrossRepoIssue(
                id=f"QUALITY-{len(existing_issues) + 1:03d}",
                title=f"Low coverage: {repo_name} ({coverage:.1f}%)",
                description=f"Test coverage is {coverage:.1f}%, below {min_coverage}% threshold.\n\n"
                f"Role: {role}\n"
                f"Files tested: {repo_data['files_tested']}\n\n"
                f"Action needed: Add tests to increase coverage to {min_coverage}% or higher.",
                status=IssueStatus.PENDING,
                priority=Priority.HIGH if coverage < 50 else Priority.MEDIUM,
                severity="quality",
                repos=[repo_name],
                created=datetime.now().isoformat(),
                updated=datetime.now().isoformat(),
                dependencies=[],
                blocking=[],
                labels=["quality", "coverage", f"role:{role}"],
                metadata={
                    "current_coverage": coverage,
                    "target_coverage": min_coverage,
                    "files_tested": repo_data["files_tested"],
                    "role": role,
                },
            )

            mgr.create_issue(new_issue)
            mgr.save()

            print(f"  ✅ Created issue {new_issue.id} for {repo_name}")
            issues_created.append(new_issue.id)

        return issues_created

    except ImportError:
        print("  ⚠️  Coordination module not available. Skipping issue creation.")
        return []
    except Exception as e:
        print(f"  ❌ Error creating coordination issues: {e}")
        return []


def store_metrics_snapshot(
    results: list[dict[str, Any]],
    avg_coverage: float,
) -> None:
    """Store metrics snapshot for historical tracking.

    Args:
        results: List of coverage results
        avg_coverage: Average coverage across all repos
    """
    try:
        # Create metrics storage directory
        metrics_dir = Path(__file__).parent.parent / "data" / "metrics"
        metrics_dir.mkdir(parents=True, exist_ok=True)

        # Create snapshot file with timestamp
        timestamp = datetime.now()
        filename = f"metrics_{timestamp.strftime('%Y%m%d_%H%M%S')}.json"
        snapshot_path = metrics_dir / filename

        # Prepare snapshot data
        snapshot = {
            "timestamp": timestamp.isoformat(),
            "summary": {
                "avg_coverage": avg_coverage,
                "repos_count": len(results),
                "total_files_tested": sum(r["files_tested"] for r in results),
            },
            "repositories": [
                {
                    "name": r["repo"],
                    "role": r["role"],
                    "coverage": r["coverage"],
                    "files_tested": r["files_tested"],
                }
                for r in results
            ],
        }

        # Write snapshot to file
        with open(snapshot_path, "w") as f:
            json.dump(snapshot, f, indent=2)

        print(f"  ✅ Stored metrics snapshot: {snapshot_path}")
        print(f"     Timestamp: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"     Average coverage: {avg_coverage:.1f}%")
        print(f"     Repositories: {len(results)}")

        # Update latest symlink
        latest_path = metrics_dir / "latest.json"
        if latest_path.exists():
            latest_path.unlink()
        latest_path.symlink_to(snapshot_path.name)

        # Clean up old snapshots (keep last 30)
        snapshots = sorted(
            metrics_dir.glob("metrics_*.json"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        for old_snapshot in snapshots[30:]:
            old_snapshot.unlink()
            print(f"  🗑️  Removed old snapshot: {old_snapshot.name}")

    except Exception as e:
        print(f"  ⚠️  Could not store metrics snapshot: {e}")
        import traceback

        traceback.print_exc()


def main() -> int:
    """Collect and display metrics across all repositories."""
    args = parse_args()

    # Load repository catalog
    repos_path = Path(__file__).parent.parent / "settings" / "repos.yaml"
    ecosystem_path = Path(__file__).parent.parent / "settings" / "ecosystem.yaml"

    with open(repos_path) as f:
        data = yaml.safe_load(f)

    repos = data.get("repos", [])

    print("📊 Mahavishnu Ecosystem Metrics")
    print("=" * 50)
    print(f"\nScanning {len(repos)} repositories...\n")

    # Collect coverage data
    results = []

    for repo in repos:
        repo_name = repo.get("name", "unknown")
        repo_path = Path(repo["path"])
        role = repo.get("role", "unknown")

        coverage_file = repo_path / ".coverage"

        if coverage_file.exists():
            print(f"  ✅ {repo_name:30} | Analyzing coverage...")

            cov_data = get_coverage_from_file(repo_path)
            if "error" in cov_data:
                print(f"     Error: {cov_data['error']}")
            else:
                coverage = cov_data.get("coverage", 0)
                files = cov_data.get("files", 0)

                results.append(
                    {
                        "repo": repo_name,
                        "role": role,
                        "coverage": coverage,
                        "files_tested": files,
                    }
                )

                # Status based on coverage
                if coverage >= 80:
                    status = "✅ Good"
                elif coverage >= 60:
                    status = "⚠️  Fair"
                else:
                    status = "❌ Needs Work"

                print(f"     Coverage: {coverage:5.1f}% | Files: {files:3} | {status}")
        else:
            print(f"  ⚪ {repo_name:30} | No coverage data")

    # Summary
    print(f"\n{'=' * 50}")
    print("Summary")
    print(f"{'=' * 50}\n")

    if results:
        avg_coverage = sum(r["coverage"] for r in results) / len(results)
        print(f"Repositories with coverage: {len(results)}")
        print(f"Average coverage: {avg_coverage:.1f}%")
        print(f"Total files tested: {sum(r['files_tested'] for r in results)}")

        # Find outliers
        print(f"\n{'=' * 50}")
        print("Coverage Leaders (> 90%):")
        leaders = [r for r in results if r["coverage"] > 90]
        if leaders:
            for r in sorted(leaders, key=lambda x: x["coverage"], reverse=True):
                print(f"  • {r['repo']:30} | {r['coverage']:5.1f}%")

        print("\nNeeds Attention (< 70%):")
        laggards = [r for r in results if r["coverage"] < 70]
        if laggards:
            for r in sorted(laggards, key=lambda x: x["coverage"]):
                print(f"  • {r['repo']:30} | {r['coverage']:5.1f}%")

        # By role
        print(f"\n{'=' * 50}")
        print("By Role:")
        print(f"{'=' * 50}\n")

        by_role = {}
        for r in results:
            role = r["role"]
            if role not in by_role:
                by_role[role] = []
            by_role[role].append(r)

        for role, repos in sorted(by_role.items()):
            avg = sum(r["coverage"] for r in repos) / len(repos)
            print(f"  {role:20} | {len(repos):2} repos | avg: {avg:5.1f}%")

    # Create coordination issues if requested
    if args.create_issues and results:
        print(f"\n{'=' * 50}")
        print("Creating Coordination Issues")
        print(f"{'=' * 50}\n")

        issues_created = create_coordination_issues(results, args.min_coverage, ecosystem_path)

        if issues_created:
            print(f"\n  ✅ Created {len(issues_created)} quality issues")
            print("  📝 View with: mahavishnu coord list-issues --severity quality")

    # Store metrics snapshot if requested
    if args.store_metrics and results:
        print(f"\n{'=' * 50}")
        print("Storing Metrics Snapshot")
        print(f"{'=' * 50}\n")

        store_metrics_snapshot(results, avg_coverage)

    # Output JSON if requested
    if args.output == "json":
        output_data = {
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "repos_with_coverage": len(results),
                "avg_coverage": avg_coverage,
                "total_files_tested": sum(r["files_tested"] for r in results),
            },
            "repositories": results,
        }

        print("\n" + json.dumps(output_data, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())

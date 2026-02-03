#!/usr/bin/env python3
"""
Generate an HTML metrics dashboard for the Mahavishnu ecosystem.

Creates a standalone HTML file with interactive charts and visualizations
of test coverage and quality metrics across all repositories.
"""

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any


def generate_dashboard(results: list[dict[str, Any]], avg_coverage: float) -> str:
    """Generate HTML dashboard from metrics results.

    Args:
        results: List of coverage results
        avg_coverage: Average coverage across all repos

    Returns:
        HTML string for the dashboard
    """
    timestamp = datetime.now().isoformat()

    # Sort results by coverage
    sorted_results = sorted(results, key=lambda x: x["coverage"], reverse=True)

    # Generate JavaScript data
    js_data = json.dumps(
        {
            "timestamp": timestamp,
            "avg_coverage": avg_coverage,
            "repositories": sorted_results,
        }
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Mahavishnu Ecosystem Metrics</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }}

        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}

        .header {{
            background: white;
            border-radius: 10px;
            padding: 30px;
            margin-bottom: 20px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }}

        .header h1 {{
            color: #667eea;
            font-size: 2.5em;
            margin-bottom: 10px;
        }}

        .header p {{
            color: #666;
            font-size: 1.1em;
        }}

        .summary {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }}

        .summary-card {{
            background: white;
            border-radius: 10px;
            padding: 20px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }}

        .summary-card h3 {{
            color: #666;
            font-size: 0.9em;
            text-transform: uppercase;
            margin-bottom: 10px;
        }}

        .summary-card .value {{
            color: #667eea;
            font-size: 2em;
            font-weight: bold;
        }}

        .charts {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(500px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }}

        .chart-card {{
            background: white;
            border-radius: 10px;
            padding: 20px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }}

        .chart-card h2 {{
            color: #333;
            margin-bottom: 20px;
        }}

        .table-card {{
            background: white;
            border-radius: 10px;
            padding: 20px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
        }}

        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #eee;
        }}

        th {{
            background: #f8f9fa;
            color: #333;
            font-weight: 600;
        }}

        tr:hover {{
            background: #f8f9fa;
        }}

        .status-good {{
            color: #10b981;
            font-weight: bold;
        }}

        .status-fair {{
            color: #f59e0b;
            font-weight: bold;
        }}

        .status-poor {{
            color: #ef4444;
            font-weight: bold;
        }}

        .status-nodata {{
            color: #9ca3af;
            font-style: italic;
        }}

        .coverage-bar {{
            width: 100%;
            height: 8px;
            background: #e5e7eb;
            border-radius: 4px;
            overflow: hidden;
        }}

        .coverage-fill {{
            height: 100%;
            background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
            transition: width 0.3s ease;
        }}

        .refresh-info {{
            text-align: center;
            color: white;
            margin-top: 20px;
            font-size: 0.9em;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📊 Mahavishnu Ecosystem Metrics</h1>
            <p>Cross-repository test coverage and quality metrics</p>
        </div>

        <div class="summary">
            <div class="summary-card">
                <h3>Average Coverage</h3>
                <div class="value">{avg_coverage:.1f}%</div>
            </div>
            <div class="summary-card">
                <h3>Repositories</h3>
                <div class="value">{len(results)}</div>
            </div>
            <div class="summary-card">
                <h3>Files Tested</h3>
                <div class="value">{sum(r["files_tested"] for r in results)}</div>
            </div>
        </div>

        <div class="charts">
            <div class="chart-card">
                <h2>Coverage by Repository</h2>
                <canvas id="coverageChart"></canvas>
            </div>
            <div class="chart-card">
                <h2>Coverage by Role</h2>
                <canvas id="roleChart"></canvas>
            </div>
        </div>

        <div class="table-card">
            <h2>Repository Details</h2>
            <table>
                <thead>
                    <tr>
                        <th>Repository</th>
                        <th>Role</th>
                        <th>Coverage</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
"""

    # Add table rows
    for repo in sorted_results:
        coverage = repo["coverage"]
        if coverage >= 80:
            status = '<span class="status-good">✓ Good</span>'
        elif coverage >= 60:
            status = '<span class="status-fair">⚠ Fair</span>'
        else:
            status = '<span class="status-poor">✗ Poor</span>'

        coverage_width = coverage
        html += f"""
                    <tr>
                        <td><strong>{repo["repo"]}</strong></td>
                        <td>{repo["role"]}</td>
                        <td>
                            <div>{coverage:.1f}%</div>
                            <div class="coverage-bar">
                                <div class="coverage-fill" style="width: {coverage_width}%"></div>
                            </div>
                        </td>
                        <td>{status}</td>
                    </tr>
"""

    html += (
        """
                </tbody>
            </table>
        </div>

        <div class="refresh-info">
            Generated: """
        + timestamp
        + """
            <br>
            <em>Regenerate with: <code>mahavishnu metrics dashboard --output metrics.html</code></em>
        </div>
    </div>

    <script>
        const data = """
        + js_data
        + """;

        // Coverage chart
        const coverageCtx = document.getElementById('coverageChart').getContext('2d');
        new Chart(coverageCtx, {{
            type: 'bar',
            data: {{
                labels: data.repositories.map(r => r.repo),
                datasets: [{{
                    label: 'Coverage %',
                    data: data.repositories.map(r => r.coverage),
                    backgroundColor: data.repositories.map(r => {{
                        if (r.coverage >= 80) return 'rgba(16, 185, 129, 0.8)';
                        if (r.coverage >= 60) return 'rgba(245, 158, 11, 0.8)';
                        return 'rgba(239, 68, 68, 0.8)';
                    }}),
                    borderRadius: 5,
                }}]
            }},
            options: {{
                responsive: true,
                plugins: {{
                    legend: {{
                        display: false
                    }}
                }},
                scales: {{
                    y: {{
                        beginAtZero: true,
                        max: 100,
                        ticks: {{
                            callback: value => value + '%'
                        }}
                    }}
                }}
            }}
        }});

        // Role chart
        const roleData = {{}};
        data.repositories.forEach(r => {{
            if (!roleData[r.role]) {{
                roleData[r.role] = [];
            }}
            roleData[r.role].push(r.coverage);
        }});

        const roleLabels = Object.keys(roleData);
        const roleAverages = roleLabels.map(role => {{
            const coverages = roleData[role];
            return coverages.reduce((a, b) => a + b, 0) / coverages.length;
        }});

        const roleCtx = document.getElementById('roleChart').getContext('2d');
        new Chart(roleCtx, {{
            type: 'doughnut',
            data: {{
                labels: roleLabels,
                datasets: [{{
                    data: roleAverages,
                    backgroundColor: [
                        'rgba(102, 126, 234, 0.8)',
                        'rgba(118, 75, 162, 0.8)',
                        'rgba(237, 100, 166, 0.8)',
                        'rgba(248, 172, 89, 0.8)',
                        'rgba(16, 185, 129, 0.8)',
                        'rgba(59, 130, 246, 0.8)',
                    ]
                }}]
            }},
            options: {{
                responsive: true,
                plugins: {{
                    legend: {{
                        position: 'bottom'
                    }}
                }}
            }}
        }});
    </script>
</body>
</html>
"""
    )
    return html


def main() -> int:
    """Generate the metrics dashboard."""
    parser = argparse.ArgumentParser(description="Generate HTML metrics dashboard")
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default="metrics_dashboard.html",
        help="Output HTML file path (default: metrics_dashboard.html)",
    )

    args = parser.parse_args()

    # Import metrics collection
    import yaml

    from scripts.collect_metrics import get_coverage_from_file

    # Load repository catalog
    repos_path = Path("settings/repos.yaml")
    with open(repos_path) as f:
        data = yaml.safe_load(f)

    repos = data.get("repos", [])

    # Collect coverage data
    results = []

    for repo in repos:
        repo_name = repo.get("name", "unknown")
        repo_path = Path(repo["path"])
        role = repo.get("role", "unknown")

        coverage_file = repo_path / ".coverage"

        if coverage_file.exists():
            cov_data = get_coverage_from_file(repo_path)
            if "error" not in cov_data:
                results.append(
                    {
                        "repo": repo_name,
                        "role": role,
                        "coverage": cov_data.get("coverage", 0),
                        "files_tested": cov_data.get("files", 0),
                    }
                )

    if not results:
        print("No coverage data found")
        return 1

    # Calculate average
    avg_coverage = sum(r["coverage"] for r in results) / len(results)

    # Generate dashboard
    html = generate_dashboard(results, avg_coverage)

    # Write to file
    output_path = Path(args.output)
    with open(output_path, "w") as f:
        f.write(html)

    print(f"✅ Dashboard generated: {output_path}")
    print(f"📊 Open in browser: file://{output_path.absolute()}")
    print(f"📈 Average coverage: {avg_coverage:.1f}%")
    print(f"📁 Repositories: {len(results)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""DuckDB to Grafana Bridge Server.

This server provides a HTTP API for Grafana to query DuckDB databases,
working around the lack of official DuckDB datasource plugin.

Usage:
    python scripts/duckdb_grafana_server.py [--port 8080] [--db-path data/learning.db]

Then add a JSON datasource in Grafana pointing to http://localhost:8080
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
from flask import Flask, jsonify, request

logger = logging.getLogger(__name__)

# Global database connection
db_connection: duckdb.DuckDBPyConnection | None = None

# Flask app
app = Flask(__name__)

# Query templates for Grafana panels
QUERY_TEMPLATES = {
    "execution_count_24h": """
        SELECT COUNT(*) as value
        FROM executions
        WHERE timestamp >= NOW() - INTERVAL '24 hours'
    """,
    "success_rate_24h": """
        SELECT (SUM(CASE WHEN success = TRUE THEN 1 ELSE 0 END) * 100.0 / COUNT(*)) as value
        FROM executions
        WHERE timestamp >= NOW() - INTERVAL '24 hours'
    """,
    "avg_quality_24h": """
        SELECT AVG(quality_score) as value
        FROM executions
        WHERE timestamp >= NOW() - INTERVAL '24 hours'
        AND quality_score IS NOT NULL
    """,
    "total_cost_24h": """
        SELECT SUM(actual_cost) as value
        FROM executions
        WHERE timestamp >= NOW() - INTERVAL '24 hours'
    """,
    "executions_over_time": """
        SELECT
            DATE_TRUNC('hour', timestamp) as time,
            COUNT(*) as value
        FROM executions
        WHERE timestamp >= NOW() - INTERVAL '7 days'
        GROUP BY time
        ORDER BY time
    """,
    "success_rate_over_time": """
        SELECT
            DATE_TRUNC('day', timestamp) as time,
            (SUM(CASE WHEN success = TRUE THEN 1 ELSE 0 END) * 100.0 / COUNT(*)) as value
        FROM executions
        WHERE timestamp >= NOW() - INTERVAL '7 days'
        GROUP BY time
        ORDER BY time
    """,
    "success_by_model_tier": """
        SELECT
            model_tier as metric,
            (SUM(CASE WHEN success = TRUE THEN 1 ELSE 0 END) * 100.0 / COUNT(*)) as value
        FROM executions
        WHERE timestamp >= NOW() - INTERVAL '7 days'
        GROUP BY model_tier
        ORDER BY value DESC
    """,
    "duration_by_model_tier": """
        SELECT
            model_tier as metric,
            AVG(duration_seconds) as value
        FROM executions
        WHERE timestamp >= NOW() - INTERVAL '7 days'
        GROUP BY model_tier
        ORDER BY value DESC
    """,
    "cost_by_model_tier": """
        SELECT
            model_tier as metric,
            SUM(actual_cost) as value
        FROM executions
        WHERE timestamp >= NOW() - INTERVAL '7 days'
        GROUP BY model_tier
        ORDER BY value DESC
    """,
    "pool_performance": """
        SELECT
            pool_type as metric,
            COUNT(*) as executions,
            (SUM(CASE WHEN success = TRUE THEN 1 ELSE 0 END) * 100.0 / COUNT(*)) as success_rate,
            AVG(duration_seconds) as avg_duration,
            AVG(actual_cost) as avg_cost
        FROM executions
        WHERE pool_type IS NOT NULL
        AND timestamp >= NOW() - INTERVAL '7 days'
        GROUP BY pool_type
        ORDER BY executions DESC
    """,
    "top_repos": """
        SELECT
            repo as metric,
            COUNT(*) as executions,
            AVG(quality_score) as avg_quality,
            AVG(duration_seconds) as avg_duration,
            SUM(actual_cost) as total_cost
        FROM executions
        WHERE timestamp >= NOW() - INTERVAL '30 days'
        GROUP BY repo
        ORDER BY executions DESC
        LIMIT 10
    """,
    "duration_percentiles": """
        SELECT
            PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY duration_seconds) as p50,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_seconds) as p95,
            PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY duration_seconds) as p99
        FROM executions
        WHERE timestamp >= NOW() - INTERVAL '7 days'
    """,
    "quality_distribution": """
        SELECT
            CASE
                WHEN quality_score >= 90 THEN 'excellent'
                WHEN quality_score >= 75 THEN 'good'
                WHEN quality_score >= 60 THEN 'fair'
                ELSE 'poor'
            END as metric,
            COUNT(*) as value
        FROM executions
        WHERE quality_score IS NOT NULL
        AND timestamp >= NOW() - INTERVAL '30 days'
        GROUP BY metric
        ORDER BY value DESC
    """,
    "task_type_distribution": """
        SELECT
            task_type as metric,
            COUNT(*) as executions,
            AVG(duration_seconds) as avg_duration,
            AVG(quality_score) as avg_quality
        FROM executions
        WHERE timestamp >= NOW() - INTERVAL '30 days'
        GROUP BY task_type
        ORDER BY executions DESC
        LIMIT 15
    """,
    "top_errors": """
        SELECT
            error_type as metric,
            COUNT(*) as value,
            MAX(timestamp) as last_occurrence
        FROM executions
        WHERE error_type IS NOT NULL
        AND timestamp >= NOW() - INTERVAL '7 days'
        GROUP BY error_type
        ORDER BY value DESC
        LIMIT 10
    """,
    "database_growth": """
        SELECT COUNT(*) as value
        FROM executions
        WHERE timestamp >= NOW() - INTERVAL '30 days'
    """,
    "avg_routing_confidence": """
        SELECT AVG(routing_confidence) * 100 as value
        FROM executions
        WHERE routing_confidence IS NOT NULL
        AND timestamp >= NOW() - INTERVAL '7 days'
    """,
}


def setup_logging(verbose: bool = False) -> None:
    """Setup logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler()],
    )


@app.route("/health")
def health() -> dict[str, Any]:
    """Health check endpoint."""
    if db_connection is None:
        return jsonify({"status": "error", "message": "Database not connected"}), 503

    try:
        # Test database connection
        result = db_connection.execute("SELECT 1").fetchone()
        return jsonify({
            "status": "ok",
            "database": "connected",
            "timestamp": datetime.now().isoformat(),
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "timestamp": datetime.now().isoformat(),
        }), 503


@app.route("/query", methods=["POST"])
def query() -> dict[str, Any]:
    """Query endpoint for Grafana JSON datasource.

    Expects JSON body with optional 'query' field for query name.
    Returns data in Grafana format.
    """
    if db_connection is None:
        return jsonify({"error": "Database not connected"}), 503

    try:
        # Get query name from request
        data = request.get_json(silent=True) or {}
        query_name = data.get("query", "execution_count_24h")

        # Get query template
        query_sql = QUERY_TEMPLATES.get(query_name)
        if not query_sql:
            return jsonify({"error": f"Unknown query: {query_name}"}), 400

        # Execute query
        result = db_connection.execute(query_sql).fetchall()

        # Convert to Grafana format
        if not result:
            return jsonify({"data": []})

        # Get column names
        columns = [desc[0] for desc in db_connection.description]

        # Format response
        rows = []
        for row in result:
            row_dict = {}
            for i, col in enumerate(columns):
                row_dict[col] = row[i]
            rows.append(row_dict)

        return jsonify({
            "data": rows,
            "columns": columns,
            "rowCount": len(rows),
        })

    except Exception as e:
        logger.error(f"Query failed: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/queries")
def list_queries() -> dict[str, Any]:
    """List available queries."""
    return jsonify({
        "queries": list(QUERY_TEMPLATES.keys()),
        "count": len(QUERY_TEMPLATES),
    })


@app.route("/search")
def search() -> dict[str, Any]:
    """Search endpoint for Grafana datasource discovery."""
    return jsonify(list(QUERY_TEMPLATES.keys()))


@app.route("/columns")
def columns() -> dict[str, Any]:
    """Return available columns for table discovery."""
    if db_connection is None:
        return jsonify({"error": "Database not connected"}), 503

    try:
        # Get table schema
        result = db_connection.execute("PRAGMA table_info('executions')").fetchall()
        columns = [
            {
                "text": row[1],
                "type": row[2],
            }
            for row in result
        ]

        return jsonify(columns)

    except Exception as e:
        logger.error(f"Failed to get columns: {e}")
        return jsonify({"error": str(e)}), 500


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="DuckDB to Grafana Bridge Server"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port to listen on (default: 8080)",
    )
    parser.add_argument(
        "--db-path",
        default="data/learning.db",
        help="Path to DuckDB database (default: data/learning.db)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.verbose)

    # Connect to database
    global db_connection
    db_path = Path(args.db_path)

    if not db_path.exists():
        logger.error(f"Database not found: {db_path}")
        logger.info("Generate test data with: python scripts/generate_test_learning_data.py")
        return 1

    try:
        logger.info(f"Connecting to database: {db_path}")
        db_connection = duckdb.connect(str(db_path))

        # Test connection
        result = db_connection.execute("SELECT COUNT(*) FROM executions").fetchone()
        logger.info(f"Database connected successfully ({result[0]} execution records)")

    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        return 1

    # Start server
    logger.info(f"Starting server on http://{args.host}:{args.port}")
    logger.info(f"Available endpoints:")
    logger.info(f"  - GET  /health          - Health check")
    logger.info(f"  - GET  /queries         - List available queries")
    logger.info(f"  - POST /query           - Execute query")
    logger.info(f"  - GET  /search          - Search queries (Grafana)")
    logger.info(f"  - GET  /columns         - Get table columns")

    try:
        app.run(host=args.host, port=args.port, debug=False)
    except KeyboardInterrupt:
        logger.info("Server stopped")
    finally:
        if db_connection:
            db_connection.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())

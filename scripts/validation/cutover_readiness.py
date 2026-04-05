#!/usr/bin/env python
"""Cutover readiness validation script.

Validates that the Storage Consolidation migration is ready for production cutover.

Usage:
    python scripts/validation/cutover_readiness.py --dsn "postgresql://user@localhost/db"
    python scripts/validation/cutover_readiness.py --dsn "..." --verbose

Exit codes:
    0: All checks passed
    1: One or more checks failed
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

try:
    import asyncpg
except ImportError:
    print("Error: asyncpg required. Install with: pip install asyncpg")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("cutover_readiness")


class CheckStatus(StrEnum):
    """Status of individual checks."""

    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    SKIP = "skip"


@dataclass
class CheckResult:
    """Result of a single validation check."""

    name: str
    status: CheckStatus
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "details": self.details,
        }


@dataclass
class ValidationResult:
    """Overall validation result."""

    timestamp: str
    status: CheckStatus
    checks: list[CheckResult]
    summary: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "timestamp": self.timestamp,
            "status": self.status.value,
            "checks": [c.to_dict() for c in self.checks],
            "summary": self.summary,
        }


class CutoverReadinessValidator:
    """Validates cutover readiness for Storage Consolidation."""

    EXPECTED_SCHEMAS = ["orchestration", "audit", "search", "integration"]
    EXPECTED_TABLES = {
        "orchestration": ["tasks", "task_runs", "task_dependencies"],
        "audit": ["task_events"],
        "search": ["documents", "document_embeddings"],
        "integration": ["session_context_links"],
    }
    VALID_STATUSES = ["pending", "in_progress", "completed", "failed", "cancelled", "blocked"]
    VALID_PRIORITIES = ["low", "medium", "high", "critical"]
    VALID_SYNC_STATUSES = ["pending", "synced", "failed", "retrying", "skipped"]

    def __init__(self, dsn: str, verbose: bool = False) -> None:
        """Initialize validator.

        Args:
            dsn: PostgreSQL connection string
            verbose: Enable verbose output
        """
        self.dsn = dsn
        self.verbose = verbose
        self._conn: asyncpg.Connection | None = None

    async def connect(self) -> asyncpg.Connection:
        """Connect to database.

        Returns:
            Database connection
        """
        if self._conn is None:
            self._conn = await asyncpg.connect(self.dsn)
        return self._conn

    async def disconnect(self) -> None:
        """Disconnect from database."""
        if self._conn:
            await self._conn.close()
            self._conn = None

    def _log(self, msg: str, level: int = logging.INFO) -> None:
        """Log message if verbose."""
        if self.verbose:
            logger.log(level, msg)

    async def check_pgvector_extension(self) -> CheckResult:
        """Check if pgvector extension is installed and working."""
        conn = await self.connect()
        try:
            result = await conn.fetchval(
                "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
            )
            if result:
                # Test vector operations
                await conn.execute("SELECT '[1,2,3]'::vector <=> '[4,5,6]'::vector")
                return CheckResult(
                    name="pgvector_extension",
                    status=CheckStatus.PASS,
                    message=f"pgvector {result} installed and functional",
                    details={"version": result},
                )
            return CheckResult(
                name="pgvector_extension",
                status=CheckStatus.FAIL,
                message="pgvector extension not installed",
                details={"hint": "Run: CREATE EXTENSION vector;"},
            )
        except Exception as e:
            return CheckResult(
                name="pgvector_extension",
                status=CheckStatus.FAIL,
                message=f"pgvector check failed: {e}",
            )

    async def check_schemas_exist(self) -> CheckResult:
        """Check if all required schemas exist."""
        conn = await self.connect()
        try:
            rows = await conn.fetch(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name = ANY($1)",
                self.EXPECTED_SCHEMAS,
            )
            found = {r["schema_name"] for r in rows}
            missing = set(self.EXPECTED_SCHEMAS) - found

            if missing:
                return CheckResult(
                    name="schemas_exist",
                    status=CheckStatus.FAIL,
                    message=f"Missing schemas: {missing}",
                    details={"found": list(found), "missing": list(missing)},
                )
            return CheckResult(
                name="schemas_exist",
                status=CheckStatus.PASS,
                message=f"All {len(found)} schemas present",
                details={"schemas": list(found)},
            )
        except Exception as e:
            return CheckResult(
                name="schemas_exist",
                status=CheckStatus.FAIL,
                message=f"Schema check failed: {e}",
            )

    async def check_tables_exist(self) -> CheckResult:
        """Check if all required tables exist."""
        conn = await self.connect()
        try:
            rows = await conn.fetch(
                "SELECT table_schema, table_name FROM information_schema.tables "
                "WHERE table_schema = ANY($1)",
                self.EXPECTED_SCHEMAS,
            )
            found: dict[str, set[str]] = {}
            for r in rows:
                schema = r["table_schema"]
                if schema not in found:
                    found[schema] = set()
                found[schema].add(r["table_name"])

            missing: dict[str, list[str]] = {}
            for schema, expected_tables in self.EXPECTED_TABLES.items():
                schema_missing = set(expected_tables) - found.get(schema, set())
                if schema_missing:
                    missing[schema] = list(schema_missing)

            if missing:
                return CheckResult(
                    name="tables_exist",
                    status=CheckStatus.FAIL,
                    message=f"Missing tables in schemas: {list(missing.keys())}",
                    details={"missing": missing},
                )

            total_tables = sum(len(t) for t in found.values())
            return CheckResult(
                name="tables_exist",
                status=CheckStatus.PASS,
                message=f"All {total_tables} required tables present",
                details={"tables_per_schema": {k: list(v) for k, v in found.items()}},
            )
        except Exception as e:
            return CheckResult(
                name="tables_exist",
                status=CheckStatus.FAIL,
                message=f"Table check failed: {e}",
            )

    async def check_constraints(self) -> CheckResult:
        """Check if CHECK constraints are properly defined."""
        conn = await self.connect()
        try:
            constraints = await conn.fetch("""
                SELECT tc.table_schema, tc.table_name, cc.check_clause
                FROM information_schema.table_constraints tc
                JOIN information_schema.check_constraints cc
                    ON tc.constraint_name = cc.constraint_name
                WHERE tc.table_schema IN ('orchestration', 'audit', 'search', 'integration')
                AND tc.constraint_type = 'CHECK'
                AND cc.check_clause LIKE '%= ANY%'
            """)

            if len(constraints) >= 4:  # At least status, priority, sync_status, dependency_type
                return CheckResult(
                    name="check_constraints",
                    status=CheckStatus.PASS,
                    message=f"{len(constraints)} CHECK constraints with enum validation found",
                    details={"constraint_count": len(constraints)},
                )
            return CheckResult(
                name="check_constraints",
                status=CheckStatus.WARN,
                message=f"Only {len(constraints)} enum CHECK constraints found (expected 4+)",
                details={"constraint_count": len(constraints)},
            )
        except Exception as e:
            return CheckResult(
                name="check_constraints",
                status=CheckStatus.FAIL,
                message=f"Constraint check failed: {e}",
            )

    async def check_hnsw_index(self) -> CheckResult:
        """Check if HNSW index exists for vector search."""
        conn = await self.connect()
        try:
            indexes = await conn.fetch("""
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE schemaname = 'search'
                AND indexdef LIKE '%hnsw%'
                AND indexdef LIKE '%vector%'
            """)

            if indexes:
                return CheckResult(
                    name="hnsw_index",
                    status=CheckStatus.PASS,
                    message=f"HNSW index found: {indexes[0]['indexname']}",
                    details={"index": indexes[0]["indexname"]},
                )
            return CheckResult(
                name="hnsw_index",
                status=CheckStatus.FAIL,
                message="HNSW index not found for vector search",
                details={"hint": "Run: CREATE INDEX ... USING hnsw (embedding vector_cosine_ops)"},
            )
        except Exception as e:
            return CheckResult(
                name="hnsw_index",
                status=CheckStatus.FAIL,
                message=f"HNSW index check failed: {e}",
            )

    async def check_fts_index(self) -> CheckResult:
        """Check if full-text search index exists."""
        conn = await self.connect()
        try:
            indexes = await conn.fetch("""
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'search'
                AND indexdef LIKE '%content_tsv%'
                AND indexdef LIKE '%gin%'
            """)

            if indexes:
                return CheckResult(
                    name="fts_index",
                    status=CheckStatus.PASS,
                    message="GIN index for full-text search found",
                    details={"index": indexes[0]["indexname"]},
                )
            return CheckResult(
                name="fts_index",
                status=CheckStatus.FAIL,
                message="Full-text search index not found",
            )
        except Exception as e:
            return CheckResult(
                name="fts_index",
                status=CheckStatus.FAIL,
                message=f"FTS index check failed: {e}",
            )

    async def check_partitions(self) -> CheckResult:
        """Check if audit.task_events is partitioned."""
        conn = await self.connect()
        try:
            partitions = await conn.fetch("""
                SELECT tablename
                FROM pg_tables
                WHERE schemaname = 'audit'
                AND tablename LIKE 'task_events%'
                ORDER BY tablename
            """)

            if len(partitions) >= 2:  # At least default + one monthly
                return CheckResult(
                    name="table_partitions",
                    status=CheckStatus.PASS,
                    message=f"Task events partitioned ({len(partitions)} partitions)",
                    details={"partitions": [p["tablename"] for p in partitions]},
                )
            return CheckResult(
                name="table_partitions",
                status=CheckStatus.WARN,
                message="Task events may not be properly partitioned",
                details={"partitions": [p["tablename"] for p in partitions]},
            )
        except Exception as e:
            return CheckResult(
                name="table_partitions",
                status=CheckStatus.FAIL,
                message=f"Partition check failed: {e}",
            )

    async def check_feature_flags(self) -> CheckResult:
        """Check if feature flags are configured in settings."""
        import yaml
        from pathlib import Path

        settings_path = Path("settings/mahavishnu.yaml")
        try:
            if settings_path.exists():
                content = settings_path.read_text()
                # Simple check for persistence settings
                has_write_mode = "persistence_write_mode" in content or "write_mode" in content
                has_read_source = "persistence_read_source" in content or "read_source" in content

                if has_write_mode or has_read_source:
                    return CheckResult(
                        name="feature_flags",
                        status=CheckStatus.PASS,
                        message="Persistence feature flags configured",
                        details={
                            "write_mode": has_write_mode,
                            "read_source": has_read_source,
                        },
                    )
            return CheckResult(
                name="feature_flags",
                status=CheckStatus.WARN,
                message="Feature flags not yet configured in settings",
                details={
                    "hint": "Add persistence_write_mode and persistence_read_source to settings",
                },
            )
        except Exception as e:
            return CheckResult(
                name="feature_flags",
                status=CheckStatus.WARN,
                message=f"Could not verify feature flags: {e}",
            )

    async def check_rollback_docs(self) -> CheckResult:
        """Check if rollback procedure is documented."""
        from pathlib import Path

        try:
            plan_path = Path("docs/plans/2026-04-02-storage-consolidation-and-akosha-role.md")
            if plan_path.exists():
                content = plan_path.read_text()
                if "rollback" in content.lower():
                    return CheckResult(
                        name="rollback_documentation",
                        status=CheckStatus.PASS,
                        message="Rollback procedure documented in plan",
                    )
            return CheckResult(
                name="rollback_documentation",
                status=CheckStatus.WARN,
                message="Rollback procedure documentation not found",
            )
        except Exception as e:
            return CheckResult(
                name="rollback_documentation",
                status=CheckStatus.WARN,
                message=f"Could not verify rollback docs: {e}",
            )

    async def run_all_checks(self) -> ValidationResult:
        """Run all validation checks.

        Returns:
            Validation result with all check results
        """
        checks = [
            self.check_pgvector_extension(),
            self.check_schemas_exist(),
            self.check_tables_exist(),
            self.check_constraints(),
            self.check_hnsw_index(),
            self.check_fts_index(),
            self.check_partitions(),
            self.check_feature_flags(),
            self.check_rollback_docs(),
        ]

        results = await asyncio.gather(*checks)

        # Calculate summary
        summary = {
            "total": len(results),
            "passed": sum(1 for r in results if r.status == CheckStatus.PASS),
            "failed": sum(1 for r in results if r.status == CheckStatus.FAIL),
            "warnings": sum(1 for r in results if r.status == CheckStatus.WARN),
            "skipped": sum(1 for r in results if r.status == CheckStatus.SKIP),
        }

        # Determine overall status
        if summary["failed"] > 0:
            overall_status = CheckStatus.FAIL
        elif summary["warnings"] > 0:
            overall_status = CheckStatus.WARN
        else:
            overall_status = CheckStatus.PASS

        return ValidationResult(
            timestamp=datetime.now(UTC).isoformat(),
            status=overall_status,
            checks=list(results),
            summary=summary,
        )


async def main(dsn: str, verbose: bool = False, output_format: str = "json") -> int:
    """Run cutover readiness validation.

    Args:
        dsn: Database connection string
        verbose: Enable verbose output
        output_format: Output format (json or text)

    Returns:
        Exit code (0 for pass, 1 for fail)
    """
    validator = CutoverReadinessValidator(dsn, verbose)

    try:
        result = await validator.run_all_checks()

        if output_format == "json":
            print(json.dumps(result.to_dict(), indent=2))
        else:
            print("\n" + "=" * 60)
            print("CUTOVER READINESS VALIDATION")
            print("=" * 60)
            print(f"Timestamp: {result.timestamp}")
            print(f"Status: {result.status.value.upper()}")
            print("\nChecks:")
            for check in result.checks:
                icon = {"pass": "✅", "fail": "❌", "warn": "⚠️", "skip": "⏭️"}[check.status.value]
                print(f"  {icon} {check.name}: {check.message}")
            print(f"\nSummary: {result.summary}")

        return 0 if result.status != CheckStatus.FAIL else 1

    except Exception as e:
        logger.error(f"Validation failed: {e}")
        return 1
    finally:
        await validator.disconnect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Validate cutover readiness for Storage Consolidation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python scripts/validation/cutover_readiness.py --dsn "postgresql://les@localhost/mahavishnu"
    python scripts/validation/cutover_readiness.py --dsn "..." --verbose --format text
        """,
    )
    parser.add_argument(
        "--dsn",
        required=True,
        help="PostgreSQL connection string",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output",
    )
    parser.add_argument(
        "--format", "-f",
        choices=["json", "text"],
        default="text",
        help="Output format (default: text)",
    )

    args = parser.parse_args()
    exit_code = asyncio.run(main(args.dsn, args.verbose, args.format))
    sys.exit(exit_code)

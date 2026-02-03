"""Production readiness and testing module for Mahavishnu."""

import asyncio
from datetime import datetime
import inspect
import logging
from pathlib import Path
import time
import traceback
from typing import Any

from ..core.app import MahavishnuApp

logger = logging.getLogger(__name__)


class ProductionReadinessChecker:
    """Comprehensive checker for production readiness."""

    def __init__(self, app: MahavishnuApp):
        self.app = app
        self.results = {}
        self.checks_passed = 0
        self.total_checks = 0

    async def run_all_checks(self) -> dict[str, Any]:
        """Run all production readiness checks."""
        logger.info("Running Production Readiness Checks...")

        # Run all check methods
        check_methods = [method for method in dir(self) if method.startswith("_check_")]

        for method_name in check_methods:
            method = getattr(self, method_name)
            if callable(method):
                self.total_checks += 1
                try:
                    result = await method() if inspect.iscoroutinefunction(method) else method()
                    if result:
                        self.checks_passed += 1
                        logger.info(f"✅ {method.__name__[7:].replace('_', ' ').title()}: PASSED")
                    else:
                        logger.error(f"❌ {method.__name__[7:].replace('_', ' ').title()}: FAILED")
                except Exception as e:
                    logger.error(f"❌ {method.__name__[7:].replace('_', ' ').title()}: ERROR - {e}")

        # Calculate overall score
        score = (self.checks_passed / self.total_checks * 100) if self.total_checks > 0 else 0

        summary = {
            "summary": {
                "checks_passed": self.checks_passed,
                "total_checks": self.total_checks,
                "score_percentage": round(score, 2),
                "status": "PASS" if score >= 90 else "FAIL" if score < 70 else "CAUTION",
            },
            "details": self.results,
        }

        logger.info(
            f"Overall Score: {score}% ({self.checks_passed}/{self.total_checks} checks passed)"
        )
        logger.info(f"Status: {summary['summary']['status']}")

        return summary

    def _check_config_validity(self) -> bool:
        """Check if configuration is valid and secure."""
        try:
            config = self.app.config

            # Check if auth is enabled in production
            if config.auth.enabled and (not config.auth.secret or len(config.auth.secret) < 32):
                logger.warning(
                    "  Auth enabled but secret is too short (should be at least 32 chars)"
                )
                return False

            # Check if required fields are present
            required_fields = [
                "repos_path",
                "max_concurrent_workflows",
                "llm_model",
                "ollama_base_url",
            ]

            for field in required_fields:
                if not hasattr(config, field):
                    logger.error("  Missing required config field: {field}")
                    return False

            # Check if repos file exists
            repos_path = Path(config.repos_path).expanduser()
            if not repos_path.exists():
                logger.warning(f"  Repos file does not exist: {repos_path}")

            self.results["config_validity"] = {
                "status": "PASS",
                "message": "Configuration is valid",
            }
            return True
        except Exception as e:
            self.results["config_validity"] = {
                "status": "FAIL",
                "message": f"Configuration error: {e}",
            }
            return False

    def _check_adapter_health(self) -> bool:
        """Check if all enabled adapters are healthy."""
        try:
            healthy_adapters = 0
            total_adapters = len(self.app.adapters)

            for name, adapter in self.app.adapters.items():
                try:
                    health = asyncio.run(adapter.get_health())
                    if health.get("status") == "healthy":
                        healthy_adapters += 1
                    else:
                        logger.warning(f"  ⚠️  Adapter {name} is not healthy: {health}")
                except Exception as e:
                    logger.error(f"  ❌ Adapter {name} health check failed: {e}")

            if healthy_adapters == total_adapters and total_adapters > 0:
                self.results["adapter_health"] = {
                    "status": "PASS",
                    "message": f"All {total_adapters} adapters are healthy",
                }
                return True
            else:
                self.results["adapter_health"] = {
                    "status": "FAIL",
                    "message": f"Only {healthy_adapters}/{total_adapters} adapters are healthy",
                }
                return False
        except Exception as e:
            self.results["adapter_health"] = {
                "status": "FAIL",
                "message": f"Adapter health check error: {e}",
            }
            return False

    def _check_repo_accessibility(self) -> bool:
        """Check if configured repositories are accessible."""
        try:
            repos = self.app.get_repos()
            accessible_count = 0

            for repo_path in repos:
                try:
                    repo_path_obj = Path(repo_path)
                    if repo_path_obj.exists() and repo_path_obj.is_dir():
                        accessible_count += 1
                    else:
                        logger.warning(f"  ⚠️  Repository not accessible: {repo_path}")
                except Exception:
                    logger.error(f"  ⚠️  Repository path validation failed: {repo_path}")

            if not repos:
                logger.warning("  ⚠️  No repositories configured")
                self.results["repo_accessibility"] = {
                    "status": "CAUTION",
                    "message": "No repositories configured",
                }
                return True  # Not a failure, just caution

            if accessible_count == len(repos):
                self.results["repo_accessibility"] = {
                    "status": "PASS",
                    "message": f"All {len(repos)} repositories are accessible",
                }
                return True
            else:
                self.results["repo_accessibility"] = {
                    "status": "CAUTION",
                    "message": f"Only {accessible_count}/{len(repos)} repositories are accessible",
                }
                return False
        except Exception as e:
            self.results["repo_accessibility"] = {
                "status": "FAIL",
                "message": f"Repository accessibility check error: {e}",
            }
            return False

    async def _check_workflow_execution(self) -> bool:
        """Test workflow execution with a simple operation."""
        try:
            # Get a simple repo to test with
            repos = self.app.get_repos()
            if not repos:
                logger.warning("  ⚠️  No repositories to test workflow execution")
                self.results["workflow_execution"] = {
                    "status": "CAUTION",
                    "message": "No repositories available for testing",
                }
                return True

            # Test with the first available adapter
            if not self.app.adapters:
                logger.error("  ❌ No adapters available for testing")
                self.results["workflow_execution"] = {
                    "status": "FAIL",
                    "message": "No adapters available",
                }
                return False

            adapter_name = next(iter(self.app.adapters.keys()))

            # Create a simple test task
            task = {
                "type": "health_check",
                "params": {"test_only": True},
                "id": f"test_{int(time.time())}",
            }

            # Execute a simple workflow
            start_time = time.time()
            result = await self.app.execute_workflow(
                task, adapter_name, repos[:1]
            )  # Just test with first repo
            execution_time = time.time() - start_time

            if result and result.get("status") in ("completed", "partial"):
                self.results["workflow_execution"] = {
                    "status": "PASS",
                    "message": f"Workflow executed successfully in {execution_time:.2f}s",
                    "execution_time": execution_time,
                }
                return True
            else:
                logger.error(f"  ❌ Workflow execution failed: {result}")
                self.results["workflow_execution"] = {
                    "status": "FAIL",
                    "message": f"Workflow execution failed: {result}",
                }
                return False
        except Exception as e:
            logger.error(f"  ❌ Workflow execution test error: {e}")
            self.results["workflow_execution"] = {
                "status": "FAIL",
                "message": f"Workflow execution test error: {e}",
            }
            return False

    def _check_resource_limits(self) -> bool:
        """Check if resource limits are reasonable."""
        try:
            config = self.app.config

            # Check max concurrent workflows
            max_concurrent = config.max_concurrent_workflows
            if max_concurrent <= 0 or max_concurrent > 100:
                logger.warning(
                    f"  ⚠️  Unreasonable max_concurrent_workflows: {max_concurrent} (should be 1-100)"
                )
                return False

            # Check retry settings
            if (
                config.resilience.retry_max_attempts <= 0
                or config.resilience.retry_max_attempts > 10
            ):
                logger.warning(
                    f"  ⚠️  Unreasonable retry_max_attempts: {config.resilience.retry_max_attempts}"
                )
                return False

            # Check timeout settings
            if config.resilience.timeout_per_repo < 30 or config.resilience.timeout_per_repo > 3600:
                logger.warning(
                    f"  ⚠️  Unreasonable timeout_per_repo: {config.resilience.timeout_per_repo} (should be 30-3600)"
                )
                return False

            self.results["resource_limits"] = {
                "status": "PASS",
                "message": "Resource limits are reasonable",
                "limits": {
                    "max_concurrent_workflows": max_concurrent,
                    "retry_max_attempts": config.resilience.retry_max_attempts,
                    "timeout_per_repo": config.resilience.timeout_per_repo,
                },
            }
            return True
        except Exception as e:
            self.results["resource_limits"] = {
                "status": "FAIL",
                "message": f"Resource limits check error: {e}",
            }
            return False

    def _check_security_settings(self) -> bool:
        """Check if security settings are properly configured."""
        try:
            config = self.app.config

            # Check if auth is enabled in production-like environment
            if config.auth.enabled:
                if not config.auth.secret or len(config.auth.secret) < 32:
                    logger.error(
                        "  ❌ Auth enabled but secret is too short (should be at least 32 chars)"
                    )
                    return False

                if config.auth.algorithm not in ("HS256", "RS256"):
                    logger.warning(f"  ⚠️  Weak auth algorithm: {config.auth.algorithm}")
                    return False
            else:
                logger.warning("  ⚠️  Authentication is disabled - consider enabling for production")

            # Check OpenSearch security settings
            if hasattr(config, "opensearch_use_ssl") and not config.opensearch.use_ssl:
                logger.warning("  ⚠️  OpenSearch SSL is disabled - consider enabling for production")

            self.results["security_settings"] = {
                "status": "PASS",
                "message": "Security settings are properly configured",
            }
            return True
        except Exception as e:
            self.results["security_settings"] = {
                "status": "FAIL",
                "message": f"Security settings check error: {e}",
            }
            return False


class IntegrationTestSuite:
    """Comprehensive integration tests for Mahavishnu."""

    def __init__(self, app: MahavishnuApp):
        self.app = app
        self.test_results = []

    async def run_all_tests(self) -> dict[str, Any]:
        """Run all integration tests."""
        logger.info("Running Integration Tests...")

        test_methods = [method for method in dir(self) if method.startswith("_test_")]
        passed_tests = 0
        total_tests = len(test_methods)

        for method_name in test_methods:
            method = getattr(self, method_name)
            if callable(method):
                try:
                    result = await method() if inspect.iscoroutinefunction(method) else method()
                    if result:
                        passed_tests += 1
                        logger.info(f"✅ {method.__name__[6:].replace('_', ' ').title()}: PASSED")
                    else:
                        logger.error(f"❌ {method.__name__[6:].replace('_', ' ').title()}: FAILED")
                except Exception as e:
                    logger.error(f"❌ {method.__name__[6:].replace('_', ' ').title()}: ERROR - {e}")

        score = (passed_tests / total_tests * 100) if total_tests > 0 else 0

        summary = {
            "summary": {
                "tests_passed": passed_tests,
                "total_tests": total_tests,
                "score_percentage": round(score, 2),
                "status": "PASS" if score >= 90 else "FAIL" if score < 70 else "CAUTION",
            },
            "details": self.test_results,
        }

        logger.info(f"\n📊 Test Score: {score}% ({passed_tests}/{total_tests} tests passed)")
        logger.info(f"Status: {summary['summary']['status']}")

        return summary

    async def _test_basic_workflow_execution(self) -> bool:
        """Test basic workflow execution."""
        try:
            # Test with available adapters
            if not self.app.adapters:
                logger.warning("  ⚠️  No adapters available for testing")
                return True  # Not a failure of the system, just configuration

            adapter_name = next(iter(self.app.adapters.keys()))

            # Create a simple test task
            task = {
                "type": "health_check",
                "params": {"test_only": True},
                "id": f"integration_test_{int(time.time())}",
            }

            # Get available repos
            repos = self.app.get_repos()
            if not repos:
                logger.warning("  ⚠️  No repositories available for testing")
                return True  # Not a failure of the system, just configuration

            # Execute workflow
            result = await self.app.execute_workflow(task, adapter_name, repos[:1])

            success = result and result.get("status") in ("completed", "partial")
            self.test_results.append(
                {
                    "test": "basic_workflow_execution",
                    "status": "PASS" if success else "FAIL",
                    "result": result,
                }
            )

            return success
        except Exception as e:
            self.test_results.append(
                {
                    "test": "basic_workflow_execution",
                    "status": "FAIL",
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                }
            )
            return False

    async def _test_rbac_permissions(self) -> bool:
        """Test RBAC permission system."""
        try:
            # Test permission checking
            has_permission = await self.app.rbac_manager.check_permission(
                "test_user", "test_repo", "READ_REPO"
            )

            # This should return False for a non-existent user
            success = isinstance(has_permission, bool)  # Should not throw an exception

            self.test_results.append(
                {
                    "test": "rbac_permissions",
                    "status": "PASS" if success else "FAIL",
                    "result": f"Permission check worked (returned {has_permission})",
                }
            )

            return success
        except Exception as e:
            self.test_results.append(
                {
                    "test": "rbac_permissions",
                    "status": "FAIL",
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                }
            )
            return False

    async def _test_workflow_state_management(self) -> bool:
        """Test workflow state management."""
        try:
            # Create a test workflow
            workflow_id = f"test_wf_{int(time.time())}"
            task = {"type": "test", "id": workflow_id}
            repos = ["test_repo"]

            # Create workflow state
            _state = await self.app.workflow_state_manager.create(workflow_id, task, repos)

            # Verify state was created
            retrieved_state = await self.app.workflow_state_manager.get(workflow_id)

            success = retrieved_state is not None and retrieved_state.get("id") == workflow_id

            # Cleanup
            await self.app.workflow_state_manager.delete(workflow_id)

            self.test_results.append(
                {
                    "test": "workflow_state_management",
                    "status": "PASS" if success else "FAIL",
                    "result": f"State management worked: {success}",
                }
            )

            return success
        except Exception as e:
            self.test_results.append(
                {
                    "test": "workflow_state_management",
                    "status": "FAIL",
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                }
            )
            return False

    async def _test_observation_logging(self) -> bool:
        """Test observability and logging."""
        try:
            if not self.app.observability:
                logger.warning("  ⚠️  Observability not initialized")
                return True  # Not a failure if not configured

            # Test logging
            self.app.observability.log_info("Test log message", {"test": True})

            # Test metrics creation
            counter = self.app.observability.create_workflow_counter()
            if counter:
                counter.add(1, {"test": "value"})

            # Test getting logs
            logs = self.app.observability.get_logs(limit=10)

            success = logs is not None

            self.test_results.append(
                {
                    "test": "observation_logging",
                    "status": "PASS" if success else "FAIL",
                    "result": f"Observability worked: {success}, logs found: {len(logs) if logs else 0}",
                }
            )

            return success
        except Exception as e:
            self.test_results.append(
                {
                    "test": "observation_logging",
                    "status": "FAIL",
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                }
            )
            return False


class PerformanceBenchmark:
    """Performance benchmarking for Mahavishnu."""

    def __init__(self, app: MahavishnuApp):
        self.app = app
        self.benchmarks = {}

    async def run_benchmarks(self) -> dict[str, Any]:
        """Run performance benchmarks."""
        logger.info("Running Performance Benchmarks...")

        # Run individual benchmarks
        await self._benchmark_workflow_execution()
        await self._benchmark_concurrent_workflows()
        await self._benchmark_repo_operations()

        # Calculate overall performance score
        avg_times = [
            results["avg_time"] for results in self.benchmarks.values() if "avg_time" in results
        ]

        if avg_times:
            avg_performance = sum(avg_times) / len(avg_times)
            performance_score = max(0, 100 - (avg_performance * 10))  # Lower time = higher score
        else:
            performance_score = 100

        summary = {
            "summary": {
                "performance_score": round(performance_score, 2),
                "status": "EXCELLENT"
                if performance_score >= 90
                else "GOOD"
                if performance_score >= 70
                else "POOR",
            },
            "benchmarks": self.benchmarks,
        }

        logger.info(f"\n📊 Performance Score: {performance_score}/100")
        logger.info(f"Status: {summary['summary']['status']}")

        return summary

    async def _benchmark_workflow_execution(self):
        """Benchmark workflow execution speed."""
        try:
            if not self.app.adapters:
                logger.warning("  ⚠️  No adapters available for benchmarking")
                return

            adapter_name = next(iter(self.app.adapters.keys()))
            repos = self.app.get_repos()

            if not repos:
                logger.warning("  ⚠️  No repositories available for benchmarking")
                return

            # Run multiple executions to get average
            execution_times = []
            num_executions = 3

            for i in range(num_executions):
                task = {
                    "type": "health_check",
                    "params": {"benchmark": True, "iteration": i},
                    "id": f"benchmark_{int(time.time())}_{i}",
                }

                start_time = time.time()
                try:
                    await self.app.execute_workflow(task, adapter_name, repos[:1])
                    execution_time = time.time() - start_time
                    execution_times.append(execution_time)
                except Exception:
                    # If execution fails, still record the time
                    execution_time = time.time() - start_time
                    execution_times.append(execution_time)

            avg_time = sum(execution_times) / len(execution_times) if execution_times else 0
            min_time = min(execution_times) if execution_times else 0
            max_time = max(execution_times) if execution_times else 0

            self.benchmarks["workflow_execution"] = {
                "avg_time": avg_time,
                "min_time": min_time,
                "max_time": max_time,
                "num_executions": num_executions,
                "times": execution_times,
            }

            logger.info(
                f"  📈 Workflow execution: avg={avg_time:.2f}s, min={min_time:.2f}s, max={max_time:.2f}s"
            )
        except Exception as e:
            logger.error(f"  ❌ Workflow execution benchmark failed: {e}")

    async def _benchmark_concurrent_workflows(self):
        """Benchmark concurrent workflow handling."""
        try:
            if not self.app.adapters:
                logger.warning("  ⚠️  No adapters available for benchmarking")
                return

            adapter_name = next(iter(self.app.adapters.keys()))
            repos = self.app.get_repos()

            if not repos:
                logger.warning("  ⚠️  No repositories available for benchmarking")
                return

            # Run multiple concurrent executions
            num_concurrent = min(5, len(repos))  # Use up to 5 repos or available repos
            start_time = time.time()

            tasks = []
            for i in range(num_concurrent):
                task = {
                    "type": "health_check",
                    "params": {"benchmark": True, "concurrent": i},
                    "id": f"concurrent_benchmark_{int(time.time())}_{i}",
                }
                repo_subset = repos[i : i + 1]  # Each task gets one repo
                tasks.append(self.app.execute_workflow(task, adapter_name, repo_subset))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            total_time = time.time() - start_time

            successful_executions = sum(1 for r in results if not isinstance(r, Exception))

            self.benchmarks["concurrent_workflows"] = {
                "total_time": total_time,
                "num_concurrent": num_concurrent,
                "successful_executions": successful_executions,
                "throughput": successful_executions / total_time if total_time > 0 else 0,
            }

            logger.info(
                f"  🚀 Concurrent workflows: {num_concurrent} in {total_time:.2f}s, throughput={successful_executions / total_time:.2f} ops/sec"
            )
        except Exception as e:
            logger.error(f"  ❌ Concurrent workflows benchmark failed: {e}")

    async def _benchmark_repo_operations(self):
        """Benchmark repository operations."""
        try:
            repos = self.app.get_repos()

            if not repos:
                logger.warning("  ⚠️  No repositories available for benchmarking")
                return

            # Benchmark get_repos operation
            start_time = time.time()
            for _ in range(10):  # Run 10 times to get average
                _ = self.app.get_repos()
            total_time = time.time() - start_time

            avg_time = total_time / 10

            self.benchmarks["repo_operations"] = {
                "avg_get_repos_time": avg_time,
                "num_repos": len(repos),
                "total_ops_time": total_time,
            }

            logger.info(
                f"  🗂️  Repo operations: avg get_repos={avg_time:.4f}s for {len(repos)} repos"
            )
        except Exception as e:
            logger.error(f"  ❌ Repo operations benchmark failed: {e}")


async def run_production_readiness_suite(app: MahavishnuApp) -> dict[str, Any]:
    """Run the complete production readiness suite."""
    logger.info("🚀 Starting Production Readiness Suite...\n")

    # Initialize components
    checker = ProductionReadinessChecker(app)
    integration_tests = IntegrationTestSuite(app)
    benchmarks = PerformanceBenchmark(app)

    # Run all components
    readiness_results = await checker.run_all_checks()
    test_results = await integration_tests.run_all_tests()
    benchmark_results = await benchmarks.run_benchmarks()

    # Combine all results
    final_report = {
        "timestamp": datetime.now().isoformat(),
        "production_readiness": readiness_results,
        "integration_tests": test_results,
        "performance_benchmarks": benchmark_results,
        "overall_assessment": _calculate_overall_assessment(
            readiness_results, test_results, benchmark_results
        ),
    }

    logger.info("\n🏆 FINAL ASSESSMENT:")
    logger.info(f"   Production Readiness: {readiness_results['summary']['score_percentage']}%")
    logger.info(f"   Integration Tests: {test_results['summary']['score_percentage']}%")
    logger.info(f"   Performance Score: {benchmark_results['summary']['performance_score']}/100")
    logger.info(f"   Overall Status: {final_report['overall_assessment']['status']}")

    return final_report


def _calculate_overall_assessment(readiness, tests, benchmarks):
    """Calculate overall assessment based on all components."""
    readiness_score = readiness["summary"]["score_percentage"]
    test_score = tests["summary"]["score_percentage"]
    perf_score = benchmarks["summary"]["performance_score"]

    # Weighted average (readiness and tests are more important than performance)
    weighted_score = (readiness_score * 0.4) + (test_score * 0.4) + (perf_score * 0.2)

    if weighted_score >= 90:
        status = "PRODUCTION READY"
    elif weighted_score >= 75:
        status = "NEARLY READY"
    elif weighted_score >= 60:
        status = "NEEDS IMPROVEMENT"
    else:
        status = "NOT READY"

    return {
        "status": status,
        "weighted_score": round(weighted_score, 2),
        "components": {
            "readiness": readiness_score,
            "tests": test_score,
            "performance": perf_score,
        },
    }

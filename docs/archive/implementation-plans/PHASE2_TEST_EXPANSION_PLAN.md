# Phase 2: Comprehensive Adapter Testing Plan

## Current Status

- **Prefect Adapter**: 20 tests (est. ~40% coverage)
- **Agno Adapter**: 11 tests (est. ~35% coverage)
- **Target**: 80%+ coverage for both adapters

## Test Expansion Strategy

### Prefect Adapter (Target: 45+ tests)

#### 1. ImportError Handling Tests (3 tests)
- ✅ test_execute_stub_when_prefect_unavailable (exists)
- ✅ test_get_health_when_prefect_unavailable (exists)
- ➕ test_prefect_not_installed_error_message
- ➕ test_stub_flow_decorator_raises_helpful_error
- ➕ test_stub_task_decorator_raises_helpful_error
- ➕ test_mock_client_methods_raise_helpful_errors

#### 2. Flow Execution Tests (8 tests)
- ✅ test_execute_method (exists)
- ➕ test_execute_flow_with_valid_flow
- ➕ test_execute_flow_with_flow_not_found
- ➕ test_execute_flow_with_invalid_parameters
- ➕ test_execute_flow_timeout_handling
- ➕ test_execute_flow_retries_on_failure
- ➕ test_execute_flow_preserves_flow_run_status
- ➕ test_execute_flow_without_prefect_raises_error
- ➕ test_execute_flow_returns_flow_run_url

#### 3. Flow Creation Tests (5 tests)
- ➕ test_create_flow_registers_flow
- ➕ test_create_flow_without_prefect_raises_error
- ➕ test_create_flow_with_description
- ➕ test_list_flows_returns_registered_flows
- ➕ test_list_flows_includes_metadata

#### 4. Flow Monitoring Tests (6 tests)
- ➕ test_monitor_flow_run_returns_status
- ➕ test_monitor_flow_run_with_completed_flow
- ➕ test_monitor_flow_run_with_failed_flow
- ➕ test_monitor_flow_run_caches_status
- ➕ test_monitor_flow_run_without_prefect_returns_cached
- ➕ test_get_flow_status_returns_cached_status

#### 5. Pool Integration Tests (5 tests)
- ➕ test_execute_in_pool_adds_pool_id_to_task
- ➕ test_execute_in_pool_delegates_to_execute
- ➕ test_execute_in_pool_with_mahavishnu_pool
- ➕ test_execute_in_pool_with_session_buddy_pool
- ➕ test_execute_in_pool_with_kubernetes_pool

#### 6. Telemetry Tests (3 tests)
- ➕ test_setup_telemetry_initializes_flag
- ➕ test_health_includes_telemetry_status
- ➕ test_telemetry_initialized_false_by_default

#### 7. Health Check Tests (5 tests)
- ✅ test_get_health_method (exists)
- ✅ test_get_health_when_prefect_unavailable (exists)
- ➕ test_health_includes_prefect_version
- ➕ test_health_includes_flows_registered
- ➕ test_health_includes_active_flow_runs
- ➕ test_health_includes_deployments_count

#### 8. Flow Run Management Tests (6 tests)
- ➕ test_cancel_flow_run_sets_cancelled_state
- ➕ test_cancel_flow_run_without_prefect_raises_error
- ➕ test_cancel_flow_run_handles_errors
- ➕ test_list_flow_runs_without_filters
- ➕ test_list_flow_runs_with_flow_name_filter
- ➕ test_list_flow_runs_with_state_filter

#### 9. Advanced Features Tests (6 tests)
- ➕ test_create_deployment_returns_deployment_id
- ➕ test_create_deployment_stores_config
- ➕ test_schedule_flow_returns_schedule_id
- ➕ test_get_flow_metrics_returns_none
- ➕ test_send_a2a_message_flow_request
- ➕ test_receive_a2a_message_status_request

#### 10. Visualization Tests (2 tests)
- ➕ test_visualize_flow_returns_mermaid_diagram
- ➕ test_visualize_flow_with_unknown_flow_returns_none

#### 11. Error Handling Tests (4 tests)
- ➕ test_execute_raises_adapter_initialization_error_on_import_error
- ➕ test_execute_raises_adapter_execution_error_on_failure
- ➕ test_execute_flow_raises_adapter_execution_error_on_flow_not_found
- ➕ test_execute_with_retry_logic

#### 12. TaskResult and FlowMetrics Tests (2 tests)
- ➕ test_task_result_dataclass
- ➕ test_flow_metrics_dataclass

**Total: 45+ tests for Prefect adapter**

---

### Agno Adapter (Target: 60+ tests)

#### 1. ImportError Handling Tests (3 tests)
- ✅ test_execute_stub_when_agno_unavailable (via execute stub)
- ✅ test_get_health_when_agno_unavailable (exists)
- ➕ test_agno_not_installed_error_message
- ➕ test_stub_agent_run_raises_helpful_error
- ➕ test_stub_agent_astream_raises_helpful_error
- ➕ test_stub_model_initialization

#### 2. Agent Execution Tests (10 tests)
- ✅ test_execute_method (exists)
- ➕ test_execute_agent_with_valid_prompt
- ➕ test_execute_agent_without_agno_raises_error
- ➕ test_execute_agent_creates_agno_agent
- ➕ test_execute_agent_returns_response
- ➕ test_execute_agent_with_custom_parameters
- ➕ test_execute_agent_raises_on_execution_error
- ➕ test_execute_agent_task_code_sweep
- ➕ test_execute_agent_task_quality_check
- ➕ test_execute_agent_task_default_operation
- ➕ test_execute_agent_task_error_handling

#### 3. Agent Creation Tests (7 tests)
- ➕ test_create_agent_registers_agent
- ➕ test_create_agent_without_agno_raises_error
- ➕ test_register_agent_returns_agent_id
- ➕ test_get_agent_returns_config
- ➕ test_get_agent_with_unknown_name_returns_none
- ➕ test_unregister_agent_removes_agent
- ➕ test_unregister_agent_with_unknown_name_returns_false

#### 4. Multi-Agent Coordination Tests (8 tests)
- ➕ test_execute_multi_agent_workflow
- ➕ test_execute_multi_agent_workflow_with_multiple_agents
- ➕ test_execute_multi_agent_workflow_exception_handling
- ➕ test_coordinate_agents_sequences_execution
- ➕ test_coordinate_agents_with_unknown_agent_skips
- ➕ test_coordinate_agents_returns_results
- ➕ test_execute_with_memory_adds_context_to_task
- ➕ test_execute_with_memory_delegates_to_execute

#### 5. Agent Management Tests (6 tests)
- ✅ test_default_agents_initialized (exists)
- ✅ test_code_analyst_config (exists)
- ➕ test_quality_checker_config
- ➕ test_documentation_agent_config
- ➕ test_list_agents_without_filter
- ➕ test_list_agents_with_role_filter

#### 6. Agent Run Tracking Tests (6 tests)
- ➕ test_get_agent_run_status_returns_status
- ➕ test_get_agent_run_status_with_unknown_run_returns_none
- ➕ test_list_agent_runs_without_filters
- ➕ test_list_agent_runs_with_agent_name_filter
- ➕ test_list_agent_runs_with_state_filter
- ➕ test_list_agent_runs_sorts_by_start_time

#### 7. Health Check Tests (5 tests)
- ✅ test_get_health_method (exists)
- ➕ test_health_includes_agno_version
- ➕ test_health_includes_agents_registered
- ➕ test_health_includes_active_agent_runs
- ➕ test_health_status_degraded_when_agents_exist
- ➕ test_health_status_unhealthy_on_error

#### 8. Agent Run Status Tests (4 tests)
- ✅ test_minimal_status (exists)
- ➕ test_full_status_with_all_fields
- ➕ test_agent_run_status_duration_calculation
- ➕ test_agent_run_status_with_result_and_error

#### 9. Multi-Agent Result Tests (3 tests)
- ✅ test_minimal_result (exists)
- ➕ test_multi_agent_result_with_all_fields
- ➕ test_multi_agent_result_coordination_overhead

#### 10. Error Handling Tests (5 tests)
- ➕ test_execute_raises_adapter_initialization_error_on_import_error
- ➕ test_execute_raises_adapter_execution_error_on_failure
- ➕ test_execute_stub_handles_gracefully
- ➕ test_execute_stub_with_code_sweep_task
- ➕ test_execute_stub_with_error_in_processing

#### 11. AgentConfig Tests (4 tests)
- ✅ test_default_values (exists)
- ➕ test_agent_config_with_custom_tools
- ➕ test_agent_config_with_memory_disabled
- ➕ test_agent_config_with_custom_temperature

#### 12. Shutdown Tests (1 test)
- ➕ test_shutdown_method_exists

**Total: 60+ tests for Agno adapter**

---

## Implementation Order

### Phase 2.1: Prefect Adapter Tests (Days 1-2)
1. Add ImportError handling tests
2. Add flow execution tests
3. Add flow creation tests
4. Add flow monitoring tests
5. Add pool integration tests
6. Add telemetry and health check tests
7. Add flow run management tests
8. Add advanced features tests
9. Add visualization and error handling tests
10. Run coverage report to verify 80%+ target

### Phase 2.2: Agno Adapter Tests (Days 3-4)
1. Add ImportError handling tests
2. Add agent execution tests
3. Add agent creation and management tests
4. Add multi-agent coordination tests
5. Add agent run tracking tests
6. Add health check and error handling tests
7. Add dataclass tests
8. Run coverage report to verify 80%+ target

### Phase 2.3: Integration and Validation (Day 5)
1. Run all adapter tests together
2. Generate combined coverage report
3. Fix any failing tests
4. Document test patterns
5. Create quick reference guide

---

## Testing Patterns

### Mock Pattern
```python
@patch('mahavishnu.core.adapters.prefect_adapter.get_client')
async def test_execute_flow_with_mock(mock_get_client):
    # Setup mock
    mock_client = AsyncMock()
    mock_get_client.return_value.__aenter__.return_value = mock_client
    mock_flow_run = MagicMock()
    mock_flow_run.id = "test-run-id"
    mock_client.create_run.return_value = mock_flow_run
    mock_state = MagicMock()
    mock_state.is_completed.return_value = True
    mock_state.result.return_value = [{"status": "completed"}]
    mock_client.wait_for_flow_run.return_value = mock_state

    # Execute
    adapter = PrefectAdapter({})
    result = await adapter.execute_flow("test-flow", {})

    # Verify
    assert result["flow_run_id"] == "test-run-id"
    assert result["status"] == "completed"
```

### Parametrized Tests Pattern
```python
@pytest.mark.parametrize("state", [
    FlowRunState.COMPLETED,
    FlowRunState.FAILED,
    FlowRunState.CANCELLED,
])
async def test_monitor_flow_run_with_different_states(state):
    # Test with different states
```

### Async Context Manager Pattern
```python
@pytest.mark.asyncio
async def test_client_context_manager():
    adapter = PrefectAdapter({})
    # Test that get_client is used as async context manager
```

### Error Injection Pattern
```python
async def test_execute_with_connection_error():
    # Simulate connection error
    with patch('mahavishnu.core.adapters.prefect_adapter.get_client') as mock_get_client:
        mock_get_client.side_effect = ConnectionError("Connection failed")
        adapter = PrefectAdapter({})
        with pytest.raises(AdapterExecutionError):
            await adapter.execute({"type": "test"}, ["/fake/repo"])
```

---

## Success Criteria

- ✅ Prefect adapter: 80%+ test coverage
- ✅ Agno adapter: 80%+ test coverage
- ✅ All tests pass
- ✅ Error paths tested
- ✅ Integration with pools tested
- ✅ Health checks tested
- ✅ ImportError handling tested
- ✅ Mock patterns consistent
- ✅ Async tests properly marked
- ✅ Coverage report generated

---

## File Structure

```
tests/unit/test_adapters/
├── test_prefect_adapter.py        (45+ tests)
├── test_agno_adapter.py           (60+ tests)
└── __init__.py
```

---

## Notes

- All async tests must use `@pytest.mark.asyncio`
- Use `unittest.mock.AsyncMock` for async mocks
- Use `unittest.mock.MagicMock` for regular mocks
- Parametrize tests to reduce duplication
- Group related tests in classes
- Use descriptive test names
- Test both success and error paths
- Mock external dependencies (Prefect, Agno)
- Test stub implementations when libraries unavailable

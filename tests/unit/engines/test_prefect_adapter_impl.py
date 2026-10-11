"""Regression tests pinning the three Prefect adapter bugs fixed 2026-10-11.

Each test corresponds to one of the three bugs and would fail loudly if a
refactor reintroduced the old shape. See plan file
``dazzling-waddling-ullman`` (and the historical memory note
``prefect-adapter-bugs-2026-10-11``) for the original bug descriptions.

**Bug A** — ``client.wait_for_flow_run`` is no longer a PrefectClient method in
3.x; the function now lives at ``prefect.flow_runs.wait_for_flow_run`` and
returns a ``FlowRun`` whose ``.state`` is the State we probe. The adapter
calls it via the instance attribute ``adapter._wait_for_flow_run``.

**Bug B** — Prefect 3.x SDK returns ``datetime.timedelta`` for
``flow_run.total_run_time`` / ``estimated_run_time``; the Pydantic
``FlowRunResponse`` schema (declared ``float | None``) rejects it.

**Bug C** — ``PREFECT_API_URL`` env var is no longer gated on
``self.config.api_key``; URL routing is unconditional. Canonical form has
the ``/api`` suffix.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.engines.prefect_adapter_impl import (
    PrefectAdapter,
    _coerce_seconds,
    _flow_run_to_response,
)

# ---------------------------------------------------------------------------
# Bug A — wait_for_flow_run path + FlowRun.state unwrap
# ---------------------------------------------------------------------------


def test_wait_for_flow_run_module_alias_imports_prefect_flow_runs() -> None:
    """The ``_wait_for_flow_run_module`` symbol MUST resolve at the
    ``prefect.flow_runs`` import path — *not* at the top-level ``prefect``
    package. A reviewer running ``python -c 'from prefect import
    wait_for_flow_run'`` will get ``AttributeError`` in 3.8.8, exactly
    what the adapter used to do. Pin the import path."""
    import prefect

    from mahavishnu.engines import prefect_adapter_impl

    assert hasattr(prefect_adapter_impl, "_wait_for_flow_run_module")
    # Must NOT exist on the top-level prefect package.
    assert not hasattr(prefect, "wait_for_flow_run")
    # MUST exist on prefect.flow_runs.
    import prefect.flow_runs

    assert hasattr(prefect.flow_runs, "wait_for_flow_run")


def test_wait_for_flow_run_default_bound_to_module_alias() -> None:
    """A fresh ``PrefectAdapter`` instance must default
    ``_wait_for_flow_run`` to the top-level ``prefect.flow_runs.wait_for_flow_run``
    so production code never talks to a non-existent client method."""
    adapter = PrefectAdapter()
    from prefect.flow_runs import wait_for_flow_run

    assert adapter._wait_for_flow_run is wait_for_flow_run


async def test_execute_unwraps_poll_result_state_not_flow_run_directly() -> None:
    """Adapter.execute() must read ``polled_flow_run.state.is_completed()``
    and ``polled_flow_run.state.result()`` — never call those methods on
    the ``FlowRun`` returned by ``wait_for_flow_run`` directly."""
    from unittest.mock import MagicMock

    from mahavishnu.core.config import PrefectConfig

    config = PrefectConfig(api_url="http://localhost:4200", api_key=None)
    adapter = PrefectAdapter(config)
    await adapter.initialize()

    # Build a FlowRun-shaped mock whose .state is a separate State-shaped mock.
    completed_payload: list[dict] = [{"repo": "/r", "status": "completed"}]
    state_mock = MagicMock()
    state_mock.is_completed = MagicMock(return_value=True)
    state_mock.result = MagicMock(return_value=completed_payload)

    flow_run_mock = MagicMock()
    flow_run_mock.id = "poll-id-1"
    flow_run_mock.state = state_mock

    # Override the wait-for-flow-run callable.
    wait_mock = AsyncMock(return_value=flow_run_mock)
    adapter._wait_for_flow_run = wait_mock

    # _get_client_context is mocked to return a fake client whose
    # create_flow_run yields a flow_run response.
    fake_client = MagicMock()
    fake_client.api_url = "http://localhost:4200"
    fake_flow_run_response = MagicMock()
    fake_flow_run_response.id = "poll-id-1"
    fake_client.create_flow_run = AsyncMock(return_value=fake_flow_run_response)
    fake_client.wait_for_flow_run = MagicMock()  # should NOT be called
    # ApiUrl attribute read inside `response = {...}` for `flow_run_url`.
    fake_client.api_url = "http://localhost:4200"

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=fake_client)
    ctx.__aexit__ = AsyncMock(return_value=None)

    with patch.object(adapter, "_get_client_context", return_value=ctx):
        result = await adapter.execute({"id": "t1", "type": "default"}, ["/repo1"])

    # Adapter must have polled via the new top-level callable, not via the
    # client's (defunct) method.
    assert wait_mock.await_count >= 1
    assert not fake_client.wait_for_flow_run.called, (
        "the adapter must not call client.wait_for_flow_run anymore"
    )

    # The unwrap path must have invoked state.is_completed() / state.result(),
    # both of which were called exactly once.
    state_mock.is_completed.assert_called_once()
    state_mock.result.assert_called_once()
    assert result["status"] == "completed"
    assert result["flow_run_id"] == "poll-id-1"
    assert result["results"] == completed_payload

    await adapter.shutdown()


# ---------------------------------------------------------------------------
# Bug B — _coerce_seconds helper for timedelta / float / None
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (timedelta(seconds=2.5), 2.5),
        (timedelta(microseconds=68566), 0.068566),  # the live value from the demo
        (1.234, 1.234),
        (0, 0.0),
        (42, 42.0),
        ("1.5", None),  # strings FAIL CLOSED, not silently coerced
        (object(), None),  # unknown types FAIL CLOSED
        (datetime(2026, 10, 11, tzinfo=UTC), None),  # datetimes NOT seconds
    ],
)
def test_coerce_seconds_handles_all_prefect_shapes(value: object, expected: float | None) -> None:
    """Pin the four behaviour quadrants:
    - ``None`` → ``None`` (passthrough)
    - ``timedelta`` → float seconds via ``.total_seconds()``
    - ``int`` / ``float`` → exact float
    - anything else → ``None`` (fail-closed, NOT silently coerced)
    """
    assert _coerce_seconds(value) == expected


def test_flow_run_response_coerces_timedelta_durations() -> None:
    """End-to-end check: a ``flow_run`` mock whose ``total_run_time`` is a
    ``datetime.timedelta`` (Prefect 3.x shape) must convert cleanly via
    ``FlowRunResponse`` — the failure surface in the original bug report."""
    flow_run = MagicMock()
    flow_run.id = "fr-1"
    flow_run.name = "demo-flow"
    flow_run.created = datetime(2026, 10, 11, tzinfo=UTC)
    flow_run.updated = None
    flow_run.total_run_time = timedelta(seconds=12.5)
    flow_run.estimated_run_time = timedelta(seconds=14.0)

    state = MagicMock()
    state.type = "COMPLETED"
    state.name = "Completed"
    flow_run.state = state
    flow_run.flow_id = "flow-id"
    flow_run.deployment_id = None
    flow_run.parameters = {}
    flow_run.tags = []
    flow_run.start_time = None
    flow_run.end_time = None
    flow_run.work_queue_name = None

    response = _flow_run_to_response(flow_run)

    assert response.total_run_time_seconds == 12.5
    assert response.estimated_run_time_seconds == 14.0
    assert response.state_type == "COMPLETED"


# ---------------------------------------------------------------------------
# Bug C — PREFECT_API_URL swap is unconditional + uses /api suffix
# ---------------------------------------------------------------------------


def test_api_key_env_swaps_url_even_when_api_key_is_none() -> None:
    """Bug C regression: ``_api_key_env`` (called from
    ``_get_client_context``) MUST populate ``PREFECT_API_URL`` even when
    ``api_key is None``. Otherwise the SDK silently falls back to
    ephemeral mode on :8285.
    """
    # Confirm the precondition via an env-state probe.
    os.environ.pop("PREFECT_API_URL", None)

    from mahavishnu.core.config import PrefectConfig

    config = PrefectConfig(api_url="http://localhost:4200", api_key=None)
    adapter = PrefectAdapter(config)

    # Capture env state during the yield, then verify the env var is
    # restored on exit (Bug C regression: previously the swap was gated on
    # api_key presence, so a local-server user with no API key would silently
    # fall back to ephemeral :8285 mode).
    observed: dict[str, object] = {}
    sentinel = object()
    with adapter._api_key_env():
        observed["inside_url"] = os.environ.get("PREFECT_API_URL", sentinel)
        observed["inside_key"] = os.environ.get("PREFECT_API_KEY", sentinel)

    assert observed["inside_url"] == "http://localhost:4200/api", (
        "Bug C regression: PREFECT_API_URL was not set during _api_key_env "
        "when api_key is None. The SDK would fall back to ephemeral mode."
    )
    # PREFECT_API_KEY should NOT be present (api_key was None).
    assert observed["inside_key"] is sentinel, (
        "PREFECT_API_KEY must not be populated when config.api_key is None."
    )
    # Outside the context the env var is removed.
    assert "PREFECT_API_URL" not in os.environ


def test_api_key_env_canonicalizes_api_suffix_when_already_present() -> None:
    """If config ``api_url`` already ends in ``/api``, the env var must
    stay that way (idempotent — do NOT double-suffix)."""
    from mahavishnu.core.config import PrefectConfig

    config = PrefectConfig(api_url="http://localhost:4200/api", api_key=None)
    adapter = PrefectAdapter(config)

    cm = adapter._api_key_env()
    cm.__enter__()
    try:
        assert os.environ.get("PREFECT_API_URL") == "http://localhost:4200/api"
    finally:
        cm.__exit__(None, None, None)


def test_api_key_env_canonicalizes_api_suffix_from_bare_host() -> None:
    """If config ``api_url`` ends WITHOUT ``/api`` (the most common shape
    in ``PrefectConfig`` defaults), the env var MUST add the suffix so
    ``prefect.client.get_client()`` resolves to the API base."""
    from mahavishnu.core.config import PrefectConfig

    config = PrefectConfig(api_url="http://localhost:4200", api_key=None)
    adapter = PrefectAdapter(config)

    cm = adapter._api_key_env()
    cm.__enter__()
    try:
        assert os.environ.get("PREFECT_API_URL") == "http://localhost:4200/api"
    finally:
        cm.__exit__(None, None, None)


def test_api_key_env_restores_prior_value_on_exit() -> None:
    """Even when we mutate the env, on context exit we restore the
    previous value (or delete if no prior value). Prevents test
    pollution across test instances."""
    # Pre-set a known value.
    os.environ["PREFECT_API_URL"] = "http://prior:4200/api"

    from mahavishnu.core.config import PrefectConfig

    config = PrefectConfig(api_url="http://localhost:4200", api_key=None)
    adapter = PrefectAdapter(config)

    with adapter._api_key_env():
        assert os.environ["PREFECT_API_URL"] == "http://localhost:4200/api"

    assert os.environ["PREFECT_API_URL"] == "http://prior:4200/api"

    # Cleanup the pre-set value so other tests aren't polluted.
    del os.environ["PREFECT_API_URL"]


def test_api_key_env_deletes_when_no_prior_value() -> None:
    """If no prior ``PREFECT_API_URL`` was set, the env var must be
    deleted on exit — never silently leak the assigned value."""
    os.environ.pop("PREFECT_API_URL", None)

    from mahavishnu.core.config import PrefectConfig

    config = PrefectConfig(api_url="http://localhost:4200", api_key=None)
    adapter = PrefectAdapter(config)

    with adapter._api_key_env():
        assert "PREFECT_API_URL" in os.environ
    assert "PREFECT_API_URL" not in os.environ

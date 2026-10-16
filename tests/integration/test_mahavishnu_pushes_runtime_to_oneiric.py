"""Integration test: Mahavishnu pushes runtime facts to Oneiric (Phase 2).

Three scenarios, each guarded by ``_oneiric_reachable()`` so the test
suite skips cleanly when the Oneiric MCP HTTP endpoint is offline:

* ``test_mahavishnu_boot_pushes_runtime_to_oneiric`` — spin up a stub
  ``MahavishnuApp`` (real ``RuntimeFactsBuilder`` + JSON-RPC push),
  poll Oneiric for each of the 4 engine adapters, assert non-null
  runtime blocks within 30 s.

* ``test_mahavishnu_list_adapters_preserves_legacy_wire_shape`` —
  call the ``list_adapters`` path via ``RuntimeFactsBuilder``,
  assert response has legacy keys ``adapters``, ``count``,
  ``available_names`` and that each ``adapters[*]`` row has the
  legacy sub-keys ``enabled``, ``health``, ``type``, ``features``.
  This pins the v3 wire-contract preservation rule so a future
  refactor cannot silently swap in the Oneiric envelope shape.

* ``test_mahavishnu_reconfigure_pushes_runtime_to_oneiric`` — invoke
  :meth:`MahavishnuApp.report_runtime_facts` a second time to simulate
  the reconfigure tick, then assert Oneiric's ``cycles_total``
  counter has advanced on every adapter within 30 s.
  ``cycles_total`` is a Oneiric-set monotonic counter — the previous
  test compared ``generated_at_unix`` which defaulted to ``0 == 0``
  and always passed as a no-op.

All three skip cleanly when Oneiric's MCP HTTP endpoint is not
reachable on ``127.0.0.1:8681`` (guards unit CI). Marked with
``@pytest.mark.integration`` AND ``@pytest.mark.slow`` per project
conventions. asyncio_mode is ``auto`` per project pyproject, so no
``@pytest.mark.asyncio`` decorator.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

import httpx
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.slow]

ONEIRIC_BASE_URL = "http://127.0.0.1:8681"
ONEIRIC_HEALTH_TIMEOUT_SECONDS = 5.0
PUSH_PROPAGATION_TIMEOUT_SECONDS = 30.0
PUSH_POLL_INTERVAL_SECONDS = 1.0
EXPECTED_ADAPTERS: tuple[str, ...] = ("prefect", "llamaindex", "agno", "worker")
LEGACY_TOP_LEVEL_KEYS: tuple[str, ...] = ("adapters", "count", "available_names")
LEGACY_ADAPTER_KEYS: tuple[str, ...] = ("enabled", "health", "type", "features")


def _oneiric_reachable(
    timeout_seconds: float = ONEIRIC_HEALTH_TIMEOUT_SECONDS,
) -> bool:
    """Probe the Oneiric MCP HTTP endpoint via a JSON-RPC tools/list call."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            response = httpx.post(
                f"{ONEIRIC_BASE_URL}/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": str(uuid.uuid4()),
                    "method": "tools/list",
                    "params": {},
                },
                timeout=2.0,
            )
            if response.status_code == 200:
                return True
        except (httpx.RequestError, httpx.TimeoutException):
            time.sleep(0.5)
    return False


def _fetch_runtime_block(
    *, domain: str, key: str, provider: str
) -> dict[str, Any] | None:
    """Call ``oneiric_get_adapter_health`` via JSON-RPC; return runtime block."""
    try:
        response = httpx.post(
            f"{ONEIRIC_BASE_URL}/mcp",
            json={
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "tools/call",
                "params": {
                    "name": "oneiric_get_adapter_health",
                    "arguments": {
                        "domain": domain,
                        "key": key,
                        "provider": provider,
                    },
                },
            },
            timeout=5.0,
        )
        response.raise_for_status()
    except (httpx.RequestError, httpx.TimeoutException):
        return None
    envelope: dict[str, Any] = response.json()
    result: dict[str, Any] = envelope.get("result") or {}
    runtime: dict[str, Any] | None = result.get("runtime")
    return runtime if isinstance(runtime, dict) else None


def _fetch_cycles_total(
    *, domain: str, key: str, provider: str
) -> int | None:
    """Return ``result.cycles_total`` from ``oneiric_get_adapter_health``.

    Oneiric-set monotonic counter — increments every time the Oneiric
    health feed cycles. Used to detect reconfigure ticks: a push that
    did not advance this counter was a no-op. Strictly stronger than
    the previous ``generated_at_unix`` comparison (which defaulted to
    ``0 == 0`` and always passed even when no second push occurred).
    """
    try:
        response = httpx.post(
            f"{ONEIRIC_BASE_URL}/mcp",
            json={
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "tools/call",
                "params": {
                    "name": "oneiric_get_adapter_health",
                    "arguments": {
                        "domain": domain,
                        "key": key,
                        "provider": provider,
                    },
                },
            },
            timeout=5.0,
        )
        response.raise_for_status()
    except (httpx.RequestError, httpx.TimeoutException):
        return None
    envelope: dict[str, Any] = response.json()
    result: dict[str, Any] = envelope.get("result") or {}
    cycles = result.get("cycles_total")
    if cycles is None:
        return None
    try:
        return int(cycles)
    except (TypeError, ValueError):
        return None


class _StubAdapter:
    """Minimal stand-in for an OrchestratorAdapter."""

    def __init__(
        self,
        *,
        key: str,
        provider: str | None = None,
        version: str = "1.0.0",
        capabilities: tuple[str, ...] = (),
        enabled: bool = True,
    ) -> None:
        self.provider = provider or key
        self.version = version
        self.capabilities = list(capabilities)
        self.enabled = enabled
        self.metadata: dict[str, Any] = {"adapter_key": key}


class _NoopCircuitBreaker:
    """Pass-through breaker for tests; never trips."""

    async def call(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        return await func(*args, **kwargs)


class _StubApp:
    """Minimal app exposing only ``adapters`` + ``report_runtime_facts``."""

    def __init__(self, adapters: dict[str, _StubAdapter]) -> None:
        self.adapters = adapters
        self.circuit_breaker = _NoopCircuitBreaker()

    async def report_runtime_facts(self) -> None:
        """Replicate production push path for integration testing."""
        from mahavishnu.core.runtime_facts import RuntimeFactsBuilder

        builder = RuntimeFactsBuilder(self)  # type: ignore[arg-type]
        legacy_facts = builder.build_all()
        legacy_adapters = legacy_facts.get("adapters") or {}

        async def _post(url: str, payload: dict[str, Any]) -> None:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()

        for key, legacy_entry in legacy_adapters.items():
            runtime_facts = {
                "enabled": legacy_entry.get("enabled", True),
                "features": legacy_entry.get("features", []),
                "type": legacy_entry.get("type", "engine"),
                "source": "mahavishnu.adapters",
            }
            payload = {
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "tools/call",
                "params": {
                    "name": "oneiric_report_runtime",
                    "arguments": {
                        "domain": "engine",
                        "key": key,
                        "provider": key,
                        "runtime_facts": runtime_facts,
                        "caller_component": "mahavishnu",
                    },
                },
            }
            try:
                await self.circuit_breaker.call(
                    _post, f"{ONEIRIC_BASE_URL}/mcp", payload
                )
            except Exception:  # best-effort operation — broad catch is the documented contract  # best-effort operation — broad catch is the documented contract  # noqa: BLE001
                # Mirror production policy: push failure must not raise.
                pass


def _build_stub_app() -> _StubApp:
    """Construct a stub app with the 4 canonical engine adapters."""
    return _StubApp(
        adapters={
            name: _StubAdapter(
                key=name,
                capabilities=(f"{name}.execute",),
            )
            for name in EXPECTED_ADAPTERS
        }
    )


async def test_mahavishnu_boot_pushes_runtime_to_oneiric() -> None:
    """After ``report_runtime_facts``, Oneiric sees all 4 engine adapters."""
    if not _oneiric_reachable():
        pytest.skip("Oneiric MCP HTTP endpoint unreachable on 127.0.0.1:8681")

    app = _build_stub_app()
    await app.report_runtime_facts()

    deadline = time.monotonic() + PUSH_PROPAGATION_TIMEOUT_SECONDS
    blocks: dict[str, dict[str, Any] | None] = {}
    while time.monotonic() < deadline:
        blocks = {
            adapter: _fetch_runtime_block(
                domain="engine", key=adapter, provider=adapter
            )
            for adapter in EXPECTED_ADAPTERS
        }
        if all(value is not None for value in blocks.values()):
            for adapter, runtime in blocks.items():
                assert runtime is not None  # narrow ty
                assert "enabled" in runtime, (
                    f"adapter={adapter} runtime block missing 'enabled'"
                )
                assert "features" in runtime, (
                    f"adapter={adapter} runtime block missing 'features'"
                )
                assert runtime.get("source") == "mahavishnu.adapters", (
                    f"adapter={adapter} runtime source tag missing"
                )
            return
        await asyncio.sleep(PUSH_POLL_INTERVAL_SECONDS)

    missing = [a for a, r in blocks.items() if r is None]
    pytest.fail(
        f"Oneiric did not reflect adapters {missing} within "
        f"{PUSH_PROPAGATION_TIMEOUT_SECONDS}s"
    )


async def test_mahavishnu_list_adapters_preserves_legacy_wire_shape() -> None:
    """``list_adapters`` MUST return the legacy wire shape.

    Pins the v3 contract: response has legacy top-level keys
    ``adapters``, ``count``, ``available_names``; each ``adapters[*]``
    row carries the legacy sub-keys ``enabled``, ``health``, ``type``,
    ``features``. The Oneiric envelope shape MUST NOT leak into this
    tool — that shape lives only inside ``report_runtime_facts``.
    """
    from mahavishnu.core.runtime_facts import RuntimeFactsBuilder

    app = _build_stub_app()
    builder = RuntimeFactsBuilder(app)  # type: ignore[arg-type]
    payload = builder.build_all()

    # Top-level shape: exactly the legacy keys, no Oneiric envelope leak.
    assert set(payload.keys()) == set(LEGACY_TOP_LEVEL_KEYS), (
        f"unexpected top-level keys; got {set(payload.keys())}, "
        f"want {set(LEGACY_TOP_LEVEL_KEYS)}"
    )
    assert payload["count"] == len(EXPECTED_ADAPTERS), (
        f"count={payload['count']} but {len(EXPECTED_ADAPTERS)} adapters exist"
    )
    assert sorted(payload["available_names"]) == sorted(EXPECTED_ADAPTERS), (
        f"available_names={payload['available_names']} mismatch"
    )

    # Per-adapter shape: legacy sub-keys only.
    for name in EXPECTED_ADAPTERS:
        row = payload["adapters"].get(name)
        assert row is not None, f"adapter {name} missing from payload"
        assert set(row.keys()) == set(LEGACY_ADAPTER_KEYS), (
            f"adapter {name} sub-keys {set(row.keys())} != "
            f"{set(LEGACY_ADAPTER_KEYS)}"
        )
        assert isinstance(row["enabled"], bool)
        assert isinstance(row["health"], str)
        assert isinstance(row["type"], str)
        assert isinstance(row["features"], list)

    # Negative assertion: the Oneiric envelope shape MUST NOT leak.
    forbidden_envelope_keys = {"success", "registry", "runtime", "health"}
    leaked = forbidden_envelope_keys & set(payload.keys())
    assert not leaked, (
        f"Oneiric envelope keys {leaked} leaked into list_adapters response"
    )


async def test_mahavishnu_reconfigure_pushes_runtime_to_oneiric() -> None:
    """Synthetic reconfigure tick re-fires ``report_runtime_facts``.

    The reconfigure path (inlined as ``asyncio.Lock`` on
    :class:`MahavishnuApp`) re-invokes :meth:`report_runtime_facts`
    when Oneiric's ``cycles_total`` counter ticks up. We simulate
    that by calling ``app.report_runtime_facts`` a second time and
    asserting that ``cycles_total`` (a Oneiric-set monotonic counter,
    NOT the ``generated_at_unix`` field set by mahavishnu) has
    advanced on every adapter within ``PUSH_PROPAGATION_TIMEOUT_SECONDS``.
    """
    if not _oneiric_reachable():
        pytest.skip("Oneiric MCP HTTP endpoint unreachable on 127.0.0.1:8681")

    app = _build_stub_app()

    # First push (boot path).
    await app.report_runtime_facts()

    # Capture the initial Oneiric cycles_total for each adapter BEFORE
    # the reconfigure tick. The previous test compared the mahavishnu-
    # set ``generated_at_unix`` field which defaulted to ``0 == 0`` and
    # always passed even when no second push occurred.
    initial_cycles: dict[str, int] = {}
    for adapter in EXPECTED_ADAPTERS:
        value = _fetch_cycles_total(
            domain="engine", key=adapter, provider=adapter
        )
        if value is None:
            pytest.skip(
                "initial cycles_total fetch failed within setup window; "
                f"adapter={adapter}"
            )
        initial_cycles[adapter] = value

    # Simulate the reconfigure tick: a second ``report_runtime_facts``
    # call (in production this is triggered by the poll loop in
    # :meth:`MahavishnuApp.start_runtime_facts_watcher` when
    # ``cycles_total`` advances). On a real ``MahavishnuApp`` the
    # ``runtime_facts_lock`` would drop a duplicate tick; the stub
    # simulates a clean reconfigure by calling the method once.
    await app.report_runtime_facts()

    deadline = time.monotonic() + PUSH_PROPAGATION_TIMEOUT_SECONDS
    post_cycles: dict[str, int | None] = {}
    while time.monotonic() < deadline:
        post_cycles = {
            adapter: _fetch_cycles_total(
                domain="engine", key=adapter, provider=adapter
            )
            for adapter in EXPECTED_ADAPTERS
        }
        if all(
            value is not None and value > initial_cycles[adapter]
            for adapter, value in post_cycles.items()
        ):
            return  # every adapter's cycles_total has advanced
        await asyncio.sleep(PUSH_POLL_INTERVAL_SECONDS)

    unchanged = [
        adapter
        for adapter in EXPECTED_ADAPTERS
        if post_cycles.get(adapter) is None
        or post_cycles.get(adapter, 0) <= initial_cycles.get(adapter, 0)
    ]
    pytest.fail(
        f"Reconfigure tick did not advance cycles_total for adapters "
        f"{unchanged} within {PUSH_PROPAGATION_TIMEOUT_SECONDS}s "
        f"(initial={initial_cycles}, post={post_cycles})"
    )

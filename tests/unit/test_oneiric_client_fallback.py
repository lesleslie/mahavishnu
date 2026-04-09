"""Coverage-focused tests for oneiric_client without oneiric_mcp installed."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

import mahavishnu.core.oneiric_client as oc


class _FakeChannel:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _FakeStub:
    def __init__(self, _channel) -> None:  # noqa: ANN001
        self.list_calls: list[tuple[object, int]] = []
        self.get_calls: list[tuple[object, int]] = []
        self.health_calls: list[tuple[object, int]] = []
        self.heartbeat_calls: list[tuple[object, int]] = []

    async def ListAdapters(self, request, timeout: int):  # noqa: ANN001
        self.list_calls.append((request, timeout))
        pb = SimpleNamespace(
            adapter_id="mahavishnu.adapter.storage.local",
            project="mahavishnu",
            domain="adapter",
            category="storage",
            provider="local",
            capabilities=["read", "write"],
            factory_path="x.y.Z",
            health_check_url="",
            metadata={"a": "b"},
            registered_at=1,
            last_heartbeat=2,
            health_status="healthy",
        )
        return SimpleNamespace(adapters=[pb])

    async def GetAdapter(self, request, timeout: int):  # noqa: ANN001
        self.get_calls.append((request, timeout))
        pb = SimpleNamespace(
            adapter_id=request.adapter_id,
            project="mahavishnu",
            domain="adapter",
            category="storage",
            provider="local",
            capabilities=["read"],
            factory_path="x.y.Z",
            health_check_url="",
            metadata={},
            registered_at=1,
            last_heartbeat=2,
            health_status="healthy",
        )
        return SimpleNamespace(adapter=pb)

    async def HealthCheck(self, request, timeout: int):  # noqa: ANN001
        self.health_calls.append((request, timeout))
        return SimpleNamespace(healthy=True)

    async def Heartbeat(self, request, timeout: int):  # noqa: ANN001
        self.heartbeat_calls.append((request, timeout))
        return SimpleNamespace(registered=True)


def _patch_fake_grpc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(oc, "ONEIRIC_MCP_AVAILABLE", True)

    oc.registry_pb2 = SimpleNamespace(  # type: ignore[attr-defined]
        ListRequest=lambda **kwargs: SimpleNamespace(**kwargs),
        GetRequest=lambda **kwargs: SimpleNamespace(**kwargs),
        HealthCheckRequest=lambda **kwargs: SimpleNamespace(**kwargs),
        HeartbeatRequest=lambda **kwargs: SimpleNamespace(**kwargs),
    )
    oc.registry_pb2_grpc = SimpleNamespace(AdapterRegistryStub=_FakeStub)  # type: ignore[attr-defined]

    async def _ready(_channel, timeout: int):  # noqa: ANN001
        return None

    monkeypatch.setattr(oc.grpc.aio, "insecure_channel", lambda _target: _FakeChannel())
    monkeypatch.setattr(oc.grpc.aio, "wait_for_channel_ready", _ready, raising=False)


class _RpcError(Exception):
    def __init__(self, code, details: str) -> None:  # noqa: ANN001
        super().__init__(details)
        self._code = code
        self._details = details

    def code(self):  # noqa: ANN201
        return self._code

    def details(self) -> str:
        return self._details


def test_get_and_set_dhara_client_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[str] = []

    class _DharaClient:
        def __init__(self, base_url: str) -> None:
            created.append(base_url)
            self.base_url = base_url

    monkeypatch.setattr("mahavishnu.core.dhara_adapter.DharaClient", _DharaClient, raising=False)
    oc._dhara_clients.clear()

    oc.set_dhara_client_base_url("http://example:9999/mcp/")
    c1 = oc.get_dhara_client()
    c2 = oc.get_dhara_client("http://example:9999/mcp")
    c3 = oc.get_dhara_client("http://other:8683/mcp")

    assert c1 is c2
    assert c1 is not c3
    assert created == ["http://example:9999/mcp", "http://other:8683/mcp"]


def test_adapter_entry_from_pb2_and_to_dict() -> None:
    pb = SimpleNamespace(
        adapter_id="a",
        project="p",
        domain="d",
        category="c",
        provider="prov",
        capabilities=("x", "y"),
        factory_path="f",
        health_check_url="",
        metadata={"k": "v"},
        registered_at=10,
        last_heartbeat=20,
        health_status="healthy",
    )
    entry = oc.AdapterEntry.from_pb2(pb)
    out = entry.to_dict()
    assert entry.health_check_url is None
    assert out["adapter_id"] == "a"
    assert out["metadata"] == {"k": "v"}
    assert out["registered_at"] is not None
    assert out["last_heartbeat"] is not None


@pytest.mark.asyncio
async def test_circuit_breaker_block_and_reset() -> None:
    breaker = oc.AdapterCircuitBreaker(failure_threshold=2, block_duration_sec=1)
    assert await breaker.is_available("a")
    await breaker.record_failure("a")
    assert await breaker.is_available("a")
    await breaker.record_failure("a")
    assert not await breaker.is_available("a")
    await breaker.record_success("a")
    assert await breaker.is_available("a")

    breaker.blocked_until["b"] = datetime.now(UTC) - timedelta(seconds=1)
    breaker.failures["b"] = 9
    assert await breaker.is_available("b")
    assert "b" not in breaker.failures


def test_client_init_raises_when_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(oc, "ONEIRIC_MCP_AVAILABLE", False)
    with pytest.raises(ImportError):
        oc.OneiricMCPClient()


@pytest.mark.asyncio
async def test_client_happy_path_and_disabled_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_fake_grpc(monkeypatch)
    client = oc.OneiricMCPClient(oc.OneiricMCPConfig(enabled=True, cache_ttl_sec=120))

    assert client._make_cache_key("p", "d", "c", True) == "p:d:c:healthy"
    await client._ensure_connected()
    assert client._connected is True

    adapters_1 = await client.list_adapters(project="p", domain="d", category="c", healthy_only=True)
    adapters_2 = await client.list_adapters(project="p", domain="d", category="c", healthy_only=True)
    assert len(adapters_1) == 1
    assert adapters_1 == adapters_2

    adapter = await client.get_adapter("mahavishnu.adapter.storage.local")
    assert adapter is not None
    assert await client.check_adapter_health("mahavishnu.adapter.storage.local") is True
    assert (
        await client.resolve_adapter(
            domain="adapter", category="storage", provider="local", project="mahavishnu"
        )
    ) is not None
    assert (
        await client.resolve_adapter(
            domain="adapter", category="storage", provider="missing", project="mahavishnu"
        )
    ) is None
    assert await client.send_heartbeat("mahavishnu.adapter.storage.local") is True

    await client.invalidate_cache()
    assert client._cache == {}

    health = await client.health_check()
    assert health["status"] == "healthy"
    assert health["connected"] is True

    await client.close()
    assert client._connected is False

    # Disabled config branches
    disabled = oc.OneiricMCPClient(oc.OneiricMCPConfig(enabled=False))
    assert await disabled.list_adapters() == []
    assert await disabled.get_adapter("x") is None
    assert await disabled.check_adapter_health("x") is False
    assert await disabled.send_heartbeat("x") is False
    assert await disabled.health_check() == {"status": "disabled", "connected": False}


@pytest.mark.asyncio
async def test_oneiric_client_error_and_tls_branches(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # noqa: ANN001
    _patch_fake_grpc(monkeypatch)
    monkeypatch.setattr(oc.grpc.aio, "AioRpcError", _RpcError, raising=False)

    # Build TLS files and patch secure channel + credentials helpers
    cert = tmp_path / "c.pem"
    key = tmp_path / "k.pem"
    ca = tmp_path / "ca.pem"
    cert.write_bytes(b"cert")
    key.write_bytes(b"key")
    ca.write_bytes(b"ca")

    creds_calls: list[dict] = []
    monkeypatch.setattr(
        oc.grpc, "ssl_channel_credentials", lambda **kwargs: creds_calls.append(kwargs) or object()
    )
    monkeypatch.setattr(oc.grpc.aio, "secure_channel", lambda _target, _creds: _FakeChannel())

    cfg = oc.OneiricMCPConfig(
        enabled=True,
        use_tls=True,
        tls_cert_path=str(cert),
        tls_key_path=str(key),
        tls_ca_path=str(ca),
    )
    client = oc.OneiricMCPClient(cfg)
    await client._ensure_connected()
    assert creds_calls and "root_certificates" in creds_calls[0]

    # Timeout branch in _ensure_connected
    async def _timeout(_channel, timeout: int):  # noqa: ANN001
        raise TimeoutError("nope")

    client2 = oc.OneiricMCPClient(
        oc.OneiricMCPConfig(enabled=True, use_tls=False, grpc_port=9000)
    )
    monkeypatch.setattr(oc.grpc.aio, "wait_for_channel_ready", _timeout, raising=False)
    with pytest.raises(ConnectionError):
        await client2._ensure_connected()

    # TLS enabled without certs
    client3 = oc.OneiricMCPClient(oc.OneiricMCPConfig(enabled=True, use_tls=True))
    with pytest.raises(ValueError):
        await client3._ensure_connected()

    # Cache expiry branch + ListAdapters UNAVAILABLE error
    _patch_fake_grpc(monkeypatch)
    monkeypatch.setattr(oc.grpc.aio, "AioRpcError", _RpcError, raising=False)
    client4 = oc.OneiricMCPClient(oc.OneiricMCPConfig(enabled=True, cache_ttl_sec=0))
    await client4._ensure_connected()
    client4._cache["*:*:*:all"] = ([SimpleNamespace()], datetime.now(UTC) - timedelta(seconds=10))

    async def list_unavailable(request, timeout: int):  # noqa: ANN001
        raise _RpcError(oc.grpc.StatusCode.UNAVAILABLE, "down")

    client4._stub.ListAdapters = list_unavailable
    with pytest.raises(ConnectionError):
        await client4.list_adapters()

    # get_adapter: blocked by circuit breaker then RPC error paths
    client5 = oc.OneiricMCPClient(oc.OneiricMCPConfig(enabled=True))
    await client5._ensure_connected()
    client5._circuit_breaker.blocked_until["a"] = datetime.now(UTC) + timedelta(seconds=60)
    assert await client5.get_adapter("a") is None
    assert await client5.check_adapter_health("a") is False

    async def get_not_found(request, timeout: int):  # noqa: ANN001
        raise _RpcError(oc.grpc.StatusCode.NOT_FOUND, "nf")

    client5._stub.GetAdapter = get_not_found
    assert await client5.get_adapter("x") is None

    async def get_other(request, timeout: int):  # noqa: ANN001
        raise _RpcError(oc.grpc.StatusCode.PERMISSION_DENIED, "denied")

    client5._stub.GetAdapter = get_other
    assert await client5.get_adapter("x") is None

    async def get_exc(request, timeout: int):  # noqa: ANN001
        raise RuntimeError("boom")

    client5._stub.GetAdapter = get_exc
    assert await client5.get_adapter("x") is None

    # health check RPC error + generic exception branches
    async def h_unavailable(request, timeout: int):  # noqa: ANN001
        raise _RpcError(oc.grpc.StatusCode.UNAVAILABLE, "down")

    client5._stub.HealthCheck = h_unavailable
    with pytest.raises(ConnectionError):
        await client5.check_adapter_health("x")

    async def h_other(request, timeout: int):  # noqa: ANN001
        raise _RpcError(oc.grpc.StatusCode.PERMISSION_DENIED, "denied")

    client5._stub.HealthCheck = h_other
    assert await client5.check_adapter_health("x") is False

    async def h_exc(request, timeout: int):  # noqa: ANN001
        raise RuntimeError("err")

    client5._stub.HealthCheck = h_exc
    assert await client5.check_adapter_health("x") is False

    # heartbeat error paths
    async def hb_unavailable(request, timeout: int):  # noqa: ANN001
        raise _RpcError(oc.grpc.StatusCode.UNAVAILABLE, "down")

    client5._connected = True
    client5._stub.Heartbeat = hb_unavailable
    with pytest.raises(ConnectionError):
        await client5.send_heartbeat("x")

    async def hb_other(request, timeout: int):  # noqa: ANN001
        raise _RpcError(oc.grpc.StatusCode.PERMISSION_DENIED, "denied")

    client5._connected = True
    client5._stub.Heartbeat = hb_other
    assert await client5.send_heartbeat("x") is False

    async def hb_exc(request, timeout: int):  # noqa: ANN001
        raise RuntimeError("err")

    client5._connected = True
    client5._stub.Heartbeat = hb_exc
    assert await client5.send_heartbeat("x") is False

    # health_check exception branch
    async def bad_list(*args, **kwargs):  # noqa: ANN002,ANN003
        raise RuntimeError("list fail")

    client5.list_adapters = bad_list  # type: ignore[method-assign]
    out = await client5.health_check()
    assert out["status"] == "unhealthy"


@pytest.mark.asyncio
async def test_oneiric_client_additional_branch_coverage(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # noqa: ANN001
    _patch_fake_grpc(monkeypatch)
    monkeypatch.setattr(oc.grpc.aio, "AioRpcError", _RpcError, raising=False)

    # TLS without CA path uses the non-mTLS credentials branch.
    cert = tmp_path / "c.pem"
    key = tmp_path / "k.pem"
    cert.write_bytes(b"cert")
    key.write_bytes(b"key")
    tls_calls: list[dict] = []
    monkeypatch.setattr(
        oc.grpc,
        "ssl_channel_credentials",
        lambda **kwargs: tls_calls.append(kwargs) or object(),
    )
    monkeypatch.setattr(oc.grpc.aio, "secure_channel", lambda _target, _creds: _FakeChannel())
    tls_client = oc.OneiricMCPClient(
        oc.OneiricMCPConfig(
            enabled=True,
            use_tls=True,
            tls_cert_path=str(cert),
            tls_key_path=str(key),
        )
    )
    await tls_client._ensure_connected()
    assert tls_calls and "root_certificates" not in tls_calls[0]

    # _ensure_connected close-existing-channel and early-return branches.
    reconnect_client = oc.OneiricMCPClient(oc.OneiricMCPConfig(enabled=True))
    reconnect_client._channel = _FakeChannel()
    reconnect_client._connected = False
    await reconnect_client._ensure_connected()
    assert reconnect_client._channel is not None
    assert reconnect_client._connected is True
    await reconnect_client._ensure_connected()

    class _LateConnectLock:
        def __init__(self, client) -> None:  # noqa: ANN001
            self.client = client

        async def __aenter__(self):
            self.client._connected = True
            return self

        async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001
            return False

    late_client = oc.OneiricMCPClient(oc.OneiricMCPConfig(enabled=True))
    late_client._channel = _FakeChannel()
    late_client._connected = False
    late_client._lock = _LateConnectLock(late_client)  # type: ignore[assignment]
    await late_client._ensure_connected()

    # list_adapters generic exception branch.
    error_client = oc.OneiricMCPClient(oc.OneiricMCPConfig(enabled=True))
    error_client._channel = _FakeChannel()
    error_client._connected = True
    error_client._stub = _FakeStub(error_client._channel)

    async def list_other(request, timeout: int):  # noqa: ANN001
        raise _RpcError(oc.grpc.StatusCode.PERMISSION_DENIED, "denied")

    error_client._stub.ListAdapters = list_other
    with pytest.raises(Exception):
        await error_client.list_adapters(use_cache=False)

    async def list_generic(request, timeout: int):  # noqa: ANN001
        raise RuntimeError("boom")

    error_client._stub.ListAdapters = list_generic
    with pytest.raises(RuntimeError):
        await error_client.list_adapters(use_cache=False)

    # get_adapter UNAVAILABLE and other error branches.
    async def get_unavailable(request, timeout: int):  # noqa: ANN001
        raise _RpcError(oc.grpc.StatusCode.UNAVAILABLE, "down")

    error_client._stub.GetAdapter = get_unavailable
    with pytest.raises(ConnectionError):
        await error_client.get_adapter("x")

    error_client._connected = True
    error_client._channel = _FakeChannel()

    async def get_other(request, timeout: int):  # noqa: ANN001
        raise _RpcError(oc.grpc.StatusCode.PERMISSION_DENIED, "denied")

    error_client._stub.GetAdapter = get_other
    assert await error_client.get_adapter("x") is None

    error_client._connected = True
    error_client._channel = _FakeChannel()

    async def get_generic(request, timeout: int):  # noqa: ANN001
        raise RuntimeError("boom")

    error_client._stub.GetAdapter = get_generic
    assert await error_client.get_adapter("x") is None

    # check_adapter_health false / rpc error / generic exception branches.
    health_client = oc.OneiricMCPClient(oc.OneiricMCPConfig(enabled=True))
    health_client._channel = _FakeChannel()
    health_client._connected = True
    health_client._stub = _FakeStub(health_client._channel)

    async def health_false(request, timeout: int):  # noqa: ANN001
        return SimpleNamespace(healthy=False)

    health_client._stub.HealthCheck = health_false
    assert await health_client.check_adapter_health("x") is False

    health_client._connected = True
    health_client._channel = _FakeChannel()

    async def health_other(request, timeout: int):  # noqa: ANN001
        raise _RpcError(oc.grpc.StatusCode.PERMISSION_DENIED, "denied")

    health_client._stub.HealthCheck = health_other
    assert await health_client.check_adapter_health("y") is False

    health_client._connected = True
    health_client._channel = _FakeChannel()

    async def health_generic(request, timeout: int):  # noqa: ANN001
        raise RuntimeError("boom")

    health_client._stub.HealthCheck = health_generic
    assert await health_client.check_adapter_health("z") is False

    # close branch
    close_client = oc.OneiricMCPClient(oc.OneiricMCPConfig(enabled=True))
    close_client._channel = _FakeChannel()
    await close_client.close()
    assert close_client._connected is False


def test_oneiric_mcp_import_success_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib
    import sys
    from types import ModuleType

    fake_registry = ModuleType("oneiric_mcp.grpc.registry_pb2")
    fake_registry_grpc = ModuleType("oneiric_mcp.grpc.registry_pb2_grpc")
    fake_grpc_pkg = ModuleType("oneiric_mcp.grpc")
    fake_grpc_pkg.registry_pb2 = fake_registry
    fake_grpc_pkg.registry_pb2_grpc = fake_registry_grpc

    fake_root = ModuleType("oneiric_mcp")
    fake_root.grpc = fake_grpc_pkg

    monkeypatch.setitem(sys.modules, "oneiric_mcp", fake_root)
    monkeypatch.setitem(sys.modules, "oneiric_mcp.grpc", fake_grpc_pkg)
    monkeypatch.setitem(sys.modules, "oneiric_mcp.grpc.registry_pb2", fake_registry)
    monkeypatch.setitem(sys.modules, "oneiric_mcp.grpc.registry_pb2_grpc", fake_registry_grpc)

    reloaded = importlib.reload(oc)
    assert reloaded.ONEIRIC_MCP_AVAILABLE is True

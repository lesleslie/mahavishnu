"""Unit tests for core.rate_limit_tools."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from mahavishnu.core.rate_limit import RateLimitConfig
import mahavishnu.core.rate_limit_tools as rate_limit_tools


@dataclass
class _Info:
    reset_time: float = 123.0
    retry_after: int = 5


class _FakeLimiter:
    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002,ANN003
        self.args = args
        self.kwargs = kwargs
        self.allowed_result = (True, _Info())
        self.keys_checked: list[str] = []
        self.violations: list[str] = []

    async def is_allowed(self, key: str):
        self.keys_checked.append(key)
        return self.allowed_result

    def record_violation(self, key: str) -> None:
        self.violations.append(key)


@pytest.fixture(autouse=True)
def _reset_globals() -> None:
    rate_limit_tools._global_limiter = None
    rate_limit_tools._tool_stats.clear()


def test_get_global_limiter_with_config(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[_FakeLimiter] = []

    def factory(*args, **kwargs):  # noqa: ANN002,ANN003
        limiter = _FakeLimiter(*args, **kwargs)
        created.append(limiter)
        return limiter

    monkeypatch.setattr(rate_limit_tools, "RateLimiter", factory)
    cfg = RateLimitConfig(
        requests_per_minute=11,
        requests_per_hour=222,
        requests_per_day=3333,
        burst_size=4,
    )

    limiter = rate_limit_tools.get_global_limiter(cfg)
    assert limiter is created[0]
    assert created[0].kwargs["per_minute"] == 11
    assert created[0].kwargs["per_hour"] == 222
    assert created[0].kwargs["per_day"] == 3333
    assert created[0].kwargs["burst_size"] == 4


def test_get_global_limiter_is_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[_FakeLimiter] = []

    def factory(*args, **kwargs):  # noqa: ANN002,ANN003
        limiter = _FakeLimiter(*args, **kwargs)
        created.append(limiter)
        return limiter

    monkeypatch.setattr(rate_limit_tools, "RateLimiter", factory)

    a = rate_limit_tools.get_global_limiter()
    b = rate_limit_tools.get_global_limiter()
    assert a is b
    assert len(created) == 1


@pytest.mark.asyncio
async def test_rate_limit_tool_allows_and_uses_user_id_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[_FakeLimiter] = []

    def factory(*args, **kwargs):  # noqa: ANN002,ANN003
        limiter = _FakeLimiter(*args, **kwargs)
        created.append(limiter)
        return limiter

    monkeypatch.setattr(rate_limit_tools, "RateLimiter", factory)

    @rate_limit_tools.rate_limit_tool(requests_per_minute=3, requests_per_hour=9, burst_size=2)
    async def tool_fn(user_id: str, payload: str) -> dict[str, str]:
        return {"payload": payload}

    result = await tool_fn(user_id="u1", payload="ok")
    assert result == {"payload": "ok"}
    assert created[0].keys_checked == ["user:u1"]

    stats = rate_limit_tools.get_tool_rate_limit_stats("tool_fn")
    assert stats["total_calls"] == 1
    assert stats["rate_limited_calls"] == 0


@pytest.mark.asyncio
async def test_rate_limit_tool_denied_returns_error_and_records_violation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[_FakeLimiter] = []

    def factory(*args, **kwargs):  # noqa: ANN002,ANN003
        limiter = _FakeLimiter(*args, **kwargs)
        limiter.allowed_result = (False, _Info(reset_time=200.0, retry_after=9))
        created.append(limiter)
        return limiter

    monkeypatch.setattr(rate_limit_tools, "RateLimiter", factory)

    @rate_limit_tools.rate_limit_tool()
    async def denied_tool() -> dict[str, str]:
        return {"should": "not-run"}

    result = await denied_tool()
    assert result["error_type"] == "rate_limit_exceeded"
    assert result["retry_after"] == 9
    assert result["reset_time"] == 200.0
    assert created[0].violations == ["default"]

    stats = rate_limit_tools.get_tool_rate_limit_stats("denied_tool")
    assert stats["total_calls"] == 1
    assert stats["rate_limited_calls"] == 1
    assert stats["last_limited"] == 200.0


@pytest.mark.asyncio
async def test_rate_limit_tool_key_func_failure_falls_back_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[_FakeLimiter] = []

    def factory(*args, **kwargs):  # noqa: ANN002,ANN003
        limiter = _FakeLimiter(*args, **kwargs)
        created.append(limiter)
        return limiter

    monkeypatch.setattr(rate_limit_tools, "RateLimiter", factory)

    def bad_key_func(_params: dict[str, object]) -> str:
        raise RuntimeError("boom")

    @rate_limit_tools.rate_limit_tool(key_func=bad_key_func)
    async def key_tool(value: str) -> dict[str, str]:
        return {"value": value}

    result = await key_tool(value="x")
    assert result == {"value": "x"}
    assert created[0].keys_checked == ["default"]


@pytest.mark.asyncio
async def test_rate_limit_tool_reraises_underlying_tool_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def factory(*args, **kwargs):  # noqa: ANN002,ANN003
        return _FakeLimiter(*args, **kwargs)

    monkeypatch.setattr(rate_limit_tools, "RateLimiter", factory)

    @rate_limit_tools.rate_limit_tool()
    async def broken_tool() -> dict[str, str]:
        raise ValueError("tool failed")

    with pytest.raises(ValueError, match="tool failed"):
        await broken_tool()

    stats = rate_limit_tools.get_tool_rate_limit_stats("broken_tool")
    assert stats["total_calls"] == 1
    assert stats["rate_limited_calls"] == 0


def test_get_all_stats_and_reset_behaviors() -> None:
    rate_limit_tools._tool_stats["a"] = {
        "total_calls": 3,
        "rate_limited_calls": 1,
        "last_limited": 10.0,
    }
    rate_limit_tools._tool_stats["b"] = {
        "total_calls": 2,
        "rate_limited_calls": 0,
        "last_limited": None,
    }

    stats = rate_limit_tools.get_all_rate_limit_stats()
    assert stats["total_calls"] == 5
    assert stats["total_rate_limited"] == 1
    assert stats["rate_limit_rate"] == 1 / 5
    assert "a" in stats["tools"]
    assert "b" in stats["tools"]

    rate_limit_tools.reset_tool_stats("a")
    assert rate_limit_tools._tool_stats["a"]["total_calls"] == 0
    assert rate_limit_tools._tool_stats["b"]["total_calls"] == 2

    rate_limit_tools.reset_tool_stats()
    assert rate_limit_tools._tool_stats == {}


def test_get_tool_rate_limit_stats_unknown_tool() -> None:
    result = rate_limit_tools.get_tool_rate_limit_stats("missing")
    assert result["tool_name"] == "missing"
    assert "error" in result

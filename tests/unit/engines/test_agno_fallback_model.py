"""Per-call failover behaviour for :class:`FallbackModel`.

The agent loop calls ``Model.invoke`` once per turn, so a provider that
fails *mid-run* — after tool calls have already been made — must be able
to fall through to the next provider rather than failing the whole run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agno.models.base import Model, ModelResponse
import pytest

from mahavishnu.engines.agno_fallback_model import FallbackModel


@dataclass
class _FakeModel(Model):
    """A model whose calls are scripted by the test."""

    id: str = "fake"
    provider: str | None = "fake"
    calls: int = 0
    error: Exception | None = None
    chunks: list[Any] | None = None

    def _maybe_raise(self) -> None:
        self.calls += 1
        if self.error is not None:
            raise self.error

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        self._maybe_raise()
        return ModelResponse(content=f"{self.id}-ok")

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        self._maybe_raise()
        return ModelResponse(content=f"{self.id}-ok")

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Any:
        self._maybe_raise()
        yield ModelResponse(content=f"{self.id}-chunk")

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> Any:
        self._maybe_raise()
        yield ModelResponse(content=f"{self.id}-chunk")

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return ModelResponse(content="parsed")

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return ModelResponse(content="parsed-delta")


# --- invoke ---------------------------------------------------------------


def test_invoke_uses_the_primary_provider() -> None:
    """The first provider answers when it succeeds."""
    primary = _FakeModel(id="primary")
    secondary = _FakeModel(id="secondary")

    model = FallbackModel(models=[primary, secondary])

    response = model.invoke()

    assert response.content == "primary-ok"
    assert primary.calls == 1
    assert secondary.calls == 0


def test_invoke_falls_back_when_the_primary_raises() -> None:
    """A primary failure mid-loop falls through to the next provider."""
    primary = _FakeModel(id="primary", error=RuntimeError("boom"))
    secondary = _FakeModel(id="secondary")

    model = FallbackModel(models=[primary, secondary])

    response = model.invoke()

    assert response.content == "secondary-ok"
    assert primary.calls == 1
    assert secondary.calls == 1


def test_invoke_raises_the_last_error_when_every_provider_fails() -> None:
    """Nothing is swallowed — the final provider's error propagates."""
    primary = _FakeModel(id="primary", error=RuntimeError("first"))
    secondary = _FakeModel(id="secondary", error=RuntimeError("second"))

    model = FallbackModel(models=[primary, secondary])

    with pytest.raises(RuntimeError, match="second"):
        model.invoke()


def test_invoke_without_providers_raises() -> None:
    """An empty chain is a programming error, not a silent no-op."""
    model = FallbackModel(models=[])

    with pytest.raises(RuntimeError, match="no providers"):
        model.invoke()


# --- ainvoke --------------------------------------------------------------


@pytest.mark.asyncio
async def test_ainvoke_falls_back_when_the_primary_raises() -> None:
    """The async path fails over the same way."""
    primary = _FakeModel(id="primary", error=RuntimeError("boom"))
    secondary = _FakeModel(id="secondary")

    model = FallbackModel(models=[primary, secondary])

    response = await model.ainvoke()

    assert response.content == "secondary-ok"
    assert secondary.calls == 1


@pytest.mark.asyncio
async def test_ainvoke_raises_the_last_error_when_every_provider_fails() -> None:
    primary = _FakeModel(id="primary", error=RuntimeError("first"))
    secondary = _FakeModel(id="secondary", error=RuntimeError("second"))

    model = FallbackModel(models=[primary, secondary])

    with pytest.raises(RuntimeError, match="second"):
        await model.ainvoke()


# --- streaming ------------------------------------------------------------


def test_invoke_stream_falls_back_when_the_primary_fails_to_start() -> None:
    """A provider that fails before yielding is skipped."""
    primary = _FakeModel(id="primary", error=RuntimeError("boom"))
    secondary = _FakeModel(id="secondary")

    model = FallbackModel(models=[primary, secondary])

    chunks = list(model.invoke_stream())

    assert [c.content for c in chunks] == ["secondary-chunk"]
    assert secondary.calls == 1


def test_invoke_stream_uses_the_primary_when_it_starts() -> None:
    primary = _FakeModel(id="primary")
    secondary = _FakeModel(id="secondary")

    model = FallbackModel(models=[primary, secondary])

    chunks = list(model.invoke_stream())

    assert [c.content for c in chunks] == ["primary-chunk"]
    assert secondary.calls == 0


@pytest.mark.asyncio
async def test_ainvoke_stream_falls_back_when_the_primary_fails_to_start() -> None:
    primary = _FakeModel(id="primary", error=RuntimeError("boom"))
    secondary = _FakeModel(id="secondary")

    model = FallbackModel(models=[primary, secondary])

    chunks = [chunk async for chunk in model.ainvoke_stream()]

    assert [c.content for c in chunks] == ["secondary-chunk"]


# --- integration with Agno ------------------------------------------------


def test_fallback_model_is_an_agno_model() -> None:
    """Agno's agent requires a ``Model`` instance — the wrapper is one."""
    assert issubclass(FallbackModel, Model)
    assert isinstance(FallbackModel(models=[_FakeModel()]), Model)


def test_capability_flags_mirror_the_primary_model() -> None:
    """Structured-output branching must follow the primary provider."""
    primary = _FakeModel(id="primary")
    primary.supports_native_structured_outputs = True

    model = FallbackModel(models=[primary, _FakeModel(id="secondary")])

    assert model.supports_native_structured_outputs is True


def test_agent_accepts_a_fallback_model() -> None:
    """Agno's agent must accept the wrapper as its model."""
    from agno.agent import Agent

    agent = Agent(name="test", model=FallbackModel(models=[_FakeModel()]))

    assert agent.model is not None

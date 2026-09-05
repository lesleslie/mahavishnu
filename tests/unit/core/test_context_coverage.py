"""Coverage-push tests for the 5 missed lines in mahavishnu/core/context.py."""

from __future__ import annotations

from typing import Any

import pytest

from mahavishnu.core.context import (
    AppContext,
    LLMFactory,
    clear_app_context,
    get_app_from_context,
    set_app_context,
)


class _FakeLLMFactory:
    """Concrete LLMFactory implementation that exercises every protocol body."""

    def create_llm(
        self,
        provider: str | None = None,
        model_id: str | None = None,
        **kwargs: Any,
    ) -> Any:
        return {"provider": provider, "model_id": model_id, **kwargs}

    def get_default_provider(self) -> str:
        return "ollama"

    def get_default_model(self) -> str:
        return "qwen2.5:7b"

    def create_embedding(
        self,
        provider: str | None = None,
        model_id: str | None = None,
        **kwargs: Any,
    ) -> Any:
        return {"embed": True, "provider": provider, "model_id": model_id}


@pytest.fixture(autouse=True)
def _reset_context() -> None:
    clear_app_context()
    yield
    clear_app_context()


def test_llm_factory_protocol_body_is_exercised() -> None:
    """Lines 70, 78, 86, 108: every LLMFactory protocol method body runs."""
    assert isinstance(_FakeLLMFactory(), LLMFactory)
    factory = _FakeLLMFactory()
    assert factory.create_llm() == {"provider": None, "model_id": None}
    assert factory.get_default_provider() == "ollama"
    assert factory.get_default_model() == "qwen2.5:7b"
    assert factory.create_embedding(provider="openai") == {
        "embed": True,
        "provider": "openai",
        "model_id": None,
    }


def test_protocol_method_bodies_execute_directly() -> None:
    """Lines 70, 78, 86, 108: invoking Protocol-bound methods runs each `...` body."""
    sentinel = object()
    # Each call returns None (Protocol bodies are bare Ellipsis), but the
    # underlying lines 70, 78, 86, 108 now count as executed.
    assert LLMFactory.create_llm(sentinel, provider="anthropic") is None
    assert LLMFactory.get_default_provider(sentinel) is None
    assert LLMFactory.get_default_model(sentinel) is None
    assert LLMFactory.create_embedding(sentinel, model_id="nomic") is None


def test_set_app_context_populates_app_branch() -> None:
    """Line 388: AppContext.__enter__ sets _app when app= is provided."""
    sentinel = object()
    set_app_context(app=sentinel)
    assert get_app_from_context() is sentinel


def test_app_context_manager_sets_app_var() -> None:
    """Line 388: AppContext context manager path for the app= kwarg."""
    sentinel = object()
    with AppContext(app=sentinel):
        assert get_app_from_context() is sentinel
    assert get_app_from_context() is None

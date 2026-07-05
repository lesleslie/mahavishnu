"""Unit tests for core.context."""

from __future__ import annotations

from mahavishnu.core.context import (
    AppContext,
    ContextNotInitializedError,
    clear_app_context,
    get_agno_adapter,
    get_learning_engine_from_context,
    get_llm_factory,
    get_websocket_server,
    is_context_initialized,
    require_agno_adapter,
    require_llm_factory,
    set_app_context,
)


def setup_function() -> None:
    clear_app_context()


def teardown_function() -> None:
    clear_app_context()


def test_getters_raise_for_required_context_when_unset() -> None:
    try:
        get_llm_factory()
        raise AssertionError("expected ContextNotInitializedError")
    except ContextNotInitializedError as exc:
        assert "llm_factory" in str(exc)
        assert "suggestion" in exc.details

    try:
        get_agno_adapter()
        raise AssertionError("expected ContextNotInitializedError")
    except ContextNotInitializedError as exc:
        assert "agno_adapter" in str(exc)
        assert "suggestion" in exc.details


def test_optional_getters_return_none_when_unset() -> None:
    assert get_websocket_server() is None
    assert get_learning_engine_from_context() is None


def test_set_app_context_sets_values_and_initialized_status() -> None:
    llm_factory = object()
    agno_adapter = object()
    websocket_server = object()
    learning_engine = object()

    set_app_context(
        llm_factory=llm_factory,
        agno_adapter=agno_adapter,
        websocket_server=websocket_server,
        learning_engine=learning_engine,
    )

    assert get_llm_factory() is llm_factory
    assert get_agno_adapter() is agno_adapter
    assert get_websocket_server() is websocket_server
    assert get_learning_engine_from_context() is learning_engine
    assert is_context_initialized() is True


def test_set_app_context_partial_update_preserves_existing_values() -> None:
    llm_factory = object()
    agno_adapter = object()
    initial_ws = object()
    updated_ws = object()

    set_app_context(
        llm_factory=llm_factory,
        agno_adapter=agno_adapter,
        websocket_server=initial_ws,
    )
    set_app_context(websocket_server=updated_ws)

    assert get_llm_factory() is llm_factory
    assert get_agno_adapter() is agno_adapter
    assert get_websocket_server() is updated_ws


def test_is_context_initialized_requires_required_components() -> None:
    assert is_context_initialized() is False

    set_app_context(llm_factory=object())
    assert is_context_initialized() is False

    clear_app_context()
    set_app_context(agno_adapter=object())
    assert is_context_initialized() is False

    clear_app_context()
    set_app_context(llm_factory=object(), agno_adapter=object())
    assert is_context_initialized() is True


def test_clear_app_context_resets_everything() -> None:
    set_app_context(
        llm_factory=object(),
        agno_adapter=object(),
        websocket_server=object(),
        learning_engine=object(),
    )
    assert is_context_initialized() is True

    clear_app_context()
    assert is_context_initialized() is False
    assert get_websocket_server() is None
    assert get_learning_engine_from_context() is None


def test_require_helpers_return_getter_functions() -> None:
    assert require_llm_factory() is get_llm_factory
    assert require_agno_adapter() is get_agno_adapter


def test_app_context_sets_and_restores_values() -> None:
    base_llm = object()
    base_agno = object()
    base_ws = object()
    base_learning = object()
    set_app_context(
        llm_factory=base_llm,
        agno_adapter=base_agno,
        websocket_server=base_ws,
        learning_engine=base_learning,
    )

    override_llm = object()
    override_ws = object()
    with AppContext(llm_factory=override_llm, websocket_server=override_ws):
        assert get_llm_factory() is override_llm
        assert get_agno_adapter() is base_agno
        assert get_websocket_server() is override_ws
        assert get_learning_engine_from_context() is base_learning

    assert get_llm_factory() is base_llm
    assert get_agno_adapter() is base_agno
    assert get_websocket_server() is base_ws
    assert get_learning_engine_from_context() is base_learning


def test_app_context_works_without_prior_values() -> None:
    llm = object()
    agno = object()

    with AppContext(llm_factory=llm, agno_adapter=agno):
        assert get_llm_factory() is llm
        assert get_agno_adapter() is agno
        assert is_context_initialized() is True

    assert is_context_initialized() is False


def test_app_context_sets_learning_engine_when_provided() -> None:
    learning_engine = object()

    with AppContext(learning_engine=learning_engine):
        assert get_learning_engine_from_context() is learning_engine

    assert get_learning_engine_from_context() is None

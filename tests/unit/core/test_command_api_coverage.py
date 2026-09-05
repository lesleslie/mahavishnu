"""Coverage-push tests for the 5 missed lines in mahavishnu/core/command_api.py"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from mahavishnu.core.command_api import (
    CommandHandler,
    CommandRegistry,
    CommandResult,
)


class _ParamsDict(BaseModel):
    """Pydantic model — exercises the kwargs path for dict params."""

    task_id: str


class _ParamsPositional:
    """Plain class accepting a single positional arg — used for list/scalar paths.

    Pydantic's BaseModel rejects ``Model(*args)`` (Pydantic v2 only takes kwargs),
    but the production code unconditionally calls ``params_model(*params)`` /
    ``params_model(params)`` for the list and scalar branches, so we need a
    model whose ``__init__`` accepts positional args.
    """

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id


async def test_dict_params_passed_as_kwargs() -> None:
    """dict params → params_model(**params); covers the dict branch."""
    captured: dict[str, Any] = {}

    async def handler(params: Any) -> CommandResult:
        captured["task_id"] = params.task_id
        captured["type"] = type(params).__name__
        return CommandResult.success(data={"ok": True})

    registry = CommandRegistry(name="cov")
    registry.command("dict_cmd", params_model=_ParamsDict)(handler)
    result = await registry.execute("dict_cmd", {"task_id": "abc"})

    assert result.success is True
    assert captured == {"task_id": "abc", "type": "_ParamsDict"}


async def test_list_params_passed_as_positional() -> None:
    """list params → params_model(*params); covers the list branch (line 176)."""
    captured: dict[str, Any] = {}

    async def handler(params: Any) -> CommandResult:
        captured["task_id"] = params.task_id
        captured["type"] = type(params).__name__
        return CommandResult.success(data={"ok": True})

    registry = CommandRegistry(name="cov")
    registry.command("list_cmd", params_model=_ParamsPositional)(handler)
    result = await registry.execute("list_cmd", ["xyz"])

    assert result.success is True
    assert captured == {"task_id": "xyz", "type": "_ParamsPositional"}


async def test_scalar_params_passed_as_single_arg() -> None:
    """scalar params → params_model(params); covers the else branch (line 178)."""
    captured: dict[str, Any] = {}

    async def handler(params: Any) -> CommandResult:
        captured["task_id"] = params.task_id
        captured["type"] = type(params).__name__
        return CommandResult.success(data={"ok": True})

    registry = CommandRegistry(name="cov")
    registry.command("scalar_cmd", params_model=_ParamsPositional)(handler)
    result = await registry.execute("scalar_cmd", "scalar-id")

    assert result.success is True
    assert captured == {"task_id": "scalar-id", "type": "_ParamsPositional"}


async def test_handler_returning_command_result_is_returned_as_is() -> None:
    """When handler returns CommandResult, invoke returns it untouched; covers line 185."""

    async def handler(params: Any) -> CommandResult:
        return CommandResult.success(data={"preset": True})

    ch = CommandHandler(name="inline", handler=handler)
    result = await ch.invoke({})

    assert isinstance(result, CommandResult)
    assert result.success is True
    assert result.data == {"preset": True}


def test_get_command_info_returns_none_for_missing_command() -> None:
    """Covers line 303: get_command_info returns None when command absent."""
    registry = CommandRegistry(name="cov")
    assert registry.get_command_info("does_not_exist") is None
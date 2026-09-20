"""Tests for ``mahavishnu.acp.errors`` — error codes and ``ACPError`` shape."""

from __future__ import annotations

import pytest

from mahavishnu.acp.errors import (
    AUTH_INVALID,
    AUTH_REQUIRED,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    SESSION_PERSISTENCE_NOT_IMPLEMENTED,
    TOO_MANY_CONCURRENT_SESSIONS,
    ACPError,
)

pytestmark = [pytest.mark.unit, pytest.mark.acp]


class TestProjectErrorCodes:
    """Project-defined ACP codes match the plan §Phase 2 Decision 1 table."""

    def test_auth_required_is_32001(self) -> None:
        assert AUTH_REQUIRED == -32001

    def test_auth_invalid_is_32002(self) -> None:
        assert AUTH_INVALID == -32002

    def test_session_persistence_not_implemented_is_32003(self) -> None:
        assert SESSION_PERSISTENCE_NOT_IMPLEMENTED == -32003

    def test_too_many_concurrent_sessions_is_32004(self) -> None:
        assert TOO_MANY_CONCURRENT_SESSIONS == -32004


class TestStandardErrorCodes:
    """Standard JSON-RPC 2.0 codes match the spec."""

    def test_parse_error_is_32700(self) -> None:
        assert PARSE_ERROR == -32700

    def test_invalid_request_is_32600(self) -> None:
        assert INVALID_REQUEST == -32600

    def test_method_not_found_is_32601(self) -> None:
        assert METHOD_NOT_FOUND == -32601

    def test_invalid_params_is_32602(self) -> None:
        assert INVALID_PARAMS == -32602

    def test_internal_error_is_32603(self) -> None:
        assert INTERNAL_ERROR == -32603


class TestACPError:
    """``ACPError`` is an ``Exception`` with ``code``, ``message``, ``data``."""

    def test_basic_construction(self) -> None:
        err = ACPError(code=AUTH_REQUIRED, message="auth required")
        assert err.code == AUTH_REQUIRED
        assert err.message == "auth required"
        assert err.data is None

    def test_data_passed_through(self) -> None:
        err = ACPError(code=AUTH_INVALID, message="bad token", data={"hint": "x"})
        assert err.data == {"hint": "x"}

    def test_to_dict_omits_none_data(self) -> None:
        err = ACPError(code=AUTH_REQUIRED, message="auth required")
        d = err.to_dict()
        assert d == {"code": AUTH_REQUIRED, "message": "auth required"}
        assert "data" not in d

    def test_to_dict_includes_data_when_set(self) -> None:
        err = ACPError(code=INVALID_PARAMS, message="bad params", data=["x"])
        d = err.to_dict()
        assert d == {"code": INVALID_PARAMS, "message": "bad params", "data": ["x"]}

    def test_is_an_exception(self) -> None:
        err = ACPError(code=INTERNAL_ERROR, message="boom")
        with pytest.raises(ACPError) as excinfo:
            raise err
        assert excinfo.value.code == INTERNAL_ERROR
        assert excinfo.value.message == "boom"

    def test_repr_is_compact(self) -> None:
        err = ACPError(code=AUTH_INVALID, message="bad token")
        r = repr(err)
        assert "ACPError" in r
        assert "-32002" in r
        assert "bad token" in r

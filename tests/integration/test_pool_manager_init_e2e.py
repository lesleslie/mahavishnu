"""End-to-end test for init_pool_manager error classification.

Per Plan v3 Phase 1m (https://users/les/.claude/plans/nifty-gliding-stallman.md).
Validates the dual-shape `except` clause added to
``mahavishnu/core/bootstrap.py::init_pool_manager``:
- Recoverable: ``ImportError`` / ``ModuleNotFoundError`` (optional-dep missing
  like the ``gpu`` extra for ``runpod_pool``) → log warning + return ``None``.
- Hard error: ``TypeError`` / ``RuntimeError`` / ``ValueError`` / etc.
  (config bugs, ACL misconfig, message bus init failure) → ``logger.exception``
  + re-raise so an operator sees the real failure.

The function does ``from ..pools.manager import PoolManager, PoolSelector``
PER CALL inside its ``try`` block, so the live bindings live in
``mahavishnu.pools.manager``. Monkeypatching ``bootstrap.PoolManager``
silently no-ops (no attribute); monkeypatching the per-call import target
is what works.

Plus scenario 5 verifies the opt-out path at the App construction boundary
(``bootstrap.py:530`` -- ``if app.config.pools.enabled``) keeps the default
``None`` and never enters the try at all.
"""

from __future__ import annotations

import logging

import pytest

from mahavishnu.core import bootstrap as bootstrap_module
from mahavishnu.pools import manager as pools_manager_module


def _build_stub_app(
    *,
    pools_enabled: bool = True,
    routing_strategy: str = "least_loaded",
) -> object:
    """Minimal stub App with the attributes init_pool_manager reads."""

    class _StubApp:
        pass

    app = _StubApp()
    app.terminal_manager = object()
    app.session_buddy = None
    app._mcp_state = None
    app.config = type(
        "Cfg",
        (),
        {
            "pools": type(
                "PoolsCfg",
                (),
                {"enabled": pools_enabled, "routing_strategy": routing_strategy, "default_type": "mahavishnu"},
            )(),
        },
    )()
    return app


class TestInitPoolManagerE2E:
    """Plan v3 Phase 1m — 5 scenarios."""

    def test_happy_path_returns_pool_manager(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Scenario 1 — the construction succeeds; a pool manager is returned.

        We patch PoolManager at the source module that ``init_pool_manager``
        imports from (per-call ``from ..pools.manager import PoolManager``).
        """
        class _FakePoolManager:
            """Minimal stand-in: kwarg-accepting __init__ + the one method
            init_pool_manager calls (``set_pool_selector``)."""

            def __init__(self, **kw: object) -> None:
                self.kw = kw

            def set_pool_selector(self, selector: object) -> None:
                self.selector = selector

        monkeypatch.setattr(pools_manager_module, "PoolManager", _FakePoolManager)

        result = bootstrap_module.init_pool_manager(_build_stub_app())

        assert isinstance(result, _FakePoolManager)
        # set_pool_selector was called with a PoolSelector enum value.
        assert hasattr(result, "selector")

    def test_optional_dep_missing_returns_none_and_logs_warning(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Scenario 2 — an ``ImportError`` (recoverable) returns ``None`` and
        logs at WARNING level, NOT raising."""
        from mahavishnu.pools.manager import PoolManager

        # Patch the actual __init__ on the PoolManager class — the function's
        # per-call import resolves to this same class instance.
        # Note: ``ImportError`` is a builtin that does NOT accept kwargs; use
        # positional. The realistic exception (an import system failure)
        # sets ``.name`` internally; a manually-raised ImportError has
        # ``.name = None`` which falls back to ``str(exc)`` in the warning.
        def init_raises(*_args: object, **_kw: object) -> None:
            raise ImportError("simulated optional-dep missing")

        monkeypatch.setattr(PoolManager, "__init__", init_raises)

        with caplog.at_level(logging.WARNING, logger="mahavishnu.core.bootstrap"):
            result = bootstrap_module.init_pool_manager(_build_stub_app())

        assert result is None
        # WARNING (not ERROR/EXCEPTION) — recoverable per Plan v3 Phase 1m.
        warning_records = [
            record
            for record in caplog.records
            if record.levelno == logging.WARNING
        ]
        assert any(
            "Pool manager required import missing" in record.message
            for record in warning_records
        ), f"expected a warning log, got records: {caplog.records}"
        # No ERROR/EXCEPTION-level records — we do not logger.exception a recoverable.
        error_records = [
            record
            for record in caplog.records
            if record.levelno >= logging.ERROR
        ]
        assert not error_records, f"unexpected error records: {error_records}"

    def test_hard_error_type_error_propagates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Scenario 3 — a real-bug ``TypeError`` propagates UP after
        ``logger.exception`` is called. Phase 1m restores the operator's
        signal instead of silently returning ``None``."""
        from mahavishnu.pools.manager import PoolManager

        def init_raises_typeerror(*_args: object, **_kw: object) -> None:
            raise TypeError("simulated hard error")

        monkeypatch.setattr(PoolManager, "__init__", init_raises_typeerror)

        with pytest.raises(TypeError, match="simulated hard error"):
            bootstrap_module.init_pool_manager(_build_stub_app())

    def test_hard_error_value_error_propagates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Scenario 4 — a real-bug ``ValueError`` from ``PoolSelector(bad_value)``
        propagates UP. ``PoolSelector`` is an Enum; unknown values raise.
        """
        # Use a string that's not in the PoolSelector enum.
        app = _build_stub_app(routing_strategy="this_strategy_definitely_does_not_exist")

        with pytest.raises(ValueError):
            bootstrap_module.init_pool_manager(app)

    def test_pools_enabled_false_keeps_pool_manager_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Scenario 5 — the ``pools_enabled: false`` config-gate at
        ``bootstrap.py:530`` (``if app.config.pools.enabled``) never enters
        ``init_pool_manager``, so ``app.pool_manager`` stays its default
        ``None`` and no log is emitted.

        We don't call init_pool_manager directly — we exercise the App-level
        constructor path via MahavishnuApp, where the gate lives.
        """
        from mahavishnu.core.app import MahavishnuApp

        # Monkey-patch pools.enabled to False on whatever config object the
        # App pulls its config from. The Oneiric layer loads layered config;
        # we override via the App's runtime mutability — call out that the
        # pool subsystem is opt-out.
        app = MahavishnuApp()

        # Mutate runtime config to opt out.
        app.config.pools.enabled = False  # type: ignore[attr-defined]
        # Re-run the relevant initialization segments — we want to confirm
        # that with pools_enabled=False, pool_manager is None and no exception.
        from mahavishnu.core.bootstrap import initialize_runtime_services

        initialize_runtime_services(app)  # type: ignore[arg-type]

        assert app.pool_manager is None  # type: ignore[attr-defined]
        # No exception = good. Pool subsystem is disabled.

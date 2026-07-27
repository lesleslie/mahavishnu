"""Unit tests for DLQ config-to-construction propagation.

Covers the wiring gap closed in
``docs/plans/2026-07-16-dlq-fail-closed-wiring.md`` (Phase 1):
``create_dlq_integration`` must forward
``MahavishnuSettings.dlq.fail_on_opensearch_unavailable`` and
``MahavishnuSettings.dlq.max_size`` into the constructed ``DeadLetterQueue``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from mahavishnu.core.dlq_integration import create_dlq_integration


def _make_app(*, fail_closed: bool, max_size: int) -> Any:
    """Minimal app stub: just the attributes create_dlq_integration reads."""
    config = SimpleNamespace(
        dlq=SimpleNamespace(
            fail_on_opensearch_unavailable=fail_closed,
            max_size=max_size,
        ),
        # create_dlq_integration also reads dlq_integration_strategy (defaults
        # to 'automatic' in the function, so this is never actually accessed).
    )
    return SimpleNamespace(
        config=config,
        opensearch_integration=None,  # opensearch_client falls through to None
        observability=None,
        dlq=None,  # force construction
    )


async def test_fail_closed_flag_propagates_from_config() -> None:
    """When config.dlq.fail_on_opensearch_unavailable=True, the DLQ must
    reflect that so ``enqueue`` honors the opt-in at runtime."""
    app = _make_app(fail_closed=True, max_size=10000)
    await create_dlq_integration(app)
    assert app.dlq is not None
    assert app.dlq._fail_on_opensearch_unavailable is True


async def test_fail_closed_flag_propagates_default_false() -> None:
    """Back-compat: when config says False, the DLQ stays in legacy
    silent-fallback mode (the existing 4 unit tests assume this default)."""
    app = _make_app(fail_closed=False, max_size=10000)
    await create_dlq_integration(app)
    assert app.dlq is not None
    assert app.dlq._fail_on_opensearch_unavailable is False


async def test_max_size_propagates_from_config() -> None:
    """dlq_integration previously read a non-existent flat ``dlq_max_size``
    attr (always defaulting to 10000). Confirm the nested-config read works."""
    app = _make_app(fail_closed=False, max_size=42)
    await create_dlq_integration(app)
    assert app.dlq is not None
    assert app.dlq._max_size == 42

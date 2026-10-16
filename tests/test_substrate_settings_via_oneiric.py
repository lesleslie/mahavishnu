"""Phase E2 TDD tests: Mahavishnu settings adopt OneiricSettings.substrate.

Per ``docs/plans/2026-09-27-shared-bodai-substrate-phase-e2.md`` §2.3,
``mahavishnu/core/config.py`` adopts the shared Bodai substrate for
``pool / retry / telemetry / auth`` (warm/cold/embedding out of scope
per spec §5.5 — Mahavishnu doesn't host those substrates).

These tests pin three top-level mirror fields on
``MahavishnuSettings`` to their canonical substrate env-var
representations:

- ``pool_workers_per_instance`` ← ``ONEIRIC__SUBSTRATE__POOL__WORKERS_PER_INSTANCE``
- ``retry_max_attempts`` ← ``ONEIRIC__SUBSTRATE__RETRY__MAX_ATTEMPTS``
- ``auth_enabled`` ← ``ONEIRIC__SUBSTRATE__AUTH__ENABLED``

The mirror fields are the canonical Phase E2 contract: callers get a
single dotted access path (``settings.pool_workers_per_instance``)
without needing to know whether the value came from a substrate env
var, substrate YAML, or per-component override. The atomic per-file
rule (no half-state: never both local default AND substrate) is
enforced by routing every default through a ``default_factory`` that
reads the substrate env var.

Phase E1 wired ``OneiricSettings.substrate`` (oneiric commit
``bde290e``); this test pins the Mahavishnu side of that contract.
"""

from __future__ import annotations

import pytest

from mahavishnu.core.config import load_settings


@pytest.fixture(autouse=True)
def _isolate_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip any inherited ``ONEIRIC__SUBSTRATE__*`` env vars per test.

    Tests below set exactly the var they care about — any leakage from
    the host shell would mask RED states and make the suite
    non-hermetic. The autouse fixture also clears the module-level
    settings cache so each test gets a fresh ``MahavishnuSettings``.
    """
    for k in list(monkeypatch.delenv if False else []):
        pass
    for key in [
        "ONEIRIC__SUBSTRATE__POOL__WORKERS_PER_INSTANCE",
        "ONEIRIC__SUBSTRATE__RETRY__MAX_ATTEMPTS",
        "ONEIRIC__SUBSTRATE__AUTH__ENABLED",
    ]:
        monkeypatch.delenv(key, raising=False)
    # Force the lazy module-level cache to clear so the next
    # ``load_settings()`` re-reads env from scratch.
    from mahavishnu.core import config as _config

    _config.reset_settings()
    yield
    _config.reset_settings()


def test_pool_workers_per_instance_via_substrate(monkeypatch: pytest.MonkeyPatch) -> None:
    """``ONEIRIC__SUBSTRATE__POOL__WORKERS_PER_INSTANCE`` flows through to the mirror field."""
    monkeypatch.setenv("ONEIRIC__SUBSTRATE__POOL__WORKERS_PER_INSTANCE", "10")
    s = load_settings()
    assert s.pool_workers_per_instance == 10


def test_retry_max_attempts_via_substrate(monkeypatch: pytest.MonkeyPatch) -> None:
    """``ONEIRIC__SUBSTRATE__RETRY__MAX_ATTEMPTS`` flows through to the mirror field."""
    monkeypatch.setenv("ONEIRIC__SUBSTRATE__RETRY__MAX_ATTEMPTS", "7")
    s = load_settings()
    assert s.retry_max_attempts == 7


def test_auth_enabled_via_substrate(monkeypatch: pytest.MonkeyPatch) -> None:
    """``ONEIRIC__SUBSTRATE__AUTH__ENABLED`` flows through to the mirror field."""
    monkeypatch.setenv("ONEIRIC__SUBSTRATE__AUTH__ENABLED", "true")
    s = load_settings()
    assert s.auth_enabled is True

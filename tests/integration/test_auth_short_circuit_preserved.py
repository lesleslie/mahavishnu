"""Auth short-circuit preservation test (Plan 2 Phase E2 Task 4).

Per `feedback-bodai-localhost-no-auth.md`: when ``auth__enabled=False``, ALL
auth gates (decorator + middleware) must short-circuit cleanly. This test
pins the *substrate wire* that the 3 component configs read from, so a
future regression that re-introduces a hard-coded ``auth.enabled=true``
path is caught before it ships.

The actual auth middleware/decorator code lives in oneiric
(``oneiric/mcp/server.py``) and has its own e2e coverage via
``tests/integration/test_oneiric_report_runtime_e2e.py`` (the existing
``oneiric_report_runtime`` tool requires auth and the e2e proves the
flag propagates). This file focuses on the *cross-component* contract:
that the substrate's auth defaults are the values the 3 components see.
"""
from __future__ import annotations

import pytest


def _fresh_substrate(monkeypatch: pytest.MonkeyPatch):
    """Import inside the test so monkeypatch env-var mutations apply.

    The substrate's env-var source (``_SubstrateEnvSource``) reads
    ``os.environ`` at ``OneiricSettings()`` construction time, so a
    fresh import + new instance per test is required for the
    override to be observed.
    """
    from oneiric.core.config import OneiricSettings

    return OneiricSettings()


def test_substrate_auth_enabled_default_is_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """The substrate's ``auth__enabled`` defaults to ``False`` so loopback traffic
    between Bodai components is trusted without ceremony.

    Per the memory rule: no auth between Bodai components on localhost.
    The default MUST be ``False``; an operator must opt-in to public-network
    auth explicitly.
    """
    # Strip any inherited substrate env vars to read the declared default.
    for k in (
        "ONEIRIC__SUBSTRATE__AUTH__ENABLED",
        "ONEIRIC__SUBSTRATE__AUTH__LOOPBACK_TRUSTED",
    ):
        monkeypatch.delenv(k, raising=False)
    s = _fresh_substrate(monkeypatch)
    assert s.substrate.auth__enabled is False, (
        "substrate auth__enabled default drifted to True — would break "
        "feedback-bodai-localhost-no-auth.md"
    )


def test_substrate_auth_loopback_trusted_default_is_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The substrate's ``auth__loopback_trusted`` defaults to ``True`` so the
    localhost escape hatch is preserved when ``auth__enabled=False``.

    The two flags are independent axes: the first declares "is auth on at
    all"; the second declares "if auth is on, do we trust the loopback".
    The default for the second is True so that on a fresh install, an
    operator who flips ``auth__enabled=True`` still doesn't break local
    inter-component traffic.
    """
    for k in (
        "ONEIRIC__SUBSTRATE__AUTH__ENABLED",
        "ONEIRIC__SUBSTRATE__AUTH__LOOPBACK_TRUSTED",
    ):
        monkeypatch.delenv(k, raising=False)
    s = _fresh_substrate(monkeypatch)
    assert s.substrate.auth__loopback_trusted is True


def test_substrate_auth_enabled_env_var_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ONEIRIC__SUBSTRATE__AUTH__ENABLED=true`` flips the flag.

    The double-underscore env-var convention is the Phase E1 contract;
    a single-underscore variant (``ONEIRIC_AUTH_ENABLED``) is NOT a
    substrate field and should NOT affect ``s.substrate.auth__enabled``.
    """
    monkeypatch.setenv("ONEIRIC__SUBSTRATE__AUTH__ENABLED", "true")
    s = _fresh_substrate(monkeypatch)
    assert s.substrate.auth__enabled is True

    # And the wrong (single-underscore) variant must NOT silently leak in.
    monkeypatch.setenv("ONEIRIC_AUTH_ENABLED", "true")
    monkeypatch.delenv("ONEIRIC__SUBSTRATE__AUTH__ENABLED")
    s2 = _fresh_substrate(monkeypatch)
    assert s2.substrate.auth__enabled is False, (
        "ONEIRIC_AUTH_ENABLED (single underscore) leaked into the substrate — "
        "the Phase E1 env-var contract is double-underscore only"
    )


def test_mahavishnu_settings_reads_substrate_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MahavishnuSettings.auth_enabled (added in Task 3) reads substrate.auth__enabled.

    This is the contract that must hold end-to-end: when an operator
    flips the substrate env var, the Mahavishnu side sees the new
    value without a code change. ``reset_settings()`` is called
    between the two flips because ``get_settings`` (aliased as
    ``load_settings``) caches the constructed instance.
    """
    from mahavishnu.core.config import load_settings, reset_settings

    monkeypatch.setenv("ONEIRIC__SUBSTRATE__AUTH__ENABLED", "true")
    s = load_settings()
    assert s.auth_enabled is True

    reset_settings()  # drop the cached instance so the next call re-reads env
    monkeypatch.setenv("ONEIRIC__SUBSTRATE__AUTH__ENABLED", "false")
    s2 = load_settings()
    assert s2.auth_enabled is False


def test_substrate_default_does_not_invert_under_pydantic_reload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Constructing ``OneiricSettings()`` twice in a row with the same env
    yields the same ``auth__enabled`` value. Guards against a regression
    where a settings-cache layer (e.g. ``functools.lru_cache``) reads the
    env on first call only and serves a stale value on the second.
    """
    monkeypatch.delenv("ONEIRIC__SUBSTRATE__AUTH__ENABLED", raising=False)
    from oneiric.core.config import OneiricSettings

    first = OneiricSettings().substrate.auth__enabled
    second = OneiricSettings().substrate.auth__enabled
    assert first == second
    assert first is False

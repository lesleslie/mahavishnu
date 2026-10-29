"""Gateway-credential resolution for the PiPool subprocess environment.

A Mahavishnu spawned by launchd inherits no interactive environment, so
``BODAI_BIFROST_VK`` is absent from the pool's parent process. Pi resolves
``$BODAI_BIFROST_VK`` from *its own* environment (``~/.pi/agent/models.json``
declares ``apiKey: "$BODAI_BIFROST_VK"`` for the ``minimax-via-bifrost``
provider), so the pool must resolve the credential itself and hand it over.

These tests are hermetic: the resolver is patched, so nothing reads the
operator's real credential store.
"""

from __future__ import annotations

import pytest

from mahavishnu.pools import pi_pool
from mahavishnu.pools.pi_pool import (
    BODAI_VIRTUAL_KEY_ENV,
    _build_subprocess_env,
)


@pytest.fixture
def stub_resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the credential resolver with a fixed, fake value."""
    monkeypatch.setattr(
        pi_pool,
        "resolve_gateway_credential",
        lambda: "sk-bf-test-virtual-key",
    )


def test_gateway_credential_is_injected_when_parent_env_lacks_it(
    monkeypatch: pytest.MonkeyPatch,
    stub_resolver: None,
) -> None:
    """The pool resolves the gateway key instead of requiring it in the env."""
    monkeypatch.delenv(BODAI_VIRTUAL_KEY_ENV, raising=False)

    env = _build_subprocess_env(env_allowlist=("PATH",))

    assert env[BODAI_VIRTUAL_KEY_ENV] == "sk-bf-test-virtual-key"


def test_parent_env_value_wins_over_the_resolver(
    monkeypatch: pytest.MonkeyPatch,
    stub_resolver: None,
) -> None:
    """An operator-exported value is forwarded unchanged."""
    monkeypatch.setenv(BODAI_VIRTUAL_KEY_ENV, "sk-bf-from-parent-env")

    env = _build_subprocess_env(env_allowlist=(BODAI_VIRTUAL_KEY_ENV,))

    assert env[BODAI_VIRTUAL_KEY_ENV] == "sk-bf-from-parent-env"


def test_unresolvable_credential_leaves_the_key_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No credential anywhere means no key — and no crash."""
    monkeypatch.delenv(BODAI_VIRTUAL_KEY_ENV, raising=False)
    monkeypatch.setattr(pi_pool, "resolve_gateway_credential", lambda: None)

    env = _build_subprocess_env(env_allowlist=("PATH",))

    assert BODAI_VIRTUAL_KEY_ENV not in env


def test_injected_credential_is_not_denylisted(
    monkeypatch: pytest.MonkeyPatch,
    stub_resolver: None,
) -> None:
    """The injected name must survive the runtime denylist.

    The denylist strips any ``BIFROST_*``-prefixed var, which is why the
    subprocess-facing name is ``BODAI_BIFROST_VK`` and not
    ``BIFROST_VIRTUAL_KEY``.
    """
    monkeypatch.delenv(BODAI_VIRTUAL_KEY_ENV, raising=False)

    assert not any(
        BODAI_VIRTUAL_KEY_ENV.startswith(prefix) for prefix in pi_pool._FORBIDDEN_ENV_PREFIXES
    )

    env = _build_subprocess_env(env_allowlist=("PATH",))

    assert BODAI_VIRTUAL_KEY_ENV in env


def test_denylisted_prefixes_still_win_over_the_injection(
    monkeypatch: pytest.MonkeyPatch,
    stub_resolver: None,
) -> None:
    """A denylisted parent var is dropped even when explicitly allowlisted."""
    monkeypatch.setenv("MINIMAX_API_KEY", "sk-minimax-secret")
    monkeypatch.delenv(BODAI_VIRTUAL_KEY_ENV, raising=False)

    env = _build_subprocess_env(env_allowlist=("MINIMAX_API_KEY",))

    assert "MINIMAX_API_KEY" not in env

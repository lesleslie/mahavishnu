"""Tests for how the gateway provisions credentials at launch.

req: REQ-BIFROST-028

The LaunchAgent execs this module without a shell, so the supervisor inherits
no interactive environment. Everything the spawned gateway needs must be
explicitly placed into ``os.environ`` before ``launch_bifrost()``.

Oneiric is asked first because it is the intended abstraction, but this
deployment has no secrets provider configured -- every boot logged
``no-secrets-provider-configured`` -- so ``resolve_secrets`` returns nothing
and the ``secrets.env`` read is what actually provisions the credentials.
These tests pin that fallback rather than leaving it incidental.

Every test runs with the credential names removed from ``os.environ`` first.
An earlier version of :func:`test_setdefault_leaves_an_already_resolved_value_alone`
inherited the developer's real ``OPENAI_API_KEY`` and printed it in a failed
assertion -- ``setdefault`` correctly declined to overwrite it, so the
assertion compared against a live secret. Hermetic by construction.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

import pytest

from mahavishnu.bifrost import gateway

if TYPE_CHECKING:
    from pathlib import Path

CREDENTIAL_NAMES = (
    "MINIMAX_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "LLAMA_SERVER_API_KEY",
)

FIXTURE_STORE = """# a comment
MINIMAX_API_KEY=upstream-minimax
export OPENAI_API_KEY="upstream-openai"
ANTHROPIC_API_KEY=upstream-anthropic
LLAMA_SERVER_API_KEY=local-llama-server
BIFROST_SETUP_TOKEN=local-setup-token
BIFROST_VIRTUAL_KEY=local-virtual-key
SOME_OTHER_KEY=not-ours
"""


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guarantee no ambient credential can leak into an assertion."""
    for name in CREDENTIAL_NAMES + ("BIFROST_SETUP_TOKEN", "BIFROST_VIRTUAL_KEY"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def secrets_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``load_secrets_env`` at a scratch credential store."""
    target = tmp_path / "secrets.env"
    target.write_text(FIXTURE_STORE, encoding="utf-8")
    monkeypatch.setattr(gateway, "SECRETS_ENV", target)
    return target


def test_provider_keys_are_provisioned_from_secrets_env(secrets_file: Path) -> None:
    """Every upstream key must be in the provisioned set.

    They are currently reaching the gateway by a path this module cannot
    observe. Reading them here makes the guarantee explicit instead of
    dependent on undocumented inheritance.
    """
    found = gateway.load_secrets_env()

    for key in gateway.NEEDED_KEYS:
        assert key in found, f"{key} must be read from the credential store"
    assert found["MINIMAX_API_KEY"] == "upstream-minimax"
    assert found["OPENAI_API_KEY"] == "upstream-openai", "quotes are shell syntax"


def test_every_configured_provider_key_is_resolved_by_the_gateway() -> None:
    """Every ``env.X`` provider key the config declares must be in ``NEEDED_KEYS``.

    The gateway resolves a provider's key from its own environment. A key
    the config declares but the gateway never resolves is dropped at
    startup, and every request for that provider then fails with
    ``no_key_supports_model`` -- which is exactly how the local
    ``llama-server`` provider became unservable.

    The requirement is derived from the shipped template rather than
    restated as a literal, so a new provider key cannot be added to the
    config without also being resolvable. A test that merely iterated
    ``NEEDED_KEYS`` would have passed with the key left out.
    """
    template = json.loads(gateway.TEMPLATE_CONFIG.read_text(encoding="utf-8"))

    declared: set[str] = set()
    for provider in template.get("providers", {}).values():
        for key in provider.get("keys", []):
            value = key.get("value", "")
            if isinstance(value, str) and value.startswith("env."):
                declared.add(value.removeprefix("env."))

    assert declared, "the template declares no env-backed provider keys"
    missing = declared - set(gateway.NEEDED_KEYS)
    assert not missing, (
        f"provider keys the gateway never resolves: {sorted(missing)}. "
        f"Add them to NEEDED_KEYS or the provider is unservable."
    )


def test_bifrost_local_credentials_are_provisioned(secrets_file: Path) -> None:
    """The loopback gateway's own credentials come from the same store."""
    found = gateway.load_secrets_env()

    assert found["BIFROST_SETUP_TOKEN"] == "local-setup-token"
    assert found["BIFROST_VIRTUAL_KEY"] == "local-virtual-key"


def test_unrelated_keys_are_not_read(secrets_file: Path) -> None:
    """Only the requested keys are loaded, never the whole file."""
    assert "SOME_OTHER_KEY" not in gateway.load_secrets_env()


def test_setdefault_leaves_an_already_resolved_value_alone(
    secrets_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Oneiric must stay authoritative when it does resolve something.

    ``serve`` runs ``resolve_secrets`` before this read and applies
    ``setdefault``, so an already-exported value must survive. Otherwise
    adding the provider keys to the read order would silently downgrade the
    intended abstraction.
    """
    monkeypatch.setenv("MINIMAX_API_KEY", "resolved-by-oneiric")

    # Exactly what serve() does.
    for key, value in gateway.load_secrets_env().items():
        os.environ.setdefault(key, value)

    assert os.environ["MINIMAX_API_KEY"] == "resolved-by-oneiric"
    # Keys Oneiric did not provide still get provisioned.
    assert os.environ["OPENAI_API_KEY"] == "upstream-openai"


def test_missing_store_is_not_an_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing credential store yields nothing rather than raising."""
    monkeypatch.setattr(gateway, "SECRETS_ENV", tmp_path / "absent.env")

    assert gateway.load_secrets_env() == {}

"""Unit tests for MahavishnuApp nanobot provider gateway integration."""

from __future__ import annotations

import builtins
import sys
from types import SimpleNamespace

import mahavishnu.core.app as appmod


def test_init_nanobot_provider_branches(monkeypatch) -> None:
    app = object.__new__(appmod.MahavishnuApp)

    # token missing -> None
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    assert appmod.MahavishnuApp._init_nanobot_provider(app) is None

    # import error -> None
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok")
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("BIFROST_BASE_URL", raising=False)
    monkeypatch.delenv("MAHAVISHNU_LLM_GATEWAY_BASE_URL", raising=False)

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001,ANN002,ANN003
        if name == "nanobot.providers":
            raise ImportError("missing")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", fake_import)
    assert appmod.MahavishnuApp._init_nanobot_provider(app) is None
    monkeypatch.setattr("builtins.__import__", real_import)

    # success path
    class _Provider:
        def __init__(self, api_key: str, base_url: str) -> None:
            self.api_key = api_key
            self.base_url = base_url

    monkeypatch.setitem(
        sys.modules,
        "nanobot.providers",
        SimpleNamespace(OpenAICompatProvider=_Provider),
    )
    provider = appmod.MahavishnuApp._init_nanobot_provider(app)
    assert provider is not None
    assert provider.api_key == "tok"
    assert provider.base_url == "https://api.anthropic.com"

    # project-specific gateway override path
    monkeypatch.setenv("MAHAVISHNU_LLM_GATEWAY_BASE_URL", "http://127.0.0.1:8471")
    gateway_provider = appmod.MahavishnuApp._init_nanobot_provider(app)
    assert gateway_provider is not None
    assert gateway_provider.base_url == "http://127.0.0.1:8471/v1"
    monkeypatch.delenv("MAHAVISHNU_LLM_GATEWAY_BASE_URL", raising=False)

    # generic exception path
    class _BadProvider:
        def __init__(self, api_key: str, base_url: str) -> None:  # noqa: ARG002
            raise RuntimeError("bad")

    monkeypatch.setitem(
        sys.modules,
        "nanobot.providers",
        SimpleNamespace(OpenAICompatProvider=_BadProvider),
    )
    assert appmod.MahavishnuApp._init_nanobot_provider(app) is None

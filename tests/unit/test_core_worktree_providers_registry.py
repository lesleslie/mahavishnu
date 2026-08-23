"""Tests for ``mahavishnu.core.worktree_providers.registry.WorktreeProviderRegistry`` (PR-D)."""

from __future__ import annotations

import pytest

from mahavishnu.core.worktree_providers.errors import ProviderUnavailableError
from mahavishnu.core.worktree_providers.registry import WorktreeProviderRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _FakeProvider:
    def __init__(self, name: str, healthy: bool = True) -> None:
        self._name = name
        self._healthy = healthy

    def provider_name(self) -> str:
        return self._name

    def health_check(self) -> bool:
        return self._healthy

    async def health(self) -> bool:
        return self._healthy


class _FakeResolverCandidate:
    def __init__(self, provider: str) -> None:
        self.provider = provider


class _FakeResolver:
    def __init__(self, candidates: list[_FakeResolverCandidate] | None = None,
                 raise_on_resolve: bool = False) -> None:
        self._candidates = candidates or []
        self._raise = raise_on_resolve

    def resolve(self, *args: object, **kwargs: object) -> list[_FakeResolverCandidate]:
        if self._raise:
            raise RuntimeError("resolver exploded")
        return list(self._candidates)


# ---------------------------------------------------------------------------
# Backward compat — positional ``providers`` arg still works
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_constructor_no_resolver_works() -> None:
    """Original ``WorktreeProviderRegistry(providers=[...])`` callers unaffected."""
    providers = [_FakeProvider("p1", healthy=True), _FakeProvider("p2", healthy=True)]
    registry = WorktreeProviderRegistry(providers)
    assert await registry.get_available_provider() is providers[0]


@pytest.mark.asyncio
async def test_legacy_skips_unhealthy_returns_first_healthy() -> None:
    providers = [
        _FakeProvider("p1", healthy=False),
        _FakeProvider("p2", healthy=True),
    ]
    registry = WorktreeProviderRegistry(providers)
    assert await registry.get_available_provider() is providers[1]


@pytest.mark.asyncio
async def test_legacy_raises_when_all_unhealthy() -> None:
    providers = [_FakeProvider("p1", healthy=False), _FakeProvider("p2", healthy=False)]
    registry = WorktreeProviderRegistry(providers)
    with pytest.raises(ProviderUnavailableError):
        await registry.get_available_provider()


@pytest.mark.asyncio
async def test_legacy_raises_when_empty() -> None:
    registry = WorktreeProviderRegistry([])
    with pytest.raises(ProviderUnavailableError):
        await registry.get_available_provider()


# ---------------------------------------------------------------------------
# Resolver path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolver_selects_matched_provider() -> None:
    """Resolver-picked candidate is selected when it matches a registered provider."""
    providers = [_FakeProvider("p1", healthy=True), _FakeProvider("p2", healthy=True)]
    resolver = _FakeResolver([_FakeResolverCandidate("p2")])
    registry = WorktreeProviderRegistry(providers, resolver=resolver)
    assert await registry.get_available_provider() is providers[1]


@pytest.mark.asyncio
async def test_resolver_falls_back_to_legacy_when_no_candidates() -> None:
    providers = [_FakeProvider("p1", healthy=True)]
    resolver = _FakeResolver(candidates=[])  # no candidates
    registry = WorktreeProviderRegistry(providers, resolver=resolver)
    assert await registry.get_available_provider() is providers[0]


@pytest.mark.asyncio
async def test_resolver_falls_back_to_legacy_on_resolver_fault() -> None:
    """Resolver exceptions fall through to the legacy health-fallback."""
    providers = [_FakeProvider("p1", healthy=True)]
    resolver = _FakeResolver(raise_on_resolve=True)
    registry = WorktreeProviderRegistry(providers, resolver=resolver)
    assert await registry.get_available_provider() is providers[0]


@pytest.mark.asyncio
async def test_resolver_picks_unhealthy_provider_falls_back() -> None:
    """If the resolver picks a registered provider that's unhealthy,
    we fall back to the legacy health-fallback (don't error out)."""
    providers = [
        _FakeProvider("p1", healthy=False),  # resolver picks this (unhealthy)
        _FakeProvider("p2", healthy=True),
    ]
    resolver = _FakeResolver([_FakeResolverCandidate("p1")])
    registry = WorktreeProviderRegistry(providers, resolver=resolver)
    # Resolver picks p1 (unhealthy) → fall back to legacy → p2 wins
    assert await registry.get_available_provider() is providers[1]


def test_resolver_constructor_default_domain_and_key() -> None:
    """Default resolver_domain / resolver_key match ADR §4 contract."""
    providers = [_FakeProvider("p1")]
    resolver = _FakeResolver()
    registry = WorktreeProviderRegistry(providers, resolver=resolver)
    assert registry._resolver_domain == "adapter"
    assert registry._resolver_key == "worktree-provider"

"""Provider registry with automatic fallback + capability-based resolver."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from .errors import ProviderUnavailableError

if TYPE_CHECKING:
    from .base import WorktreeProvider

logger = logging.getLogger(__name__)


class WorktreeProviderRegistry:
    """Registry with automatic fallback + Oneiric resolver wiring (ADR §4).

    Two selection paths:

    1. **Resolver path** (preferred when ``resolver`` is set): capability-
       based selection via Oneiric's ``Resolver.resolve(domain, key,
       capabilities=[...], require_all=True)``. Honors
       ``ResolverSettings.selections[domain][key]`` overrides via
       ``traced_decision`` OTel span.

    2. **Legacy path** (fallback): ordered health-based fallback. The
       first provider whose ``health_check()`` returns ``True`` wins.

    The resolver path is selected automatically when ``resolver`` is
    set at construction. Legacy callers (positional ``providers`` only)
    keep the original health-fallback behavior with no breaking change.
    """

    def __init__(
        self,
        providers: list[WorktreeProvider] | None = None,
        *,
        resolver: Any | None = None,
        resolver_domain: str = "adapter",
        resolver_key: str = "worktree-provider",
    ) -> None:
        """Initialize registry.

        Args:
            providers: Ordered list of legacy providers (used when
                resolver returns None or is unset).
            resolver: Oneiric ``Resolver`` instance (optional). When
                set, ``get_available_provider`` consults it first.
            resolver_domain: Resolver domain key (default ``"adapter"``).
            resolver_key: Resolver selection key
                (default ``"worktree-provider"``).
        """
        self._providers = providers or []
        self._resolver = resolver
        self._resolver_domain = resolver_domain
        self._resolver_key = resolver_key
        self._provider_health: dict[str, bool] = {}
        self._last_health_check: dict[str, float] = {}

        logger.info(
            f"WorktreeProviderRegistry initialized with {len(self._providers)} "
            f"providers (resolver={resolver is not None}): "
            f"{', '.join(p.provider_name() for p in self._providers)}"
        )

    async def get_available_provider(self) -> WorktreeProvider:
        """Get an available provider.

        Tries the resolver first (when configured). If the resolver
        returns a provider candidate that matches one of our registered
        providers, use it. Otherwise falls through to the legacy
        ordered health-fallback.
        """
        # 1. Resolver path
        if self._resolver is not None:
            try:
                # Capability-based selection. ``require_all=True`` ensures
                # only candidates declaring BOTH "worktree" + "v4" are
                # considered. The resolver scores by capability match
                # count, then priority, then registry order.
                candidates = self._resolver.resolve(
                    self._resolver_domain,
                    self._resolver_key,
                    capabilities=["worktree", "v4"],
                    require_all=True,
                )
            except Exception as exc:  # noqa: BLE001 — best-effort resolver; logged + falls back to legacy health check
                # pragma: no cover - resolver faults
                logger.warning(
                    "worktree-resolver-fault",
                    extra={
                        "domain": self._resolver_domain,
                        "key": self._resolver_key,
                        "error": str(exc),
                    },
                )
                candidates = []

            if candidates:
                # Pick highest-scoring candidate (resolver already
                # sorts by capability match count + priority).
                top = candidates[0]
                # Match against our registered providers by name.
                for p in self._providers:
                    if p.provider_name() == getattr(top, "provider", None):
                        try:
                            # v4 providers expose ``health()`` (returns
                            # HealthReport); v1 providers only have
                            # ``health_check()`` (returns bool). Cast
                            # to Any because ``hasattr`` doesn't narrow
                            # for ty; runtime check is correct.
                            from typing import cast

                            if hasattr(p, "health") and await cast("Any", p).health():
                                self._provider_health[p.provider_name()] = True
                                return p
                        except Exception:  # noqa: BLE001 — best-effort health probe; logged + falls through to legacy path
                            logger.warning(
                                "worktree-resolver-selected-unhealthy",
                                extra={"provider": p.provider_name()},
                            )
                # No registered provider matched the resolver's pick.
                # Fall through to legacy path below.

        # 2. Legacy path: ordered health fallback
        for provider in self._providers:
            provider_name = provider.provider_name()
            try:
                # Check if provider is healthy
                if not provider.health_check():
                    logger.warning(f"Provider {provider_name} is unhealthy, skipping")
                    self._provider_health[provider_name] = False
                    continue

                # Provider is healthy
                self._provider_health[provider_name] = True
                self._last_health_check[provider_name] = asyncio.get_event_loop().time()

                logger.debug(f"Using provider: {provider_name}")
                return provider

            except Exception as e:
                logger.warning(
                    f"Provider {provider_name} health check failed: {e}",
                    exc_info=True,
                )
                self._provider_health[provider_name] = False
                continue

        # No provider available
        provider_names = [p.provider_name() for p in self._providers]
        error_msg = f"No worktree providers available. Tried: {', '.join(provider_names)}"

        logger.error(error_msg)
        raise ProviderUnavailableError(
            message=error_msg,
            details={"provider_count": len(self._providers)},
            providers=provider_names,
        )

    def get_provider_health(self) -> dict[str, bool]:
        """Get health status of all providers.

        Returns:
            Dictionary mapping provider name to health status
        """
        return self._provider_health.copy()

    def get_primary_provider(self) -> WorktreeProvider:
        """Get the primary (first) provider.

        Returns:
            Primary provider instance

        Raises:
            IndexError: If no providers configured
        """
        if not self._providers:
            raise IndexError("No providers configured in registry")

        return self._providers[0]

    async def health_check_loop(
        self,
        interval_seconds: float = 30.0,
    ) -> None:
        """Periodically check health of all providers.

        Runs in the background to update provider health status.
        Useful for monitoring and alerting.

        Args:
            interval_seconds: Seconds between health checks
        """
        logger.info(f"Starting provider health check loop (interval={interval_seconds}s)")

        while True:
            try:
                await asyncio.sleep(interval_seconds)

                for provider in self._providers:
                    provider_name = provider.provider_name()

                    try:
                        is_healthy = provider.health_check()
                        self._provider_health[provider_name] = is_healthy
                        self._last_health_check[provider_name] = asyncio.get_event_loop().time()

                        if not is_healthy:
                            logger.warning(f"Provider {provider_name} is unhealthy")
                        else:
                            logger.debug(f"Provider {provider_name} is healthy")

                    except Exception:
                        logger.exception(
                            "Health check failed",
                            extra={"provider": provider_name},
                        )
                        self._provider_health[provider_name] = False

            except asyncio.CancelledError:
                logger.info("Provider health check loop cancelled")
                break
            except Exception:
                logger.exception("Error in health check loop")
                # Continue loop despite errors

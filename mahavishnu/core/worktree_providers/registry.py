"""Provider registry with automatic fallback."""

import asyncio
import logging
from typing import Any

from .base import WorktreeProvider
from .errors import ProviderUnavailableError

logger = logging.getLogger(__name__)


class WorktreeProviderRegistry:
    """Registry with automatic fallback for resilience.

    This registry manages multiple worktree providers with automatic fallback:
    - Tries providers in order (primary first)
    - Skips unhealthy providers
    - Raises ProviderUnavailableError if all providers fail

    Example:
        >>> providers = [SessionBuddyWorktreeProvider(), DirectGitWorktreeProvider()]
        >>> registry = WorktreeProviderRegistry(providers)
        >>> provider = await registry.get_available_provider()
        >>> await provider.create_worktree(...)
    """

    def __init__(self, providers: list[WorktreeProvider]) -> None:
        """Initialize registry with ordered providers.

        Args:
            providers: Ordered list of providers (primary first)
        """
        self._providers = providers
        self._provider_health: dict[str, bool] = {}
        self._last_health_check: dict[str, float] = {}

        logger.info(
            f"WorktreeProviderRegistry initialized with {len(providers)} providers: "
            f"{', '.join(p.provider_name() for p in providers)}"
        )

    async def get_available_provider(self) -> WorktreeProvider:
        """Get first available provider from registry.

        Tries each provider in order, skipping unhealthy ones.
        Returns the first provider that passes health_check().

        Returns:
            Available provider instance

        Raises:
            ProviderUnavailableError: If no providers are healthy
        """
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
                # Provider health check raised an exception
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

                    except Exception as e:
                        logger.error(
                            f"Health check failed for {provider_name}: {e}",
                            exc_info=True,
                        )
                        self._provider_health[provider_name] = False

            except asyncio.CancelledError:
                logger.info("Provider health check loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in health check loop: {e}", exc_info=True)
                # Continue loop despite errors

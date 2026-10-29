"""Per-call provider failover for the Agno adapter.

Agno's agent loop calls :meth:`agno.models.base.Model.invoke` (or
``ainvoke``) once per turn — see
``agno.models.base.Model._process_model_response`` — so overriding those
two methods is enough to fail over *mid-loop*, not merely when the model
is constructed.

This matters because a provider can fail after the agent has started:
the MiniMax API can rate-limit or go down between the first and the fifth
tool call. A chain that is only consulted at construction time would fail
the whole run; a chain consulted per call keeps the run alive on the local
llama-server.

Tool-call transcripts stay compatible across the failover. Agno formats
the message list itself and hands the same ``messages`` to whichever
model answers, so a fallback provider receives the previous provider's
``role="tool"`` turns in the standard OpenAI chat-completions shape —
which every provider in the chain speaks.

req: REQ-AGNO-007
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agno.models.base import Model
from oneiric.core.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from agno.models.base import ModelResponse

logger = get_logger(__name__)


@dataclass
class FallbackModel(Model):
    """An Agno model that fails over across providers on every call.

    The models are tried in order. The first one that returns a response
    wins; a provider that raises is logged at WARNING and the next one is
    tried. If every provider fails, the last error is re-raised so nothing
    is swallowed.

    Attributes:
        models: The providers to try, in order. The first entry is the
            primary; the rest are fallbacks.
    """

    models: list[Model] = field(default_factory=list)
    id: str = "fallback-chain"
    name: str | None = "fallback-chain"
    provider: str | None = "fallback-chain"

    #: The model that answered the most recent call. The base class calls
    #: ``_parse_provider_response`` on ``self``, so the parse step has to
    #: be delegated to whichever provider actually produced the response.
    _active: Model | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Mirror the primary model's capability flags.

        Agno branches on ``supports_native_structured_outputs`` when it
        decides how to render a structured-output request, so the wrapper
        must advertise what the primary actually supports rather than the
        base class's conservative default.
        """
        super().__post_init__()
        primary = self.models[0] if self.models else None
        if primary is not None:
            self.supports_native_structured_outputs = primary.supports_native_structured_outputs
            self.supports_json_schema_outputs = primary.supports_json_schema_outputs

    def _require_models(self) -> list[Model]:
        """Return the provider list, or raise when the chain is empty."""
        if not self.models:
            raise RuntimeError("FallbackModel has no providers to fall back to")
        return self.models

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        """Invoke the first provider that succeeds.

        Args:
            *args: Positional arguments forwarded to the provider.
            **kwargs: Keyword arguments forwarded to the provider.

        Returns:
            The provider's response.

        Raises:
            Exception: The last provider's error, when every provider
                fails.
        """
        last_error: Exception | None = None
        for model in self._require_models():
            try:
                response = model.invoke(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001, RUF100
                last_error = exc
                logger.warning(
                    "Agno failover: provider %s failed (%s); trying the next provider",
                    getattr(model, "provider", None) or getattr(model, "id", "?"),
                    exc,
                )
                continue
            self._active = model
            return response
        raise last_error if last_error else RuntimeError("FallbackModel has no providers")

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        """Asynchronously invoke the first provider that succeeds.

        Args:
            *args: Positional arguments forwarded to the provider.
            **kwargs: Keyword arguments forwarded to the provider.

        Returns:
            The provider's response.

        Raises:
            Exception: The last provider's error, when every provider
                fails.
        """
        last_error: Exception | None = None
        for model in self._require_models():
            try:
                response = await model.ainvoke(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001, RUF100
                last_error = exc
                logger.warning(
                    "Agno failover: provider %s failed (%s); trying the next provider",
                    getattr(model, "provider", None) or getattr(model, "id", "?"),
                    exc,
                )
                continue
            self._active = model
            return response
        raise last_error if last_error else RuntimeError("FallbackModel has no providers")

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        """Stream from the first provider that produces a chunk.

        A provider that fails *before* yielding anything is skipped and
        the next one is tried. A failure *after* the first chunk cannot be
        retried — the consumer already has a partial response — so it
        propagates.

        Args:
            *args: Positional arguments forwarded to the provider.
            **kwargs: Keyword arguments forwarded to the provider.

        Yields:
            The provider's streamed response chunks.

        Raises:
            Exception: The last provider's error, when every provider
                fails before yielding.
        """
        last_error: Exception | None = None
        for model in self._require_models():
            try:
                stream = model.invoke_stream(*args, **kwargs)
                first = next(stream)
            except StopIteration:
                # The provider produced an empty stream — a valid (if
                # uninteresting) answer, not a failure.
                self._active = model
                return
            except Exception as exc:  # noqa: BLE001, RUF100
                last_error = exc
                logger.warning(
                    "Agno failover: provider %s failed to start streaming (%s); "
                    "trying the next provider",
                    getattr(model, "provider", None) or getattr(model, "id", "?"),
                    exc,
                )
                continue
            self._active = model
            yield first
            yield from stream
            return
        raise last_error if last_error else RuntimeError("FallbackModel has no providers")

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        """Asynchronously stream from the first provider that produces a chunk.

        Args:
            *args: Positional arguments forwarded to the provider.
            **kwargs: Keyword arguments forwarded to the provider.

        Yields:
            The provider's streamed response chunks.

        Raises:
            Exception: The last provider's error, when every provider
                fails before yielding.
        """
        last_error: Exception | None = None
        for model in self._require_models():
            try:
                stream = model.ainvoke_stream(*args, **kwargs)
                first = await anext(stream)
            except StopAsyncIteration:
                self._active = model
                return
            except Exception as exc:  # noqa: BLE001, RUF100
                last_error = exc
                logger.warning(
                    "Agno failover: provider %s failed to start streaming (%s); "
                    "trying the next provider",
                    getattr(model, "provider", None) or getattr(model, "id", "?"),
                    exc,
                )
                continue
            self._active = model
            yield first
            async for chunk in stream:
                yield chunk
            return
        raise last_error if last_error else RuntimeError("FallbackModel has no providers")

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        """Parse a provider response using the provider that produced it."""
        active = self._active or (self.models[0] if self.models else None)
        if active is None:
            raise RuntimeError("FallbackModel has no providers")
        return active._parse_provider_response(response, **kwargs)

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        """Parse a streamed delta using the provider that produced it."""
        active = self._active or (self.models[0] if self.models else None)
        if active is None:
            raise RuntimeError("FallbackModel has no providers")
        return active._parse_provider_response_delta(response)


__all__ = ["FallbackModel"]

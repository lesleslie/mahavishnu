"""Mock model backend (REQ-EVAL-002).

Echoes the prompt back as the model's output. That echo-means-equal
mapping is what lets an ``ExactMatchScorer`` score ``1.0`` whenever the
dataset's ``expected`` equals its ``input`` — so the whole pipeline can
be exercised end to end without a provider credential or a network
call.
"""

from __future__ import annotations

from mahavishnu.core.eval.engine import ModelConfig, ModelResponse, TokenUsage


class MockModelBackend:
    """A model backend that echoes the prompt back."""

    async def complete(self, prompt: str, model_config: ModelConfig) -> ModelResponse:
        """Echo the prompt back as the model's output.

        Args:
            prompt: The prompt to echo.
            model_config: The model configuration. Unused — the mock
                always behaves the same way.

        Returns:
            A response whose output is the prompt.
        """
        tokens = len(prompt) // 4
        return ModelResponse(
            output=prompt,
            usage=TokenUsage(
                prompt_tokens=tokens,
                completion_tokens=tokens,
                total_tokens=len(prompt) // 2,
            ),
            latency_ms=10.0,
        )


__all__ = ["MockModelBackend"]

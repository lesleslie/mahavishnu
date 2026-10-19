#!/usr/bin/env python
"""Example usage of PydanticAIAdapter.

This script demonstrates:
- Adapter initialization with model configuration
- Creating and executing agents
- Fallback model behavior
- MCP tool integration
- Agent chaining

Run with: python examples/pydantic_ai_adapter_example.py
"""

from __future__ import annotations

import asyncio
import logging

# Set OPENAI_API_KEY (Bodai vkey) so Pydantic-AI's OpenAIProvider
# authenticates against the local Bifrost gateway. Pydantic-AI's
# OpenAIProvider reads OPENAI_API_KEY + OPENAI_BASE_URL from env at
# construction; OPENAI_BASE_URL is set in ~/.zshenv. We use the
# importlib bootstrap because ``from examples._bifrost_setup import
# ...`` doesn't resolve when Python prepends ``examples/`` to
# sys.path (the case when running this file directly).
import importlib.util as _il
import sys as _sys
from pathlib import Path as _Path

_shim_path = _Path(__file__).resolve().parent / "_bifrost_setup.py"
_spec = _il.spec_from_file_location("examples._bifrost_setup", _shim_path)
assert _spec is not None and _spec.loader is not None, "_bifrost_setup.py missing"
_module = _il.module_from_spec(_spec)
_sys.modules["examples._bifrost_setup"] = _module
_spec.loader.exec_module(_module)
_module.configure_bifrost_env()

from mahavishnu.adapters.ai.pydantic_ai_adapter import (
    FallbackStrategy,
    MCPToolConfig,
    ModelConfig,
    PydanticAIAdapter,
    PydanticAISettings,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def basic_example() -> None:
    """Basic adapter usage example."""
    print("\n" + "=" * 60)
    print("BASIC EXAMPLE: Simple agent execution")
    print("=" * 60)

    # Configure the primary model
    primary_model = ModelConfig(
        provider="openai",
        model_name="gpt-4",
        temperature=0.7,
        max_tokens=4096,
    )

    # Create settings
    settings = PydanticAISettings(
        primary_model=primary_model,
        fallback_models=[],
        fallback_strategy=FallbackStrategy.DISABLED,
        max_concurrent_agents=5,
    )

    # Create and initialize adapter
    adapter = PydanticAIAdapter(settings)

    # Check if pydantic-ai is available
    if not adapter._pydantic_ai_available:
        print("⚠️  pydantic-ai not installed. Install with: pip install pydantic-ai")
        print("   This example demonstrates configuration only.")
        return

    await adapter.initialize()
    print(f"✓ Adapter initialized: {adapter.name}")
    print(f"  Capabilities: {adapter.capabilities}")

    # Execute a simple task. Pass output_type=str so Pydantic AI has a
    # valid output schema (Agent() rejects None — see pydantic_ai UserError).
    result = await adapter.execute(
        task={"prompt": "What is 2 + 2?", "output_type": str},
        repos=[],
    )
    print(f"  Result: {result}")

    await adapter.shutdown()


async def fallback_example() -> None:
    """Demonstrate fallback model behavior."""
    print("\n" + "=" * 60)
    print("FALLBACK EXAMPLE: Primary + fallback models")
    print("=" * 60)

    # Configure primary model (OpenAI)
    primary_model = ModelConfig(
        provider="openai",
        model_name="gpt-4",
        temperature=0.7,
    )

    # Configure fallback model (Anthropic)
    fallback_model = ModelConfig(
        provider="anthropic",
        model_name="claude-sonnet-4-5",
        temperature=0.5,
    )

    # Configure OpenAI-compatible as second fallback
    openai_fallback = ModelConfig(
        provider="openai",
        model_name="llama3",
        base_url="http://localhost:8081",
    )

    settings = PydanticAISettings(
        primary_model=primary_model,
        fallback_models=[fallback_model, openai_fallback],
        fallback_strategy=FallbackStrategy.SEQUENTIAL,
    )

    adapter = PydanticAIAdapter(settings)

    if not adapter._pydantic_ai_available:
        print("⚠️  pydantic-ai not installed. Configuration shown:")
        print(f"  Primary: {primary_model.safe_string()}")
        print(f"  Fallbacks: {[m.safe_string() for m in settings.fallback_models]}")
        print(f"  Strategy: {settings.fallback_strategy}")
        return

    await adapter.initialize()

    # If primary fails, adapter will try fallbacks in order. output_type=str
    # so Pydantic AI has a valid output schema for Agent().
    result = await adapter.execute(
        task={"prompt": "Analyze the sentiment: 'I love this product!'", "output_type": str},
        repos=[],
    )
    print(f"  Result: {result}")

    await adapter.shutdown()


async def mcp_tools_example() -> None:
    """Demonstrate MCP tool integration."""
    print("\n" + "=" * 60)
    print("MCP TOOLS EXAMPLE: Native MCP tool integration")
    print("=" * 60)

    # Configure MCP tools
    mcp_tools = [
        MCPToolConfig(
            name="filesystem",
            command="mcp-filesystem",
            args=["--root", "/tmp/workspace"],
            enabled=True,
        ),
        MCPToolConfig(
            name="github",
            command="mcp-github",
            env={"GITHUB_TOKEN": "${GITHUB_TOKEN}"},
            enabled=True,
        ),
    ]

    settings = PydanticAISettings(
        primary_model=ModelConfig(
            provider="anthropic",
            model_name="claude-sonnet-4-5",
        ),
        mcp_tools=mcp_tools,
    )

    adapter = PydanticAIAdapter(settings)

    if not adapter._pydantic_ai_available:
        print("⚠️  pydantic-ai not installed. Configuration shown:")
        print(f"  MCP Tools configured: {[t.name for t in mcp_tools]}")
        return

    await adapter.initialize()
    print(f"✓ MCP tools initialized: {list(adapter._mcp_servers.keys())}")

    # Agent can now use MCP tools. output_type=str so Pydantic AI has a
    # valid output schema for Agent().
    result = await adapter.execute(
        task={
            "prompt": "List files in the workspace and summarize the project structure",
            "tools": ["filesystem"],
            "output_type": str,
        },
        repos=[],
    )
    print(f"  Result: {result}")

    await adapter.shutdown()


async def agent_chaining_example() -> None:
    """Demonstrate agent chaining pattern."""
    print("\n" + "=" * 60)
    print("AGENT CHAINING EXAMPLE: Multi-step workflows")
    print("=" * 60)

    settings = PydanticAISettings(
        primary_model=ModelConfig(
            provider="openai",
            model_name="gpt-4",
        ),
    )

    adapter = PydanticAIAdapter(settings)

    if not adapter._pydantic_ai_available:
        print("⚠️  pydantic-ai not installed. Concept demonstration:")
        print("  1. Research Agent → Gathers information")
        print("  2. Analysis Agent → Processes and analyzes")
        print("  3. Writer Agent → Produces final output")
        return

    await adapter.initialize()

    # Create specialized agents. Pass output_type=str so Pydantic AI has a
    # valid output schema (Agent() rejects None — see pydantic_ai UserError).
    research_agent = await adapter.create_agent(
        name="researcher",
        instructions="You are a research assistant. Gather and summarize information.",
        output_type=str,
    )

    analysis_agent = await adapter.create_agent(
        name="analyst",
        instructions="You are an analyst. Process data and identify patterns.",
        output_type=str,
    )

    writer_agent = await adapter.create_agent(
        name="writer",
        instructions="You are a technical writer. Create clear documentation.",
        output_type=str,
    )

    # Chain agents: research → analysis → writing
    result = await adapter.chain_agents(
        agent_ids=[research_agent, analysis_agent, writer_agent],
        initial_prompt="Research Python async patterns and create a summary guide",
    )
    print(f"  Final result: {result}")

    await adapter.shutdown()


async def health_check_example() -> None:
    """Demonstrate health check functionality."""
    print("\n" + "=" * 60)
    print("HEALTH CHECK EXAMPLE: Monitoring adapter status")
    print("=" * 60)

    settings = PydanticAISettings(
        primary_model=ModelConfig(
            provider="openai",
            model_name="gpt-4",
        ),
    )

    adapter = PydanticAIAdapter(settings)

    # Check health before initialization
    health = await adapter.get_health()
    print(f"  Before init: {health['status']}")
    print(f"    Reason: {health['details'].get('reason', 'N/A')}")

    if adapter._pydantic_ai_available:
        await adapter.initialize()

        # Check health after initialization
        health = await adapter.get_health()
        print(f"  After init: {health['status']}")
        print(f"    Primary model: {health['details'].get('primary_model', 'N/A')}")

        await adapter.shutdown()


async def main() -> None:
    """Run all examples."""
    print("\n" + "=" * 60)
    print("PYDANTIC-AI ADAPTER EXAMPLES")
    print("=" * 60)
    print("\nThese examples demonstrate the PydanticAIAdapter capabilities.")
    print("Install pydantic-ai to run the full examples:")
    print("  pip install pydantic-ai")

    await basic_example()
    await fallback_example()
    await mcp_tools_example()
    await agent_chaining_example()
    await health_check_example()

    print("\n" + "=" * 60)
    print("EXAMPLES COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

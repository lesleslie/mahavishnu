"""No provider carries a ``prompt_cache`` block, and here is why.

Bifrost's per-provider ``prompt_cache`` block (``auto_inject``, ``ttl``,
``cache_control_injection_points``) synthesizes cache breakpoints for
requests that carry **none**. Its own upstream schema says so plainly:

    "Synthesize prompt-cache breakpoints for requests that carry none.
     Off by default. Agentic clients such as Codex send no cache markers,
     so providers that cache implicitly slide the cached prefix onto the
     latest message and bill a cache write every turn."

    "Requests that already carry their own cache_control or
     prompt_cache_breakpoint are never modified."

Claude Code always carries its own ``cache_control`` markers, so the
block is skipped entirely for this gateway's traffic -- not overridden,
*skipped*. Adding it would look like enabling caching and change nothing
at all, which is the most expensive kind of no-op: it reads as a fix.

The TTL that the block could have set is reachable from the client
instead. Claude Code v2.1.323 exposes ``promptCacheTtl`` /
``CLAUDE_CODE_PROMPT_CACHE_TTL`` (main conversation) and
``subagentPromptCacheTtl`` / ``CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL``
(everything else), both ``"5m"`` or ``"1h"``. Its own description of the
default is the reason the lever was left alone: "Unset = automatic: 1
hour on a Claude subscription within its usage limits, 5 minutes on an
API key, Bedrock, Vertex or Foundry." This gateway authenticates with a
virtual key -- the API-key branch -- so the effective TTL was always
5 minutes.

The lever is left unused on purpose, not overlooked. It was worth about
$70/month against the 11-06..11-08 traffic and about $0/month against
the traffic that follows it, because the population that resumes a
session after a pause collapsed by 97%. See
``docs/decisions/2026-11-08-bifrost-cache-layers.md``.

If a future change adds Codex traffic (the client the block was built
for), this guard is what should be revisited -- not the other way round.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

# All tests in this module are unit tests; mark them so the
# integration selector can skip them in fast feedback runs.
pytestmark = pytest.mark.unit

TEMPLATE = (
    Path(__file__).resolve().parents[2] / "config" / "bifrost" / "config.template.json"
)

#: The provider that carries Claude Code's traffic. The block would be
#: skipped for it whatever it said, but it is named here so a future
#: change that adds the block to the wrong provider is caught too.
CLAUDE_CODE_PROVIDERS = ("minimax-anthropic", "minimax-openai")


@pytest.fixture(scope="module")
def template() -> dict[str, Any]:
    """The repo's Bifrost config template -- the durable source of truth.

    Asserting against the template rather than the live config means
    the guard survives an operator editing their live copy, and still
    catches a regression landing in the repo.
    """
    if not TEMPLATE.exists():
        pytest.skip(f"Bifrost config template not present at {TEMPLATE}")
    return json.loads(TEMPLATE.read_text(encoding="utf-8"))


def test_no_provider_carries_a_prompt_cache_block(
    template: dict[str, Any],
) -> None:
    """No provider may carry a ``prompt_cache`` block.

    The block is skipped for any request that already carries its own
    ``cache_control`` -- which is every Claude Code request -- so adding
    it here would change nothing while looking like it enabled caching.
    """
    providers = template.get("providers", {})
    assert providers, "the template declares no providers at all"

    offenders = [
        name
        for name, provider in providers.items()
        if isinstance(provider, dict) and "prompt_cache" in provider
    ]
    assert not offenders, (
        f"provider(s) {offenders} carry a prompt_cache block. Bifrost skips that "
        "block for any request that already carries its own cache_control "
        "markers, which is every Claude Code request, so it would be a no-op "
        "that reads as an enable. The TTL it could set is reachable from the "
        "client instead, via CLAUDE_CODE_PROMPT_CACHE_TTL."
    )


def test_the_provider_cache_is_not_configured_anywhere(
    template: dict[str, Any],
) -> None:
    """The key must not appear anywhere in the template.

    A nested placement -- under ``custom_provider_config``, say -- would
    satisfy the per-provider check above while still being a no-op, so
    the whole template is checked.
    """
    assert "prompt_cache" not in json.dumps(template), (
        "the template mentions prompt_cache somewhere other than a provider "
        "block; the whole key is a no-op for Claude Code traffic"
    )


def test_the_claude_code_providers_are_still_declared(
    template: dict[str, Any],
) -> None:
    """The guard above is only meaningful if these providers still exist.

    A rename would silently turn the test above into a no-op, so the
    names the decision depends on are pinned.
    """
    providers = template.get("providers", {})
    for name in CLAUDE_CODE_PROVIDERS:
        assert name in providers, (
            f"provider {name!r} is gone from the template; the decision record "
            "and the README section it backs refer to it by name"
        )

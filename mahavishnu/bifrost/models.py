"""Per-harness descriptors for the Bifrost client toggles.

req: REQ-BIFROST-025

``scripts/bifrost-toggle-claude-url`` and ``scripts/bifrost-toggle-qwen-url``
were near-duplicates -- the Qwen one's own docstring said it "mirrors" the
Claude one. The only things that actually vary between harnesses are captured
here as data; :mod:`mahavishnu.bifrost.toggles` holds the single state machine.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclasses_field
from pathlib import Path

from .paths import BIFROST_BACKUP_DIR, DEFAULT_BIFROST_HOST, DEFAULT_BIFROST_PORT

VIRTUAL_KEY_HEADER = "x-bf-vk"

#: Header the gateway's CEL routing rules match on to pin a harness to one
#: provider. Bifrost evaluates routing rules against request headers, and
#: ``ANTHROPIC_CUSTOM_HEADERS`` is how Claude Code sends them.
ROUTE_HEADER = "x-bf-route"

#: Route value that pins Claude Code to the Anthropic-native MiniMax path.
#:
#: The gateway config defines two providers that both claim ``MiniMax-M3``:
#: ``minimax-anthropic`` (base type ``anthropic`` -> MiniMax's own
#: ``/anthropic/v1/messages``, which returns genuine Anthropic responses with
#: signed thinking blocks) and ``minimax-openai`` (base type ``openai`` ->
#: MiniMax's ``/v1/chat/completions``, which returns reasoning *inline* in
#: the assistant text, because only Bifrost's native ``minimax`` provider
#: sends ``reasoning_split``). Bare model-name resolution cannot choose
#: between them -- this header makes the choice explicit.
ROUTE_ANTHROPIC_NATIVE = "anthropic_native"

#: Traffic class for Claude Code's cache bucket.
#:
#: The gateway's semantic cache resolves a request's bucket from the
#: ``x-bf-cache-key`` header, falling back to the plugin's shared
#: ``default_cache_key`` when the header is absent. Claude Code's system
#: prompt carries the current date, working directory, and environment
#: details, and the plugin is configured to exclude the system prompt from
#: the cache key -- so in the shared bucket two Claude Code sessions that
#: start from the same instruction can be served each other's cached
#: response. A class of its own keeps Claude Code out of the namespace the
#: rest of the fleet shares.
CACHE_TRAFFIC_CLASS_CLAUDE_CODE = "claude-code"

#: Traffic class for Qwen Code's cache bucket. Same reasoning as
#: :data:`CACHE_TRAFFIC_CLASS_CLAUDE_CODE`: a namespace of its own, so
#: Qwen's entries do not sit in the gateway's shared default.
CACHE_TRAFFIC_CLASS_QWEN_CODE = "qwen-code"

#: Env var holding the Bifrost virtual key. Never inlined into settings.
VIRTUAL_KEY_ENV = "BIFROST_VIRTUAL_KEY"

#: Claude Code's per-slot model defaults, and the id each slot falls back
#: to when the harness talks to MiniMax directly.
#:
#: The gateway's alias table maps ``claude-*-5-5`` onto MiniMax, so a
#: Claude id is a request the GATEWAY understands and the upstream does
#: not: MiniMax's own endpoint knows ``MiniMax-M3`` and
#: ``MiniMax-M3.1-Flash`` and nothing else. Point the harness back at
#: the upstream with a Claude id still in place and every request is
#: refused.
#:
#: The slot ids are kept distinct because they are not interchangeable:
#: the gateway serves ``MiniMax-M3`` for the opus and sonnet slots and
#: ``MiniMax-M3.1-Flash`` for the haiku slot, so a haiku slot pointed at
#: ``MiniMax-M3`` would move the fast slot onto the heavy model.
CC_MODEL_SLOTS: dict[str, str] = {
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "MiniMax-M3",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "MiniMax-M3",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "MiniMax-M3.1-Flash",
}

#: The Claude ids the gateway aliases onto MiniMax. A harness holding one
#: of these is holding a gateway-only id: valid in front of the gateway,
#: refused by the upstream.
CC_GATEWAY_ONLY_MODEL_IDS: frozenset[str] = frozenset(
    {
        "claude-opus-5-5",
        "claude-opus-5.5",
        "claude-opus-4-6",
        "claude-sonnet-5-5",
        "claude-sonnet-4-6",
        "claude-sonnet-4.6",
        "claude-haiku-5-5",
        "claude-haiku-4-5",
        "claude-fable-5-1",
        "claude-mythos-5-1",
    }
)


@dataclass(frozen=True)
class HarnessDescriptor:
    """Everything that differs between a client harness.

    Attributes:
        key: CLI-facing short name (``cc`` / ``qwen``).
        label: Human-readable harness name for help text.
        settings_path: Harness settings file the toggle reads and writes.
        url_env_var: Env key inside ``settings["env"]`` holding the base URL.
        url_suffix: Path appended to ``http://<host>:<port>`` for Bifrost.
        credential_sink: Where the virtual-key header belongs for this
            harness -- ``env`` for Claude Code (``ANTHROPIC_CUSTOM_HEADERS``)
            or ``model`` for Qwen Code (``model.generationConfig``). The
            latter pairs with the runtime-model style this toggle uses: Qwen's
            docs state that ``customHeaders`` under ``model`` applies to
            runtime models with no matching ``modelProviders`` entry, and the
            two levels do not merge.
        restart_note: Harness-specific post-toggle reminder.
        route_header: ``(header, value)`` written alongside the virtual key to
            pin this harness to one gateway provider. ``None`` means the
            harness follows the gateway's own model-name resolution.
        cache_traffic_class: Traffic class whose derived cache bucket this
            harness uses, or ``None`` to leave the bucket to the gateway's
            default. See
            :func:`mahavishnu.bifrost.cache_headers.resolve_cache_bucket`.
            Ignored when ``cache_enabled`` is ``False``.
        cache_enabled: Whether this harness's requests engage the gateway's
            **response** cache at all.

            ``False`` means the toggle writes no bucket header -- and with
            the plugin's ``default_cache_key`` unset, a request that names
            no bucket does not reach the cache at all, so the harness
            neither reads from it nor writes to it.

            This is a decision about the *response* cache only. The
            provider's own prompt cache is a different layer that operates
            on the request's token prefix, is unaffected by any header
            this toggle writes, and on the agent path is the cache that
            actually carries the traffic.
    """

    key: str
    label: str
    settings_path: Path
    url_env_var: str
    url_suffix: str
    credential_sink: str
    restart_note: str
    route_header: tuple[str, str] | None = None
    cache_traffic_class: str | None = None
    cache_enabled: bool = True
    #: The settings keys (inside ``settings["env"]``) holding this
    #: harness's per-slot model defaults, and the upstream-valid id for
    #: each slot. Empty means the harness has no such slot -- Qwen Code
    #: carries its model in a different shape and has no per-slot
    #: default to rewrite.
    #:
    #: The gateway resolves a ``claude-*-5-5`` id onto MiniMax through
    #: its alias table; the upstream provider does not know that id. So
    #: the id is only valid while the gateway is in front, and the
    #: toggle has to put the upstream-valid one back when it is not.
    model_slots: dict[str, str] = dataclasses_field(default_factory=dict)

    @property
    def backup_path(self) -> Path:
        """Path holding this harness's pre-toggle URL and credential."""
        return BIFROST_BACKUP_DIR / f"{self.key}-url-backup.txt"

    def bifrost_url(
        self, host: str = DEFAULT_BIFROST_HOST, port: int = DEFAULT_BIFROST_PORT
    ) -> str:
        """Return the Bifrost base URL for this harness."""
        return f"http://{host}:{port}{self.url_suffix}"


CC_HARNESS = HarnessDescriptor(
    key="cc",
    label="Claude Code",
    settings_path=Path.home() / ".claude" / "settings.json",
    url_env_var="ANTHROPIC_BASE_URL",
    url_suffix="/anthropic",
    credential_sink="env",
    restart_note="restart any running Claude Code session for this to take effect",
    # Claude Code's three model slots. The gateway serves the MiniMax ids
    # unchanged, so the standing default works in front of the gateway
    # and needs no rewrite there; the ids are restored when the harness
    # is pointed back at the upstream, where a gateway-only Claude id
    # would be refused.
    model_slots=CC_MODEL_SLOTS,
    # Claude Code speaks the Anthropic Messages protocol, so it must reach
    # MiniMax over MiniMax's Anthropic-native endpoint to get genuine
    # Anthropic responses. The route header tells the gateway which provider
    # to use; without it the bare model name is ambiguous.
    route_header=(ROUTE_HEADER, ROUTE_ANTHROPIC_NATIVE),
    # Claude Code does NOT use the gateway's response cache. Measured over
    # 48h against this gateway: Claude Code carried 11,077 of 11,103
    # requests (99.8%), and the response cache served 43 of them -- worth
    # $2.60 a month against a $4,832 monthly bill. Meanwhile every
    # consulted request paid an embedding round trip (~950 ms, measured in
    # the plugin's own logs), and 59% of them failed the embedding
    # outright, because a Claude Code turn routinely carries more text than
    # the embedding model's 8192-token input ceiling.
    #
    # It also carried a correctness hazard. The bucket is one static
    # string in this file, so every Claude Code session on the host shares
    # it, and Bifrost's identity scoping partitions entries by virtual key
    # and user -- and Claude Code sends no user id, so all of its sessions
    # land in one scope. Two cross-session cache hits were measured in 24h
    # (both between this repo's own probe sessions): one session was served
    # another's response.
    #
    # The provider's prompt cache is untouched by any of this. It caches
    # the request's token prefix upstream and no header this toggle writes
    # reaches it; on this path it is already serving 91-92% of input
    # tokens from cache, 96-99% per request in steady state.
    #
    # The traffic class is kept so the toggle still recognises and strips
    # a bucket header left by an earlier version.
    cache_traffic_class=CACHE_TRAFFIC_CLASS_CLAUDE_CODE,
    cache_enabled=False,
)

QWEN_HARNESS = HarnessDescriptor(
    key="qwen",
    label="Qwen Code",
    settings_path=Path.home() / ".qwen" / "settings.json",
    url_env_var="OPENAI_BASE_URL",
    url_suffix="/v1",
    credential_sink="model",
    restart_note="restart any running Qwen Code session for this to take effect",
    # Qwen's active model resolves to the ``anthropic`` provider entry, so
    # the toggle points that entry at the gateway's Anthropic surface --
    # which is what gets it MiniMax's Anthropic-native responses with
    # signed thinking blocks, rather than the OpenAI-compatible surface
    # where the reasoning arrives inline. The route header then makes the
    # provider choice explicit instead of leaving it to bare model-name
    # resolution.
    route_header=(ROUTE_HEADER, ROUTE_ANTHROPIC_NATIVE),
    # A bucket of its own, so Qwen's cache entries do not share the
    # gateway's default namespace with the rest of the fleet.
    cache_traffic_class=CACHE_TRAFFIC_CLASS_QWEN_CODE,
)

HARNESSES: dict[str, HarnessDescriptor] = {
    CC_HARNESS.key: CC_HARNESS,
    QWEN_HARNESS.key: QWEN_HARNESS,
}

#: Acceptable aliases so ``claude`` and ``qwen`` work as well as ``cc``.
_ALIASES: dict[str, str] = {
    "cc": "cc",
    "claude": "cc",
    "claude-code": "cc",
    "qwen": "qwen",
    "qwen-code": "qwen",
}


def resolve_harness(name: str) -> HarnessDescriptor:
    """Return the descriptor for ``name``.

    req: REQ-BIFROST-025

    Args:
        name: Harness short name or alias.

    Returns:
        The matching descriptor.

    Raises:
        KeyError: If ``name`` is not a known harness or alias.
    """
    try:
        return HARNESSES[_ALIASES[name.lower()]]
    except KeyError:
        raise KeyError(name) from None

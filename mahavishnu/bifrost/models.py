"""Per-harness descriptors for the Bifrost client toggles.

req: REQ-BIFROST-025

``scripts/bifrost-toggle-claude-url`` and ``scripts/bifrost-toggle-qwen-url``
were near-duplicates -- the Qwen one's own docstring said it "mirrors" the
Claude one. The only things that actually vary between harnesses are captured
here as data; :mod:`mahavishnu.bifrost.toggles` holds the single state machine.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .paths import BIFROST_BACKUP_DIR, DEFAULT_BIFROST_HOST, DEFAULT_BIFROST_PORT

VIRTUAL_KEY_HEADER = "x-bf-vk"

#: Env var holding the Bifrost virtual key. Never inlined into settings.
VIRTUAL_KEY_ENV = "BIFROST_VIRTUAL_KEY"


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
    """

    key: str
    label: str
    settings_path: Path
    url_env_var: str
    url_suffix: str
    credential_sink: str
    restart_note: str

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
)

QWEN_HARNESS = HarnessDescriptor(
    key="qwen",
    label="Qwen Code",
    settings_path=Path.home() / ".qwen" / "settings.json",
    url_env_var="OPENAI_BASE_URL",
    url_suffix="/v1",
    credential_sink="model",
    restart_note="restart any running Qwen Code session for this to take effect",
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

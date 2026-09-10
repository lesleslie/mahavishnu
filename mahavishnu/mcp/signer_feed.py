"""Lifespan-owned signer feed state for Mahavishnu's ``/health`` aggregator.

The :class:`SignerFeedState` is the lifespan's single source of truth
for what the skills_signer feed reports to ``/health``. It bundles:

- the manifest itself (pure data, lives in :mod:`mahavishnu.skills_signer`)
- the four mandatory feed signals required by
  ``mcp-backend-wiring-discipline.md`` (``feed_entities_count``,
  ``feed_last_updated_timestamp``, ``cycles_total``, ``errors_total``)
- the lifespan-owned :class:`SkillsSigner` so Phase 1 ``list_skills`` /
  ``get_skill`` MCP tools can produce signatures without re-reading
  the PEM from disk
- a ``generation`` token so concurrent-app teardown checks can
  verify ownership before clearing state

Why this lives in ``mahavishnu/mcp/`` (not ``mahavishnu/skills_signer/``):

The ``skills_signer`` package is supposed to replicate byte-for-byte
across the 5 Bodai servers. Lifecycle state (counters, timestamps,
generation tokens) is per-server MCP wiring concern. By keeping the
package pure data and adding the feed state here, the cross-server
package stays trivial to copy-paste and the per-server wiring
contract is explicit.

Mahavishnu-specific: this state is created lazily inside ``start()``
because mahavishnu has no async lifespan (per plan §10.3.2 option c).
The /health route is registered before ``start()`` runs to support
launchd's early probe; during the brief warm-up window between
``start()`` entering and ``SignerFeedState`` being constructed,
``/health`` returns 503 with ``checks.skills_signer.error =
"awaiting start()"``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import os
from pathlib import Path
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mahavishnu.skills_signer import PubkeyManifest, SkillsSigner

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level singleton (Phase 1 helper surface).
#
# Mahavishnu's ``start()`` constructs the SignerFeedState after the
# FastMCP app is built (per plan §10.3.2 option c — mahavishnu has no
# async lifespan). Concurrent app instances (tests, hot reload)
# overwrite this; the launchd wrapper tolerates up to 120s of warm-up
# before considering the process failed.
#
# The lock pattern mirrors the akosha reference impl byte-for-byte:
# a ``threading.Lock`` guards the singleton swap so concurrent calls
# to ``init_signer_feed_state()`` cannot tear the singleton.
# ---------------------------------------------------------------------------

_signer_feed_state: SignerFeedState | None = None
_signer_state_lock = threading.Lock()


def init_signer_feed_state() -> SignerFeedState:
    """Load or create the persisted signing keypair, build the manifest,
    and install a fresh :class:`SignerFeedState` as the module singleton.

    Idempotent within a single ``start()`` call (subsequent calls
    overwrite the singleton, bumping the generation token). Tests
    that want a clean slate call :func:`reset_signer_feed_state`.

    The :class:`SkillsSigner` is constructed from the persisted keypair
    (no separate disk read) so Phase 1 ``list_skills`` / ``get_skill``
    MCP tools can produce signatures without re-reading the PEM.

    Raises:
        OSError: when the persistence path cannot be created.
        ValueError: when the persisted file is not a valid ed25519
            PEM private key.
    """
    from mahavishnu.skills_signer import (
        SkillsSigner,
        build_pubkey_manifest,
        load_or_create_keypair,
    )

    global _signer_feed_state

    key_path = _resolve_signer_key_path()
    keypair = load_or_create_keypair(key_path)
    manifest = build_pubkey_manifest(keypair)
    server_signer = SkillsSigner.from_keypair(keypair)

    with _signer_state_lock:
        if _signer_feed_state is not None:
            # Re-init: bump the generation token so the old probe's
            # captured state is invalidated.
            new_state = SignerFeedState(
                manifest=manifest,
                signer=server_signer,
                generation=_signer_feed_state.generation + 1,
            )
        else:
            new_state = SignerFeedState(
                manifest=manifest,
                signer=server_signer,
            )
        _signer_feed_state = new_state

    logger.info(
        "skills_signer feed state initialized key_id=%s key_path=%s",
        keypair.key_id,
        key_path,
    )
    return new_state


def get_signer_feed_state() -> SignerFeedState | None:
    """Return the current :class:`SignerFeedState` or ``None`` if not
    yet initialized (start() hasn't completed the signer init step).
    """
    return _signer_feed_state


def reset_signer_feed_state() -> None:
    """Clear the module singleton (test helper).

    Acquires ``_signer_state_lock`` so a concurrent ``init_signer_feed_state``
    call cannot race the reset and leave a stale singleton behind.
    """
    global _signer_feed_state
    with _signer_state_lock:
        _signer_feed_state = None


def _resolve_signer_key_path() -> Path:
    """Resolve the persisted keypair path for Mahavishnu.

    Default: ``~/.mahavishnu/state/skills_signer/private_key.pem``.
    Override via ``MAHAVISHNU_SKILLS_SIGNER_KEY_PATH`` for tests and
    non-standard locations.
    """
    env_path = os.getenv("MAHAVISHNU_SKILLS_SIGNER_KEY_PATH")
    if env_path:
        return Path(env_path).expanduser()
    return Path.home() / ".mahavishnu" / "state" / "skills_signer" / "private_key.pem"


@dataclass
class SignerFeedState:
    """Lifespan-owned state for the skills_signer ``/health`` feed.

    Constructed at lifespan startup after the keypair is loaded/persisted
    and the manifest is built. Mutation happens only via the
    :meth:`record_cycle` / :meth:`record_error` helpers so the
    ``last_updated_timestamp`` stays consistent with the cycle counter.

    Attributes:
        manifest: the :class:`PubkeyManifest` published in ``/health``.
        signer: the :class:`SkillsSigner` for producing Phase 1
            ``get_skill`` / ``get_agent`` response signatures.
        last_updated_timestamp: unix timestamp of the most recent update
            (initial creation or last :meth:`record_cycle`).
        cycles_total: count of successful feed update cycles since startup.
        errors_total: count of failed feed update cycles since startup.
        generation: monotonic token so teardown can detect
            cross-app state contamination. Incremented whenever the
            state is rebuilt (e.g., after a key load failure).
    """

    manifest: PubkeyManifest
    signer: SkillsSigner
    last_updated_timestamp: float = field(default_factory=time.time)
    cycles_total: int = 0
    errors_total: int = 0
    generation: int = 0

    def record_cycle(self) -> None:
        """Mark a successful feed update. Bumps ``cycles_total`` and
        ``last_updated_timestamp``.
        """
        self.cycles_total += 1
        self.last_updated_timestamp = time.time()

    def record_error(self) -> None:
        """Mark a failed feed update. Bumps ``errors_total`` and
        ``last_updated_timestamp`` (the timestamp is updated even on
        errors so operators can see the feed is still being polled).
        """
        self.errors_total += 1
        self.last_updated_timestamp = time.time()

    def is_ok(self) -> bool:
        """True when the feed has at least one entry. Empty manifests
        return False so the ``/health`` endpoint returns 503.
        """
        return not self.manifest.is_empty()

    def as_dict(self) -> dict[str, object]:
        """Serialize for the ``/health`` payload.

        Returns a flat dict compatible with the other Mahavishnu feed
        entries (``ok``, ``feed_entities_count``,
        ``feed_last_updated_timestamp``, ``cycles_total``,
        ``errors_total``). The manifest data is nested under
        ``key_count`` / ``pubkeys`` for backwards compat with Phase 2/6
        installers that already parse those fields.
        """
        manifest_dict = self.manifest.as_dict()
        return {
            "ok": self.is_ok(),
            "feed": "skills_signer",
            "feed_entities_count": manifest_dict["key_count"],
            "feed_last_updated_timestamp": self.last_updated_timestamp,
            "cycles_total": self.cycles_total,
            "errors_total": self.errors_total,
            "generation": self.generation,
            "key_count": manifest_dict["key_count"],
            "pubkeys": manifest_dict["pubkeys"],
        }


__all__ = [
    "SignerFeedState",
    "get_signer_feed_state",
    "init_signer_feed_state",
    "reset_signer_feed_state",
]

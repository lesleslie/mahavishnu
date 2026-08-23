"""Identity and auth primitives for mahavishnu.

Defines the ``Principal`` type that represents the identity under which a
storage operation is performed. Multi-tenancy in mahavishnu (ADR 015
v4 §5) is enforced at the storage boundary: every worktree and cache
operation takes a ``Principal`` so the storage layer can isolate users,
audit per-principal actions, and apply cleanup policies.

Prior to this module, ``mcp/auth.py`` used bare ``user_id: str`` with no
typed principal object. v4 of ADR 015 introduces ``Principal`` as the
canonical identity type for storage operations; legacy ``user_id``
strings are accepted via ``Principal.from_uid(uid)`` for backward
compatibility.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal


# Cleanup policy applied to a worktree at SessionEnd.
#   - 'mark'  (default): mark worktree abandoned in registry; never auto-remove
#   - 'keep': same as 'mark' but also preserve uncommitted-change snapshot
#   - 'remove': auto-remove the worktree (DESTRUCTIVE; loses uncommitted work)
CleanupPolicy = Literal["mark", "keep", "remove"]


@dataclass(frozen=True, slots=True)
class Principal:
    """Identity for storage operations. Multi-tenant boundary key.

    Constructed via:
      - ``Principal.from_uid(uid)`` for local-host contexts (uid
        derivation from os.getuid())
      - ``Principal.anonymous()`` for serverless / unauthenticated contexts
      - ``Principal.current()`` for the current process's uid

    Attributes:
        uid: Operating-system UID; ``None`` for ``Principal.anonymous()``.
        name: Human-readable identifier (defaults to ``"uid:<n>"`` or
            ``"anonymous"``).
        scopes: Authorization scopes (e.g., ``{"worktree:create", "cache:write"}``).
        cleanup_policy_override: Per-principal override for the cleanup
            policy; ``None`` falls back to the deployment-level default
            (``StorageSettings.cleanup_policy_default``).

    The ``is_anonymous`` property returns ``True`` when no uid is set;
    serverless deployments should create one ``Principal.anonymous()`` per
    invocation rather than reusing a single instance.
    """

    uid: int | None
    name: str
    scopes: frozenset[str] = field(default_factory=frozenset)
    cleanup_policy_override: CleanupPolicy | None = None

    @classmethod
    def from_uid(cls, uid: int, *, name: str | None = None) -> Principal:
        """Construct a Principal from an OS uid.

        Args:
            uid: The POSIX uid (or equivalent on the host platform).
            name: Optional human-readable name. Defaults to ``"uid:<n>"``.

        Returns:
            A Principal with the given uid and a default name.
        """
        return cls(uid=uid, name=name or f"uid:{uid}")

    @classmethod
    def anonymous(cls) -> Principal:
        """Construct an anonymous Principal (uid=None).

        Use one per serverless invocation, not a shared singleton.
        """
        return cls(uid=None, name="anonymous")

    @classmethod
    def current(cls) -> Principal:
        """Construct a Principal from ``os.getuid()`` for the current process.

        Raises:
            OSError: If ``os.getuid()`` is not available (e.g., on Windows
                or in a serverless context where uid is meaningless). Callers
                in those environments should use ``Principal.anonymous()``
                explicitly instead.
        """
        return cls.from_uid(os.getuid())

    @property
    def is_anonymous(self) -> bool:
        """True when the principal has no uid (serverless / unauthenticated)."""
        return self.uid is None

    def has_scope(self, scope: str) -> bool:
        """True if ``scope`` is in this principal's scope set (or scopes is empty=all)."""
        if not self.scopes:
            return True  # empty scopes = all scopes (the default)
        return scope in self.scopes


__all__ = ["CleanupPolicy", "Principal"]

"""XDG Base Directory resolution for app-owned runtime paths.

Session-Buddy's runtime data historically lived under ``~/.claude/data``,
a Claude-Code-specific directory. Storing there asserts that Claude Code
owns the data, but the Bodai components are harness agnostic. This module
resolves the XDG Base Directory locations that replace it.

The four resolvers follow the XDG Base Directory Specification and join
the resolved root with the *owning* app name:

===============  ======================  ==================
XDG variable    Spec default root       Resolver
===============  ======================  ==================
XDG_DATA_HOME   ``~/.local/share``       :func:`data_dir`
XDG_STATE_HOME  ``~/.local/state``       :func:`state_dir`
XDG_CACHE_HOME  ``~/.cache``             :func:`cache_dir`
XDG_CONFIG_HOME ``~/.config``            :func:`config_dir`
===============  ======================  ==================

The owner is always the application that *writes* the file, never the
repository that happens to read it. Mahavishnu's own state uses the
``mahavishnu`` app name; Session-Buddy's reflection store uses
``session-buddy`` even when Mahavishnu is the one opening it.

Environment lookups use ``os.environ.get`` and ``os.path.expanduser``
rather than :meth:`pathlib.Path.home` so a test can override ``HOME``
and the XDG variables.

Importing this module has no side effects: it never creates a directory
and never touches the filesystem.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["cache_dir", "config_dir", "data_dir", "state_dir"]

_DEFAULT_DATA_ROOT = "~/.local/share"
_DEFAULT_STATE_ROOT = "~/.local/state"
_DEFAULT_CACHE_ROOT = "~/.cache"
_DEFAULT_CONFIG_ROOT = "~/.config"


def _resolve_root(env_var: str, default: str) -> Path:
    """Resolve one XDG root from the environment, or the spec default.

    An unset *or empty* environment variable falls back to the default,
    as the XDG Base Directory Specification requires.
    """
    configured = os.environ.get(env_var)
    if configured:
        return Path(os.path.expanduser(configured))
    return Path(os.path.expanduser(default))


def _app_dir(env_var: str, default: str, app: str) -> Path:
    """Resolve an XDG root joined with the owning app name."""
    return _resolve_root(env_var, default) / app


def data_dir(app: str = "session-buddy") -> Path:
    """Return the persistent data directory owned by ``app``.

    Persistent data that must survive restarts and cannot be regenerated.

    Examples:
        >>> data_dir()
        PosixPath('/Users/les/.local/share/session-buddy')
        >>> data_dir("mahavishnu")
        PosixPath('/Users/les/.local/share/mahavishnu')
    """
    return _app_dir("XDG_DATA_HOME", _DEFAULT_DATA_ROOT, app)


def state_dir(app: str = "session-buddy") -> Path:
    """Return the state directory owned by ``app``.

    State that persists across restarts but can be regenerated or
    discarded (locks, queues, logs, sync bookkeeping).

    Examples:
        >>> state_dir()
        PosixPath('/Users/les/.local/state/session-buddy')
    """
    return _app_dir("XDG_STATE_HOME", _DEFAULT_STATE_ROOT, app)


def cache_dir(app: str = "session-buddy") -> Path:
    """Return the regenerable cache directory owned by ``app``.

    Examples:
        >>> cache_dir()
        PosixPath('/Users/les/.cache/session-buddy')
    """
    return _app_dir("XDG_CACHE_HOME", _DEFAULT_CACHE_ROOT, app)


def config_dir(app: str = "session-buddy") -> Path:
    """Return the configuration directory owned by ``app``.

    Examples:
        >>> config_dir()
        PosixPath('/Users/les/.config/session-buddy')
    """
    return _app_dir("XDG_CONFIG_HOME", _DEFAULT_CONFIG_ROOT, app)

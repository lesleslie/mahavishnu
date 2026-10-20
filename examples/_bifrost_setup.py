"""Runtime shim: route Pydantic-AI demos through Bifrost without persisting the vkey.

Importing this module sets ``OPENAI_API_KEY`` in the current process's
``os.environ`` to the ``bodai-pi-pool`` Bifrost virtual key (the same one
used by the Pi pool, which already authenticates successfully against
the gateway). The vkey is read from the local Bifrost config DB at
import time — it is never written to disk and never appears in a shell
command.

Combined with ``OPENAI_BASE_URL=http://127.0.0.1:8471/v1`` (set in
``~/.zshenv``), Pydantic-AI's ``OpenAIProvider`` will send every
chat-completion request through the Bifrost gateway:

  * Pydantic-AI reads ``OPENAI_API_KEY`` and ``OPENAI_BASE_URL`` from
    the environment when the ``OpenAIProvider`` is constructed.
  * Bifrost accepts the bodai-pi-pool vkey as the Authorization Bearer
    token, routes the request to the configured provider (MiniMax-M3
    by default), records it in the request log, and returns a
    chat-completion response in OpenAI's wire format.

Usage at the top of any demo that uses Pydantic-AI:

    from examples._bifrost_setup import configure_bifrost_env
    configure_bifrost_env()

(The import is enough — calling ``configure_bifrost_env()`` is
idempotent and just a marker for readers.)

If the Bifrost config DB is missing or the vkey has been rotated, the
shim logs a warning and leaves ``OPENAI_API_KEY`` unset. The demo will
then surface a 401 "virtual key required" error from Bifrost, which is
the same behaviour as without the shim — no silent fallback.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

_BIFROST_CONFIG_DB = Path.home() / ".config" / "bifrost" / "config.db"
_BIFROST_VKEY_NAME = "bodai-pi-pool"


def _load_bodai_vkey() -> str | None:
    """Read the bodai-pi-pool vkey from the local Bifrost config DB.

    Returns None if the DB or vkey is missing. Never logs the vkey value.
    """
    if not _BIFROST_CONFIG_DB.exists():
        logger.warning(
            "Bifrost config DB not found at %s — leaving OPENAI_API_KEY unset",
            _BIFROST_CONFIG_DB,
        )
        return None
    try:
        with sqlite3.connect(_BIFROST_CONFIG_DB) as con:
            row = con.execute(
                "SELECT value FROM governance_virtual_keys "
                "WHERE name = ? AND is_active = 1",
                (_BIFROST_VKEY_NAME,),
            ).fetchone()
    except sqlite3.Error as exc:
        logger.warning(
            "Failed to read bodai-pi-pool vkey from %s: %s — leaving OPENAI_API_KEY unset",
            _BIFROST_CONFIG_DB,
            exc,
        )
        return None
    if not row:
        logger.warning(
            "Active vkey '%s' not found in %s — leaving OPENAI_API_KEY unset",
            _BIFROST_VKEY_NAME,
            _BIFROST_CONFIG_DB,
        )
        return None
    return row[0]


def configure_bifrost_env() -> None:
    """Set OPENAI_API_KEY for Pydantic-AI to authenticate with Bifrost.

    Always overwrites — even if ``OPENAI_API_KEY`` is already set (e.g. to
    a real OpenAI project key in ``~/.config/secrets.env``). The intent
    of the shim is to redirect Pydantic-AI's chat-completion traffic
    through Bifrost, which requires the bodai-pi-pool vkey as the
    Bearer token. A real OpenAI project key would be rejected by
    Bifrost's vkey validator and the request would 401 out — defeating
    the whole point.

    Operators who intentionally want direct OpenAI traffic for a given
    demo can call :func:`bypass` instead, or set ``BIFROST_SETUP_DISABLED=1``
    in the shell env before launching the demo.
    """
    if os.environ.get("BIFROST_SETUP_DISABLED") == "1":
        logger.debug(
            "BIFROST_SETUP_DISABLED=1 — leaving OPENAI_API_KEY as-is"
        )
        return
    vkey = _load_bodai_vkey()
    if vkey is None:
        return  # warning already logged
    os.environ["OPENAI_API_KEY"] = vkey
    logger.debug(
        "OPENAI_API_KEY set to bodai-pi-pool vkey (length=%d) for Bifrost routing",
        len(vkey),
    )


def bypass() -> None:
    """Skip the Bifrost setup — leave OPENAI_API_KEY (and OPENAI_BASE_URL) as-is.

    Use this for a single demo run when you want direct OpenAI traffic
    for diagnostic purposes:

        $ BIFROST_SETUP_DISABLED=1 python examples/pydantic_ai_agent.py
    """
    logger.debug("BIFROST_SETUP bypass requested")


def configure_via_importlib() -> None:
    """Bootstrap helper for demos that import the shim under ``examples._bifrost_setup``.

    When a demo is invoked as ``python examples/<demo>.py``, Python
    prepends ``examples/`` to ``sys.path`` — *not* the project root —
    so a plain ``from examples._bifrost_setup import ...`` import fails
    with ``ModuleNotFoundError`` from the demo's directory.

    This helper resolves the shim by file path relative to the project
    root (computed from ``__file__``), loads it via ``importlib.util``,
    and calls ``configure_bifrost_env()``. Demos should call this
    immediately after their ``from __future__ import annotations``
    line — before any ``from pydantic_ai import ...`` line.
    """
    import importlib.util as _il
    import sys as _sys

    project_root = Path(__file__).resolve().parent.parent
    shim_path = project_root / "examples" / "_bifrost_setup.py"
    if not shim_path.exists():
        logger.warning(
            "_bifrost_setup shim not found at %s — leaving OPENAI_API_KEY unset",
            shim_path,
        )
        return
    spec = _il.spec_from_file_location("examples._bifrost_setup", shim_path)
    if spec is None or spec.loader is None:
        logger.warning(
            "Could not load spec for %s — leaving OPENAI_API_KEY unset",
            shim_path,
        )
        return
    module = _il.module_from_spec(spec)
    _sys.modules["examples._bifrost_setup"] = module
    spec.loader.exec_module(module)
    module.configure_bifrost_env()


# Module-level side effects are intentionally NOT performed on import.
# Callers must invoke ``configure_bifrost_env()`` (or the
# ``configure_via_importlib()`` bootstrap) explicitly so the vkey is
# read at the moment of demo launch rather than at module load.

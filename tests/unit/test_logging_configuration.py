"""The process log level must survive third-party import side effects.

``crackerjack/__init__.py`` calls, at import time::

    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING),
        cache_logger_on_first_use=True,
    )

Its own comment says it silences structlog "so oneiric's later
``configure_logging(DEBUG)`` call takes effect normally" -- but
``oneiric.core.logging.configure_logging`` is only ever called from
oneiric's CLI. A library consumer (mahavishnu's MCP server) never runs
the oneiric CLI, so structlog stayed pinned at WARNING for the life of
the process and every INFO/DEBUG line was dropped.

That is how a change-point tick loop that had *never once run* stayed
invisible: the lifecycle could not log "started", and the detector
could not log "drift detected".
"""

from __future__ import annotations

import logging
import structlog

from mahavishnu.core.bootstrap import configure_logging
from mahavishnu.core.config import MahavishnuSettings


def _simulate_crackerjack_downgrade() -> None:
    """Reproduce crackerjack's import-time structlog.configure."""
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING),
        cache_logger_on_first_use=True,
    )


def test_configure_logging_restores_the_structlog_level() -> None:
    """After the downgrade, the level must come back."""
    previous_wrapper = structlog.get_config()["wrapper_class"]
    previous_handlers = list(logging.getLogger().handlers)
    previous_level = logging.getLogger().level
    try:
        _simulate_crackerjack_downgrade()
        assert structlog.get_config()["wrapper_class"].__name__ == "BoundLoggerFilteringAtWarning"

        configure_logging(MahavishnuSettings())

        assert structlog.get_config()["wrapper_class"].__name__ == "BoundLoggerFilteringAtInfo"
    finally:
        structlog.configure(wrapper_class=previous_wrapper)
        logging.getLogger().handlers = previous_handlers
        logging.getLogger().setLevel(previous_level)


def test_configure_logging_installs_a_stdlib_root_handler() -> None:
    """224 modules use stdlib logging; without a root handler they are mute."""
    previous_handlers = list(logging.getLogger().handlers)
    previous_level = logging.getLogger().level
    try:
        logging.getLogger().handlers = []
        logging.getLogger().setLevel(logging.WARNING)

        configure_logging(MahavishnuSettings())

        root = logging.getLogger()
        assert root.handlers, "no root handler: every stdlib INFO line is dropped"
        assert root.level <= logging.INFO
    finally:
        logging.getLogger().handlers = previous_handlers
        logging.getLogger().setLevel(previous_level)


def test_configure_logging_never_raises() -> None:
    """Logging setup must never block startup."""
    configure_logging(None)
    configure_logging(MahavishnuSettings())


def test_the_app_restores_logging_after_its_imports() -> None:
    """The app must not leave the process muted after a crackerjack import."""
    import mahavishnu.core.app as app_module

    previous_wrapper = structlog.get_config()["wrapper_class"]
    try:
        _simulate_crackerjack_downgrade()

        app = app_module.MahavishnuApp()

        assert structlog.get_config()["wrapper_class"].__name__ == "BoundLoggerFilteringAtInfo"
        assert app.config is not None
    finally:
        structlog.configure(wrapper_class=previous_wrapper)

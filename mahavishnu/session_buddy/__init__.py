"""Session Buddy integration package for Mahavishnu.

This package exposes the Session Buddy integration modules under
``mahavishnu.session_buddy.*``. The submodule import that
``test_mcp_git_analytics.py`` performs (``from
mahavishnu.session_buddy.integration import SessionBuddyIntegration``)
requires this package to be importable as a regular package — i.e.
this ``__init__`` file must exist. Without it, ``mahavishnu.session_buddy``
falls back to namespace-package semantics and
``mahavishnu.session_buddy.integration`` cannot be imported as a
single dotted path, so any ``monkeypatch.setattr("mahavishnu.session_buddy.integration....", ...)``
in tests fails with ``AttributeError: module 'mahavishnu.session_buddy' has no attribute 'integration'``.
"""

from __future__ import annotations

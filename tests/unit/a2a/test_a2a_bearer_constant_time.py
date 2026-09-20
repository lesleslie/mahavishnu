"""A2A regression tests — locks the Phase 1.5 Bearer fix in.

Per plan §Phase 1.5 Task 4: ``test_auth_uses_constant_time_compare``
locks the A2A fix in.

The pre-Phase-1.5 A2A code used plain ``!=`` to compare bearer
tokens, which is timing-attack-vulnerable. Phase 1.5 replaces that
with ``secrets.compare_digest``. These tests pin that change so a
future refactor cannot silently revert to the vulnerable form.
"""

from __future__ import annotations

import inspect

import pytest

pytestmark = pytest.mark.unit


class TestA2ABearerConstantTime:
    """The A2A Bearer middleware uses ``secrets.compare_digest`` (constant-time)."""

    def test_auth_uses_constant_time_compare(self) -> None:
        """The ``!=`` string compare is forbidden; ``secrets.compare_digest`` is required.

        Pins the plan §Phase 1.5 fix. If a future refactor reverts to
        ``!=``, this test fails — the reviewer sees the regression in
        CI rather than in production.
        """
        from mahavishnu.a2a import server

        source = inspect.getsource(server._A2ABearerMiddleware.__call__)
        assert "secrets.compare_digest" in source, (
            "A2A Bearer middleware must use secrets.compare_digest (Phase 1.5 fix); "
            "plain != is timing-attack-vulnerable"
        )
        # Belt-and-suspenders: forbid the dangerous idioms in this function's
        # source.
        assert "auth != expected" not in source, (
            "A2A Bearer middleware must NOT use plain 'auth != expected' compare"
        )
        assert "auth==expected" not in source.replace(" ", ""), (
            "A2A Bearer middleware must NOT use plain 'auth == expected' compare"
        )

    def test_auth_middleware_does_not_leak_timing_in_source(self) -> None:
        """Sanity: the source itself doesn't reveal a timing leak.

        The middleware should compare full byte strings without
        early-return on length mismatch. ``secrets.compare_digest`` does
        this; ``==``/``!=`` do not (Python's short-circuit evaluation
        returns False on the first mismatched byte, leaking length).
        """
        from mahavishnu.a2a import server

        source = inspect.getsource(server._A2ABearerMiddleware.__call__)
        # ``if not secrets.compare_digest(...)`` is the canonical form.
        # ``if auth != expected`` would be a regression. Use the negated
        # form for symmetry with the canonical ``if not ...`` pattern.
        assert "compare_digest" in source

    def test_secrets_import_is_present(self) -> None:
        """``secrets`` is imported at module level (not local to a function)."""
        from mahavishnu.a2a import server

        module_source = inspect.getsource(server)
        assert "import secrets" in module_source, (
            "A2A server.py must import 'secrets' at module level"
        )

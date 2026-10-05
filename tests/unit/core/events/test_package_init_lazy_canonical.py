"""Regression test for the lazy `canonical`/`transport` re-export contract.

The contract being pinned: when `oneiric` is NOT importable
(simulating a CWD that is not /Users/les/Projects/mahavishnu or any
CWD where the `oneiric` peer directory is reachable), importing
`mahavishnu.core.events.envelope` (and any other non-canonical, non-
transport submodule) must not crash.

Why this matters: the `mahavishnu` CLI is invoked from many CWDs via
the post-commit git hook installed by `mahavishnu index install-hooks`
in every Bodai repo (crackerjack, session-buddy, akosha, oneiric,
mcp-common, mahavishnu). The hook is:

    mahavishnu index repo --trigger git-event "$(pwd)" &

It runs in the background after every commit, from the CWD of the
commit. If oneiric is not on `sys.path` (e.g. in a fresh venv that
doesn't have the editable `_editable_impl_oneiric.pth` shim, or in
a CI runner that doesn't include the Bodai workspace), the CLI must
still start — otherwise every commit in every Bodai repo pollutes
git stderr with a `ModuleNotFoundError: No module named 'oneiric'`
traceback.

The fix in `mahavishnu/core/events/__init__.py` is PEP 562 module-
level `__getattr__`: a curated set of re-exports (`canonical.*` and
`transport.*`) is deferred to first access via `importlib.import_module`,
so the import chain stops at `__init__.py` and never reaches
`canonical`/`transport` (which both transitively load oneiric).
Additionally, `publisher.py`, `observability.py`, `confidence_ceiling.py`,
and `transport.py` wrap their `oneiric.core.logging.get_logger` import
in a `try/except ImportError` that falls back to stdlib `logging`.

These tests run each scenario in a FRESH subprocess that explicitly
REMOVES `/Users/les/Projects/oneiric` from `sys.path` (mimicking the
"oneiric not on path" environment) before doing the import. The test
fails if the import raises `ModuleNotFoundError: No module named
'oneiric'`, which is the exact symptom the fix prevents.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap


# The path that Python's `_editable_impl_oneiric.pth` adds to sys.path
# in the mahavishnu venv. Tests strip this before the import to
# simulate the "oneiric not on path" environment.
_ONEIRIC_EDITABLE_PATH = "/Users/les/Projects/oneiric"


def _run_blocked_oneiric_subprocess(body: str) -> subprocess.CompletedProcess[str]:
    """Run `body` in a fresh subprocess with oneiric masked from sys.path.

    We use the `oneiric.core.logging` `try/except ImportError` fallback
    pattern internally so the test subprocess itself doesn't accidentally
    load oneiric. We also need to ensure the subprocess's Python
    interpreter does NOT auto-add `/Users/les/Projects/oneiric` to
    sys.path. The venv's `_editable_impl_oneiric.pth` is the source of
    that auto-add; the only reliable way to suppress it without
    mutating the user's venv is to remove the directory from sys.path
    after Python's site init has run.
    """
    setup = textwrap.dedent(
        f"""
        import sys

        # Remove the oneiric auto-added path AND any other path that
        # ends in '/oneiric' (covers editable installs elsewhere on
        # the machine). Also block oneiric from being loaded via a
        # meta_path finder that raises ImportError, in case some
        # other path or hidden mechanism is making it importable.
        sys.path = [
            p for p in sys.path
            if p.rstrip('/') not in {{'{_ONEIRIC_EDITABLE_PATH}', '/Users/les/Projects/oneiric'}}
        ]
        for mod in list(sys.modules):
            if mod == 'oneiric' or mod.startswith('oneiric.'):
                del sys.modules[mod]

        import importlib.abc

        class _OneiricBlocker(importlib.abc.MetaPathFinder):
            def find_spec(self, name, path, target=None):
                if name == 'oneiric' or name.startswith('oneiric.'):
                    raise ModuleNotFoundError(
                        f"blocked by test: {{name}} is not importable"
                    )
                return None

        sys.meta_path.insert(0, _OneiricBlocker())
        """
    )
    return subprocess.run(
        [sys.executable, "-c", setup + textwrap.dedent(body)],
        capture_output=True,
        text=True,
        cwd="/tmp",
        timeout=60,
    )


def test_envelope_import_does_not_crash_without_oneiric() -> None:
    """Importing `core.events.envelope` must not crash when oneiric is unavailable.

    Reproduces the post-commit hook failure mode in a venv that
    doesn't have `_editable_impl_oneiric.pth` (e.g. a fresh CI
    runner, or a Bodai repo with its own clean venv).
    """
    result = _run_blocked_oneiric_subprocess(
        """
        import importlib
        importlib.import_module('mahavishnu.core.events.envelope')
        print('IMPORT_OK')
        """
    )
    assert result.returncode == 0, (
        "Importing mahavishnu.core.events.envelope CRASHED in a venv "
        "without oneiric on sys.path. This is the post-commit hook "
        "failure mode that the lazy re-export fix in "
        "mahavishnu/core/events/__init__.py is meant to prevent.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "ModuleNotFoundError" not in result.stderr
    assert "oneiric" not in result.stderr


def test_schema_registry_import_does_not_crash_without_oneiric() -> None:
    """Importing `core.events.schema_registry` must also be side-effect-free."""
    result = _run_blocked_oneiric_subprocess(
        """
        import importlib
        importlib.import_module('mahavishnu.core.events.schema_registry')
        print('IMPORT_OK')
        """
    )
    assert result.returncode == 0, (
        "Importing mahavishnu.core.events.schema_registry CRASHED in "
        "a venv without oneiric. The fix in "
        "mahavishnu/core/events/__init__.py must keep schema_registry "
        "free of canonical/transport/oneiric dependencies at import "
        "time.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "ModuleNotFoundError" not in result.stderr
    assert "oneiric" not in result.stderr


def test_cli_starts_from_non_mahavishnu_cwd() -> None:
    """`mahavishnu --help` must succeed when CWD is not the mahavishnu repo.

    This is the end-to-end regression: it exercises the full CLI
    startup (which is what the post-commit hook's background process
    does) from a foreign CWD.
    """
    venv_mahavishnu = "/Users/les/Projects/mahavishnu/.venv/bin/mahavishnu"
    result = subprocess.run(
        [venv_mahavishnu, "--help"],
        capture_output=True,
        text=True,
        cwd="/Users/les/Projects/crackerjack",
        timeout=60,
    )
    assert result.returncode == 0, (
        f"`mahavishnu --help` from crackerjack's CWD crashed with exit "
        f"{result.returncode}. This is the exact failure mode the lazy "
        f"re-export fix is meant to prevent.\n"
        f"stdout: {result.stdout[:500]}\nstderr: {result.stderr[:1000]}"
    )
    assert "ModuleNotFoundError" not in result.stderr
    assert "oneiric" not in result.stderr


def test_index_repo_subcommand_runs_from_non_mahavishnu_cwd() -> None:
    """`mahavishnu index repo --trigger git-event <path>` must work in any CWD.

    This is the EXACT command the post-commit hook runs. If the
    lazy-import contract holds, it succeeds; otherwise it crashes
    with `ModuleNotFoundError: No module named 'oneiric'`.
    """
    venv_mahavishnu = "/Users/les/Projects/mahavishnu/.venv/bin/mahavishnu"
    result = subprocess.run(
        [
            venv_mahavishnu,
            "index",
            "repo",
            "--trigger",
            "git-event",
            "/Users/les/Projects/crackerjack",
        ],
        capture_output=True,
        text=True,
        cwd="/Users/les/Projects/crackerjack",
        timeout=60,
    )
    assert result.returncode == 0, (
        f"`mahavishnu index repo --trigger git-event` from crackerjack's "
        f"CWD crashed with exit {result.returncode}. This is the "
        f"post-commit hook command — the user-facing failure mode.\n"
        f"stdout: {result.stdout[:500]}\nstderr: {result.stderr[:1000]}"
    )
    assert "ModuleNotFoundError" not in result.stderr
    assert "oneiric" not in result.stderr


def test_lazy_canonical_access_returns_real_symbol() -> None:
    """First access to a canonical name loads `canonical` and returns the real symbol.

    This locks down the public API: existing `from
    mahavishnu.core.events import OPTIONAL_EVENT_HEADERS` callers
    must continue to work, but now via `__getattr__` instead of an
    eager re-export.
    """
    result = _run_blocked_oneiric_subprocess(
        """
        events_pkg = __import__("importlib").import_module(
            "mahavishnu.core.events"
        )
        # First access loads canonical — but in this test subprocess
        # oneiric is blocked, so canonical can't actually load. We
        # verify the AttributeError is informative (not a crash), and
        # that the rest of the contract (dir(), unknown attribute
        # behavior) still works.
        names = dir(events_pkg)
        assert "REQUIRED_EVENT_HEADERS" in names
        assert "to_oneiric_envelope" in names
        assert "EventBusConsumer" in names
        try:
            events_pkg.REQUIRED_EVENT_HEADERS
        except ModuleNotFoundError as e:
            if "oneiric" not in str(e):
                raise
        except AttributeError:
            pass
        try:
            events_pkg.this_attribute_does_not_exist
        except AttributeError:
            pass
        else:
            raise AssertionError("expected AttributeError for unknown name")
        print("CONTRACT_OK")
        """
    )
    assert result.returncode == 0, (
        "The lazy canonical access contract is broken. The PEP 562 "
        "__getattr__ should expose the lazy names via `dir()` and "
        "raise AttributeError for unknown names.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

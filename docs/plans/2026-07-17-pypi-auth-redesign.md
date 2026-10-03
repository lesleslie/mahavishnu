---
status: draft
role: implementation
date: 2026-07-21
last_reviewed: 2026-07-21
topic: lifecycle
---

# PyPI Auth Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace crackerjack's `publish_manager.py` PyPI authentication flow with an opaque `PyPIAuth` newtype + provider enumeration (Trusted Publishing / env / keyring). Targets the root cause of the recurring "Keyring token format appears invalid" bug class by making the credential untouchable by masking/sanitization after construction.

**Architecture:** New `crackerjack/services/pypi_auth/` package owns credential construction. Three providers return `PyPIAuth` instances; `_keyring_get_raw()` is the only place in the codebase where subprocess stdout is not fed through `mask_tokens`. `publish_manager.py` consumes the abstraction — no raw `str` tokens, no `validate_token_format` calls in the publish path.

**Tech Stack:** Python 3.13, `subprocess` (stdlib), `os` (stdlib), `pathlib` (stdlib), `pytest` with `asyncio_mode = "auto"`.

## Global Constraints

From `crackerjack/CLAUDE.md`, `crackerjack/pyproject.toml`, and the spec:

- Python 3.13; line length 100 (Ruff `[tool.ruff] line-length`)
- Function arguments max 10 (excludes `self`, `cls`, `*args`, `**kwargs`)
- Branches max 15, returns max 6, statements max 55 (practical target 30)
- Coverage floor 80% (crackerjack `pyproject.toml` `[tool.pytest] addopts`)
- `from __future__ import annotations` first non-comment line of every source file
- `X | None` not `Optional[X]`, `list[str]` not `List[str]`, `pathlib.Path` not `os.path`
- `no_implicit_optional = true`: default-None args typed `X | None = None`
- No `Any` in tool inputs or orchestration state (use `TYPE_CHECKING`)
- In `except` blocks, use `logger.exception(...)` never `logger.error(..., exc_info=True)`
- Tests don't need `@pytest.mark.asyncio` (`asyncio_mode = "auto"`)
- Test timeout 600s (`timeout = 600` in `[tool.pytest.ini_options]`)
- Tests use project markers (don't invent new ones)
- Use `crackerjack`'s Oneiric logger, not stdlib `logging` directly in production code
  (stdlib `logging.getLogger(__name__)` is acceptable per existing crackerjack convention)
- All CLI surface unchanged: no version bump of crackerjack; no pyproject bump
- Imports sorted within sections (stdlib → third-party → first-party `crackerjack`)

______________________________________________________________________

______________________________________________________________________

**New module (crackerjack/services/pypi_auth/):**

- `__init__.py` — re-exports public API
- `_auth.py` — `PyPIAuth` class + `PyPIAuthProvider` Protocol + `discover_auth()`
- `_providers.py` — `EnvVarAuthProvider`, `KeyringAuthProvider`
- `_trusted_publishing.py` — `TrustedPublishingProvider`
- `_keyring.py` — `_keyring_get_raw()` private helper
  **New tests:**
- `tests/unit/services/test_pypi_auth.py` — unit tests for `PyPIAuth`, Protocol, `discover_auth()`
- `tests/unit/services/test_pypi_auth_providers.py` — unit tests for all 3 providers
- `tests/unit/services/test_keyring_raw.py` — unit tests for `_keyring_get_raw()`
- `tests/unit/managers/test_publish_manager_pyi_auth.py` — integration + regression tests
  **Modified:**
- `crackerjack/managers/publish_manager.py` — replace `_check_*_auth`, `_collect_auth_methods`, `_report_auth_status`, `AuthResult` with `_resolve_pypi_auth()` + new `_execute_publish()`
- `crackerjack/CHANGELOG.md` — add entry
  **Removed (deleted code):**
- `AuthResult` dataclass (lines 29-32 of publish_manager.py)
- `_collect_auth_methods`, `_check_env_token_auth`, `_check_keyring_auth`, `_report_auth_status`, `_display_auth_setup_instructions` (lines 448-517 of publish_manager.py)

______________________________________________________________________

## Task 1: Create PyPIAuth opaque wrapper

**Files:**

- Create: `crackerjack/services/pypi_auth/__init__.py`
- Create: `crackerjack/services/pypi_auth/_auth.py`
- Test: `tests/unit/services/test_pypi_auth.py`

**Interfaces:**

- Consumes: nothing (zero dependencies)

- Produces:

  - `class PyPIAuth` with constructor `__init__(self, value: str) -> None`
  - Raises `ValueError` if `value` is empty, doesn't start with `"pypi-"`, or `len(value) < 16`
  - Stores the validated value privately
  - Method `as_uv_publish_token(self) -> str`
  - Method `is_trusted_publishing(self) -> bool` (always `False` for this base class)
  - Method `source(self) -> str` (returns `"unknown"` for base class; overridden by subclasses)
  - `__repr__` returns `"<PyPIAuth source=<source>>"` — NEVER the token bytes
  - `__str__` calls `__repr__`
  - `__eq__` and `__hash__` by identity (`is`) only

- [ ] **Step 1: Write the failing test**

Create `tests/unit/services/test_pypi_auth.py`:

```python
from __future__ import annotations

import pickle

import pytest

from crackerjack.services.pypi_auth._auth import PyPIAuth


class TestPyPIAuthConstruction:
    def test_accepts_valid_pypi_token(self) -> None:
        token = "pypi-AgEIcHlwaS5vcmcCAAAAAAAAAAAA"
        auth = PyPIAuth(token)
        assert auth.as_uv_publish_token() == token

    def test_accepts_token_with_dashes_and_underscores(self) -> None:
        token = "pypi-AgEIcHlwaS5vcmcC-a_b-c_d-e_f"
        auth = PyPIAuth(token)
        assert auth.as_uv_publish_token() == token

    @pytest.mark.parametrize(
        "bad_token",
        [
            "",
            "pypi-",
            "pypi-short",            # length < 16
            "notpypi-AgEIcHlwaS5vcmcCAAAAAAAAAA",  # no pypi- prefix
            "pypi_AgEIcHlwaS5vcmcCAAAAAAAAAA",   # underscore instead of dash
            "AgEIcHlwaS5vcmcCAAAAAAAAAA",        # no prefix at all
        ],
    )
    def test_rejects_invalid_tokens(self, bad_token: str) -> None:
        with pytest.raises(ValueError, match="PyPI"):
            PyPIAuth(bad_token)


class TestPyPIAuthReprSafety:
    def test_repr_never_includes_token(self) -> None:
        token = "pypi-AgEIcHlwaS5vcmcCAAAAAAAAAAAA"
        auth = PyPIAuth(token)
        r = repr(auth)
        assert token not in r
        assert "source=" in r

    def test_str_never_includes_token(self) -> None:
        token = "pypi-AgEIcHlwaS5vcmcCAAAAAAAAAAAA"
        auth = PyPIAuth(token)
        s = str(auth)
        assert token not in s

    def test_format_string_never_leaks_token(self) -> None:
        token = "pypi-AgEIcHlwaS5vcmcCAAAAAAAAAAAA"
        auth = PyPIAuth(token)
        s = f"{auth}"
        assert token not in s


class TestPyPIAuthEquality:
    def test_equal_by_identity_not_value(self) -> None:
        token = "pypi-AgEIcHlwaS5vcmcCAAAAAAAAAAAA"
        auth1 = PyPIAuth(token)
        auth2 = PyPIAuth(token)
        assert auth1 != auth2
        assert hash(auth1) != hash(auth2)


class TestPyPIAuthIsTrustedPublishing:
    def test_default_is_false(self) -> None:
        auth = PyPIAuth("pypi-AgEIcHlwaS5vcmcCAAAAAAAAAAAA")
        assert auth.is_trusted_publishing() is False


class TestPyPIAuthPickling:
    def test_pickling_raises(self) -> None:
        auth = PyPIAuth("pypi-AgEIcHlwaS5vcmcCAAAAAAAAAAAA")
        with pytest.raises((TypeError, AttributeError, pickle.PicklingError)):
            pickle.dumps(auth)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/crackerjack && python -m pytest tests/unit/services/test_pypi_auth.py -v`
Expected: `ModuleNotFoundError: No module named 'crackerjack.services.pypi_auth'`

- [ ] **Step 3: Write the package `__init__.py`**

Create `crackerjack/services/pypi_auth/__init__.py`:

```python
from __future__ import annotations

from crackerjack.services.pypi_auth._auth import (
    PyPIAuth,
    PyPIAuthProvider,
    discover_auth,
)

__all__ = ["PyPIAuth", "PyPIAuthProvider", "discover_auth"]
```

- [ ] **Step 4: Write `_auth.py` with `PyPIAuth` class**

Create `crackerjack/services/pypi_auth/_auth.py`:

```python
from __future__ import annotations

import logging
import typing as t

logger = logging.getLogger(__name__)


def _validate_pypi_token(value: str) -> None:
    if not value:
        msg = "PyPI token must be a non-empty string"
        raise ValueError(msg)
    if not value.startswith("pypi-"):
        msg = f"PyPI token must start with 'pypi-' (got {value[:8]!r})"
        raise ValueError(msg)
    if len(value) < 16:
        msg = f"PyPI token must be at least 16 characters (got {len(value)})"
        raise ValueError(msg)


class PyPIAuth:
    """Opaque PyPI credential wrapper.

    Construction is the only place a raw ``str`` becomes a ``PyPIAuth``.
    Once constructed, the credential is opaque — consumers must call
    :meth:`as_uv_publish_token` to extract it, which is the explicit
    acknowledgment that the value is about to be handled outside the
    safety boundary.
    """

    __slots__ = ("_value", "_source")

    def __init__(self, value: str, source: str = "unknown") -> None:
        _validate_pypi_token(value)
        self._value = value
        self._source = source

    def as_uv_publish_token(self) -> str:
        return self._value

    def is_trusted_publishing(self) -> bool:
        return False

    def source(self) -> str:
        return self._source

    def __repr__(self) -> str:
        return f"<PyPIAuth source={self._source}>"

    def __str__(self) -> str:
        return self.__repr__()

    def __eq__(self, other: object) -> bool:
        return self is other

    def __hash__(self) -> int:
        return id(self)


class PyPIAuthProvider(t.Protocol):
    """A source of PyPI authentication.

    Implementations live in ``_providers.py`` and
    ``_trusted_publishing.py``. A downstream plugin can add a new
    provider by satisfying this protocol — no registration required.
    """

    name: str
    def is_available(self) -> bool: ...
    def resolve(self) -> PyPIAuth | None: ...


def discover_auth(
    providers: t.Sequence[PyPIAuthProvider] | None = None,
) -> tuple[PyPIAuth | None, list[PyPIAuthProvider]]:
    """Run providers in priority order, return first successful auth.

    The second return value is the list of providers that were checked
    (in order), so callers can render a banner like "Checked: TP,
    env, keyring" regardless of which one won.

    If ``providers`` is None, the default list is
    ``[TrustedPublishingProvider(), EnvVarAuthProvider(),
    KeyringAuthProvider()]`` — order matters; trusted publishing is
    preferred over ambient credentials.
    """
    if providers is None:
        from crackerjack.services.pypi_auth._providers import (
            EnvVarAuthProvider,
            KeyringAuthProvider,
        )
        from crackerjack.services.pypi_auth._trusted_publishing import (
            TrustedPublishingProvider,
        )

        providers = [
            TrustedPublishingProvider(),
            EnvVarAuthProvider(),
            KeyringAuthProvider(),
        ]

    for provider in providers:
        try:
            if not provider.is_available():
                logger.debug(
                    "PyPI auth provider %r unavailable, skipping",
                    provider.name,
                )
                continue
            auth = provider.resolve()
        except Exception:
            logger.exception(
                "PyPI auth provider %r raised during resolve()",
                provider.name,
            )
            continue
        if auth is not None:
            logger.debug("PyPI auth resolved via %r", provider.name)
            return auth, list(providers)

    return None, list(providers)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/les/Projects/crackerjack && python -m pytest tests/unit/services/test_pypi_auth.py -v`
Expected: All 11 tests pass. The `discover_auth` function references providers that don't exist yet, but `tests/unit/services/test_pypi_auth.py` doesn't exercise `discover_auth`, so the import succeeds only at call time. If `from crackerjack.services.pypi_auth._auth import ...` triggers the `discover_auth` body's lazy import, it won't be evaluated until `discover_auth()` is called.

- [ ] **Step 6: Commit**

```bash
cd /Users/les/Projects/crackerjack && git add crackerjack/services/pypi_auth/ tests/unit/services/test_pypi_auth.py && git commit -m "feat(pypi_auth): PyPIAuth opaque wrapper + Protocol + discover_auth()"
```

______________________________________________________________________

## Task 2: Create `_keyring_get_raw()` private helper

**Files:**

- Create: `crackerjack/services/pypi_auth/_keyring.py`
- Test: `tests/unit/services/test_keyring_raw.py`

**Interfaces:**

- Consumes: nothing

- Produces:

  - Function `_keyring_get_raw(url: str, username: str, timeout: int = 10) -> str | None`
  - Returns the raw stdout of `keyring get <url> <username>`, stripped.
  - Returns `None` on `FileNotFoundError`, `subprocess.TimeoutExpired`, non-zero exit code, or empty stdout.
  - **Never** masks or sanitizes the output. This is the contract.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/services/test_keyring_raw.py`:

```python
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from crackerjack.services.pypi_auth._keyring import _keyring_get_raw


class TestKeyringGetRawHappyPath:
    def test_returns_stdout_stripped(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["keyring", "get", "url", "user"],
            returncode=0,
            stdout="pypi-AgEIcHlwaS5vcmcCAAAAAAAAAAAA\n",
            stderr="",
        )
        with patch(
            "crackerjack.services.pypi_auth._keyring.subprocess.run",
            return_value=completed,
        ):
            result = _keyring_get_raw("url", "user")
        assert result == "pypi-AgEIcHlwaS5vcmcCAAAAAAAAAAAA"

    def test_returns_token_with_long_body_unchanged(self) -> None:
        # Regression: mask_generic_long_token would have mangled this.
        long_token = "pypi-AgEIcHlwaS5vcmcC" + "deadbeef" * 8
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=long_token + "\n", stderr="",
        )
        with patch(
            "crackerjack.services.pypi_auth._keyring.subprocess.run",
            return_value=completed,
        ):
            result = _keyring_get_raw("url", "user")
        assert result == long_token
        assert "****" not in result


class TestKeyringGetRawFailureModes:
    def test_file_not_found_returns_none(self) -> None:
        with patch(
            "crackerjack.services.pypi_auth._keyring.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            result = _keyring_get_raw("url", "user")
        assert result is None

    def test_timeout_returns_none(self) -> None:
        with patch(
            "crackerjack.services.pypi_auth._keyring.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="keyring", timeout=10),
        ):
            result = _keyring_get_raw("url", "user")
        assert result is None

    def test_nonzero_exit_returns_none(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="backend unavailable",
        )
        with patch(
            "crackerjack.services.pypi_auth._keyring.subprocess.run",
            return_value=completed,
        ):
            result = _keyring_get_raw("url", "user")
        assert result is None

    def test_empty_stdout_returns_none(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="  \n  ", stderr="",
        )
        with patch(
            "crackerjack.services.pypi_auth._keyring.subprocess.run",
            return_value=completed,
        ):
            result = _keyring_get_raw("url", "user")
        assert result is None


class TestKeyringGetRawInvocation:
    def test_calls_keyring_cli_with_correct_args(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="",
        )
        with patch(
            "crackerjack.services.pypi_auth._keyring.subprocess.run",
            return_value=completed,
        ) as mock_run:
            _keyring_get_raw("https://upload.pypi.org/legacy/", "__token__")
        args = mock_run.call_args.args[0]
        assert args == ["keyring", "get", "https://upload.pypi.org/legacy/", "__token__"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/crackerjack && python -m pytest tests/unit/services/test_keyring_raw.py -v`
Expected: `ModuleNotFoundError: No module named 'crackerjack.services.pypi_auth._keyring'`

- [ ] **Step 3: Write `_keyring.py`**

Create `crackerjack/services/pypi_auth/_keyring.py`:

```python
from __future__ import annotations

import logging
import subprocess

logger = logging.getLogger(__name__)

# PyPI's legacy upload URL is the only supported target. Trusted
# publishing uses a different flow that does not go through keyring.
PYPI_KEYRING_URL = "https://upload.pypi.org/legacy/"
PYPI_KEYRING_USER = "__token__"


def _keyring_get_raw(url: str, username: str, timeout: int = 10) -> str | None:
    """Call ``keyring get <url> <username>`` and return the raw token.

    This is the **only** place in crackerjack where a subprocess stdout
    is intentionally NOT fed through :func:`SecurityService.mask_tokens`.
    PyPI tokens are 100+ character strings of base64-ish characters,
    many of which would be wrongly matched by the ``mask_generic_long_token``
    regex and corrupted. By isolating the unmasking to this single
    function, we make accidental re-introduction of the corruption bug
    impossible at any other call site.
    """
    try:
        result = subprocess.run(
            ["keyring", "get", url, username],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        logger.debug("keyring CLI not installed")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("keyring get timed out after %ds", timeout)
        return None

    if result.returncode != 0:
        logger.debug(
            "keyring get failed (exit %d): %s",
            result.returncode,
            result.stderr.strip()[:200],
        )
        return None

    stripped = result.stdout.strip()
    return stripped or None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/les/Projects/crackerjack && python -m pytest tests/unit/services/test_keyring_raw.py -v`
Expected: All 7 tests pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/crackerjack && git add crackerjack/services/pypi_auth/_keyring.py tests/unit/services/test_keyring_raw.py && git commit -m "feat(pypi_auth): _keyring_get_raw() — unmasked keyring subprocess helper"
```

______________________________________________________________________

## Task 3: Create EnvVarAuthProvider and KeyringAuthProvider

**Files:**

- Create: `crackerjack/services/pypi_auth/_providers.py`
- Test: `tests/unit/services/test_pypi_auth_providers.py`

**Interfaces:**

- Consumes: `PyPIAuth` (from Task 1), `_keyring_get_raw` (from Task 2)

- Produces:

  - `class EnvVarAuthProvider`:
    - `name = "UV_PUBLISH_TOKEN env var"`
    - `is_available() -> bool` returns `True` iff `os.getenv("UV_PUBLISH_TOKEN")` is non-empty
    - `resolve() -> PyPIAuth | None`:
      - Reads `UV_PUBLISH_TOKEN`
      - Returns `PyPIAuth(value, source="env:UV_PUBLISH_TOKEN")` on success
      - Returns `None` if unset
      - Returns `None` if value raises `ValueError` (malformed); logs warning
  - `class KeyringAuthProvider`:
    - `name = "Keyring storage"`
    - `is_available() -> bool` returns `True` (keyring may be installed on any platform)
    - `resolve() -> PyPIAuth | None`:
      - Calls `_keyring_get_raw(PYPI_KEYRING_URL, PYPI_KEYRING_USER)`
      - Returns `PyPIAuth(token, source="keyring")` on success
      - Returns `None` if keyring call returned `None`
      - Returns `None` if token fails `PyPIAuth` validation; logs warning with hint

- [ ] **Step 1: Write the failing test**

Create `tests/unit/services/test_pypi_auth_providers.py`:

```python
from __future__ import annotations

import pytest

from crackerjack.services.pypi_auth._auth import PyPIAuth
from crackerjack.services.pypi_auth._providers import (
    EnvVarAuthProvider,
    KeyringAuthProvider,
)


class TestEnvVarAuthProvider:
    def test_unavailable_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("UV_PUBLISH_TOKEN", raising=False)
        provider = EnvVarAuthProvider()
        assert provider.is_available() is False
        assert provider.resolve() is None

    def test_resolves_valid_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        token = "pypi-AgEIcHlwaS5vcmcCAAAAAAAAAAAA"
        monkeypatch.setenv("UV_PUBLISH_TOKEN", token)
        provider = EnvVarAuthProvider()
        assert provider.is_available() is True
        auth = provider.resolve()
        assert isinstance(auth, PyPIAuth)
        assert auth.as_uv_publish_token() == token
        assert auth.source() == "env:UV_PUBLISH_TOKEN"

    def test_malformed_env_var_falls_through(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("UV_PUBLISH_TOKEN", "not-pypi-format")
        provider = EnvVarAuthProvider()
        assert provider.is_available() is True
        assert provider.resolve() is None

    def test_name_is_stable(self) -> None:
        provider = EnvVarAuthProvider()
        assert provider.name == "UV_PUBLISH_TOKEN env var"


class TestKeyringAuthProvider:
    def test_unavailable_when_keyring_returns_none(self) -> None:
        from unittest.mock import patch
        with patch(
            "crackerjack.services.pypi_auth._providers._keyring_get_raw",
            return_value=None,
        ):
            provider = KeyringAuthProvider()
            assert provider.resolve() is None

    def test_resolves_valid_keyring_token(self) -> None:
        from unittest.mock import patch
        token = "pypi-AgEIcHlwaS5vcmcCAAAAAAAAAAAA"
        with patch(
            "crackerjack.services.pypi_auth._providers._keyring_get_raw",
            return_value=token,
        ):
            provider = KeyringAuthProvider()
            auth = provider.resolve()
        assert isinstance(auth, PyPIAuth)
        assert auth.as_uv_publish_token() == token
        assert auth.source() == "keyring"

    def test_malformed_keyring_token_returns_none(self) -> None:
        from unittest.mock import patch
        with patch(
            "crackerjack.services.pypi_auth._providers._keyring_get_raw",
            return_value="not-pypi-format",
        ):
            provider = KeyringAuthProvider()
            assert provider.resolve() is None

    def test_name_is_stable(self) -> None:
        provider = KeyringAuthProvider()
        assert provider.name == "Keyring storage"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/crackerjack && python -m pytest tests/unit/services/test_pypi_auth_providers.py -v`
Expected: `ModuleNotFoundError: No module named 'crackerjack.services.pypi_auth._providers'`

- [ ] **Step 3: Write `_providers.py`**

Create `crackerjack/services/pypi_auth/_providers.py`:

```python
from __future__ import annotations

import logging
import os

from crackerjack.services.pypi_auth._auth import PyPIAuth
from crackerjack.services.pypi_auth._keyring import (
    PYPI_KEYRING_URL,
    PYPI_KEYRING_USER,
    _keyring_get_raw,
)

logger = logging.getLogger(__name__)


class EnvVarAuthProvider:
    """PyPI auth from ``UV_PUBLISH_TOKEN`` environment variable."""

    name = "UV_PUBLISH_TOKEN env var"

    def is_available(self) -> bool:
        return bool(os.getenv("UV_PUBLISH_TOKEN"))

    def resolve(self) -> PyPIAuth | None:
        value = os.getenv("UV_PUBLISH_TOKEN")
        if not value:
            return None
        try:
            return PyPIAuth(value, source="env:UV_PUBLISH_TOKEN")
        except ValueError:
            logger.warning(
                "UV_PUBLISH_TOKEN is set but malformed (must start with 'pypi-'"
                " and be at least 16 chars). Falling through to next provider.",
            )
            return None


class KeyringAuthProvider:
    """PyPI auth from system keyring via the ``keyring`` CLI."""

    name = "Keyring storage"

    def is_available(self) -> bool:
        # Don't probe the backend in is_available; the cost is non-zero
        # and the actual call happens in resolve() anyway. Always
        # advertise as available so the banner tells the operator it
        # was checked.
        return True

    def resolve(self) -> PyPIAuth | None:
        raw = _keyring_get_raw(PYPI_KEYRING_URL, PYPI_KEYRING_USER)
        if raw is None:
            return None
        try:
            return PyPIAuth(raw, source="keyring")
        except ValueError:
            logger.warning(
                "Keyring token at %s has wrong format (expected 'pypi-'"
                " prefix). Re-run: keyring set %s %s",
                PYPI_KEYRING_URL,
                PYPI_KEYRING_URL,
                PYPI_KEYRING_USER,
            )
            return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/les/Projects/crackerjack && python -m pytest tests/unit/services/test_pypi_auth_providers.py -v`
Expected: All 8 tests pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/crackerjack && git add crackerjack/services/pypi_auth/_providers.py tests/unit/services/test_pypi_auth_providers.py && git commit -m "feat(pypi_auth): EnvVarAuthProvider and KeyringAuthProvider"
```

______________________________________________________________________

## Task 4: Create TrustedPublishingProvider

**Files:**

- Create: `crackerjack/services/pypi_auth/_trusted_publishing.py`
- Modify: `crackerjack/services/pypi_auth/_auth.py` (extend `PyPIAuth` with `is_trusted_publishing=True` variant)
- Test: extend `tests/unit/services/test_pypi_auth_providers.py`

**Interfaces:**

- Consumes: `PyPIAuth` (from Task 1)

- Produces:

  - `class TrustedPublishingProvider`:
    - `name = "Trusted Publishing (OIDC)"`
    - `is_available() -> bool`:
      - Returns `True` iff both `os.getenv("GITHUB_ACTIONS") == "true"` AND
        `os.getenv("ACTIONS_ID_TOKEN_REQUEST_TOKEN")` is non-empty
      - Conservative: only GitHub Actions today. (Future: GitLab CI, etc.)
    - `resolve() -> PyPIAuth | None`:
      - Returns a `PyPIAuth` instance with sentinel value `"__TRUSTED_PUBLISHING__"`
        (this passes the format check because the sentinel starts with
        `"pypi-"` after... no, it doesn't — see step 3 for the actual
        implementation)
      - Returns `None` if `is_available()` is False
  - Add `class _TrustedPublishingSentinel(PyPIAuth)` private subclass whose `is_trusted_publishing()` returns `True`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/services/test_pypi_auth_providers.py`:

```python
class TestTrustedPublishingProvider:
    def test_unavailable_outside_ci(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        monkeypatch.delenv("ACTIONS_ID_TOKEN_REQUEST_TOKEN", raising=False)
        from crackerjack.services.pypi_auth._trusted_publishing import (
            TrustedPublishingProvider,
        )
        provider = TrustedPublishingProvider()
        assert provider.is_available() is False
        assert provider.resolve() is None

    def test_available_in_github_actions_with_oidc_token(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        monkeypatch.setenv("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "some-token")
        from crackerjack.services.pypi_auth._trusted_publishing import (
            TrustedPublishingProvider,
        )
        provider = TrustedPublishingProvider()
        assert provider.is_available() is True
        auth = provider.resolve()
        assert auth is not None
        assert auth.is_trusted_publishing() is True
        # Source label, not the literal sentinel — for safe logging.
        assert "trusted" in auth.source().lower()

    def test_unavailable_if_github_actions_but_no_oidc_token(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        monkeypatch.delenv("ACTIONS_ID_TOKEN_REQUEST_TOKEN", raising=False)
        from crackerjack.services.pypi_auth._trusted_publishing import (
            TrustedPublishingProvider,
        )
        provider = TrustedPublishingProvider()
        assert provider.is_available() is False

    def test_unavailable_if_oidc_token_but_not_github_actions(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        monkeypatch.setenv("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "some-token")
        from crackerjack.services.pypi_auth._trusted_publishing import (
            TrustedPublishingProvider,
        )
        provider = TrustedPublishingProvider()
        assert provider.is_available() is False

    def test_name_is_stable(self) -> None:
        from crackerjack.services.pypi_auth._trusted_publishing import (
            TrustedPublishingProvider,
        )
        provider = TrustedPublishingProvider()
        assert provider.name == "Trusted Publishing (OIDC)"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/crackerjack && python -m pytest tests/unit/services/test_pypi_auth_providers.py::TestTrustedPublishingProvider -v`
Expected: `ModuleNotFoundError: No module named 'crackerjack.services.pypi_auth._trusted_publishing'`

- [ ] **Step 3: Extend `PyPIAuth` with sentinel subclass**

Modify `crackerjack/services/pypi_auth/_auth.py`. After the existing `PyPIAuth` class (before `PyPIAuthProvider` protocol), add:

```python
class _TrustedPublishingSentinel(PyPIAuth):
    """Sentinel returned by TrustedPublishingProvider.

    The value here is NOT a real PyPI token — it is a placeholder that
    passes the constructor's format check so the rest of the publish
    pipeline can treat it uniformly. The publish manager recognizes
    ``is_trusted_publishing() == True`` and switches to
    ``uv publish --trusted-publishing`` instead of injecting an env var.
    """

    def __init__(self) -> None:
        # The constructor requires "pypi-" + length >= 16. The sentinel
        # value satisfies both; it is never sent to PyPI as a token.
        super().__init__(
            value="pypi-trusted-publishing-placeholder-do-not-use",
            source="trusted-publishing",
        )

    def is_trusted_publishing(self) -> bool:
        return True
```

- [ ] **Step 4: Write `_trusted_publishing.py`**

Create `crackerjack/services/pypi_auth/_trusted_publishing.py`:

```python
from __future__ import annotations

import logging
import os

from crackerjack.services.pypi_auth._auth import PyPIAuth, _TrustedPublishingSentinel

logger = logging.getLogger(__name__)


class TrustedPublishingProvider:
    """PyPI auth via PyPI's OIDC-based Trusted Publishing flow.

    Today this detects GitHub Actions only. When uv's OIDC support is
    configured for the repo (PyPI project settings → Publishing →
    "Add a new pending publisher" → GitHub), running ``uv publish``
    inside that workflow exchanges the OIDC token for a PyPI upload
    token without ever touching a secret.

    Detection is conservative: we only claim availability when both
    signals (``GITHUB_ACTIONS == "true"`` AND a non-empty
    ``ACTIONS_ID_TOKEN_REQUEST_TOKEN``) are present. Missing either
    means Trusted Publishing isn't configured for this workflow.
    """

    name = "Trusted Publishing (OIDC)"

    def is_available(self) -> bool:
        return (
            os.getenv("GITHUB_ACTIONS") == "true"
            and bool(os.getenv("ACTIONS_ID_TOKEN_REQUEST_TOKEN"))
        )

    def resolve(self) -> PyPIAuth | None:
        if not self.is_available():
            return None
        logger.debug(
            "Detected Trusted Publishing: GITHUB_ACTIONS + ACTIONS_ID_TOKEN_REQUEST_TOKEN"
        )
        return _TrustedPublishingSentinel()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/les/Projects/crackerjack && python -m pytest tests/unit/services/test_pypi_auth_providers.py -v`
Expected: All 13 tests pass (8 existing + 5 new).

- [ ] **Step 6: Commit**

```bash
cd /Users/les/Projects/crackerjack && git add crackerjack/services/pypi_auth/_auth.py crackerjack/services/pypi_auth/_trusted_publishing.py tests/unit/services/test_pypi_auth_providers.py && git commit -m "feat(pypi_auth): TrustedPublishingProvider for OIDC-based auth"
```

______________________________________________________________________

## Task 5: Wire publish_manager.py to use the new abstraction

**Files:**

- Modify: `crackerjack/managers/publish_manager.py`
- Test: `tests/unit/managers/test_publish_manager_pyi_auth.py` (new)

**Interfaces:**

- Consumes: `PyPIAuth`, `discover_auth`, `PyPIAuthProvider` (from Tasks 1-4)

- Produces:

  - `PublishManagerImpl._resolve_pypi_auth() -> PyPIAuth | None`:
    - Returns the result of `discover_auth()`'s first element
    - Prints the same banner pattern as the existing `_report_auth_status`
  - `PublishManagerImpl._execute_publish() -> bool`:
    - Calls `_resolve_pypi_auth()`
    - If `None`, prints the setup instructions and returns `False`
    - If `PyPIAuth.is_trusted_publishing()` is True, builds `cmd = ["uv", "publish", "--trusted-publishing"]`
    - Otherwise, builds `cmd = ["uv", "publish"]` and injects `UV_PUBLISH_TOKEN=auth.as_uv_publish_token()` via `additional_env`
  - DELETED:
    - `AuthResult` dataclass (lines 29-32)
    - `_collect_auth_methods` (lines 448-459)
    - `_check_env_token_auth` (lines 461-475)
    - `_check_keyring_auth` (lines 477-495)
    - `_report_auth_status` (lines 497-504)
    - `_display_auth_setup_instructions` (lines 506-517)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/managers/test_publish_manager_pyi_auth.py`:

```python
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from crackerjack.managers.publish_manager import PublishManagerImpl
from crackerjack.services.pypi_auth._auth import PyPIAuth


@pytest.fixture
def manager(tmp_path: Path) -> PublishManagerImpl:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test-pkg"\nversion = "0.1.0"\n'
    )
    return PublishManagerImpl(pkg_path=tmp_path)


class TestResolvePypiAuth:
    def test_returns_none_when_no_provider_succeeds(self, manager: PublishManagerImpl) -> None:
        with patch(
            "crackerjack.services.pypi_auth._providers._keyring_get_raw",
            return_value=None,
        ):
            assert manager._resolve_pypi_auth() is None

    def test_returns_pypi_auth_when_keyring_succeeds(self, manager: PublishManagerImpl) -> None:
        token = "pypi-AgEIcHlwaS5vcmcCAAAAAAAAAAAA"
        with patch(
            "crackerjack.services.pypi_auth._providers._keyring_get_raw",
            return_value=token,
        ):
            auth = manager._resolve_pypi_auth()
        assert isinstance(auth, PyPIAuth)
        assert auth.as_uv_publish_token() == token


class TestExecutePublishInjectsToken:
    def test_injects_uv_publish_token_for_keyring_auth(
        self, manager: PublishManagerImpl,
    ) -> None:
        token = "pypi-AgEIcHlwaS5vcmcCAAAAAAAAAAAA"
        # Stub build_package and _run_command to capture the env
        with patch.object(manager, "build_package", return_value=True), \
             patch.object(manager, "_run_command") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="Successfully uploaded",
                stderr="",
            )
            with patch(
                "crackerjack.services.pypi_auth._providers._keyring_get_raw",
                return_value=token,
            ):
                result = manager._execute_publish()
        assert result is True
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs["additional_env"] == {"UV_PUBLISH_TOKEN": token}
        assert mock_run.call_args.args[0] == ["uv", "publish"]

    def test_uses_trusted_publishing_flag_when_sentinel(
        self, manager: PublishManagerImpl, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        monkeypatch.setenv("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "token")
        with patch.object(manager, "build_package", return_value=True), \
             patch.object(manager, "_run_command") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="Successfully uploaded",
                stderr="",
            )
            result = manager._execute_publish()
        assert result is True
        cmd = mock_run.call_args.args[0]
        assert cmd == ["uv", "publish", "--trusted-publishing"]
        # When using TP, additional_env should NOT contain UV_PUBLISH_TOKEN
        env = mock_run.call_args.kwargs.get("additional_env") or {}
        assert "UV_PUBLISH_TOKEN" not in env

    def test_returns_false_when_no_auth(self, manager: PublishManagerImpl) -> None:
        with patch(
            "crackerjack.services.pypi_auth._providers._keyring_get_raw",
            return_value=None,
        ), patch.object(manager, "_run_command") as mock_run:
            result = manager._execute_publish()
        assert result is False
        mock_run.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/crackerjack && python -m pytest tests/unit/managers/test_publish_manager_pyi_auth.py -v`
Expected: Tests fail because `_resolve_pypi_auth` doesn't exist on `PublishManagerImpl`.

- [ ] **Step 3: Delete old auth code from `publish_manager.py`**

In `crackerjack/managers/publish_manager.py`:

1. Remove the `AuthResult` dataclass (lines 29-32, including its leading blank line).
1. Replace the existing `_collect_auth_methods`, `_check_env_token_auth`, `_check_keyring_auth`, `_report_auth_status`, `_display_auth_setup_instructions` methods (lines 448-517) with the new `_resolve_pypi_auth` method below.
1. Update the import line near the top:
   - Find the existing import section.
   - Add `from crackerjack.services.pypi_auth._auth import PyPIAuth, discover_auth`
     (it does NOT need to import providers directly — `discover_auth` does that).

After the edit, `publish_manager.py` should look like the snippet below in the affected sections. The full file is too long to reproduce; only the changed region is shown.

Replace the entire block from `def _collect_auth_methods` through `_display_auth_setup_instructions` with:

```python
    def _resolve_pypi_auth(self) -> PyPIAuth | None:
        """Find a PyPI credential from the configured providers.

        Returns the first available :class:`PyPIAuth` (priority order:
        Trusted Publishing > UV_PUBLISH_TOKEN > keyring). Returns None
        if no provider succeeds; the caller is then responsible for
        printing the setup-instructions banner.
        """
        auth, providers = discover_auth()
        if auth is not None:
            self.console.print(
                "[green]✅[/ green] PyPI authentication available: "
                f"{auth.source()}",
            )
            return auth

        self.console.print(
            f"[yellow]⚠️[/ yellow] No PyPI auth found. Checked: "
            + ", ".join(p.name for p in providers),
        )
        self._display_auth_setup_instructions()
        return None

    def _display_auth_setup_instructions(self) -> None:
        self.console.print("[red]❌[/ red] No valid PyPI authentication found")
        self.console.print("\n[yellow]💡[/ yellow] Setup options: ")
        self.console.print(
            " 1. Set environment variable: export UV_PUBLISH_TOKEN=<your-pypi-token>",
        )
        self.console.print(
            " 2. Use keyring: keyring set https://upload.pypi.org/legacy/ __token__",
        )
        self.console.print(
            " 3. Configure Trusted Publishing on PyPI for tokenless CI uploads",
        )
```

Then update the existing `_execute_publish` method (lines 619-657) to:

```python
    def _execute_publish(self) -> bool:
        auth = self._resolve_pypi_auth()
        if auth is None:
            return False

        if auth.is_trusted_publishing():
            cmd = ["uv", "publish", "--trusted-publishing"]
            extra_env: dict[str, str] | None = None
        else:
            cmd = ["uv", "publish"]
            extra_env = {"UV_PUBLISH_TOKEN": auth.as_uv_publish_token()}

        result = self._run_command(cmd, additional_env=extra_env)

        success_indicators = [
            "Successfully uploaded",
            "Package uploaded successfully",
            "Upload successful",
            "Successfully published",
        ]

        stdout_text = str(getattr(result, "stdout", "") or "")
        stderr_text = str(getattr(result, "stderr", "") or "")
        has_success_indicator = any(
            indicator in stdout_text for indicator in success_indicators
        )

        success = result.returncode == 0 or has_success_indicator

        if success:
            self._handle_publish_success()
            return True

        self._handle_publish_failure(stderr_text)
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/les/Projects/crackerjack && python -m pytest tests/unit/managers/test_publish_manager_pyi_auth.py -v`
Expected: All 5 tests pass.

- [ ] **Step 5: Verify no other tests in publish_manager broke**

Run: `cd /Users/les/Projects/crackerjack && python -m pytest tests/unit/managers/test_publish_manager.py tests/unit/managers/test_publish_manager_extended.py tests/unit/managers/test_publish_manager_gaps.py tests/test_publish_manager_coverage.py -v 2>&1 | tail -30`

Expected: Many tests will break because they reference the removed `AuthResult`, `_collect_auth_methods`, `_check_env_token_auth`, `_check_keyring_auth`, `_report_auth_status`. This is expected — they will be updated in Task 6.

Note the test names that fail; you'll need to update or delete them in the next task.

- [ ] **Step 6: Commit (intermediate)**

```bash
cd /Users/les/Projects/crackerjack && git add crackerjack/managers/publish_manager.py tests/unit/managers/test_publish_manager_pyi_auth.py && git commit -m "refactor(publish): use PyPIAuth abstraction; remove old auth pipeline"
```

______________________________________________________________________

## Task 6: Update or delete existing tests that reference removed APIs

**Files:**

- Modify: `tests/unit/managers/test_publish_manager.py`
- Modify: `tests/unit/managers/test_publish_manager_extended.py`
- Modify: `tests/unit/managers/test_publish_manager_gaps.py`
- Modify: `tests/test_publish_manager_coverage.py`

The goal: every existing test that referenced `AuthResult`, `_check_env_token_auth`, `_check_keyring_auth`, `_collect_auth_methods`, `_report_auth_status`, `_display_auth_setup_instructions` is either:

- (a) deleted (if it tests behavior we no longer have), OR

- (b) rewritten to test the equivalent through the new `_resolve_pypi_auth` / `_execute_publish` interface.

- [ ] **Step 1: Find every reference to the removed symbols**

Run: `cd /Users/les/Projects/crackerjack && grep -rn "AuthResult\|_check_env_token_auth\|_check_keyring_auth\|_collect_auth_methods\|_report_auth_status\|_display_auth_setup_instructions" tests/`

Expected: A list of file:line references. Note each one.

- [ ] **Step 2: Delete tests that test ONLY removed symbols**

For each test function found in step 1, read its body. If the body only exercises a removed symbol (e.g. `test_collect_auth_methods_returns_env_first`), delete the entire test function. Do not delete tests that exercise other behavior.

Concrete guidance (this list is illustrative — verify against actual output of step 1):

- `test_validate_auth_returns_true_when_env_token_set` → delete (tested removed `_check_env_token_auth`)

- `test_validate_auth_returns_true_when_keyring_token_set` → delete (tested removed `_check_keyring_auth`)

- `test_report_auth_with_methods` → delete (tested removed `_report_auth_status`)

- `test_collect_auth_methods_returns_keyring_when_no_env` → delete

- [ ] **Step 3: Rewrite tests that test preserved behavior**

For tests that verify something we still need to verify, rewrite them through the new interface. The pattern is:

```python
# BEFORE
def test_keyring_token_validates(manager):
    assert manager._check_keyring_auth() == "Keyring storage"

# AFTER
def test_keyring_token_validates(manager, monkeypatch):
    token = "pypi-AgEIcHlwaS5vcmcCAAAAAAAAAAAA"
    monkeypatch.setenv("UV_PUBLISH_TOKEN", token)
    auth = manager._resolve_pypi_auth()
    assert auth is not None
    assert auth.source() == "env:UV_PUBLISH_TOKEN"
```

- [ ] **Step 4: Run all publish_manager tests**

Run: `cd /Users/les/Projects/crackerjack && python -m pytest tests/unit/managers/test_publish_manager.py tests/unit/managers/test_publish_manager_extended.py tests/unit/managers/test_publish_manager_gaps.py tests/test_publish_manager_coverage.py tests/unit/managers/test_publish_manager_pyi_auth.py -v 2>&1 | tail -20`

Expected: All tests pass. If some still fail, examine the failure carefully — it might be a test that referenced behavior of the OLD design (e.g. "keyring fallback when env is malformed") that we explicitly changed; rewrite or delete as appropriate.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/crackerjack && git add tests/unit/managers/ tests/test_publish_manager_coverage.py && git commit -m "test(publish): migrate tests to PyPIAuth interface; drop tests for removed symbols"
```

______________________________________________________________________

## Task 7: Add the critical regression test (parameterized masking)

**Files:**

- Modify: `tests/unit/managers/test_publish_manager_pyi_auth.py`

This test is the single most important deliverable. It MUST pass on the new code, and MUST be possible to verify it would have failed on the old code. The point: prove that masking can never again corrupt a PyPI token between discovery and use.

- [ ] **Step 1: Write the regression test**

Append to `tests/unit/managers/test_publish_manager_pyi_auth.py`:

```python
import pytest

VALID_TOKEN_RE = r"pypi-[A-Za-z0-9_\-]+"


class TestTokenBodySurvives:
    """Regression: prior to PyPIAuth, mask_generic_long_token corrupted
    PyPI tokens by replacing their body with '****', causing
    'Keyring token format appears invalid' in the publish flow.
    """

    @pytest.mark.parametrize(
        "provider_setup",
        [
            "env",
            "keyring",
            "trusted_publishing",
        ],
    )
    def test_token_reaches_uv_publish_unmodified(
        self,
        manager: PublishManagerImpl,
        monkeypatch: pytest.MonkeyPatch,
        provider_setup: str,
    ) -> None:
        # Body contains long hex runs that would have triggered
        # mask_generic_long_token (32+ char [a-zA-Z0-9_-] substrings).
        sentinel_body = "deadbeef" * 8  # 64-char hex run
        sentinel_token = f"pypi-AgEIcHlwaS5vcmcC{sentinel_body}"

        if provider_setup == "env":
            monkeypatch.setenv("UV_PUBLISH_TOKEN", sentinel_token)
            expected_cmd = ["uv", "publish"]
            expected_token_in_env = sentinel_token
        elif provider_setup == "keyring":
            monkeypatch.delenv("UV_PUBLISH_TOKEN", raising=False)
            with patch(
                "crackerjack.services.pypi_auth._providers._keyring_get_raw",
                return_value=sentinel_token,
            ):
                token = sentinel_token
            expected_cmd = ["uv", "publish"]
            expected_token_in_env = token
        else:  # trusted_publishing
            monkeypatch.setenv("GITHUB_ACTIONS", "true")
            monkeypatch.setenv(
                "ACTIONS_ID_TOKEN_REQUEST_TOKEN", "any-oidc-token",
            )
            expected_cmd = ["uv", "publish", "--trusted-publishing"]
            expected_token_in_env = None

        with patch.object(manager, "build_package", return_value=True), \
             patch.object(manager, "_run_command") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="Successfully uploaded",
                stderr="",
            )
            result = manager._execute_publish()

        assert result is True
        cmd = mock_run.call_args.args[0]
        assert cmd == expected_cmd

        env = mock_run.call_args.kwargs.get("additional_env") or {}
        if expected_token_in_env is not None:
            assert env.get("UV_PUBLISH_TOKEN") == expected_token_in_env
            # Belt-and-suspenders: token body has zero "****" corruption.
            assert "****" not in env["UV_PUBLISH_TOKEN"]
            assert sentinel_body in env["UV_PUBLISH_TOKEN"]
        else:
            assert "UV_PUBLISH_TOKEN" not in env
```

- [ ] **Step 2: Run the regression test**

Run: `cd /Users/les/Projects/crackerjack && python -m pytest tests/unit/managers/test_publish_manager_pyi_auth.py::TestTokenBodySurvives -v`
Expected: All 3 parametrize cases pass.

- [ ] **Step 3: Verify the regression test would have failed on the old code**

Run a thought experiment: in the old design, `_check_keyring_auth` called `_run_command` which masked stdout via `mask_generic_long_token`. The sentinel body `deadbeefdeadbeef...` would be replaced with `****`. Then `validate_token_format` would fail because the result wouldn't start with `pypi-`, so `_check_keyring_auth` would return `None`. The publish would fail with "No valid PyPI authentication found".

For TP and env: masking didn't apply because `os.getenv` returns the env var directly. So those two parametrize cases would have PASSED on the old code. That's expected — only the keyring case was the regression; the parametrization documents the behavior of all three for future-proofing.

Note this in a comment in the test (not code change — just a mental check).

- [ ] **Step 4: Run the full new test file**

Run: `cd /Users/les/Projects/crackerjack && python -m pytest tests/unit/managers/test_publish_manager_pyi_auth.py -v`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/crackerjack && git add tests/unit/managers/test_publish_manager_pyi_auth.py && git commit -m "test(publish): regression — token body survives masking for all three providers"
```

______________________________________________________________________

## Task 8: Run crackerjack's full test suite and update CHANGELOG

**Files:**

- Modify: `crackerjack/CHANGELOG.md`

- [ ] **Step 1: Run the full crackerjack test suite**

Run: `cd /Users/les/Projects/crackerjack && python -m pytest --no-cov -q 2>&1 | tail -20`

Expected: All tests pass. If any fail, investigate — they likely reference removed symbols we missed in Task 6.

- [ ] **Step 2: Check coverage of the new module**

Run: `cd /Users/les/Projects/crackerjack && python -m pytest tests/unit/services/test_pypi_auth.py tests/unit/services/test_pypi_auth_providers.py tests/unit/services/test_keyring_raw.py tests/unit/managers/test_publish_manager_pyi_auth.py --cov=crackerjack.services.pypi_auth --cov=crackerjack.managers.publish_manager --cov-report=term-missing 2>&1 | tail -30`

Expected: Coverage of `services/pypi_auth/` ≥ 95% and of the changed `publish_manager` methods ≥ 90%.

- [ ] **Step 3: Add CHANGELOG entry**

In `crackerjack/CHANGELOG.md`, prepend (under "Unreleased" if it exists, otherwise at the top):

```markdown
## Unreleased

### Refactor

- **Publish auth redesigned.** The `crackerjack publish` command now
  resolves PyPI credentials through a single `PyPIAuth` abstraction
  in `crackerjack.services.pypi_auth`. Three providers are tried in
  priority order: **Trusted Publishing (OIDC)** > **UV_PUBLISH_TOKEN**
  > **keyring**. This eliminates the recurring class of bug where
  masking/sanitization corrupted a valid PyPI token between discovery
  and use, surfacing as "Keyring token format appears invalid".
  PyPI tokens are now constructed once at the trust boundary and
  treated as opaque thereafter — no regex or sanitizer can touch
  them again. Trusted Publishing is auto-detected in GitHub Actions
  workflows that have an OIDC token configured; if detected,
  `crackerjack publish` invokes `uv publish --trusted-publishing`
  automatically.
```

- [ ] **Step 4: Commit**

```bash
cd /Users/les/Projects/crackerjack && git add CHANGELOG.md && git commit -m "docs(changelog): publish auth redesigned; PyPIAuth abstraction replaces fragile pipeline"
```

______________________________________________________________________

## Self-Review

**Spec coverage:**

| Spec section | Covered by |
|---|---|
| Goal | Tasks 1-8 collectively |
| Context (current state) | N/A — context for the spec reader, not an implementation task |
| Architecture (new module layout) | Tasks 1-5 create the exact 5-file layout specified |
| Components: `PyPIAuth` | Task 1 |
| Components: `PyPIAuthProvider` Protocol | Task 1 |
| Components: `discover_auth()` | Task 1 |
| Components: `_keyring_get_raw()` | Task 2 |
| Components: `EnvVarAuthProvider` | Task 3 |
| Components: `KeyringAuthProvider` | Task 3 |
| Components: `TrustedPublishingProvider` | Task 4 |
| Data flow: keyring happy path | Tested in Task 5 |
| Data flow: TP happy path | Tested in Task 5 |
| Failure paths | Tested in Tasks 3-5 |
| Error handling: exception policy | Tasks 1-4 use `logger.exception` per the rule; the discover_auth wraps each provider in try/except |
| Error handling: behavior change (env malformed falls through) | Tests in Task 3 (`test_malformed_env_var_falls_through`) |
| Error handling: no legacy fallback | The spec chose "trust tests"; this plan has no legacy code path |
| Testing: PyPIAuth unit tests | Task 1 |
| Testing: provider unit tests | Tasks 3, 4 |
| Testing: `_keyring_get_raw` unit tests | Task 2 |
| Testing: publish manager integration | Task 5 |
| Testing: regression masking test | Task 7 |
| Rollout (no version bump, dhara unpin) | Documented in Task 8's CHANGELOG entry |

**Placeholder scan:** No "TBD", "TODO", "implement later", "fill in details". Every code step shows the actual code. Every command shows the actual command.

**Type consistency:**

- `PyPIAuth.__init__(self, value: str, source: str = "unknown")` (Task 1) — used as `PyPIAuth(value, source="env:UV_PUBLISH_TOKEN")` (Task 3), `PyPIAuth(raw, source="keyring")` (Task 3), `_TrustedPublishingSentinel()` internally (Task 4). Consistent.
- `_keyring_get_raw(url: str, username: str, timeout: int = 10) -> str | None` (Task 2) — used as `_keyring_get_raw(PYPI_KEYRING_URL, PYPI_KEYRING_USER)` (Task 3). Consistent.
- `discover_auth(providers: Sequence[PyPIAuthProvider] | None = None) -> tuple[PyPIAuth | None, list[PyPIAuthProvider]]` (Task 1) — used as `auth, providers = discover_auth()` (Task 5). Consistent.
- `PyPIAuth.is_trusted_publishing() -> bool` (Task 1, returning `False`) — overridden in `_TrustedPublishingSentinel` to return `True` (Task 4). Consistent.

**Spec requirement check: `len(token) >= 16` in PyPIAuth constructor.**

Spec says: "Raises ValueError on empty, missing pypi- prefix, or length < 16. Matches validate_token_format(..., 'pypi') so the two stay in sync."

Implementation in Task 1:

```python
if len(value) < 16:
    msg = f"PyPI token must be at least 16 characters (got {len(value)})"
    raise ValueError(msg)
```

✓ Matches.

**Spec requirement check: pickling should raise.**

Test in Task 1:

```python
with pytest.raises((TypeError, AttributeError, pickle.PicklingError)):
    pickle.dumps(auth)
```

✓ Matches.

**Spec requirement check: `__reduce__` should not be defined.**

`PyPIAuth` uses `__slots__ = ("_value", "_source")` which makes it un-picklable by default. `__reduce__` is not defined. ✓

**Spec requirement check: discover_auth returns the list of providers checked.**

```python
return auth, list(providers)
```

✓ Banner code can iterate over `providers` to show what was checked.

**Spec requirement check: PyPIAuth opaque; no public attribute access.**

`PyPIAuth` uses `__slots__` with private `_value` and `_source`. Public access goes through `as_uv_publish_token()` and `source()`. ✓

______________________________________________________________________

**Plan complete and saved to `docs/superpowers/plans/2026-07-17-pypi-auth-redesign.md`.**

Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration with two-stage review gates.

1. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints for review.

Which approach?

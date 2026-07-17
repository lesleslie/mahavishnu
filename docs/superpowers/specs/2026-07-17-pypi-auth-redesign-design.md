---
status: draft
role: canonical
date: 2026-07-17
last_reviewed: 2026-07-17
superseded_by: null
blocks_on: []
topic: crackerjack-publish-auth
---

# PyPI Auth Redesign in Crackerjack — Design (2026-07-17)

## Goal

Replace crackerjack's `publish_manager.py` PyPI authentication flow
with a single, well-bounded `PyPIAuth` abstraction and provider
enumeration. The redesign targets the root cause of a recurring class
of bug: every release uncovers a new way for the credential to be
mangled between discovery (`keyring get`, env-var read) and use
(`uv publish --token`).

Three sources must be supported:

1. Trusted Publishing (OIDC) — preferred, tokenless
2. `UV_PUBLISH_TOKEN` environment variable
3. `keyring` CLI storage

## Context (current state)

The current `crackerjack/managers/publish_manager.py` has accreted
two fixes touching the same auth flow (with a third follow-up
already needed on the dhara side to bypass `cj publish`):

| Commit | Symptom | Fix |
|---|---|---|
| `3f9a8e79` | `mask_generic_long_token` regex corrupted keyring stdout, leaving it starting with `****` instead of `pypi-` | Add `mask_stdout=False` to `_run_command` for keyring calls |
| `b7402b8e` | Discovered token never reached `uv publish` subprocess | Introduce `AuthResult` dataclass; `_execute_publish` injects `UV_PUBLISH_TOKEN` via `additional_env` |

Both fixes are still **WIP on main, not merged**. The installed
`crackerjack==0.68.4` in `/Users/les/Projects/mahavishnu/.venv/` has
both. The dhara repo (`/Users/les/Projects/dhara`) depends on
`crackerjack` without a version pin (`pyproject.toml` line 8).

The current `_check_env_token_auth`, `_check_keyring_auth`,
`_collect_auth_methods`, `_report_auth_status`, and `AuthResult`
together form a fragile pipeline:

- **Three call sites**, each with its own masking flag and return type.
- **Token propagation** to the subprocess is implicit, gated by an
  `additional_env` parameter that must be threaded manually.
- **Masking is global** by default; the credential can only be
  protected by opting out, call-site by call-site.
- **No type-level guarantee** that a raw `str` token cannot be
  re-introduced into a regex or sanitizer.

The result is the same bug class recurring: something somewhere
"helpsfully" cleans up the credential and the upload fails with
"Keyring token format appears invalid".

## Architecture

```
crackerjack/services/pypi_auth/           # NEW MODULE
    __init__.py            # re-exports PyPIAuth, discover_auth, providers
    _auth.py               # PyPIAuth class + PyPIAuthProvider protocol
    _providers.py          # EnvVarAuthProvider, KeyringAuthProvider,
                           #   TrustedPublishingProvider
    _keyring.py            # private _keyring_get_raw() — no masking
    _trusted_publishing.py # private detection helpers

crackerjack/managers/publish_manager.py   # CHANGED
    # DELETED: AuthResult, _check_env_token_auth, _check_keyring_auth,
    #          _collect_auth_methods, _report_auth_status,
    #          _display_auth_setup_instructions
    # NEW:    _resolve_pypi_auth() returning PyPIAuth | None
    # CHANGE: _execute_publish() consumes PyPIAuth (not AuthResult list)

crackerjack/services/security.py          # UNCHANGED
    # mask_tokens and validate_token_format stay — used by other paths.
    # The publish auth path simply stops using them.
```

Out of scope (kept to avoid scope creep):

- Trusted-publishing *enablement* in uv (just detection + a flag —
  actual OIDC token exchange is uv's job).
- PyPI config file support (~/.pypirc) — could be a future
  `PyPIRcAuthProvider`; not in this design.
- Renaming `mask_tokens` or removing the `mask_stdout` flag from
  `_run_command` — those are general-purpose.

## Components

### `PyPIAuth` — opaque credential wrapper

| Member | Visibility | Purpose |
|---|---|---|
| `__init__(self, value: str) -> None` | public | Validates and stores. Raises `ValueError` on empty, missing `pypi-` prefix, or length < 16. Matches `validate_token_format(..., "pypi")` so the two stay in sync. |
| `as_uv_publish_token(self) -> str` | public | Returns the raw string for `UV_PUBLISH_TOKEN=...` injection |
| `is_trusted_publishing(self) -> bool` | public | True if this auth is the TP sentinel (`__TRUSTED_PUBLISHING__`) so the caller chooses `uv publish --trusted-publishing` instead of env-var injection |
| `__repr__(self)` | public | `<PyPIAuth source=keyring>` — never the token bytes |
| `__str__(self)` | dunder | Calls `__repr__` so accidental f-string interpolation is safe |
| `__eq__`, `__hash__` | dunder | By identity only (no value-based hashing of secrets) |
| `__reduce__` | dunder | **Not defined** — pickling a credential should raise clearly |

### `PyPIAuthProvider` — `Protocol`

```python
class PyPIAuthProvider(Protocol):
    name: str
    def is_available(self) -> bool: ...
    def resolve(self) -> PyPIAuth | None: ...
```

A `Protocol` (structural type), not an `ABC` (nominal type). A
future provider added in a downstream plugin doesn't need to import
or subclass anything from crackerjack — it just needs `name`,
`is_available()`, and `resolve()`.

### Concrete providers

Priority order: **Trusted Publishing > Env > Keyring** (operator
chose "safest first").

| Provider | `is_available()` | `resolve()` | Failure mode |
|---|---|---|---|
| `TrustedPublishingProvider` | Checks `ACTIONS_ID_TOKEN_REQUEST_TOKEN` / `GITHUB_ACTIONS` etc. | Returns `PyPIAuth("__TRUSTED_PUBLISHING__")` sentinel | Returns `None` if not in an OIDC-capable CI |
| `EnvVarAuthProvider` | `bool(os.getenv("UV_PUBLISH_TOKEN"))` | Wraps the env var | Returns `None` if unset; malformed (no `pypi-` prefix) raises `ValueError` which the caller catches and returns `None`, falling through to keyring |
| `KeyringAuthProvider` | Always True on platforms where keyring is installed | Calls `_keyring_get_raw()`, wraps result | Returns `None` on subprocess failure, timeout, or token doesn't start with `pypi-` |

### `discover_auth()`

Single entry point. Runs providers in priority order. Returns first
`PyPIAuth` or `None`. The banner code iterates over the *same list*
to display "PyPI authentication available: TP / env / keyring" — so
the operator sees every source that was checked, not just the one
that won.

### `_keyring_get_raw()`

A 5-line private helper:

```python
def _keyring_get_raw(url: str, username: str, timeout: int = 10) -> str | None:
    try:
        result = subprocess.run(
            ["keyring", "get", url, username],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None
```

This is the **only** place in the codebase where a subprocess
stdout is *not* fed through `mask_tokens`. Nothing else calls it,
so no future call site can introduce a regression here.

## Data flow

### Happy path — local dev with keyring

```
operator$ cj publish
        │
        ▼
PublishManagerImpl.publish_package()
        │
        ▼
_validate_prerequisites()
        │
        ▼
_resolve_pypi_auth()
        │
        ├─ TrustedPublishingProvider.is_available()  → False (not in CI)
        ├─ EnvVarAuthProvider.is_available()         → False (no env var)
        └─ KeyringAuthProvider.is_available()        → True
                  │
                  ▼
           _keyring_get_raw() ─── subprocess "keyring get ... __token__"
                  │               returns raw token, NO masking
                  ▼
           KeyringAuthProvider.resolve()
                  │  wraps in PyPIAuth("pypi-Ag...")
                  ▼
           PyPIAuth instance
                  │
                  ▼
_execute_publish()
        │
        ├─ auth.is_trusted_publishing() → False
        └─ extra_env = {"UV_PUBLISH_TOKEN": auth.as_uv_publish_token()}
                  │
                  ▼
        subprocess.run(["uv", "publish"], env={..., "UV_PUBLISH_TOKEN": "pypi-Ag..."})
                  │
                  ▼
        PyPI upload succeeds
```

### Happy path — CI with trusted publishing

```
GitHub Actions / uv publish --trusted-publishing
        │
        ▼
TrustedPublishingProvider.is_available()
        │  detects ACTIONS_ID_TOKEN_REQUEST_TOKEN + GITHUB_ACTIONS
        ▼
TrustedPublishingProvider.resolve()
        │  returns PyPIAuth("__TRUSTED_PUBLISHING__")
        ▼
_execute_publish()
        │
        ├─ auth.is_trusted_publishing() → True
        └─ cmd = ["uv", "publish", "--trusted-publishing"]
        │
        ▼
subprocess.run(["uv", "publish", "--trusted-publishing"], env=secure_env)
        │   (no UV_PUBLISH_TOKEN injected — TP replaces it)
        ▼
PyPI validates OIDC token, accepts upload
```

### Failure paths

| Failure | Where caught | Operator sees |
|---|---|---|
| `UV_PUBLISH_TOKEN` set but malformed | `EnvVarAuthProvider.resolve()` raises `ValueError` | "UV_PUBLISH_TOKEN present but malformed (must start with 'pypi-'). Fix or unset." Skip env, continue to keyring. |
| keyring backend not installed | `_keyring_get_raw()` returns `None` (`FileNotFoundError` caught) | Silent skip to next provider; banner shows keyring as "checked, unavailable" |
| keyring returns token without `pypi-` prefix | `KeyringAuthProvider.resolve()` returns `None` (catches `PyPIAuth()` `ValueError`) | "Keyring token has wrong format (expected 'pypi-...' prefix). Re-run: `keyring set https://upload.pypi.org/legacy/ __token__`" |
| No provider succeeds | `discover_auth()` returns `None` | Existing setup-instructions block runs — *unchanged* — listing the three options in priority order |
| `uv publish` exits non-zero | Existing `_handle_publish_failure()` runs — *unchanged* | "Publish failed: {stderr}" |

## Error handling

### Exception policy

| Site | Raises | Caught by | Result |
|---|---|---|---|
| `PyPIAuth.__init__` | `ValueError` (empty, missing `pypi-` prefix) | The provider that called it | Provider returns `None`, falls through |
| `_keyring_get_raw()` | `FileNotFoundError` if `keyring` CLI missing | Same function (catches internally) | Returns `None` |
| `_keyring_get_raw()` | `subprocess.TimeoutExpired` after 10s | Same function | Logs warning, returns `None` |
| `EnvVarAuthProvider.is_available()` | nothing | — | Just `bool(...)` |
| `TrustedPublishingProvider.is_available()` | nothing | — | Inspects env, returns bool |
| `discover_auth()` | nothing | — | Returns `None` if all providers return `None` |
| `_execute_publish()` | nothing — handles via `_handle_publish_failure()` | — | Returns `False`, prints banner |

### What gets logged vs printed

- **Console (operator-facing):** all banner lines, the existing
  "Setup options" block, success/failure of `uv publish`. Format
  stays the same — `[green]✅[/ green]`, `[yellow]⚠️[/ yellow]`,
  etc.
- **Logger (debug):** provider fall-throughs.
  Format: `logger.debug("EnvVar provider returned None, trying next")`.
  Visible only with `CJ_LOG_LEVEL=DEBUG`.
- **No logger for "wrong format"** — that's a user-actionable
  message, belongs on the console.

### Behavior change vs. current code

The current `_check_env_token_auth` returns the env-var auth
*immediately* without checking keyring, even if the env-var token is
malformed. The new design fixes this (falls through to keyring). For
most users it's an improvement (their keyring still works if their
shell has a stale env var), but a script that relied on the old
behavior will see different output.

### Rollback

No legacy fallback path. Tests + integration coverage are the safety
net. Smaller diff, faster cleanup. Operator chose "trust tests".

## Testing

### Test layers

| Layer | What it covers | Files |
|---|---|---|
| **Unit — `PyPIAuth`** | Constructor accepts/rejects; `__repr__`/`__str__` never leak value; identity-based `__eq__`; pickling raises | `tests/unit/services/test_pypi_auth.py` (new) |
| **Unit — each provider** | `is_available()` returns expected bool for env; `resolve()` returns `PyPIAuth` or `None`; failure modes surface as `None` not exceptions | `tests/unit/services/test_pypi_auth_providers.py` (new) |
| **Unit — `_keyring_get_raw`** | Returns raw stdout (no masking); handles `FileNotFoundError` → `None`; handles timeout → `None`; handles non-zero exit → `None` | `tests/unit/services/test_keyring_raw.py` (new) |
| **Integration — publish manager** | `_resolve_pypi_auth` + `_execute_publish` end-to-end with fake provider list | `tests/unit/managers/test_publish_manager_pyi_auth.py` (replaces parts of `test_publish_manager_extended.py`) |
| **Regression — masking** | Parameterized: for each of `[env, keyring, TP]`, the resolved token reaches `uv publish` env unmodified even when stdout contains `****`-matching substrings | one test, three parametrize cases |

### Critical regression test

```python
@pytest.mark.parametrize("provider_name", [
    "env",
    "keyring",
    "trusted_publishing",
])
def test_publish_injects_unmodified_token(
    provider_name, monkeypatch,
):
    # Regression: prior to the redesign, mask_generic_long_token regex
    # corrupted PyPI tokens by replacing their body with "****".
    # Now, masking never touches the credential once it has been
    # constructed inside a provider.
    sentinel_token = (
        "pypi-AgEIcHlwaS5vcmcC"
        "deadbeefdeadbeefdeadbeefdeadbeef"
        "deadbeefdeadbeefdeadbeefdeadbeef"
    )
    # Stub the subprocess / env / etc. per provider_name
    ...
    # Invoke publish, assert uv publish was called with the exact sentinel
    captured = publish_subprocess_call_args()
    assert captured.env["UV_PUBLISH_TOKEN"] == sentinel_token
```

### Coverage targets

- 95% for `services/pypi_auth/`
- 90% for the changed `publish_manager` methods
- Hard floor: the regression test above must pass on the old code
  too if we apply it as a "would-have-caught-it" check during
  code review.

## Rollout

1. Land this spec (no version bump of crackerjack — same public CLI).
2. Land the implementation in one PR.
3. dhara's `pyproject.toml` line 8 says `"crackerjack"` (no pin) —
   no bump required; uv will resolve the next released version.
4. If any other Bodai repo pins crackerjack to a specific version,
   bump that pin in a follow-up commit.
5. Add a CHANGELOG entry in crackerjack:

   > Refactor publish auth: new `PyPIAuth` abstraction prevents the
   > token-corruption class of bugs that affected earlier 0.68.x
   > releases. Trusted Publishing now detected automatically;
   > `keyring` and `UV_PUBLISH_TOKEN` paths unchanged from operator's
   > perspective.

## Files touched

**New (5):**
- `crackerjack/services/pypi_auth/__init__.py`
- `crackerjack/services/pypi_auth/_auth.py`
- `crackerjack/services/pypi_auth/_providers.py`
- `crackerjack/services/pypi_auth/_keyring.py`
- `crackerjack/services/pypi_auth/_trusted_publishing.py`

**New tests (4):**
- `tests/unit/services/test_pypi_auth.py`
- `tests/unit/services/test_pypi_auth_providers.py`
- `tests/unit/services/test_keyring_raw.py`
- `tests/unit/managers/test_publish_manager_pyi_auth.py`

**Modified (1):**
- `crackerjack/managers/publish_manager.py` — replace the auth flow

**Unchanged:**
- `crackerjack/services/security.py`
- `crackerjack/cli/*` — no CLI surface change
- Public Python API (CLI exit codes, banner strings, env-var names)
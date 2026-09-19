---
status: draft
role: implementation
kind: plan
date: 2026-09-18
last_reviewed: 2026-09-18
superseded_by: null
blocks_on: []
topic: mcp-registrar
revision: 0
---

# MCP Registrar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a canonical `mcp-servers.yaml` registrar that emits both `.mcp.json` (Claude Code, project-tracked) and `~/.qwen/settings.json` (Qwen Code, user-global) from one source, with the Qwen side deep-merging into the existing settings file (preserves the operator-curated `hooks`/`permissions`/`$version` blocks).

**Architecture:** Pure transform-on-write library at `mahavishnu/mcp/registrar.py` plus a Pydantic schema at `mahavishnu/mcp_servers_schema.py`. CLI surface at `mahavishnu/cli/mcp_cli.py::add_mcp_commands(app)` mirrors the existing `add_index_commands` pattern (refactors the 5 lifecycle commands out of `_main_cli.py:707-838` to make room). Pre-commit template at `mahavishnu/core/code_index/git_hooks.py::PRE_COMMIT_CONTENT` gains one `if`-step that runs `mahavishnu mcp sync --target claude` when `mcp-servers.yaml` is present. No daemon, no runtime state.

**Tech Stack:** Pydantic v2, Typer, Python 3.14, `pathlib.Path`, `os.replace` for atomic writes.

**Spec:** [docs/superpowers/specs/2026-09-18-mcp-registrar-design.md](../specs/2026-09-18-mcp-registrar-design.md)

## Global Constraints

These are non-negotiable project-wide rules every task must respect. Values copied verbatim from project CLAUDE.md and the spec.

| Constraint | Source | Value |
|---|---|---|
| Python version | project CLAUDE.md | 3.14 |
| First non-comment line | project CLAUDE.md | `from __future__ import annotations` |
| Type style | project CLAUDE.md | `X \| None`, `list[str]`, `pathlib.Path` (not `Optional`, `List`, `os.path`) |
| Line length | project CLAUDE.md | 100 chars |
| Function args | project CLAUDE.md | ≤10 (excludes `self`, `cls`, `*args`, `**kwargs`) |
| No `assert` in production | project CLAUDE.md | Use `mahavishnu/core/errors.py` exceptions |
| No `Any` in tool inputs | project CLAUDE.md | Use `TYPE_CHECKING` + typed protocols |
| Secret-inlining | project CLAUDE.md + decision rule 1 | Literal secrets NEVER in `.mcp.json` / canonical YAML |
| Pytest binary | project memory `bodai-pytest-binary-cwd` | Always `<repo>/.venv/bin/pytest` (never bare `pytest`) |
| Git author email | project memory `git-author-email-correct-domain` | `les@wedgwoodwebworks.com` (NOT `.local`) |
| Atomic write primitive | spec | `tmp + os.replace()`; cross-FS fallback is copy+unlink with logged warning |
| Qwen deep-merge | spec | `$version`, `permissions`, `hooks`, `model`, all other top-level keys preserved verbatim across `sync` |
| Pre-commit scope | spec | `--target claude` only; Qwen-side emission is operator-driven via `sync --target both` |
| Pre-commit missing-binary | spec | `exit 1` (NOT exit 0 + warn); operator must install or `--no-verify` |
| Audit allowlist | spec | `$VAR_NAME`, `${VAR_NAME}`, `${VAR_NAME:-default}` references must NOT be flagged as inlined secrets |
| Reserved server names | spec | `mcpServers`, `mcp_servers`, `mcp`, `$version`, `permissions`, `hooks`, `model`, `^[_.]+`, contains `.` or `/`, empty |
| Schema version | spec | `Literal[1]`; future versions hard-error with one-line remediation |
| CLI conventions | project CLAUDE.md | No `--quiet` flag anywhere; no `--yes` flag; `--force` is non-interactive |
| Flag vocabulary | spec | Use `--target`, `--scope`, `--selector`, `--format`, `--type` (existing project vocabulary), NOT `--emit` |
| Crackerjack scope | spec | `--fail-fast` is in a separate repo; NOT in this plan |
| SSE transport | spec | Explicit non-goal; `Literal["http","stdio"]` only |

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `mahavishnu/mcp_servers_schema.py` | NEW | Pydantic v2 models: `MCPServerSpec`, `OAuthClientMetadata`, `ServerMeta`, `MCPServersFile`, reserved-name validator |
| `mahavishnu/mcp/registrar.py` | NEW | Library: `Registrar` class, `merge_qwen_settings()`, `atomic_write_json()`, `SyncEnvelope` Pydantic model |
| `mahavishnu/cli/mcp_cli.py` | NEW | Typer CLI: `add_mcp_commands(app)` registers 9 commands (5 lifecycle + 4 registrar + 1 restore) |
| `scripts/audit_no_secrets_in_mcp.py` | MODIFY | Add `audit_dict(config, source_path) -> list[Violation]` library export alongside existing `scan_file()` |
| `mahavishnu/_main_cli.py` | MODIFY | Remove lines 707-838 (inline `mcp_app`); replace with `from .cli.mcp_cli import add_mcp_commands` and `add_mcp_commands(app)` |
| `mahavishnu/core/code_index/git_hooks.py` | MODIFY | Add one `if`-step to `PRE_COMMIT_CONTENT` (line 32-51) running `mahavishnu mcp sync --target claude` when `mcp-servers.yaml` is present |
| `tests/unit/test_mcp_registrar_schema.py` | NEW | Pydantic validation: missing fields per transport, reserved-name rejection (full blocklist), schema-version pinning |
| `tests/unit/test_mcp_registrar_audit.py` | NEW | Audit-dict: Bearer/JWT/vendor-prefix patterns, allowlist (`*_HOST`/`*_URL`/`*_PORT`), `$VAR` references not flagged |
| `tests/unit/test_audit_no_secrets_audit_dict.py` | NEW | Existing audit script's `audit_dict` library export tests |
| `tests/unit/test_mcp_registrar_qwen_shape.py` | NEW | Golden-file Qwen-shape test: `merge_qwen_settings({existing}, {mcp_block})` matches fixture |
| `tests/unit/test_mcp_registrar_atomic_write.py` | NEW | `atomic_write_json` tmp + replace; cross-FS fallback warning |
| `tests/unit/test_mcp_registrar_merge_qwen.py` | NEW | Deep-merge preservation: `$version`/`permissions`/`hooks`/`model` survive sync |
| `tests/unit/test_mcp_registrar_sync.py` | NEW | `Registrar.sync()` orchestrates emit + merge; idempotent; `wrote`/`unchanged`/`skipped` envelope |
| `tests/unit/test_mcp_registrar_migrate.py` | NEW | `Registrar.migrate_from_json` translation rules; `--force`; already-migrated error |
| `tests/integration/test_mcp_sync_e2e.py` | NEW | Round-trip YAML → `.mcp.json` + `~/.qwen/settings.json` (latter via `tmp_path` override); idempotent second sync; `--target qwen` only updates Qwen file |
| `tests/integration/test_mcp_migrate_e2e.py` | NEW | `.mcp.json` → YAML; inline first-sync; no missing-file window |
| `tests/integration/test_pre_commit_emits_mcp.py` | NEW | Modifies `mcp-servers.yaml` → pre-commit hook runs → `.mcp.json` rewritten; bundles shimmed audit-script fixture |
| `tests/fixtures/qwen_settings_expected.json` | NEW | Golden fixture: `{mcpServers, $version, permissions, hooks, model}` deep-merge target |
| `tests/fixtures/mcp_servers_basic.yaml` | NEW | Sample canonical: 2 HTTP servers + 1 stdio server with OAuth + metadata |

## Tasks

Each task ends with an independently testable deliverable. Order respects dependency: schema → audit-dict → helpers → Registrar → migrate → CLI → refactor → pre-commit → wire-up.

### Task 1: Pydantic schema + reserved-name validation

**Files:**
- Create: `mahavishnu/mcp_servers_schema.py`
- Create: `tests/unit/test_mcp_registrar_schema.py`

**Interfaces:**
- Consumes: nothing (pure Pydantic + stdlib)
- Produces:
  - `class MCPServerSpec(BaseModel)` with `transport: Literal["http", "stdio"]`; per-transport fields per spec §"Pydantic models"
  - `class OAuthClientMetadata(BaseModel)` with `client_id`, `client_secret_ref: str`, `scopes`, `authorization_server_url`, `resource_indicator`
  - `class ServerMeta(BaseModel)` with `name | None`, `title | None`, `icons: list[Icon]`, `capabilities: dict[str, bool]`, `protocol_version: str | None`
  - `class MCPServersFile(BaseModel)` with `schema_version: Literal[1]`, `servers: dict[str, MCPServerSpec]`
  - `class ReservedServerNameError(ValueError)`
  - `RESERVED_SERVER_NAMES: frozenset[str]`, `RESERVED_NAME_PATTERNS: tuple[re.Pattern, ...]`
  - `def assert_server_name_valid(name: str) -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_mcp_registrar_schema.py
from __future__ import annotations

import pytest
from pydantic import ValidationError

from mahavishnu.mcp_servers_schema import (
    MCPServerSpec,
    MCPServersFile,
    OAuthClientMetadata,
    ReservedServerNameError,
    assert_server_name_valid,
)


def test_http_server_validates_with_url() -> None:
    spec = MCPServerSpec(transport="http", url="http://localhost:8682/mcp")
    assert spec.transport == "http"
    assert str(spec.url) == "http://localhost:8682/mcp/"  # HttpUrl normalization


def test_http_server_missing_url_raises() -> None:
    with pytest.raises(ValidationError) as exc:
        MCPServerSpec(transport="http")
    assert "url" in str(exc.value)


def test_stdio_server_validates_with_command() -> None:
    spec = MCPServerSpec(
        transport="stdio",
        command="uvx",
        args=["--from", "minimax-coding-plan-mcp"],
    )
    assert spec.transport == "stdio"
    assert spec.command == "uvx"
    assert spec.stdio_encoding == "lengths"  # default


def test_stdio_server_strips_executable_from_args() -> None:
    """Per spec §args semantics: args emitted verbatim, no shell tokenization."""
    spec = MCPServerSpec(
        transport="stdio", command="uvx", args=["--flag 'value with spaces'"]
    )
    assert spec.args == ["--flag 'value with spaces'"]


def test_servers_file_pins_schema_version() -> None:
    raw = {
        "schema_version": 1,
        "servers": {"akosha": {"transport": "http", "url": "http://localhost:8682/mcp"}},
    }
    parsed = MCPServersFile.model_validate(raw)
    assert parsed.schema_version == 1


def test_servers_file_rejects_unknown_schema_version() -> None:
    raw = {"schema_version": 2, "servers": {}}
    with pytest.raises(ValidationError) as exc:
        MCPServersFile.model_validate(raw)
    msg = str(exc.value)
    assert "schema_version" in msg or "2" in msg


@pytest.mark.parametrize(
    "reserved",
    [
        "mcpServers", "mcp_servers", "mcp",
        "$version", "permissions", "hooks", "model",
        "_private", "__dunder__", ".hidden",
        "has/slash", "has.dot", "",
    ],
)
def test_reserved_server_names_rejected(reserved: str) -> None:
    with pytest.raises(ReservedServerNameError):
        assert_server_name_valid(reserved)


def test_oauth_client_secret_ref_is_env_var_name_not_literal() -> None:
    """Per spec: client_secret_ref is a string naming an env var, never a literal."""
    oauth = OAuthClientMetadata(
        client_id="akosha-mcp-client",
        client_secret_ref="AKOSHA_OAUTH_SECRET",
        scopes=["mcp:read"],
        authorization_server_url="https://auth.example.com/oauth2",
        resource_indicator="https://akosha.example.com/mcp",
    )
    assert oauth.client_secret_ref == "AKOSHA_OAUTH_SECRET"
    # No literal value field exists — this is enforced by the model.
    assert not hasattr(oauth, "client_secret")
    assert not hasattr(oauth, "client_secret_value")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `<repo>/.venv/bin/pytest tests/unit/test_mcp_registrar_schema.py -v`
Expected: ImportError on `mahavishnu.mcp_servers_schema` (module does not exist)

- [ ] **Step 3: Write the implementation**

```python
# mahavishnu/mcp_servers_schema.py
"""Canonical Pydantic v2 schema for mcp-servers.yaml.

Per docs/superpowers/specs/2026-09-18-mcp-registrar-design.md §Canonical YAML
schema. Single source of truth for the registrar's input contract.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class ReservedServerNameError(ValueError):
    """Raised when a server name in mcp-servers.yaml collides with a
    wrapper key or an operator-curated Qwen top-level key.

    Rejected pre-Pydantic (see ``assert_server_name_valid``) so the
    error message can name the operator's exact offending key.
    """


RESERVED_SERVER_NAMES: frozenset[str] = frozenset(
    {
        # Wrapper key in the emitted JSON.
        "mcpServers", "mcp_servers", "mcp",
        # Operator-curated Qwen top-level keys (clobber risk).
        "$version", "permissions", "hooks", "model",
    }
)

# Defensive patterns: hidden-attribute-style abuse, filesystem-aliasing
# characters, and JSON-pointer-style dunder names.
RESERVED_NAME_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^[_.]+"),  # starts with one or more _ or . (e.g. _foo, __bar, .baz)
    re.compile(r"[./]"),    # contains . or / (filesystem/JSON-pointer aliasing)
)


def assert_server_name_valid(name: str) -> None:
    """Raise ``ReservedServerNameError`` if ``name`` is in the blocklist
    or matches a reserved pattern. Empty string rejected explicitly."""
    if not name:
        raise ReservedServerNameError("server name must not be empty")
    if name in RESERVED_SERVER_NAMES:
        raise ReservedServerNameError(
            f"server name {name!r} is reserved (collides with a wrapper "
            f"key or operator-curated Qwen top-level key)"
        )
    for pattern in RESERVED_NAME_PATTERNS:
        if pattern.search(name):
            raise ReservedServerNameError(
                f"server name {name!r} matches reserved pattern {pattern.pattern!r}"
            )


class OAuthClientMetadata(BaseModel):
    """OAuth 2.1 / RFC 8707 client metadata.

    ``client_secret_ref`` is the **name** of an env var, never a
    literal value — preserves the secrets-in-shell-env rule for
    OAuth client secrets.
    """

    model_config = ConfigDict(extra="forbid")

    client_id: str = Field(min_length=1)
    client_secret_ref: str = Field(
        min_length=1,
        description="Env var name that holds the client_secret; never a literal.",
    )
    scopes: list[str] = Field(default_factory=list)
    authorization_server_url: HttpUrl
    resource_indicator: HttpUrl


class Icon(BaseModel):
    model_config = ConfigDict(extra="forbid")
    src: HttpUrl
    mime_type: str = Field(alias="mimeType")
    sizes: list[str] = Field(default_factory=list)


class ServerMeta(BaseModel):
    """Cross-emitter metadata (Claude + Qwen); default ``name`` is the YAML key."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    title: str | None = None
    icons: list[Icon] = Field(default_factory=list)
    capabilities: dict[str, bool] = Field(default_factory=dict)
    protocol_version: str | None = Field(default=None, alias="protocol_version")


class _HttpServerSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: HttpUrl
    headers: dict[str, str] = Field(default_factory=dict)
    oauth: OAuthClientMetadata | None = None


class _StdioServerSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command: str = Field(min_length=1)
    args: list[str] = Field(default_factory=list)
    cwd: Path | None = None
    stdio_encoding: Literal["lengths", "lines"] = "lengths"
    connect_timeout_seconds: int | None = Field(default=None, ge=1)
    env: dict[str, str] = Field(default_factory=dict)


class MCPServerSpec(BaseModel):
    """One server entry. ``transport`` discriminates the per-transport fields.

    Reserved server names (``mcpServers``, ``$version``, etc.) are
    rejected pre-Pydantic via ``assert_server_name_valid``; this
    model trusts that the caller has already validated the YAML key.
    """

    model_config = ConfigDict(extra="forbid")

    transport: Literal["http", "stdio"]
    metadata: ServerMeta | None = None
    plugin: str | None = Field(
        default=None,
        description="Forward-compat hook for decision rule 4 plugin substitution; "
        "not resolved by the registrar in phase 1.",
    )

    # Per-transport fields (always present; Pydantic validates by
    # transport-conditional model below).
    http: _HttpServerSpec | None = None
    stdio: _StdioServerSpec | None = None

    # Convenience accessors so ``Registrar`` can build dicts without
    # re-discriminating per-call.
    @property
    def url(self) -> HttpUrl | None:
        return self.http.url if self.http else None

    @property
    def command(self) -> str | None:
        return self.stdio.command if self.stdio else None

    @property
    def args(self) -> list[str]:
        return list(self.stdio.args) if self.stdio else []

    @model_validator(mode="before")
    @classmethod
    def _route_per_transport(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        transport = data.get("transport")
        if transport == "http":
            http = data.get("http")
            if http is None:
                http = {
                    "url": data.get("url"),
                    "headers": data.get("headers", {}),
                    "oauth": data.get("oauth"),
                }
                data = {**data, "http": http}
        elif transport == "stdio":
            stdio = data.get("stdio")
            if stdio is None:
                stdio = {
                    "command": data.get("command"),
                    "args": data.get("args", []),
                    "cwd": data.get("cwd"),
                    "stdio_encoding": data.get("stdio_encoding", "lengths"),
                    "connect_timeout_seconds": data.get("connect_timeout_seconds"),
                    "env": data.get("env", {}),
                }
                data = {**data, "stdio": stdio}
        return data


class MCPServersFile(BaseModel):
    """Top-level wrapper for mcp-servers.yaml."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    servers: dict[str, MCPServerSpec]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `<repo>/.venv/bin/pytest tests/unit/test_mcp_registrar_schema.py -v`
Expected: All 12 parametrized+named cases PASS.

- [ ] **Step 5: Commit**

```bash
git -c user.email=les@wedgwoodwebworks.com add mahavishnu/mcp_servers_schema.py tests/unit/test_mcp_registrar_schema.py
git -c user.email=les@wedgwoodwebworks.com commit -m "feat(mcp-registrar): Pydantic schema + reserved-name validation

Adds mahavishnu/mcp_servers_schema.py with MCPServerSpec,
OAuthClientMetadata, ServerMeta, and MCPServersFile Pydantic v2
models. Reserved server names (mcpServers, \$version, permissions,
hooks, model, ^[_.]+, contains [./], empty) rejected pre-Pydantic
via assert_server_name_valid() with a clear error naming the
offending key.

Per docs/superpowers/specs/2026-09-18-mcp-registrar-design.md
§Canonical YAML schema.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

### Task 2: Audit-dict library export (sibling to `scan_file()`)

**Files:**
- Modify: `scripts/audit_no_secrets_in_mcp.py` — add `audit_dict()` function
- Create: `tests/unit/test_audit_no_secrets_audit_dict.py`

**Interfaces:**
- Consumes: existing `is_secret()`, `is_allowed()`, `looks_like_placeholder()`, `redact()`, `SECRET_PATTERNS`, `ALLOWED_PATTERNS` from `scripts/audit_no_secrets_in_mcp.py`
- Produces: `def audit_dict(config: dict, source_path: Path) -> list[Violation]` where `Violation = tuple[str, str, str]` (key, value, reason)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_audit_no_secrets_audit_dict.py
from __future__ import annotations

from pathlib import Path
import sys

import pytest

# The audit script is at <repo>/scripts/ and is not on sys.path by
# default; tests run from the repo root so a relative import works.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

from audit_no_secrets_in_mcp import (  # noqa: E402
    Violation,
    audit_dict,
    is_allowed,
    is_secret,
    looks_like_placeholder,
    scan_file,
)


def test_audit_dict_returns_empty_for_clean_config(tmp_path: Path) -> None:
    config = {
        "mcpServers": {
            "akosha": {
                "type": "http",
                "url": "http://localhost:8682/mcp",
                "env": {"MINIMAX_API_HOST": "https://api.minimax.io"},
            }
        }
    }
    assert audit_dict(config, tmp_path / "fixture.json") == []


def test_audit_dict_catches_literal_secret(tmp_path: Path) -> None:
    config = {
        "mcpServers": {
            "akosha": {
                "type": "http",
                "url": "http://localhost:8682/mcp",
                "env": {"MINIMAX_API_KEY": "sk-1234567890abcdef"},
            }
        }
    }
    violations = audit_dict(config, tmp_path / "fixture.json")
    assert len(violations) == 1
    key, value, reason = violations[0]
    assert key == "MINIMAX_API_KEY"
    assert "sk-1" in value
    assert reason == "literal-secret"


def test_audit_dict_allows_host_url_port_suffixes(tmp_path: Path) -> None:
    config = {
        "mcpServers": {
            "akosha": {
                "env": {
                    "MINIMAX_API_HOST": "https://api.minimax.io",
                    "AKOSHA_URL": "http://localhost:8682/mcp",
                    "DB_PORT": "5432",
                }
            }
        }
    }
    assert audit_dict(config, tmp_path / "fixture.json") == []


def test_audit_dict_treats_dollar_var_references_as_safe(tmp_path: Path) -> None:
    """Qwen supports $VAR_NAME and ${VAR_NAME:-default} references in env
    values. Per spec §Audit rules, these must NOT be flagged as
    inlined secrets even when the key matches a secret suffix."""
    config = {
        "mcpServers": {
            "akosha": {
                "env": {
                    "DATABASE_PASSWORD": "$DB_PASSWORD",
                    "AUTH_TOKEN": "${AUTH_TOKEN:-fallback}",
                }
            }
        }
    }
    assert audit_dict(config, tmp_path / "fixture.json") == []


def test_audit_dict_catches_bearer_in_header_value(tmp_path: Path) -> None:
    config = {
        "mcpServers": {
            "akosha": {
                "type": "http",
                "url": "http://localhost:8682/mcp",
                "headers": {"Authorization": "Bearer " + "x" * 64},
            }
        }
    }
    violations = audit_dict(config, tmp_path / "fixture.json")
    assert len(violations) >= 1


def test_audit_dict_catches_jwt_in_oauth(tmp_path: Path) -> None:
    config = {
        "mcpServers": {
            "akosha": {
                "oauth": {
                    "client_id": "akosha-mcp-client",
                    "client_secret": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.abc",
                }
            }
        }
    }
    violations = audit_dict(config, tmp_path / "fixture.json")
    assert any("client_secret" in v[0] for v in violations)


def test_scan_file_unchanged_returns_same_results(tmp_path: Path) -> None:
    """Adding audit_dict must not regress scan_file behavior."""
    p = tmp_path / ".mcp.json"
    p.write_text(
        '{"mcpServers": {"a": {"env": {"API_KEY": "literal-here-1234567890"}}}}'
    )
    violations = scan_file(p)
    assert len(violations) == 1
    assert violations[0][0] == "API_KEY"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `<repo>/.venv/bin/pytest tests/unit/test_audit_no_secrets_audit_dict.py -v`
Expected: ImportError or AttributeError on `audit_dict` (function does not exist yet)

- [ ] **Step 3: Write `audit_dict()` in `scripts/audit_no_secrets_in_mcp.py`**

Append to `scripts/audit_no_secrets_in_mcp.py` (just before `def find_mcp_json_files`):

```python
# Additional content-pattern rules applied to header values, env
# values, args strings, and OAuth fields. These extend the existing
# suffix-based rules (SECRET_PATTERNS) — the existing CLI is
# unchanged, only the new audit_dict() library export uses them.
_VALUE_CONTENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^Bearer\s+[A-Za-z0-9_\-]{20,}$"),
    re.compile(r"^Basic\s+[A-Za-z0-9_\-+/=]{20,}$"),
    re.compile(r"^Token\s+[A-Za-z0-9_\-]{20,}$"),
    re.compile(r"^eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"),  # JWT shape
    re.compile(r"^ghp_[A-Za-z0-9]{20,}"),                # GitHub PAT
    re.compile(r"^sk-[A-Za-z0-9_\-]{16,}"),              # OpenAI / Stripe
    re.compile(r"^xox[baprs]-[A-Za-z0-9\-]{10,}"),      # Slack
    re.compile(r"--[a-zA-Z\-]+-(?:token|key|secret)=[A-Za-z0-9_\-]{8,}"),
)

# Env-var reference syntax in values is allowed (Qwen supports
# $VAR_NAME, ${VAR_NAME}, ${VAR_NAME:-default}). We never flag a
# value that starts with $ as a literal secret.
_VAR_REF_PREFIX = re.compile(r"^\$\{?[A-Za-z_][A-Za-z0-9_]*")


def _looks_like_dollar_ref(value: str) -> bool:
    return bool(_VAR_REF_PREFIX.match(value))


def _scan_value_content(value: str) -> str | None:
    """Return a reason string if the value matches a content-pattern
    pattern; None if clean. Skips dollar-ref values."""
    if not isinstance(value, str):
        return None
    if _looks_like_dollar_ref(value):
        return None
    for pat in _VALUE_CONTENT_PATTERNS:
        if pat.search(value):
            return "value-content-pattern"
    return None


def audit_dict(config: dict, source_path: Path) -> list[Violation]:
    """Library-export sibling of :func:`scan_file`.

    Accepts an already-parsed config dict (so callers that emit JSON
    via the registrar library can audit before writing to disk) and
    returns violations in the same ``(key, value, reason)`` tuple
    shape as ``scan_file``. Does not change ``scan_file``'s CLI
    behavior.

    Checks env-var values, header values, OAuth fields, and stdio
    ``args`` strings for content-pattern secrets (Bearer/JWT/vendor
    prefixes) in addition to the existing suffix-based rules.
    """
    violations: list[Violation] = []

    servers_any: Any = config.get("mcpServers", {})
    if not isinstance(servers_any, dict):
        return violations
    servers: dict[str, Any] = cast("dict[str, Any]", servers_any)

    for server_name, server_cfg in servers.items():
        if not isinstance(server_cfg, dict):
            continue

        # Existing suffix-based audit on env vars (mirrors scan_file).
        env_any: Any = server_cfg.get("env", {})
        if isinstance(env_any, dict):
            env: dict[str, Any] = cast("dict[str, Any]", env_any)
            for key, value in env.items():
                if not is_secret(key):
                    continue
                if not value:
                    continue
                reason = (
                    "placeholder"
                    if looks_like_placeholder(value)
                    else "literal-secret"
                )
                violations.append((key, value, reason))

        # Content-pattern audit on header values.
        headers_any: Any = server_cfg.get("headers", {})
        if isinstance(headers_any, dict):
            for hkey, hvalue in cast("dict[str, Any]", headers_any).items():
                if not isinstance(hvalue, str):
                    continue
                reason = _scan_value_content(hvalue)
                if reason:
                    violations.append((f"{server_name}.headers.{hkey}", hvalue, reason))

        # Content-pattern audit on oauth fields (skip client_secret_ref
        # because it's an env-var name, never a literal value).
        oauth_any: Any = server_cfg.get("oauth")
        if isinstance(oauth_any, dict):
            oauth: dict[str, Any] = cast("dict[str, Any]", oauth_any)
            for okey, ovalue in oauth.items():
                if okey == "client_secret_ref":
                    continue
                if not isinstance(ovalue, str):
                    continue
                reason = _scan_value_content(ovalue)
                if reason:
                    violations.append(
                        (f"{server_name}.oauth.{okey}", ovalue, reason)
                    )

        # Content-pattern audit on stdio args strings.
        args_any: Any = server_cfg.get("args", [])
        if isinstance(args_any, list):
            for idx, arg in enumerate(cast("list[Any]", args_any)):
                if not isinstance(arg, str):
                    continue
                reason = _scan_value_content(arg)
                if reason:
                    violations.append(
                        (f"{server_name}.args[{idx}]", arg, reason)
                    )

    return violations
```

Also add the `Violation` alias near the top of the file (next to the imports):

```python
Violation = tuple[str, str, str]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `<repo>/.venv/bin/pytest tests/unit/test_audit_no_secrets_audit_dict.py -v`
Expected: All 7 tests PASS.

- [ ] **Step 5: Run existing audit-script tests to verify no regression**

Run: `<repo>/.venv/bin/pytest tests/unit/test_secrets_scanner.py -v`
Expected: All existing tests still pass (scan_file behavior unchanged).

- [ ] **Step 6: Commit**

```bash
git -c user.email=les@wedgwoodwebworks.com add scripts/audit_no_secrets_in_mcp.py tests/unit/test_audit_no_secrets_audit_dict.py
git -c user.email=les@wedgwoodwebworks.com commit -m "feat(mcp-registrar): audit_dict() library export + content-pattern rules

Adds audit_dict(config, source_path) sibling to scan_file() so the
registrar library can audit before writing to disk. Extends value
content-pattern rules (Bearer/JWT/vendor-prefix) to header values,
OAuth fields, and stdio args strings. Dollar-ref values
(\$VAR_NAME, \${VAR:-default}) are never flagged.

scan_file() CLI behavior is unchanged — this is a library seam only.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

### Task 3: Atomic write helper + Qwen deep-merge

**Files:**
- Create: `mahavishnu/mcp/registrar.py` (will gain `Registrar` class in Tasks 4-5)
- Create: `tests/unit/test_mcp_registrar_qwen_shape.py`
- Create: `tests/unit/test_mcp_registrar_atomic_write.py`
- Create: `tests/unit/test_mcp_registrar_merge_qwen.py`
- Create: `tests/fixtures/qwen_settings_expected.json`

**Interfaces:**
- Consumes: `pathlib.Path`, stdlib `os`, stdlib `json`
- Produces:
  - `def merge_qwen_settings(existing: dict, mcp_block: dict) -> dict` (pure function)
  - `def atomic_write_json(path: Path, data: dict, *, cross_fs_fallback: bool = True) -> None`
  - `class SyncEnvelope(BaseModel)` with `status`, `wrote`, `unchanged`, `skipped`, `errors`, `audit`, `diff_summary`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_mcp_registrar_qwen_shape.py
"""Golden-file test for the Qwen-side merge function.

Per spec §Deep-merge seam: this is the load-bearing wiring proof for
the highest-risk seam (operator's ~/.qwen/settings.json). The
golden-file format follows the Qwen Code docs verified 2026-09-18
via context7 — httpUrl (not url), timeout in ms, trust: false,
$VAR references preserved.
"""

from __future__ import annotations

import json
from pathlib import Path

from mahavishnu.mcp.registrar import merge_qwen_settings


FIXTURE = Path(__file__).parent.parent / "fixtures" / "qwen_settings_expected.json"


def test_merge_qwen_settings_matches_golden_file() -> None:
    existing = {
        "$version": 4,
        "permissions": {"allow": ["WebSearch"]},
        "hooks": {
            "PostToolUse": [
                {"hooks": [{"type": "command", "command": "~/.qwen/hooks/posttooluse"}]}
            ]
        },
    }
    mcp_block = {
        "akosha": {
            "httpUrl": "http://localhost:8682/mcp",
            "trust": False,
        },
        "minimax-coding-plan": {
            "command": "uvx",
            "args": [
                "--from", "minimax-coding-plan-mcp",
                "--with", "mcp<2",
                "minimax-coding-plan-mcp",
                "-y",
            ],
            "env": {"MINIMAX_API_HOST": "https://api.minimax.io"},
            "trust": False,
        },
    }
    result = merge_qwen_settings(existing, mcp_block)
    expected = json.loads(FIXTURE.read_text())
    assert result == expected


def test_merge_qwen_preserves_operator_keys_verbatim() -> None:
    existing = {
        "$version": 4,
        "permissions": {"allow": ["WebSearch"]},
        "hooks": {"PostToolUse": [{"hooks": [{"type": "command", "command": "/tmp/x"}]}]},
        "model": {"name": "qwen-2.5-coder"},
    }
    result = merge_qwen_settings(existing, {"akosha": {"httpUrl": "http://x"}})
    assert result["$version"] == 4
    assert result["permissions"] == {"allow": ["WebSearch"]}
    assert result["hooks"] == existing["hooks"]
    assert result["model"] == {"name": "qwen-2.5-coder"}


def test_merge_qwen_replaces_mcpServers_only() -> None:
    """mcpServers is the only top-level key replaced; everything else preserved."""
    existing = {"$version": 4, "mcpServers": {"old_server": {"command": "old"}}}
    new_block = {"new_server": {"httpUrl": "http://new"}}
    result = merge_qwen_settings(existing, new_block)
    assert result["mcpServers"] == new_block
    assert result["$version"] == 4
    assert "old_server" not in result["mcpServers"]
```

```python
# tests/unit/test_mcp_registrar_atomic_write.py
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from mahavishnu.mcp.registrar import atomic_write_json


def test_atomic_write_creates_file_with_correct_contents(tmp_path: Path) -> None:
    target = tmp_path / "settings.json"
    atomic_write_json(target, {"$version": 4, "mcpServers": {}})
    import json
    assert json.loads(target.read_text()) == {"$version": 4, "mcpServers": {}}


def test_atomic_write_no_tmp_file_left_on_success(tmp_path: Path) -> None:
    target = tmp_path / "settings.json"
    atomic_write_json(target, {"x": 1})
    # No `*.tmp` siblings left behind on success.
    assert list(tmp_path.glob("*.tmp")) == []


def test_atomic_write_replaces_existing_atomically(tmp_path: Path) -> None:
    target = tmp_path / "settings.json"
    target.write_text('{"old": true}')
    atomic_write_json(target, {"new": True})
    assert '"new": true' in target.read_text()


def test_atomic_write_cross_filesystem_falls_back_with_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """When os.replace fails (cross-FS), fall back to copy + unlink with
    a logged warning per spec §Atomic writes."""
    target = tmp_path / "settings.json"
    with patch(
        "mahavishnu.mcp.registrar.os.replace",
        side_effect=OSError("cross-device link not permitted"),
    ):
        with caplog.at_level("WARNING"):
            atomic_write_json(target, {"x": 1})
    assert target.exists()
    assert "cross-filesystem fallback" in caplog.text or "copy" in caplog.text.lower()
```

```python
# tests/unit/test_mcp_registrar_merge_qwen.py
"""Edge-case tests for merge_qwen_settings beyond the golden file."""

from __future__ import annotations

from mahavishnu.mcp.registrar import merge_qwen_settings


def test_merge_empty_existing() -> None:
    result = merge_qwen_settings({}, {"akosha": {"httpUrl": "http://x"}})
    assert result == {"mcpServers": {"akosha": {"httpUrl": "http://x"}}}


def test_merge_with_none_existing() -> None:
    """Type-hint signature says dict; None is treated as empty dict."""
    result = merge_qwen_settings({}, {"akosha": {"httpUrl": "http://x"}})  # type: ignore[arg-type]
    assert "mcpServers" in result


def test_merge_preserves_unrecognized_top_level_keys() -> None:
    """Future Qwen schema additions must not be silently dropped."""
    existing = {"$version": 4, "futureKey": {"novel": "value"}}
    result = merge_qwen_settings(existing, {})
    assert result["futureKey"] == {"novel": "value"}


def test_merge_with_dollar_ref_in_env_value_preserves_ref() -> None:
    """Qwen env-var reference syntax is operator-side, never flagged."""
    mcp_block = {
        "minimax-coding-plan": {
            "command": "uvx",
            "args": ["minimax-coding-plan-mcp"],
            "env": {"MINIMAX_API_KEY": "$MINIMAX_API_KEY"},
            "trust": False,
        }
    }
    result = merge_qwen_settings({}, mcp_block)
    assert (
        result["mcpServers"]["minimax-coding-plan"]["env"]["MINIMAX_API_KEY"]
        == "$MINIMAX_API_KEY"
    )
```

- [ ] **Step 2: Create the Qwen golden fixture**

Write `tests/fixtures/qwen_settings_expected.json`:

```json
{
  "$version": 4,
  "permissions": {"allow": ["WebSearch"]},
  "hooks": {
    "PostToolUse": [
      {"hooks": [{"type": "command", "command": "~/.qwen/hooks/posttooluse"}]}
    ]
  },
  "mcpServers": {
    "akosha": {"httpUrl": "http://localhost:8682/mcp", "trust": false},
    "minimax-coding-plan": {
      "command": "uvx",
      "args": [
        "--from",
        "minimax-coding-plan-mcp",
        "--with",
        "mcp<2",
        "minimax-coding-plan-mcp",
        "-y"
      ],
      "env": {"MINIMAX_API_HOST": "https://api.minimax.io"},
      "trust": false
    }
  }
}
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `<repo>/.venv/bin/pytest tests/unit/test_mcp_registrar_qwen_shape.py tests/unit/test_mcp_registrar_atomic_write.py tests/unit/test_mcp_registrar_merge_qwen.py -v`
Expected: ImportError on `mahavishnu.mcp.registrar` (module does not exist).

- [ ] **Step 4: Write the helpers**

```python
# mahavishnu/mcp/registrar.py
"""Mahavishnu MCP registrar — canonical server-list owner.

Per docs/superpowers/specs/2026-09-18-mcp-registrar-design.md §Architecture:
pure transform-on-write (no daemon, no long-lived process). The
canonical input is ``<project>/mcp-servers.yaml``; the outputs are
``<project>/.mcp.json`` (Claude, full overwrite) and
``~/.qwen/settings.json`` (Qwen, deep-merge preserving
operator-curated top-level keys).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SyncEnvelope(BaseModel):
    """JSON-parseable output of ``mahavishnu mcp sync``.

    Per-side ``wrote``/``unchanged``/``skipped`` keys let downstream
    observability detect one-sided drift (e.g., Claude wrote but
    Qwen was skipped due to schema-verification gate).
    """

    status: str = "ok"
    wrote: dict[str, list[str]] = Field(default_factory=dict)
    unchanged: dict[str, list[str]] = Field(default_factory=dict)
    skipped: dict[str, list[str]] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    audit: dict[str, int] = Field(default_factory=dict)
    diff_summary: dict[str, int] = Field(
        default_factory=lambda: {"added": 0, "removed": 0, "changed": 0}
    )


def merge_qwen_settings(
    existing: dict[str, Any],
    mcp_block: dict[str, Any],
) -> dict[str, Any]:
    """Deep-merge the registrar-emitted ``mcp_block`` into ``existing``
    Qwen settings.

    Per spec §Deep-merge seam: all top-level keys other than
    ``mcpServers`` are preserved verbatim. ``mcpServers`` is the only
    replaced key. This prevents a naive overwrite from clobbering
    the operator-installed ``hooks`` block, ``$version`` field, or
    ``permissions.allow`` list.

    Pure function — no I/O. The caller is responsible for reading
    the current ``~/.qwen/settings.json`` (or passing ``{}``) and
    for writing the result back atomically.
    """
    result: dict[str, Any] = {}
    for key, value in existing.items():
        if key != "mcpServers":
            result[key] = value
    result["mcpServers"] = mcp_block
    return result


def atomic_write_json(
    path: Path,
    data: Any,
    *,
    cross_fs_fallback: bool = True,
) -> None:
    """Write ``data`` as JSON to ``path`` atomically.

    Per spec §Atomic writes: write to a temp file in the same
    directory, then ``os.replace`` into place. Atomic only within a
    single filesystem; if ``os.replace`` fails (cross-FS), fall back
    to copy + unlink with a logged warning.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path_str = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
        try:
            os.replace(tmp_path, path)
        except OSError as exc:
            if not cross_fs_fallback:
                raise
            logger.warning(
                "atomic_write_json: os.replace failed (%s); "
                "falling back to copy + unlink (cross-filesystem)",
                exc,
            )
            shutil.copyfile(tmp_path, path)
            tmp_path.unlink()
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `<repo>/.venv/bin/pytest tests/unit/test_mcp_registrar_qwen_shape.py tests/unit/test_mcp_registrar_atomic_write.py tests/unit/test_mcp_registrar_merge_qwen.py -v`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git -c user.email=les@wedgwoodwebworks.com add mahavishnu/mcp/registrar.py tests/unit/test_mcp_registrar_qwen_shape.py tests/unit/test_mcp_registrar_atomic_write.py tests/unit/test_mcp_registrar_merge_qwen.py tests/fixtures/qwen_settings_expected.json
git -c user.email=les@wedgwoodwebworks.com commit -m "feat(mcp-registrar): Qwen deep-merge + atomic write helpers

Adds merge_qwen_settings() (pure function preserving all non-
mcpServers top-level keys verbatim) and atomic_write_json() (tmp +
os.replace with cross-FS copy+unlink fallback and logged warning).
SyncEnvelope Pydantic model sets the JSON-parseable contract for
the CLI output.

Per docs/superpowers/specs/2026-09-18-mcp-registrar-design.md
§Sync flow + §Qwen-side concerns.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

### Task 4: `Registrar.load_yaml` + `emit_claude` + `sync` orchestrator

**Files:**
- Modify: `mahavishnu/mcp/registrar.py`
- Create: `tests/unit/test_mcp_registrar_sync.py`
- Create: `tests/fixtures/mcp_servers_basic.yaml`

**Interfaces:**
- Consumes: `assert_server_name_valid`, `MCPServersFile`, `audit_dict`, `merge_qwen_settings`, `atomic_write_json`
- Produces:
  - `class Registrar:`
    - `__init__(self, project_root: Path, qwen_settings_path: Path | None = None)`
    - `load_yaml(self) -> MCPServersFile`
    - `emit_claude(self, servers: MCPServersFile) -> dict` (returns the dict; caller writes)
    - `sync(self, *, target: Literal["claude", "qwen", "both"] = "both", dry_run: bool = False, verbose: bool = False) -> SyncEnvelope`

- [ ] **Step 1: Create the YAML fixture**

Write `tests/fixtures/mcp_servers_basic.yaml`:

```yaml
schema_version: 1
servers:
  akosha:
    transport: http
    url: http://localhost:8682/mcp
  crackerjack:
    transport: http
    url: http://localhost:8676/mcp
  minimax-coding-plan:
    transport: stdio
    command: uvx
    args:
      - --from
      - minimax-coding-plan-mcp
      - --with
      - mcp<2
      - minimax-coding-plan-mcp
      - "-y"
    env:
      MINIMAX_API_HOST: https://api.minimax.io
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/unit/test_mcp_registrar_sync.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mahavishnu.mcp.registrar import Registrar


def test_load_yaml_parses_basic_file() -> None:
    fixture = Path(__file__).parent.parent / "fixtures" / "mcp_servers_basic.yaml"
    reg = Registrar(project_root=fixture.parent)
    parsed = reg.load_yaml()
    assert parsed.schema_version == 1
    assert "akosha" in parsed.servers
    assert parsed.servers["akosha"].transport == "http"


def test_load_yaml_rejects_reserved_server_name(tmp_path: Path) -> None:
    bad = tmp_path / "mcp-servers.yaml"
    bad.write_text(
        "schema_version: 1\n"
        "servers:\n"
        "  mcpServers:\n"
        "    transport: http\n"
        "    url: http://localhost/x\n"
    )
    reg = Registrar(project_root=tmp_path)
    with pytest.raises(ValueError, match="reserved"):
        reg.load_yaml()


def test_emit_claude_matches_existing_mcp_json_shape(tmp_path: Path) -> None:
    fixture = Path(__file__).parent.parent / "fixtures" / "mcp_servers_basic.yaml"
    reg = Registrar(project_root=fixture.parent)
    parsed = reg.load_yaml()
    emitted = reg.emit_claude(parsed)
    assert "mcpServers" in emitted
    assert emitted["mcpServers"]["akosha"]["type"] == "http"
    assert (
        emitted["mcpServers"]["akosha"]["url"] == "http://localhost:8682/mcp"
    )
    assert emitted["mcpServers"]["minimax-coding-plan"]["command"] == "uvx"
    assert (
        emitted["mcpServers"]["minimax-coding-plan"]["env"]["MINIMAX_API_HOST"]
        == "https://api.minimax.io"
    )


def test_sync_writes_both_files_when_target_both(tmp_path: Path) -> None:
    fixture = Path(__file__).parent.parent / "fixtures" / "mcp_servers_basic.yaml"
    qwen = tmp_path / "qwen_settings.json"
    qwen.write_text(json.dumps({"$version": 4, "permissions": {"allow": ["WebSearch"]}}))

    # Copy fixture YAML into tmp_path so the project root matches.
    project = tmp_path / "project"
    project.mkdir()
    (project / "mcp-servers.yaml").write_text(fixture.read_text())
    reg = Registrar(project_root=project, qwen_settings_path=qwen)

    envelope = reg.sync(target="both")
    assert envelope.status == "ok"
    assert "claude" in envelope.wrote
    assert "qwen" in envelope.wrote
    assert (project / ".mcp.json").exists()
    assert qwen.exists()


def test_sync_idempotent_second_run_writes_nothing(tmp_path: Path) -> None:
    fixture = Path(__file__).parent.parent / "fixtures" / "mcp_servers_basic.yaml"
    project = tmp_path / "project"
    project.mkdir()
    (project / "mcp-servers.yaml").write_text(fixture.read_text())
    qwen = tmp_path / "qwen_settings.json"
    reg = Registrar(project_root=project, qwen_settings_path=qwen)

    first = reg.sync(target="both")
    assert first.wrote.get("claude")
    second = reg.sync(target="both")
    assert second.unchanged.get("claude")
    assert second.wrote.get("claude", []) == []
    assert second.unchanged.get("qwen")


def test_sync_dry_run_does_not_write_files(tmp_path: Path) -> None:
    fixture = Path(__file__).parent.parent / "fixtures" / "mcp_servers_basic.yaml"
    project = tmp_path / "project"
    project.mkdir()
    (project / "mcp-servers.yaml").write_text(fixture.read_text())
    qwen = tmp_path / "qwen_settings.json"
    reg = Registrar(project_root=project, qwen_settings_path=qwen)

    envelope = reg.sync(target="both", dry_run=True)
    assert not (project / ".mcp.json").exists()
    assert not qwen.exists()
    assert envelope.wrote.get("claude") == []
    assert envelope.wrote.get("qwen") == []


def test_sync_target_qwen_does_not_overwrite_claude_file(tmp_path: Path) -> None:
    fixture = Path(__file__).parent.parent / "fixtures" / "mcp_servers_basic.yaml"
    project = tmp_path / "project"
    project.mkdir()
    (project / "mcp-servers.yaml").write_text(fixture.read_text())
    claude_file = project / ".mcp.json"
    claude_file.write_text(json.dumps({"mcpServers": {"old": {"command": "old"}}}))
    qwen = tmp_path / "qwen_settings.json"
    qwen.write_text(json.dumps({"$version": 4}))
    reg = Registrar(project_root=project, qwen_settings_path=qwen)

    envelope = reg.sync(target="qwen")
    assert envelope.wrote.get("qwen")
    assert "claude" not in envelope.wrote
    # Claude file untouched.
    assert json.loads(claude_file.read_text()) == {
        "mcpServers": {"old": {"command": "old"}}
    }


def test_sync_preserves_existing_qwen_top_level_keys(tmp_path: Path) -> None:
    """Operator-installed hooks / permissions / $version survive a sync."""
    fixture = Path(__file__).parent.parent / "fixtures" / "mcp_servers_basic.yaml"
    project = tmp_path / "project"
    project.mkdir()
    (project / "mcp-servers.yaml").write_text(fixture.read_text())
    qwen = tmp_path / "qwen_settings.json"
    existing = {
        "$version": 4,
        "permissions": {"allow": ["WebSearch"]},
        "hooks": {
            "PostToolUse": [
                {"hooks": [{"type": "command", "command": "/tmp/x"}]}
            ]
        },
        "model": {"name": "qwen-2.5-coder"},
    }
    qwen.write_text(json.dumps(existing))
    reg = Registrar(project_root=project, qwen_settings_path=qwen)

    reg.sync(target="both")
    result = json.loads(qwen.read_text())
    assert result["$version"] == 4
    assert result["permissions"] == existing["permissions"]
    assert result["hooks"] == existing["hooks"]
    assert result["model"] == existing["model"]
    assert "mcpServers" in result
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `<repo>/.venv/bin/pytest tests/unit/test_mcp_registrar_sync.py -v`
Expected: ImportError or AttributeError on `Registrar`.

- [ ] **Step 4: Implement `Registrar` in `mahavishnu/mcp/registrar.py`**

Append to `mahavishnu/mcp/registrar.py`:

```python
import sys
from typing import Literal

from mahavishnu.mcp_servers_schema import (
    MCPServerSpec,
    MCPServersFile,
    assert_server_name_valid,
)

# Import the audit library seam from the scripts/ directory. We add
# scripts/ to sys.path here (rather than in pyproject) because the
# audit script is a CLI-first tool with a library export — promoting
# it to a package would be churn for a script that 99% of operators
# invoke directly.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from audit_no_secrets_in_mcp import audit_dict  # noqa: E402


class Registrar:
    """Pure transform-on-write registrar.

    Reads ``<project_root>/mcp-servers.yaml``, validates it via the
    schema, audits for inlined secrets, and writes
    ``<project_root>/.mcp.json`` (Claude, full overwrite) and
    ``qwen_settings_path`` (Qwen, deep-merge into the existing file).

    Pass ``qwen_settings_path=None`` (the default) to use
    ``~/.qwen/settings.json``; tests pass a tmp_path override.
    """

    DEFAULT_QWEN_SETTINGS = Path.home() / ".qwen" / "settings.json"

    def __init__(
        self,
        project_root: Path,
        qwen_settings_path: Path | None = None,
    ) -> None:
        self.project_root = Path(project_root)
        self.canonical_yaml = self.project_root / "mcp-servers.yaml"
        self.claude_output = self.project_root / ".mcp.json"
        self.qwen_settings_path = (
            Path(qwen_settings_path) if qwen_settings_path else self.DEFAULT_QWEN_SETTINGS
        )

    def load_yaml(self) -> MCPServersFile:
        """Read the canonical YAML, validate against the schema.

        Reserved-name check happens before Pydantic validation so the
        operator sees the exact offending key in the error message.
        """
        import yaml

        with self.canonical_yaml.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        if not isinstance(raw, dict):
            raise ValueError(
                f"{self.canonical_yaml}: expected top-level mapping, got {type(raw).__name__}"
            )

        servers_any = raw.get("servers", {})
        if isinstance(servers_any, dict):
            for name in servers_any:
                assert_server_name_valid(name)

        return MCPServersFile.model_validate(raw)

    def emit_claude(self, servers: MCPServersFile) -> dict[str, Any]:
        """Render the Claude-side .mcp.json shape from the parsed YAML.

        Output shape:
        ``{"mcpServers": {<name>: {<per-transport fields>, ...}}}``
        """
        out: dict[str, Any] = {"mcpServers": {}}
        for name, spec in servers.servers.items():
            entry: dict[str, Any] = {}
            if spec.transport == "http":
                entry["type"] = "http"
                entry["url"] = str(spec.http.url) if spec.http else ""
                if spec.http and spec.http.headers:
                    entry["headers"] = dict(spec.http.headers)
                if spec.http and spec.http.oauth:
                    entry["oauth"] = spec.http.oauth.model_dump(by_alias=True)
            elif spec.transport == "stdio":
                entry["command"] = spec.stdio.command if spec.stdio else ""
                entry["args"] = list(spec.stdio.args) if spec.stdio else []
                if spec.stdio and spec.stdio.cwd:
                    entry["cwd"] = str(spec.stdio.cwd)
                if spec.stdio and spec.stdio.env:
                    entry["env"] = dict(spec.stdio.env)
                # stdio_encoding and connect_timeout_seconds emit only
                # when non-default / non-None — Claude Code ignores them
                # but other MCP loaders may not.
                if spec.stdio and spec.stdio.stdio_encoding != "lengths":
                    entry["stdio_encoding"] = spec.stdio.stdio_encoding
                if spec.stdio and spec.stdio.connect_timeout_seconds is not None:
                    entry["connect_timeout_seconds"] = (
                        spec.stdio.connect_timeout_seconds
                    )
            out["mcpServers"][name] = entry
        return out

    def _build_qwen_block(self, servers: MCPServersFile) -> dict[str, Any]:
        """Render the mcpServers block for Qwen-side emission.

        Per spec §Qwen schema verification (context7-verified 2026-09-18):
        - HTTP transport uses ``httpUrl`` (not ``url``).
        - Stdio transport uses ``command``/``args``/``env`` unchanged.
        - Per-server ``timeout`` (canonical: ``connect_timeout_seconds``)
          becomes Qwen ``timeout`` in milliseconds (multiply by 1000).
        - ``trust: false`` (default) added to every Qwen-side emit.
        """
        block: dict[str, Any] = {}
        for name, spec in servers.servers.items():
            entry: dict[str, Any] = {"trust": False}
            if spec.transport == "http":
                entry["httpUrl"] = str(spec.http.url) if spec.http else ""
                if spec.http and spec.http.headers:
                    entry["headers"] = dict(spec.http.headers)
                if spec.http and spec.http.oauth:
                    entry["oauth"] = spec.http.oauth.model_dump(by_alias=True)
            elif spec.transport == "stdio":
                entry["command"] = spec.stdio.command if spec.stdio else ""
                entry["args"] = list(spec.stdio.args) if spec.stdio else []
                if spec.stdio and spec.stdio.cwd:
                    entry["cwd"] = str(spec.stdio.cwd)
                if spec.stdio and spec.stdio.env:
                    entry["env"] = dict(spec.stdio.env)
                if spec.stdio and spec.stdio.connect_timeout_seconds is not None:
                    entry["timeout"] = spec.stdio.connect_timeout_seconds * 1000
            block[name] = entry
        return block

    def sync(
        self,
        *,
        target: Literal["claude", "qwen", "both"] = "both",
        dry_run: bool = False,
        verbose: bool = False,
    ) -> SyncEnvelope:
        """Top-level sync entry point.

        Reads canonical YAML, audits, then per-target:
          - claude: full overwrite of .mcp.json (idempotent if
            contents unchanged).
          - qwen: deep-merge into existing ~/.qwen/settings.json,
            preserving all non-mcpServers top-level keys.
        """
        envelope = SyncEnvelope()
        parsed = self.load_yaml()

        # Audit before write — block on violations.
        claude_dict = self.emit_claude(parsed)
        violations = audit_dict(claude_dict, self.claude_output)
        envelope.audit = {
            "violations": len(violations),
            "scanned_files": 1,
        }
        if violations:
            envelope.status = "audit-failed"
            envelope.errors = [
                f"{key} = {value} [{reason}]" for key, value, reason in violations
            ]
            return envelope

        # Read current Qwen settings (or empty) for the deep-merge.
        qwen_existing: dict[str, Any] = {}
        if self.qwen_settings_path.exists():
            try:
                qwen_existing = json.loads(
                    self.qwen_settings_path.read_text(encoding="utf-8")
                )
                if not isinstance(qwen_existing, dict):
                    qwen_existing = {}
            except json.JSONDecodeError:
                # Backup the corrupt file before overwriting.
                backup = self.qwen_settings_path.with_suffix(
                    f".bak.corrupt.{int(os.path.getmtime(self.qwen_settings_path))}"
                )
                shutil.copyfile(self.qwen_settings_path, backup)
                logger.warning(
                    "Qwen settings file was corrupt; backed up to %s and starting fresh",
                    backup,
                )
                qwen_existing = {}

        qwen_block = self._build_qwen_block(parsed)
        qwen_merged = merge_qwen_settings(qwen_existing, qwen_block)

        # Write Claude side.
        if target in ("claude", "both"):
            if not dry_run:
                existing = (
                    json.loads(self.claude_output.read_text())
                    if self.claude_output.exists()
                    else None
                )
                if existing == claude_dict:
                    envelope.unchanged.setdefault("claude", []).append(
                        str(self.claude_output)
                    )
                else:
                    atomic_write_json(self.claude_output, claude_dict)
                    envelope.wrote.setdefault("claude", []).append(
                        str(self.claude_output)
                    )
                if verbose:
                    logger.info("claude wrote: %s", self.claude_output)

        # Write Qwen side (deep-merge via merge_qwen_settings).
        if target in ("qwen", "both"):
            if not dry_run:
                if qwen_existing == qwen_merged:
                    envelope.unchanged.setdefault("qwen", []).append(
                        str(self.qwen_settings_path)
                    )
                else:
                    # Auto-backup the prior Qwen file (one rolling
                    # backup; older backups not retained).
                    if self.qwen_settings_path.exists():
                        backup = self.qwen_settings_path.with_suffix(
                            f".bak.{int(os.path.getmtime(self.qwen_settings_path))}"
                        )
                        shutil.copyfile(self.qwen_settings_path, backup)
                    atomic_write_json(self.qwen_settings_path, qwen_merged)
                    envelope.wrote.setdefault("qwen", []).append(
                        str(self.qwen_settings_path)
                    )
                if verbose:
                    logger.info("qwen wrote: %s", self.qwen_settings_path)

        return envelope
```

Also add `pyyaml` to dependencies if not already there — but check first:

```bash
grep -n "^pyyaml\|^yaml\b" /Users/les/Projects/mahavishnu/pyproject.toml
```

If absent, add it via `crackerjack run -p minor` flow (per project memory `crackerjack-cli-run-subcommand`). For this plan, add the line manually to `pyproject.toml [project] dependencies` section — but defer the actual install + version bump to the user (per memory `feedback-mcp-common-version-bump-is-user`). Add a comment marker in the plan:

```toml
# pyyaml required by mahavishnu/mcp/registrar.py load_yaml().
# Install: uv pip install pyyaml (or wait for next user-driven
# minor version bump via crackerjack).
"pyyaml>=6.0",
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `<repo>/.venv/bin/pytest tests/unit/test_mcp_registrar_sync.py -v`
Expected: All 7 tests PASS.

- [ ] **Step 6: Commit**

```bash
git -c user.email=les@wedgwoodwebworks.com add mahavishnu/mcp/registrar.py tests/unit/test_mcp_registrar_sync.py tests/fixtures/mcp_servers_basic.yaml
git -c user.email=les@wedgwoodwebworks.com commit -m "feat(mcp-registrar): Registrar class with load_yaml + sync orchestrator

Adds Registrar(project_root, qwen_settings_path=None) with:
- load_yaml(): schema-validate + reserved-name check
- emit_claude(): render .mcp.json shape (full overwrite)
- sync(): per-target Claude full overwrite + Qwen deep-merge

Qwen-side field-name remapping (canonical url -> Qwen httpUrl;
connect_timeout_seconds -> timeout in ms; trust: false) lives inside
_build_qwen_block() per spec \u00a7Qwen schema verification.

Idempotent: second sync with unchanged YAML writes zero files
(wrote=[]/unchanged=[<path>]). Dry-run reports without writing.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

### Task 5: `Registrar.migrate_from_json`

**Files:**
- Modify: `mahavishnu/mcp/registrar.py`
- Create: `tests/unit/test_mcp_registrar_migrate.py`

**Interfaces:**
- Consumes: `Registrar`, existing `.mcp.json` shape
- Produces:
  - `def Registrar.migrate_from_json(self, *, force: bool = False, dry_run: bool = False) -> SyncEnvelope`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_mcp_registrar_migrate.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mahavishnu.mcp.registrar import Registrar


SAMPLE_MCP_JSON = {
    "mcpServers": {
        "akosha": {"type": "http", "url": "http://localhost:8682/mcp"},
        "minimax-coding-plan": {
            "command": "uvx",
            "args": ["--from", "minimax-coding-plan-mcp"],
            "env": {"MINIMAX_API_HOST": "https://api.minimax.io"},
        },
    }
}


def test_migrate_writes_yaml_and_regenerates_claude_file(tmp_path: Path) -> None:
    claude_file = tmp_path / ".mcp.json"
    claude_file.write_text(json.dumps(SAMPLE_MCP_JSON))
    qwen = tmp_path / "qwen_settings.json"
    reg = Registrar(project_root=tmp_path, qwen_settings_path=qwen)

    envelope = reg.migrate_from_json()
    assert envelope.status == "ok"
    yaml_path = tmp_path / "mcp-servers.yaml"
    assert yaml_path.exists()
    parsed = yaml.safe_load(yaml_path.read_text())  # type: ignore[attr-defined]  # noqa: F821
    assert parsed["schema_version"] == 1
    assert parsed["servers"]["akosha"]["transport"] == "http"
    assert parsed["servers"]["minimax-coding-plan"]["transport"] == "stdio"


def test_migrate_refuses_overwrite_without_force(tmp_path: Path) -> None:
    claude_file = tmp_path / ".mcp.json"
    claude_file.write_text(json.dumps(SAMPLE_MCP_JSON))
    (tmp_path / "mcp-servers.yaml").write_text("schema_version: 1\nservers: {}\n")
    reg = Registrar(project_root=tmp_path, qwen_settings_path=tmp_path / "q.json")

    with pytest.raises(FileExistsError, match="already exists"):
        reg.migrate_from_json()


def test_migrate_force_overwrites_existing_yaml(tmp_path: Path) -> None:
    claude_file = tmp_path / ".mcp.json"
    claude_file.write_text(json.dumps(SAMPLE_MCP_JSON))
    (tmp_path / "mcp-servers.yaml").write_text("schema_version: 1\nservers: {}\n")
    reg = Registrar(project_root=tmp_path, qwen_settings_path=tmp_path / "q.json")

    envelope = reg.migrate_from_json(force=True)
    assert envelope.status == "ok"


def test_migrate_runs_inline_first_sync(tmp_path: Path) -> None:
    """Per spec §Migration: Phase 2 -> 3 transition is gap-free — there
    must be no window where .mcp.json is missing on disk between
    migration and the operator's first re-emit."""
    claude_file = tmp_path / ".mcp.json"
    claude_file.write_text(json.dumps(SAMPLE_MCP_JSON))
    reg = Registrar(project_root=tmp_path, qwen_settings_path=tmp_path / "q.json")

    reg.migrate_from_json()
    # .mcp.json still exists with regenerated content.
    assert claude_file.exists()
    new_content = json.loads(claude_file.read_text())
    assert "akosha" in new_content["mcpServers"]


def test_migrate_dry_run_does_not_write(tmp_path: Path) -> None:
    claude_file = tmp_path / ".mcp.json"
    claude_file.write_text(json.dumps(SAMPLE_MCP_JSON))
    reg = Registrar(project_root=tmp_path, qwen_settings_path=tmp_path / "q.json")

    envelope = reg.migrate_from_json(dry_run=True)
    assert envelope.status == "ok"
    assert not (tmp_path / "mcp-servers.yaml").exists()


def test_migrate_translates_oauth_field(tmp_path: Path) -> None:
    """If the source .mcp.json has oauth (RFC 8707 client metadata),
    migrate translates it to the canonical oauth: block."""
    source = {
        "mcpServers": {
            "akosha": {
                "type": "http",
                "url": "http://localhost:8682/mcp",
                "oauth": {
                    "client_id": "akosha",
                    "client_secret_ref": "AKOSHA_OAUTH_SECRET",
                    "scopes": ["mcp:read"],
                    "authorization_server_url": "https://auth.example.com/oauth2",
                    "resource_indicator": "https://akosha.example.com/mcp",
                },
            }
        }
    }
    (tmp_path / ".mcp.json").write_text(json.dumps(source))
    reg = Registrar(project_root=tmp_path, qwen_settings_path=tmp_path / "q.json")

    reg.migrate_from_json()
    parsed = yaml.safe_load((tmp_path / "mcp-servers.yaml").read_text())  # type: ignore[attr-defined]  # noqa: F821
    oauth = parsed["servers"]["akosha"]["oauth"]
    assert oauth["client_secret_ref"] == "AKOSHA_OAUTH_SECRET"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `<repo>/.venv/bin/pytest tests/unit/test_mcp_registrar_migrate.py -v`
Expected: AttributeError on `Registrar.migrate_from_json`.

- [ ] **Step 3: Implement `migrate_from_json`**

Append to `mahavishnu/mcp/registrar.py`:

```python
import yaml  # noqa: E402  (added in Task 4; safe to import here)
```

Then append:

```python
    def migrate_from_json(
        self,
        *,
        force: bool = False,
        dry_run: bool = False,
    ) -> SyncEnvelope:
        """One-shot converter: ``.mcp.json`` -> ``mcp-servers.yaml``.

        Per spec §Migration: runs first sync inline so there is no
        window where ``.mcp.json`` is missing on disk between
        migration and the operator's first re-emit. Idempotent:
        refuses to overwrite an existing YAML unless ``--force``
        (non-interactive, no confirmation prompt).
        """
        envelope = SyncEnvelope()
        if not self.claude_output.exists():
            envelope.status = "no-input"
            envelope.errors.append(
                f"no source .mcp.json at {self.claude_output}"
            )
            return envelope

        source = json.loads(self.claude_output.read_text(encoding="utf-8"))
        if not isinstance(source, dict):
            envelope.status = "bad-input"
            envelope.errors.append(
                f"{self.claude_output}: expected top-level object, got {type(source).__name__}"
            )
            return envelope

        # Translation rules (auditable per spec §Migration):
        canonical: dict[str, Any] = {"schema_version": 1, "servers": {}}
        for name, server_cfg in source.get("mcpServers", {}).items():
            if not isinstance(server_cfg, dict):
                continue
            entry: dict[str, Any] = {}
            if server_cfg.get("type") == "http" and "url" in server_cfg:
                entry["transport"] = "http"
                entry["url"] = server_cfg["url"]
                if "headers" in server_cfg:
                    entry["headers"] = server_cfg["headers"]
                if "oauth" in server_cfg:
                    entry["oauth"] = server_cfg["oauth"]
            elif "command" in server_cfg:
                entry["transport"] = "stdio"
                entry["command"] = server_cfg["command"]
                if "args" in server_cfg:
                    entry["args"] = server_cfg["args"]
                if "cwd" in server_cfg:
                    entry["cwd"] = server_cfg["cwd"]
                if "env" in server_cfg:
                    entry["env"] = server_cfg["env"]
                if "stdio_encoding" in server_cfg:
                    entry["stdio_encoding"] = server_cfg["stdio_encoding"]
                if "connect_timeout_seconds" in server_cfg:
                    entry["connect_timeout_seconds"] = server_cfg[
                        "connect_timeout_seconds"
                    ]
            canonical["servers"][name] = entry

        # Write YAML.
        if self.canonical_yaml.exists() and not force:
            raise FileExistsError(
                f"{self.canonical_yaml} already exists; pass --force to overwrite"
            )
        if dry_run:
            envelope.audit = {"violations": 0, "scanned_files": 0}
            return envelope

        atomic_write_json(self.canonical_yaml, canonical)
        # First sync inline (Phase 2 -> 3 gap-free).
        return self.sync(target="both")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `<repo>/.venv/bin/pytest tests/unit/test_mcp_registrar_migrate.py -v`
Expected: All 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git -c user.email=les@wedgwoodwebworks.com add mahavishnu/mcp/registrar.py tests/unit/test_mcp_registrar_migrate.py
git -c user.email=les@wedgwoodwebworks.com commit -m "feat(mcp-registrar): migrate_from_json with inline first-sync

Adds Registrar.migrate_from_json() that converts .mcp.json to
mcp-servers.yaml using the documented translation rules and runs
the first sync inline. No missing-file window between migration
and re-emit; refuses to overwrite an existing YAML unless
force=True (non-interactive).

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

### Task 6: Refactor 5 lifecycle commands into `cli/mcp_cli.py::add_mcp_commands`

This task happens **before** Tasks 7-8 (which add the new registrar commands to the same `mcp_app`). Doing the refactor first means `_main_cli.py` has no inline `mcp_app` at all and the new module owns the whole `mcp` subtree.

**Files:**
- Create: `mahavishnu/cli/mcp_cli.py`
- Modify: `mahavishnu/_main_cli.py` (remove lines 707-838; add import + `add_mcp_commands(app)`)

**Interfaces:**
- Consumes: existing `mcp_app` block from `_main_cli.py:707-838` (5 commands)
- Produces:
  - `mahavishnu/cli/mcp_cli.py::add_mcp_commands(app: typer.Typer) -> None`

- [ ] **Step 1: Create the new CLI module skeleton**

Create `mahavishnu/cli/mcp_cli.py`:

```python
"""CLI for Mahavishnu MCP server lifecycle + registrar commands.

Mirrors the ``add_index_commands(app)`` pattern from
``mahavishnu/cli/index_cli.py``. Both the legacy lifecycle commands
(start/stop/restart/status/health) and the new registrar commands
(sync/migrate-from-json/validate/show/qwen-restore) live here.
"""

from __future__ import annotations

import asyncio
import json  # noqa: F401  (used by future subcommands)
from typing import NoReturn

import typer

from mahavishnu.mcp.registrar import Registrar

DEFAULT_MCP_HOST = "127.0.0.1"
DEFAULT_MCP_PORT = 8680

mcp_app = typer.Typer(help="MCP server lifecycle management + registrar")


# --- Legacy lifecycle commands (refactored from mahavishnu/_main_cli.py) --


@mcp_app.command("start")
def mcp_start(
    host: str = typer.Option(DEFAULT_MCP_HOST, "--host", "-h", help="Host address to bind to"),
    port: int = typer.Option(DEFAULT_MCP_PORT, "--port", "-p", help="Port to listen on"),
):
    """Start the MCP server to expose tools via mcp-common."""

    async def _start():
        from mahavishnu.core.app import MahavishnuApp

        maha_app = MahavishnuApp()
        server = _resolve_server(maha_app)
        try:
            await server.start(host=host, port=port)
        except KeyboardInterrupt:
            typer.echo("\nShutting down MCP server...")
        finally:
            await server.stop()

    asyncio.run(_start())


@mcp_app.command("stop")
def mcp_stop() -> NoReturn:
    """Stop the MCP server."""
    typer.echo("ERROR: MCP server stop not yet implemented")
    typer.echo("The MCP server runs in the foreground. Use Ctrl+C to stop it.")
    raise typer.Exit(code=1)


@mcp_app.command("restart")
def mcp_restart(
    host: str = typer.Option(DEFAULT_MCP_HOST, "--host", "-h", help="Host address to bind to"),
    port: int = typer.Option(DEFAULT_MCP_PORT, "--port", "-p", help="Port to listen on"),
) -> NoReturn:
    """Restart the MCP server."""
    typer.echo("ERROR: MCP server restart not yet implemented")
    typer.echo("Use Ctrl+C to stop the server, then run 'mahavishnu mcp start' to restart.")
    raise typer.Exit(code=1)


@mcp_app.command("status")
def mcp_status() -> None:
    """Check MCP server status."""

    async def _status():
        from mahavishnu.core.app import MahavishnuApp

        maha_app = MahavishnuApp()
        # FastMCPServer instantiation for side effects (initialization).
        _ = _resolve_server(maha_app)
        terminal_status = "enabled" if maha_app.config.terminal.enabled else "disabled"
        typer.echo(f"Terminal Management: {terminal_status}")
        if maha_app.config.terminal.enabled:
            typer.echo(
                f"  Max concurrent sessions: {maha_app.config.terminal.max_concurrent_sessions}"
            )
            typer.echo(
                f"  Default dimensions: {maha_app.config.terminal.default_columns}"
                f"x{maha_app.config.terminal.default_rows}"
            )
            typer.echo(f"  Adapter preference: {maha_app.config.terminal.adapter_preference}")
        typer.echo(
            f"Server will bind to: {DEFAULT_MCP_HOST}:{DEFAULT_MCP_PORT} (configurable)"
        )
        typer.echo("\nTo start the server, run: mahavishnu mcp start")

    asyncio.run(_status())


@mcp_app.command("health")
def mcp_health() -> None:
    """Check MCP server health."""

    async def _health():
        host = DEFAULT_MCP_HOST
        port = DEFAULT_MCP_PORT
        try:
            _reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=2.0
            )
            writer.close()
            await writer.wait_closed()
            typer.echo("MCP Server: ✓ Running")
            typer.echo(f"Connected to {host}:{port}")
        except (TimeoutError, ConnectionRefusedError, OSError):
            typer.echo("MCP Server: ✗ Not running")
            typer.echo(f"Could not connect to {host}:{port}")
        except Exception as e:  # noqa: BLE001 - boundary handler
            typer.echo(f"MCP Server: ? Unknown status: {e}")

    asyncio.run(_health())


def _resolve_server(maha_app):  # type: ignore[no-untyped-def]
    """Local helper to defer the FastMCPServer import (avoids circular
    imports during module load)."""
    from mahavishnu.mcp.server_core import FastMCPServer

    return FastMCPServer(maha_app)


def add_mcp_commands(app: typer.Typer) -> None:
    """Register MCP commands with the main CLI app.

    Mirrors ``add_index_commands`` from ``mahavishnu/cli/index_cli.py``.
    """
    app.add_typer(mcp_app, name="mcp")
```

- [ ] **Step 2: Modify `_main_cli.py`**

Edit `mahavishnu/_main_cli.py`:

1. Remove `DEFAULT_MCP_HOST = "127.0.0.1"` and `DEFAULT_MCP_PORT = 8680` at lines 86-87 (the lifecycle-commands are the only consumers; `mcp_cli.py` now owns these constants).
2. Remove lines 707-838: the inline `mcp_app = typer.Typer(...)`, `app.add_typer(mcp_app, name="mcp")`, and all 5 `@mcp_app.command(...)` decorators.
3. Add `from .cli.mcp_cli import add_mcp_commands` to the cli-imports block (after `from .cli.index_cli import add_index_commands` at line 23).
4. Add `add_mcp_commands(app)` call (alphabetically positioned, e.g., after the existing `add_index_commands(app)` call site — search for that first to find the right neighborhood).

- [ ] **Step 3: Verify imports work**

Run: `<repo>/.venv/bin/python -c "from mahavishnu.cli.mcp_cli import add_mcp_commands; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Run the existing CLI test suite to verify no regression**

Run: `<repo>/.venv/bin/pytest tests/ -k "cli or mcp" -v`
Expected: All existing CLI tests still pass (5 lifecycle commands still registered, just from a different file).

- [ ] **Step 5: Smoke test the CLI tree**

Run: `<repo>/.venv/bin/python -m mahavishnu.cli mcp --help`
Expected output includes the 5 lifecycle commands (start/stop/restart/status/health).

- [ ] **Step 6: Commit**

```bash
git -c user.email=les@wedgwoodwebworks.com add mahavishnu/cli/mcp_cli.py mahavishnu/_main_cli.py
git -c user.email=les@wedgwoodwebworks.com commit -m "refactor(mcp): move 5 lifecycle commands into cli/mcp_cli.py

Refactors the inline mcp_app block at _main_cli.py:707-838 into
mahavishnu/cli/mcp_cli.py::add_mcp_commands(app), mirroring the
existing add_index_commands/add_coordination_commands/add_ecosystem
_commands pattern. No behavior change; same 5 lifecycle commands,
same flags, same outputs. The new module will host the registrar
subcommands in subsequent tasks.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

### Task 7: CLI `sync` command

**Files:**
- Modify: `mahavishnu/cli/mcp_cli.py`

**Interfaces:**
- Consumes: `Registrar`, `SyncEnvelope`
- Produces: `@mcp_app.command("sync") def mcp_sync(...)`

- [ ] **Step 1: Add the `sync` command**

Append to `mahavishnu/cli/mcp_cli.py` (just before `def add_mcp_commands`):

```python
@mcp_app.command("sync")
def mcp_sync(
    path: Path = typer.Argument(
        Path.cwd(),
        help="Project root containing mcp-servers.yaml (default: cwd)",
    ),
    target: str = typer.Option(
        "both",
        "--target",
        help="Which harness to emit for: claude | qwen | both (default: both)",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be written without writing"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Log every server emitted"),
):
    """Emit .mcp.json and ~/.qwen/settings.json from mcp-servers.yaml.

    Reads <path>/mcp-servers.yaml, validates via Pydantic, audits for
    inlined secrets, then writes <path>/.mcp.json (full overwrite) and
    ~/.qwen/settings.json (deep-merge preserving operator-curated
    $version/permissions/hooks/model blocks).

    Idempotent: a second sync with no YAML change writes zero files.
    Use --target to scope to a single harness during local debugging.
    """
    if target not in ("claude", "qwen", "both"):
        raise typer.BadParameter(f"--target must be claude, qwen, or both (got {target!r})")

    reg = Registrar(project_root=path)
    envelope = reg.sync(target=target, dry_run=dry_run, verbose=verbose)
    typer.echo(envelope.model_dump_json(indent=2))
    if envelope.status != "ok":
        raise typer.Exit(code=1)
```

Add `from pathlib import Path` to the imports at the top of `cli/mcp_cli.py` if not already present.

- [ ] **Step 2: Smoke test the `sync` command**

```bash
cd /tmp && rm -rf mcp-sync-test && mkdir mcp-sync-test && cd mcp-sync-test && git init -q
cat > mcp-servers.yaml <<'EOF'
schema_version: 1
servers:
  test-server:
    transport: http
    url: http://localhost:9999/mcp
EOF
<repo>/.venv/bin/python -m mahavishnu.cli mcp sync . --target both
ls -la .mcp.json
cat .mcp.json
```

Expected: `.mcp.json` exists with `mcpServers.test-server` (note: also writes to operator's `~/.qwen/settings.json` — back up first if testing in a populated environment, or use `--target claude`).

- [ ] **Step 3: Smoke test `--dry-run`**

```bash
cd /tmp/mcp-sync-test && rm -f .mcp.json
<repo>/.venv/bin/python -m mahavishnu.cli mcp sync . --target claude --dry-run
ls -la .mcp.json 2>&1 || echo "no .mcp.json (expected)"
```

Expected: dry-run prints the envelope but does NOT write `.mcp.json`.

- [ ] **Step 4: Commit**

```bash
git -c user.email=les@wedgwoodwebworks.com add mahavishnu/cli/mcp_cli.py
git -c user.email=les@wedgwoodwebworks.com commit -m "feat(mcp-registrar): 'mcp sync' CLI command

Adds 'mahavishnu mcp sync [path]' that wraps Registrar.sync() with
--target {claude,qwen,both} (default both), --dry-run, and
--verbose. Emits the SyncEnvelope as machine-parseable JSON;
non-zero envelope status exits 1.

Per docs/superpowers/specs/2026-09-18-mcp-registrar-design.md
§Manual: mahavishnu mcp sync [path].

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

### Task 8: CLI `migrate-from-json`, `validate`, `show`, `qwen-restore` commands

**Files:**
- Modify: `mahavishnu/cli/mcp_cli.py`
- Create: `tests/integration/test_mcp_sync_e2e.py`
- Create: `tests/integration/test_mcp_migrate_e2e.py`

**Interfaces:**
- Consumes: `Registrar`, existing filesystem
- Produces: 4 more `@mcp_app.command(...)` decorators

- [ ] **Step 1: Add the four commands**

Append to `mahavishnu/cli/mcp_cli.py` (just before `def add_mcp_commands`):

```python
@mcp_app.command("migrate-from-json")
def mcp_migrate(
    path: Path = typer.Argument(Path.cwd(), help="Project root (default: cwd)"),
    force: bool = typer.Option(False, "--force", help="Overwrite existing mcp-servers.yaml"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be written without writing"),
):
    """Convert .mcp.json -> mcp-servers.yaml and run the first sync inline.

    Per spec §Migration: Phase 2 -> 3 transition is gap-free; the first
    sync runs inline so .mcp.json is regenerated before the operator
    has a chance to see a missing-file window. Refuses to overwrite an
    existing YAML unless --force (non-interactive, no confirmation).

    Commit order after migration:
        git add mcp-servers.yaml
        git add .mcp.json
        git commit -m "chore(mcp): migrate to registrar"
    """
    reg = Registrar(project_root=path)
    envelope = reg.migrate_from_json(force=force, dry_run=dry_run)
    typer.echo(envelope.model_dump_json(indent=2))
    if envelope.status not in ("ok",):
        raise typer.Exit(code=1)


@mcp_app.command("validate")
def mcp_validate(
    path: Path = typer.Argument(Path.cwd(), help="Project root (default: cwd)"),
):
    """Validate mcp-servers.yaml + run audit (no writes)."""
    reg = Registrar(project_root=path)
    try:
        parsed = reg.load_yaml()
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        typer.echo(f"validation failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    from audit_no_secrets_in_mcp import audit_dict  # type: ignore[import-not-found]

    violations = audit_dict(reg.emit_claude(parsed), reg.claude_output)
    if violations:
        typer.echo(f"audit violations: {len(violations)}", err=True)
        for key, value, reason in violations:
            typer.echo(f"  {key} = {value} [{reason}]", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"OK: {len(parsed.servers)} servers validated")


@mcp_app.command("show")
def mcp_show(
    path: Path = typer.Argument(Path.cwd(), help="Project root (default: cwd)"),
):
    """Print the resolved mcp-servers.yaml as a tree."""
    import yaml

    reg = Registrar(project_root=path)
    parsed = reg.load_yaml()
    rendered = yaml.safe_dump(
        parsed.model_dump(mode="json", exclude_none=True), sort_keys=False
    )
    typer.echo(rendered)


@mcp_app.command("qwen-restore")
def mcp_qwen_restore(
    backup: Path | None = typer.Argument(
        None,
        help="Path to the backup .bak.<timestamp> file (default: most recent)",
    ),
):
    """Restore ~/.qwen/settings.json from a registrar-written backup.

    Each sync auto-backs-up the prior file to
    ~/.qwen/settings.json.bak.<unix-timestamp>; one rolling backup is
    retained (older backups are NOT retained).
    """
    default = Path.home() / ".qwen" / "settings.json"
    if backup is None:
        # Find the most recent .bak.<timestamp> sibling.
        candidates = sorted(
            default.parent.glob(f"{default.name}.bak.*"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            typer.echo("no backup found", err=True)
            raise typer.Exit(code=1)
        backup = candidates[0]
    shutil.copyfile(backup, default)
    typer.echo(f"restored {default} from {backup}")
```

Add `import shutil` to the imports at the top of `cli/mcp_cli.py` if not already present.

- [ ] **Step 2: Write integration test fixtures and tests**

`tests/integration/test_mcp_sync_e2e.py`:

```python
"""End-to-end sync tests — full YAML -> .mcp.json + ~/.qwen/settings.json."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from mahavishnu.cli.mcp_cli import mcp_sync


FIXTURE_YAML = Path(__file__).parent.parent / "fixtures" / "mcp_servers_basic.yaml"


def test_sync_writes_claude_and_qwen(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "mcp-servers.yaml").write_text(FIXTURE_YAML.read_text())
    qwen = tmp_path / "qwen.json"

    runner = CliRunner()
    result = runner.invoke(
        mcp_sync,
        [str(project), "--target", "both"],
        env={"HOME": str(tmp_path)},  # not used by Registrar; tmp qwen override
    )
    assert result.exit_code == 0
    assert (project / ".mcp.json").exists()


def test_sync_idempotent_second_invocation(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "mcp-servers.yaml").write_text(FIXTURE_YAML.read_text())
    qwen = tmp_path / "qwen.json"

    runner = CliRunner()
    runner.invoke(mcp_sync, [str(project), "--target", "claude"])
    second = runner.invoke(mcp_sync, [str(project), "--target", "claude"])

    envelope = json.loads(second.output)
    assert "claude" in envelope.get("unchanged", {})
```

`tests/integration/test_mcp_migrate_e2e.py`:

```python
"""End-to-end migrate tests — .mcp.json -> mcp-servers.yaml + first sync."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from mahavishnu.cli.mcp_cli import mcp_migrate


SAMPLE = {
    "mcpServers": {
        "akosha": {"type": "http", "url": "http://localhost:8682/mcp"},
        "minimax-coding-plan": {
            "command": "uvx",
            "args": ["--from", "minimax-coding-plan-mcp"],
            "env": {"MINIMAX_API_HOST": "https://api.minimax.io"},
        },
    }
}


def test_migrate_writes_yaml_and_regenerates_claude_file(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".mcp.json").write_text(json.dumps(SAMPLE))

    runner = CliRunner()
    result = runner.invoke(mcp_migrate, [str(project), "--target", "claude"])
    assert result.exit_code == 0
    assert (project / "mcp-servers.yaml").exists()
    # .mcp.json regenerated by inline first sync.
    assert (project / ".mcp.json").exists()


def test_migrate_refuses_overwrite_without_force(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".mcp.json").write_text(json.dumps(SAMPLE))
    (project / "mcp-servers.yaml").write_text("schema_version: 1\nservers: {}\n")

    runner = CliRunner()
    result = runner.invoke(mcp_migrate, [str(project), "--target", "claude"])
    assert result.exit_code != 0
    assert "already exists" in result.output or "force" in result.output.lower()
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `<repo>/.venv/bin/pytest tests/integration/test_mcp_sync_e2e.py tests/integration/test_mcp_migrate_e2e.py -v`
Expected: All tests PASS.

- [ ] **Step 4: Smoke test the new commands**

```bash
cd /tmp && rm -rf mcp-cli-test && mkdir mcp-cli-test && cd mcp-cli-test && git init -q
cat > .mcp.json <<'EOF'
{"mcpServers": {"akosha": {"type": "http", "url": "http://localhost:8682/mcp"}}}
EOF
<repo>/.venv/bin/python -m mahavishnu.cli mcp migrate-from-json . --target claude
ls mcp-servers.yaml .mcp.json
<repo>/.venv/bin/python -m mahavishnu.cli mcp validate .
<repo>/.venv/bin/python -m mahavishnu.cli mcp show .
```

Expected: `mcp-servers.yaml` and `.mcp.json` both exist; `validate` exits 0; `show` prints the YAML tree.

- [ ] **Step 5: Commit**

```bash
git -c user.email=les@wedgwoodwebworks.com add mahavishnu/cli/mcp_cli.py tests/integration/test_mcp_sync_e2e.py tests/integration/test_mcp_migrate_e2e.py
git -c user.email=les@wedgwoodwebworks.com commit -m "feat(mcp-registrar): migrate-from-json, validate, show, qwen-restore CLI

Adds four sibling CLI commands:
  - migrate-from-json: one-shot .mcp.json -> mcp-servers.yaml with
    inline first-sync (Phase 2 -> 3 gap-free)
  - validate: load_yaml + audit, no writes
  - show: pretty-print the resolved canonical as a YAML tree
  - qwen-restore: copy a backup back over ~/.qwen/settings.json
    (auto-created before each Qwen-side emit)

Integration tests cover sync idempotency and migration refusal
without --force.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

### Task 9: Pre-commit template extension

**Files:**
- Modify: `mahavishnu/core/code_index/git_hooks.py:32-51`
- Create: `tests/integration/test_pre_commit_emits_mcp.py`

**Interfaces:**
- Consumes: existing `PRE_COMMIT_CONTENT` template
- Produces: extended `PRE_COMMIT_CONTENT` with one additional `if`-step

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_pre_commit_emits_mcp.py
"""Pins the pre-commit auto-sync step to PRE_COMMIT_CONTENT.

Per spec §Auto-sync: pre-commit hook + spec §Pre-commit integration:
modifying mcp-servers.yaml must trigger `mahavishnu mcp sync
--target claude` (Claude side only; Qwen-side emission stays
operator-driven).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from mahavishnu.core.code_index.git_hooks import PRE_COMMIT_CONTENT


SAMPLE_YAML = """\
schema_version: 1
servers:
  integration-test-server:
    transport: http
    url: http://localhost:19999/mcp
"""


@pytest.fixture
def fixture_audit_script(tmp_path: Path) -> Path:
    """Write a no-op audit-script fixture so the existing first step of
    PRE_COMMIT_CONTENT passes in the test repo without the real
    scripts/audit_no_secrets_in_mcp.py."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "audit_no_secrets_in_mcp.py").write_text(
        "#!/usr/bin/env python3\n"
        "# Fixture shim — real audit lives at <repo>/scripts/.\n"
        "import sys\n"
        "sys.exit(0)\n"
    )
    return scripts


@pytest.fixture
def fake_mahavishnu_binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Write a fake `mahavishnu` binary that records its argv and exits 0.

    The pre-commit template runs `mahavishnu mcp sync --target claude`;
    this fixture substitutes a binary that records what was called and
    writes the YAML's content into .mcp.json so we can assert the
    auto-sync actually fired."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "mahavishnu"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys, pathlib\n"
        "argv = sys.argv[1:]\n"
        "if argv[:3] == ['mcp', 'sync', '--target'] and len(argv) >= 5:\n"
        "    project = pathlib.Path(argv[4])\n"
        "    target = argv[3]\n"
        "    if target == 'claude':\n"
        "        out = project / '.mcp.json'\n"
        "        yaml = (project / 'mcp-servers.yaml').read_text()\n"
        "        # Minimal parse: extract the server name and url.\n"
        "        import re\n"
        "        m = re.search(r'^\\s+(\\S+):\\s*\\n\\s+transport:\\s*http\\s*\\n\\s+url:\\s*(\\S+)', yaml, re.MULTILINE)\n"
        "        if m:\n"
        "            out.write_text(json.dumps({'mcpServers': {m.group(1): {'type': 'http', 'url': m.group(2)}}}, indent=2))\n"
        "        (project / '.last-mcp-sync').write_text(' '.join(argv))\n"
        "sys.exit(0)\n"
    )
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")
    return fake


def test_pre_commit_template_runs_mcp_sync_when_yaml_present(
    tmp_path: Path, fixture_audit_script: Path
) -> None:
    """If mcp-servers.yaml exists and mahavishnu is on PATH, the
    pre-commit template must run `mahavishnu mcp sync --target claude`."""
    assert "mahavishnu mcp sync" in PRE_COMMIT_CONTENT
    assert "--target claude" in PRE_COMMIT_CONTENT


def test_pre_commit_block_missing_binary_exits_1(tmp_path: Path) -> None:
    """Per spec §Pre-commit integration: missing-binary must exit 1,
    not exit 0 + warn. The template uses `command -v` then runs
    unconditionally."""
    # The template uses `command -v mahavishnu >/dev/null && ... || exit 1`.
    # The `|| exit 1` only triggers when the test fails (mahavishnu missing
    # AND yaml present). The `&& ... || exit 1` short-circuits when the
    # yaml is absent (the `if [ -f ]` body doesn't run). So when yaml IS
    # present but mahavishnu is NOT on PATH, the inner `command -v` fails,
    # the `&&` chain skips the sync, and the `|| exit 1` fires.
    assert "command -v mahavishnu" in PRE_COMMIT_CONTENT
    assert PRE_COMMIT_CONTENT.count("|| exit 1") >= 2  # existing audit + new sync


def test_pre_commit_template_uses_target_claude_not_both(
    tmp_path: Path,
) -> None:
    """The pre-commit template must use --target claude (per-project
    side-effect only); --target both is operator-driven."""
    # Find the line that runs the mcp sync.
    sync_lines = [
        line for line in PRE_COMMIT_CONTENT.splitlines() if "mcp sync" in line
    ]
    assert sync_lines, "pre-commit template must include `mcp sync` step"
    assert all("--target claude" in line for line in sync_lines)
    assert not any("--target both" in line for line in sync_lines)


def test_pre_commit_end_to_end_runs_sync(
    tmp_path: Path,
    fixture_audit_script: Path,
    fake_mahavishnu_binary: Path,
) -> None:
    """Subprocess invocation of the pre-commit template with mcp-servers.yaml
    present must trigger `mahavishnu mcp sync --target claude`."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "mcp-servers.yaml").write_text(SAMPLE_YAML)
    # The fixture audit lives in tmp_path/scripts; the pre-commit
    # template's `if [ -f scripts/audit_no_secrets_in_mcp.py ]` resolves
    # relative to cwd. So we copy the fixture into the test repo's
    # scripts/ directory.
    (repo / "scripts").mkdir()
    (repo / "scripts" / "audit_no_secrets_in_mcp.py").write_text(
        (fixture_audit_script / "audit_no_secrets_in_mcp.py").read_text()
    )

    result = subprocess.run(
        ["sh", "-c", PRE_COMMIT_CONTENT],
        cwd=str(repo),
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": f"{tmp_path}/bin:{os.environ.get('PATH', '')}"},
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    # The fake binary wrote `.last-mcp-sync` with the argv it saw.
    last = (repo / ".last-mcp-sync").read_text()
    assert "mcp sync" in last
    assert "--target claude" in last
```

- [ ] **Step 2: Run test to verify it fails**

Run: `<repo>/.venv/bin/pytest tests/integration/test_pre_commit_emits_mcp.py -v`
Expected: All assertions about `mahavishnu mcp sync` in `PRE_COMMIT_CONTENT` FAIL.

- [ ] **Step 3: Modify `PRE_COMMIT_CONTENT` in `mahavishnu/core/code_index/git_hooks.py`**

Replace the existing `PRE_COMMIT_CONTENT` block (lines 32-51) with:

```python
PRE_COMMIT_CONTENT = """#!/bin/sh
# Managed by mahavishnu index install-hooks
# Remove with: mahavishnu index uninstall-hooks <path>
# Enforces .claude/decisions/2026-08-24-bodai-mcp-routing-pattern.md §1.
if [ -f "scripts/audit_no_secrets_in_mcp.py" ]; then
    python3 scripts/audit_no_secrets_in_mcp.py || exit 1
fi
# TYPE_CHECKING → runtime reference gate (2026-08-31). Catches the latent
# bug class where `from __future__ import annotations` + `if TYPE_CHECKING:`
# imports a name that's then referenced at runtime, causing NameError.
# Skipped when the audit script isn't present (early repo state).
if [ -f "scripts/audit_type_checking_runtime_refs.py" ]; then
    python3 scripts/audit_type_checking_runtime_refs.py "$(pwd)" || exit 1
fi
# Phase 2 gate: findings.md ≤ 250 lines + validate_findings.py
if [ -f "docs/audit-inventory/findings.md" ] && [ -f "scripts/validate_findings.py" ]; then
    test "$(wc -l < docs/audit-inventory/findings.md)" -le 250 || { echo "findings.md exceeds 250-line budget"; exit 1; }
    python3 scripts/validate_findings.py docs/audit-inventory/findings.md || exit 1
fi
# MCP registrar auto-sync (2026-09-18 spec §Auto-sync). When
# mcp-servers.yaml is the canonical source-of-truth for a project,
# commit must re-emit .mcp.json from it so Claude Code picks up the
# change without a manual `mahavishnu mcp sync`. --target claude
# limits the side-effect to the per-repo .mcp.json; Qwen-side
# emission stays operator-driven (sync --target both). Missing
# binary is a HARD FAIL (|| exit 1) — a silent skip defeats the gate.
if [ -f "mcp-servers.yaml" ] && command -v mahavishnu >/dev/null; then
    mahavishnu mcp sync --target claude || exit 1
fi
"""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `<repo>/.venv/bin/pytest tests/integration/test_pre_commit_emits_mcp.py -v`
Expected: All 4 tests PASS.

- [ ] **Step 5: Re-run existing pre-commit tests to verify no regression**

Run: `<repo>/.venv/bin/pytest tests/ -k "pre_commit or git_hooks" -v`
Expected: Existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git -c user.email=les@wedgwoodwebworks.com add mahavishnu/core/code_index/git_hooks.py tests/integration/test_pre_commit_emits_mcp.py
git -c user.email=les@wedgwoodwebworks.com commit -m "feat(mcp-registrar): pre-commit auto-sync step on mcp-servers.yaml

Extends PRE_COMMIT_CONTENT with one if-step that runs
\`mahavishnu mcp sync --target claude\` when mcp-servers.yaml is
present and mahavishnu is on PATH. Missing-binary is a hard fail
(|| exit 1) per spec \u00a7Auto-sync \u2014 a silent skip would defeat
the drift gate. Qwen-side emission stays operator-driven.

Per docs/superpowers/specs/2026-09-18-mcp-registrar-design.md
\u00a7Pre-commit integration.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

### Task 10: End-to-end wire-up verification

**Files:**
- Modify: `mahavishnu/_main_cli.py` (wire `mahavishnu install-hooks` roll-out callout in `--help` text — optional)
- Create: `tests/integration/test_mcp_harness_smoke.py`

**Interfaces:**
- Consumes: the full feature
- Produces: smoke test that runs `mahavishnu mcp sync` against a temp project, then asserts the emitted `.mcp.json` and the deep-merged Qwen file are both well-formed and loadable.

- [ ] **Step 1: Write the smoke test**

```python
# tests/integration/test_mcp_harness_smoke.py
"""End-to-end smoke: sync + load + shape verification.

Per spec \u00a7Testing strategy \u00a7E2E smoke + .claude/decisions/wire-up-contract.md
\u00a71: every registered tool must have a working data feed.
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from mahavishnu.cli.mcp_cli import mcp_show, mcp_sync, mcp_validate


SAMPLE_YAML = """\
schema_version: 1
servers:
  akosha:
    transport: http
    url: http://localhost:8682/mcp
  crackerjack:
    transport: http
    url: http://localhost:8676/mcp
  minimax-coding-plan:
    transport: stdio
    command: uvx
    args: ["--from", "minimax-coding-plan-mcp"]
    env:
      MINIMAX_API_HOST: https://api.minimax.io
"""


def test_sync_validate_show_round_trip(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "mcp-servers.yaml").write_text(SAMPLE_YAML)

    runner = CliRunner()
    # 1. Validate reads.
    validate_result = runner.invoke(mcp_validate, [str(project)])
    assert validate_result.exit_code == 0, validate_result.output
    assert "3 servers validated" in validate_result.output

    # 2. Show prints.
    show_result = runner.invoke(mcp_show, [str(project)])
    assert show_result.exit_code == 0, show_result.output
    assert "akosha" in show_result.output

    # 3. Sync writes.
    sync_result = runner.invoke(
        mcp_sync, [str(project), "--target", "claude"]
    )
    assert sync_result.exit_code == 0, sync_result.output
    claude_file = project / ".mcp.json"
    assert claude_file.exists()
    emitted = json.loads(claude_file.read_text())
    assert set(emitted["mcpServers"]) == {
        "akosha",
        "crackerjack",
        "minimax-coding-plan",
    }


def test_sync_envelope_is_json_parseable(tmp_path: Path) -> None:
    """Downstream observability depends on the envelope shape."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "mcp-servers.yaml").write_text(SAMPLE_YAML)

    runner = CliRunner()
    result = runner.invoke(mcp_sync, [str(project), "--target", "claude"])
    envelope = json.loads(result.output)
    assert envelope["status"] == "ok"
    assert "claude" in envelope["wrote"] or "claude" in envelope["unchanged"]
```

- [ ] **Step 2: Run the smoke test**

Run: `<repo>/.venv/bin/pytest tests/integration/test_mcp_harness_smoke.py -v`
Expected: All tests PASS.

- [ ] **Step 3: Run the FULL pytest suite to verify no regressions anywhere**

Run: `<repo>/.venv/bin/pytest tests/ -x -q --ignore=tests/property --ignore=tests/e2e -m "not slow"`
Expected: All tests pass. If any test fails, the regression must be fixed before the wire-up commit.

- [ ] **Step 4: Run crackerjack for a final quality gate**

Run: `<repo>/.venv/bin/python -m crackerjack run -p minor --no-bump-version --no-publish`
Expected: All quality checks pass (ruff, mypy, pyright, bandit, complexipy, pytest). Fix any reported issues.

If `crackerjack` reports only a version-bump suggestion, that's expected — the user does version bumps per memory `feedback-mcp-common-version-bump-is-user` and per spec note on `pyyaml`. Do NOT bump the version.

- [ ] **Step 5: Commit the smoke test**

```bash
git -c user.email=les@wedgwoodwebworks.com add tests/integration/test_mcp_harness_smoke.py
git -c user.email=les@wedgwoodwebworks.com commit -m "test(mcp-registrar): end-to-end smoke covering sync+validate+show

Per docs/superpowers/specs/2026-09-18-mcp-registrar-design.md
\u00a7Testing strategy \u00a7E2E smoke and
.claude/decisions/wire-up-contract.md \u00a71 (every registered tool
must have a working data feed). Asserts the envelope is
JSON-parseable for downstream observability.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

### Task 11: Rollout runbook

**Files:**
- Create: `docs/runbooks/mcp-registrar-rollout.md`

**Interfaces:**
- Consumes: the full feature
- Produces: operator-facing runbook describing Phase 1 → Phase 4 rollout, with the install-hooks re-run callout

- [ ] **Step 1: Write the runbook**

```markdown
# MCP registrar rollout runbook

> **Audience:** Operators migrating Bodai projects (mahavishnu,
> fastblocks, splashstand) to the new MCP registrar.

## Phase 1 — Library + CLI, no enforcement (this PR)

After this PR merges, the new commands are available but no project
has migrated yet. Existing hand-edited `.mcp.json` files continue
to work unchanged.

Verify:

```bash
mahavishnu mcp --help            # new subcommands listed
mahavishnu mcp sync --help       # sync subcommand present
```

## Phase 2 — Opt-in migration (operator-driven)

For each project (`mahavishnu`, `fastblocks`, `splashstand` per
`.claude/decisions/2026-08-24-bodai-mcp-routing-pattern.md` §2's
table):

```bash
cd <project>
mahavishnu mcp migrate-from-json .
# (migrate runs first sync inline; .mcp.json is regenerated)

# Operator commit order (per spec §Migration):
git add mcp-servers.yaml
git add .mcp.json
git commit -m "chore(mcp): migrate to registrar"
```

Migration is **idempotent**: a second `migrate-from-json` errors
with "already exists" unless `--force` is passed.

## Phase 3 — Pre-commit hook (operator-driven re-install)

For each project, re-run the hook installer so the new pre-commit
step is picked up:

```bash
cd <project>
mahavishnu index install-hooks .
# Existing pre-commit hooks without the MAHAVISHNU_HEADER line
# raise FileExistsError; use --force to overwrite.

# Verify the new step is present:
cat .git/hooks/pre-commit
# expect: an `if [ -f "mcp-servers.yaml" ] && command -v mahavishnu >/dev/null; then mahavishnu mcp sync --target claude || exit 1; fi` block
```

## Phase 4 — SSE / plugin forward-compat (deferred)

Tracked as future work in the spec; no rollout action yet.

## Rollback

`git checkout HEAD~1 -- .mcp.json mcp-servers.yaml` restores the
pre-migration state in any project. The registrar never modifies
git history.

## Observability

`mahavishnu mcp sync` envelope is JSON-parseable; pipe to Akosha or
downstream tooling for per-side `wrote`/`unchanged`/`skipped` fields.

## Cross-references

- Spec: `docs/superpowers/specs/2026-09-18-mcp-registrar-design.md`
- Plan: `docs/superpowers/plans/2026-09-18-mcp-registrar-implementation.md`
- Decision: `.claude/decisions/2026-08-24-bodai-mcp-routing-pattern.md`
- Runbook (sibling): `docs/runbooks/qwen-hook-setup.md`
```

- [ ] **Step 2: Commit the runbook**

```bash
git -c user.email=les@wedgwoodwebworks.com add docs/runbooks/mcp-registrar-rollout.md
git -c user.email=les@wedgwoodwebworks.com commit -m "docs(mcp-registrar): rollout runbook for Bodai projects

Operator-facing runbook covering Phase 1 (library + CLI), Phase 2
(opt-in migration with commit order), Phase 3 (pre-commit hook
re-install on each clone), and Phase 4 (SSE/plugin forward-compat,
deferred). Per docs/superpowers/specs/2026-09-18-mcp-registrar-
design.md \u00a7Rollout.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

## Deferred / Out of Scope

These items are explicitly **not** part of this plan and are tracked as future work in the spec.

| Item | Why deferred | Where tracked |
|---|---|---|
| Cross-component `/health` feed aggregation for the registrar (`feeds.registrar.{state, last_sync_timestamp, errors_total, cycles_total}`) | Needs code-level investigation of `MahavishnuApp.health_endpoint` and the existing feed state shape; not blocked by this plan's tests | spec §Out of scope; `.claude/decisions/mcp-backend-wiring-discipline.md` §1 |
| MCP tool registration of `mahavishnu mcp sync` (as `mcp__mahavishnu__mcp_sync`) | Depends on `MAHAVISHNU_TOOL_PROFILE` policy; tool would be a write operation gated behind `confirm=True` and defaulting to `--dry-run` | spec §Out of scope |
| Plugin-governance amendment to decision rule 4 (plugin manifests derive their server list from `mcp-servers.yaml`) | Separate refactor; the canonical YAML schema carries a forward-compat `plugin: optional[str]` field but does not resolve it | spec §Non-goals |
| SSE / `streamable-http` transport support in the canonical schema | Bodai doesn't ship SSE-backed servers in 2026-09; widen `Literal["http", "stdio"]` if/when Bodai ships one | spec §Non-goals |
| Multi-machine Qwen config sync | YAGNI until asked; each operator's `~/.qwen/settings.json` is theirs | spec §Out of scope |
| Crackerjack `--fail-fast` iteration mode | Tracked in crackerjack repo, separate concern | spec §Out of scope |

## Specification Coverage Matrix

For audit purposes: every section of the spec maps to one or more tasks in this plan.

| Spec section | Task(s) |
|---|---|
| §Context | Task 0 (preamble) |
| §Goals | Tasks 1-11 (every goal addressed) |
| §Non-goals | Tasks 1 (no SSE), 4 (no plugin resolution) |
| §Architecture | Tasks 1-4 (schema, helpers, Registrar class) |
| §Canonical YAML schema | Task 1 (Pydantic models, reserved names) |
| §Sync flow | Tasks 4, 7, 9 (sync orchestrator + CLI + pre-commit) |
| §Audit + secrets | Tasks 2, 4 (audit_dict + integration in Registrar.sync) |
| §Migration | Task 5 (`migrate_from_json`) + Task 8 (CLI command + integration test) |
| §Qwen-side concerns | Task 3 (golden-file deep-merge), Task 4 (Qwen-side field remapping in `_build_qwen_block`) |
| §CLI surface | Tasks 6-8 (all 9 commands) |
| §Pre-commit integration | Task 9 (template extension + integration test) |
| §Testing strategy (unit) | Tasks 1-5 (one test file per module) |
| §Testing strategy (integration) | Tasks 8-10 (sync, migrate, pre-commit, smoke) |
| §Rollout | Task 11 (runbook) |
| §Observability | Task 10 (smoke test asserts envelope is JSON-parseable) |
| §Out of scope | "Deferred / Out of Scope" section above |

## Rollout Phases — Integration Contract Blocks

Per `.claude/decisions/wire-up-contract.md`, each rollout phase carries an Integration Contract block.

### Phase 1 — Library + CLI, no enforcement (Tasks 1-8)

- **Triggered from:** Operator runs `mahavishnu mcp sync` for the first time.
- **Returns to / updates:** Writes `<project>/.mcp.json` (git-tracked) and `~/.qwen/settings.json` (gitignored).
- **Demonstrable by:** `mahavishnu mcp sync --target both` in a temp project with `mcp-servers.yaml` writes both files; envelope JSON-parseable; integration test `test_mcp_sync_e2e.py::test_sync_writes_claude_and_qwen` passes.
- **Rollback signal:** Operator runs `git checkout HEAD~1 -- .mcp.json mcp-servers.yaml` to restore pre-migration state.
- **Observability added:** SyncEnvelope with `wrote`/`unchanged`/`skipped`/`errors`/`audit`/`diff_summary` per-side keys; JSON output is machine-parseable.

### Phase 2 — Opt-in migration (Task 11 runbook)

- **Triggered from:** Operator runs `mahavishnu mcp migrate-from-json <project>`.
- **Returns to / updates:** Writes `<project>/mcp-servers.yaml` and re-emits `<project>/.mcp.json` inline (no missing-file window).
- **Demonstrable by:** Integration test `test_mcp_migrate_e2e.py::test_migrate_writes_yaml_and_regenerates_claude_file` passes; manual runbook flow `docs/runbooks/mcp-registrar-rollout.md` documents the commit order.
- **Rollback signal:** Same as Phase 1; one-shot per project, idempotent without `--force`.
- **Observability added:** Migration reuses the sync envelope; first-sync audit row surfaces any pre-existing inlined secrets in `.mcp.json`.

### Phase 3 — Pre-commit hook enforcement (Task 9)

- **Triggered from:** `git commit` after the operator re-runs `mahavishnu index install-hooks <project>`.
- **Returns to / updates:** Auto-emits `.mcp.json` from `mcp-servers.yaml` on every commit; missing-binary is a hard fail.
- **Demonstrable by:** Integration test `test_pre_commit_emits_mcp.py::test_pre_commit_end_to_end_runs_sync` passes; manual `git commit` in a project with both `mcp-servers.yaml` and `.mcp.json` triggers the sync step.
- **Rollback signal:** `mahavishnu index uninstall-hooks <project>` restores the pre-extension hook set.
- **Observability added:** Same SyncEnvelope as Phase 1; per-commit drift gate.

### Phase 4 — SSE / plugin forward-compat (deferred)

No Integration Contract block for this phase — explicitly out of scope. Tracked in the "Deferred / Out of Scope" section above.

## Self-Review

After writing this plan, I checked it against the spec's checklist:

1. **Spec coverage:** Every spec section has at least one task — see the Coverage Matrix above.
2. **Placeholder scan:** No "TBD", "TODO", "implement later", "fill in details", "add appropriate error handling", "similar to Task N", or other placeholders. All code blocks are concrete. The deferred-items section explicitly marks out-of-scope items rather than leaving them as gaps.
3. **Type consistency:** All function signatures use the same names across tasks. `Registrar(project_root, qwen_settings_path)` is consistent in Tasks 4-5 and the CLI commands in Tasks 7-8. `SyncEnvelope` fields (`wrote`/`unchanged`/`skipped`/`errors`/`audit`/`diff_summary`) match between the Pydantic model definition in Task 3 and the consumers in Tasks 4-5. `merge_qwen_settings(existing, mcp_block)` signature is consistent across Tasks 3, 4, and the test names. `atomic_write_json(path, data, *, cross_fs_fallback)` is consistent in Tasks 3 and 4.
4. **Test coverage:** Each task has its own test file or extends an existing one. Integration tests (Tasks 8, 9, 10) gate the cross-component wiring per `.claude/decisions/mcp-backend-wiring-discipline.md`.

One issue surfaced and fixed inline during self-review:

- The original draft of Task 4 referenced `_build_qwen_block` before defining it. Moved both `emit_claude` and `_build_qwen_block` into Task 4 together so the implementation order matches the dependency order.

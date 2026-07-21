---
status: draft
role: canonical
topic: lifecycle
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
blocks_on: []
---

# Frontmatter Validator Wiring — Design (2026-07-16)

## Goal

Wire Mahavishnu's `scripts/validate_document_frontmatter.py` into the
Crackerjack ecosystem so the validator:

1. Exposes a `crackerjack docs validate` CLI subcommand.
1. Exposes an MCP tool on the existing Crackerjack MCP server.
1. Runs during `crackerjack run`'s `run_documentation_cleanup_phase`.

No pre-commit hook. Single source of truth: the validator remains
in Mahavishnu (`scripts/validate_document_frontmatter.py`); Crackerjack
imports it.

## Context (current state)

The validator lives in `mahavishnu/scripts/validate_document_frontmatter.py`
(~750 lines, 21 pytest tests passing). It supports:

- `--strict`, `--allow-nonstandard`, `--validate-links`, `--json` modes.
- A `LITE` schema for `.claude/decisions/` (no `superseded_by` / `blocks_on`).
- Per-store exclusions (`.archive/`, `docs/plans/drafts/`, `PLAN_INDEX.md`).

Crackerjack (`/Users/les/Projects/crackerjack`) currently exposes:

- A `docs` Typer CLI group at `crackerjack/cli/docs_cli.py` (commands:
  `init`, `build`, …).
- An MCP server with tool modules under `crackerjack/mcp/tools/` (each
  module exports `register_X_tools(mcp_app)`).
- A doc cleanup phase at `crackerjack/core/phase_coordinator.py:1152`
  (`run_documentation_cleanup_phase`) gated by `options.cleanup_docs`.

The two repos share the Bodai `pyproject.toml` pattern (`>=3.13`,
hatchling, FastMCP, mcp-common). Mahavishnu is already a dev dependency
of Crackerjack (`crackerjack/services/...` imports from `mahavishnu`).
The validator can be imported as `mahavishnu.scripts.validate_document_frontmatter`
once exposed via the package, OR Crackerjack can invoke the script as
a subprocess to keep dependencies one-directional (Mahavishnu does not
import from Crackerjack).

## Architecture

The validator script becomes a service in Crackerjack. The service wraps
the validator CLI as a subprocess (one-directional dependency). Crackerjack
gains:

| New surface | Path | Type |
|-------------|------|------|
| `crackerjack docs validate` | `crackerjack/cli/docs_cli.py` (extend) | Typer subcommand |
| `crackerjack_doc_frontmatter_validate` | `crackerjack/mcp/tools/doc_tools.py` (new) | MCP tool |
| `crackerjack.services.FrontmatterValidator` | `crackerjack/services/frontmatter_validator.py` (new) | Service wrapper |
| Phase hook | `crackerjack/core/phase_coordinator.py:run_documentation_cleanup_phase` (extend) | Pre-cleanup step |

The wrapper executes `python -m mahavishnu.scripts.validate_document_frontmatter`
as a subprocess and parses its JSON output. Result dataclass:

```python
@dataclass
class FrontmatterValidationResult:
    success: bool
    errors: list[dict[str, str]]   # file, line, code, message
    warnings: list[dict[str, str]]
    files_scanned: int
    duration_ms: int
    error_count: int
    warning_count: int
```

Wrapper contract:

```python
class FrontmatterValidator:
    def __init__(
        self,
        pkg_path: Path | None = None,
        timeout_seconds: int = 120,
    ) -> None: ...

    def validate(
        self,
        strict: bool = False,
        allow_nonstandard: bool = True,
        validate_links: bool = False,
        store: str | None = None,
    ) -> FrontmatterValidationResult: ...

    def validate_or_raise(self, **kwargs: t.Any) -> FrontmatterValidationResult:
        # Calls validate(); raises FrontmatterValidationError if errors>0
        ...
```

The wrapper uses `secure_subprocess.run` (existing Crackerjack utility)
to invoke the validator. Working directory defaults to `pkg_path` so the
validator discovers the right stores.

## Components

### 1. `crackerjack/services/frontmatter_validator.py` (new, ~120 lines)

- `FrontmatterValidationResult` dataclass (above).
- `FrontmatterValidator` class with `validate()` and `validate_or_raise()`.
- `FrontmatterValidationError(Exception)` with `.result` attribute.
- Reuses `crackerjack.services.secure_subprocess.run`.

### 2. `crackerjack/cli/docs_cli.py` (extend)

Add a `validate` Typer subcommand:

```python
@app.command()
def validate(
    strict: bool = typer.Option(False, "--strict", help="Treat warnings as errors."),
    store: str | None = typer.Option(None, "--store", help="Limit scan to a single store."),
    validate_links: bool = typer.Option(False, "--validate-links", help="Also check cross-references."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of human-readable."),
    pkg_path: Path = typer.Option(Path.cwd(), "--path", help="Repo root."),
) -> None:
    """Validate YAML frontmatter on docs/, .claude/decisions/, etc."""
    ...
```

Subcommand lives under the existing `crackerjack docs` Typer group so it
shows up in `crackerjack docs --help`. Exit code mirrors the validator:
0 on success, 1 on errors, 2 on warnings (when `--strict`).

### 3. `crackerjack/mcp/tools/doc_tools.py` (new, ~80 lines)

Mirrors the `register_X_tools` pattern used by sibling modules
(`utility_tools.py`, `core_tools.py`):

```python
def register_doc_tools(mcp_app: t.Any) -> None:
    _register_frontmatter_validate_tool(mcp_app)


async def crackerjack_doc_frontmatter_validate(
    strict: bool = False,
    allow_nonstandard: bool = True,
    validate_links: bool = False,
    store: str | None = None,
) -> str:
    """Validate YAML frontmatter across the docs/ tree. Returns JSON."""
    ...
```

Wired into the server via `crackerjack/mcp/tools/__init__.py`:

```python
from .doc_tools import register_doc_tools  # NEW
# ... and add to __all__
```

### 4. `crackerjack/core/phase_coordinator.py` (extend)

Inside `run_documentation_cleanup_phase`, **before** the existing
`cleanup_service.cleanup_documentation()` call, add:

```python
from crackerjack.services.frontmatter_validator import (
    FrontmatterValidator,
    FrontmatterValidationError,
)

validator = FrontmatterValidator(console=self.console, pkg_path=self.pkg_path)
try:
    result = validator.validate(allow_nonstandard=True)
except FrontmatterValidationError as exc:
    self.session.fail_task(
        "documentation_cleanup",
        f"frontmatter validation failed: {exc.result.error_count} errors",
    )
    return False

self.session.track_task(
    "frontmatter_validation",
    f"Frontmatter: {result.error_count} errors, {result.warning_count} warnings",
)
```

The phase continues on success; cleanup runs as before. The
`frontmatter_validation` task is added to the session log so it
appears in the crackerjack status output alongside other phase tasks.

This means `crackerjack run --cleanup-docs` automatically runs
validation first. Users who don't pass `--cleanup-docs` keep their
current behavior — validation is opt-in via the existing flag.

## Data flow

`crackerjack run --cleanup-docs`:

```
phase_coordinator.run_documentation_cleanup_phase
  └─ FrontmatterValidator.validate(allow_nonstandard=True)
       └─ secure_subprocess.run(["python", "-m",
            "mahavishnu.scripts.validate_document_frontmatter",
            "--allow-nonstandard", "--json"])
            └─ Mahavishnu validator scans 6 stores
            └─ returns JSON {errors, warnings, files_scanned, ...}
       └─ parses JSON → FrontmatterValidationResult
  └─ if errors>0: fail_task("documentation_cleanup", ...)
  └─ else: cleanup_service.cleanup_documentation(dry_run=...)
```

CLI invocation: `crackerjack docs validate --strict --store docs/plans/`
runs the same subprocess with `--strict --store docs/plans/` and prints
a Rich table or JSON.

MCP invocation: `mcp__crackerjack__crackerjack_doc_frontmatter_validate`
returns the parsed `FrontmatterValidationResult` as JSON.

## Error handling

- Subprocess timeout (default 120s): raise `FrontmatterValidationError`
  with `result=None` and `.reason="timeout"`.
- Non-zero exit but valid JSON: return result with `success=False`,
  populated error/warning lists.
- Crashed subprocess (no JSON): raise `FrontmatterValidationError`
  with `result=None` and `.reason="crash"` carrying stderr.
- Phase hook: convert `FrontmatterValidationError` to phase failure,
  set `documentation_cleanup` task as failed.

When `--strict` is used, warnings count as errors and exit code 1.
Default mode (`--allow-nonstandard`) is permissive — same as today.

## Testing

Three layers of tests, all in `crackerjack/tests/`:

1. **`test_frontmatter_validator.py`** (unit, ~200 lines)
   - Mock `secure_subprocess.run` to return canned JSON.
   - Cover: success, errors-only, warnings-only, timeout, crash,
     `--strict` exit code, `--store` flag pass-through.
1. **`test_doc_cli.py`** (CLI, ~100 lines)
   - Use `typer.testing.CliRunner` against `crackerjack docs validate`.
   - Cover: default flags, `--json`, `--strict`, `--store`, missing
     repo path.
1. **`test_phase_coordinator_integration.py`** (integration, ~120 lines)
   - Use a fixture that synthesizes a tmp repo with one valid and one
     invalid frontmatter file.
   - Verify `run_documentation_cleanup_phase` fails when validator
     returns errors, succeeds when clean.

Mahavishnu's existing 21 pytest tests in
`mahavishnu/tests/unit/test_document_frontmatter.py` continue to gate
the validator itself. Crackerjack tests only verify the wrapper, not
the validator's logic.

## Dependencies

Crackerjack already depends on Mahavishnu (per `crackerjack/services/`
imports). No new dependencies. The wrapper invokes the validator as
a subprocess to keep the dependency direction one-way
(`crackerjack` → `mahavishnu`); Mahavishnu never imports from Crackerjack.

If the validator script is not installed as a module, the wrapper
falls back to running the raw script via `python /Users/les/Projects/mahavishnu/scripts/validate_document_frontmatter.py`
(discovered via `crackerjack.services.tool_filter` or a hard-coded
fallback path). Document the fallback in the service docstring.

## Rollout

1. Implement wrapper + CLI + MCP + phase hook in Crackerjack
   (single PR, ~3 commits: service, CLI/MCP, phase hook + tests).
1. Run `crackerjack docs validate` against the Crackerjack repo itself
   (currently has no frontmatter on docs — expect ~N warnings as legacy
   docs are surfaced for triage). Decision: gate rollout on
   Crackerjack docs being clean, OR ship without gating and fix
   warnings in a follow-up.
1. Tag a Crackerjack release (current: 0.68.4 → 0.69.0 minor bump).
1. Update `mahavishnu/docs/schemas/document-frontmatter-v1.md` to
   reference the new Crackerjack surface (1-line addition).

## Out of scope

- Frontmatter auto-fix (write changes to disk). Validator is read-only.
- Pre-commit hook integration (explicitly excluded per user direction).
- A new dedicated MCP server. Reuse existing Crackerjack MCP server.
- P7 cross-repo normalization. See companion plan
  `docs/superpowers/plans/2026-07-16-p7-cross-repo-playbook.md`
  (separate wave, separate design).

## P7 cross-repo expansion (companion decision)

Per user direction, P7 runs in two waves:

- **Wave P7.A** (template repo: session-buddy):
  - Apply full Plan-Lifecycle-Unification playbook to session-buddy.
  - Produce `docs/plans/2026-07-16-p7-cross-repo-playbook.md`
    capturing per-repo gotchas (file conventions, vocab extensions
    needed, links to other repos).
- **Wave P7.B** (parallel fan-out, 4 repos):
  - Apply playbook to dhara, crackerjack, akosha, oneiric in parallel.
  - Each subagent reads the playbook and runs the same workflow.
  - Coordinator validates + commits per-repo.

P7.A must complete first; P7.B is gated on P7.A producing the
playbook. P7.B fan-out runs as a single Workflow tool invocation.

## Risks

- **Mahavishnu validator module path**: must be importable as
  `mahavishnu.scripts.validate_document_frontmatter`. If not, the
  wrapper falls back to running the raw script.
- **Phase ordering**: frontmatter validation runs before doc cleanup.
  If a user has docs that intentionally violate frontmatter, they
  need to either fix them or skip the cleanup phase. Document in
  `crackerjack docs --help`.
- **Cross-platform subprocess**: validator uses Python 3.13; Crackerjack
  targets the same. No platform-specific code paths.

## Open questions

None. Both architecture decisions (crackerjack integration shape and
P7 scope/sequencing) resolved via AskUserQuestion on 2026-07-16.

---
status: active
role: canonical
date: 2026-08-25
last_reviewed: 2026-08-29
superseded_by: null
topic: bodai-cli-contract
---

# Bodai CLI Contract

Established by the 2026-08-25 ultracode CLI audit
(`docs/plans/2026-08-25-bodai-cli-audit-implementation.md`).
Renamed to `OneiricCLIBase` on 2026-08-26 (oneiric commit `f76d65b`); the
contract applies to the renamed symbol going forward. The `BodaiCLIBase`
name is retained as a back-compat alias in `oneiric.cli.base` through
the 0.19.x release line; it is removed in 0.20.

## Decision rule

### 1. Every Core 7 CLI extends `OneiricCLIBase`

Each Core 7 component CLI is a `typer.Typer` instance that extends
`oneiric.cli.base.OneiricCLIBase`. Subclasses provide:

- `version` subcommand (auto-registered from the base)
- `doctor` subcommand (calls subclass's `_doctor_checks()`)
- `health` subcommand (calls subclass's `_health_probe()`)
- `--json` global flag
- `ExitCode` enum (`SUCCESS=0`, `ERROR=1`, `USAGE_ERROR=2`,
  `UNAVAILABLE=3`, `PERMISSION_DENIED=4`, `TIMEOUT=124`)

Do **not** `from oneiric.cli.base import BodaiCLIBase` in new code —
use `OneiricCLIBase`. The `BodaiCLIBase` alias is a 0.19.x back-compat
shim and will be removed when oneiric 0.20 ships. Mahavishnu itself
still imports the alias (pre-rename code) and works against installed
`oneiric==0.19.0`; that import will fail once oneiric 0.20 is
installed in the same venv.

### 2. Lifecycle-bearing repos use `MCPServerCLIFactory.register_lifecycle_handlers`

crackerjack, dhara, session-buddy use lifecycle verbs (`start`, `stop`,
`status`, `health`). Construct:

```python
factory = MCPServerCLIFactory(component_name="...")
app = OneiricCLIBase(component_name=..., version_provider=...)
factory.register_lifecycle_handlers(app)
```

### 3. Each Core 7 registers in `bodai.apps` entry-point group

In `pyproject.toml`:

```toml
[project.entry-points."bodai.apps"]
<repo> = "<module>:<app>"
```

This lets the `bodai` umbrella CLI discover every Core 7 app via
`importlib.metadata.entry_points(group="bodai.apps")`. The entry-point
key is the canonical repo name (e.g. `mahavishnu`, not
`mahavishnu-app`). Module attribute is the `typer.Typer` instance —
typically named `app`.

### 4. Each Core 7 implements `_doctor_checks()` and `_health_probe()`

No vacuous implementations. Per-repo CI tests assert at least one check
is returned and at least one health probe runs.

## Enforcement

- Pre-commit hook: `scripts/audit_no_secrets_in_mcp.py` (existing)
- CI: `.github/workflows/umbrella-ci.yml` (umbrella job, bodai repo)
- Per-repo CI: existing pytest + `OneiricCLIBase`-specific tests

## Migration note (2026-08-26)

`OneiricCLIBase` rename applied to all 6 Core 7 repos (mahavishnu,
dhara, session-buddy, akosha, crackerjack, oneiric). The
`from oneiric.cli.base import BodaiCLIBase` line in
`mahavishnu/cli/base.py` is the only remaining reference; it works
today because installed `oneiric==0.19.0` still exports the alias.
Track the migration in this contract until that import line is
updated to `OneiricCLIBase`.

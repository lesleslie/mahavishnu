---
date: 2026-09-19
status: complete
role: implementation
topic: crackerjack-private-index-publishing
last_reviewed: 2026-10-15
superseded_by: null
---

# crackerjack: configurable private-index publishing

## Context

Today, crackerjack's publish path is hardcoded to PyPI: `uv publish --trusted-publishing always` or `uv publish` with `UV_PUBLISH_TOKEN`, both targeting `https://upload.pypi.org/legacy/`. There is no CLI flag, env var, or settings key to redirect to a private package index — so any proprietary or private-org project (like mdinject publishing to its own GitLab PyPI registry) cannot use `crackerjack -p minor` and must drop down to raw `uv publish` from CI.

The user wants this fixed at the crackerjack level so it works as a first-class feature in the publish stage. Specifically, three config layers:

1. **CLI flag** — `--publish-url <URL>` on the `crackerjack -p` / `crackerjack run` commands
2. **Oneiric settings** — `publish_url` in `settings/crackerjack.yaml` (or `local.yaml`) so a repo can default to its own index without per-invocation flags
3. **Env var** — `CRACKERJACK_PUBLISH_URL` for CI/CD contexts

The Mahavishnu `ecosystem.yaml` per-repo `publish_url` (so `mahavishnu pool route_execute` can pass the right flag when dispatching `crackerjack -p minor` for a specific repo) is **explicitly out of scope** for this change — that requires a net-new dispatcher in Mahavishnu, not a small crackerjack extension. It is called out as a follow-up at the end of this plan.

This change is for **crackerjack only** (a Bodai project), so:
- Pre-1.0 merge policy: commit directly to `main` (no PR)
- Never bump version (user does via `crackerjack run -p minor` per memory `feedback-mcp-common-version-bump-is-user`)
- Never push without explicit approval (memory `feedback-bodai-push-is-user-controlled`)
- No pre-commit hooks (memory `no-bodai-pre-commit-hook`)

## Design

### Config resolution order (highest → lowest)

1. CLI flag `--publish-url <URL>` (one-off override)
2. Env var `CRACKERJACK_PUBLISH_URL` (CI override)
3. Oneiric settings key `publishing.publish_url` (repo-level default)
4. Unset → no `--publish-url` arg passed to `uv publish` (existing PyPI behavior, unchanged)

### Auth interaction

`uv publish` rejects `--publish-url` combined with `--trusted-publishing always` (mutually exclusive — OIDC is PyPI-only). When `publish_url` is set, `_execute_publish` falls back to token auth: `UV_PUBLISH_TOKEN` from keyring or env, same path currently used for the non-trusted branch. This means:

- **PyPI (no `publish_url`)**: trusted-publishing path when available, else token path — unchanged
- **Private index (`publish_url` set)**: always token path; OIDC trusted publishing not used
- **GitLab PyPI CI**: `CI_JOB_TOKEN` flows through `UV_PUBLISH_TOKEN` exactly like today's PyPI token branch — no auth-model changes needed

### Files to modify (crackerjack only)

**Config plumbing** (4 files):

1. `crackerjack/config/settings.py:55` — `class PublishSettings(OneiricMCPConfig)`:
   - Add `publish_url: str | None = None`

2. `crackerjack/models/config.py:151-171` — `class PublishConfig` dataclass (the runtime one — used by `api.py:13,335,351`, `config_adapter.py:15,90`, `__main__.py:300,818,846`):
   - Add `publish_url: str | None = None` field
   - Update `from_settings(settings: PublishSettings)` to pass `publish_url=settings.publish_url`

3. `crackerjack/models/pydantic_models.py:118-137` — `class PublishConfig` Pydantic mirror (parallel/legacy, used by `WorkflowOptionsPydantic` and `from_settings`):
   - Add `publish_url: str | None = None` field
   - Update `from_settings` to match

4. `crackerjack/managers/publish_manager.py`:
   - `__init__` (~line 63-87): accept `publish_url: str | None = None`, store on `self`
   - `_execute_publish` (~line 744-756): add third branch — when `self.publish_url` is set, build `cmd = ["uv", "publish", "--publish-url", self.publish_url]` and use the token-auth env path (skip OIDC)
   - `_handle_dry_run_publish` (~line 740): when `publish_url` is set, include `--publish-url <URL>` in the dry-run print so users see what would happen

**CLI surface** (2 files):

5. `crackerjack/cli/options.py:293-305` — next to the existing `--publish` typer option, add:
   ```python
   "publish_url": typer.Option(
       None,
       "--publish-url",
       envvar="CRACKERJACK_PUBLISH_URL",
       help=(
           "PEP 517 repository URL for uploads (overrides PyPI default). "
           "Example: https://gitlab.com/api/v4/projects/<id>/packages/pypi/upload. "
           "When set, OIDC trusted publishing is disabled and token auth is used."
       ),
   ),
   ```
   The `envvar=` binding makes Typer auto-read `CRACKERJACK_PUBLISH_URL` when the flag is absent — gives us CLI flag + env var resolution for free.

6. `crackerjack/__main__.py:300, 818, 846` (call sites that build `PublishConfig`) — pass the new `publish_url=options.publish_url` kwarg through to `PublishConfig.from_settings` or wherever `PublishConfig(...)` is instantiated. The exact plumbing depends on how `options` reaches those sites; plan is to thread the kwarg through wherever `PublishConfig` is constructed.

**Settings defaults** (2 files):

7. `settings/crackerjack.yaml` — under the existing `publishing:` block (or wherever the other `PublishSettings` keys live), add `publish_url: null`. Match the existing nesting convention — if `publish_version`/`bump_version`/`all_workflow` are flat, follow that; if they live under `publishing:`, follow that. Plan defers to the existing convention.

8. `settings/local.yaml.example` — add a commented example showing `publish_url: "https://gitlab.com/api/v4/projects/.../packages/pypi/upload"` so users discover the feature.

**Tests** (2 files):

9. `tests/unit/managers/test_publish_manager_pyi_auth.py` — extend the fixture at line 21-26 to pass `publish_url="https://example.test/pypi"`; add a new test asserting `_execute_publish` builds `["uv", "publish", "--publish-url", "https://example.test/pypi"]` (and not the trusted-publishing flag) when `publish_url` is set. Mirror test for the dry-run path.

10. `tests/test_models_comprehensive.py:69-73` — `test_publish_config_defaults` adds `assert config.publish_url is None`.

**Docs** (1 file, small):

11. `docs/` — search for the existing "publish" / "PyPI" doc page; add a section titled "Private package indexes" with one paragraph + the install command example. If no dedicated publish doc exists, add a short `docs/publish-url.md` and link it from the README.

### Out of scope (called out for follow-up)

- **Mahavishnu ecosystem.yaml dispatch**: `mahavishnu/git_hook_handlers.py:29-34, 92-107` has only a hardcoded `_GIT_EVENT_COMMANDS` dict calling `crackerjack run --fast-hooks-only`. There is no existing `crackerjack -p minor` dispatcher; per the Explore agent, building one with per-repo `publish_url` synthesis from `settings/ecosystem.yaml` would be net-new code in `mahavishnu/adapters/` (or a new `mahavishnu/cli/repo_cli.py` command). Separate plan/worktree, separate review.

- **mdinject CI migration to use the new crackerjack feature**: depends on this PR landing + a crackerjack release that includes it. Once shipped, the existing `.gitlab-ci.yml` `release` job (commit `4d99d20`) can swap its raw `uv publish` step for `uv run crackerjack -p minor --publish-url "$CI_API_V4_URL/projects/$CI_PROJECT_ID/packages/pypi/upload"`. Trivial follow-up, but blocked on the crackerjack release.

## Verification

1. **Unit tests pass**:
   ```bash
   cd /Users/les/Projects/crackerjack
   uv run pytest tests/unit/managers/test_publish_manager_pyi_auth.py tests/test_models_comprehensive.py -v
   ```
   Expect: existing tests still pass + the new `--publish-url` branch test passes.

2. **CLI flag shows up**:
   ```bash
   cd /Users/les/Projects/crackerjack
   uv run crackerjack --help | grep -A2 publish-url
   uv run crackerjack -p --help | grep -A2 publish-url
   ```
   Expect: help text matches what was added in `cli/options.py`.

3. **Env var flows through**:
   ```bash
   cd /Users/les/Projects/crackerjack
   CRACKERJACK_PUBLISH_URL=https://example.test uv run crackerjack -p minor --dry-run 2>&1 | grep publish-url
   ```
   Expect: dry-run prints `Would publish package to https://example.test` with `--publish-url https://example.test` in the would-be command.

4. **Settings YAML flows through** (write `publishing.publish_url: https://example.test` to a scratch `local.yaml`, run the same dry-run, confirm it overrides nothing else but is picked up).

5. **CLI flag beats env var**: pass both `--publish-url https://cli.test` and `CRACKERJACK_PUBLISH_URL=https://env.test`; expect CLI value to win.

6. **Existing PyPI behavior unchanged**: `uv run crackerjack -p patch --dry-run` (no flag, no env, no setting) → must still print `Would publish package to PyPI` with no `--publish-url` in the command.

7. **Full crackerjack run** (sanity): `uv run crackerjack run --fast-hooks-only` in `crackerjack/` itself; expect all hooks green and no regressions.

8. **Cross-repo smoke**: tag a scratch repo at `v0.0.1-test` with a configured `publish_url`, run `uv run crackerjack -p patch --publish-url <url>` from there; confirm `uv publish` is invoked with the flag (the upload itself can fail — we just want to see the command constructed right).

## Critical files (summary)

| File | Why |
|---|---|
| `crackerjack/config/settings.py:55` | `PublishSettings` — root of the new field |
| `crackerjack/models/config.py:151-171` | Runtime `PublishConfig` dataclass (dataclass wins at runtime per Explore) |
| `crackerjack/models/pydantic_models.py:118-137` | Parallel Pydantic mirror — must stay in sync |
| `crackerjack/managers/publish_manager.py:744-756` | Where `["uv", "publish", ...]` is built; add third branch + dry-run print |
| `crackerjack/cli/options.py:293-305` | Add `--publish-url` next to `--publish`; `envvar=` binding gives env var support |
| `crackerjack/__main__.py:300,818,846` | Three call sites that build `PublishConfig`; thread the kwarg through |
| `settings/crackerjack.yaml` | Add `publish_url: null` to the relevant block |
| `settings/local.yaml.example` | Document the new key |
| `tests/unit/managers/test_publish_manager_pyi_auth.py:21-26` | Extend fixture + add branch test |
| `tests/test_models_comprehensive.py:69-73` | `test_publish_config_defaults` extended |
| `docs/` (publish-url.md or existing page) | One-paragraph "Private package indexes" section |

## Constraints

- Bodai pre-1.0: commit directly to `main`, no PR
- Do NOT bump `pyproject.toml` version — user does
- Do NOT `git push` — wait for explicit approval
- No pre-commit hook bypass needed (Bodai uses crackerjack for CI, not pre-commit)
- Author email: `les@wedgwoodwebworks.com` (not `.local`)
- Commit trailer: `Co-Authored-By: Claude Code <noreply@anthropic.com>`
- Bundle only the files modified — no dirty-tree bundling

## Out of scope (explicit)

- Mahavishnu `ecosystem.yaml` per-repo `publish_url` synthesis + new dispatcher for `crackerjack -p minor`
- mdinject CI migration to the new crackerjack feature (blocked on this PR + a release)
- `crackerjack --publish-test` flag — still a stub; separate work
- Removing stale `.github/workflows/` files in mdinject — separate cleanup

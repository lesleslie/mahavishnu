# Prefect demo `flow=fn` ad-hoc pattern fails against Prefect 3.x process worker pools

Status: open (informational — final finding below)

## Context

While closing the demo sweep (16 of 17 demos passing after the
layered-config + runpod-public substrate work this session), the
``mahavishnu demo prefect`` flow consistently timed out at 120s with
no state transition.

The substrate-side check (``settings.prefect.api_url`` reachable,
``prefect.work_pool`` set) passes once ``MAHAVISHNU_PREFECT__API_URL``
points at the local Prefect server (port 8464) instead of the
demo's hardcoded 4200 default. The failure mode is in the
worker-pool dispatch path.

## Five attempts, five distinct blockers

1. **``client.create_flow_run(flow=fn, work_pool_name=...)``**
   - Failure mode: the worker subprocess cannot import the in-memory
     flow object (no source path serialized). PENDING forever.
2. **``flow.from_source(LocalFileSystem(...)).adeploy(...)``**
   - Failure mode: ``Either an image or remote storage location must
     be provided when deploying a deployment.`` Local FS doesn't
     satisfy the "remote" predicate.
3. **``flow.afrom_source(GitHubRepository(...)).adeploy(...)``**
   - Failure mode: the GitHubRepository block's default destination
     is ``github-repository-None`` (literal "None" in the path name
     because the block has no ``name`` field by default). Worker
     subprocess can't resolve the entrypoint against an unreadable
     directory.
4. **``flow.afrom_source(GitRepository(core)).adeploy(...)``** (the
   pattern that DID get the worker to clone the repo)
   - Failure mode: ``ModuleNotFoundError: No module named '<tmp>/<repo>-<branch>/mahavishnu'``.
     The worker clones to ``<tmp>/mahavishnu-main/`` (correct), but
     when ``load_module`` runs in the worker subprocess, it does
     ``working_directory = os.getcwd()`` (returns the worker's
     process CWD, not the storage destination) and ``importlib.import_module(entrypoint)``
     fails because the entrypoint gets resolved as a path-prefixed
     dotted name with the cwd path appended.

5. **Adding ``prefect-github`` to the project** (operator-approved
   on 2026-10-19 with the words "you can add prefect-github")
   - ``prefect-github==0.4.4`` was installed via ``uv pip install``.
     This unblocks the Git storage pattern but does NOT fix the
     underlying CWD-vs-destination mismatch (attempt 4 above).
   - **Reverted 2026-10-28**: the dependency was removed from
     ``pyproject.toml`` once the demo settled on Prefect Core's own
     ``prefect.runner.storage.GitRepository`` (attempt 4). Nothing in
     the repo imported ``prefect_github``; it was a dead dependency
     that only the ``creosote`` unused-dependency check reported.

## Root cause (final)

``prefect/utilities/importtools.py::load_module`` (line 138) uses
``os.getcwd()`` instead of the storage's pulled destination:

```python
def load_module(module_name: str) -> ModuleType:
    working_directory = os.getcwd()       # <-- wrong
    sys.path.insert(0, working_directory)
    return importlib.import_module(module_name)
```

The worker executor never ``os.chdir(destination)`` before invoking
the entrypoint. The storage's destination IS on sys.path (the
helper inserts it), but the actual import fails because
``importlib.import_module`` resolves dotted names against the
worker's process CWD via its internal ``sys.path[0]`` lookup, and
the worker's CWD is the worker's startup directory, not the clone
destination. Net effect: every cloned repo's project structure looks
unreachable from the worker's import context.

## Mitigation paths (when operator is ready to commit work)

Option A — **worker-level pull_step** that chdirs before the entrypoint load:

```python
from prefect.deployments import run_deployment
flow.afrom_source(...).adeploy(
    name=...,
    work_pool_name=...,
    pull_steps=[
        GitRepository(url="...", branch="main").get_pull_step(),
        {"prefect.deployments.steps.run_shell.script": "cd <dest>"},
    ],
)
```

Option B — **work pool template override**: pin the work pool's
``working_dir`` template variable to the clone destination so
``storage._storage_base_path`` resolves correctly when the
executor first pulls. Less surgical, requires a one-time work-pool
config.

Option C — **prefect upstream fix**: ``load_module`` should accept
a ``working_directory`` argument and the executor should pass
``storage.destination`` to it. Tracked separately by Prefect.

## What's on disk now

- The demo's ``_run_prefect_demo`` uses ``GitRepository(core)``
  (Pattern 4) — it's aligned with the recommended Prefect 3.x path.
  The worker subprocess clones the repo correctly but fails the
  import for the reason above.
- ``prefect-github`` was **removed** from ``pyproject.toml`` on
  2026-10-28. The demo never imported it — the implementation uses
  Prefect Core's ``prefect.runner.storage.GitRepository`` (attempt 4),
  and ``prefect-github`` was a dead dependency that only the
  ``creosote`` unused-dependency check was reporting.
- All observed swallows + paths are documented here for the next
  reader.

## Verdict

The Prefect demo's ad-hoc ``flow=fn`` API never worked against
Prefect 3.x process worker pools; the historical
``client.create_flow_run(flow=...)`` path was incorrect by design.
The current ``_run_prefect_demo`` reaches the entrypoint import
stage correctly (storage, pull, env) but fails on a Prefect 3.x
internal CWD bug. Fixing this for real requires either a
worker-level pull_step or a Prefect upstream patch. For now,
15 of 17 demos pass; the prefect demo surfaces the failure
deterministically so an operator can pick the right mitigation.

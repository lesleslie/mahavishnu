# Prefect demo `flow=fn` ad-hoc pattern fails against Prefect 3.x process worker pools

Status: open (no decision rule — informational)

## Context

While closing the demo sweep (16 of 17 demos passing after the
layered-config + runpod-public substrate work this session), the
``mahavishnu demo prefect`` flow consistently timed out at 120s with
no state transition.

The substrate-side check (``settings.prefect.api_url`` reachable,
``prefect.work_pool`` set) passes once ``MAHAVISHNU_PREFECT__API_URL``
points at the local Prefect server (port 8464) instead of the
demo's hardcoded 4200 default. The failure mode lives in the
worker-pool dispatch path inside ``_run_prefect_demo``
(``mahavishnu/cli/demo_cli.py``):

```python
flow_run = await client.create_flow_run(
    flow=flow_func,
    parameters=parameters,
    work_pool_name=work_pool,
    ...
)
```

Per Prefect 3.x semantics, ``create_flow_run(flow=<in-memory>)`` does
NOT persist the source location anywhere reachable by the worker
subprocess. Process-type workers spawn a fresh Python interpreter in
a fresh CWD and try to import the flow by name; with no
``PrefectFileSystem``-stored source path, the import fails silently
and the run sits in PENDING until the demo's poll timeout. Status
stays ``SCHEDULED`` forever.

## Findings (during this session's four attempts to fix)

1. **``flow.from_source(source=LocalFileSystem(basepath=...)).deploy(...)``**
   - Fails with: ``Either an image or remote storage location must
     be provided when deploying a deployment.``
   - ``LocalFileSystem`` does not satisfy the "remote storage"
     predicate. ``Git`` is a separate integration
     (``prefect_github`` / ``prefect.git``); the project does not
     install it, and the project's pyproject.toml is the only path
     where adding it would be safe.

2. **``flow.adeploy(image=None, work_pool_name=...)``**
   - Same storage error. ``image=None`` is not sufficient because
     the deployment validation gates on storage.

3. **``flow.serve(host='127.0.0.1', port=...)``**
   - In 3.8.8, ``Flow.serve`` does NOT accept ``host``/``port``
     kwargs (verified — ``TypeError: got an unexpected keyword
     argument 'host'``). It uses ``uvicorn`` default ``127.0.0.1:8080``
     and is fixed by project-level CLI flags, not kwargs.
   - Even with the right host/port, the deployment registered by
     ``serve`` is per-binary: every invocation of the demo would
     re-register an ephemeral process serving the same flow name,
     not a deployment that's actually deployable.

4. **Putting it on the queue via the GitHub URL as ``Git``
   storage** is the production-shaped fix: install ``prefect_github``
   in the venv (``uv add prefect-github``, which bumps
   ``pyproject.toml``'s ``[project].dependencies`` — currently
   user-controlled per
   ``feedback-mcp-common-version-bump-is-user.md``), and use
   ``Git(repository="github.com/lesleslie/mahavishnu.git", reference="main")``
   as the deployment's storage. The worker subprocess clones from
   the remote and imports the flow module. Requires the project's
   GitHub repo to be reachable from the worker subprocess's network,
   and requires either CI to install ``prefect-github`` or a one-
   time operator step.

## Why this is left open

Two architectural mismatches stack:

- ``flow=fn`` ad-hoc is brittle by Prefect 3.x design — operators
  who don't want to deploy every flow before running it once are
  out of luck in Prefect 3.x.
- The project lacks GitHub storage integration; adding
  ``prefect-github`` is a dependency change gated on operator
  approval (per the same rule that gates ``mcp-common`` bumps).

Out of scope for the demo sweep this session. Documented here so the
next reader doesn't re-traverse the four attempts and hit the
same gates.

## Recommended fix path (when operator approves)

1. Operator: ``uv add prefect-github`` (bumps pyproject.toml).
2. Modify ``_run_prefect_demo`` to call
   ``process_repositories_flow.afrom_source(source=Git(repository="https://github.com/lesleslie/mahavishnu.git", reference="main"), entrypoint="mahavishnu.engines.prefect_adapter_impl:process_repositories_flow").adeploy(name="mahavishnu-demo-flow", work_pool_name=prefect_cfg.work_pool)``.
3. ``run_deployment(name="<flow_name>/mahavishnu-demo-flow",
   parameters=..., timeout=120)`` against the persisted deployment.
4. The pre-existing worker (started manually per the work-pool
   prep section of this session, OR via a launchd plist on the
   operator's machine) picks the run up, clones the repo, and
   executes the flow.

For now, 16 of 17 demos pass; the prefect demo is the lone
known-limitation entry.

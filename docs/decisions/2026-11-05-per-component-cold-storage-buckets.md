---
status: active
role: canonical
kind: decision
date: 2026-11-05
last_reviewed: 2026-11-05
superseded_by: null
topic: per-component-cold-storage-buckets
---

# Per-component cold-storage buckets

## Context

The Bodai fleet's cold (object-store) tier was configured through Oneiric's
**substrate** settings, which are fleet-wide by construction:

```
ONEIRIC__SUBSTRATE__COLD__BACKEND
ONEIRIC__SUBSTRATE__COLD__BUCKET
ONEIRIC__SUBSTRATE__COLD__PREFIX
ONEIRIC__SUBSTRATE__COLD__COMPRESSION
```

`oneiric/core/substrate_settings.py:171-181` describes the intended shape:

- `cold__bucket` — *"Cold-tier bucket name (shared across Bodai components)."*
  Default `oneiric-substrate-shared`.
- `cold__prefix` — *"Object-key prefix used to isolate per-component cold
  data. Akosha uses `akosha/`; Session-Buddy uses `sb/`; etc."*

So the design is **one shared bucket, per-component prefixes**.

That design's isolation mechanism does not work. `cold__prefix` is a single
fleet-wide env var, and a component cannot override it — the component-scoped
overrides covered `backend`, `bucket`, `region`, `endpoint_url` and the
credentials, but **not** the prefix. Two components reading the substrate
would resolve the same prefix and overwrite each other's objects.

Meanwhile the two components that actually have a cold tier were writing
genuinely different things:

| Component | Path | Object shape | Key layout |
|---|---|---|---|
| Akosha | `akosha/modes/standard.py`, `akosha/storage/cold_store.py` | conversation rows | `conversations/` |
| Session-Buddy | `session_buddy/storage/cloud_sync.py` | whole DuckDB file snapshots (`reflection.duckdb`, `knowledge_graph.duckdb`) | `systems/{system_id}/uploads/{upload_id}/` |

Session-Buddy never read the substrate at all — it has its own
`cloud_sync.cloud_bucket` setting and its own key layout. Mahavishnu has no
cold tier at all (no `cold__` reference anywhere in `mahavishnu/`).

## Decision rule

**Each component that has a cold tier owns its own bucket. The bucket name
and the key prefix are component settings, not fleet settings.**

Component-owned:

- the bucket name
- the key prefix (an internal detail once the bucket isolates)
- the credential env-var names

Still fleet-wide, because they are genuinely shared policy or describe the
account rather than the component:

- `cold__backend` — which protocol/tier (R2 vs S3 vs GCS vs Azure)
- `cold__compression`, `cold__retention_days`
- the endpoint URL and region (they describe the *account*)
- the R2 credential *values* (R2 API keys are account-scoped, not
  bucket-scoped — so there is no isolation argument for separate keys, and
  the per-component env-var *names* exist so a bucket-scoped token can be
  dropped in later without another config change)

The fleet-wide `ONEIRIC__SUBSTRATE__COLD__BUCKET` / `_PREFIX` remain as
**defaults** for a component that has not overridden them. They must not be
set to one component's values: the prefix is the substrate's isolation
mechanism and it is only settable fleet-wide, so a shared bucket with a
shared prefix is a collision.

### Where each value lives

| Value | Layer | Example |
|---|---|---|
| Bucket name | component-scoped env, or the component's XDG overlay | `AKOSHA__STORAGE__COLD__BUCKET=akosha-cold` |
| Key prefix | component-scoped env | `AKOSHA__STORAGE__COLD__PREFIX=conversations/` |
| Credentials | env only — never a tracked YAML, never a plist | `SESSION_BUDDY_CLOUD_SYNC__CLOUD_SECRET_ACCESS_KEY` |
| Backend / compression | fleet-wide | `ONEIRIC__SUBSTRATE__COLD__BACKEND=s3` |

Buckets as of 2026-11-05:

- `akosha-cold` — Akosha
- `session-buddy-cold` — Session-Buddy

`mahavishnu-cold` is deliberately **not** created: Mahavishnu has no cold
tier. A component that grows one gets a bucket then.

## Env-var layering: why env beats the XDG overlay

Oneiric's source chain (`oneiric/core/config.py:484-520`, "first returned
wins") is:

1. `init_settings` (constructor kwargs)
2. env source (`{PREFIX}_{SECTION}__{FIELD}`)
3. legacy single-underscore alias source
4. `ONEIRIC__SUBSTRATE__*` source
5-9. **YAML layers** — XDG local, XDG config, project local, project yaml, project yml
10-11. dotenv (deactivated by the loader), file secrets

**Env vars outrank every YAML layer, including the XDG overlay.** An operator
who writes `cold:` in `~/.config/akosha/local.yaml` expects it to take
effect; if the same key is also exported in the environment, the environment
wins — silently.

This is why cold-storage configuration drifted into the environment in the
first place: `cold.bucket` / `cold.prefix` are **substrate-mapped**, so
`akosha/config.py:_strip_substrate_mapped` removes them from *every* YAML
layer, including the XDG overlay. The only way to set them was an env var.

The component-scoped overrides are the way out: `AKOSHA__STORAGE__COLD__BUCKET`
and `AKOSHA__STORAGE__COLD__PREFIX` are applied after the strip, so they
populate a field the substrate would otherwise own.

## Related: no component config in `.envrc`

`.envrc` is a **direnv** hook. It is applied only when a shell's working
directory is inside the repo, and only when direnv is installed and the file
has been allowed. Two consequences:

1. A service launched by launchd (cwd elsewhere) sees a different
   configuration than a developer shell inside the repo.
2. The exported values outrank the XDG overlay for every process started
   from that directory, including unrelated tools.

So `.envrc` is for **tooling** (`layout uv`), never for component
configuration. Component configuration goes to the XDG overlay
(`~/.config/{component}/local.yaml`) or to the component-scoped env vars in
`~/.config/secrets.env` — the latter only for values that must not be
written to disk in a tracked file (credentials).

The fleet currently has three `.envrc` files that set component config:

| Repo | Vars | Status |
|---|---|---|
| `akosha` | `AKOSHA__STORAGE__HOT__PG_URL` | **Dead and tracked.** `pg_url` is a `WarmStorageConfig` field, not a `HotStorageConfig` field, so the var binds to nothing; the correct spelling is `AKOSHA__STORAGE__WARM__PG_URL`. It is also a credentialed URL in a tracked file, committed since 2025-02-01. The live warm-tier connection lives in the XDG overlay. |
| `oneiric` | `HEALTH_FEED_HALFLIFE_SECONDS` | **Live and tracked.** Read via `os.environ.get` in `oneiric/mcp/server.py:145`. Not a secret, but directory-scoped and unprefixed. |
| `opera-cloud-mcp` | 14 × `OPERA_*` (incl. `OPERA_CLIENT_SECRET`) | **Correctly gitignored** (`.gitignore:56`), but still directory-scoped. |

Every other Bodai repo's `.envrc` contains only `layout uv`.

## Alternatives considered

**One shared bucket for the whole fleet.** Rejected: the isolation mechanism
(prefix) is only settable fleet-wide, so it cannot isolate two writers. It
would need the component-scoped prefix override *before* it could work —
which is this decision, one step earlier.

**Per-component buckets with a shared credential pair.** What we do. R2 keys
are account-scoped, so separate buckets do not require separate keys.

**Prefix-only isolation on one bucket.** Rejected: it makes every component
depend on a fleet-wide prefix, and the prefix is exactly the knob that
cannot be scoped per component.

## Follow-up (not done here)

`oneiric`'s `SubstrateSettings.cold__bucket` / `cold__prefix` are still
declared as substrate fields, and `akosha`'s `_strip_substrate_mapped` still
strips `cold.bucket` / `cold.prefix` from YAML. Un-mapping them at the
substrate level would let each component's XDG overlay own its bucket
directly, with no env var at all for the bucket name. That is a cross-repo
change to a published library and needs an operator version bump — it is
deliberately not bundled with the component-level fixes above.

## Status

Accepted. Implemented 2026-11-05:

- `akosha`: `AKOSHA__STORAGE__COLD__PREFIX` component-scoped override
  (commit `0a07461`).
- `session-buddy`: cloud credentials read from
  `SESSION_BUDDY_CLOUD_SYNC__CLOUD_{ACCESS_KEY_ID,SECRET_ACCESS_KEY}` and
  `SESSION_BUDDY_CLOUD_SYNC__SYSTEM_ID` instead of Akosha's namespace
  (commit `817d0cc6`).
- Buckets `akosha-cold` and `session-buddy-cold` created in Cloudflare R2.

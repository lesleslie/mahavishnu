# Mahavishnu Admin Shell

Mahavishnu ships the most fully-developed per-repo admin shell
(`mahavishnu.shell.MahavishnuShell`). It extends
`oneiric.admin_shell.AdminShell` and adds component-specific
magics + namespace helpers for orchestrator inspection.

## Magics

- `%repos` — list repos from the registered ecosystem catalog, with
  per-repo health (`healthy` / `degraded` / `unknown`) and last-indexed
  timestamp.
- `%workflow` — show in-flight workflows from the running Mahavishnu
  pool, grouped by adapter and worker.

## Namespace

- `app` — the running Mahavishnu `MahavishnuApp` instance
- `settings` — the active `MahavishnuSettings` (post-overlay)
- `logger` — the Oneiric logger bound to `service.name=mahavishnu`
- `adapter_registry` — the live `AdapterRegistry` (read-only at runtime)

## Cross-component admin shells

All 5 per-repo admin shells share the `AdminShell` base class in
`oneiric.shell`. See `oneiric/docs/ONEIRIC_ADMIN_SHELL.md` for the
canonical base class doc and the layout of all current subclasses.
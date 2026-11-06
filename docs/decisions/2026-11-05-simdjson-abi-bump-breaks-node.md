---
status: active
role: canonical
kind: decision
date: 2026-11-05
last_reviewed: 2026-11-05
superseded_by: null
topic: simdjson-abi-bump-breaks-node
---

# `simdjson` ABI bump breaks `node` — pin it, and rebuild node against it

## Context

On 2026-11-05, Homebrew upgraded `simdjson` 5.0.5 → 5.1.1 as a side effect of
a `brew install` of a node-dependent formula. `simdjson` versions its shared
library by ABI number, so the dylib was renamed
`libsimdjson.34.dylib` → `libsimdjson.36.dylib`. `node` 26.12.1_1 had been
compiled against 5.0.5 and hard-links the *versioned* path
`/usr/local/opt/simdjson/lib/libsimdjson.34.dylib`.

Twenty formulae declare a dependency on `simdjson` (`brew uses --installed
simdjson`). Only two Mach-O files actually link the dylib — `node`'s
`bin/node` and `lib/libnode.147.dylib` — but the other eighteen are node
scripts that inherit node's runtime, so node is the entire blast radius.
`/usr/local/opt/simdjson` (Homebrew's opt symlink) was additionally missing,
which is a second, independent way to produce the same dyld error.

The failure has **two distinct layers, and clearing the first does not clear
the second**:

1. **Loud** — `dyld: Library not loaded: .../libsimdjson.34.dylib`.
2. **Silent memory corruption** — after relinking node onto the unversioned
   `libsimdjson.dylib` alias, node loads and then aborts inside its native
   `internal/modules/package_json_reader` with
   `std::bad_alloc` whenever the JSON contains a string value
   (`{"a":1}` parses; `{"name":"x"}` aborts). Every node CLI that resolves a
   package scope dies.

Layer 2 is not a linker trick that can be waved away: 56 of the 251 public
headers under `include/` differ between the two upstream tags, including
every `*/stringparsing_defs.h`, the DOM and ondemand parser headers,
`padded_string_view.h`, and `generic/numberparsing.h`.
`haswell/stringparsing_defs.h` removes `struct escaping` outright. A
spot-check of `implementation.h` / `base.h` / `error.h` shows them
byte-identical and proves nothing — the changed headers are precisely the
ones node's package.json reader compiles against. Node's *other* simdjson
consumer (UTF-8 validation) still behaves correctly against the newer
library, so a passing `Buffer` round-trip is also not evidence of
compatibility.

## Decision rule

**Pin `simdjson`; never work around its ABI bump by relinking.**

- `brew pin simdjson` is the standing mitigation. Without it, the next
  `brew install` of a node-dependent formula re-runs the bump and re-breaks
  node. Install node-dependent formulae with
  `brew install --ignore-dependencies <formula>`.
- **Never** create `libsimdjson.34.dylib` as an alias of the `.36` library.
  The mangled symbol names survive the bump (only the *name* is encoded, not
  the type or array size), so the link succeeds and the incompatibility
  surfaces later as `bad_alloc` instead of a dyld error. A loud failure is
  the better outcome.
- The correct repair is to **rebuild node against the installed simdjson**
  (`brew upgrade node` → 26.13.0_2). It is mutually exclusive with
  downgrading simdjson: 5.0.5 ships only `.34`, which would break a node
  built against 5.1.1. Choose one; do not do both.
- After the rebuild, keep node's link **versioned** and rely on the pin. A
  versioned link fails loudly if `simdjson` ever moves; an unversioned link
  would follow the bump silently.

**Interim, if node must run before the rebuild lands:** restoring the opt
symlink (`ln -sfn ../Cellar/simdjson/<ver> /usr/local/opt/simdjson`) clears
layer 1 only. Relinking node onto the unversioned alias clears layer 1 too
but leaves the machine in the layer-2 state: node loads, its UTF-8 paths
behave, and its package.json reader corrupts memory. Treat that as a
**corruption-prone holding pattern, not a fix** — revert it by restoring the
binaries from
`~/.local/state/mahavishnu/backups/node-simdjson-relink-<date>/`, or delete
the relink so node fails loudly instead.

**Recovery trap:** an interrupted `brew upgrade` leaves an *empty*
`Cellar/<formula>/<newversion>/` directory. `brew outdated` then reports the
new version as installed and `brew upgrade` **no-ops**. Remove the empty
directory before retrying, or the retry silently does nothing.

## Diagnosing it

Two probes separate the layers:

```bash
# Layer 1 — dyld linkage
otool -L "$(brew --prefix)/bin/node" | grep simdjson

# Layer 2 — native package.json reader (the simdjson consumer)
node --expose-internals -e \
  'const r=require("internal/modules/package_json_reader"); r.read("<pkg.json>")'
```

A `cwd` matrix (`node -e 'require("/abs/path")'` from the repo root vs from
`/tmp`) shows the layer-2 crash is *content*-dependent, not
location-dependent: it fires only in a directory whose package scope has a
package.json containing a string value.

## Status

Active. `simdjson` is pinned; node 26.13.0_2 rebuild pending (source build —
Homebrew publishes no x86_64 macOS bottle for node).

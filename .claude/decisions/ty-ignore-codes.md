---
status: active
role: canonical
date: 2026-07-26
last_reviewed: 2026-07-26
topic: ty-ignore-codes
---

# `ty: ignore[...]` policy for `*-mcp`

One-line summary: use precise ty diagnostic codes for verified type-checker boundaries; never hide ty diagnostics behind mypy/ruff ignore syntax.

## Context

Crackerjack uses **ty** as its type checker (it replaced zuban). Ty does not interpret
bare `# type: ignore` comments or mypy/ruff codes such as `assignment` and
`attr-defined`. Those comments can look like suppressions while leaving the ty
diagnostic active, so bare `# type: ignore` and stray mypy/ruff codes are
common and silently fail to suppress.

A useful gotcha from the audit: malformed `session.run` suppression comments
swallowed commas and arguments, producing cascading `unresolved-attribute`
diagnostics that looked like helper-method indentation problems. The comment
placement matters as much as the code choice.

## Decision rule

Use one specific `# ty: ignore[<code>]` comment, attached to the expression that
emits the verified diagnostic. Before adding it, try narrowing, a correct
annotation, `cast`, an overload, or a typed adapter.

1. **A proven `None`-to-required-type boundary** uses
   `invalid-argument-type` only after the `None` path has been checked and the
   boundary is intentional:

   ```python
   if result is not None:
       components.append(result)

   # Only when a framework boundary is proven safe and cannot be narrowed:
   components.append(result)  # ty: ignore[invalid-argument-type]
   ```

   Prefer the first form or `cast("ComponentHealth", result)`. Do not use this
   code as a blanket escape for arbitrary third-party overload mismatches. The
   Neo4j calls retained after the pass at
   `neo4j-mcp/neo4j_mcp/client.py:89,110,132,154,187,231,260,298,344,356`
   are third-party API/stub boundaries and are a review signal, not the model
   for a new `None` suppression.

2. **A dynamically provided attribute** uses `unresolved-attribute` only when
   runtime setup demonstrably creates that attribute:

   ```python
   app._penpot_client = client  # ty: ignore[unresolved-attribute]
   ```

   This matches `penpot-api-mcp/penpot_api_mcp/server.py:54` and the analogous
   client stashes in `porkbun-dns-mcp/.../server.py:92` and
   `porkbun-domain-mcp/.../server.py:88`. Prefer a typed wrapper, protocol, or
   explicit application state when one is practical; check for a typo before
   suppressing.

3. **An Oneiric/mcp-common mixin configuration slot** may use
   `invalid-assignment` when the base mixin's static type is narrower than the
   verified runtime contract:

   ```python
   self.config = config  # ty: ignore[invalid-assignment]
   ```

   The pattern appears in `excalidraw-mcp/.../__main__.py:33`,
   `langsmith-mcp/.../__main__.py:33`, and
   `penpot-api-mcp/.../__main__.py:32`. Prefer a typed property or a cast if it
   preserves the contract without suppressing the assignment.

4. **An optional, type-checking-only import** may use
   `unresolved-import` when the package is intentionally absent at runtime:

   ```python
   if TYPE_CHECKING:
       from optional_dependency import ProtocolType  # ty: ignore[unresolved-import]
   ```

   This is for an optional type-only dependency, not a missing production import.
   Fix the import path or dependency declaration for runtime imports. See the
   existing Bodai example at `session-buddy/session_buddy/resource_cleanup.py:93`.

5. **A framework-generated constructor with an incomplete static signature** is
   a narrow, review-only exception for `call-arg`:

   ```python
   settings = FrameworkSettings()  # ty: ignore[call-arg]
   ```

   Confirm the call is valid at runtime and covered by a test before using it.
   `langsmith-mcp/langsmith_mcp/__main__.py:92` is a review candidate because
   `LangSmithSettings` declares a required API key; supplying the required data
   or using the settings loader is preferable to suppressing the call.

   **Threshold rule.** A single file may carry at most **5** ty suppressions.
   Files crossing this threshold (`neo4j-mcp/neo4j_mcp/client.py` is the
   current example, with 10 suppressed lines) trigger a forced audit before
   more are added. The audit must decide whether each suppression is a real
   boundary or a sign that the typing should be redone. This rule is enforced
   by crackerjack's `ty_ratchet` diagnostic-count gate.

6. **When a function's declared return type is narrower than its actual return,
   fix the annotation, never suppress.** A `# type: ignore` here masks a real
   bug — the caller is reading a richer value than the type promises — and the
   fix is to widen the annotation (or narrow the return) to match the
   contract. Examples observed on the `*-mcp` fleet:

   - `langsmith-mcp/langsmith_mcp/server.py` — `health_check()` declared as
     `dict[str, Any]` while it actually returns a `HealthCheckResponse`.
   - `mailgun-mcp/mailgun_mcp/server.py` — same `health_check` shape.
   - `opera-cloud-mcp/opera_cloud_mcp/server.py` — same `health_check` shape.
   - `neo4j-mcp/neo4j_mcp/client.py` — `_ensure_driver()` declared as
     `AsyncDriver | None` while it always returns a live driver.

   The corrective move is to import the response dataclass / concrete type and
   widen the annotation. A suppression turned every one of these into a silent
   contract drift; the right fix is the import plus the annotation.

## Status

Active. This decision applies to all Bodai `*-mcp` repositories. It is a
classification and review policy, not a blanket allowance for new suppressions.
Existing comments may be migrated during normal touch-ups, but each migration
must be checked with ty rather than mechanically translated from mypy syntax.

## Anti-patterns

- `# type: ignore` (bare), or `# type: ignore[assignment]`, `arg-type`,
  `attr-defined`, `union-attr`, `call-overload`, or another mypy/ruff code.
  Replace it with a real fix or the exact code ty reports.
- Keeping both forms on one line, for example
  `# type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]`.
- Letting a single file accumulate more than 5 ty suppressions without a
  forced audit. `neo4j-mcp/neo4j_mcp/client.py` is the current mass-suppression
  signal.
- Using `unresolved-attribute` for a possibly misspelled or never-initialized
  attribute, or `unresolved-import` for an import that production code needs.
- Using `invalid-argument-type` to silence an unexamined library-stub mismatch,
  or placing multiple ignore directives on one argument line. The post-fix Neo4j
  comments are now attached to the flagged argument/call; preserve that placement.
  A comment inserted before a closing call can swallow commas or arguments and
  create cascading diagnostics.
- Using `# type: ignore` (bare or mypy-syntax) to mask a function whose declared
  return type is narrower than its actual return. Always widen the annotation;
  the suppression was hiding a real bug.
- Suppressing a diagnostic that can be removed with a narrow check, explicit
  type, `cast`, overload, dependency configuration, or a small API refactor.

## Audit cadence

Before each crackerjack pass on the `*-mcp` fleet, search primary source and test
files for both `ty: ignore` and `# type: ignore`, report counts by repository and
code, and inspect any file that crosses 5 ty suppressions. Re-run ty after
adding or removing a directive and remove `unused-ignore-comment` warnings.
Repeat the audit after a ty/Crackerjack upgrade or when a new diagnostic code
appears in more than one repository; update this decision when the established
code mapping changes.

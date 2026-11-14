---
status: active
role: canonical
kind: decision
date: 2026-07-26
last_reviewed: 2026-11-14
topic: ty-ignore-codes
---

# `ty: ignore[...]` policy for the fleet

One-line summary: use precise ty diagnostic codes for verified type-checker boundaries; never hide ty diagnostics behind mypy/ruff ignore syntax.

**ty is the only type checker in the fleet.** mypy has no configuration and no
dependency anywhere — it was never run by CI in any repo. Every suppression in
every repo is therefore spelled for ty.

## Context

Crackerjack uses **ty** as its type checker (it replaced zuban). Ty does not interpret
bare `# type: ignore` comments or mypy/ruff codes such as `assignment` and
`attr-defined`. Those comments can look like suppressions while leaving the ty
diagnostic active, so bare `# type: ignore` and stray mypy/ruff codes are
common and silently fail to suppress.

The fleet carried 2,711 bracketed mypy directives and 105 blanket ones. Every
bracketed directive was inert — ty never read the bracketed form at all, so
those 2,711 comments suppressed nothing at all while reading like suppressions.
The fleet-wide migration on 2026-11-14 deleted them, converted the live blanket
directives into specific ty rules, and removed mypy's configuration. The two
`NameError` defects that the blanket directives had been hiding are fixed.

A useful gotcha from the audit: malformed `session.run` suppression comments
swallowed commas and arguments, producing cascading `missing-attribute`
diagnostics that looked like helper-method indentation problems. The comment
placement matters as much as the code choice.

## Decision rule

Use one specific `# ty: ignore[<code>]` comment, attached to the expression that
emits the verified diagnostic. Before adding it, try narrowing, a correct
annotation, `cast`, an overload, or a typed adapter.

**What enforces this.** Two different mechanisms, and they do not overlap:

- **Syntax.** `crackerjack.tools.ty_ignore_syntax` rejects mypy/ruff ignore
  syntax — bare `# type: ignore` and `# type: ignore[<code>]` — because ty
  does not interpret it, so those comments suppress nothing while reading
  like suppressions. It also rejects a line that carries both spellings.
  The hook is **on by default** (`hooks.enable_ty_ignore_syntax`); a repo
  that needs an exception sets it to `false`.
- **Rule-name validity.** ty itself. It reports `ignore-comment-unknown-rule`
  and exits non-zero for a code it does not know, which is what makes the
  rename coupling described below safe.

Because ty owns rule-name validity, no registry of ty rule names is needed
anywhere, and there is nothing to keep in sync with the codes below. The codes
in this section are the **policy** — which suppressions the fleet sanctions —
not the enforcement list.

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

2. **A dynamically provided attribute** uses `missing-attribute` only when
   runtime setup demonstrably creates that attribute:

   ```python
   app._penpot_client = client  # ty: ignore[missing-attribute]
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
   `import-not-found` when the package is intentionally absent at runtime:

   ```python
   if TYPE_CHECKING:
       from optional_dependency import ProtocolType  # ty: ignore[import-not-found]
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
   boundary or a sign that the typing should be redone. This rule is **not**
   machine-enforced: `ty_ratchet` counts the diagnostics ty reports, and a
   suppression removes the diagnostic from that count. The threshold is
   enforced by review, not by the gate.

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

7. **`invalid-explicit-return` is the legitimate narrow case.** Some patterns
   legitimately need the suppression when the narrow type is intentional and
   the widening would mislead callers — for example, decorator factories
   that return `Callable[..., T]` while their inner closure returns
   `Awaitable[T]`. Cite a real example before adding it:
   `excalidraw-mcp/excalidraw_mcp/retry_utils.py:245`. Default to fixing the
   annotation (Rule #6) over suppressing with this code.

   ```python
   def async_wrapper(...) -> Callable[..., T]:  # ty: ignore[invalid-explicit-return]
       ...
   ```

8. **`invalid-await` flags `await <sync-call>`.** The fix is to drop the
   `await`; the function being awaited is sync. Examples fixed in the fleet:
   `excalidraw-mcp/excalidraw_mcp/cli.py:141` (was `await None`),
   `opera-cloud-mcp/opera_cloud_mcp/main.py:572` (was `await app.run()`),
   `opera-cloud-mcp/opera_cloud_mcp/server.py:81` (same `asyncio.run(app.run())`
   shape). Suppress only when awaitability is dynamic and undecidable.

   ```python
   result = sync_or_async_fn(...)  # ty: ignore[invalid-await]
   ```

9. **`unused-type-ignore-comment` is a meta-code** — ty emits it on a dead
   suppression, not a code you write. Treat its appearance as a signal:
   remove the dead suppression rather than adding the code.

   ```python
   # ty reports this on a dead suppression; remove the suppression instead:
   foo()  # ty: ignore[unused-type-ignore-comment]
   ```

## Status

Active. This decision applies to every repository in the fleet, not only the
`*-mcp` ones. It is a classification and review policy, not a blanket allowance
for new suppressions.

**The migration is complete.** As of 2026-11-14:

- No mypy configuration remains: no `mypy.ini`, no `[tool.mypy]` section, no
  mypy dependency in any repo's dependency groups.
- No mypy-syntax directive remains in any committed repo. The
  `ty-ignore-syntax` gate reports 0 findings across the fleet.
- Every live suppression names a specific ty rule.

Any suppression added from here on must be `# ty: ignore[<rule>]`. A bare
`# type: ignore` is rejected by the gate: it reads like a suppression but
suppresses nothing in ty, so it silently hides nothing while convincing the
author that a diagnostic was silenced.

**Rule-name version coupling.** The codes named below are the ty >= 0.0.104
spellings. ty 0.0.104 renamed three of them: `unresolved-attribute` became
`missing-attribute`, `unresolved-import` became `import-not-found`, and
`invalid-return-type` became `invalid-explicit-return`. A directive naming a
pre-0.0.104 spelling is not a no-op — ty reports it as
`renamed-rule-in-ignore-comment`, and ty exits non-zero on warnings alone.

**The rename was a split, not a rename.** `unresolved-attribute` became
*two* rules: `missing-attribute` (the attribute is genuinely absent) and
`missing-union-attribute` (the attribute is absent on the `None` member of a
union). A blanket rename leaves the union case unsuppressed. The reliable
method is to strip the directive and read back the diagnostic ty actually
reports for that line — `ty explain rule <name>` resolves a rule name but
does not tell you which rule applies to a given site.

## Anti-patterns

- `# type: ignore` (bare), or `# type: ignore[assignment]`, `arg-type`,
  `attr-defined`, `union-attr`, `call-overload`, or another mypy/ruff code.
  Replace it with a real fix or the exact code ty reports. The
  `ty-ignore-syntax` gate rejects both spellings, and it is on by default:
  a mypy-syntax comment is a comment that looks like a suppression and
  suppresses nothing.
- A blanket `# ty: ignore` with no rule name. ty honours the bare form as a
  blanket per-line suppression, so it *does* silence a diagnostic — but it
  silences every diagnostic on that line, and the next one to appear is
  silenced with no record of why. Name the rule.
- Keeping both forms on one line, for example
  `# type: ignore[attr-defined]  # ty: ignore[missing-attribute]`.
- Letting a single file accumulate more than 5 ty suppressions without a
  forced audit. `neo4j-mcp/neo4j_mcp/client.py` is the current mass-suppression
  signal.
- Using `missing-attribute` for a possibly misspelled or never-initialized
  attribute, or `import-not-found` for an import that production code needs.
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

**Meta-code note.** `unused-type-ignore-comment` is not a suppression you write
— it is what ty emits when a suppression is suppressing nothing (a dead
suppression). Treat its appearance as a signal: remove the dead suppression
rather than adding the code to your code.

## Audit cadence

Before each crackerjack pass on the `*-mcp` fleet, search primary source and test
files for both `ty: ignore` and `# type: ignore`, report counts by repository and
code, and inspect any file that crosses 5 ty suppressions. Re-run ty after
adding or removing a directive and remove `unused-ignore-comment` warnings.
Repeat the audit after a ty/Crackerjack upgrade or when a new diagnostic code
appears in more than one repository; update this decision when the established
code mapping changes.

**Measure the test tree too.** A repo that scopes ty with
`[tool.ty] src = { include = ["<pkg>/**/*.py"] }` filters ty's whole file
discovery, so `ty check tests` finds no files and exits 0 — a "clean" result
that measured nothing. `crackerjack.tools.ty_ratchet --split` overrides
`src.include` per gate for this reason, and reports **GATE ERROR** rather than
PASS when a populated directory yields no files. Treat a `test: PASS (0/N)`
line with no file count as suspect until the gate has been shown to see the
test tree.

The crackerjack hook enforces the *syntax* rules above and nothing else;
ty enforces rule-name validity natively. This file holds the *policy* — which
suppressions the fleet sanctions and what each one means. Nothing parses this
file, so adding a code here is a policy decision and needs no matching code
change anywhere else.

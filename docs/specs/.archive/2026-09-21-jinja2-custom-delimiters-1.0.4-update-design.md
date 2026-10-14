# jinja2-custom-delimiters 1.0.4 Update — Design Spec (revised)

**Date:** 2026-09-21
**Status:** Draft — under multi-agent review, second iteration
**Target repo:** `/Users/les/Projects/jinja2-custom-delimiters`
**Working location:** main checkout of target repo (per user selection)
**Source:** brainstorming session 2026-09-21

______________________________________________________________________

## Context

The `jinja2-custom-delimiters` plugin (v1.0.3, last released 2026-01-19) is a
PyCharm Professional plugin that lets users configure custom Jinja2 template
delimiters (`[[ ]]`, `[% %]`, `[# #]`) while preserving PyCharm's built-in
Jinja2 formatter. It is a **paid** plugin with marketplace license gating.

The plugin's current platform target is `sinceBuild=252, untilBuild=253.*`
(PyCharm 2025.2 → 2025.3). PyCharm has since released 2026.1, 2026.2, and
2026.3. Users on newer IDEs **cannot install** the plugin from the
Marketplace because the build range doesn't include them.

This update widens the supported build range to include 2026.x releases and
brings the plugin's tooling, audit surface, and CI hygiene in line with the
project owner's current conventions (crackerjack for CI/CD, no provider-
specific workflows).

## Current-state corrections (applied from review)

These are facts about the live working tree that diverge from the prior
draft. Captured up front so the rest of the spec doesn't inherit the drift.

- `gradle/wrapper/gradle-wrapper.properties` is **`9.4.1`** on disk (not
  `9.1.0`). `gradle.properties:26` says `gradleVersion = 9.1.0` — the
  `tasks.wrapper` block in `build.gradle.kts` would silently downgrade the
  wrapper if invoked. **Resolution: bump `gradleVersion` to `9.4.1` to
  match.**
- `gradle/libs.versions.toml:12` pins `intelliJPlatform = 2.13.1` (Mar
  2026). Seven minor releases newer exist — **`2.19.0`** (14 Sep 2026) is
  the latest. 2.13.1 cannot resolve build 263. **Resolution: bump to
  `2.19.0`** (or whatever 2.x is current at Phase 1 start). This is the
  single most load-bearing correction.
- `settings.gradle.kts:2` pins `foojay-resolver-convention version "1.0.0"`. Java 25 metadata may not be in 1.0.0. **Resolution: bump
  to `>= 1.1.0`** (latest at Phase 1 start).
- `foojay-resolver-convention` is referenced in `settings.gradle.kts`
  but **not currently applied** to `build.gradle.kts` as a plugin block —
  actually it IS applied at `settings.gradle.kts:2` which is the
  conventional pattern. (Java reviewer was incorrect; see Phase 1 audit
  verification.)
- `.gitignore` does **not** cover `.gradle/`, `.intellijPlatform/sandbox/`,
  `.jbeval/`, `.crackerjack/`, `.crackerjack_cache/`. Prior spec text
  incorrectly claimed it did. **Resolution: add all five to `.gitignore`
  as part of Phase 2.**
- `AUDIT-SUMMARY.md` (Dec 2025) listed 2 open critical issues. Verification
  against commit history: **CRITICAL #3, #4, #6 are closed** (commits
  `e0ae8af`, `2bbc0f8`). **Only HIGH #6 (null-handling) remains open.**
- `LicenseGate.isLicensedOrPending()` returns `true` when `licensed == null` (silent-fallback path). `MarketplaceLicenseChecker.isLicensed()`
  returns `null` when `LicensingFacade.getInstance() == null`. This
  violates the spec's hard-fail contract — must be removed.
- The crackerjack Kotlin adapter hook names are `kotlin.ktlint`,
  `kotlin.detekt`, `kotlin.test` (per
  `/Users/les/Projects/crackerjack/crackerjack/adapters/kotlin/hooks.py:70-96`).
  The Gradle task names invoked by those hooks are `ktlintCheck`,
  `detekt`, `test`. Prior spec mixed the two vocabularies.
- The plugin does **not** currently apply `ktlint` or `detekt` Gradle
  plugins. Without them, the `kotlin.ktlint` and `kotlin.detekt` hooks
  probe-and-skip silently. Phase 2 gate as written would pass with only
  `kotlin.test` running.
- `mcp__crackerjack__kotlin_bump_version` enforces `MAHAVISHNU_PROJECT_ROOTS`
  allowlist registration + `MAHAVISHNU_AUTH_ENABLED=true` +
  `MAHAVISHNU_JWT_SECRET`. Without these, the tool raises `PermissionError`.
- Plugin manifest `<product-descriptor release-date="20251203">` is
  v1.0.1's date. v1.0.4's `release-date` must be the actual build/upload
  date.
- `.github/dependabot.yml` and `codecov.yml` (repo root) become orphans
  once `.github/workflows/*` is deleted. Trim/delete as part of Phase 4g.

## Goals

1. **Make the plugin installable on PyCharm 2026.1 / 2026.2 / 2026.3** without
   breaking 2025.2 / 2025.3 users. `sinceBuild=252` stays; `untilBuild`
   opens to `263.*`. **2026.3 may not be in RELEASE channel yet** — if not
   GA, drop it from the matrix and ship 2025.2 → 2026.2; add 2026.3 in
   a follow-up 1.0.5.
1. **Bump Java toolchain to 25** (required by 2026.2 platform) +
   reconcile `gradleVersion` drift to 9.4.1.
1. **Bump `intelliJPlatform` Gradle plugin to 2.19.0** (or latest 2.x at
   Phase 1 start) — without this, 2026.x Verifier matrix can't run.
1. **Wire crackerjack as the audit surface.** Add `.crackerjack.toml`,
   apply `ktlint` + `detekt` Gradle plugins, run hooks with correct names
   (`kotlin.ktlint`, `kotlin.detekt`, `kotlin.test`).
1. **Verify the plugin actually works on real PyCharm builds** by running
   `pluginVerification.ides.select` against the available PyCharm
   Professional release builds (252, 253, 261, 262, [263 if GA]).
1. **Replace GitHub Actions with crackerjack.** Delete
   `.github/workflows/`, `.github/dependabot.yml`, `codecov.yml`. Keep
   `.github/FUNDING.yml` (GitHub platform parses this for sponsorship
   display — not a CI surface).
1. **Sweep the remaining pre-existing tech-debt** — HIGH #6 (null-
   handling in `Jinja2DelimitersSettings`/`LicenseGate`).
1. **Hard-fail license contract.** Remove silent-fallback paths so any
   license check failure (network, endpoint moved, cert expired) surfaces
   loudly to the user with actionable guidance.

## Non-goals (explicit exclusions)

- **No new features.** The delimiter handling, settings UI, formatter
  integration, and license gate all behave identically for the *happy
  path*. We're widening the install matrix and updating tooling, not
  changing the plugin surface.
- **No CI config added.** Crackerjack is the audit surface. No GitHub
  Actions, GitLab CI, CircleCI, or any other provider-specific CI file.
- **No automated publish.** `./gradlew publishPlugin` stays as a manual
  command with credentials in env vars (`PUBLISH_TOKEN`, `CERTIFICATE_CHAIN`,
  `PRIVATE_KEY`, `PRIVATE_KEY_PASSWORD`).
- **No worktree creation.** Work happens in the main checkout of
  `/Users/les/Projects/jinja2-custom-delimiters`.
- **No Gradle wrapper bump (just reconcile).** Wrapper is already 9.4.1
  on disk; bump `gradleVersion` in `gradle.properties` to match.
- **No `CLI` plugin.** The plugin is a GUI-only IntelliJ plugin; the
  existing pre/post format processors and settings UI are the entire
  surface.

## Architecture (unchanged)

The 4-file plugin architecture from v1.0.3's simplification is the load-
bearing decision and stays:

- `settings/Jinja2DelimitersSettings.java` — `PersistentStateComponent` with
  thread-safe getters/setters (`volatile` fields, synchronized access)
- `settings/Jinja2DelimitersConfigurable.java` — settings UI panel
- `formatting/CustomJinja2PreFormatProcessor.java` — converts custom
  delimiters to standard Jinja2 before formatting
- `formatting/CustomJinja2PostFormatProcessor.java` — converts back after
  formatting
- `formatting/DelimiterConversionUtil.java` — delimiter token replacement
- `licensing/MarketplaceLicenseChecker.java` — paid-plugin license gate
- `licensing/LicenseGate.java` — gates paid features behind license

These are the entire plugin surface. **No new classes unless audit forces
them.**

## Changes by layer

### Build layer

| File | Change |
|------|--------|
| `gradle.properties` | `pluginVersion` 1.0.3 → 1.0.4; `pluginSinceBuild` 252 (unchanged); `pluginUntilBuild` 253.\* → 263.*; `platformVersion` 2025.2 → 2025.3; **`gradleVersion` 9.1.0 → 9.4.1** (reconcile with wrapper) |
| `build.gradle.kts` | `java.toolchain.languageVersion` 21 → 25; **`alias(libs.plugins.ktlint)` added**; **`alias(libs.plugins.detekt)` added**; `pluginVerification.ides.select.types` `PyCharmProfessional`, channels `RELEASE`, sinceBuild 252, untilBuild 263.* |
| `gradle/libs.versions.toml` | `intelliJPlatform` 2.13.1 → 2.19.0 (or latest 2.x); add `[plugins]` entries for `ktlint` (use the official `org.jlleitschuh.gradle.ktlint` plugin, latest at Phase 1 start) and `detekt` (use the official `io.gitlab.arturbosch.detekt` plugin, latest at Phase 1 start) |
| `settings.gradle.kts` | `foojay-resolver-convention` version 1.0.0 → `>= 1.1.0` (for Java 25 metadata) |
| `gradle/wrapper/gradle-wrapper.properties` | **No change** — already 9.4.1; reconciled by `gradle.properties` update above |

### Plugin manifest

| File | Change |
|------|--------|
| `src/main/resources/META-INF/plugin.xml` | `<change-notes>` adds 1.0.4 entry summarizing platform range expansion; `<product-descriptor>` `release-version` bump (10 → 11) **AND `release-date` bump to actual build/upload date** |

### Source code

**Audit-driven changes only.** Phase 1 must verify (via commit log + grep)
that CRITICAL #3, #4, #6 are closed; only HIGH #6 remains.

**HIGH #6 fix — null-handling in `Jinja2DelimitersSettings.java`:**

| File:line | Defect | Fix |
|---|---|---|
| `:36` | `synchronized` on `getState()` is cargo-cult | Remove `synchronized`; rely on EDT-only contract per JetBrains docs |
| `:41-43` | `loadState` uses `XmlSerializerUtil.copyBean` which writes via reflection, bypassing setter null-checks | Replace `copyBean` with explicit `setXxx(state.getXxx())` calls inside `loadState` |
| `:48-83` | Getters have null-fallback (e.g., `blockStartString != null ? blockStartString : "{%"`); field defaults at `:21-28` already initialize correctly | Remove null-fallback from getters; rely on defaults |

**Cross-check against 2026.x deprecations:**

- `PersistentStateComponent` lifecycle annotations — unchanged in 2026.x
- `BasePlatformTestCase` API — unchanged
- `preFormatProcessor` / `postFormatProcessor` extension-point signatures
  — unchanged (verified against `api-changes-list-2025.html` and
  `api-changes-list-2026.html`)
- `applicationConfigurable` registration — unchanged
- `com.intellij.modules.python` module dependency — verify still exists
  in 2026.3 (Phase 1 check)

### License (`licensing/MarketplaceLicenseChecker.java`, `licensing/LicenseGate.java`)

**Silent-fallback removal checklist (this is the hard-fail contract):**

| File:line | Current behavior | Required fix |
|---|---|---|
| `MarketplaceLicenseChecker.java:121-124` | `isLicensed()` returns `null` when facade unavailable | Throw `LicenseUnavailableException` with actionable message |
| `MarketplaceLicenseChecker.java:139-158` | `requestLicense()` silently no-ops if actions missing | Throw on missing actions; surface user dialog |
| `MarketplaceLicenseChecker.java:195, 222` | `catch (Throwable ignored)` swallows ALL exceptions | At minimum log via `Logger.warn` with exception type; rethrow for hard-fail |
| `LicenseGate.java:13-15` | `isLicensedOrPending()` returns `true` when `licensed == null` | Return `false` (hard-fail in formatter path) |
| `LicenseGate.java:18-21` | `ensureLicensed()` treats `null` as `true` | Return `false`; let format processor throw |

**User-actionable error format (apply consistently):**

```
Your Jinja2 Custom Delimiters license could not be verified.

Reason: <network unreachable | token expired | marketplace endpoint moved | unknown>
Action: Visit https://plugins.jetbrains.com/plugin/<plugin-id> to renew
        or re-authenticate. Restart PyCharm after renewal.

(If this error persists, contact les@wedgwoodwebworks.com)
```

**Null-pending exception:** Per user decision (preserved from prior draft),
first-launch before license subsystem is ready stays **permissive** — only
confirmed license failures hard-fail. Document this carve-out in
`LicenseGate` Javadoc.

### Tests (`src/test/java/`)

**Existing tests:** adjust thread-safety tests if behavior changes from
HIGH #6 fix. Run `./gradlew test` after the source change.

**New tests required** (the spec's "smoke test" is necessary but
insufficient):

| Test | Why |
|---|---|
| `LicenseGate.isLicensedOrPending()` returns `false` when facade is `null` | Enforces hard-fail contract |
| `LicenseGate.ensureLicensed()` debounce — second call within 60s does not re-prompt | Existing `PROMPT_INTERVAL_MS = 60_000L` debounce has no test |
| `Jinja2DelimitersConfigurable.apply()` throws `ConfigurationException` on license failure | Existing throw path (commit `e0ae8af`) untested |
| `Jinja2DelimitersConfigurable.createComponent()` returns unlicensed panel when not licensed | Existing panel swap untested |
| `CustomJinja2PreFormatProcessor.process` round-trip | Audit HIGH #4 explicit ask; entire formatter contract untested |
| `CustomJinja2PostFormatProcessor.processElement` round-trip | Mirror of above |
| `CustomJinja2PostFormatProcessor.processText` round-trip | Mirror of above |
| `DelimiterConversionUtil` empty-delimiter safety | `String.replace("", ...)` Java 9+ no-op behavior worth pinning |
| `Jinja2DelimitersSettings.loadState` null-resilience | After HIGH #6 fix, setter path should reject null |
| `MarketplaceLicenseChecker.isKeyValid` and `isLicenseServerStampValid` | License crypto untested; vectors for valid/expired stamp |

### Docs

| File | Change |
|------|--------|
| `CHANGELOG.md` | **Add** `[1.0.4]` entry under `[Unreleased]`; keep `[Unreleased]` header for next release. Note: PyCharm 2026.1–2026.3 support, Java 25 toolchain, hard-fail license behavior. |
| `README.md` | Java badge: `21+` → `25+`. Requirements line: "PyCharm Professional 2025.2 – 2026.x". |
| `AGENTS.md` | Java 25 prerequisite prominent; cert renewal cadence (annual token / 3-year cert); note `foojay-resolver-convention` auto-provisioning; note `MAHAVISHNU_PROJECT_ROOTS` registration requirement for `kotlin_bump_version`. |
| `RELEASING.md` (NEW) | Document the 11-phase release process (per DevOps review finding 9.4). Captures the canonical release flow so next release doesn't start from scratch. |

### Repo hygiene

| Action | Reason |
|--------|--------|
| Delete `.github/workflows/*` (3 files: `build.yml`, `release.yml`, `run-ui-tests.yml`) | Provider-specific CI; replaced by crackerjack |
| Delete `.github/dependabot.yml` | After workflow deletion, `github-actions` ecosystem is a no-op; `gradle` ecosystem is replaced by crackerjack — whole file is dead config |
| Delete `codecov.yml` (repo root) | `codecov/codecov-action@v6` upload is gone with `build.yml`; codecov gets no new data — file is misleading dead config |
| Keep `.github/FUNDING.yml` | GitHub platform parses this for sponsorship display; not a CI surface |
| Keep `.github/ISSUE_TEMPLATE/`, `.github/PULL_REQUEST_TEMPLATE.md` if present | Platform features, not CI |
| Add `.gitignore` entries | **REQUIRED — the prior spec incorrectly claimed these were covered.** Add: `.gradle/`, `.intellijPlatform/sandbox/`, `.jbeval/`, `.crackerjack/`, `.crackerjack_cache/`, `.oneiric_cache/`, `build/distributions/`, `.bak` |
| **Commit pattern warning:** per `bodai-canonical-gitignore-runtime-artifacts.md`, do NOT use `git commit -- <pathspec>` when deleting `.github/workflows/` AND updating `.gitignore` in the same commit. Use `git add .gitignore .github/workflows/` + plain `git commit -m "..."`. |

### Audit surface (new)

| File | Change |
|------|--------|
| `.crackerjack.toml` (NEW, repo root) | Selects `kotlin` adapter; emits `kotlin.ktlint`, `kotlin.detekt`, `kotlin.test` hooks (these are the **crackerjack hook names**, not the Gradle task names). `fail-strict` is the default behavior (any non-zero exit aborts the run); no explicit config needed. |

## Data flow & build flow

### Dev-time audit pipeline

```
crackerjack run
  └─ KotlinAdapter.detect (sees build.gradle.kts)
       └─ GradleTaskProbe.has_task("ktlintCheck")  → emit kotlin.ktlint hook
       └─ GradleTaskProbe.has_task("detekt")       → emit kotlin.detekt hook
       └─ GradleTaskProbe.has_task("test")         → emit kotlin.test hook
            └─ ./gradlew ktlintCheck   (fail-strict; default behavior)
            └─ ./gradlew detekt        (fail-strict)
            └─ ./gradlew test          (fail-strict)
```

**Phase 2 prerequisite:** ktlint and detekt Gradle plugins MUST be applied
(via `alias(libs.plugins.ktlint)` and `alias(libs.plugins.detekt)` in
`build.gradle.kts`) before `crackerjack run` emits non-skipped hooks.

### Build pipeline

```
./gradlew build
  ├─ compileJava (Java 25 toolchain, Azul Zulu via foojay)
  ├─ test (JUnit 4.13.2, IntelliJ Platform test framework)
  ├─ verifyPlugin
  └─ buildPlugin
       └─ intellijPlatform { pluginVerification.ides.select }
            ├─ PyCharmProfessional 2025.2 (build 252)
            ├─ PyCharmProfessional 2025.3 (build 253)
            ├─ PyCharmProfessional 2026.1 (build 261)
            ├─ PyCharmProfessional 2026.2 (build 262)
            └─ PyCharmProfessional 2026.3 (build 263) — IF in RELEASE channel
```

### Publish pipeline (manual, push-consent gated)

```
operator: confirm "git push consent" to bodai/mahavishnu MCP
mcp__crackerjack__kotlin_bump_version(level="patch", project_root=..., dry_run=true)
  └─ KotlinLifecycle
       ├─ read version from GradlePropertiesVersionSource
       ├─ verify proposed: 1.0.3 → 1.0.4
       └─ print plan, do NOT execute

operator: confirm dry-run matches expectation
mcp__crackerjack__kotlin_bump_version(level="patch", project_root=..., dry_run=false, release=false)
  └─ KotlinLifecycle
       ├─ write 1.0.4 to gradle.properties
       ├─ git commit --allow-empty -m "bump: 1.0.4"  (commit content is NOT empty — file is staged)
       ├─ git tag -a v1.0.4 -m "..."
       ├─ git push origin v1.0.4  (operator-confirmed; per feedback-bodai-push-is-user-controlled.md)
       └─ on any failure: rollback per `crackerjack/adapters/kotlin/lifecycle.py:155-201`

operator: ./gradlew publishPlugin
  ├─ patchChangelog (auto-renders 1.0.4 entry from CHANGELOG.md)
  └─ POST to plugins.jetbrains.com
       ├─ requires PUBLISH_TOKEN
       ├─ requires CERTIFICATE_CHAIN + PRIVATE_KEY + PRIVATE_KEY_PASSWORD
       └─ Marketplace re-runs Plugin Verifier server-side as final gate

operator: cp build/distributions/*.zip ~/.mahavishnu/artifacts/jinja2-custom-delimiters/1.0.4/
operator: shasum -a 256 ~/.mahavishnu/artifacts/jinja2-custom-delimiters/1.0.4/*.zip
```

### MCP auth preflight (Phase 9 prerequisite)

```
# Required environment
export MAHAVISHNU_AUTH_ENABLED=true
export MAHAVISHNU_JWT_SECRET=<secret>
# Allowlist registration (one-time, idempotent)
# Project root must be registered before mcp__crackerjack__kotlin_bump_version accepts the call
```

### Cross-pipeline invariants

- Crackerjack and Gradle don't share state — each owns its own hooks
- Both must pass before `publishPlugin`
- Plugin Verifier failures are the only kind that block Marketplace upload
- Version bump is reversible via `KotlinLifecycle` rollback contract
- **`git push` requires explicit operator consent** per
  `feedback-bodai-push-is-user-controlled.md` — never auto-pushed by
  crackerjack without confirmation

## Error handling & rollback

### Failure tiers

| Tier | Failure | Detection | Recovery |
|------|---------|-----------|----------|
| 1 | Crackerjack hook fails (ktlint / detekt / test) | stderr + non-zero exit | Edit code, re-run; no state to undo |
| 2 | `./gradlew compileJava` fails | stderr | Edit source; no state to undo |
| 2 | `./gradlew test` fails | stderr + report XML | Fix code or test; `build/` is gitignored |
| 2 | `./gradlew verifyPlugin` fails | stderr | Structural issue; must fix before continuing |
| 3 | Plugin Verifier rejects against a specific PyCharm build | exit code + report in `build/reports/pluginVerifier/` | **Manually inspect the HTML report** (don't trust exit code alone); drop that build from matrix, fix the deprecation, or raise untilBuild ceiling |
| 3 | Plugin Verifier reports warnings (not failures) | HTML report warnings | Read report; address any deprecation hints even if exit=0 |
| 4 | `publishPlugin` 401/403 | HTTP response | Re-source `PUBLISH_TOKEN`; re-run |
| 4 | `publishPlugin` signature rejection | HTTP response | Re-check `CERTIFICATE_CHAIN` + `PRIVATE_KEY` env vars |
| 4 | Marketplace re-verification rejects after upload | Marketplace email + API | Yank via Marketplace admin; release as `1.0.5` |
| 5 | `kotlin_bump_version` push fails | exit code | Auto-rollback per `KotlinLifecycle` |
| 5 | `MarketplaceLicenseChecker` fails (license API drift, network, cert) | exception | **Hard-fail** with user-actionable error; user must renew / re-auth / contact support |

### Specific risks

1. **`intelliJPlatform=2.13.1` is stale.** Will not resolve build 263.
   Mitigation: bump to 2.19.0 (or latest 2.x).

1. **Java 21 → 25 toolchain migration.** Build environments without
   Azul 25 fail. Mitigation: `foojay-resolver-convention >= 1.1.0`
   auto-downloads. Document Java 25 as hard prerequisite in AGENTS.md.

1. **Gradle wrapper version drift** (9.1.0 vs 9.4.1). The
   `tasks.wrapper` block will silently downgrade the wrapper if invoked.
   Mitigation: bump `gradleVersion` to 9.4.1 to match.

1. **Existing 2025.2 user breakage.** `sinceBuild=252` is preserved, so
   the plugin remains installable. But `untilBuild=263.*` means newer
   IDEs refuse it. Mitigation: Plugin Verifier matrix covers the full
   range.

1. **License API drift.** If 2026.x deprecates the v1 auth flow, paid
   users hit a loud error (per hard-fail contract). Mitigation:
   hard-fail with actionable message. User-driven audit via paid users
   effectively becomes the smoke test for the new endpoint.

1. **2026.3 not in RELEASE channel yet.** Mitigation: drop 2026.3 from
   matrix; ship narrower release; add in 1.0.5.

1. **Marketplace signing cert expiry.** Operational, not technical.
   Document renewal cadence in AGENTS.md.

1. **Pre-existing tech-debt (`HIGH #6`).** Null-handling in
   `Jinja2DelimitersSettings`/`LicenseGate` may have masked bugs.
   Mitigation: full HIGH #6 fix as part of this update.

1. **`MarketplaceLicenseChecker` `catch (Throwable ignored)` lines 195,
   222.** Silent-swallowing is the exact anti-pattern the hard-fail
   contract forbids. Mitigation: replace with logger + rethrow.

1. **Configuration cache interaction.** `org.gradle.configuration-cache=true`

   - `org.gradle.caching=true` may interact poorly with
     `intelliJPlatform` 2.19.0. Mitigation: after the bump, run
     `./gradlew help --configuration-cache`; if it fails, disable and
     document.

### Release rollback strategy

If `1.0.4` ships and breaks:

- Hotfix branch → `1.0.5` → same pipeline
- Or revert to `1.0.3` via Marketplace admin panel

`gradle.properties` is the single source of truth for the version; any
rollback is a single-line edit + standard bump/push/publish.

## Testing & validation — phase gates

### Phase 0 — Toolchain prep (NEW)

- Bump `intelliJPlatform` 2.13.1 → 2.19.0 in `gradle/libs.versions.toml`
- Bump `gradleVersion` 9.1.0 → 9.4.1 in `gradle.properties` (reconcile
  with wrapper)
- Bump `foojay-resolver-convention` 1.0.0 → 1.1.0+ in
  `settings.gradle.kts`
- Run `./gradlew help --configuration-cache` — must succeed
- Gate: clean baseline build (Java 25 toolchain resolved via foojay)

### Phase 1 — Audit ingestion (no code changes)

- Read `AUDIT-SUMMARY.md`, `CRITICAL-AUDIT-REPORT-2025.md`,
  `FIXES-COMPLETED.md`, `TEST-FIXES-SUMMARY.md`
- Read full commit log since v1.0.1
- **Verify:** CRITICAL #3, #4 closed (commits `e0ae8af`, `2bbc0f8`);
  HIGH #6 still open
- Output: confirmed list of remaining tech-debt items, mapped to
  files/lines, severity ranked
- If any closed-claimed items are still open → escalate
- If `com.intellij.modules.python` module does not exist in 2026.x → add
  to Risk #4 and decide on matrix scope

### Phase 2 — Repo hygiene (NEW, moved up from Phase 4g)

- Add `.gradle/`, `.intellijPlatform/sandbox/`, `.jbeval/`,
  `.crackerjack/`, `.crackerjack_cache/`, `.oneiric_cache/` to `.gitignore`
- Delete `.github/workflows/*`, `.github/dependabot.yml`, `codecov.yml`
- Keep `.github/FUNDING.yml`
- Commit pattern: `git add .gitignore .github/workflows/` + plain
  `git commit -m "..."` (do not use `git commit -- <pathspec>` per
  `bodai-canonical-gitignore-runtime-artifacts.md`)
- Gate: `git status` clean; `ls .github/` shows only `FUNDING.yml`

### Phase 3 — Crackerjack wire-up

- Add `ktlint` + `detekt` versions to `[plugins]` block of
  `gradle/libs.versions.toml`
- Add `alias(libs.plugins.ktlint)` and `alias(libs.plugins.detekt)` to
  `build.gradle.kts`
- Create `.crackerjack.toml` at plugin root
- Run `mcp__crackerjack__kotlin_list_hooks(project_root=...)` first;
  assert response contains all three hook names (`kotlin.ktlint`,
  `kotlin.detekt`, `kotlin.test`)
- Then `mcp__crackerjack__crackerjack_run(...)`; assert exit 0 AND
  warning-free (no `Skipping ... task absent` logs)
- Gate: 3 hooks emit, all pass

### Phase 4 — Implementation (the actual work)

- 4a: Bump Java toolchain 21 → 25 in `build.gradle.kts`
- 4b: Edit `plugin.xml` — `<product-descriptor>` `release-version` 10 → 11
  and `release-date` to build date; `<change-notes>` adds 1.0.4 entry
- 4c: Apply HIGH #6 fixes — remove synchronized on `getState()`,
  replace `copyBean` with explicit setters, remove null-fallbacks in
  getters
- 4d: License gate silent-fallback removal — per the 5-row checklist
  in the License section above
- 4e: Add 8+ new tests per the Tests table
- 4f: Update docs — CHANGELOG.md (add `[1.0.4]`), README.md (Java badge,
  requirements), AGENTS.md (Java 25, cert renewal, MCP allowlist), new
  RELEASING.md (11-phase process)
- Gate per sub-phase: `./gradlew test` passes; `crackerjack run` exits 0

### Phase 5 — Plugin Verifier run (the real gate)

- `./gradlew verifyPlugin` after Phase 4 completes
- Reads `pluginVerification.ides.select` and runs against:
  - PyCharm 2025.2 (build 252)
  - PyCharm 2025.3 (build 253)
  - PyCharm 2026.1 (build 261)
  - PyCharm 2026.2 (build 262)
  - PyCharm 2026.3 (build 263) — **if RELEASE channel exists**
- Each build produces a report in `build/reports/pluginVerifier/`
- **Manually inspect each report's HTML for warnings** (not just failures)
- Gate: zero failures AND no deprecation warnings across all builds
- If build 263 not in RELEASE channel: drop it; ship 2025.2→2026.2; add
  2026.3 in 1.0.5

### Phase 6 — Manual sandbox QA

- `./gradlew runIdeForUiTests`
- Manual checklist:
  - Open `.j2` file with `[[ ]]` delimiters
  - Settings → Jinja2 Custom Delimiters → configure `[%`, `[[`, `[#`
  - Save settings; reload file
  - Run formatter (Ctrl+Alt+L); confirm delimiters preserved
  - Restart IDE; confirm settings persist
  - **Force license check to fail** (mock or expired token); confirm
    hard-fail with clear actionable error
- Gate: all manual checks pass

### Phase 7 — Pack & publish dry-run + archive

- `./gradlew buildPlugin` — produces `build/distributions/*.zip`
- Inspect `.zip` contents; confirm `META-INF/plugin.xml` has new
  `<change-notes>` and that `<idea-version>` reflects `sinceBuild=252, untilBuild=263.*`
- Archive `.zip` out-of-repo:
  ```bash
  mkdir -p ~/.mahavishnu/artifacts/jinja2-custom-delimiters/1.0.4
  cp build/distributions/*.zip ~/.mahavishnu/artifacts/jinja2-custom-delimiters/1.0.4/
  shasum -a 256 ~/.mahavishnu/artifacts/jinja2-custom-delimiters/1.0.4/*.zip
  ```
- **DO NOT run `publishPlugin`**

### Phase 8 — Pre-publish verification

- `crackerjack run` — exit 0, warning-free
- `./gradlew test` — exit 0
- `./gradlew verifyPlugin` — exit 0 (re-run; if 2 consecutive runs fail
  on the same build, drop that build from matrix)
- `git status` clean; all changes committed
- Tag not yet created

### Phase 9 — MCP auth preflight + version bump

- Verify environment:
  ```bash
  export MAHAVISHNU_AUTH_ENABLED=true
  export MAHAVISHNU_JWT_SECRET=<secret>
  ```
- Verify `/Users/les/Projects/jinja2-custom-delimiters` is registered
  in `MAHAVISHNU_PROJECT_ROOTS`
- **Operator gives explicit push consent** per
  `feedback-bodai-push-is-user-controlled.md` (do NOT auto-push)
- `mcp__crackerjack__kotlin_bump_version(level="patch", project_root=..., dry_run=true)` first
- Verify proposed: `1.0.3 → 1.0.4`; tag will be `v1.0.4`
- Re-run with `dry_run=false, release=false`
- Verify tag pushed; verify `gradle.properties` reads `pluginVersion=1.0.4`
- Fallback: if `kotlin_bump_version` MCP tool is unavailable, manual
  `git tag -a v1.0.4 -m "..."` + manual `git push origin v1.0.4`

### Phase 10 — Final publish (manual)

- `cd /Users/les/Projects/jinja2-custom-delimiters`
- `./gradlew publishPlugin`
- Watch for HTTP responses
- Confirm in JetBrains Marketplace admin panel: `1.0.4` listed,
  `sinceBuild=252, untilBuild=263.*` (verify Marketplace-side
  compatibility range matches)

### Phase 11 — Post-publish first-week monitor (NEW)

- Within 7 days of publish: check GitHub Issues for any critical
  filed against `1.0.4`
- Verify Marketplace install: open PyCharm 2026.3 → Settings → Plugins
  → Marketplace → search "Jinja2 Custom Delimiters" → confirm `1.0.4`
  is the latest, supports 2026.3
- If critical issues filed: triage → hotfix `1.0.5` → same pipeline

## Risks (called out explicitly)

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| `intelliJPlatform=2.13.1` cannot resolve build 263 | **High** | **High** | Bump to 2.19.0 |
| Gradle wrapper drift (9.1.0 vs 9.4.1) | High | Medium | Reconcile `gradleVersion` |
| foojay 1.0.0 missing Java 25 metadata | Medium | High | Bump to ≥ 1.1.0 |
| License API drift in 2026.x | Medium | High (paid users) | Loud hard-fail UX |
| Open tech-debt (`HIGH #6`) | High | Medium | Apply fix in Phase 4c |
| Java 25 unavailable on dev machines | Low | Medium | `foojay-resolver-convention` auto-download |
| Cert expiry mid-cycle | Low | High (publish blocks) | Document renewal in AGENTS.md |
| Verifier rejects against 2026.2 specifically | Medium | Low | Drop 2026.2 from matrix; ship narrower release |
| 2026.3 not in RELEASE channel yet | Medium | Low | Drop from matrix; add in 1.0.5 |
| Marketplace upload rejected post-publish | Low | High | Yank via admin panel; release as 1.0.5 |
| `.gitignore` doesn't cover runtime artifacts | **High** | **High** | Add in Phase 2 |
| Crackerjack hooks silently skip without Gradle plugins | **High** | **High** | Apply ktlint/detekt plugins in Phase 3 prerequisite |
| Configuration cache breaks after `intelliJPlatform` bump | Low | Medium | Test in Phase 0; disable + document if needed |

## Open questions

None at design time. All decisions captured.

## Success criteria

1. `crackerjack run` exits 0 with 3 hooks emitting (no `task absent`
   warnings)
1. `./gradlew test` exits 0 (including the 8+ new tests)
1. `./gradlew verifyPlugin` exits 0 against all available PyCharm
   builds (252, 253, 261, 262, [263 if GA])
1. No deprecation warnings in any Verifier HTML report
1. `./gradlew buildPlugin` produces a `.zip` with manifest reflecting
   new version, new `release-date`, and platform range
1. `.zip` archived to `~/.mahavishnu/artifacts/jinja2-custom-delimiters/1.0.4/`
1. Manual sandbox QA passes all 6 checklist items, including hard-fail
   license UX
1. HIGH #6 fixes landed (no synchronized on `getState()`, setters used
   in `loadState`, no null-fallbacks in getters)
1. License silent-fallback paths removed; hard-fail UX verified
1. `git tag v1.0.4` is pushed (with operator consent);
   `gradle.properties` reads `pluginVersion=1.0.4`
1. `./gradlew publishPlugin` returns 2xx; plugin appears in
   Marketplace with PyCharm 2025.2 → 2026.x supported
1. Phase 11 first-week check finds no critical issues filed against
   `1.0.4`

## Reference

- Source brainstorm: this conversation, 2026-09-21
- Plugin current state: v1.0.3, last commit 2026-01-19
- Audit documents: `AUDIT-SUMMARY.md`, `CRITICAL-AUDIT-REPORT-2025.md`,
  `FIXES-COMPLETED.md`, `TEST-FIXES-SUMMARY.md` in target repo
- Crackerjack Kotlin adapter: `/Users/les/Projects/crackerjack/crackerjack/adapters/kotlin/`
  - Hook names: `hooks.py:70-96`
  - Lifecycle: `lifecycle.py:155-201`
  - Version source: `version_source.py:39`
- Crackerjack MCP tools:
  - `mcp__crackerjack__kotlin_bump_version` (`language_tools.py:262`)
  - `mcp__crackerjack__kotlin_list_hooks`
  - `mcp__crackerjack__crackerjack_run`
- IntelliJ Platform Gradle Plugin: 2.19.0 (14 Sep 2026) — confirmed via
  release index
- JetBrains Plugin SDK Incompatible Changes 2025/2026: no changes to
  `LicensingFacade`, `PreFormatProcessor`, `PostFormatProcessor`,
  `product-descriptor`
- Memory:
  - `feedback-bodai-no-provider-specific-ci.md`
  - `feedback-bodai-push-is-user-controlled.md`
  - `bodai-canonical-gitignore-runtime-artifacts.md`

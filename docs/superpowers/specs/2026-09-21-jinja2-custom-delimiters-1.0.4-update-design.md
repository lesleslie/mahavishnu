# jinja2-custom-delimiters 1.0.4 Update — Design Spec

**Date:** 2026-09-21
**Status:** Draft — pending subagent review
**Target repo:** `/Users/les/Projects/jinja2-custom-delimiters`
**Working location:** main checkout of target repo (per user selection)
**Source:** brainstorming session 2026-09-21

---

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

## Goals

1. **Make the plugin installable on PyCharm 2026.1 / 2026.2 / 2026.3** without
   breaking 2025.2 / 2025.3 users. `sinceBuild=252` stays; `untilBuild`
   opens to `263.*`.
2. **Bump Java toolchain to 25** (required by 2026.2 platform).
3. **Wire crackerjack as the audit surface.** Add `.crackerjack.toml` at the
   plugin root, run ktlint + detekt + Gradle test through the Kotlin
   adapter hooks.
4. **Verify the plugin actually works on real PyCharm builds** by running
   `pluginVerification.ides.select` against all 5 release builds (252, 253,
   261, 262, 263).
5. **Replace GitHub Actions with crackerjack.** Delete `.github/workflows/`,
   keep `.github/FUNDING.yml` (GitHub platform parses this for sponsorship
   display — not a CI surface).
6. **Sweep the pre-existing tech-debt** from `AUDIT-SUMMARY.md` (Dec 2025,
   2 open critical issues at v1.0.1 — verify status before starting).
7. **Verify license-check behavior is hard-fail** in the new platform range
   (paid plugin: license API drift must surface loudly, not silently).

## Non-goals (explicit exclusions)

- **No new features.** The delimiter handling, settings UI, formatter
  integration, and license gate all behave identically. We're widening the
  install matrix and updating tooling, not changing the plugin surface.
- **No CI config added.** Crackerjack is the audit surface. No GitHub
  Actions, GitLab CI, CircleCI, or any other provider-specific CI file.
- **No automated publish.** `./gradlew publishPlugin` stays as a manual
  command with credentials in env vars (`PUBLISH_TOKEN`, `CERTIFICATE_CHAIN`,
  `PRIVATE_KEY`, `PRIVATE_KEY_PASSWORD`).
- **No worktree creation.** Work happens in the main checkout of
  `/Users/les/Projects/jinja2-custom-delimiters`.
- **No Gradle wrapper bump.** `9.1.0` is current and works for 2026.x.
- **No `cli.py` / CLI surface.** The plugin is a GUI-only IntelliJ plugin;
  the existing pre/post format processors and settings UI are the entire
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
| `gradle.properties` | `pluginVersion` 1.0.3 → 1.0.4; `pluginSinceBuild` 252 (unchanged); `pluginUntilBuild` 253.* → 263.*; `platformVersion` 2025.2 → 2025.3 |
| `build.gradle.kts` | `java.toolchain.languageVersion` 21 → 25; `pluginVerification.ides.select` types `PyCharmProfessional`, channels `RELEASE`, sinceBuild 252, untilBuild 263.* |
| `gradle/libs.versions.toml` | `intelliJPlatform` 2.13.1 (verify latest 2.13.x patch; don't bump major); add `ktlint` and `detekt` versions only if `.crackerjack.toml` needs them in catalog |

### Plugin manifest

| File | Change |
|------|--------|
| `src/main/resources/META-INF/plugin.xml` | `<change-notes>` adds 1.0.4 entry summarizing platform range expansion; `<product-descriptor>` release-version bump (10 → 11) |

### Source code

**Audit-driven changes only.** Read `AUDIT-SUMMARY.md`,
`CRITICAL-AUDIT-REPORT-2025.md`, `FIXES-COMPLETED.md`,
`TEST-FIXES-SUMMARY.md`, and the v1.0.2 / v1.0.3 commit log first. Identify
the 2 critical issues still open from Dec 2025. For each, decide:
- If it touches an API deprecated in 2026.x → fix as part of this update
- If it's a stylistic issue → fix
- If it requires architectural change → escalate to a separate spec

Specific code areas to audit against 2026.x deprecations:
- `PersistentStateComponent` lifecycle annotations
- `BasePlatformTestCase` API (test framework)
- `preFormatProcessor` / `postFormatProcessor` extension point signatures
- `applicationConfigurable` registration

### License

`licensing/MarketplaceLicenseChecker.java`:
- Verify the licensing endpoint URL hasn't changed
- Verify the request signature/headers are still accepted by the current
  Marketplace auth flow
- **Confirm hard-fail behavior** when the license check returns 401/403/5xx
  (per user decision 2026-09-21)
- Add a user-actionable error message that includes:
  - Why the check failed (network / token expired / endpoint moved)
  - URL the user should visit (https://plugins.jetbrains.com/...)
  - Token renewal / re-auth steps

### Tests

`src/test/java/`:
- Adjust thread-safety tests if `PersistentStateComponent` API changed
- Add a smoke test for the hard-fail license path (mock 401/403)
- Verify `BasePlatformTestCase` imports still resolve for the new platform

### Docs

| File | Change |
|------|--------|
| `CHANGELOG.md` | Move `[Unreleased]` → `[1.0.4]` entry; note platform range expansion |
| `README.md` | "Requirements" line: PyCharm 2025.2–2026.x, Java 25 |
| `AGENTS.md` | Document Java 25 prerequisite; add cert renewal reminder |

### Repo hygiene

| Action | Reason |
|--------|--------|
| Delete `.github/workflows/*` | Provider-specific CI; replaced by crackerjack per `feedback-bodai-no-provider-specific-ci.md` |
| Keep `.github/FUNDING.yml` | GitHub platform parses this for sponsorship display; not a CI surface |
| Keep `.github/ISSUE_TEMPLATE/`, `.github/PULL_REQUEST_TEMPLATE.md` if present | Platform features, not CI |
| Confirm `.gitignore` covers `build/`, `.gradle/`, `.intellijPlatform/sandbox/`, `.jbeval/` | Already covered per `bodai-canonical-gitignore-runtime-artifacts.md` |

### Audit surface (new)

| File | Change |
|------|--------|
| `.crackerjack.toml` (NEW, repo root) | Selects `kotlin` adapter; hooks `ktlintCheck`, `detektCheck`, `test`; fail-strict on all three |

## Data flow & build flow

### Dev-time audit pipeline

```
crackerjack run
  └─ KotlinAdapter.detect (sees build.gradle.kts)
       └─ GradleTaskProbe.has_task("ktlintCheck")  → emit hook
       └─ GradleTaskProbe.has_task("detektCheck")  → emit hook
       └─ GradleTaskProbe.has_task("test")         → emit hook
            └─ ./gradlew ktlintCheck   (fail-strict)
            └─ ./gradlew detektCheck   (fail-strict, per user decision)
            └─ ./gradlew test          (fail-strict)
```

### Build pipeline

```
./gradlew build
  ├─ compileJava (Java 25 toolchain)
  ├─ test (JUnit 4.13.2, IntelliJ Platform test framework)
  ├─ verifyPlugin
  └─ buildPlugin
       └─ intellijPlatform { pluginVerification.ides.select }
            ├─ PyCharmProfessional 2025.2 (build 252)
            ├─ PyCharmProfessional 2025.3 (build 253)
            ├─ PyCharmProfessional 2026.1 (build 261)
            ├─ PyCharmProfessional 2026.2 (build 262)
            └─ PyCharmProfessional 2026.3 (build 263)
```

### Publish pipeline (manual)

```
./gradlew publishPlugin
  ├─ patchChangelog
  └─ POST to plugins.jetbrains.com
       ├─ requires PUBLISH_TOKEN
       ├─ requires CERTIFICATE_CHAIN + PRIVATE_KEY + PRIVATE_KEY_PASSWORD
       └─ Marketplace re-runs Plugin Verifier server-side as final gate
```

### Version-bump driver

```
mcp__crackerjack__kotlin_bump_version(level="patch", project_root=..., dry_run=true)
  └─ KotlinLifecycle
       ├─ read version from GradlePropertiesVersionSource
       ├─ write new version to gradle.properties
       ├─ git commit --allow-empty -m "bump: 1.0.4"
       ├─ git tag -a v1.0.4 -m "..."
       └─ git push origin v1.0.4
       └─ on any failure: rollback per `crackerjack/adapters/kotlin/lifecycle.py`
```

### Cross-pipeline invariants

- Crackerjack and Gradle don't share state — each owns its own hooks
- Both must pass before `publishPlugin`
- Plugin Verifier failures are the only kind that block Marketplace upload
- Version bump is reversible via the `KotlinLifecycle` rollback contract

## Error handling & rollback

### Failure tiers

| Tier | Failure | Detection | Recovery |
|------|---------|-----------|----------|
| 1 | Crackerjack hook fails | stderr + non-zero exit | Edit code, re-run; no state to undo |
| 2 | `./gradlew compileJava` fails | stderr | Edit source; no state to undo |
| 2 | `./gradlew test` fails | stderr + report XML | Fix code or test; `build/` is gitignored |
| 2 | `./gradlew verifyPlugin` fails | stderr | Structural issue; must fix before continuing |
| 3 | Plugin Verifier rejects against a specific PyCharm build | exit code + report in `build/reports/pluginVerifier/` | Drop that build from matrix (ship narrower release), fix the deprecation, or raise untilBuild ceiling |
| 4 | `publishPlugin` 401/403 | HTTP response | Re-source `PUBLISH_TOKEN`; re-run |
| 4 | `publishPlugin` signature rejection | HTTP response | Re-check `CERTIFICATE_CHAIN` + `PRIVATE_KEY` env vars |
| 4 | Marketplace re-verification rejects after upload | Marketplace email + API | Yank via Marketplace admin; release as `1.0.5` |
| 5 | `kotlin_bump_version` push fails | exit code | Auto-rollback per `KotlinLifecycle` |
| 5 | `MarketplaceLicenseChecker` fails (license API drift) | HTTP response | **Hard-fail** in formatter with user-actionable error message |

### Specific risks

1. **Java 21 → 25 toolchain migration.** Build environments without Azul25
   fail. Mitigation: `foojay-resolver-convention` (already pinned to 1.0.0)
   auto-downloads. Document Java 25 as hard prerequisite in AGENTS.md.

2. **Existing 2025.2 user breakage.** `sinceBuild=252` is preserved, so the
   plugin remains installable. But `untilBuild=263.*` means newer IDEs
   refuse it. Mitigation: Plugin Verifier matrix covers the full range.

3. **License API drift.** If 2026.x deprecates the v1 auth flow, paid
   users hit a loud error. Mitigation: hard-fail with actionable message
   (per user decision). User-driven audit via paid users effectively
   becomes the smoke test for the new endpoint.

4. **Marketplace signing cert expiry.** Operational, not technical.
   Document renewal in AGENTS.md.

5. **Pre-existing tech-debt bleeding through.** 2 critical issues open from
   Dec 2025 may touch APIs deprecated in 2026.x. Mitigation: Phase 1
   audit-reading is mandatory before any code edits.

### Release rollback strategy

If `1.0.4` ships and breaks:
- Hotfix branch → `1.0.5` → same pipeline
- Or revert to `1.0.3` via Marketplace admin panel

`gradle.properties` is the single source of truth for the version; any
rollback is a single-line edit + standard bump/push/publish.

## Testing & validation — phase gates

### Phase 1 — Audit ingestion (no code changes)

- Read `AUDIT-SUMMARY.md`, `CRITICAL-AUDIT-REPORT-2025.md`,
  `FIXES-COMPLETED.md`, `TEST-FIXES-SUMMARY.md`
- Read full commit log since v1.0.1
- Output: verified list of open tech-debt items, mapped to files/lines, with
  severity ranking
- If open critical issues touch APIs deprecated in 2026.x → expand scope;
  otherwise proceed

### Phase 2 — Crackerjack wire-up (audit-only)

- Create `.crackerjack.toml` at plugin root
- Run `crackerjack run` against current state
- Confirm ktlint/detekt/test pass on existing code
- If any fails, fix as part of Phase 4 (tech-debt sweep)
- Gate: `crackerjack run` exits 0

### Phase 3 — Local build verification (baseline)

- `./gradlew build` against current 1.0.3 code with Java 21 toolchain
- Confirms starting point is clean before edits
- `./gradlew runIde` smoke-launch — does the plugin load in sandbox?
- Gate: clean build + IDE launches + plugin visible in Settings panel

### Phase 4 — Implementation (the actual work)

- 4a: Edit gradle config
- 4b: Edit plugin.xml
- 4c: Edit Java sources (driven by Phase 1 findings)
- 4d: Update license checker (hard-fail error UX)
- 4e: Update tests
- 4f: Update docs
- 4g: Delete `.github/workflows/`, keep `FUNDING.yml`
- Gate per sub-phase: `./gradlew test` passes after each

### Phase 5 — Plugin Verifier run (the real gate)

- `./gradlew verifyPlugin` after Phase 4 completes
- Reads `pluginVerification.ides.select` and runs against:
  - PyCharm 2025.2 (build 252)
  - PyCharm 2025.3 (build 253)
  - PyCharm 2026.1 (build 261)
  - PyCharm 2026.2 (build 262)
  - PyCharm 2026.3 (build 263)
- Each build produces a report in `build/reports/pluginVerifier/`
- Gate: zero failures across all 5 builds

### Phase 6 — Manual sandbox QA

- `./gradlew runIdeForUiTests`
- Manual checklist:
  - Open `.j2` file with `[[ ]]` delimiters
  - Settings → Jinja2 Custom Delimiters → configure `[%`, `[[`, `[#`
  - Save settings; reload file
  - Run formatter (Ctrl+Alt+L); confirm delimiters preserved
  - Restart IDE; confirm settings persist
  - Force license check to fail (mock or expired token); confirm hard fail
    with clear error
- Gate: all manual checks pass

### Phase 7 — Pack & publish dry-run

- `./gradlew buildPlugin` — produces `build/distributions/*.zip`
- Inspect `.zip` contents; confirm `META-INF/plugin.xml` has new
  `<change-notes>` and `<idea-version>` aligns
- **DO NOT run `publishPlugin`**

### Phase 8 — Pre-publish verification

- `crackerjack run` — exit 0
- `./gradlew test` — exit 0
- `./gradlew verifyPlugin` — exit 0 (re-run; sometimes flaky)
- `git status` clean; all changes committed
- Tag not yet created

### Phase 9 — Version bump via MCP

- `mcp__crackerjack__kotlin_bump_version(level="patch", project_root=..., dry_run=true)` first
- Verify proposed version: `1.0.3 → 1.0.4`
- Re-run with `dry_run=false`
- Verify tag pushed; verify `gradle.properties` reflects `1.0.4`

### Phase 10 — Final publish (manual)

- `cd /Users/les/Projects/jinja2-custom-delimiters`
- `./gradlew publishPlugin`
- Watch for HTTP responses
- Confirm in JetBrains Marketplace admin panel

## Risks (called out explicitly)

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Open tech-debt touches 2026.x-deprecated APIs | Medium | Medium | Phase 1 audit reading |
| License API drift in 2026.x | Medium | High (paid users) | Loud hard-fail UX |
| Java 25 unavailable on dev machines | Low | Medium | `foojay-resolver-convention` auto-download |
| Cert expiry mid-cycle | Low | High (publish blocks) | Document renewal in AGENTS.md |
| Verifier rejects against2026.2 specifically | Medium | Low | Drop2026.2 from matrix; ship narrower release |
| Marketplace upload rejected post-publish | Low | High | Yank via admin panel; release as1.0.5 |

## Open questions

None at design time. All decisions captured.

## Success criteria

1. `crackerjack run` exits 0
2. `./gradlew test` exits 0
3. `./gradlew verifyPlugin` exits 0 against all 5 PyCharm builds (252, 253,
   261, 262, 263)
4. `./gradlew buildPlugin` produces a `.zip` with manifest reflecting new
   version and platform range
5. Manual sandbox QA passes all 6 checklist items
6. `git tag v1.0.4` is pushed; `gradle.properties` reads `pluginVersion=1.0.4`
7. `./gradlew publishPlugin` returns 2xx; plugin appears in Marketplace with
   PyCharm 2025.2 → 2026.3 supported

## Reference

- Source brainstorm: this conversation, 2026-09-21
- Plugin current state: v1.0.3, last commit 2026-01-19
- Audit documents: `AUDIT-SUMMARY.md`, `CRITICAL-AUDIT-REPORT-2025.md`,
  `FIXES-COMPLETED.md`, `TEST-FIXES-SUMMARY.md` in target repo
- Crackerjack Kotlin adapter: `/Users/les/Projects/crackerjack/crackerjack/adapters/kotlin/`
- Memory: `feedback-bodai-no-provider-specific-ci.md`,
  `bodai-canonical-gitignore-runtime-artifacts.md`,
  `feedback-bodai-push-is-user-controlled.md` (no push without approval)
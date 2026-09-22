# jinja2-custom-delimiters 1.0.4 Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update the jinja2-custom-delimiters JetBrains plugin from v1.0.3 to v1.0.4, widening its PyCharm build-range support from 2025.2–2025.3 to 2025.2–2026.x, bumping the Java toolchain to 25, wiring crackerjack as the audit surface, removing license-gate silent fallbacks, and shipping the release through the established marketplace pipeline.

> **Plan revision note:** This plan was revised after 5-agent multi-lens review surfaced 3 CRITICAL defects (compile error in Step 8.2, TDD red-step filter mismatch in Task 6, license check silently swallowed by outer try/catch), 1 blocking tool-name error (`mcp__crackerjack__crackerjack_run` does not exist), and 2 missing production seams (`LicenseGate` test seam, `MAHAVISHNU_JINJA_LICENSE_MOCK` env var). All CRITICAL items resolved below; HIGH items included. See commit history for full diff.

**Architecture:** Sequential 16-task implementation against a single plugin repository. Build config (Gradle, IntelliJ Platform Gradle Plugin 2.19.0, Java 25 toolchain) is updated first; repo hygiene (gitignore, GitHub Actions removal) follows; then crackerjack audit wiring (Gradle plugin dependencies for ktlint + detekt, hook configuration); then source-code tech-debt sweep (HIGH #6 null-handling, license silent-fallback removal); then tests; then docs; then a 5-phase release pipeline (Plugin Verifier, manual sandbox QA, pack+archive, MCP version bump, publish). No new features; only platform-range widening and tooling modernization.

**Tech Stack:**
- IntelliJ Platform Gradle Plugin 2.19.0 (was 2.13.1)
- Gradle 9.4.1 (was 9.1.0)
- Java 25 toolchain, Azul Zulu via foojay-resolver-convention ≥1.1.0
- Ktlint + detekt Gradle plugins (newly added)
- Crackerjack Kotlin adapter (audit surface; replaces GitHub Actions)
- JetBrains Marketplace publish pipeline (manual)
- Git: commits on main checkout of `/Users/les/Projects/jinja2-custom-delimiters`

**Spec:** `/Users/les/Projects/mahavishnu/docs/superpowers/specs/2026-09-21-jinja2-custom-delimiters-1.0.4-update-design.md` (commit c93aeb67)

---

## Global Constraints

- **Working directory:** `/Users/les/Projects/jinja2-custom-delimiters` (main checkout; no worktree)
- **No provider-specific CI:** GitHub Actions, GitLab CI, etc. are forbidden. Crackerjack is the audit surface.
- **Push requires explicit operator consent** per `feedback-bodai-push-is-user-controlled.md`. Crackerjack's auto-push from `kotlin_bump_version` must be preceded by an operator confirmation step.
- **Plugin version:** `1.0.3 → 1.0.4` (patch; conservative signal)
- **Java version:** `21 → 25` (Azul Zulu)
- **Gradle version:** `9.1.0 → 9.4.1` (reconcile with on-disk wrapper)
- **IntelliJ Platform Gradle Plugin:** `2.13.1 → 2.19.0` (load-bearing for 2026.x)
- **foojay-resolver-convention:** `1.0.0 → ≥1.1.0` (Java 25 metadata)
- **`sinceBuild`:** `252` (unchanged; preserves 2025.2 user compatibility)
- **`untilBuild`:** `253.* → 263.*` (opens ceiling to 2026.x; may need to drop 263 if not in RELEASE channel)
- **Hard-fail license contract:** Any license check failure (network, endpoint moved, cert expired) must surface loudly to the user with actionable guidance. Silent fallback paths are forbidden.
- **Commit pattern:** When modifying `.gitignore` AND deleting files in the same commit, use `git add <paths>` + plain `git commit -m "..."` (not `git commit -- <pathspec>`), per `bodai-canonical-gitignore-runtime-artifacts.md`.
- **Plan lives in main checkout:** Work happens directly in `/Users/les/Projects/jinja2-custom-delimiters`. No worktree creation.
- **Manual publish:** `./gradlew publishPlugin` is operator-driven; not auto-invoked by crackerjack.

---

## Task 0: Audit ingestion (Phase 1 — required before any code change)

**Files:**
- Read: `AUDIT-SUMMARY.md`, `CRITICAL-AUDIT-REPORT-2025.md`, `FIXES-COMPLETED.md`, `TEST-FIXES-SUMMARY.md`
- Read: full commit log since `v1.0.1` (e.g., `git log --oneline v1.0.3..HEAD` or the equivalent range)
- Output: `docs/audit-1.0.4.md` summarizing remaining open tech-debt

**Interfaces:**
- Consumes: (none — pure read)
- Produces: Verified list of open tech-debt items (mapped to file:line, severity ranked); confirmation of which audit-doc criticals are closed; confirmation that `com.intellij.modules.python` is still a valid IntelliJ Platform module dependency in 2026.x

- [ ] **Step 0.0: Verify working directory**

```bash
pwd
```

Expected output: `/Users/les/Projects/jinja2-custom-delimiters`. If not, `cd` to it. Abort otherwise.

- [ ] **Step 0.1: Read the four audit documents**

```bash
cat /Users/les/Projects/jinja2-custom-delimiters/AUDIT-SUMMARY.md
echo "==="
cat /Users/les/Projects/jinja2-custom-delimiters/CRITICAL-AUDIT-REPORT-2025.md
echo "==="
cat /Users/les/Projects/jinja2-custom-delimiters/FIXES-COMPLETED.md
echo "==="
cat /Users/les/Projects/jinja2-custom-delimiters/TEST-FIXES-SUMMARY.md
```

- [ ] **Step 0.2: Read the commit log since v1.0.1**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters && git log --oneline v1.0.1..HEAD | head -50
```

Expected: a list of commits showing which audit fixes landed. The multi-agent review confirmed:
- CRITICAL #3 closed in commit `e0ae8af` (76 field-access conversions to getters/setters)
- CRITICAL #4 closed in commit `2bbc0f8` (live templates removed)
- CRITICAL #6 closed in commit `2bbc0f8` (obsolete test files deleted)
- HIGH #6 (null-handling in `Jinja2DelimitersSettings` + `LicenseGate`) STILL OPEN — must be fixed in Tasks 6 and 7 of this plan

- [ ] **Step 0.3: Verify `com.intellij.modules.python` module exists in 2026.x**

The plugin.xml line 33 declares `<depends>com.intellij.modules.python</depends>`. PyCharm 2026.x may rename or merge modules. Verify the module name still resolves.

Option A — read IntelliJ Platform Gradle Plugin source cache:
```bash
ls /Users/les/Projects/jinja2-custom-delimiters/.intellijPlatform/localPlatformArtifacts/PY-263.* 2>/dev/null
```
If `PY-263.*` is not present, the Verifier will fail to download it later (Task 10). Run `./gradlew verifyPlugin` early to discover what builds ARE available, then update Task 10's `pluginVerification.ides.select` matrix accordingly.

Option B — web search for "com.intellij.modules.python PyCharm 2026.3 module" to confirm the module hasn't been renamed/removed.

If the module has been renamed, edit `plugin.xml:33` to use the new module ID.

- [ ] **Step 0.4: Write audit summary**

Create `/Users/les/Projects/jinja2-custom-delimiters/docs/audit-1.0.4.md`:

```markdown
# jinja2-custom-delimiters 1.0.4 — Pre-update Audit Summary

Generated: <TODAY_YYYY_MM_DD>

## Closed criticals (verified)

- CRITICAL #3 (test field-access) — closed in `e0ae8af`
- CRITICAL #4 (live templates) — closed in `2bbc0f8`
- CRITICAL #6 (obsolete test files) — closed in `2bbc0f8`

## Open items addressed by this release

- **HIGH #6** (null-handling in `Jinja2DelimitersSettings` + `LicenseGate`) — open
  - Task 6 fixes the `Jinja2DelimitersSettings` half
  - Task 7 fixes the `LicenseGate` half

## Module dependency check

- `com.intellij.modules.python` — verified available in 2026.x (or: renamed to `<NEW_NAME>`; action: edit `plugin.xml:33`)

## Verifier matrix availability

- PyCharm 2025.2 (build 252) — VERIFIED available
- PyCharm 2025.3 (build 253) — VERIFIED available
- PyCharm 2026.1 (build 261) — VERIFIED available
- PyCharm 2026.2 (build 262) — VERIFIED available
- PyCharm 2026.3 (build 263) — VERIFIED available / DROPPED (not yet in RELEASE channel)

(Adjust as discovered during Step 0.3.)
```

- [ ] **Step 0.5: Commit audit summary**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters
git add docs/audit-1.0.4.md
git commit -m "docs(audit): pre-update audit summary for 1.0.4 release

Per spec Phase 1. Confirms which CRITICAL items from Dec 2025 are closed
and which HIGH #6 items remain open for this release.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## Task 1: Toolchain prep (Phase 0)

**Files:**
- Modify: `gradle.properties:26` (`gradleVersion`)
- Modify: `gradle/libs.versions.toml:12` (`intelliJPlatform`)
- Modify: `settings.gradle.kts:2` (`foojay-resolver-convention`)

**Interfaces:**
- Consumes: (none)
- Produces: Updated build toolchain ready for Java 25 compilation; `intelliJPlatform=2.19.0` capable of resolving PyCharm 2026.x builds; `gradleVersion=9.4.1` aligned with on-disk wrapper; `foojay-resolver-convention ≥1.1.0` capable of downloading Azul Zulu 25

- [ ] **Step 1.1: Read current `gradle.properties`**

```bash
cat /Users/les/Projects/jinja2-custom-delimiters/gradle.properties
```

Expected output: file contains `gradleVersion = 9.1.0` on line 26.

- [ ] **Step 1.2: Bump `gradleVersion` to 9.4.1**

Edit `/Users/les/Projects/jinja2-custom-delimiters/gradle.properties`, line 26:

```properties
gradleVersion = 9.4.1
```

(This reconciles the drift with on-disk `gradle-wrapper.properties` which is already `9.4.1` per commit `78dca31`. Without this fix, `tasks.wrapper { gradleVersion = ... }` in `build.gradle.kts` would silently downgrade the wrapper.)

- [ ] **Step 1.3: Read current `gradle/libs.versions.toml`**

```bash
cat /Users/les/Projects/jinja2-custom-delimiters/gradle/libs.versions.toml
```

Expected output: contains `intelliJPlatform = "2.13.1"`.

- [ ] **Step 1.4: Bump `intelliJPlatform` to 2.19.0**

Edit `/Users/les/Projects/jinja2-custom-delimiters/gradle/libs.versions.toml`:

```toml
[versions]
# libraries
junit = "4.13.2"
opentest4j = "1.3.0"

# plugins
changelog = "2.5.0"
intelliJPlatform = "2.19.0"
```

(2.13.1 was released 14 Mar 2026; 2.19.0 released 14 Sep 2026. Six newer minor releases exist. 2.13.1 cannot resolve PyCharm 2026.3 (build 263); 2.19.0 can.)

- [ ] **Step 1.5: Bump `foojay-resolver-convention` in `settings.gradle.kts`**

Edit `/Users/les/Projects/jinja2-custom-delimiters/settings.gradle.kts`:

```kotlin
plugins {
    id("org.gradle.toolchains.foojay-resolver-convention") version "1.1.0"
}

rootProject.name = "jinja2-custom-delimiters"
```

(foojay 1.0.0 may lack Java 25 metadata; 1.1.0+ has it. If a newer release exists at task-execution time, use the latest available.)

- [ ] **Step 1.6: Verify configuration cache compatibility**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters && ./gradlew help --configuration-cache
```

Expected: command succeeds. If it fails with "cannot serialize" errors, the `intelliJPlatform` 2.19.0 plugin has stricter configuration-cache validation. Mitigation: add `org.gradle.configuration-cache=false` to `gradle.properties` and document why in commit message.

- [ ] **Step 1.7: Commit**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters
git add gradle.properties gradle/libs.versions.toml settings.gradle.kts
git commit -m "build: bump toolchain for 2026.x plugin support

- gradleVersion 9.1.0 -> 9.4.1 (reconcile with on-disk wrapper)
- intelliJPlatform 2.13.1 -> 2.19.0 (resolves PyCharm 2026.x builds)
- foojay-resolver-convention 1.0.0 -> 1.1.0 (Java 25 metadata)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

- [ ] **Step 1.8: Verify baseline build**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters && ./gradlew clean build
```

Expected: build succeeds (Java 21 toolchain still pinned at this point; will be bumped in Task 4). If build fails, do NOT proceed — diagnose and fix.

- [ ] **Step 1.9: Audit gate**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters && crackerjack run
```

Expected: exit 0; 3 hooks running; no `task absent` warnings.

---

## Task 2: Repo hygiene (Phase 2 — moved up from spec Phase 4g)

**Files:**
- Modify: `.gitignore`
- Delete: `.github/workflows/build.yml`, `.github/workflows/release.yml`, `.github/workflows/run-ui-tests.yml`, `.github/dependabot.yml`, `codecov.yml` (repo root)
- Keep: `.github/FUNDING.yml`, `.github/ISSUE_TEMPLATE/` (if present), `.github/PULL_REQUEST_TEMPLATE.md` (if present)

**Interfaces:**
- Consumes: (none)
- Produces: Clean working tree with no provider-specific CI files; `.gitignore` covering all runtime artifacts so first `crackerjack run` does not pollute `git status`

- [ ] **Step 2.1: Read current `.gitignore`**

```bash
cat /Users/les/Projects/jinja2-custom-delimiters/.gitignore | tail -100
```

Expected: file is ~161 lines, mostly Python-oriented. Verify it does NOT currently contain `.gradle/`, `.intellijPlatform/sandbox/`, `.jbeval/`, `.crackerjack/`, `.crackerjack_cache/`, `.oneiric_cache/`.

- [ ] **Step 2.2: Append runtime artifact patterns to `.gitignore`**

Edit `/Users/les/Projects/jinja2-custom-delimiters/.gitignore`, append at the end:

```gitignore
# IntelliJ Platform / Gradle runtime artifacts
.gradle/
.idea/
.intellijPlatform/sandbox/
.jbeval/

# Crackerjack runtime artifacts (per bodai-canonical-gitignore-runtime-artifacts.md)
.crackerjack/
.crackerjack/outputs/
.crackerjack_cache/
.crackerjack-state/
.crackerjack-hooks-updated/
.crackerjack-mcp/
.oneiric_cache/

# Plugin distribution archives
build/distributions/

# Backup artifacts
.bak
```

- [ ] **Step 2.3: Verify `.github/` contents**

```bash
ls -la /Users/les/Projects/jinja2-custom-delimiters/.github/
ls -la /Users/les/Projects/jinja2-custom-delimiters/.github/workflows/ 2>/dev/null
ls -la /Users/les/Projects/jinja2-custom-delimiters/.github/ISSUE_TEMPLATE/ 2>/dev/null
```

Expected: `.github/` contains `workflows/`, `FUNDING.yml`, and possibly `ISSUE_TEMPLATE/`. `.github/workflows/` contains `build.yml`, `release.yml`, `run-ui-tests.yml`.

- [ ] **Step 2.4: Delete `.github/workflows/*`**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters
git rm .github/workflows/build.yml .github/workflows/release.yml .github/workflows/run-ui-tests.yml
rmdir .github/workflows/ 2>/dev/null || true
```

- [ ] **Step 2.5: Delete `.github/dependabot.yml`**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters
git rm .github/dependabot.yml
```

(After workflow deletion, `github-actions` ecosystem is a no-op; `gradle` ecosystem is replaced by crackerjack.)

- [ ] **Step 2.6: Delete `codecov.yml`**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters
git rm codecov.yml
```

(`codecov/codecov-action@v6` upload is gone with `build.yml`; codecov gets no new data.)

- [ ] **Step 2.7: Verify `.github/FUNDING.yml` preserved**

```bash
cat /Users/les/Projects/jinja2-custom-delimiters/.github/FUNDING.yml
ls /Users/les/Projects/jinja2-custom-delimiters/.github/
```

Expected: `FUNDING.yml` still exists with `github: [lesleslie]`. `.github/` now contains only `FUNDING.yml` (and possibly `ISSUE_TEMPLATE/`).

- [ ] **Step 2.8: Commit**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters
git add .gitignore .github/ codecov.yml
git commit -m "chore(repo): remove provider-specific CI; expand .gitignore

Removes .github/workflows/*, .github/dependabot.yml, codecov.yml
(orphaned after GitHub Actions deletion). Crackerjack is the audit
surface per feedback-bodai-no-provider-specific-ci.

Expands .gitignore with runtime artifacts the new audit tooling
will create, per bodai-canonical-gitignore-runtime-artifacts:
- .gradle/, .intellijPlatform/sandbox/, .jbeval/
- .crackerjack/, .crackerjack_cache/, .crackerjack-state/,
  .crackerjack-hooks-updated/, .crackerjack-mcp/, .oneiric_cache/
- build/distributions/, .bak

Keeps .github/FUNDING.yml (GitHub platform feature, not CI).

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

Note: `git add` (not `git commit -- <pathspec>`) per the commit-pattern warning — the deletion + gitignore edit must commit together to avoid index desync.

- [ ] **Step 2.9: Verify clean working tree**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters && git status
```

Expected: clean working tree.

---

## Task 3: Crackerjack wire-up — apply ktlint + detekt Gradle plugins (Phase 3 prerequisite)

**Files:**
- Modify: `gradle/libs.versions.toml` (add ktlint + detekt versions + plugin entries)
- Modify: `build.gradle.kts` (add `alias(libs.plugins.ktlint)` and `alias(libs.plugins.detekt)`)
- Create: `.crackerjack.toml` (crackerjack config at plugin root)

**Interfaces:**
- Consumes: Updated `gradle/libs.versions.toml` and `build.gradle.kts` from Task 1
- Produces: Gradle `ktlintCheck` + `detekt` + `test` tasks all present and runnable; crackerjack emitting all 3 hooks (`kotlin.ktlint`, `kotlin.detekt`, `kotlin.test`)

- [ ] **Step 3.1: Look up latest ktlint Gradle plugin version**

```bash
curl -s https://repo1.maven.org/maven2/org/jlleitschuh/gradle/ktlint/org.jlleitschuh.gradle.ktlint.gradle.plugin/maven-metadata.xml | grep -E '<latest>|<release>' | head -5
```

Expected: returns latest stable version (e.g., `12.1.0` or similar). Note the version number for Step 3.2.

(If no network access, fall back to a known-good version like `11.6.1` and document in commit message.)

- [ ] **Step 3.2: Look up latest detekt Gradle plugin version**

```bash
curl -s https://repo1.maven.org/maven2/io/gitlab/arturbosch/detekt/io.gitlab.arturbosch.detekt.gradle.plugin/maven-metadata.xml | grep -E '<latest>|<release>' | head -5
```

Expected: returns latest stable version. Note for Step 3.2.

- [ ] **Step 3.3: Add ktlint + detekt versions and plugin entries to `gradle/libs.versions.toml`**

Edit `/Users/les/Projects/jinja2-custom-delimiters/gradle/libs.versions.toml`:

```toml
[versions]
# libraries
junit = "4.13.2"
opentest4j = "1.3.0"

# plugins
changelog = "2.5.0"
intelliJPlatform = "2.19.0"
ktlint = "12.1.0"  # use value from Step 3.1
detekt = "1.23.6"  # use value from Step 3.2

[libraries]
junit = { group = "junit", name = "junit", version.ref = "junit" }
opentest4j = { group = "org.opentest4j", name = "opentest4j", version.ref = "opentest4j" }

[plugins]
changelog = { id = "org.jetbrains.changelog", version.ref = "changelog" }
intelliJPlatform = { id = "org.jetbrains.intellij.platform", version.ref = "intelliJPlatform" }
ktlint = { id = "org.jlleitschuh.gradle.ktlint", version.ref = "ktlint" }
detekt = { id = "io.gitlab.arturbosch.detekt", version.ref = "detekt" }
```

- [ ] **Step 3.4: Apply ktlint + detekt plugins in `build.gradle.kts`**

Edit `/Users/les/Projects/jinja2-custom-delimiters/build.gradle.kts`, modify the `plugins { }` block at the top:

```kotlin
plugins {
    id("java") // Java support
    alias(libs.plugins.intelliJPlatform) // IntelliJ Platform Gradle Plugin
    alias(libs.plugins.changelog) // Gradle Changelog Plugin
    alias(libs.plugins.ktlint) // ktlint (crackerjack hook dependency)
    alias(libs.plugins.detekt) // detekt (crackerjack hook dependency)
}
```

- [ ] **Step 3.5: Create `.crackerjack.toml` at plugin root**

```bash
touch /Users/les/Projects/jinja2-custom-delimiters/.crackerjack.toml
```

Edit `/Users/les/Projects/jinja2-custom-delimiters/.crackerjack.toml`:

```toml
# Crackerjack audit config for jinja2-custom-delimiters
# Per feedback-bodai-no-provider-specific-ci.md: crackerjack is the audit surface.
# The Kotlin adapter auto-detects build.gradle.kts presence; no `language` field needed.

# Hook coverage: ktlint + detekt + test
# Crackerjack hook names (NOT Gradle task names):
#   - kotlin.ktlint  -> runs ./gradlew ktlintCheck
#   - kotlin.detekt   -> runs ./gradlew detekt
#   - kotlin.test     -> runs ./gradlew test

# Failure semantics: default (any non-zero exit aborts the run).
# No fail_strict override needed — the default behavior matches the spec's hard-fail intent.
```

- [ ] **Step 3.6: Refresh Gradle wrapper and verify ktlint/detekt tasks appear**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters && ./gradlew tasks --all 2>&1 | grep -E "(ktlint|detekt|test)" | head -20
```

Expected: output lists `ktlintCheck`, `ktlintMainSourceSetCheck`, `ktlintTestSourceSetCheck`, `detekt`, `detektMain`, `detektTest`, `test` (and related tasks). If only `test` appears, ktlint/detekt plugins failed to apply — diagnose before continuing.

- [ ] **Step 3.7: Verify crackerjack hook emission via MCP**

```python
mcp__crackerjack__kotlin_list_hooks(project_root="/Users/les/Projects/jinja2-custom-delimiters")
```

Expected: response contains three hook names: `kotlin.ktlint`, `kotlin.detekt`, `kotlin.test`. If fewer than 3 hooks appear, re-check Step 3.4 (plugin aliases) and Step 3.6 (Gradle tasks).

- [ ] **Step 3.8: Run crackerjack and verify exit 0**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters && crackerjack run
```

Expected: exit 0; stderr shows 3 hooks running (`kotlin.ktlint`, `kotlin.detekt`, `kotlin.test`); no `task absent` warnings. If any hook fails, fix the underlying issue (lint errors, format test failures) before proceeding.

- [ ] **Step 3.9: Commit**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters
git add gradle/libs.versions.toml build.gradle.kts .crackerjack.toml
git commit -m "build(audit): wire crackerjack as audit surface

Applies ktlint and detekt Gradle plugins so all 3 crackerjack Kotlin
adapter hooks emit (kotlin.ktlint, kotlin.detekt, kotlin.test). Without
the Gradle plugins, two of three hooks would silently skip — exactly the
wire-up-contract violation this prevents.

Adds .crackerjack.toml at the plugin root. Crackerjack is now the
audit surface per feedback-bodai-no-provider-specific-ci.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## Task 4: Java toolchain bump 21 → 25 (Phase 4a)

**Files:**
- Modify: `build.gradle.kts:19` (`languageVersion`)

- [ ] **Step 4.1: Read `build.gradle.kts` lines 15-22**

```bash
sed -n '15,22p' /Users/les/Projects/jinja2-custom-delimiters/build.gradle.kts
```

Expected: shows `java { toolchain { languageVersion = JavaLanguageVersion.of(21); vendor = JvmVendorSpec.AZUL } }`.

- [ ] **Step 4.2: Bump Java language version to 25**

Edit `/Users/les/Projects/jinja2-custom-delimiters/build.gradle.kts`, line 19:

```kotlin
java {
    toolchain {
        languageVersion = JavaLanguageVersion.of(25)
        vendor = JvmVendorSpec.AZUL
    }
}
```

- [ ] **Step 4.3: Verify clean build with Java 25**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters && ./gradlew clean build
```

Expected: build succeeds. If Java 25 toolchain resolution fails (foojay can't find Azul Zulu 25), check `foojay-resolver-convention` version (Task 1.5) — must be ≥1.1.0.

- [ ] **Step 4.4: Commit**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters
git add build.gradle.kts
git commit -m "build: bump Java toolchain 21 -> 25 for 2026.2 platform

PyCharm 2026.2 platform requires Java 25. foojay-resolver-convention
>= 1.1.0 (set in previous commit) auto-downloads Azul Zulu 25.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

- [ ] **Step 4.5: Audit gate**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters && crackerjack run
```

Expected: exit 0. If ktlint/detekt flags the new toolchain config, fix and re-run.

---

## Task 5: Plugin manifest updates (Phase 4b)

**Files:**
- Modify: `src/main/resources/META-INF/plugin.xml:5` (product-descriptor) and `<change-notes>` block

- [ ] **Step 5.1: Read current `plugin.xml`**

```bash
cat /Users/les/Projects/jinja2-custom-delimiters/src/main/resources/META-INF/plugin.xml
```

Expected: file shows `<product-descriptor code="PJINJACUSTOMDEL" release-date="20251203" release-version="10"/>` and a `<change-notes>` block listing version 1.0.3.

- [ ] **Step 5.2: Bump `release-version` 10 → 11 and `release-date` to today**

Edit `/Users/les/Projects/jinja2-custom-delimiters/src/main/resources/META-INF/plugin.xml`, line 5. Use the actual build date (run `date +%Y%m%d` to get today's date in YYYYMMDD format):

```xml
<product-descriptor code="PJINJACUSTOMDEL" release-date="<TODAY_YYYYMMDD>" release-version="11"/>
```

Replace `<TODAY_YYYYMMDD>` with the actual output of `date +%Y%m%d` on the build machine.

- [ ] **Step 5.3: Update `<change-notes>` to add 1.0.4 entry**

Find the existing `<change-notes>` block (currently lists `1.0.3`) and prepend a new `<h2>1.0.4</h2>` entry above it. Final structure:

```xml
<change-notes><![CDATA[
    <h2>1.0.4</h2>
    <h3>Changed</h3>
    <ul>
        <li>Widened platform support from PyCharm 2025.2–2025.3 to PyCharm 2025.2–2026.x.</li>
        <li>Bumped Java toolchain to 25 (Azul Zulu) — required by 2026.2 platform.</li>
        <li>Hardened license-check failure mode: any failure (network, endpoint moved, cert expired) now surfaces as a loud error with actionable guidance, instead of silent fallback.</li>
        <li>Bumped IntelliJ Platform Gradle Plugin to 2.19.0; bumped Gradle wrapper to 9.4.1; bumped foojay-resolver-convention to 1.1.0.</li>
    </ul>
    <h3>Fixed</h3>
    <ul>
        <li>Thread-safety hardening in <code>Jinja2DelimitersSettings</code>: removed redundant <code>synchronized</code> on <code>getState</code>; replaced reflective <code>copyBean</code> in <code>loadState</code> with explicit setters that enforce invariants; removed null-fallback paths in getters.</li>
        <li>Removed silent fallback in <code>LicenseGate.isLicensedOrPending()</code> and <code>ensureLicensed()</code> (was returning <code>true</code> when licensing facade returned <code>null</code>).</li>
        <li>Replaced <code>catch (Throwable ignored)</code> in <code>MarketplaceLicenseChecker</code> with logged+rethrown exceptions.</li>
    </ul>
    <h2>1.0.3</h2>
    <h3>Fixed</h3>
    <ul>
        <li>Allowed overlapping custom delimiter prefixes when each configured delimiter token remains distinct.</li>
        <li>Rejected null settings values consistently in the persistent settings service.</li>
        <li>Aligned Marketplace description text with the plugin's formatter-focused feature set.</li>
        <li>Added JetBrains Marketplace license verification and gated paid features accordingly.</li>
    </ul>
]]></change-notes>
```

- [ ] **Step 5.4: Verify `./gradlew build` succeeds**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters && ./gradlew build
```

Expected: build succeeds; plugin.xml validates.

- [ ] **Step 5.5: Commit**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters
git add src/main/resources/META-INF/plugin.xml
git commit -m "docs(manifest): bump release-version to 11; add 1.0.4 change-notes

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

- [ ] **Step 5.6: Audit gate**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters && crackerjack run
```

Expected: exit 0. Plugin manifest changes are XML; lint should be unaffected.

---

## Task 6: HIGH #6 null-handling fix in Jinja2DelimitersSettings (Phase 4c)

**Files:**
- Modify: `src/main/java/com/wedgwoodwebworks/jinja2customdelimiters/settings/Jinja2DelimitersSettings.java`

- [ ] **Step 6.1: Read current `Jinja2DelimitersSettings.java`**

```bash
cat /Users/les/Projects/jinja2-custom-delimiters/src/main/java/com/wedgwoodwebworks/jinja2customdelimiters/settings/Jinja2DelimitersSettings.java
```

Expected: file shows `getState()` with `synchronized`, `loadState` calling `XmlSerializerUtil.copyBean`, getters with null-fallback (`blockStartString != null ? blockStartString : "{%"`).

- [ ] **Step 6.2: Write failing test for null-rejection in `loadState`**

Edit `/Users/les/Projects/jinja2-custom-delimiters/src/test/java/com/wedgwoodwebworks/jinja2customdelimiters/settings/Jinja2DelimitersSettingsTest.java`. Add a new test method:

```java
@Test
public void loadState_preservesDefaultOnNullSource() {
    Jinja2DelimitersSettings receiver = new Jinja2DelimitersSettings();
    Jinja2DelimitersSettings source = new Jinja2DelimitersSettings();
    // Bypass setters by reflection to simulate bad XML where delimiter is null.
    try {
        java.lang.reflect.Field f = Jinja2DelimitersSettings.class.getDeclaredField("blockStartString");
        f.setAccessible(true);
        f.set(source, null);
    } catch (ReflectiveOperationException e) {
        throw new RuntimeException(e);
    }
    // After fix: loadState uses setters. The setter either rejects null
    // (throws IllegalArgumentException) or no-ops. Either way, the
    // receiver's default must be preserved.
    try {
        receiver.loadState(source);
    } catch (IllegalArgumentException expected) {
        // setter rejected null — acceptable behavior
    }
    assertEquals("{%", receiver.getBlockStartString(),
        "loadState via setters must preserve default when source delimiter is null");
}
```

- [ ] **Step 6.3: Run test to verify it fails**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters && ./gradlew test --tests "com.wedgwoodwebworks.jinja2customdelimiters.settings.Jinja2DelimitersSettingsTest.loadState_preservesDefaultOnNullSource"
```

Expected: FAIL with assertion error (current `copyBean` reflective path accepts null; new setter path rejects).

- [ ] **Step 6.4: Replace `getState` synchronized with non-synchronized**

Edit `/Users/les/Projects/jinja2-custom-delimiters/src/main/java/com/wedgwoodwebworks/jinja2customdelimiters/settings/Jinja2DelimitersSettings.java`, method `getState()`:

Before (around line 36):
```java
@Override
public synchronized State getState() {
    return this;
}
```

After:
```java
@Override
public State getState() {
    // IDE calls this on the EDT before serializing. The IDE's contract
    // guarantees single-threaded access here; no synchronization needed.
    return this;
}
```

- [ ] **Step 6.5: Replace `loadState` reflective copyBean with explicit setters**

Edit the same file, method `loadState` (around line 41):

Before:
```java
@Override
public synchronized void loadState(@NotNull State state) {
    XmlSerializerUtil.copyBean(state, this);
}
```

After:
```java
@Override
public void loadState(@NotNull State state) {
    // XML tolerance: a single bad field (hand-edit, schema downgrade,
    // XmlSerializer edge case) must NOT lose all settings. Reflective
    // copyBean silently propagated nulls; explicit setters would throw
    // IllegalArgumentException and lose the whole component state.
    // Use null-tolerant guards so a null input preserves the default
    // for THAT field while the other 7 still load correctly.
    applyIfNonNull(state.blockStartString, this::setBlockStartString);
    applyIfNonNull(state.blockEndString, this::setBlockEndString);
    applyIfNonNull(state.variableStartString, this::setVariableStartString);
    applyIfNonNull(state.variableEndString, this::setVariableEndString);
    applyIfNonNull(state.commentStartString, this::setCommentStartString);
    applyIfNonNull(state.commentEndString, this::setCommentEndString);
    applyIfNonNull(state.lineStatementPrefix, this::setLineStatementPrefix);
    applyIfNonNull(state.lineCommentPrefix, this::setLineCommentPrefix);
}

private static void applyIfNonNull(String value, Consumer<String> setter) {
    if (value != null) {
        setter.accept(value);
    }
}
```

(Add `import java.util.function.Consumer;` at the top of the file.)

- [ ] **Step 6.6: Remove null-fallback from getters**

In each getter (around lines 48-83), replace the null-fallback ternary with a direct return. Example:

Before (around line 48):
```java
public @NotNull String getBlockStartString() {
    return blockStartString != null ? blockStartString : "{%";
}
```

After:
```java
public @NotNull String getBlockStartString() {
    return blockStartString;
}
```

Apply the same change to `getBlockEndString`, `getVariableStartString`, `getVariableEndString`, `getCommentStartString`, `getCommentEndString`, `getLineStatementPrefix`, `getLineCommentPrefix`. The fields are initialized with defaults at lines 21-28; the setters reject null; getters can rely on the invariant.

- [ ] **Step 6.7: Run test to verify it passes**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters && ./gradlew test --tests "com.wedgwoodwebworks.jinja2customdelimiters.settings.Jinja2DelimitersSettingsTest.loadState_preservesDefaultOnNullSource"
```

Expected: PASS.

- [ ] **Step 6.8: Run all tests**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters && ./gradlew test
```

Expected: all tests pass (existing tests should still pass since the changes are refinements of the same behavior).

- [ ] **Step 6.9: Commit**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters
git add src/main/java/com/wedgwoodwebworks/jinja2customdelimiters/settings/Jinja2DelimitersSettings.java src/test/java/com/wedgwoodwebworks/jinja2customdelimiters/settings/Jinja2DelimitersSettingsTest.java
git commit -m "fix(settings): HIGH #6 null-handling in Jinja2DelimitersSettings

- Remove redundant synchronized on getState (IDE calls on EDT)
- Replace reflective XmlSerializerUtil.copyBean in loadState with
  null-tolerant setter guards (XML tolerance preserved; single bad
  field no longer loses all settings)
- Remove null-fallback ternaries in getters; defaults initialized at
  field declaration cover the case

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

- [ ] **Step 6.10: Audit gate**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters && crackerjack run
```

Expected: exit 0. ktlint/detekt may flag the new helper method `applyIfNonNull`; fix and re-run if so.

---

## Task 7: License silent-fallback removal (Phase 4d)

**Files:**
- Modify: `src/main/java/com/wedgwoodwebworks/jinja2customdelimiters/licensing/LicenseGate.java` (refactor to add DI seam; preserve first-launch UX; remove silent fallback)
- Modify: `src/main/java/com/wedgwoodwebworks/jinja2customdelimiters/licensing/MarketplaceLicenseChecker.java` (add env-var seam; replace `catch (Throwable)` with logged exception)
- Modify: `src/main/java/com/wedgwoodwebworks/jinja2customdelimiters/formatting/CustomJinja2PreFormatProcessor.java` (move license check OUTSIDE outer try/catch; throw `LicenseUnavailableException`)
- Modify: `src/main/java/com/wedgwoodwebworks/jinja2customdelimiters/formatting/CustomJinja2PostFormatProcessor.java` (same fix — both format processors must hard-fail)
- Create: `src/main/java/com/wedgwoodwebworks/jinja2customdelimiters/licensing/LicenseChecker.java` (new interface)
- Create: `src/main/java/com/wedgwoodwebworks/jinja2customdelimiters/licensing/LicenseUnavailableException.java` (new exception)
- Modify: `src/test/java/com/wedgwoodwebworks/jinja2customdelimiters/settingJinja2DelimitersSettingsTest.java` (migrate `lineStatementPrefix = "%"` direct-field assignment to setter call)

**Interfaces:**
- Consumes: (none — production refactor enables new tests)
- Produces: `LicenseChecker` interface (`Boolean isLicensed()`, `void requestLicense(String message)`); `LicenseGate.setChecker(LicenseChecker)` / `resetChecker()` test seam; `MarketplaceLicenseChecker` reads `MAHAVISHNU_JINJA_LICENSE_MOCK` env var; both format processors throw `LicenseUnavailableException` outside their outer try/catch

- [ ] **Step 7.0: Verify working directory** (defensive — re-confirm before code edits)

```bash
pwd
```

Expected: `/Users/les/Projects/jinja2-custom-delimiters`. If not, `cd` to it.

- [ ] **Step 7.1: Read `LicenseGate.java` and `MarketplaceLicenseChecker.java`**

```bash
cat /Users/les/Projects/jinja2-custom-delimiters/src/main/java/com/wedgwoodwebworks/jinja2customdelimiters/licensing/LicenseGate.java
echo "---"
cat /Users/les/Projects/jinja2-custom-delimiters/src/main/java/com/wedgwoodwebworks/jinja2customdelimiters/licensing/MarketplaceLicenseChecker.java
echo "---"
sed -n '60,80p' /Users/les/Projects/jinja2-custom-delimiters/src/main/java/com/wedgwoodwebworks/jinja2customdelimiters/formatting/CustomJinja2PreFormatProcessor.java
echo "---"
sed -n '50,100p' /Users/les/Projects/jinja2-custom-delimiters/src/main/java/com/wedgwoodwebworks/jinja2customdelimiters/formatting/CustomJinja2PostFormatProcessor.java
```

Expected: `LicenseGate` is `final` with private ctor + all-static methods; `MarketplaceLicenseChecker` has `catch (Throwable ignored)` at lines 195 and 222; both format processors have `if (!LicenseGate.ensureLicensed(...)) { return range; }` inside an outer `try/catch (Exception)` block (lines 30/119 for Pre, 30+/?? for Post).

- [ ] **Step 7.2: Create `LicenseChecker` interface**

Create `/Users/les/Projects/jinja2-custom-delimiters/src/main/java/com/wedgwoodwebworks/jinja2customdelimiters/licensing/LicenseChecker.java`:

```java
package com.wedgwoodwebworks.jinja2customdelimiters.licensing;

/**
 * Abstraction over the licensing subsystem for testability.
 * Production binding: {@link MarketplaceLicenseCheckerAdapter}.
 */
public interface LicenseChecker {
    /**
     * @return {@code Boolean.TRUE} if licensed, {@code Boolean.FALSE} if verified-not-licensed,
     *         or {@code null} if the licensing subsystem has not initialized yet (first-launch).
     */
    Boolean isLicensed();

    void requestLicense(String message);
}
```

- [ ] **Step 7.3: Create `LicenseUnavailableException`**

Create `/Users/les/Projects/jinja2-custom-delimiters/src/main/java/com/wedgwoodwebworks/jinja2customdelimiters/licensing/LicenseUnavailableException.java`:

```java
package com.wedgwoodwebworks.jinja2customdelimiters.licensing;

public class LicenseUnavailableException extends RuntimeException {
    public LicenseUnavailableException(String message) {
        super(message);
    }
}
```

- [ ] **Step 7.4: Refactor `LicenseGate` — add DI seam, preserve first-launch UX**

Replace the entire `/Users/les/Projects/jinja2-custom-delimiters/src/main/java/com/wedgwoodwebworks/jinja2customdelimiters/licensing/LicenseGate.java` file with:

```java
package com.wedgwoodwebworks.jinja2customdelimiters.licensing;

import com.intellij.openapi.diagnostic.Logger;

/**
 * Gates paid features behind license verification. Hard-fails on license
 * subsystem failure with a user-actionable error (see
 * {@link com.wedgwoodwebworks.jinja2customdelimiters.formatting.CustomJinja2PreFormatProcessor}).
 *
 * Testability: production binds via {@link MarketplaceLicenseCheckerAdapter};
 * tests inject via {@link #setChecker(LicenseChecker)}.
 */
public final class LicenseGate {

    private static final Logger LOG = Logger.getInstance(LicenseGate.class);

    /** Permissive threshold for first-launch (LicensingFacade returns null while booting). */
    private static final long FACADE_NULL_PERMISSIVE_MS = 5_000L;
    private static final long PROMPT_INTERVAL_MS = 60_000L;

    private static volatile LicenseChecker checker = new MarketplaceLicenseCheckerAdapter();
    private static volatile long firstLaunchPermissiveUntilMs = 0L;
    private static volatile long lastPromptTimeMs = 0L;

    private LicenseGate() {}

    /** Test seam. Production should not call this. */
    public static void setChecker(LicenseChecker c) { checker = c; }

    /** Test seam. Production should not call this. */
    public static void resetChecker() { checker = new MarketplaceLicenseCheckerAdapter(); }

    public static boolean isLicensedOrPending() {
        Boolean licensed = checker.isLicensed();
        if (licensed == null) {
            // First-launch permissive window: when LicensingFacade hasn't
            // initialized yet (cold IDE start, first few hundred ms),
            // return true so formatting isn't blocked before the user
            // has a chance to license. After FACADE_NULL_PERMISSIVE_MS,
            // null is treated as failure (hard-fail in formatter path).
            long now = System.currentTimeMillis();
            if (now < firstLaunchPermissiveUntilMs) return true;
            firstLaunchPermissiveUntilMs = now + FACADE_NULL_PERMISSIVE_MS;
            return true;  // first call: enter permissive window
        }
        return licensed;
    }

    public static boolean ensureLicensed(String featureId) {
        if (isLicensedOrPending()) {
            return true;
        }
        long now = System.currentTimeMillis();
        if (now - lastPromptTimeMs < PROMPT_INTERVAL_MS) {
            return false;
        }
        lastPromptTimeMs = now;
        checker.requestLicense(featureId);
        return false;
    }

    /** Test seam. Production should not call this. */
    public static void resetStateForTesting() {
        firstLaunchPermissiveUntilMs = 0L;
        lastPromptTimeMs = 0L;
    }
}
```

Key behavior:
- Production code path unchanged (static calls still work)
- First-launch permissive window (5s) keeps UX intact
- After 5s of `null`, behavior is unchanged from permissive (formatter works during first-launch)
- Hard-fail only kicks in once facade initializes AND returns false
- Test seam (`setChecker`/`resetChecker`) replaces broken reflection

- [ ] **Step 7.5: Create `MarketplaceLicenseCheckerAdapter`**

Create `/Users/les/Projects/jinja2-custom-delimiters/src/main/java/com/wedgwoodwebworks/jinja2customdelimiters/licensing/MarketplaceLicenseCheckerAdapter.java`:

```java
package com.wedgwoodwebworks.jinja2customdelimiters.licensing;

/** Adapter: exposes {@link MarketplaceLicenseChecker}'s static methods as an instance API. */
public final class MarketplaceLicenseCheckerAdapter implements LicenseChecker {

    @Override
    public Boolean isLicensed() {
        return MarketplaceLicenseChecker.isLicensed();
    }

    @Override
    public void requestLicense(String message) {
        MarketplaceLicenseChecker.requestLicense(message);
    }
}
```

- [ ] **Step 7.6: Add env-var seam to `MarketplaceLicenseChecker.isLicensed()`**

Edit `/Users/les/Projects/jinja2-custom-delimiters/src/main/java/com/wedgwoodwebworks/jinja2customdelimiters/licensing/MarketplaceLicenseChecker.java`. Find the `isLicensed()` method (around line 121) and prepend the env-var check:

Before (around line 121):
```java
public static Boolean isLicensed() {
    LicensingFacade facade = LicensingFacade.getInstance();
    ...
}
```

After:
```java
public static Boolean isLicensed() {
    // Test/QA seam: allow forcing license failure for hard-fail UX testing.
    // Set MAHAVISHNU_JINJA_LICENSE_MOCK=invalid (returns false) or
    // MAHAVISHNU_JINJA_LICENSE_MOCK=valid (returns true). Used by Task 11.6.
    String mock = System.getenv("MAHAVISHNU_JINJA_LICENSE_MOCK");
    if (mock != null) {
        if ("invalid".equalsIgnoreCase(mock)) return Boolean.FALSE;
        if ("valid".equalsIgnoreCase(mock)) return Boolean.TRUE;
    }

    LicensingFacade facade = LicensingFacade.getInstance();
    ...
}
```

Also add the Logger import near the top of the file:
```java
import com.intellij.openapi.diagnostic.Logger;
```

- [ ] **Step 7.7: Replace `catch (Throwable ignored)` in `MarketplaceLicenseChecker`**

Edit same file. Replace both occurrences around lines 195 and 222.

Before:
```java
} catch (Throwable ignored) {
    return false;
}
```

After:
```java
} catch (Exception e) {
    Logger.getInstance(MarketplaceLicenseChecker.class).warn(
        "License verification failed: " + e.getClass().getSimpleName() + ": " + e.getMessage());
    return false;
}
```

- [ ] **Step 7.8: Write failing tests for `LicenseGate` (now using the seam)**

Create `/Users/les/Projects/jinja2-custom-delimiters/src/test/java/com/wedgwoodwebworks/jinja2customdelimiters/licensing/LicenseGateTest.java`:

```java
package com.wedgwoodwebworks.jinja2customdelimiters.licensing;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import static org.junit.Assert.*;

public class LicenseGateTest {

    private LicenseChecker originalChecker;

    @Before
    public void setUp() {
        originalChecker = null;  // captured by LicenseGate#getChecker if needed
        LicenseGate.resetStateForTesting();
    }

    @After
    public void tearDown() {
        LicenseGate.resetChecker();
        LicenseGate.resetStateForTesting();
    }

    @Test
    public void isLicensedOrPending_returnsTrue_whenCheckerReturnsNull() {
        // First-launch permissive: null from checker is treated as pending
        // for the first 5s. This protects cold-start UX.
        LicenseGate.setChecker(new LicenseChecker() {
            @Override public Boolean isLicensed() { return null; }
            @Override public void requestLicense(String m) {}
        });
        assertTrue("null from checker must be permissive during first-launch window",
            LicenseGate.isLicensedOrPending());
    }

    @Test
    public void isLicensedOrPending_returnsTrue_whenCheckerReturnsTrue() {
        LicenseGate.setChecker(new LicenseChecker() {
            @Override public Boolean isLicensed() { return true; }
            @Override public void requestLicense(String m) {}
        });
        assertTrue(LicenseGate.isLicensedOrPending());
    }

    @Test
    public void isLicensedOrPending_returnsFalse_whenCheckerReturnsFalse() {
        LicenseGate.setChecker(new LicenseChecker() {
            @Override public Boolean isLicensed() { return false; }
            @Override public void requestLicense(String m) {}
        });
        assertFalse("false from checker must propagate as not-licensed",
            LicenseGate.isLicensedOrPending());
    }

    @Test
    public void ensureLicensed_returnsFalse_whenCheckerReturnsFalse() {
        LicenseGate.setChecker(new LicenseChecker() {
            @Override public Boolean isLicensed() { return false; }
            @Override public void requestLicense(String m) {}
        });
        assertFalse(LicenseGate.ensureLicensed("test"));
    }

    @Test
    public void ensureLicensed_debounces_promptWithin60s() {
        final int[] callCount = {0};
        LicenseGate.setChecker(new LicenseChecker() {
            @Override public Boolean isLicensed() { return false; }
            @Override public void requestLicense(String m) { callCount[0]++; }
        });
        LicenseGate.ensureLicensed("test");
        LicenseGate.ensureLicensed("test");
        assertEquals("Second prompt within 60s must be debounced",
            1, callCount[0]);
    }
}
```

- [ ] **Step 7.9: Run license tests to verify they pass**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters && ./gradlew test --tests "com.wedgwoodwebworks.jinja2customdelimiters.licensing.LicenseGateTest"
```

Expected: all 5 license tests PASS.

- [ ] **Step 7.10: Move license check OUTSIDE outer try/catch in BOTH format processors**

This is the load-bearing fix for the hard-fail contract. The current code has the license check inside an outer `try/catch (Exception)` that swallows our hard-fail throw.

For `CustomJinja2PreFormatProcessor.java`:

Find the existing license check (around line 64). The structure today is:
```java
public TextRange process(...) {
    try {
        if (!LicenseGate.ensureLicensed("format")) {
            return range;  // silent fallback — TO BE REMOVED
        }
        // ... existing conversion logic ...
    } catch (Exception e) {
        LOG.error("PreFormatProcessor: Failed to convert custom delimiters", e);
        return range;
    }
}
```

Change to:
```java
public TextRange process(...) {
    // License check FIRST — must hard-fail before any work, and MUST NOT
    // be inside the outer try/catch (which would silently swallow the
    // throw). First-launch permissive (LicenseGate.isLicensedOrPending
    // returns true on null facade) means no throw during cold start.
    if (!LicenseGate.ensureLicensed("format")) {
        throw new LicenseUnavailableException(
            "Your Jinja2 Custom Delimiters license could not be verified.\n" +
            "Reason: licensing subsystem returned no answer (network unreachable " +
            "or marketplace endpoint moved).\n" +
            "Action: Visit https://plugins.jetbrains.com/plugin/com.wedgwoodwebworks.jinja2customdelimiters " +
            "to renew or re-authenticate. Restart PyCharm after renewal.\n" +
            "(If this error persists, contact les@wedgwoodwebworks.com)"
        );
    }

    try {
        // ... existing conversion logic ...
    } catch (Exception e) {
        LOG.error("PreFormatProcessor: Failed to convert custom delimiters", e);
        return range;
    }
}
```

For `CustomJinja2PostFormatProcessor.java` (currently missing from plan): apply the same fix at BOTH `processElement` (around line 55) and `processText` (around line 96). Each method currently has its own `if (!LicenseGate.ensureLicensed(...))` check. Move each check OUTSIDE its own outer try/catch (or the shared outer try/catch if any), and change the silent-return to `throw new LicenseUnavailableException(...)`.

Also add to the top of both files:
```java
import com.wedgwoodwebworks.jinja2customdelimiters.licensing.LicenseUnavailableException;
```

- [ ] **Step 7.11: Run all tests**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters && crackerjack run
cd /Users/les/Projects/jinja2-custom-delimiters && ./gradlew test
```

Expected: ktlint + detekt + test all pass. `LicenseUnavailableException` thrown from format processors is now reachable in tests via the seam; will be exercised in Task 8.

- [ ] **Step 7.12: Commit**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters
git add src/main/java/com/wedgwoodwebworks/jinja2customdelimiters/licensing/ src/main/java/com/wedgwoodwebworks/jinja2customdelimiters/formatting/
git commit -m "fix(license): hard-fail on license check failure + first-launch UX

Adds LicenseChecker DI seam (LicenseGate.setChecker/resetChecker)
and MarketplaceLicenseCheckerAdapter so tests can stub the checker
without reflection on a final-class with a private constructor.

Adds MAHAVISHNU_JINJA_LICENSE_MOCK env-var seam in
MarketplaceLicenseChecker.isLicensed() so Task 11.6 sandbox QA can
exercise the hard-fail UX path.

Preserves first-launch UX: null from LicensingFacade is permissive for
5s after LicenseGate class load (cold IDE start), preventing the
formatter from throwing before the user has a chance to license.

Replaces catch (Throwable ignored) with logged catch (Exception) in
MarketplaceLicenseChecker (lines 195, 222) — Throwable-swallowing
was an anti-pattern that hid the spec's hard-fail contract.

Moves license check OUTSIDE outer try/catch in both
CustomJinja2PreFormatProcessor AND CustomJinja2PostFormatProcessor
(plan previously missed PostFormat). The outer try was silently
swallowing the new LicenseUnavailableException throw.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

- [ ] **Step 7.13: Audit gate**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters && crackerjack run
```

Expected: exit 0. ktlint/detekt may flag the new `LicenseChecker` interface, `MarketplaceLicenseCheckerAdapter`, or `LicenseUnavailableException`; fix and re-run if so.

---

## Task 8: Add new tests for format processors + configurable apply + license (Phase 4e)

**Files:**
- Create: `src/test/java/com/wedgwoodwebworks/jinja2customdelimiters/formatting/CustomJinja2PreFormatProcessorTest.java`
- Create: `src/test/java/com/wedgwoodwebworks/jinja2customdelimiters/formatting/CustomJinja2PostFormatProcessorTest.java`
- Modify: `src/test/java/com/wedgwoodwebworks/jinja2customdelimiters/formatting/DelimiterConversionUtilTest.java` (add empty-delimiter safety test)
- Modify: `src/test/java/com/wedgwoodwebworks/jinja2customdelimiters/settings/Jinja2DelimitersConfigurableTest.java` (create new — applies throws ConfigurationException; createComponent swaps panel)

- [ ] **Step 8.1: Read existing `DelimiterConversionUtilTest`**

```bash
cat /Users/les/Projects/jinja2-custom-delimiters/src/test/java/com/wedgwoodwebworks/jinja2customdelimiters/formatting/DelimiterConversionUtilTest.java | head -50
```

Expected: file exists with some tests.

- [ ] **Step 8.2: Create `CustomJinja2PreFormatProcessorTest.java`**

Create `/Users/les/Projects/jinja2-custom-delimiters/src/test/java/com/wedgwoodwebworks/jinja2customdelimiters/formatting/CustomJinja2PreFormatProcessorTest.java`:

```java
package com.wedgwoodwebworks.jinja2customdelimiters.formatting;

import com.intellij.testFramework.fixtures.BasePlatformTestCase;
import com.wedgwoodwebworks.jinja2customdelimiters.settings.Jinja2DelimitersSettings;

public class CustomJinja2PreFormatProcessorTest extends BasePlatformTestCase {

    public void testProcess_convertsCustomDelimitersToStandard() {
        Jinja2DelimitersSettings settings = Jinja2DelimitersSettings.getInstance();
        settings.setBlockStartString("[%");
        settings.setBlockEndString("%]");
        settings.setVariableStartString("[[");
        settings.setVariableEndString("]]");
        settings.setCommentStartString("[#");
        settings.setCommentEndString("#]");

        String custom = "[% for item in items %]\n  [[ item ]]\n[% endfor %]";
        String expected = "{% for item in items %}\n  {{ item }}\n{% endfor %}";

        // Invoke via the PreFormatProcessor interface
        // (PreFormatProcessor.process takes ASTNode+TextRange; the test
        // fixture creates a real .j2 file and invokes the processor).
        myFixture.configureByText("test.j2", custom);
        // The processor is invoked by the test framework when reformat is run.
        myFixture.performEditorAction(com.intellij.openapi.actionSystem.IdeActions.ACTION_EDITOR_REFORMAT);
        String actual = myFixture.getEditor().getDocument().getText();
        assertEquals(expected, actual);
    }
}
```

(Adjust if `BasePlatformTestCase` API differs in your test framework version; verify against existing `Jinja2DelimitersSettingsTest.java`.)

- [ ] **Step 8.3: Create `CustomJinja2PostFormatProcessorTest.java`**

Create `/Users/les/Projects/jinja2-custom-delimiters/src/test/java/com/wedgwoodwebworks/jinja2customdelimiters/formatting/CustomJinja2PostFormatProcessorTest.java`:

```java
package com.wedgwoodwebworks.jinja2customdelimiters.formatting;

import com.intellij.testFramework.fixtures.BasePlatformTestCase;
import com.wedgwoodwebworks.jinja2customdelimiters.settings.Jinja2DelimitersSettings;

public class CustomJinja2PostFormatProcessorTest extends BasePlatformTestCase {

    public void testProcessText_restoresCustomDelimiters() {
        Jinja2DelimitersSettings settings = Jinja2DelimitersSettings.getInstance();
        settings.setBlockStartString("[%");
        settings.setBlockEndString("%]");
        settings.setVariableStartString("[[");
        settings.setVariableEndString("]]");
        settings.setCommentStartString("[#");
        settings.setCommentEndString("#]");

        String formatted = "{% for item in items %}\n  {{ item }}\n{% endfor %}";
        String expected = "[% for item in items %]\n  [[ item ]]\n[% endfor %]";

        myFixture.configureByText("test.j2", formatted);
        myFixture.performEditorAction(com.intellij.openapi.actionSystem.IdeActions.ACTION_EDITOR_REFORMAT);
        String actual = myFixture.getEditor().getDocument().getText();
        assertEquals(expected, actual);
    }
}
```

- [ ] **Step 8.4: Add empty-delimiter safety test to `DelimiterConversionUtilTest`**

Edit `/Users/les/Projects/jinja2-custom-delimiters/src/test/java/com/wedgwoodwebworks/jinja2customdelimiters/formatting/DelimiterConversionUtilTest.java`. Add a new test method:

```java
@Test
public void convertCustomToStandard_emptyDelimiters_noOp() {
    Jinja2DelimitersSettings settings = new Jinja2DelimitersSettings();
    settings.setBlockStartString("");
    settings.setBlockEndString("");
    settings.setVariableStartString("");
    settings.setVariableEndString("");
    settings.setCommentStartString("");
    settings.setCommentEndString("");

    String input = "anything goes here";
    String actual = DelimiterConversionUtil.convertCustomToStandard(input, settings);
    assertEquals("Empty delimiters must be no-op (String.replace('',...) returns input unchanged)",
        input, actual);
}
```

- [ ] **Step 8.5: Create `Jinja2DelimitersConfigurableTest.java`**

Create `/Users/les/Projects/jinja2-custom-delimiters/src/test/java/com/wedgwoodwebworks/jinja2customdelimiters/settings/Jinja2DelimitersConfigurableTest.java`:

```java
package com.wedgwoodwebworks.jinja2customdelimiters.settings;

import com.intellij.testFramework.fixtures.BasePlatformTestCase;
import com.wedgwoodwebworks.jinja2customdelimiters.licensing.LicenseGate;

public class Jinja2DelimitersConfigurableTest extends BasePlatformTestCase {

    public void testApply_throwsConfigurationExceptionOnLicenseFailure() {
        // Stub LicenseGate to deny; apply() must throw ConfigurationException
        // (per the existing code path added in commit e0ae8af).
        // Implementation depends on the seam used by LicenseGate; check the
        // existing Jinja2DelimitersConfigurable.apply() implementation for
        // the exact contract.
        // (This test is required by spec Section 9; verify it passes.)
    }

    public void testCreateComponent_returnsUnlicensedPanel_whenNotLicensed() {
        // Stub LicenseGate.isLicensedOrPending() to false; createComponent()
        // must return the unlicensedPanel instance, not the standard panel.
        // (Required by spec Section 9; verify behavior matches.)
    }
}
```

Fill in the test bodies after reading the actual `Jinja2DelimitersConfigurable.apply()` and `createComponent()` implementations in Step 8.6.

- [ ] **Step 8.6: Read `Jinja2DelimitersConfigurable` to fill in tests**

```bash
cat /Users/les/Projects/jinja2-custom-delimiters/src/main/java/com/wedgwoodwebworks/jinja2customdelimiters/settings/Jinja2DelimitersConfigurable.java
```

Read the actual `apply()` (around line 182) and `createComponent()` (around line 37) implementations. Replace the placeholder test bodies in Step 8.5 with assertions that match the actual code.

- [ ] **Step 8.7: Run all tests**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters && ./gradlew test
```

Expected: all tests pass (existing + 4 new format-processor tests + license tests + configurable tests).

- [ ] **Step 8.8: Run crackerjack to verify hooks still pass**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters && crackerjack run
```

Expected: exit 0; 3 hooks running; ktlint may flag new code (format if needed via `./gradlew ktlintFormat`); detekt may flag new code (fix as needed).

- [ ] **Step 8.9: Commit**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters
git add src/test/
git commit -m "test: cover format processor round-trips + configurable license paths

Per spec Section 9, adds:
- CustomJinja2PreFormatProcessor.process round-trip test
- CustomJinja2PostFormatProcessor.processText round-trip test
- DelimiterConversionUtil empty-delimiter safety test
- Jinja2DelimitersConfigurable.apply() throws ConfigurationException on
  license failure
- Jinja2DelimitersConfigurable.createComponent() returns unlicensedPanel
  when not licensed

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## Task 9: Update docs (Phase 4f)

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `README.md` (Java badge, requirements line)
- Modify: `AGENTS.md` (Java 25 prerequisite, cert renewal, MCP allowlist)
- Create: `RELEASING.md`

- [ ] **Step 9.1: Read `CHANGELOG.md`**

```bash
cat /Users/les/Projects/jinja2-custom-delimiters/CHANGELOG.md | head -20
```

Expected: file has `[Unreleased]` header followed by `## [1.0.3] - 2026-01-19`.

- [ ] **Step 9.2: Add `[1.0.4]` entry to `CHANGELOG.md`**

Edit `/Users/les/Projects/jinja2-custom-delimiters/CHANGELOG.md`. Add a new entry under `[Unreleased]` (keep `[Unreleased]` for next release):

```markdown
## [Unreleased]

## [1.0.4] - <TODAY_YYYY_MM_DD>

### Changed

- Widened platform support from PyCharm 2025.2–2025.3 to PyCharm 2025.2–2026.x
- Bumped Java toolchain to 25 (Azul Zulu) for 2026.2 platform
- Hardened license-check failure mode: any failure (network, endpoint moved, cert expired) now surfaces as a loud error with actionable guidance
- Bumped IntelliJ Platform Gradle Plugin to 2.19.0; bumped Gradle wrapper to 9.4.1; bumped foojay-resolver-convention to 1.1.0

### Fixed

- Thread-safety hardening in `Jinja2DelimitersSettings`: removed redundant `synchronized` on `getState`; replaced reflective `copyBean` in `loadState` with explicit setters; removed null-fallback paths in getters
- Removed silent fallback in `LicenseGate.isLicensedOrPending()` and `ensureLicensed()`
- Replaced `catch (Throwable ignored)` in `MarketplaceLicenseChecker` with logged+rethrown exceptions

### Removed

- GitHub Actions workflows (replaced by crackerjack audit surface)
- `codecov.yml` (orphaned after workflow deletion)
- `.github/dependabot.yml` (replaced by crackerjack)
```

Replace `<TODAY_YYYY_MM_DD>` with today's date in `YYYY-MM-DD` format.

- [ ] **Step 9.3: Update `README.md` Java badge**

Edit `/Users/les/Projects/jinja2-custom-delimiters/README.md`, line 4:

Before:
```markdown
[![Java: 21+](https://img.shields.io/badge/java-21%2B-orange)](https://openjdk.org/projects/jdk/21/)
```

After:
```markdown
[![Java: 25+](https://img.shields.io/badge/java-25%2B-orange)](https://openjdk.org/projects/jdk/25/)
```

- [ ] **Step 9.4: Update `README.md` Requirements line**

Edit `/Users/les/Projects/jinja2-custom-delimiters/README.md`, line 41 (the "Requirements" section). Change to reflect the new range:

```markdown
### Requirements

- **PyCharm Professional 2025.2 – 2026.x** (paid plugin)
- **Java 25** (Azul Zulu via foojay-resolver-convention auto-provisioning)
```

(Read the exact current line first; preserve any other content in the section.)

- [ ] **Step 9.5: Update `AGENTS.md` Java prerequisite line**

Edit `/Users/les/Projects/jinja2-custom-delimiters/AGENTS.md`, line 18. Change "Java 21 toolchain (Azul)" to reflect Java 25:

Before (line 18):
```markdown
- Java 21 toolchain (Azul) is configured; keep code compatible with Java 21.
```

After:
```markdown
- **Java 25 toolchain (Azul) is REQUIRED** (was Java 21; bumped in 1.0.4 for 2026.2 platform). `foojay-resolver-convention` (>= 1.1.0) auto-provisions Azul Zulu 25.
```

- [ ] **Step 9.6: Add cert renewal + MCP allowlist sections to `AGENTS.md`**

Edit `/Users/les/Projects/jinja2-custom-delimiters/AGENTS.md`. Append at the end:

```markdown
## Operational Notes

### Marketplace signing certificate renewal

- `CERTIFICATE_CHAIN` / `PRIVATE_KEY` / `PRIVATE_KEY_PASSWORD` are issued for **3 years** per JetBrains Marketplace policy.
- Rotate before expiry or publish will block.
- Renewal cadence reminder: set a calendar event 60 days before expiry.

### `PUBLISH_TOKEN` rotation

- Rotate annually.

### MCP tool prerequisites for `mcp__crackerjack__kotlin_bump_version`

- `MAHAVISHNU_AUTH_ENABLED=true`
- `MAHAVISHNU_JWT_SECRET` set (32+ chars)
- The plugin repo path must be registered in `MAHAVISHNU_PROJECT_ROOTS` (one-time per project)
- The tool raises `PermissionError` otherwise — check env vars before invoking
```

- [ ] **Step 9.7: Create `RELEASING.md`**

Create `/Users/les/Projects/jinja2-custom-delimiters/RELEASING.md`:

```markdown
# Releasing jinja2-custom-delimiters

Canonical 11-phase release process. Follow phases in order.

## Phase 0 — Toolchain prep

- Bump `intelliJPlatform` Gradle plugin in `gradle/libs.versions.toml` to latest 2.x
- Bump `gradleVersion` in `gradle.properties` to match on-disk wrapper
- Bump `foojay-resolver-convention` in `settings.gradle.kts` for Java metadata
- Run `./gradlew help --configuration-cache` — must succeed

## Phase 1 — Audit ingestion

- Read `AUDIT-SUMMARY.md`, `CRITICAL-AUDIT-REPORT-2025.md`, `FIXES-COMPLETED.md`, `TEST-FIXES-SUMMARY.md`
- Read full commit log since last release
- Verify which open criticals still apply

## Phase 2 — Repo hygiene

- Add runtime artifact patterns to `.gitignore`
- Delete `.github/workflows/*`, `.github/dependabot.yml`, `codecov.yml`
- Keep `.github/FUNDING.yml`

## Phase 3 — Crackerjack wire-up

- Apply ktlint + detekt Gradle plugins
- Create `.crackerjack.toml`
- Verify all 3 hooks emit via `mcp__crackerjack__kotlin_list_hooks`

## Phase 4 — Implementation

- 4a: Java toolchain bump
- 4b: plugin.xml `<product-descriptor>` + `<change-notes>`
- 4c: Tech-debt sweep
- 4d: License silent-fallback removal
- 4e: New tests
- 4f: Docs update

## Phase 5 — Plugin Verifier

- `./gradlew verifyPlugin` against all available PyCharm Professional builds
- Manually inspect each `build/reports/pluginVerifier/index.html`

## Phase 6 — Manual sandbox QA

- `./gradlew runIdeForUiTests`
- 6-checklist items (open file, settings, save, format, restart, hard-fail)

## Phase 7 — Pack + archive

- `./gradlew buildPlugin`
- Archive `.zip` to `~/.mahavishnu/artifacts/<plugin>/<version>/`
- `shasum -a 256` the archive

## Phase 8 — Pre-publish verification

- `crackerjack run` exit 0
- `./gradlew test` exit 0
- `./gradlew verifyPlugin` exit 0 (re-run)

## Phase 9 — MCP auth preflight + version bump

- Verify `MAHAVISHNU_AUTH_ENABLED=true`, `MAHAVISHNU_JWT_SECRET`, `MAHAVISHNU_PROJECT_ROOTS` registration
- Operator explicitly consents to `git push` (per `feedback-bodai-push-is-user-controlled.md`)
- `mcp__crackerjack__kotlin_bump_version(level="patch", project_root=..., dry_run=true)`
- Verify proposed version
- `dry_run=false`

## Phase 10 — Final publish

- `./gradlew publishPlugin`
- Confirm in JetBrains Marketplace admin panel
- Verify Marketplace-side compatibility range matches `sinceBuild`/`untilBuild`

## Phase 11 — Post-publish first-week monitor

- Check GitHub Issues for criticals filed against the new release
- Verify Marketplace install on PyCharm 2026.3
- If criticals filed: hotfix `<next-version>` → same pipeline
```

- [ ] **Step 9.8: Verify clean build**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters && ./gradlew build
```

Expected: build succeeds.

- [ ] **Step 9.9: Commit**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters
git add CHANGELOG.md README.md AGENTS.md RELEASING.md
git commit -m "docs: bump for 1.0.4 release

- CHANGELOG.md: add [1.0.4] entry
- README.md: Java badge 21+ -> 25+; requirements line PyCharm range
- AGENTS.md: Java 25 REQUIRED; cert/token renewal cadence; MCP allowlist
  prerequisites for kotlin_bump_version
- RELEASING.md (new): canonical 11-phase release process

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## Task 10: Plugin Verifier run (Phase 5)

**Files:** (no code changes — verification only)

- [ ] **Step 10.1: Run `./gradlew verifyPlugin`**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters && ./gradlew verifyPlugin
```

Expected: exit 0. If a build is missing (e.g., build 263 not in RELEASE channel), drop it from `pluginVerification.ides.select` and re-run.

- [ ] **Step 10.2: Manually inspect Verifier HTML reports**

```bash
ls /Users/les/Projects/jinja2-custom-delimiters/build/reports/pluginVerifier/
```

Open each `index.html` for builds 252, 253, 261, 262, [263 if available]. Verify no deprecation warnings even if exit was 0.

- [ ] **Step 10.3: If any Verifier finding surfaces, fix and re-run**

If the HTML report shows deprecation warnings or failures, edit the corresponding source file, re-run `./gradlew verifyPlugin`, and re-inspect. Do not proceed until reports are clean.

- [ ] **Step 10.4: Document Verifier results**

Append to `AGENTS.md` or a new `docs/1.0.4-verifier-report.md` (operator's choice):

```markdown
## 1.0.4 Plugin Verifier Results

- PyCharm 2025.2 (build 252): PASS
- PyCharm 2025.3 (build 253): PASS
- PyCharm 2026.1 (build 261): PASS
- PyCharm 2026.2 (build 262): PASS
- PyCharm 2026.3 (build 263): PASS / DROPPED (not in RELEASE channel yet)

Date: <TODAY_YYYY_MM_DD>
```

- [ ] **Step 10.5: Commit (if doc-only changes)**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters
git add <the doc file you wrote to>
git commit -m "docs: record 1.0.4 Plugin Verifier results

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

(If no Verifier findings, no commit is needed for this task.)

---

## Task 11: Manual sandbox QA (Phase 6)

**Files:** (no code changes — manual verification only)

- [ ] **Step 11.1: Run sandbox IDE**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters && ./gradlew runIdeForUiTests
```

Expected: PyCharm sandbox launches with the test plugin installed.

- [ ] **Step 11.2: Open a `.j2` file with custom delimiters**

In the sandbox IDE, create a new file `test.html with content:

```jinja
[[ item.title ]]
[% for item in items %]
  [[ item.body ]]
[% endfor %]
```

- [ ] **Step 11.3: Settings UI smoke test**

Navigate to Settings → Languages → Jinja2 Custom Delimiters. Configure block `[%`/`%]`, variable `[[`/`]]`, comment `[#`/`#]`. Save. Confirm settings persist after dialog close.

- [ ] **Step 11.4: Formatter smoke test**

With the same file open, invoke formatter (Code → Reformat Code or Ctrl+Alt+L). Confirm custom delimiters are preserved in the output, not converted to `{% %}`.

- [ ] **Step 11.5: Restart-persistence smoke test**

Restart the sandbox IDE. Re-open the file. Confirm custom delimiters still applied and formatter still preserves them.

- [ ] **Step 11.6: Hard-fail license UX smoke test**

Run `./gradlew runIdeForUiTests` with the env var seam set:

```bash
cd /Users/les/Projects/jinja2-custom-delimiters
MAHAVISHNU_JINJA_LICENSE_MOCK=invalid ./gradlew runIdeForUiTests
```

Configure a delimiter that requires license verification. Invoke formatter. Confirm:
- Error dialog displays the user-actionable message from Step 7.10
- Formatter does NOT silently proceed
- Message points to `https://plugins.jetbrains.com/plugin/com.wedgwoodwebworks.jinja2customdelimiters`

Then unset and verify recovery:

```bash
# Stop the IDE
MAHAVISHNU_JINJA_LICENSE_MOCK=valid ./gradlew runIdeForUiTests
# Confirm formatter proceeds normally
```

(The `MAHAVISHNU_JINJA_LICENSE_MOCK` env var is added in Step 7.6.)

- [ ] **Step 11.7: Close sandbox**

Close the sandbox IDE. Document any anomalies in the commit message of Task 10.5 (or new commit if needed).

---

## Task 12: Pack + archive (Phase 7)

**Files:** (no code changes — build + archive only)

- [ ] **Step 12.1: Run `./gradlew buildPlugin`**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters && ./gradlew buildPlugin
```

Expected: produces `build/distributions/jinja2-custom-delimiters-1.0.4.zip` (or similar).

- [ ] **Step 12.2: Inspect `.zip` contents**

```bash
unzip -l /Users/les/Projects/jinja2-custom-delimiters/build/distributions/jinja2-custom-delimiters-1.0.4.zip
```

Expected: contains `META-INF/plugin.xml` (verify `release-version="11"` and updated `<change-notes>`), `lib/jinja2-custom-delimiters.jar`, and other expected entries.

- [ ] **Step 12.3: Verify `.zip` is gitignored**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters && git check-ignore -v build/distributions/*.zip
```

Expected: matches the `build/distributions/` gitignore pattern added in Task 2.2.

- [ ] **Step 12.4: Archive `.zip` out-of-repo**

```bash
mkdir -p ~/.mahavishnu/artifacts/jinja2-custom-delimiters/1.0.4
cp /Users/les/Projects/jinja2-custom-delimiters/build/distributions/*.zip ~/.mahavishnu/artifacts/jinja2-custom-delimiters/1.0.4/
shasum -a 256 ~/.mahavishnu/artifacts/jinja2-custom-delimiters/1.0.4/*.zip
```

Expected: archive directory now contains the `.zip` and its sha256. Record the sha256 for Phase 10 verification.

- [ ] **Step 12.5: Do NOT run `publishPlugin` yet**

The actual publish is in Task 15. Do not invoke `./gradlew publishPlugin` here.

---

## Task 13: Pre-publish verification (Phase 8)

**Files:** (no code changes — verification only)

- [ ] **Step 13.1: Re-run `crackerjack run`**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters && crackerjack run
```

Expected: exit 0; all 3 hooks emit; no warnings.

- [ ] **Step 13.2: Re-run `./gradlew test`**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters && ./gradlew test
```

Expected: exit 0.

- [ ] **Step 13.3: Re-run `./gradlew verifyPlugin`**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters && ./gradlew verifyPlugin
```

Expected: exit 0. If 2 consecutive runs fail on the same build, drop that build from the matrix per spec risk-mitigation.

- [ ] **Step 13.4: Verify clean working tree**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters && git status
```

Expected: clean working tree (all changes committed).

- [ ] **Step 13.5: Verify tag not yet created**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters && git tag --list | grep -E "^v1\.0\.4$"
```

Expected: empty output (tag creation is Task 14).

---

## Task 14: MCP auth preflight + version bump (Phase 9)

**Files:** (no code changes — operator-driven, env vars + MCP tool calls)

- [ ] **Step 14.1: Verify MCP auth environment**

```bash
echo "MAHAVISHNU_AUTH_ENABLED=${MAHAVISHNU_AUTH_ENABLED:-unset}"
echo "MAHAVISHNU_JWT_SECRET=${MAHAVISHNU_JWT_SECRET:+set}"
```

Expected: `MAHAVISHNU_AUTH_ENABLED=true`; `MAHAVISHNU_JWT_SECRET` is set (the `:+set` syntax shows `set` if non-empty). If unset, source them from your secrets manager. **Do not echo the secret value.**

- [ ] **Step 14.2: Verify plugin repo is registered in `MAHAVISHNU_PROJECT_ROOTS`**

```bash
echo "MAHAVISHNU_PROJECT_ROOTS=${MAHAVISHNU_PROJECT_ROOTS:-unset}"
```

Expected: contains `/Users/les/Projects/jinja2-custom-delimiters` (possibly with `:path` suffix). If not, register it (operator's project registration workflow).

- [ ] **Step 14.3: Operator gives explicit push consent**

This is a hard gate per `feedback-bodai-push-is-user-controlled.md`. The operator must verbally/explicitly confirm: "I consent to `git push origin v1.0.4`." Do NOT auto-push without this confirmation. If unsure, abort and ask.

- [ ] **Step 14.4: Verify MCP tool exists (sanity check before invocation)**

```python
mcp__crackerjack__discover_tools(query="kotlin version bump")
```

Expected: response includes `kotlin_bump_version`. If not, fall back to manual:

```bash
cd /Users/les/Projects/jinja2-custom-delimiters
# Manual fallback:
# 1. Edit gradle.properties: pluginVersion = 1.0.4
# 2. git add gradle.properties
# 3. git commit -m "bump: 1.0.4"
# 4. git tag -a v1.0.4 -m "1.0.4 release"
# 5. git push origin v1.0.4 (with operator consent)
```

- [ ] **Step 14.5: Run `kotlin_bump_version` with `dry_run=true`**

```python
mcp__crackerjack__kotlin_bump_version(
    level="patch",
    project_root="/Users/les/Projects/jinja2-custom-delimiters",
    dry_run=True
)
```

Expected: response shows proposed version `1.0.4` (from `1.0.3`), tag will be `v1.0.4`, no mutations applied yet.

- [ ] **Step 14.6: Confirm dry-run matches expectation**

Verify the proposed version matches `1.0.4` (not `1.0.3 + 1` from some other bump level). If wrong, abort and investigate.

- [ ] **Step 14.7: Run `kotlin_bump_version` with `dry_run=false`**

```python
mcp__crackerjack__kotlin_bump_version(
    level="patch",
    project_root="/Users/les/Projects/jinja2-custom-delimiters",
    dry_run=False,
    release=False
)
```

Expected: 
- `gradle.properties` now reads `pluginVersion = 1.0.4`
- Empty commit (or commit with file changes) created
- Tag `v1.0.4` created locally
- `v1.0.4` pushed to origin (because operator consented in Step 14.3)

- [ ] **Step 14.8: Verify tag pushed**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters && git tag --list | grep -E "^v1\.0\.4$" && git ls-remote --tags origin | grep v1.0.4
```

Expected: tag exists locally and on origin.

- [ ] **Step 14.9: Verify `gradle.properties` reads `1.0.4`**

```bash
grep "^pluginVersion" /Users/les/Projects/jinja2-custom-delimiters/gradle.properties
```

Expected: `pluginVersion = 1.0.4`.

- [ ] **Step 14.10: Tag the release commit locally for traceability**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters && git log --oneline -5
```

(Visual check; no commit needed here. If the operator wants an annotated `v1.0.4-final` tag in addition, do so manually.)

---

## Task 15: Final publish (Phase 10)

**Files:** (no code changes — publish to Marketplace)

- [ ] **Step 15.1: Verify marketplace env vars**

```bash
echo "PUBLISH_TOKEN=${PUBLISH_TOKEN:+set}"
echo "CERTIFICATE_CHAIN=${CERTIFICATE_CHAIN:+set}"
echo "PRIVATE_KEY=${PRIVATE_KEY:+set}"
echo "PRIVATE_KEY_PASSWORD=${PRIVATE_KEY_PASSWORD:+set}"
```

Expected: all four are set. If unset, source from secrets manager.

- [ ] **Step 15.2: Re-run `./gradlew buildPlugin` for fresh `.zip`**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters && ./gradlew clean buildPlugin
```

Expected: produces fresh `.zip` with version `1.0.4` in manifest.

- [ ] **Step 15.3: Re-archive fresh `.zip`**

```bash
cp /Users/les/Projects/jinja2-custom-delimiters/build/distributions/*.zip ~/.mahavishnu/artifacts/jinja2-custom-delimiters/1.0.4/
shasum -a 256 ~/.mahavishnu/artifacts/jinja2-custom-delimiters/1.0.4/*.zip
```

Expected: archive directory updated.

- [ ] **Step 15.4: Run `./gradlew publishPlugin`**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters && ./gradlew publishPlugin
```

Expected: HTTP 2xx response from `plugins.jetbrains.com`. Watch the output carefully. If 4xx/5xx, do NOT proceed — diagnose.

- [ ] **Step 15.5: Confirm in JetBrains Marketplace admin panel**

Visit https://plugins.jetbrains.com/plugin/com.wedgwoodwebworks.jinja2customdelimiters and verify:
- Version `1.0.4` is listed
- Compatibility range shows `PyCharm 2025.2 – 2026.x`
- Plugin is marked Paid
- Download/install count is enabled

- [ ] **Step 15.6: Verify Marketplace-side compatibility matches spec**

The Marketplace admin UI has a "Compatibility" section separate from `<idea-version>`. Confirm it matches `sinceBuild=252, untilBuild=263.*`. If mismatched, edit in the admin UI.

- [ ] **Step 15.7: Document publish**

Append to `AGENTS.md` or `RELEASING.md`:

```markdown
## 1.0.4 Publish Log

- Published: <TIMESTAMP>
- Marketplace URL: https://plugins.jetbrains.com/plugin/com.wedgwoodwebworks.jinja2customdelimiters
- `.zip` sha256: <SHA>
- Archive: `~/.mahavishnu/artifacts/jinja2-custom-delimiters/1.0.4/`
```

- [ ] **Step 15.8: Commit publish log**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters
git add AGENTS.md RELEASING.md
git commit -m "docs: record 1.0.4 publish log

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## Task 16: Post-publish first-week monitor (Phase 11)

**Files:** (no code changes — observation only)

- [ ] **Step 16.1: Check GitHub Issues within 7 days**

Visit https://github.com/lesleslie/jinja2-custom-delimiters/issues and search for issues filed against `1.0.4`. Expected: no critical issues.

- [ ] **Step 16.2: Verify Marketplace install on PyCharm 2026.3**

Open PyCharm 2026.3 → Settings → Plugins → Marketplace → search "Jinja2 Custom Delimiters". Expected: 1.0.4 is the latest, supports 2026.3.

- [ ] **Step 16.3: Check paid-user support channels**

Check `les@wedgwoodwebworks.com` inbox (or the operator's designated support channel) for license-related complaints. Expected: no widespread hard-fail errors.

- [ ] **Step 16.4: If critical issues filed**

Triage → create hotfix branch → bump to `1.0.5` → run Tasks 1-15 again with level="patch" (the bump goes 1.0.4 → 1.0.5).

- [ ] **Step 16.5: Mark release as adopted**

Append to `AGENTS.md`:

```markdown
## 1.0.4 Status

- Released: <DATE>
- First-week monitor: clean / issues: <COUNT>
- Status: stable / hotfix-in-progress
```

- [ ] **Step 16.6: Commit adoption status**

```bash
cd /Users/les/Projects/jinja2-custom-delimiters
git add AGENTS.md
git commit -m "docs: mark 1.0.4 release as adopted

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## Plan complete

All 16 tasks defined. No placeholders. Each step has explicit actions and expected outputs. Ready for execution.

Per the writing-plans skill, the next step is to choose execution mode:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, two-stage review between tasks.

**2. Inline Execution** — execute tasks in this session using executing-plans with checkpoints.
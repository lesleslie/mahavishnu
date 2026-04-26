# Pattern Learning & Scaffolding Design

**Date:** 2026-04-26
**Status:** Draft
**Approach:** Pattern Library Service (Approach B)
**Prerequisites:** Config Consolidation (2026-04-26-config-consolidation-design.md), Agent & Skill Modernization (2026-04-26-agent-skill-modernization-design.md), Code Indexing Integration (2026-04-26-code-indexing-integration-design.md)

## 1. Problem Statement

Mahavishnu can orchestrate workflows across repositories but cannot learn and reproduce the architectural patterns used in existing Fastblocks/Oneiric web applications. When building a new Fastblocks app, every project starts from scratch — there is no mechanism to say "use the auth pattern from Splashstand" or "generate a project skeleton like Fastblocks."

**Current state:**
- **Fastblocks** is an async Python web framework (Starlette + Jinja2 `[[ ]]` delimiters + HTMX + Oneiric adapters)
- **Splashstand** is a production reference implementation demonstrating real-world Fastblocks patterns (auth, admin, analytics, PWA, Cloud Run deployment)
- The ecosystem has symbol-level code graphs (functions, classes, imports) but no **architectural pattern** detection or storage
- No scaffolding capability — Mahavishnu cannot generate new projects from learned patterns
- Each new Fastblocks app requires manually replicating conventions from previous projects

**Impact:** Building a new Fastblocks/Oneiric web app requires manual replication of established patterns from existing projects. This is slow, error-prone, and doesn't scale beyond the patterns held in a single developer's memory.

## 2. Goals

- Store reusable architectural patterns from existing Fastblocks/Oneiric projects in a structured, queryable format
- Provide a CLI to scaffold new Fastblocks projects from composed patterns
- Support hybrid interaction: pattern selection for architecture skeleton, chat-driven generation for custom parts
- Suggest new patterns from existing code using the code graph (human-in-the-loop, never auto-save)
- Validate generated projects against pattern contracts
- Generate complete, runnable Fastblocks projects — not just skeletons

## 3. Non-Goals

- Building a web UI for pattern browsing (CLI + chat is sufficient)
- Learning business logic patterns from existing apps (only scaffolding + component patterns)
- Supporting non-Fastblocks frameworks (React, Django, etc.)
- Replacing existing project templates or cookiecutters
- Auto-deploying generated apps (generation only — deployment is a separate concern)
- Creating a " marketplace" for sharing patterns across teams

## 4. Current State

### 4.1 What Exists Today

| Capability | Component | Status |
|-----------|-----------|--------|
| Symbol-level code graph | Akosha + Session-Buddy | Built — functions, classes, imports, calls |
| Cross-repo symbol search | Akosha `search_all_systems` | Built |
| Skill tracking | Session-Buddy | Built — invocation history, success rates |
| Workflow orchestration | Mahavishnu | Built — multi-repo task execution |
| Quality gates | Crackerjack | Built — lint, test, scan |
| Code graph indexing | Mahavishnu (spec 3) | Designed — call chains, impact analysis, re-indexing |

### 4.2 What's Missing

| Capability | Gap Description |
|-----------|----------------|
| Architectural pattern detection | No system detects project-level patterns (directory structure, adapter wiring, template conventions) |
| Pattern library | No structured storage of "canonical Fastblocks patterns" |
| Code scaffolding | No ability to generate new projects from pattern templates |
| Pattern composition | No mechanism to combine multiple patterns (auth + nav + dashboard) |
| Pattern provenance | No way to trace patterns back to their source repos |
| Framework awareness | Code graph treats Fastblocks symbols the same as any Python symbols |

### 4.3 Reference: What Lovable Does

Lovable generates full React/Supabase apps from chat. Key capabilities to learn from:

1. **Template library** — curated component templates (auth flows, dashboards, forms) with metadata
2. **Code generation** — natural language → working project with real dependencies
3. **Iterative refinement** — chat-driven modifications after initial generation
4. **Framework awareness** — understands React conventions, Supabase schemas, Tailwind classes

This spec adapts those capabilities for the Fastblocks/Oneiric ecosystem.

## 5. Architecture

### 5.1 Three-Module Pipeline

```
Existing Projects (Fastblocks, Splashstand, future apps)
         │
         ▼
┌─────────────────┐
│  Pattern         │  Analyzes projects, suggests patterns, never auto-saves
│  Extractor      │  (manual curation + AI suggestion + conversation capture)
└────────┬────────┘
         │ writes
         ▼
┌─────────────────┐
│  Pattern         │  Structured YAML files, version-controlled, queryable
│  Library        │  Organized by category: scaffolding/, components/, deployment/
│  (YAML files)   │  Each pattern has: structure, templates, slots, metadata
└────────┬────────┘
         │ reads
         ▼
┌─────────────────┐
│  Scaffolding     │  Composes patterns → generates working project on disk
│  Engine         │  Phase 1: deterministic template rendering (skeleton)
│                 │  Phase 2: AI-assisted chat refinement (custom parts)
└────────┬────────┘
         │ outputs
         ▼
  New Fastblocks App (on disk, ready to run)
```

### 5.2 Module Responsibilities

| Module | Reads | Writes | Interface |
|--------|-------|--------|-----------|
| Pattern Extractor | Code graph (spec 3), project files | Pattern Library (YAML files) | `mahavishnu patterns create/suggest` CLI commands |
| Pattern Library | YAML pattern files | Nothing (read-only) | YAML file system + query module |
| Scaffolding Engine | Pattern Library, user chat | File system (new project) | `mahavishnu scaffold` CLI command + chat integration |

### 5.3 Storage Location

Patterns live in the Mahavishnu project directory:

```
mahavishnu/
├── patterns/                      # Pattern Library root
│   ├── scaffolding/               # Project skeleton patterns
│   │   ├── project.yaml          # Base Fastblocks project structure
│   │   └── minimal.yaml          # Minimal project (no adapters)
│   ├── components/                # Reusable UI component patterns
│   │   ├── nav.yaml              # Navigation bar component
│   │   ├── table.yaml            # Data table with HTMX pagination
│   │   ├── form.yaml             # Form component with validation
│   │   ├── card.yaml             # Reusable card/panel component
│   │   └── dashboard.yaml        # Dashboard layout with widgets
│   ├── adapters/                  # Adapter integration patterns
│   │   ├── auth.yaml             # Authentication adapter (session-based)
│   │   ├── analytics.yaml        # Analytics integration adapter
│   │   └── admin.yaml           # Admin panel adapter
│   ├── deployment/               # Deployment configuration patterns
│   │   ├── cloudrun.yaml         # Google Cloud Run deployment
│   │   ├── docker.yaml           # Docker containerization
│   │   └── github-actions.yaml   # CI/CD via GitHub Actions
│   └── composite/                 # Multi-pattern compositions
│       ├── splashstand-app.yaml # Full Splashstand-like app (composite)
│       └── ...
```

Patterns are YAML files, not database records. Rationale:
- Human-editable (manual curation is the primary input method)
- Git-versioned (pattern evolution is trackable)
- Git-friendly (diffs show pattern changes clearly)
- No operational complexity (no database to run, backup, or migrate)
- Queryable via simple YAML parsing (no query language needed)

### 5.4 Principle Compliance

| Principle | Compliance |
|-----------|-----------|
| 1. One owner per concern | Pattern Library owns pattern data. Engine owns generation. Extractor owns suggestion logic. |
| 2. Cache is not authority | Pattern YAML files are the authority, not derived data. |
| 3. UI is presentation | CLI + chat are interfaces; patterns are the data. |
| 4. Review-gated learning | AI suggestions are drafts, never auto-saved. |
| 5. Reuse mature systems | Builds on code graph (spec 3), config consolidation (spec 1), skill modernization (spec 2). |
| 6. Security boundaries | Generated projects contain no secrets. Config values are placeholders. |
| 7. Typed contracts | Pattern YAML schema validated by Pydantic model at load time. |

## 6. Pattern Format

### 6.1 Pattern YAML Schema

Each pattern is a single YAML file with this structure:

```yaml
# Metadata
id: scaffolding/project
name: Fastblocks Project Skeleton
description: Base project structure with Oneiric config, entry point, and settings
version: 1.0
source_repos: [fastblocks, splashstand]
confidence: 0.95
depends: []
tags: [fastblocks, skeleton, base]

# Structural definition
structure:
  dirs:
    - path: settings/
      required: true
      description: Oneiric YAML configuration directory
    - path: templates/base/blocks/
      required: true
      description: Base template blocks for HTMX partial rendering
    - path: templates/pages/
      required: false
      description: Page-level templates
    - path: adapters/
      required: false
      description: Custom Oneiric adapters
    - path: static/
      required: false
      description: Static assets (CSS, JS, images)
  files:
    - path: main.py
      required: true
      template: entry-point
      description: Application entry point with route definitions
    - path: pyproject.toml
      required: true
      template: pyproject
      description: Python project dependencies and metadata
    - path: settings/app.yml
      required: true
      template: settings-app
      description: Application-level Oneiric settings
    - path: settings/adapters.yml
      required: false
      template: settings-adapters
      description: Adapter configuration

# Jinja templates for file content generation
templates:
  entry-point: |
    from starlette.routing import Route
    from oneiric.core.resolution import Resolver

    depends = Resolver()

    def resolve_dep(key):
        candidate = depends.resolve("{{ project_name }}", key)
        if candidate is None:
            raise RuntimeError(f"Missing dependency: {key}")
        factory = getattr(candidate, "factory", None)
        return factory() if callable(factory) else candidate

    routes = [Route("/", endpoint=homepage)]
    app = resolve_dep("app")
  pyproject: |
    [project]
    name = "{{ project_name }}"
    requires-python = ">=3.12"
    dependencies = ["fastblocks", "oneiric"]

# Extension points for other patterns
slots:
  nav: templates/base/blocks/
  auth: adapters/
  middleware: main.py
```

### 6.2 Slot Mechanism

Slots are named extension points where component patterns plug in. When a pattern declares `slot: scaffolding/project:templates/base/blocks/`, it means "this pattern's files go into the project's base blocks directory."

**Slot resolution rules:**
1. Only one pattern can claim a slot per project (conflict detection)
2. Slot paths are relative to the project root
3. If a required slot has no pattern, scaffolding fails with a clear error ("nav slot declared by project pattern but no nav pattern included")
4. Optional slots are silently skipped if unpopulated

### 6.3 Pattern Composition

Patterns compose via dependency resolution:

```yaml
# composite/pwa-app.yaml
id: composite/pwa-app
name: Full PWA Application
depends:
  - scaffolding/project
  - components/nav
  - components/form
  - components/table
  - adapters/auth
  - deployment/cloudrun
```

The Engine resolves this as a dependency graph:
1. `scaffolding/project` is the root (no dependencies)
2. Component patterns plug into project's slots
3. Adapter patterns plug into project's adapter slot
4. Deployment patterns add deployment config files

### 6.4 Pattern Variables

Templates use Jinja2 variables for customization:

| Variable | Source | Description |
|----------|--------|-------------|
| `{{ project_name }}` | CLI argument | Python package name (kebab-case) |
| `{{ project_title }}` | CLI argument or config | Human-readable title |
| `{{ author }}` | Git config | Author name for pyproject.toml |
| `{{ version }}` | CLI flag or "0.1.0" | Initial version |

Templates are rendered with these variables at generation time. The same template with different variables produces different content.

## 7. Pattern Extractor

### 7.1 Three Entry Points

**Manual curation (primary):**
```bash
mahavishnu patterns create \
  --name "auth" \
  --from-project splashstand \
  --category adapters \
  --description "Session-based auth with CSRF protection"
```

Opens an editor with a draft YAML pre-populated from the source project's structure. Developer edits and saves.

**AI suggestion (builds on code indexing spec):**
```bash
mahavishnu patterns suggest \
  --repos fastblocks,splashstand \
  --confidence-threshold 0.7
```

Uses the code graph to find recurring structures:
1. Cluster projects by directory layout similarity (shared dirs, similar nesting depth)
2. Within clusters, identify shared files (same filenames, similar imports)
3. Extract common adapter registrations, middleware stacks, template structures
4. Draft a pattern YAML with confidence score based on prevalence across repos
5. Present to human for approval — never auto-saves

**Conversation capture (builds on session-buddy):**
After successfully building an app via chat, Mahavishnu offers:
- "This app used 4 patterns: project, nav, auth, cloudrun. Save as a composite pattern?"
- The composite pattern captures the exact file structure and configuration from the session

### 7.2 AI Suggestion Algorithm

```python
def suggest_patterns(repo_paths: list[str]) -> list[PatternDraft]:
    """Analyze repos and suggest patterns using code graph data."""
    # 1. Collect directory structures from all repos
    dir_structures = {repo: get_directory_tree(repo) for repo in repo_paths}

    # 2. Find shared directory patterns (directories appearing in N/M repos)
    shared_dirs = find_common_subtrees(dir_structures, min_prevalence=0.5)

    # 3. For each shared directory, find shared files
    for dir_path, prevalence in shared_dirs.items():
        shared_files = find_common_files(dir_structures, dir_path, min_prevalence=0.5)

    # 4. Cluster into pattern categories
    patterns = cluster_into_patterns(shared_dirs, shared_files)

    # 5. For each pattern, extract common file content as templates
    for pattern in patterns:
        pattern.templates = extract_common_templates(
            dir_structures, pattern.files, min_prevalence=0.5
        )

    # 6. Score by confidence (prevalence across repos + structural consistency)
    for pattern in patterns:
        pattern.confidence = calculate_confidence(
            prevalence=pattern.repo_count / len(repo_paths),
            consistency=measure_structural_consistency(pattern)
        )

    return [p for p in patterns if p.confidence >= threshold]
```

**Important:** The suggestion algorithm produces drafts, not patterns. All drafts require human review before entering the Pattern Library.

### 7.3 Pattern Validation

When a pattern is saved (manually or after review), it's validated:

```python
def validate_pattern(pattern: Pattern) -> list[ValidationIssue]:
    issues = []

    # Schema validation
    issues.extend(validate_yaml_schema(pattern))

    # Structural integrity
    for f in pattern.structure.files:
        if f.required and not has_template(pattern, f):
            issues.append(f"Required file '{f.path}' has no template")

    # Slot compatibility
    for slot_name, slot_path in pattern.slots.items():
        if not slot_path.startswith(pattern.structure.dirs[0].path):
            issues.append(f"Slot '{slot_name}' path '{slot_path}' is outside pattern dirs")

    # Cross-pattern consistency
    if pattern.depends:
        for dep_id in pattern.depends:
            if not pattern_library.has(dep_id):
                issues.append(f"Dependency '{dep_id}' not found in library")

    return issues
```

## 8. Scaffolding Engine

### 8.1 Phase 1: Deterministic Scaffolding

```bash
mahavishnu scaffold "my-app" \
  --patterns scaffolding/project,components/nav,components/table,components/form \
  --title "My Application" \
  --author "les" \
  --output /Users/les/Projects/my-app
```

**Execution:**
1. Load all pattern YAMLs from the library
2. Build dependency graph from `depends` fields
3. Validate: all dependencies satisfied, no slot conflicts
4. Topological sort patterns (dependencies first)
5. For each pattern (in order):
   a. Create required directories
   b. Render required files from templates (with variables filled in)
   c. Register slot claims (so dependent patterns know where to write)
6. Write pyproject.toml, settings, entry point
7. Run `uv init` or equivalent to install dependencies
8. Verify: `mahavishnu patterns validate --project /Users/les/Projects/my-app`

**Output:** A working Fastblocks project with proper structure, config, and basic components. Ready to `python main.py`.

### 8.2 Phase 2: Chat-Driven Refinement

After Phase 1, the user continues in a Mahavishnu session:

```
User: "Add a dashboard page with a stats summary card"
→ Mahavishnu generates templates/pages/dashboard.html
→ Adds dashboard route to main.py
→ Validates output against composed pattern spec

User: "Use the auth pattern with Google OAuth"
→ Mahavishnu loads adapters/auth.yaml pattern
→ Runs Phase 1 composition with auth pattern added
→ Generates adapters/auth.py, settings/auth.yml
→ Updates main.py with session middleware

User: "Deploy to Cloud Run"
→ Mahavishnu loads deployment/cloudrun.yaml pattern
→ Generates Dockerfile, cloudbuild.yaml
→ Adds deploy command to pyproject.toml
```

Each Phase 2 step is either:
- **Pattern composition** (loading a new pattern and re-running Phase 1 for affected files)
- **AI generation** (Claude generates custom content for pages, business logic, etc.)

### 8.3 Pattern Contract Validation

After each generation step (Phase 1 or Phase 2), the Engine validates the output:

```python
def validate_project(project_path: str, patterns: list[Pattern]) -> list[Issue]:
    issues = []

    # Check required structure
    for pattern in patterns:
        for d in pattern.structure.dirs:
            if d.required and not (project_path / d.path).exists():
                issues.append(f"Required directory '{d.path}' missing from generated project")

    # Check required files
    for pattern in patterns:
        for f in pattern.structure.files:
            if f.required and not (project_path / f.path).exists():
                issues.append(f"Required file '{f.path}' missing from generated project")

    # Check slot integrity
    for pattern in patterns:
        for slot_name, slot_path in pattern.slots.items():
            slot_dir = project_path / slot_path
            if slot_dir.exists():
                files_in_slot = list(slot_dir.glob("*"))
                if not files_in_slot:
                    issues.append(f"Slot '{slot_name}' is empty — no pattern filled it")

    return issues
```

### 8.4 Generation Idempotency

Re-running scaffolding with the same patterns and variables produces the same output. This enables:

- **Diffing** two generated projects to see what changed
- **Re-scaffolding** a project to update it to a new pattern version
- **Conflict detection** when manual edits overlap with pattern-managed files

Pattern-managed files include a header comment:
```python
# pattern: scaffolding/project v1.0
# DO NOT EDIT BELOW THIS LINE — managed by mahavishnu scaffold
# To customize, modify the pattern template, not this file
```

If a user edits a pattern-managed file and then re-scaffolds, the Engine detects the conflict and offers:
1. Keep manual edits (remove pattern management header from that file)
2. Overwrite with pattern (lose manual edits)
3. Show diff and let user decide

## 9. CLI Interface

### 9.1 Pattern Management Commands

```bash
# Create a pattern manually
mahavishnu patterns create --name "auth" --from-project splashstand --category adapters

# Suggest patterns from existing repos (AI-assisted)
mahavishnu patterns suggest --repos fastblocks,splashstand --confidence-threshold 0.7

# List all patterns
mahavishnu patterns list [--category scaffolding|components|adapters|deployment|composite]

# Show pattern details
mahavishnu patterns show auth

# Validate pattern library integrity
mahavishnu patterns validate

# Search patterns
mahavishnu patterns search --query "authentication" --source-repos splashstand
```

### 9.2 Scaffolding Commands

```bash
# Scaffold a new project
mahavishnu scaffold "my-app" \
  --patterns scaffolding/project,components/nav \
  --title "My Application" \
  --output /path/to/my-app

# Add a pattern to an existing project
mahavishnu scaffold "my-app" --add-pattern components/form --output /path/to/my-app

# Validate a generated project against its patterns
mahavishnu scaffold "my-app" --validate --output /path/to/my-app

# Show what patterns would be included (dry run)
mahavishnu scaffold "my-app" --patterns "*" --dry-run
```

### 9.3 Integration with Existing Mahavishnu CLI

Pattern commands extend the existing CLI namespace:
- `mahavishnu patterns *` — pattern library management
- `mahavishnu scaffold *` — project scaffolding
- Both are subcommands of the `mahavishnu` CLI, following the existing command pattern

## 10. Pattern Categories

### 10.1 Initial Pattern Catalog

**Scaffolding (2 patterns):**

| Pattern | Source | Description |
|--------|--------|-------------|
| `scaffolding/project` | Fastblocks, Splashstand | Full project structure with settings, templates, entry point |
| `scaffolding/minimal` | Fastblocks | Minimal project — just entry point and pyproject.toml |

**Components (6 patterns):**

| Pattern | Source | Description |
|--------|--------|-------------|
| `components/nav` | Splashstand | Navigation bar with mobile responsive toggle |
| `components/table` | Splashstand | Data table with HTMX pagination and sorting |
| `components/form` | Splashstand | Form component with validation and HTMX submission |
| `components/card` | Fastblocks | Reusable card/panel component |
| `components/dashboard` | Splashstand | Dashboard layout with widget slots |
| `components/hero` | Fastblocks | Hero section for landing pages |

**Adapters (3 patterns):**

| Pattern | Source | Description |
|--------|--------|-------------|
| `adapters/auth` | Splashstand | Session-based auth with CSRF, login/logout routes |
| `adapters/analytics` | Splashstand | Analytics integration adapter with event tracking |
| `adapters/admin` | Splashstand | Admin panel with role-based access control |

**Deployment (3 patterns):**

| Pattern | Source | Description |
|--------|--------|-------------|
| `deployment/cloudrun` | Splashstand | Google Cloud Run deployment with Dockerfile and cloudbuild |
| `deployment/docker` | Fastblocks | Docker containerization with multi-stage builds |
| `deployment/github-actions` | Mahavishnu | CI/CD pipeline with quality gates |

**Composite (1 pattern):**

| Pattern | Depends On | Description |
|--------|-----------|-------------|
| `composite/pwa-app` | project, nav, form, table, auth, cloudrun | Full PWA application matching Splashstand's architecture |

## 11. Dependency Chain

This spec depends on three prerequisite specs:

| Prerequisite | Dependency | What This Spec Needs |
|-------------|------------|---------------------|
| Config Consolidation | Self-contained environment | Mahavishnu has access to all MCP tools and agents |
| Agent Modernization | Agents/skills reference ecosystem tools | A "scaffold" skill can orchestrate the engine |
| Code Indexing | Symbol-level code graph | Pattern Extractor uses graph data for AI suggestions |

### 11.1 Delivery Phase

This spec is **Phase 2.5** in the master plan — after the three prerequisite specs complete (Phase 2). Rationale:

- The Pattern Extractor's AI suggestion feature requires the code graph from spec 3
- The Scaffolding Engine's validation requires the config to be consolidated (spec 1)
- The CLI integration requires agents to know about pattern tools (spec 2)

### 11.2 Incremental Delivery

| Delivery | Capability | Depends On | Effort |
|----------|-----------|-----------|--------|
| **1st** | Pattern format + library storage + manual create command | Config consolidation | Small |
| **2nd** | Scaffolding engine Phase 1 (deterministic) | Item 1 | Medium |
| **3rd** | Pattern Extractor (manual + basic AI suggestion) | Code indexing spec | Medium |
| **4th** | Scaffolding engine Phase 2 (chat refinement) | Items 1-3 | Medium |
| **5th** | Conversation capture (save session as composite pattern) | Items 1-4 | Small |
| **6th** | Pattern validation and contract enforcement | Items 1-5 | Small |

## 12. Acceptance Criteria

1. `mahavishnu patterns create --name auth --from-project splashstand` generates a draft pattern YAML in `patterns/adapters/auth.yaml`
2. `mahavishnu patterns suggest --repos fastblocks,splashstand` produces at least 3 suggested patterns with confidence scores
3. Suggested patterns are never auto-saved to the library without human approval
4. `mahavishnu patterns list` shows all patterns grouped by category with version and source repos
5. `mahavishnu scaffold "test-app" --patterns scaffolding/project` generates a working Fastblocks project that runs with `python main.py`
6. Generated project has the correct directory structure matching the pattern's `structure.dirs` specification
7. Generated files contain the pattern management header comment
8. `mahavishnu scaffold "test-app" --add-pattern components/nav` adds the nav component without breaking existing files
9. `mahavishnu scaffold "test-app" --validate` reports zero contract violations
10. Re-scaffolding with the same patterns produces the same output (deterministic)
11. Phase 2 chat refinement ("add a dashboard page") generates `templates/pages/dashboard.html` and updates `main.py`
12. Adding a pattern via chat triggers validation and reports any contract violations
13. All 15 initial patterns in Section 10 exist in the library
14. `mahavishnu patterns validate` passes with zero errors on the default pattern catalog
15. No generated project contains secrets, API keys, or credentials — all config values are placeholders

## 13. ADR Reference

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Storage format | YAML files in project directory | Human-editable, git-versioned, no database needed. |
| Pattern composition | Dependency graph with topological sort | Clean ordering, no circular dependencies. |
| Slot mechanism | Named extension points with path resolution | Components declare where they plug in, engine resolves conflicts. |
| Template engine | Jinja2 | Same templating Fastblocks already uses. No new dependency. |
| Phase separation | Deterministic (Phase 1) then AI-assisted (Phase 2) | Phase 1 is repeatable and testable. Phase 2 adds flexibility. |
| File management | Header comments mark pattern-managed files | Enables conflict detection and manual override. |
| AI suggestion | Draft-only, never auto-save | Prevents noise from false-positive pattern detection. |
| Pattern provenance | `source_repos` field in pattern metadata | Enables "show patterns from Splashstand" queries. |

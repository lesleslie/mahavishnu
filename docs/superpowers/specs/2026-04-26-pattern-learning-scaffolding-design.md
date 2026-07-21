---
status: draft
role: implementation
topic: learning-pipeline
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
blocks_on: []
---

# Pattern Learning & Scaffolding Design

**Date:** 2026-04-26
**Status:** Draft <!-- legacy status: Draft — see YAML frontmatter -->
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
1. **Code generation** — natural language → working project with real dependencies
1. **Iterative refinement** — chat-driven modifications after initial generation
1. **Framework awareness** — understands React conventions, Supabase schemas, Tailwind classes

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
| Pattern Library | YAML pattern files | Nothing (read-only for Phase 1 scaffolding) | YAML file system + query module |
| Scaffolding Engine | Pattern Library, project manifest | File system (new project), Pattern Library (user-approved composite capture only) | `mahavishnu scaffold` CLI command + chat integration |

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
- Queryable via keyword matching on `name`, `description`, and `tags` fields (no query language needed)

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
# Format version (enables future migrations)
schema_version: 1

# Metadata
id: scaffolding/project
name: Fastblocks Project Skeleton
description: Base project structure with Oneiric config, entry point, and settings
version: "1.0.0"
source_repos: [fastblocks, splashstand]
confidence: 1.0  # 1.0 for manually curated; computed for AI-suggested
# Pattern composition dependencies (NOT Python package dependencies —
# those are handled by the pyproject.toml template)
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
# NOTE: Pattern templates use standard Jinja2 {{ }} delimiters.
# Generated .html template files use Fastblocks [[ ]] delimiters.
# The Engine configures the Jinja2 environment based on output file type.
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
    dependencies = {{ dependencies | toml_array }}
    # toml_array: custom Jinja2 filter registered by the Engine.
    # Takes a list of strings, outputs a TOML array: ["dep1", "dep2"]
    # The Engine registers this filter at startup alongside the Jinja2 environments.

# Extension points for other patterns
slots:
  nav:
    path: templates/base/blocks/
    files: [nav.html, nav-mobile.html]
    required: false
  auth:
    path: adapters/
    files: [auth.py]
    required: false
  middleware:
    path: main.py
    type: file-merge
    merge_strategy: marker-injection
    required: false
```

### 6.2 Slot Mechanism

Slots are named extension points where component patterns plug in. Each slot has a type:

**Directory slots** (default) — the pattern writes files into a directory:

```yaml
slots:
  nav:
    path: templates/base/blocks/
    files: [nav.html, nav-mobile.html]
    required: false
```

Multiple patterns can write to the same directory as long as their `files` lists are disjoint. Conflict detection is **file-level**, not directory-level.

**File-merge slots** — the pattern injects content into an existing file:

```yaml
slots:
  middleware:
    path: main.py
    type: file-merge
    merge_strategy: marker-injection
    required: false
```

The owning pattern's template includes markers that merging patterns inject into:

```python
# In scaffolding/project's main.py template:
routes = [Route("/", endpoint=homepage)]

# {{slot:middleware}}

app = resolve_dep("app")
```

When `adapters/auth` claims the `middleware` slot, its template provides the injection content:

```python
# Content injected at {{slot:middleware}}:
from starlette.middleware import Middleware
middleware = [
    Middleware(SessionMiddleware, secret_key="{{ session_secret }}"),
]
```

**Slot resolution rules:**

1. **File-level conflict detection**: two patterns conflict only if they both write the same output file path. Multiple patterns writing to the same directory is allowed.
1. Slot paths are relative to the project root
1. If a required slot has no pattern, scaffolding fails with a clear error ("nav slot declared by project pattern but no nav pattern included")
1. Optional slots (required: false) are silently skipped if unpopulated
1. File-merge slots use marker-injection: the base template defines `{{slot:<name>}}` markers, merging patterns provide replacement content
1. A pattern's `id` prefix must match its parent directory (e.g., `adapters/auth` must live in `patterns/adapters/auth.yaml`)

### 6.3 Pattern Composition

Patterns compose via dependency resolution:

```yaml
# composite/pwa-app.yaml
id: composite/pwa-app
name: Full PWA Application
depends:
  - id: scaffolding/project
    version: ">=1.0.0"
  - id: components/nav
  - id: components/form
  - id: components/table
  - id: adapters/auth
  - id: deployment/cloudrun
```

Composite patterns are **purely additive** — they declare `depends` and `tags` but no `structure`, `templates`, or `slots` of their own. They cannot override a dependency's template. If a different variant is needed (e.g., PWA-specific auth), create a separate pattern (e.g., `adapters/auth-pwa`) that the composite references instead.

The Engine resolves this as a dependency graph:

1. `scaffolding/project` is the root (no dependencies)
1. Component patterns plug into project's slots via file-level claims
1. Adapter patterns plug into project's adapter slot
1. Deployment patterns add deployment config files

**Circular dependency detection:** The Engine runs cycle detection (DFS-based) on the dependency graph during validation. Patterns with circular dependencies fail validation with a clear error identifying the cycle.

### 6.4 Pattern Variables

Templates use Jinja2 variables for customization:

| Variable | Source | Description |
|----------|--------|-------------|
| `{{ project_name }}` | CLI argument | Python package name (kebab-case, e.g., `my-app`) |
| `{{ project_slug }}` | Derived | Python-importable name (snake_case, e.g., `my_app`) |
| `{{ project_title }}` | CLI argument or config | Human-readable title (e.g., `My Application`) |
| `{{ author }}` | Git config | Author name for pyproject.toml |
| `{{ version }}` | CLI flag or `"0.1.0"` | Initial version |
| `{{ python_version }}` | Config or `"3.12"` | Python version for pyproject.toml |
| `{{ dependencies }}` | Computed from pattern set | List of package names, joinable with Jinja2 filters |
| `{{ adapter_names }}` | Computed from pattern set | Names of included adapter patterns |
| `{{ session_secret }}` | Auto-generated | Random secret for session middleware (auth patterns) |

### 6.5 Jinja2 Delimiter Layers

The scaffolding system uses two Jinja2 delimiter configurations:

| Layer | Delimiters | Used For |
|-------|-----------|----------|
| Pattern templates | `{{ }}` / `{% %}` | Scaffolding variables in `.py`, `.toml`, `.yml` templates |
| Generated HTML templates | `[[ ]]` / `[% %]` | Fastblocks-compatible HTML templates (runtime rendering) |

The Engine creates two Jinja2 environments:

1. **Scaffold environment**: standard delimiters (`{{ }}`), used for Python/YAML/TOML files
1. **Template environment**: Fastblocks delimiters (`[[ ]]`), used for `.html` files

Template file selection is based on output file extension: `.html` → template environment, all others → scaffold environment. Templates are rendered in **strict mode** — undefined variables raise an error rather than rendering empty strings.

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
1. Within clusters, identify shared files (same filenames, similar imports)
1. Extract common adapter registrations, middleware stacks, template structures
1. Draft a pattern YAML with confidence score based on prevalence across repos
1. Present to human for approval — never auto-saves

**Conversation capture (builds on session-buddy):**
After successfully building an app via chat, Mahavishnu offers:

- "This app used 4 patterns: project, nav, auth, cloudrun. Save as a composite pattern?"
- The composite pattern captures the exact file structure and configuration from the session

### 7.2 AI Suggestion Algorithm

The AI suggestion operates at two levels: **structural** (filesystem-based, always available) and **content** (requires code graph from spec 3 or LLM assist).

```python
def suggest_patterns(repo_paths: list[str], min_prevalence: float = 0.7) -> list[PatternDraft]:
    """Analyze repos and suggest patterns."""
    # 1. Collect directory structures from all repos (filesystem-level, no code graph needed)
    dir_structures = {repo: get_sorted_path_list(repo) for repo in repo_paths}

    # 2. Find shared directory patterns
    # Uses difflib.SequenceMatcher on sorted path lists to compute directory-tree edit distance
    shared_dirs = find_common_subtrees(dir_structures, min_prevalence=min_prevalence)

    # 3. For each shared directory, find shared files
    for dir_path, prevalence in shared_dirs.items():
        shared_files = find_common_files(dir_structures, dir_path, min_prevalence=min_prevalence)

    # 4. Cluster into pattern categories using hierarchical agglomerative clustering
    # Distance metric: normalized path-list edit distance (difflib.SequenceMatcher ratio)
    # Stopping criterion: clusters merge until inter-cluster distance > 0.3
    # Labeling: most common directory path in the cluster becomes the pattern category
    patterns = cluster_into_patterns(shared_dirs, shared_files)

    # 5. For each pattern, extract file content templates
    # SCOPE: structural similarity only (shared filenames, directory layout).
    # Content-level template extraction (diffing file contents to find variable regions)
    # is deferred to LLM-assisted refinement in the editor step, or manual curation.
    # Rationale: synthesizing Jinja2 templates from N similar files requires understanding
    # which differences are project-specific variables vs. genuine code differences.
    # This is an LLM task, not a diff task.
    for pattern in patterns:
        pattern.structure = build_structure_from_clusters(pattern.clusters)

    # 6. Score by confidence (prevalence across repos + structural consistency)
    for pattern in patterns:
        pattern.confidence = calculate_confidence(
            prevalence=pattern.repo_count / len(repo_paths),
            consistency=measure_structural_consistency(pattern)
        )

    return [p for p in patterns if p.confidence >= threshold]
```

**Note on code graph usage:** When the code graph from spec 3 is available, the algorithm additionally queries it for shared adapter registrations, middleware stacks, and import patterns. These enrich the structural analysis with symbol-level evidence. When the code graph is unavailable, the algorithm degrades to filesystem-only analysis (directory layout + file names).

**Important:** The suggestion algorithm produces drafts, not patterns. All drafts require human review before entering the Pattern Library.

### 7.2.1 Manual Curation Details

The `--from-project` flag resolves the named repo from `settings/repos.yaml`, then:

1. Reads the repo's directory tree and file listing
1. Pre-populates `structure.dirs` and `structure.files` with the repo's layout
1. Copies file contents into `templates` (raw, not parameterized)
1. Sets `source_repos` to `[<repo_name>]`
1. Opens the draft in the user's `$EDITOR` for refinement (remove irrelevant files, parameterize values, declare slots)

The developer then edits the draft down to just the pattern-specific parts and saves.

### 7.3 Pattern Validation

When a pattern is saved (manually or after review), it's validated:

```python
def validate_pattern(pattern: Pattern, library: PatternLibrary) -> list[ValidationIssue]:
    issues = []

    # Schema validation (Pydantic model)
    issues.extend(validate_yaml_schema(pattern))

    # ID matches file path (e.g., adapters/auth must be in patterns/adapters/)
    expected_prefix = pattern.file_path.parent.name  # directory name
    if not pattern.id.startswith(expected_prefix + "/"):
        issues.append(f"Pattern ID '{pattern.id}' doesn't match directory '{expected_prefix}/'")

    # Structural integrity
    for f in pattern.structure.files:
        if f.required and not has_template(pattern, f):
            issues.append(f"Required file '{f.path}' has no template")

    # Path traversal prevention
    # NOTE: PathValidator and dependency graph utilities are new modules
    # to be created as part of this spec's implementation.
    for d in pattern.structure.dirs:
        if not is_safe_path(d.path):
            issues.append(f"Directory path '{d.path}' contains path traversal")
    for f in pattern.structure.files:
        if not is_safe_path(f.path):
            issues.append(f"File path '{f.path}' contains path traversal")

    # Slot compatibility — check against ALL pattern dirs, not just dirs[0]
    all_dir_paths = {d.path for d in pattern.structure.dirs}
    for slot_name, slot in pattern.slots.items():
        # Find a parent dir that contains this slot path
        parent = find_parent_dir(slot.path, all_dir_paths)
        if parent is None:
            issues.append(f"Slot '{slot_name}' path '{slot.path}' is outside all pattern dirs")

    # Template syntax validation (parse with Jinja2 to catch syntax errors)
    for name, template_str in pattern.templates.items():
        try:
            jinja_env.parse(template_str)
        except TemplateSyntaxError as e:
            issues.append(f"Template '{name}' has Jinja2 syntax error: {e}")

    # Cross-pattern consistency
    if pattern.depends:
        for dep in pattern.depends:
            dep_id = dep.id if isinstance(dep, dict) else dep
            if not library.has(dep_id):
                issues.append(f"Dependency '{dep_id}' not found in library")

    # Circular dependency detection (DFS-based)
    # NOTE: detect_dependency_cycles is a new utility to be created
    # in the scaffolding module (not reusing an existing module).
    cycles = detect_dependency_cycles(pattern.id, library)
    if cycles:
        issues.append(f"Circular dependency detected: {' -> '.join(cycles)}")

    # ID uniqueness across library
    if library.has(pattern.id) and library.get(pattern.id).file_path != pattern.file_path:
        issues.append(f"Duplicate pattern ID '{pattern.id}'")

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
1. Build dependency graph from `depends` fields
1. Validate: all dependencies satisfied, no file-level conflicts, no circular dependencies
1. Topological sort patterns (dependencies first). **Secondary sort:** alphabetical by pattern ID for deterministic ordering among same-level patterns.
1. Scaffold to a **temporary directory** (e.g., `/tmp/mahavishnu-scaffold-{uuid}/`):
   a. For each pattern (in sorted order):
   - Create required directories
   - Render required files from templates (with variables filled in)
   - Apply file-merge slot injections (replace `{{slot:<name>}}` markers with claiming pattern content)
   - Register slot claims (so dependent patterns know where to write)
1. Write `.mahavishnu/manifest.json` with pattern set, versions, and content hashes
1. Write `.mahavishnu/patterns.lock` with exact pattern IDs and versions used
1. Initialize git repo and create initial commit
1. **Atomically rename** temp directory to final output path (on success only)
1. Run `uv init` or equivalent to install dependencies
1. Verify: `mahavishnu scaffold validate --project /Users/les/Projects/my-app`

**Rollback:** If any step fails (template rendering error, missing dependency, write failure), the temp directory is deleted and the user receives a clear error. The final output path is never touched unless all steps succeed.

**Output:** A working Fastblocks project with proper structure, config, and basic components. Ready to `python main.py`.

### 8.1.1 Project Manifest

Phase 1 writes `.mahavishnu/manifest.json` to every generated project:

```json
{
  "schema_version": 1,
  "project_name": "my-app",
  "patterns": [
    {"id": "scaffolding/project", "version": "1.0.0", "file_hash": "sha256:abc123..."},
    {"id": "components/nav", "version": "1.0.0", "file_hash": "sha256:def456..."}
  ],
  "generated_at": "2026-04-26T12:00:00Z",
  "variables": {"project_name": "my-app", "project_slug": "my_app"}
}
```

This manifest bridges Phase 1 and Phase 2: when the user continues in a Mahavishnu session, the Engine reads the manifest to know which project and patterns are active. Phase 2 reads the manifest to determine the target project directory and active pattern set.

### 8.2 Phase 2: Chat-Driven Refinement

After Phase 1, the user continues in a Mahavishnu session. The Engine reads `.mahavishnu/manifest.json` from the project directory to determine the active pattern set and project location. The user can also explicitly specify the project: `mahavishnu scaffold --project /path/to/my-app`.

```
User: "Add a dashboard page with a stats summary card"
→ Mahavishnu generates templates/pages/dashboard.html (AI generation)
→ Adds dashboard route to main.py (AI generation)
→ Validates output against composed pattern spec

User: "Use the auth pattern with Google OAuth"
→ Mahavishnu loads adapters/auth.yaml pattern
→ Re-runs Phase 1 pipeline on the expanded pattern set (original + auth)
→ Generates adapters/auth.py, settings/auth.yml
→ Updates main.py with session middleware (via middleware file-merge slot)
→ Updates manifest.json with the new pattern
→ Creates a git commit for the change

User: "Deploy to Cloud Run"
→ Mahavishnu loads deployment/cloudrun.yaml pattern
→ Re-runs Phase 1 pipeline on the expanded pattern set
→ Generates Dockerfile, cloudbuild.yaml
→ Adds deploy command to pyproject.toml
→ Updates manifest.json and commits
```

Each Phase 2 step is either:

- **Pattern composition** (loading a new pattern and running an incremental merge against the existing project — see below)
- **AI generation** (Claude generates custom content for pages, business logic, etc. — written to new files that don't conflict with pattern-managed files)

**Incremental merge for pattern composition:** When adding a pattern to an existing project (detected by the presence of `.mahavishnu/manifest.json`), the Engine does NOT re-run the full Phase 1 pipeline (which would conflict with the existing directory). Instead:

1. Scaffolds the new pattern to a temp directory
1. Merges temp contents into the existing project directory using the conflict detection logic from Section 8.4 (hash comparison, keep/overwrite/merge prompts)
1. Updates `.mahavishnu/manifest.json` with the new pattern
1. Creates a git commit for the change

**Phase 2 staging:** AI-generated content is written to files first, then shown to the user for approval before committing. Pattern composition steps are deterministic and commit automatically after validation passes.

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

Re-running scaffolding with the same patterns and variables produces the same output. This is verified via the `.mahavishnu/patterns.lock` file and per-file content hashes in the manifest.

**Idempotency mechanism:**

1. `.mahavishnu/patterns.lock` records exact pattern IDs and versions used
1. `.mahavishnu/manifest.json` records SHA-256 hashes of every generated file
1. Re-scaffolding with the same lock file produces identical file contents (verified by hash comparison)
1. If a pattern version changed since the lock file was created, the Engine warns and offers to update

**Conflict detection for manual edits:**
When re-scaffolding, the Engine compares each file's current hash against the manifest hash. If a file was manually edited:

- Pattern-managed files (generated from templates): Engine shows diff between current content and expected template output, offers keep/overwrite/merge
- User-added files (not in manifest): left untouched

**Pattern-managed file markers:** Generated files include a lightweight comment header:

```python
# Managed by mahavishnu scaffold — pattern: scaffolding/project v1.0.0
# Manual edits detected on re-scaffold. Edit the pattern template to make permanent changes.
```

**Atomic writes:** Pattern YAML files in the library use atomic write (write to temp file, then rename) to prevent concurrent write corruption.

## 9. CLI Interface

### 9.1 Pattern Management Commands

```bash
# Create a pattern manually
mahavishnu patterns create --name "auth" --from-project splashstand --category adapters

# Suggest patterns from existing repos (AI-assisted)
mahavishnu patterns suggest --repos fastblocks,splashstand --confidence-threshold 0.7

# List all patterns
mahavishnu patterns list [--category scaffolding|components|adapters|deployment|composite]

# Show pattern details (full ID required to avoid ambiguity)
mahavishnu patterns show adapters/auth

# Validate pattern library integrity
mahavishnu patterns validate

# Search patterns
mahavishnu patterns search --query "authentication" --source-repos splashstand

# Edit a pattern (opens in $EDITOR)
mahavishnu patterns edit adapters/auth
```

### 9.2 Scaffolding Commands

```bash
# Scaffold a new project (Phase 1 — deterministic)
mahavishnu scaffold "my-app" \
  --patterns scaffolding/project,components/nav \
  --title "My Application" \
  --output /path/to/my-app

# Add a pattern to an existing project (Phase 1 re-scaffolding)
# Re-runs the full Phase 1 pipeline with the expanded pattern set
mahavishnu scaffold add --project /path/to/my-app --pattern components/form

# Validate a generated project against its manifest
mahavishnu scaffold validate --project /path/to/my-app

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
| **3a** | Pattern Extractor (manual curation only) | Item 1 | Small |
| **3b** | Pattern Extractor (AI suggestion) | Code indexing spec + auth gate | Medium |
| **4th** | Scaffolding engine Phase 2 (chat refinement) | Items 1-3a | Medium |
| **5th** | Conversation capture (save session as composite pattern) | Items 1-4 | Small |
| **6th** | Pattern validation and contract enforcement | Items 1-5 | Small |

**Note:** Delivery 3b (AI suggestion) has a transitive dependency on the auth gate from the Code Indexing spec. If auth is delayed, AI suggestion is delayed. Delivery 3a (manual curation) has no such dependency and can proceed independently.

## 12. Acceptance Criteria

1. `mahavishnu patterns create --name auth --from-project splashstand` generates a draft pattern YAML in `patterns/adapters/auth.yaml`
1. `mahavishnu patterns suggest --repos fastblocks,splashstand` produces at least 3 suggested patterns with confidence scores
1. Suggested patterns are never auto-saved to the library without human approval
1. `mahavishnu patterns list` shows all patterns grouped by category with version and source repos
1. `mahavishnu scaffold "test-app" --patterns scaffolding/project` generates a working Fastblocks project that runs with `python main.py`
1. Generated project has the correct directory structure matching the pattern's `structure.dirs` specification
1. Generated files contain the pattern management header comment
1. `mahavishnu scaffold add --project /path/to/test-app --pattern components/nav` adds the nav component without breaking existing files
1. `mahavishnu scaffold "test-app" --validate` reports zero contract violations
1. Re-scaffolding with the same patterns produces the same output (deterministic)
1. Phase 2 chat refinement ("add a dashboard page") generates `templates/pages/dashboard.html` and updates `main.py`
1. Adding a pattern via chat triggers validation and reports any contract violations
1. All 15 initial patterns in Section 10 exist in the library
1. `mahavishnu patterns validate` passes with zero errors on the default pattern catalog
1. No generated project contains secrets, API keys, or credentials — all config values are placeholders

## 13. ADR Reference

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Storage format | YAML files in project directory | Human-editable, git-versioned, no database needed. |
| Pattern composition | Dependency graph with topological sort + alphabetical secondary key | Clean ordering, no circular dependencies, deterministic output. |
| Slot mechanism | File-level claims + marker-injection for file merges | Multiple patterns can share a directory; file-level conflicts detected precisely. |
| Template engine | Jinja2 with two delimiter environments | Scaffold templates use `{{ }}`, generated HTML uses `[[ ]]` (Fastblocks). |
| Phase separation | Deterministic (Phase 1) then AI-assisted (Phase 2) | Phase 1 is repeatable and testable. Phase 2 adds flexibility. |
| File management | Manifest + lockfile + hash verification | `.mahavishnu/manifest.json` and `.mahavishnu/patterns.lock` enable idempotency and conflict detection. |
| Rollback | Temp-dir-then-rename | Partial failures never corrupt the output directory. |
| AI suggestion | Structural similarity only, content via LLM/manual | Template synthesis from diffs is unreliable; structural analysis is sufficient for drafts. |
| Clustering algorithm | Hierarchical agglomerative with path-list edit distance | Feasible with stdlib (difflib), appropriate for small repo counts. |
| Pattern provenance | `source_repos` field in pattern metadata | Enables "show patterns from Splashstand" queries. |
| Version format | Semantic versioning as string (`"1.0.0"`) | Avoids float parsing issues; supports pre-release tags. |
| Confidence | 1.0 for manual, computed for AI-suggested | Manual curation is authoritative; AI needs scoring. |

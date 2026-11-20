# FastBlocks Builder Product Architecture

**Date**: 2026-05-02
**Status**: Proposal
**Scope**: How to build a Lovable-style product on top of FastBlocks and Mahavishnu

## Summary

If you want a Lovable-style product using FastBlocks instead of React, the cleanest split is:

- **Mahavishnu**: control plane, orchestration, agent routing, workflow execution, observability
- **FastBlocks**: builder/runtime substrate, component system, rendering primitives, framework-native constraints
- **New product repo**: end-user product surface, chat/app-builder UX, project/session model, publish flow

Do **not** put the entire product layer into Mahavishnu. Mahavishnu is strongest as infrastructure behind the product, not as the product itself.

Do **not** put the entire product layer into FastBlocks either. FastBlocks should stay opinionated about how FastBlocks apps are structured and rendered, but it should not become the whole commercial app-builder control plane and SaaS shell.

## Recommended Repo Split

### Mahavishnu

Mahavishnu should own:

- prompt execution orchestration
- agent/team routing
- multi-step workflow coordination
- repo coordination and messaging
- background jobs and long-running tasks
- trace collection, metrics, and operational visibility
- policy hooks and approval checkpoints

Mahavishnu should **not** become the canonical home for:

- end-user builder UX
- browser-side preview state
- app templates as framework primitives
- customer/project billing/account constructs

### FastBlocks

FastBlocks should own:

- component primitives
- layout and application scaffolding conventions
- template packs and starter structures
- framework-native validation rules
- rendering/runtime behavior
- builder-facing APIs needed to preview or compile FastBlocks apps

FastBlocks should be the source of truth for what “good FastBlocks output” means.

### New Product Repo

Create a separate product repo for the Lovable-style builder itself.

That repo should own:

- chat-to-app user experience
- prompt/session/project data model
- project editing lifecycle
- live preview orchestration in the browser
- deployment/publish UX
- account/workspace concepts
- product analytics and user-facing operations

This repo can call Mahavishnu for orchestration and call FastBlocks for generation/rendering primitives.

## Where Each Missing Layer Should Live

### 1. Prompt-to-spec translator

**Primary home**: new product repo

Reason:

- This is product-specific behavior, not generic orchestration
- It will evolve with UX, pricing, target users, and supported app categories
- It should produce a product-level app spec, not a generic workflow request

Mahavishnu's role:

- run the translator workflow
- delegate subtasks to workers or agents
- track execution, retries, and metrics

FastBlocks' role:

- provide target schema expectations and generation constraints

Recommended shape:

- Product repo defines `AppSpec`
- Mahavishnu executes `prompt -> clarified intent -> AppSpec draft -> validation -> plan`
- FastBlocks consumes validated `AppSpec`

### 2. Design/template system

**Primary home**: FastBlocks

Reason:

- Templates and component idioms are framework-native concerns
- Guarding style, composition, layout, and app structure belongs close to the renderer/builder
- If templates live outside FastBlocks, drift is likely

Product repo role:

- choose which template family to use
- expose template selection to the user
- store project-level design decisions

Mahavishnu role:

- orchestrate template selection/refinement workflows if AI is involved

Recommended shape:

- FastBlocks owns starter kits, component grammar, page patterns, and theme packs
- Product repo chooses and configures them

### 3. Live preview/session state

**Split ownership**

**Primary product/session ownership**: new product repo

**Preview runtime ownership**: FastBlocks

Reason:

- User sessions, draft history, builder state, and collaboration concepts are product concerns
- Rendering, hydration/update hooks, and preview runtime behavior are framework concerns

Mahavishnu role:

- manage background build/refresh jobs
- emit events for long-running generation or rebuilds
- coordinate with WebSocket/event infrastructure if needed

Recommended shape:

- Product repo owns `Project`, `Draft`, `PreviewSession`, `ConversationSession`
- FastBlocks exposes previewable build artifacts or a preview server/runtime API
- Mahavishnu triggers rebuild/regenerate/update workflows

### 4. Deployment/publish flow

**Primary home**: new product repo

Reason:

- Deployment UX is a product concern
- End users need project/environment/publish semantics, not raw orchestration primitives
- This layer usually expands into auth, secrets, domains, deploy targets, and rollback UX

Mahavishnu role:

- execute deployment workflows
- coordinate approvals, checks, and retries
- integrate with external deploy targets

FastBlocks role:

- produce deployable artifacts consistent with FastBlocks conventions

Recommended shape:

- Product repo owns `Publish`, `Environment`, `DeploymentTarget`
- Mahavishnu runs the publish pipeline
- FastBlocks produces the build output that pipeline deploys

### 5. Guardrails for FastBlocks idioms

**Primary home**: FastBlocks

Reason:

- The framework should define what valid, idiomatic output is
- Validation should not depend on product-specific prompt logic
- This is the strongest way to avoid “generated but not really maintainable” output

Secondary enforcement:

- product repo can reject invalid plans before generation
- Mahavishnu can run validation gates in the workflow

Recommended shape:

- FastBlocks owns validators, linters, schema rules, scaffolding constraints, and repair hints
- Product repo surfaces errors and repair options to the user
- Mahavishnu orchestrates `generate -> validate -> repair -> preview`

## Recommended Topology

### Option A: Best default

1. **New product repo** for the user-facing builder
2. **FastBlocks** as the framework substrate
3. **Mahavishnu** as orchestration backend

This is the recommended structure.

Benefits:

- preserves Mahavishnu's control-plane identity
- preserves FastBlocks' framework identity
- gives the product room to evolve independently
- avoids turning either infrastructure repo into a product-shaped monolith

### Option B: Start inside FastBlocks, then split

This is acceptable only if you want to prototype quickly and keep the first version tightly coupled to FastBlocks.

Use this only if:

- the product is definitely FastBlocks-only
- the first goal is proving UX, not platform cleanliness
- you accept future extraction work

Risk:

- FastBlocks can become overloaded with product concepts that do not belong in the framework

### Option C: Put it in Mahavishnu

Not recommended except for internal prototypes.

Why not:

- Mahavishnu will become product/UI-heavy
- builder-specific concerns will muddy orchestration concerns
- the repo will drift away from its strongest commercial niche

## Practical Recommendation

Build a **new product repo** for the end-user builder and keep the split disciplined:

- **Mahavishnu** = orchestrate
- **FastBlocks** = generate/render/validate FastBlocks-native apps
- **New repo** = sellable product experience

If you need to move fast, prototype the product layer in FastBlocks first, but treat that as a temporary incubation path and keep interfaces clean enough to extract later.

## Suggested Initial Boundaries

### New product repo modules

- `builder/chat/` - prompt intake, clarification, conversation handling
- `builder/specs/` - `AppSpec`, page model, app intent model
- `builder/projects/` - project/session/draft persistence
- `builder/preview/` - preview session API and state
- `builder/publish/` - deployment and publish UX
- `builder/integrations/mahavishnu/` - orchestration client
- `builder/integrations/fastblocks/` - framework generation client

### FastBlocks additions

- canonical `AppSpec` consumer or translator hooks
- template registry
- idiom validator
- repair hints for invalid generated structures
- preview runtime API

### Mahavishnu additions

- builder-oriented orchestration workflows
- generation pipeline templates
- validation and repair workflow stages
- deployment workflow templates
- richer progress/event streaming for builder tasks

## Final Answer

For the five missing product-layer items:

- **prompt-to-spec translator**: new product repo
- **design/template system**: FastBlocks
- **live preview/session state**: split, with product repo owning session state and FastBlocks owning preview runtime
- **deployment/publish flow**: new product repo, orchestrated by Mahavishnu
- **guardrails for FastBlocks idioms**: FastBlocks, with workflow enforcement from Mahavishnu

If the goal is a real external product, use a **new repo**. If the goal is a short internal prototype, incubating in FastBlocks is tolerable, but Mahavishnu should remain the backend control plane rather than the UI product shell.

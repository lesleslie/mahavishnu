______________________________________________________________________

title: Docker Optimize
owner: Delivery Operations
last_reviewed: 2025-02-06
supported_platforms:

- macOS
- Linux
  required_scripts: []
  risk: medium
  status: active
  id: 01K6EEXBS8Z18FQ39WT67VDXN4
  category: deployment

______________________________________________________________________

## Docker Optimize

Use this tool to reduce image size, improve build speed, and tighten runtime security.

## Focus areas

- Prefer small base images: `alpine`, `slim`, or `distroless`
- Use multi-stage builds for build-time dependencies
- Combine related `RUN` commands where it helps caching
- Remove package manager caches and temporary build artifacts
- Run as a non-root user when possible
- Pin versions for reproducible builds

## Workflow

1. Identify the app type and runtime needs.
1. Review the Dockerfile for base image, layers, and cleanup.
1. Suggest the smallest change that improves size or security.
1. Validate with build time, final image size, and startup behavior.

## Output

- A prioritized list of fixes
- A revised Dockerfile snippet when useful
- A short note on tradeoffs, especially compatibility vs. image size

## Requirements

$ARGUMENTS

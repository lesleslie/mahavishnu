______________________________________________________________________

title: Config Validate
owner: Operations Enablement Guild
last_reviewed: 2025-02-06
supported_platforms:

- macOS
- Linux
  required_scripts: []
  risk: medium
  status: active
  id: 01K6EEXD1MZSEWY34FPMG3ZKHA
  category: workflow

______________________________________________________________________

## Configuration Validation

Use this tool to check configuration files, schemas, and environment consistency.

## Focus areas

- Schema validation and type safety
- Secret detection and safe defaults
- Environment drift detection
- Required-key coverage across configs
- Test coverage for config loading paths

## Workflow

1. Discover config files and environment variants.
1. Flag obvious secret exposure and invalid patterns.
1. Compare required keys across environments.
1. Add schema validation where it prevents real failures.
1. Keep the validator stack simple and deterministic.

## Output

- Validation findings
- Missing or inconsistent keys
- Suggested schema or test improvements

## Requirements

$ARGUMENTS

# Initiative 2: Config Unification + Validation CLI

## Metadata
- Status: `not_started`
- Owner Role: `Core Eng`
- Target Window: `2026-04-13` to `2026-04-24`

## Outcome
Introduce deterministic preflight validation to prevent configuration-related runtime failures.

## Work Package Checklist
- [ ] `I2-1` Scaffold `config_validator.py` command
- [ ] `I2-2` Add repo/adapters/pool checks
- [ ] `I2-3` Add MCP connectivity and full mode checks
- [ ] `I2-4` Add CI config matrix job

## Dependencies
- `I1-1`

## Exit Criteria
- `mahavishnu validate --full` blocks bad configs
- CI matrix enforces validation across environments

## Risks
- False positives in strict validation
- Drift between config schema and runtime expectations

## Progress Log
- 2026-04-04: Plan file created.

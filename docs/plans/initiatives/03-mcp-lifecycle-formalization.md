# Initiative 3: MCP Lifecycle Formalization

## Metadata
- Status: `not_started`
- Owner Role: `Core Eng`
- Target Window: `2026-04-13` to `2026-04-24`

## Outcome
Make adapter lifecycle behavior explicit, testable, and uniform.

## Work Package Checklist
- [ ] `I3-1` Add abstract lifecycle contract
- [ ] `I3-2` Add `AdapterMetadata` model
- [ ] `I3-3` Update Prefect/Agno/LlamaIndex implementations
- [ ] `I3-4` Lifecycle conformance tests

## Dependencies
- `I1-1`

## Exit Criteria
- All adapters implement lifecycle contract
- CI blocks non-conforming adapters

## Risks
- Breaking existing adapters during migration
- Incomplete lifecycle semantics in edge cases

## Progress Log
- 2026-04-04: Plan file created.

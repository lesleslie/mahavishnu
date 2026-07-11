# Feature: <feature-slug>

**Owner:** <name or role>
**Created:** YYYY-MM-DD
**Last updated:** YYYY-MM-DD
**Repo(s):** <list of repo paths>

## State — pick one

- [ ] **built** (code merged, no callers wired)
- [ ] **wired** (entry-point exists; integration contract executed end-to-end)
- [ ] **adopted** (in active use by ≥1 user/workflow/agent)

## Wiring checklist

- [ ] Entry point registered (CLI command / MCP tool / FastAPI route / handler)
- [ ] Trigger path identified (who calls this, and from where)
- [ ] Returns / state updates land in expected destination
- [ ] End-to-end smoke check documented (one command that proves it works)
- [ ] Observability hook in place (log/metric/trace)
- [ ] Rollback signal defined

## Built (yes/no)

\<yes | no — "yes" iff the code is merged even if no callers exist yet>

## Wired (yes/no)

\<yes | no — "yes" iff an entry point is registered AND the integration
contract has been executed end-to-end at least once>

## Trigger path

\<who calls this feature, and from where? include the exact entry-point
symbol or path, e.g. `mahavishnu.cli.foo.run_command` or the
@mcp.tool-registered function name>

## Integration point

\<which app, CLI subcommand, MCP tool, workflow, or pool handler
consumes the new code? include the destination path that is mutated,
e.g. `mahavishnu/state/foo.db` or an HTTP route>

## End-to-end check

\<one concrete CLI command, HTTP request, or test name that exercises
trigger → integration → observable result. if you cannot name it,
the wiring does not exist>

## Blocker

\<if state != "adopted": one paragraph — what is preventing the next
transition?>

## Next action

\<single concrete step, with owner and date>

## Related

- Plan: \<path to docs/plans/...>
- Integration contract: \<link to the deliverable 1 template instance>
- Audit evidence: \<output path of scripts/audit_orphans.py>

## How to save to Session-Buddy

After completing this file, persist a one-line summary to Session-Buddy
for cross-session retrieval by calling the Session-Buddy MCP tool
`store_reflection` with the following shape (replace the `<…>` values
from the fields above):

```python
mcp__session-buddy__store_reflection(
    content=(
        "Feature <feature-slug>: state=<built|wired|adopted>, "
        "built=<yes|no>, wired=<yes|no>, "
        "blocker=<one-sentence summary of the Blocker field, or 'none'>, "
        "next=<one-sentence summary of the Next action field>"
    ),
    tags=["feature-tracking", "<feature-slug>", "wire-up-state"],
)
```

That call returns a reflection ID; paste that ID into the section below
so the long-form record and the searchable reflection stay linked.

## Session-Buddy

- Reflection ID: \<returned by store_reflection, e.g. "r_abc123…">
- Saved at: \<ISO timestamp from the call's response>

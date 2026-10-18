---
description: Show jot inbox vitals (open/done counts)
allowed-tools: []
---

Run `mahavishnu jot vitals` and display the output verbatim.
---
description: Show drain candidates with suggested actions (/jot drain slash command; open jots ranked for dispatch/defer/done/delete/skip)
allowed-tools: []
---

Run `mahavishnu jot drain {{query}} --limit {{limit | default:5}} --include-in-flight {{include_in_flight | default:false}}` and display the output verbatim.

Defaults: limit=5, include-in-flight=false. Pass `--query` to scope by surface text.
---
description: Create a new jot from text (/jot add slash command; quick-capture scratchpad)
allowed-tools: []
---

Run `mahavishnu jot add {{text}}` and display the output verbatim.
---
description: List jots newest first (/jot list slash command; status filter open|done, optional limit)
allowed-tools: []
---

Run `mahavishnu jot list --status {{status | default:open}} --limit {{limit | default:20}}` and display the output verbatim.

Defaults: status=open, limit=20. To see done jots, pass `--status done`.
---
description: Show one jot by handle (/jot show slash command; full id, short_id, or unambiguous substring)
allowed-tools: []
---

Run `mahavishnu jot show {{handle}}` and display the output verbatim.
---
description: Edit a jot's text (/jot edit slash command; mutates the jot identified by handle)
allowed-tools: []
---

Run `mahavishnu jot edit {{handle}} {{new_text}}` and display the output verbatim.
---
description: Mark a jot as done (/jot done slash command; mutates the jot identified by handle)
allowed-tools: []
---

Run `mahavishnu jot done {{handle}}` and display the output verbatim.
---
description: Reopen a done jot (/jot reopen slash command; mutates the jot identified by handle)
allowed-tools: []
---

Run `mahavishnu jot reopen {{handle}}` and display the output verbatim.
---
description: Lexical search across jots (/jot search slash command; substring match with optional limit)
allowed-tools: []
---

Run `mahavishnu jot search {{query}} --limit {{limit | default:20}}` and display the output verbatim.

Default limit=20.
---
description: Surface relevant jots for the given context (/jot resurface slash command; session_start | tool_result trigger)
allowed-tools: []
---

Run `mahavishnu jot resurface --trigger {{trigger | default:session_start}} --context-text "{{context_text | default:""}}"` and display the output verbatim.

Defaults: trigger=session_start, context-text="". Pass `--trigger tool_result --context-text "<text>"` to scope by tool-result context.

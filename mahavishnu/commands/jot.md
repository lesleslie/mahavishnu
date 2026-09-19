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

Defaults: limit=5, include_in_flight=false. Pass `--query` to scope by surface text.

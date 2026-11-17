---
title: Jot Vitals
owner: Operations Enablement Guild
last_reviewed: '2026-11-17'
status: active
id: 01a1e93007b1773b8b2a42aacc812b33
category: workflow
description: Show jot inbox vitals, and drive the jot lifecycle - drain, add, list, show, edit, done, reopen, search and resurface.
allowed-tools: []
---

Run `mahavishnu jot vitals` and display the output verbatim.

## `/jot drain`

Show drain candidates with suggested actions (open jots ranked for dispatch/defer/done/delete/skip).

Run `mahavishnu jot drain {{query}} --limit {{limit | default:5}} --include-in-flight {{include_in_flight | default:false}}` and display the output verbatim.

Defaults: limit=5, include-in-flight=false. Pass `--query` to scope by surface text.

## `/jot add`

Create a new jot from text (quick-capture scratchpad).

Run `mahavishnu jot add {{text}}` and display the output verbatim.

## `/jot list`

List jots newest first (status filter open|done, optional limit).

Run `mahavishnu jot list --status {{status | default:open}} --limit {{limit | default:20}}` and display the output verbatim.

Defaults: status=open, limit=20. To see done jots, pass `--status done`.

## `/jot show`

Show one jot by handle (full id, short_id, or unambiguous substring).

Run `mahavishnu jot show {{handle}}` and display the output verbatim.

## `/jot edit`

Edit a jot's text (mutates the jot identified by handle).

Run `mahavishnu jot edit {{handle}} {{new_text}}` and display the output verbatim.

## `/jot done`

Mark a jot as done (mutates the jot identified by handle).

Run `mahavishnu jot done {{handle}}` and display the output verbatim.

## `/jot reopen`

Reopen a done jot.

Run `mahavishnu jot reopen {{handle}}` and display the output verbatim.

## `/jot search`

Lexical search across jots (substring match with optional limit).

Run `mahavishnu jot search {{query}} --limit {{limit | default:20}}` and display the output verbatim.

Default limit=20.

## `/jot resurface`

Surface relevant jots for the given context (session_start | tool_result trigger).

Run `mahavishnu jot resurface --trigger {{trigger | default:session_start}} --context-text "{{context_text | default:""}}"` and display the output verbatim.

Defaults: trigger=session_start, context-text="". Pass `--trigger tool_result --context-text "<text>"` to scope by tool-result context.

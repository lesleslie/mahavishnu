______________________________________________________________________

bans:

- pattern: 'Co-Authored-By:\\s\*Claude'
  message: 'No AI attribution in commit messages'
- pattern: 'Generated with Claude Code'
  message: 'No AI tooling attribution'
- pattern: '[bot]\\s\*$'
  message: 'No bot suffix in commit messages'
- pattern: '^##\\s\*(What this MR does|Why we need it)\\s\*$'
  message: 'No fill-in-the-blank headings; use descriptive titles'
- pattern: '\*\*(Root cause|Fix|Risk|What changes):\*\*'
  message: 'No bold-tag structure in prose; integrate naturally'
- pattern: 'verified locally'
  message: 'Proof of work must be command-reproducible'
  required_disclosures:
- 'MR description: include Changes: bullet list'
- 'Commit message: include reproducible test command if applicable'

______________________________________________________________________

# Style SOP — Mahavishnu default

This SOP constrains how agents write MR descriptions, commit messages,
and other operator-facing artifacts. The goal: output that doesn't look
AI-generated and is grounded in actual project work.

## Voice

Write MR descriptions as continuous prose with a `Changes:` bullet list
at the end, the way an engineer would write it manually. No "What this
MR does / Why we need it" templates.

## Proof of work

When claiming verification, include the actual command and its relevant
output. Not "verified locally" — `pytest tests/test_foo.py::test_bar -v`
with the relevant 3 lines.

## What makes output smell AI

- Bold inline tags like `**Root cause:**`, `**Fix:**`, `**Risk:**` —
  the single most reliable AI-flavor tell.
- Fill-in-the-blank section headings.
- Generic prose without specific numbers or measurements.
- Co-Authored-By or [bot] suffixes in commit messages.

## What makes output look human

- Specific measurements ("reduces p99 from 340ms to 95ms over 1000 requests").
- Honest post-mortems ("I tried X first; it didn't work because Y").
- Names of specific files and functions.
- Concrete commands and their output.

## Editing this SOP

Operators edit this file at any time. The next MR picks up the new rules.
No daemon restart, no code change. To ban something new, add to the YAML
frontmatter's `bans` list with a regex pattern and a message.

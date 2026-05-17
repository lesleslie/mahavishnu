______________________________________________________________________

## name: infographic-creator description: Create infographic DSL output from text content.

# Infographic Creator

## Overview

Use this skill when the user wants an infographic expressed in AntV Infographic DSL.

## Core Rules

- Output only the infographic DSL, not Markdown or prose.
- Start with `infographic <template-name>`.
- Use `data` and `theme` blocks with two-space indentation.
- Pick one main data field that matches the template type.

## Common Fields

- `list-*` -> `lists`
- `sequence-*` -> `sequences`
- `compare-*` -> `compares`
- `hierarchy-*` -> `root` or `items`
- `relation-*` -> `nodes` and `relations`
- `chart-*` -> `values`

## Quick Notes

- Use icons when they help with scanning.
- Use `theme` for palette, font, and stylization.
- Keep the structure compact and avoid extra explanation.

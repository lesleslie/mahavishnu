______________________________________________________________________

## name: narrative-text-visualization description: Generate structured narrative text output using the T8 schema.

# Narrative Text Visualization

## Overview

Use this skill when the user wants a structured narrative report expressed as T8 schema.

## Core Rules

- Output only the JSON schema.
- Use the schema fields `headline`, `sections`, `paragraphs`, and `phrases`.
- Label important values as entities when they add meaning.
- Keep data factual and sourced.

## Common Entity Types

- `metric_name`
- `metric_value`
- `ratio_value`
- `trend_desc`
- `dim_value`
- `time_desc`

## Notes

- Use public, authentic sources only.
- Do not invent or guess data.

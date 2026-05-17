______________________________________________________________________

## name: resolve-components description: Use when debugging Oneiric component selection.

# Resolve Components

## Overview

Use this skill to explain why Oneiric selected one component over another.

## When to Use

- Debugging selection precedence
- Understanding shadowed candidates
- Explaining resolution decisions
- Troubleshooting conflicts

## Precedence

1. Explicit selection
1. Stack order
1. Priority
1. Registration order

## Quick Reference

- Explain: `resolver.explain(...)`
- List candidates: `resolver.candidates(...)`
- Select explicitly: `resolver.select(...)`
- Resolve current target: `resolver.resolve(...)`
- View conflicts: `resolver.conflicts(...)`

## Notes

- Resolution should be deterministic and explainable.
- Prefer explicit selection when the choice matters.

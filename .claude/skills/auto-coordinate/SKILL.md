______________________________________________________________________

## name: auto-coordinate description: Use when coordinating issues or todos that should persist with git state.

# Auto-Coordinate

## Overview

Use this skill when coordination state should be linked to git branches and preserved across sessions.

## When to Use

- Creating an issue
- Closing an issue
- Creating a todo
- Completing a todo

## Core Rule

- Coordination state without git linkage is ephemeral.

## Quick Reference

- Issue flow: check branch, suggest branch naming, then commit and push on close
- Todo flow: check blockers, then surface dependent work

## Notes

- Keep branch names tied to issue IDs.
- Remind the user to clean up branches after work is done.

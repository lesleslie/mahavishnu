______________________________________________________________________

## name: configure-oneiric description: Use when setting up Oneiric configuration or troubleshooting precedence.

# Configure Oneiric

## Overview

Use this skill to set up, validate, and troubleshoot Oneiric configuration.

## Configuration Layers

1. Defaults
1. Committed config
1. Local overrides
1. Environment variables

## When to Use

- Setting up Oneiric for the first time
- Validating configuration
- Troubleshooting precedence issues
- Creating local overrides

## Quick Reference

- Show config: `oneiric config show`
- Validate config: `oneiric config validate`
- Explain field: `oneiric config explain --field <field>`
- Generate template: `oneiric config init`
- View effective config: `oneiric config effective`

## Notes

- Higher layers override lower layers.
- Keep local overrides gitignored.

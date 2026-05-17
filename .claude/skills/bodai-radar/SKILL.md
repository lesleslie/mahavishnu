______________________________________________________________________

## name: bodai-radar description: Use when checking ecosystem health across Bodai components.

# Bodai Radar

## Overview

Use this skill for a quick health snapshot across Crackerjack, Mahavishnu, Akosha, Dhara, and Session-Buddy.

## When to Use

- Starting a work session
- Checking whether any component is degraded or down
- Getting a morning standup overview
- Verifying health after deployment or config changes

## Core Rule

- One command should summarize the ecosystem clearly.
- Each component contributes one primary signal.

## Quick Reference

- Crackerjack: quality metrics
- Mahavishnu: health status
- Akosha: anomaly detection
- Dhara: adapter health
- Session-Buddy: recent activity summary

## Notes

- Classify each signal as green, yellow, red, or grey.
- If a component is unhealthy, route to the relevant follow-up skill.

______________________________________________________________________

## name: quality-pulse description: Use when analyzing quality trends, anomalies, or degradation signals.

# Quality Pulse

## Overview

Use this skill to check whether quality is improving or degrading across repos or adapters.

## When to Use

- Checking quality trends
- Detecting anomalies
- Correlating metrics between systems
- Getting a quality health snapshot

## Core Rule

- Detect degradation before it becomes an incident.

## Quick Reference

- Trends: `mcp__akosha__analyze_trends`
- Anomalies: `mcp__akosha__detect_anomalies`
- Correlations: `mcp__akosha__correlate_systems`
- Status: `mcp__crackerjack__get_comprehensive_status`

## Notes

- Check metric availability first.
- Report confidence when data is sparse.

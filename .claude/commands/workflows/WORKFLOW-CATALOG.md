______________________________________________________________________

title: Workflow Catalog & Decision Tree
owner: Platform Engineering
last_reviewed: 2025-10-01
risk: low
status: active
id: 01K6EGMX8YTJN4P9ZVW0ERBQ2H

______________________________________________________________________

## Workflow Catalog

Use this catalog to pick the smallest workflow that matches the task.

## Quick Routing

- New feature or product work -> `feature/feature-delivery-lifecycle.md`
- Incident, outage, or system instability -> `maintenance/incident-response.md` or `maintenance/stability-lifecycle.md`
- Disaster recovery -> `maintenance/disaster-recovery.md`
- Legacy modernization -> `maintenance/legacy-modernize.md`
- Security hardening -> `maintenance/security-hardening.md`
- Container, ML, DB, or API release work -> deployment workflow in the same category
- Automation tasks -> `automation/automation-orchestration.md`
- Adoption or usage tracking -> `monitoring/adoption-analytics.md`

## Rule of Thumb

- Choose the workflow that matches the largest risk or coordination burden.
- Prefer a specific workflow over the catalog when one clearly fits.
- Use the catalog only to route, not to execute.

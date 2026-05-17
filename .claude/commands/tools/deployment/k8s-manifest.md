______________________________________________________________________

title: K8S Manifest
owner: Delivery Operations
last_reviewed: 2025-02-06
supported_platforms:

- macOS
- Linux
  required_scripts: []
  risk: medium
  status: active
  id: 01K6EEXBTQ0HH6Z3QYJMRYHN5J
  category: deployment

______________________________________________________________________

## Kubernetes Manifest Generation

Use this tool to produce production-ready Kubernetes resources with the smallest useful manifest set.

## Focus areas

- Correct workload type: Deployment, StatefulSet, Job, CronJob, DaemonSet
- Secure defaults: non-root, read-only root filesystem, minimal RBAC
- Resource requests and limits
- Health probes, config, secrets, and service exposure
- Observability annotations and rollout strategy
- Multi-environment customization via overlays or values

## Workflow

1. Identify app type, ports, dependencies, and storage needs.
1. Choose the smallest Kubernetes object set that fits the workload.
1. Add probes, resources, securityContext, and labels.
1. Include only the manifests needed for the target environment.
1. Validate against cluster conventions and deployability.

## Output

- Recommended manifest set
- Key security and scaling settings
- Optional Helm/Kustomize notes if the project already uses them

## Requirements

$ARGUMENTS

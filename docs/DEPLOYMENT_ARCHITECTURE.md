# Deployment Architecture

## Overview

This document outlines the production deployment architecture for the Mahavishnu platform.

## Platform Selection

### Container Orchestration

- **Kubernetes**: Primary orchestration platform for production deployments
- **Docker Compose**: For staging and development environments

### Infrastructure as Code

- **Terraform**: For cloud infrastructure provisioning
- **Helm Charts**: For Kubernetes application deployments

## Cluster Sizing

### OpenSearch Requirements

- **Development**: Single node, 4 CPU, 8GB RAM, 50GB disk
- **Staging**: 3 nodes, 8 CPU, 16GB RAM, 100GB disk each
- **Production**: 3+ nodes, 16 CPU, 32GB RAM, 500GB disk each

### Mahavishnu Service Requirements

- **Development**: 2 CPU, 4GB RAM
- **Staging**: 4 CPU, 8GB RAM
- **Production**: 8+ CPU, 16GB+ RAM (auto-scaling enabled)

## Networking

### VPC Configuration

- Private subnets for application pods
- Public subnets for load balancers
- NAT gateways for outbound traffic
- Security groups restricting inbound/outbound traffic

### Service Mesh

- Istio for service-to-service communication
- mTLS encryption for all internal traffic
- Traffic management and observability

## Security

### Network Security

- Private clusters with no public endpoints
- VPN access for administrative tasks
- Network policies restricting pod communication

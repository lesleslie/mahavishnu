# Repository Role Taxonomy

Mahavishnu uses a role-based taxonomy to organize repositories and enable intelligent workflow routing. Each repository is assigned a single role that defines its purpose within the ecosystem.

## Available Roles

| Role | Description | Example Repos |
|------|-------------|---|
| **orchestrator** | Coordinates workflows and manages cross-repository operations | mahavishnu |
| **resolver** | Platform foundation: component resolution, lifecycle management, adapters, domain bridges, remote delivery | oneiric |
| **manager** | Manages state, sessions, and knowledge across the ecosystem | session-buddy |
| **inspector** | Validates code quality and enforces development standards | crackerjack |
| **builder** | Builds applications and web interfaces | fastblocks |
| **soothsayer** | Reveals hidden patterns and insights across distributed systems | akosha |
| **app** | End-user applications with graphical interfaces | mdinject, splashstand |
| **asset** | UI libraries, component collections, and style guides | fastbulma |
| **foundation** | Foundational utilities, libraries, and shared code | mcp-common |
| **visualizer** | Creates visual diagrams and documentation | excalidraw-mcp, mermaid-mcp |
| **extension** | Extends framework capabilities with pluggable modules | jinja2-inflection |
| **tool** | Specialized tools and integrations via MCP protocol | mailgun-mcp, raindropio-mcp |

## Repository Metadata

Each repository in `settings/repos.yaml` includes:

```yaml
repos:
  - path: "/path/to/repo"
    name: "repository-name"
    package: "python-package-name"
    nickname: "short-name"  # optional
    role: "orchestrator"
    tags: ["backend", "python"]
    description: "Human-readable description"
    mcp: "native"  # or "3rd-party"
```

## Role-Based Queries

```bash
mahavishnu list-repos --role orchestrator    # Orchestrator repos
mahavishnu list-repos --role tool            # MCP tool integrations
mahavishnu list-repos --role asset           # UI libraries
mahavishnu show-role tool                    # Details about tool role
```

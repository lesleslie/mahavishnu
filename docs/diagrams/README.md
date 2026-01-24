# Mahavishnu Diagrams

This directory contains visual diagrams and architecture documentation for the Mahavishnu project.

## Available Diagrams

### Architecture Diagrams

| Diagram | Description | File |
|---------|-------------|------|
| System Architecture | Overall system architecture showing all components and their interactions | `system-architecture.png` |
| Configuration Loading | Oneiric's 4-layer configuration loading hierarchy | `configuration-loading.png` |
| Entity Relationships | Data model relationships and entities | `entity-relationships.png` |

### Workflow Diagrams

| Diagram | Description | File |
|---------|-------------|------|
| Workflow Execution Sequence | Complete sequence diagram of workflow execution | `workflow-execution.png` |
| Workflow Process | Detailed flowchart of workflow execution process | `workflow-process.png` |

### Security & Resilience Diagrams

| Diagram | Description | File |
|---------|-------------|------|
| Circuit Breaker States | State machine for circuit breaker pattern | `circuit-breaker-states.png` |
| Authentication Flow | JWT authentication and authorization flow | `authentication-flow.png` |

### Development Diagrams

| Diagram | Description | File |
|---------|-------------|------|
| Git Branching Strategy | Feature branch workflow for development | `git-branching-strategy.png` |

## Usage in Documentation

Include these diagrams in Markdown files:

```markdown
![System Architecture](docs/diagrams/system-architecture.png)

![Configuration Loading](docs/diagrams/configuration-loading.png)
```

## Generating New Diagrams

### Mermaid Diagrams

Mahavishnu uses the Mermaid MCP server to generate diagrams. To create new diagrams:

1. Edit Mermaid source code in documentation files
2. Use the MCP tool to generate:
   ```bash
   # Generate as PNG
   mcp__mermaid__generate_mermaid_diagram outputType="base64"

   # Generate as SVG
   mcp__mermaid__generate_mermaid_diagram outputType="svg_url"
   ```
3. Download and save to `docs/diagrams/`

### Excalidraw Diagrams

For more visual/hand-drawn style diagrams, use the Excalidraw MCP server:

```bash
# Create visual architecture diagrams
mcp__excalidraw__create_element
```

## Diagram Categories

### Technical Documentation
- Sequence diagrams for API flows
- Architecture diagrams for system overview
- Entity relationship diagrams for data models

### Presentations
- Use Excalidraw for stakeholder presentations
- Use Mermaid for technical documentation

### Planning
- Git branching strategies
- Feature workflows
- Deployment processes

## File Formats

- **PNG**: Raster images for documents and presentations
- **SVG**: Vector images for web and scaling
- **Excalidraw**: Editable format for visual modifications

## Maintenance

When updating diagrams:
1. Keep both PNG and SVG versions when possible
2. Update this README with new diagrams
3. Reference diagrams in relevant documentation files
4. Use descriptive filenames
5. Keep diagrams under 200KB when possible for web performance

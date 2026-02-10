# Auto-Diagram Quick Start

## 30-Second Setup

```bash
# Already installed with Mahavishnu
mahavishnu diagram generate ./myproject --output diagram.svg
```

That's it! You now have a professional architecture diagram.

## Common Tasks

### Generate Architecture Diagram

```bash
mahavishnu diagram generate ./myproject --type architecture --output arch.svg
```

### Generate Dependency Graph

```bash
mahavishnu diagram generate ./myproject --type dependency --output deps.svg
```

### Generate Database Schema

```bash
mahavishnu diagram generate ./myproject --type erd --output schema.svg
```

### Analyze Codebase

```bash
mahavishnu diagram analyze ./myproject
```

### Export Multiple Formats

```bash
# SVG (default)
mahavishnu diagram generate . -o diagram.svg

# Mermaid (for Markdown)
mahavishnu diagram generate . -o diagram.md --format mermaid

# Interactive HTML
mahavishnu diagram generate . -o diagram.html --format html

# Graphviz DOT
mahavishnu diagram generate . -o diagram.dot --format dot
```

### Change Layout Algorithm

```bash
# Hierarchical (default - good for architecture)
mahavishnu diagram generate . --layout hierarchical

# Force-directed (good for dependencies)
mahavishnu diagram generate . --layout force_directed

# Circular (good for cyclical relationships)
mahavishnu diagram generate . --layout circular

# Grid (good for regular structures)
mahavishnu diagram generate . --layout grid
```

### Include Tests

```bash
mahavishnu diagram generate . --include-tests
```

## Python API

```python
import asyncio
from mahavishnu.integrations.auto_diagram import DiagramGenerator

async def main():
    generator = DiagramGenerator()
    
    # Generate diagram
    diagram = await generator.generate_architecture_diagram(
        root_path=".",
        name="my_architecture",
    )
    
    # Export
    await generator.export_diagram(diagram, "architecture.svg")

asyncio.run(main())
```

## Output Examples

### Architecture Diagram
Shows high-level components: services, APIs, databases, and their relationships.

### Dependency Diagram
Shows module imports and dependencies between components.

### ERD Diagram
Shows database tables, columns, and relationships.

### Sequence Diagram
Shows request/response flow through the system.

## Tips

1. **First time?** Start with `--type architecture` for a high-level view
2. **Large project?** Use `--layout hierarchical` for cleaner diagrams
3. **Need details?** Use `--type dependency` for full dependency graph
4. **Documentation?** Use `--format mermaid` for Markdown files
5. **Interactive?** Use `--format html` for zoom/pan diagrams

## Next Steps

- Read [Full Guide](AUTO_DIAGRAM_GUIDE.md) for advanced features
- Check [API Reference](#) for complete API documentation
- See [Examples](#) for real-world usage

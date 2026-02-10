# Auto-Diagram Generation Guide

## Overview

The Auto-Diagram Generation integration automatically creates architecture diagrams from Python codebases. It analyzes code structure, detects relationships between components, and generates professional visualizations in multiple formats.

## Features

### 5 Diagram Types

1. **Architecture Diagrams**: High-level system architecture showing services, APIs, databases, and their relationships
2. **Dependency Graphs**: Module import dependencies and call graphs
3. **Sequence Diagrams**: Request/response flows through the system
4. **Entity Relationship Diagrams (ERD)**: Database schema and relationships
5. **Deployment Diagrams**: Infrastructure topology and deployment architecture

### 4 Layout Algorithms

1. **Force-Directed**: Physics-based simulation for organic, balanced layouts
2. **Hierarchical**: Layered layout for clear hierarchy (top-to-bottom)
3. **Circular**: Arrange nodes in a circle for cyclical relationships
4. **Grid**: Regular grid layout for organized structures
5. **Orthogonal**: Straight horizontal/vertical edges with grid snapping

### 5 Export Formats

1. **SVG**: Scalable vector graphics (perfect for documents)
2. **PNG**: Raster images (requires cairosvg)
3. **Mermaid.js**: Markdown-friendly format for documentation
4. **Graphviz DOT**: Standard graph format for further processing
5. **Interactive HTML**: D3.js-powered interactive diagrams with zoom/pan

## Installation

The auto-diagram integration is included with Mahavishnu. Optional dependencies:

```bash
# For PNG export
pip install cairosvg

# For FastAPI web service
pip install fastapi uvicorn
```

## Quick Start

### Command Line

```bash
# Generate architecture diagram
mahavishnu diagram generate ./myproject --type architecture --output arch.svg

# Generate dependency diagram
mahavishnu diagram generate ./myproject --type dependency --output deps.svg

# Generate with custom layout
mahavishnu diagram generate ./myproject --type architecture --layout circular

# Analyze codebase statistics
mahavishnu diagram analyze ./myproject

# Include test files
mahavishnu diagram generate ./myproject --include-tests
```

### Python API

```python
import asyncio
from mahavishnu.integrations.auto_diagram import (
    DiagramGenerator,
    DiagramConfig,
    DiagramType,
    ExportFormat,
    LayoutAlgorithm,
)

async def generate_diagrams():
    # Configure generator
    config = DiagramConfig(
        format=ExportFormat.SVG,
        layout_algorithm=LayoutAlgorithm.HIERARCHICAL,
        include_tests=False,
        min_confidence=0.7,
    )

    generator = DiagramGenerator(config=config)

    # Generate architecture diagram
    diagram = await generator.generate_architecture_diagram(
        root_path="/path/to/project",
        name="my_architecture",
    )

    # Export to SVG
    await generator.export_diagram(
        diagram,
        output_path="architecture.svg",
        format=ExportFormat.SVG,
    )

    # Generate multiple formats
    for format in [ExportFormat.SVG, ExportFormat.MERMAID, ExportFormat.HTML]:
        output = f"architecture.{format.value}"
        await generator.export_diagram(diagram, output, format)

    # Print statistics
    print(f"Components: {diagram.metadata.component_count}")
    print(f"Relationships: {diagram.metadata.relationship_count}")
    print(f"Confidence: {diagram.metadata.confidence:.2%}")
    print(f"Analysis time: {diagram.metadata.analysis_duration_ms:.1f}ms")

asyncio.run(generate_diagrams())
```

## Advanced Usage

### Incremental Analysis

The analyzer caches results for faster subsequent runs:

```python
from mahavishnu.integrations.auto_diagram import CodebaseAnalyzer, AnalysisState

# Create analyzer with state
state = AnalysisState()
analyzer = CodebaseAnalyzer(config=config, state=state)

# First run - full analysis
components1, relationships1 = await analyzer.analyze("/path/to/project")

# Second run - uses cache (only analyzes changed files)
components2, relationships2 = await analyzer.analyze("/path/to/project", incremental=True)
```

### Custom Configuration

```python
from mahavishnu.integrations.auto_diagram import DiagramConfig, DiagramStyle

# Custom styling
style = DiagramStyle(
    color_scheme="pastel",
    node_shape="ellipse",
    edge_style="dashed",
    font_size=14,
    show_labels=True,
    group_by_module=True,
)

# Full configuration
config = DiagramConfig(
    style=style,
    format=ExportFormat.SVG,
    layout_algorithm=LayoutAlgorithm.FORCE_DIRECTED,
    max_depth=5,  # Limit traversal depth
    include_tests=False,
    include_venv=False,
    min_confidence=0.6,
    exclude_patterns=[
        r"migrations",
        r"\.pyc",
        r"__pycache__",
    ],
)
```

### Sequence Diagrams

Trace execution flow from an entry point:

```python
generator = DiagramGenerator()

# Generate sequence diagram for a specific endpoint
diagram = await generator.generate_sequence_diagram(
    root_path="/path/to/project",
    entry_point="handle_request",  # Function name to trace
    name="request_flow",
)

await generator.export_diagram(diagram, "sequence.svg")
```

### ERD Diagrams

Generate database schema diagrams:

```python
# Detect SQLAlchemy models and relationships
diagram = await generator.generate_erd_diagram(
    root_path="/path/to/project",
    name="database_schema",
)

await generator.export_diagram(diagram, "schema.svg")
```

## FastAPI Web Service

Start the diagram generation web service:

```bash
# Start server
uvicorn mahavishnu.integrations.auto_diagram:diagram_app --reload --port 8080
```

### API Endpoints

```bash
# Generate diagram
curl -X POST http://localhost:8080/generate \
  -H "Content-Type: application/json" \
  -d '{
    "root_path": "/path/to/project",
    "diagram_type": "architecture",
    "name": "my_diagram",
    "format": "svg"
  }'

# Check status
curl http://localhost:8080/status/my_diagram

# Download diagram
curl http://localhost:8080/download/my_diagram -o diagram.svg

# Health check
curl http://localhost:8080/health
```

## Component Types Detected

The analyzer detects these component types:

- **Modules**: Python packages and modules
- **Classes**: Class definitions with inheritance
- **Functions**: Function and method definitions
- **Services**: Business logic services
- **API Endpoints**: FastAPI route handlers
- **Models**: Database models (SQLAlchemy, etc.)
- **Databases**: Database connections
- **Microservices**: Independent service units
- **Utilities**: Helper functions and utilities

## Relationship Types Detected

The analyzer detects these relationship types:

- **Imports**: Module import statements
- **Calls**: Function/method calls
- **Inherits**: Class inheritance
- **Implements**: Interface implementation
- **Depends On**: Dependency relationships
- **Associated With**: General associations
- **Composed Of**: Composition relationships
- **Flows To**: Data flow
- **Foreign Key**: Database foreign keys
- **Deployed On**: Deployment relationships

## Confidence Scoring

Each detected relationship has a confidence score (0.0-1.0):

- **1.0 (High)**: Direct imports, explicit inheritance
- **0.8-0.9**: Function calls, API endpoints
- **0.6-0.7**: Inferred relationships
- **< 0.5**: Uncertain relationships

Filter by confidence:

```python
config = DiagramConfig(min_confidence=0.7)  # Only high-confidence relationships
```

## Performance

### Optimization Tips

1. **Use Incremental Analysis**: Cache results for faster runs
2. **Limit Scope**: Exclude tests, venv, migrations
3. **Set Max Depth**: Limit traversal depth for large codebases
4. **Choose Appropriate Layout**: Hierarchical is fastest for large graphs

### Benchmarks

On a typical codebase (100 files, 5000 LOC):

- **Analysis**: ~2-3 seconds first run, ~0.5s incremental
- **Layout (Hierarchical)**: ~0.2s
- **Layout (Force-directed)**: ~1-2s (100 iterations)
- **Export (SVG)**: ~0.1s
- **Export (HTML)**: ~0.2s

## Examples

### Microservice Architecture

```python
# Analyze microservice project
diagram = await generator.generate_architecture_diagram(
    root_path="./microservices",
    name="microservice_arch",
)

# Shows services, databases, APIs, and communication
await generator.export_diagram(diagram, "microservices.svg")
```

### Monolith Decomposition

```python
# Understand monolithic codebase structure
diagram = await generator.generate_dependency_diagram(
    root_path="./legacy_app",
    name="legacy_deps",
)

# Identify tight coupling and circular dependencies
await generator.export_diagram(diagram, "dependencies.svg")
```

### API Documentation

```python
# Generate API endpoint diagrams
diagram = await generator.generate_architecture_diagram(
    root_path="./api_project",
)

# Export to Mermaid for Markdown docs
await generator.export_diagram(diagram, "api_architecture.md", format=ExportFormat.MERMAID)
```

## Troubleshooting

### Import Errors

```python
# If you get import errors for graph libraries
pip install networkx  # For graph algorithms
pip install graphviz  # For DOT export
pip install cairosvg  # For PNG export
```

### Large Codebases

For very large codebases (1000+ files):

```python
config = DiagramConfig(
    max_depth=2,  # Limit depth
    exclude_patterns=[
        r"test_",
        r"__pycache__",
        r"migrations",
        r"node_modules",
    ],
    min_confidence=0.8,  # Filter low-confidence
)
```

### Memory Issues

If you encounter memory issues:

```python
# Analyze in chunks
for module_dir in Path("./project").glob("*/"):
    diagram = await generator.generate_architecture_diagram(
        root_path=module_dir,
        name=f"{module_dir.name}_arch",
    )
```

## Integration with CI/CD

### GitHub Actions

```yaml
name: Generate Diagrams

on: [push, pull_request]

jobs:
  diagrams:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install mahavishnu[all]
      
      - name: Generate diagrams
        run: |
          mahavishnu diagram generate . --type architecture --output docs/architecture.svg
          mahavishnu diagram generate . --type dependency --output docs/dependencies.svg
      
      - name: Upload diagrams
        uses: actions/upload-artifact@v3
        with:
          name: diagrams
          path: docs/*.svg
```

### Pre-commit Hook

```bash
# .git/hooks/pre-commit
#!/bin/bash
# Auto-generate diagrams on commit

mahavishnu diagram generate . --type architecture --output docs/architecture.svg
git add docs/architecture.svg
```

## Best Practices

1. **Commit Generated Diagrams**: Include diagrams in version control
2. **Update Regularly**: Regenerate diagrams after significant changes
3. **Use Multiple Formats**: SVG for docs, Mermaid for README, HTML for interactive viewing
4. **Filter Noise**: Exclude tests, migrations, and generated code
5. **Set Confidence Threshold**: Use 0.7-0.8 for production diagrams
6. **Choose Appropriate Layout**: Hierarchical for architecture, Force-directed for dependencies

## Contributing

To extend the diagram generator:

1. Add new component types in `ComponentType` enum
2. Add detection logic in `CodebaseAnalyzer._detect_function_type()`
3. Add new layout algorithms in `LayoutEngine`
4. Add new export formats in `DiagramGenerator._export_*()`

## References

- [Graphviz](https://graphviz.org/) - Graph visualization software
- [Mermaid.js](https://mermaid.js.org/) - Markdown diagram syntax
- [D3.js](https://d3js.org/) - Interactive data visualization
- [Python AST](https://docs.python.org/3/library/ast.html) - Abstract Syntax Tree

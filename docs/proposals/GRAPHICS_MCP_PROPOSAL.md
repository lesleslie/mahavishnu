# Graphics-MCP Proposal

## Executive Summary

A unified graphics manipulation MCP server that provides a common API for multiple graphics applications (GIMP, Inkscape, Blender) with Oneiric configuration, mcp-common patterns, and FastMCP implementation.

## Problem Statement

Current graphics MCP servers have limitations:
- **gimp-mcp**: Requires plugin running inside GIMP, stdio-only, no HTTP support
- **Inkscape**: Only shell-mode automation, no MCP integration
- **Blender**: No existing MCP server in our stack
- **Fragmentation**: Each tool has different APIs and patterns

## Proposed Solution

### `graphics-mcp` - Unified Graphics Manipulation Server

A FastMCP-based server that:
1. Supports multiple graphics backends (GIMP, Inkscape, Blender, ImageMagick)
2. Provides both stdio and HTTP transport
3. Uses Oneiric for configuration
4. Follows mcp-common patterns for consistency

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     graphics-mcp                             │
│                    (FastMCP Server)                          │
├─────────────────────────────────────────────────────────────┤
│  Transport Layer                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │    stdio     │  │    HTTP      │  │   WebSocket      │   │
│  │  (default)   │  │ :3040/mcp    │  │   (realtime)     │   │
│  └──────────────┘  └──────────────┘  └──────────────────┘   │
├─────────────────────────────────────────────────────────────┤
│  Core Services (mcp-common patterns)                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │ HealthCheck  │  │ ErrorHandling│  │   Validation     │   │
│  │   System     │  │   (retry)    │  │   (Pydantic)     │   │
│  └──────────────┘  └──────────────┘  └──────────────────┘   │
├─────────────────────────────────────────────────────────────┤
│  Backend Adapters                                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │    GIMP      │  │   Inkscape   │  │     Blender      │   │
│  │  (D-Bus/HTTP)│  │  (CLI/HTTP)  │  │   (Python API)   │   │
│  └──────────────┘  └──────────────┘  └──────────────────┘   │
│  ┌──────────────┐  ┌──────────────┐                         │
│  │  ImageMagick │  │   Pillow     │                         │
│  │    (CLI)     │  │  (Direct)    │                         │
│  └──────────────┘  └──────────────┘                         │
└─────────────────────────────────────────────────────────────┘
```

## Configuration (Oneiric)

```yaml
# settings/graphics.yaml
server_name: "Graphics MCP Server"
version: "1.0.0"

# Transport configuration
transport:
  stdio:
    enabled: true
  http:
    enabled: true
    host: "127.0.0.1"
    port: 3040
  websocket:
    enabled: false
    port: 3041

# Backend configuration
backends:
  gimp:
    enabled: true
    connection_type: "dbus"  # dbus, http, plugin
    dbus_service: "org.gimp.GIMP"
    http_port: 9877  # For plugin-based connection
    timeout: 30

  inkscape:
    enabled: true
    connection_type: "cli"  # cli, http
    command: "inkscape"
    shell_mode: true
    timeout: 60

  blender:
    enabled: true
    connection_type: "python"  # python, cli
    command: "blender"
    background_mode: true
    timeout: 120

  imagemagick:
    enabled: true
    connection_type: "cli"
    convert_command: "magick"  # or "convert" on older versions
    timeout: 30

  pillow:
    enabled: true
    connection_type: "direct"  # Direct Python import

# Quality defaults
defaults:
  output_format: "png"
  quality: 95
  compression: 6

# Security
security:
  allowed_paths:
    - "~/Pictures"
    - "~/Documents"
    - "/tmp"
  max_file_size_mb: 100
```

## MCP Tools

### Universal Tools (All Backends)

```python
# Image operations
@mcp.tool()
async def open_image(path: str, backend: str = "auto") -> ImageInfo:
    """Open an image file in specified backend."""

@mcp.tool()
async def save_image(
    image_id: str,
    path: str,
    format: str = "png",
    quality: int = 95
) -> str:
    """Save image to file."""

@mcp.tool()
async def get_image_info(image_id: str) -> ImageInfo:
    """Get image metadata (dimensions, format, color space)."""

@mcp.tool()
async def close_image(image_id: str) -> bool:
    """Close image and free resources."""
```

### Raster Operations (GIMP, ImageMagick, Pillow)

```python
@mcp.tool()
async def resize_image(
    image_id: str,
    width: int,
    height: int,
    maintain_aspect: bool = True,
    interpolation: str = "lanczos"
) -> ImageInfo:
    """Resize image with specified interpolation."""

@mcp.tool()
async def crop_image(
    image_id: str,
    x: int, y: int,
    width: int, height: int
) -> ImageInfo:
    """Crop image to specified region."""

@mcp.tool()
async def rotate_image(
    image_id: str,
    angle: float,
    expand: bool = True
) -> ImageInfo:
    """Rotate image by angle in degrees."""

@mcp.tool()
async def adjust_colors(
    image_id: str,
    brightness: float = 0,
    contrast: float = 0,
    saturation: float = 0,
    hue: float = 0
) -> ImageInfo:
    """Adjust color properties."""

@mcp.tool()
async def apply_filter(
    image_id: str,
    filter_name: str,
    params: dict[str, Any]
) -> ImageInfo:
    """Apply named filter (blur, sharpen, edge-detect, etc.)."""

@mcp.tool()
async def layer_operation(
    image_id: str,
    operation: str,  # new, delete, duplicate, merge, reorder
    layer_id: str | None = None,
    params: dict[str, Any] | None = None
) -> LayerInfo:
    """Perform layer operations."""
```

### Vector Operations (Inkscape)

```python
@mcp.tool()
async def create_shape(
    document_id: str,
    shape_type: str,  # rectangle, ellipse, polygon, path, text
    params: dict[str, Any]
) -> ShapeInfo:
    """Create a vector shape."""

@mcp.tool()
async def apply_svg_filter(
    document_id: str,
    object_id: str,
    filter_name: str
) -> bool:
    """Apply SVG filter to object."""

@mcp.tool()
async def export_svg(
    document_id: str,
    path: str,
    area: str = "document"  # document, selection, drawing
) -> str:
    """Export to SVG format."""

@mcp.tool()
async def text_to_path(document_id: str, text_id: str) -> str:
    """Convert text object to path."""
```

### 3D Operations (Blender)

```python
@mcp.tool()
async def create_object(
    scene_id: str,
    object_type: str,  # cube, sphere, cylinder, plane, mesh
    params: dict[str, Any]
) -> ObjectInfo:
    """Create a 3D object."""

@mcp.tool()
async def apply_modifier(
    object_id: str,
    modifier_type: str,  # subsurf, bevel, mirror, boolean
    params: dict[str, Any]
) -> bool:
    """Apply modifier to object."""

@mcp.tool()
async def render_scene(
    scene_id: str,
    output_path: str,
    engine: str = "cycles",  # cycles, eevee, workbench
    resolution: tuple[int, int] = (1920, 1080),
    samples: int = 128
) -> str:
    """Render scene to image."""

@mcp.tool()
async def set_material(
    object_id: str,
    material_params: dict[str, Any]
) -> str:
    """Apply material to object."""
```

## Project Structure

```
graphics-mcp/
├── graphics_mcp/
│   ├── __init__.py
│   ├── cli.py                 # CLI entry point
│   ├── server.py              # FastMCP server setup
│   ├── config.py              # Oneiric-based settings
│   ├── models.py              # Pydantic models
│   ├── exceptions.py          # Custom exceptions
│   │
│   ├── backends/
│   │   ├── __init__.py
│   │   ├── base.py            # Abstract backend interface
│   │   ├── gimp.py            # GIMP backend (D-Bus/HTTP)
│   │   ├── inkscape.py        # Inkscape backend (CLI)
│   │   ├── blender.py         # Blender backend (Python)
│   │   ├── imagemagick.py     # ImageMagick backend (CLI)
│   │   └── pillow.py          # Pillow backend (Direct)
│   │
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── universal.py       # Universal image tools
│   │   ├── raster.py          # Raster-specific tools
│   │   ├── vector.py          # Vector-specific tools
│   │   └── three_d.py         # 3D-specific tools
│   │
│   └── utils/
│       ├── __init__.py
│       ├── path_validation.py # Security: path validation
│       └── format_detection.py
│
├── settings/
│   └── graphics.yaml          # Default configuration
│
├── tests/
│   ├── conftest.py
│   ├── test_backends/
│   └── test_tools/
│
├── pyproject.toml
└── README.md
```

## Dependencies

```toml
[project]
dependencies = [
    "fastmcp>=0.9.0",
    "mcp-common @ git+https://github.com/lesleslie/mcp-common.git",
    "oneiric>=0.5.0",
    "pillow>=11.0.0",
    "pydantic>=2.10.0",
    "rich>=13.0.0",
]

[project.optional-dependencies]
gimp = [
    "pygobject>=3.50.0",  # For D-Bus communication
]
blender = [
    # Blender uses its own Python, so this is for background mode
]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
    "pytest-cov>=6.0.0",
    "ruff>=0.9.0",
    "mypy>=1.14.0",
]
```

## Implementation Phases

### Phase 1: Foundation (Week 1)
- [ ] Project structure setup
- [ ] Oneiric configuration
- [ ] Base backend interface
- [ ] Pillow backend (direct Python, easiest)
- [ ] Universal tools implementation
- [ ] Basic HTTP transport

### Phase 2: CLI Backends (Week 2)
- [ ] ImageMagick backend
- [ ] Inkscape CLI backend
- [ ] Raster and vector tools
- [ ] Format detection and conversion

### Phase 3: Advanced Backends (Week 3)
- [ ] GIMP D-Bus backend
- [ ] GIMP HTTP fallback (plugin-based)
- [ ] Blender background mode
- [ ] 3D tools implementation

### Phase 4: Polish (Week 4)
- [ ] WebSocket transport
- [ ] Comprehensive error handling
- [ ] Full test coverage
- [ ] Documentation

## Comparison with gimp-mcp

| Feature | gimp-mcp | graphics-mcp |
|---------|----------|--------------|
| Transport | stdio only | stdio + HTTP + WebSocket |
| Configuration | Hardcoded | Oneiric (YAML + env) |
| Backends | GIMP only | GIMP, Inkscape, Blender, ImageMagick, Pillow |
| GIMP Connection | Plugin required | D-Bus (native) or plugin fallback |
| Architecture | Single file | Modular backend system |
| Error Handling | Basic | Retry + circuit breaker |
| Testing | Minimal | Comprehensive |
| mcp-common | No | Yes |

## Worker Integration

The `application-gimp`, `application-inkscape`, and `application-blender` worker types in Mahavishnu can use this server:

```python
# In mahavishnu/workers/application.py
class ApplicationWorker(BaseWorker):
    async def execute_gimp_operation(self, operation: str, params: dict):
        """Execute GIMP operation via graphics-mcp."""
        result = await self.mcp_client.call_tool(
            "graphics-mcp",
            operation,
            params
        )
        return result
```

## Security Considerations

1. **Path Validation**: All file paths validated against allowed directories
2. **File Size Limits**: Configurable max file size to prevent DoS
3. **Sandbox Mode**: Optional container execution for untrusted operations
4. **Rate Limiting**: Prevent abuse via operation rate limits

## Next Steps

1. Create repository: `graphics-mcp`
2. Set up project structure with mcp-common patterns
3. Implement Pillow backend as proof of concept
4. Add ImageMagick backend for CLI operations
5. Integrate with Mahavishnu worker system

## References

- [FastMCP Documentation](https://github.com/anthropics/fastmcp)
- [mcp-common Patterns](https://github.com/lesleslie/mcp-common)
- [Oneiric Configuration](https://github.com/lesleslie/oneiric)
- [GIMP Python API](https://www.gimp.org/docs/python/)
- [Inkscape Command Line](https://inkscape.org/doc/inkscape-man.html)
- [Blender Python API](https://docs.blender.org/api/current/)

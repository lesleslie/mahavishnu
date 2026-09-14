# Installation

This guide covers how to install and set up Mahavishnu.

## Prerequisites

- Python 3.14 or higher
- pip or uv package manager

## Installing Mahavishnu

### Using uv (recommended)

```bash
uv sync
```

For development dependencies, use:

```bash
uv sync --group dev
```

### Using pip

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e .
```

## Installing with Optional Dependencies

Optional dependency groups cover specific runtime integrations:

```bash
uv sync --group ai        # Pydantic AI adapter
uv sync --group gpu       # RunPod GPU pool
uv sync --group sandbox   # E2B sandbox worker
uv sync --group shepherd  # Shepherd worker backend
```

## Verifying Installation

After installation, you can verify that Mahavishnu is properly installed:

```bash
uv run mahavishnu --help
```

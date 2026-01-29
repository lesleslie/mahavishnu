# Installation

This guide covers how to install and set up Mahavishnu.

## Prerequisites

- Python 3.13 or higher
- pip or uv package manager

## Installing Mahavishnu

### Using uv (recommended)

```bash
uv venv
source .venv/bin/activate
uv pip install -e .
```

### Using pip

```bash
pip install -e .
```

## Installing with Optional Dependencies

### For LangGraph workflows

```bash
pip install -e .[langgraph]
```

### For Prefect workflows

```bash
pip install -e .[prefect]
```

### For all adapters

```bash
pip install -e .[all]
```

## Verifying Installation

After installation, you can verify that Mahavishnu is properly installed:

```bash
mahavishnu --help
```

# Prefect Adapter

The Prefect adapter provides integration with Prefect for general workflow orchestration.

## Overview

Prefect is ideal for general workflow orchestration, ETL pipelines, and automation tasks.

## Configuration

```yaml
prefect:
  enabled: true
  api_url: "https://api.prefect.cloud"
  api_key: "${PREFECT_API_KEY}"
  work_pool: "default"
  timeout: 300
```

## Usage

```bash
mahavishnu sweep --tag backend --adapter prefect
```

## Features

- Pure Python workflow definitions
- Lightweight infrastructure requirements
- Cost-effective compared to Airflow
- Robust scheduling and monitoring

## Best Practices

- Use for general workflow orchestration
- Implement proper task retries
- Monitor flow run performance
- Use work pools for resource management
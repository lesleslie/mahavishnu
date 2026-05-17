# CLI Reference

Quick reference for Mahavishnu CLI commands.

## Repository Management

```bash
mahavishnu list-repos                          # List all repositories
mahavishnu list-repos --tag backend            # Filter by tag
mahavishnu list-repos --role orchestrator      # Filter by role
mahavishnu list-roles                          # Show all available roles
mahavishnu show-role tool                      # Details about a role
mahavishnu list-nicknames                      # All repository nicknames
```

## Content Ingestion

```bash
mahavishnu ingest web --url "https://example.com"
mahavishnu ingest blog --url "https://blog.example.com/post"
mahavishnu ingest book --path ~/Documents/book.pdf
mahavishnu quality evaluate --content-id <id>
```

## WebSocket & Monitoring

```bash
mahavishnu websocket start --port 8690
mahavishnu monitor pools
mahavishnu monitor workflows
```

## Routing System

```bash
mahavishnu routing stats                                    # View routing statistics
mahavishnu routing recalculate                              # Update adapter preferences
mahavishnu routing set-budget --type daily --limit 50      # Set cost budget
mahavishnu routing set-strategy --task-type AI_TASK --strategy cost
mahavishnu routing list-budgets
mahavishnu routing delete-budget --type daily
```

## MCP Server

```bash
mahavishnu mcp start     # Start MCP server
mahavishnu mcp status    # Check status
mahavishnu mcp health    # Health probe
mahavishnu mcp stop      # Stop server
```

## Pool Management

```bash
mahavishnu pool spawn --type mahavishnu --name local --min 2 --max 5
mahavishnu pool list
mahavishnu pool execute pool_abc --prompt "Write code"
mahavishnu pool route --prompt "Write code" --selector least_loaded
mahavishnu pool scale pool_abc --target 10
mahavishnu pool health
mahavishnu pool close pool_abc
mahavishnu pool close-all
```

## Workflow & Sweep

```bash
mahavishnu sweep --tag python --adapter prefect
```

## Testing & Quality

```bash
pytest
pytest --cov=mahavishnu --cov-report=html
crackerjack run
```

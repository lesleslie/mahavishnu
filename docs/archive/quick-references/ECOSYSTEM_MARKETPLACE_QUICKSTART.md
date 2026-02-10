# Ecosystem Marketplace - Quick Reference

## Installation & Setup

```bash
# Authenticate
mahavishnu marketplace login --api-key mk_live_abc123

# Verify installation
mahavishnu marketplace --help
```

## Common Commands

### Search & Browse

```bash
# Search packages
mahavishnu marketplace search "data pipeline"

# Search with filters
mahavishnu marketplace search "agent" \\
    --category agent \\
    --verified \\
    --sort downloads \\
    --limit 10

# Show trending
mahavishnu marketplace trending --category agent

# View package details
mahavishnu marketplace show data-pipeline-agent

# View marketplace stats
mahavishnu marketplace stats
```

### Install & Manage

```bash
# Install package
mahavishnu marketplace install data-pipeline-agent

# Install specific version
mahavishnu marketplace install data-pipeline-agent --version 1.2.0

# List installed
mahavishnu marketplace list --verbose

# Update package
mahavishnu marketplace update data-pipeline-agent

# Uninstall package
mahavishnu marketplace uninstall data-pipeline-agent
```

### Publish

```bash
# Initialize package template
mahavishnu marketplace init \\
    --name "my-agent" \\
    --category agent \\
    --output package.json

# Validate package.json
mahavishnu marketplace validate --package-file package.json

# Publish package
mahavishnu marketplace publish --package-file package.json

# Save as draft
mahavishnu marketplace publish --package-file package.json --draft
```

### Engage

```bash
# Rate package
mahavishnu marketplace rate data-pipeline-agent --rating 5

# Review package
mahavishnu marketplace review data-pipeline-agent \\
    --title "Excellent!" \\
    --content "Great package" \\
    --rating 5

# View profile
mahavishnu marketplace profile

# View another user
mahavishnu marketplace profile --user alice
```

### Utilities

```bash
# Open web UI
mahavishnu marketplace web

# Logout
mahavishnu marketplace logout
```

## Package Categories

- `agent`: AI agents
- `tool`: Command-line tools
- `workflow`: Workflow templates
- `integration`: Third-party integrations
- `template`: Code templates
- `extension`: Platform extensions
- `ui_component`: UI components
- `dataset`: Datasets
- `model`: ML models
- `documentation`: Documentation

## Sort Options

- `relevance`: Search relevance (default)
- `downloads`: Most downloads
- `rating`: Highest rated
- `updated`: Recently updated
- `created`: Recently created
- `name`: Alphabetical

## Filters

- `--category, -c`: Filter by category
- `--license, -l`: Filter by license
- `--free`: Free packages only
- `--verified, -V`: Verified packages only
- `--limit, -n`: Max results (1-100)
- `--verbose, -v`: Detailed output

## Licenses

- `MIT`: MIT License
- `Apache-2.0`: Apache License 2.0
- `GPL-3.0`: GNU GPL 3.0
- `BSD-3-Clause`: BSD 3-Clause
- `ISC`: ISC License
- `Proprietary`: Proprietary
- `CC-BY-4.0`: CC BY 4.0
- `CC-BY-NC-4.0`: CC BY-NC 4.0

## package.json Template

```json
{
  "name": "my-agent",
  "description": "Brief description",
  "long_description": "Detailed description",
  "version": "1.0.0",
  "author": "username",
  "category": "agent",
  "tags": ["tag1", "tag2"],
  "license": "MIT",
  "repository_url": "https://github.com/user/repo",
  "homepage_url": "https://example.com",
  "documentation_url": "https://docs.example.com",
  "download_url": "https://cdn.example.com/package-1.0.0.tar.gz",
  "icon_url": "https://cdn.example.com/icon.png",
  "screenshots": [],
  "price_usd": 0.0,
  "subscription_monthly_usd": null,
  "dependencies": {
    "mahavishnu-core": ">=1.0.0"
  },
  "compatible_versions": ["1.0.0"],
  "status": "published"
}
```

## Python API

```python
from mahavishnu.integrations.ecosystem_marketplace_cli import (
    MarketplaceClient,
    PackageCategory,
    PackageSortBy,
)

# Initialize
client = MarketplaceClient(config)

# Search
packages = await client.search_packages(
    query="data pipeline",
    category=PackageCategory.AGENT,
    verified_only=True,
    sort_by=PackageSortBy.DOWNLOADS,
    limit=10,
)

# Get package
pkg = await client.get_package("data-pipeline-agent")

# Install
manifest = await client.install_package(
    "data-pipeline-agent",
    version="1.2.0",
)

# Rate
await client.rate_package("data-pipeline-agent", 5)

# Review
await client.review_package(
    "data-pipeline-agent",
    "Excellent!",
    "Great package",
    5,
)

# Get trending
trending = await client.get_trending(
    category=PackageCategory.AGENT,
    limit=10,
)

# Get stats
stats = await client.get_statistics()

# Get profile
profile = await client.get_user_profile("alice")
```

## REST API

### Base URL
```
https://marketplace.mahavishnu.ai/api/v1
```

### Authentication
```bash
curl -H "Authorization: Bearer YOUR_API_KEY" \\
     https://marketplace.mahavishnu.ai/api/v1/packages
```

### Endpoints

```bash
# Search
GET /packages?q=query&category=agent&verified=true

# Get package
GET /packages/{package_id}

# Install
POST /packages/install
{"package_id": "data-pipeline-agent", "version": "1.2.0"}

# Publish
POST /packages
{...package metadata...}

# Rate
POST /packages/{package_id}/rating
{"rating": 5}

# Review
POST /packages/{package_id}/reviews
{"title": "Excellent!", "content": "Great", "rating": 5}

# Get reviews
GET /packages/{package_id}/reviews

# Get user profile
GET /users/{username}

# Get stats
GET /stats

# Get trending
GET /trending?category=agent&limit=10

# List installed
GET /packages/installed

# Update installed
POST /packages/installed/{package_id}/update

# Uninstall
DELETE /packages/installed/{package_id}
```

## Error Handling

```bash
# Package not found
mahavishnu marketplace install nonexistent-package
# Error: Package 'nonexistent-package' not found

# Invalid rating
mahavishnu marketplace rate data-pipeline-agent --rating 6
# Error: Rating must be between 1 and 5

# Validation errors
mahavishnu marketplace validate --package-file package.json
# ✓ Package file is valid: package.json
# ⚠ Warnings:
#   - Missing description

# Network errors
mahavishnu marketplace search "test"
# Error: Failed to connect to marketplace API
# Please check your internet connection
```

## Configuration

### Config File

```yaml
# settings/local.yaml
marketplace_api_key: "mk_live_abc123"
```

### Environment Variable

```bash
export MAHAVISHNU_MARKETPLACE_API_KEY="mk_live_abc123"
```

## Troubleshooting

### Installation Issues

```bash
# Check package details
mahavishnu marketplace show package-id

# Verify download URL
curl -I DOWNLOAD_URL

# Check dependencies
mahavishnu marketplace show package-id --verbose
```

### Authentication Issues

```bash
# Logout and login
mahavishnu marketplace logout
mahavishnu marketplace login --api-key NEW_KEY

# Check config
cat settings/local.yaml
```

### Search Issues

```bash
# Try broader search
mahavishnu marketplace search "keyword"

# List all categories
mahavishnu marketplace search "" --limit 100

# Check trending
mahavishnu marketplace trending
```

## Best Practices

### Publishing

1. **Validate first**: Always run `validate` before `publish`
2. **Use semver**: Follow semantic versioning (1.2.3)
3. **Clear descriptions**: Provide helpful short and long descriptions
4. **Screenshots**: Include multiple screenshots
5. **Documentation**: Link to full documentation
6. **License**: Choose appropriate license
7. **Pricing**: Consider fair pricing for paid packages

### Security

1. **HTTPS only**: Use HTTPS for all URLs
2. **Verify sources**: Only install from verified packages
3. **Check dependencies**: Review package dependencies
4. **Keep updated**: Update packages regularly
5. **Review code**: Audit package code before using in production

### Community

1. **Rate packages**: Help others discover quality packages
2. **Write reviews**: Share your experiences
3. **Report issues**: Report bugs and security issues
4. **Contribute**: Improve existing packages
5. **Share**: Publish your own packages

## Support

- **Documentation**: https://docs.mahavishnu.ai/marketplace
- **Issues**: https://github.com/mahavishnu/marketplace/issues
- **Email**: marketplace@mahavishnu.ai
- **Discord**: https://discord.gg/mahavishnu

## Summary

The Ecosystem Marketplace provides:

- **15 CLI commands** for complete package management
- **10 categories** for organizing packages
- **8 licenses** for flexibility
- **Security** with verified packages and scores
- **Monetization** with paid packages and subscriptions
- **Search** with advanced filters
- **Ratings & reviews** for community feedback
- **Trending** for discovery
- **Web UI** for visual browsing
- **REST API** for programmatic access

Happy packaging!

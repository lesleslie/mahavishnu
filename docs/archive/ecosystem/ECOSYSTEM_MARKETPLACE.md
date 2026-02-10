# Ecosystem Marketplace

The Ecosystem Marketplace is a centralized platform for discovering, installing, publishing, and managing Mahavishnu packages, agents, tools, workflows, and integrations.

## Features

- **Package Discovery**: Search and browse thousands of community-contributed packages
- **One-Click Installation**: Install packages with automatic dependency resolution
- **Publishing**: Share your packages with the community
- **Ratings & Reviews**: Rate and review packages to help others discover quality content
- **Monetization**: Earn money from paid packages and subscriptions
- **Security**: Verified packages with security scores
- **Analytics**: Track downloads, ratings, and earnings

## Quick Start

### Installation

```bash
# Install a free package
mahavishnu marketplace install data-pipeline-agent

# Install a specific version
mahavishnu marketplace install data-pipeline-agent --version 1.2.0

# Install to custom directory
mahavishnu marketplace install data-pipeline-agent --path /opt/mahavishnu/packages
```

### Search

```bash
# Basic search
mahavishnu marketplace search "data pipeline"

# Search with filters
mahavishnu marketplace search "agent" \\
    --category agent \\
    --verified \\
    --sort downloads \\
    --limit 10
```

### Publishing

```bash
# Initialize package template
mahavishnu marketplace init \\
    --name my-agent \\
    --category agent \\
    --output package.json

# Edit package.json, then publish
mahavishnu marketplace publish --package-file package.json

# Save as draft (don't publish yet)
mahavishnu marketplace publish --package-file package.json --draft
```

## CLI Commands

### marketplace search

Search for packages in the marketplace.

```bash
mahavishnu marketplace search QUERY [OPTIONS]
```

**Options:**
- `--category, -c`: Filter by category (agent, tool, workflow, integration, template, extension, ui_component, dataset, model, documentation)
- `--license, -l`: Filter by license (MIT, Apache-2.0, GPL-3.0, BSD-3-Clause, ISC, Proprietary, CC-BY-4.0, CC-BY-NC-4.0)
- `--free`: Only show free packages
- `--verified, -V`: Only show verified packages
- `--sort, -s`: Sort order (relevance, downloads, rating, updated, created, name)
- `--limit, -n`: Maximum results (1-100, default: 20)
- `--verbose, -v`: Show detailed output

**Examples:**
```bash
# Search for data agents
mahavishnu marketplace search "data agent" --category agent

# Find verified workflow tools, sorted by downloads
mahavishnu marketplace search "workflow" \\
    --category workflow \\
    --verified \\
    --sort downloads \\
    --limit 10
```

### marketplace install

Install a package from the marketplace.

```bash
mahavishnu marketplace install PACKAGE_ID [OPTIONS]
```

**Options:**
- `--version, -v`: Specific version (uses latest if not specified)
- `--path, -p`: Installation directory (default: ~/.mahavishnu/packages/)

**Examples:**
```bash
# Install latest version
mahavishnu marketplace install data-pipeline-agent

# Install specific version
mahavishnu marketplace install data-pipeline-agent --version 1.2.0

# Install to custom directory
mahavishnu marketplace install data-pipeline-agent \\
    --path /opt/mahavishnu/packages
```

### marketplace list

List installed packages.

```bash
mahavishnu marketplace list [OPTIONS]
```

**Options:**
- `--category, -c`: Filter by category
- `--verbose, -v`: Show detailed output

**Examples:**
```bash
# List all installed packages
mahavishnu marketplace list

# List installed agents with details
mahavishnu marketplace list --category agent --verbose
```

### marketplace update

Update an installed package to the latest version.

```bash
mahavishnu marketplace update PACKAGE_ID
```

**Example:**
```bash
mahavishnu marketplace update data-pipeline-agent
```

### marketplace uninstall

Uninstall a package.

```bash
mahavishnu marketplace uninstall PACKAGE_ID [OPTIONS]
```

**Options:**
- `--yes, -y`: Skip confirmation prompt

**Example:**
```bash
mahavishnu marketplace uninstall data-pipeline-agent
mahavishnu marketplace uninstall data-pipeline-agent --yes
```

### marketplace publish

Publish a package to the marketplace.

```bash
mahavishnu marketplace publish --package-file FILE [OPTIONS]
```

**Options:**
- `--package-file, -f`: Package metadata JSON file (required)
- `--draft, -d`: Save as draft (don't publish)

**Example:**
```bash
# Publish package
mahavishnu marketplace publish --package-file package.json

# Save as draft
mahavishnu marketplace publish --package-file package.json --draft
```

### marketplace rate

Rate a package (1-5 stars).

```bash
mahavishnu marketplace rate PACKAGE_ID --rating RATING
```

**Options:**
- `--rating, -r`: Rating (1-5 stars, required)

**Example:**
```bash
mahavishnu marketplace rate data-pipeline-agent --rating 5
```

### marketplace review

Submit a package review.

```bash
mahavishnu marketplace review PACKAGE_ID [OPTIONS]
```

**Options:**
- `--title, -t`: Review title (required)
- `--content, -c`: Review content (required)
- `--rating, -r`: Rating (1-5 stars, required)

**Example:**
```bash
mahavishnu marketplace review data-pipeline-agent \\
    --title "Excellent package" \\
    --content "Great for building data pipelines" \\
    --rating 5
```

### marketplace show

Show detailed package information.

```bash
mahavishnu marketplace show PACKAGE_ID [OPTIONS]
```

**Options:**
- `--reviews, -r`: Include reviews

**Example:**
```bash
mahavishnu marketplace show data-pipeline-agent
mahavishnu marketplace show data-pipeline-agent --reviews
```

### marketplace profile

Show or update user profile.

```bash
mahavishnu marketplace profile [OPTIONS]
```

**Options:**
- `--user, -u`: Username (default: current user)
- `--update`: Update profile mode

**Examples:**
```bash
# Show current user profile
mahavishnu marketplace profile

# Show another user's profile
mahavishnu marketplace profile --user alice

# Update profile (opens web UI)
mahavishnu marketplace profile --update
```

### marketplace stats

Show marketplace-wide statistics.

```bash
mahavishnu marketplace stats
```

**Output includes:**
- Total packages and downloads
- Total users and reviews
- Packages by category
- Recent activity
- Trending packages

### marketplace trending

Show trending packages.

```bash
mahavishnu marketplace trending [OPTIONS]
```

**Options:**
- `--category, -c`: Filter by category
- `--limit, -n`: Maximum results (1-50, default: 10)

**Examples:**
```bash
# Show top 10 trending packages
mahavishnu marketplace trending

# Show trending agents
mahavishnu marketplace trending --category agent --limit 20
```

### marketplace init

Initialize a new package template.

```bash
mahavishnu marketplace init --name NAME --category CATEGORY [OPTIONS]
```

**Options:**
- `--name, -n`: Package name (required)
- `--category, -c`: Package category (required)
- `--output, -o`: Output file (default: package.json)

**Example:**
```bash
mahavishnu marketplace init \\
    --name "my-agent" \\
    --category agent \\
    --output my-package.json
```

### marketplace validate

Validate a package metadata file before publishing.

```bash
mahavishnu marketplace validate --package-file FILE
```

**Example:**
```bash
mahavishnu marketplace validate --package-file package.json
```

### marketplace login

Authenticate with the marketplace.

```bash
mahavishnu marketplace login --api-key API_KEY
```

**Example:**
```bash
mahavishnu marketplace login --api-key mk_live_abc123
```

### marketplace logout

Remove marketplace authentication.

```bash
mahavishnu marketplace logout
```

### marketplace web

Open the marketplace web interface.

```bash
mahavishnu marketplace web
```

## Package Metadata

### package.json Structure

```json
{
  "name": "data-pipeline-agent",
  "description": "Agent for building data pipelines",
  "long_description": "A comprehensive agent for building scalable data pipelines",
  "version": "1.2.3",
  "author": "alice",
  "category": "agent",
  "tags": ["data", "pipeline", "etl", "automation"],
  "license": "MIT",
  "repository_url": "https://github.com/alice/data-pipeline-agent",
  "homepage_url": "https://data-pipeline.ai",
  "documentation_url": "https://docs.data-pipeline.ai",
  "download_url": "https://cdn.marketplace.mahavishnu.ai/packages/data-pipeline-agent-1.2.3.tar.gz",
  "icon_url": "https://cdn.marketplace.mahavishnu.ai/icons/data-pipeline-agent.png",
  "screenshots": [
    "https://cdn.marketplace.mahavishnu.ai/screenshots/s1.png"
  ],
  "price_usd": 0.0,
  "subscription_monthly_usd": null,
  "dependencies": {
    "mahavishnu-core": ">=1.0.0",
    "python": ">=3.10"
  },
  "compatible_versions": ["1.0.0", "1.1.0", "1.2.0"],
  "status": "published"
}
```

### Fields

- `name`: Package name (required)
- `description`: Short description (required)
- `long_description`: Detailed description
- `version`: Semantic version (required, e.g., 1.2.3)
- `author`: Author username or organization (required)
- `category`: Package category (required)
  - `agent`: AI agents
  - `tool`: Command-line tools
  - `workflow`: Workflow templates
  - `integration`: Third-party integrations
  - `template`: Code templates
  - `extension`: Mahavishnu extensions
  - `ui_component`: UI components
  - `dataset`: Datasets
  - `model`: ML models
  - `documentation`: Documentation packages
- `tags`: Searchable tags (array)
- `license`: Package license (required)
  - `MIT`, `Apache-2.0`, `GPL-3.0`, `BSD-3-Clause`, `ISC`, `Proprietary`, `CC-BY-4.0`, `CC-BY-NC-4.0`
- `repository_url`: Source repository URL
- `homepage_url`: Homepage URL
- `documentation_url`: Documentation URL
- `download_url`: Package download URL (required)
- `icon_url`: Package icon URL
- `screenshots`: Screenshot URLs (array)
- `price_usd`: One-time purchase price (0 = free)
- `subscription_monthly_usd`: Monthly subscription price (optional)
- `dependencies`: Required packages (object mapping name to version)
- `compatible_versions`: Compatible Mahavishnu versions (array)
- `status`: Publication status
  - `draft`: Draft (not published)
  - `pending_review`: Awaiting moderation
  - `approved`: Approved for publication
  - `published`: Published and visible
  - `deprecated`: Deprecated but still available
  - `removed`: Removed from marketplace

## Categories

### Agent
AI agents that perform automated tasks.
- Examples: Data pipeline agents, testing agents, code generation agents

### Tool
Command-line tools and utilities.
- Examples: Database migrators, log analyzers, deployment tools

### Workflow
Workflow templates and automation.
- Examples: CI/CD workflows, data processing workflows, monitoring workflows

### Integration
Third-party service integrations.
- Examples: Slack integration, GitHub integration, AWS integration

### Template
Code and project templates.
- Examples: FastAPI project template, React component template

### Extension
Mahavishnu platform extensions.
- Examples: Custom adapters, custom CLI commands

### UI Component
User interface components and themes.
- Examples: Dashboard widgets, custom themes

### Dataset
Datasets for ML and analytics.
- Examples: Training datasets, benchmark datasets

### Model
Machine learning models.
- Examples: NLP models, computer vision models

### Documentation
Documentation and guides.
- Examples: API documentation, tutorial packages

## Publishing Workflow

### 1. Prepare Your Package

```bash
# Initialize package template
mahavishnu marketplace init \\
    --name "my-agent" \\
    --category agent \\
    --output package.json
```

### 2. Edit package.json

Fill in all required fields:
- Name, description, version
- Author, category, license
- Download URL (upload package to CDN or repository)
- Dependencies and compatible versions

### 3. Validate

```bash
mahavishnu marketplace validate --package-file package.json
```

### 4. Publish

```bash
# Publish immediately (enters review queue)
mahavishnu marketplace publish --package-file package.json

# Save as draft (publish later)
mahavishnu marketplace publish --package-file package.json --draft
```

### 5. Review Process

- Automated security scanning
- Manual review by marketplace moderators
- Approval usually within 24-48 hours
- You'll receive email notification

## Monetization

### Pricing Models

#### Free
```json
{
  "price_usd": 0.0
}
```

#### One-Time Purchase
```json
{
  "price_usd": 99.0
}
```

#### Subscription
```json
{
  "price_usd": 99.0,
  "subscription_monthly_usd": 29.0
}
```

### Earnings

- Revenue share: 70% to author, 30% to marketplace
- Minimum payout: $50
- Payout methods: PayPal, Stripe, Bank Transfer
- Payout schedule: Monthly

### Tracking Earnings

```bash
# View your earnings
mahavishnu marketplace profile

# See detailed analytics
mahavishnu marketplace web
```

## Security

### Verified Packages

Verified packages have:
- Passed security audit
- Code review by marketplace team
- Trusted badge on listing

### Security Scores

- 90-100: Excellent
- 75-89: Good
- 60-74: Fair
- < 60: Poor

### Best Practices

1. **Use HTTPS** for all download URLs
2. **Sign packages** with GPG keys
3. **Include checksums** (SHA256)
4. **Document dependencies** clearly
5. **Keep packages updated**

## API Reference

### MarketplaceClient

Python client for programmatic access.

```python
from mahavishnu.integrations.ecosystem_marketplace_cli import MarketplaceClient

# Initialize client
client = MarketplaceClient(config)

# Search packages
packages = await client.search_packages("data pipeline")

# Get package details
pkg = await client.get_package("data-pipeline-agent")

# Install package
manifest = await client.install_package("data-pipeline-agent")

# Rate package
pkg = await client.rate_package("data-pipeline-agent", 5)

# Submit review
review = await client.review_package(
    "data-pipeline-agent",
    "Excellent!",
    "Great package",
    5
)

# Get trending
trending = await client.get_trending(category=PackageCategory.AGENT)

# Get statistics
stats = await client.get_statistics()
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

#### Search Packages
```
GET /packages?q=query&category=agent&verified=true&sort=downloads&limit=20
```

#### Get Package
```
GET /packages/{package_id}
```

#### Install Package
```
POST /packages/install
{
  "package_id": "data-pipeline-agent",
  "version": "1.2.0",
  "install_path": "/path/to/install"
}
```

#### Publish Package
```
POST /packages
{
  "name": "my-package",
  "description": "...",
  "version": "1.0.0",
  ...
}
```

#### Rate Package
```
POST /packages/{package_id}/rating
{
  "rating": 5
}
```

#### Submit Review
```
POST /packages/{package_id}/reviews
{
  "title": "Great!",
  "content": "Excellent package",
  "rating": 5
}
```

#### Get User Profile
```
GET /users/{username}
```

#### Get Statistics
```
GET /stats
```

#### Get Trending
```
GET /trending?category=agent&limit=10
```

## Webhooks

Receive notifications for marketplace events.

### Configure Webhook

```bash
curl -X POST https://marketplace.mahavishnu.ai/api/v1/webhooks \\
     -H "Authorization: Bearer YOUR_API_KEY" \\
     -d {
       "url": "https://your-server.com/webhook",
       "events": ["package.installed", "package.rated", "review.posted"]
     }
```

### Events

- `package.installed`: Your package was installed
- `package.rated`: Your package was rated
- `review.posted`: Your package received a review
- `package.purchased`: Your paid package was purchased
- `payout.processed`: Payout was processed

### Webhook Payload

```json
{
  "event": "package.installed",
  "timestamp": "2024-06-25T12:00:00Z",
  "data": {
    "package_id": "data-pipeline-agent",
    "version": "1.2.3",
    "installer": "user123"
  }
}
```

## Rate Limiting

API requests are rate limited:
- Free tier: 100 requests/hour
- Verified publishers: 1000 requests/hour
- Enterprise: Unlimited

Rate limit headers:
```
X-RateLimit-Limit: 1000
X-RateLimit-Remaining: 950
X-RateLimit-Reset: 1719300000
```

## Best Practices

### Package Naming

- Use kebab-case: `data-pipeline-agent`
- Be descriptive: `workflow-automation` not `wa`
- Avoid trademarked terms

### Versioning

Use semantic versioning:
- `MAJOR.MINOR.PATCH`
- MAJOR: Breaking changes
- MINOR: New features (backward compatible)
- PATCH: Bug fixes (backward compatible)

### Documentation

- Provide clear README
- Include installation instructions
- Document dependencies
- Provide usage examples
- Keep documentation updated

### Support

- Respond to reviews and questions
- Fix bugs promptly
- Release updates regularly
- Engage with the community

## Troubleshooting

### Installation Fails

```bash
# Check dependencies
mahavishnu marketplace show PACKAGE_ID

# Verify download URL
curl -I DOWNLOAD_URL

# Install with verbose output
mahavishnu marketplace install PACKAGE_ID --verbose
```

### Authentication Issues

```bash
# Logout and login again
mahavishnu marketplace logout
mahavishnu marketplace login --api-key NEW_KEY

# Check API key validity
curl -H "Authorization: Bearer YOUR_KEY" \\
     https://marketplace.mahavishnu.ai/api/v1/users/me
```

### Package Not Found

```bash
# Search for similar packages
mahavishnu marketplace search "similar name"

# Check package status
mahavishnu marketplace show PACKAGE_ID

# Try exact package ID
mahavishnu marketplace install EXACT_PACKAGE_ID
```

## Support

- Documentation: https://docs.mahavishnu.ai/marketplace
- Issues: https://github.com/mahavishnu/marketplace/issues
- Email: marketplace@mahavishnu.ai
- Discord: https://discord.gg/mahavishnu

## License

The Ecosystem Marketplace is part of Mahavishnu.
See LICENSE file for details.

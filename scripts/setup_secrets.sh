#!/bin/bash
# Secrets Setup Script for Production Deployment
#
# This script creates secure random secrets for production deployment.
# Run this once before deploying to production.
#
# Usage:
#   ./scripts/setup_secrets.sh
#
# After running, verify the secrets were created:
#   ls -la secrets/

set -e

SECRETS_DIR="$(dirname "$0")/../secrets"
cd "$SECRETS_DIR"

echo "Setting up production secrets in $SECRETS_DIR..."

# Generate secure random passwords
# postgres_password: 32 char alphanumeric
openssl rand -base64 24 | tr -d '/+=' | head -c 32 > postgres_password.txt
echo "✓ Generated postgres_password.txt"

# redis_password: 32 char alphanumeric
openssl rand -base64 24 | tr -d '/+=' | head -c 32 > redis_password.txt
echo "✓ Generated redis_password.txt"

# jwt_secret: 64 char (minimum 32 for HS256)
openssl rand -base64 48 | tr -d '/+=' | head -c 64 > jwt_secret.txt
echo "✓ Generated jwt_secret.txt"

# Set restrictive permissions (readable only by owner)
chmod 600 *.txt
echo "✓ Set file permissions to 600"

echo ""
echo "Secrets created successfully!"
echo ""
echo "IMPORTANT:"
echo "  1. Do NOT commit these files to version control"
echo "  2. Add 'secrets/' to .gitignore if not already present"
echo "  3. Store backups of these secrets securely"
echo "  4. Rotate secrets periodically (recommended: 90 days)"
echo ""
echo "To deploy with production settings:"
echo "  docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d"

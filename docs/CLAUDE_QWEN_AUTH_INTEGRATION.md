# Claude Code, Codex, and Qwen Authentication Integration Guide

## Overview

Mahavishnu now supports multiple authentication methods to work seamlessly with Claude Code subscriptions, Codex subscriptions, and Qwen (free service). This implementation provides:

1. **Claude Code subscription token authentication** - For users with Claude Code subscriptions
2. **Codex subscription token authentication** - For users with Codex subscriptions (legacy support)
3. **Qwen free service support** - Recognizing Qwen as a free service that doesn't require authentication
4. **Backward compatibility** - Maintains existing JWT authentication
5. **Flexible configuration** - Support for multiple auth methods simultaneously

## Configuration

### Enable Claude Code Subscription Authentication

To enable Claude Code subscription authentication, update your configuration:

```yaml
# settings/mahavishnu.yaml
subscription_auth_enabled: true
subscription_auth_secret: ${MAHAVISHNU_SUBSCRIPTION_AUTH_SECRET}
subscription_auth_algorithm: "HS256"
subscription_auth_expire_minutes: 60
```

Set the environment variable:
```bash
export MAHAVISHNU_SUBSCRIPTION_AUTH_SECRET="your_very_long_secret_key_at_least_32_chars"
```

### Enable JWT Authentication (existing)

```yaml
# settings/mahavishnu.yaml
auth_enabled: true
auth_secret: ${MAHAVISHNU_AUTH_SECRET}
auth_algorithm: "HS256"
auth_expire_minutes: 60
```

## CLI Commands

### Generate Claude Code Subscription Token

Generate a subscription token for Claude Code:

```bash
mahavishnu generate-claude-token <user_id>
```

Example:
```bash
mahavishnu generate-claude-token "user_12345"
```

This will output a Claude Code subscription token that can be used with the authorization header.

### Generate Codex Subscription Token

Generate a subscription token for Codex (legacy):

```bash
mahavishnu generate-codex-token <user_id>
```

Example:
```bash
mahavishnu generate-codex-token "user_12345"
```

This will output a Codex subscription token that can be used with the authorization header.

### Use with Claude Code

When using Claude Code, you can now use the generated subscription token:

```bash
# Set the token in your environment
export CLAUDE_CODE_TOKEN=$(mahavishnu generate-claude-token "my_user_id")

# Use the token in API calls
curl -H "Authorization: Bearer $CLAUDE_CODE_TOKEN" \
     -H "Content-Type: application/json" \
     http://localhost:3000/api/workflow/list-repos
```

## Authentication Methods Priority

The authentication system follows this priority order:

1. **Subscription Token** - If the token contains subscription-specific claims (`subscription_type`), it's processed as a subscription token
2. **JWT Token** - Standard JWT authentication for backward compatibility
3. **Qwen Free** - Qwen is recognized as a free service requiring no authentication

## API Usage

When making API calls to the MCP server, use the appropriate authentication header:

### Claude Code Subscription
```http
Authorization: Bearer <claude-subscription-token>
```

### Codex Subscription
```http
Authorization: Bearer <codex-subscription-token>
```

### JWT Authentication (existing)
```http
Authorization: Bearer <jwt-token>
```

## Architecture

The authentication system is built around the `MultiAuthHandler` class which:

1. **Supports multiple authentication methods** simultaneously
2. **Determines the correct method** by inspecting token claims
3. **Validates tokens** using the appropriate validator
4. **Returns consistent results** regardless of the authentication method used
5. **Distinguishes between Claude Code and Codex** subscriptions based on the `subscription_type` claim

### Classes

- `SubscriptionAuth` - Handles Claude Code and Codex subscription token creation and validation
- `JWTAuth` - Handles traditional JWT authentication (unchanged)
- `MultiAuthHandler` - Coordinates between authentication methods
- `AuthMethod` - Enum for different authentication methods

## Security Considerations

1. **Secret Length**: Both JWT and subscription auth secrets must be at least 32 characters
2. **Token Expiration**: Subscription tokens have configurable expiration times
3. **Claim Verification**: Authentication method is determined by inspecting token claims before validation
4. **Environment Variables**: Secrets should be stored in environment variables, not hardcoded

## Backward Compatibility

This implementation maintains full backward compatibility with existing JWT authentication. All existing configurations and tokens will continue to work without changes.

## Troubleshooting

### Common Issues

1. **Token Expiration**: If you receive "Token has expired" errors, regenerate your token
2. **Invalid Signature**: Ensure your secret keys match between token generation and validation
3. **Wrong Authentication Method**: Check that you're using the correct token type for your use case

### Debugging

Enable debug logging to see which authentication method is being used:

```bash
# In your configuration
logging:
  level: DEBUG
```

This will log authentication method selection and validation steps.
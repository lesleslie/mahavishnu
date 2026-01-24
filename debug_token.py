"""Debug script to check token expiration issue."""

import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
import jwt

# Add the project root to the path so we can import mahavishnu modules
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from mahavishnu.core.subscription_auth import SubscriptionAuth

# Create a test subscription auth
secret = 'a_very_long_secret_key_that_is_at_least_32_characters'
auth = SubscriptionAuth(secret, expire_minutes=60)

# Create a token
user_id = "test_user_123"
token = auth.create_subscription_token(user_id, "claude_code", ["read", "execute"])

print(f"Created token: {token[:100]}...")

# Decode the token to see its contents (without verifying signature)
decoded = jwt.decode(token, options={"verify_signature": False})
print(f"Decoded token: {decoded}")

# Check the expiration
exp_timestamp = decoded.get('exp')
print(f"Expiration timestamp: {exp_timestamp}")
print(f"Expiration datetime: {datetime.fromtimestamp(exp_timestamp)}")
print(f"Current datetime: {datetime.utcnow()}")

# Check if it's considered expired
is_expired = datetime.utcnow().timestamp() > exp_timestamp
print(f"Is expired: {is_expired}")

# Now try to verify with the actual method
try:
    result = auth.verify_subscription_token(token)
    print(f"Verification succeeded: {result}")
except Exception as e:
    print(f"Verification failed: {e}")
"""Test script for Claude Code and Qwen authentication implementation."""

import os
from pathlib import Path
import sys

# Add the project root to the path so we can import mahavishnu modules
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from mahavishnu.core.config import MahavishnuSettings
from mahavishnu.core.subscription_auth import AuthMethod, MultiAuthHandler


def test_claude_subscription_auth():
    """Test Claude Code subscription authentication functionality."""
    print("Testing Claude Code subscription authentication...")

    # Create a test configuration with subscription auth enabled
    os.environ["MAHAVISHNU_SUBSCRIPTION_AUTH_SECRET"] = (
        "a_very_long_secret_key_that_is_at_least_32_characters"
    )

    config = MahavishnuSettings(
        subscription_auth_enabled=True,
        subscription_auth_secret=os.environ.get("MAHAVISHNU_SUBSCRIPTION_AUTH_SECRET"),
        subscription_auth_expire_minutes=60,  # Set a longer expiration for testing
    )

    # Initialize the auth handler
    auth_handler = MultiAuthHandler(config)

    # Test that Claude Code subscription is recognized as available
    assert auth_handler.is_claude_subscribed() == True, (
        "Claude Code subscription should be available"
    )
    print("✅ Claude Code subscription is properly configured")

    # Test token creation
    user_id = "test_user_123"
    token = auth_handler.create_claude_subscription_token(
        user_id=user_id, scopes=["read", "execute", "workflow_manage"]
    )

    print(f"Generated Claude Code token: {token[:50]}...")

    # Verify the token can be authenticated
    auth_header = f"Bearer {token}"
    result = auth_handler.authenticate_request(auth_header)

    assert result["user"] == user_id, f"Expected user {user_id}, got {result['user']}"
    assert result["method"] == AuthMethod.CLAUDE_SUBSCRIPTION, (
        f"Expected method {AuthMethod.CLAUDE_SUBSCRIPTION}, got {result['method']}"
    )
    assert "read" in result["scopes"], "Read scope should be present"

    print("✅ Claude Code subscription token creation and authentication works correctly")


def test_qwen_free_auth():
    """Test that Qwen is recognized as a free service."""
    print("\nTesting Qwen free service recognition...")

    # Create a minimal config without any auth enabled
    config = MahavishnuSettings()

    # Initialize the auth handler
    auth_handler = MultiAuthHandler(config)

    # Test that Qwen is recognized as free
    assert auth_handler.is_qwen_free() == True, "Qwen should be recognized as free service"
    print("✅ Qwen is correctly recognized as a free service")


def test_jwt_fallback():
    """Test that JWT authentication still works as before."""
    print("\nTesting JWT authentication fallback...")

    # Set up environment for JWT auth
    os.environ["MAHAVISHNU_AUTH_SECRET"] = "another_very_long_secret_key_that_is_at_least_32_chars"

    config = MahavishnuSettings(
        auth_enabled=True, auth_secret=os.environ.get("MAHAVISHNU_AUTH_SECRET")
    )

    # Initialize the auth handler
    auth_handler = MultiAuthHandler(config)

    # Create a JWT token using the JWT auth directly
    jwt_token = auth_handler.jwt_auth.create_access_token({"sub": "test_user"})

    # Test that the JWT token can be authenticated
    auth_header = f"Bearer {jwt_token}"
    result = auth_handler.authenticate_request(auth_header)

    assert result["user"] == "test_user", f"Expected user test_user, got {result['user']}"
    assert result["method"] == AuthMethod.JWT, (
        f"Expected method {AuthMethod.JWT}, got {result['method']}"
    )

    print("✅ JWT authentication still works correctly")


def test_multi_auth_priority():
    """Test that both auth methods are available and prioritized correctly."""
    print("\nTesting multi-authentication priority...")

    # Set up both auth methods
    os.environ["MAHAVISHNU_AUTH_SECRET"] = "jwt_test_secret_that_is_at_least_32_characters_long"
    os.environ["MAHAVISHNU_SUBSCRIPTION_AUTH_SECRET"] = (
        "subscription_test_secret_that_is_at_least_32_chars"
    )

    config = MahavishnuSettings(
        auth_enabled=True,
        auth_secret=os.environ.get("MAHAVISHNU_AUTH_SECRET"),
        subscription_auth_enabled=True,
        subscription_auth_secret=os.environ.get("MAHAVISHNU_SUBSCRIPTION_AUTH_SECRET"),
    )

    # Initialize the auth handler
    auth_handler = MultiAuthHandler(config)

    # Create both types of tokens
    jwt_token = auth_handler.jwt_auth.create_access_token({"sub": "jwt_user"})
    claude_token = auth_handler.subscription_auth.create_subscription_token(
        user_id="claude_user", subscription_type="claude_code", scopes=["read", "execute"]
    )
    codex_token = auth_handler.subscription_auth.create_subscription_token(
        user_id="codex_user", subscription_type="codex", scopes=["read", "execute"]
    )

    # Test JWT token authentication
    jwt_result = auth_handler.authenticate_request(f"Bearer {jwt_token}")
    assert jwt_result["user"] == "jwt_user"
    assert jwt_result["method"] == AuthMethod.JWT

    # Test Claude subscription token authentication
    claude_result = auth_handler.authenticate_request(f"Bearer {claude_token}")
    assert claude_result["user"] == "claude_user"
    assert claude_result["method"] == AuthMethod.CLAUDE_SUBSCRIPTION

    # Test Codex subscription token authentication
    codex_result = auth_handler.authenticate_request(f"Bearer {codex_token}")
    assert codex_result["user"] == "codex_user"
    assert codex_result["method"] == AuthMethod.CODEX_SUBSCRIPTION

    print("✅ JWT, Claude, and Codex authentication all work correctly")


def test_codex_subscription_auth():
    """Test Codex subscription authentication functionality."""
    print("\nTesting Codex subscription authentication...")

    # Create a test configuration with subscription auth enabled
    os.environ["MAHAVISHNU_SUBSCRIPTION_AUTH_SECRET"] = (
        "a_very_long_secret_key_that_is_at_least_32_characters"
    )

    config = MahavishnuSettings(
        subscription_auth_enabled=True,
        subscription_auth_secret=os.environ.get("MAHAVISHNU_SUBSCRIPTION_AUTH_SECRET"),
        subscription_auth_expire_minutes=60,  # Set a longer expiration for testing
    )

    # Initialize the auth handler
    auth_handler = MultiAuthHandler(config)

    # Test that Codex subscription is available (same underlying mechanism as Claude)
    assert auth_handler.is_codex_subscribed() == True, "Codex subscription should be available"
    print("✅ Codex subscription is properly configured")

    # Test Codex token creation
    user_id = "test_codex_user_123"
    token = auth_handler.create_codex_subscription_token(
        user_id=user_id, scopes=["read", "execute", "workflow_manage"]
    )

    print(f"Generated Codex subscription token: {token[:50]}...")

    # Verify the Codex token can be authenticated
    auth_header = f"Bearer {token}"
    result = auth_handler.authenticate_request(auth_header)

    assert result["user"] == user_id, f"Expected user {user_id}, got {result['user']}"
    assert result["method"] == AuthMethod.CODEX_SUBSCRIPTION, (
        f"Expected method {AuthMethod.CODEX_SUBSCRIPTION}, got {result['method']}"
    )
    assert "read" in result["scopes"], "Read scope should be present"

    print("✅ Codex subscription token creation and authentication works correctly")


def run_all_tests():
    """Run all authentication tests."""
    print("Running authentication tests for Claude Code, Codex, and Qwen integration...\n")

    try:
        test_claude_subscription_auth()
        test_codex_subscription_auth()
        test_qwen_free_auth()
        test_jwt_fallback()
        test_multi_auth_priority()

        print(
            "\n🎉 All tests passed! Claude Code, Codex, and Qwen authentication integration is working correctly."
        )

    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    run_all_tests()

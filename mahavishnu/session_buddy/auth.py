"""Cross-project authentication for Session Buddy integration."""

from datetime import datetime, timedelta
import hashlib
import hmac
import json
import os
from typing import Any

from ..core.config import MahavishnuSettings


class CrossProjectAuth:
    """Shared authentication for Session Buddy ↔ Mahavishnu communication.

    Attributes:
        shared_secret: Shared secret key for HMAC signing
    """

    def __init__(self, shared_secret: str) -> None:
        """Initialize cross-project authentication.

        Args:
            shared_secret: Shared secret key for HMAC signing
        """
        self.shared_secret = shared_secret

    def sign_message(self, message: dict[str, Any]) -> str:
        """Generate HMAC-SHA256 signature for cross-project messages.

        Args:
            message: Message dictionary to sign

        Returns:
            Hexadecimal HMAC-SHA256 signature
        """
        message_str = json.dumps(message, sort_keys=True)
        hmac_obj = hmac.new(self.shared_secret.encode(), message_str.encode(), hashlib.sha256)
        return hmac_obj.hexdigest()

    def verify_message(self, message: dict[str, Any], signature: str) -> bool:
        """Verify message signature.

        Args:
            message: Message dictionary to verify
            signature: Signature to verify against

        Returns:
            True if signature is valid, False otherwise
        """
        expected = self.sign_message(message)
        return hmac.compare_digest(expected, signature)


class MessageAuthenticator:
    """Handles authentication for cross-project messages.

    Attributes:
        config: Mahavishnu configuration
        auth_secret: Shared secret for authentication
        authenticator: CrossProjectAuth instance
    """

    def __init__(self, config: MahavishnuSettings) -> None:
        """Initialize message authenticator.

        Args:
            config: Mahavishnu configuration

        Raises:
            ValueError: If auth secret is not configured or is too short
        """
        self.config = config
        self.auth_secret = getattr(
            config, "cross_project_auth_secret", os.getenv("CROSS_PROJECT_AUTH_SECRET")
        )

        if not self.auth_secret:
            raise ValueError(
                "Cross-project authentication requires a shared secret. "
                "Set CROSS_PROJECT_AUTH_SECRET environment variable or "
                "configure cross_project_auth_secret in settings."
            )

        if len(self.auth_secret) < 32:
            raise ValueError(
                "Cross-project authentication secret must be at least 32 characters long "
                "for security purposes."
            )

        self.authenticator = CrossProjectAuth(self.auth_secret)

    def create_authenticated_message(
        self, from_project: str, to_project: str, content: dict[str, Any]
    ) -> dict[str, Any]:
        """Create an authenticated message for cross-project communication.

        Args:
            from_project: Source project identifier
            to_project: Target project identifier
            content: Message content dictionary

        Returns:
            Authenticated message with signature
        """
        # Create the message payload
        message_payload = {
            "from_project": from_project,
            "to_project": to_project,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        }

        # Sign the message
        signature = self.authenticator.sign_message(message_payload)

        # Return the authenticated message
        return {"message": message_payload, "signature": signature, "algorithm": "HMAC-SHA256"}

    def verify_authenticated_message(
        self, authenticated_message: dict[str, Any]
    ) -> tuple[bool, dict[str, Any] | None]:
        """Verify an authenticated message and return its content if valid.

        Args:
            authenticated_message: Message dictionary with signature

        Returns:
            Tuple of (is_valid, message_payload or None)
        """
        try:
            message_payload = authenticated_message.get("message")
            signature = authenticated_message.get("signature")
            algorithm = authenticated_message.get("algorithm", "HMAC-SHA256")

            if not message_payload or not signature:
                return False, None

            if algorithm != "HMAC-SHA256":
                return False, None

            # Verify the signature - message_payload is guaranteed to be dict here
            is_valid = self.authenticator.verify_message(message_payload, signature)

            if is_valid:
                # Check if message is too old (replay attack prevention)
                timestamp_str = message_payload.get("timestamp") if message_payload else None
                if timestamp_str:
                    try:
                        timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                        # Allow messages up to 5 minutes old
                        if datetime.now() - timestamp > timedelta(minutes=5):
                            return False, None
                    except ValueError:
                        # If timestamp is invalid, reject the message
                        return False, None

                return True, message_payload
            else:
                return False, None

        except Exception:
            return False, None

    def is_cross_project_auth_enabled(self) -> bool:
        """Check if cross-project authentication is enabled.

        Returns:
            True if authentication is configured and enabled
        """
        return bool(self.auth_secret)


class AuthenticatedSessionBuddyClient:
    """Authenticated client for Session Buddy communication.

    Attributes:
        config: Mahavishnu configuration
        authenticator: MessageAuthenticator instance
        logger: Logger instance
    """

    def __init__(self, config: MahavishnuSettings) -> None:
        """Initialize authenticated Session-Buddy client.

        Args:
            config: Mahavishnu configuration
        """
        self.config = config
        self.authenticator = MessageAuthenticator(config)
        self.logger = __import__("logging").getLogger(__name__)

    async def send_authenticated_message(
        self, from_project: str, to_project: str, content: dict[str, Any]
    ) -> dict[str, Any]:
        """Send an authenticated message to Session Buddy.

        Args:
            from_project: Source project identifier
            to_project: Target project identifier
            content: Message content

        Returns:
            Result dictionary with status and message_id
        """
        try:
            # Create authenticated message
            authenticated_msg = self.authenticator.create_authenticated_message(
                from_project, to_project, content
            )

            # In a real implementation, this would send the message via HTTP API or MCP
            # For now, we'll simulate the sending process
            self.logger.info(f"Sending authenticated message from {from_project} to {to_project}")

            # Simulate sending the message
            # In a real implementation, this would be an actual API call
            result = {
                "status": "sent",
                "message_id": f"auth_msg_{hash(str(authenticated_msg))}",
                "timestamp": datetime.now().isoformat(),
            }

            return result
        except Exception as e:
            self.logger.error(f"Error sending authenticated message: {e}")
            return {"status": "error", "error": str(e)}

    async def receive_authenticated_message(
        self, received_message: dict[str, Any]
    ) -> dict[str, Any]:
        """Receive and verify an authenticated message from Session Buddy.

        Args:
            received_message: Received message dictionary with signature

        Returns:
            Result dictionary with validation status and content
        """
        try:
            # Verify the message
            is_valid, message_content = self.authenticator.verify_authenticated_message(
                received_message
            )

            if is_valid and message_content:
                self.logger.info(
                    f"Received valid authenticated message from {message_content.get('from_project')}"
                )

                return {
                    "status": "valid",
                    "content": message_content.get("content"),
                    "from_project": message_content.get("from_project"),
                    "to_project": message_content.get("to_project"),
                    "timestamp": message_content.get("timestamp"),
                }
            else:
                self.logger.warning("Received invalid authenticated message")

                return {"status": "invalid", "error": "Message signature verification failed"}
        except Exception as e:
            self.logger.error(f"Error receiving authenticated message: {e}")
            return {"status": "error", "error": str(e)}

    async def validate_project_access(
        self, requesting_project: str, target_project: str, action: str
    ) -> bool:
        """Validate if a project has access to perform an action on another project.

        Args:
            requesting_project: Project requesting access
            target_project: Target project to access
            action: Action to perform

        Returns:
            True if access is granted, False otherwise
        """
        # In a real implementation, this would check permissions in a database or configuration
        # For now, we'll implement a simple policy

        # Allow all projects to send messages to each other
        # In a real implementation, this would be more granular
        if action == "send_message":
            return True

        # Allow projects to access their own data
        return requesting_project == target_project


# Example usage and testing
async def test_cross_project_authentication() -> None:
    """Test the cross-project authentication functionality.

    This is a demonstration function showing how to use the authentication system.
    """
    from ..core.config import MahavishnuSettings

    # Create a mock config with auth secret
    config = MahavishnuSettings()
    config.cross_project_auth_secret = "very_secure_shared_secret_that_is_at_least_32_chars_long"

    # Initialize authenticator
    authenticator = MessageAuthenticator(config)

    # Test message signing and verification
    test_message = {
        "from_project": "mahavishnu",
        "to_project": "session_buddy",
        "content": {"type": "test", "data": "hello world"},
    }

    # Create authenticated message
    auth_msg = authenticator.create_authenticated_message(
        from_project="mahavishnu",
        to_project="session_buddy",
        content=test_message,
    )

    # Verify the message
    is_valid, payload = authenticator.verify_authenticated_message(auth_msg)

    if is_valid:
        print("✓ Authentication test passed")
        print(f"  Verified message: {payload}")
    else:
        print("✗ Authentication test failed")

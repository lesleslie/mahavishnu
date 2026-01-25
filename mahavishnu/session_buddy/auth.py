"""Cross-project authentication for Session Buddy integration."""
import json
import hmac
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import os
import asyncio

from ..core.config import MahavishnuSettings


class CrossProjectAuth:
    """Shared authentication for Session Buddy ↔ Mahavishnu communication."""
    
    def __init__(self, shared_secret: str):
        self.shared_secret = shared_secret
    
    def sign_message(self, message: dict) -> str:
        """HMAC-SHA256 signature for cross-project messages"""
        message_str = json.dumps(message, sort_keys=True)
        hmac_obj = hmac.new(
            self.shared_secret.encode(),
            message_str.encode(),
            hashlib.sha256
        )
        return hmac_obj.hexdigest()

    def verify_message(self, message: dict, signature: str) -> bool:
        """Verify message signature"""
        expected = self.sign_message(message)
        return hmac.compare_digest(expected, signature)


class MessageAuthenticator:
    """Handles authentication for cross-project messages."""
    
    def __init__(self, config: MahavishnuSettings):
        self.config = config
        self.auth_secret = getattr(config, 'cross_project_auth_secret', os.getenv('CROSS_PROJECT_AUTH_SECRET'))
        
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
    
    def create_authenticated_message(self, from_project: str, to_project: str, content: Dict[str, Any]) -> Dict[str, Any]:
        """Create an authenticated message for cross-project communication."""
        # Create the message payload
        message_payload = {
            "from_project": from_project,
            "to_project": to_project,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "nonce": f"{from_project}_{int(datetime.now().timestamp() * 1000000)}"  # Unique per message
        }
        
        # Sign the message
        signature = self.authenticator.sign_message(message_payload)
        
        # Return the authenticated message
        return {
            "message": message_payload,
            "signature": signature,
            "algorithm": "HMAC-SHA256"
        }
    
    def verify_authenticated_message(self, authenticated_message: Dict[str, Any]) -> tuple[bool, Optional[Dict[str, Any]]]:
        """Verify an authenticated message and return its content if valid."""
        try:
            message_payload = authenticated_message.get("message")
            signature = authenticated_message.get("signature")
            algorithm = authenticated_message.get("algorithm", "HMAC-SHA256")
            
            if not message_payload or not signature:
                return False, None
            
            if algorithm != "HMAC-SHA256":
                return False, None
            
            # Verify the signature
            is_valid = self.authenticator.verify_message(message_payload, signature)
            
            if is_valid:
                # Check if message is too old (replay attack prevention)
                timestamp_str = message_payload.get("timestamp")
                if timestamp_str:
                    try:
                        timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
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
        """Check if cross-project authentication is enabled."""
        return bool(self.auth_secret)


class AuthenticatedSessionBuddyClient:
    """Authenticated client for Session Buddy communication."""
    
    def __init__(self, config: MahavishnuSettings):
        self.config = config
        self.authenticator = MessageAuthenticator(config)
        self.logger = __import__('logging').getLogger(__name__)
    
    async def send_authenticated_message(self, from_project: str, to_project: str, content: Dict[str, Any]) -> Dict[str, Any]:
        """Send an authenticated message to Session Buddy."""
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
                "timestamp": datetime.now().isoformat()
            }
            
            return result
        except Exception as e:
            self.logger.error(f"Error sending authenticated message: {str(e)}")
            return {
                "status": "error",
                "error": str(e)
            }
    
    async def receive_authenticated_message(self, received_message: Dict[str, Any]) -> Dict[str, Any]:
        """Receive and verify an authenticated message from Session Buddy."""
        try:
            # Verify the message
            is_valid, message_content = self.authenticator.verify_authenticated_message(received_message)
            
            if is_valid:
                self.logger.info(f"Received valid authenticated message from {message_content.get('from_project')}")
                
                return {
                    "status": "valid",
                    "content": message_content.get("content"),
                    "from_project": message_content.get("from_project"),
                    "to_project": message_content.get("to_project"),
                    "timestamp": message_content.get("timestamp")
                }
            else:
                self.logger.warning("Received invalid authenticated message")
                
                return {
                    "status": "invalid",
                    "error": "Message signature verification failed"
                }
        except Exception as e:
            self.logger.error(f"Error receiving authenticated message: {str(e)}")
            return {
                "status": "error",
                "error": str(e)
            }
    
    async def validate_project_access(self, requesting_project: str, target_project: str, action: str) -> bool:
        """Validate if a project has access to perform an action on another project."""
        # In a real implementation, this would check permissions in a database or configuration
        # For now, we'll implement a simple policy
        
        # Allow all projects to send messages to each other
        # In a real implementation, this would be more granular
        if action == "send_message":
            return True
        
        # Allow projects to access their own data
        if requesting_project == target_project:
            return True
        
        # For other actions, implement more restrictive policies
        # This is where you'd check roles, permissions, etc.
        return False


# Example usage and testing
async def test_cross_project_authentication():
    """Test the cross-project authentication functionality."""
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
        "content": {"type": "test", "data": "hello world"}
    }
    
    # Create authenticated message
    auth_msg = authenticator.create_authenticated_message(
        "mahavishnu", "session_buddy", test_message["content"]
    )
    
    print("Original message:", test_message)
    print("Authenticated message:", auth_msg)
    
    # Verify the message
    is_valid, content = authenticator.verify_authenticated_message(auth_msg)
    print("Verification result:", is_valid)
    print("Verified content:", content)
    
    # Test with tampered message
    tampered_msg = auth_msg.copy()
    tampered_msg["message"]["content"]["data"] = "tampered data"
    is_valid_tampered, _ = authenticator.verify_authenticated_message(tampered_msg)
    print("Tampered message verification:", is_valid_tampered)
    
    # Test client
    client = AuthenticatedSessionBuddyClient(config)
    result = await client.send_authenticated_message(
        "mahavishnu", "session_buddy", {"test": "data"}
    )
    print("Send result:", result)


if __name__ == "__main__":
    asyncio.run(test_cross_project_authentication())
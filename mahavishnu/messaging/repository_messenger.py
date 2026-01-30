"""Repository messenger for inter-repository communication."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any
import uuid

from ..session_buddy.auth import CrossProjectAuth


class MessageType(Enum):
    """Types of messages that can be sent between repositories."""

    CODE_CHANGE_NOTIFICATION = "code_change_notification"
    WORKFLOW_STATUS_UPDATE = "workflow_status_update"
    QUALITY_ALERT = "quality_alert"
    DEPENDENCY_UPDATE = "dependency_update"
    SECURITY_SCAN_RESULT = "security_scan_result"
    CUSTOM = "custom"


class MessagePriority(Enum):
    """Priority levels for messages."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class RepositoryMessage:
    """Structure for a message between repositories."""

    id: str
    sender_repo: str
    receiver_repo: str
    message_type: MessageType
    content: dict[str, Any]
    priority: MessagePriority = MessagePriority.NORMAL
    timestamp: datetime = None
    correlation_id: str | None = None  # For tracking related messages
    expires_at: datetime | None = None  # Optional expiration time
    signature: str | None = None  # For authentication

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
        if self.correlation_id is None:
            self.correlation_id = str(uuid.uuid4())


class RepositoryMessenger:
    """Manages messaging between repositories."""

    def __init__(self, app):
        self.app = app
        self.logger = __import__("logging").getLogger(__name__)
        self.messages: list[RepositoryMessage] = []
        self.subscribers: dict[str, list[callable]] = {}  # repo -> list of callbacks
        self.authenticator: CrossProjectAuth | None = None

        # Initialize authenticator if cross-project auth is configured
        auth_secret = getattr(app.config, "cross_project_auth_secret", None)
        if auth_secret:
            self.authenticator = CrossProjectAuth(auth_secret)

    def subscribe(self, repo_name: str, callback: callable):
        """Subscribe to messages for a specific repository."""
        if repo_name not in self.subscribers:
            self.subscribers[repo_name] = []
        self.subscribers[repo_name].append(callback)
        self.logger.info(f"Subscribed to messages for repository: {repo_name}")

    def unsubscribe(self, repo_name: str, callback: callable):
        """Unsubscribe from messages for a specific repository."""
        if repo_name in self.subscribers and callback in self.subscribers[repo_name]:
            self.subscribers[repo_name].remove(callback)
            self.logger.info(f"Unsubscribed from messages for repository: {repo_name}")

    async def send_message(
        self,
        sender_repo: str,
        receiver_repo: str,
        message_type: MessageType,
        content: dict[str, Any],
        priority: MessagePriority = MessagePriority.NORMAL,
        correlation_id: str | None = None,
    ) -> RepositoryMessage:
        """Send a message from one repository to another."""
        try:
            # Create message ID
            message_id = f"msg_{uuid.uuid4().hex[:12]}"

            # Create the message
            message = RepositoryMessage(
                id=message_id,
                sender_repo=sender_repo,
                receiver_repo=receiver_repo,
                message_type=message_type,
                content=content,
                priority=priority,
                correlation_id=correlation_id,
            )

            # Add authentication signature if authenticator is available
            if self.authenticator:
                message.signature = self.authenticator.sign_message(
                    {
                        "id": message.id,
                        "sender_repo": message.sender_repo,
                        "receiver_repo": message.receiver_repo,
                        "message_type": message.message_type.value,
                        "content": message.content,
                        "timestamp": message.timestamp.isoformat(),
                        "correlation_id": message.correlation_id,
                    }
                )

            # Store the message
            self.messages.append(message)

            # Notify subscribers
            await self._notify_subscribers(message)

            self.logger.info(
                f"Message sent from {sender_repo} to {receiver_repo}: {message_type.value}"
            )

            return message
        except Exception as e:
            self.logger.error(f"Error sending message: {e}")
            raise

    async def _notify_subscribers(self, message: RepositoryMessage):
        """Notify subscribers of a new message."""
        # Notify the receiver's subscribers
        if message.receiver_repo in self.subscribers:
            for callback in self.subscribers[message.receiver_repo]:
                try:
                    await callback(message)
                except Exception as e:
                    self.logger.error(f"Error in subscriber callback: {e}")

        # Also notify wildcard subscribers (those interested in all messages)
        if "*" in self.subscribers:
            for callback in self.subscribers["*"]:
                try:
                    await callback(message)
                except Exception as e:
                    self.logger.error(f"Error in wildcard subscriber callback: {e}")

    async def get_messages_for_repo(
        self,
        repo_name: str,
        message_type: MessageType | None = None,
        limit: int = 50,
        since: datetime | None = None,
    ) -> list[RepositoryMessage]:
        """Get messages for a specific repository."""
        try:
            # Filter messages for the specified repository
            repo_messages = [
                msg
                for msg in self.messages
                if msg.receiver_repo == repo_name
                and (message_type is None or msg.message_type == message_type)
                and (since is None or msg.timestamp >= since)
            ]

            # Sort by timestamp (newest first)
            repo_messages.sort(key=lambda x: x.timestamp, reverse=True)

            # Return limited results
            return repo_messages[:limit]
        except Exception as e:
            self.logger.error(f"Error getting messages for repo {repo_name}: {e}")
            return []

    async def broadcast_message(
        self,
        sender_repo: str,
        message_type: MessageType,
        content: dict[str, Any],
        target_repos: list[str] | None = None,
        priority: MessagePriority = MessagePriority.NORMAL,
    ) -> list[RepositoryMessage]:
        """Broadcast a message to multiple repositories."""
        try:
            # If no specific targets, send to all configured repositories
            if target_repos is None:
                target_repos = self.app.get_repos()

            sent_messages = []
            for repo in target_repos:
                if repo != sender_repo:  # Don't send to self
                    message = await self.send_message(
                        sender_repo=sender_repo,
                        receiver_repo=repo,
                        message_type=message_type,
                        content=content,
                        priority=priority,
                    )
                    sent_messages.append(message)

            self.logger.info(
                f"Broadcast message from {sender_repo} to {len(sent_messages)} repositories"
            )
            return sent_messages
        except Exception as e:
            self.logger.error(f"Error broadcasting message: {e}")
            raise

    async def acknowledge_message(self, message_id: str, receiver_repo: str) -> bool:
        """Acknowledge receipt of a message."""
        try:
            # In a real implementation, this would update the message status
            # For now, we'll just log the acknowledgment
            self.logger.info(f"Message {message_id} acknowledged by {receiver_repo}")
            return True
        except Exception as e:
            self.logger.error(f"Error acknowledging message {message_id}: {e}")
            return False

    async def get_unacknowledged_messages(self, repo_name: str) -> list[RepositoryMessage]:
        """Get messages that haven't been acknowledged by a repository."""
        # In a real implementation, this would check a database of acknowledgments
        # For now, return all messages for the repository
        return await self.get_messages_for_repo(repo_name)

    async def cleanup_expired_messages(self):
        """Remove expired messages from the queue."""
        try:
            current_time = datetime.now()
            expired_count = 0

            # Remove expired messages
            self.messages = [
                msg
                for msg in self.messages
                if msg.expires_at is None or msg.expires_at > current_time
            ]

            expired_count = len(
                [msg for msg in self.messages if msg.expires_at and msg.expires_at <= current_time]
            )

            if expired_count > 0:
                self.logger.info(f"Cleaned up {expired_count} expired messages")
        except Exception as e:
            self.logger.error(f"Error cleaning up expired messages: {e}")

    async def verify_message_signature(self, message: RepositoryMessage) -> bool:
        """Verify the signature of an incoming message."""
        if not self.authenticator or not message.signature:
            # If no authenticator or signature, return True for backward compatibility
            return True

        # Create the message payload to verify
        payload = {
            "id": message.id,
            "sender_repo": message.sender_repo,
            "receiver_repo": message.receiver_repo,
            "message_type": message.message_type.value,
            "content": message.content,
            "timestamp": message.timestamp.isoformat(),
            "correlation_id": message.correlation_id,
        }

        return self.authenticator.verify_message(payload, message.signature)


class RepositoryMessengerManager:
    """Manager for repository messenger functionality."""

    def __init__(self, app):
        self.app = app
        self.messenger = RepositoryMessenger(app)
        self.logger = __import__("logging").getLogger(__name__)

    async def process_repository_changes(
        self, repo_path: str, changes: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Process repository changes and notify other repositories."""
        try:
            # Create a notification message about the changes
            content = {
                "repo_path": repo_path,
                "changes": changes,
                "timestamp": datetime.now().isoformat(),
                "change_count": len(changes),
            }

            # Broadcast the change notification to other repositories
            messages = await self.messenger.broadcast_message(
                sender_repo=repo_path,
                message_type=MessageType.CODE_CHANGE_NOTIFICATION,
                content=content,
            )

            return {
                "status": "success",
                "messages_sent": len(messages),
                "changes_notified": len(changes),
            }
        except Exception as e:
            self.logger.error(f"Error processing repository changes: {e}")
            return {"status": "error", "error": str(e)}

    async def notify_workflow_status(
        self, workflow_id: str, status: str, repo_path: str, target_repos: list[str] = None
    ) -> dict[str, Any]:
        """Notify other repositories about workflow status changes."""
        try:
            content = {
                "workflow_id": workflow_id,
                "status": status,
                "repo_path": repo_path,
                "timestamp": datetime.now().isoformat(),
            }

            # Send status update to target repositories
            if target_repos:
                messages = []
                for target_repo in target_repos:
                    if target_repo != repo_path:
                        message = await self.messenger.send_message(
                            sender_repo=repo_path,
                            receiver_repo=target_repo,
                            message_type=MessageType.WORKFLOW_STATUS_UPDATE,
                            content=content,
                        )
                        messages.append(message)
            else:
                # Broadcast to all repositories
                messages = await self.messenger.broadcast_message(
                    sender_repo=repo_path,
                    message_type=MessageType.WORKFLOW_STATUS_UPDATE,
                    content=content,
                )

            return {
                "status": "success",
                "messages_sent": len(messages),
                "workflow_id": workflow_id,
                "workflow_status": status,
            }
        except Exception as e:
            self.logger.error(f"Error notifying workflow status: {e}")
            return {"status": "error", "error": str(e)}

    async def send_quality_alert(
        self, repo_path: str, alert_type: str, description: str, severity: str = "medium"
    ) -> dict[str, Any]:
        """Send a quality alert to other repositories."""
        try:
            content = {
                "repo_path": repo_path,
                "alert_type": alert_type,
                "description": description,
                "severity": severity,
                "timestamp": datetime.now().isoformat(),
            }

            # Broadcast quality alert
            messages = await self.messenger.broadcast_message(
                sender_repo=repo_path,
                message_type=MessageType.QUALITY_ALERT,
                content=content,
                priority=MessagePriority.HIGH
                if severity.lower() in ("high", "critical")
                else MessagePriority.NORMAL,
            )

            return {
                "status": "success",
                "messages_sent": len(messages),
                "alert_type": alert_type,
                "severity": severity,
            }
        except Exception as e:
            self.logger.error(f"Error sending quality alert: {e}")
            return {"status": "error", "error": str(e)}

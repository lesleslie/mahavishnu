"""MCP tools for repository messaging."""

from datetime import datetime
from typing import Any

from ...messaging.repository_messenger import (
    MessagePriority,
    MessageType,
    RepositoryMessengerManager,
)


def register_repository_messaging_tools(server, app, mcp_client):
    """Register repository messaging tools with the MCP server."""

    # Initialize the repository messenger manager
    messenger_manager = RepositoryMessengerManager(app)

    @server.tool()
    async def send_repository_message(
        sender_repo: str,
        receiver_repo: str,
        message_type: str,
        content: dict[str, Any],
        priority: str = "NORMAL",
    ) -> dict[str, Any]:
        """Send a message from one repository to another.

        Args:
            sender_repo: Repository sending the message
            receiver_repo: Repository receiving the message
            message_type: Type of message (CODE_CHANGE_NOTIFICATION, WORKFLOW_STATUS_UPDATE, etc.)
            content: Message content as a dictionary
            priority: Message priority (LOW, NORMAL, HIGH, CRITICAL)

        Returns:
            Status of the message sending operation
        """
        try:
            # Validate message type
            try:
                msg_type = MessageType(message_type.upper())
            except ValueError:
                return {
                    "status": "error",
                    "error": f"Invalid message type: {message_type}. Valid types: {[mt.value for mt in MessageType]}",
                }

            # Validate priority
            try:
                priority_enum = MessagePriority(priority.upper())
            except ValueError:
                return {
                    "status": "error",
                    "error": f"Invalid priority: {priority}. Valid priorities: {[mp.value for mp in MessagePriority]}",
                }

            # Send the message
            message = await messenger_manager.messenger.send_message(
                sender_repo=sender_repo,
                receiver_repo=receiver_repo,
                message_type=msg_type,
                content=content,
                priority=priority_enum,
            )

            return {
                "status": "success",
                "message_id": message.id,
                "sent_at": message.timestamp.isoformat(),
                "priority": message.priority.value,
            }
        except Exception as e:
            return {"status": "error", "error": f"Failed to send repository message: {str(e)}"}

    @server.tool()
    async def broadcast_repository_message(
        sender_repo: str,
        message_type: str,
        content: dict[str, Any],
        target_repos: list[str] | None = None,
        priority: str = "NORMAL",
    ) -> dict[str, Any]:
        """Broadcast a message to multiple repositories.

        Args:
            sender_repo: Repository sending the message
            message_type: Type of message (CODE_CHANGE_NOTIFICATION, WORKFLOW_STATUS_UPDATE, etc.)
            content: Message content as a dictionary
            target_repos: List of repositories to send to (None = all repositories)
            priority: Message priority (LOW, NORMAL, HIGH, CRITICAL)

        Returns:
            Status of the broadcast operation
        """
        try:
            # Validate message type
            try:
                msg_type = MessageType(message_type.upper())
            except ValueError:
                return {
                    "status": "error",
                    "error": f"Invalid message type: {message_type}. Valid types: {[mt.value for mt in MessageType]}",
                }

            # Validate priority
            try:
                priority_enum = MessagePriority(priority.upper())
            except ValueError:
                return {
                    "status": "error",
                    "error": f"Invalid priority: {priority}. Valid priorities: {[mp.value for mp in MessagePriority]}",
                }

            # Broadcast the message
            messages = await messenger_manager.messenger.broadcast_message(
                sender_repo=sender_repo,
                message_type=msg_type,
                content=content,
                target_repos=target_repos,
                priority=priority_enum,
            )

            return {
                "status": "success",
                "messages_sent": len(messages),
                "message_ids": [msg.id for msg in messages],
                "target_repos": target_repos or app.get_repos(),
            }
        except Exception as e:
            return {"status": "error", "error": f"Failed to broadcast repository message: {str(e)}"}

    @server.tool()
    async def get_repository_messages(
        receiver_repo: str,
        message_type: str | None = None,
        limit: int = 50,
        since: str | None = None,
    ) -> dict[str, Any]:
        """Get messages for a specific repository.

        Args:
            receiver_repo: Repository to get messages for
            message_type: Optional message type to filter by
            limit: Maximum number of messages to return
            since: Optional ISO format datetime string to filter messages from

        Returns:
            List of messages for the repository
        """
        try:
            # Parse message type if provided
            msg_type = None
            if message_type:
                try:
                    msg_type = MessageType(message_type.upper())
                except ValueError:
                    return {
                        "status": "error",
                        "error": f"Invalid message type: {message_type}. Valid types: {[mt.value for mt in MessageType]}",
                    }

            # Parse since datetime if provided
            since_dt = None
            if since:
                try:
                    since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
                except ValueError:
                    return {
                        "status": "error",
                        "error": f"Invalid datetime format for 'since': {since}. Use ISO format.",
                    }

            # Get messages
            messages = await messenger_manager.messenger.get_messages_for_repo(
                repo_name=receiver_repo, message_type=msg_type, limit=limit, since=since_dt
            )

            return {
                "status": "success",
                "messages": [
                    {
                        "id": msg.id,
                        "sender_repo": msg.sender_repo,
                        "receiver_repo": msg.receiver_repo,
                        "message_type": msg.message_type.value,
                        "content": msg.content,
                        "priority": msg.priority.value,
                        "timestamp": msg.timestamp.isoformat(),
                        "correlation_id": msg.correlation_id,
                    }
                    for msg in messages
                ],
                "count": len(messages),
            }
        except Exception as e:
            return {"status": "error", "error": f"Failed to get repository messages: {str(e)}"}

    @server.tool()
    async def acknowledge_repository_message(message_id: str, receiver_repo: str) -> dict[str, Any]:
        """Acknowledge receipt of a message.

        Args:
            message_id: ID of the message to acknowledge
            receiver_repo: Repository acknowledging the message

        Returns:
            Status of the acknowledgment
        """
        try:
            success = await messenger_manager.messenger.acknowledge_message(
                message_id, receiver_repo
            )

            return {
                "status": "success" if success else "error",
                "message_id": message_id,
                "acknowledged_by": receiver_repo,
                "success": success,
            }
        except Exception as e:
            return {
                "status": "error",
                "error": f"Failed to acknowledge repository message: {str(e)}",
            }

    @server.tool()
    async def notify_repository_changes(
        repo_path: str, changes: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Notify other repositories about changes in a repository.

        Args:
            repo_path: Path of the repository with changes
            changes: List of changes to notify about

        Returns:
            Status of the notification operation
        """
        try:
            result = await messenger_manager.process_repository_changes(repo_path, changes)

            return {
                "status": result["status"],
                "messages_sent": result.get("messages_sent", 0),
                "changes_notified": result.get("changes_notified", 0),
            }
        except Exception as e:
            return {"status": "error", "error": f"Failed to notify repository changes: {str(e)}"}

    @server.tool()
    async def notify_workflow_status(
        workflow_id: str, status: str, repo_path: str, target_repos: list[str] | None = None
    ) -> dict[str, Any]:
        """Notify other repositories about workflow status changes.

        Args:
            workflow_id: ID of the workflow
            status: New status of the workflow
            repo_path: Repository where workflow is running
            target_repos: Optional list of target repositories (None = all)

        Returns:
            Status of the notification operation
        """
        try:
            result = await messenger_manager.notify_workflow_status(
                workflow_id, status, repo_path, target_repos
            )

            return {
                "status": result["status"],
                "messages_sent": result.get("messages_sent", 0),
                "workflow_id": workflow_id,
            }
        except Exception as e:
            return {"status": "error", "error": f"Failed to notify workflow status: {str(e)}"}

    @server.tool()
    async def send_quality_alert(
        repo_path: str, alert_type: str, description: str, severity: str = "medium"
    ) -> dict[str, Any]:
        """Send a quality alert to other repositories.

        Args:
            repo_path: Repository sending the alert
            alert_type: Type of quality alert
            description: Description of the quality issue
            severity: Severity level (low, medium, high, critical)

        Returns:
            Status of the alert sending operation
        """
        try:
            result = await messenger_manager.send_quality_alert(
                repo_path, alert_type, description, severity
            )

            return {
                "status": result["status"],
                "messages_sent": result.get("messages_sent", 0),
                "alert_type": alert_type,
                "severity": severity,
            }
        except Exception as e:
            return {"status": "error", "error": f"Failed to send quality alert: {str(e)}"}

    print("✅ Registered 7 repository messaging tools with MCP server")

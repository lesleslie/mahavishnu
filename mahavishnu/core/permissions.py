"""Permissions and RBAC module for Mahavishnu."""

from datetime import datetime, timedelta, timezone

UTC = timezone.utc
from enum import Enum

import jwt
from pydantic import BaseModel

from .config import MahavishnuSettings
from .errors import ConfigurationError


class Permission(str, Enum):
    READ_REPO = "read_repo"
    WRITE_REPO = "write_repo"
    EXECUTE_WORKFLOW = "execute_workflow"
    MANAGE_WORKFLOWS = "manage_workflows"
    LIST_WORKFLOWS = "list_workflows"
    VIEW_WORKFLOW_STATUS = "view_workflow_status"
    CANCEL_WORKFLOW = "cancel_workflow"
    READ_ADAPTERS = "read_adapters"
    MANAGE_TERMINALS = "manage_terminals"


class Role(BaseModel):
    name: str
    permissions: list[Permission]
    allowed_repos: list[str] | None = None  # None = all repos


class User(BaseModel):
    user_id: str
    roles: list[Role]
    email: str | None = None
    name: str | None = None
    created_at: datetime = datetime.now()


class RBACManager:
    """Role-Based Access Control manager for Mahavishnu."""

    def __init__(self, config: MahavishnuSettings):
        self.config = config
        self.users: dict[str, User] = {}
        self.roles: dict[str, Role] = {}

        # Initialize default roles
        self._init_default_roles()

    def _init_default_roles(self):
        """Initialize default roles for the system."""
        # Admin role - full access
        admin_role = Role(
            name="admin",
            permissions=list(Permission),
            allowed_repos=None,  # All repos
        )
        self.roles["admin"] = admin_role

        # Developer role - limited access
        developer_role = Role(
            name="developer",
            permissions=[
                Permission.READ_REPO,
                Permission.EXECUTE_WORKFLOW,
                Permission.LIST_WORKFLOWS,
                Permission.VIEW_WORKFLOW_STATUS,
            ],
            allowed_repos=[],  # Will be set per user
        )
        self.roles["developer"] = developer_role

        # Viewer role - read-only access
        viewer_role = Role(
            name="viewer",
            permissions=[
                Permission.READ_REPO,
                Permission.LIST_WORKFLOWS,
                Permission.VIEW_WORKFLOW_STATUS,
            ],
            allowed_repos=[],
        )
        self.roles["viewer"] = viewer_role

    async def create_user(
        self, user_id: str, roles: list[str], allowed_repos: list[str] | None = None
    ) -> User:
        """Create a new user with specified roles."""
        role_objects = []
        for role_name in roles:
            if role_name in self.roles:
                # Create a copy of the role with user-specific repo permissions
                role_copy = self.roles[role_name].copy()
                role_copy.allowed_repos = allowed_repos
                role_objects.append(role_copy)

        user = User(user_id=user_id, roles=role_objects)
        self.users[user_id] = user
        return user

    async def check_permission(self, user_id: str, repo: str, permission: Permission) -> bool:
        """Check if user has permission for repo."""
        if user_id not in self.users:
            return False

        user = self.users[user_id]

        # Check if user has the required permission in any of their roles
        has_permission = False
        for role in user.roles:
            # If role allows all repos or user has access to this specific repo
            if permission in role.permissions and (
                role.allowed_repos is None or repo in role.allowed_repos
            ):
                has_permission = True
                break

        return has_permission

    async def get_user_permissions(self, user_id: str, repo: str) -> list[Permission]:
        """Get all permissions for a user on a specific repo."""
        if user_id not in self.users:
            return []

        user = self.users[user_id]
        permissions = set()

        for role in user.roles:
            # If role allows all repos or user has access to this specific repo
            if role.allowed_repos is None or repo in role.allowed_repos:
                permissions.update(role.permissions)

        return list(permissions)

    async def filter_repos_by_permission(self, user_id: str, permission: Permission) -> list[str]:
        """Get all repos a user has a specific permission for."""
        if user_id not in self.users:
            return []

        user = self.users[user_id]
        repos = set()

        for role in user.roles:
            if permission in role.permissions:
                if role.allowed_repos is None:
                    # This is a special case - we can't return "all repos" without knowing the full repo list
                    # In practice, this would need to be handled differently
                    continue
                else:
                    repos.update(role.allowed_repos)

        return list(repos)


class JWTManager:
    """JWT token management for authentication."""

    # Minimum entropy requirements for JWT secrets
    MIN_SECRET_LENGTH = 32  # characters

    def __init__(self, config: MahavishnuSettings):
        self.config = config

        # Critical security: Never use hardcoded secrets
        if not config.auth_secret:
            raise ConfigurationError(
                "MAHAVISHNU_AUTH_SECRET environment variable must be set. "
                "Generate a secure secret with: python -c 'import secrets; print(secrets.token_urlsafe(32))'"
            )

        # Validate minimum entropy (length check as proxy for entropy)
        if len(config.auth_secret) < self.MIN_SECRET_LENGTH:
            raise ConfigurationError(
                f"JWT secret must be at least {self.MIN_SECRET_LENGTH} characters long. "
                f"Current length: {len(config.auth_secret)} characters. "
                "Generate a secure secret with: python -c 'import secrets; print(secrets.token_urlsafe(32))'"
            )

        self.secret = config.auth_secret
        self.algorithm = config.auth_algorithm
        self.expire_minutes = config.auth_expire_minutes

    def create_token(self, user_id: str, additional_claims: dict = None) -> str:
        """Create a JWT token for a user."""
        payload = {
            "user_id": user_id,
            "exp": datetime.now(tz=UTC) + timedelta(minutes=self.expire_minutes),
            "iat": datetime.now(tz=UTC),
            "type": "access",
        }

        if additional_claims:
            payload.update(additional_claims)

        token = jwt.encode(payload, self.secret, algorithm=self.algorithm)
        return token

    def verify_token(self, token: str) -> dict:
        """Verify a JWT token and return the payload."""
        try:
            payload = jwt.decode(token, self.secret, algorithms=[self.algorithm])
            return payload
        except jwt.ExpiredSignatureError as e:
            raise ValueError("Token has expired") from e
        except jwt.InvalidTokenError as e:
            raise ValueError("Invalid token") from e

    def refresh_token(self, token: str) -> str:
        """Refresh an existing token."""
        payload = self.verify_token(token)
        # Remove exp to create fresh expiration
        if "exp" in payload:
            del payload["exp"]

        payload["exp"] = datetime.now(tz=UTC) + timedelta(minutes=self.expire_minutes)
        payload["refreshed_at"] = datetime.now(tz=UTC).isoformat()

        return jwt.encode(payload, self.secret, algorithm=self.algorithm)


class CrossProjectAuth:
    """Shared authentication for cross-project communication."""

    def __init__(self, shared_secret: str):
        self.shared_secret = shared_secret

    def sign_message(self, message: dict) -> str:
        """HMAC-SHA256 signature for cross-project messages"""
        import hashlib
        import hmac
        import json

        message_str = json.dumps(message, sort_keys=True)
        hmac_obj = hmac.new(self.shared_secret.encode(), message_str.encode(), hashlib.sha256)
        return hmac_obj.hexdigest()

    def verify_message(self, message: dict, signature: str) -> bool:
        """Verify message signature"""
        import hmac

        expected = self.sign_message(message)
        return hmac.compare_digest(expected, signature)

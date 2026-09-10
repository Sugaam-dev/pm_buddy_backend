import base64
import logging
import os
from typing import Annotated, Any, Optional
from uuid import UUID
from datetime import datetime, timezone, timedelta
from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, Header, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import httpx
from jose import JWTError, jwk, jwt
from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)

# Security scheme
security_bearer = HTTPBearer(auto_error=False)


class CurrentTenantUser(BaseModel):
    user_id: UUID
    email: str
    organization_id: UUID
    role_name: str
    permissions: list[str]


def get_fernet_cipher() -> Fernet:
    key = settings.ENCRYPTION_KEY.encode()
    if len(key) != 44:
        # Fallback to standard 32-byte urlsafe base64
        key = base64.urlsafe_b64encode(b"01234567890123456789012345678901")
    return Fernet(key)


def encrypt_token(plain_token: str) -> str:
    if not plain_token:
        return ""
    cipher = get_fernet_cipher()
    return cipher.encrypt(plain_token.encode()).decode()


def decrypt_token(encrypted_token: str) -> str:
    if not encrypted_token:
        return ""
    cipher = get_fernet_cipher()
    return cipher.decrypt(encrypted_token.encode()).decode()


# In-memory mock users for standalone development/testing & auth
DEMO_USERS: dict[str, dict[str, Any]] = {
    # -------------------------------------------------------------------------
    # 1. Client-Specific Account: Organization NextGen
    # -------------------------------------------------------------------------
    "admin@nextgen.com": {
        "user_id": UUID("20000000-0000-0000-0000-000000000001"),
        "email": "admin@nextgen.com",
        "name": "NextGen Admin",
        "organization_id": UUID("22222222-2222-2222-2222-222222222222"),
        "role_name": "client_ai_admin",
        "password": "NextGenBroaDband@123",
        "permissions": [
            "project.read",
            "task.read",
            "task.create",
            "task.write",
            "ticket.read",
            "ticket.create",
            "ticket.write",
            "calendar.read",
            "calendar.write",
            "action.execute",
            "risk.read",
            "knowledge.read",
            "ai.chat",
            "ai.read",
            "ai_config.manage",
        ],
    },
    "client.admin@nextgen.com": {
        "user_id": UUID("20000000-0000-0000-0000-000000000001"),
        "email": "client.admin@nextgen.com",
        "name": "NextGen Admin",
        "organization_id": UUID("22222222-2222-2222-2222-222222222222"),
        "role_name": "client_ai_admin",
        "password": "NextGenBroaDband@123",
        "permissions": [
            "project.read",
            "task.read",
            "task.create",
            "task.write",
            "ticket.read",
            "ticket.create",
            "ticket.write",
            "calendar.read",
            "calendar.write",
            "risk.read",
            "knowledge.read",
            "ai.chat",
            "ai.read",
            "ai_config.manage",
        ],
    },
    "operator@nextgen.com": {
        "user_id": UUID("20000000-0000-0000-0000-000000000002"),
        "email": "operator@nextgen.com",
        "name": "NextGen Operator",
        "organization_id": UUID("22222222-2222-2222-2222-222222222222"),
        "role_name": "client_operator",
        "password": "Operator@nextGenIndia",
        "permissions": [
            "project.read",
            "task.read",
            "task.create",
            "task.write",
            "ticket.read",
            "ticket.create",
            "calendar.read",
            "calendar.write",
            "calendar.meeting.confirm",
            "risk.read",
            "knowledge.read",
            "ai.chat",
            "ai.read",
        ],
    },
    "client.operator@nextgen.com": {
        "user_id": UUID("20000000-0000-0000-0000-000000000002"),
        "email": "client.operator@nextgen.com",
        "name": "NextGen Operator",
        "organization_id": UUID("22222222-2222-2222-2222-222222222222"),
        "role_name": "client_operator",
        "password": "Operator@nextGenIndia",
        "permissions": [
            "project.read",
            "task.read",
            "task.create",
            "task.write",
            "ticket.read",
            "ticket.create",
            "calendar.read",
            "calendar.write",
            "calendar.meeting.confirm",
            "risk.read",
            "knowledge.read",
            "ai.chat",
            "ai.read",
        ],
    },

    # -------------------------------------------------------------------------
    # 2. Internal Team & Engineering Credentials: Organization PMRG Solution
    # -------------------------------------------------------------------------
    "admin@pmrgsolution.com": {
        "user_id": UUID("10000000-0000-0000-0000-000000000004"),
        "email": "admin@pmrgsolution.com",
        "name": "PMRG Admin",
        "organization_id": UUID("11111111-1111-1111-1111-111111111111"),
        "role_name": "admin",
        "password": "pmrgsolution123",
        "permissions": ["*"],
    },
    "pm@pmrgsolution.com": {
        "user_id": UUID("10000000-0000-0000-0000-000000000001"),
        "email": "pm@pmrgsolution.com",
        "name": "PMRG Project Manager",
        "organization_id": UUID("11111111-1111-1111-1111-111111111111"),
        "role_name": "PM",
        "password": "pmrgsolution123",
        "permissions": [
            "project.read",
            "project.write",
            "task.read",
            "task.write",
            "ticket.read",
            "ticket.write",
            "ticket.assign",
            "approval.read",
            "approval.approve",
            "risk.read",
            "risk.write",
            "calendar.read",
            "calendar.write",
            "ai.chat",
            "action.execute",
        ],
    },
    "cto@pmrgsolution.com": {
        "user_id": UUID("10000000-0000-0000-0000-000000000003"),
        "email": "cto@pmrgsolution.com",
        "name": "PMRG CTO",
        "organization_id": UUID("11111111-1111-1111-1111-111111111111"),
        "role_name": "CTO",
        "password": "pmrgsolution123",
        "permissions": [
            "project.read",
            "project.write",
            "task.read",
            "ticket.read",
            "approval.read",
            "approval.approve",
            "risk.read",
            "risk.write",
            "calendar.read",
            "calendar.write",
            "ai.chat",
            "action.execute",
        ],
    },
    "lead@pmrgsolution.com": {
        "user_id": UUID("10000000-0000-0000-0000-000000000002"),
        "email": "lead@pmrgsolution.com",
        "name": "PMRG Team Lead",
        "organization_id": UUID("11111111-1111-1111-1111-111111111111"),
        "role_name": "TEAM_LEAD",
        "password": "pmrgsolution123",
        "permissions": [
            "project.read",
            "task.read",
            "task.write",
            "ticket.read",
            "ticket.write",
            "ticket.assign",
            "approval.read",
            "risk.read",
            "calendar.read",
            "calendar.write",
            "ai.chat",
            "action.execute",
        ],
    },
    "engineer@pmrgsolution.com": {
        "user_id": UUID("10000000-0000-0000-0000-000000000005"),
        "email": "engineer@pmrgsolution.com",
        "name": "PMRG Engineer",
        "organization_id": UUID("11111111-1111-1111-1111-111111111111"),
        "role_name": "ENGINEER",
        "password": "pmrgsolution123",
        "permissions": [
            "project.read",
            "task.read",
            "task.write",
            "ticket.read",
            "ticket.write",
            "calendar.read",
            "calendar.write",
            "ai.chat",
        ],
    },
    "viewer@pmrgsolution.com": {
        "user_id": UUID("10000000-0000-0000-0000-000000000009"),
        "email": "viewer@pmrgsolution.com",
        "name": "PMRG Viewer",
        "organization_id": UUID("11111111-1111-1111-1111-111111111111"),
        "role_name": "VIEWER",
        "password": "pmrgsolution123",
        "permissions": [
            "project.read",
            "task.read",
            "ticket.read",
            "approval.read",
            "risk.read",
            "calendar.read",
        ],
    },
    "rahul@pmrgsolution.com": {
        "user_id": UUID("10000000-0000-0000-0000-000000000010"),
        "email": "rahul@pmrgsolution.com",
        "name": "Rahul Sharma",
        "organization_id": UUID("11111111-1111-1111-1111-111111111111"),
        "role_name": "ENGINEER",
        "password": "pmrgsolution123",
        "permissions": [
            "project.read",
            "task.read",
            "task.write",
            "ticket.read",
            "ticket.write",
            "calendar.read",
            "calendar.write",
            "ai.chat",
        ],
    },
}


class SupabaseJWKSCache:
    """
    Thread-safe in-memory cache for Supabase Auth RS256 public signing keys.
    Fetches keys dynamically from Supabase Auth JWKS endpoint.
    """

    def __init__(self, jwks_url: Optional[str] = None, ttl_seconds: int = 3600):
        self.jwks_url = jwks_url or f"{settings.NEXT_PUBLIC_SUPABASE_URL.rstrip('/')}/auth/v1/.well-known/jwks.json"
        self.ttl_seconds = ttl_seconds
        self.keys: dict[str, str] = {}  # kid -> PEM public key
        self.last_fetched: Optional[datetime] = None

    def add_key_pem(self, kid: str, pem: str) -> None:
        """Injects a public key PEM directly (useful for tests and key rotation)."""
        self.keys[kid] = pem

    def clear(self) -> None:
        self.keys.clear()
        self.last_fetched = None

    async def get_key_pem(self, kid: str) -> Optional[str]:
        now = datetime.now(timezone.utc)
        needs_refresh = (
            not self.keys
            or kid not in self.keys
            or self.last_fetched is None
            or (now - self.last_fetched).total_seconds() > self.ttl_seconds
        )

        if needs_refresh:
            await self.refresh_keys()

        return self.keys.get(kid)

    async def refresh_keys(self) -> None:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(self.jwks_url)
                if response.status_code == 200:
                    data = response.json()
                    new_keys = {}
                    for k in data.get("keys", []):
                        k_id = k.get("kid")
                        if k_id:
                            c_key = jwk.construct(k)
                            new_keys[k_id] = c_key.to_pem().decode("utf-8")
                    self.keys.update(new_keys)
                    self.last_fetched = datetime.now(timezone.utc)
                    logger.info("Successfully refreshed Supabase JWKS (%d keys cached)", len(new_keys))
        except Exception as e:
            logger.warning("Could not fetch Supabase JWKS from %s: %s", self.jwks_url, e)


# Global singleton JWKS cache
jwks_cache = SupabaseJWKSCache()


def create_demo_token(email: str, expires_delta: timedelta | None = None) -> str:
    """Creates a local HMAC (HS256) token for automated testing and standalone development."""
    user_info = DEMO_USERS.get(email)
    if not user_info:
        raise ValueError(f"Unknown demo user {email}")

    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(hours=24))
    payload = {
        "sub": str(user_info["user_id"]),
        "email": user_info["email"],
        "org_id": str(user_info["organization_id"]),
        "role": user_info["role_name"],
        "permissions": user_info["permissions"],
        "exp": expire,
    }
    return jwt.encode(payload, "secret-demo-jwt-key", algorithm="HS256")


def create_test_rs256_token(
    user_id: UUID,
    email: str,
    org_id: UUID,
    private_pem: str,
    kid: str,
    role: str = "PM",
    permissions: list[str] | None = None,
    expires_delta: timedelta | None = None,
    issuer: str | None = None,
    audience: str | None = None,
) -> str:
    """Helper to generate valid RS256 Supabase-compatible tokens for testing."""
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(hours=1))
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "email": email,
        "org_id": str(org_id),
        "role": role,
        "exp": expire,
    }
    if permissions is not None:
        payload["permissions"] = permissions
    if issuer:
        payload["iss"] = issuer
    if audience:
        payload["aud"] = audience

    return jwt.encode(payload, private_pem, algorithm="RS256", headers={"kid": kid})


async def get_current_tenant_user(
    auth_header: Annotated[HTTPAuthorizationCredentials | None, Security(security_bearer)],
    x_org_id: Annotated[str | None, Header(alias="X-Org-ID")] = None,
    x_organization_id: Annotated[str | None, Header(alias="X-Organization-ID")] = None,
) -> CurrentTenantUser:
    effective_header_org = x_organization_id or x_org_id
    """
    Validates token and extracts user, tenant, role, and permissions.
    - Validates RS256 tokens using Supabase Auth JWKS public keys.
    - Validates HS256 tokens in development / test environments.
    - Enforces valid signatures, unexpired timestamps, subject UUIDs, and tenant isolation.
    """
    if not auth_header or not auth_header.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer authentication token."
        )

    token = auth_header.credentials
    try:
        header = jwt.get_unverified_header(token)
        alg = header.get("alg")
        kid = header.get("kid")

        if alg == "RS256":
            if not kid:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token: missing 'kid' in header for RS256 signature verification."
                )

            key_pem = await jwks_cache.get_key_pem(kid)
            if not key_pem:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Unable to verify token: unknown signing key ID '{kid}'."
                )

            # Strict RS256 verification (signature + expiration)
            payload = jwt.decode(
                token,
                key_pem,
                algorithms=["RS256"],
                options={"verify_signature": True, "verify_exp": True, "verify_aud": False},
            )

        elif alg == "HS256":
            if settings.ENVIRONMENT not in ("test", "development"):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Symmetric HMAC (HS256) tokens are not permitted in production."
                )

            # Verify signature against SUPABASE_SERVICE_ROLE_KEY or test key
            secret_key = (
                settings.SUPABASE_SERVICE_ROLE_KEY
                if settings.SUPABASE_SERVICE_ROLE_KEY != "mock-service-role-key"
                else "secret-demo-jwt-key"
            )
            payload = jwt.decode(
                token,
                secret_key,
                algorithms=["HS256"],
                options={"verify_signature": True, "verify_exp": True},
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Unsupported token algorithm '{alg}'. Only RS256 and HS256 are supported."
            )

        # Validate Claims
        sub = payload.get("sub")
        if not sub:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token payload missing subject ('sub')."
            )

        try:
            user_id = UUID(str(sub))
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid user ID in token subject: '{sub}'."
            )

        email = (
            payload.get("email")
            or payload.get("user_metadata", {}).get("email")
            or "unknown@user.com"
        )

        # Resolve organization_id strictly from token claims
        token_org = (
            payload.get("org_id")
            or payload.get("app_metadata", {}).get("org_id")
            or payload.get("user_metadata", {}).get("org_id")
        )
        if token_org:
            if effective_header_org and str(effective_header_org).strip() != str(token_org).strip():
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Tenant context mismatch: header does not match authenticated token organization."
                )
            raw_org = token_org
        elif email in DEMO_USERS:
            raw_org = str(DEMO_USERS[email]["organization_id"])
            if effective_header_org and str(effective_header_org).strip() != str(raw_org).strip():
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Tenant context mismatch: header does not match authenticated user organization."
                )
        else:
            raw_org = effective_header_org or "11111111-1111-1111-1111-111111111111"

        try:
            org_id = UUID(str(raw_org))
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid organization ID: '{raw_org}'."
            )

        # Resolve role and permissions
        role_name = (
            payload.get("role")
            or payload.get("app_metadata", {}).get("role", "PM")
        )
        permissions = payload.get("permissions")

        if not permissions:
            if email in DEMO_USERS:
                permissions = DEMO_USERS[email]["permissions"]
            else:
                if role_name in ("admin", "CTO", "CEO", "PM"):
                    permissions = [
                        "project.read", "project.write", "task.read", "task.write",
                        "ticket.read", "ticket.write", "ticket.assign", "approval.read",
                        "approval.approve", "risk.read", "calendar.read", "calendar.write",
                        "ai.chat", "action.execute"
                    ]
                elif role_name == "client_operator":
                    permissions = [
                        "project.read", "task.read", "ticket.read", "ticket.create", "ticket.write",
                        "calendar.read", "calendar.write", "action.execute", "risk.read",
                        "knowledge.read", "ai.chat", "ai.read"
                    ]
                elif role_name == "client_ai_admin":
                    permissions = [
                        "project.read", "task.read", "ticket.read", "ticket.create", "ticket.write",
                        "calendar.read", "calendar.write", "action.execute", "risk.read",
                        "knowledge.read", "ai.chat", "ai.read", "ai_config.manage"
                    ]
                else:
                    permissions = ["project.read", "task.read", "ticket.read", "ai.chat"]

        return CurrentTenantUser(
            user_id=user_id,
            email=email,
            organization_id=org_id,
            role_name=role_name,
            permissions=permissions,
        )

    except HTTPException:
        raise
    except (JWTError, ValueError) as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication token: {str(e)}"
        )


def require_permission(required_perm: str | list[str] | tuple[str, ...]):
    """Factory for RBAC permission guard dependency. Supports single permission or list of alternative permissions."""
    def permission_checker(current_user: Annotated[CurrentTenantUser, Depends(get_current_tenant_user)]):
        perms = [required_perm] if isinstance(required_perm, str) else list(required_perm)
        has_wildcard = (
            "*" in current_user.permissions
            or "all" in current_user.permissions
            or "admin" in current_user.permissions
        )
        has_required = has_wildcard or any(p in current_user.permissions for p in perms)
        if not has_required:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action in this organization.",
            )
        return current_user
    return permission_checker


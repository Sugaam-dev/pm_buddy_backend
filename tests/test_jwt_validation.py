import pytest
from datetime import timedelta
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from fastapi import HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials

from app.core.config import settings
from app.core.security import (
    CurrentTenantUser,
    create_demo_token,
    create_test_rs256_token,
    get_current_tenant_user,
    jwks_cache,
    require_permission,
)


@pytest.fixture(scope="module")
def rsa_keypair():
    """Generates an RSA 2048 key pair for RS256 JWT tests."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    return private_pem, public_pem


@pytest.fixture(autouse=True)
def clean_jwks_cache():
    """Clears JWKS cache between tests."""
    jwks_cache.clear()
    yield
    jwks_cache.clear()


@pytest.mark.asyncio
async def test_valid_rs256_token_validation(rsa_keypair):
    """Verifies that a valid RS256 token signed by Supabase Auth key parses correctly."""
    private_pem, public_pem = rsa_keypair
    kid = "supabase-test-key-1"
    jwks_cache.add_key_pem(kid, public_pem)

    user_id = uuid4()
    org_id = uuid4()
    email = "carol@acme.com"

    token = create_test_rs256_token(
        user_id=user_id,
        email=email,
        org_id=org_id,
        private_pem=private_pem,
        kid=kid,
        role="PM",
        permissions=["project.read", "task.read"],
    )

    auth = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    user = await get_current_tenant_user(auth_header=auth)

    assert isinstance(user, CurrentTenantUser)
    assert user.user_id == user_id
    assert user.organization_id == org_id
    assert user.email == email
    assert user.role_name == "PM"
    assert "project.read" in user.permissions


@pytest.mark.asyncio
async def test_forged_rs256_signature_rejected(rsa_keypair):
    """Verifies that an RS256 token signed with an untrusted private key is rejected with HTTP 401."""
    _, public_pem = rsa_keypair
    kid = "supabase-test-key-1"
    jwks_cache.add_key_pem(kid, public_pem)

    # Generate an attacker private key
    attacker_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    attacker_pem = attacker_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    forged_token = create_test_rs256_token(
        user_id=uuid4(),
        email="attacker@evil.com",
        org_id=uuid4(),
        private_pem=attacker_pem,
        kid=kid,
    )

    auth = HTTPAuthorizationCredentials(scheme="Bearer", credentials=forged_token)
    with pytest.raises(HTTPException) as exc_info:
        await get_current_tenant_user(auth_header=auth)

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Invalid authentication token" in exc_info.value.detail


@pytest.mark.asyncio
async def test_expired_rs256_token_rejected(rsa_keypair):
    """Verifies that an expired RS256 token is rejected with HTTP 401."""
    private_pem, public_pem = rsa_keypair
    kid = "supabase-test-key-1"
    jwks_cache.add_key_pem(kid, public_pem)

    expired_token = create_test_rs256_token(
        user_id=uuid4(),
        email="expired@acme.com",
        org_id=uuid4(),
        private_pem=private_pem,
        kid=kid,
        expires_delta=timedelta(seconds=-10),
    )

    auth = HTTPAuthorizationCredentials(scheme="Bearer", credentials=expired_token)
    with pytest.raises(HTTPException) as exc_info:
        await get_current_tenant_user(auth_header=auth)

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Signature has expired" in exc_info.value.detail or "expired" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_unknown_kid_rejected(rsa_keypair):
    """Verifies that an RS256 token referencing an unknown kid raises HTTP 401."""
    private_pem, _ = rsa_keypair
    token = create_test_rs256_token(
        user_id=uuid4(),
        email="unknown_kid@acme.com",
        org_id=uuid4(),
        private_pem=private_pem,
        kid="non-existent-kid",
    )

    auth = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    with pytest.raises(HTTPException) as exc_info:
        await get_current_tenant_user(auth_header=auth)

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert "unknown signing key" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_missing_bearer_token_rejected():
    """Verifies that missing authentication credentials returns HTTP 401."""
    with pytest.raises(HTTPException) as exc_info:
        await get_current_tenant_user(auth_header=None)

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Missing Bearer authentication token" in exc_info.value.detail


@pytest.mark.asyncio
async def test_hs256_rejected_in_production(rsa_keypair):
    """Verifies that symmetric HMAC HS256 tokens are strictly rejected when ENVIRONMENT=production."""
    demo_token = create_demo_token("alice@acme.com")
    auth = HTTPAuthorizationCredentials(scheme="Bearer", credentials=demo_token)

    original_env = settings.ENVIRONMENT
    try:
        settings.ENVIRONMENT = "production"
        with pytest.raises(HTTPException) as exc_info:
            await get_current_tenant_user(auth_header=auth)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert "not permitted in production" in exc_info.value.detail
    finally:
        settings.ENVIRONMENT = original_env


@pytest.mark.asyncio
async def test_require_permission_guard():
    """Verifies that require_permission enforces permission checks."""
    user = CurrentTenantUser(
        user_id=uuid4(),
        email="user@acme.com",
        organization_id=uuid4(),
        role_name="ENGINEER",
        permissions=["project.read", "task.read"],
    )

    # Allowed permission
    checker_read = require_permission("project.read")
    assert checker_read(current_user=user) == user

    # Denied permission
    checker_write = require_permission("project.write")
    with pytest.raises(HTTPException) as exc_info:
        checker_write(current_user=user)

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

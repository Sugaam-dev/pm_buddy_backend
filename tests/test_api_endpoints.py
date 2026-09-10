import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_health_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_auth_login_and_me():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Login with demo user
        login_res = await client.post("/api/v1/auth/login", json={"email": "pm@pmrgsolution.com", "password": "pmrgsolution123"})
        assert login_res.status_code == 200
        token_data = login_res.json()
        assert "access_token" in token_data
        token = token_data["access_token"]

        # 2. Get me profile
        me_res = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert me_res.status_code == 200
        me_data = me_res.json()
        assert me_data["email"] == "pm@pmrgsolution.com"
        assert me_data["role"] == "PM"
        assert "project.read" in me_data["permissions"]


@pytest.mark.asyncio
async def test_auth_signup():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Signup with new user
        signup_res = await client.post("/api/v1/auth/signup", json={
            "name": "New Developer",
            "email": "developer.test@acme.com",
            "password": "Password123!",
        })
        assert signup_res.status_code == 201
        data = signup_res.json()
        assert "access_token" in data
        assert data["user"]["role"] == "VIEWER"
        assert "admin" not in data["user"]["permissions"]
        assert "*" not in data["user"]["permissions"]

        # 2. Duplicate signup should be rejected
        dup_res = await client.post("/api/v1/auth/signup", json={
            "name": "Duplicate Developer",
            "email": "developer.test@acme.com",
            "password": "Password123!",
        })
        assert dup_res.status_code == 400

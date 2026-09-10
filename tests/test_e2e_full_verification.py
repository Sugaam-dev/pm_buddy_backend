import pytest
import httpx
from uuid import uuid4

FRONTEND_URL = "http://localhost:3000"
BACKEND_URL = "http://localhost:8000"


@pytest.mark.asyncio
async def test_e2e_public_landing_page_content():
    """Verify Landing page content, branding, logo, and CTAs."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        res = await client.get(f"{FRONTEND_URL}/")
        assert res.status_code == 200
        html = res.text

        # Company branding
        assert "PMRG Solution LLP" in html
        assert "PM BUDDY" in html
        assert "/pmrg-logo.png" in html

        # Hero content
        assert "AI-Native Operational Intelligence for Engineering Teams" in html
        assert "PM Buddy helps engineering organizations understand what needs attention" in html

        # Sections
        assert "ai proposes. humans confirm." in html.lower()
        assert "Get Started" in html
        assert "Sign In" in html


@pytest.mark.asyncio
async def test_e2e_login_and_signup_page_content():
    """Verify login and signup pages render properly."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        login_res = await client.get(f"{FRONTEND_URL}/login")
        assert login_res.status_code == 200
        assert "PM Buddy" in login_res.text or "PM BUDDY" in login_res.text
        assert "PMRG" in login_res.text or "pmrg" in login_res.text or "Authentication" in login_res.text

        signup_res = await client.get(f"{FRONTEND_URL}/signup")
        assert signup_res.status_code == 200
        assert "Create your account" in signup_res.text or "Viewer" in signup_res.text


@pytest.mark.asyncio
async def test_e2e_403_access_restricted_page():
    """Verify 403 Access Restricted page renders correctly."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        res = await client.get(f"{FRONTEND_URL}/403")
        assert res.status_code == 200
        assert "Access Restricted" in res.text
        assert "Return to Dashboard" in res.text


@pytest.mark.asyncio
async def test_e2e_signup_api_and_role_assignment():
    """Test public signup API: provisions default non-privileged role and rejects duplicates."""
    test_email = f"test.engineer.{uuid4().hex[:6]}@acme.com"
    async with httpx.AsyncClient(timeout=10.0) as client:
        # 1. Valid Signup
        signup_res = await client.post(
            f"{BACKEND_URL}/api/v1/auth/signup",
            json={
                "name": "Alex E2E Tester",
                "email": test_email,
                "password": "Password123!",
            },
        )
        assert signup_res.status_code == 201
        data = signup_res.json()
        assert "access_token" in data
        assert data["user"]["email"] == test_email
        # CRITICAL SECURITY RULE: must be VIEWER default, not privileged
        assert data["user"]["role"] == "VIEWER"
        assert "*" not in data["user"]["permissions"]
        assert "admin" not in data["user"]["permissions"]

        # 2. Duplicate Signup rejection
        dup_res = await client.post(
            f"{BACKEND_URL}/api/v1/auth/signup",
            json={
                "name": "Duplicate Tester",
                "email": test_email,
                "password": "Password123!",
            },
        )
        assert dup_res.status_code == 400


@pytest.mark.asyncio
async def test_e2e_all_roles_authentication():
    """Test login across all roles in PMRG Solution and NextGen."""
    roles_to_test = [
        ("admin@pmrgsolution.com", "admin", "pmrgsolution123"),
        ("pm@pmrgsolution.com", "PM", "pmrgsolution123"),
        ("cto@pmrgsolution.com", "CTO", "pmrgsolution123"),
        ("lead@pmrgsolution.com", "TEAM_LEAD", "pmrgsolution123"),
        ("engineer@pmrgsolution.com", "ENGINEER", "pmrgsolution123"),
        ("viewer@pmrgsolution.com", "VIEWER", "pmrgsolution123"),
        ("admin@nextgen.com", "client_ai_admin", "NextGenBroaDband@123"),
        ("client.admin@nextgen.com", "client_ai_admin", "NextGenBroaDband@123"),
    ]

    async with httpx.AsyncClient(timeout=10.0) as client:
        for email, expected_role, pwd in roles_to_test:
            res = await client.post(
                f"{BACKEND_URL}/api/v1/auth/login",
                json={"email": email, "password": pwd},
            )
            assert res.status_code == 200
            data = res.json()
            assert "access_token" in data
            assert data["user"]["role"] == expected_role


@pytest.mark.asyncio
async def test_e2e_rbac_direct_api_enforcement():
    """Verify that backend permissions are strictly enforced on direct calls."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        # Viewer Login
        viewer_login = await client.post(
            f"{BACKEND_URL}/api/v1/auth/login",
            json={"email": "viewer@pmrgsolution.com", "password": "pmrgsolution123"},
        )
        viewer_token = viewer_login.json()["access_token"]

        # Viewer is forbidden from creating meetings (calendar.write)
        write_res = await client.post(
            f"{BACKEND_URL}/api/v1/calendar/events",
            json={
                "title": "Unauthorized Meeting",
                "start_time": "2026-09-08T10:00:00Z",
                "end_time": "2026-09-08T10:30:00Z",
                "attendees": ["viewer@pmrgsolution.com"],
            },
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
        assert write_res.status_code == 403

        # Engineer Login
        engineer_login = await client.post(
            f"{BACKEND_URL}/api/v1/auth/login",
            json={"email": "engineer@pmrgsolution.com", "password": "pmrgsolution123"},
        )
        engineer_token = engineer_login.json()["access_token"]

        # Engineer is forbidden from ticket reassignment (ticket.assign)
        assign_res = await client.post(
            f"{BACKEND_URL}/api/v1/tickets/00000000-0000-0000-0000-000000000000/assign",
            json={"assignee_id": "10000000-0000-0000-0000-000000000005"},
            headers={"Authorization": f"Bearer {engineer_token}"},
        )
        assert assign_res.status_code == 403


@pytest.mark.asyncio
async def test_e2e_all_seventeen_frontend_routes_accessible():
    """Verify that all 17 public and protected routes return HTTP 200."""
    routes = [
        "/",
        "/login",
        "/signup",
        "/403",
        "/app/dashboard",
        "/app/ai",
        "/app/projects",
        "/app/tasks",
        "/app/tickets",
        "/app/calendar",
        "/app/approvals",
        "/app/risks",
        "/app/knowledge",
        "/app/actions",
        "/app/notifications",
        "/app/search",
        "/app/settings",
    ]
    async with httpx.AsyncClient(timeout=10.0) as client:
        for r in routes:
            res = await client.get(f"{FRONTEND_URL}{r}")
            assert res.status_code == 200, f"Route {r} failed with status {res.status_code}"

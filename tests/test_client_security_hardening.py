import pytest
from httpx import ASGITransport, AsyncClient
from uuid import uuid4

from app.core.security import create_demo_token
from app.main import app


@pytest.mark.asyncio
async def test_client_ai_admin_profile_and_permissions():
    """Verify NextGen client_ai_admin identity, tenant claims, and strict least-privilege permissions."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token = create_demo_token("admin@nextgen.com")
        res = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200
        data = res.json()
        assert data["email"] == "admin@nextgen.com"
        assert data["role"] == "client_ai_admin"
        assert data["organization_id"] == "22222222-2222-2222-2222-222222222222"

        # Explicit Allow-list check
        expected_perms = {
            "ticket.read", "ticket.create", "ticket.write",
            "calendar.read",
            "project.read",
            "task.read",
            "ai.chat",
            "action.execute",
            "ai_config.manage"
        }
        for perm in expected_perms:
            assert perm in data["permissions"], f"Expected {perm} in client permissions"

        # Explicit Deny-list check
        forbidden_perms = {
            "*", "admin",
            "approval.write", "approval.approve",
            "ticket.assign"
        }
        for perm in forbidden_perms:
            assert perm not in data["permissions"], f"Did NOT expect {perm} in client permissions"


@pytest.mark.asyncio
async def test_client_admin_deny_list_endpoints():
    """Verify that client_ai_admin receives 403 Forbidden on restricted operational governance endpoints."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token = create_demo_token("admin@nextgen.com")
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Governance approval execution is forbidden for client admin
        appr_res = await client.post(
            f"/api/v1/approvals/{uuid4()}/decide",
            headers=headers,
            json={"decision": "approved", "notes": "Client attempt to approve gate"}
        )
        assert appr_res.status_code == 403, f"Expected 403, got {appr_res.status_code}"

        # 2. Direct calendar creation is blocked for client to enforce HITL
        cal_res = await client.post(
            "/api/v1/calendar/events",
            headers=headers,
            json={
                "title": "Bypass Sync",
                "start_time": "2026-09-10T10:00:00Z",
                "end_time": "2026-09-10T11:00:00Z"
            }
        )
        assert cal_res.status_code == 403, f"Expected 403, got {cal_res.status_code}"
        assert "direct calendar mutation is restricted" in cal_res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_tenant_header_tampering_rejection():
    """Verify that attempting to spoof another tenant via X-Organization-ID is blocked with 403."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token = create_demo_token("admin@nextgen.com")
        # Token is for NextGen (22222222-...), attacker tries to access PMRG Solution (11111111-...)
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Organization-ID": "11111111-1111-1111-1111-111111111111"
        }
        res = await client.get("/api/v1/tickets/", headers=headers)
        assert res.status_code == 403, f"Expected 403, got {res.status_code}"
        assert "tenant" in res.json()["detail"].lower() and "mismatch" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_client_admin_allowed_reads_and_ticket_creation():
    """Verify allowed client endpoints: reading projects, calendar, tasks, and creating tickets."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token = create_demo_token("admin@nextgen.com")
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Read projects
        proj_res = await client.get("/api/v1/projects/", headers=headers)
        assert proj_res.status_code == 200

        # 2. Read calendar
        cal_res = await client.get("/api/v1/calendar/events", headers=headers)
        assert cal_res.status_code == 200

        # 3. Read tasks
        task_res = await client.get("/api/v1/tasks/", headers=headers)
        assert task_res.status_code == 200

        # 4. Create ticket
        new_ticket = await client.post(
            "/api/v1/tickets/",
            headers=headers,
            json={
                "title": "NextGen Portal Connectivity Lag",
                "description": "Observed intermittent 504 gateway timeouts on report export.",
                "severity": "high",
                "priority": "P1",
                "category": "Incident",
                "affected_service": "reports-service"
            }
        )
        assert new_ticket.status_code in (200, 201)
        ticket_data = new_ticket.json()
        assert ticket_data["title"] == "NextGen Portal Connectivity Lag"
        ticket_id = ticket_data["id"]

        # 5. Read created ticket by ID
        get_res = await client.get(f"/api/v1/tickets/{ticket_id}", headers=headers)
        assert get_res.status_code == 200
        assert get_res.json()["id"] == ticket_id


@pytest.mark.asyncio
async def test_tenant_ai_config_encryption_and_rbac():
    """Verify that client_ai_admin can securely store encrypted keys, without plaintext leakage."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin_token = create_demo_token("admin@nextgen.com")
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # 1. Save new API Key
        raw_key = "AIzaSyTestClientSecretKey998877665544"
        save_res = await client.post(
            "/api/v1/ai/config",
            headers=admin_headers,
            json={"provider": "google_gemini", "api_key": raw_key}
        )
        assert save_res.status_code == 200
        save_data = save_res.json()
        assert raw_key not in str(save_data), "Raw API key leaked in response!"
        assert save_data["masked_key"] == "****5544"

        # 2. Get AI Config list
        list_res = await client.get("/api/v1/ai/config", headers=admin_headers)
        assert list_res.status_code == 200
        configs = list_res.json()
        assert len(configs) >= 1
        assert raw_key not in str(configs), "Raw API key leaked in config list!"
        matching = [c for c in configs if c["provider"] == "google_gemini"]
        assert len(matching) == 1
        assert matching[0]["masked_key"] == "****5544"

        # 3. Clean up / delete key
        del_res = await client.delete("/api/v1/ai/config?provider=google_gemini", headers=admin_headers)
        assert del_res.status_code == 200

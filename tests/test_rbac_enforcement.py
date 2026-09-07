import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.security import create_demo_token


@pytest.mark.asyncio
async def test_viewer_role_cannot_write_calendar():
    """Dave (Viewer) has calendar.read but lacks calendar.write permission."""
    token = create_demo_token("dave@acme.com")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Dave can read calendar slots
        read_res = await client.get(
            "/api/v1/calendar/slots?attendees=alice@acme.com",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert read_res.status_code == 200

        # Dave is forbidden from creating meetings
        write_res = await client.post(
            "/api/v1/calendar/events",
            json={
                "title": "Unauthorized Meeting",
                "start_time": "2026-09-08T10:00:00Z",
                "end_time": "2026-09-08T10:30:00Z",
                "attendees": ["dave@acme.com"],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert write_res.status_code == 403
        assert "User does not have required permission 'calendar.write'" in write_res.json()["detail"]


@pytest.mark.asyncio
async def test_pm_role_can_create_meeting():
    """Alice (PM) has calendar.write and can create meetings."""
    token = create_demo_token("alice@acme.com")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/v1/calendar/events",
            json={
                "title": "PM Sprint Alignment",
                "start_time": "2026-09-09T14:00:00Z",
                "end_time": "2026-09-09T14:30:00Z",
                "attendees": ["alice@acme.com", "rahul@acme.com"],
                "meeting_type": "standup",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 201
        data = res.json()
        assert data["title"] == "PM Sprint Alignment"
        assert data["status"] == "confirmed"


@pytest.mark.asyncio
async def test_admin_wildcard_permission():
    """Sarah (Admin) has '*' permission and can access any guarded endpoint."""
    token = create_demo_token("sarah@acme.com")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get(
            "/api/v1/calendar/events",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200


@pytest.mark.asyncio
async def test_engineer_cannot_assign_tickets():
    """Rahul (Engineer) has ticket.read and ticket.write, but lacks ticket.assign."""
    token = create_demo_token("rahul@acme.com")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Can view tickets
        read_res = await client.get(
            "/api/v1/tickets/",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert read_res.status_code == 200

        # Cannot reassign ticket
        assign_res = await client.post(
            "/api/v1/tickets/00000000-0000-0000-0000-000000000000/assign",
            json={"assignee_id": "10000000-0000-0000-0000-000000000005"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert assign_res.status_code == 403


@pytest.mark.asyncio
async def test_cross_tenant_calendar_isolation():
    """Bob (Globex Inc) cannot view Acme Corp meetings."""
    globex_token = create_demo_token("bob@globex.com")
    acme_token = create_demo_token("alice@acme.com")
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Alice (Acme) fetches Acme events
        acme_events = (await client.get(
            "/api/v1/calendar/events",
            headers={"Authorization": f"Bearer {acme_token}"},
        )).json()

        # Bob (Globex) fetches Globex events
        globex_events = (await client.get(
            "/api/v1/calendar/events",
            headers={"Authorization": f"Bearer {globex_token}"},
        )).json()

        acme_ids = {e["id"] for e in acme_events}
        globex_ids = {e["id"] for e in globex_events}

        # Sets must be completely disjoint
        assert acme_ids.isdisjoint(globex_ids)

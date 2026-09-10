import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.security import create_demo_token


@pytest.mark.asyncio
async def test_engineer_cannot_assign_tickets():
    """Engineer has ticket.read and ticket.write, but lacks ticket.assign."""
    token = create_demo_token("engineer@pmrgsolution.com")
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
    """NextGen Admin cannot view PMRG Solution meetings."""
    nextgen_token = create_demo_token("admin@nextgen.com")
    pmrg_token = create_demo_token("pm@pmrgsolution.com")
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # PMRG PM fetches PMRG events
        pmrg_events = (await client.get(
            "/api/v1/calendar/events",
            headers={"Authorization": f"Bearer {pmrg_token}"},
        )).json()

        # NextGen Admin fetches NextGen events
        nextgen_events = (await client.get(
            "/api/v1/calendar/events",
            headers={"Authorization": f"Bearer {nextgen_token}"},
        )).json()

        pmrg_ids = {e["id"] for e in pmrg_events}
        nextgen_ids = {e["id"] for e in nextgen_events}

        # Cross-tenant sets must be disjoint
        assert pmrg_ids.isdisjoint(nextgen_ids), "Cross-tenant leak detected!"

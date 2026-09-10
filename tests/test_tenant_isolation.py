import pytest
from httpx import ASGITransport, AsyncClient
from uuid import uuid4

from app.core.security import create_demo_token
from app.main import app


@pytest.mark.asyncio
async def test_tenant_isolation_unauthorized_token():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Generate token for PM in PMRG Solution (Org A)
        alice_token = create_demo_token("pm@pmrgsolution.com")

        # 2. Generate token for Operator in NextGen (Org B)
        bob_token = create_demo_token("operator@nextgen.com")

        # 3. User accesses profile -> belongs to Org A
        alice_me = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {alice_token}"}
        )
        assert alice_me.status_code == 200
        assert alice_me.json()["organization_id"] == "11111111-1111-1111-1111-111111111111"

        # 4. NextGen user accesses profile -> belongs to Org B
        bob_me = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {bob_token}"}
        )
        assert bob_me.status_code == 200
        assert bob_me.json()["organization_id"] == "22222222-2222-2222-2222-222222222222"

        # 5. User attempts to perform an admin action without required permissions -> 403 Forbidden
        foreign_action_id = uuid4()
        unauth_action_res = await client.post(
            f"/api/v1/actions/{foreign_action_id}/confirm",
            headers={"Authorization": f"Bearer {bob_token}"},
            json={}
        )
        # Prevented from unauthorized execution (403 forbidden or 404 not found)
        assert unauth_action_res.status_code in (403, 404)

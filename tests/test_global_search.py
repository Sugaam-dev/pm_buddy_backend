import pytest
from uuid import uuid4

from app.core.database import AsyncSessionLocal
from app.models.entities import Organization, Project, Task, Ticket
from app.services.search_service import SearchService


@pytest.mark.asyncio
async def test_global_search_across_entities():
    async with AsyncSessionLocal() as session:
        org_id = uuid4()
        org = Organization(id=org_id, name="Search Org", slug=f"search-{org_id.hex[:8]}")
        session.add(org)

        proj = Project(
            id=uuid4(),
            organization_id=org_id,
            name="Quantum Sharding Engine",
            key="QNTM",
            description="Next generation distributed sharding cluster",
            owner_id=uuid4(),
        )
        task = Task(
            id=uuid4(),
            organization_id=org_id,
            project_id=proj.id,
            title="Benchmark Quantum Throughput",
            description="Target 100k TPS",
            status="todo",
        )
        session.add_all([proj, task])
        await session.commit()

        # Search for "Quantum"
        search_res = await SearchService.global_search(
            session=session,
            organization_id=org_id,
            query="Quantum",
            user_permissions=["*"],
        )
        assert search_res["total_results"] >= 2
        assert "projects" in search_res["results"]
        assert "tasks" in search_res["results"]

        # Cleanup via cascade
        await session.delete(org)
        await session.commit()


@pytest.mark.asyncio
async def test_global_search_tenant_isolation():
    async with AsyncSessionLocal() as session:
        org_a = uuid4()
        org_b = uuid4()

        o_a = Organization(id=org_a, name="Search Org A", slug=f"sea-a-{org_a.hex[:8]}")
        o_b = Organization(id=org_b, name="Search Org B", slug=f"sea-b-{org_b.hex[:8]}")
        session.add_all([o_a, o_b])

        proj_b = Project(
            id=uuid4(),
            organization_id=org_b,
            name="Ultra Classified Project B",
            key="UCB",
            owner_id=uuid4(),
        )
        session.add(proj_b)
        await session.commit()

        # Org A searches for Org B project title
        search_a = await SearchService.global_search(
            session=session,
            organization_id=org_a,
            query="Ultra Classified Project B",
            user_permissions=["*"],
        )
        assert search_a["total_results"] == 0

        # Cleanup via cascade
        await session.delete(o_a)
        await session.delete(o_b)
        await session.commit()

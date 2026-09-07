import pytest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.core.database import AsyncSessionLocal
from app.engines.project_health_engine import ProjectHealthEngine
from app.models.entities import Approval, Organization, Project, Risk, Task, Ticket
from app.services.daily_briefing_service import DailyBriefingService
from app.services.recommendation_service import RecommendationService


@pytest.mark.asyncio
async def test_project_health_engine_deterministic_score():
    async with AsyncSessionLocal() as session:
        org_id = uuid4()
        org = Organization(id=org_id, name="Health Test Org", slug=f"health-{org_id.hex[:8]}")
        session.add(org)

        proj = Project(
            id=uuid4(),
            organization_id=org_id,
            name="Health Project",
            key="HLTH",
            owner_id=uuid4(),
        )
        session.add(proj)
        await session.commit()

        # Healthy initially (no negative factors)
        health_clean = await ProjectHealthEngine.evaluate_project_health(session, org_id, proj.id)
        assert health_clean["health_score"] == 100
        assert health_clean["status"] == "healthy"

        # Add a breached SLA ticket and a critical risk
        now = datetime.now(timezone.utc)
        breached_ticket = Ticket(
            id=uuid4(),
            organization_id=org_id,
            project_id=proj.id,
            ticket_number="TCK-9999",
            title="Outage",
            description="DB down",
            category="bug",
            severity="critical",
            priority="P0",
            status="open",
            sla_due_at=now - timedelta(hours=2),  # Breached
        )
        crit_risk = Risk(
            id=uuid4(),
            organization_id=org_id,
            project_id=proj.id,
            title="Compliance loss",
            category="compliance",
            likelihood=5,
            impact=4,  # Score 20 (>= 15)
            status="active",
        )
        session.add_all([breached_ticket, crit_risk])
        await session.commit()

        # Evaluate degraded health
        health_degraded = await ProjectHealthEngine.evaluate_project_health(session, org_id, proj.id)
        assert health_degraded["health_score"] < 100
        assert health_degraded["status"] in ("at_risk", "critical")
        assert len(health_degraded["factors"]) >= 2

        # Cleanup
        await session.delete(breached_ticket)
        await session.delete(crit_risk)
        await session.delete(proj)
        await session.delete(org)
        await session.commit()


@pytest.mark.asyncio
async def test_daily_briefing_aggregation():
    async with AsyncSessionLocal() as session:
        org_id = uuid4()
        org = Organization(id=org_id, name="Briefing Org", slug=f"briefing-{org_id.hex[:8]}")
        session.add(org)
        await session.commit()

        briefing = await DailyBriefingService.get_daily_briefing(session, org_id)
        assert "date" in briefing
        assert "summary" in briefing
        assert isinstance(briefing["summary"]["high_priority_tasks_count"], int)
        assert isinstance(briefing["meetings"], list)

        await session.delete(org)
        await session.commit()


@pytest.mark.asyncio
async def test_action_recommendations():
    async with AsyncSessionLocal() as session:
        org_id = uuid4()
        org = Organization(id=org_id, name="Recs Org", slug=f"recs-{org_id.hex[:8]}")
        session.add(org)

        proj = Project(id=uuid4(), organization_id=org_id, name="Recs Project", key="REC", owner_id=uuid4())
        session.add(proj)

        now = datetime.now(timezone.utc)
        # Breached ticket
        ticket = Ticket(
            id=uuid4(),
            organization_id=org_id,
            project_id=proj.id,
            ticket_number="TCK-8888",
            title="Payment gateway failure",
            description="500 errors",
            category="incident",
            severity="critical",
            status="open",
            sla_due_at=now - timedelta(hours=1),
        )
        session.add(ticket)
        await session.commit()

        recs = await RecommendationService.get_action_recommendations(session, org_id, limit=3)
        assert len(recs) >= 1
        assert any("propose_escalation" in r["action_type"] for r in recs)

        await session.delete(ticket)
        await session.delete(proj)
        await session.delete(org)
        await session.commit()

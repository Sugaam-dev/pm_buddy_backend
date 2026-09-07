import pytest
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from app.engines.prediction_engine import HeuristicPredictionProvider


@pytest.mark.asyncio
async def test_heuristic_prediction_critical_breach_risk():
    provider = HeuristicPredictionProvider()
    now = datetime.now(timezone.utc)
    
    # 90% of SLA elapsed, heavy assignee workload (6 open tickets), critical severity, 3 dependencies
    created = now - timedelta(hours=9)
    due = now + timedelta(hours=1)

    result = await provider.predict_ticket_breach_risk(
        ticket_id=uuid4(),
        created_at=created,
        sla_due_at=due,
        severity="critical",
        assignee_active_tickets=6,
        dependency_count=3,
    )

    assert result.risk_score >= 70
    assert result.risk_level in ["HIGH", "CRITICAL"]
    assert len(result.contributing_factors) == 4

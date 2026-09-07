from datetime import datetime, timedelta, timezone
from app.engines.priority_engine import PriorityEngine


def test_priority_engine_p0_critical_breach():
    now = datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc)
    # SLA breached 3 days ago, blocks 3 tasks, critical impact, project at risk
    result = PriorityEngine.evaluate(
        sla_due_at=now - timedelta(days=3),
        is_blocked=True,
        blocked_downstream_count=3,
        impact_level="critical",
        target_due_date=now - timedelta(days=3),
        project_health="at_risk",
        now=now,
    )

    assert result.tier == "P0"
    assert result.score >= 85
    assert any(f.factor_name == "SLA Urgency" and f.normalized_value == 1.0 for f in result.factors)


def test_priority_engine_p3_routine_task():
    now = datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc)
    # Due in 10 days, not blocked, low impact, healthy project
    result = PriorityEngine.evaluate(
        sla_due_at=now + timedelta(days=10),
        is_blocked=False,
        blocked_downstream_count=0,
        impact_level="low",
        target_due_date=now + timedelta(days=10),
        project_health="healthy",
        now=now,
    )

    assert result.tier == "P3"
    assert result.score < 45

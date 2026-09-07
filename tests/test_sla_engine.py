from datetime import datetime, timedelta, timezone
from app.engines.sla_engine import SLAEngine, SLAStatus


def test_sla_engine_normal_status():
    now = datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc)
    res = SLAEngine.evaluate_status(
        created_at=now - timedelta(hours=2),
        sla_due_at=now + timedelta(hours=48),
        warning_minutes_before=1440,
        now=now,
    )
    assert res["status"] == SLAStatus.NORMAL
    assert res["is_breached"] is False


def test_sla_engine_warning_status():
    now = datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc)
    res = SLAEngine.evaluate_status(
        created_at=now - timedelta(hours=36),
        sla_due_at=now + timedelta(hours=12),
        warning_minutes_before=1440,
        now=now,
    )
    assert res["status"] == SLAStatus.WARNING
    assert res["is_breached"] is False


def test_sla_engine_breached_status():
    now = datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc)
    res = SLAEngine.evaluate_status(
        created_at=now - timedelta(hours=80),
        sla_due_at=now - timedelta(hours=8),
        warning_minutes_before=1440,
        now=now,
    )
    assert res["status"] == SLAStatus.BREACHED
    assert res["is_breached"] is True
    assert res["hours_overdue"] == 8.0

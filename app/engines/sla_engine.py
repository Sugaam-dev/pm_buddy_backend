from datetime import datetime, timezone
from enum import Enum
from typing import Any


class SLAStatus(str, Enum):
    NORMAL = "normal"
    WARNING = "warning"
    BREACHED = "breached"


class SLAEngine:
    """
    Evaluates entity status against organizational SLA rules.
    Emits warnings and breach detections deterministically.
    """

    @staticmethod
    def evaluate_status(
        created_at: datetime,
        sla_due_at: datetime,
        warning_minutes_before: int = 1440,  # default 24h warning
        now: datetime | None = None,
    ) -> dict[str, Any]:
        now = now or datetime.now(timezone.utc)

        if now >= sla_due_at:
            overdue_seconds = (now - sla_due_at).total_seconds()
            return {
                "status": SLAStatus.BREACHED,
                "is_breached": True,
                "days_overdue": round(overdue_seconds / 86400.0, 1),
                "hours_overdue": round(overdue_seconds / 3600.0, 1),
                "remaining_seconds": 0,
            }

        remaining_seconds = (sla_due_at - now).total_seconds()
        remaining_minutes = remaining_seconds / 60.0

        if remaining_minutes <= warning_minutes_before:
            return {
                "status": SLAStatus.WARNING,
                "is_breached": False,
                "hours_remaining": round(remaining_seconds / 3600.0, 1),
                "remaining_seconds": int(remaining_seconds),
            }

        return {
            "status": SLAStatus.NORMAL,
            "is_breached": False,
            "hours_remaining": round(remaining_seconds / 3600.0, 1),
            "remaining_seconds": int(remaining_seconds),
        }

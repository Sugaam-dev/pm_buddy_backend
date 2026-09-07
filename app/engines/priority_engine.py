from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass
class PriorityFactorResult:
    factor_name: str
    raw_value: Any
    normalized_value: float  # 0.0 to 1.0
    weight: int
    weighted_score: float
    explanation: str


@dataclass
class PriorityEvaluation:
    score: int  # 0 to 100
    tier: str   # P0, P1, P2, P3
    factors: list[PriorityFactorResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "tier": self.tier,
            "factors": [
                {
                    "name": f.factor_name,
                    "normalized_value": round(f.normalized_value, 2),
                    "weight": f.weight,
                    "weighted_score": round(f.weighted_score, 1),
                    "explanation": f.explanation,
                }
                for f in self.factors
            ],
        }


class PriorityEngine:
    """
    Deterministic Governance Priority Calculator.
    Invariant: Rules calculate; AI explains.
    Formula: Score = min(100, sum(w_i * Factor_i))
    """

    WEIGHTS = {
        "sla_breach": 30,
        "blocker": 25,
        "impact": 20,
        "overdue": 15,
        "project_health": 10,
    }

    @classmethod
    def evaluate(
        cls,
        sla_due_at: datetime | None,
        is_blocked: bool,
        blocked_downstream_count: int,
        impact_level: str,  # critical, high, medium, low
        target_due_date: datetime | None,
        project_health: str,  # at_risk, caution, healthy
        now: datetime | None = None,
    ) -> PriorityEvaluation:
        now = now or datetime.now(timezone.utc)
        factors: list[PriorityFactorResult] = []

        # 1. SLA Breach Factor (Weight = 30)
        sla_norm = 0.0
        sla_desc = "Within SLA boundaries"
        if sla_due_at:
            if now > sla_due_at:
                days_overdue = (now - sla_due_at).total_seconds() / 86400.0
                sla_norm = min(1.0, 0.7 + (0.1 * days_overdue))
                sla_desc = f"SLA Breached by {days_overdue:.1f} days"
            else:
                # Approaching breach within 24 hours
                hours_remaining = (sla_due_at - now).total_seconds() / 3600.0
                if hours_remaining <= 24:
                    sla_norm = 0.5
                    sla_desc = f"SLA Approaching breach in {hours_remaining:.1f} hours"

        factors.append(
            PriorityFactorResult(
                factor_name="SLA Urgency",
                raw_value=sla_due_at.isoformat() if sla_due_at else None,
                normalized_value=sla_norm,
                weight=cls.WEIGHTS["sla_breach"],
                weighted_score=sla_norm * cls.WEIGHTS["sla_breach"],
                explanation=sla_desc,
            )
        )

        # 2. Blocker Severity Factor (Weight = 25)
        blocker_norm = 0.0
        blocker_desc = "Not blocking critical paths"
        if blocked_downstream_count >= 3:
            blocker_norm = 1.0
            blocker_desc = f"Blocking {blocked_downstream_count} downstream tasks/milestones"
        elif blocked_downstream_count in (1, 2):
            blocker_norm = 0.6
            blocker_desc = f"Blocking {blocked_downstream_count} downstream tasks"
        elif is_blocked:
            blocker_norm = 0.3
            blocker_desc = "Task is blocked by external dependency"

        factors.append(
            PriorityFactorResult(
                factor_name="Blocker Dependency",
                raw_value=blocked_downstream_count,
                normalized_value=blocker_norm,
                weight=cls.WEIGHTS["blocker"],
                weighted_score=blocker_norm * cls.WEIGHTS["blocker"],
                explanation=blocker_desc,
            )
        )

        # 3. Business Impact Factor (Weight = 20)
        impact_map = {"critical": 1.0, "high": 0.7, "medium": 0.4, "low": 0.1}
        impact_norm = impact_map.get(impact_level.lower(), 0.4)
        factors.append(
            PriorityFactorResult(
                factor_name="Business Impact",
                raw_value=impact_level,
                normalized_value=impact_norm,
                weight=cls.WEIGHTS["impact"],
                weighted_score=impact_norm * cls.WEIGHTS["impact"],
                explanation=f"{impact_level.capitalize()} business / customer impact",
            )
        )

        # 4. Due Date Proximity Factor (Weight = 15)
        due_norm = 0.0
        due_desc = "Adequate time until due date"
        if target_due_date:
            if now > target_due_date:
                days_past = (now - target_due_date).total_seconds() / 86400.0
                due_norm = min(1.0, 0.5 + (0.1 * days_past))
                due_desc = f"Past target due date by {days_past:.1f} days"
            else:
                hours_left = (target_due_date - now).total_seconds() / 3600.0
                if hours_left <= 24:
                    due_norm = 0.5
                    due_desc = "Due within next 24 hours"
                elif hours_left <= 48:
                    due_norm = 0.3
                    due_desc = "Due within next 48 hours"

        factors.append(
            PriorityFactorResult(
                factor_name="Due Date Proximity",
                raw_value=target_due_date.isoformat() if target_due_date else None,
                normalized_value=due_norm,
                weight=cls.WEIGHTS["overdue"],
                weighted_score=due_norm * cls.WEIGHTS["overdue"],
                explanation=due_desc,
            )
        )

        # 5. Project Criticality Factor (Weight = 10)
        health_map = {"at_risk": 1.0, "caution": 0.5, "healthy": 0.1}
        health_norm = health_map.get(project_health.lower(), 0.5)
        factors.append(
            PriorityFactorResult(
                factor_name="Project Criticality",
                raw_value=project_health,
                normalized_value=health_norm,
                weight=cls.WEIGHTS["project_health"],
                weighted_score=health_norm * cls.WEIGHTS["project_health"],
                explanation=f"Parent project health is '{project_health}'",
            )
        )

        # Calculate final total
        total_score = int(round(min(100.0, sum(f.weighted_score for f in factors))))

        # Tier mapping
        if total_score >= 85:
            tier = "P0"
        elif total_score >= 70:
            tier = "P1"
        elif total_score >= 45:
            tier = "P2"
        else:
            tier = "P3"

        return PriorityEvaluation(score=total_score, tier=tier, factors=factors)

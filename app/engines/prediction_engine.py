from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID


@dataclass
class PredictionFactor:
    factor_name: str
    impact_score: float
    description: str


@dataclass
class PredictionResult:
    risk_score: int  # 0 to 100
    risk_level: str  # LOW, MEDIUM, HIGH, CRITICAL
    contributing_factors: list[PredictionFactor]
    model_version: str


class IPredictionProvider(ABC):
    @abstractmethod
    async def predict_ticket_breach_risk(
        self,
        ticket_id: UUID,
        created_at: datetime,
        sla_due_at: datetime,
        severity: str,
        assignee_active_tickets: int,
        dependency_count: int,
    ) -> PredictionResult:
        pass


class HeuristicPredictionProvider(IPredictionProvider):
    """
    Deterministic/statistical heuristic risk evaluation.
    Invariant: Transparent risk score (0-100), not pseudo-scientific probabilities.
    """

    async def predict_ticket_breach_risk(
        self,
        ticket_id: UUID,
        created_at: datetime,
        sla_due_at: datetime,
        severity: str,
        assignee_active_tickets: int,
        dependency_count: int,
    ) -> PredictionResult:
        now = datetime.now(timezone.utc)
        factors: list[PredictionFactor] = []

        total_duration = max(1.0, (sla_due_at - created_at).total_seconds())
        elapsed_duration = max(0.0, (now - created_at).total_seconds())
        elapsed_pct = min(1.0, elapsed_duration / total_duration)

        # 1. Elapsed SLA Factor (Weight = 35)
        f_elapsed = elapsed_pct * 35.0
        factors.append(
            PredictionFactor(
                factor_name="Elapsed SLA Percentage",
                impact_score=round(f_elapsed, 1),
                description=f"{elapsed_pct * 100:.1f}% of allocated SLA has already passed",
            )
        )

        # 2. Assignee Workload Saturation (Weight = 30)
        if assignee_active_tickets >= 5:
            f_load = 30.0
            load_desc = f"Assignee is heavily loaded ({assignee_active_tickets} active tickets)"
        elif assignee_active_tickets in (3, 4):
            f_load = 18.0
            load_desc = f"Assignee has moderate workload ({assignee_active_tickets} active tickets)"
        else:
            f_load = 6.0
            load_desc = f"Assignee has light workload ({assignee_active_tickets} active tickets)"

        factors.append(
            PredictionFactor(
                factor_name="Assignee Workload",
                impact_score=round(f_load, 1),
                description=load_desc,
            )
        )

        # 3. Severity Complexity (Weight = 20)
        sev_map = {"critical": 20.0, "high": 14.0, "medium": 8.0, "low": 2.0}
        f_sev = sev_map.get(severity.lower(), 8.0)
        factors.append(
            PredictionFactor(
                factor_name="Incident Severity",
                impact_score=round(f_sev, 1),
                description=f"{severity.capitalize()} severity classification requires deep triage",
            )
        )

        # 4. Dependency Count (Weight = 15)
        f_dep = min(15.0, dependency_count * 5.0)
        factors.append(
            PredictionFactor(
                factor_name="Blocking Dependencies",
                impact_score=round(f_dep, 1),
                description=f"{dependency_count} unresolved upstream dependencies",
            )
        )

        total_risk = int(round(min(100.0, sum(f.impact_score for f in factors))))

        if total_risk >= 80:
            level = "CRITICAL"
        elif total_risk >= 60:
            level = "HIGH"
        elif total_risk >= 40:
            level = "MEDIUM"
        else:
            level = "LOW"

        return PredictionResult(
            risk_score=total_risk,
            risk_level=level,
            contributing_factors=factors,
            model_version="heuristic-v1.0",
        )

from datetime import datetime, timezone
from typing import Any
from uuid import UUID
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engines.sla_engine import SLAEngine
from app.models.entities import Approval, Project


class ApprovalService:
    @staticmethod
    async def list_approvals(
        session: AsyncSession,
        organization_id: UUID,
        project_id: UUID | None = None,
        status: str = "pending",
        breached_only: bool = False,
    ) -> list[dict[str, Any]]:
        stmt = (
            select(Approval, Project.name.label("project_name"), Project.key.label("project_key"))
            .join(Project, Approval.project_id == Project.id)
            .where(
                Approval.organization_id == organization_id,
                Approval.status == status
            )
        )

        if project_id:
            stmt = stmt.where(Approval.project_id == project_id)

        result = await session.execute(stmt)
        rows = result.all()

        now = datetime.now(timezone.utc)
        items = []
        for app, proj_name, proj_key in rows:
            sla_info = SLAEngine.evaluate_status(app.created_at, app.sla_due_at, now=now)
            if breached_only and not sla_info["is_breached"]:
                continue

            items.append({
                "id": str(app.id),
                "project_id": str(app.project_id),
                "project_name": proj_name,
                "project_key": proj_key,
                "title": app.title,
                "description": app.description,
                "stage": app.stage,
                "status": app.status,
                "approver_id": str(app.approver_id),
                "sla_due_at": app.sla_due_at.isoformat(),
                "sla_status": sla_info["status"].value,
                "is_breached": sla_info["is_breached"],
                "days_overdue": sla_info.get("days_overdue", 0),
            })

        # Sort: breached first
        items.sort(key=lambda x: (not x["is_breached"], x["sla_due_at"]))
        return items

    @staticmethod
    async def get_blocking_approvers(
        session: AsyncSession, organization_id: UUID
    ) -> list[dict[str, Any]]:
        """Identifies approvers blocking the most active approvals."""
        stmt = (
            select(
                Approval.approver_id,
                func.count(Approval.id).label("pending_count")
            )
            .where(
                Approval.organization_id == organization_id,
                Approval.status == "pending"
            )
            .group_by(Approval.approver_id)
            .order_by(func.count(Approval.id).desc())
        )
        result = await session.execute(stmt)
        rows = result.all()
        return [
            {"approver_id": str(r.approver_id), "pending_approvals_count": r.pending_count}
            for r in rows
        ]

    @staticmethod
    async def decide_step(
        session: AsyncSession,
        organization_id: UUID,
        approval_id: UUID,
        user_id: UUID,
        decision: str,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Mutates governance gate approval status to approved or rejected."""
        stmt = (
            select(Approval)
            .where(
                Approval.id == approval_id,
                Approval.organization_id == organization_id,
            )
            .with_for_update()
        )
        approval = (await session.execute(stmt)).scalar_one_or_none()
        if not approval:
            from fastapi import HTTPException, status
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found.")

        is_approved = decision.lower() in ("approved", "approve")
        approval.status = "approved" if is_approved else "rejected"
        await session.flush()

        return {
            "approval_id": str(approval.id),
            "status": approval.status,
            "decided_by": str(user_id),
            "decision": approval.status,
            "notes": notes,
        }


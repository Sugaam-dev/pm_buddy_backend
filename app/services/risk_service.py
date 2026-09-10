from typing import Any
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Project, Risk


class RiskService:
    @staticmethod
    async def list_risks(
        session: AsyncSession,
        organization_id: UUID,
        project_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        stmt = (
            select(Risk, Project.name.label("project_name"))
            .outerjoin(Project, Risk.project_id == Project.id)
            .where(Risk.organization_id == organization_id)
            .order_by((Risk.likelihood * Risk.impact).desc())
        )

        if project_id:
            stmt = stmt.where(Risk.project_id == project_id)

        result = await session.execute(stmt)
        rows = result.all()

        return [
            {
                "id": str(r.id),
                "project_id": str(r.project_id),
                "project_name": proj_name,
                "title": r.title,
                "description": r.description,
                "category": r.category,
                "likelihood": r.likelihood,
                "impact": r.impact,
                "score": r.likelihood * r.impact,
                "status": r.status,
                "owner_id": str(r.owner_id) if r.owner_id else None,
                "mitigation_plan": r.mitigation_plan,
            }
            for r, proj_name in rows
        ]

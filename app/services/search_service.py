import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import (
    Approval,
    CalendarEvent,
    KnowledgeDocument,
    Project,
    Risk,
    Task,
    Ticket,
)

logger = logging.getLogger(__name__)


class SearchService:
    @staticmethod
    async def global_search(
        session: AsyncSession,
        organization_id: UUID,
        query: str,
        user_permissions: List[str],
        category: Optional[str] = None,
        limit_per_category: int = 5,
    ) -> Dict[str, Any]:
        """Performs tenant-scoped, permission-aware search across all 7 operational entities."""
        cleaned_q = query.strip()
        if not cleaned_q:
            return {"query": query, "total_results": 0, "results": {}}

        wildcard = f"%{cleaned_q}%"
        results: Dict[str, List[Dict[str, Any]]] = {}
        total = 0

        has_wildcard = "*" in user_permissions

        # 1. Projects
        if (has_wildcard or any("project" in p for p in user_permissions)) and (not category or category == "projects"):
            stmt = select(Project).where(
                Project.organization_id == organization_id,
                Project.deleted_at.is_(None),
                or_(
                    Project.name.ilike(wildcard),
                    Project.key.ilike(wildcard),
                    Project.description.ilike(wildcard),
                ),
            ).limit(limit_per_category)
            proj_items = [
                {
                    "id": str(p.id),
                    "title": f"[{p.key}] {p.name}",
                    "subtitle": p.description or f"Health: {p.health} | Status: {p.status}",
                    "category": "projects",
                    "link": f"/projects?id={p.id}",
                }
                for p in (await session.execute(stmt)).scalars().all()
            ]
            if proj_items:
                results["projects"] = proj_items
                total += len(proj_items)

        # 2. Tasks
        if (has_wildcard or any("task" in p for p in user_permissions)) and (not category or category == "tasks"):
            stmt = select(Task).where(
                Task.organization_id == organization_id,
                Task.deleted_at.is_(None),
                or_(
                    Task.title.ilike(wildcard),
                    Task.description.ilike(wildcard),
                ),
            ).limit(limit_per_category)
            task_items = [
                {
                    "id": str(t.id),
                    "title": t.title,
                    "subtitle": f"Priority: {t.priority} | Status: {t.status}",
                    "category": "tasks",
                    "link": f"/tasks?id={t.id}",
                }
                for t in (await session.execute(stmt)).scalars().all()
            ]
            if task_items:
                results["tasks"] = task_items
                total += len(task_items)

        # 3. Tickets
        if (has_wildcard or any("ticket" in p for p in user_permissions)) and (not category or category == "tickets"):
            stmt = select(Ticket).where(
                Ticket.organization_id == organization_id,
                Ticket.deleted_at.is_(None),
                or_(
                    Ticket.ticket_number.ilike(wildcard),
                    Ticket.title.ilike(wildcard),
                    Ticket.description.ilike(wildcard),
                ),
            ).limit(limit_per_category)
            ticket_items = [
                {
                    "id": str(tk.id),
                    "title": f"[{tk.ticket_number}] {tk.title}",
                    "subtitle": f"Severity: {tk.severity} | Status: {tk.status}",
                    "category": "tickets",
                    "link": f"/tickets?id={tk.id}",
                }
                for tk in (await session.execute(stmt)).scalars().all()
            ]
            if ticket_items:
                results["tickets"] = ticket_items
                total += len(ticket_items)

        # 4. Risks
        if (has_wildcard or any("risk" in p for p in user_permissions)) and (not category or category == "risks"):
            stmt = select(Risk).where(
                Risk.organization_id == organization_id,
                or_(
                    Risk.title.ilike(wildcard),
                    Risk.description.ilike(wildcard),
                ),
            ).limit(limit_per_category)
            risk_items = [
                {
                    "id": str(r.id),
                    "title": r.title,
                    "subtitle": f"Category: {r.category} | Impact: {r.impact}x{r.likelihood}",
                    "category": "risks",
                    "link": f"/risks?id={r.id}",
                }
                for r in (await session.execute(stmt)).scalars().all()
            ]
            if risk_items:
                results["risks"] = risk_items
                total += len(risk_items)

        # 5. Approvals
        if (has_wildcard or any("approval" in p for p in user_permissions)) and (not category or category == "approvals"):
            stmt = select(Approval).where(
                Approval.organization_id == organization_id,
                or_(
                    Approval.title.ilike(wildcard),
                    Approval.description.ilike(wildcard),
                    Approval.stage.ilike(wildcard),
                ),
            ).limit(limit_per_category)
            approval_items = [
                {
                    "id": str(a.id),
                    "title": a.title,
                    "subtitle": f"Stage: {a.stage} | Status: {a.status}",
                    "category": "approvals",
                    "link": f"/approvals?id={a.id}",
                }
                for a in (await session.execute(stmt)).scalars().all()
            ]
            if approval_items:
                results["approvals"] = approval_items
                total += len(approval_items)

        # 6. Calendar Events
        if (has_wildcard or any("calendar" in p for p in user_permissions)) and (not category or category == "calendar"):
            stmt = select(CalendarEvent).where(
                CalendarEvent.organization_id == organization_id,
                CalendarEvent.status != "cancelled",
                or_(
                    CalendarEvent.title.ilike(wildcard),
                    CalendarEvent.description.ilike(wildcard),
                ),
            ).limit(limit_per_category)
            cal_items = [
                {
                    "id": str(ce.id),
                    "title": ce.title,
                    "subtitle": f"{ce.start_time.strftime('%b %d, %H:%M')} | {ce.meeting_type}",
                    "category": "calendar",
                    "link": f"/calendar?id={ce.id}",
                }
                for ce in (await session.execute(stmt)).scalars().all()
            ]
            if cal_items:
                results["calendar"] = cal_items
                total += len(cal_items)

        # 7. Knowledge Documents
        if (has_wildcard or any("knowledge" in p for p in user_permissions) or any("project" in p for p in user_permissions)) and (not category or category == "knowledge"):
            stmt = select(KnowledgeDocument).where(
                KnowledgeDocument.organization_id == organization_id,
                KnowledgeDocument.status == "ready",
                or_(
                    KnowledgeDocument.title.ilike(wildcard),
                    KnowledgeDocument.description.ilike(wildcard),
                    KnowledgeDocument.content.ilike(wildcard),
                ),
            ).limit(limit_per_category)
            doc_items = [
                {
                    "id": str(kd.id),
                    "title": kd.title,
                    "subtitle": f"Type: {kd.document_type} | {kd.description or ''}",
                    "category": "knowledge",
                    "link": f"/knowledge?id={kd.id}",
                }
                for kd in (await session.execute(stmt)).scalars().all()
            ]
            if doc_items:
                results["knowledge"] = doc_items
                total += len(doc_items)

        return {
            "query": cleaned_q,
            "total_results": total,
            "results": results,
        }

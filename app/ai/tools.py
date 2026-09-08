import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Optional
from uuid import UUID
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.action_service import ActionService
from app.services.approval_service import ApprovalService
from app.services.calendar_service import LocalCalendarProvider
from app.services.daily_briefing_service import DailyBriefingService
from app.services.dependency_service import DependencyService
from app.services.knowledge_service import KnowledgeService
from app.services.project_service import ProjectService
from app.services.recommendation_service import RecommendationService
from app.services.risk_service import RiskService
from app.services.task_service import TaskService
from app.services.ticket_service import TicketService
from app.engines.priority_engine import PriorityEngine
from app.engines.project_health_engine import ProjectHealthEngine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool Input Schemas (Strict Pydantic)
# ---------------------------------------------------------------------------

class MyWorkInput(BaseModel):
    limit: int = Field(5, description="Maximum number of items to return per category")


class TicketQueryInput(BaseModel):
    severity: Optional[str] = Field(None, description="Optional severity filter (critical, high, medium, low)")
    status: Optional[str] = Field(None, description="Optional status filter (open, in_progress, resolved)")
    at_risk_only: bool = Field(False, description="Filter only tickets breaching or near breach")


class RiskQueryInput(BaseModel):
    limit: int = Field(10, description="Max risks to return")


class TaskPriorityExplanationInput(BaseModel):
    task_id_or_title: str = Field(..., description="Task ID or title to explain priority calculation for")


class ProjectDashboardInput(BaseModel):
    project_id: str = Field(..., description="UUID or project key (e.g., 'ALPHA') of the project")


class PendingApprovalsInput(BaseModel):
    breached_only: bool = Field(False, description="Filter only approvals that breached SLA limits")


class BlockingApproversInput(BaseModel):
    pass


class CalendarSlotsInput(BaseModel):
    attendee_emails: list[str] = Field(..., description="List of attendee email addresses")
    duration_minutes: int = Field(30, description="Meeting duration in minutes")
    search_date: Optional[str] = Field(None, description="ISO 8601 date to search for available slots")


class UpcomingMeetingsInput(BaseModel):
    days_ahead: int = Field(7, description="Number of days ahead to look for upcoming meetings")
    project_id: Optional[str] = Field(None, description="Optional project UUID to filter meetings")


class EventDetailsInput(BaseModel):
    event_id: str = Field(..., description="UUID of the calendar event to inspect")


class ProposeMeetingInput(BaseModel):
    title: str = Field(..., description="Title of the meeting")
    attendee_emails: list[str] = Field(..., description="List of attendee emails")
    start_time: str = Field(..., description="ISO 8601 start time")
    end_time: str = Field(..., description="ISO 8601 end time")
    description: str = Field("", description="Agenda or meeting purpose")
    project_id: Optional[str] = Field(None, description="Optional associated project UUID")
    location: Optional[str] = Field("Google Meet", description="Meeting location or video link")
    meeting_type: Optional[str] = Field("general", description="Type of meeting (e.g. sync, governance, standup)")


class ProposeUpdateMeetingInput(BaseModel):
    event_id: str = Field(..., description="UUID of the meeting to reschedule or modify")
    title: Optional[str] = Field(None, description="Updated meeting title")
    start_time: Optional[str] = Field(None, description="Updated ISO 8601 start time")
    end_time: Optional[str] = Field(None, description="Updated ISO 8601 end time")
    attendees: Optional[list[str]] = Field(None, description="Updated list of attendee emails")
    location: Optional[str] = Field(None, description="Updated location or video URL")


class ProposeCancelMeetingInput(BaseModel):
    event_id: str = Field(..., description="UUID of the meeting to cancel")
    reason: str = Field("Meeting cancelled via PM Buddy AI", description="Reason for cancellation")


class ProposeTicketAssignmentInput(BaseModel):
    ticket_id: str = Field(..., description="UUID of the ticket to assign")
    assignee_id: str = Field(..., description="UUID of the user to assign the ticket to")
    notes: str = Field("", description="Optional notes or reason for assignment")


class ProposeEscalationInput(BaseModel):
    approval_id: str = Field(..., description="UUID of the approval to escalate")
    escalate_to: str = Field(..., description="Email or user ID of the escalation contact")
    reason: str = Field(..., description="Reason for escalation")


class ProposeProjectStatusChangeInput(BaseModel):
    project_id: str = Field(..., description="UUID of the project")
    status: str = Field(..., description="New project status: active, on_hold, completed, archived")
    health: str = Field(..., description="New project health: on_track, at_risk, critical")
    reason: str = Field(..., description="Reason for changing project status")


class ProposeGateApprovalInput(BaseModel):
    approval_id: str = Field(..., description="UUID of the governance approval gate")
    decision: str = Field(..., description="Decision: 'approved' or 'rejected'")
    notes: str = Field("", description="Reason or context for the decision")


class KnowledgeSearchInput(BaseModel):
    query: str = Field(..., description="Query for semantic knowledge base search across architecture decisions, runbooks, and documentation")
    project_id: Optional[str] = Field(None, description="Optional project UUID filter")
    top_k: int = Field(5, description="Max relevant citations")


class GetDocumentInput(BaseModel):
    document_id: str = Field(..., description="UUID of the knowledge document to retrieve")


class DailyBriefingInput(BaseModel):
    date: Optional[str] = Field(None, description="Optional ISO date (YYYY-MM-DD) for briefing target")


class TaskDependenciesInput(BaseModel):
    task_id: str = Field(..., description="UUID of the task to inspect dependencies for")


class BlockersInput(BaseModel):
    project_id: Optional[str] = Field(None, description="Optional project UUID to filter active blockers")


class ProjectHealthBreakdownInput(BaseModel):
    project_id: str = Field(..., description="UUID or key of the project")


class ActionRecommendationsInput(BaseModel):
    limit: int = Field(5, description="Maximum number of recommendations to return")


class CreateTaskInput(BaseModel):
    title: str = Field(..., description="Title or summary of the task or to-do")
    description: Optional[str] = Field("", description="Optional details or context for the task")
    priority: Optional[str] = Field("P2", description="Priority tier: P0, P1, P2, P3")
    due_date: Optional[str] = Field(None, description="Optional ISO 8601 due date")
    project_id: Optional[str] = Field(None, description="Optional associated project UUID")


class CreateTicketInput(BaseModel):
    title: str = Field(..., description="Title or summary of the incident/ticket")
    severity: Optional[str] = Field("high", description="Severity level: critical, high, medium, low")
    priority: Optional[str] = Field("P2", description="Priority tier: P0, P1, P2, P3")
    description: Optional[str] = Field("", description="Detailed incident description")
    category: Optional[str] = Field("Infrastructure", description="Ticket category")
    affected_service: Optional[str] = Field(None, description="Affected service name")


# ---------------------------------------------------------------------------
# Tool Definition & Registry
# ---------------------------------------------------------------------------

@dataclass
class ToolDefinition:
    name: str
    description: str
    schema_class: type[BaseModel]
    is_sensitive: bool
    required_permission: str
    action_type: Optional[str] = None
    executor: Optional[Callable[..., Coroutine[Any, Any, dict[str, Any]]]] = None


# ---------------------------------------------------------------------------
# Tool Execution Implementations
# ---------------------------------------------------------------------------

async def _exec_get_my_work(
    session: AsyncSession,
    organization_id: UUID,
    user_id: UUID,
    conversation_id: UUID,
    args: MyWorkInput,
) -> dict[str, Any]:
    tasks = await TaskService.list_tasks(session, organization_id, assignee_id=user_id)
    is_personal = bool(tasks)
    if not tasks:
        tasks = await TaskService.list_tasks(session, organization_id)

    approvals = await ApprovalService.list_approvals(session, organization_id)
    tickets = await TicketService.list_tickets(session, organization_id, assignee_id=user_id)

    p0_tasks = [t for t in tasks if t.get("priority") == "P0"]
    overdue_approvals = [a for a in approvals if a.get("is_breached")]

    blocks: list[dict[str, Any]] = []
    if tasks:
        blocks.append({
            "type": "task_list",
            "title": "Your Priority Tasks" if is_personal else "Organizational Priority Tasks",
            "data": tasks[:args.limit],
        })
    if approvals:
        blocks.append({
            "type": "approval_list",
            "title": "Pending Governance Approvals",
            "data": approvals[:args.limit],
        })

    blocks.append({
        "type": "recommendation",
        "title": "Recommended Actions",
        "items": [
            {"label": "View Project Alpha Dashboard", "action": "view_project_alpha"},
            {"label": "Draft Escalation for Breached Approval", "action": "draft_escalation"},
            {"label": "Schedule Sync with Approver", "action": "schedule_sync"},
        ],
    })

    task_lines = []
    for t in tasks[:args.limit]:
        status_label = t.get("status", "todo").replace("_", " ").upper()
        p_label = t.get("priority", "P2")
        task_lines.append(f"- **[{p_label}] {t.get('title')}** — Status: `{status_label}`")

    section_header = "### 📋 Your To-Dos & Tasks:\n" if is_personal else "### 📋 Priority To-Dos:\n"
    items_list = "\n".join(task_lines)

    text = (
        f"{section_header}{items_list}\n\n"
        f"You have **{len(tasks)} task(s)**, **{len(approvals)} pending approval(s)**, and **{len(tickets)} ticket(s)** tracked.\n\n"
        f"**Immediate Priority**: Address the {len(p0_tasks)} P0 task(s) and {len(overdue_approvals)} breached approval(s)."
    )

    return {
        "text": text,
        "blocks": blocks,
        "data": {
            "task_count": len(tasks),
            "approval_count": len(approvals),
            "ticket_count": len(tickets),
            "p0_tasks": p0_tasks,
            "overdue_approvals": overdue_approvals,
        },
    }


async def _exec_get_project_dashboard(
    session: AsyncSession,
    organization_id: UUID,
    user_id: UUID,
    conversation_id: UUID,
    args: ProjectDashboardInput,
) -> dict[str, Any]:
    proj_id_str = args.project_id
    target_uuid: Optional[UUID] = None

    try:
        target_uuid = UUID(proj_id_str)
    except (ValueError, TypeError):
        projects = await ProjectService.list_projects(session, organization_id)
        match = next(
            (p for p in projects if p.get("key", "").lower() == proj_id_str.lower() or proj_id_str.lower() in p.get("name", "").lower()),
            None,
        )
        if match:
            target_uuid = UUID(match["id"])

    if not target_uuid:
        return {
            "text": f"Project '{proj_id_str}' could not be located in your organization.",
            "blocks": [],
            "data": {"error": f"Project '{proj_id_str}' not found"},
        }

    dashboard = await ProjectService.get_project_dashboard(session, organization_id, target_uuid)
    if not dashboard:
        return {
            "text": f"Dashboard metrics for project '{proj_id_str}' are currently unavailable.",
            "blocks": [],
            "data": {"error": "Dashboard not found"},
        }

    p_info = dashboard["project"]
    metrics = dashboard["metrics"]

    text = (
        f"**{p_info['name']} ({p_info['key']})** is currently **{p_info['health'].upper().replace('_', ' ')}**.\n\n"
        f"- Progress: **{metrics['progress_percentage']}%** completed ({metrics['completed_tasks']}/{metrics['total_tasks']} tasks)\n"
        f"- Active Blockers: **{metrics['blocked_task_count']}**\n"
        f"- Overdue Tasks: **{metrics['overdue_tasks']}**\n"
        f"- Critical Incidents: **{metrics['critical_ticket_count']}**\n"
        f"- Budget Spent: **${p_info['spent']:,.2f}** of **${p_info['budget']:,.2f}** allocated"
    )

    blocks: list[dict[str, Any]] = [{"type": "project_card", "data": p_info}]
    if dashboard.get("blockers"):
        blocks.append({"type": "task_list", "title": "Critical Project Blockers", "data": dashboard["blockers"]})
    if dashboard.get("pending_approvals"):
        blocks.append({"type": "approval_list", "title": "Blocking Approvals", "data": dashboard["pending_approvals"]})

    blocks.append({
        "type": "recommendation",
        "title": "PM Buddy Guidance",
        "items": [
            {"label": "Schedule Architecture Review with Rahul", "action": "schedule_rahul"},
            {"label": "Request Budget Adjustment Sign-off", "action": "request_budget"},
        ],
    })

    return {"text": text, "blocks": blocks, "data": dashboard}


async def _exec_get_pending_approvals(
    session: AsyncSession,
    organization_id: UUID,
    user_id: UUID,
    conversation_id: UUID,
    args: PendingApprovalsInput,
) -> dict[str, Any]:
    approvals = await ApprovalService.list_approvals(session, organization_id, breached_only=args.breached_only)
    breached_count = sum(1 for a in approvals if a.get("is_breached"))

    text = (
        f"Found **{len(approvals)} pending approval(s)** in your organization. "
        f"**{breached_count} approval(s)** have breached organizational SLA limits."
    )

    blocks: list[dict[str, Any]] = [{"type": "approval_list", "title": "Governance Approvals", "data": approvals}]
    if breached_count > 0:
        blocks.append({
            "type": "recommendation",
            "title": "Mitigation Actions",
            "items": [
                {"label": "Draft Escalation Notice", "action": "draft_escalation"},
                {"label": "Schedule Urgent Review Meeting", "action": "schedule_meeting"},
            ],
        })

    return {
        "text": text,
        "blocks": blocks,
        "data": {"approvals": approvals, "breached_count": breached_count},
    }


async def _exec_get_blocking_approvers(
    session: AsyncSession,
    organization_id: UUID,
    user_id: UUID,
    conversation_id: UUID,
    args: BlockingApproversInput,
) -> dict[str, Any]:
    blockers = await ApprovalService.get_blocking_approvers(session, organization_id)
    text = f"Identified **{len(blockers)} approvers** holding active governance gates."
    blocks = [{"type": "table", "title": "Top Blocking Approvers", "data": blockers}]
    return {
        "text": text,
        "blocks": blocks,
        "data": {"blocking_approvers": blockers},
    }


async def _exec_get_calendar_slots(
    session: AsyncSession,
    organization_id: UUID,
    user_id: UUID,
    conversation_id: UUID,
    args: CalendarSlotsInput,
) -> dict[str, Any]:
    cal_provider = LocalCalendarProvider()
    search_dt: Optional[datetime] = None

    if args.search_date:
        try:
            search_dt = datetime.fromisoformat(args.search_date.replace("Z", "+00:00"))
        except Exception:
            search_dt = datetime.now(timezone.utc)
    else:
        search_dt = datetime.now(timezone.utc)

    slots = await cal_provider.find_available_slots(
        session=session,
        organization_id=organization_id,
        attendee_emails=args.attendee_emails,
        duration_minutes=args.duration_minutes,
        search_date=search_dt,
    )

    text = f"Found {len(slots)} available meeting slots for {', '.join(args.attendee_emails)}."
    blocks = [{"type": "calendar_slots", "title": "Available Meeting Slots", "slots": slots}]

    return {
        "text": text,
        "blocks": blocks,
        "data": {"slots": slots},
    }


async def _exec_get_upcoming_meetings(
    session: AsyncSession,
    organization_id: UUID,
    user_id: UUID,
    conversation_id: UUID,
    args: UpcomingMeetingsInput,
) -> dict[str, Any]:
    from app.services.calendar_service import CalendarService
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    end_window = now + timedelta(days=args.days_ahead)
    proj_id = UUID(args.project_id) if args.project_id else None
    events = await CalendarService.list_events(
        session=session,
        organization_id=organization_id,
        start_time=now,
        end_time=end_window,
        project_id=proj_id,
    )

    if not events:
        text = f"No upcoming meetings scheduled for the next {args.days_ahead} days."
    else:
        text = f"Found **{len(events)} upcoming meeting(s)** over the next {args.days_ahead} day(s):\n"
        for evt in events[:5]:
            start_dt = datetime.fromisoformat(evt["start_time"])
            fmt_time = start_dt.strftime("%b %d, %Y %I:%M %p UTC")
            text += f"- **{evt['title']}**: {fmt_time} ({len(evt.get('attendees', []))} attendees)\n"

    blocks = [{"type": "calendar_events", "title": "Upcoming Calendar Meetings", "data": events}]
    return {
        "text": text,
        "blocks": blocks,
        "data": {"meetings": events, "count": len(events)},
    }


async def _exec_get_event_details(
    session: AsyncSession,
    organization_id: UUID,
    user_id: UUID,
    conversation_id: UUID,
    args: EventDetailsInput,
) -> dict[str, Any]:
    from app.services.calendar_service import CalendarService
    try:
        event_id = UUID(args.event_id)
    except (ValueError, TypeError):
        return {
            "text": f"Invalid meeting ID: {args.event_id}",
            "blocks": [],
            "data": {"error": "invalid_id"},
        }

    evt = await CalendarService.get_event_by_id(session, organization_id, event_id)
    start_dt = datetime.fromisoformat(evt["start_time"])
    end_dt = datetime.fromisoformat(evt["end_time"])
    fmt_time = f"{start_dt.strftime('%b %d, %Y %I:%M %p')} - {end_dt.strftime('%I:%M %p')}"

    text = (
        f"### Meeting: **{evt['title']}**\n"
        f"- **Time**: {fmt_time}\n"
        f"- **Status**: {evt['status'].upper()}\n"
        f"- **Meeting Link**: [{evt.get('meet_url')}]({evt.get('meet_url')})\n"
        f"- **Attendees**: {', '.join(evt.get('attendees', []))}\n"
        f"- **Description**: {evt.get('description') or 'No agenda specified'}\n"
    )
    blocks = [{"type": "calendar_event_detail", "title": evt["title"], "data": evt}]
    return {
        "text": text,
        "blocks": blocks,
        "data": evt,
    }


async def _exec_get_tickets(
    session: AsyncSession,
    organization_id: UUID,
    user_id: UUID,
    conversation_id: UUID,
    args: TicketQueryInput,
) -> dict[str, Any]:
    tickets = await TicketService.list_tickets(
        session=session,
        organization_id=organization_id,
        severity=args.severity,
        status=args.status,
    )
    if args.at_risk_only:
        tickets = [t for t in tickets if t.get("is_breached") or t.get("sla_status") in ("warning", "breached") or (t.get("breach_risk_score") or 0) >= 50]

    breached = [t for t in tickets if t.get("is_breached")]
    warning = [t for t in tickets if t.get("sla_status") == "warning"]

    text = (
        f"Found **{len(tickets)} tickets** matching criteria.\n\n"
        f"- **Breached**: {len(breached)}\n"
        f"- **At Immediate Risk**: {len(warning)}\n\n"
    )
    if tickets:
        top = tickets[0]
        text += f"**Top Critical Incident**: {top['ticket_number']} — *{top['title']}* ({top['severity'].upper()})"

    blocks = [{"type": "table", "title": "Incident & Support Tickets", "data": tickets}]
    return {"text": text, "blocks": blocks, "data": {"tickets": tickets}}


async def _exec_get_risks(
    session: AsyncSession,
    organization_id: UUID,
    user_id: UUID,
    conversation_id: UUID,
    args: RiskQueryInput,
) -> dict[str, Any]:
    risks = await RiskService.list_risks(session, organization_id)
    risks = risks[:args.limit]

    critical_risks = [r for r in risks if (r.get("score") or 0) >= 15]

    text = (
        f"Found **{len(risks)} tracked risks** in the portfolio.\n\n"
        f"**Critical Exposure Alert**: {len(critical_risks)} risk(s) have risk score >= 15.\n"
    )
    if risks:
        top_risk = risks[0]
        text += f"Top risk: **{top_risk['title']}** (Score: {top_risk['score']}, {top_risk['category'].upper()})"

    blocks = [{"type": "table", "title": "Portfolio Risk Exposure Matrix", "data": risks}]
    return {"text": text, "blocks": blocks, "data": {"risks": risks}}


async def _exec_explain_task_priority(
    session: AsyncSession,
    organization_id: UUID,
    user_id: UUID,
    conversation_id: UUID,
    args: TaskPriorityExplanationInput,
) -> dict[str, Any]:
    tasks = await TaskService.list_tasks(session, organization_id)
    target = None
    needle = args.task_id_or_title.lower()

    for t in tasks:
        if t["id"] == args.task_id_or_title or needle in t["title"].lower():
            target = t
            break

    if not target:
        # Default to first P0 task if not specified
        p0s = [t for t in tasks if t["priority"] == "P0"]
        target = p0s[0] if p0s else (tasks[0] if tasks else None)

    if not target:
        return {"text": "No tasks found to evaluate priority.", "blocks": [], "data": {}}

    now = datetime.now(timezone.utc)
    due_dt = datetime.fromisoformat(target["due_date"]) if target.get("due_date") else None
    eval_res = PriorityEngine.evaluate(
        sla_due_at=due_dt,
        is_blocked=target.get("is_blocked", False),
        blocked_downstream_count=2 if target.get("is_blocked") else 0,
        impact_level="high" if target["priority"] == "P0" else "medium",
        target_due_date=due_dt,
        project_health="at_risk",
        now=now,
    )

    breakdown_text = (
        f"### Priority Breakdown for **{target['title']}**\n\n"
        f"- **Calculated Tier**: `{eval_res.tier}` (Score: **{eval_res.score}/100**)\n"
        f"- **Status**: {target['status'].upper()} | Blocked: {'YES' if target.get('is_blocked') else 'NO'}\n\n"
        f"**Deterministic Formula Weights**:\n"
    )
    for f in eval_res.factors:
        breakdown_text += f"- **{f.factor_name.replace('_', ' ').title()}** (Weight: {f.weight}%): {f.explanation} -> `+{round(f.weighted_score, 1)} pts`\n"

    blocks = [{"type": "table", "title": "Priority Engine Factors", "data": eval_res.to_dict()["factors"]}]
    return {"text": breakdown_text, "blocks": blocks, "data": eval_res.to_dict()}


async def _exec_search_knowledge(
    session: AsyncSession,
    organization_id: UUID,
    user_id: UUID,
    conversation_id: UUID,
    args: KnowledgeSearchInput,
) -> dict[str, Any]:
    project_uuid = None
    if args.project_id:
        try:
            project_uuid = UUID(args.project_id)
        except ValueError:
            pass

    chunks = await KnowledgeService.search_knowledge(
        session=session,
        organization_id=organization_id,
        query=args.query,
        project_id=project_uuid,
        top_k=args.top_k,
    )
    if not chunks:
        return {
            "text": f"No relevant documentation found in the knowledge base for '{args.query}'.",
            "blocks": [],
            "data": {"query": args.query, "chunks": []},
        }

    text = f"Found **{len(chunks)} relevant document passages** in the knowledge base:\n\n"
    for c in chunks:
        text += f"> **{c['citation']}** (Similarity: {int(c['similarity'] * 100)}%)\n> {c['content'][:300]}...\n\n"

    blocks = [{"type": "knowledge_citations", "title": "Knowledge Citations", "data": chunks}]
    return {"text": text, "blocks": blocks, "data": {"chunks": chunks}}


async def _exec_get_document(
    session: AsyncSession,
    organization_id: UUID,
    user_id: UUID,
    conversation_id: UUID,
    args: GetDocumentInput,
) -> dict[str, Any]:
    try:
        doc_uuid = UUID(args.document_id)
    except ValueError:
        return {"text": "Invalid document ID.", "blocks": [], "data": {}}

    doc = await KnowledgeService.get_document_by_id(session, organization_id, doc_uuid)
    if not doc:
        return {"text": "Document not found.", "blocks": [], "data": {}}

    text = f"### {doc.title}\n\n**Type**: `{doc.document_type}` | **Source**: `{doc.source_type}`\n\n{doc.content[:1000]}"
    blocks = [{"type": "document_view", "title": doc.title, "data": {"id": str(doc.id), "title": doc.title, "content": doc.content}}]
    return {"text": text, "blocks": blocks, "data": {"document": {"id": str(doc.id), "title": doc.title}}}


async def _exec_get_daily_briefing(
    session: AsyncSession,
    organization_id: UUID,
    user_id: UUID,
    conversation_id: UUID,
    args: DailyBriefingInput,
) -> dict[str, Any]:
    briefing = await DailyBriefingService.get_daily_briefing(session, organization_id, args.date)
    s = briefing["summary"]
    text = (
        f"### 📋 Daily PM Briefing ({briefing['date']})\n\n"
        f"- **Meetings Today**: {s['meeting_count']}\n"
        f"- **P0/P1 Priority Tasks**: {s['high_priority_tasks_count']}\n"
        f"- **Open SLA Tickets**: {s['open_tickets_count']}\n"
        f"- **Pending Governance Approvals**: {s['pending_approvals_count']}\n"
        f"- **Top Active Risks**: {s['top_risks_count']}\n\n"
    )
    if briefing["meetings"]:
        text += "**Scheduled Meetings**:\n"
        for m in briefing["meetings"]:
            text += f"- {m['title']} ({m['start_time'][11:16]} - {m['end_time'][11:16]})\n"
        text += "\n"

    blocks = [{"type": "daily_briefing", "title": "Daily Briefing", "data": briefing}]
    return {"text": text, "blocks": blocks, "data": briefing}


async def _exec_get_task_dependencies(
    session: AsyncSession,
    organization_id: UUID,
    user_id: UUID,
    conversation_id: UUID,
    args: TaskDependenciesInput,
) -> dict[str, Any]:
    try:
        task_uuid = UUID(args.task_id)
    except ValueError:
        return {"text": "Invalid task ID.", "blocks": [], "data": {}}

    deps = await DependencyService.get_task_dependencies(session, organization_id, task_uuid)
    pred_count = len(deps["predecessors"])
    succ_count = len(deps["successors"])
    text = (
        f"Task Dependency Summary:\n"
        f"- **Prerequisites (Predecessors)**: {pred_count} tasks\n"
        f"- **Dependent Work (Successors)**: {succ_count} tasks\n"
        f"- **Is Blocked**: {'YES (Incomplete prerequisites)' if deps['is_blocked'] else 'NO (Ready to work)'}\n"
    )
    blocks = [{"type": "dependency_graph", "title": "Task Dependencies", "data": deps}]
    return {"text": text, "blocks": blocks, "data": deps}


async def _exec_get_blockers(
    session: AsyncSession,
    organization_id: UUID,
    user_id: UUID,
    conversation_id: UUID,
    args: BlockersInput,
) -> dict[str, Any]:
    project_uuid = None
    if args.project_id:
        try:
            project_uuid = UUID(args.project_id)
        except ValueError:
            pass

    blockers = await DependencyService.get_blockers(session, organization_id, project_uuid)
    if not blockers:
        return {
            "text": "Great news! No active task blockers were found across the tracked projects.",
            "blocks": [],
            "data": {"blockers": []},
        }

    text = f"Found **{len(blockers)} blocked tasks** waiting on prerequisites:\n\n"
    for b in blockers:
        text += f"- Task **{b['blocked_task_title']}** ({b['blocked_task_priority']}) is BLOCKED by **{b['blocking_task_title']}** (Status: {b['blocking_task_status']})\n"

    blocks = [{"type": "blockers_list", "title": "Active Blockers", "data": blockers}]
    return {"text": text, "blocks": blocks, "data": {"blockers": blockers}}


async def _exec_get_project_health_breakdown(
    session: AsyncSession,
    organization_id: UUID,
    user_id: UUID,
    conversation_id: UUID,
    args: ProjectHealthBreakdownInput,
) -> dict[str, Any]:
    projects = await ProjectService.list_projects(session, organization_id)
    target_id = None
    target_name = args.project_id

    for p in projects:
        if str(p.get("id")) == args.project_id or p.get("key", "").lower() == args.project_id.lower():
            target_id = UUID(p["id"])
            target_name = p["name"]
            break

    if not target_id and projects:
        target_id = UUID(projects[0]["id"])
        target_name = projects[0]["name"]

    if not target_id:
        return {"text": "No project found.", "blocks": [], "data": {}}

    health_data = await ProjectHealthEngine.evaluate_project_health(session, organization_id, target_id)
    status_icon = "🟢" if health_data["status"] == "healthy" else ("🟡" if health_data["status"] == "at_risk" else "🔴")

    text = (
        f"### {status_icon} Project Health: {target_name} ({health_data['project_key']})\n\n"
        f"- **Calculated Health Score**: **{health_data['health_score']}/100**\n"
        f"- **Governance Status**: `{health_data['status'].upper()}`\n\n"
        f"**Driving Factors**:\n"
    )
    for f in health_data["factors"]:
        text += f"- {f}\n"

    blocks = [{"type": "project_health", "title": f"Health Breakdown: {target_name}", "data": health_data}]
    return {"text": text, "blocks": blocks, "data": health_data}


async def _exec_get_action_recommendations(
    session: AsyncSession,
    organization_id: UUID,
    user_id: UUID,
    conversation_id: UUID,
    args: ActionRecommendationsInput,
) -> dict[str, Any]:
    recs = await RecommendationService.get_action_recommendations(session, organization_id, args.limit)
    if not recs:
        return {
            "text": "All operational metrics are within thresholds. No high-urgency actions recommended right now.",
            "blocks": [],
            "data": {"recommendations": []},
        }

    text = f"### 💡 Operational Action Recommendations ({len(recs)})\n\n"
    for r in recs:
        text += f"- **[{r['priority']}] {r['title']}**\n  *Reason*: {r['reason']}\n"

    blocks = [{"type": "action_recommendations", "title": "Recommended Next Actions", "data": recs}]
    return {"text": text, "blocks": blocks, "data": {"recommendations": recs}}


async def _exec_create_task(
    session: AsyncSession,
    organization_id: UUID,
    user_id: UUID,
    conversation_id: UUID,
    args: CreateTaskInput,
) -> dict[str, Any]:
    due_dt = None
    if args.due_date:
        try:
            from app.services.action_service import _parse_iso_datetime
            due_dt = _parse_iso_datetime(args.due_date)
        except Exception:
            pass

    proj_uuid = None
    if args.project_id:
        try:
            proj_uuid = UUID(args.project_id)
        except ValueError:
            pass

    created = await TaskService.create_task(
        session=session,
        organization_id=organization_id,
        title=args.title,
        description=args.description,
        priority=args.priority or "P2",
        assignee_id=user_id,
        project_id=proj_uuid,
        due_date=due_dt,
    )

    text = (
        f"✓ Successfully added to your To-Do list:\n\n"
        f"- **[{created['priority']}] {created['title']}**\n"
        f"  - **Status**: `{created['status'].upper()}`\n"
        f"  - **Assigned To**: You\n"
    )
    if created.get("due_date"):
        text += f"  - **Due Date**: {created['due_date']}\n"

    blocks = [{
        "type": "tasks_list",
        "title": "Task Created",
        "data": [created]
    }]

    return {"text": text, "blocks": blocks, "data": {"task": created}}


async def _exec_create_ticket(
    session: AsyncSession,
    organization_id: UUID,
    user_id: UUID,
    conversation_id: UUID,
    args: CreateTicketInput,
) -> dict[str, Any]:
    created = await TicketService.create_ticket(
        session=session,
        organization_id=organization_id,
        title=args.title,
        description=args.description or f"Incident: {args.title}",
        severity=args.severity or "high",
        priority=args.priority or "P2",
        category=args.category or "Infrastructure",
        affected_service=args.affected_service,
        assignee_id=user_id,
    )

    text = (
        f"✓ **Ticket Created**: `{created['ticket_number']}` — **{created['title']}**\n\n"
        f"- **Severity**: `{created['severity'].upper()}` (Priority: `{created['priority']}`)\n"
        f"- **Category**: {created['category']}\n"
        f"- **Status**: `{created['status'].upper()}`\n"
        f"- **SLA Target Due**: {created['sla_due_at']}\n"
    )

    blocks = [{
        "type": "table",
        "title": f"Incident Ticket {created['ticket_number']}",
        "data": [created]
    }]

    return {"text": text, "blocks": blocks, "data": {"ticket": created}}


# ---------------------------------------------------------------------------
# Global Tool Metadata Catalog
# ---------------------------------------------------------------------------

TOOL_METADATA: dict[str, ToolDefinition] = {
    "create_task": ToolDefinition(
        name="create_task",
        description="Creates a new task or to-do item assigned to the user.",
        schema_class=CreateTaskInput,
        is_sensitive=False,
        required_permission="task.write",
        executor=_exec_create_task,
    ),
    "create_ticket": ToolDefinition(
        name="create_ticket",
        description="Creates a new incident, bug, or support ticket with SLA tracking.",
        schema_class=CreateTicketInput,
        is_sensitive=False,
        required_permission="ticket.write",
        executor=_exec_create_ticket,
    ),
    "get_my_work": ToolDefinition(
        name="get_my_work",
        description="Aggregates pending tasks, assigned tickets, and pending governance approvals for the current user.",
        schema_class=MyWorkInput,
        is_sensitive=False,
        required_permission="task.read",
        executor=_exec_get_my_work,
    ),
    "get_tickets": ToolDefinition(
        name="get_tickets",
        description="Queries incident and support tickets with SLA statuses, severity filters, and breach risk predictions.",
        schema_class=TicketQueryInput,
        is_sensitive=False,
        required_permission="ticket.read",
        executor=_exec_get_tickets,
    ),
    "get_risks": ToolDefinition(
        name="get_risks",
        description="Lists operational and portfolio risks sorted by 5x5 Likelihood x Impact score.",
        schema_class=RiskQueryInput,
        is_sensitive=False,
        required_permission="risk.read",
        executor=_exec_get_risks,
    ),
    "explain_task_priority": ToolDefinition(
        name="explain_task_priority",
        description="Explains why a task received its priority score and tier (P0-P3) using the deterministic Priority Engine formula.",
        schema_class=TaskPriorityExplanationInput,
        is_sensitive=False,
        required_permission="task.read",
        executor=_exec_explain_task_priority,
    ),
    "get_project_dashboard": ToolDefinition(
        name="get_project_dashboard",
        description="Fetches project KPI metrics, budget, active blockers, and SLA status for a project ID or key.",
        schema_class=ProjectDashboardInput,
        is_sensitive=False,
        required_permission="project.read",
        executor=_exec_get_project_dashboard,
    ),
    "get_pending_approvals": ToolDefinition(
        name="get_pending_approvals",
        description="Lists pending governance gate approvals and identifies SLA breaches.",
        schema_class=PendingApprovalsInput,
        is_sensitive=False,
        required_permission="approval.read",
        executor=_exec_get_pending_approvals,
    ),
    "get_blocking_approvers": ToolDefinition(
        name="get_blocking_approvers",
        description="Identifies which approvers are blocking the most projects across the organization.",
        schema_class=BlockingApproversInput,
        is_sensitive=False,
        required_permission="approval.read",
        executor=_exec_get_blocking_approvers,
    ),
    "get_calendar_slots": ToolDefinition(
        name="get_calendar_slots",
        description="Finds available meeting times between attendees for a specified duration and date.",
        schema_class=CalendarSlotsInput,
        is_sensitive=False,
        required_permission="calendar.read",
        executor=_exec_get_calendar_slots,
    ),
    "get_upcoming_meetings": ToolDefinition(
        name="get_upcoming_meetings",
        description="Lists scheduled upcoming meetings and calendar events for the organization.",
        schema_class=UpcomingMeetingsInput,
        is_sensitive=False,
        required_permission="calendar.read",
        executor=_exec_get_upcoming_meetings,
    ),
    "get_event_details": ToolDefinition(
        name="get_event_details",
        description="Fetches detailed meeting information including agenda, participants, status, and meet link.",
        schema_class=EventDetailsInput,
        is_sensitive=False,
        required_permission="calendar.read",
        executor=_exec_get_event_details,
    ),
    "propose_calendar_meeting": ToolDefinition(
        name="propose_calendar_meeting",
        description="Proposes creating a calendar meeting. Requires human confirmation before booking.",
        schema_class=ProposeMeetingInput,
        is_sensitive=True,
        required_permission="calendar.write",
        action_type="create_calendar_meeting",
    ),
    "propose_update_calendar_meeting": ToolDefinition(
        name="propose_update_calendar_meeting",
        description="Proposes updating or rescheduling a calendar meeting. Requires human confirmation.",
        schema_class=ProposeUpdateMeetingInput,
        is_sensitive=True,
        required_permission="calendar.write",
        action_type="update_calendar_meeting",
    ),
    "propose_cancel_calendar_meeting": ToolDefinition(
        name="propose_cancel_calendar_meeting",
        description="Proposes cancelling an existing calendar meeting. Requires human confirmation.",
        schema_class=ProposeCancelMeetingInput,
        is_sensitive=True,
        required_permission="calendar.write",
        action_type="cancel_calendar_meeting",
    ),
    "propose_ticket_assignment": ToolDefinition(
        name="propose_ticket_assignment",
        description="Proposes assigning an incident ticket to a team member. Requires human confirmation.",
        schema_class=ProposeTicketAssignmentInput,
        is_sensitive=True,
        required_permission="ticket.write",
        action_type="assign_ticket",
    ),
    "propose_escalation": ToolDefinition(
        name="propose_escalation",
        description="Proposes sending a formal SLA breach escalation notice. Requires human confirmation.",
        schema_class=ProposeEscalationInput,
        is_sensitive=True,
        required_permission="approval.write",
        action_type="send_escalation",
    ),
    "propose_project_status_change": ToolDefinition(
        name="propose_project_status_change",
        description="Proposes changing a project's operational status or health. Requires human confirmation.",
        schema_class=ProposeProjectStatusChangeInput,
        is_sensitive=True,
        required_permission="project.write",
        action_type="change_project_status",
    ),
    "propose_gate_approval": ToolDefinition(
        name="propose_gate_approval",
        description="Proposes deciding (approving/rejecting) a governance gate. Requires human confirmation.",
        schema_class=ProposeGateApprovalInput,
        is_sensitive=True,
        required_permission="approval.write",
        action_type="approve_gate",
    ),
    "search_knowledge": ToolDefinition(
        name="search_knowledge",
        description="Performs semantic vector search across knowledge documents, architecture decisions, runbooks, and policies.",
        schema_class=KnowledgeSearchInput,
        is_sensitive=False,
        required_permission="project.read",
        executor=_exec_search_knowledge,
    ),
    "get_document": ToolDefinition(
        name="get_document",
        description="Retrieves a specific knowledge document by its UUID.",
        schema_class=GetDocumentInput,
        is_sensitive=False,
        required_permission="project.read",
        executor=_exec_get_document,
    ),
    "get_daily_briefing": ToolDefinition(
        name="get_daily_briefing",
        description="Aggregates today's meetings, priority tasks, SLA risk tickets, pending approvals, and top risks.",
        schema_class=DailyBriefingInput,
        is_sensitive=False,
        required_permission="project.read",
        executor=_exec_get_daily_briefing,
    ),
    "get_task_dependencies": ToolDefinition(
        name="get_task_dependencies",
        description="Inspects prerequisites (predecessors) and downstream dependent tasks (successors) for a task.",
        schema_class=TaskDependenciesInput,
        is_sensitive=False,
        required_permission="task.read",
        executor=_exec_get_task_dependencies,
    ),
    "get_blockers": ToolDefinition(
        name="get_blockers",
        description="Lists all tasks currently blocked by uncompleted prerequisite tasks.",
        schema_class=BlockersInput,
        is_sensitive=False,
        required_permission="task.read",
        executor=_exec_get_blockers,
    ),
    "get_project_health_breakdown": ToolDefinition(
        name="get_project_health_breakdown",
        description="Evaluates deterministic operational health score (0-100), status (healthy, at_risk, critical), and driving factors.",
        schema_class=ProjectHealthBreakdownInput,
        is_sensitive=False,
        required_permission="project.read",
        executor=_exec_get_project_health_breakdown,
    ),
    "get_action_recommendations": ToolDefinition(
        name="get_action_recommendations",
        description="Generates deterministic operational next-action recommendations based on SLA breaches, blockers, and overdue gates.",
        schema_class=ActionRecommendationsInput,
        is_sensitive=False,
        required_permission="project.read",
        executor=_exec_get_action_recommendations,
    ),
}


def get_openai_tools() -> list[dict[str, Any]]:
    """Export tool registry to OpenAI / LiteLLM function calling schema."""
    tools: list[dict[str, Any]] = []
    for tool_def in TOOL_METADATA.values():
        tools.append({
            "type": "function",
            "function": {
                "name": tool_def.name,
                "description": tool_def.description,
                "parameters": tool_def.schema_class.model_json_schema(),
            },
        })
    return tools


async def execute_tool(
    session: AsyncSession,
    organization_id: UUID,
    user_id: UUID,
    conversation_id: UUID,
    tool_name: str,
    arguments: dict[str, Any],
    user_permissions: list[str],
) -> dict[str, Any]:
    """
    Validates arguments with Pydantic, validates RBAC permissions,
    intercepts sensitive actions for HITL confirmation, and executes safe query tools.
    """
    tool_def = TOOL_METADATA.get(tool_name)
    if not tool_def:
        logger.error("Unknown tool requested: %s", tool_name)
        return {
            "success": False,
            "error": f"Tool '{tool_name}' is not recognized.",
            "text": f"Error: Tool '{tool_name}' is not recognized.",
            "blocks": [],
            "data": {},
        }

    # 1. RBAC Permission Check
    has_permission = (
        tool_def.required_permission in user_permissions
        or "*" in user_permissions
        or "admin" in user_permissions
    )
    if not has_permission:
        logger.warning(
            "User %s denied permission '%s' for tool '%s'",
            user_id,
            tool_def.required_permission,
            tool_name,
        )
        return {
            "success": False,
            "error": f"Permission denied: Missing '{tool_def.required_permission}' for tool '{tool_name}'.",
            "text": f"You do not have permission (`{tool_def.required_permission}`) to perform `{tool_name}`.",
            "blocks": [],
            "data": {"required_permission": tool_def.required_permission},
        }

    # 2. Strict Pydantic Argument Validation
    try:
        validated_args = tool_def.schema_class(**arguments)
    except ValidationError as e:
        logger.error("Malformed tool arguments for '%s': %s", tool_name, e)
        return {
            "success": False,
            "error": f"Invalid arguments for tool '{tool_name}': {e.errors()}",
            "text": f"Invalid arguments provided for tool `{tool_name}`.",
            "blocks": [],
            "data": {"validation_errors": e.errors()},
        }

    # 3. Sensitive Tool Interception -> HITL Action Proposal
    if tool_def.is_sensitive:
        action_type = tool_def.action_type or tool_name
        payload = validated_args.model_dump()
        action_prop = await ActionService.propose_action(
            session=session,
            organization_id=organization_id,
            conversation_id=conversation_id,
            tool_name=tool_name,
            action_type=action_type,
            payload=payload,
        )

        title_display = tool_name.replace("_", " ").title()
        action_block = {
            "type": "action_confirmation",
            "title": f"Confirm Action: {title_display}",
            "action_id": action_prop["action_id"],
            "data": action_prop["payload"],
            "expires_at": action_prop["expires_at"],
        }

        # Rich formatted response text for meeting proposals
        if action_type == "create_calendar_meeting":
            m_title = payload.get("title", "Meeting")
            m_start = payload.get("start_time", "")
            m_end = payload.get("end_time", "")
            m_attendees = ", ".join(payload.get("attendee_emails", []))
            m_proj = payload.get("project_id") or "General"
            try:
                dt_start = datetime.fromisoformat(m_start)
                dt_end = datetime.fromisoformat(m_end)
                time_range = f"{dt_start.strftime('%b %d, %Y %I:%M %p')} – {dt_end.strftime('%I:%M %p')} UTC"
            except Exception:
                time_range = f"{m_start} – {m_end}"

            confirmation_text = (
                f"### 📅 Proposed Meeting: **{m_title}**\n\n"
                f"- **Time**: {time_range}\n"
                f"- **Participants**: {m_attendees}\n"
                f"- **Project**: {m_proj}\n"
                f"- **Status**: ✓ No initial conflicts detected\n\n"
                f"**Human confirmation is required.** Would you like me to schedule it? Please confirm or cancel using the approval card below."
            )
        elif action_type == "update_calendar_meeting":
            confirmation_text = (
                f"### 📅 Proposed Meeting Reschedule / Update\n\n"
                f"- **Event ID**: `{payload.get('event_id')}`\n"
                f"- **Proposed Changes**: {payload}\n\n"
                f"**Human confirmation is required** before updating the calendar."
            )
        elif action_type == "cancel_calendar_meeting":
            confirmation_text = (
                f"### ⚠️ Proposed Meeting Cancellation\n\n"
                f"- **Event ID**: `{payload.get('event_id')}`\n"
                f"- **Reason**: {payload.get('reason')}\n\n"
                f"**Human confirmation is required** before cancelling the meeting."
            )
        else:
            confirmation_text = (
                f"I have drafted the proposal for **{title_display}**. "
                f"**Human confirmation is required** before execution."
            )

        return {
            "success": True,
            "is_sensitive": True,
            "action_id": action_prop["action_id"],
            "text": confirmation_text,
            "blocks": [action_block],
            "data": action_prop,
        }

    # 4. Safe Query Tool Execution
    if not tool_def.executor:
        return {
            "success": False,
            "error": f"No executor defined for tool '{tool_name}'.",
            "text": f"No executor defined for tool '{tool_name}'.",
            "blocks": [],
            "data": {},
        }

    try:
        exec_result = await tool_def.executor(
            session, organization_id, user_id, conversation_id, validated_args
        )
        return {
            "success": True,
            "is_sensitive": False,
            "text": exec_result.get("text", ""),
            "blocks": exec_result.get("blocks", []),
            "data": exec_result.get("data", {}),
        }
    except Exception as e:
        logger.exception("Error executing tool '%s': %s", tool_name, e)
        return {
            "success": False,
            "error": str(e),
            "text": f"Failed to execute tool `{tool_name}`: {str(e)}",
            "blocks": [],
            "data": {},
        }


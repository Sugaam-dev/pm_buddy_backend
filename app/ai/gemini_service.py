import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID
import google.generativeai as genai
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.tools import TOOL_METADATA, execute_tool
from app.core.config import settings

logger = logging.getLogger(__name__)

# Fallback/Direct Gemini API key
DEFAULT_GEMINI_KEY = ""
default_gemini_key = os.environ.get("GEMINI_API_KEY") or getattr(settings, "GEMINI_API_KEY", None) or DEFAULT_GEMINI_KEY

PM_BUDDY_SYSTEM_PROMPT = (
    "You are PM Buddy, an AI Operational Intelligence and Governance partner for engineering teams. "
    "You assist Project Managers, CTOs, Team Leads, and Engineers with project tracking, incident handling, meeting scheduling, and organizational knowledge retrieval. "
    "You have access to tools for querying tasks, tickets, risks, governance approvals, calendar availability, task dependencies, operational briefings, project health, and knowledge base documents. "
    "CRITICAL RULES: "
    "1. Always use available tools to query factual operational data and knowledge documents. Never make up tasks, tickets, schedules, or architectural facts. "
    "2. RAG & Citations: When answering questions about architecture decisions, PRDs, runbooks, policies, or postmortems, use search_knowledge. Always ground your answer in retrieved citations (e.g. 'According to: Payment Architecture Decision — v2.1'). If the knowledge base does not contain the answer, explicitly state that evidence is insufficient. "
    "3. Daily Briefing & Health: Use get_daily_briefing for daily operational summaries and get_project_health_breakdown for deterministic project health scores. "
    "4. Task Dependencies: Use get_task_dependencies and get_blockers to analyze blockers and downstream impacts. "
    "5. Action Recommendations: Use get_action_recommendations to suggest high-leverage next steps. "
    "6. Calendar is a first-class module: use get_calendar_slots, get_upcoming_meetings, and get_event_details when asked about schedules or meetings. "
    "7. Human-in-the-Loop (HITL): Every mutation or sensitive action (proposing a meeting, updating/cancelling a meeting, assigning a ticket, escalating an approval, changing project status) MUST use the appropriate propose_* tool. It will trigger a human confirmation card with a 15-minute expiration. "
    "8. Format your responses with structured markdown, bullet points, and clear actionable takeaways."
)


# Python tool definitions with type annotations and docstrings for Gemini
def get_my_work(limit: int = 5) -> str:
    """Aggregates pending priority tasks, assigned tickets, and pending governance approvals for the current user."""
    return ""


def get_tickets(severity: str = "", status: str = "", at_risk_only: bool = False) -> str:
    """Queries incident and support tickets with SLA statuses, severity filters, and breach risk predictions."""
    return ""


def get_risks(limit: int = 10) -> str:
    """Lists operational and portfolio risks sorted by 5x5 Likelihood x Impact score."""
    return ""


def explain_task_priority(task_id_or_title: str) -> str:
    """Explains why a task received its priority score and tier (P0-P3) using the deterministic Priority Engine formula."""
    return ""


def get_project_dashboard(project_id: str) -> str:
    """Fetches project KPI metrics, budget, active blockers, and SLA status for a project ID or key (e.g. ALPHA)."""
    return ""


def get_pending_approvals(breached_only: bool = False) -> str:
    """Lists pending governance gate approvals and identifies SLA breaches."""
    return ""


def get_blocking_approvers() -> str:
    """Identifies which approvers are blocking the most projects across the organization."""
    return ""


def get_calendar_slots(attendee_emails: list[str], duration_minutes: int = 30, search_date: str = "") -> str:
    """Finds available conflict-free meeting times between attendees for a specified duration and date."""
    return ""


def get_upcoming_meetings(days_ahead: int = 7, project_id: str = "") -> str:
    """Lists scheduled upcoming meetings and calendar events for the organization."""
    return ""


def get_event_details(event_id: str) -> str:
    """Fetches detailed meeting information including agenda, participants, status, and meet link."""
    return ""


def propose_calendar_meeting(
    title: str,
    attendee_emails: list[str],
    start_time: str,
    end_time: str,
    description: str = "",
    project_id: str = "",
    location: str = "Google Meet",
    meeting_type: str = "general",
) -> str:
    """Proposes creating a calendar meeting. Requires human confirmation before booking."""
    return ""


def propose_update_calendar_meeting(
    event_id: str,
    title: str = "",
    start_time: str = "",
    end_time: str = "",
    attendees: list[str] = None,
    location: str = "",
) -> str:
    """Proposes updating or rescheduling a calendar meeting. Requires human confirmation."""
    return ""


def propose_cancel_calendar_meeting(
    event_id: str,
    reason: str = "Meeting cancelled via PM Buddy AI",
) -> str:
    """Proposes cancelling an existing calendar meeting. Requires human confirmation."""
    return ""


def propose_ticket_assignment(
    ticket_id: str,
    assignee_id: str,
    notes: str = "",
) -> str:
    """Proposes assigning an incident ticket to a team member. Requires human confirmation."""
    return ""


def propose_escalation(
    approval_id: str,
    escalate_to: str,
    reason: str,
) -> str:
    """Proposes sending a formal SLA breach escalation notice. Requires human confirmation."""
    return ""


def propose_project_status_change(
    project_id: str,
    status: str,
    health: str,
    reason: str,
) -> str:
    """Proposes changing a project operational status or health. Requires human confirmation."""
    return ""


def propose_gate_approval(
    approval_id: str,
    decision: str,
    notes: str = "",
) -> str:
    """Proposes deciding (approving/rejecting) a governance gate. Requires human confirmation."""
    return ""


def search_knowledge(query: str, project_id: str = "", top_k: int = 5) -> str:
    """Performs semantic vector search across knowledge base documentation, architecture decision records, runbooks, and policies. Use when user asks about architecture decisions, requirements, guidelines, or procedures."""
    return ""


def get_document(document_id: str) -> str:
    """Retrieves full content and metadata of a knowledge document by its UUID."""
    return ""


def get_daily_briefing(date: str = "") -> str:
    """Aggregates today's operational briefing: scheduled meetings, priority tasks, open SLA tickets, pending approvals, and top risks."""
    return ""


def get_task_dependencies(task_id: str) -> str:
    """Inspects task prerequisites (predecessors) and downstream dependent work (successors) to check if a task is blocked."""
    return ""


def get_blockers(project_id: str = "") -> str:
    """Lists all active task blockers and dependencies waiting on incomplete prerequisite tasks."""
    return ""


def get_project_health_breakdown(project_id: str) -> str:
    """Evaluates deterministic operational health score (0-100), status (healthy, at_risk, critical), and driving negative factors for a project."""
    return ""


def get_action_recommendations(limit: int = 5) -> str:
    """Provides prioritized, deterministic operational recommendations for high-leverage next actions (e.g. escalating breached tickets, unblocking tasks, approving overdue gates)."""
    return ""


ALL_GEMINI_TOOLS = [
    get_my_work,
    get_tickets,
    get_risks,
    explain_task_priority,
    get_project_dashboard,
    get_pending_approvals,
    get_blocking_approvers,
    get_calendar_slots,
    get_upcoming_meetings,
    get_event_details,
    propose_calendar_meeting,
    propose_update_calendar_meeting,
    propose_cancel_calendar_meeting,
    propose_ticket_assignment,
    propose_escalation,
    propose_project_status_change,
    propose_gate_approval,
    search_knowledge,
    get_document,
    get_daily_briefing,
    get_task_dependencies,
    get_blockers,
    get_project_health_breakdown,
    get_action_recommendations,
]


class GeminiService:
    """
    Direct Google Gemini Integration via the official google-generativeai SDK.
    Supports tool calling, multi-turn reasoning, RBAC enforcement, and HITL action interception.
    """

    _model: Optional[genai.GenerativeModel] = None
    _configured_key: Optional[str] = None

    @classmethod
    def get_api_key(cls) -> str:
        """Resolves the live Gemini API key from settings, env, or default."""
        return (
            os.environ.get("GEMINI_API_KEY")
            or getattr(settings, "GEMINI_API_KEY", None)
            or getattr(settings, "gemini_api_key", None)
            or os.environ.get("gemini_api_key")
            or DEFAULT_GEMINI_KEY
        )

    @classmethod
    def get_model(cls) -> genai.GenerativeModel:
        """Lazy-initializes the Gemini GenerativeModel with tools."""
        api_key = cls.get_api_key()
        if cls._model is None or cls._configured_key != api_key:
            genai.configure(api_key=api_key)
            cls._configured_key = api_key
            model_name = getattr(settings, "LLM_MODEL", "gemini-3.6-flash")
            if not model_name or "gemini" not in model_name:
                model_name = "gemini-3.6-flash"

            cls._model = genai.GenerativeModel(
                model_name=model_name,
                tools=ALL_GEMINI_TOOLS,
                system_instruction=PM_BUDDY_SYSTEM_PROMPT,
            )
            logger.info("Initialized direct Gemini GenerativeModel: %s", model_name)

        return cls._model

    @classmethod
    async def generate_response(
        cls,
        session: AsyncSession,
        organization_id: UUID,
        user_id: UUID,
        conversation_id: UUID,
        prompt: str,
        user_permissions: list[str],
    ) -> dict[str, Any]:
        """
        Executes a prompt against Gemini with dynamic tool calling and HITL interception.
        """
        model = cls.get_model()
        chat = model.start_chat(enable_automatic_function_calling=False)

        accumulated_blocks: list[dict[str, Any]] = []
        action_proposed = False

        # First turn: Send user prompt
        response = chat.send_message(prompt)

        # Loop up to 3 turns if tool calls are requested
        max_turns = 3
        current_turn = 0

        while current_turn < max_turns:
            current_turn += 1
            has_tool_call = False

            for part in response.parts:
                if fn_call := getattr(part, "function_call", None):
                    has_tool_call = True
                    tool_name = fn_call.name
                    # Convert protobuf MapComposite / RepeatedComposite to python dict
                    tool_args = {}
                    for k, v in fn_call.args.items():
                        if hasattr(v, "values"):  # list
                            tool_args[k] = list(v)
                        else:
                            tool_args[k] = v

                    logger.info("Gemini invoked tool '%s' with args %s", tool_name, tool_args)

                    # Execute tool via strict RBAC & HITL validation
                    tool_result = await execute_tool(
                        session=session,
                        organization_id=organization_id,
                        user_id=user_id,
                        conversation_id=conversation_id,
                        tool_name=tool_name,
                        arguments=tool_args,
                        user_permissions=user_permissions,
                    )

                    if tool_result.get("blocks"):
                        accumulated_blocks.extend(tool_result["blocks"])

                    # If sensitive HITL action was proposed, STOP turn and return proposal
                    if tool_result.get("is_sensitive"):
                        action_proposed = True
                        return {
                            "text": tool_result.get("text", "I have prepared the action proposal. Please review and confirm below."),
                            "blocks": accumulated_blocks,
                            "actions": [tool_result.get("data", {})],
                            "model": "gemini-3.6-flash",
                        }

                    # Feed tool execution result back to Gemini
                    result_summary = tool_result.get("text") or json.dumps(tool_result.get("data", {}))
                    response = chat.send_message(
                        genai.protos.Content(
                            parts=[
                                genai.protos.Part(
                                    function_response=genai.protos.FunctionResponse(
                                        name=tool_name,
                                        response={"result": result_summary},
                                    )
                                )
                            ]
                        )
                    )
                    break

            if not has_tool_call:
                break

        # Final text from model
        final_text = ""
        try:
            final_text = response.text
        except Exception:
            for part in response.parts:
                if hasattr(part, "text") and part.text:
                    final_text += part.text

        return {
            "text": final_text,
            "blocks": accumulated_blocks,
            "actions": [],
            "model": "gemini-3.6-flash",
        }

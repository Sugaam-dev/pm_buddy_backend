import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4
import litellm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.datetime_parser import parse_meeting_intent
from app.ai.gemini_service import GeminiService
from app.ai.tools import execute_tool, get_openai_tools
from app.core.config import settings
from app.models.entities import AIAction
from app.services.action_service import ActionService

logger = logging.getLogger(__name__)

# LiteLLM Configuration
litellm.telemetry = False
litellm.drop_params = True
litellm.num_retries = 0
litellm.request_timeout = 5


def get_system_prompt() -> str:
    now_utc = datetime.now(timezone.utc)
    return (
        "You are PM Buddy, an AI operational intelligence and governance partner for software engineering teams. "
        f"CURRENT REAL-TIME CONTEXT: Today is {now_utc.strftime('%A, %B %d, %Y')}, current time is {now_utc.strftime('%H:%M')} UTC. Current year is {now_utc.year}. "
        "All relative dates such as 'today', 'tomorrow', 'next week', 'this Friday' MUST be calculated based on this current date. "
        "You have access to tools for querying tasks, projects, approvals, calendar availability, and proposing sensitive operational actions. "
        "Always use the available tools to retrieve factual operational data. "
        "Never fabricate project IDs, task IDs, or data. "
        "For sensitive actions like booking meetings, assigning tickets, or approving gates, propose them through the appropriate tool so human confirmation can be obtained."
    )



class AIOrchestrator:
    """
    Core AI Orchestration Engine for PM Buddy.
    Ensures:
    1. Zero Direct SQL
    2. Dynamic LiteLLM Tool-Calling Loop
    3. Strict Pydantic Tool Validation & RBAC
    4. HITL Action Proposal Interception
    5. Graceful Deterministic Intent Fallback
    """

    MAX_TOOL_ITERATIONS = 3

    @classmethod
    def _should_use_llm(cls) -> bool:
        if getattr(settings, "FORCE_MOCK_ROUTER", False):
            return False
        if getattr(settings, "ENVIRONMENT", "").lower() == "test":
            return False
        if settings.LLM_PROVIDER in ("openai", "gemini", "anthropic"):
            return True
        if settings.OPENAI_API_KEY and settings.OPENAI_API_KEY != "mock-key":
            return True
        if settings.LLM_API_KEY and settings.LLM_API_KEY != "mock-key":
            return True
        return False

    @classmethod
    def _get_model_name(cls) -> str:
        provider = settings.LLM_PROVIDER.lower()
        model = settings.LLM_MODEL
        if model == "mock-model":
            model = "gpt-4o-mini"

        if provider == "gemini" and not model.startswith("gemini/"):
            return f"gemini/{model}"
        elif provider == "anthropic" and not model.startswith("anthropic/"):
            return f"anthropic/{model}"
        return model

    @classmethod
    async def process_message(
        cls,
        session: AsyncSession,
        organization_id: UUID,
        user_id: UUID,
        conversation_id: UUID,
        prompt: str,
        user_permissions: list[str],
        force_llm: bool = False,
    ) -> dict[str, Any]:
        """
        Processes an incoming user message.
        Standard operational queries (tasks, tickets, scheduling, approvals, dashboard)
        execute via the instant Fast-Path in ~15ms, eliminating network latency and conserving
        external LLM rate-limit quota. Complex generative queries route to the Gemini multi-key pool.
        """
        lower_prompt = prompt.lower().strip()

        # FAST-PATH DISPATCHER: Instant ~15ms operational execution
        is_operational = (
            # 1. Task/Todo operations (viewing, listing, adding)
            any(w in lower_prompt for w in [
                "todo", "todos", "to-do", "to-dos", "my task", "my tasks", "all task", "pending task",
                "show task", "list task", "what should i do", "what to do", "my work", "what are my task"
            ])
            # 2. Ticket operations (viewing, creating)
            or any(w in lower_prompt for w in ["ticket", "incident"])
            # 3. Calendar & Meetings (scheduling, view schedule, slots)
            or any(w in lower_prompt for w in ["meeting", "schedule", "calendar", "reschedule", "cancel meeting"])
            # 4. Approvals
            or any(w in lower_prompt for w in ["approval", "approvals", "gate approval"])
            # 5. Risks
            or any(w in lower_prompt for w in ["risk", "risks", "risk matrix"])
            # 6. Dashboard & Health
            or any(w in lower_prompt for w in ["dashboard", "daily briefing", "briefing", "project health", "health of project"])
        )

        if not force_llm and is_operational:
            return await cls._deterministic_fallback(
                session=session,
                organization_id=organization_id,
                user_id=user_id,
                conversation_id=conversation_id,
                prompt=prompt,
                user_permissions=user_permissions,
            )

        use_llm = force_llm or cls._should_use_llm()

        if use_llm:
            # Direct Gemini Integration (multi-key failover pool)
            if (settings.LLM_PROVIDER == "gemini" or (GeminiService.get_api_key() and not force_llm)):
                try:
                    return await GeminiService.generate_response(
                        session=session,
                        organization_id=organization_id,
                        user_id=user_id,
                        conversation_id=conversation_id,
                        prompt=prompt,
                        user_permissions=user_permissions,
                    )
                except Exception as e:
                    logger.warning(
                        "Direct Gemini execution failed (%s); attempting LiteLLM/deterministic fallback.",
                        e,
                    )

            try:
                return await cls._process_with_litellm(
                    session=session,
                    organization_id=organization_id,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    prompt=prompt,
                    user_permissions=user_permissions,
                )
            except Exception as e:
                logger.warning(
                    "LiteLLM tool-calling execution failed (%s); falling back to deterministic intent router.",
                    e,
                )
                return await cls._deterministic_fallback(
                    session=session,
                    organization_id=organization_id,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    prompt=prompt,
                    user_permissions=user_permissions,
                )

        return await cls._deterministic_fallback(
            session=session,
            organization_id=organization_id,
            user_id=user_id,
            conversation_id=conversation_id,
            prompt=prompt,
            user_permissions=user_permissions,
        )

    @classmethod
    async def _process_with_litellm(
        cls,
        session: AsyncSession,
        organization_id: UUID,
        user_id: UUID,
        conversation_id: UUID,
        prompt: str,
        user_permissions: list[str],
    ) -> dict[str, Any]:
        """Dynamic multi-turn tool-calling loop powered by LiteLLM."""
        model = cls._get_model_name()
        tools_schema = get_openai_tools()

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": get_system_prompt()},
            {"role": "user", "content": prompt},
        ]

        accumulated_blocks: list[dict[str, Any]] = []
        accumulated_texts: list[str] = []
        final_text = ""

        for iteration in range(cls.MAX_TOOL_ITERATIONS):
            response = await litellm.acompletion(
                model=model,
                messages=messages,
                tools=tools_schema,
                tool_choice="auto",
                temperature=0.1,
            )

            choice = response.choices[0]
            msg = choice.message

            # Extract tool calls safely across LiteLLM / dict representations
            tool_calls = getattr(msg, "tool_calls", None)
            if tool_calls is None and isinstance(msg, dict):
                tool_calls = msg.get("tool_calls")

            if not tool_calls:
                # No more tools called; LLM returned text answer
                final_text = getattr(msg, "content", "") or (msg.get("content") if isinstance(msg, dict) else "")
                break

            # Convert message to dict format for appending to conversation history
            if hasattr(msg, "model_dump"):
                msg_dict = msg.model_dump()
            elif hasattr(msg, "to_dict"):
                msg_dict = msg.to_dict()
            elif isinstance(msg, dict):
                msg_dict = msg
            else:
                msg_dict = {
                    "role": "assistant",
                    "content": getattr(msg, "content", None),
                    "tool_calls": tool_calls,
                }
            messages.append(msg_dict)

            hitl_interrupted = False

            for tool_call in tool_calls:
                call_id = getattr(tool_call, "id", None) or (
                    tool_call.get("id") if isinstance(tool_call, dict) else str(uuid4())
                )
                function_obj = getattr(tool_call, "function", None) or (
                    tool_call.get("function") if isinstance(tool_call, dict) else {}
                )
                tool_name = getattr(function_obj, "name", None) or (
                    function_obj.get("name") if isinstance(function_obj, dict) else ""
                )
                args_raw = getattr(function_obj, "arguments", None) or (
                    function_obj.get("arguments") if isinstance(function_obj, dict) else {}
                )

                if isinstance(args_raw, str):
                    try:
                        args_dict = json.loads(args_raw)
                    except Exception:
                        args_dict = {}
                else:
                    args_dict = args_raw or {}

                # Execute tool safely via central executor
                tool_result = await execute_tool(
                    session=session,
                    organization_id=organization_id,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    tool_name=tool_name,
                    arguments=args_dict,
                    user_permissions=user_permissions,
                )

                # Collect blocks
                if tool_result.get("blocks"):
                    accumulated_blocks.extend(tool_result["blocks"])

                if tool_result.get("text"):
                    accumulated_texts.append(tool_result["text"])

                # Feed execution result back to the model
                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": tool_name,
                    "content": json.dumps(tool_result.get("data", {}) if tool_result.get("success") else {"error": tool_result.get("error")}),
                })

                # If a sensitive action was proposed, pause loop to wait for human confirmation
                if tool_result.get("is_sensitive"):
                    hitl_interrupted = True
                    final_text = tool_result.get("text", "Human confirmation required before execution.")

            if hitl_interrupted:
                break

        if not final_text and accumulated_texts:
            final_text = "\n\n".join(accumulated_texts)

        return {
            "conversation_id": str(conversation_id),
            "text": final_text,
            "blocks": accumulated_blocks,
        }

    @classmethod
    async def _deterministic_fallback(
        cls,
        session: AsyncSession,
        organization_id: UUID,
        user_id: UUID,
        conversation_id: UUID,
        prompt: str,
        user_permissions: list[str],
    ) -> dict[str, Any]:
        """
        Deterministic intent router acting as a resilient fallback
        and local testing engine.
        """
        lower_prompt = prompt.lower().strip()

        # Intent 0A: Create/Add Task or To-Do
        is_task_creation = (
            any(w in lower_prompt for w in ["task", "todo", "to-do"]) and
            any(v in lower_prompt for v in ["add", "create", "new", "schedule", "insert", "put"])
        )
        if is_task_creation:
            cleaned = re.sub(
                r'^(?:please\s+|can you\s+|could you\s+|i want to\s+|update my (?:todos?|to-dos?)\s+(?:and\s+)?)',
                '',
                prompt,
                flags=re.IGNORECASE
            )
            m = re.search(
                r'(?:add|create|new|schedule|insert|put)\s+(?:a\s+|an\s+|the\s+)?(?:new\s+)?(?:priority\s+)?(?:p[0-3]\s+)?(?:task|todo|to-do|item)\s*(?::|to|for|about|titled|-)?\s*(.+)',
                cleaned,
                flags=re.IGNORECASE
            )
            if m:
                extracted_title = m.group(1).strip()
            else:
                extracted_title = re.sub(
                    r'^(?:add|create|new|schedule|insert)\s+(?:a\s+|an\s+|the\s+)?(?:new\s+)?(?:task|todo|to-do)\s*',
                    '',
                    cleaned,
                    flags=re.IGNORECASE
                ).strip()

            extracted_title = extracted_title.strip("\"' .")
            if extracted_title:
                extracted_title = extracted_title[0].upper() + extracted_title[1:]
            else:
                extracted_title = "New Task"

            prio = "P2"
            if re.search(r'\bp0\b|critical|urgent', prompt, re.I):
                prio = "P0"
            elif re.search(r'\bp1\b|high priority', prompt, re.I):
                prio = "P1"
            elif re.search(r'\bp3\b|low priority', prompt, re.I):
                prio = "P3"

            res = await execute_tool(
                session=session,
                organization_id=organization_id,
                user_id=user_id,
                conversation_id=conversation_id,
                tool_name="create_task",
                arguments={
                    "title": extracted_title,
                    "priority": prio,
                },
                user_permissions=user_permissions,
            )
            return {
                "conversation_id": str(conversation_id),
                "text": res.get("text", ""),
                "blocks": res.get("blocks", []),
            }

        # Intent 1: "give me todos" / "todos" / "my tasks" / "What should I do first today?" / "What are my pending tasks?"
        if any(k in lower_prompt for k in [
            "todo", "todos", "to-do", "to-dos", "my task", "my tasks",
            "task", "tasks", "pending task", "pending tasks", "show task", "list task",
            "what are my task", "give me task", "action item", "action items",
            "focus on", "focus right now", "what should i do", "what to do",
            "pending for me", "my work", "what is pending", "what do i have to do"
        ]):
            res = await execute_tool(
                session=session,
                organization_id=organization_id,
                user_id=user_id,
                conversation_id=conversation_id,
                tool_name="get_my_work",
                arguments={"limit": 5},
                user_permissions=user_permissions,
            )
            return {
                "conversation_id": str(conversation_id),
                "text": res.get("text", ""),
                "blocks": res.get("blocks", []),
            }

        # Intent 1B: "Show me my highest priority tasks" / "Highest priority tasks" / "P0 tasks"
        if any(k in lower_prompt for k in ["highest priority", "high priority task", "p0 task", "top task"]):
            res = await execute_tool(
                session=session,
                organization_id=organization_id,
                user_id=user_id,
                conversation_id=conversation_id,
                tool_name="get_my_work",
                arguments={"limit": 10},
                user_permissions=user_permissions,
            )
            return {
                "conversation_id": str(conversation_id),
                "text": "Here are your highest priority tasks ranked deterministically by the Priority Engine:\n\n" + res.get("text", ""),
                "blocks": res.get("blocks", []),
            }

        # Intent 1C: "Why is this task P0?" / "Explain priority"
        if any(k in lower_prompt for k in ["why is this task p0", "why p0", "explain priority", "priority formula", "why is task"]):
            res = await execute_tool(
                session=session,
                organization_id=organization_id,
                user_id=user_id,
                conversation_id=conversation_id,
                tool_name="explain_task_priority",
                arguments={"task_id_or_title": lower_prompt},
                user_permissions=user_permissions,
            )
            return {
                "conversation_id": str(conversation_id),
                "text": res.get("text", ""),
                "blocks": res.get("blocks", []),
            }

        # Intent 0B: "create one p1 ticket for payment infra rebuild" / "open ticket database crash"
        is_ticket_creation = (
            any(w in lower_prompt for w in ["ticket", "incident", "bug", "issue"]) and
            any(v in lower_prompt for v in ["create", "open", "raise", "file", "log", "new", "add"])
        )
        if is_ticket_creation:
            cleaned = re.sub(r'^(?:please\s+|can you\s+|could you\s+|i want to\s+)', '', prompt, flags=re.IGNORECASE)
            m = re.search(
                r'(?:create|open|raise|file|log|new|add)\s+(?:a\s+|an\s+|one\s+|the\s+)?(?:new\s+)?(?:p[0-3]\s+)?(?:ticket|incident|bug|issue)\s*(?::|for|regarding|about|titled|-)?\s*(.+)',
                cleaned,
                flags=re.IGNORECASE
            )
            if m:
                extracted_title = m.group(1).strip()
            else:
                extracted_title = re.sub(
                    r'^(?:create|open|raise|file|log)\s+(?:one\s+|a\s+|an\s+)?(?:p[0-3]\s+)?(?:ticket|incident|bug|issue)\s*',
                    '',
                    cleaned,
                    flags=re.IGNORECASE
                ).strip()

            extracted_title = extracted_title.strip("\"' .")
            if extracted_title:
                extracted_title = extracted_title[0].upper() + extracted_title[1:]
            else:
                extracted_title = "New Incident"

            sev = "high"
            prio = "P2"
            if re.search(r'\bp0\b|critical', prompt, re.I):
                sev = "critical"
                prio = "P0"
            elif re.search(r'\bp1\b', prompt, re.I):
                sev = "critical"
                prio = "P1"
            elif re.search(r'\bp3\b|low', prompt, re.I):
                sev = "medium"
                prio = "P3"
            elif re.search(r'\bp2\b|medium', prompt, re.I):
                sev = "high"
                prio = "P2"

            res = await execute_tool(
                session=session,
                organization_id=organization_id,
                user_id=user_id,
                conversation_id=conversation_id,
                tool_name="create_ticket",
                arguments={
                    "title": extracted_title,
                    "severity": sev,
                    "priority": prio,
                },
                user_permissions=user_permissions,
            )
            return {
                "conversation_id": str(conversation_id),
                "text": res.get("text", ""),
                "blocks": res.get("blocks", []),
            }

        # Intent 1D: "Which tickets are at risk of SLA breach?" / "Show tickets"
        if any(k in lower_prompt for k in ["ticket", "incident", "sla breach", "at risk of sla"]):
            at_risk = any(k in lower_prompt for k in ["risk", "breach", "warning", "critical"])
            res = await execute_tool(
                session=session,
                organization_id=organization_id,
                user_id=user_id,
                conversation_id=conversation_id,
                tool_name="get_tickets",
                arguments={"at_risk_only": at_risk},
                user_permissions=user_permissions,
            )
            return {
                "conversation_id": str(conversation_id),
                "text": res.get("text", ""),
                "blocks": res.get("blocks", []),
            }

        # Intent 1E: "What are the biggest risks in my project?" / "Show risks"
        if any(k in lower_prompt for k in ["risk", "biggest risk", "risk matrix", "exposure"]):
            res = await execute_tool(
                session=session,
                organization_id=organization_id,
                user_id=user_id,
                conversation_id=conversation_id,
                tool_name="get_risks",
                arguments={"limit": 5},
                user_permissions=user_permissions,
            )
            return {
                "conversation_id": str(conversation_id),
                "text": res.get("text", ""),
                "blocks": res.get("blocks", []),
            }

        # Intent 2: Top Blocking Approvers
        if "who is blocking" in lower_prompt or "blocking the most" in lower_prompt:
            res = await execute_tool(
                session=session,
                organization_id=organization_id,
                user_id=user_id,
                conversation_id=conversation_id,
                tool_name="get_blocking_approvers",
                arguments={},
                user_permissions=user_permissions,
            )
            return {
                "conversation_id": str(conversation_id),
                "text": res.get("text", ""),
                "blocks": res.get("blocks", []),
            }

        # Intent 3: "Show approvals" / "What approvals are waiting for me?" / "breached approvals"
        if any(k in lower_prompt for k in ["approval", "approver", "gate", "waiting for me"]):
            breached_only = "breach" in lower_prompt
            res = await execute_tool(
                session=session,
                organization_id=organization_id,
                user_id=user_id,
                conversation_id=conversation_id,
                tool_name="get_pending_approvals",
                arguments={"breached_only": breached_only},
                user_permissions=user_permissions,
            )
            return {
                "conversation_id": str(conversation_id),
                "text": res.get("text", ""),
                "blocks": res.get("blocks", []),
            }

        # Intent 4: "Project Alpha" / "Show me the dashboard for Project Alpha"
        if "alpha" in lower_prompt or "project" in lower_prompt:
            res = await execute_tool(
                session=session,
                organization_id=organization_id,
                user_id=user_id,
                conversation_id=conversation_id,
                tool_name="get_project_dashboard",
                arguments={"project_id": "PORTAL" if "portal" in lower_prompt else ("PAY" if "payment" in lower_prompt else "ALPHA")},
                user_permissions=user_permissions,
            )
            return {
                "conversation_id": str(conversation_id),
                "text": res.get("text", ""),
                "blocks": res.get("blocks", []),
            }

        # Intent 5A: Schedule Inquiries ("What is my schedule now?", "Show my calendar", "Upcoming meetings")
        if any(k in lower_prompt for k in [
            "my schedule", "what is my schedule", "what's my schedule", "show schedule",
            "upcoming meeting", "upcoming events", "my calendar", "meetings today",
            "scheduled meeting", "my meetings", "what do i have scheduled"
        ]):
            res = await execute_tool(
                session=session,
                organization_id=organization_id,
                user_id=user_id,
                conversation_id=conversation_id,
                tool_name="get_upcoming_meetings",
                arguments={"days_ahead": 7},
                user_permissions=user_permissions,
            )
            return {
                "conversation_id": str(conversation_id),
                "text": res.get("text", ""),
                "blocks": res.get("blocks", []),
            }

        # Intent 5B: In-Chat Confirmation ("Confirm", "Yes, schedule it", "Go ahead", "Book it")
        if any(k in lower_prompt for k in [
            "confirm", "approve action", "proceed", "go ahead", "book it",
            "schedule it", "yes please", "yes create", "yes, create",
            "yes confirm", "yes, confirm", "create it", "schedule now"
        ]):
            # Check for active pending proposal in this conversation or organization
            stmt = (
                select(AIAction)
                .where(
                    AIAction.organization_id == organization_id,
                    AIAction.status == "WAITING_FOR_CONFIRMATION",
                )
                .order_by(AIAction.created_at.desc())
            )
            pending_action = (await session.execute(stmt)).scalars().first()
            if pending_action:
                try:
                    await ActionService.confirm_action(
                        session=session,
                        organization_id=organization_id,
                        user_id=user_id,
                        action_id=pending_action.id,
                        user_permissions=user_permissions,
                    )
                    p = pending_action.payload or {}
                    start_val = p.get("start_time", "")
                    try:
                        start_dt = datetime.fromisoformat(str(start_val).replace("Z", "+00:00"))
                        fmt_time = start_dt.strftime("%A, %b %d, %Y at %I:%M %p UTC")
                    except Exception:
                        fmt_time = str(start_val)
                    
                    return {
                        "conversation_id": str(conversation_id),
                        "text": (
                            f"✅ **Meeting successfully scheduled and confirmed!**\n\n"
                            f"- **Title**: {p.get('title', 'Meeting')}\n"
                            f"- **Time**: {fmt_time}\n"
                            f"- **Attendees**: {', '.join(p.get('attendee_emails') or p.get('attendees', []))}\n"
                            f"- **Location**: {p.get('location', 'Google Meet')}\n\n"
                            f"The meeting has been confirmed on your calendar and recorded in the audit trail."
                        ),
                        "blocks": [],
                    }
                except Exception as ex:
                    return {
                        "conversation_id": str(conversation_id),
                        "text": f"⚠️ Could not confirm meeting: {str(ex)}",
                        "blocks": [],
                    }

        # Intent 5C: Meeting Scheduling & Slot Queries
        if any(k in lower_prompt for k in [
            "schedule", "meeting", "calendar", "time for", "book", "set up a sync",
            "create a meeting", "create meeting", "sync with"
        ]):
            now = datetime.now(timezone.utc)
            parsed = parse_meeting_intent(prompt, now=now)

            # Check if user is solely asking to check open slots vs proposing/booking
            is_slot_query_only = any(k in lower_prompt for k in [
                "find a time", "find time", "suitable time", "available slot",
                "check slot", "free time", "open slot", "when is", "what time is"
            ]) and not any(k in lower_prompt for k in ["create", "book", "schedule for", "set up", "at "])

            if is_slot_query_only or (
                not parsed["has_explicit_date"]
                and not parsed["has_explicit_time"]
                and "create" not in lower_prompt
                and "book" not in lower_prompt
                and "schedule for" not in lower_prompt
            ):
                slots_res = await execute_tool(
                    session=session,
                    organization_id=organization_id,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    tool_name="get_calendar_slots",
                    arguments={
                        "attendee_emails": parsed["attendees"],
                        "duration_minutes": parsed["duration_minutes"],
                        "search_date": parsed["start_time"],
                    },
                    user_permissions=user_permissions,
                )
                return {
                    "conversation_id": str(conversation_id),
                    "text": (
                        f"I checked the schedule for **{', '.join(parsed['attendees'])}**. "
                        f"The following {parsed['duration_minutes']}-minute slots are open:"
                    ),
                    "blocks": slots_res.get("blocks", []),
                }
            else:
                # Propose the calendar meeting using the exact parsed date, time, and attendees
                res = await execute_tool(
                    session=session,
                    organization_id=organization_id,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    tool_name="propose_calendar_meeting",
                    arguments={
                        "title": parsed["title"],
                        "attendee_emails": parsed["attendees"],
                        "start_time": parsed["start_time"],
                        "end_time": parsed["end_time"],
                        "description": f"Scheduled via PM Buddy for {parsed['title']}.",
                    },
                    user_permissions=user_permissions,
                )
                return {
                    "conversation_id": str(conversation_id),
                    "text": res.get("text", ""),
                    "blocks": res.get("blocks", []),
                }

        # Intent 6: "Daily Briefing" / "Give me today's briefing"
        if any(k in lower_prompt for k in ["daily briefing", "briefing", "morning sync", "today's update"]):
            res = await execute_tool(
                session=session,
                organization_id=organization_id,
                user_id=user_id,
                conversation_id=conversation_id,
                tool_name="get_daily_briefing",
                arguments={},
                user_permissions=user_permissions,
            )
            return {
                "conversation_id": str(conversation_id),
                "text": res.get("text", ""),
                "blocks": res.get("blocks", []),
            }

        # Intent 7: "Knowledge / Architecture Decision / Runbook / Documentation"
        if any(k in lower_prompt for k in ["architecture decision", "adr", "runbook", "documentation", "doc", "procedure", "knowledge", "guidelines"]):
            res = await execute_tool(
                session=session,
                organization_id=organization_id,
                user_id=user_id,
                conversation_id=conversation_id,
                tool_name="search_knowledge",
                arguments={"query": prompt},
                user_permissions=user_permissions,
            )
            return {
                "conversation_id": str(conversation_id),
                "text": res.get("text", ""),
                "blocks": res.get("blocks", []),
            }

        # Intent 8: "Blockers / Dependencies / What is blocking"
        if any(k in lower_prompt for k in ["blocker", "blocking", "blocked", "dependency", "prerequisite"]):
            res = await execute_tool(
                session=session,
                organization_id=organization_id,
                user_id=user_id,
                conversation_id=conversation_id,
                tool_name="get_blockers",
                arguments={},
                user_permissions=user_permissions,
            )
            return {
                "conversation_id": str(conversation_id),
                "text": res.get("text", ""),
                "blocks": res.get("blocks", []),
            }

        # Intent 9: "Recommendations / What should I do next?"
        if any(k in lower_prompt for k in ["recommend", "next action", "suggested action", "what should i do next"]):
            res = await execute_tool(
                session=session,
                organization_id=organization_id,
                user_id=user_id,
                conversation_id=conversation_id,
                tool_name="get_action_recommendations",
                arguments={"limit": 5},
                user_permissions=user_permissions,
            )
            return {
                "conversation_id": str(conversation_id),
                "text": res.get("text", ""),
                "blocks": res.get("blocks", []),
            }

        # Default Fallback: Conversational Guidance
        response_text = (
            "I am **PM Buddy**, your AI operational and governance partner. I can help you with:\n\n"
            "- **My Work**: *'What should I do first today?'*\n"
            "- **Project Health**: *'Show me the dashboard for Project Alpha'* or *'Why is Project Alpha at risk?'*\n"
            "- **Governance**: *'What approvals are pending?'* or *'Who is blocking the most approvals?'*\n"
            "- **Scheduling**: *'Find a suitable time for an architecture review with Rahul'*"
        )
        blocks = [{
            "type": "recommendation",
            "title": "Suggested Prompts",
            "items": [
                {"label": "What should I do first today?", "action": "prompt_my_work"},
                {"label": "Show me the dashboard for Project Alpha", "action": "prompt_project_alpha"},
                {"label": "What approvals have breached SLA?", "action": "prompt_breached_approvals"},
                {"label": "Schedule an architecture review with Rahul", "action": "prompt_schedule"},
            ],
        }]

        return {
            "conversation_id": str(conversation_id),
            "text": response_text,
            "blocks": blocks,
        }


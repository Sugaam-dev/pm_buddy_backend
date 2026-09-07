import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4
import litellm
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.gemini_service import GeminiService
from app.ai.tools import execute_tool, get_openai_tools
from app.core.config import settings

logger = logging.getLogger(__name__)

# LiteLLM Configuration
litellm.telemetry = False
litellm.drop_params = True

SYSTEM_PROMPT = (
    "You are PM Buddy, an AI operational intelligence and governance partner for software engineering teams. "
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
        Processes an incoming user message through LiteLLM tool-calling loop,
        falling back to deterministic intent routing if LiteLLM is not configured
        or fails.
        """
        use_llm = force_llm or cls._should_use_llm()

        if use_llm:
            # Direct Gemini Integration (official SDK, zero OpenAI dependency)
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
            {"role": "system", "content": SYSTEM_PROMPT},
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

        # Intent 1: "What should I focus on right now?" / "What should I do first today?" / "What are my pending tasks?"
        if any(k in lower_prompt for k in ["focus on", "focus right now", "what should i do", "what to do", "pending task", "pending for me", "my work", "what is pending"]):
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

        # Intent 5: "Schedule a meeting" / "Find a suitable time for review"
        if any(k in lower_prompt for k in ["schedule", "meeting", "calendar", "time for", "book", "set up a sync"]):
            # Extract attendees dynamically
            attendees = ["alice.pm@acme.com"]
            if "rahul" in lower_prompt:
                attendees.append("rahul@acme.com" if "rahul@acme.com" in lower_prompt else "rahul.arch@acme.com")
            elif "charlie" in lower_prompt:
                attendees.append("charlie@acme.com")
            elif "bob" in lower_prompt:
                attendees.append("bob@globex.com" if "globex" in lower_prompt else "bob@acme.com")
            else:
                attendees.append("rahul.arch@acme.com")

            # Check if user requested to book or specified a specific time / slot
            has_time_specification = any(k in lower_prompt for k in [
                "2:00", "2 pm", "3:00", "3 pm", "4:00", "4 pm", "10:00", "10 am", "11:00", "11 am", "confirm", "book", "tomorrow"
            ])

            if has_time_specification:
                # Retrieve slots first to find a suitable slot or construct requested time
                slots_res = await execute_tool(
                    session=session,
                    organization_id=organization_id,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    tool_name="get_calendar_slots",
                    arguments={
                        "attendee_emails": attendees,
                        "duration_minutes": 30,
                    },
                    user_permissions=user_permissions,
                )
                slots = slots_res.get("data", {}).get("slots", [])
                
                # Derive title
                title = "Project Review"
                if "architecture" in lower_prompt or "arch" in lower_prompt:
                    title = "Project Alpha Architecture Gate Review"
                elif "standup" in lower_prompt:
                    title = "Daily Standup"
                elif "sync" in lower_prompt:
                    title = "Project Sync"
                elif "planning" in lower_prompt:
                    title = "Sprint Planning Session"

                # If "tomorrow at 3 pm" or specific time requested
                now = datetime.now(timezone.utc)
                if "tomorrow" in lower_prompt and ("3 pm" in lower_prompt or "15:00" in lower_prompt):
                    tomorrow = now + timedelta(days=1)
                    req_start = tomorrow.replace(hour=15, minute=0, second=0, microsecond=0)
                    req_end = req_start + timedelta(minutes=30)
                    start_iso = req_start.isoformat()
                    end_iso = req_end.isoformat()
                elif slots:
                    slot = slots[1] if len(slots) > 1 else slots[0]
                    start_iso = slot["start_time"]
                    end_iso = slot["end_time"]
                else:
                    req_start = (now + timedelta(days=1)).replace(hour=14, minute=0, second=0, microsecond=0)
                    start_iso = req_start.isoformat()
                    end_iso = (req_start + timedelta(minutes=30)).isoformat()

                res = await execute_tool(
                    session=session,
                    organization_id=organization_id,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    tool_name="propose_calendar_meeting",
                    arguments={
                        "title": title,
                        "attendee_emails": attendees,
                        "start_time": start_iso,
                        "end_time": end_iso,
                        "description": f"Scheduled via PM Buddy for {title}.",
                    },
                    user_permissions=user_permissions,
                )
                return {
                    "conversation_id": str(conversation_id),
                    "text": res.get("text", ""),
                    "blocks": res.get("blocks", []),
                }
            else:
                res = await execute_tool(
                    session=session,
                    organization_id=organization_id,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    tool_name="get_calendar_slots",
                    arguments={
                        "attendee_emails": attendees,
                        "duration_minutes": 30,
                    },
                    user_permissions=user_permissions,
                )
                return {
                    "conversation_id": str(conversation_id),
                    "text": (
                        f"I checked the schedule for **{', '.join(attendees)}**. The following 30-minute slots are open:"
                    ),
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


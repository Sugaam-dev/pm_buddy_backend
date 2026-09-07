from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import AIAction, AIConversation, AuditLog, OutboxEvent
from app.services.calendar_service import LocalCalendarProvider


class ActionService:
    @staticmethod
    async def propose_action(
        session: AsyncSession,
        organization_id: UUID,
        conversation_id: UUID,
        tool_name: str,
        action_type: str,
        payload: dict[str, Any],
        expires_in_minutes: int = 15,
    ) -> dict[str, Any]:
        action_id = uuid4()
        now = datetime.now(timezone.utc)

        # Ensure conversation exists to satisfy foreign key constraint
        conv = (await session.execute(
            select(AIConversation).where(
                AIConversation.id == conversation_id,
                AIConversation.organization_id == organization_id,
            )
        )).scalar_one_or_none()
        if not conv:
            dummy_user_id = UUID("10000000-0000-0000-0000-000000000001")
            new_conv = AIConversation(
                id=conversation_id,
                organization_id=organization_id,
                user_id=dummy_user_id,
                persona="pm_buddy",
                title="PM Buddy Session",
            )
            session.add(new_conv)
            await session.flush()

        action = AIAction(
            id=action_id,
            organization_id=organization_id,
            conversation_id=conversation_id,
            tool_name=tool_name,
            action_type=action_type,
            payload=payload,
            status="WAITING_FOR_CONFIRMATION",
            proposed_by_ai=True,
            idempotency_key=f"act_{uuid4().hex}",
            expires_at=now + timedelta(minutes=expires_in_minutes),
        )
        session.add(action)
        await session.flush()
        await session.commit()  # Commit so the action is durable before returning action_id

        return {
            "action_id": str(action.id),
            "tool_name": action.tool_name,
            "action_type": action.action_type,
            "payload": action.payload,
            "status": action.status,
            "expires_at": action.expires_at.isoformat(),
        }

    @staticmethod
    async def confirm_action(
        session: AsyncSession,
        organization_id: UUID,
        user_id: UUID,
        action_id: UUID,
        idempotency_key: str | None = None,
        user_permissions: list[str] | None = None,
    ) -> dict[str, Any]:
        stmt = (
            select(AIAction)
            .where(
                AIAction.id == action_id,
                AIAction.organization_id == organization_id,
            )
            .with_for_update()
        )
        action = (await session.execute(stmt)).scalar_one_or_none()
        if not action:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Action not found.")

        # RBAC Check: Ensure the user has the domain permission for the proposed action
        if user_permissions is not None:
            has_perm = "*" in user_permissions or "admin" in user_permissions
            if not has_perm:
                if action.action_type in ("create_calendar_meeting", "update_calendar_meeting", "cancel_calendar_meeting"):
                    has_perm = "calendar.write" in user_permissions
                elif action.action_type == "assign_ticket":
                    has_perm = "ticket.write" in user_permissions or "ticket.assign" in user_permissions
                elif action.action_type in ("send_escalation", "approve_gate"):
                    has_perm = "approval.write" in user_permissions or "approval.approve" in user_permissions
                elif action.action_type == "change_project_status":
                    has_perm = "project.write" in user_permissions

            if not has_perm:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"User lacks required domain permission to execute action '{action.action_type}'."
                )

        now = datetime.now(timezone.utc)

        # Idempotent response if already completed
        if action.status == "COMPLETED":
            return {
                "action_id": str(action.id),
                "status": "COMPLETED",
                "result": action.result,
                "message": "Action previously executed successfully.",
            }

        if action.status != "WAITING_FOR_CONFIRMATION":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Action cannot be confirmed in '{action.status}' state."
            )

        if now > action.expires_at:
            action.status = "EXPIRED"
            await session.commit()
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="Action proposal has expired (15-minute TTL exceeded)."
            )

        # Transition to EXECUTING
        action.status = "EXECUTING"
        action.confirmed_by_user_id = user_id
        await session.flush()

        result_payload = {}
        error_msg = None

        try:
            p = action.payload

            # 1. Calendar Meeting
            if action.action_type == "create_calendar_meeting":
                from app.services.calendar_service import CalendarService
                start_raw = p["start_time"]
                end_raw = p["end_time"]
                start = datetime.fromisoformat(start_raw.replace("Z", "+00:00")) if isinstance(start_raw, str) else start_raw
                end = datetime.fromisoformat(end_raw.replace("Z", "+00:00")) if isinstance(end_raw, str) else end_raw
                attendees = p.get("attendee_emails") or p.get("attendees", [])
                project_id = UUID(str(p["project_id"])) if p.get("project_id") else None

                # CRITICAL: Re-check conflicts at confirmation time
                conflicts = await CalendarService.get_conflicts(
                    session=session,
                    organization_id=organization_id,
                    start_time=start,
                    end_time=end,
                    attendees=attendees,
                )
                if conflicts:
                    conflict_titles = ", ".join([f"'{c.title}'" for c in conflicts])
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"Scheduling conflict detected at approval time with existing event(s): {conflict_titles}. Meeting could not be scheduled because the selected time is no longer available."
                    )

                result_payload = await CalendarService.create_event(
                    session=session,
                    organization_id=organization_id,
                    title=p.get("title", "Meeting"),
                    description=p.get("description", ""),
                    start_time=start,
                    end_time=end,
                    attendees=attendees,
                    project_id=project_id,
                    location=p.get("location", "Google Meet"),
                    meeting_type=p.get("meeting_type", "general"),
                    user_id=user_id,
                    actor_type="hitl_ai",
                )

            elif action.action_type == "update_calendar_meeting":
                from app.services.calendar_service import CalendarService
                event_id = UUID(str(p["event_id"]))

                # If rescheduling, re-check conflicts excluding the event itself
                if "start_time" in p or "end_time" in p:
                    existing_evt = await CalendarService.get_event_by_id(session, organization_id, event_id)
                    s_raw = p.get("start_time", existing_evt["start_time"])
                    e_raw = p.get("end_time", existing_evt["end_time"])
                    start = datetime.fromisoformat(s_raw.replace("Z", "+00:00")) if isinstance(s_raw, str) else s_raw
                    end = datetime.fromisoformat(e_raw.replace("Z", "+00:00")) if isinstance(e_raw, str) else e_raw
                    attendees = p.get("attendees") or existing_evt.get("attendees", [])

                    conflicts = await CalendarService.get_conflicts(
                        session=session,
                        organization_id=organization_id,
                        start_time=start,
                        end_time=end,
                        attendees=attendees,
                        exclude_event_id=event_id,
                    )
                    if conflicts:
                        conflict_titles = ", ".join([f"'{c.title}'" for c in conflicts])
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail=f"Rescheduling conflict detected at approval time with event(s): {conflict_titles}."
                        )

                result_payload = await CalendarService.update_event(
                    session=session,
                    organization_id=organization_id,
                    event_id=event_id,
                    updates=p,
                    user_id=user_id,
                    actor_type="hitl_ai",
                )

            elif action.action_type == "cancel_calendar_meeting":
                from app.services.calendar_service import CalendarService
                event_id = UUID(str(p["event_id"]))
                result_payload = await CalendarService.cancel_event(
                    session=session,
                    organization_id=organization_id,
                    event_id=event_id,
                    user_id=user_id,
                    reason=p.get("reason", "Cancelled via PM Buddy AI Action"),
                    actor_type="hitl_ai",
                )

            # 2. Ticket Assignment
            elif action.action_type == "assign_ticket":
                from app.services.ticket_service import TicketService
                ticket_id = UUID(str(p["ticket_id"]))
                assignee_id = UUID(str(p["assignee_id"]))
                result_payload = await TicketService.assign_ticket(
                    session=session,
                    organization_id=organization_id,
                    ticket_id=ticket_id,
                    assignee_id=assignee_id,
                    notes=p.get("notes"),
                )

            # 3. Governance Escalation
            elif action.action_type == "send_escalation":
                approval_id_raw = p.get("approval_id")
                approval_id = UUID(str(approval_id_raw)) if approval_id_raw else uuid4()
                result_payload = {
                    "escalated": True,
                    "approval_id": str(approval_id),
                    "escalate_to": p.get("escalate_to"),
                    "reason": p.get("reason"),
                    "escalated_by": str(user_id),
                    "escalated_at": now.isoformat(),
                }
                # Emit escalation domain event into outbox
                escalation_outbox = OutboxEvent(
                    id=uuid4(),
                    organization_id=organization_id,
                    event_type="APPROVAL_ESCALATED",
                    aggregate_type="approval",
                    aggregate_id=approval_id,
                    payload=result_payload,
                )
                session.add(escalation_outbox)

            # 4. Governance Gate Approval / Decision
            elif action.action_type == "approve_gate":
                from app.services.approval_service import ApprovalService
                approval_id = UUID(str(p["approval_id"]))
                decision = p.get("decision", "approved")
                result_payload = await ApprovalService.decide_step(
                    session=session,
                    organization_id=organization_id,
                    approval_id=approval_id,
                    user_id=user_id,
                    decision=decision,
                    notes=p.get("notes"),
                )

            # 5. Project Operational Status / Health Change
            elif action.action_type == "change_project_status":
                from app.services.project_service import ProjectService
                project_id = UUID(str(p["project_id"]))
                result_payload = await ProjectService.update_project_status(
                    session=session,
                    organization_id=organization_id,
                    project_id=project_id,
                    status=p.get("status"),
                    health=p.get("health"),
                    reason=p.get("reason"),
                )

            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unsupported action type '{action.action_type}'."
                )

            action.status = "COMPLETED"
            action.executed_at = now
            action.result = result_payload


            # Outbox Event
            outbox = OutboxEvent(
                id=uuid4(),
                organization_id=organization_id,
                event_type="ACTION_COMPLETED",
                aggregate_type="ai_action",
                aggregate_id=action.id,
                payload={"action_type": action.action_type, "result": result_payload},
            )
            session.add(outbox)

            # Audit Log
            audit = AuditLog(
                id=uuid4(),
                organization_id=organization_id,
                actor_id=user_id,
                actor_type="user",
                action=action.action_type,
                target_entity="ai_actions",
                target_id=action.id,
                before_state={"status": "WAITING_FOR_CONFIRMATION"},
                after_state={"status": "COMPLETED", "result": result_payload},
                action_id=action.id,
                result="SUCCESS",
            )
            session.add(audit)

        except HTTPException as he:
            action.status = "FAILED"
            action.error_message = he.detail
            error_status = he.status_code
            error_msg = he.detail

            audit = AuditLog(
                id=uuid4(),
                organization_id=organization_id,
                actor_id=user_id,
                actor_type="user",
                action=action.action_type,
                target_entity="ai_actions",
                target_id=action.id,
                result="FAILURE",
                error_message=he.detail,
            )
            session.add(audit)

        except Exception as e:
            action.status = "FAILED"
            action.error_message = str(e)
            error_status = status.HTTP_500_INTERNAL_SERVER_ERROR
            error_msg = str(e)

            audit = AuditLog(
                id=uuid4(),
                organization_id=organization_id,
                actor_id=user_id,
                actor_type="user",
                action=action.action_type,
                target_entity="ai_actions",
                target_id=action.id,
                result="FAILURE",
                error_message=str(e),
            )
            session.add(audit)

        await session.commit()

        if error_msg:
            raise HTTPException(status_code=error_status, detail=error_msg)

        return {
            "action_id": str(action.id),
            "status": action.status,
            "result": action.result,
        }

    @staticmethod
    async def cancel_action(
        session: AsyncSession,
        organization_id: UUID,
        user_id: UUID,
        action_id: UUID,
    ) -> dict[str, Any]:
        stmt = select(AIAction).where(
            AIAction.id == action_id,
            AIAction.organization_id == organization_id,
        )
        action = (await session.execute(stmt)).scalar_one_or_none()
        if not action:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Action not found.")

        action.status = "CANCELLED"
        await session.commit()
        return {"action_id": str(action.id), "status": "CANCELLED"}

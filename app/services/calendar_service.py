from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID, uuid4
from fastapi import HTTPException, status
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import CalendarConnection, CalendarEvent, CalendarEventParticipant, AuditLog, OutboxEvent


class CalendarService:
    @staticmethod
    async def find_available_slots(
        session: AsyncSession,
        organization_id: UUID,
        attendee_emails: list[str],
        duration_minutes: int = 30,
        search_date: Optional[datetime] = None,
        start_hour: int = 9,
        end_hour: int = 18,
    ) -> list[dict[str, Any]]:
        """
        Find conflict-free meeting slots within business hours (start_hour to end_hour)
        on search_date, checking against existing confirmed and tentative calendar events.
        """
        if not search_date:
            search_date = datetime.now(timezone.utc)
        elif search_date.tzinfo is None:
            search_date = search_date.replace(tzinfo=timezone.utc)

        day_start = search_date.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        day_end = search_date.replace(hour=end_hour, minute=0, second=0, microsecond=0)

        # Generate candidate slots in 30-minute step increments
        candidate_slots: list[dict[str, Any]] = []
        current_slot_start = day_start
        step = timedelta(minutes=30)
        slot_duration = timedelta(minutes=duration_minutes)

        while current_slot_start + slot_duration <= day_end:
            current_slot_end = current_slot_start + slot_duration
            start_fmt = current_slot_start.strftime("%I:%M %p")
            end_fmt = current_slot_end.strftime("%I:%M %p")
            candidate_slots.append({
                "start": current_slot_start,
                "end": current_slot_end,
                "label": f"{start_fmt} - {end_fmt}",
            })
            current_slot_start += step

        # Fetch existing events for organization that overlap the day
        stmt = (
            select(CalendarEvent)
            .where(
                CalendarEvent.organization_id == organization_id,
                CalendarEvent.status.in_(["confirmed", "tentative"]),
                CalendarEvent.end_time > day_start,
                CalendarEvent.start_time < day_end,
            )
        )
        existing_events = (await session.execute(stmt)).scalars().all()

        # If attendee emails provided, fetch participant records to see conflicts
        clean_attendee_emails = {email.lower().strip() for email in attendee_emails if email.strip()}

        available_slots = []
        for slot in candidate_slots:
            conflict = False
            for evt in existing_events:
                # Interval overlap test: max(startA, startB) < min(endA, endB)
                evt_start = evt.start_time if evt.start_time.tzinfo else evt.start_time.replace(tzinfo=timezone.utc)
                evt_end = evt.end_time if evt.end_time.tzinfo else evt.end_time.replace(tzinfo=timezone.utc)

                if max(slot["start"], evt_start) < min(slot["end"], evt_end):
                    if clean_attendee_emails:
                        evt_attendees = {str(a).lower().strip() for a in (evt.attendees or [])}
                        if not clean_attendee_emails.isdisjoint(evt_attendees):
                            conflict = True
                            break
                    else:
                        conflict = True
                        break

            if not conflict:
                available_slots.append({
                    "start_time": slot["start"].isoformat(),
                    "end_time": slot["end"].isoformat(),
                    "duration_minutes": duration_minutes,
                    "label": slot["label"],
                    "is_available": True,
                })

        return available_slots

    @staticmethod
    async def list_events(
        session: AsyncSession,
        organization_id: UUID,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        project_id: Optional[UUID] = None,
        status_filter: Optional[str] = None,
        user_email: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """List calendar events for an organization with optional time, project, and status filters."""
        query = select(CalendarEvent).where(CalendarEvent.organization_id == organization_id)

        if start_time:
            query = query.where(CalendarEvent.end_time >= start_time)
        if end_time:
            query = query.where(CalendarEvent.start_time <= end_time)
        if project_id:
            query = query.where(CalendarEvent.project_id == project_id)
        if status_filter:
            query = query.where(CalendarEvent.status == status_filter)
        else:
            # Default: omit cancelled meetings unless explicitly asked
            query = query.where(CalendarEvent.status != "cancelled")

        query = query.order_by(CalendarEvent.start_time.asc())
        events = (await session.execute(query)).scalars().all()

        # Fetch participants for these events
        event_ids = [e.id for e in events]
        participants_by_event: dict[UUID, list[dict[str, Any]]] = {eid: [] for eid in event_ids}

        if event_ids:
            p_stmt = select(CalendarEventParticipant).where(CalendarEventParticipant.event_id.in_(event_ids))
            participants = (await session.execute(p_stmt)).scalars().all()
            for p in participants:
                participants_by_event[p.event_id].append({
                    "id": str(p.id),
                    "user_email": p.user_email,
                    "user_id": str(p.user_id) if p.user_id else None,
                    "response_status": p.response_status,
                })

        result = []
        for evt in events:
            p_list = participants_by_event.get(evt.id, [])
            if user_email:
                attendee_set = {str(a).lower().strip() for a in (evt.attendees or [])}
                p_emails = {p["user_email"].lower().strip() for p in p_list}
                if user_email.lower().strip() not in attendee_set and user_email.lower().strip() not in p_emails:
                    continue

            result.append({
                "id": str(evt.id),
                "organization_id": str(evt.organization_id),
                "external_event_id": evt.external_event_id,
                "title": evt.title,
                "description": evt.description,
                "start_time": evt.start_time.isoformat(),
                "end_time": evt.end_time.isoformat(),
                "attendees": evt.attendees or [],
                "participants": p_list,
                "project_id": str(evt.project_id) if evt.project_id else None,
                "timezone": evt.timezone,
                "location": evt.location,
                "meeting_type": evt.meeting_type,
                "status": evt.status,
                "meet_url": evt.meet_url,
                "created_by": str(evt.created_by) if evt.created_by else None,
                "created_at": evt.created_at.isoformat(),
                "updated_at": evt.updated_at.isoformat(),
            })

        return result

    @staticmethod
    async def get_event_by_id(
        session: AsyncSession,
        organization_id: UUID,
        event_id: UUID,
    ) -> dict[str, Any]:
        """Fetch a single calendar event by ID with its participants."""
        stmt = select(CalendarEvent).where(
            CalendarEvent.id == event_id,
            CalendarEvent.organization_id == organization_id,
        )
        evt = (await session.execute(stmt)).scalar_one_or_none()
        if not evt:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Calendar event not found.")

        p_stmt = select(CalendarEventParticipant).where(CalendarEventParticipant.event_id == evt.id)
        participants = (await session.execute(p_stmt)).scalars().all()

        return {
            "id": str(evt.id),
            "organization_id": str(evt.organization_id),
            "external_event_id": evt.external_event_id,
            "title": evt.title,
            "description": evt.description,
            "start_time": evt.start_time.isoformat(),
            "end_time": evt.end_time.isoformat(),
            "attendees": evt.attendees or [],
            "participants": [
                {
                    "id": str(p.id),
                    "user_email": p.user_email,
                    "user_id": str(p.user_id) if p.user_id else None,
                    "response_status": p.response_status,
                }
                for p in participants
            ],
            "project_id": str(evt.project_id) if evt.project_id else None,
            "timezone": evt.timezone,
            "location": evt.location,
            "meeting_type": evt.meeting_type,
            "status": evt.status,
            "meet_url": evt.meet_url,
            "created_by": str(evt.created_by) if evt.created_by else None,
            "created_at": evt.created_at.isoformat(),
            "updated_at": evt.updated_at.isoformat(),
        }

    @staticmethod
    async def create_event(
        session: AsyncSession,
        organization_id: UUID,
        title: str,
        description: str,
        start_time: datetime,
        end_time: datetime,
        attendees: list[str],
        project_id: Optional[UUID] = None,
        location: Optional[str] = None,
        timezone_str: str = "UTC",
        meeting_type: str = "general",
        user_id: Optional[UUID] = None,
        actor_type: str = "user",
    ) -> dict[str, Any]:
        """Create a new calendar event, register participants, and emit audit & outbox records."""
        if start_time >= end_time:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Meeting start time must be strictly before end time."
            )

        now = datetime.now(timezone.utc)
        evt_id = uuid4()
        meet_id = uuid4().hex[:8]
        meet_url = f"https://meet.google.com/pmb-{meet_id}"

        # Clean attendees & enforce tenant isolation
        clean_attendees = list({a.strip() for a in attendees if a.strip()})
        from app.core.security import DEMO_USERS
        for email in clean_attendees:
            u_info = DEMO_USERS.get(email.lower())
            if u_info and u_info["organization_id"] != organization_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Cross-tenant scheduling forbidden: Attendee '{email}' belongs to a different organization."
                )

        evt = CalendarEvent(
            id=evt_id,
            organization_id=organization_id,
            external_event_id=f"local_evt_{uuid4().hex[:10]}",
            title=title,
            description=description,
            start_time=start_time,
            end_time=end_time,
            attendees=clean_attendees,
            status="confirmed",
            meet_url=meet_url,
            project_id=project_id,
            timezone=timezone_str,
            location=location or "Google Meet",
            meeting_type=meeting_type,
            organizer_id=user_id,
            created_by=user_id,
            updated_by=user_id,
            created_at=now,
            updated_at=now,
        )
        session.add(evt)

        # Create participants
        participant_records = []
        for email in clean_attendees:
            p = CalendarEventParticipant(
                id=uuid4(),
                event_id=evt_id,
                user_email=email,
                user_id=None,
                response_status="accepted" if user_id and email in ("alice@acme.com", "sarah@acme.com") else "needs_action",
                created_at=now,
                updated_at=now,
            )
            session.add(p)
            participant_records.append({
                "id": str(p.id),
                "user_email": p.user_email,
                "response_status": p.response_status,
            })

        # Record Audit Log
        audit = AuditLog(
            id=uuid4(),
            organization_id=organization_id,
            actor_id=user_id,
            actor_type=actor_type,
            action="CALENDAR_EVENT_CREATED",
            target_entity="calendar_events",
            target_id=evt_id,
            before_state=None,
            after_state={
                "id": str(evt_id),
                "title": title,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "attendees": clean_attendees,
                "project_id": str(project_id) if project_id else None,
            },
            result="SUCCESS",
            created_at=now,
        )
        session.add(audit)

        # Record Transactional Outbox
        outbox = OutboxEvent(
            id=uuid4(),
            organization_id=organization_id,
            event_type="CALENDAR_EVENT_SCHEDULED",
            aggregate_type="calendar_event",
            aggregate_id=evt_id,
            payload={
                "event_id": str(evt_id),
                "title": title,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "attendees": clean_attendees,
                "meet_url": meet_url,
                "project_id": str(project_id) if project_id else None,
                "scheduled_by": str(user_id) if user_id else None,
            },
            status="PENDING",
            created_at=now,
        )
        session.add(outbox)
        await session.flush()

        return {
            "id": str(evt.id),
            "organization_id": str(evt.organization_id),
            "external_event_id": evt.external_event_id,
            "title": evt.title,
            "description": evt.description,
            "start_time": evt.start_time.isoformat(),
            "end_time": evt.end_time.isoformat(),
            "attendees": evt.attendees,
            "participants": participant_records,
            "project_id": str(evt.project_id) if evt.project_id else None,
            "timezone": evt.timezone,
            "location": evt.location,
            "meeting_type": evt.meeting_type,
            "status": evt.status,
            "meet_url": evt.meet_url,
            "created_at": evt.created_at.isoformat(),
        }

    @staticmethod
    async def update_event(
        session: AsyncSession,
        organization_id: UUID,
        event_id: UUID,
        updates: dict[str, Any],
        user_id: Optional[UUID] = None,
        actor_type: str = "user",
    ) -> dict[str, Any]:
        """Update existing calendar event, update participants, and emit audit & outbox records."""
        stmt = (
            select(CalendarEvent)
            .where(
                CalendarEvent.id == event_id,
                CalendarEvent.organization_id == organization_id,
            )
            .with_for_update()
        )
        evt = (await session.execute(stmt)).scalar_one_or_none()
        if not evt:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Calendar event not found.")

        now = datetime.now(timezone.utc)
        before_state = {
            "title": evt.title,
            "start_time": evt.start_time.isoformat(),
            "end_time": evt.end_time.isoformat(),
            "status": evt.status,
            "attendees": evt.attendees,
        }

        if "title" in updates and updates["title"] is not None:
            evt.title = updates["title"]
        if "description" in updates and updates["description"] is not None:
            evt.description = updates["description"]
        if "start_time" in updates and updates["start_time"] is not None:
            raw = updates["start_time"]
            evt.start_time = datetime.fromisoformat(raw.replace("Z", "+00:00")) if isinstance(raw, str) else raw
        if "end_time" in updates and updates["end_time"] is not None:
            raw = updates["end_time"]
            evt.end_time = datetime.fromisoformat(raw.replace("Z", "+00:00")) if isinstance(raw, str) else raw
        if "location" in updates and updates["location"] is not None:
            evt.location = updates["location"]
        if "meeting_type" in updates and updates["meeting_type"] is not None:
            evt.meeting_type = updates["meeting_type"]
        if "status" in updates and updates["status"] is not None:
            evt.status = updates["status"]
        if "project_id" in updates:
            pid = updates["project_id"]
            evt.project_id = UUID(str(pid)) if pid else None

        if evt.start_time >= evt.end_time:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Meeting start time must be strictly before end time."
            )

        if "attendees" in updates and updates["attendees"] is not None:
            new_attendees = list({a.strip() for a in updates["attendees"] if a.strip()})
            evt.attendees = new_attendees
            existing_p = (await session.execute(
                select(CalendarEventParticipant).where(CalendarEventParticipant.event_id == evt.id)
            )).scalars().all()
            existing_emails = {p.user_email for p in existing_p}

            for em in new_attendees:
                if em not in existing_emails:
                    session.add(CalendarEventParticipant(
                        id=uuid4(),
                        event_id=evt.id,
                        user_email=em,
                        response_status="needs_action",
                        created_at=now,
                        updated_at=now,
                    ))

        evt.updated_by = user_id
        evt.updated_at = now

        # Audit Log
        audit = AuditLog(
            id=uuid4(),
            organization_id=organization_id,
            actor_id=user_id,
            actor_type=actor_type,
            action="CALENDAR_EVENT_UPDATED",
            target_entity="calendar_events",
            target_id=evt.id,
            before_state=before_state,
            after_state={
                "title": evt.title,
                "start_time": evt.start_time.isoformat(),
                "end_time": evt.end_time.isoformat(),
                "status": evt.status,
                "attendees": evt.attendees,
            },
            result="SUCCESS",
            created_at=now,
        )
        session.add(audit)

        # Outbox Event
        outbox = OutboxEvent(
            id=uuid4(),
            organization_id=organization_id,
            event_type="CALENDAR_EVENT_UPDATED",
            aggregate_type="calendar_event",
            aggregate_id=evt.id,
            payload={
                "event_id": str(evt.id),
                "title": evt.title,
                "start_time": evt.start_time.isoformat(),
                "end_time": evt.end_time.isoformat(),
                "status": evt.status,
            },
            status="PENDING",
            created_at=now,
        )
        session.add(outbox)
        await session.flush()

        return await CalendarService.get_event_by_id(session, organization_id, evt.id)

    @staticmethod
    async def cancel_event(
        session: AsyncSession,
        organization_id: UUID,
        event_id: UUID,
        user_id: Optional[UUID] = None,
        reason: Optional[str] = None,
        actor_type: str = "user",
    ) -> dict[str, Any]:
        """Cancel an event and emit audit & outbox records."""
        stmt = (
            select(CalendarEvent)
            .where(
                CalendarEvent.id == event_id,
                CalendarEvent.organization_id == organization_id,
            )
            .with_for_update()
        )
        evt = (await session.execute(stmt)).scalar_one_or_none()
        if not evt:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Calendar event not found.")

        now = datetime.now(timezone.utc)
        evt.status = "cancelled"
        evt.updated_by = user_id
        evt.updated_at = now

        # Audit Log
        audit = AuditLog(
            id=uuid4(),
            organization_id=organization_id,
            actor_id=user_id,
            actor_type=actor_type,
            action="CALENDAR_EVENT_CANCELLED",
            target_entity="calendar_events",
            target_id=evt.id,
            before_state={"status": "confirmed"},
            after_state={"status": "cancelled", "reason": reason},
            result="SUCCESS",
            created_at=now,
        )
        session.add(audit)

        # Outbox Event
        outbox = OutboxEvent(
            id=uuid4(),
            organization_id=organization_id,
            event_type="CALENDAR_EVENT_CANCELLED",
            aggregate_type="calendar_event",
            aggregate_id=evt.id,
            payload={
                "event_id": str(evt.id),
                "title": evt.title,
                "reason": reason,
                "cancelled_by": str(user_id) if user_id else None,
            },
            status="PENDING",
            created_at=now,
        )
        session.add(outbox)
        await session.flush()

        return {
            "id": str(evt.id),
            "status": "cancelled",
            "message": f"Calendar event '{evt.title}' cancelled successfully.",
        }

    @staticmethod
    async def get_conflicts(
        session: AsyncSession,
        organization_id: UUID,
        start_time: datetime,
        end_time: datetime,
        attendees: list[str],
        exclude_event_id: Optional[UUID] = None,
    ) -> list[CalendarEvent]:
        """
        Check for any overlapping confirmed or tentative events for the given attendees
        in the organization between start_time and end_time.
        """
        start_utc = start_time if start_time.tzinfo else start_time.replace(tzinfo=timezone.utc)
        end_utc = end_time if end_time.tzinfo else end_time.replace(tzinfo=timezone.utc)

        stmt = (
            select(CalendarEvent)
            .where(
                CalendarEvent.organization_id == organization_id,
                CalendarEvent.status.in_(["confirmed", "tentative"]),
                CalendarEvent.start_time < end_utc,
                CalendarEvent.end_time > start_utc,
            )
        )
        if exclude_event_id:
            stmt = stmt.where(CalendarEvent.id != exclude_event_id)

        overlapping_events = (await session.execute(stmt)).scalars().all()
        clean_attendees = {a.lower().strip() for a in attendees if a.strip()}

        conflicts = []
        for evt in overlapping_events:
            if clean_attendees:
                evt_attendees = {str(a).lower().strip() for a in (evt.attendees or [])}
                if not clean_attendees.isdisjoint(evt_attendees):
                    conflicts.append(evt)
            else:
                conflicts.append(evt)

        return conflicts


# Backward-compatibility adapter for existing references to LocalCalendarProvider
class LocalCalendarProvider:
    async def find_available_slots(
        self,
        session: AsyncSession,
        organization_id: UUID,
        attendee_emails: list[str],
        duration_minutes: int,
        search_date: datetime,
    ) -> list[dict[str, Any]]:
        return await CalendarService.find_available_slots(
            session=session,
            organization_id=organization_id,
            attendee_emails=attendee_emails,
            duration_minutes=duration_minutes,
            search_date=search_date,
        )

    async def create_event(
        self,
        session: AsyncSession,
        organization_id: UUID,
        title: str,
        description: str,
        start_time: datetime,
        end_time: datetime,
        attendees: list[str],
        project_id: Optional[UUID] = None,
        location: Optional[str] = None,
        timezone: str = "UTC",
        meeting_type: str = "general",
        user_id: Optional[UUID] = None,
    ) -> dict[str, Any]:
        return await CalendarService.create_event(
            session=session,
            organization_id=organization_id,
            title=title,
            description=description,
            start_time=start_time,
            end_time=end_time,
            attendees=attendees,
            project_id=project_id,
            location=location,
            timezone_str=timezone,
            meeting_type=meeting_type,
            user_id=user_id,
        )

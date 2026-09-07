from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, Query, Path, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import CurrentTenantUser, require_permission
from app.services.calendar_service import CalendarService

router = APIRouter(prefix="/calendar", tags=["Calendar"])


class CreateEventRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = ""
    start_time: datetime
    end_time: datetime
    attendees: list[str] = Field(default_factory=list)
    project_id: Optional[UUID] = None
    location: Optional[str] = "Google Meet"
    timezone: str = "UTC"
    meeting_type: str = "general"


class UpdateEventRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    attendees: Optional[list[str]] = None
    project_id: Optional[UUID] = None
    location: Optional[str] = None
    timezone: Optional[str] = None
    meeting_type: Optional[str] = None
    status: Optional[str] = None


class CancelEventRequest(BaseModel):
    reason: Optional[str] = "Meeting cancelled by organizer"


@router.get("/slots")
async def get_available_slots(
    attendees: str = Query("alice@acme.com,rahul@acme.com"),
    duration_minutes: int = Query(30),
    search_date: Optional[datetime] = Query(None),
    user: CurrentTenantUser = Depends(require_permission("calendar.read")),
    db: AsyncSession = Depends(get_db),
):
    attendee_list = [a.strip() for a in attendees.split(",") if a.strip()]
    target_date = search_date or datetime.now(timezone.utc)
    return await CalendarService.find_available_slots(
        session=db,
        organization_id=user.organization_id,
        attendee_emails=attendee_list,
        duration_minutes=duration_minutes,
        search_date=target_date,
    )


@router.get("/events")
async def list_calendar_events(
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    project_id: Optional[UUID] = Query(None),
    status: Optional[str] = Query(None),
    user_email: Optional[str] = Query(None),
    user: CurrentTenantUser = Depends(require_permission("calendar.read")),
    db: AsyncSession = Depends(get_db),
):
    return await CalendarService.list_events(
        session=db,
        organization_id=user.organization_id,
        start_time=start_time,
        end_time=end_time,
        project_id=project_id,
        status_filter=status,
        user_email=user_email,
    )


@router.get("/events/{event_id}")
async def get_calendar_event(
    event_id: UUID = Path(...),
    user: CurrentTenantUser = Depends(require_permission("calendar.read")),
    db: AsyncSession = Depends(get_db),
):
    return await CalendarService.get_event_by_id(
        session=db,
        organization_id=user.organization_id,
        event_id=event_id,
    )


@router.post("/events", status_code=status.HTTP_201_CREATED)
async def create_calendar_event(
    req: CreateEventRequest,
    user: CurrentTenantUser = Depends(require_permission("calendar.write")),
    db: AsyncSession = Depends(get_db),
):
    res = await CalendarService.create_event(
        session=db,
        organization_id=user.organization_id,
        title=req.title,
        description=req.description or "",
        start_time=req.start_time,
        end_time=req.end_time,
        attendees=req.attendees,
        project_id=req.project_id,
        location=req.location,
        timezone_str=req.timezone,
        meeting_type=req.meeting_type,
        user_id=user.user_id,
        actor_type="user",
    )
    await db.commit()
    return res


@router.patch("/events/{event_id}")
async def update_calendar_event(
    req: UpdateEventRequest,
    event_id: UUID = Path(...),
    user: CurrentTenantUser = Depends(require_permission("calendar.write")),
    db: AsyncSession = Depends(get_db),
):
    updates = req.model_dump(exclude_unset=True)
    res = await CalendarService.update_event(
        session=db,
        organization_id=user.organization_id,
        event_id=event_id,
        updates=updates,
        user_id=user.user_id,
        actor_type="user",
    )
    await db.commit()
    return res


@router.delete("/events/{event_id}")
async def cancel_calendar_event(
    event_id: UUID = Path(...),
    req: Optional[CancelEventRequest] = None,
    user: CurrentTenantUser = Depends(require_permission("calendar.write")),
    db: AsyncSession = Depends(get_db),
):
    reason = req.reason if req else "Cancelled by user"
    res = await CalendarService.cancel_event(
        session=db,
        organization_id=user.organization_id,
        event_id=event_id,
        user_id=user.user_id,
        reason=reason,
        actor_type="user",
    )
    await db.commit()
    return res

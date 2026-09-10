import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional


WEEKDAYS = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}

MONTHS = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}

# Organization-specific attendee resolution is performed authoritatively by AttendeeResolver
NAME_TO_EMAIL: dict[str, str] = {}



def parse_meeting_intent(prompt: str, now: Optional[datetime] = None) -> dict[str, Any]:
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    lower = prompt.lower()

    # 1. Parse Duration
    duration_minutes = 30
    dur_hr_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:hour|hr|h)s?\b", lower)
    dur_min_match = re.search(r"(\d+)\s*(?:min|minute|m\b)s?", lower)
    if dur_hr_match:
        try:
            hrs = float(dur_hr_match.group(1))
            duration_minutes = int(hrs * 60)
        except ValueError:
            pass
    elif dur_min_match:
        try:
            duration_minutes = int(dur_min_match.group(1))
        except ValueError:
            pass
    elif "1 hour" in lower or "one hour" in lower or "1 hr" in lower:
        duration_minutes = 60
    elif "2 hours" in lower or "two hours" in lower or "2 hrs" in lower:
        duration_minutes = 120
    elif "45 min" in lower:
        duration_minutes = 45
    elif "15 min" in lower:
        duration_minutes = 15

    # 2. Parse Date
    target_date = now.date()
    has_explicit_date = False

    if "tomorrow" in lower or "tmrw" in lower:
        target_date = now.date() + timedelta(days=1)
        has_explicit_date = True
    elif "day after tomorrow" in lower:
        target_date = now.date() + timedelta(days=2)
        has_explicit_date = True
    elif "today" in lower or "tonight" in lower or "this morning" in lower or "this afternoon" in lower:
        target_date = now.date()
        has_explicit_date = True
    else:
        weekday_found = False
        for name, wd_num in WEEKDAYS.items():
            if re.search(rf"\b{name}\b", lower):
                current_wd = now.weekday()
                days_ahead = (wd_num - current_wd) % 7
                if days_ahead == 0 and ("next" in lower or now.hour >= 18):
                    days_ahead = 7
                elif "next" in lower and days_ahead < 7:
                    days_ahead += 7
                target_date = now.date() + timedelta(days=days_ahead)
                has_explicit_date = True
                weekday_found = True
                break

        if not weekday_found:
            # 1. Check YYYY-MM-DD or YYYY/MM/DD
            iso_match = re.search(r"\b(202\d)[/-](\d{1,2})[/-](\d{1,2})\b", lower)
            if iso_match:
                try:
                    y, m, d = int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3))
                    target_date = datetime(y, m, d).date()
                    has_explicit_date = True
                except ValueError:
                    pass

            # 2. Check DD/MM/YYYY or DD-MM-YYYY or DD.MM.YYYY
            if not has_explicit_date:
                dmy_match = re.search(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](202\d|\d{2})\b", lower)
                if dmy_match:
                    try:
                        p1 = int(dmy_match.group(1))
                        p2 = int(dmy_match.group(2))
                        y_val = int(dmy_match.group(3))
                        if y_val < 100:
                            y_val += 2000
                        if p1 > 12:
                            d, m = p1, p2
                        elif p2 > 12:
                            m, d = p1, p2
                        else:
                            # Standard international/UK/IN is DD/MM/YYYY
                            d, m = p1, p2
                        target_date = datetime(y_val, m, d).date()
                        has_explicit_date = True
                    except ValueError:
                        pass

            # 3. Check Month names with days and optional year
            if not has_explicit_date:
                for m_name, m_num in MONTHS.items():
                    m_pat1 = rf"\b{m_name}\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:\s*,?\s*(202\d))?\b"
                    m_pat2 = rf"\b(\d{{1,2}})(?:st|nd|rd|th)?(?:\s+of)?\s+{m_name}(?:\s*,?\s*(202\d))?\b"
                    m1 = re.search(m_pat1, lower)
                    m2 = re.search(m_pat2, lower)
                    if m1:
                        d_val = int(m1.group(1))
                        y_val = int(m1.group(2)) if m1.group(2) else now.year
                        target_date = datetime(y_val, m_num, d_val).date()
                        has_explicit_date = True
                        break
                    elif m2:
                        d_val = int(m2.group(1))
                        y_val = int(m2.group(2)) if m2.group(2) else now.year
                        target_date = datetime(y_val, m_num, d_val).date()
                        has_explicit_date = True
                        break

    # 3. Parse Time
    target_hour = 10
    target_minute = 0
    has_explicit_time = False

    slot_range_match = re.search(
        r"(\d{1,2})(?::(\d{2}))?(?::\d{2})?\s*(am|pm)\s*-\s*(\d{1,2})(?::(\d{2}))?(?::\d{2})?\s*(am|pm)",
        lower,
    )
    if slot_range_match:
        h1 = int(slot_range_match.group(1))
        m1 = int(slot_range_match.group(2) or 0)
        merid1 = slot_range_match.group(3)
        if merid1 == "pm" and h1 < 12:
            h1 += 12
        elif merid1 == "am" and h1 == 12:
            h1 = 0

        h2 = int(slot_range_match.group(4))
        m2 = int(slot_range_match.group(5) or 0)
        merid2 = slot_range_match.group(6)
        if merid2 == "pm" and h2 < 12:
            h2 += 12
        elif merid2 == "am" and h2 == 12:
            h2 = 0

        target_hour = h1
        target_minute = m1
        diff_mins = (h2 * 60 + m2) - (h1 * 60 + m1)
        if diff_mins > 0:
            duration_minutes = diff_mins
        has_explicit_time = True
    else:
        # Check AM/PM time, e.g. 10am, 10:30pm, 10:30:00 am
        time_match = re.search(r"\b(?:at\s+|for\s+)?(\d{1,2})(?::(\d{2}))?(?::\d{2})?\s*(am|pm)\b", lower)
        if time_match:
            h = int(time_match.group(1))
            m = int(time_match.group(2) or 0)
            merid = time_match.group(3)
            if merid == "pm" and h < 12:
                h += 12
            elif merid == "am" and h == 12:
                h = 0
            target_hour = h
            target_minute = m
            has_explicit_time = True
        else:
            # Check 24-hour military / HH:MM or HH:MM:SS format e.g. 12:30 or 12:30:00
            military_match = re.search(r"\b(?:at\s+|for\s+)?([01]?\d|2[0-3]):([0-5]\d)(?::[0-5]\d)?\b", lower)
            if military_match:
                target_hour = int(military_match.group(1))
                target_minute = int(military_match.group(2))
                has_explicit_time = True
            elif "noon" in lower or "midday" in lower:
                target_hour = 12
                target_minute = 0
                has_explicit_time = True
            else:
                bare_match = re.search(r"\bat\s+(\d{1,2})\b", lower)
                if bare_match:
                    h = int(bare_match.group(1))
                    if 1 <= h <= 6:
                        target_hour = h + 12
                    else:
                        target_hour = h
                    target_minute = 0
                    has_explicit_time = True

    if not has_explicit_time:
        if target_date == now.date():
            target_hour = max(10, min(now.hour + 1, 17))
        else:
            target_hour = 10
        target_minute = 0

    start_dt = datetime(
        year=target_date.year,
        month=target_date.month,
        day=target_date.day,
        hour=target_hour,
        minute=target_minute,
        tzinfo=timezone.utc,
    )
    end_dt = start_dt + timedelta(minutes=duration_minutes)

    # 4. Parse Attendees
    raw_attendees: list[str] = []
    found_emails = re.findall(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", prompt)
    for email in found_emails:
        if email.lower() not in [a.lower() for a in raw_attendees]:
            raw_attendees.append(email.lower())

    # Extract participant names following 'with', 'between', 'invite', or 'sync with'
    name_clause = re.search(
        r"\b(?:with|between|invite|sync with)\s+(.+?)(?=\s+(?:for\b|about\b|regarding\b|the title\b|title\b|titled\b|on\s+\d|at\s+\d|from\b|by\b|tomorrow|today|next|this|$|\.))",
        prompt,
        re.IGNORECASE,
    )
    if name_clause:
        matched_phrase = name_clause.group(1).strip()
        # Split on commas, "and", "&", or whitespace
        delimiters = r",|\band\b|&|\s+"
        tokens = [t.strip("\"' .,") for t in re.split(delimiters, matched_phrase) if t.strip("\"' .,")]
        stop_words = {"a", "an", "the", "one", "meeting", "sync", "team", "brief", "catchup", "call"}
        for t in tokens:
            if t.lower() not in stop_words and len(t) >= 2:
                if t.lower() not in [a.lower() for a in raw_attendees]:
                    raw_attendees.append(t)

    # Check for timezone
    tz_match = re.search(r"\b(utc|gmt|ist|est|edt|cst|cdt|pst|pdt)\b", lower)
    explicit_timezone = tz_match.group(1).upper() if tz_match else None

    # 5. Parse Title
    title = None

    # Check for "title of the meeting is <title>" or "title is <title>" or "titled <title>"
    title_explicit_match = re.search(
        r"\b(?:title\s+(?:of\s+(?:the\s+)?meeting\s+)?is|titled|named)\s+([a-zA-Z0-9\s/&_-]{2,40}?)(?=\s+(?:on\s+\d|at\s+\d|with\b|from\b|by\b|tomorrow|today|next|this|$|\.))",
        prompt,
        re.IGNORECASE,
    )
    if title_explicit_match:
        extracted = title_explicit_match.group(1).strip()
        extracted = re.sub(r"^(?:a|an|the)\s+", "", extracted, flags=re.IGNORECASE).strip()
        if len(extracted) >= 2:
            title = extracted.title()

    if not title:
        # Check for "for <topic>" or "about <topic>" or "regarding <topic>"
        topic_match = re.search(
            r"\b(?:for|about|regarding)\s+([a-zA-Z0-9\s/&_-]{3,40}?)(?=\s+(?:on\s+\d|at\s+\d|with\b|from\b|by\b|tomorrow|today|next|this|$|\.))",
            prompt,
            re.IGNORECASE,
        )
        if topic_match:
            extracted = topic_match.group(1).strip()
            extracted = re.sub(r"^(?:a|an|the)\s+", "", extracted, flags=re.IGNORECASE).strip()
            stop_words = {"tomorrow", "today", "yesterday", "next week", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
            if extracted.lower() not in stop_words and len(extracted) >= 3:
                title = extracted.title()

    if not title:
        if "requirement" in lower or "requirements" in lower:
            title = "Requirement Analysis"
        elif "architecture" in lower or "arch" in lower:
            title = "Architecture Review"
        elif "standup" in lower:
            title = "Daily Standup"
        elif "sync" in lower or "quick sync" in lower:
            title = "Project Sync"
        elif "planning" in lower or "sprint" in lower:
            title = "Sprint Planning"
        elif "incident" in lower or "postmortem" in lower or "post-mortem" in lower:
            title = "Incident Review"
        elif "demo" in lower:
            title = "Sprint Demo"
        elif "1:1" in lower or "one on one" in lower:
            title = "1-on-1 Catchup"
        elif any(k in lower for k in ["dev team", "development team", "engineering team"]):
            title = "Dev Team Sync"
        else:
            if raw_attendees:
                title = f"Meeting with {raw_attendees[0].capitalize()}"
            else:
                title = "Team Meeting"

    return {
        "title": title,
        "start_time": start_dt.isoformat(),
        "end_time": end_dt.isoformat(),
        "duration_minutes": duration_minutes,
        "attendees": raw_attendees,
        "raw_attendees": raw_attendees,
        "explicit_timezone": explicit_timezone,
        "has_explicit_time": has_explicit_time,
        "has_explicit_date": has_explicit_date,
    }

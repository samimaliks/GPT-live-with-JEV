"""Read and create events on the signed-in user's primary calendar."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from googleapiclient.discovery import build

from backend.app.config import TIMEZONE
from backend.app.google_oauth import credentials_for
from backend.app.meetings import EMAIL_RE, guest_addresses


def _iso(value: dict) -> tuple[str, str, bool]:
    start_raw = (value.get("start") or {}).get("dateTime") or ""
    end_raw = (value.get("end") or {}).get("dateTime") or ""
    if start_raw and end_raw:
        return start_raw, end_raw, False
    start_day = (value.get("start") or {}).get("date") or ""
    end_day = (value.get("end") or {}).get("date") or ""
    return start_day, end_day, True


def list_events(email: str, limit: int = 8) -> list[dict]:
    service = build("calendar", "v3", credentials=credentials_for(email))
    now = datetime.now(ZoneInfo(TIMEZONE)).isoformat()
    result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=now,
            maxResults=limit,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    events: list[dict] = []
    for item in result.get("items", []):
        start, end, all_day = _iso(item)
        guests = [person.get("email", "") for person in item.get("attendees") or [] if person.get("email")]
        events.append(
            {
                "id": item.get("id") or f"event-{len(events)}",
                "title": item.get("summary") or "(no title)",
                "start": start,
                "end": end,
                "allDay": all_day,
                "guests": guests,
            }
        )
    return events


def create_event(
    owner_email: str,
    title: str,
    start: datetime,
    end: datetime,
    guests: list[str] | None = None,
) -> tuple[str, str]:
    """Create an event on the signed-in calendar. Guests are added only when provided."""
    zone = ZoneInfo(TIMEZONE)
    title = " ".join(title.split())
    if not title or len(title) > 80:
        raise ValueError("The event needs a short title.")
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("The event time needs a timezone.")
    start = start.astimezone(zone)
    end = end.astimezone(zone)
    minutes = int((end - start).total_seconds() // 60)
    if minutes < 5 or minutes > 480:
        raise ValueError("The event length must be between 5 minutes and 8 hours.")
    if start <= datetime.now(zone):
        raise ValueError("The event time has already passed.")
    people = guest_addresses(" ".join(guests or []))
    if guests and len(people) != len({item.strip().lower() for item in guests if item.strip()}):
        raise ValueError("Each guest needs a normal email address.")
    for person in people:
        if not EMAIL_RE.fullmatch(person):
            raise ValueError("Each guest needs a normal email address.")
    if len(people) > 10:
        raise ValueError("Add up to 10 guest emails.")
    body: dict = {
        "summary": title,
        "description": "Added by your personal assistant.",
        "start": {"dateTime": start.isoformat(), "timeZone": TIMEZONE},
        "end": {"dateTime": end.isoformat(), "timeZone": TIMEZONE},
    }
    if people:
        body["attendees"] = [{"email": person} for person in people]
    service = build("calendar", "v3", credentials=credentials_for(owner_email))
    event = (
        service.events()
        .insert(
            calendarId="primary",
            sendUpdates="all" if people else "none",
            body=body,
        )
        .execute()
    )
    link = event.get("htmlLink")
    if not isinstance(link, str) or not link:
        raise RuntimeError("Google created the event but did not return a link.")
    clock = start.strftime("%I:%M %p").lstrip("0")
    return link, f"{start.strftime('%A %d %B')} at {clock}"

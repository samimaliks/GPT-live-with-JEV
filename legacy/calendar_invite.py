"""Old desktop Google login. The Vite app does not use this module."""

from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import json
import re
from datetime import datetime
from pathlib import Path as FilePath
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from backend.app.config import MEETING_TITLE, TIMEZONE
from backend.app.meetings import (
    EMAIL_RE,
    meeting_minutes,
    meeting_window,
    wants_calendar_invite,
    wants_existing_invites,
)

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
CREDENTIALS_PATH = FilePath("credentials.json")
TOKEN_PATH = FilePath("token.json")
REDIRECT_URI = "http://localhost:8085/"
NUMBER_WORDS = {
    "zero": "0",
    "oh": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
}
SKIP_WORDS = {"the", "email", "address", "is", "my", "yes", "please", "send", "me", "an", "that", "its"}


def spoken_email(text: str) -> str:
    written = EMAIL_RE.findall(text)
    if written:
        return written[-1].lower()
    cleaned = text.lower().replace("at the rate", " at ")
    cleaned = re.sub(r"\b([a-z0-9-]+)\s+dot\s+([a-z]{2,})\b", r"\1.\2", cleaned)
    found = list(re.finditer(r"\bat\s+([a-z0-9.-]+\.[a-z]{2,})", cleaned))
    if not found:
        return ""
    domain = found[-1].group(1)
    before = cleaned[: found[-1].start()]
    named = re.search(r"email(?: address)? is\s+(.+)$", before)
    chunk = named.group(1) if named else " ".join(re.findall(r"[a-z0-9]+", before)[-12:])
    chunk = re.split(r"\b(?:sorry|correction)\b", chunk)[-1]
    parts: list[str] = []
    for token in re.findall(r"[a-z0-9]+", chunk):
        if token in NUMBER_WORDS:
            parts.append(NUMBER_WORDS[token])
        elif token in SKIP_WORDS:
            continue
        else:
            parts.append(token)
    local = "".join(parts)
    if len(local) < 2:
        return ""
    return f"{local}@{domain}"


def credentials_ready() -> bool:
    return CREDENTIALS_PATH.is_file() or TOKEN_PATH.is_file()


def _credentials() -> Credentials:
    creds: Credentials | None = None
    if TOKEN_PATH.is_file():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not CREDENTIALS_PATH.is_file():
            raise FileNotFoundError(
                "credentials.json is missing. In Google Cloud, create an OAuth desktop client "
                "and save that JSON here as credentials.json."
            )
        client = json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))
        block = dict(client.get("installed") or client.get("web") or {})
        block["redirect_uris"] = [REDIRECT_URI]
        flow = InstalledAppFlow.from_client_config({"installed": block}, SCOPES)
        creds = flow.run_local_server(port=8085, open_browser=True)
    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    return creds


def _speak_when(start: dict[str, str]) -> str:
    raw = start.get("dateTime") or ""
    if not raw:
        return start.get("date") or "unscheduled"
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(ZoneInfo(TIMEZONE))
    hour = str(int(parsed.strftime("%I")))
    return parsed.strftime(f"%A %d %B at {hour}:%M %p")


def list_upcoming_invites(limit: int = 8) -> list[str]:
    """Upcoming events on the signed-in organizer calendar. Empty when there are none."""
    service = build("calendar", "v3", credentials=_credentials())
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
    lines: list[str] = []
    for event in result.get("items", []):
        title = event.get("summary") or "(no title)"
        when = _speak_when(event.get("start") or {})
        guests = [person.get("email", "") for person in event.get("attendees") or [] if person.get("email")]
        guest_text = ", ".join(guests) if guests else "no guests listed"
        lines.append(f"{title}, {when}, guests: {guest_text}")
    return lines


def create_invite(*, email: str, start: datetime, end: datetime, title: str, timezone: str) -> str:
    """Put the meeting on the signed-in calendar and email the guest. Returns the event link."""
    service = build("calendar", "v3", credentials=_credentials())
    event = (
        service.events()
        .insert(
            calendarId="primary",
            sendUpdates="all",
            body={
                "summary": title,
                "description": "Meeting booked by your personal assistant.",
                "start": {"dateTime": start.isoformat(), "timeZone": timezone},
                "end": {"dateTime": end.isoformat(), "timeZone": timezone},
                "attendees": [{"email": email}],
            },
        )
        .execute()
    )
    link = event.get("htmlLink")
    if not isinstance(link, str) or not link:
        raise RuntimeError("Google created the event but did not return a link.")
    return link

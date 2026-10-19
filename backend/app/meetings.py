"""When a caller is asking to list events or send an invite, and the default slot."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from backend.app.config import TIMEZONE

EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")


def wants_existing_invites(text: str) -> bool:
    """True when the user asks to read existing calendar events (not create a new one)."""
    low = text.lower()
    # Creating a new event is handled elsewhere.
    if re.search(r"\b(create|add|book)\b.{0,40}\b(event|meeting|appointment|invite)\b", low):
        return False
    if re.search(
        r"\b(what(?:'s| is| are)?)\b.{0,40}\b(on my (?:calendar|schedule)|my (?:events?|meetings?|appointments?|invites?))\b"
        r"|\b(what|which)\b.{0,40}\b(events?|meetings?|appointments?|invites?)\b"
        r"|\b(show|list|read|tell|get|fetch|pull|give)\b.{0,40}\b(me\s+)?(my\s+)?(all\s+)?(calendar|events?|meetings?|appointments?|invites?|schedule)\b"
        r"|\b(do i have|any|have i|got any)\b.{0,30}\b(events?|meetings?|appointments?|invites?)\b"
        r"|\b(upcoming|existing|already)\b.{0,20}\b(events?|meetings?|appointments?|invites?|calendar)\b"
        r"|\b(check|look at|open)\b.{0,20}\b(my\s+)?(calendar|schedule)\b"
        r"|\b(see|find|view)\b.{0,40}\b(my\s+)?(events?|meetings?|appointments?|invites?|calendar|schedule)\b"
        r"|\b(unable|can't|cannot|don't|dont)\b.{0,40}\b(see|find|view)\b.{0,40}\b(events?|meetings?|appointments?|calendar)\b"
        r"|\bmy (?:events?|meetings?|appointments?)\b.{0,20}\b(today|tomorrow|this week)?\b",
        low,
    ):
        return True
    # Noisy speech often still contains both an ask word and a calendar word.
    has_cal = re.search(
        r"\b(calendar|schedule|meetings?|events?|appointments?|invites?)\b",
        low,
    )
    has_ask = re.search(
        r"\b(what|what's|whats|which|when|show|list|see|check|get|tell|read|any|"
        r"unable|can't|cannot|where|do i have|have i)\b",
        low,
    )
    if has_cal and has_ask:
        return True
    if "invite" not in low and "calendar" not in low:
        return False
    return re.search(
        r"\b(existing|already|list|lists)\b|my account|what are|what's|what is|which invite|show me|read me|tell me|don't want to send|do not want to send",
        low,
    ) is not None


def wants_calendar_invite(text: str) -> bool:
    """True when the caller asks to send or book. A later send still counts after a list question."""
    low = text.lower()
    low = re.split(r"don'?t want to send|do not want to send", low)[-1]
    if "book" in low and "meeting" in low:
        return True
    return re.search(r"\b(send|schedule|set up|setup)\b", low) is not None and re.search(
        r"\b(invite|calendar|meeting)\b", low
    ) is not None


def wants_new_event(text: str) -> bool:
    """True when the user asks to put a new event on their own calendar."""
    low = text.lower()
    low = re.split(r"don'?t want to send|do not want to send", low)[-1]
    if re.search(r"\b(never mind|nevermind|cancel that|forget it)\b", low):
        return False
    listing = wants_existing_invites(low)
    noun = re.search(r"\b(event|meeting|appointment|calendar|invite)\b", low) is not None
    named = re.search(r"\b(create|add|book|schedule|set up|setup|send)\b", low) is not None and noun
    timed = re.search(r"\b(create|add|book|schedule|set up|setup)\b", low) is not None and re.search(
        r"\b(today|tomorrow|tonight|noon|midnight|monday|tuesday|wednesday|thursday|friday|saturday|sunday|am|pm)\b|\bat\s+\d",
        low,
    ) is not None
    creating = named or timed
    if listing and not creating:
        return False
    return creating


def wants_guests(text: str) -> bool:
    """True when the user asks to add people to the event being created."""
    low = text.lower()
    low = re.split(
        r"don'?t want to send|do not want to send|no guests?|without guests?|don'?t add guests?|do not add guests?",
        low,
    )[-1]
    if wants_existing_invites(low) and not re.search(r"\b(add|with|include)\b", low):
        return False
    return re.search(
        r"\b(?:add|with|include|invite)\b.{0,40}\b(?:guests?|attendees?|people)\b"
        r"|\bguests?\b"
        r"|\battendees?\b"
        r"|\bsend(?:\s+\w+){0,2}\s+invite\b"
        r"|\binvite\s+(?:someone|them|people|guests?)\b",
        low,
    ) is not None


def guest_addresses(text: str, limit: int = 10) -> list[str]:
    found: list[str] = []
    for match in EMAIL_RE.findall(text):
        email = match.strip().lower()
        if email not in found:
            found.append(email)
    return found[:limit]


def cancels_new_event(text: str) -> bool:
    return re.search(r"\b(never mind|nevermind|cancel that|forget it|don't create|do not create)\b", text.lower()) is not None


def wants_move_event(text: str) -> bool:
    """True when the user asks to move or reschedule an existing event."""
    low = text.lower()
    if re.search(r"\b(never mind|nevermind|cancel that|forget it)\b", low):
        return False
    if wants_new_event(low) and not re.search(r"\b(move|reschedule|postpone)\b", low):
        return False
    if re.search(r"\b(move|reschedule|postpone|push)\b", low) and re.search(
        r"\b(event|meeting|appointment|session|invite|it|that|this)\b",
        low,
    ):
        return True
    if re.search(r"\b(change|update)\b.{0,30}\b(time|day|date)\b", low) and re.search(
        r"\b(event|meeting|appointment|session|invite|it|that|this)\b",
        low,
    ):
        return True
    return False


def match_calendar_event(events: list[dict], text: str) -> dict | None:
    """Pick the calendar event the user named, by title words."""
    low = text.lower()
    best: dict | None = None
    best_score = 0.0
    for event in events:
        if event.get("allDay"):
            continue
        title = str(event.get("title") or "").lower()
        words = [word for word in re.findall(r"[a-z0-9]+", title) if len(word) > 2 and word not in _GENERIC_TITLE]
        if not words:
            continue
        hits = sum(1 for word in words if word in low)
        score = hits / len(words)
        if hits and score > best_score:
            best = event
            best_score = score
    if best is not None and best_score >= 0.34:
        return best
    timed = [event for event in events if not event.get("allDay")]
    if len(timed) == 1 and re.search(r"\b(it|that|this)\b.{0,20}\b(event|meeting|appointment|session)?\b", low):
        return timed[0]
    return None


def parse_move_event(text: str, now: datetime, events: list[dict]) -> tuple[dict | None, list[str]]:
    """Read which event to move, the new day, and optional new time. Keeps length if omitted."""
    zone = ZoneInfo(TIMEZONE)
    if now.tzinfo is None:
        now = now.replace(tzinfo=zone)
    else:
        now = now.astimezone(zone)
    missing: list[str] = []
    target = match_calendar_event(events, text)
    if target is None:
        missing.append("which event")
    day, day_phrase = _find_day(text, now)
    clock, time_phrase, ambiguous_time, ranged = _find_time(text)
    minutes, _length_phrase, bad_length = _find_minutes(text)
    if minutes is None and ranged is not None and 5 <= ranged <= 480:
        minutes = ranged
        bad_length = False
    if day is None:
        missing.append("day")
    if target is None or day is None:
        if ambiguous_time and clock is None:
            missing.append("morning or afternoon")
        return None, missing

    old_start = datetime.fromisoformat(str(target["start"]))
    if old_start.tzinfo is None:
        old_start = old_start.replace(tzinfo=zone)
    else:
        old_start = old_start.astimezone(zone)
    old_end = datetime.fromisoformat(str(target["end"]))
    if old_end.tzinfo is None:
        old_end = old_end.replace(tzinfo=zone)
    else:
        old_end = old_end.astimezone(zone)
    old_minutes = max(5, int((old_end - old_start).total_seconds() // 60))
    if minutes is None:
        minutes = old_minutes
    elif bad_length:
        return None, ["a length from 5 minutes to 8 hours"]
    if clock is None:
        hour, minute = old_start.hour, old_start.minute
    else:
        hour, minute = clock
    start = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if start <= now:
        if re.search(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", day_phrase, re.I):
            start = start + timedelta(days=7)
        else:
            return None, ["a later time"]
    end = start + timedelta(minutes=minutes)
    clock_label = start.strftime("%I:%M %p").lstrip("0")
    return {
        "id": target["id"],
        "title": target["title"],
        "start": start,
        "end": end,
        "minutes": minutes,
        "when": f"{start.strftime('%A %d %B')} at {clock_label}",
    }, []


def meeting_minutes(text: str) -> int:
    low = text.lower()
    if "20" in low or "twenty" in low:
        return 20
    return 15


def meeting_window(minutes: int) -> tuple[datetime, datetime, str]:
    zone = ZoneInfo(TIMEZONE)
    start = (datetime.now(zone) + timedelta(days=1)).replace(hour=15, minute=0, second=0, microsecond=0)
    end = start + timedelta(minutes=minutes)
    return start, end, start.strftime("%A %d %B at 3:00 PM")


_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_HOUR_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8}
_CLOCK_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}
_ORDINALS = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
    "eleventh": 11,
    "twelfth": 12,
    "thirteenth": 13,
    "fourteenth": 14,
    "fifteenth": 15,
    "sixteenth": 16,
    "seventeenth": 17,
    "eighteenth": 18,
    "nineteenth": 19,
    "twentieth": 20,
    "twenty-first": 21,
    "twenty first": 21,
    "twenty-second": 22,
    "twenty second": 22,
    "twenty-third": 23,
    "twenty third": 23,
    "twenty-fourth": 24,
    "twenty fourth": 24,
    "twenty-fifth": 25,
    "twenty fifth": 25,
    "twenty-sixth": 26,
    "twenty sixth": 26,
    "twenty-seventh": 27,
    "twenty seventh": 27,
    "twenty-eighth": 28,
    "twenty eighth": 28,
    "twenty-ninth": 29,
    "twenty ninth": 29,
    "thirtieth": 30,
    "thirty-first": 31,
    "thirty first": 31,
}
_MINUTE_WORDS = {
    "five": 5,
    "ten": 10,
    "fifteen": 15,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "forty-five": 45,
    "forty five": 45,
    "sixty": 60,
    "ninety": 90,
}
_GENERIC_TITLE = {"event", "meeting", "appointment", "calendar", "it", "one", "that"}


def _clock(hour: int, minute: int, suffix: str) -> tuple[int, int] | None:
    suffix = suffix.lower().replace(".", "")
    if suffix in {"am", "pm"}:
        if not 1 <= hour <= 12:
            return None
        if hour == 12:
            hour = 0
        if suffix == "pm":
            hour += 12
        return hour, minute
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return hour, minute
    return None


def _all_clocks(text: str) -> list[tuple[int, tuple[int, int], str]]:
    matches: list[tuple[int, tuple[int, int], str]] = []
    for named in re.finditer(r"\b(noon|midday|midnight)\b", text, re.I):
        word = named.group(1).lower()
        clock = (0, 0) if word == "midnight" else (12, 0)
        matches.append((named.start(), clock, named.group(0)))
    for spoken in re.finditer(r"\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)\b", text, re.I):
        clock = _clock(int(spoken.group(1)), int(spoken.group(2) or 0), spoken.group(3))
        if clock is not None:
            matches.append((spoken.start(), clock, spoken.group(0)))
    words = "|".join(sorted(_CLOCK_WORDS, key=len, reverse=True))
    for spoken in re.finditer(rf"\b(?:at\s+)?({words})\s*(a\.?m\.?|p\.?m\.?)\b", text, re.I):
        clock = _clock(_CLOCK_WORDS[spoken.group(1).lower()], 0, spoken.group(2))
        if clock is not None:
            matches.append((spoken.start(), clock, spoken.group(0)))
    if not re.search(r"\b(?:a\.?m\.?|p\.?m\.?)\b", text, re.I):
        for exact in re.finditer(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", text):
            clock = _clock(int(exact.group(1)), int(exact.group(2)), "")
            if clock is not None:
                matches.append((exact.start(), clock, exact.group(0)))
    matches.sort(key=lambda item: item[0])
    return matches


def _find_time(text: str) -> tuple[tuple[int, int] | None, str, bool, int | None]:
    """Return the start clock, its phrase, whether a bare hour was ambiguous, and a range length."""
    matches = _all_clocks(text)
    bare = re.search(r"\bat\s+(\d{1,2})(?!\s*:)(?!\s*a\.?m\.?)(?!\s*p\.?m\.?)\b", text, re.I)
    if not matches:
        return None, "", bare is not None, None
    _pos, clock, phrase = matches[0]
    span: int | None = None
    if len(matches) > 1:
        start_m = clock[0] * 60 + clock[1]
        end_m = matches[1][1][0] * 60 + matches[1][1][1]
        if end_m > start_m:
            span = end_m - start_m
    return clock, phrase, False, span


def _find_day(text: str, now: datetime) -> tuple[datetime | None, str]:
    low = text.lower()
    found: list[tuple[int, datetime, str]] = []
    today = re.search(r"\btoday\b", low)
    tomorrow = re.search(r"\btomorrow\b", low)
    if today:
        found.append((today.start(), now.replace(hour=0, minute=0, second=0, microsecond=0), today.group(0)))
    if tomorrow:
        start = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        found.append((tomorrow.start(), start, tomorrow.group(0)))
    for name, index in _WEEKDAYS.items():
        next_week = re.search(rf"\bnext\s+week(?:'s)?\s+{name}\b", low)
        if next_week:
            week_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now.weekday())
            found.append((next_week.start(), week_start + timedelta(days=7 + index), next_week.group(0)))
            continue
        match = re.search(rf"\b(next\s+)?{name}\b", low)
        if not match:
            continue
        days = (index - now.weekday()) % 7
        if match.group(1) and days == 0:
            days = 7
        found.append((match.start(), (now + timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0), match.group(0)))
    month_names = "|".join(_MONTHS)
    ordinals = "|".join(sorted(_ORDINALS, key=len, reverse=True))
    years = [int(year) for year in re.findall(r"\b(20\d{2})\b", low)]
    spoken_year = years[-1] if years else None

    def _dated(day: int, month: int, phrase: str, at: int) -> None:
        year = spoken_year or now.year
        try:
            candidate = now.replace(year=year, month=month, day=day, hour=0, minute=0, second=0, microsecond=0)
        except ValueError:
            return
        if spoken_year is None and candidate.date() < now.date():
            try:
                candidate = candidate.replace(year=year + 1)
            except ValueError:
                return
        found.append((at, candidate, phrase))

    for match in re.finditer(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({month_names})\b", low):
        _dated(int(match.group(1)), _MONTHS[match.group(2)], match.group(0), match.start())
    for match in re.finditer(rf"\b({ordinals})\s+(?:of\s+)?({month_names})\b", low):
        _dated(_ORDINALS[match.group(1)], _MONTHS[match.group(2)], match.group(0), match.start())
    for match in re.finditer(rf"\b({month_names})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", low):
        _dated(int(match.group(2)), _MONTHS[match.group(1)], match.group(0), match.start())
    for match in re.finditer(rf"\b({month_names})\s+({ordinals})\b", low):
        _dated(_ORDINALS[match.group(2)], _MONTHS[match.group(1)], match.group(0), match.start())
    if not found:
        return None, ""
    found.sort(key=lambda item: item[0])
    _start, day, phrase = found[-1]
    return day, phrase


def _find_minutes(text: str) -> tuple[int | None, str, bool]:
    low = text.lower()
    found: list[tuple[int, int, str]] = []
    half = re.search(r"\bhalf(?:\s+an)?\s+hour\b", low)
    if half:
        found.append((half.start(), 30, half.group(0)))
    one = re.search(r"\b(?:an|one)\s+hour\b", low)
    if one:
        found.append((one.start(), 60, one.group(0)))
    for word, hours in _HOUR_WORDS.items():
        if word == "one":
            continue
        match = re.search(rf"\b{word}\s+hours\b", low)
        if match:
            found.append((match.start(), hours * 60, match.group(0)))
    for match in re.finditer(r"\b(\d+)\s*(?:hours|hour|hrs|hr)\b", low):
        found.append((match.start(), int(match.group(1)) * 60, match.group(0)))
    for match in re.finditer(r"\b(\d+)\s*(?:minutes|minute|mins|min)\b", low):
        found.append((match.start(), int(match.group(1)), match.group(0)))
    for word, minutes in sorted(_MINUTE_WORDS.items(), key=lambda item: len(item[0]), reverse=True):
        match = re.search(rf"\b{re.escape(word)}\s*(?:minutes|minute|mins|min)\b", low)
        if match:
            found.append((match.start(), minutes, match.group(0)))
    if not found:
        return None, "", False
    found.sort(key=lambda item: item[0])
    _start, minutes, phrase = found[-1]
    if minutes < 5 or minutes > 480:
        return None, phrase, True
    return minutes, phrase, False


def _title_from(text: str, removals: list[str]) -> str:
    cleaned = text
    for phrase in removals:
        if phrase:
            cleaned = re.sub(re.escape(phrase), " ", cleaned, count=1, flags=re.I)
    cleaned = re.sub(
        r"^\s*(?:please\s+)?(?:create|add|book|schedule|set up|setup)\s+(?:an?\s+|the\s+)?(?:new\s+)?(?:event|meeting|appointment)?",
        " ",
        cleaned,
        count=1,
        flags=re.I,
    )
    cleaned = re.sub(r"\b(?:called|titled|named|on my calendar|to my calendar|for me)\b", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,-")
    words = [word for word in cleaned.split() if word.lower() not in {"a", "an", "the", "for", "at", "on", "to", "my", "please"}]
    title = " ".join(words).strip()
    if title.lower() in _GENERIC_TITLE or len(title) < 2 or len(title) > 80:
        return ""
    return title


def _explicit_title(text: str) -> str:
    match = re.search(
        r"\btitle(?:\s+of\s+the\s+event)?\s+is\s+([A-Za-z0-9][^,.]{1,80}?)(?=\s*(?:,|\.|for\b|at\b|on\b|and\b|from\b|$))",
        text,
        re.I,
    )
    if not match:
        return ""
    title = " ".join(match.group(1).split()).strip(" .,-")
    if title.lower() in _GENERIC_TITLE or len(title) < 2 or len(title) > 80:
        return ""
    return title


def parse_new_event(text: str, now: datetime) -> tuple[dict | None, list[str]]:
    """Read a title, day, start time, and length. Missing details stay missing."""
    zone = ZoneInfo(TIMEZONE)
    if now.tzinfo is None:
        now = now.replace(tzinfo=zone)
    else:
        now = now.astimezone(zone)
    markers = list(re.finditer(r"\b(schedule|create|book|set up|setup)\b", text, re.I))
    segment = text[markers[0].start():] if markers else text
    missing: list[str] = []
    clock, time_phrase, ambiguous_time, ranged = _find_time(segment)
    day, day_phrase = _find_day(segment, now)
    minutes, length_phrase, bad_length = _find_minutes(segment)
    if minutes is None and ranged is not None and 5 <= ranged <= 480:
        minutes = ranged
        bad_length = False
    title = _explicit_title(segment) or _title_from(segment, [time_phrase, day_phrase, length_phrase])
    if not title:
        missing.append("title")
    if day is None:
        missing.append("day")
    if clock is None:
        missing.append("time")
    if minutes is None:
        missing.append("length")
    if missing or day is None or clock is None or minutes is None:
        if ambiguous_time and "time" in missing:
            missing = ["morning or afternoon" if item == "time" else item for item in missing]
        if bad_length and "length" in missing:
            missing = ["a length from 5 minutes to 8 hours" if item == "length" else item for item in missing]
        return None, missing
    start = day.replace(hour=clock[0], minute=clock[1], second=0, microsecond=0)
    if start <= now:
        if re.search(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", day_phrase, re.I):
            start = start + timedelta(days=7)
        else:
            return None, ["a later time"]
    if start > now + timedelta(days=366):
        return None, ["a day within the next year"]
    end = start + timedelta(minutes=minutes)
    clock_label = start.strftime("%I:%M %p").lstrip("0")
    return {
        "title": title,
        "start": start,
        "end": end,
        "minutes": minutes,
        "when": f"{start.strftime('%A %d %B')} at {clock_label}",
    }, []
